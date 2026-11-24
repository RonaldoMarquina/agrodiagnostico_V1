"""Persistent local key preparation and fail-closed JWT configuration."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from app.infrastructure.internal_auth import (
    TrustedKeyRegistry,
    create_internal_token,
    verify_internal_token,
)
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

    def test_internal_key_preparer_preserves_workers_and_adds_notification_key(self):
        root = Path(__file__).resolve().parents[3]
        script_path = root / 'scripts/prepare_internal_keys.py'
        spec = importlib.util.spec_from_file_location('prepare_internal_keys', script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            run = subprocess.run(
                [sys.executable, str(script_path), '--directory', str(directory)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertNotIn('BEGIN PRIVATE KEY', run.stdout)
            self.assertNotIn('BEGIN PUBLIC KEY', run.stdout)

            worker1_priv = directory / 'internal_worker_1_private_key.pem'
            worker2_priv = directory / 'internal_worker_2_private_key.pem'
            notif_priv = directory / 'internal_notification_1_private_key.pem'
            notif_pub = directory / 'internal_notification_1_public_key.pem'
            registry_path = directory / 'internal_service_keys.json'

            for p in (worker1_priv, worker2_priv, notif_priv, notif_pub, registry_path):
                self.assertTrue(p.is_file(), f'Missing expected key file: {p.name}')
                self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

            before_worker1 = worker1_priv.read_bytes()
            before_worker2 = worker2_priv.read_bytes()
            before_notif = notif_priv.read_bytes()
            registry_data = json.loads(registry_path.read_text())
            self.assertEqual(
                set(registry_data.keys()),
                {'worker-1-key', 'worker-2-key', 'notification-1-key'},
            )
            self.assertEqual(registry_data['worker-1-key']['principal'], 'ai_inference')
            self.assertEqual(registry_data['worker-2-key']['principal'], 'ai_inference')
            self.assertEqual(registry_data['notification-1-key']['principal'], 'notification')
            self.assertEqual(registry_data['notification-1-key']['instance_id'], 'notification-1')

            # Simulate legacy persistence dir containing only worker-1/worker-2 in registry
            legacy_registry = {
                'worker-1-key': registry_data['worker-1-key'],
                'worker-2-key': registry_data['worker-2-key'],
            }
            registry_path.write_text(json.dumps(legacy_registry, indent=2))

            module.prepare(directory)
            self.assertEqual(worker1_priv.read_bytes(), before_worker1)
            self.assertEqual(worker2_priv.read_bytes(), before_worker2)
            self.assertEqual(notif_priv.read_bytes(), before_notif)
            upgraded = json.loads(registry_path.read_text())
            self.assertEqual(upgraded, registry_data)

            # Verify notification-1 token validates against the generated registry
            with patch.dict(os.environ, {'INTERNAL_SERVICE_KEYS_FILE': str(registry_path)}, clear=True):
                registry = TrustedKeyRegistry.from_environment()
                token = create_internal_token(
                    private_key_pem=notif_priv.read_text(),
                    kid='notification-1-key',
                    instance_id='notification-1',
                )
                ident = verify_internal_token(token, registry=registry)
                self.assertEqual(ident.principal, 'notification')
                self.assertEqual(ident.instance_id, 'notification-1')

            # Corrupted registry entry must fail closed without overwriting private keys
            corrupted = dict(upgraded)
            corrupted['notification-1-key'] = dict(corrupted['notification-1-key'], principal='ai_inference')
            registry_path.write_text(json.dumps(corrupted, indent=2))
            with self.assertRaises(ValueError):
                module.prepare(directory)
            self.assertEqual(notif_priv.read_bytes(), before_notif)

    def test_missing_key_cannot_issue_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(TokenError):
                TokenManager.from_environment().create_access_token('user', 'USER')
