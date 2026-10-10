"""Race real internal claim and owner cancellation against PostgreSQL row locking."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
import time
import uuid

import jwt

from check_async_acceptance import request_json, encode_multipart_form, create_jpeg_bytes


def main():
    secrets = Path('/test_secrets')
    now = int(time.time())
    user = jwt.encode({'sub': str(uuid.uuid4()), 'role': 'USER', 'iss': 'agrodiagnostico-identity',
        'aud': 'agrodiagnostico-api', 'jti': str(uuid.uuid4()), 'iat': now, 'exp': now+600},
        (secrets/'jwt_private_key.pem').read_text(), algorithm='EdDSA')
    service = jwt.encode({'sub': 'ai_inference', 'instance_id': 'worker-1', 'iss': 'agrodiagnostico-internal',
        'aud': 'diagnosis-internal', 'jti': str(uuid.uuid4()), 'iat': now, 'exp': now+60},
        (secrets/'internal_worker_1_private_key.pem').read_text(), algorithm='EdDSA', headers={'kid':'worker-1-key'})
    for _ in range(4):
        body, content_type = encode_multipart_form('image', 'race.jpg', create_jpeg_bytes(width=201))
        code, row, _ = request_json('http://nginx:8080/api/v1/diagnoses', 'POST', body,
            {'Authorization':'Bearer '+user,'Idempotency-Key':str(uuid.uuid4()),'Content-Type':content_type})
        assert code == 202
        diagnosis_id = row['id']
        barrier = Barrier(2)
        def claim():
            barrier.wait()
            return request_json(f'http://diagnosis:8000/internal/diagnoses/{diagnosis_id}/claim', 'POST',
                                headers={'Authorization':'Bearer '+service})[0]
        def cancel():
            barrier.wait()
            return request_json(f'http://nginx:8080/api/v1/diagnoses/{diagnosis_id}/cancel', 'POST',
                                headers={'Authorization':'Bearer '+user})[0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(claim), pool.submit(cancel)
            outcome = (first.result(), second.result())
        assert outcome in ((200,409), (409,200)), outcome
        state = request_json(f'http://nginx:8080/api/v1/diagnoses/{diagnosis_id}',
                              headers={'Authorization':'Bearer '+user})[1]['status']
        assert state == ('PROCESANDO' if outcome[0] == 200 else 'CANCELADO'), (outcome,state)
    print('Concurrent claim/cancel: exactly one winner in four real PostgreSQL races')


if __name__ == '__main__':
    main()
