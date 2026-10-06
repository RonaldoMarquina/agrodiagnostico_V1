#!/usr/bin/env python3
"""Identity acceptance on disposable PostgreSQL, three processes and Nginx.

Only containers/network created by this invocation are removed. Never reads
DB_HOST, development credentials or existing databases. No tokens are printed.
"""
import concurrent.futures
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from prepare_identity_keys import prepare

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://identity-test.example'
PASSWORD = 'SyntheticPassword123!'


def run(args, *, data=None, expected=0, env=None):
    process_env = {**os.environ, 'APP_ENV': 'local', 'HTTP_PORT': '8080',
                   'S3_BUCKET': 'agro-local', 'S3_REGION': 'us-east-1',
                   'PERSISTENCE_SECRETS_DIR': '/tmp', **(env or {})}
    result = subprocess.run(args, input=data, env=process_env, capture_output=True, text=True, timeout=180)
    if result.returncode != expected:
        err = (result.stderr or result.stdout or '')[-500:].strip()
        raise RuntimeError(f'Acceptance subprocess failed: {args[0]} exit={result.returncode}; err={err}')
    return result.stdout.strip()


def request(port, path, *, method='GET', payload=None, headers=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(f'http://127.0.0.1:{port}'+path, data=body, method=method,
                                 headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        data = response.read()
        cookies = SimpleCookie()
        for value in response.headers.get_all('Set-Cookie', []):
            cookies.load(value)
        return response.status, json.loads(data) if data else None, cookies, response.headers


def main():
    def interrupted(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, interrupted)
    tag = 'agro-identity-check-'+uuid.uuid4().hex[:10]
    network = tag+'-net'
    containers = []
    checks = []
    # Resolve pinned project images directly from canonical Dockerfiles and Compose, avoiding missing-env interpolation.
    import re
    dc_text = (ROOT/'docker-compose.yml').read_text()
    postgres_match = re.search(r'image:\s*(postgres:[^\s]+)', dc_text)
    postgres_image = postgres_match.group(1) if postgres_match else 'postgres:16-alpine@sha256:3c5c8892d184f738f4fe282d14ddaa613a38f00f4189d2d94725ebe6f2909ddb'
    dockerfile = (ROOT/'infra/docker/frontend.Dockerfile').read_text()
    proxy_image = re.findall(r'FROM (nginx:[^\s]+)', dockerfile)[0]
    image = tag+'-image'
    built = False
    try:
        print('Building isolated Identity acceptance image...', flush=True)
        run(['docker', 'build', '-q', '-f', str(ROOT/'services/identity/Dockerfile'), '-t', image, str(ROOT)])
        built = True
        run(['docker', 'network', 'create', network])
        with tempfile.TemporaryDirectory(prefix=tag+'-') as tmp:
            directory = Path(tmp)
            directory.chmod(0o755)  # Only synthetic credentials in this disposable directory.
            prepare(directory)
            private_before = (directory/'jwt_private_key.pem').read_bytes()
            prepare(directory)
            assert private_before == (directory/'jwt_private_key.pem').read_bytes()
            db_password = directory/'db_password'
            db_password.write_text(secrets.token_urlsafe(32)); db_password.chmod(0o644)
            for name in ['jwt_private_key.pem', 'jwt_public_key.pem']:
                (directory/name).chmod(0o644)
            pg = tag+'-pg'; containers.append(pg)
            run(['docker', 'run', '-d', '--name', pg, '--network', network,
                 '--network-alias', 'postgres', '--mount', f'type=bind,src={directory},dst=/secrets,readonly',
                 '-e', 'POSTGRES_USER=postgres', '-e', 'POSTGRES_DB=postgres',
                 '-e', 'POSTGRES_PASSWORD_FILE=/secrets/db_password', postgres_image])
            for _ in range(60):
                probe = subprocess.run(['docker', 'exec', pg, 'pg_isready', '-U', 'postgres'], capture_output=True)
                if probe.returncode == 0:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError('Disposable PostgreSQL not ready')

            # Dedicated application role has no superuser/database/role creation rights.
            password = db_password.read_text()
            run(['docker','exec','-i',pg,'psql','-U','postgres','-v','ON_ERROR_STOP=1'],
                data=f"CREATE ROLE identity LOGIN PASSWORD '{password}'; CREATE DATABASE identity OWNER identity;")
            print('Disposable PostgreSQL ready; migrating and starting three instances...', flush=True)

            common = ['--network', network, '--mount', f'type=bind,src={directory},dst=/secrets,readonly',
                      '-e', 'APP_ENV=local', '-e', 'DB_HOST=postgres', '-e', 'DB_PASSWORD_FILE=/secrets/db_password',
                      '-e', 'JWT_PRIVATE_KEY_PATH=/secrets/jwt_private_key.pem',
                      '-e', 'JWT_PUBLIC_KEY_PATH=/secrets/jwt_public_key.pem', '-e', 'ALLOWED_ORIGINS='+ORIGIN]

            def migrate(*args):
                # Explicitly named so cleanup also covers interrupted one-shot containers.
                name = tag+'-migration'
                if name not in containers:
                    containers.append(name)
                return run(['docker', 'run', '--rm', '--name', name, *common, image, 'python', '-m', 'app.migrate', *args])

            def sql(statement, *, expected=0):
                return run(['docker', 'exec', '-i', pg, 'psql', '-U', 'identity', '-d', 'identity',
                            '-v', 'ON_ERROR_STOP=1', '-At'], data=statement, expected=expected)

            assert sql("SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname='identity'") == 'f'
            # Startup fails closed without a signing key, before opening a listener.
            output = run(['docker','run','--rm',*common,'-e','JWT_PRIVATE_KEY_PATH=',image], expected=1)
            assert 'configuration_invalid: JWT_PRIVATE_KEY_PATH' in output
            # Populate a historical row at revision 0002 without asserting it was complete.
            # Direct Alembic call avoids migrate's head-readiness assertion on an older target.
            run(['docker','run','--rm',*common,image,'python','-c',
                 'from alembic import command; from app.persistence import config; command.upgrade(config(), "identity_0002")'])
            old_id = str(uuid.uuid4())
            sql(f"INSERT INTO audit_logs (id,event_type) VALUES ('{old_id}','HISTORICAL_TEST');")
            migrate('upgrade', 'head')
            assert sql(f"SELECT legacy AND action IS NULL AND correlation_id IS NULL FROM audit_logs WHERE id='{old_id}'") == 't'
            migrate('upgrade', 'head')
            checks.append('migration 0002->0003 preserves historical audit and is repeatable')
            print('PASS '+checks[-1], flush=True)

            ports = []
            for suffix in ['a','b','c']:
                name = tag+'-'+suffix; containers.append(name)
                run(['docker','run','-d','--name',name,'--network-alias','identity-'+suffix,
                     '-p','127.0.0.1::8000',*common,image])
                port = int(run(['docker','port',name,'8000/tcp']).rsplit(':',1)[1]); ports.append(port)
                for _ in range(60):
                    try:
                        if request(port,'/health/ready')[0] == 200:
                            break
                    except (OSError, urllib.error.URLError):
                        pass
                    time.sleep(.5)
                else:
                    raise RuntimeError('Disposable Identity not ready')
            # Exercise the repo's actual proxy locations against a three-server upstream.
            conf = (ROOT/'infra/nginx/default.conf').read_text().replace('server identity:8000;',
                  'server identity-a:8000;\n    server identity-b:8000;\n    server identity-c:8000;').replace(
                  'server diagnosis:8000;', 'server identity-a:8000;')
            (directory/'nginx.conf').write_text(conf)
            proxy = tag+'-proxy'; containers.append(proxy)
            run(['docker','run','-d','--name',proxy,'--network',network,'-p','127.0.0.1::8080',
                 '--mount',f'type=bind,src={directory}/nginx.conf,dst=/etc/nginx/conf.d/default.conf,readonly',proxy_image])
            proxy_port = int(run(['docker','port',proxy,'8080/tcp']).rsplit(':',1)[1])
            last_status = None
            for _ in range(80):
                try:
                    last_status, _, _, _ = request(proxy_port,'/api/v1/profile')
                    if last_status == 401:
                        break
                except (OSError, urllib.error.URLError) as exc:
                    last_status = str(exc)
                time.sleep(.5)
            else:
                raise RuntimeError(f'Disposable proxy not ready; last_status={last_status}')

            email = 'processes@example.com'
            registered = request(proxy_port,'/api/v1/auth/register',method='POST',payload={
                'email':email,'password':PASSWORD,'display_name':'Synthetic'})
            assert registered[0] == 201
            user_id = registered[1]['id']
            assert sql(f"SELECT count(*) FROM audit_logs WHERE action='USER_REGISTERED' AND target_id='{user_id}' AND correlation_id='{registered[3]['X-Correlation-ID']}'") == '1'

            def login(port=ports[0], password=PASSWORD):
                result = request(port,'/api/v1/auth/login',method='POST',headers={'Origin':ORIGIN},
                                 payload={'email':email,'password':password})
                assert result[0] == 200
                return result

            def session_headers(result):
                refresh = result[2]['__Secure-agro_refresh'].value
                csrf = result[1]['csrf_token']
                return {'Origin':ORIGIN,'X-CSRF-Token':csrf,
                        'Cookie':f'__Secure-agro_refresh={refresh}; csrf_token={csrf}'}

            def refresh(port, result):
                return request(port,'/api/v1/auth/refresh',method='POST',headers=session_headers(result))

            first = login(); second = refresh(ports[1], first); assert second[0] == 200
            assert request(ports[2],'/api/v1/auth/logout',method='POST',headers=session_headers(second))[0] == 204
            assert refresh(ports[0],second)[0] == 401
            checks.append('login A / refresh B / logout C and revoked refresh rejected')
            print('PASS '+checks[-1], flush=True)

            first = login()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda p: refresh(p,first), ports[:2]))
            assert sorted(result[0] for result in results) == [200,401]
            winner = next(result for result in results if result[0] == 200)
            assert refresh(ports[2],winner)[0] == 401
            checks.append('concurrent refresh: one winner, reuse revokes full family')
            print('PASS '+checks[-1], flush=True)

            first = login()
            bad = session_headers(first); bad['X-CSRF-Token']='arbitrary'
            bad['Cookie'] = bad['Cookie'].split(';')[0]+'; csrf_token=arbitrary'
            assert request(proxy_port,'/api/v1/auth/refresh',method='POST',headers=bad)[0] == 403
            bad = session_headers(first); bad['Origin']='http://identity-test.example:4444'
            assert request(proxy_port,'/api/v1/auth/refresh',method='POST',headers=bad)[0] == 403
            checks.append('proxy rejects unbound CSRF and different scheme/port Origin')
            print('PASS '+checks[-1], flush=True)

            password2 = 'SyntheticPassword456!'
            assert request(ports[1],'/api/v1/profile/password',method='PUT',
                headers={'Authorization':'Bearer '+first[1]['access_token']},
                payload={'current_password':PASSWORD,'new_password':password2})[0] == 200
            assert refresh(ports[2],first)[0] == 401
            first = login(password=password2)
            # Deliver a synthetic recovery credential via fixture SQL, never an HTTP backdoor.
            # Dispatch itself is exercised by the isolated unit test email adapter.
            recovery = secrets.token_urlsafe(32)
            import hashlib
            digest = hashlib.sha256(recovery.encode()).hexdigest()
            sql(f"INSERT INTO password_recovery_tokens(id,user_id,token_hash,expires_at) VALUES ('{uuid.uuid4()}','{user_id}','{digest}',now()+interval '30 minutes')")
            result = request(ports[1],'/api/v1/auth/password-recovery/confirm',method='POST',
                             payload={'token':recovery,'new_password':PASSWORD})
            assert result[0] == 200 and refresh(ports[2],first)[0] == 401
            assert request(ports[2],'/api/v1/auth/password-recovery/confirm',method='POST',payload={'token':recovery,'new_password':password2})[0] == 400
            checks.append('password change/reset revoke sessions across processes; reset token single-use')
            print('PASS '+checks[-1], flush=True)

            # Provision via actual CLI in the disposable DB, passing secret only on stdin.
            run(['docker','exec','-i',tag+'-a','python','-c',
                 'import sys; from app.cli import create_initial_admin; raise SystemExit(create_initial_admin("admin@example.com",sys.stdin.read(),"Admin"))'],data=PASSWORD)
            admin=request(ports[0],'/api/v1/auth/login',method='POST',headers={'Origin':ORIGIN},payload={'email':'admin@example.com','password':PASSWORD})
            assert admin[0] == 200
            first=login()
            assert request(proxy_port,'/api/v1/admin/users',headers={'Authorization':'Bearer '+first[1]['access_token']})[0]==403
            assert request(proxy_port,'/api/v1/admin/users',headers={'Authorization':'Bearer '+admin[1]['access_token']})[0]==200
            result=request(ports[1],f'/api/v1/admin/users/{user_id}/block',method='PATCH',headers={'Authorization':'Bearer '+admin[1]['access_token']})
            assert result[0]==200 and refresh(ports[2],first)[0]==401
            assert request(ports[0],'/api/v1/auth/login',method='POST',headers={'Origin':ORIGIN},payload={'email':email,'password':PASSWORD})[0]==401
            checks.append('ADMIN block revokes sessions; blocked login 401; proxy RBAC')
            print('PASS '+checks[-1], flush=True)

            assert sql("SELECT count(*) FROM audit_logs WHERE NOT legacy AND (action IS NULL OR correlation_id IS NULL)")=='0'
            sql("UPDATE audit_logs SET event_type='CHANGED'", expected=3)
            sql('DELETE FROM audit_logs',expected=3)
            sql("INSERT INTO audit_logs(id,event_type) VALUES (gen_random_uuid(),'MISSING_CONTEXT')",expected=3)
            actions=set(sql('SELECT DISTINCT action FROM audit_logs WHERE NOT legacy').splitlines())
            assert {'USER_REGISTERED','LOGIN_SUCCESS','LOGIN_FAILED','LOGOUT','PASSWORD_CHANGED','PASSWORD_RECOVERY_CONFIRMED','USER_BLOCKED','INITIAL_ADMIN_PROVISIONED','REFRESH_TOKEN_REUSE_DETECTED'} <= actions
            checks.append('audit normative context/events and PostgreSQL append-only enforced')
            print('PASS '+checks[-1], flush=True)
            print(f'PASS identity integration: {len(checks)} checks, 3 independent processes, disposable PostgreSQL/Nginx',flush=True)
    except Exception:
        import traceback
        traceback.print_exc()
        raise
    finally:
        for name in reversed(containers):
            subprocess.run(['docker','rm','-fv',name],capture_output=True)
        subprocess.run(['docker','network','rm',network],capture_output=True)
        if built:
            subprocess.run(['docker','image','rm',image],capture_output=True)


if __name__=='__main__':
    main()
