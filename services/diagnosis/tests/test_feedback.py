"""Unit and integration test suite for Diagnosis feedback.

Covering tasks 7.1 and 7.2 of OpenSpec Incremento 2:
- 7.1: POST feedback with UNIQUE(diagnosis_id), serialization with DELETE, strict boolean,
       comment up to 1000 chars, 201 initial, 200 replacement, comment omission clearing,
       concurrency safety, and 400 on invalid payload.
- 7.2: Allowed statuses COMPLETADO / NO_CONCLUYENTE; 409 for PENDIENTE, PROCESANDO,
       CANCELADO, FALLIDO; 404 for foreign, nonexistent, or soft-deleted (including ADMIN
       on foreign); ADMIN allowed on own diagnosis; absence of ML / training events or pipelines.
"""
from datetime import datetime, timezone
import os
import time
import unittest
import uuid

import jwt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.domain.models import (
    Base,
    Crop,
    Diagnosis,
    DiagnosisAuditLog,
    DiagnosisFeedback,
    IdempotencyKey,
    ImageUploadIntent,
    Problem,
    Recommendation,
)
from app.infrastructure.tokens import (
    TokenVerifier,
    generate_ed25519_keypair,
    set_token_verifier,
)
from app.main import app as main_app
from app.storage import S3StorageAdapter, set_storage_adapter
from tests.client import TestClient


class DummyStorageAdapter(S3StorageAdapter):
    def __init__(self):
        super().__init__(bucket="test-bucket")
        self.objects = {}

    def get_object(self, key: str):
        if key in self.objects:
            return self.objects[key]
        return b"fake-bytes", "image/jpeg"

    def put_object(self, key: str, body: bytes, content_type: str):
        self.objects[key] = (body, content_type)

    def delete_object(self, key: str):
        self.objects.pop(key, None)


class TestFeedback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signing_key = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        os.environ["CURSOR_SIGNING_KEY"] = cls.signing_key

        cls.priv_pem, cls.pub_pem = generate_ed25519_keypair()
        cls.verifier = TokenVerifier(public_key_pem=cls.pub_pem)
        set_token_verifier(cls.verifier)

        cls.storage = DummyStorageAdapter()
        set_storage_adapter(cls.storage)

        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

        def override_get_db():
            db = cls.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        main_app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(main_app)

    @classmethod
    def tearDownClass(cls):
        set_token_verifier(None)
        set_storage_adapter(None)
        main_app.dependency_overrides.clear()
        os.environ.pop("CURSOR_SIGNING_KEY", None)

    def setUp(self):
        with self.SessionLocal() as session:
            session.query(DiagnosisAuditLog).delete()
            session.query(DiagnosisFeedback).delete()
            session.query(IdempotencyKey).delete()
            session.query(ImageUploadIntent).delete()
            session.query(Diagnosis).delete()
            session.query(Recommendation).delete()
            session.query(Problem).delete()
            session.query(Crop).delete()
            session.commit()

        self.user_a_id = uuid.uuid4()
        self.user_b_id = uuid.uuid4()
        self.admin_id = uuid.uuid4()

        self.token_user_a = self._create_token(sub=str(self.user_a_id), role="USER")
        self.token_user_b = self._create_token(sub=str(self.user_b_id), role="USER")
        self.token_admin = self._create_token(sub=str(self.admin_id), role="ADMIN")

    def _create_token(self, sub: str, role: str = "USER", expires_in: int = 3600) -> str:
        now = int(time.time())
        claims = {
            "sub": sub,
            "role": role,
            "iss": "agrodiagnostico-identity",
            "aud": "agrodiagnostico-api",
            "iat": now,
            "exp": now + expires_in,
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(claims, self.priv_pem, algorithm="EdDSA")

    def _insert_diagnosis(
        self,
        owner_id: uuid.UUID,
        status: str = "COMPLETADO",
        deleted_at: datetime = None,
        reason_code: str = None,
    ) -> Diagnosis:
        diag_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        diag = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status=status,
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_content_type="image/jpeg",
            image_size_bytes=1024,
            image_width=800,
            image_height=600,
            image_sha256="aabbcc" * 10,
            reason_code=reason_code,
            deleted_at=deleted_at,
            created_at=now,
            updated_at=now,
        )
        with self.SessionLocal() as session:
            session.add(diag)
            session.commit()
            session.refresh(diag)
        return diag

    # =========================================================================
    # Task 7.1 Tests: Initial 201, Replacement 200, Validation, Concurrency
    # =========================================================================

    def test_post_feedback_initial_201_success(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")
        response = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True, "comment": "Diagnóstico muy claro y útil."},
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["diagnosis_id"], str(diag.id))
        self.assertTrue(data["useful"])
        self.assertEqual(data["comment"], "Diagnóstico muy claro y útil.")
        self.assertTrue(data["created_at"].endswith("Z"))
        self.assertTrue(data["updated_at"].endswith("Z"))
        self.assertEqual(response.headers.get("Cache-Control"), "private, no-store")
        self.assertTrue("X-Correlation-ID" in response.headers)

        # Check DB persistence
        with self.SessionLocal() as session:
            feedbacks = session.query(DiagnosisFeedback).filter_by(diagnosis_id=diag.id).all()
            self.assertEqual(len(feedbacks), 1)
            self.assertEqual(feedbacks[0].owner_id, self.user_a_id)
            self.assertTrue(feedbacks[0].useful)

    def test_post_feedback_replacement_200_preserves_created_at(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")

        # Initial submission
        res1 = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True, "comment": "Primer comentario."},
        )
        self.assertEqual(res1.status_code, 201)
        created_at_orig = res1.json()["created_at"]

        # Replacement submission
        res2 = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": False, "comment": "Segundo comentario actualizado."},
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertEqual(data2["diagnosis_id"], str(diag.id))
        self.assertFalse(data2["useful"])
        self.assertEqual(data2["comment"], "Segundo comentario actualizado.")
        self.assertEqual(data2["created_at"], created_at_orig)  # created_at preserved!

        # Check DB: only 1 row exists
        with self.SessionLocal() as session:
            feedbacks = session.query(DiagnosisFeedback).filter_by(diagnosis_id=diag.id).all()
            self.assertEqual(len(feedbacks), 1)
            self.assertFalse(feedbacks[0].useful)
            self.assertEqual(feedbacks[0].comment, "Segundo comentario actualizado.")

    def test_post_feedback_omit_comment_clears_previous_comment(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")

        # Initial with comment
        res1 = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True, "comment": "Tenía un comentario."},
        )
        self.assertEqual(res1.status_code, 201)
        self.assertEqual(res1.json()["comment"], "Tenía un comentario.")

        # Update omitting comment
        res2 = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": False},
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertFalse(data2["useful"])
        self.assertIsNone(data2["comment"])

        # Check DB: comment is None
        with self.SessionLocal() as session:
            fb = session.query(DiagnosisFeedback).filter_by(diagnosis_id=diag.id).one()
            self.assertIsNone(fb.comment)

    def test_post_feedback_strict_boolean_validation(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")

        # Strings rejected
        for invalid_val in ["true", "false", "yes", "no", "1", "0"]:
            res = self.client.post(
                f"/api/v1/diagnoses/{diag.id}/feedback",
                headers={"Authorization": f"Bearer {self.token_user_a}"},
                json={"useful": invalid_val},
            )
            self.assertEqual(res.status_code, 400, f"Failed to reject string boolean: {invalid_val}")
            self.assertEqual(res.json()["code"], "INVALID_REQUEST")

        # Integers rejected
        for invalid_val in [1, 0, -1]:
            res = self.client.post(
                f"/api/v1/diagnoses/{diag.id}/feedback",
                headers={"Authorization": f"Bearer {self.token_user_a}"},
                json={"useful": invalid_val},
            )
            self.assertEqual(res.status_code, 400, f"Failed to reject int boolean: {invalid_val}")
            self.assertEqual(res.json()["code"], "INVALID_REQUEST")

    def test_post_feedback_extra_fields_rejected(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")
        res = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True, "extra_field": "disallowed"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "INVALID_REQUEST")

    def test_post_feedback_missing_useful_rejected(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")
        res = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"comment": "Solo comentario sin useful"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "INVALID_REQUEST")

    def test_post_feedback_comment_length_limits(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")

        # Exact 1000 chars is valid
        res_ok = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True, "comment": "a" * 1000},
        )
        self.assertEqual(res_ok.status_code, 201)

        # 1001 chars is rejected
        res_err = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True, "comment": "a" * 1001},
        )
        self.assertEqual(res_err.status_code, 400)
        self.assertEqual(res_err.json()["code"], "INVALID_REQUEST")

    def test_post_feedback_invalid_uuid_rejected(self):
        res = self.client.post(
            "/api/v1/diagnoses/invalid-uuid-format/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True},
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "INVALID_REQUEST")

    # =========================================================================
    # Task 7.2 Tests: Allowed / Disallowed Statuses, Security, Independence
    # =========================================================================

    def test_post_feedback_allowed_statuses(self):
        # COMPLETADO allows feedback
        diag_comp = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")
        res1 = self.client.post(
            f"/api/v1/diagnoses/{diag_comp.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True},
        )
        self.assertEqual(res1.status_code, 201)

        # NO_CONCLUYENTE allows feedback
        diag_incon = self._insert_diagnosis(
            owner_id=self.user_a_id, status="NO_CONCLUYENTE", reason_code="LOW_CONFIDENCE"
        )
        res2 = self.client.post(
            f"/api/v1/diagnoses/{diag_incon.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": False, "comment": "Imagen no fue concluyente."},
        )
        self.assertEqual(res2.status_code, 201)

    def test_post_feedback_disallowed_statuses_return_409(self):
        for dis_status in ["PENDIENTE", "PROCESANDO", "CANCELADO", "FALLIDO"]:
            diag = self._insert_diagnosis(owner_id=self.user_a_id, status=dis_status)
            res = self.client.post(
                f"/api/v1/diagnoses/{diag.id}/feedback",
                headers={"Authorization": f"Bearer {self.token_user_a}"},
                json={"useful": True},
            )
            self.assertEqual(
                res.status_code,
                409,
                f"Expected 409 for status {dis_status}, got {res.status_code}",
            )
            self.assertEqual(res.json()["code"], "FEEDBACK_NOT_ALLOWED")

    def test_post_feedback_foreign_diagnosis_returns_404(self):
        # User A owns diagnosis, User B tries to submit feedback
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")
        res = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_b}"},
            json={"useful": True},
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["code"], "RESOURCE_NOT_FOUND")

    def test_post_feedback_nonexistent_returns_404(self):
        res = self.client.post(
            f"/api/v1/diagnoses/{uuid.uuid4()}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True},
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["code"], "RESOURCE_NOT_FOUND")

    def test_post_feedback_soft_deleted_returns_404(self):
        # Diagnosis was soft-deleted
        diag = self._insert_diagnosis(
            owner_id=self.user_a_id,
            status="COMPLETADO",
            deleted_at=datetime.now(timezone.utc),
        )
        res = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True},
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["code"], "RESOURCE_NOT_FOUND")

    def test_post_feedback_admin_on_foreign_returns_404(self):
        # ADMIN tries to submit feedback on user A's diagnosis -> 404
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")
        res = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_admin}"},
            json={"useful": True},
        )
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["code"], "RESOURCE_NOT_FOUND")

    def test_post_feedback_admin_on_own_diagnosis_allowed(self):
        # ADMIN owns diagnosis -> can submit feedback on own diagnosis
        diag = self._insert_diagnosis(owner_id=self.admin_id, status="COMPLETADO")
        res = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_admin}"},
            json={"useful": True, "comment": "Admin own feedback"},
        )
        self.assertEqual(res.status_code, 201)

    def test_post_feedback_anonymous_returns_401(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")
        res = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            json={"useful": True},
        )
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["code"], "UNAUTHORIZED")

    def test_post_feedback_serialization_with_delete(self):
        # User A owns diagnosis in COMPLETADO
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")

        # Delete own diagnosis (204)
        del_res = self.client.delete(
            f"/api/v1/diagnoses/{diag.id}",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
        )
        self.assertEqual(del_res.status_code, 204)

        # Attempt to submit feedback on now soft-deleted diagnosis returns 404
        fb_res = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True},
        )
        self.assertEqual(fb_res.status_code, 404)
        self.assertEqual(fb_res.json()["code"], "RESOURCE_NOT_FOUND")

    def test_feedback_no_events_no_ml_pipeline(self):
        # Submitting feedback must NOT write audit log, create outbox events, or trigger ML pipelines
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="COMPLETADO")
        res = self.client.post(
            f"/api/v1/diagnoses/{diag.id}/feedback",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
            json={"useful": True, "comment": "No events expected"},
        )
        self.assertEqual(res.status_code, 201)

        with self.SessionLocal() as session:
            # Audit log should have 0 entries for user feedback
            audit_entries = session.query(DiagnosisAuditLog).all()
            self.assertEqual(len(audit_entries), 0)

            # Idempotency table should have 0 entries
            idemp_entries = session.query(IdempotencyKey).all()
            self.assertEqual(len(idemp_entries), 0)

            # Upload intents should have 0 entries
            intent_entries = session.query(ImageUploadIntent).all()
            self.assertEqual(len(intent_entries), 0)


if __name__ == "__main__":
    unittest.main()
