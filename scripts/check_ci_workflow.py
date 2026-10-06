"""Check executable CI plan and security/version invariants; actionlint checks YAML."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {'workflow', 'python-lint', 'ci-tests', 'contracts', 'dataset', 'backend',
            'frontend-install', 'frontend-lint', 'frontend-types', 'frontend-tests',
            'frontend-build', 'openspec', 'persistence', 'environment', 'identity-integration', 'diagnosis-integration'}


def validate_plan(plan):
    names = [s['id'] for s in plan['steps']]
    if len(names) != len(set(names)) or set(names) != REQUIRED:
        raise ValueError('CI plan missing/duplicate required steps')
    diagnosis = next(s for s in plan['steps'] if s['id'] == 'diagnosis-integration')
    if diagnosis['command'] != ['python3', 'scripts/check_acceptance_incremento2.py']:
        raise ValueError('Diagnosis integration must execute the acceptance suite')
    for step in plan['steps']:
        if not step.get('command') or not 1 <= step.get('timeout_seconds', 0) <= 1800:
            raise ValueError('CI command or timeout missing')


def main():
    validate_plan(json.loads((ROOT/'tooling/ci/plan.json').read_text()))
    workflow = (ROOT/'.github/workflows/application-ci.yml').read_text()
    config = json.loads((ROOT/'tooling/ci/tools.json').read_text())
    refs = re.findall(r'uses: ([^\s]+)', workflow)
    expected = {a['repository']+'@'+a['sha'] for a in config['actions']}
    assert set(refs) == expected and all(re.search(r'@[0-9a-f]{40}$', x) for x in refs)
    for token in ('pull_request:', 'push:', 'branches: [main]', 'contents: read', 'timeout-minutes:',
                  'persist-credentials: false', 'if: always()', 'scripts/run_ci.py', 'scripts/cleanup_ci.py'):
        assert token in workflow, 'Workflow missing '+token
    for token in ('pull_request_target', 'secrets.', 'continue-on-error', 'self-hosted', 'gpu'):
        assert token not in workflow, 'Forbidden workflow option '+token
    result = subprocess.run([str(ROOT/'tooling/ci/bin/actionlint'), '-shellcheck=', '-pyflakes=',
                             str(ROOT/'.github/workflows/application-ci.yml')], cwd=ROOT)
    if result.returncode:
        raise SystemExit(result.returncode)
    print('PASS workflow: immutable actions, required stages, least permissions, always cleanup/artifacts')


if __name__ == '__main__':
    main()
