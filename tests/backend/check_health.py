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

    def test_openapi_contains_only_technical_operations(self):
        self.assertEqual(set(main.app.openapi()['paths']), {'/health/live', '/health/ready'})


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HealthTests)
    if suite.countTestCases() == 0:
        raise SystemExit('Empty backend suite')
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
