"""Unit tests for Argon2id and SHA-256 cryptographic security utilities."""
import unittest
from app.infrastructure.security import (
    validate_password_policy,
    hash_password,
    verify_password,
    generate_secure_token,
    hash_token,
    verify_token_hash,
)


class TestSecurity(unittest.TestCase):
    def test_password_policy_bounds(self):
        # Min length is 12, max length is 128
        self.assertFalse(validate_password_policy("short"))
        self.assertFalse(validate_password_policy("12345678901"))  # 11 chars
        self.assertTrue(validate_password_policy("123456789012"))   # 12 chars
        self.assertTrue(validate_password_policy("ValidPassword123!"))
        self.assertTrue(validate_password_policy("a" * 128))        # 128 chars
        self.assertFalse(validate_password_policy("a" * 129))       # 129 chars
        self.assertFalse(validate_password_policy(None))
        self.assertFalse(validate_password_policy(12345))

    def test_argon2id_hash_and_verify(self):
        pwd = "CorrectHorseBatteryStaple123"
        hashed = hash_password(pwd)
        self.assertTrue(hashed.startswith("$argon2id$"))
        self.assertTrue(verify_password(pwd, hashed))
        self.assertFalse(verify_password("WrongPassword123", hashed))
        self.assertFalse(verify_password("", hashed))
        self.assertFalse(verify_password(pwd, ""))

    def test_hash_password_rejects_invalid_policy(self):
        with self.assertRaises(ValueError):
            hash_password("short")

    def test_secure_token_and_sha256_hash(self):
        token1 = generate_secure_token(32)
        token2 = generate_secure_token(32)
        self.assertNotEqual(token1, token2)

        h1 = hash_token(token1)
        self.assertEqual(len(h1), 64)  # 64 hex chars = 256 bits
        self.assertEqual(h1, hash_token(token1))  # deterministic

        self.assertTrue(verify_token_hash(token1, h1))
        self.assertFalse(verify_token_hash(token2, h1))
        self.assertFalse(verify_token_hash("wrong", h1))


if __name__ == "__main__":
    unittest.main()
