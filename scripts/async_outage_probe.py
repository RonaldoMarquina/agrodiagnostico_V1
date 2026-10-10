"""Acceptance-only probe, run with the orchestrator's isolated Compose secrets."""
import json
from pathlib import Path
import sys
import time
import uuid

import jwt
import psycopg

from check_async_acceptance import request_json, create_jpeg_bytes, encode_multipart_form


def main():
    secrets = Path('/test_secrets')
    password = (secrets / 'diagnosis_password').read_text().strip()
    def query(sql, args=()):
        with psycopg.connect(host='postgres', user='diagnosis', dbname='diagnosis', password=password) as db:
            return db.execute(sql, args).fetchone()
    if len(sys.argv) > 1:
        diagnosis_id = sys.argv[1]
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            row = query('SELECT status FROM diagnoses WHERE id=%s', (diagnosis_id,))
            if row and row[0] == 'NO_CONCLUYENTE':
                assert query("SELECT count(*) FROM diagnosis_outbox WHERE diagnosis_id=%s AND event_type='DiagnosisFinished'", (diagnosis_id,))[0] == 1
                print('Broker restored: pending request reached one terminal result')
                return
            time.sleep(0.5)
        raise AssertionError('Pending work did not recover after broker restart')
    now = int(time.time())
    token = jwt.encode({'sub': str(uuid.uuid4()), 'role': 'USER', 'iss': 'agrodiagnostico-identity',
                        'aud': 'agrodiagnostico-api', 'jti': str(uuid.uuid4()), 'iat': now, 'exp': now+600},
                       (secrets/'jwt_private_key.pem').read_text(), algorithm='EdDSA')
    assert request_json('http://diagnosis:8000/health/ready')[0] == 200
    body, content_type = encode_multipart_form('image', 'outage.jpg', create_jpeg_bytes(width=201))
    status, response, _ = request_json('http://nginx:8080/api/v1/diagnoses', 'POST', body,
        {'Authorization': f'Bearer {token}', 'Idempotency-Key': str(uuid.uuid4()), 'Content-Type': content_type})
    assert status == 202, (status, response)
    diagnosis_id = response['id']
    assert query('SELECT status FROM diagnoses WHERE id=%s', (diagnosis_id,))[0] == 'PENDIENTE'
    assert query('SELECT count(*) FROM diagnosis_outbox WHERE diagnosis_id=%s AND sent_at IS NULL', (diagnosis_id,))[0] == 1
    print('OUTAGE_DIAG=' + diagnosis_id)


if __name__ == '__main__':
    main()
