"""Event validation for incoming DiagnosisAnalyzed v1 and outgoing DiagnosisFinished v1 messages.

Strict invariants:
- Analyzed v1 validated strictly against DiagnosisAnalyzed.v1.schema.json.
- Finished v1 validated strictly against DiagnosisFinished.v1.schema.json.
- Canonical payload hashing for inbox deduplication.
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import unquote, urldefrag

from jsonschema import Draft202012Validator, FormatChecker


def _find_contracts_root() -> Path:
    candidates = [
        Path("contracts"),
        Path("/service/contracts"),
        Path("/contracts"),
        Path("/checks/contracts"),
    ]
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        cand = parent / "contracts"
        if cand.is_dir() and (cand / "events").is_dir():
            return cand.resolve()
    for c in candidates:
        if c.is_dir() and (c / "events").is_dir():
            return c.resolve()
    return Path("contracts").resolve()


CONTRACTS_ROOT = _find_contracts_root()


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _resolve_schema(node: Any, document: Path, boundary: Path) -> Any:
    """Resolve JSON pointer references locally within the contracts boundary."""
    if isinstance(node, list):
        return [_resolve_schema(v, document, boundary) for v in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        uri, pointer = urldefrag(node["$ref"])
        target = (document.parent / uri).resolve() if uri else document.resolve()
        val = _read_json(target)
        if pointer:
            for segment in pointer.lstrip("/").split("/"):
                segment = unquote(segment).replace("~1", "/").replace("~0", "~")
                val = val[int(segment)] if isinstance(val, list) else val[segment]
        resolved = _resolve_schema(val, target, boundary)
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        if siblings:
            return {"allOf": [resolved, _resolve_schema(siblings, document, boundary)]}
        return resolved
    return {k: _resolve_schema(v, document, boundary) for k, v in node.items()}


_VALIDATOR_V1: Optional[Draft202012Validator] = None
_VALIDATOR_V2: Optional[Draft202012Validator] = None
_VALIDATOR_ANALYZED_V1: Optional[Draft202012Validator] = None
_VALIDATOR_FINISHED_V1: Optional[Draft202012Validator] = None


def get_v1_validator() -> Draft202012Validator:
    global _VALIDATOR_V1
    if _VALIDATOR_V1 is None:
        p = CONTRACTS_ROOT / "events" / "DiagnosisRequested.v1.schema.json"
        raw = _read_json(p)
        resolved = _resolve_schema(raw, p, CONTRACTS_ROOT)
        _VALIDATOR_V1 = Draft202012Validator(resolved, format_checker=FormatChecker())
    return _VALIDATOR_V1


def get_v2_validator() -> Draft202012Validator:
    global _VALIDATOR_V2
    if _VALIDATOR_V2 is None:
        p = CONTRACTS_ROOT / "events" / "DiagnosisRequested.v2.schema.json"
        raw = _read_json(p)
        resolved = _resolve_schema(raw, p, CONTRACTS_ROOT)
        _VALIDATOR_V2 = Draft202012Validator(resolved, format_checker=FormatChecker())
    return _VALIDATOR_V2


def get_analyzed_v1_validator() -> Draft202012Validator:
    global _VALIDATOR_ANALYZED_V1
    if _VALIDATOR_ANALYZED_V1 is None:
        p = CONTRACTS_ROOT / "events" / "DiagnosisAnalyzed.v1.schema.json"
        raw = _read_json(p)
        resolved = _resolve_schema(raw, p, CONTRACTS_ROOT)
        _VALIDATOR_ANALYZED_V1 = Draft202012Validator(resolved, format_checker=FormatChecker())
    return _VALIDATOR_ANALYZED_V1


def get_finished_v1_validator() -> Draft202012Validator:
    global _VALIDATOR_FINISHED_V1
    if _VALIDATOR_FINISHED_V1 is None:
        p = CONTRACTS_ROOT / "events" / "DiagnosisFinished.v1.schema.json"
        raw = _read_json(p)
        resolved = _resolve_schema(raw, p, CONTRACTS_ROOT)
        _VALIDATOR_FINISHED_V1 = Draft202012Validator(resolved, format_checker=FormatChecker())
    return _VALIDATOR_FINISHED_V1


def compute_canonical_hash(payload: Any) -> str:
    """Compute SHA-256 hash of canonically formatted JSON (sorted keys, no extra whitespace)."""
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def validate_diagnosis_analyzed_v1(data: Any) -> Tuple[bool, Optional[str]]:
    """Validate incoming message against DiagnosisAnalyzed v1 contract."""
    if not isinstance(data, dict):
        return False, "MALFORMED_MESSAGE: Payload is not a JSON object"
    if data.get("event_type") != "DiagnosisAnalyzed":
        return False, f"UNSUPPORTED_EVENT_TYPE: {data.get('event_type')}"
    if data.get("schema_version") != 1:
        return False, f"UNKNOWN_SCHEMA_VERSION: {data.get('schema_version')}"
    validator = get_analyzed_v1_validator()
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        first_err = errors[0]
        path_str = "/".join(map(str, first_err.path)) or "root"
        return False, f"SCHEMA_VALIDATION_FAILED: {path_str} {first_err.message}"
    return True, None


def validate_diagnosis_finished_v1(data: Any) -> Tuple[bool, Optional[str]]:
    """Validate outgoing message against DiagnosisFinished v1 contract."""
    if not isinstance(data, dict):
        return False, "MALFORMED_MESSAGE: Payload is not a JSON object"
    if data.get("event_type") != "DiagnosisFinished":
        return False, f"UNSUPPORTED_EVENT_TYPE: {data.get('event_type')}"
    if data.get("schema_version") != 1:
        return False, f"UNKNOWN_SCHEMA_VERSION: {data.get('schema_version')}"
    validator = get_finished_v1_validator()
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    if errors:
        first_err = errors[0]
        path_str = "/".join(map(str, first_err.path)) or "root"
        return False, f"SCHEMA_VALIDATION_FAILED: {path_str} {first_err.message}"
    return True, None


def validate_diagnosis_requested(data: Any) -> Tuple[bool, Optional[str], Optional[int]]:
    """Validate message against DiagnosisRequested v1 or v2 contract."""
    if not isinstance(data, dict):
        return False, "MALFORMED_MESSAGE: Payload is not a JSON object", None

    event_type = data.get("event_type")
    if event_type != "DiagnosisRequested":
        return False, f"UNSUPPORTED_EVENT_TYPE: {event_type}", None

    version = data.get("schema_version")
    if version == 1:
        validator = get_v1_validator()
        errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
        if errors:
            first_err = errors[0]
            path_str = "/".join(map(str, first_err.path)) or "root"
            return False, f"SCHEMA_VALIDATION_FAILED_V1: {path_str} {first_err.message}", 1
        return True, None, 1
    elif version == 2:
        validator = get_v2_validator()
        errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
        if errors:
            first_err = errors[0]
            path_str = "/".join(map(str, first_err.path)) or "root"
            return False, f"SCHEMA_VALIDATION_FAILED_V2: {path_str} {first_err.message}", 2
        return True, None, 2
    else:
        return False, f"UNKNOWN_SCHEMA_VERSION: {version}", version


