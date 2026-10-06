"""Unit tests for Ed25519 JWT verification and claims validation in Diagnosis."""
import time
import unittest
import uuid
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.infrastructure.tokens import (
    TokenVerifier,
    TokenExpiredError,
    TokenInvalidError,
    TokenError,
    generate_ed25519_keypair,
)


class TestDiagnosisTokens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.priv_pem, cls.pub_pem = generate_ed25519_keypair()
        cls.verifier = TokenVerifier(public_key_pem=cls.pub_pem)

    def _create_token(
        self,
        sub: str = None,
        role: str = "USER",
        iss: str = "agrodiagnostico-identity",
        aud: str = "agrodiagnostico-api",
        expires_in: int = 60,
        extra_claims: dict = None,
        omit_claims: list = None,
        algorithm: str = "EdDSA",
        key: str = None,
    ) -> str:
        now = int(time.time())
        claims = {
            "sub": str(sub or uuid.uuid4()),
            "role": role,
            "iss": iss,
            "aud": aud,
            "iat": now,
            "exp": now + expires_in,
            "jti": str(uuid.uuid4()),
        }
        if extra_claims:
            claims.update(extra_claims)
        if omit_claims:
            for c in omit_claims:
                claims.pop(c, None)

        signing_key = key or self.priv_pem
        return jwt.encode(claims, signing_key, algorithm=algorithm)

    def test_valid_token_decoding(self):
        user_id = str(uuid.uuid4())
        token = self._create_token(sub=user_id, role="USER")
        payload = self.verifier.decode_access_token(token)

        self.assertEqual(payload["sub"], user_id)
        self.assertEqual(payload["role"], "USER")
        self.assertEqual(payload["iss"], "agrodiagnostico-identity")
        self.assertEqual(payload["aud"], "agrodiagnostico-api")
        self.assertIn("jti", payload)

    def test_valid_admin_token(self):
        admin_id = str(uuid.uuid4())
        token = self._create_token(sub=admin_id, role="ADMIN")
        payload = self.verifier.decode_access_token(token)
        self.assertEqual(payload["role"], "ADMIN")

    def test_token_expiration(self):
        token = self._create_token(expires_in=-10)
        with self.assertRaises(TokenExpiredError):
            self.verifier.decode_access_token(token)

    def test_tampered_token_signature(self):
        token = self._create_token()
        parts = token.split(".")
        tampered = f"{parts[0]}.eyJyYW5kb20iOiJib2d1cyJ9.{parts[2]}"
        with self.assertRaises(TokenInvalidError):
            self.verifier.decode_access_token(tampered)

    def test_untrusted_signing_key(self):
        other_priv, _ = generate_ed25519_keypair()
        token = self._create_token(key=other_priv)
        with self.assertRaises(TokenInvalidError):
            self.verifier.decode_access_token(token)

    def test_wrong_issuer(self):
        token = self._create_token(iss="rogue-identity-service")
        with self.assertRaises(TokenInvalidError):
            self.verifier.decode_access_token(token)

    def test_wrong_audience(self):
        token = self._create_token(aud="other-system")
        with self.assertRaises(TokenInvalidError):
            self.verifier.decode_access_token(token)

    def test_disallowed_algorithm_hs256(self):
        # Attacker tries to use HMAC with public key as secret
        claims = {
            "sub": str(uuid.uuid4()),
            "role": "USER",
            "iss": "agrodiagnostico-identity",
            "aud": "agrodiagnostico-api",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
            "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(claims, "secret-key", algorithm="HS256")
        with self.assertRaises(TokenInvalidError):
            self.verifier.decode_access_token(token)

    def test_disallowed_algorithm_none(self):
        claims = {
            "sub": str(uuid.uuid4()),
            "role": "USER",
            "iss": "agrodiagnostico-identity",
            "aud": "agrodiagnostico-api",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
            "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(claims, "", algorithm="none")
        with self.assertRaises(TokenInvalidError):
            self.verifier.decode_access_token(token)

    def test_missing_mandatory_claims(self):
        for missing in ["sub", "role", "iss", "aud", "exp", "iat", "jti"]:
            token = self._create_token(omit_claims=[missing])
            with self.assertRaises(TokenInvalidError, msg=f"Should reject when {missing} is missing"):
                self.verifier.decode_access_token(token)

    def test_invalid_sub_uuid(self):
        token = self._create_token(sub="not-a-valid-uuid")
        with self.assertRaises(TokenInvalidError):
            self.verifier.decode_access_token(token)

    def test_invalid_role(self):
        for bad_role in ["SUPERUSER", "GUEST", "admin", "user", ""]:
            token = self._create_token(role=bad_role)
            with self.assertRaises(TokenInvalidError, msg=f"Should reject invalid role: {bad_role}"):
                self.verifier.decode_access_token(token)

    def test_fail_closed_without_public_key(self):
        unconfigured_verifier = TokenVerifier(public_key_pem=None)
        token = self._create_token()
        with self.assertRaises(TokenError):
            unconfigured_verifier.decode_access_token(token)

    def test_fail_closed_with_non_ed25519_key(self):
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pub_pem = rsa_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        with self.assertRaises(TokenError):
            TokenVerifier(public_key_pem=rsa_pub_pem)


if __name__ == "__main__":
    unittest.main()
