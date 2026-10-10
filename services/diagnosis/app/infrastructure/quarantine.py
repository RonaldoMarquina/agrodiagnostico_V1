"""Transactional quarantine and operational audit helpers for Diagnosis service.

Ensures:
- Safe quarantine: stores only message hash, routing key, error reason, consumer, and validated UUIDs.
- Never stores raw payloads, images, credentials, or arbitrary blobs.
- Operational audit: strictly transactional, rollback if audit fails, automatic sanitization of sensitive fields.
"""
from datetime import datetime, timezone
import hashlib
from typing import Any, Dict, Optional
import uuid

from sqlalchemy.orm import Session

from app.domain.models import DiagnosisAuditLog, DiagnosisQuarantineMessage

SENSITIVE_KEYS = {
    "password",
    "token",
    "secret",
    "authorization",
    "access_token",
    "refresh_token",
    "jwt",
    "key",
    "private_key",
}


def sanitize_details(details: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not details:
        return details
    sanitized: Dict[str, Any] = {}
    for k, v in details.items():
        if any(secret_term in k.lower() for secret_term in SENSITIVE_KEYS):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_details(v)
        elif isinstance(v, bytes):
            sanitized[k] = f"<{len(v)} bytes redacted>"
        else:
            sanitized[k] = v
    return sanitized


def record_quarantine_message(
    session: Session,
    consumer: str,
    routing_key: str,
    raw_payload: bytes,
    error_reason: str,
    diagnosis_id: Optional[uuid.UUID] = None,
    event_id: Optional[uuid.UUID] = None,
) -> DiagnosisQuarantineMessage:
    """Safely records an invalid or unprocessable message in quarantine.

    Raw message bytes are hashed using SHA-256 and never persisted directly.
    """
    message_hash = hashlib.sha256(raw_payload).hexdigest()
    quarantine_entry = DiagnosisQuarantineMessage(
        consumer=consumer[:50],
        routing_key=routing_key[:100],
        message_hash=message_hash,
        error_reason=error_reason[:255],
        diagnosis_id=diagnosis_id,
        event_id=event_id,
    )
    session.add(quarantine_entry)
    return quarantine_entry


def build_dlq_descriptor(
    quarantine_entry: DiagnosisQuarantineMessage,
) -> Dict[str, Any]:
    """Constructs a safe DLQ descriptor payload without secrets or raw payloads."""
    created_str = (
        quarantine_entry.created_at.isoformat()
        if quarantine_entry.created_at
        else datetime.now(timezone.utc).isoformat()
    )
    return {
        "descriptor_type": "QuarantineDescriptor",
        "quarantine_id": str(quarantine_entry.id),
        "consumer": quarantine_entry.consumer,
        "routing_key": quarantine_entry.routing_key,
        "dlq_routing_key": f"{quarantine_entry.routing_key}.dlq",
        "message_hash": quarantine_entry.message_hash,
        "error_reason": quarantine_entry.error_reason,
        "diagnosis_id": str(quarantine_entry.diagnosis_id) if quarantine_entry.diagnosis_id else None,
        "event_id": str(quarantine_entry.event_id) if quarantine_entry.event_id else None,
        "quarantined_at": created_str,
    }


def publish_dlq_descriptor(
    channel: Any,
    quarantine_entry: DiagnosisQuarantineMessage,
    exchange: str = "agrodiagnostico.events",
) -> bool:
    """Publishes a safe DLQ descriptor to RabbitMQ.
    
    Returns True if published without error.
    """
    import json
    try:
        import pika
        props = pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,
            message_id=str(quarantine_entry.id),
        )
    except Exception:
        props = None

    payload = build_dlq_descriptor(quarantine_entry)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    dlq_routing_key = f"{quarantine_entry.routing_key}.dlq"

    channel.confirm_delivery()
    channel.basic_publish(
        exchange=exchange,
        routing_key=dlq_routing_key,
        body=body,
        properties=props,
        mandatory=True,
    )
    return True


def publish_pending_quarantine_descriptors(
    session: Session,
    channel: Any,
    batch_size: int = 50,
    exchange: str = "agrodiagnostico.events",
) -> int:
    """Delivers pending DLQ descriptors for quarantined messages.
    
    If DLQ/broker is temporarily unavailable, descriptors remain in quarantine table
    with descriptor_sent_at IS NULL (recuperable).
    """
    from datetime import datetime, timezone
    from sqlalchemy import select

    stmt = (
        select(DiagnosisQuarantineMessage)
        .where(DiagnosisQuarantineMessage.descriptor_sent_at.is_(None))
        .order_by(DiagnosisQuarantineMessage.created_at.asc())
        .limit(batch_size)
    )
    records = session.execute(stmt).scalars().all()
    count = 0
    now = datetime.now(timezone.utc)

    for rec in records:
        try:
            publish_dlq_descriptor(channel, rec, exchange=exchange)
            rec.descriptor_sent_at = now
            session.commit()
            count += 1
        except Exception:
            session.rollback()
            break
    return count


def record_audit_log(
    session: Session,
    actor_id: uuid.UUID,
    action: str,
    target_type: str,
    correlation_id: uuid.UUID,
    target_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> DiagnosisAuditLog:
    """Inserts an audit log entry in the current session.

    Sensitive data is sanitized. The caller must commit the session as part of
    the outer transaction; any exception during logging triggers rollback.
    """
    safe_details = sanitize_details(details)
    log_entry = DiagnosisAuditLog(
        actor_id=actor_id,
        action=action[:50],
        target_type=target_type[:50],
        target_id=target_id[:100] if target_id else None,
        correlation_id=correlation_id,
        details=safe_details,
    )
    session.add(log_entry)
    return log_entry

