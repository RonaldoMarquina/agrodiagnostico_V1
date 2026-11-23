"""Preprocesado tensorial compartido por entrenamiento e inferencia CPU.

La transformación determinista conserva un único contrato de dimensiones,
orientación EXIF, RGB y normalización. La aumentación se permite solo en TRAIN.
"""

from dataclasses import dataclass
import io
import math
import os
import platform
import random
import statistics
import time
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
import torch
from torchvision.transforms.functional import pil_to_tensor


MAX_IMAGE_BYTES = 15 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "TIFF", "WEBP"}
ALLOWED_MODES = {"1", "L", "LA", "P", "RGB", "RGBA", "CMYK", "I;16"}
MULTIFRAME_PRIMARY_ONLY_FORMATS = {"MPO"}
MULTIFRAME_REJECTED_FORMATS = {"PNG", "TIFF", "WEBP"}


@dataclass(frozen=True)
class DecodeMetadata:
    """Metadatos observados antes de convertir una imagen a RGB."""

    format: str
    mode: str
    width: int
    height: int
    frames: int
    selected_frame: int

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "mode": self.mode,
            "width": self.width,
            "height": self.height,
            "frames": self.frames,
            "selected_frame": self.selected_frame,
        }


@dataclass(frozen=True)
class TensorSpec:
    width: int = 64
    height: int = 64
    min_dimension: int = 200
    max_dimension: int = 6000
    mean: tuple[float, float, float] = (0.485, 0.456, 0.406)
    std: tuple[float, float, float] = (0.229, 0.224, 0.225)

    def __post_init__(self) -> None:
        if type(self.width) is not int or type(self.height) is not int or not 32 <= self.width <= 1024 or not 32 <= self.height <= 1024:
            raise ValueError("Tamaño tensorial fuera de rango")
        if type(self.min_dimension) is not int or type(self.max_dimension) is not int or not 1 <= self.min_dimension <= self.max_dimension <= 10000:
            raise ValueError("Límites de imagen inválidos")
        if len(self.mean) != 3 or len(self.std) != 3:
            raise ValueError("Se requieren tres canales RGB")
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1 for value in self.mean) or any(not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 1 for value in self.std):
            raise ValueError("Normalización inválida")

    def to_dict(self) -> dict:
        return {
            "input_size": [self.width, self.height], "channels": 3, "color_space": "RGB",
            "mean": list(self.mean), "std": list(self.std),
            "min_dimension": self.min_dimension, "max_dimension": self.max_dimension,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "TensorSpec":
        if value.get("channels") != 3 or value.get("color_space") != "RGB":
            raise ValueError("Contrato de color incompatible")
        size = value["input_size"]
        if len(size) != 2:
            raise ValueError("input_size inválido")
        return cls(size[0], size[1], value["min_dimension"], value["max_dimension"],
                   tuple(value["mean"]), tuple(value["std"]))


def _alpha_to_rgb(image: Image.Image) -> Image.Image:
    has_alpha = image.mode in {"LA", "RGBA"} or (
        image.mode == "P" and "transparency" in image.info
    )
    if not has_alpha:
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, rgba).convert("RGB")


def decode_image_to_rgb(image_bytes: bytes, spec: TensorSpec) -> tuple[Image.Image, DecodeMetadata]:
    """Verifica el contenedor y devuelve el frame autorizado convertido a RGB."""
    if not isinstance(image_bytes, bytes) or not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Bytes de imagen ausentes o excesivos")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image_bytes)) as probe:
                fmt = probe.format
                mode = probe.mode
                width, height = probe.size
                frames = int(getattr(probe, "n_frames", 1))
                probe.verify()
            if fmt not in ALLOWED_FORMATS:
                raise ValueError("Formato de imagen no permitido")
            if mode not in ALLOWED_MODES:
                raise ValueError("Modo de imagen no permitido")
            if frames < 1:
                raise ValueError("Imagen sin frame decodificable")
            if fmt in MULTIFRAME_REJECTED_FORMATS and frames != 1:
                raise ValueError("Imagen animada o multipágina no permitida")
            if fmt not in MULTIFRAME_PRIMARY_ONLY_FORMATS and frames != 1:
                raise ValueError("Contenedor multiframe no permitido")
            if not (spec.min_dimension <= width <= spec.max_dimension and
                    spec.min_dimension <= height <= spec.max_dimension):
                raise ValueError("Dimensiones de imagen fuera de rango")
            with Image.open(io.BytesIO(image_bytes)) as image:
                if image.format != fmt or image.mode != mode or image.size != (width, height):
                    raise ValueError("Metadatos de imagen inconsistentes")
                image.seek(0)
                image.load()
                oriented = ImageOps.exif_transpose(image)
                rgb = _alpha_to_rgb(oriented)
                metadata = DecodeMetadata(
                    format=fmt,
                    mode=mode,
                    width=width,
                    height=height,
                    frames=frames,
                    selected_frame=0,
                )
                return rgb.copy(), metadata
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Imagen corrupta, excesiva o no decodificable") from exc


def image_to_tensor(image_bytes: bytes, spec: TensorSpec, *, split: str, augment: bool = False, seed: int | None = None) -> torch.Tensor:
    """Decodifica bytes reales y devuelve tensor float32 CHW en CPU."""
    if split not in {"TRAIN", "VAL", "TEST", "EXTERNAL", "INFERENCE"}:
        raise ValueError("Partición desconocida")
    if augment and split != "TRAIN":
        raise ValueError("Aumentación permitida solo en TRAIN")
    if augment and (type(seed) is not int or seed < 0):
        raise ValueError("Aumentación TRAIN requiere semilla reproducible")
    rgb, _ = decode_image_to_rgb(image_bytes, spec)
    if augment and random.Random(seed).random() < 0.5:
        rgb = ImageOps.mirror(rgb)
    resized = rgb.resize((spec.width, spec.height), Image.Resampling.BILINEAR)
    tensor = pil_to_tensor(resized).to(dtype=torch.float32).div_(255.0)
    mean = torch.tensor(spec.mean, dtype=torch.float32).view(3, 1, 1)
    std = torch.tensor(spec.std, dtype=torch.float32).view(3, 1, 1)
    result = (tensor - mean) / std
    if result.shape != (3, spec.height, spec.width) or not bool(torch.isfinite(result).all()):
        raise ValueError("Tensor inválido")
    return result.contiguous()


def measure_cpu_preprocessing(image_bytes: bytes, spec: TensorSpec, *, iterations: int = 5) -> dict:
    """Mide solo este preprocesado sobre un fixture; no usa presupuesto G0."""
    if type(iterations) is not int or not 1 <= iterations <= 100:
        raise ValueError("Número de mediciones inválido")
    measurements = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        image_to_tensor(image_bytes, spec, split="INFERENCE")
        measurements.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(measurements)
    return {
        "scope": "TENSOR_PREPROCESSING_FIXTURE_ONLY", "iterations": iterations,
        "median_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[math.ceil(.95 * iterations) - 1], 4),
        "machine": platform.machine(), "logical_cpus": os.cpu_count(),
        "torch_threads": torch.get_num_threads(),
    }
