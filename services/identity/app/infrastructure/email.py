"""Email delivery adapter for password recovery and identity notifications."""
import logging
import os
from typing import List, Optional, Protocol

logger = logging.getLogger("identity.email")


class EmailSender(Protocol):
    """Decoupled interface for dispatching emails."""

    def send_password_recovery(self, to_email: str, raw_token: str) -> bool:
        """Send password recovery email containing the one-time token."""
        ...


class InMemoryEmailSender:
    """In-memory email sender for testing and development."""

    def __init__(self):
        self.sent_messages: List[dict] = []

    def send_password_recovery(self, to_email: str, raw_token: str) -> bool:
        self.sent_messages.append({
            "to": to_email,
            "type": "PASSWORD_RECOVERY",
            "token": raw_token,
        })
        return True

    def clear(self):
        self.sent_messages.clear()


class LoggingEmailSender:
    """Local development email sender that logs delivery attempts safely."""

    def send_password_recovery(self, to_email: str, raw_token: str) -> bool:
        # Mask email and do NOT log raw token in production logs
        masked = to_email[:2] + "***@" + to_email.split("@")[-1] if "@" in to_email else "***"
        logger.info(f"Password recovery email dispatched to {masked}")
        return True


_GLOBAL_SENDER: Optional[EmailSender] = None


def get_email_sender() -> EmailSender:
    global _GLOBAL_SENDER
    if _GLOBAL_SENDER is None:
        mode = os.environ.get("EMAIL_SENDER_MODE", "memory")
        if mode == "logging":
            _GLOBAL_SENDER = LoggingEmailSender()
        else:
            _GLOBAL_SENDER = InMemoryEmailSender()
    return _GLOBAL_SENDER


def set_email_sender(sender: EmailSender) -> None:
    global _GLOBAL_SENDER
    _GLOBAL_SENDER = sender
