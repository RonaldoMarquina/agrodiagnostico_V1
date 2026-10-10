"""Acceptance fault injection around actual RabbitMQ publisher confirmations."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import jwt
import pika
from sqlalchemy import select

from check_async_acceptance import request_json, create_jpeg_bytes, encode_multipart_form
from app.domain.models import Diagnosis, DiagnosisOutbox
from app.infrastructure.outbox import claim_outbox_batch, DiagnosisOutboxPublisher
from app.persistence import get_sessionmaker

SECRETS = Path('/test_secrets')


def main():
    maker = get_sessionmaker()
    if len(sys.argv)>1 and sys.argv[1] == 'child':
        stage, diagnosis_id = sys.argv[2:]
        connection = pika.BlockingConnection(pika.ConnectionParameters(host='rabbitmq', credentials=pika.PlainCredentials(
            'rabbit_diagnosis', (SECRETS/'rabbit_diagnosis_password').read_text().strip())))
        channel = connection.channel()
        publish = channel.basic_publish
        def crash_publish(**kwargs):
            if stage == 'before_confirm':
                os._exit(73)
            publish(**kwargs)
            os._exit(73)
        channel.basic_publish = crash_publish
        with maker() as db:
            token, items = claim_outbox_batch(db, batch_size=100)
            selected = [item for item in items if str(item.diagnosis_id) == diagnosis_id]
            assert len(selected) == 1
            DiagnosisOutboxPublisher().publish_batch(db, selected, token, channel=channel)
        raise AssertionError('Publisher crash point was not reached')
    if len(sys.argv)>1 and sys.argv[1] == 'verify':
        for diagnosis_id in json.loads(Path('/test_state/publishers.json').read_text()):
            deadline = time.monotonic()+100
            while time.monotonic()<deadline:
                with maker() as db:
                    diag = db.get(Diagnosis, uuid.UUID(diagnosis_id))
                    events = db.scalars(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diag.id)).all()
                    if diag.status == 'NO_CONCLUYENTE' and all(e.sent_at for e in events):
                        assert len([e for e in events if e.event_type == 'DiagnosisFinished']) == 1
                        break
                time.sleep(.5)
            else:
                raise AssertionError('Publisher crash failed to recover')
        print('Publisher crashes before/after confirm recovered with one Finished per diagnosis')
        return
    now = int(time.time())
    auth = jwt.encode({'sub': str(uuid.uuid4()), 'role': 'USER', 'iss': 'agrodiagnostico-identity',
                      'aud': 'agrodiagnostico-api', 'jti': str(uuid.uuid4()), 'iat': now, 'exp': now+600},
                     (SECRETS/'jwt_private_key.pem').read_text(), algorithm='EdDSA')
    identifiers = []
    for stage in ('before_confirm', 'after_confirm_before_sent_commit'):
        body, content_type = encode_multipart_form('image', 'publisher.jpg', create_jpeg_bytes(width=201))
        code, response, _ = request_json('http://nginx:8080/api/v1/diagnoses', 'POST', body,
            {'Authorization': 'Bearer '+auth, 'Idempotency-Key': str(uuid.uuid4()), 'Content-Type': content_type})
        assert code == 202
        diagnosis_id = response['id']
        result = subprocess.run([sys.executable, __file__, 'child', stage, diagnosis_id], timeout=30)
        assert result.returncode == 73, (stage, result.returncode)
        with maker() as db:
            row = db.scalar(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == uuid.UUID(diagnosis_id), DiagnosisOutbox.event_type == 'DiagnosisRequested'))
            assert row.sent_at is None, 'Uncommitted confirmation must be retried'
        identifiers.append(diagnosis_id)
        print('Publisher process killed at '+stage, flush=True)
    Path('/test_state/publishers.json').write_text(json.dumps(identifiers))


if __name__ == '__main__':
    main()
