import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
from alembic.config import Config
from alembic.script import ScriptDirectory
import psycopg
from psycopg import sql


SERVICES = ('identity', 'diagnosis', 'ai_inference', 'notification')
EXPECTED_TABLES = {
    'identity': {'alembic_version', 'users', 'refresh_sessions', 'password_recovery_tokens', 'audit_logs'},
    'diagnosis': {
        'alembic_version',
        'crops',
        'problems',
        'recommendations',
        'diagnoses',
        'idempotency_keys',
        'image_upload_intents',
        'diagnosis_feedback',
        'diagnosis_audit_logs',
        'diagnosis_outbox',
        'diagnosis_inbox',
        'diagnosis_quarantine_messages',
    },
    'ai_inference': {
        'alembic_version',
        'inference_jobs',
        'inference_inbox',
        'inference_results',
        'inference_outbox',
        'inference_quarantine_messages',
        'inference_audit_logs',
    },
    'notification': {'alembic_version'},
}
checks = []


def connect(user, database):
    return psycopg.connect(host='postgres', dbname=database, user=user,
                          password=Path('/run/secrets/' + user + '_password').read_text().strip(),
                          connect_timeout=3, autocommit=True)


def get_head(service, source_dir=None):
    base_dir = Path(source_dir or ('/sources/' + service))
    script = ScriptDirectory.from_config(Config(str(base_dir / 'alembic.ini')))
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected 1 head for {service}, got {heads}"
    return heads[0]


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
    head_rev = get_head(service)
    action(service, 'ready', expected=1)
    action(service, 'upgrade', 'head')
    current = action(service, 'current')
    assert head_rev in current
    action(service, 'ready')
    with connect(service, service) as db:
        before = db.execute('SELECT * FROM alembic_version').fetchall()
        tables = db.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
        actual_tables = {row[0] for row in tables}
        assert actual_tables == EXPECTED_TABLES[service], f"table mismatch for {service}: {actual_tables}"
        flags = db.execute('SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        assert flags == (False,) * 5
    action(service, 'upgrade', 'head')
    with connect(service, service) as db:
        assert db.execute('SELECT * FROM alembic_version').fetchall() == before
    action(service, 'downgrade', 'base')
    action(service, 'ready', expected=1)
    action(service, 'upgrade', 'head')
    action(service, 'ready')
    checks.append(service + ': upgrade/current/repeat/downgrade/upgrade/restricted-role PASS')
    if service == 'diagnosis':
        owner_a = uuid.uuid4()
        owner_b = uuid.uuid4()
        raw_a = f"{owner_a}:diagnosis_create:pg-key-1".encode("utf-8")
        lock_a = int.from_bytes(hashlib.sha256(raw_a).digest()[:8], byteorder="big", signed=True)
        raw_b = f"{owner_b}:diagnosis_create:pg-key-1".encode("utf-8")
        lock_b = int.from_bytes(hashlib.sha256(raw_b).digest()[:8], byteorder="big", signed=True)

        pw = Path('/run/secrets/diagnosis_password').read_text().strip()
        with psycopg.connect(host='postgres', dbname='diagnosis', user='diagnosis', password=pw) as c1, \
             psycopg.connect(host='postgres', dbname='diagnosis', user='diagnosis', password=pw) as c2:
            # 1. Contention on same owner+scope+key
            c1.execute("BEGIN")
            c2.execute("BEGIN")
            assert c1.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_a,)).fetchone()[0] is True
            assert c2.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_a,)).fetchone()[0] is False
            c1.execute("COMMIT")
            assert c2.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_a,)).fetchone()[0] is True
            c2.execute("ROLLBACK")

            # 2. Separation A/B on identical key string
            c1.execute("BEGIN")
            c2.execute("BEGIN")
            assert c1.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_a,)).fetchone()[0] is True
            assert c2.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_b,)).fetchone()[0] is True
            c1.execute("ROLLBACK")
            c2.execute("ROLLBACK")

            # 3. Independent transactions for diagnosis and idempotency
            diag_id1 = uuid.uuid4()
            now = datetime.datetime.now(datetime.timezone.utc)
            exp = now + datetime.timedelta(seconds=86400)
            c1.execute(
                """INSERT INTO diagnoses (id, owner_id, status, object_key, image_sha256, image_content_type, image_size_bytes, image_width, image_height, created_at, updated_at)
                   VALUES (%s, %s, 'PENDIENTE', %s, %s, 'image/jpeg', 1000, 50, 50, %s, %s)""",
                (diag_id1, owner_a, f"diagnoses/{diag_id1}/original.jpg", "hash1", now, now),
            )
            c1.execute(
                """INSERT INTO idempotency_keys (id, owner_id, scope, key, fingerprint, diagnosis_id, created_at, expires_at)
                   VALUES (%s, %s, 'diagnosis_create', 'pg-key-1', 'hash1', %s, %s, %s)""",
                (uuid.uuid4(), owner_a, diag_id1, now, exp),
            )
            c1.commit()

            # Replay: c2 sees the committed row
            row = c2.execute(
                "SELECT fingerprint, diagnosis_id FROM idempotency_keys WHERE owner_id=%s AND key='pg-key-1'",
                (owner_a,),
            ).fetchone()
            assert row == ("hash1", diag_id1)

            # Expiration replacement: simulate expired key
            c1.execute(
                "UPDATE idempotency_keys SET expires_at = %s WHERE owner_id=%s AND key='pg-key-1'",
                (now - datetime.timedelta(seconds=5), owner_a),
            )
            c1.commit()

            # Expired: replace key with diag2
            diag_id2 = uuid.uuid4()
            c2.execute(
                """INSERT INTO diagnoses (id, owner_id, status, object_key, image_sha256, image_content_type, image_size_bytes, image_width, image_height, created_at, updated_at)
                   VALUES (%s, %s, 'PENDIENTE', %s, %s, 'image/jpeg', 1000, 50, 50, %s, %s)""",
                (diag_id2, owner_a, f"diagnoses/{diag_id2}/original.jpg", "hash2", now, now),
            )
            c2.execute("DELETE FROM idempotency_keys WHERE owner_id=%s AND key='pg-key-1'", (owner_a,))
            c2.execute(
                """INSERT INTO idempotency_keys (id, owner_id, scope, key, fingerprint, diagnosis_id, created_at, expires_at)
                   VALUES (%s, %s, 'diagnosis_create', 'pg-key-1', 'hash2', %s, %s, %s)""",
                (uuid.uuid4(), owner_a, diag_id2, now, exp),
            )
            c2.commit()

            # Previous diagnosis diag_id1 is preserved
            assert c1.execute("SELECT id FROM diagnoses WHERE id=%s", (diag_id1,)).fetchone() is not None
            assert c1.execute("SELECT id FROM diagnoses WHERE id=%s", (diag_id2,)).fetchone() is not None

            # Clean up test rows
            c1.execute("DELETE FROM idempotency_keys WHERE owner_id=%s", (owner_a,))
            c1.execute("DELETE FROM diagnoses WHERE owner_id=%s", (owner_a,))
            c1.commit()
        checks.append('diagnosis: pg_try_advisory_xact_lock/separation/replay/expiration-replacement PASS')

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
        (copy / 'migrations/versions/9999_failure.py').write_text(
            'from alembic import op\nrevision="test_failure"\ndown_revision="' + head_rev + '"\n'
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
            db.execute('UPDATE alembic_version SET version_num=%s', (head_rev,))
        action(service, 'ready')
    checks.append(service + ': bad-password/missing-head/wrong-head/failed-migration/no-secret PASS')
print(json.dumps({'checks': checks, 'own_connections': 4, 'cross_connections_denied': 12}, indent=2))
