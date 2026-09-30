"""Scoped Compose evidence and cleanup. Never records environment/secret files."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess

PROJECT = re.compile(r'^agro-(?:env|mig)-test-[0-9a-f]{12}$')


def redact(text, secrets=()):
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'(://[^\s:/]+:)[^\s@]+@', r'\1[REDACTED]@', text)
    return text.replace('SYNTHETIC_INVALID_PASSWORD_DO_NOT_LOG_83', '[REDACTED]')


class ComposeEvidence:
    def __init__(self, project):
        if not PROJECT.fullmatch(project):
            raise ValueError('Not an isolated acceptance project')
        self.project = project
        self.directory = Path(os.environ['AGRO_CI_ARTIFACTS']) if os.environ.get('AGRO_CI_ARTIFACTS') else None
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory/(project+'.project.json')).write_text(json.dumps({'project': project})+'\n')
        # Timeout/cancellation must pass through the caller's finally cleanup.
        def interrupted(signum, frame):
            raise SystemExit(128+signum)
        signal.signal(signal.SIGTERM, interrupted)

    def record(self, output, secrets):
        if self.directory:
            with (self.directory/(self.project+'.log')).open('a') as stream:
                stream.write(redact(output, secrets)+'\n')

    def collect(self, base, env, secrets):
        if not self.directory:
            return
        for args in (['ps', '--all'], ['logs', '--no-color', '--tail', '150']):
            try:
                result = subprocess.run(base+args, env=env, capture_output=True, text=True, timeout=25)
                self.record(' '.join(args)+'\n'+result.stdout+result.stderr, secrets)
            except subprocess.TimeoutExpired:
                self.record('Evidence collection timed out: '+args[0], secrets)

    def verify_cleanup(self):
        resources = remaining(self.project)
        if self.directory:
            (self.directory/(self.project+'.cleanup.json')).write_text(json.dumps(resources, indent=2)+'\n')
        if any(resources.values()):
            raise RuntimeError('Acceptance project has residual resources: '+self.project)


def remaining(project):
    if not PROJECT.fullmatch(project):
        raise ValueError('Invalid cleanup project')
    commands = {
        'containers': ['docker', 'ps', '-aq'],
        'volumes': ['docker', 'volume', 'ls', '-q'],
        'networks': ['docker', 'network', 'ls', '-q'],
    }
    result = {kind: subprocess.check_output(cmd+['--filter', 'label=com.docker.compose.project='+project], text=True, timeout=30).split()
              for kind, cmd in commands.items()}
    result['images'] = subprocess.check_output(['docker', 'image', 'ls', '--format', '{{.Repository}}:{{.Tag}}',
                                                '--filter', 'reference='+project+'-*:*'], text=True, timeout=30).split()
    return result


def cleanup(directory):
    """Fallback for always() after an interrupted runner; exact registered labels only."""
    for file in Path(directory).glob('*.project.json'):
        project = json.loads(file.read_text())['project']
        resources = remaining(project)
        for kind, command in [('containers', ['docker', 'rm', '-f']), ('networks', ['docker', 'network', 'rm']), ('volumes', ['docker', 'volume', 'rm']), ('images', ['docker', 'image', 'rm'])]:
            if resources[kind]:
                subprocess.run(command+resources[kind], check=True, capture_output=True, timeout=120)
        result = remaining(project)
        (Path(directory)/(project+'.cleanup.json')).write_text(json.dumps(result, indent=2)+'\n')
        if any(result.values()):
            raise RuntimeError('Cleanup incomplete: '+project)
