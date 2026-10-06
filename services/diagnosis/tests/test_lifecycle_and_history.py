"""Test suite for Diagnosis lifecycle, keyset history, deletion, and supervision.

Covering tasks 5.1 to 5.4 of OpenSpec Incremento 2:
- 5.1: Atomic non-revertible cancellation, concurrency race, terminal 409s, foreign/tombstone 404s.
- 5.2: Idempotent own soft-delete (204), tombstone hiding in all user routes, detail variants.
- 5.3: Keyset history, HMAC-SHA256 cursors, bounds, tie-breaking, deleted anchor, tamper/rotation.
- 5.4: Admin supervision, minimal fields, exclusion of tombstones, audit log, RBAC.
"""
from datetime import datetime, timedelta, timezone
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
from app.infrastructure.cursor import encode_cursor, format_utc_iso
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


class TestLifecycleAndHistory(unittest.TestCase):
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
        status: str = "PENDIENTE",
        deleted_at: datetime = None,
        created_at: datetime = None,
        updated_at: datetime = None,
        reason_code: str = None,
        result_data: dict = None,
    ) -> Diagnosis:
        now = datetime.now(timezone.utc)
        diag_id = uuid.uuid4()
        c_at = created_at or now
        u_at = updated_at or now

        diag = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status=status,
            object_key=f"diagnoses/{diag_id}/original.jpg",
            image_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            image_content_type="image/jpeg",
            image_size_bytes=1024,
            deleted_at=deleted_at,
            created_at=c_at,
            updated_at=u_at,
            reason_code=reason_code,
        )
        if result_data:
            diag.crop_code = result_data.get("crop_code")
            diag.class_code = result_data.get("class_code")
            diag.raw_score = result_data.get("raw_score")
            diag.model_id = result_data.get("model_id")
            diag.model_version = result_data.get("model_version")
            diag.dataset_version = result_data.get("dataset_version")
            diag.catalog_version = result_data.get("catalog_version")
            diag.recommendation_id = result_data.get("recommendation_id")
            diag.recommendation_text = result_data.get("recommendation_text")

        with self.SessionLocal() as session:
            session.add(diag)
            session.commit()
            session.refresh(diag)
            return diag

    # =========================================================================
    # Task 5.1: Cancellation
    # =========================================================================

    def test_cancel_own_pendiente_success_200(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        headers = {
            "Authorization": f"Bearer {self.token_user_a}",
            "X-Correlation-ID": str(uuid.uuid4()),
        }
        resp = self.client.post(f"/api/v1/diagnoses/{diag.id}/cancel", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], str(diag.id))
        self.assertEqual(data["status"], "CANCELADO")
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)
        self.assertTrue(data["created_at"].endswith("Z"))
        self.assertTrue(data["updated_at"].endswith("Z"))
        self.assertEqual(resp.headers.get("Cache-Control"), "private, no-store")

        with self.SessionLocal() as session:
            refreshed = session.get(Diagnosis, diag.id)
            self.assertEqual(refreshed.status, "CANCELADO")

    def test_cancel_concurrency_race_single_winner(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        headers = {"Authorization": f"Bearer {self.token_user_a}"}

        resp1 = self.client.post(f"/api/v1/diagnoses/{diag.id}/cancel", headers=headers)
        resp2 = self.client.post(f"/api/v1/diagnoses/{diag.id}/cancel", headers=headers)

        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 409)
        self.assertEqual(resp2.json()["code"], "DIAGNOSIS_NOT_CANCELABLE")

    def test_cancel_non_cancelable_statuses_return_409(self):
        non_cancelable_statuses = [
            "PROCESANDO",
            "COMPLETADO",
            "NO_CONCLUYENTE",
            "FALLIDO",
            "CANCELADO",
        ]
        headers = {"Authorization": f"Bearer {self.token_user_a}"}
        for st in non_cancelable_statuses:
            with self.subTest(status=st):
                diag = self._insert_diagnosis(owner_id=self.user_a_id, status=st)
                resp = self.client.post(f"/api/v1/diagnoses/{diag.id}/cancel", headers=headers)
                self.assertEqual(resp.status_code, 409)
                self.assertEqual(resp.json()["code"], "DIAGNOSIS_NOT_CANCELABLE")
                with self.SessionLocal() as session:
                    refreshed = session.get(Diagnosis, diag.id)
                    self.assertEqual(refreshed.status, st)

    def test_cancel_foreign_returns_404(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        headers = {"Authorization": f"Bearer {self.token_user_b}"}
        resp = self.client.post(f"/api/v1/diagnoses/{diag.id}/cancel", headers=headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["code"], "NOT_FOUND")

    def test_cancel_admin_on_user_route_returns_404(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        headers = {"Authorization": f"Bearer {self.token_admin}"}
        resp = self.client.post(f"/api/v1/diagnoses/{diag.id}/cancel", headers=headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["code"], "NOT_FOUND")

    def test_cancel_nonexistent_returns_404(self):
        headers = {"Authorization": f"Bearer {self.token_user_a}"}
        resp = self.client.post(f"/api/v1/diagnoses/{uuid.uuid4()}/cancel", headers=headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["code"], "NOT_FOUND")

    def test_cancel_soft_deleted_returns_404(self):
        now = datetime.now(timezone.utc)
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE", deleted_at=now)
        headers = {"Authorization": f"Bearer {self.token_user_a}"}
        resp = self.client.post(f"/api/v1/diagnoses/{diag.id}/cancel", headers=headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["code"], "NOT_FOUND")

    # =========================================================================
    # Task 5.2: Soft Deletion and Contractual Detail
    # =========================================================================

    def test_delete_own_diagnosis_success_204(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        headers = {"Authorization": f"Bearer {self.token_user_a}"}
        resp = self.client.delete(f"/api/v1/diagnoses/{diag.id}", headers=headers)
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.text, "")

        with self.SessionLocal() as session:
            refreshed = session.get(Diagnosis, diag.id)
            self.assertIsNotNone(refreshed.deleted_at)
            self.assertEqual(refreshed.status, "PENDIENTE")  # State is conserved

    def test_delete_repeated_idempotent_204(self):
        now = datetime.now(timezone.utc)
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE", deleted_at=now)
        headers = {"Authorization": f"Bearer {self.token_user_a}"}
        resp = self.client.delete(f"/api/v1/diagnoses/{diag.id}", headers=headers)
        self.assertEqual(resp.status_code, 204)

    def test_delete_foreign_returns_404(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        headers = {"Authorization": f"Bearer {self.token_user_b}"}
        resp = self.client.delete(f"/api/v1/diagnoses/{diag.id}", headers=headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["code"], "NOT_FOUND")

    def test_delete_admin_on_user_route_returns_404(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        headers = {"Authorization": f"Bearer {self.token_admin}"}
        resp = self.client.delete(f"/api/v1/diagnoses/{diag.id}", headers=headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["code"], "NOT_FOUND")

    def test_delete_nonexistent_returns_404(self):
        headers = {"Authorization": f"Bearer {self.token_user_a}"}
        resp = self.client.delete(f"/api/v1/diagnoses/{uuid.uuid4()}", headers=headers)
        self.assertEqual(resp.status_code, 404)

    def test_tombstone_hidden_in_all_user_endpoints(self):
        now = datetime.now(timezone.utc)
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE", deleted_at=now)
        headers = {"Authorization": f"Bearer {self.token_user_a}"}

        # 1. Detail
        r_det = self.client.get(f"/api/v1/diagnoses/{diag.id}", headers=headers)
        self.assertEqual(r_det.status_code, 404)

        # 2. Image
        r_img = self.client.get(f"/api/v1/diagnoses/{diag.id}/image", headers=headers)
        self.assertEqual(r_img.status_code, 404)

        # 3. Cancel
        r_can = self.client.post(f"/api/v1/diagnoses/{diag.id}/cancel", headers=headers)
        self.assertEqual(r_can.status_code, 404)

    def test_detail_variants(self):
        headers = {"Authorization": f"Bearer {self.token_user_a}"}

        # 1. PENDIENTE
        d_pen = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        r = self.client.get(f"/api/v1/diagnoses/{d_pen.id}", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {
            "id": str(d_pen.id),
            "status": "PENDIENTE",
            "created_at": format_utc_iso(d_pen.created_at),
            "updated_at": format_utc_iso(d_pen.updated_at),
        })

        # 2. PROCESANDO
        d_pro = self._insert_diagnosis(owner_id=self.user_a_id, status="PROCESANDO")
        r = self.client.get(f"/api/v1/diagnoses/{d_pro.id}", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "PROCESANDO")

        # 3. CANCELADO
        d_can = self._insert_diagnosis(owner_id=self.user_a_id, status="CANCELADO")
        r = self.client.get(f"/api/v1/diagnoses/{d_can.id}", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "CANCELADO")

        # 4. NO_CONCLUYENTE
        d_noc = self._insert_diagnosis(
            owner_id=self.user_a_id,
            status="NO_CONCLUYENTE",
            reason_code="LOW_CONFIDENCE",
        )
        r = self.client.get(f"/api/v1/diagnoses/{d_noc.id}", headers=headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "NO_CONCLUYENTE")
        self.assertEqual(data["reason_code"], "LOW_CONFIDENCE")

        # 5. FALLIDO
        d_fal = self._insert_diagnosis(
            owner_id=self.user_a_id,
            status="FALLIDO",
            reason_code="INFERENCE_ERROR",
        )
        r = self.client.get(f"/api/v1/diagnoses/{d_fal.id}", headers=headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "FALLIDO")
        self.assertEqual(data["reason_code"], "INFERENCE_ERROR")

        # 6. COMPLETADO
        rec_id = uuid.uuid4()
        d_com = self._insert_diagnosis(
            owner_id=self.user_a_id,
            status="COMPLETADO",
            result_data={
                "crop_code": "POTATO",
                "class_code": "POTATO_EARLY_BLIGHT",
                "raw_score": 0.94,
                "model_id": "classifier-v1",
                "model_version": "1.0.0",
                "dataset_version": "2026-09",
                "catalog_version": "1.0.0",
                "recommendation_id": rec_id,
                "recommendation_text": "Texto sintético de prueba.",
            },
        )
        r = self.client.get(f"/api/v1/diagnoses/{d_com.id}", headers=headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["status"], "COMPLETADO")
        self.assertIn("result", data)
        res = data["result"]
        self.assertEqual(res["crop_code"], "POTATO")
        self.assertEqual(res["class_code"], "POTATO_EARLY_BLIGHT")
        self.assertEqual(res["raw_score"], 0.94)
        self.assertEqual(res["model"]["model_id"], "classifier-v1")
        self.assertEqual(res["recommendation"]["recommendation_id"], str(rec_id))

    def test_detail_foreign_and_admin_return_404(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        r_b = self.client.get(
            f"/api/v1/diagnoses/{diag.id}",
            headers={"Authorization": f"Bearer {self.token_user_b}"},
        )
        self.assertEqual(r_b.status_code, 404)

        r_adm = self.client.get(
            f"/api/v1/diagnoses/{diag.id}",
            headers={"Authorization": f"Bearer {self.token_admin}"},
        )
        self.assertEqual(r_adm.status_code, 404)

    # =========================================================================
    # Task 5.3: Keyset Pagination and HMAC Cursors
    # =========================================================================

    def test_user_list_pagination_limit_bounds(self):
        headers = {"Authorization": f"Bearer {self.token_user_a}"}
        for bad_limit in [0, -1, 101]:
            with self.subTest(limit=bad_limit):
                r = self.client.get(f"/api/v1/diagnoses?limit={bad_limit}", headers=headers)
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json()["code"], "INVALID_PAGINATION")

    def test_user_list_keyset_navigation_and_tie_breaking(self):
        base_time = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        items = []
        for i in range(5):
            t = base_time + timedelta(seconds=i if i != 2 else 1)  # Items 1 and 2 have identical timestamp
            diag = self._insert_diagnosis(
                owner_id=self.user_a_id,
                status="PENDIENTE",
                created_at=t,
            )
            items.append(diag)

        headers = {"Authorization": f"Bearer {self.token_user_a}"}

        # Page 1 (limit=2)
        r1 = self.client.get("/api/v1/diagnoses?limit=2", headers=headers)
        self.assertEqual(r1.status_code, 200)
        p1 = r1.json()
        self.assertEqual(len(p1["items"]), 2)
        self.assertIsNotNone(p1["next_cursor"])

        # Page 2 (limit=2)
        r2 = self.client.get(f"/api/v1/diagnoses?limit=2&cursor={p1['next_cursor']}", headers=headers)
        self.assertEqual(r2.status_code, 200)
        p2 = r2.json()
        self.assertEqual(len(p2["items"]), 2)
        self.assertIsNotNone(p2["next_cursor"])

        # Page 3 (limit=2)
        r3 = self.client.get(f"/api/v1/diagnoses?limit=2&cursor={p2['next_cursor']}", headers=headers)
        self.assertEqual(r3.status_code, 200)
        p3 = r3.json()
        self.assertEqual(len(p3["items"]), 1)
        self.assertIsNone(p3["next_cursor"])

        all_ids = [it["id"] for it in p1["items"] + p2["items"] + p3["items"]]
        self.assertEqual(len(all_ids), 5)
        self.assertEqual(len(set(all_ids)), 5)  # No duplicates

    def test_user_list_excludes_soft_deleted_and_other_users(self):
        now = datetime.now(timezone.utc)
        d_a_active = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        d_a_del = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE", deleted_at=now)
        d_b = self._insert_diagnosis(owner_id=self.user_b_id, status="PENDIENTE")

        headers = {"Authorization": f"Bearer {self.token_user_a}"}
        r = self.client.get("/api/v1/diagnoses", headers=headers)
        self.assertEqual(r.status_code, 200)
        ids = [it["id"] for it in r.json()["items"]]
        self.assertIn(str(d_a_active.id), ids)
        self.assertNotIn(str(d_a_del.id), ids)
        self.assertNotIn(str(d_b.id), ids)

    def test_user_list_deleted_anchor_continues_forward(self):
        base_time = datetime(2026, 10, 1, 10, 0, 0, tzinfo=timezone.utc)
        d1 = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE", created_at=base_time + timedelta(seconds=30))
        d2 = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE", created_at=base_time + timedelta(seconds=20))
        d3 = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE", created_at=base_time + timedelta(seconds=10))

        headers = {"Authorization": f"Bearer {self.token_user_a}"}
        r1 = self.client.get("/api/v1/diagnoses?limit=2", headers=headers)
        self.assertEqual(r1.status_code, 200)
        cursor1 = r1.json()["next_cursor"]

        # Soft delete d2 (the anchor row for cursor1)
        with self.SessionLocal() as session:
            ref = session.get(Diagnosis, d2.id)
            ref.deleted_at = datetime.now(timezone.utc)
            session.commit()

        # Request page 2 using cursor1
        r2 = self.client.get(f"/api/v1/diagnoses?limit=2&cursor={cursor1}", headers=headers)
        self.assertEqual(r2.status_code, 200)
        items2 = r2.json()["items"]
        self.assertEqual(len(items2), 1)
        self.assertEqual(items2[0]["id"], str(d3.id))
        self.assertNotIn(str(d2.id), [it["id"] for it in items2])

    def test_cursor_invalid_cases_return_400(self):
        headers_a = {"Authorization": f"Bearer {self.token_user_a}"}
        d1 = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")

        # 1. Valid cursor for user A
        valid_cursor = encode_cursor(
            created_at=d1.created_at,
            diagnosis_id=d1.id,
            principal_id=self.user_a_id,
            purpose="user_diagnoses",
        )

        # 2. Used by User B -> 400
        headers_b = {"Authorization": f"Bearer {self.token_user_b}"}
        r = self.client.get(f"/api/v1/diagnoses?cursor={valid_cursor}", headers=headers_b)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "INVALID_PAGINATION")

        # 3. Purpose admin_supervision on user endpoint -> 400
        admin_cursor = encode_cursor(
            created_at=d1.created_at,
            diagnosis_id=d1.id,
            principal_id=self.user_a_id,
            purpose="admin_supervision",
        )
        r = self.client.get(f"/api/v1/diagnoses?cursor={admin_cursor}", headers=headers_a)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "INVALID_PAGINATION")

        # 4. Tampered signature -> 400
        parts = valid_cursor.split(".")
        tampered_sig = parts[0] + "." + parts[1][:-2] + ("AA" if not parts[1].endswith("AA") else "BB")
        r = self.client.get(f"/api/v1/diagnoses?cursor={tampered_sig}", headers=headers_a)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "INVALID_PAGINATION")

        # 5. Malformed string -> 400
        for bad in ["not-a-cursor", "foo.bar.baz", ""]:
            if bad:
                r = self.client.get(f"/api/v1/diagnoses?cursor={bad}", headers=headers_a)
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json()["code"], "INVALID_PAGINATION")

        # 6. Key rotation -> 400
        old_key = os.environ.get("CURSOR_SIGNING_KEY")
        try:
            os.environ["CURSOR_SIGNING_KEY"] = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            r = self.client.get(f"/api/v1/diagnoses?cursor={valid_cursor}", headers=headers_a)
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["code"], "INVALID_PAGINATION")
        finally:
            os.environ["CURSOR_SIGNING_KEY"] = old_key

    # =========================================================================
    # Task 5.4: Admin Supervision and Auditing
    # =========================================================================

    def test_admin_diagnoses_list_200_and_audit(self):
        now = datetime.now(timezone.utc)
        d_a = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        d_b = self._insert_diagnosis(owner_id=self.user_b_id, status="NO_CONCLUYENTE", reason_code="LOW_CONFIDENCE")
        d_del = self._insert_diagnosis(owner_id=self.user_a_id, status="CANCELADO", deleted_at=now)

        cid = uuid.uuid4()
        headers = {
            "Authorization": f"Bearer {self.token_admin}",
            "X-Correlation-ID": str(cid),
        }
        resp = self.client.get("/api/v1/admin/diagnoses", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        self.assertIn("next_cursor", data)

        returned_ids = [it["id"] for it in data["items"]]
        self.assertIn(str(d_a.id), returned_ids)
        self.assertIn(str(d_b.id), returned_ids)
        self.assertNotIn(str(d_del.id), returned_ids)  # Tombstones excluded

        # Verify minimal fields only: no object_key, no image, no feedback
        for item in data["items"]:
            self.assertEqual(set(item.keys()) - {"reason_code"}, {"id", "owner_id", "status", "created_at", "updated_at"})
            self.assertNotIn("object_key", item)
            self.assertNotIn("image", item)

        # Verify audit log recorded
        with self.SessionLocal() as session:
            logs = session.scalars(select(DiagnosisAuditLog)).all()
            self.assertEqual(len(logs), 1)
            entry = logs[0]
            self.assertEqual(entry.actor_id, self.admin_id)
            self.assertEqual(entry.action, "ADMIN_LIST_DIAGNOSES")
            self.assertEqual(entry.target_type, "diagnosis")
            self.assertEqual(entry.correlation_id, cid)

    def test_admin_diagnoses_role_and_auth_checks(self):
        # 1. Anonymous -> 401
        r_anon = self.client.get("/api/v1/admin/diagnoses")
        self.assertEqual(r_anon.status_code, 401)
        self.assertEqual(r_anon.json()["code"], "UNAUTHORIZED")

        # 2. USER role -> 403
        r_user = self.client.get(
            "/api/v1/admin/diagnoses",
            headers={"Authorization": f"Bearer {self.token_user_a}"},
        )
        self.assertEqual(r_user.status_code, 403)
        self.assertEqual(r_user.json()["code"], "FORBIDDEN")

    def test_admin_cannot_access_foreign_images(self):
        diag = self._insert_diagnosis(owner_id=self.user_a_id, status="PENDIENTE")
        resp = self.client.get(
            f"/api/v1/diagnoses/{diag.id}/image",
            headers={"Authorization": f"Bearer {self.token_admin}"},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["code"], "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
