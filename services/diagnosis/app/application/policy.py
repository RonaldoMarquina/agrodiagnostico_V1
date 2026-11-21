"""Publication policy domain and application service for Diagnosis.

In accordance with ADR-0009 and Section 7 of increment 4:
- Invariant: Diagnosis is the sole publication authority.
- Policies are immutable and linked to exact model/dataset tuples and bundle digest.
- Activation and retirement atomically update Problem.model_supported in catalog.
- Mandatory operator context (actor, reason) and transactional audit logging.
- Prohibits public HTTP endpoints or PATCH for model_supported.
- Fails closed on missing governance, invalid calibration, or audit failure.
"""
from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.models import (
    Crop,
    DiagnosisAuditLog,
    Problem,
    PublicationPolicy,
)
from app.infrastructure.quarantine import record_audit_log
from app.infrastructure.publication_policy import lock_publication_policy
from app.infrastructure.pilot_policy_evidence import verify_pilot_policy_evidence

logger = logging.getLogger("diagnosis.policy")

SYSTEM_OPERATOR_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

VALID_CLASS_CODES = {
    "POTATO_HEALTHY": "POTATO",
    "POTATO_EARLY_BLIGHT": "POTATO",
    "POTATO_LATE_BLIGHT": "POTATO",
    "MAIZE_HEALTHY": "MAIZE",
    "MAIZE_COMMON_RUST": "MAIZE",
    "MAIZE_LEAF_BLIGHT": "MAIZE",
    "MAIZE_GRAY_LEAF_SPOT": "MAIZE",
}


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
        if cand.is_dir() and (cand / "ml").is_dir():
            return cand.resolve()
    for c in candidates:
        if c.is_dir() and (c / "ml").is_dir():
            return c.resolve()
    return Path("contracts").resolve()


CONTRACTS_ROOT = _find_contracts_root()


def load_publication_policy_schema() -> dict:
    schema_path = CONTRACTS_ROOT / "ml" / "publication-policy.v1.schema.json"
    if not schema_path.is_file():
        raise FileNotFoundError(f"Publication policy schema not found at {schema_path}")
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _is_finite_number(val: Any) -> bool:
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return False
    return not (math.isnan(val) or math.isinf(val))


def validate_publication_policy_payload(payload: dict) -> Tuple[bool, Optional[str]]:
    """Strictly validates a publication policy dictionary against contract and domain rules."""
    if not isinstance(payload, dict):
        return False, "Payload must be a JSON object"

    # 1. JSON Schema validation
    try:
        schema = load_publication_policy_schema()
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(payload))
        if errors:
            first_err = errors[0]
            path = ".".join(str(p) for p in first_err.path)
            return False, f"SCHEMA_VALIDATION_FAILED at '{path}': {first_err.message}"
    except Exception as ex:
        return False, f"SCHEMA_LOAD_OR_VALIDATION_ERROR: {str(ex)}"

    # 2. Domain & Governance validation
    governance = payload.get("governance", {})
    if not governance.get("g0_protocol_version") or not str(governance["g0_protocol_version"]).strip():
        return False, "EVIDENCE_MISSING: g0_protocol_version is mandatory and cannot be blank"
    if not governance.get("g2_approval_reference") or not str(governance["g2_approval_reference"]).strip():
        return False, "EVIDENCE_MISSING: g2_approval_reference is mandatory and cannot be blank"
    if not governance.get("approved_by") or not str(governance["approved_by"]).strip():
        return False, "EVIDENCE_MISSING: approved_by is mandatory and cannot be blank"
    if not governance.get("approved_at"):
        return False, "EVIDENCE_MISSING: approved_at date-time is mandatory"

    # 3. Approved classes validation
    approved_classes = payload.get("approved_classes", [])
    if not approved_classes:
        return False, "APPROVED_CLASSES_EMPTY: Policy must approve at least one class"

    seen_classes: Set[str] = set()
    for idx, item in enumerate(approved_classes):
        class_code = item.get("class_code")
        crop_code = item.get("crop_code")

        if class_code not in VALID_CLASS_CODES:
            return False, f"INVALID_CLASS_CODE at approved_classes[{idx}]: {class_code}"

        if VALID_CLASS_CODES[class_code] != crop_code:
            return (
                False,
                f"CROP_CLASS_MISMATCH at approved_classes[{idx}]: {class_code} belongs to {VALID_CLASS_CODES[class_code]}, not {crop_code}",
            )

        if class_code in seen_classes:
            return False, f"DUPLICATE_APPROVED_CLASS: {class_code} appears multiple times"
        seen_classes.add(class_code)

        min_conf = item.get("min_confidence_threshold")
        if not _is_finite_number(min_conf) or min_conf < 0.0 or min_conf > 1.0:
            return False, f"INVALID_THRESHOLD at approved_classes[{idx}]: min_confidence_threshold must be a finite float in [0.0, 1.0]"

        cal_params = item.get("calibration_params", {})
        slope = cal_params.get("slope")
        intercept = cal_params.get("intercept")
        if not _is_finite_number(slope) or not _is_finite_number(intercept):
            return False, f"NON_FINITE_CALIBRATION_PARAMS at approved_classes[{idx}]: slope and intercept must be finite floats"

    return True, None


def import_publication_policy(
    db: Session,
    actor: str,
    reason: str,
    policy_data: dict,
    apply: bool = False,
    release_bundle_path: Optional[Path] = None,
    g2_approval_path: Optional[Path] = None,
) -> dict:
    """Imports an immutable publication policy into the database.

    Dry-run by default unless apply=True.
    """
    if not actor or not actor.strip():
        raise ValueError("Operator context required: --actor cannot be blank.")
    if not reason or not reason.strip():
        raise ValueError("Operator context required: --reason cannot be blank.")

    is_valid, err = validate_publication_policy_payload(policy_data)
    if not is_valid:
        raise ValueError(f"POLICY_VALIDATION_ERROR: {err}")

    evidence = None
    if policy_data["governance"]["g0_protocol_version"] == "1.2.0":
        if release_bundle_path is None or g2_approval_path is None:
            raise ValueError("EVIDENCE_MISSING: bundle y acta G2 obligatorios para el piloto")
        evidence = verify_pilot_policy_evidence(
            policy_data, release_bundle_path, g2_approval_path)

    policy_id = uuid.UUID(policy_data["policy_id"])
    target_model = policy_data["target_model"]

    # Check for duplicate policy_id
    existing = db.execute(
        select(PublicationPolicy).where(PublicationPolicy.id == policy_id)
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"POLICY_ALREADY_EXISTS: Policy ID {policy_id} is already registered.")

    now = datetime.now(timezone.utc)
    policy_entry = PublicationPolicy(
        id=policy_id,
        policy_version=policy_data["policy_version"],
        model_id=target_model["model_id"],
        model_version=target_model["model_version"],
        dataset_version=target_model["dataset_version"],
        bundle_digest=target_model["bundle_digest"],
        payload=policy_data,
        active=False,
        created_at=now,
    )

    result = {
        "action": "IMPORT",
        "mode": "APPLIED" if apply else "DRY_RUN",
        "policy_id": str(policy_id),
        "policy_version": policy_entry.policy_version,
        "target_model": target_model,
        "approved_classes_count": len(policy_data["approved_classes"]),
        "governance": policy_data["governance"],
        "verified_evidence": evidence,
    }

    if apply:
        db.add(policy_entry)
        record_audit_log(
            session=db,
            actor_id=SYSTEM_OPERATOR_ACTOR_ID,
            action="POLICY_IMPORTED",
            target_type="publication_policy",
            correlation_id=uuid.uuid4(),
            target_id=str(policy_id),
            details={
                "actor": actor,
                "reason": reason,
                "policy_version": policy_entry.policy_version,
                "model_id": policy_entry.model_id,
                "model_version": policy_entry.model_version,
                "dataset_version": policy_entry.dataset_version,
                "bundle_digest": policy_entry.bundle_digest,
                "g2_evidence": evidence,
            },
        )
        db.commit()
    else:
        db.rollback()

    return result


def activate_publication_policy(
    db: Session,
    actor: str,
    reason: str,
    policy_id: uuid.UUID,
    apply: bool = False,
) -> dict:
    """Activates a publication policy and atomically updates Problem.model_supported.

    Dry-run by default unless apply=True.
    """
    if not actor or not actor.strip():
        raise ValueError("Operator context required: --actor cannot be blank.")
    if not reason or not reason.strip():
        raise ValueError("Operator context required: --reason cannot be blank.")

    if apply:
        lock_publication_policy(db, exclusive=True)
    # Find the target policy
    stmt = select(PublicationPolicy).where(PublicationPolicy.id == policy_id)
    if apply and db.bind and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    policy = db.execute(stmt).scalar_one_or_none()

    if policy is None:
        raise ValueError(f"POLICY_NOT_FOUND: Policy ID {policy_id} does not exist.")

    approved_classes: Set[str] = {
        ac["class_code"] for ac in policy.payload.get("approved_classes", [])
    }

    now = datetime.now(timezone.utc)
    result = {
        "action": "ACTIVATE",
        "mode": "APPLIED" if apply else "DRY_RUN",
        "policy_id": str(policy_id),
        "policy_version": policy.policy_version,
        "approved_classes": sorted(list(approved_classes)),
        "previously_active": policy.active,
    }

    if apply:
        problems = db.execute(select(Problem)).scalars().all()
        missing = approved_classes - {problem.code for problem in problems}
        if missing:
            raise ValueError("CATALOG_CLASS_MISSING: " + ", ".join(sorted(missing)))
        # Deactivate all other policies
        active_policies = db.execute(
            select(PublicationPolicy).where(
                PublicationPolicy.active.is_(True),
                PublicationPolicy.id != policy_id,
            )
        ).scalars().all()
        for ap in active_policies:
            ap.active = False
            ap.retired_at = now
        # Release the partial unique index slot before assigning the new active
        # row; ORM flush order is otherwise not guaranteed.
        db.flush()

        policy.active = True
        policy.activated_at = now
        policy.retired_at = None

        # Atomically update catalog problem support
        supported_problems = []
        for prob in problems:
            prob.model_supported = prob.code in approved_classes
            if prob.model_supported:
                supported_problems.append(prob.code)

        record_audit_log(
            session=db,
            actor_id=SYSTEM_OPERATOR_ACTOR_ID,
            action="POLICY_ACTIVATED",
            target_type="publication_policy",
            correlation_id=uuid.uuid4(),
            target_id=str(policy_id),
            details={
                "actor": actor,
                "reason": reason,
                "policy_version": policy.policy_version,
                "approved_classes": sorted(list(approved_classes)),
                "supported_problems": supported_problems,
            },
        )
        db.commit()
        result["supported_problems"] = supported_problems
    else:
        db.rollback()

    return result


def retire_publication_policy(
    db: Session,
    actor: str,
    reason: str,
    policy_id: Optional[uuid.UUID] = None,
    apply: bool = False,
) -> dict:
    """Retires a publication policy (or current active policy) and resets catalog support.

    Dry-run by default unless apply=True.
    """
    if not actor or not actor.strip():
        raise ValueError("Operator context required: --actor cannot be blank.")
    if not reason or not reason.strip():
        raise ValueError("Operator context required: --reason cannot be blank.")

    if apply:
        lock_publication_policy(db, exclusive=True)
    stmt = select(PublicationPolicy)
    if policy_id is not None:
        stmt = stmt.where(PublicationPolicy.id == policy_id)
    else:
        stmt = stmt.where(PublicationPolicy.active.is_(True))

    if apply and db.bind and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()

    policy = db.execute(stmt).scalar_one_or_none()
    if policy is None:
        raise ValueError("NO_POLICY_TO_RETIRE: No matching or active policy found to retire.")

    now = datetime.now(timezone.utc)
    result = {
        "action": "RETIRE",
        "mode": "APPLIED" if apply else "DRY_RUN",
        "policy_id": str(policy.id),
        "policy_version": policy.policy_version,
        "was_active": policy.active,
    }

    if apply:
        policy.active = False
        policy.retired_at = now

        # An inactive historical policy has no authority over current support.
        if result["was_active"]:
            problems = db.execute(select(Problem)).scalars().all()
            for prob in problems:
                prob.model_supported = False

        record_audit_log(
            session=db,
            actor_id=SYSTEM_OPERATOR_ACTOR_ID,
            action="POLICY_RETIRED",
            target_type="publication_policy",
            correlation_id=uuid.uuid4(),
            target_id=str(policy.id),
            details={
                "actor": actor,
                "reason": reason,
                "policy_version": policy.policy_version,
            },
        )
        db.commit()
    else:
        db.rollback()

    return result


def get_publication_policy_status(db: Session) -> dict:
    """Returns current active policy and catalog problem support status (read-only)."""
    active_policy = db.execute(
        select(PublicationPolicy).where(PublicationPolicy.active.is_(True))
    ).scalar_one_or_none()

    problems = db.execute(select(Problem).order_by(Problem.code)).scalars().all()
    supported_problems = [p.code for p in problems if p.model_supported]
    unsupported_problems = [p.code for p in problems if not p.model_supported]

    status: Dict[str, Any] = {
        "active_policy": None,
        "catalog_summary": {
            "supported_problems": supported_problems,
            "unsupported_problems": unsupported_problems,
            "total_supported": len(supported_problems),
            "total_problems": len(problems),
        },
    }

    if active_policy is not None:
        status["active_policy"] = {
            "id": str(active_policy.id),
            "version": active_policy.policy_version,
            "model_id": active_policy.model_id,
            "model_version": active_policy.model_version,
            "dataset_version": active_policy.dataset_version,
            "bundle_digest": active_policy.bundle_digest,
            "activated_at": active_policy.activated_at.isoformat() if active_policy.activated_at else None,
            "approved_classes": [
                {
                    "class_code": ac["class_code"],
                    "crop_code": ac["crop_code"],
                    "min_confidence_threshold": ac["min_confidence_threshold"],
                }
                for ac in active_policy.payload.get("approved_classes", [])
            ],
        }

    return status
