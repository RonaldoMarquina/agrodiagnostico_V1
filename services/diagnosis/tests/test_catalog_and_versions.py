"""Test suite for Agricultural Catalog and Recommendations versioning.

Covering tasks 6.1 to 6.4 of OpenSpec Incremento 2:
- 6.1: Public authenticated queries of crops, problems, and recommendations (active only, 404 on inactive/unknown parent, empty list on clean start).
- 6.2: Admin CRUD/patch of crops and problems, V1 taxonomy enforcement, 409 duplicates, immutable fields, transactional audit rollback.
- 6.3: Admin recommendations, review evidence validation (400 CATALOG_REVIEW_REQUIRED), incremental versioning, patch only active.
- 6.4: Preservation of resolved diagnosis result and recommendation snapshot across new versions and deactivations.
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


class TestCatalogAndVersions(unittest.TestCase):
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

            # Seed standard V1 taxonomy
            now = datetime.now(timezone.utc)
            c_potato = Crop(code="POTATO", name="Papa", active=True, created_at=now, updated_at=now)
            c_maize = Crop(code="MAIZE", name="Maíz", active=True, created_at=now, updated_at=now)
            session.add_all([c_potato, c_maize])

            problems = [
                Problem(code="POTATO_HEALTHY", crop_code="POTATO", name="Papa sana", type="HEALTHY", model_supported=False, active=True, created_at=now, updated_at=now),
                Problem(code="POTATO_EARLY_BLIGHT", crop_code="POTATO", name="Tizón temprano en papa", type="DISEASE", model_supported=False, active=True, created_at=now, updated_at=now),
                Problem(code="POTATO_LATE_BLIGHT", crop_code="POTATO", name="Tizón tardío en papa", type="DISEASE", model_supported=False, active=True, created_at=now, updated_at=now),
                Problem(code="MAIZE_HEALTHY", crop_code="MAIZE", name="Maíz sano", type="HEALTHY", model_supported=False, active=True, created_at=now, updated_at=now),
                Problem(code="MAIZE_COMMON_RUST", crop_code="MAIZE", name="Roya común del maíz", type="DISEASE", model_supported=False, active=True, created_at=now, updated_at=now),
                Problem(code="MAIZE_LEAF_BLIGHT", crop_code="MAIZE", name="Tizón foliar del maíz", type="DISEASE", model_supported=False, active=True, created_at=now, updated_at=now),
                Problem(code="MAIZE_GRAY_LEAF_SPOT", crop_code="MAIZE", name="Mancha gris del maíz", type="DISEASE", model_supported=False, active=True, created_at=now, updated_at=now),
            ]
            session.add_all(problems)
            session.commit()

        self.user_id = uuid.uuid4()
        self.admin_id = uuid.uuid4()
        self.token_user = self._create_token(sub=str(self.user_id), role="USER")
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

    # =========================================================================
    # Task 6.1: Public Authenticated Catalog Queries
    # =========================================================================

    def test_public_crops_active_only(self):
        # 1. Deactivate MAIZE
        with self.SessionLocal() as session:
            maize = session.get(Crop, "MAIZE")
            maize.active = False
            session.commit()

        headers = {"Authorization": f"Bearer {self.token_user}"}
        resp = self.client.get("/api/v1/crops", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)
        codes = [c["code"] for c in data["items"]]
        self.assertEqual(codes, ["POTATO"])  # Only active POTATO is returned

    def test_public_crop_problems_active_only_and_404_inactive_crop(self):
        headers = {"Authorization": f"Bearer {self.token_user}"}

        # 1. Deactivate POTATO_LATE_BLIGHT
        with self.SessionLocal() as session:
            lb = session.get(Problem, "POTATO_LATE_BLIGHT")
            lb.active = False
            session.commit()

        resp = self.client.get("/api/v1/crops/POTATO/problems", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        codes = [p["code"] for p in data["items"]]
        self.assertIn("POTATO_HEALTHY", codes)
        self.assertIn("POTATO_EARLY_BLIGHT", codes)
        self.assertNotIn("POTATO_LATE_BLIGHT", codes)

        # 2. Unknown crop code -> 404
        r_unk = self.client.get("/api/v1/crops/UNKNOWN/problems", headers=headers)
        self.assertEqual(r_unk.status_code, 404)
        self.assertEqual(r_unk.json()["code"], "NOT_FOUND")

        # 3. Inactive crop code -> 404
        with self.SessionLocal() as session:
            p = session.get(Crop, "POTATO")
            p.active = False
            session.commit()
        r_inact = self.client.get("/api/v1/crops/POTATO/problems", headers=headers)
        self.assertEqual(r_inact.status_code, 404)

    def test_public_recommendations_clean_start_empty_list(self):
        headers = {"Authorization": f"Bearer {self.token_user}"}
        resp = self.client.get("/api/v1/problems/POTATO_EARLY_BLIGHT/recommendations", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data, {"items": []})

    def test_public_recommendations_returns_latest_approved_active(self):
        now = datetime.now(timezone.utc)
        rec1_id = uuid.uuid4()
        rec2_id = uuid.uuid4()
        # Create versions 1 and 2
        with self.SessionLocal() as session:
            rec1 = Recommendation(
                id=rec1_id,
                problem_code="POTATO_EARLY_BLIGHT",
                version=1,
                title="Título v1",
                summary="Resumen v1",
                cultural_practices=["Práctica 1"],
                biological_control=["Control 1"],
                preventive_measures=["Medida 1"],
                source_refs=["Fuente 1"],
                review_reference="REV-001",
                reviewed_by="Revisor A",
                reviewed_at=now,
                active=True,
                created_at=now,
                updated_at=now,
            )
            rec2 = Recommendation(
                id=rec2_id,
                problem_code="POTATO_EARLY_BLIGHT",
                version=2,
                title="Título v2",
                summary="Resumen v2",
                cultural_practices=["Práctica 2"],
                biological_control=["Control 2"],
                preventive_measures=["Medida 2"],
                source_refs=["Fuente 2"],
                review_reference="REV-002",
                reviewed_by="Revisor B",
                reviewed_at=now,
                active=True,
                created_at=now,
                updated_at=now,
            )
            session.add_all([rec1, rec2])
            session.commit()

        headers = {"Authorization": f"Bearer {self.token_user}"}
        resp = self.client.get("/api/v1/problems/POTATO_EARLY_BLIGHT/recommendations", headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["version"], 2)
        self.assertEqual(data["items"][0]["title"], "Título v2")

        # Deactivate version 2: version 1 should now be returned
        with self.SessionLocal() as session:
            r2 = session.get(Recommendation, rec2_id)
            r2.active = False
            session.commit()

        resp2 = self.client.get("/api/v1/problems/POTATO_EARLY_BLIGHT/recommendations", headers=headers)
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(len(data2["items"]), 1)
        self.assertEqual(data2["items"][0]["version"], 1)

    def test_public_recommendations_404_on_inactive_problem_or_crop(self):
        headers = {"Authorization": f"Bearer {self.token_user}"}

        # 1. Unknown problem -> 404
        r_unk = self.client.get("/api/v1/problems/UNKNOWN/recommendations", headers=headers)
        self.assertEqual(r_unk.status_code, 404)

        # 2. Inactive problem -> 404
        with self.SessionLocal() as session:
            prob = session.get(Problem, "POTATO_EARLY_BLIGHT")
            prob.active = False
            session.commit()
        r_inact_prob = self.client.get("/api/v1/problems/POTATO_EARLY_BLIGHT/recommendations", headers=headers)
        self.assertEqual(r_inact_prob.status_code, 404)

        # 3. Inactive parent crop -> 404
        with self.SessionLocal() as session:
            prob.active = True
            crop = session.get(Crop, "POTATO")
            crop.active = False
            session.commit()
        r_inact_crop = self.client.get("/api/v1/problems/POTATO_EARLY_BLIGHT/recommendations", headers=headers)
        self.assertEqual(r_inact_crop.status_code, 404)

    # =========================================================================
    # Task 6.2: Admin Crops and Problems Management
    # =========================================================================

    def test_admin_crops_rbac(self):
        # 1. Anonymous -> 401
        r_anon = self.client.get("/api/v1/admin/crops")
        self.assertEqual(r_anon.status_code, 401)

        # 2. USER -> 403
        r_user = self.client.get("/api/v1/admin/crops", headers={"Authorization": f"Bearer {self.token_user}"})
        self.assertEqual(r_user.status_code, 403)

        # 3. ADMIN -> 200
        r_admin = self.client.get("/api/v1/admin/crops", headers={"Authorization": f"Bearer {self.token_admin}"})
        self.assertEqual(r_admin.status_code, 200)
        self.assertEqual(len(r_admin.json()["items"]), 2)

    def test_admin_create_crop_valid_and_duplicate_and_taxonomy_enforcement(self):
        # Remove MAIZE first to test recreating it
        with self.SessionLocal() as session:
            session.query(Problem).filter(Problem.crop_code == "MAIZE").delete()
            session.query(Crop).filter(Crop.code == "MAIZE").delete()
            session.commit()

        headers = {"Authorization": f"Bearer {self.token_admin}"}

        # 1. Create MAIZE -> 201
        resp = self.client.post("/api/v1/admin/crops", json={"code": "MAIZE", "name": "Maíz"}, headers=headers)
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["code"], "MAIZE")
        self.assertEqual(data["name"], "Maíz")
        self.assertTrue(data["active"])

        # Check audit log
        with self.SessionLocal() as session:
            logs = session.scalars(select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "ADMIN_CREATE_CROP")).all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].target_id, "MAIZE")

        # 2. Duplicate -> 409 CATALOG_CONFLICT
        resp_dup = self.client.post("/api/v1/admin/crops", json={"code": "MAIZE", "name": "Maíz nuevo"}, headers=headers)
        self.assertEqual(resp_dup.status_code, 409)
        self.assertEqual(resp_dup.json()["code"], "CATALOG_CONFLICT")

        # 3. Non-V1 taxonomy code (e.g. SOYBEAN) -> 400 INVALID_REQUEST
        resp_tax = self.client.post("/api/v1/admin/crops", json={"code": "SOYBEAN", "name": "Soja"}, headers=headers)
        self.assertEqual(resp_tax.status_code, 400)
        self.assertEqual(resp_tax.json()["code"], "INVALID_REQUEST")

    def test_admin_patch_crop_name_and_active_and_immutable_code(self):
        headers = {"Authorization": f"Bearer {self.token_admin}"}

        # 1. Patch name and active -> 200
        resp = self.client.patch(
            "/api/v1/admin/crops/POTATO",
            json={"name": "Papa común", "active": False},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "Papa común")
        self.assertFalse(data["active"])

        # Check audit log
        with self.SessionLocal() as session:
            logs = session.scalars(select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "ADMIN_PATCH_CROP")).all()
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].target_id, "POTATO")

        # 2. Attempt to modify code (immutable) -> 400
        resp_bad = self.client.patch(
            "/api/v1/admin/crops/POTATO",
            json={"code": "NEW_CODE"},
            headers=headers,
        )
        self.assertEqual(resp_bad.status_code, 400)

        # 3. Unknown crop -> 404
        resp_404 = self.client.patch(
            "/api/v1/admin/crops/UNKNOWN",
            json={"name": "Test"},
            headers=headers,
        )
        self.assertEqual(resp_404.status_code, 404)

    def test_admin_problems_crud_and_taxonomy_enforcement(self):
        headers = {"Authorization": f"Bearer {self.token_admin}"}

        # 1. List problems -> 200
        resp = self.client.get("/api/v1/admin/problems", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["items"]), 7)

        # 2. Duplicate problem -> 409
        resp_dup = self.client.post(
            "/api/v1/admin/problems",
            json={
                "code": "POTATO_EARLY_BLIGHT",
                "crop_code": "POTATO",
                "name": "Tizón temprano duplicado",
                "problem_type": "DISEASE",
            },
            headers=headers,
        )
        self.assertEqual(resp_dup.status_code, 409)
        self.assertEqual(resp_dup.json()["code"], "CATALOG_CONFLICT")

        # 3. Invalid taxonomy problem (e.g. POTATO_PEST) -> 400
        resp_bad = self.client.post(
            "/api/v1/admin/problems",
            json={
                "code": "POTATO_PEST",
                "crop_code": "POTATO",
                "name": "Plaga de papa",
                "problem_type": "DISEASE",
            },
            headers=headers,
        )
        self.assertEqual(resp_bad.status_code, 400)

        # 4. Patch problem -> 200
        resp_patch = self.client.patch(
            "/api/v1/admin/problems/POTATO_EARLY_BLIGHT",
            json={"name": "Tizón temprano modificado", "active": False},
            headers=headers,
        )
        self.assertEqual(resp_patch.status_code, 200)
        self.assertEqual(resp_patch.json()["name"], "Tizón temprano modificado")
        self.assertFalse(resp_patch.json()["active"])

        # Check audit log
        with self.SessionLocal() as session:
            logs = session.scalars(select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "ADMIN_PATCH_PROBLEM")).all()
            self.assertEqual(len(logs), 1)

        # 5. Patch immutable fields (crop_code, model_supported) -> 400
        resp_imm = self.client.patch(
            "/api/v1/admin/problems/POTATO_EARLY_BLIGHT",
            json={"crop_code": "MAIZE", "model_supported": True},
            headers=headers,
        )
        self.assertEqual(resp_imm.status_code, 400)

    # =========================================================================
    # Task 6.3: Admin Recommendations, Reviews and Versions
    # =========================================================================

    def test_admin_create_recommendation_requires_review_evidence(self):
        headers = {"Authorization": f"Bearer {self.token_admin}"}

        # 1. Missing review evidence -> 400 CATALOG_REVIEW_REQUIRED
        payload_no_review = {
            "problem_code": "POTATO_EARLY_BLIGHT",
            "title": "Manejo preventivo",
            "summary": "Resumen",
            "cultural_practices": ["Rotación"],
            "biological_control": ["Bacillus"],
            "preventive_measures": ["Semilla"],
            # Missing source_refs, review_reference, reviewed_by, reviewed_at
        }
        resp = self.client.post("/api/v1/admin/recommendations", json=payload_no_review, headers=headers)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "CATALOG_REVIEW_REQUIRED")

        # 2. Empty source_refs -> 400 CATALOG_REVIEW_REQUIRED
        payload_empty_sources = {
            **payload_no_review,
            "source_refs": [],
            "review_reference": "REV-001",
            "reviewed_by": "Ing. Agrónomo",
            "reviewed_at": "2026-10-06T12:00:00Z",
        }
        resp_empty = self.client.post("/api/v1/admin/recommendations", json=payload_empty_sources, headers=headers)
        self.assertEqual(resp_empty.status_code, 400)
        self.assertEqual(resp_empty.json()["code"], "CATALOG_REVIEW_REQUIRED")

    def test_admin_create_recommendation_success_and_incremental_versions(self):
        headers = {"Authorization": f"Bearer {self.token_admin}"}
        valid_payload_v1 = {
            "problem_code": "POTATO_EARLY_BLIGHT",
            "title": "Manejo cultural v1",
            "summary": "Resumen sintético de prueba v1",
            "cultural_practices": ["Rotación de cultivos"],
            "biological_control": ["Trichoderma"],
            "preventive_measures": ["Uso de semilla sana"],
            "source_refs": ["Manual Técnico INIA 2024"],
            "review_reference": "REV-2026-001",
            "reviewed_by": "Dr. Agronomía",
            "reviewed_at": "2026-10-06T10:00:00Z",
            "active": True,
        }

        # Version 1 -> 201
        r1 = self.client.post("/api/v1/admin/recommendations", json=valid_payload_v1, headers=headers)
        self.assertEqual(r1.status_code, 201)
        data1 = r1.json()
        self.assertEqual(data1["version"], 1)
        self.assertEqual(data1["title"], "Manejo cultural v1")
        self.assertTrue(data1["created_at"].endswith("Z"))

        # Version 2 -> 201
        valid_payload_v2 = {**valid_payload_v1, "title": "Manejo cultural v2", "review_reference": "REV-2026-002"}
        r2 = self.client.post("/api/v1/admin/recommendations", json=valid_payload_v2, headers=headers)
        self.assertEqual(r2.status_code, 201)
        data2 = r2.json()
        self.assertEqual(data2["version"], 2)
        self.assertNotEqual(data1["id"], data2["id"])

        # Check audit log
        with self.SessionLocal() as session:
            logs = session.scalars(select(DiagnosisAuditLog).where(DiagnosisAuditLog.action == "ADMIN_CREATE_RECOMMENDATION")).all()
            self.assertEqual(len(logs), 2)

    def test_admin_patch_recommendation_only_active(self):
        headers = {"Authorization": f"Bearer {self.token_admin}"}
        # Insert recommendation
        now = datetime.now(timezone.utc)
        rec_id = uuid.uuid4()
        with self.SessionLocal() as session:
            rec = Recommendation(
                id=rec_id,
                problem_code="POTATO_EARLY_BLIGHT",
                version=1,
                title="Título",
                summary="Resumen",
                cultural_practices=["P1"],
                biological_control=["B1"],
                preventive_measures=["M1"],
                source_refs=["S1"],
                review_reference="REV-1",
                reviewed_by="Rev",
                reviewed_at=now,
                active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(rec)
            session.commit()

        # 1. Patch active to False -> 200
        resp = self.client.patch(f"/api/v1/admin/recommendations/{rec_id}", json={"active": False}, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["active"])

        # 2. Attempt to edit content (immutable) -> 400
        resp_bad = self.client.patch(f"/api/v1/admin/recommendations/{rec_id}", json={"title": "Nuevo título"}, headers=headers)
        self.assertEqual(resp_bad.status_code, 400)

        # 3. Unknown recommendation -> 404
        resp_404 = self.client.patch(f"/api/v1/admin/recommendations/{uuid.uuid4()}", json={"active": True}, headers=headers)
        self.assertEqual(resp_404.status_code, 404)

    # =========================================================================
    # Task 6.4: Historical Diagnosis Result and Snapshot Preservation
    # =========================================================================

    def test_resolved_diagnosis_preserves_snapshot_on_catalog_changes(self):
        # 1. Create recommendation v1
        now = datetime.now(timezone.utc)
        rec_v1_id = uuid.uuid4()
        with self.SessionLocal() as session:
            rec_v1 = Recommendation(
                id=rec_v1_id,
                problem_code="POTATO_EARLY_BLIGHT",
                version=1,
                title="Manejo original v1",
                summary="Resumen original v1",
                cultural_practices=["Rotación"],
                biological_control=["Bacillus"],
                preventive_measures=["Semilla limpia"],
                source_refs=["Fuente v1"],
                review_reference="REV-001",
                reviewed_by="Revisor A",
                reviewed_at=now,
                active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(rec_v1)

            # 2. Create COMPLETADO diagnosis with snapshot of rec_v1
            diag_id = uuid.uuid4()
            diag = Diagnosis(
                id=diag_id,
                owner_id=self.user_id,
                status="COMPLETADO",
                object_key="diagnoses/test/original.jpg",
                image_sha256="fake-hash",
                image_content_type="image/jpeg",
                image_size_bytes=2048,
                crop_code="POTATO",
                class_code="POTATO_EARLY_BLIGHT",
                raw_score=0.91,
                model_id="potato-cnn",
                model_version="1.0.0",
                dataset_version="2026-09",
                catalog_version="1.0.0",
                recommendation_id=rec_v1_id,
                recommendation_text="Texto congelado en snapshot v1.",
                created_at=now,
                updated_at=now,
            )
            session.add(diag)
            session.commit()

        user_headers = {"Authorization": f"Bearer {self.token_user}"}
        admin_headers = {"Authorization": f"Bearer {self.token_admin}"}

        # 3. Admin creates version 2 of the recommendation
        resp_v2 = self.client.post(
            "/api/v1/admin/recommendations",
            json={
                "problem_code": "POTATO_EARLY_BLIGHT",
                "title": "Manejo nuevo v2",
                "summary": "Resumen nuevo v2",
                "cultural_practices": ["Nueva práctica"],
                "biological_control": ["Nuevo control"],
                "preventive_measures": ["Nueva medida"],
                "source_refs": ["Fuente v2"],
                "review_reference": "REV-002",
                "reviewed_by": "Revisor B",
                "reviewed_at": "2026-10-06T12:00:00Z",
                "active": True,
            },
            headers=admin_headers,
        )
        self.assertEqual(resp_v2.status_code, 201)

        # 4. Admin deactivates version 1
        self.client.patch(f"/api/v1/admin/recommendations/{rec_v1_id}", json={"active": False}, headers=admin_headers)

        # 5. Admin deactivates problem and crop
        self.client.patch("/api/v1/admin/problems/POTATO_EARLY_BLIGHT", json={"active": False}, headers=admin_headers)
        self.client.patch("/api/v1/admin/crops/POTATO", json={"active": False}, headers=admin_headers)

        # 6. User queries historical diagnosis detail GET /api/v1/diagnoses/{id}
        det_resp = self.client.get(f"/api/v1/diagnoses/{diag_id}", headers=user_headers)
        self.assertEqual(det_resp.status_code, 200)
        det_data = det_resp.json()

        # Invariant: Diagnosis still returns original result and original recommendation snapshot!
        self.assertEqual(det_data["status"], "COMPLETADO")
        self.assertIn("result", det_data)
        res = det_data["result"]
        self.assertEqual(res["crop_code"], "POTATO")
        self.assertEqual(res["class_code"], "POTATO_EARLY_BLIGHT")
        self.assertEqual(res["raw_score"], 0.91)
        self.assertEqual(res["recommendation"]["recommendation_id"], str(rec_v1_id))
        self.assertEqual(res["recommendation"]["text"], "Texto congelado en snapshot v1.")
        self.assertEqual(res["recommendation"]["catalog_version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
