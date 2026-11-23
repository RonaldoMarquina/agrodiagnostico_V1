"""Adaptadores de inferencia técnica para el worker de AI Inference.

Proporciona:
- Interfaz común `InferenceAdapter`.
- `SimulatedInferenceAdapter`: simulador determinista con doble guardia (APP_ENV="test" y ENABLE_SIMULATED_INFERENCE="true").
- `RealModelInferenceAdapter`: ejecutor real de release bundle inmutable en CPU, con:
    - Validación rigurosa de bytes y dimensiones de imagen (BAD_IMAGE si no decodificable o fuera de [min_dim, max_dim]).
    - Cero versiones o duraciones sintéticas si la imagen es rechazada antes de ejecutar el modelo (nulabilidad conjunta de metadatos).
    - Detección de cultivo y abstención ante cultivos no soportados (UNSUPPORTED_CROP con crop_code=null).
    - Control técnico de confianza mínima (LOW_CONFIDENCE si raw_score < min_confidence_threshold).
    - Medición real de latencia en milisegundos (`inference_ms`).
"""
from abc import ABC, abstractmethod
import io
import math
import struct
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.model_loader import load_authorized_bundle
from app.simulator import run_simulated_inference

try:
    from PIL import Image
except ImportError:
    Image = None


def softmax(scores: List[float]) -> List[float]:
    max_s = max(scores)
    exps = [math.exp(s - max_s) for s in scores]
    sum_exps = sum(exps) or 1.0
    return [e / sum_exps for e in exps]


def extract_image_meta(image_bytes: bytes) -> Tuple[bool, Optional[str], Optional[int], Optional[int]]:
    """Extrae formato y dimensiones de bytes de imagen de forma segura.

    Returns:
        (is_valid, format, width, height)
    """
    if not image_bytes or len(image_bytes) < 8:
        return False, None, None, None

    if Image is not None:
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                img.verify()
            with Image.open(io.BytesIO(image_bytes)) as img:
                img.load()
                return True, (img.format or "JPEG").upper(), img.width, img.height
        except Exception:
            return False, None, None, None

    # Fallback sin Pillow: parsing de encabezados binarios
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(image_bytes) >= 24:
        w, h = struct.unpack(">II", image_bytes[16:24])
        return True, "PNG", w, h

    if image_bytes.startswith(b"\xFF\xD8"):
        idx = 2
        length_bytes = len(image_bytes)
        while idx < length_bytes - 8:
            if image_bytes[idx] != 0xFF:
                idx += 1
                continue
            marker = image_bytes[idx + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                if idx + 9 <= length_bytes:
                    h, w = struct.unpack(">HH", image_bytes[idx + 5:idx + 9])
                    return True, "JPEG", w, h
            if idx + 4 <= length_bytes:
                segment_len = struct.unpack(">H", image_bytes[idx + 2:idx + 4])[0]
                idx += 2 + segment_len
            else:
                break

    return False, None, None, None


class InferenceAdapter(ABC):
    """Interfaz base para adaptadores de inferencia."""

    @abstractmethod
    def run_inference(self, diagnosis_id: uuid.UUID, image_bytes: bytes) -> Dict[str, Any]:
        """Ejecuta inferencia y retorna diccionario compatible con DiagnosisAnalyzed v1."""
        pass


class SimulatedInferenceAdapter(InferenceAdapter):
    """Adaptador de simulación exclusivo de entorno de pruebas con doble guardia."""

    def run_inference(self, diagnosis_id: uuid.UUID, image_bytes: bytes) -> Dict[str, Any]:
        try:
            import app.worker as worker_mod
            if hasattr(worker_mod, "run_simulated_inference"):
                return worker_mod.run_simulated_inference(diagnosis_id=diagnosis_id, image_bytes=image_bytes)
        except ImportError:
            pass
        return run_simulated_inference(diagnosis_id=diagnosis_id, image_bytes=image_bytes)


class DemoUnavailableInferenceAdapter(InferenceAdapter):
    """Adaptador seguro para demostración cuando no hay modelo aprobado.

    No inspecciona la imagen, no carga pesos y nunca produce una predicción. La
    abstención usa un ``reason_code`` existente del contrato para que Diagnosis
    publique ``NO_CONCLUYENTE`` sin aparentar que existe inferencia real.
    """

    def run_inference(self, diagnosis_id: uuid.UUID, image_bytes: bytes) -> Dict[str, Any]:
        del diagnosis_id, image_bytes
        return {
            "outcome": "ABSTENTION",
            "crop_code": None,
            "class_code": None,
            "raw_score": None,
            "model_id": None,
            "model_version": None,
            "dataset_version": None,
            "inference_ms": None,
            "reason_code": "UNSUPPORTED_CLASS",
        }


class RealModelInferenceAdapter(InferenceAdapter):
    """Adaptador de inferencia real basado en bundle de modelo inmutable en CPU."""

    def __init__(self, bundle_data: Dict[str, Any], weights_data: Dict[str, Any]):
        self.bundle_data = bundle_data
        self.weights_data = weights_data
        self.model_id = bundle_data["model_id"]
        self.model_version = bundle_data["model_version"]
        self.dataset_version = bundle_data["dataset_version"]
        self.architecture = bundle_data["architecture"]
        self.class_map = bundle_data["class_map"]
        self.rejection = bundle_data.get("rejection_components", {})

        self.min_dim = int(self.rejection.get("min_dimension", 200))
        self.max_dim = int(self.rejection.get("max_dimension", 6000))
        self.min_confidence = float(self.rejection.get("min_confidence_threshold", 0.65))
        self.crop_threshold = float(self.rejection.get("crop_detection_threshold", 0.85))

        self.is_hierarchical = "weights_data" in weights_data or "crop_weights" in weights_data

    @classmethod
    def from_bundle_file(cls, bundle_path: Any, weights_dir: Optional[Any] = None) -> "RealModelInferenceAdapter":
        bundle_data, weights_data = load_authorized_bundle(bundle_path, weights_dir)
        return cls(bundle_data, weights_data)

    def _extract_features(self, image_bytes: bytes) -> List[float]:
        """Extrae vector determinista de 64 dimensiones para el clasificador CPU."""
        if Image is not None:
            try:
                with Image.open(io.BytesIO(image_bytes)) as img:
                    rgb = img.convert("RGB").resize((8, 8), Image.Resampling.BILINEAR)
                    pixels = list(rgb.getdata())
                    features = []
                    for r, g, b in pixels:
                        intensity = (r + g + b) / (3.0 * 255.0)
                        features.append(round(intensity, 6))
                    return features[:64]
            except Exception:
                pass

        # Extracción determinista a partir de los bytes (64 floats normalizados)
        features = [0.0] * 64
        total_len = len(image_bytes)
        chunk_size = max(1, total_len // 64)
        for i in range(64):
            start = i * chunk_size
            end = min(total_len, start + chunk_size)
            chunk = image_bytes[start:end]
            if chunk:
                avg_val = sum(chunk) / (len(chunk) * 255.0)
                features[i] = round(avg_val, 6)
        return features

    def _forward_joint(self, features: List[float]) -> Tuple[str, str, float]:
        """Ejecuta inferencia conjunta sobre 7 clases."""
        weights = self.weights_data.get("weights", [])
        bias = self.weights_data.get("bias", [0.0] * len(self.class_map))
        num_classes = len(self.class_map)

        logits = list(bias)
        feat_dim = len(features)
        for i, val in enumerate(features):
            if i < len(weights):
                w_row = weights[i]
                for c in range(min(num_classes, len(w_row))):
                    logits[c] += val * w_row[c]

        probs = softmax(logits)
        best_idx = int(max(range(len(probs)), key=lambda i: probs[i]))
        best_prob = probs[best_idx]

        class_info = self.class_map.get(str(best_idx), {"class_code": "POTATO_HEALTHY", "crop_code": "POTATO"})
        return class_info["crop_code"], class_info["class_code"], best_prob

    def _forward_hierarchical(self, features: List[float]) -> Tuple[Optional[str], Optional[str], float, bool]:
        """Ejecuta inferencia jerárquica: Detector de cultivo en etapa 1 + Clasificador de patología en etapa 2."""
        raw_model = self.weights_data.get("weights_data", self.weights_data)
        crop_w = raw_model.get("crop_weights", [])
        crop_b = raw_model.get("crop_bias", [0.0, 0.0, 0.0])

        # Etapa 1: Crop logits [POTATO, MAIZE, OOD]
        crop_logits = list(crop_b)
        for i, val in enumerate(features):
            if i < len(crop_w):
                row = crop_w[i]
                for c in range(min(3, len(row))):
                    crop_logits[c] += val * row[c]

        crop_probs = softmax(crop_logits)
        # Índice 0: POTATO, 1: MAIZE, 2: OOD
        if crop_probs[2] > 0.40 or max(crop_probs[0], crop_probs[1]) < self.crop_threshold:
            # Cultivo desconocido o fuera de dominio
            return None, None, crop_probs[2], True

        winner_crop = "POTATO" if crop_probs[0] >= crop_probs[1] else "MAIZE"

        # Etapa 2: Sub-clasificador de patología
        prefix = "potato" if winner_crop == "POTATO" else "maize"
        dis_w = raw_model.get(f"{prefix}_weights", [])
        dis_b = raw_model.get(f"{prefix}_bias", [0.0] * 4)

        dis_logits = list(dis_b)
        for i, val in enumerate(features):
            if i < len(dis_w):
                row = dis_w[i]
                for c in range(min(len(dis_b), len(row))):
                    dis_logits[c] += val * row[c]

        dis_probs = softmax(dis_logits)
        best_dis_idx = int(max(range(len(dis_probs)), key=lambda i: dis_probs[i]))
        best_dis_prob = dis_probs[best_dis_idx]

        # Mapear al código de clase correspondiente al cultivo
        sub_classes = [
            v["class_code"] for k, v in self.class_map.items() if v["crop_code"] == winner_crop
        ]
        class_code = sub_classes[min(best_dis_idx, len(sub_classes) - 1)]

        return winner_crop, class_code, best_dis_prob, False

    def run_inference(self, diagnosis_id: uuid.UUID, image_bytes: bytes) -> Dict[str, Any]:
        """Ejecuta la inferencia sobre los bytes provistos."""
        # Paso 1: Pre-validación de bytes y dimensiones de imagen
        is_valid, fmt, w, h = extract_image_meta(image_bytes)
        if not is_valid or w is None or h is None:
            # Rechazo previo a la ejecución: Metadatos deben ser nulos conforme a contrato
            return {
                "outcome": "ABSTENTION",
                "crop_code": None,
                "class_code": None,
                "raw_score": None,
                "model_id": None,
                "model_version": None,
                "dataset_version": None,
                "inference_ms": None,
                "reason_code": "BAD_IMAGE",
            }

        if w < self.min_dim or h < self.min_dim or w > self.max_dim or h > self.max_dim:
            return {
                "outcome": "ABSTENTION",
                "crop_code": None,
                "class_code": None,
                "raw_score": None,
                "model_id": None,
                "model_version": None,
                "dataset_version": None,
                "inference_ms": None,
                "reason_code": "BAD_IMAGE",
            }

        # Paso 2: Cómputo acotado en CPU con medición real de tiempo
        start_time = time.monotonic()
        features = self._extract_features(image_bytes)

        if self.is_hierarchical:
            crop, cls_code, score, is_ood = self._forward_hierarchical(features)
            elapsed_ms = max(1, int((time.monotonic() - start_time) * 1000))

            if is_ood or crop is None:
                # Abstención por cultivo ajeno
                return {
                    "outcome": "ABSTENTION",
                    "crop_code": None,
                    "class_code": None,
                    "raw_score": None,
                    "model_id": self.model_id,
                    "model_version": self.model_version,
                    "dataset_version": self.dataset_version,
                    "inference_ms": elapsed_ms,
                    "reason_code": "UNSUPPORTED_CROP",
                }
        else:
            crop, cls_code, score = self._forward_joint(features)
            elapsed_ms = max(1, int((time.monotonic() - start_time) * 1000))

        # Paso 3: Control técnico de umbral mínimo de confianza
        if score < self.min_confidence:
            return {
                "outcome": "ABSTENTION",
                "crop_code": crop,
                "class_code": None,
                "raw_score": None,
                "model_id": self.model_id,
                "model_version": self.model_version,
                "dataset_version": self.dataset_version,
                "inference_ms": elapsed_ms,
                "reason_code": "LOW_CONFIDENCE",
            }

        # Paso 4: Predicción técnica aprobada
        return {
            "outcome": "PREDICTION",
            "crop_code": crop,
            "class_code": cls_code,
            "raw_score": round(score, 4),
            "model_id": self.model_id,
            "model_version": self.model_version,
            "dataset_version": self.dataset_version,
            "inference_ms": elapsed_ms,
            "reason_code": None,
        }
