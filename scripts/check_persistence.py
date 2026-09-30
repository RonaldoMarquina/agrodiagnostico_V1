#!/usr/bin/env python3
"""Integration acceptance: unique Compose project, generated secrets, scoped cleanup."""
import json
from ci_support import ComposeEvidence
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ('identity', 'diagnosis', 'ai_inference', 'notification')
project = 'agro-mig-test-' + uuid.uuid4().hex[:12]
started = time.monotonic()


def main():
    evidence = ComposeEvidence(project)
    with tempfile.TemporaryDirectory(prefix='agro-migrations-') as tmp:
        env = {**os.environ, 'PERSISTENCE_SECRETS_DIR': tmp, 'APP_ENV': 'local', 'HTTP_PORT': '8080', 'S3_BUCKET': 'agro-local', 'S3_REGION': 'us-east-1'}
        base = ['docker', 'compose', '--profile', 'persistence-check', '-p', project, '-f', str(ROOT / 'docker-compose.yml')]
        secrets = []

        def run(args, expect=0, timeout=180):
            result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
            output = result.stdout + result.stderr
            evidence.record(output, secrets)
            for secret in secrets:
                if secret in output:
                    raise RuntimeError('Credential found in subprocess output; output suppressed')
            if result.returncode != expect:
                # Docker output has no expanded configuration; strip any secret defensively.
                print(output[-5000:])
                raise RuntimeError('Unexpected command exit: ' + str(result.returncode))
            return result.stdout

        try:
            run(['python3', 'scripts/prepare_persistence.py', '--directory', tmp])
            secrets = [p.read_text().strip() for p in Path(tmp).glob('*_password')]
            run(base + ['config', '--quiet'])
            print('Building locked migration images...', flush=True)
            run(base + ['build', 'db-bootstrap', *[s + '-migrate' for s in SERVICES]], timeout=600)
            run(base + ['up', '-d', '--wait', 'postgres'], timeout=120)
            run(base + ['run', '--rm', '--no-deps', 'db-bootstrap'])
            run(base + ['run', '--rm', '--no-deps', 'db-bootstrap'])
            print('Clean bootstrap and second initialization PASS', flush=True)
            print(run(base + ['run', '--rm', '--no-deps', '-v', str(ROOT / 'services') + ':/sources:ro',
                              '-v', str(ROOT / 'tests/persistence/check_databases.py') + ':/check.py:ro',
                              'db-bootstrap', 'python', '/check.py'], timeout=180), flush=True)
            checks = [s + '-schema-check' for s in SERVICES]
            run(base + ['up', '-d', *checks], timeout=180)
            run(base + ['wait', *checks])
            print('One-shot dependency chain PASS', flush=True)
            # Preserve named volume during stop/recreation, then check the same heads.
            run(base + ['down'])
            run(base + ['up', '-d', '--wait', 'postgres'], timeout=120)
            # Read heads BEFORE bootstrap/migrations can recreate anything.
            for service in SERVICES:
                run(base + ['run', '--rm', '--no-deps', service + '-migrate',
                            'python', '-m', 'app.migrate', 'ready'])
            print('Persisted heads verified before reapplying migrations PASS', flush=True)
            run(base + ['up', '-d', *checks], timeout=180)
            run(base + ['wait', *checks])
            print('Stop/recreate without volume deletion PASS', flush=True)
            run(base + ['rm', '-s', '-f', 'identity-schema-check', 'identity-migrate'])
            override = Path(tmp) / 'failure.json'
            override.write_text(json.dumps({'services': {'identity-migrate': {'environment': {'DB_PASSWORD_FILE': '/run/secrets/missing'}}}}))
            failed = base + ['-f', str(override)]
            run(failed + ['up', '-d', 'identity-schema-check'], expect=1)
            # Its successful prerequisite failed: schema-check may be created, never successful.
            state = json.loads(run(base + ['ps', '--all', '--format', 'json', 'identity-schema-check']) or '{}')
            assert state.get('State') in (None, 'created'), 'check ran despite failed prerequisite'
            run(base + ['rm', '-s', '-f', 'identity-schema-check', 'identity-migrate'])
            run(base + ['up', '-d', 'identity-schema-check'])
            run(base + ['wait', 'identity-schema-check'])
            print('Failed one-shot blocks schema-check; corrected rerun PASS', flush=True)
            logs = run(base + ['logs', '--no-color'])
            assert 'SYNTHETIC_INVALID_PASSWORD_DO_NOT_LOG_83' not in logs
            print('No credentials in captured commands or container logs PASS', flush=True)
        finally:
            # Only this script's random test project, never developer volumes.
            evidence.collect(base, env, secrets)
            run(base + ['down', '--volumes', '--remove-orphans', '--rmi', 'local'])
            evidence.verify_cleanup()
        print('PASS project=' + project + ' duration_seconds=' + str(round(time.monotonic() - started, 3)))


if __name__ == '__main__':
    main()
