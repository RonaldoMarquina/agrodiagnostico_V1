"""Publication policy decision engine for Diagnosis service.

In accordance with ADR-0008, ADR-0009, and Section 7 of increment 4:
- Invariant: Diagnosis is the sole arbiter of publication and catalog recommendations.
- Publication policies are immutable, linking exact model/dataset tuples and bundle digest.
- Evaluates active PublicationPolicy with row-level serialization against concurrent retire/activate.
- Precedence of reason codes:
    1. UNSUPPORTED_CROP (checked prior in consumer)
    2. UNSUPPORTED_CLASS (version mismatch, unapproved class, problem not supported)
    3. LOW_CONFIDENCE (calibrated confidence below inclusive threshold)
    4. CATALOG_UNAVAILABLE (missing active reviewed recommendation)
- Inclusive frontier check: calibrated_confidence >= min_confidence_threshold is accepted.
- Fails closed on missing policy, retired policy, or missing review metadata.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import os
from typing import Any, Dict, Optional, Tuple
import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.models import (
    Problem,
    PublicationPolicy,
    Recommendation,
)


@dataclass
class PublicationDecision:
    accepted: bool
    reason_code: Optional[str]
    calibrated_confidence: Optional[float] = None
    policy_id: Optional[uuid.UUID] = None
    policy_version: Optional[str] = None
    policy_digest: Optional[str] = None
    recommendation: Optional[Recommendation] = None


def _is_finite_number(val: Any) -> bool:
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return False
    return not (math.isnan(val) or math.isinf(val))


def sigmoid(z: float) -> float:
    if not _is_finite_number(z):
        raise ValueError(f"Non-finite value in sigmoid: {z}")
    if z >= 40.0:
        return 1.0
    if z <= -40.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


# A single transaction-scoped lock serializes finalization with policy switches.
# Shared decisions may coexist; activation/retirement take the exclusive form.
POLICY_LOCK_KEY = 74127412001


def lock_publication_policy(session: Session, *, exclusive: bool) -> None:
    if session.bind and session.bind.dialect.name == "postgresql":
        function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
        session.execute(text(f"SELECT {function}(:key)"), {"key": POLICY_LOCK_KEY})


def evaluate_publication(session: Session, payload: dict) -> PublicationDecision:
    """Evaluates whether an incoming DiagnosisAnalyzed PREDICTION can be published as COMPLETADO."""
    model_id = payload.get("model_id")
    model_version = payload.get("model_version")
    dataset_version = payload.get("dataset_version")
    class_code = payload.get("class_code")
    crop_code = payload.get("crop_code")
    raw_score = payload.get("raw_score")

    # Serialize the whole decision with activation/retirement, including the
    # no-active-policy case where row locks alone cannot protect an empty set.
    lock_publication_policy(session, exclusive=False)
    # 1. Fetch active PublicationPolicy with row lock for share
    policy_stmt = select(PublicationPolicy).where(PublicationPolicy.active.is_(True))
    if session.bind and session.bind.dialect.name == "postgresql":
        policy_stmt = policy_stmt.with_for_update(read=True)

    active_policy = session.execute(policy_stmt).scalar_one_or_none()

    # 2. Handle active policy evaluation
    if active_policy is not None:
        # A. Exact tuple check
        if (
            active_policy.model_id != model_id
            or active_policy.model_version != model_version
            or active_policy.dataset_version != dataset_version
        ):
            return PublicationDecision(accepted=False, reason_code="UNSUPPORTED_CLASS")

        # B. Check class in approved_classes
        approved_classes = active_policy.payload.get("approved_classes", [])
        class_config = None
        for ac in approved_classes:
            if ac.get("class_code") == class_code and ac.get("crop_code") == crop_code:
                class_config = ac
                break

        if class_config is None:
            return PublicationDecision(accepted=False, reason_code="UNSUPPORTED_CLASS")

        # C. Check catalog Problem support in database
        problem = session.execute(
            select(Problem).where(
                Problem.code == class_code,
                Problem.crop_code == crop_code,
                Problem.active.is_(True),
            )
        ).scalar_one_or_none()

        if problem is None or not problem.model_supported:
            return PublicationDecision(accepted=False, reason_code="UNSUPPORTED_CLASS")

        # D. Calibration computation
        if not _is_finite_number(raw_score):
            return PublicationDecision(accepted=False, reason_code="LOW_CONFIDENCE")

        cal_params = class_config.get("calibration_params", {})
        slope = cal_params.get("slope")
        intercept = cal_params.get("intercept")
        if not _is_finite_number(slope) or not _is_finite_number(intercept):
            return PublicationDecision(accepted=False, reason_code="LOW_CONFIDENCE")

        if active_policy.payload.get("governance", {}).get("g0_protocol_version") == "1.2.0":
            bounded = min(max(float(raw_score), 1e-6), 1 - 1e-6)
            z = slope * math.log(bounded / (1 - bounded)) + intercept
        else:
            # Historical fixture policies retain their original scalar rule.
            z = slope * float(raw_score) + intercept
        calibrated_conf = round(sigmoid(z), 4)

        # E. Inclusive frontier threshold comparison: calibrated_confidence >= threshold is accepted
        min_threshold = class_config.get("min_confidence_threshold", 0.0)
        if calibrated_conf < min_threshold:
            return PublicationDecision(
                accepted=False,
                reason_code="LOW_CONFIDENCE",
                calibrated_confidence=calibrated_conf,
                policy_id=active_policy.id,
                policy_version=active_policy.policy_version,
                policy_digest=active_policy.bundle_digest,
            )

        # F. Catalog recommendation check
        rec = session.execute(
            select(Recommendation)
            .where(
                Recommendation.problem_code == class_code,
                Recommendation.active.is_(True),
            )
            .order_by(Recommendation.version.desc())
        ).scalars().first()

        if rec is None:
            return PublicationDecision(
                accepted=False,
                reason_code="CATALOG_UNAVAILABLE",
                calibrated_confidence=calibrated_conf,
                policy_id=active_policy.id,
                policy_version=active_policy.policy_version,
                policy_digest=active_policy.bundle_digest,
            )

        # Check reviewed catalog requirements
        cat_reqs = active_policy.payload.get("catalog_requirements", {})
        if cat_reqs.get("require_reviewed_catalog", True):
            if not rec.review_reference or not rec.reviewed_by or not rec.reviewed_at:
                return PublicationDecision(
                    accepted=False,
                    reason_code="CATALOG_UNAVAILABLE",
                    calibrated_confidence=calibrated_conf,
                    policy_id=active_policy.id,
                    policy_version=active_policy.policy_version,
                    policy_digest=active_policy.bundle_digest,
                )

        # All criteria satisfied!
        return PublicationDecision(
            accepted=True,
            reason_code=None,
            calibrated_confidence=calibrated_conf,
            policy_id=active_policy.id,
            policy_version=active_policy.policy_version,
            policy_digest=active_policy.bundle_digest,
            recommendation=rec,
        )

    # 3. Fallback when NO active policy is in DB
    # Backward compatibility for simulated test fixtures (Incremento 3 legacy test suite)
    if os.environ.get("APP_ENV") == "test" and os.environ.get("ENABLE_SIMULATED_INFERENCE") == "true":
        version = (model_id, model_version, dataset_version)
        if version != ("synth-model-v1", "0.1.0-synth", "ds-synth-2026.1"):
            return PublicationDecision(accepted=False, reason_code="UNSUPPORTED_CLASS")

        problem = session.execute(
            select(Problem).where(
                Problem.code == class_code,
                Problem.crop_code == crop_code,
                Problem.active.is_(True),
            )
        ).scalar_one_or_none()
        if problem is None or not problem.model_supported:
            return PublicationDecision(accepted=False, reason_code="UNSUPPORTED_CLASS")

        if raw_score is None or raw_score < 0.9:
            return PublicationDecision(accepted=False, reason_code="LOW_CONFIDENCE")

        rec = session.execute(
            select(Recommendation)
            .where(
                Recommendation.problem_code == class_code,
                Recommendation.active.is_(True),
            )
            .order_by(Recommendation.version.desc())
        ).scalars().first()

        if rec is None:
            return PublicationDecision(accepted=False, reason_code="CATALOG_UNAVAILABLE")

        return PublicationDecision(
            accepted=True,
            reason_code=None,
            recommendation=rec,
        )

    # Production default without active policy: fail closed
    return PublicationDecision(accepted=False, reason_code="UNSUPPORTED_CLASS")


def prediction_rejection(payload: dict, session: Optional[Session] = None) -> Optional[str]:
    """Compatibility wrapper returning reason_code string if rejected, or None if accepted."""
    if session is not None:
        decision = evaluate_publication(session=session, payload=payload)
        return decision.reason_code if not decision.accepted else None

    # Stateless fallback for older callers
    if (os.environ.get("APP_ENV") != "test"
            or os.environ.get("ENABLE_SIMULATED_INFERENCE") != "true"):
        return "UNSUPPORTED_CLASS"
    version = (payload.get("model_id"), payload.get("model_version"), payload.get("dataset_version"))
    if version != ("synth-model-v1", "0.1.0-synth", "ds-synth-2026.1"):
        return "UNSUPPORTED_CLASS"
    if payload.get("raw_score", 0) < 0.9:
        return "LOW_CONFIDENCE"
    return None
