"""Exercise deadline and concurrent recovery against the isolated Diagnosis PostgreSQL database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import uuid
import json

from sqlalchemy import select

from app.application.internal_diagnoses import get_db_now
from app.application.lease_recovery import recover_expired_leases
from app.domain.models import Diagnosis, DiagnosisOutbox
from app.consumer import DiagnosisAnalyzedConsumer
from app.persistence import get_sessionmaker


def main():
    maker = get_sessionmaker()
    identifiers = []
    with maker() as db:
        now = get_db_now(db)
        for attempts, deadline, signaled in [(1, -1, True), (3, 240, False), (1, 240, False)]:
            diagnosis_id = uuid.uuid4()
            identifiers.append(diagnosis_id)
            db.add(Diagnosis(id=diagnosis_id, owner_id=uuid.uuid4(), status='PROCESANDO',
                object_key=f'diagnoses/{diagnosis_id}/original.jpg', image_sha256='0'*64,
                image_content_type='image/jpeg', image_size_bytes=1, lease_token=uuid.uuid4(),
                lease_owner='worker-1', attempt_count=attempts,
                lease_expires_at=now-timedelta(seconds=20),
                processing_deadline_at=now+timedelta(seconds=deadline),
                recovery_signaled_at=now-timedelta(seconds=10) if signaled else None,
                correlation_id=uuid.uuid4()))
        db.commit()
    barrier = Barrier(2)
    def recover():
        barrier.wait()
        with maker() as db:
            recover_expired_leases(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(recover), pool.submit(recover)
        first.result()
        second.result()
    with maker() as db:
        for diagnosis_id in identifiers[:2]:
            row = db.get(Diagnosis, diagnosis_id)
            assert row.status == 'FALLIDO' and row.reason_code == 'PROCESSING_TIMEOUT'
            events = db.scalars(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == diagnosis_id)).all()
            assert len(events) == 1 and events[0].event_type == 'DiagnosisFinished'
        events = db.scalars(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == identifiers[2])).all()
        assert len(events) == 1 and events[0].event_type == 'DiagnosisRequested'
        row = db.get(Diagnosis, identifiers[2])
        row.processing_deadline_at = get_db_now(db)-timedelta(seconds=1)
        db.commit()
        recover_expired_leases(db)
        assert db.get(Diagnosis, identifiers[2]).status == 'FALLIDO'
        events = db.scalars(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == identifiers[2])).all()
        assert sum(event.event_type == 'DiagnosisFinished' for event in events) == 1
    # Competing result and recovery use independent real PostgreSQL transactions.
    with maker() as db:
        now = get_db_now(db)
        race_id, lease_token = uuid.uuid4(), uuid.uuid4()
        db.add(Diagnosis(id=race_id, owner_id=uuid.uuid4(), status='PROCESANDO',
            object_key=f'diagnoses/{race_id}/original.jpg', image_sha256='0'*64,
            image_content_type='image/jpeg', image_size_bytes=1, lease_token=lease_token,
            lease_owner='worker-1', attempt_count=3, lease_expires_at=now-timedelta(seconds=20),
            processing_deadline_at=now+timedelta(seconds=200), correlation_id=uuid.uuid4()))
        db.commit()
    envelope = {'event_id':str(uuid.uuid4()),'event_type':'DiagnosisAnalyzed','schema_version':1,
        'occurred_at':now.strftime('%Y-%m-%dT%H:%M:%SZ'),'correlation_id':str(uuid.uuid4()),
        'payload':{'diagnosis_id':str(race_id),'lease_token':str(lease_token),'outcome':'ABSTENTION',
                   'reason_code':'LOW_CONFIDENCE','crop_code':None,'model_id':None,'model_version':None,
                   'dataset_version':None,'inference_ms':None}}
    class Channel:
        def basic_ack(self, delivery_tag):
            pass
    barrier = Barrier(2)
    def finish():
        barrier.wait()
        return DiagnosisAnalyzedConsumer(maker).process_message(Channel(), 1, json.dumps(envelope).encode(), 'diagnosis.analyzed.v1')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(recover), pool.submit(finish)
        first.result()
        assert second.result()
    with maker() as db:
        assert db.get(Diagnosis, race_id).status == 'FALLIDO'
        events = db.scalars(select(DiagnosisOutbox).where(DiagnosisOutbox.diagnosis_id == race_id)).all()
        assert len(events) == 1 and events[0].event_type == 'DiagnosisFinished'
    print('PostgreSQL: late result/recovery race preserves one terminal and one Finished')
    print('PostgreSQL: concurrent recovery emits one signal; budget and deadline close once, including after prior signal')


if __name__ == '__main__':
    main()
