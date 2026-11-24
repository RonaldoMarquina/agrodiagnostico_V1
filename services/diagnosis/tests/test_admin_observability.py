"""Unit tests for Diagnosis administrative observability, audit, models, system status, and D-19 audited image reads (ADR-0016)."""
import asyncio
from datetime import datetime, timedelta, timezone
import os
import time
import unittest
from unittest.mock import patch
import uuid

import httpx
import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.domain.models import (
    Base,
    Diagnosis,
    DiagnosisAuditLog,
    DiagnosisOutbox,
    DiagnosisQuarantineMessage,
    PublicationPolicy,
)
from app.infrastructure.tokens import (
    TokenVerifier,
    generate_ed25519_keypair,
    set_token_verifier,
)
from app.main import app as main_app
from app.storage import (
    ObjectNotFoundError,
    S3StorageAdapter,
    StorageUnavailableError,
    set_storage_adapter,
)
from tests.client import TestClient


class InMemoryStorageAdapter(S3StorageAdapter):
    def __init__(self):
        super().__init__(bucket="test-bucket")
        self.objects = {}
        self.fail_unavailable = False

    def get_object(self, key: str):
        if self.fail_unavailable:
            raise StorageUnavailableError("simulated s3 outage")
        if key not in self.objects:
            raise ObjectNotFoundError(f"missing {key}")
        return self.objects[key]

    def put_object(self, key: str, body: bytes, content_type: str):
        self.objects[key] = (body, content_type)

    def delete_object(self, key: str):
        self.objects.pop(key, None)


class TestAdminObservability(unittest.TestCase):
    def setUp(self):
        self._prev_cursor_key = os.environ.get("CURSOR_SIGNING_KEY")
        self._prev_real_auth = os.environ.get("REAL_INFERENCE_AUTHORIZED")
        os.environ["CURSOR_SIGNING_KEY"] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        os.environ["REAL_INFERENCE_AUTHORIZED"] = "false"

        self.priv_pem, self.pub_pem = generate_ed25519_keypair()
        set_token_verifier(TokenVerifier(public_key_pem=self.pub_pem))

        self.storage = InMemoryStorageAdapter()
        set_storage_adapter(self.storage)

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        main_app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(main_app)

        self.admin_id = uuid.uuid4()
        self.other_admin_id = uuid.uuid4()
        self.user_id = uuid.uuid4()

        self.admin_headers = {"Authorization": f"Bearer {self._make_token(self.admin_id, 'ADMIN')}"}
        self.other_admin_headers = {"Authorization": f"Bearer {self._make_token(self.other_admin_id, 'ADMIN')}"}
        self.user_headers = {"Authorization": f"Bearer {self._make_token(self.user_id, 'USER')}"}

    def tearDown(self):
        main_app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)
        if self._prev_cursor_key is None:
            os.environ.pop("CURSOR_SIGNING_KEY", None)
        else:
            os.environ["CURSOR_SIGNING_KEY"] = self._prev_cursor_key
        if self._prev_real_auth is None:
            os.environ.pop("REAL_INFERENCE_AUTHORIZED", None)
        else:
            os.environ["REAL_INFERENCE_AUTHORIZED"] = self._prev_real_auth

    def _make_token(self, user_id: uuid.UUID, role: str) -> str:
        now = int(time.time())
        payload = {
            "sub": str(user_id),
            "role": role,
            "iss": "agrodiagnostico-identity",
            "aud": "agrodiagnostico-api",
            "iat": now,
            "exp": now + 900,
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(payload, self.priv_pem, algorithm="EdDSA")

    def _seed_diagnosis(
        self,
        db,
        *,
        owner_id: uuid.UUID,
        status: str = "PENDIENTE",
        reason_code=None,
        raw_score=None,
        calibrated_confidence=None,
        model_id=None,
        model_version=None,
        dataset_version=None,
        created_at=None,
        deleted_at=None,
    ) -> Diagnosis:
        diag_id = uuid.uuid4()
        dt = created_at or datetime.now(timezone.utc)
        diag = Diagnosis(
            id=diag_id,
            owner_id=owner_id,
            status=status,
            object_key=f"diagnoses/{owner_id}/{diag_id}.jpg",
            image_sha256="a" * 64,
            image_content_type="image/jpeg",
            image_size_bytes=128,
            raw_score=raw_score,
            calibrated_confidence=calibrated_confidence,
            reason_code=reason_code,
            model_id=model_id,
            model_version=model_version,
            dataset_version=dataset_version,
            created_at=dt,
            updated_at=dt,
            deleted_at=deleted_at,
        )
        db.add(diag)
        return diag

    def test_metrics_summary_aggregates_empty_and_populated_with_rbac_and_bounds(self):
        # 401 unauthenticated, 403 USER
        self.assertEqual(self.client.get("/api/v1/admin/metrics/summary").status_code, 401)
        self.assertEqual(
            self.client.get("/api/v1/admin/metrics/summary", headers=self.user_headers).status_code,
            403,
        )

        # Empty DB -> total 0, average_confidence null, all 6 statuses 0
        res_empty = self.client.get("/api/v1/admin/metrics/summary", headers=self.admin_headers)
        self.assertEqual(res_empty.status_code, 200)
        self.assertEqual(res_empty.headers.get("cache-control"), "private, no-store")
        empty_data = res_empty.json()
        self.assertEqual(empty_data["total"], 0)
        self.assertIsNone(empty_data["average_confidence"])
        self.assertEqual(
            empty_data["by_status"],
            {
                "PENDIENTE": 0,
                "PROCESANDO": 0,
                "COMPLETADO": 0,
                "NO_CONCLUYENTE": 0,
                "FALLIDO": 0,
                "CANCELADO": 0,
            },
        )
        self.assertEqual(empty_data["daily_series"], [])

        # Seed diagnoses across two days
        day1 = datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        day2 = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            self._seed_diagnosis(db, owner_id=self.user_id, status="COMPLETADO", calibrated_confidence=0.90, created_at=day1)
            self._seed_diagnosis(db, owner_id=self.user_id, status="NO_CONCLUYENTE", reason_code="LOW_CONFIDENCE", raw_score=0.50, created_at=day1)
            self._seed_diagnosis(db, owner_id=self.user_id, status="NO_CONCLUYENTE", reason_code="BAD_IMAGE", created_at=day2)
            self._seed_diagnosis(db, owner_id=self.user_id, status="FALLIDO", created_at=day2)
            self._seed_diagnosis(db, owner_id=self.user_id, status="PENDIENTE", created_at=day2)
            db.commit()

        res = self.client.get(
            "/api/v1/admin/metrics/summary",
            params={"from": "2026-11-19T00:00:00Z", "to": "2026-11-22T23:59:59Z"},
            headers=self.admin_headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 5)
        self.assertEqual(data["by_status"]["COMPLETADO"], 1)
        self.assertEqual(data["by_status"]["NO_CONCLUYENTE"], 2)
        self.assertEqual(data["by_status"]["FALLIDO"], 1)
        self.assertEqual(data["by_status"]["PENDIENTE"], 1)
        self.assertEqual(data["by_inconclusive_reason"], {"LOW_CONFIDENCE": 1, "BAD_IMAGE": 1})
        self.assertAlmostEqual(data["average_confidence"], 0.7, places=4)
        self.assertEqual(
            data["daily_series"],
            [
                {"date": "2026-11-20", "total": 2, "completed": 1, "inconclusive": 1, "failed": 0},
                {"date": "2026-11-21", "total": 3, "completed": 0, "inconclusive": 1, "failed": 1},
            ],
        )

        # Invalid ranges -> 400 (from > to, and > 90 days)
        self.assertEqual(
            self.client.get(
                "/api/v1/admin/metrics/summary",
                params={"from": "2026-11-22T00:00:00Z", "to": "2026-11-20T00:00:00Z"},
                headers=self.admin_headers,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/admin/metrics/summary",
                params={"from": "2026-01-01T00:00:00Z", "to": "2026-06-01T00:00:00Z"},
                headers=self.admin_headers,
            ).status_code,
            400,
        )

    def test_audit_diagnosis_pagination_filters_and_rbac(self):
        self.assertEqual(self.client.get("/api/v1/admin/audit/diagnosis").status_code, 401)
        self.assertEqual(
            self.client.get("/api/v1/admin/audit/diagnosis", headers=self.user_headers).status_code,
            403,
        )

        base_dt = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
        inserted_ids = []
        with self.SessionLocal() as db:
            for idx in range(5):
                row = DiagnosisAuditLog(
                    id=uuid.uuid4(),
                    actor_id=self.admin_id,
                    action="ADMIN_VIEW_DIAGNOSIS_IMAGE" if idx % 2 == 0 else "CATALOG_CREATE_CROP",
                    target_type="DIAGNOSIS" if idx % 2 == 0 else "CROP",
                    target_id=f"target-{idx}",
                    correlation_id=uuid.uuid4(),
                    details={"idx": idx, "token": "SHOULD_BE_REDACTED"},
                    created_at=base_dt + timedelta(minutes=idx),
                )
                db.add(row)
                inserted_ids.append(str(row.id))
            db.commit()

        seen = []
        cursor = None
        while True:
            params = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            res = self.client.get("/api/v1/admin/audit/diagnosis", params=params, headers=self.admin_headers)
            self.assertEqual(res.status_code, 200)
            payload = res.json()
            for item in payload["items"]:
                seen.append(item["id"])
                self.assertNotIn("token", item["details"] or {})
            cursor = payload["next_cursor"]
            if cursor is None:
                break

        self.assertEqual(seen, list(reversed(inserted_ids)))

        # Filters work
        res_f = self.client.get(
            "/api/v1/admin/audit/diagnosis",
            params={"action": "ADMIN_VIEW_DIAGNOSIS_IMAGE", "target_type": "DIAGNOSIS"},
            headers=self.admin_headers,
        )
        self.assertEqual(res_f.status_code, 200)
        self.assertEqual(len(res_f.json()["items"]), 3)

        # Invalid cursor, cross-admin cursor, filter mismatch, invalid range -> 400
        first = self.client.get(
            "/api/v1/admin/audit/diagnosis", params={"limit": 2}, headers=self.admin_headers
        ).json()
        self.assertIsNotNone(first["next_cursor"])
        self.assertEqual(
            self.client.get(
                "/api/v1/admin/audit/diagnosis",
                params={"cursor": "bad.cursor"},
                headers=self.admin_headers,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/admin/audit/diagnosis",
                params={"limit": 2, "cursor": first["next_cursor"]},
                headers=self.other_admin_headers,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/admin/audit/diagnosis",
                params={"limit": 2, "action": "CATALOG_CREATE_CROP", "cursor": first["next_cursor"]},
                headers=self.admin_headers,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/admin/audit/diagnosis",
                params={"from": "2026-11-23T00:00:00Z", "to": "2026-11-20T00:00:00Z"},
                headers=self.admin_headers,
            ).status_code,
            400,
        )

    def test_models_inventory_honors_gate_blocked_and_aggregates_history(self):
        self.assertEqual(self.client.get("/api/v1/admin/models", headers=self.user_headers).status_code, 403)

        t1 = datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 11, 21, 12, 0, 0, tzinfo=timezone.utc)
        with self.SessionLocal() as db:
            db.add(
                PublicationPolicy(
                    policy_version="v1.4.3-demo-policy",
                    model_id="demo-no-concluyente",
                    model_version="0.0.0-demo",
                    dataset_version="demo-v1",
                    bundle_digest="b" * 64,
                    payload={"mode": "demo"},
                    active=True,
                )
            )
            self._seed_diagnosis(
                db,
                owner_id=self.user_id,
                status="NO_CONCLUYENTE",
                model_id="demo-no-concluyente",
                model_version="0.0.0-demo",
                dataset_version="demo-v1",
                created_at=t1,
            )
            self._seed_diagnosis(
                db,
                owner_id=self.user_id,
                status="NO_CONCLUYENTE",
                model_id="demo-no-concluyente",
                model_version="0.0.0-demo",
                dataset_version="demo-v1",
                created_at=t2,
            )
            db.commit()

        res = self.client.get("/api/v1/admin/models", headers=self.admin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["real_inference_authorized"])
        self.assertEqual(data["runtime_status"], "INACTIVE_GATE_BLOCKED")
        self.assertIsNone(data["active_model"])
        self.assertEqual(data["active_policy_version"], "v1.4.3-demo-policy")
        self.assertEqual(len(data["historical_versions"]), 1)
        self.assertEqual(data["historical_versions"][0]["model_id"], "demo-no-concluyente")
        self.assertEqual(data["historical_versions"][0]["diagnoses_count"], 2)

    def test_system_status_probes_timeouts_optional_assistant_and_local_counts(self):
        self.assertEqual(self.client.get("/api/v1/admin/system/status", headers=self.user_headers).status_code, 403)

        # Seed 1 pending outbox, 1 sent outbox, and 2 quarantine rows
        with self.SessionLocal() as db:
            db.add(
                DiagnosisOutbox(
                    event_id=uuid.uuid4(),
                    event_type="DiagnosisRequested",
                    schema_version=2,
                    routing_key="diagnosis.requested.v2",
                    envelope={"test": True},
                    sent_at=None,
                )
            )
            db.add(
                DiagnosisOutbox(
                    event_id=uuid.uuid4(),
                    event_type="DiagnosisRequested",
                    schema_version=2,
                    routing_key="diagnosis.requested.v2",
                    envelope={"test": True},
                    sent_at=datetime.now(timezone.utc),
                )
            )
            for idx in range(2):
                db.add(
                    DiagnosisQuarantineMessage(
                        consumer="diagnosis",
                        routing_key="diagnosis.analyzed.v1",
                        message_hash=f"{idx}" * 64,
                        error_reason="invalid_schema",
                    )
                )
            db.commit()

        # Case 1: Core healthy, optional assistant DOWN -> overall_status == OK
        def probe_core_ok(client: httpx.AsyncClient, url: str, timeout: float):
            if "assistant" in url:
                return "DOWN", None
            return "OK", 11

        with patch("app.application.observability._probe_health_ready", side_effect=probe_core_ok), \
             patch("app.application.observability.schema_ready", return_value=True), \
             patch("app.application.observability.storage_ready", return_value=True):
            res = self.client.get("/api/v1/admin/system/status", headers=self.admin_headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["overall_status"], "OK")
            self.assertEqual(data["outbox_pending_count"], 1)
            self.assertEqual(data["quarantine_count"], 2)
            by_name = {s["name"]: s for s in data["services"]}
            self.assertEqual(by_name["identity"]["status"], "OK")
            self.assertEqual(by_name["diagnosis"]["status"], "OK")
            self.assertEqual(by_name["assistant"]["status"], "DOWN")
            self.assertTrue(by_name["assistant"]["optional"])

        # Case 2: One core dependency times out -> UNKNOWN and overall_status == DEGRADED (no 500)
        def probe_with_timeout(client: httpx.AsyncClient, url: str, timeout: float):
            if "notification" in url:
                return "UNKNOWN", None
            return "OK", 9

        with patch("app.application.observability._probe_health_ready", side_effect=probe_with_timeout), \
             patch("app.application.observability.schema_ready", return_value=True), \
             patch("app.application.observability.storage_ready", return_value=True):
            res_deg = self.client.get("/api/v1/admin/system/status", headers=self.admin_headers)
            self.assertEqual(res_deg.status_code, 200)
            data_deg = res_deg.json()
            self.assertEqual(data_deg["overall_status"], "DEGRADED")
            by_name = {s["name"]: s for s in data_deg["services"]}
            self.assertEqual(by_name["notification"]["status"], "UNKNOWN")
            self.assertIsNone(by_name["notification"]["latency_ms"])

    def test_system_status_cancels_slow_response_bodies_within_parallel_deadline(self):
        cancelled: set[str] = set()

        class SlowBody(httpx.AsyncByteStream):
            def __init__(self, host: str):
                self.host = host

            async def __aiter__(self):
                try:
                    await asyncio.sleep(2.0)
                    yield b'{"status":"ready"}'
                except asyncio.CancelledError:
                    cancelled.add(self.host)
                    raise

        def respond(request: httpx.Request) -> httpx.Response:
            if request.url.host in ("identity", "notification"):
                return httpx.Response(200, stream=SlowBody(request.url.host))
            if request.url.host == "assistant":
                return httpx.Response(503)
            return httpx.Response(200, json={"status": "ready"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with (
            patch.dict(os.environ, {
                "IDENTITY_HEALTH_URL": "http://identity/health/ready",
                "AI_INFERENCE_HEALTH_URL": "http://ai_inference/health/ready",
                "NOTIFICATION_HEALTH_URL": "http://notification/health/ready",
                "ASSISTANT_HEALTH_URL": "http://assistant/health/ready",
            }),
            patch("app.application.observability.httpx.AsyncClient", return_value=client),
            patch("app.application.observability.HEALTH_PROBE_TIMEOUT_SECONDS", 0.5),
            patch("app.application.observability.schema_ready", return_value=True),
            patch("app.application.observability.storage_ready", return_value=True),
        ):
            started = time.monotonic()
            response = self.client.get("/api/v1/admin/system/status", headers=self.admin_headers)
            elapsed = time.monotonic() - started

        self.assertEqual(response.status_code, 200)
        self.assertLess(elapsed, 1.0)
        self.assertEqual(cancelled, {"identity", "notification"})
        payload = response.json()
        self.assertEqual(payload["overall_status"], "DEGRADED")
        services = {service["name"]: service for service in payload["services"]}
        self.assertEqual(services["ai_inference"]["status"], "OK")
        self.assertEqual(services["assistant"]["status"], "DEGRADED")
        for name in cancelled:
            self.assertEqual(services[name]["status"], "UNKNOWN")
            self.assertIsNone(services[name]["latency_ms"])

    def test_admin_diagnosis_image_d19_audit_and_privacy_invariants(self):
        with self.SessionLocal() as db:
            diag = self._seed_diagnosis(db, owner_id=self.user_id, status="NO_CONCLUYENTE")
            deleted_diag = self._seed_diagnosis(
                db,
                owner_id=self.user_id,
                status="NO_CONCLUYENTE",
                deleted_at=datetime.now(timezone.utc),
            )
            db.commit()
            diag_id = diag.id
            deleted_id = deleted_diag.id
            self.storage.put_object(diag.object_key, b"\xff\xd8\xff\xe0FAKEJPEG", "image/jpeg")

        # 1. USER cannot access /api/v1/admin/diagnoses/{id}/image -> 403
        res_user = self.client.get(
            f"/api/v1/admin/diagnoses/{diag_id}/image",
            headers=self.user_headers,
        )
        self.assertEqual(res_user.status_code, 403)

        # 2. Owner route /api/v1/diagnoses/{id}/image remains isolated with 404 for ADMIN on foreign diagnosis
        res_owner_route = self.client.get(
            f"/api/v1/diagnoses/{diag_id}/image",
            headers=self.admin_headers,
        )
        self.assertEqual(res_owner_route.status_code, 404)

        # 3. /api/v1/admin/diagnoses remains metadata-only (no object_key or image bytes)
        res_list = self.client.get("/api/v1/admin/diagnoses", headers=self.admin_headers)
        self.assertEqual(res_list.status_code, 200)
        for item in res_list.json()["items"]:
            self.assertNotIn("object_key", item)
            self.assertNotIn("image_url", item)

        # 4. Explicit audited read via /api/v1/admin/diagnoses/{id}/image succeeds and records ADMIN_VIEW_DIAGNOSIS_IMAGE
        cid = str(uuid.uuid4())
        res_ok = self.client.get(
            f"/api/v1/admin/diagnoses/{diag_id}/image",
            headers={**self.admin_headers, "X-Correlation-ID": cid},
        )
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.body, b"\xff\xd8\xff\xe0FAKEJPEG")
        self.assertEqual(res_ok.headers.get("cache-control"), "private, no-store")
        self.assertEqual(res_ok.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(res_ok.headers.get("x-correlation-id"), cid)

        with self.SessionLocal() as db:
            audit_rows = (
                db.query(DiagnosisAuditLog)
                .filter(DiagnosisAuditLog.action == "ADMIN_VIEW_DIAGNOSIS_IMAGE")
                .all()
            )
            self.assertEqual(len(audit_rows), 1)
            self.assertEqual(audit_rows[0].actor_id, self.admin_id)
            self.assertEqual(audit_rows[0].target_type, "DIAGNOSIS")
            self.assertEqual(audit_rows[0].target_id, str(diag_id))
            self.assertEqual(str(audit_rows[0].correlation_id), cid)

        # 5. Missing, soft-deleted, or storage-missing image returns 404 without adding a new audit entry
        self.assertEqual(
            self.client.get(
                f"/api/v1/admin/diagnoses/{uuid.uuid4()}/image",
                headers=self.admin_headers,
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/api/v1/admin/diagnoses/{deleted_id}/image",
                headers=self.admin_headers,
            ).status_code,
            404,
        )
        with self.SessionLocal() as db:
            count_after = (
                db.query(DiagnosisAuditLog)
                .filter(DiagnosisAuditLog.action == "ADMIN_VIEW_DIAGNOSIS_IMAGE")
                .count()
            )
            self.assertEqual(count_after, 1)


if __name__ == "__main__":
    unittest.main()
