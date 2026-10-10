"""Explicit synthetic acceptance policy; no production model is approved yet."""
import os


def prediction_rejection(payload: dict) -> str | None:
    # This threshold is a fixture assertion, not calibrated agronomic confidence.
    if (os.environ.get("APP_ENV") != "test"
            or os.environ.get("ENABLE_SIMULATED_INFERENCE") != "true"):
        return "UNSUPPORTED_CLASS"
    version = (payload.get("model_id"), payload.get("model_version"), payload.get("dataset_version"))
    if version != ("synth-model-v1", "0.1.0-synth", "ds-synth-2026.1"):
        return "UNSUPPORTED_CLASS"
    if payload.get("raw_score", 0) < 0.9:
        return "LOW_CONFIDENCE"
    return None
