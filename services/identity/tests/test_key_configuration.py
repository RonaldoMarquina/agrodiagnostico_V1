"""Persistent local key preparation and fail-closed JWT configuration."""
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from app.infrastructure.tokens import TokenManager, TokenError


class TestKeyConfiguration(unittest.TestCase):
    def test_preparer_preserves_and_validates_keys(self):
        root = Path(__file__).resolve().parents[3]
        path = root/'scripts/prepare_identity_keys.py'
        spec = importlib.util.spec_from_file_location('prepare_keys', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            module.prepare(directory)
            private = directory/'jwt_private_key.pem'; public = directory/'jwt_public_key.pem'
            before = private.read_bytes(), public.read_bytes()
            module.prepare(directory)
            self.assertEqual(before, (private.read_bytes(), public.read_bytes()))
            self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
            with patch.dict(os.environ, {'JWT_PRIVATE_KEY_PATH': str(private), 'JWT_PUBLIC_KEY_PATH': str(public)}, clear=True):
                manager = TokenManager.from_environment()
                import uuid
                token = manager.create_access_token(uuid.uuid4(), 'USER')
                self.assertEqual(manager.decode_access_token(token)['role'], 'USER')
            public.write_text('invalid')
            with self.assertRaises(ValueError):
                module.prepare(directory)
            self.assertEqual(private.read_bytes(), before[0])

    def test_missing_key_cannot_issue_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TokenError):
                TokenManager.from_environment().create_access_token('user', 'USER')
