"""Unit tests for email sender adapters."""
import unittest
from app.infrastructure.email import InMemoryEmailSender, LoggingEmailSender


class TestEmailSender(unittest.TestCase):
    def test_in_memory_sender(self):
        sender = InMemoryEmailSender()
        self.assertEqual(len(sender.sent_messages), 0)
        success = sender.send_password_recovery("farmer@example.com", "secret-token-123")
        self.assertTrue(success)
        self.assertEqual(len(sender.sent_messages), 1)
        self.assertEqual(sender.sent_messages[0]["to"], "farmer@example.com")
        self.assertEqual(sender.sent_messages[0]["token"], "secret-token-123")
        sender.clear()
        self.assertEqual(len(sender.sent_messages), 0)

    def test_logging_sender(self):
        sender = LoggingEmailSender()
        success = sender.send_password_recovery("farmer@example.com", "secret-token-123")
        self.assertTrue(success)


if __name__ == "__main__":
    unittest.main()
