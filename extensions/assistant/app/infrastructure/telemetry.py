"""Safe structured logging and low-cardinality metrics for the assistant extension (ADR-0015).

Never logs user text, prompts, tokens, API keys, or raw provider payloads.
Never uses user identifiers as metric labels.
"""
from collections import Counter
import json
import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("agrodiagnostico.assistant")

ALLOWED_LOG_FIELDS = frozenset(
    {
        "event",
        "correlation_id",
        "role",
        "intent",
        "decision",
        "http_status",
        "latency_ms",
        "provider",
        "error_class",
        "reason_code",
    }
)


class MetricsRegistry:
    """Thread-safe in-memory counters with strictly low-cardinality labels."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Counter = Counter()

    def increment(self, metric_name: str, **labels: str) -> None:
        if "user_id" in labels or "sub" in labels or "email" in labels:
            raise ValueError("High-cardinality user identifiers are forbidden in metrics")
        key = (metric_name, tuple(sorted((str(k), str(v)) for k, v in labels.items())))
        with self._lock:
            self._counters[key] += 1

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            out: Dict[str, int] = {}
            for (name, label_pairs), count in self._counters.items():
                if label_pairs:
                    suffix = ",".join(f"{k}={v}" for k, v in label_pairs)
                    out[f"{name}{{{suffix}}}"] = count
                else:
                    out[name] = count
            return out

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()


_GLOBAL_METRICS = MetricsRegistry()


def get_metrics() -> MetricsRegistry:
    return _GLOBAL_METRICS


def build_safe_log_record(
    *,
    event: str,
    correlation_id: str,
    role: Optional[str] = None,
    intent: Optional[str] = None,
    decision: Optional[str] = None,
    http_status: Optional[int] = None,
    latency_ms: Optional[float] = None,
    provider: Optional[str] = None,
    error_class: Optional[str] = None,
    reason_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a strictly allowlisted structured log payload."""
    payload: Dict[str, Any] = {
        "event": event,
        "correlation_id": correlation_id,
    }
    optional_fields = {
        "role": role,
        "intent": intent,
        "decision": decision,
        "http_status": http_status,
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "provider": provider,
        "error_class": error_class,
        "reason_code": reason_code,
    }
    for key, value in optional_fields.items():
        if value is not None and key in ALLOWED_LOG_FIELDS:
            payload[key] = value
    return payload


def log_assistant_event(
    *,
    level: int = logging.INFO,
    event: str,
    correlation_id: str,
    role: Optional[str] = None,
    intent: Optional[str] = None,
    decision: Optional[str] = None,
    http_status: Optional[int] = None,
    latency_ms: Optional[float] = None,
    provider: Optional[str] = None,
    error_class: Optional[str] = None,
    reason_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Emit a safe JSON log line and return the emitted dict."""
    record = build_safe_log_record(
        event=event,
        correlation_id=correlation_id,
        role=role,
        intent=intent,
        decision=decision,
        http_status=http_status,
        latency_ms=latency_ms,
        provider=provider,
        error_class=error_class,
        reason_code=reason_code,
    )
    logger.log(level, json.dumps(record, sort_keys=True, ensure_ascii=False))
    return record
