import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from check_ci_workflow import validate_plan
from ci_support import PROJECT, redact
from run_ci import execute


class ControlTests(unittest.TestCase):
    def test_all_mandatory_steps_required(self):
        plan = json.loads((ROOT/'tooling/ci/plan.json').read_text())
        validate_plan(plan)
        for step in plan['steps']:
            missing = copy.deepcopy(plan)
            missing['steps'] = [s for s in missing['steps'] if s['id'] != step['id']]
            with self.subTest(step=step['id']), self.assertRaises(ValueError):
                validate_plan(missing)
        duplicated = copy.deepcopy(plan); duplicated['steps'].append(plan['steps'][0])
        with self.assertRaises(ValueError):
            validate_plan(duplicated)

    def test_diagnosis_acceptance_cannot_be_replaced_by_noop(self):
        plan = json.loads((ROOT/'tooling/ci/plan.json').read_text())
        step = next(s for s in plan['steps'] if s['id'] == 'diagnosis-integration')
        step['command'] = ['true']
        with self.assertRaises(ValueError):
            validate_plan(plan)

    def test_failed_process_is_not_success(self):
        code, output = execute([sys.executable, '-c', 'raise SystemExit(7)'], 5, os.environ.copy())
        self.assertEqual(code, 7)

    def test_timeout_is_failure(self):
        code, output = execute([sys.executable, '-c', 'import time; time.sleep(10)'], .05, os.environ.copy())
        self.assertEqual(code, 124)
        self.assertIn('timeout', output)

    def test_redaction(self):
        secrets = ['synthetic-secret-123', 'synthetic-access-321']
        output = redact(' '.join(secrets)+' postgresql://user:private@db/x', secrets)
        for secret in secrets+['private']:
            self.assertNotIn(secret, output)
        self.assertIn('[REDACTED]', output)

    def test_cleanup_names_cannot_target_developer_project(self):
        for name in ['agrodiagnostico-v1', 'production', 'agro-env-test-anything', 'agro-env-test-123456789012;ls']:
            self.assertIsNone(PROJECT.fullmatch(name))
        self.assertIsNotNone(PROJECT.fullmatch('agro-env-test-123456abcdef'))

    def test_empty_suite_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'tests/ci').mkdir(parents=True)
            result = subprocess.run([sys.executable, str(ROOT/'scripts/check_ci_tests.py')], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Empty CI test suite', result.stderr)


if __name__ == '__main__':
    unittest.main()
