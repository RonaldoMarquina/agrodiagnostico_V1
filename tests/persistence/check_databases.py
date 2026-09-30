"""Runs only in the disposable acceptance project, with explicit test credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import psycopg
from psycopg import sql

SERVICES = ('identity', 'diagnosis', 'ai_inference', 'notification')
checks = []


def connect(user, database):
    return psycopg.connect(host='postgres', dbname=database, user=user,
                          password=Path('/run/secrets/' + user + '_password').read_text().strip(),
                          connect_timeout=3, autocommit=True)


def action(service, *args, source=None, secret=None, expected=0):
    env = {**os.environ, 'DB_HOST': 'postgres',
           'DB_PASSWORD_FILE': secret or '/run/secrets/' + service + '_password'}
    run = subprocess.run(['python', '-m', 'app.migrate', *args],
                         cwd=source or '/sources/' + service, env=env,
                         capture_output=True, text=True, timeout=20)
    for p in Path('/run/secrets').iterdir():
        assert p.read_text().strip() not in run.stdout + run.stderr, 'credential leaked'
    if secret:
        assert Path(secret).read_text().strip() not in run.stdout + run.stderr, 'test credential leaked'
    assert run.returncode == expected, (service, args, run.returncode, 'unexpected exit')
    return run.stdout


for service in SERVICES:
    action(service, 'ready', expected=1)
    action(service, 'upgrade', 'head')
    current = action(service, 'current')
    assert service + '_0001' in current
    action(service, 'ready')
    with connect(service, service) as db:
        before = db.execute('SELECT * FROM alembic_version').fetchall()
        tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
        assert tables == [('alembic_version',)], 'domain table present'
        flags = db.execute('SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        assert flags == (False,) * 5
    action(service, 'upgrade', 'head')
    with connect(service, service) as db:
        assert db.execute('SELECT * FROM alembic_version').fetchall() == before
    action(service, 'downgrade', 'base')
    action(service, 'ready', expected=1)
    action(service, 'upgrade', 'head')
    action(service, 'ready')
    checks.append(service + ': upgrade/current/repeat/downgrade/upgrade/no-domain/restricted-role PASS')
    for target in SERVICES:
        try:
            with connect(service, target) as db:
                db.execute('SELECT * FROM alembic_version').fetchall()
        except psycopg.OperationalError as exc:
            assert service != target
            # Permission denial, not a network failure or wrong credential.
            assert exc.sqlstate == '42501' or 'permission denied for database' in str(exc)
        else:
            assert service == target, 'cross-service connection permitted'
    with tempfile.TemporaryDirectory() as tmp:
        wrong = Path(tmp) / 'wrong-password'
        wrong.write_text('SYNTHETIC_INVALID_PASSWORD_DO_NOT_LOG_83')
        action(service, 'upgrade', 'head', secret=str(wrong), expected=1)
        action(service, 'ready', secret=str(wrong), expected=1)
        copy = Path(tmp) / 'service'
        shutil.copytree('/sources/' + service, copy, ignore=shutil.ignore_patterns('.venv', '__pycache__'))
        (copy / 'migrations/versions/0002_failure.py').write_text(
            'from alembic import op\nrevision="test_failure"\ndown_revision="' + service + '_0001"\n'
            'def upgrade():\n    op.execute("SELECT 1/0")\n'
            'def downgrade():\n    pass\n')
        action(service, 'upgrade', 'head', source=str(copy), expected=1)
        action(service, 'ready', source=str(copy), expected=1)
        with connect(service, service) as db:
            assert db.execute('SELECT * FROM alembic_version').fetchall() == before
        # Unknown/wrong head must fail even though the database is reachable.
        with connect(service, service) as db:
            db.execute("UPDATE alembic_version SET version_num='unknown_revision'")
        action(service, 'ready', expected=1)
        with connect(service, service) as db:
            db.execute('UPDATE alembic_version SET version_num=%s', (service + '_0001',))
        action(service, 'ready')
    checks.append(service + ': bad-password/missing-head/wrong-head/failed-migration/no-secret PASS')
print(json.dumps({'checks': checks, 'own_connections': 4, 'cross_connections_denied': 12}, indent=2))
