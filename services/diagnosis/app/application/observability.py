"""Application services for administrative observability, audit, model inventory, system status, and audited image reads (ADR-0016)."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

import httpx
from fastapi import HTTPException, status
from sqlalchemy import desc, func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.domain.models import (
    Diagnosis,
    DiagnosisAuditLog,
    DiagnosisOutbox,
    DiagnosisQuarantineMessage,
    PublicationPolicy,
)
from app.infrastructure.cursor import (
    compute_filter_hash,
    decode_cursor,
    encode_cursor,
    format_utc_iso,
    parse_utc_iso,
)
from app.infrastructure.security import Principal
from app.persistence import schema_ready
from app.storage import (
    ObjectNotFoundError,
    S3StorageAdapter,
    StorageUnavailableError,
    storage_ready,
)

OFFICIAL_STATUSES = (
    "PENDIENTE",
    "PROCESANDO",
    "COMPLETADO",
    "NO_CONCLUYENTE",
    "FALLIDO",
    "CANCELADO",
)
MAX_METRICS_WINDOW_DAYS = 90
DEFAULT_METRICS_WINDOW_DAYS = 30
HEALTH_PROBE_TIMEOUT_SECONDS = 2.0
HEALTH_RESPONSE_MAX_BYTES = 4096
CURSOR_PURPOSE_ADMIN_DIAGNOSIS_AUDIT = "admin_diagnosis_audit"

_SENSITIVE_DETAIL_KEYS = frozenset({
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "private_key",
    "authorization",
    "cookie",
})


def _normalize_db_dt(db: Session, dt: datetime) -> datetime:
    utc_dt = dt.astimezone(timezone.utc) if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        return utc_dt.replace(tzinfo=None)
    return utc_dt


def _sanitize_details(details: Any) -> Optional[dict[str, Any]]:
    if not isinstance(details, dict):
        return None
    clean: dict[str, Any] = {}
    for k, v in details.items():
        if str(k).lower() in _SENSITIVE_DETAIL_KEYS:
            continue
        if isinstance(v, dict):
            nested = _sanitize_details(v)
            if nested is not None:
                clean[str(k)] = nested
        else:
            clean[str(k)] = v
    return clean


def get_metrics_summary(
    db: Session,
    from_raw: Optional[str] = None,
    to_raw: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute real aggregated diagnosis metrics over a bounded UTC window (<= 90 days)."""
    now = datetime.now(timezone.utc)
    try:
        parsed_from = parse_utc_iso(from_raw) if from_raw is not None else None
        parsed_to = parse_utc_iso(to_raw) if to_raw is not None else None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Formato de fecha inválido en parámetros from/to.",
            },
        )

    if parsed_from is None and parsed_to is None:
        parsed_to = now
        parsed_from = now - timedelta(days=DEFAULT_METRICS_WINDOW_DAYS)
    elif parsed_from is None and parsed_to is not None:
        parsed_from = parsed_to - timedelta(days=DEFAULT_METRICS_WINDOW_DAYS)
    elif parsed_from is not None and parsed_to is None:
        parsed_to = parsed_from + timedelta(days=DEFAULT_METRICS_WINDOW_DAYS)

    assert parsed_from is not None and parsed_to is not None
    if parsed_from > parsed_to or (parsed_to - parsed_from) > timedelta(days=MAX_METRICS_WINDOW_DAYS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Rango de fechas inválido o superior a 90 días.",
            },
        )

    db_from = _normalize_db_dt(db, parsed_from)
    db_to = _normalize_db_dt(db, parsed_to)

    rows = (
        db.query(
            Diagnosis.status,
            Diagnosis.reason_code,
            Diagnosis.calibrated_confidence,
            Diagnosis.raw_score,
            Diagnosis.created_at,
        )
        .filter(Diagnosis.created_at >= db_from, Diagnosis.created_at <= db_to)
        .all()
    )

    by_status: Dict[str, int] = {s: 0 for s in OFFICIAL_STATUSES}
    by_inconclusive_reason: Dict[str, int] = {}
    confidence_values: List[float] = []
    daily_buckets: Dict[str, Dict[str, int]] = {}

    for diag_status, reason_code, calibrated_conf, raw_score, created_at in rows:
        if diag_status in by_status:
            by_status[diag_status] += 1
        if diag_status == "NO_CONCLUYENTE" and reason_code:
            by_inconclusive_reason[reason_code] = by_inconclusive_reason.get(reason_code, 0) + 1

        conf_val = calibrated_conf if calibrated_conf is not None else raw_score
        if conf_val is not None:
            confidence_values.append(float(conf_val))

        day_key = format_utc_iso(created_at)[:10]
        bucket = daily_buckets.setdefault(
            day_key,
            {"total": 0, "completed": 0, "inconclusive": 0, "failed": 0},
        )
        bucket["total"] += 1
        if diag_status == "COMPLETADO":
            bucket["completed"] += 1
        elif diag_status == "NO_CONCLUYENTE":
            bucket["inconclusive"] += 1
        elif diag_status == "FALLIDO":
            bucket["failed"] += 1

    average_confidence = (
        round(sum(confidence_values) / len(confidence_values), 4)
        if confidence_values
        else None
    )

    daily_series = [
        {"date": day_key, **daily_buckets[day_key]}
        for day_key in sorted(daily_buckets.keys())
    ]

    return {
        "from_utc": format_utc_iso(parsed_from),
        "to_utc": format_utc_iso(parsed_to),
        "total": len(rows),
        "by_status": by_status,
        "by_inconclusive_reason": by_inconclusive_reason,
        "average_confidence": average_confidence,
        "daily_series": daily_series,
    }


def list_diagnosis_audit(
    db: Session,
    principal: Principal,
    limit: int = 20,
    cursor: Optional[str] = None,
    action: Optional[str] = None,
    actor_id: Optional[uuid.UUID] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    from_raw: Optional[str] = None,
    to_raw: Optional[str] = None,
) -> Dict[str, Any]:
    """List diagnosis_audit_logs using HMAC keyset pagination bound to principal and filters."""
    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_PAGINATION",
                "message": "El parámetro limit debe estar entre 1 y 100.",
            },
        )

    parsed_from: Optional[datetime] = None
    parsed_to: Optional[datetime] = None
    try:
        if from_raw is not None:
            parsed_from = parse_utc_iso(from_raw)
        if to_raw is not None:
            parsed_to = parse_utc_iso(to_raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": "Formato de fecha inválido en parámetros from/to.",
            },
        )

    if parsed_from is not None and parsed_to is not None and parsed_from > parsed_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_REQUEST",
                "message": "El parámetro from no puede ser posterior a to.",
            },
        )

    filter_hash = compute_filter_hash({
        "action": action,
        "actor_id": str(actor_id) if actor_id else None,
        "target_type": target_type,
        "target_id": target_id,
        "from": format_utc_iso(parsed_from) if parsed_from else None,
        "to": format_utc_iso(parsed_to) if parsed_to else None,
    })

    query = db.query(DiagnosisAuditLog).order_by(
        desc(DiagnosisAuditLog.created_at),
        desc(DiagnosisAuditLog.id),
    )

    if action is not None:
        query = query.filter(DiagnosisAuditLog.action == action)
    if actor_id is not None:
        query = query.filter(DiagnosisAuditLog.actor_id == actor_id)
    if target_type is not None:
        query = query.filter(DiagnosisAuditLog.target_type == target_type)
    if target_id is not None:
        query = query.filter(DiagnosisAuditLog.target_id == target_id)
    if parsed_from is not None:
        query = query.filter(DiagnosisAuditLog.created_at >= _normalize_db_dt(db, parsed_from))
    if parsed_to is not None:
        query = query.filter(DiagnosisAuditLog.created_at <= _normalize_db_dt(db, parsed_to))

    if cursor is not None:
        cursor_dt, cursor_id = decode_cursor(
            cursor,
            expected_principal_id=principal.id,
            expected_purpose=CURSOR_PURPOSE_ADMIN_DIAGNOSIS_AUDIT,
            expected_filter_hash=filter_hash,
        )
        db_cursor_dt = _normalize_db_dt(db, cursor_dt)
        query = query.filter(
            (DiagnosisAuditLog.created_at < db_cursor_dt)
            | ((DiagnosisAuditLog.created_at == db_cursor_dt) & (DiagnosisAuditLog.id < cursor_id))
        )

    rows = query.limit(limit + 1).all()
    has_next = len(rows) > limit
    items = rows[:limit]

    next_cursor = None
    if has_next and items:
        last = items[-1]
        next_cursor = encode_cursor(
            created_at=last.created_at,
            diagnosis_id=last.id,
            principal_id=principal.id,
            purpose=CURSOR_PURPOSE_ADMIN_DIAGNOSIS_AUDIT,
            filter_hash=filter_hash,
        )

    return {
        "items": [
            {
                "id": str(row.id),
                "actor_id": str(row.actor_id),
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "correlation_id": str(row.correlation_id),
                "details": _sanitize_details(row.details),
                "created_at": format_utc_iso(row.created_at),
            }
            for row in items
        ],
        "next_cursor": next_cursor,
    }


def get_models_inventory(db: Session) -> Dict[str, Any]:
    """Read-only honest inventory of runtime authorization state and historical model versions."""
    real_inference_authorized = (
        os.environ.get("REAL_INFERENCE_AUTHORIZED", "false").strip().lower() == "true"
    )

    active_policy = (
        db.query(PublicationPolicy)
        .filter(PublicationPolicy.active.is_(True))
        .order_by(desc(PublicationPolicy.created_at))
        .first()
    )
    active_policy_version = active_policy.policy_version if active_policy is not None else None

    if not real_inference_authorized:
        runtime_status = "INACTIVE_GATE_BLOCKED"
        active_model = None
    else:
        runtime_status = "AUTHORIZED"
        active_model = (
            {
                "model_id": active_policy.model_id,
                "model_version": active_policy.model_version,
                "dataset_version": active_policy.dataset_version,
            }
            if active_policy is not None
            else None
        )

    hist_rows = (
        db.query(
            Diagnosis.model_id,
            Diagnosis.model_version,
            Diagnosis.dataset_version,
            func.count(Diagnosis.id).label("diagnoses_count"),
            func.max(Diagnosis.created_at).label("last_used_at"),
        )
        .filter(
            Diagnosis.model_id.isnot(None),
            Diagnosis.model_version.isnot(None),
            Diagnosis.dataset_version.isnot(None),
        )
        .group_by(Diagnosis.model_id, Diagnosis.model_version, Diagnosis.dataset_version)
        .order_by(desc(func.max(Diagnosis.created_at)))
        .all()
    )

    historical_versions = [
        {
            "model_id": r.model_id,
            "model_version": r.model_version,
            "dataset_version": r.dataset_version,
            "diagnoses_count": int(r.diagnoses_count),
            "last_used_at": format_utc_iso(r.last_used_at),
        }
        for r in hist_rows
    ]

    return {
        "real_inference_authorized": real_inference_authorized,
        "runtime_status": runtime_status,
        "active_model": active_model,
        "active_policy_version": active_policy_version,
        "historical_versions": historical_versions,
    }


async def _probe_health_ready(
    client: httpx.AsyncClient, url: str, timeout: float
) -> Tuple[str, Optional[int]]:
    """Read an internal readiness response within one deadline, including its body."""
    started = time.monotonic()
    try:
        async with asyncio.timeout(timeout):
            async with client.stream("GET", url) as response:
                status_code = response.status_code
                body = bytearray()
                if status_code == 200:
                    async for chunk in response.aiter_bytes(chunk_size=HEALTH_RESPONSE_MAX_BYTES + 1):
                        body.extend(chunk)
                        if len(body) > HEALTH_RESPONSE_MAX_BYTES:
                            break
    except (TimeoutError, httpx.TimeoutException):
        return "UNKNOWN", None
    except (httpx.RequestError, httpx.InvalidURL):
        return "DOWN", None

    elapsed_ms = int((time.monotonic() - started) * 1000)
    if status_code == 503:
        return "DEGRADED", elapsed_ms
    if status_code != 200:
        return "DOWN", elapsed_ms
    if len(body) <= HEALTH_RESPONSE_MAX_BYTES:
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError):
            payload = None
        if isinstance(payload, dict) and payload.get("status") in ("ready", "ok"):
            return "OK", elapsed_ms
    return "DEGRADED", elapsed_ms


async def _probe_services(targets: list[tuple[str, str, bool]]) -> dict[str, dict[str, Any]]:
    async with httpx.AsyncClient(
        timeout=HEALTH_PROBE_TIMEOUT_SECONDS,
        headers={"Accept": "application/json"},
        trust_env=False,
    ) as client:
        results = await asyncio.gather(*(
            _probe_health_ready(client, url, HEALTH_PROBE_TIMEOUT_SECONDS)
            for _, url, _ in targets
        ))
    return {
        name: {"name": name, "status": state, "optional": optional, "latency_ms": latency}
        for (name, _, optional), (state, latency) in zip(targets, results, strict=True)
    }


def _get_local_status(db: Session) -> Tuple[Dict[str, Any], int, int]:
    local_start = time.monotonic()
    try:
        diag_ready = schema_ready() and storage_ready()
        diag_latency = max(0, int((time.monotonic() - local_start) * 1000))
        diag_status = "OK" if diag_ready else "DEGRADED"
    except Exception:
        diag_latency = None
        diag_status = "DOWN"

    local_status = {
        "name": "diagnosis",
        "status": diag_status,
        "optional": False,
        "latency_ms": diag_latency,
    }

    outbox_pending_count = int(
        db.query(func.count(DiagnosisOutbox.id))
        .filter(DiagnosisOutbox.sent_at.is_(None))
        .scalar()
        or 0
    )
    quarantine_count = int(
        db.query(func.count(DiagnosisQuarantineMessage.id)).scalar() or 0
    )
    return local_status, outbox_pending_count, quarantine_count


async def get_system_status(db: Session) -> Dict[str, Any]:
    """Aggregate remote health, local readiness and Diagnosis counters."""
    remote_targets = [
        ("identity", os.environ.get("IDENTITY_HEALTH_URL", "http://identity:8000/health/ready"), False),
        ("ai_inference", os.environ.get("AI_INFERENCE_HEALTH_URL", "http://ai_inference:8000/health/ready"), False),
        ("notification", os.environ.get("NOTIFICATION_HEALTH_URL", "http://notification:8000/health/ready"), False),
        ("assistant", os.environ.get("ASSISTANT_HEALTH_URL", "http://assistant:8000/health/ready"), True),
    ]
    results_by_name, local = await asyncio.gather(
        _probe_services(remote_targets),
        run_in_threadpool(_get_local_status, db),
    )
    results_by_name["diagnosis"], outbox_pending_count, quarantine_count = local
    ordered_names = ("identity", "diagnosis", "ai_inference", "notification", "assistant")
    services = [results_by_name[name] for name in ordered_names]

    core_statuses = [svc["status"] for svc in services if not svc["optional"]]
    if all(s == "OK" for s in core_statuses):
        overall_status = "OK"
    elif all(s == "DOWN" for s in core_statuses):
        overall_status = "DOWN"
    else:
        overall_status = "DEGRADED"

    return {
        "overall_status": overall_status,
        "checked_at": format_utc_iso(datetime.now(timezone.utc)),
        "services": services,
        "outbox_pending_count": outbox_pending_count,
        "quarantine_count": quarantine_count,
    }


def get_admin_diagnosis_image(
    db: Session,
    principal: Principal,
    diagnosis_id: uuid.UUID,
    correlation_id: uuid.UUID,
    storage: S3StorageAdapter,
) -> Tuple[bytes, str]:
    """Explicit audited administrative read of a diagnosis image (D-19, ADR-0016)."""
    diag = db.get(Diagnosis, diagnosis_id)
    if diag is None or diag.deleted_at is not None or not diag.object_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "Recurso no encontrado."},
        )

    try:
        data, content_type = storage.get_object(diag.object_key)
    except ObjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "Recurso no encontrado."},
        )
    except StorageUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "STORAGE_UNAVAILABLE", "message": "Almacenamiento temporalmente no disponible."},
        )

    # Mandatory immutable audit record committed BEFORE delivering binary bytes
    audit = DiagnosisAuditLog(
        actor_id=principal.id,
        action="ADMIN_VIEW_DIAGNOSIS_IMAGE",
        target_type="DIAGNOSIS",
        target_id=str(diag.id),
        correlation_id=correlation_id,
        details={
            "owner_id": str(diag.owner_id),
            "status": diag.status,
        },
    )
    db.add(audit)
    db.commit()

    return data, diag.image_content_type or content_type
