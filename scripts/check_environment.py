#!/usr/bin/env python3
"""Run group 4 acceptance in a unique, disposable Compose project."""
import json
from ci_support import ComposeEvidence
import os
import re
from pathlib import Path
import socket
import stat
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
import uuid

ROOT=Path(__file__).resolve().parents[1]
SERVICES=['identity','diagnosis','ai_inference','notification']
project='agro-env-test-'+uuid.uuid4().hex[:12]
started=time.monotonic()


def main():
    evidence = ComposeEvidence(project)
    with tempfile.TemporaryDirectory(prefix='agro-integrated-') as tmp:
        tmp=Path(tmp)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        config=tmp/'config.env'
        config.write_text(f'APP_ENV=local\nHTTP_PORT={port}\nS3_BUCKET=agro-local\nS3_REGION=us-east-1\nPERSISTENCE_SECRETS_DIR={tmp}/secrets\nLOCAL_UID={os.getuid()}\nLOCAL_GID={os.getgid()}\n')
        env={k:v for k,v in os.environ.items() if k not in ['APP_ENV','HTTP_PORT','S3_BUCKET','S3_REGION','PERSISTENCE_SECRETS_DIR','LOCAL_UID','LOCAL_GID']}
        base=['docker','compose','--env-file',str(config),'-p',project,'-f',str(ROOT/'docker-compose.yml')]
        secrets=[]

        def run(args,expected=0,timeout=240):
            r=subprocess.run(args,cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
            output=r.stdout+r.stderr
            evidence.record(output, secrets)
            for secret in secrets:
                if secret in output:
                    raise RuntimeError('Secret in command output (suppressed)')
            if r.returncode!=expected:
                print(output[-6500:],flush=True)
                raise RuntimeError('Unexpected exit '+str(r.returncode)+' for '+args[-1])
            return r.stdout

        def probe(mode):
            print(run(base+['run','--rm','--no-deps','probe','python','tests/check_runtime.py',mode]),flush=True)

        try:
            run(['python3','scripts/prepare_local.py','--directory',str(tmp/'secrets')])
            run(['python3','scripts/prepare_local.py','--directory',str(tmp/'secrets')])
            secret_dir = tmp/'secrets'
            assert stat.S_IMODE(secret_dir.stat().st_mode) == 0o700
            assert stat.S_IMODE((secret_dir/'s3_config.json').stat().st_mode) == 0o644
            assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in secret_dir.iterdir()
                       if p.name != 's3_config.json')
            print('S3 bind secret mode and private host directory PASS', flush=True)
            for p in (tmp/'secrets').iterdir():
                if p.name.endswith('_password') or p.name=='rabbit_cookie':secrets.append(p.read_text().strip())
                elif p.name in ['s3_admin.json','s3_ai.json','s3_diagnosis.json']:
                    secrets.extend(json.loads(p.read_text()).values())
            bad=['docker','compose','--env-file','/dev/null','-p',project,'-f',str(ROOT/'docker-compose.yml'),'config','--quiet']
            # Compose must reject missing required configuration before startup.
            r=subprocess.run(bad,cwd=ROOT,env=env,capture_output=True,text=True)
            assert r.returncode != 0 and ('required' in r.stderr or 'required' in r.stdout)
            run(base+['config','--quiet'])
            print('Required configuration and idempotent preparation PASS',flush=True)
            print('Building locked APIs, frontend and probes...',flush=True)
            run(base+['--profile','test','build'],timeout=900)
            boot=time.monotonic()
            run(base+['up','-d','--wait','--wait-timeout','180'],timeout=240)
            print('Integrated startup PASS seconds='+str(round(time.monotonic()-boot,3)),flush=True)
            # Confirm only proxy published, loopback only, through actual container config.
            ids=run(base+['ps','-q']).split()
            containers=json.loads(run(['docker','inspect',*ids]))
            for c in containers:
                svc=c['Config']['Labels']['com.docker.compose.service']
                bindings=c['HostConfig']['PortBindings'] or {}
                if svc=='nginx':assert bindings=={'8080/tcp':[{'HostIp':'127.0.0.1','HostPort':str(port)}]}
                else:assert not bindings,svc
            page=urllib.request.urlopen(f'http://127.0.0.1:{port}/',timeout=5).read().decode()
            assert '<div id="root">' in page and '/assets/' in page
            assets=re.findall(r'(?:src|href)="(/assets/[^"]+)"',page)
            assert assets
            for asset in assets:
                assert urllib.request.urlopen(f'http://127.0.0.1:{port}'+asset,timeout=5).status==200
            expected_routes = {'/internal/diagnoses/x/claim': 404, '/health/ready': 404,
                               '/ai': 404, '/api/v1/diagnoses': 401}
            for route, expected_status in expected_routes.items():
                try:urllib.request.urlopen(f'http://127.0.0.1:{port}'+route,timeout=5)
                except urllib.error.HTTPError as exc:
                    assert exc.code == expected_status, (route, exc.code, expected_status)
                    if route.startswith('/api/'):
                        assert exc.headers['Cache-Control']=='private, no-store'
                        data=json.loads(exc.read());uuid.UUID(data['correlation_id'])
                else:raise AssertionError('Unexpected published route '+route)
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/auth/login',timeout=5)
            except urllib.error.HTTPError as exc:
                assert exc.code==405, f'Expected 405 for GET /api/v1/auth/login, got {exc.code}'
            print('Loopback-only proxy, static page and rejected routes PASS',flush=True)
            for svc in SERVICES:
                text=run(base+['run','--rm','--no-deps','-e','APP_ENV=',svc],expected=1)
                assert 'configuration_invalid: APP_ENV' in text
            print('Invalid API configuration exits nonzero without secrets PASS',flush=True)
            probe('health')
            for mode in ['revision-empty','revision-wrong']:
                probe(mode);probe('identity');probe('revision-restore')
            probe('health')
            run(base+['stop','postgres'])
            probe('postgres')
            run(base+['up','-d','--wait','--wait-timeout','60','postgres'])
            probe('health')
            run(base+['stop','redis']);probe('health')
            run(base+['up','-d','--wait','redis'])
            run(base+['stop','s3']);probe('s3')
            run(base+['up','-d','--wait','s3'])
            run(base+['run','--rm','--no-deps','s3-bootstrap'])
            probe('health')
            probe('seed')
            run(base+['down'],timeout=180)
            # Recover existing data before any initializer/migration can recreate it.
            run(base+['up','-d','--wait','--wait-timeout','180','postgres','rabbitmq','s3'],timeout=240)
            probe('recover')
            run(base+['up','-d','--wait','--wait-timeout','180'],timeout=240)
            probe('health')
            run(base+['logs','--no-color'])
            print('Degradation/recovery and persistent data PASS; logs contain no credentials',flush=True)
        finally:
            evidence.collect(base, env, secrets)
            run(base+['--profile','test','--profile','persistence-check','down','--volumes','--remove-orphans','--rmi','local'],timeout=180)
            evidence.verify_cleanup()
        print('PASS project='+project+' duration_seconds='+str(round(time.monotonic()-started,3)),flush=True)


if __name__=='__main__':
    main()
