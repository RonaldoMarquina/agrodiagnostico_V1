"""Strict JSON Schema validation for DiagnosisFinished v1 events (ADR-0014)."""
import hashlib
import json
from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import unquote, urldefrag

from jsonschema import Draft202012Validator, FormatChecker


def _find_contracts_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        cand = parent / "contracts"
        if cand.is_dir() and (cand / "events").is_dir():
            return cand.resolve()
    for cand in (Path("/service/contracts"), Path("/contracts"), Path("contracts")):
        if cand.is_dir() and (cand / "events").is_dir():
            return cand.resolve()
    return Path("contracts").resolve()


CONTRACTS_ROOT = _find_contracts_root()
_VALIDATOR_FINISHED_V1: Optional[Draft202012Validator] = None


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_schema(node: Any, document: Path, boundary: Path) -> Any:
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


def get_finished_v1_validator() -> Draft202012Validator:
    global _VALIDATOR_FINISHED_V1
    if _VALIDATOR_FINISHED_V1 is None:
        schema_path = CONTRACTS_ROOT / "events" / "DiagnosisFinished.v1.schema.json"
        raw = _read_json(schema_path)
        resolved = _resolve_schema(raw, schema_path, CONTRACTS_ROOT)
        _VALIDATOR_FINISHED_V1 = Draft202012Validator(resolved, format_checker=FormatChecker())
    return _VALIDATOR_FINISHED_V1


def compute_canonical_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_diagnosis_finished_v1(data: Any) -> Tuple[bool, Optional[str]]:
    if not isinstance(data, dict):
        return False, "MALFORMED_MESSAGE"
    if data.get("event_type") != "DiagnosisFinished":
        return False, "UNSUPPORTED_EVENT_TYPE"
    if data.get("schema_version") != 1:
        return False, "UNSUPPORTED_SCHEMA_VERSION"
    validator = get_finished_v1_validator()
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        return False, "SCHEMA_VALIDATION_FAILED"
    return True, None
