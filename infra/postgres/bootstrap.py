"""Idempotent privileged bootstrap, never imported or mounted in application APIs."""
import os
from pathlib import Path
import psycopg
from psycopg import sql

SERVICES = ('identity', 'diagnosis', 'ai_inference', 'notification')


def password(name):
    value = Path('/run/secrets/' + name).read_text().strip()
    if not value:
        raise ValueError('Empty secret')
    return value


def connect(db='postgres'):
    return psycopg.connect(host=os.environ.get('DB_HOST', 'postgres'), dbname=db,
                          user='postgres', password=password('postgres_password'),
                          connect_timeout=3, autocommit=True)


def main():
    try:
        with connect() as conn:
            # One bootstrap at a time; CREATE DATABASE cannot run inside a transaction.
            conn.execute('SELECT pg_advisory_lock(830003)')
            for service in SERVICES:
                if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (service,)).fetchone():
                    conn.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(service)))
                conn.execute(sql.SQL('ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}').format(sql.Identifier(service), sql.Literal(password(service + '_password'))))
                if conn.execute('SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=%s', (service,)).fetchone():
                    raise ValueError('Unexpected role membership; review manually')
                owner = conn.execute('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s', (service,)).fetchone()
                if owner is None:
                    conn.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(service), sql.Identifier(service)))
                elif owner[0] != service:
                    raise ValueError('Unexpected database owner; do not take over existing data')
                conn.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC').format(sql.Identifier(service)))
                for other in SERVICES:
                    if other != service and conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (other,)).fetchone():
                        conn.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM {}').format(sql.Identifier(service), sql.Identifier(other)))
                conn.execute(sql.SQL('GRANT CONNECT, CREATE, TEMPORARY ON DATABASE {} TO {}').format(sql.Identifier(service), sql.Identifier(service)))
            for database in ('postgres', 'template1'):
                conn.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM PUBLIC').format(sql.Identifier(database)))
            for service in SERVICES:
                with connect(service) as db:
                    db.execute('REVOKE ALL ON SCHEMA public FROM PUBLIC')
                    db.execute(sql.SQL('GRANT USAGE, CREATE ON SCHEMA public TO {}').format(sql.Identifier(service)))
        print('bootstrap_ok: four private databases and restricted roles')
        return 0
    except Exception:
        print('bootstrap_failed: review configuration and ownership; no secrets logged')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
