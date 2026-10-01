"""Create normative append-only audit entries in the caller's transaction."""
from app.domain.models import AuditLog


def audit_entry(*, user_id, event_type, correlation_id, target_id=None, **metadata):
    return AuditLog(user_id=user_id, event_type=event_type, actor_id=user_id,
                    target_id=target_id if target_id is not None else user_id,
                    action=event_type, correlation_id=correlation_id, legacy=False, **metadata)
