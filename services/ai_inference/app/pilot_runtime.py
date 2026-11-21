"""CPU inference for the immutable, project-owner-approved potato pilot.

The historical JSON-weight adapter is a test fixture and is never used here.
"""

import math
import multiprocessing
from pathlib import Path
import time
from typing import Any
import uuid

from agro_ml.data.tensor_preprocessing import TensorSpec, image_to_tensor
from agro_ml.pilot_release import CLASSES, digest, load_pilot_bundle
import torch


class PilotModelInferenceAdapter:
    requires_identified_crop = True

    def __init__(self, model: torch.nn.Module, bundle: dict):
        self.model = model.cpu().eval()
        self.bundle = bundle
        self.spec = TensorSpec.from_dict({
            **bundle["preprocessing"],
            "min_dimension": bundle["rejection_components"]["min_dimension"],
            "max_dimension": bundle["rejection_components"]["max_dimension"],
        })

    @classmethod
    def from_bundle_file(cls, path: Path, expected_sha256: str,
                         approval_sha256: str | None = None) -> "PilotModelInferenceAdapter":
        if approval_sha256 is not None and digest(path.parent / "g2-approval.json") != approval_sha256:
            raise ValueError("Acta G2 no coincide con el SHA autorizado")
        model, bundle, _report = load_pilot_bundle(
            path, expected_sha256, require_approval_record=True,
        )
        return cls(model, bundle)

    @staticmethod
    def _abstain(reason: str, *, bundle: dict | None = None, inference_ms: int | None = None,
                 crop_code: str | None = None) -> dict[str, Any]:
        return {
            "outcome": "ABSTENTION", "crop_code": crop_code, "class_code": None,
            "raw_score": None, "reason_code": reason,
            "model_id": bundle["model_id"] if bundle else None,
            "model_version": bundle["model_version"] if bundle else None,
            "dataset_version": bundle["dataset_version"] if bundle else None,
            "inference_ms": inference_ms,
        }

    def run_inference(self, diagnosis_id: uuid.UUID, image_bytes: bytes,
                      *, identified_crop: str | None = None) -> dict[str, Any]:
        if identified_crop != "POTATO":
            return self._abstain("UNSUPPORTED_CROP")
        try:
            tensor = image_to_tensor(image_bytes, self.spec, split="INFERENCE").unsqueeze(0)
        except ValueError:
            return self._abstain("BAD_IMAGE")

        started = time.perf_counter_ns()
        with torch.inference_mode():
            probabilities = torch.softmax(self.model(tensor), dim=1)[0].tolist()
        inference_ms = max(0, round((time.perf_counter_ns() - started) / 1_000_000))
        if len(probabilities) != 3 or any(not math.isfinite(value) for value in probabilities):
            raise ValueError("Salida del modelo inválida")

        candidate = max(range(2), key=lambda index: probabilities[index])
        class_code = CLASSES[candidate]
        raw_score = probabilities[candidate]
        parameters = self.bundle["calibration"]["parameters_per_class"][class_code]
        bounded = min(max(raw_score, 1e-6), 1 - 1e-6)
        logit = math.log(bounded / (1 - bounded))
        z = parameters["slope"] * logit + parameters["intercept"]
        calibrated = 1 / (1 + math.exp(-max(-40, min(40, z))))
        if probabilities[2] >= raw_score:
            return self._abstain("UNSUPPORTED_CROP", bundle=self.bundle,
                                 inference_ms=inference_ms)
        if calibrated < self.bundle["rejection_components"]["min_confidence_threshold"]:
            return self._abstain("LOW_CONFIDENCE", bundle=self.bundle,
                                 inference_ms=inference_ms, crop_code="POTATO")
        return {
            "outcome": "PREDICTION", "crop_code": "POTATO", "class_code": class_code,
            "raw_score": raw_score, "reason_code": None,
            "model_id": self.bundle["model_id"],
            "model_version": self.bundle["model_version"],
            "dataset_version": self.bundle["dataset_version"],
            "inference_ms": inference_ms,
        }


def _inference_process(send, bundle_path: str, expected_sha256: str, approval_sha256: str,
                       diagnosis_id: uuid.UUID, image_bytes: bytes, identified_crop: str) -> None:
    """Fresh process validates the pinned bundle before any image computation."""
    try:
        adapter = PilotModelInferenceAdapter.from_bundle_file(
            Path(bundle_path), expected_sha256, approval_sha256)
        send.send(("ok", adapter.run_inference(
            diagnosis_id, image_bytes, identified_crop=identified_crop)))
    except Exception:
        send.send(("error", "Pilot inference process failed"))
    finally:
        send.close()


class BoundedPilotInferenceAdapter:
    """Terminate over-budget inference without blocking the worker's lease heartbeat."""

    requires_identified_crop = True

    def __init__(self, bundle_path: Path, expected_sha256: str,
                 approval_sha256: str, timeout_seconds: float = 20):
        if not math.isfinite(timeout_seconds) or not 1 <= timeout_seconds <= 25:
            raise ValueError("Pilot inference timeout must be within 1–25 seconds")
        # Fail closed at startup, before subscribing to queues. No request can
        # supply a path or checksum; the pinned approved release is checked again
        # in each isolated execution process.
        PilotModelInferenceAdapter.from_bundle_file(bundle_path, expected_sha256, approval_sha256)
        self.bundle_path = bundle_path
        self.expected_sha256 = expected_sha256
        self.approval_sha256 = approval_sha256
        self.timeout_seconds = timeout_seconds

    def run_inference(self, diagnosis_id: uuid.UUID, image_bytes: bytes,
                      *, identified_crop: str | None = None) -> dict[str, Any]:
        if identified_crop != "POTATO":
            return PilotModelInferenceAdapter._abstain("UNSUPPORTED_CROP")
        if not isinstance(image_bytes, bytes) or len(image_bytes) > 15 * 1024 * 1024:
            return PilotModelInferenceAdapter._abstain("BAD_IMAGE")
        context = multiprocessing.get_context("spawn")
        receive, send = context.Pipe(duplex=False)
        process = context.Process(
            target=_inference_process,
            args=(send, str(self.bundle_path), self.expected_sha256, self.approval_sha256,
                  diagnosis_id, image_bytes, identified_crop),
            daemon=True,
        )
        try:
            process.start()
            send.close()
            if not receive.poll(self.timeout_seconds):
                raise TimeoutError("Pilot inference exceeded its CPU wall-time budget")
            status, result = receive.recv()
            process.join(timeout=1)
            if status != "ok" or process.exitcode != 0:
                raise RuntimeError("Pilot inference process failed")
            return result
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
            receive.close()
            send.close()
