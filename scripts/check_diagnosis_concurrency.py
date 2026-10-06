"""Real PostgreSQL races; only invoked inside the disposable acceptance runner."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.catalog import create_admin_recommendation
from app.application.diagnoses import (
    DiagnosisFeedbackInput, cancel_diagnosis, create_diagnosis, submit_diagnosis_feedback,
)
from app.domain.image import ValidatedImage
from app.domain.models import Diagnosis, DiagnosisFeedback, IdempotencyKey
from app.infrastructure.security import Principal
from app.persistence import engine


def run_checks():
    db_engine = engine()
    assert db_engine.dialect.name == 'postgresql'
    owner = Principal(uuid.uuid4(), 'ADMIN', str(uuid.uuid4()))
    image = ValidatedImage(b'fixture', 7, 'a' * 64, 'image/jpeg', '.jpg', 1, 1)

    class Storage:
        def __init__(self):
            self.entered, self.release = Event(), Event()
            self.lock = Lock()
            self.puts = 0

        def put_object(self, **kwargs):
            with self.lock:
                self.puts += 1
            self.entered.set()
            assert self.release.wait(10), 'upload synchronization timeout'

    storage = Storage()
    key = str(uuid.uuid4())

    def create():
        with Session(db_engine) as db:
            row = create_diagnosis(db, owner, key, image, storage)
            return row.id

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(create)
            try:
                assert storage.entered.wait(10)
                second = pool.submit(create)
                try:
                    second.result(timeout=10)
                    raise AssertionError('Concurrent upload unexpectedly accepted')
                except HTTPException as exc:
                    assert exc.status_code == 409 and exc.detail['code'] == 'IDEMPOTENCY_IN_PROGRESS'
            finally:
                storage.release.set()
            diagnosis_id = first.result(timeout=10)
        assert create() == diagnosis_id and storage.puts == 1
        with Session(db_engine) as db:
            assert len(db.scalars(select(IdempotencyKey).where(IdempotencyKey.owner_id == owner.id)).all()) == 1
        print('PASS PostgreSQL concurrent idempotency: 409 in progress, one acceptance and replay', flush=True)

        def race(operation):
            barrier = Barrier(2, timeout=10)
            def invoke():
                with Session(db_engine) as db:
                    # Acquire independent physical connections before simultaneous release.
                    db.connection()
                    barrier.wait()
                    return operation(db)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(invoke) for _ in range(2)]
                return [future.result(timeout=15) for future in futures]

        def cancel(db):
            try:
                cancel_diagnosis(db, owner, diagnosis_id)
                return 200
            except HTTPException as exc:
                assert exc.detail['code'] == 'DIAGNOSIS_NOT_CANCELABLE'
                return exc.status_code
        assert sorted(race(cancel)) == [200, 409]
        print('PASS PostgreSQL simultaneous cancellation: one winner', flush=True)

        payload = dict(problem_code='POTATO_HEALTHY', title='Concurrency fixture', summary='Synthetic fixture',
                       cultural_practices=[], biological_control=[], preventive_measures=[],
                       source_refs=['synthetic fixture'], review_reference='fixture', reviewed_by='fixture',
                       reviewed_at='2026-01-01T00:00:00Z')
        versions = race(lambda db: create_admin_recommendation(db, owner, uuid.uuid4(), payload)['version'])
        assert len(set(versions)) == 2 and max(versions) - min(versions) == 1
        print('PASS PostgreSQL simultaneous recommendation versions: unique consecutive versions', flush=True)

        # Terminal fixture belongs solely to this disposable test database.
        with Session(db_engine) as db:
            terminal = Diagnosis(owner_id=owner.id, status='NO_CONCLUYENTE', reason_code='BAD_IMAGE',
                                 object_key='fixture/' + str(uuid.uuid4()), image_sha256='b' * 64,
                                 image_content_type='image/jpeg', image_size_bytes=7)
            db.add(terminal); db.commit(); terminal_id = terminal.id
        results = race(lambda db: submit_diagnosis_feedback(db, owner, terminal_id,
                              DiagnosisFeedbackInput(useful=True, comment=str(uuid.uuid4()))))
        assert sorted(code for _, code in results) == [200, 201]
        with Session(db_engine) as db:
            rows = db.scalars(select(DiagnosisFeedback).where(DiagnosisFeedback.diagnosis_id == terminal_id)).all()
            assert len(rows) == 1
            last = next(data for data, code in results if code == 200)
            assert rows[0].comment == last['comment']
        print('PASS PostgreSQL simultaneous feedback: one row, final update preserved', flush=True)
    finally:
        db_engine.dispose()
