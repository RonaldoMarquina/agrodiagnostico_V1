"""Contract acceptance only: no evidence of runtime authorization/delivery."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / 'contracts'
spec = importlib.util.spec_from_file_location('validate_contracts', ROOT / 'scripts/validate_contracts.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = {p.name.split('.')[0]: v.read(p) for p in (CONTRACTS / 'openapi').glob('*.json')}

    def op(self, service, path, method):
        return self.docs[service]['paths'][path][method]

    def test_package_and_all_embedded_examples(self):
        report = v.validate_package(CONTRACTS)
        self.assertEqual(report['operations'], 57)
        self.assertEqual(report['extension_openapi'], 1)
        self.assertEqual(report['extension_operations'], 3)
        self.assertGreater(report['embedded_examples'], 100)

    def test_positive_and_negative_fixtures(self):
        cases = v.read(ROOT / 'tests/contracts/fixtures/schema-cases.json')
        self.assertGreater(len(cases), 100, 'No empty or silently omitted fixture suite')
        self.assertTrue(any(c['valid'] for c in cases))
        self.assertTrue(any(not c['valid'] for c in cases))
        for case in cases:
            with self.subTest(case=case['name']):
                schema = v.resolve({'$ref': case['schema']}, CONTRACTS / 'fixtures.json', CONTRACTS)
                errors = list(v.validator(schema).iter_errors(case['value']))
                paths = [('/'.join(map(str, e.absolute_path)), e.validator) for e in errors]
                self.assertEqual(not errors, case['valid'], str(paths))

    def test_broken_reference_fixture_rejected(self):
        fixture = v.read(ROOT / 'tests/contracts/fixtures/broken-reference.json')
        with self.assertRaises(FileNotFoundError):
            v.resolve(fixture, CONTRACTS / 'openapi/fixture.json', CONTRACTS)

    def test_cli_fails_for_broken_reference_in_actual_operation(self):
        with tempfile.TemporaryDirectory(prefix='agro-negative-') as tmp:
            dest = Path(tmp) / 'contracts'
            shutil.copytree(CONTRACTS, dest)
            file = dest / 'openapi/identity.openapi.json'
            doc = v.read(file)
            doc['paths']['/api/v1/profile']['get']['responses']['200']['content']['application/json']['schema'] = v.read(ROOT / 'tests/contracts/fixtures/broken-reference.json')
            file.write_text(json.dumps(doc))
            run = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_contracts.py'), '--root', str(dest)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertIn('FAILED', run.stdout)

    def test_reference_boundaries(self):
        for ref in ['https://example.test/schema', '../../README.md', '#/$defs/missing']:
            with self.subTest(ref=ref), self.assertRaises((ValueError, KeyError)):
                v.resolve({'$ref': ref}, CONTRACTS / 'schemas/common.schema.json', CONTRACTS)

    def test_health_status_per_service(self):
        for service in self.docs:
            live = self.op(service, '/health/live', 'get')
            ready = self.op(service, '/health/ready', 'get')
            self.assertEqual(set(live['responses']), {'200'})
            self.assertEqual(set(ready['responses']), {'200', '503'})
            self.assertEqual(live['security'], [])
            self.assertEqual(ready['x-visibility'], 'internal')
            for code, status in [('200', 'ready'), ('503', 'not_ready')]:
                schema = ready['responses'][code]['content']['application/json']['schema']
                v.validator(schema).validate({'service': service, 'status': status})
                self.assertFalse(v.validator(schema).is_valid({'service': service, 'status': 'secret-detail'}))
                self.assertFalse(v.validator(schema).is_valid({'service': 'wrong', 'status': status}))

    def test_security_matrix(self):
        matrix = v.read(CONTRACTS / 'security-matrix.json')
        index = v.read(CONTRACTS / 'operations.json')
        self.assertEqual({r['operation_id'] for r in matrix}, {r['operation_id'] for r in index})
        for row in matrix:
            entry = next(r for r in index if r['operation_id'] == row['operation_id'])
            op = self.op(entry['service'], entry['path'], entry['method'].lower())
            self.assertEqual(op['security'], row['security'])
            for status in row['negative_statuses']:
                self.assertIn(str(status), op['responses'])
            if entry['path'].startswith('/internal/'):
                self.assertEqual(op['security'], [{'ServiceBearer': []}])
                self.assertIn('403', op['responses'])
            if entry['path'].endswith('/image'):
                self.assertNotIn('302', op['responses'])
                self.assertEqual(op['responses']['200']['headers']['Cache-Control']['schema'], {'const': 'private, no-store'})
        for name in ['refresh', 'logout']:
            op = self.op('identity', '/api/v1/auth/' + name, 'post')
            self.assertEqual(op['security'], [{'RefreshCookie': [], 'CsrfHeader': []}])
            self.assertTrue(next(p for p in op['parameters'] if p['name'] == 'Origin')['required'])
        for name, code in [('login', '200'), ('refresh', '200'), ('logout', '204')]:
            cookie = self.op('identity', '/api/v1/auth/' + name, 'post')['responses'][code]['headers']['Set-Cookie']['example']
            for flag in ['HttpOnly', 'Secure', 'SameSite=Lax', 'Path=/api/v1/auth']:
                self.assertIn(flag, cookie)
            self.assertNotIn('Domain=', cookie)
            if name == 'logout':
                self.assertIn('Max-Age=0', cookie)

    def test_pagination_bounds_and_invalid_cursors(self):
        for service, path in [('diagnosis', '/api/v1/diagnoses'), ('notification', '/api/v1/notifications')]:
            op = self.op(service, path, 'get')
            limit = next(p['schema'] for p in op['parameters'] if p['name'] == 'limit')
            cursor = next(p['schema'] for p in op['parameters'] if p['name'] == 'cursor')
            self.assertEqual(limit['default'], 20)
            for valid in [1, 20, 100]:
                v.validator(limit).validate(valid)
            for invalid in [0, -1, 101, '20', 1.5]:
                self.assertFalse(v.validator(limit).is_valid(invalid))
            for invalid in ['', 'x' * 2049, 1]:
                self.assertFalse(v.validator(cursor).is_valid(invalid))
            self.assertIn('400', op['responses'])

    def test_upload_contract_and_idempotency_examples(self):
        op = self.op('diagnosis', '/api/v1/diagnoses', 'post')
        for status in [202, 400, 401, 409, 413, 415]:
            self.assertIn(str(status), op['responses'])
        schema = op['requestBody']['content']['multipart/form-data']['schema']
        self.assertEqual(schema['required'], ['image'])
        self.assertEqual(set(schema['properties']), {'image', 'identified_crop'})
        self.assertEqual(schema['properties']['identified_crop']['enum'], ['POTATO'])
        v.validator(schema).validate({'image': 'synthetic', 'identified_crop': 'POTATO'})
        self.assertFalse(v.validator(schema).is_valid({'image': 'synthetic', 'identified_crop': 'MAIZE'}))
        self.assertFalse(v.validator(schema).is_valid({'image': 'synthetic', 'crop_code': 'POTATO'}))
        self.assertEqual(op['x-upload-policy']['max_file_bytes'], 10485760)
        self.assertEqual(op['x-upload-policy']['max_decoded_pixels'], 24000000)
        self.assertEqual(op['x-upload-policy']['v1_pending_media_types'], ['image/heic', 'image/heif'])
        policy = op['x-idempotency']
        self.assertEqual(policy['namespace'], ['owner_id', 'operation', 'key'])
        self.assertEqual(policy['retention_seconds'], 86400)
        self.assertFalse(policy['sliding'])
        scenarios = v.read(CONTRACTS / 'http-scenarios.json')
        idem = {s['id']: s for s in scenarios if s['id'].startswith('idempotency-')}
        for key, expected in [('same', 'same-id-current-status'), ('changed', 409), ('owner', 'independent'), ('expired', 'new-request'), ('deleted', 409), ('in-progress', 409)]:
            self.assertEqual(idem['idempotency-' + key]['expected'], expected)
        self.assertEqual(idem['idempotency-expired']['elapsed_seconds'], policy['retention_seconds'])
        self.assertEqual(idem['idempotency-same']['elapsed_seconds'], policy['retention_seconds'] - 1)
        self.assertEqual(policy['different_content'], idem['idempotency-changed']['expected'])
        self.assertEqual(policy['same_content'], idem['idempotency-same']['expected'])
        self.assertEqual(policy['different_owner'], idem['idempotency-owner']['expected'])
        self.assertEqual(policy['expired'], idem['idempotency-expired']['expected'])
        first = op['responses']['202']['content']['application/json']['example']
        self.assertEqual(idem['idempotency-same']['body']['id'], first['id'])
        self.assertEqual(idem['idempotency-same']['body']['created_at'], first['created_at'])
        self.assertNotEqual(idem['idempotency-owner']['body']['id'], first['id'])
        self.assertNotEqual(idem['idempotency-expired']['body']['id'], first['id'])
        # Declarative acceptance cases: validates response shape, not a fake handler.
        index = {r['operation_id']: r for r in v.read(CONTRACTS / 'operations.json')}
        for scenario in scenarios:
            with self.subTest(scenario=scenario['id']):
                entry = index[scenario['operation_id']]
                op = self.op(entry['service'], entry['path'], entry['method'].lower())
                response = op['responses'][str(scenario['status'])]
                if 'body' in scenario:
                    schema = response['content']['application/json']['schema']
                    schema = v.resolve(schema, CONTRACTS / ('openapi/' + entry['service'] + '.openapi.json'), CONTRACTS)
                    v.validator(schema).validate(scenario['body'])
                self.assertFalse(scenario['runtime_verified'])

    def test_event_routing_and_future_guarantees(self):
        routing = v.read(CONTRACTS / 'events/routing.json')
        expected = {
            ('DiagnosisRequested', 1): ('diagnosis', 'ai_inference', 'diagnosis.requested.v1'),
            ('DiagnosisRequested', 2): ('diagnosis', 'ai_inference', 'diagnosis.requested.v2'),
            ('DiagnosisAnalyzed', 1): ('ai_inference', 'diagnosis', 'diagnosis.analyzed.v1'),
            ('DiagnosisFinished', 1): ('diagnosis', 'notification', 'diagnosis.finished.v1'),
        }
        self.assertEqual(len(routing['events']), 4)
        for row in routing['events']:
            self.assertEqual((row['producer'], row['consumer'], row['routing_key']), expected[(row['event_type'], row['schema_version'])])
            self.assertTrue(row['durable_queue'])
            self.assertTrue(row['dlq'])
            self.assertTrue((CONTRACTS / 'events' / row['schema']).is_file())
            self.assertEqual(row['ack'], 'after-local-commit')
        self.assertEqual(routing['deduplicate_by'], ['consumer', 'event_id'])
        self.assertEqual(routing['max_attempts'], 3)
        self.assertEqual(routing['outbox_mark_sent'], 'after-publisher-confirm-and-no-return')
        scenarios = routing['future_scenarios']
        self.assertTrue({'duplicate', 'stale-lease', 'publish-crash', 'commit-crash', 'unknown-version', 'terminal-replay', 'email-down', 'redis-down', 'unroutable'} <= {s['id'] for s in scenarios})
        self.assertTrue(all(s['status'] == 'pending-runtime' for s in scenarios))

    def test_deferred_inventory_has_owner_before_consumers(self):
        items = v.read(CONTRACTS / 'deferred-operations.json')
        ids = {v['capability'] for v in items}
        self.assertTrue({'password-confirmation', 'password-change', 'feedback', 'notification-read', 'admin-users', 'admin-catalog', 'admin-diagnoses', 'audit', 'metrics', 'model-info'} <= ids)
        for item in items:
            self.assertEqual(item['status'], 'pending-contract')
            self.assertTrue(item['owner'])
            self.assertIn(item['increment'], [1, 2, 5])
            self.assertTrue(item['before_consumer'])

    def test_notification_and_internal_contact_contracts(self):
        mark_read = self.op('notification', '/api/v1/notifications/{id}/read', 'patch')
        self.assertEqual(mark_read['operationId'], 'notification_mark_read')
        self.assertEqual(mark_read['x-status'], 'implemented')
        self.assertEqual(mark_read['x-increment'], 5)
        self.assertEqual(mark_read['security'], [{'UserBearer': []}])
        self.assertNotIn('requestBody', mark_read)
        for status in ('200', '400', '401', '404'):
            self.assertIn(status, mark_read['responses'])

        prefs = self.op('notification', '/api/v1/notification-preferences', 'get')
        self.assertEqual(prefs['x-status'], 'implemented')
        self.assertEqual(
            prefs['responses']['200']['content']['application/json']['example'],
            {'email_enabled': False},
        )

        contact = self.op('identity', '/internal/users/{id}/contact', 'get')
        self.assertEqual(contact['operationId'], 'identity_internal_user_contact')
        self.assertEqual(contact['x-status'], 'implemented')
        self.assertEqual(contact['x-increment'], 5)
        self.assertEqual(contact['x-visibility'], 'internal')
        self.assertEqual(contact['security'], [{'ServiceBearer': []}])
        for status in ('200', '400', '401', '403', '404', '503'):
            self.assertIn(status, contact['responses'])
        self.assertEqual(
            contact['responses']['200']['headers']['Cache-Control']['schema'],
            {'const': 'private, no-store'},
        )

    def test_extension_assistant_contract_and_security_matrix(self):
        ext_doc = v.read(CONTRACTS / 'openapi/extensions/assistant.openapi.json')
        ext_ops = v.read(CONTRACTS / 'extensions-operations.json')
        ext_matrix = v.read(CONTRACTS / 'extensions-security-matrix.json')

        self.assertEqual({r['operation_id'] for r in ext_ops}, {r['operation_id'] for r in ext_matrix})
        self.assertEqual({r['operation_id'] for r in ext_ops}, {'assistant_live', 'assistant_ready', 'assistant_send_message'})

        for row in ext_matrix:
            entry = next(r for r in ext_ops if r['operation_id'] == row['operation_id'])
            op = ext_doc['paths'][entry['path']][entry['method'].lower()]
            self.assertEqual(op['security'], row['security'])
            self.assertTrue(op['x-extension'])
            self.assertEqual(op['x-owner'], 'assistant')
            for status in row['negative_statuses']:
                self.assertIn(str(status), op['responses'])

        send_op = ext_doc['paths']['/api/v1/assistant/messages']['post']
        self.assertEqual(send_op['operationId'], 'assistant_send_message')
        self.assertEqual(send_op['x-status'], 'implemented')
        self.assertEqual(send_op['security'], [{'UserBearer': []}])
        self.assertEqual(send_op['x-limits'], {'max_input_chars': 2000, 'max_transport_bytes': 16384})
        for status in ('200', '400', '401', '403', '413', '429', '500', '503', '504'):
            self.assertIn(status, send_op['responses'])
            self.assertEqual(
                send_op['responses'][status]['headers']['Cache-Control']['schema'],
                {'const': 'private, no-store'},
            )
        self.assertIn('Retry-After', send_op['responses']['429']['headers'])

    def test_admin_observability_and_notification_ux_contracts(self):
        block_op = self.op('identity', '/api/v1/admin/users/{id}/block', 'patch')
        self.assertIn('409', block_op['responses'])
        self.assertIn('requestBody', block_op)
        self.assertFalse(block_op['requestBody']['required'])

        expected_new = [
            ('identity', '/api/v1/admin/users/stats', 'get', 'identity_admin_user_stats', ('200', '400', '401', '403')),
            ('identity', '/api/v1/admin/audit/identity', 'get', 'identity_admin_list_audit', ('200', '400', '401', '403')),
            ('diagnosis', '/api/v1/admin/metrics/summary', 'get', 'diagnosis_admin_metrics_summary', ('200', '400', '401', '403')),
            ('diagnosis', '/api/v1/admin/audit/diagnosis', 'get', 'diagnosis_admin_list_audit', ('200', '400', '401', '403')),
            ('diagnosis', '/api/v1/admin/models', 'get', 'diagnosis_admin_list_models', ('200', '400', '401', '403')),
            ('diagnosis', '/api/v1/admin/system/status', 'get', 'diagnosis_admin_system_status', ('200', '400', '401', '403')),
            ('diagnosis', '/api/v1/admin/diagnoses/{id}/image', 'get', 'diagnosis_admin_get_image', ('200', '400', '401', '403', '404', '503')),
            ('notification', '/api/v1/notifications/read-all', 'patch', 'notification_mark_all_read', ('200', '400', '401')),
            ('notification', '/api/v1/notifications/unread-count', 'get', 'notification_unread_count', ('200', '400', '401')),
        ]
        for service, path, method, op_id, statuses in expected_new:
            with self.subTest(operation_id=op_id):
                op = self.op(service, path, method)
                self.assertEqual(op['operationId'], op_id)
                self.assertEqual(op['x-increment'], 5)
                self.assertEqual(op['security'], [{'UserBearer': []}])
                for code in statuses:
                    self.assertIn(code, op['responses'])
                    self.assertEqual(
                        op['responses'][code]['headers']['Cache-Control']['schema'],
                        {'const': 'private, no-store'},
                    )

        admin_image = self.op('diagnosis', '/api/v1/admin/diagnoses/{id}/image', 'get')
        self.assertNotIn('302', admin_image['responses'])
        self.assertEqual(
            set(admin_image['responses']['200']['content']),
            {'image/jpeg', 'image/png', 'image/webp'},
        )
        models_example = self.op('diagnosis', '/api/v1/admin/models', 'get')['responses']['200']['content']['application/json']['example']
        self.assertFalse(models_example['real_inference_authorized'])
        self.assertIsNone(models_example['active_model'])
        self.assertEqual(models_example['runtime_status'], 'INACTIVE_GATE_BLOCKED')


if __name__ == '__main__':
    unittest.main()
