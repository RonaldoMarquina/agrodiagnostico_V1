"""Decoupled email delivery adapters for Notification service (ADR-0014)."""
from email.message import EmailMessage
import logging
import os
from pathlib import Path
import smtplib
from typing import List, Optional, Protocol

logger = logging.getLogger("notification.email")


class EmailDeliveryError(Exception):
    """Safe domain error raised when an email provider fails."""

    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


class EmailDeliveryAdapter(Protocol):
    def send_diagnosis_finished(
        self,
        to_email: str,
        diagnosis_id: str,
        final_status: str,
        correlation_id: str,
    ) -> None:
        ...


def mask_email(email: str) -> str:
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    prefix = local[:2] if len(local) >= 2 else "*"
    return f"{prefix}***@{domain}"


class InMemoryEmailDeliveryAdapter:
    """Deterministic in-memory adapter for unit tests and failure simulation."""

    def __init__(self, fail_times: int = 0, always_fail: bool = False):
        self.sent: List[dict] = []
        self.fail_times = fail_times
        self.always_fail = always_fail
        self.attempts = 0

    def send_diagnosis_finished(
        self,
        to_email: str,
        diagnosis_id: str,
        final_status: str,
        correlation_id: str,
    ) -> None:
        self.attempts += 1
        if self.always_fail or self.attempts <= self.fail_times:
            raise EmailDeliveryError("EMAIL_PROVIDER_UNAVAILABLE")
        self.sent.append(
            {
                "to": to_email,
                "diagnosis_id": diagnosis_id,
                "final_status": final_status,
                "correlation_id": correlation_id,
            }
        )


class LoggingEmailDeliveryAdapter:
    """Safe local adapter that logs masked delivery attempts without network calls."""

    def send_diagnosis_finished(
        self,
        to_email: str,
        diagnosis_id: str,
        final_status: str,
        correlation_id: str,
    ) -> None:
        logger.info(
            "Email notification dispatched recipient=%s diagnosis_id=%s final_status=%s correlation_id=%s",
            mask_email(to_email),
            diagnosis_id,
            final_status,
            correlation_id,
        )


class SmtpEmailDeliveryAdapter:
    """Configurable SMTP delivery adapter for production deployments."""

    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: bool = True,
        timeout_seconds: float = 10.0,
    ):
        self.host = host
        self.port = port
        self.sender = sender
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> "SmtpEmailDeliveryAdapter":
        host = os.environ.get("SMTP_HOST", "").strip()
        port = int(os.environ.get("SMTP_PORT", "587"))
        sender = os.environ.get("SMTP_FROM", "no-reply@agrodiagnostico.local").strip()
        username = os.environ.get("SMTP_USER")
        password = os.environ.get("SMTP_PASSWORD")
        pw_file = os.environ.get("SMTP_PASSWORD_FILE")
        if not password and pw_file and Path(pw_file).is_file():
            password = Path(pw_file).read_text().strip()
        use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
        timeout = float(os.environ.get("SMTP_TIMEOUT_SECONDS", "10.0"))
        return cls(
            host=host,
            port=port,
            sender=sender,
            username=username,
            password=password,
            use_tls=use_tls,
            timeout_seconds=timeout,
        )

    def send_diagnosis_finished(
        self,
        to_email: str,
        diagnosis_id: str,
        final_status: str,
        correlation_id: str,
    ) -> None:
        if not self.host:
            raise EmailDeliveryError("SMTP_NOT_CONFIGURED")

        msg = EmailMessage()
        msg["Subject"] = f"AgroDiagnóstico: tu diagnóstico finalizó ({final_status})"
        msg["From"] = self.sender
        msg["To"] = to_email
        msg["X-Correlation-ID"] = correlation_id
        msg.set_content(
            f"Tu solicitud de diagnóstico {diagnosis_id} finalizó con estado {final_status}.\n"
            "Ingresa a la plataforma AgroDiagnóstico para revisar el detalle."
        )

        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.send_message(msg)
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailDeliveryError("SMTP_AUTH_FAILED") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError("SMTP_UNAVAILABLE") from exc


_GLOBAL_ADAPTER: Optional[EmailDeliveryAdapter] = None


def get_email_delivery_adapter() -> EmailDeliveryAdapter:
    global _GLOBAL_ADAPTER
    if _GLOBAL_ADAPTER is None:
        mode = os.environ.get("EMAIL_DELIVERY_MODE", "logging").strip().lower()
        if mode == "memory":
            _GLOBAL_ADAPTER = InMemoryEmailDeliveryAdapter()
        elif mode == "smtp":
            _GLOBAL_ADAPTER = SmtpEmailDeliveryAdapter.from_environment()
        else:
            _GLOBAL_ADAPTER = LoggingEmailDeliveryAdapter()
    return _GLOBAL_ADAPTER


def set_email_delivery_adapter(adapter: Optional[EmailDeliveryAdapter]) -> None:
    global _GLOBAL_ADAPTER
    _GLOBAL_ADAPTER = adapter
