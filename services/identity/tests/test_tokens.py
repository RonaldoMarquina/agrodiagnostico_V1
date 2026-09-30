"""Unit tests for Ed25519 (EdDSA) asymmetric JWT token management."""
import time
import unittest
import uuid

from app.infrastructure.tokens import (
    TokenManager,
    TokenExpiredError,
    TokenInvalidError,
    TokenError,
    generate_ed25519_keypair,
)


class TestTokens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.priv_pem, cls.pub_pem = generate_ed25519_keypair()
        cls.manager = TokenManager(
            private_key_pem=cls.priv_pem,
            public_key_pem=cls.pub_pem,
        )

    def test_create_and_decode_token(self):
        user_id = uuid.uuid4()
        token = self.manager.create_access_token(user_id=user_id, role="USER", expires_in_seconds=60)
        self.assertIsInstance(token, str)

        payload = self.manager.decode_access_token(token)
        self.assertEqual(payload["sub"], str(user_id))
        self.assertEqual(payload["role"], "USER")
        self.assertEqual(payload["iss"], "agrodiagnostico-identity")
        self.assertEqual(payload["aud"], "agrodiagnostico-api")
        self.assertIn("exp", payload)
        self.assertIn("iat", payload)
        self.assertIn("jti", payload)
        self.assertGreater(payload["exp"], payload["iat"])

    def test_token_expiration(self):
        user_id = uuid.uuid4()
        # Create token that expired 10 seconds ago
        token = self.manager.create_access_token(user_id=user_id, role="USER", expires_in_seconds=-10)
        with self.assertRaises(TokenExpiredError):
            self.manager.decode_access_token(token)

    def test_tampered_token_rejected(self):
        user_id = uuid.uuid4()
        token = self.manager.create_access_token(user_id=user_id, role="USER")
        parts = token.split(".")
        # Tamper payload part
        tampered_token = f"{parts[0]}.eyJyYW5kb20iOiJib2d1cyJ9.{parts[2]}"
        with self.assertRaises(TokenInvalidError):
            self.manager.decode_access_token(tampered_token)

    def test_wrong_key_rejected(self):
        # Generate another untrusted keypair
        other_priv, _ = generate_ed25519_keypair()
        other_manager = TokenManager(private_key_pem=other_priv)
        token = other_manager.create_access_token(user_id=uuid.uuid4(), role="USER")

        # Decoding with our public key should fail signature verification
        with self.assertRaises(TokenInvalidError):
            self.manager.decode_access_token(token)

    def test_wrong_issuer_or_audience_rejected(self):
        custom_manager = TokenManager(
            private_key_pem=self.priv_pem,
            public_key_pem=self.pub_pem,
            issuer="wrong-issuer",
            audience="agrodiagnostico-api",
        )
        token = custom_manager.create_access_token(user_id=uuid.uuid4(), role="USER")
        with self.assertRaises(TokenInvalidError):
            self.manager.decode_access_token(token)

    def test_public_key_only_verifier(self):
        # Instances that only verify do not need private key
        verifier = TokenManager(public_key_pem=self.pub_pem)
        user_id = uuid.uuid4()
        token = self.manager.create_access_token(user_id=user_id, role="ADMIN")
        payload = verifier.decode_access_token(token)
        self.assertEqual(payload["role"], "ADMIN")

        # Verifier cannot create tokens without private key
        with self.assertRaises(TokenError):
            verifier.create_access_token(user_id=user_id, role="ADMIN")


if __name__ == "__main__":
    unittest.main()
