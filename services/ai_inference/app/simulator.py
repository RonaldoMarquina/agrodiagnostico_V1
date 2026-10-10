"""Provisional deterministic simulator for technical inference verification.

CRITICAL ARCHITECTURAL CONSTRAINTS:
1. NO REAL ML MODEL: There is currently no trained machine learning vision model or
   weights deployed in this service (deferred to the ML and evaluation increment).
2. STRICT TEST ENVIRONMENT GUARD: This simulator is ONLY permitted to execute when
   APP_ENV="test" AND ENABLE_SIMULATED_INFERENCE="true". In normal Compose, development,
   or production environments, any execution fails closed immediately.
3. ZERO PUBLIC HTTP SELECTION: Scenarios cannot be selected via HTTP request bodies,
   headers, or client parameters. Scenarios are strictly driven by deterministic test fixtures.
4. ISOLATED ARTIFACTS: Outcomes produced are synthetic test fixtures adhering strictly
   to the DiagnosisAnalyzed v1 contract.
"""
from enum import Enum
import os
from typing import Any, Dict, Optional
import uuid


class SimulatorScenario(str, Enum):
    PREDICTION = "PREDICTION"
    ABSTENTION = "ABSTENTION"
    FAILURE = "FAILURE"


# In-memory fixture mapping for unit and integration testing
_FIXTURE_SCENARIOS: Dict[uuid.UUID, Dict[str, Any]] = {}
_DEFAULT_FIXTURE_SCENARIO: Optional[SimulatorScenario] = None


def is_simulation_permitted() -> bool:
    """Validate that simulation is explicitly permitted by environment configuration."""
    app_env = os.environ.get("APP_ENV", "").lower()
    enable_sim = os.environ.get("ENABLE_SIMULATED_INFERENCE", "").lower()
    return app_env == "test" and enable_sim == "true"


def ensure_simulation_permitted() -> None:
    """Enforce strict fail-closed guard against running simulated inference in non-test environments."""
    if not is_simulation_permitted():
        app_env = os.environ.get("APP_ENV", "unspecified")
        enable_sim = os.environ.get("ENABLE_SIMULATED_INFERENCE", "false")
        raise RuntimeError(
            f"Simulated inference is strictly prohibited: APP_ENV='{app_env}' (expected 'test') "
            f"and ENABLE_SIMULATED_INFERENCE='{enable_sim}' (expected 'true'). "
            "No real ML model exists yet; normal startup fails closed."
        )


def set_diagnosis_fixture(diagnosis_id: uuid.UUID, scenario_data: Dict[str, Any]) -> None:
    """Register an explicit deterministic fixture for a specific diagnosis ID."""
    _FIXTURE_SCENARIOS[diagnosis_id] = scenario_data


def set_default_fixture_scenario(scenario: SimulatorScenario) -> None:
    """Set the default scenario when no specific diagnosis fixture is registered."""
    global _DEFAULT_FIXTURE_SCENARIO
    _DEFAULT_FIXTURE_SCENARIO = scenario


def clear_fixture_scenarios() -> None:
    """Clear all registered fixtures."""
    global _DEFAULT_FIXTURE_SCENARIO
    _FIXTURE_SCENARIOS.clear()
    _DEFAULT_FIXTURE_SCENARIO = None


def generate_synthetic_prediction(
    crop_code: str = "POTATO",
    class_code: str = "POTATO_EARLY_BLIGHT",
    raw_score: float = 0.92,
) -> Dict[str, Any]:
    """Generate synthetic prediction fixture."""
    return {
        "outcome": "PREDICTION",
        "crop_code": crop_code,
        "class_code": class_code,
        "raw_score": raw_score,
        "model_id": "synth-model-v1",
        "model_version": "0.1.0-synth",
        "dataset_version": "ds-synth-2026.1",
        "inference_ms": 45,
        "reason_code": None,
    }


def generate_synthetic_abstention(
    reason_code: str = "LOW_CONFIDENCE",
    crop_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate synthetic abstention fixture with null metadata."""
    return {
        "outcome": "ABSTENTION",
        "crop_code": crop_code,
        "class_code": None,
        "raw_score": None,
        "model_id": None,
        "model_version": None,
        "dataset_version": None,
        "inference_ms": None,
        "reason_code": reason_code,
    }


def generate_synthetic_failure(
    reason_code: str = "INFERENCE_ERROR",
) -> Dict[str, Any]:
    """Generate synthetic technical failure fixture with null metadata."""
    return {
        "outcome": "FAILURE",
        "crop_code": None,
        "class_code": None,
        "raw_score": None,
        "model_id": None,
        "model_version": None,
        "dataset_version": None,
        "inference_ms": None,
        "reason_code": reason_code,
    }


def _extract_image_width(raw: bytes) -> Optional[int]:
    """Extract image width from JPEG/PNG bytes without requiring Pillow."""
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(raw)) as img:
            return img.width
    except Exception:
        pass

    if raw.startswith(b"\xFF\xD8"):
        import struct
        idx = 2
        while idx < len(raw) - 8:
            if raw[idx] != 0xFF:
                idx += 1
                continue
            marker = raw[idx + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                _, w = struct.unpack(">HH", raw[idx + 5:idx + 9])
                return w
            elif idx + 4 <= len(raw):
                length = struct.unpack(">H", raw[idx + 2:idx + 4])[0]
                idx += 2 + length
            else:
                break

    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        import struct
        return struct.unpack(">I", raw[16:20])[0]

    return None


def run_simulated_inference(diagnosis_id: uuid.UUID, image_bytes: bytes) -> Dict[str, Any]:
    """Execute simulated inference for a diagnosis image.
    
    Strictly verifies environment prerequisites, checks input bytes, and returns
    a deterministic technical result dictionary.
    """
    ensure_simulation_permitted()

    if not image_bytes or len(image_bytes) == 0:
        return generate_synthetic_failure(reason_code="IMAGE_UNAVAILABLE")

    # Check explicit per-diagnosis fixture first
    if diagnosis_id in _FIXTURE_SCENARIOS:
        return _FIXTURE_SCENARIOS[diagnosis_id]

    # Check default fixture scenario
    scenario = _DEFAULT_FIXTURE_SCENARIO
    if scenario is None:
        # Check synthetic fixture encoded in test image dimensions
        width = _extract_image_width(image_bytes)
        if width == 201:
            scenario = SimulatorScenario.ABSTENTION
        elif width == 202:
            scenario = SimulatorScenario.FAILURE
        elif width == 200:
            scenario = SimulatorScenario.PREDICTION

    if scenario is None:
        env_scenario = os.environ.get("SIMULATED_SCENARIO", "PREDICTION").upper()
        try:
            scenario = SimulatorScenario(env_scenario)
        except ValueError:
            scenario = SimulatorScenario.PREDICTION

    if scenario == SimulatorScenario.ABSTENTION:
        reason = os.environ.get("SIMULATED_ABSTENTION_REASON", "LOW_CONFIDENCE")
        return generate_synthetic_abstention(reason_code=reason)
    elif scenario == SimulatorScenario.FAILURE:
        reason = os.environ.get("SIMULATED_FAILURE_REASON", "INFERENCE_ERROR")
        return generate_synthetic_failure(reason_code=reason)
    else:
        crop = os.environ.get("SIMULATED_CROP", "POTATO")
        cls_code = os.environ.get("SIMULATED_CLASS", "POTATO_EARLY_BLIGHT")
        score = float(os.environ.get("SIMULATED_SCORE", "0.92"))
        return generate_synthetic_prediction(crop_code=crop, class_code=cls_code, raw_score=score)

