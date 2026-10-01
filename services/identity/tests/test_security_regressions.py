"""Regressions discovered after the increment 1 archive; isolated SQLite only."""
import os
import uuid
from unittest.mock import patch
import unittest
from tests import test_auth_api
from app.domain.models import AuditLog, User, RefreshSession
from app.infrastructure.security import csrf_for_refresh


class TestSecurityRegressions(unittest.TestCase):
    setUp = test_auth_api.TestAuthApi.setUp
    tearDown = test_auth_api.TestAuthApi.tearDown
    def register_login(self):
        payload = {'email': 'regression@example.com', 'password': 'ValidPassword123!', 'display_name': 'Test'}
        registered = self.client.post('/api/v1/auth/register', json=payload)
        login = self.client.post('/api/v1/auth/login', headers={'Origin': self.allowed_origin},
                                 json={k: payload[k] for k in ('email', 'password')})
        self.assertEqual(login.status_code, 200)
        return registered, login, payload

    def test_exact_origin(self):
        with patch.dict(os.environ, {'ALLOWED_ORIGINS': 'https://allowed.example'}):
            for origin in ['http://allowed.example', 'https://allowed.example:4444', 'https://allowed.example.attacker.test', 'null']:
                response = self.client.post('/api/v1/auth/login', headers={'Origin': origin},
                                            json={'email': 'x@example.com', 'password': 'test'})
                self.assertEqual(response.status_code, 403)

    def test_csrf_bound_to_refresh_session(self):
        _, login, _ = self.register_login()
        token = login.cookies['__Secure-agro_refresh']
        for csrf in ['arbitrary', csrf_for_refresh('another-session')]:
            for path in ['refresh', 'logout']:
                response = self.client.post('/api/v1/auth/'+path,
                    headers={'Origin': self.allowed_origin, 'X-CSRF-Token': csrf},
                    cookies={'__Secure-agro_refresh': token, 'csrf_token': csrf})
                self.assertEqual(response.status_code, 403)
        with self.TestingSessionLocal() as db:
            session = db.query(RefreshSession).one()
            self.assertIsNone(session.revoked_at)
            self.assertIsNone(session.rotated_at)

    def test_blocked_login_is_generic_and_audited(self):
        _, _, payload = self.register_login()
        with self.TestingSessionLocal() as db:
            db.query(User).one().status = 'BLOCKED'
            db.commit()
        response = self.client.post('/api/v1/auth/login', headers={'Origin': self.allowed_origin},
                                    json={k: payload[k] for k in ('email', 'password')})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'INVALID_CREDENTIALS')
        self.assertNotIn('__Secure-agro_refresh', response.cookies)

    def test_logout_unknown_session(self):
        token = 'unknown-session'; csrf = csrf_for_refresh(token)
        response = self.client.post('/api/v1/auth/logout',
            headers={'Origin': self.allowed_origin, 'X-CSRF-Token': csrf},
            cookies={'__Secure-agro_refresh': token, 'csrf_token': csrf})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.cookies['__Secure-agro_refresh'], '')

    def test_correlation_and_registration_audit(self):
        registered, _, payload = self.register_login()
        with self.TestingSessionLocal() as db:
            event = db.query(AuditLog).filter_by(action='USER_REGISTERED').one()
            self.assertEqual(str(event.correlation_id), registered.headers['X-Correlation-ID'])
            self.assertEqual(event.actor_id, event.target_id)
            self.assertFalse(event.legacy)
        for header in [None, str(uuid.uuid4()), 'invalid']:
            headers = {} if header is None else {'X-Correlation-ID': header}
            response = self.client.post('/api/v1/auth/register', headers=headers, json=payload)
            self.assertEqual(response.json()['correlation_id'], response.headers['X-Correlation-ID'])

    def test_error_clears_refresh_cookie(self):
        _, login, _ = self.register_login()
        cookies = login.cookies
        headers = {'Origin': self.allowed_origin, 'X-CSRF-Token': login.json()['csrf_token']}
        self.assertEqual(self.client.post('/api/v1/auth/refresh', headers=headers, cookies=cookies).status_code, 200)
        response = self.client.post('/api/v1/auth/refresh', headers=headers, cookies=cookies)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.cookies['__Secure-agro_refresh'], '')

    def test_registration_rolls_back_if_audit_fails(self):
        with patch('app.api.auth.audit_entry', side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):
                self.client.post('/api/v1/auth/register', json={
                    'email': 'rollback@example.com', 'password': 'ValidPassword123!', 'display_name': 'Test'})
        with self.TestingSessionLocal() as db:
            self.assertEqual(db.query(User).count(), 0)
            self.assertEqual(db.query(AuditLog).count(), 0)
