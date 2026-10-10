"""Run separately in each service's locked environment."""
import json
import unittest
from unittest.mock import patch

from app import main
from app.persistence import schema_ready


class HealthTests(unittest.TestCase):
    def test_missing_database_configuration_fails_closed(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(schema_ready())

    def test_readiness_dependency_failure_and_recovery(self):
        for available in (False, True):
            with self.subTest(available=available), patch.object(main, 'schema_ready', return_value=available):
                if hasattr(main, 'storage_ready'):
                    with patch.object(main, 'storage_ready', return_value=True):
                        result = main.ready()
                else:
                    result = main.ready()
                self.assertEqual(result.status_code, 200 if available else 503)
                self.assertEqual(set(json.loads(result.body)), {'status', 'service'})
                self.assertEqual(main.live()['status'], 'alive')
        if hasattr(main, 'storage_ready'):
            with patch.object(main, 'schema_ready', return_value=True), patch.object(main, 'storage_ready', return_value=False):
                self.assertEqual(main.ready().status_code, 503)

    def test_openapi_contains_only_implemented_operations(self):
        if getattr(main, 'SERVICE', None) == 'identity':
            expected_paths = {
                '/health/live', '/health/ready',
                '/api/v1/auth/register', '/api/v1/auth/login',
                '/api/v1/auth/refresh', '/api/v1/auth/logout',
                '/api/v1/auth/password-recovery', '/api/v1/auth/password-recovery/confirm',
                '/api/v1/profile', '/api/v1/profile/password',
                '/api/v1/admin/users', '/api/v1/admin/users/{id}/block', '/api/v1/admin/users/{id}/activate',
            }
            self.assertEqual(set(main.app.openapi()['paths']), expected_paths)
        elif getattr(main, 'SERVICE', None) == 'diagnosis':
            expected_paths = {
                '/health/live', '/health/ready',
                '/api/v1/diagnoses', '/api/v1/diagnoses/{id}',
                '/api/v1/diagnoses/{id}/cancel',
                '/api/v1/diagnoses/{id}/image',
                '/api/v1/diagnoses/{id}/feedback',
                '/api/v1/admin/diagnoses',
                '/api/v1/crops',
                '/api/v1/crops/{code}/problems',
                '/api/v1/problems/{code}/recommendations',
                '/api/v1/admin/crops',
                '/api/v1/admin/crops/{code}',
                '/api/v1/admin/problems',
                '/api/v1/admin/problems/{code}',
                '/api/v1/admin/recommendations',
                '/api/v1/admin/recommendations/{id}',
                '/internal/diagnoses/{id}/claim',
                '/internal/diagnoses/{id}/lease/renew',
                '/internal/diagnoses/{id}/image',
            }
            self.assertEqual(set(main.app.openapi()['paths']), expected_paths)
        else:
            self.assertEqual(set(main.app.openapi()['paths']), {'/health/live', '/health/ready'})



if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HealthTests)
    if suite.countTestCases() == 0:
        raise SystemExit('Empty backend suite')
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
