"""Kill actual worker subprocesses at transaction boundaries in an isolated acceptance stack."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import httpx
import jwt
import pika
from sqlalchemy import select
from sqlalchemy.orm import Session

from check_async_acceptance import request_json, create_jpeg_bytes, encode_multipart_form
from app.domain.models import InferenceResult, InferenceInbox, InferenceOutbox
from app.infrastructure.auth import InternalTokenSigner
from app.persistence import get_sessionmaker
from app.worker import InferenceWorker

SECRETS = Path('/test_secrets')


def child(stage, diagnosis_id):
    connection = pika.BlockingConnection(pika.ConnectionParameters(host='rabbitmq', credentials=pika.PlainCredentials(
        'rabbit_ai_inference', (SECRETS/'rabbit_ai_inference_password').read_text().strip())))
    channel = connection.channel()
    deadline = time.monotonic()+30
    while time.monotonic() < deadline:
        method, _, body = channel.basic_get('ai_inference.diagnosis-requested.v2', auto_ack=False)
        if method is None:
            connection.sleep(0.2)
            continue
        if json.loads(body)['payload']['diagnosis_id'] != diagnosis_id:
            # Hold unrelated deliveries unacked until this probe exits; closing the
            # connection returns them without a head-of-queue requeue loop.
            continue
        if stage == 'before_claim':
            os._exit(72)
        client = httpx.Client(timeout=10)
        original_post = client.post
        renewals = []
        if stage == 'heartbeat':
            import app.worker as worker_module
            original_infer = worker_module.run_simulated_inference
            def slow_infer(**kwargs):
                time.sleep(22)
                return original_infer(**kwargs)
            worker_module.run_simulated_inference = slow_infer
        def post(url, **kwargs):
            response = original_post(url, **kwargs)
            if url.endswith('/lease/renew'):
                assert response.status_code == 200
                renewals.append(response.json())
            if stage == 'after_claim' and url.endswith('/claim') and response.status_code == 200:
                os._exit(72)
            return response
        client.post = post
        original_commit = Session.commit
        def commit(session):
            result_pending = any(isinstance(item, InferenceResult) for item in session.new)
            if stage == 'before_commit' and result_pending:
                os._exit(72)
            return original_commit(session)
        Session.commit = commit
        if stage == 'after_commit_before_ack':
            channel.basic_ack = lambda **kwargs: os._exit(72)
        worker = InferenceWorker(get_sessionmaker(), 'http://diagnosis:8000',
                                 InternalTokenSigner.from_environment(), http_client=client)
        worker.process_message(channel, method.delivery_tag, body, method.routing_key)
        if stage == 'heartbeat':
            assert renewals, 'Long execution must renew its lease via the internal API'
            connection.close()
            return
        raise AssertionError('Crash checkpoint was not reached')
    raise AssertionError('Requested delivery did not reach crash worker')


def token():
    now = int(time.time())
    return jwt.encode({'sub': str(uuid.uuid4()), 'role': 'USER', 'iss': 'agrodiagnostico-identity',
                       'aud': 'agrodiagnostico-api', 'jti': str(uuid.uuid4()), 'iat': now, 'exp': now+600},
                      (SECRETS/'jwt_private_key.pem').read_text(), algorithm='EdDSA')


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'child':
        child(sys.argv[2], sys.argv[3])
        return
    if len(sys.argv) > 1 and sys.argv[1] == 'verify':
        identifiers = json.loads(sys.argv[2])
        # Use the real owner's public API token; no Diagnosis database access from AI.
        for entry in identifiers:
            deadline = time.monotonic()+110
            while time.monotonic() < deadline:
                status, row, _ = request_json('http://nginx:8080/api/v1/diagnoses/'+entry['id'],
                                              headers={'Authorization': 'Bearer '+entry['token']})
                if status == 200 and row['status'] == 'NO_CONCLUYENTE':
                    break
                time.sleep(0.5)
            else:
                raise AssertionError('Worker crash was not recovered: '+entry['stage'])
            with get_sessionmaker()() as session:
                results = session.scalars(select(InferenceResult).where(InferenceResult.diagnosis_id == uuid.UUID(entry['id']))).all()
                assert len(results) == 1, (entry['stage'], len(results))
            print('Recovered worker checkpoint: '+entry['stage'])
        return
    identifiers = []
    for stage in ('before_claim', 'after_claim', 'before_commit', 'after_commit_before_ack', 'heartbeat'):
        auth = token()
        body, content_type = encode_multipart_form('image', 'crash.jpg', (Path(__file__).resolve().parents[1]/'tests/integration/fixtures/async-abstention.jpg').read_bytes())
        status, row, _ = request_json('http://nginx:8080/api/v1/diagnoses', 'POST', body,
            {'Authorization': 'Bearer '+auth, 'Idempotency-Key': str(uuid.uuid4()), 'Content-Type': content_type})
        assert status == 202, (status, row)
        diagnosis_id = row['id']
        result = subprocess.run([sys.executable, __file__, 'child', stage, diagnosis_id], timeout=40)
        assert result.returncode == (0 if stage == 'heartbeat' else 72), (stage, result.returncode)
        with get_sessionmaker()() as session:
            for model in (InferenceResult, InferenceInbox, InferenceOutbox):
                rows = session.scalars(select(model).where(model.diagnosis_id == uuid.UUID(diagnosis_id))).all()
                assert len(rows) == (1 if stage in ('after_commit_before_ack', 'heartbeat') else 0), (stage, model.__name__, len(rows))
        identifiers.append({'id': diagnosis_id, 'token': auth, 'stage': stage})
        print(('Lease renewal verified: ' if stage == 'heartbeat' else 'Worker process killed at ')+stage, flush=True)
    # Store credentials in a mounted temporary file, never stdout/CI logs.
    Path('/test_state/crashes.json').write_text(json.dumps(identifiers))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'verify-file':
        sys.argv = [sys.argv[0], 'verify', Path('/test_state/crashes.json').read_text()]
    main()
