#!/usr/bin/env python3
"""Acceptance checks for developer tools; no application services are started."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True, help='New JSON report; existing files are never overwritten')
parser.add_argument('--with-torch', action='store_true', help='Download CPU-only PyTorch into a temporary venv')
args = parser.parse_args()
output = Path(args.output).resolve()
if output.exists():
    parser.error('Output already exists')
root = Path(__file__).resolve().parents[1]
results = []
env = dict(os.environ, OPENSPEC_TELEMETRY='0', DO_NOT_TRACK='1', PIP_DISABLE_PIP_VERSION_CHECK='1', GIT_TERMINAL_PROMPT='0')
def check(name, command, cwd=root, timeout=120):
    print(name, flush=True)
    try:
        proc = subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        code, text = proc.returncode, proc.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        code, text = -1, str(exc)
    results.append(dict(name=name, command=shlex.join(command), cwd=str(cwd), exit_code=code, status='LISTO' if code == 0 else 'BLOQUEADO', output=text))
    print(text[-2500:], flush=True)
    return code == 0

for name, command in [
    ('OS', ['cat','/etc/os-release']),
    ('Kernel', ['uname','-a']),
    ('Disk', ['df','-h','.']),
    ('RAM', ['free','-h']),
    ('CPU', ['lscpu']),
    ('Git', ['git','--version']),
    ('Compiler', ['gcc','--version']),
    ('C++ compiler', ['g++','--version']),
    ('Make', ['make','--version']),
    ('Git repository', ['git','rev-parse','--show-toplevel']),
    ('Python', ['python3','--version']),
    ('Node', ['node','-p','JSON.stringify({version:process.version,lts:process.release.lts})']),
    ('npm', ['npm','--version']),
    ('Docker daemon', ['docker','version']),
    ('Docker startup', ['systemctl','is-enabled','docker']),
    ('Docker active', ['systemctl','is-active','docker']),
    ('Compose', ['docker','compose','version']),
    ('Docker smoke', ['docker','run','--rm','--network','none','hello-world@sha256:5e23090353324d887c48ad5e5c56d294eab81588df9605b07d1afe895f9cc8f8']),
    ('Docker image digest', ['docker','image','inspect','hello-world@sha256:5e23090353324d887c48ad5e5c56d294eab81588df9605b07d1afe895f9cc8f8','--format','{{json .RepoDigests}}']),
    ('OpenSpec version', ['openspec','--version']),
    ('OpenSpec changes', ['openspec','list','--json']),
    ('OpenSpec specs', ['openspec','list','--specs','--json']),
    ('OpenSpec doctor', ['openspec','doctor','--json']),
    ('OpenSpec schema', ['openspec','schema','validate','spec-driven']),
    ('OpenSpec templates', ['openspec','templates','--json']),
    ('OpenSpec artifacts', ['openspec','validate','--all','--strict','--no-interactive','--json']),
    ('GPU PCI', ['lspci','-nnk']),
]:
    check(name, command)
check('Project Compose', ['docker','compose','config','--quiet'])
with tempfile.TemporaryDirectory(prefix='agro-acceptance-') as temp:
    tmp = Path(temp)
    py = str(tmp / 'venv/bin/python')
    if check('Python venv', ['python3','-m','venv',str(tmp/'venv')]):
        if check('Python package install', [py,'-m','pip','install','--index-url','https://pypi.org/simple','packaging==25.0','PyYAML==6.0.3'], timeout=180):
            check('Python import', [py,'-c',"import packaging; from packaging.version import Version; assert Version('1.2') < Version('2.0'); print(packaging.__version__)"])
            check('OpenSpec config YAML', [py,'-c',"import yaml; from pathlib import Path; c=yaml.safe_load(Path('openspec/config.yaml').read_text()); assert c['schema']=='spec-driven'; assert isinstance(c['context'],str); print('Valid YAML; spec-driven; context present')"])
        if args.with_torch:
            if check('PyTorch CPU install', [py,'-m','pip','install','--index-url','https://download.pytorch.org/whl/cpu','torch==2.9.1+cpu'], timeout=600):
                check('PyTorch CPU tensor and autograd', [py,'-c',"import torch; x=torch.tensor([2.0],requires_grad=True); (x*x).sum().backward(); assert x.grad.item()==4.0; assert x.device.type=='cpu'; print({'torch':torch.__version__,'device':str(x.device),'gradient':x.grad.item(),'hip':torch.version.hip})"])
                check('Temporary Python dependencies', [py,'-m','pip','freeze'])
    # Use a file to avoid shell quoting differences in npm scripts.
    (tmp/'check.cjs').write_text("require('node:assert/strict').equal(2 + 2, 4); console.log('Node/npm OK');")
    (tmp/'package.json').write_text(json.dumps({'private':True,'scripts':{'check':'node check.cjs'}}))
    check('npm execution', ['npm','run','check'], cwd=tmp)
    check('npm registry', ['npm','view','@fission-ai/openspec@1.13.2','version','engines','--json','--registry=https://registry.npmjs.org'], cwd=tmp)
    compose = tmp/'compose.yaml'
    compose.write_text('services:\n  smoke:\n    image: hello-world@sha256:5e23090353324d887c48ad5e5c56d294eab81588df9605b07d1afe895f9cc8f8\n    network_mode: none\n')
    check('Compose smoke', ['docker','compose','-p','agro-env-'+str(os.getpid()),'-f',str(compose),'run','--rm','--no-deps','smoke'])
for item in results:
    if item['name']=='OpenSpec artifacts' and item['exit_code']==0 and json.loads(item['output'])['summary']['totals']['items']==0:
        item['status']='PENDIENTE DE IMPLEMENTACIÓN'
    if item['name']=='Project Compose' and (root/'docker-compose.yml').read_text().strip()=='name: agrodiagnostico-v1\nservices: {}':
        item['status']='PENDIENTE DE IMPLEMENTACIÓN'
    if item['name']=='OpenSpec artifacts' and ('No items' in item['output'] or 'No changes' in item['output']):
        item['status']='PENDIENTE DE IMPLEMENTACIÓN'
results.extend([
    {'name':'Frontend, microservices, contracts, migrations, tests and application CI','status':'PENDIENTE DE IMPLEMENTACIÓN','output':'Only scaffolding exists; no build or application tests executed.'},
    {'name':'PostgreSQL, RabbitMQ, Redis, S3 and Nginx','status':'PENDIENTE DE IMPLEMENTACIÓN','output':'Project Compose services are empty; no service readiness claimed.'},
    {'name':'Public domain, Cloudflare, TLS and CDN','status':'PENDIENTE DE IMPLEMENTACIÓN','output':'Verify when public deployment exists; no external service configured.'},
])
report = {'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'root':str(root),'checks':results}
with output.open('x') as stream:
    json.dump(report,stream,indent=2,ensure_ascii=False)
print('Report:',output)
raise SystemExit(1 if any(r['status']=='BLOQUEADO' for r in results) else 0)
