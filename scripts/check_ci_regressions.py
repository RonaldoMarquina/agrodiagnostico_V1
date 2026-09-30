#!/usr/bin/env python3
"""Prove global CI failure in isolated copies; never modifies the working tree."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
CASES = {'invalid-event': 'contracts', 'broken-http-reference': 'contracts',
         'failed-migration': 'persistence', 'failed-readiness': 'environment', 'timeout': 'environment'}


def mutate(root, case):
    changed = {}
    def edit(relative, transform):
        path = root/relative
        changed[relative] = path.read_bytes()
        path.write_text(transform(path.read_text()))
    if case == 'invalid-event':
        def invalid(text):
            data = json.loads(text)
            target = next(x for x in data if x['valid'] and x['schema'] == 'events/DiagnosisRequested.v1.schema.json')
            target['value'].pop('event_id')
            return json.dumps(data, indent=2)+'\n'
        edit('tests/contracts/fixtures/schema-cases.json', invalid)
    elif case == 'broken-http-reference':
        def broken(text):
            data = json.loads(text)
            data['paths']['/health/live']['get']['responses']['200']['content']['application/json']['schema'] = {'$ref': '../schemas/missing-ci-fixture.json'}
            return json.dumps(data, indent=2)+'\n'
        edit('contracts/openapi/identity.openapi.json', broken)
    elif case == 'failed-migration':
        path = next((root/'services/identity/migrations/versions').glob('*.py'))
        edit(str(path.relative_to(root)), lambda s: s.replace('def upgrade():\n    pass', 'def upgrade():\n    raise RuntimeError("synthetic migration regression")'))
    else:
        def readiness(text):
            start = text.index('\n  identity:\n'); end = text.index('\n  diagnosis:\n', start)
            block = text[start:end].replace('DB_HOST: postgres', 'DB_HOST: unavailable-readiness-fixture')
            return text[:start]+block+text[end:]
        edit('docker-compose.yml', readiness)
        if case == 'timeout':
            def shorter(text):
                data = json.loads(text)
                next(x for x in data['steps'] if x['id'] == 'environment')['timeout_seconds'] = 45
                return json.dumps(data, indent=2)+'\n'
            edit('tooling/ci/plan.json', shorter)
    if not changed or any(data == (root/path).read_bytes() for path, data in changed.items()):
        raise RuntimeError('Regression mutation did not change its target')
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--artifacts', type=Path)
    args = parser.parse_args()
    output = (args.artifacts or ROOT/'.local/ci'/('regressions-'+uuid.uuid4().hex)).resolve()
    output.mkdir(parents=True, exist_ok=False)
    summary = []
    for case in ([args.case] if args.case else CASES):
        with tempfile.TemporaryDirectory(prefix='agro-ci-regression-') as tmp:
            copy = Path(tmp)/'repo'
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns('.git', '.agents', '.codex', '.local', '.env', '.env.*', '.venv', 'node_modules', '__pycache__', '.ruff_cache', 'dist', 'bin'))
            # Reuse read-only tools, not application dependencies, secrets or Docker volumes.
            for relative in ['tooling/ci/node_modules', 'tooling/ci/.venv', 'tooling/ci/bin']:
                (copy/relative).symlink_to(ROOT/relative, target_is_directory=True)
            changed = mutate(copy, case)
            artifact = output/case
            print('Regression '+case+'...', flush=True)
            try:
                result = subprocess.run(['python3', 'scripts/run_ci.py', '--artifacts', str(artifact)], cwd=copy,
                                        capture_output=True, text=True, timeout=3000)
                (output/(case+'.log')).write_text(result.stdout+result.stderr)
                report = json.loads((artifact/'summary.json').read_text())
                failed = [x for x in report['steps'] if x['exit_code'] != 0]
                assert result.returncode != 0 and report['status'] == 'failed'
                assert failed and failed[-1]['id'] == CASES[case], (case, report)
                if case == 'timeout':
                    assert failed[-1]['exit_code'] == 124
                cleanups = list(artifact.glob('*.cleanup.json'))
                if CASES[case] in ('persistence', 'environment'):
                    assert cleanups, 'Missing cleanup evidence'
                assert all(not any(json.loads(p.read_text()).values()) for p in cleanups)
                summary.append({'case': case, 'global_exit': result.returncode, 'stage': failed[-1], 'cleanup_verified': True,
                                'mutated_original_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in changed.items()}})
                print('PASS expected global failure: '+case, flush=True)
            finally:
                for relative, original in changed.items():
                    (copy/relative).write_bytes(original)
                    assert (copy/relative).read_bytes() == original
                # Both normal and failed pipeline paths scope their Docker cleanup by recorded project.
                subprocess.run(['python3', str(ROOT/'scripts/cleanup_ci.py'), '--artifacts', str(artifact)], check=True)
                (output/'regressions.json').write_text(json.dumps(summary, indent=2)+'\n')
    print('PASS regressions: '+str(len(summary))+'; '+str(output), flush=True)


if __name__ == '__main__':
    main()
