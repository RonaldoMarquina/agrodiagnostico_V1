#!/usr/bin/env python3
"""Same required CI pipeline locally and on GitHub; nonzero on any missing/failing stage."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from check_ci_workflow import validate_plan
from ci_support import cleanup, redact

ROOT = Path(__file__).resolve().parents[1]


def execute(command, timeout, env):
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
        return process.returncode, output
    except subprocess.TimeoutExpired:
        # TERM lets acceptance scripts collect diagnostics and run finally cleanup.
        os.killpg(process.pid, signal.SIGTERM)
        try:
            output, _ = process.communicate(timeout=210)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
        return 124, output+'\nCI stage timeout\n'
    except BaseException:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=210)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise


def versions(env):
    commands = {'python': ['python3', '--version'], 'node': ['node', '--version'],
                'npm': ['npm', '--version'], 'openspec': ['openspec', '--version'],
                'docker': ['docker', 'version', '--format', '{{.Server.Version}}'],
                'compose': ['docker', 'compose', 'version', '--short']}
    return {name: subprocess.check_output(command, env=env, text=True, timeout=30).strip()
            for name, command in commands.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path)
    args = parser.parse_args()
    directory = (args.artifacts or ROOT/'.local/ci'/uuid.uuid4().hex).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, AGRO_CI_ARTIFACTS=str(directory), PYTHONUNBUFFERED='1',
               DOCKER_BUILDKIT='0', COMPOSE_BAKE='false', OPENSPEC_TELEMETRY='0',
               PATH=str(ROOT/'tooling/ci/node_modules/.bin')+os.pathsep+os.environ['PATH'])
    report = {'status': 'failed', 'steps': [], 'expected_steps': [], 'versions': {},
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    result = 1
    def interrupted(signum, frame):
        raise SystemExit(128+signum)
    signal.signal(signal.SIGTERM, interrupted)
    try:
        plan = json.loads((ROOT/'tooling/ci/plan.json').read_text())
        validate_plan(plan)
        report['expected_steps'] = [s['id'] for s in plan['steps']]
        report['versions'] = versions(env)
        pin = json.loads((ROOT/'tooling/ci/tools.json').read_text())
        for name in ('python', 'node', 'npm', 'openspec', 'docker', 'compose'):
            value = report['versions'][name].removeprefix('Python ').removeprefix('v').split('+')[0]
            if value != pin[name]:
                raise ValueError(f'{name}: expected {pin[name]}, observed {value}')
        revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, capture_output=True)
        report['revision'] = revision.stdout.strip() if revision.returncode == 0 else 'sin commit'
        # File allowlist excludes private datasets, environments, caches and secret files.
        paths = [p for folder in ('scripts', 'tests', 'contracts', 'services', 'frontend', 'tooling/ci', 'openspec', 'infra', 'ml/manifests')
                 for p in (ROOT/folder).rglob('*') if p.is_file() and not any(x in p.parts for x in ('node_modules', '.venv', '__pycache__', 'dist', 'bin'))]
        paths += [ROOT/'docker-compose.yml', ROOT/'.github/workflows/application-ci.yml']
        report['sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}
        for step in plan['steps']:
            print('CI '+step['id']+'...', flush=True)
            started = time.monotonic()
            code, output = execute(step['command'], step['timeout_seconds'], env)
            (directory/(step['id']+'.log')).write_text(redact(output))
            report['steps'].append({'id': step['id'], 'exit_code': code, 'duration_seconds': round(time.monotonic()-started, 3)})
            if code:
                print(redact(output[-5000:]), flush=True)
                print('FAIL '+step['id']+' exit='+str(code)+'; report='+str(directory), flush=True)
                break
        if len(report['steps']) == len(plan['steps']) and all(s['exit_code'] == 0 for s in report['steps']):
            result = 0
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        report['error'] = redact(str(error))
        print('CI failed: '+type(error).__name__, flush=True)
    finally:
        try:
            cleanup(directory)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            report['cleanup_error'] = type(error).__name__
            result = 1
        report['status'] = 'passed' if result == 0 else 'failed'
        (directory/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(report['status'].upper()+' CI; artifacts='+str(directory), flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
