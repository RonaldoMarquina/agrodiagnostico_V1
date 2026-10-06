#!/usr/bin/env python3
"""End-to-end isolated acceptance test for Incremento 2: Diagnosis and Catalog.

Executes complete acceptance covering:
- Disposable PostgreSQL (16-alpine) with separate identity and diagnosis roles/databases
- Disposable SeaweedFS (4.17) private S3 storage
- Identity service container (Ed25519 JWT issuer and user/admin management)
- Diagnosis service container (fastapi backend with persistence, S3, catalog, feedback)
- Nginx reverse proxy container with repository's exact default.conf
- Runner container executing full acceptance suite inside the Docker bridge network

Covers OpenSpec Task 8.2:
1. Real JWT issuance: Ed25519 access tokens issued by Identity and verified by Diagnosis.
2. Ingestion (Carga): Multipart image upload, 202 Accepted, PENDIENTE status.
3. Replay: Idempotent replay with same key returns identical 202 with original ID and created_at.
4. A/B Isolation: User B cannot view, cancel, or leak User A's diagnoses/images/idempotency.
5. Keyset History: Keyset pagination with HMAC signed cursor, invalid cursor returns 400.
6. Cancellation: Conditional cancellation of PENDIENTE returns 200, second cancel returns 409.
7. Tombstone: Soft delete returns 204, repeatable 204, subsequent GET returns 404.
8. Catalog & Admin: Public crops/problems/recommendations and admin management/diagnoses.
9. Feedback: Feedback on COMPLETED terminal fixture (201/200), 409 on PENDIENTE, 404 on foreign.
10. S3 & SQL Fault Injection: 503 STORAGE_UNAVAILABLE / PERSISTENCE_UNAVAILABLE when down.
11. Intent Reconciler: Cleans orphaned S3 objects and intents, preserves referenced objects.
12. Zero external dependencies: No RabbitMQ, Redis, Email worker, or AI inference required.
"""
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
if Path("/service").exists() and "/service" not in sys.path:
    sys.path.insert(0, "/service")
from prepare_identity_keys import prepare as prepare_identity_keys

PASSWORD = "SyntheticPassword123!"


# ==============================================================================
# HTTP Client Helper (used inside runner container)
# ==============================================================================

def request_json(url, method="GET", payload=None, headers=None):
    body = None
    hdrs = headers.copy() if headers else {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            return resp.status, json.loads(data) if data else None, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        data = exc.read()
        return exc.code, json.loads(data) if data else None, dict(exc.headers)


def request_multipart(url, image_bytes, filename="leaf.jpg", headers=None):
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    hdrs = headers.copy() if headers else {}
    hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: image/jpeg\r\n\r\n"
    ).encode("utf-8") + image_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
    hdrs["Content-Length"] = str(len(body))

    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            return resp.status, json.loads(data) if data else None, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        data = exc.read()
        return exc.code, json.loads(data) if data else None, dict(exc.headers)


def request_raw(url, method="GET", headers=None):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def get_header(hdrs, name):
    name_lower = name.lower()
    for k, v in hdrs.items():
        if k.lower() == name_lower:
            return v
    return None


def create_synthetic_jpeg():
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new("RGB", (120, 120), color=(34, 139, 34))
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ==============================================================================
# Acceptance Suite (executed inside runner container)
# ==============================================================================

def run_acceptance_suite(proxy_url, db_password_file):
    print("=" * 70, flush=True)
    print("RUNNING ISOLATED ACCEPTANCE TEST SUITE (Incremento 2)", flush=True)
    print("=" * 70, flush=True)

    db_password = Path(db_password_file).read_text().strip()

    # Wait for proxy readiness
    print("\n[1/11] Waiting for Nginx reverse proxy readiness...", flush=True)
    ready = False
    for _ in range(30):
        try:
            st, _, _ = request_json(f"{proxy_url}/api/v1/crops")
            if st == 401:  # Unauthenticated 401 confirms proxy -> diagnosis routing
                ready = True
                break
        except Exception:
            pass
        time.sleep(1)
    if not ready:
        raise RuntimeError("Nginx proxy failed to reach ready state")
    print("  ✓ Reverse proxy and backends are responsive", flush=True)

    # --------------------------------------------------------------------------
    # 1. Identity & Real Ed25519 JWT
    # --------------------------------------------------------------------------
    print("\n[2/11] Testing Identity registration, login and Ed25519 JWT tokens...", flush=True)

    # Register User A
    email_a = f"user_a_{uuid.uuid4().hex[:6]}@example.com"
    st, data, _ = request_json(
        f"{proxy_url}/api/v1/auth/register",
        method="POST",
        payload={"email": email_a, "password": PASSWORD, "display_name": "Agricultor A"},
    )
    assert st == 201, f"Failed registering user A: {st} {data}"
    user_a_id = data["id"]

    origin_hdr = {"Origin": "https://identity-test.example"}

    # Login User A
    st, data, _ = request_json(
        f"{proxy_url}/api/v1/auth/login",
        method="POST",
        payload={"email": email_a, "password": PASSWORD},
        headers=origin_hdr,
    )
    assert st == 200, f"Failed logging in user A: {st} {data}"
    token_a = data["access_token"]
    auth_a = {"Authorization": f"Bearer {token_a}"}

    # Register User B
    email_b = f"user_b_{uuid.uuid4().hex[:6]}@example.com"
    st, data, _ = request_json(
        f"{proxy_url}/api/v1/auth/register",
        method="POST",
        payload={"email": email_b, "password": PASSWORD, "display_name": "Agricultor B"},
    )
    assert st == 201, f"Failed registering user B: {st} {data}"
    user_b_id = data["id"]

    # Login User B
    st, data, _ = request_json(
        f"{proxy_url}/api/v1/auth/login",
        method="POST",
        payload={"email": email_b, "password": PASSWORD},
        headers=origin_hdr,
    )
    assert st == 200, f"Failed logging in user B: {st} {data}"
    token_b = data["access_token"]
    auth_b = {"Authorization": f"Bearer {token_b}"}

    # Login Admin
    st, data, _ = request_json(
        f"{proxy_url}/api/v1/auth/login",
        method="POST",
        payload={"email": "admin@example.com", "password": PASSWORD},
        headers=origin_hdr,
    )
    assert st == 200, f"Failed logging in admin: {st} {data}"
    token_admin = data["access_token"]
    auth_admin = {"Authorization": f"Bearer {token_admin}"}

    # Negative auth
    st, data, _ = request_json(f"{proxy_url}/api/v1/diagnoses")
    assert st == 401, f"Expected 401 unauthenticated, got {st}"

    st, data, _ = request_json(f"{proxy_url}/api/v1/admin/diagnoses", headers=auth_a)
    assert st == 403, f"Expected 403 for user accessing admin, got {st}"

    print("  ✓ Real Ed25519 JWT issued by Identity and verified statelessly by Diagnosis", flush=True)

    # --------------------------------------------------------------------------
    # 2. Ingestion & Replay Idempotency
    # --------------------------------------------------------------------------
    print("\n[3/11] Testing image upload ingestion and idempotency replay...", flush=True)
    img_bytes = create_synthetic_jpeg()
    idemp_key = f"key-{uuid.uuid4().hex}"

    headers_a = {**auth_a, "Idempotency-Key": idemp_key}
    st, data, hdrs = request_multipart(f"{proxy_url}/api/v1/diagnoses", img_bytes, headers=headers_a)
    assert st == 202, f"Expected 202 Accepted, got {st}: {data}"
    assert data["status"] == "PENDIENTE"
    diag_id = data["id"]
    created_at = data["created_at"]
    assert "private, no-store" in (get_header(hdrs, "cache-control") or "")
    assert get_header(hdrs, "x-correlation-id") is not None

    # Replay identical request
    st, data_replay, _ = request_multipart(f"{proxy_url}/api/v1/diagnoses", img_bytes, headers=headers_a)
    assert st == 202, f"Expected 202 on replay, got {st}: {data_replay}"
    assert data_replay["id"] == diag_id, "Replay returned different diagnosis ID"
    assert data_replay["created_at"] == created_at, "Replay returned different created_at"
    assert data_replay["status"] == "PENDIENTE"

    print("  ✓ Upload accepted (202) and idempotent replay confirmed with identical ID/timestamp", flush=True)

    # --------------------------------------------------------------------------
    # 3. A/B Isolation
    # --------------------------------------------------------------------------
    print("\n[4/11] Testing multi-tenant A/B isolation...", flush=True)

    # User B cannot access User A's diagnosis
    st, _, _ = request_json(f"{proxy_url}/api/v1/diagnoses/{diag_id}", headers=auth_b)
    assert st == 404, f"Expected 404 for User B accessing User A diagnosis, got {st}"

    # User B cannot access User A's image
    st, _, _ = request_raw(f"{proxy_url}/api/v1/diagnoses/{diag_id}/image", headers=auth_b)
    assert st == 404, f"Expected 404 for User B accessing User A image, got {st}"

    # User B cannot cancel User A's diagnosis
    st, _, _ = request_json(f"{proxy_url}/api/v1/diagnoses/{diag_id}/cancel", method="POST", headers=auth_b)
    assert st == 404, f"Expected 404 for User B cancelling User A diagnosis, got {st}"

    # User B uploading with same Idempotency-Key gets separate diagnosis
    headers_b = {**auth_b, "Idempotency-Key": idemp_key}
    st, data_b, _ = request_multipart(f"{proxy_url}/api/v1/diagnoses", img_bytes, headers=headers_b)
    assert st == 202, f"Expected 202 for User B upload, got {st}"
    assert data_b["id"] != diag_id, "User B leaked User A's diagnosis ID through idempotency key"

    print("  ✓ Multi-tenant A/B isolation strictly enforced across all operations", flush=True)

    # --------------------------------------------------------------------------
    # 4. Image Retrieval
    # --------------------------------------------------------------------------
    print("\n[5/11] Testing private S3 image retrieval...", flush=True)
    st, img_retrieved, hdrs = request_raw(f"{proxy_url}/api/v1/diagnoses/{diag_id}/image", headers=auth_a)
    assert st == 200, f"Expected 200 for image retrieval, got {st}"
    assert get_header(hdrs, "content-type") == "image/jpeg"
    assert "private, no-store" in (get_header(hdrs, "cache-control") or "")
    assert img_retrieved == img_bytes, "Retrieved image bytes do not match uploaded bytes"
    print("  ✓ Private image retrieval verified (correct bytes, Content-Type, Cache-Control)", flush=True)

    # --------------------------------------------------------------------------
    # 5. Keyset History & HMAC Cursor
    # --------------------------------------------------------------------------
    print("\n[6/11] Testing keyset history pagination and HMAC signed cursor...", flush=True)
    # Upload 2 more diagnoses for User A
    for i in range(2):
        key = f"key-hist-{i}-{uuid.uuid4().hex}"
        st, _, _ = request_multipart(f"{proxy_url}/api/v1/diagnoses", img_bytes, headers={**auth_a, "Idempotency-Key": key})
        assert st == 202

    # Request first page limit=2
    st, page1, _ = request_json(f"{proxy_url}/api/v1/diagnoses?limit=2", headers=auth_a)
    assert st == 200, f"Expected 200 for history page 1, got {st}"
    assert len(page1["items"]) == 2
    cursor = page1["next_cursor"]
    assert cursor is not None, "Expected next_cursor in page 1"

    # Request second page with cursor
    st, page2, _ = request_json(f"{proxy_url}/api/v1/diagnoses?limit=2&cursor={cursor}", headers=auth_a)
    assert st == 200, f"Expected 200 for history page 2, got {st}"
    assert len(page2["items"]) >= 1

    # Check no ID overlap between pages
    ids1 = {item["id"] for item in page1["items"]}
    ids2 = {item["id"] for item in page2["items"]}
    assert ids1.isdisjoint(ids2), "Duplicate items found across paginated pages"

    # Invalid cursor rejected with 400 INVALID_PAGINATION
    st, err_data, _ = request_json(f"{proxy_url}/api/v1/diagnoses?cursor=tampered_cursor", headers=auth_a)
    assert st == 400, f"Expected 400 for tampered cursor, got {st}"
    assert err_data["code"] == "INVALID_PAGINATION"

    # User B using User A's cursor rejected with 400 INVALID_PAGINATION
    st, err_data, _ = request_json(f"{proxy_url}/api/v1/diagnoses?cursor={cursor}", headers=auth_b)
    assert st == 400, f"Expected 400 for foreign cursor, got {st}"
    assert err_data["code"] == "INVALID_PAGINATION"

    print("  ✓ Keyset pagination and HMAC cursor integrity verified", flush=True)

    # --------------------------------------------------------------------------
    # 6. Cancellation & Tombstone Soft Delete
    # --------------------------------------------------------------------------
    print("\n[7/11] Testing cancellation and tombstone soft deletion...", flush=True)
    # Upload fresh diagnosis to cancel
    st, cancel_target, _ = request_multipart(
        f"{proxy_url}/api/v1/diagnoses",
        img_bytes,
        headers={**auth_a, "Idempotency-Key": f"cancel-target-{uuid.uuid4().hex}"},
    )
    cancel_id = cancel_target["id"]

    # Cancel PENDIENTE -> 200
    st, cancel_resp, _ = request_json(f"{proxy_url}/api/v1/diagnoses/{cancel_id}/cancel", method="POST", headers=auth_a)
    assert st == 200, f"Expected 200 on cancel, got {st}"
    assert cancel_resp["status"] == "CANCELADO"

    # Second cancel -> 409 DIAGNOSIS_NOT_CANCELABLE
    st, err, _ = request_json(f"{proxy_url}/api/v1/diagnoses/{cancel_id}/cancel", method="POST", headers=auth_a)
    assert st == 409, f"Expected 409 on second cancel, got {st}"
    assert err["code"] == "DIAGNOSIS_NOT_CANCELABLE"

    # Soft Delete -> 204
    st, _, _ = request_raw(f"{proxy_url}/api/v1/diagnoses/{cancel_id}", method="DELETE", headers=auth_a)
    assert st == 204, f"Expected 204 on delete, got {st}"

    # Repeated Delete -> 204 (idempotent)
    st, _, _ = request_raw(f"{proxy_url}/api/v1/diagnoses/{cancel_id}", method="DELETE", headers=auth_a)
    assert st == 204, f"Expected 204 on repeated delete, got {st}"

    # Subsequent GET -> 404
    st, _, _ = request_json(f"{proxy_url}/api/v1/diagnoses/{cancel_id}", headers=auth_a)
    assert st == 404, f"Expected 404 on deleted diagnosis GET, got {st}"

    # Subsequent GET image -> 404
    st, _, _ = request_raw(f"{proxy_url}/api/v1/diagnoses/{cancel_id}/image", headers=auth_a)
    assert st == 404, f"Expected 404 on deleted diagnosis image GET, got {st}"

    print("  ✓ Cancellation state machine and idempotent soft-delete tombstones verified", flush=True)

    # --------------------------------------------------------------------------
    # 7. Catalog & Admin Supervision
    # --------------------------------------------------------------------------
    print("\n[8/11] Testing public catalog, administrative management, and supervision...", flush=True)

    # Public crops
    st, crops, _ = request_json(f"{proxy_url}/api/v1/crops", headers=auth_a)
    assert st == 200, f"Expected 200 for crops, got {st}"
    crop_codes = {c["code"] for c in crops["items"]}
    assert "POTATO" in crop_codes and "MAIZE" in crop_codes

    # Public candidate conditions
    st, problems, _ = request_json(f"{proxy_url}/api/v1/crops/POTATO/problems", headers=auth_a)
    assert st == 200
    prob_codes = {p["code"] for p in problems["items"]}
    assert "POTATO_EARLY_BLIGHT" in prob_codes

    # Public recommendations (initially empty)
    st, recs, _ = request_json(f"{proxy_url}/api/v1/problems/POTATO_EARLY_BLIGHT/recommendations", headers=auth_a)
    assert st == 200
    assert recs["items"] == []

    # Admin: Update crop name
    st, updated_crop, _ = request_json(
        f"{proxy_url}/api/v1/admin/crops/POTATO",
        method="PATCH",
        payload={"name": "Papa Andina Actualizada", "active": True},
        headers=auth_admin,
    )
    assert st == 200, f"Expected 200 on admin crop patch, got {st}"
    assert updated_crop["name"] == "Papa Andina Actualizada"

    # Admin: Create recommendation version 1 with review evidence
    rec_payload = {
        "problem_code": "POTATO_EARLY_BLIGHT",
        "title": "Manejo integrado de tizón temprano en papa",
        "summary": "Prácticas culturales preventivas para mitigar Alternaria solani.",
        "cultural_practices": ["Rotación de cultivos mínimo por 2 años.", "Distanciamiento entre surcos."],
        "biological_control": ["Uso preventivo de Trichoderma spp."],
        "preventive_measures": ["Monitoreo constante de hojas basales."],
        "source_refs": ["Manual Técnico INIA 2024", "Guía FAO Papa"],
        "review_reference": "REV-2026-001",
        "reviewed_by": "Ing. Agrónomo Certificado",
        "reviewed_at": "2026-10-01T12:00:00Z",
        "active": True,
    }
    st, rec_v1, _ = request_json(
        f"{proxy_url}/api/v1/admin/recommendations",
        method="POST",
        payload=rec_payload,
        headers=auth_admin,
    )
    assert st == 201, f"Expected 201 on admin recommendation create, got {st}"
    assert rec_v1["version"] == 1
    assert rec_v1["active"] is True

    # Public recommendations now returns version 1
    st, recs_after, _ = request_json(f"{proxy_url}/api/v1/problems/POTATO_EARLY_BLIGHT/recommendations", headers=auth_a)
    assert st == 200
    assert len(recs_after["items"]) == 1
    assert recs_after["items"][0]["version"] == 1

    # Admin diagnoses supervision
    st, admin_diag, _ = request_json(f"{proxy_url}/api/v1/admin/diagnoses", headers=auth_admin)
    assert st == 200
    assert "items" in admin_diag
    for item in admin_diag["items"]:
        assert "object_key" not in item
        assert "image" not in item
        assert "feedback" not in item

    print("  ✓ Public catalog, versioned recommendations, and admin supervision verified", flush=True)

    # --------------------------------------------------------------------------
    # 8. Feedback with Terminal Fixture
    # --------------------------------------------------------------------------
    print("\n[9/11] Testing feedback submission with terminal fixture...", flush=True)

    # Insert terminal COMPLETADO fixture into database
    fixture_id = str(uuid.uuid4())
    import psycopg
    conn = psycopg.connect(
        host="postgres", port=5432, user="diagnosis",
        password=db_password, dbname="diagnosis",
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO diagnoses (
                id, owner_id, crop_code, status, object_key,
                image_sha256, image_content_type, image_size_bytes,
                class_code, raw_score, model_version,
                created_at, updated_at
            ) VALUES (
                %s, %s, 'POTATO', 'COMPLETADO', 'diagnoses/fixture/original.jpg',
                'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'image/jpeg', 1024,
                'POTATO_EARLY_BLIGHT', 0.95, 'v1.0.0',
                NOW(), NOW()
            );
            """,
            (fixture_id, user_a_id),
        )
        conn.commit()
    conn.close()

    # User A creates feedback -> 201 Created
    st, fb1, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{fixture_id}/feedback",
        method="POST",
        payload={"useful": True, "comment": "Diagnóstico preciso y de gran ayuda"},
        headers=auth_a,
    )
    assert st == 201, f"Expected 201 on initial feedback, got {st}: {fb1}"
    assert fb1["useful"] is True
    assert fb1["comment"] == "Diagnóstico preciso y de gran ayuda"

    # User A updates feedback -> 200 OK (comment omitted clears previous comment)
    st, fb2, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{fixture_id}/feedback",
        method="POST",
        payload={"useful": False},
        headers=auth_a,
    )
    assert st == 200, f"Expected 200 on feedback update, got {st}: {fb2}"
    assert fb2["useful"] is False
    assert fb2["comment"] is None

    # User B calls feedback on User A's diagnosis -> 404
    st, _, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{fixture_id}/feedback",
        method="POST",
        payload={"useful": True},
        headers=auth_b,
    )
    assert st == 404, f"Expected 404 for User B submitting feedback on foreign diagnosis, got {st}"

    # User A calls feedback on PENDIENTE diagnosis -> 409 FEEDBACK_NOT_ALLOWED
    st, fb_err, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_id}/feedback",
        method="POST",
        payload={"useful": True},
        headers=auth_a,
    )
    assert st == 409, f"Expected 409 on PENDIENTE diagnosis feedback, got {st}"
    assert fb_err["code"] == "FEEDBACK_NOT_ALLOWED"

    print("  ✓ Feedback lifecycle (201 create, 200 update, comment clearing, state check) verified", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("PHASE 1 ACCEPTANCE CHECKS PASSED!", flush=True)
    print("=" * 70, flush=True)


# ==============================================================================
# Fault Injection & Reconciler Checks (executed inside runner container)
# ==============================================================================

def run_s3_down_check(proxy_url, auth_token):
    print("\nTesting S3 failure handling (503 STORAGE_UNAVAILABLE)...", flush=True)
    img_bytes = create_synthetic_jpeg()
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Idempotency-Key": f"s3-down-{uuid.uuid4().hex}",
    }
    st, data, _ = request_multipart(f"{proxy_url}/api/v1/diagnoses", img_bytes, headers=headers)
    assert st == 503, f"Expected 503 STORAGE_UNAVAILABLE when S3 is down, got {st}: {data}"
    assert data["code"] == "STORAGE_UNAVAILABLE"
    print("  ✓ S3 failure correctly handled: returns 503 STORAGE_UNAVAILABLE", flush=True)


def run_s3_recovered_check(proxy_url, auth_token):
    print("\nTesting S3 recovery handling (202 Accepted after storage restores)...", flush=True)
    img_bytes = create_synthetic_jpeg()
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Idempotency-Key": f"s3-recovered-{uuid.uuid4().hex}",
    }
    st = None
    data = None
    for attempt in range(15):
        try:
            st, data, _ = request_multipart(f"{proxy_url}/api/v1/diagnoses", img_bytes, headers=headers)
            if st == 202:
                break
        except Exception:
            pass
        time.sleep(1)
    assert st == 202, f"Expected 202 Accepted after S3 recovery, got {st}: {data}"
    print("  ✓ Storage recovery verified: new upload accepted (202)", flush=True)


def run_sql_recovered_check(proxy_url, auth_token):
    print("\nTesting PostgreSQL recovery handling (202 Accepted after database restores)...", flush=True)
    img_bytes = create_synthetic_jpeg()
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Idempotency-Key": f"sql-recovered-{uuid.uuid4().hex}",
    }
    st = None
    data = None
    for attempt in range(15):
        try:
            st, data, _ = request_multipart(f"{proxy_url}/api/v1/diagnoses", img_bytes, headers=headers)
            if st == 202:
                break
        except Exception:
            pass
        time.sleep(1)
    assert st == 202, f"Expected 202 Accepted after SQL recovery, got {st}: {data}"
    print("  ✓ Database recovery verified: new upload accepted (202)", flush=True)


def run_sql_down_check(proxy_url, auth_token):
    print("\nTesting PostgreSQL failure handling (503 PERSISTENCE_UNAVAILABLE)...", flush=True)
    img_bytes = create_synthetic_jpeg()
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Idempotency-Key": f"sql-down-{uuid.uuid4().hex}",
    }
    st, data, _ = request_multipart(f"{proxy_url}/api/v1/diagnoses", img_bytes, headers=headers)
    assert st == 503, f"Expected 503 PERSISTENCE_UNAVAILABLE when SQL is down, got {st}: {data}"
    assert data["code"] == "PERSISTENCE_UNAVAILABLE"
    print("  ✓ Database failure correctly handled: returns 503 PERSISTENCE_UNAVAILABLE", flush=True)


def run_reconciler_check(db_password_file, s3_admin_file):
    print("\nTesting Intent Reconciler (compensation & cleanup)...", flush=True)
    import boto3
    from botocore.config import Config
    import psycopg

    db_password = Path(db_password_file).read_text().strip()
    s3_admin = json.loads(Path(s3_admin_file).read_text())

    s3_client = boto3.client(
        "s3",
        endpoint_url="http://s3:8333",
        region_name="us-east-1",
        aws_access_key_id=s3_admin["access_key"],
        aws_secret_access_key=s3_admin["secret_key"],
        config=Config(connect_timeout=3, read_timeout=3, retries={"max_attempts": 0}, s3={"addressing_style": "path"}),
    )

    # 1. Put an orphaned S3 object and insert an orphaned intent in DB
    orphan_diag_id = str(uuid.uuid4())
    orphan_key = f"diagnoses/{orphan_diag_id}/original.jpg"
    s3_client.put_object(Bucket="agro-local", Key=orphan_key, Body=b"orphan-bytes")

    # 2. Put a referenced S3 object and insert a valid diagnosis and intent
    ref_diag_id = str(uuid.uuid4())
    ref_key = f"diagnoses/{ref_diag_id}/original.jpg"
    s3_client.put_object(Bucket="agro-local", Key=ref_key, Body=b"referenced-bytes")

    conn = psycopg.connect(
        host="postgres", port=5432, user="diagnosis",
        password=db_password, dbname="diagnosis",
    )
    with conn.cursor() as cur:
        # Orphan intent (no diagnosis exists)
        cur.execute(
            """
            INSERT INTO image_upload_intents (id, diagnosis_id, object_key, owner_id, created_at)
            VALUES (%s, %s, %s, %s, NOW());
            """,
            (str(uuid.uuid4()), orphan_diag_id, orphan_key, str(uuid.uuid4())),
        )
        # Referenced diagnosis and its intent
        ref_owner_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO diagnoses (
                id, owner_id, crop_code, status, object_key,
                image_sha256, image_content_type, image_size_bytes,
                created_at, updated_at
            ) VALUES (
                %s, %s, 'POTATO', 'PENDIENTE', %s,
                'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'image/jpeg', 1024,
                NOW(), NOW()
            );
            """,
            (ref_diag_id, ref_owner_id, ref_key),
        )
        cur.execute(
            """
            INSERT INTO image_upload_intents (id, diagnosis_id, object_key, owner_id, created_at)
            VALUES (%s, %s, %s, %s, NOW());
            """,
            (str(uuid.uuid4()), ref_diag_id, ref_key, ref_owner_id),
        )
        conn.commit()
    conn.close()

    # 3. Execute reconciler
    if "/service" not in sys.path:
        sys.path.insert(0, "/service")
    from app.application.reconcile import reconcile_image_upload_intents
    from app.persistence import get_sessionmaker
    from app.storage import S3StorageAdapter

    session_maker = get_sessionmaker()
    storage = S3StorageAdapter()
    with session_maker() as db:
        stats = reconcile_image_upload_intents(db, storage, limit=50)

    print(f"  Reconciler executed: {stats}", flush=True)
    assert stats["processed"] >= 2
    assert stats["cleaned_orphans"] >= 1
    assert stats["reconciled_valid"] >= 1

    # 4. Verify orphaned S3 object deleted
    from botocore.exceptions import ClientError
    try:
        s3_client.head_object(Bucket="agro-local", Key=orphan_key)
        assert False, "Orphaned S3 object was NOT deleted by reconciler"
    except ClientError as exc:
        assert exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404

    # 5. Verify referenced S3 object PRESERVED
    resp = s3_client.head_object(Bucket="agro-local", Key=ref_key)
    assert resp["ResponseMetadata"]["HTTPStatusCode"] == 200, "Referenced S3 object was wrongly deleted"

    # 6. Verify both intents removed from DB
    conn = psycopg.connect(
        host="postgres", port=5432, user="diagnosis",
        password=db_password, dbname="diagnosis",
    )
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM image_upload_intents WHERE diagnosis_id IN (%s, %s);", (orphan_diag_id, ref_diag_id))
        count = cur.fetchone()[0]
        assert count == 0, f"Expected 0 intents remaining, found {count}"
    conn.close()

    print("  ✓ Intent reconciler verified: cleaned orphan object and intent, preserved referenced object", flush=True)


# ==============================================================================
# Host Orchestrator
# ==============================================================================

def main():
    # If invoked inside runner container
    if len(sys.argv) > 1 and sys.argv[1] == "--runner":
        mode = sys.argv[2]
        proxy_url = sys.argv[3]
        db_pwd_file = sys.argv[4]
        if mode == "acceptance":
            run_acceptance_suite(proxy_url, db_pwd_file)
        elif mode == "s3-down":
            token = sys.argv[5]
            run_s3_down_check(proxy_url, token)
        elif mode == "s3-recovered":
            token = sys.argv[5]
            run_s3_recovered_check(proxy_url, token)
        elif mode == "sql-down":
            token = sys.argv[5]
            run_sql_down_check(proxy_url, token)
        elif mode == "sql-recovered":
            token = sys.argv[5]
            run_sql_recovered_check(proxy_url, token)
        elif mode == "reconcile":
            s3_admin_file = sys.argv[5]
            run_reconciler_check(db_pwd_file, s3_admin_file)
        return

    print("Starting Isolated Full Acceptance Test (Incremento 2)...", flush=True)
    tag = f"agro-diag-acc-{uuid.uuid4().hex[:8]}"
    network = f"{tag}-net"
    containers = []

    def cleanup():
        print("\nCleaning up disposable test resources...", flush=True)
        for c in containers:
            subprocess.run(["docker", "rm", "-f", c], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "network", "rm", network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def interrupted(signum, frame):
        cleanup()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    diag_image = f"{tag}-diag"
    id_image = f"{tag}-id"

    try:
        # Create isolated Docker bridge network
        subprocess.check_call(["docker", "network", "create", network], stdout=subprocess.DEVNULL)

        with tempfile.TemporaryDirectory(prefix=f"{tag}-") as tmp_dir:
            tmp = Path(tmp_dir)
            tmp.chmod(0o755)

            # 1. Prepare keys & secrets
            prepare_identity_keys(tmp)
            (tmp / "cursor_signing_key").write_text(secrets.token_hex(32))

            db_password = secrets.token_urlsafe(32)
            (tmp / "db_password").write_text(db_password)

            s3_admin = {"access_key": secrets.token_hex(12), "secret_key": secrets.token_urlsafe(32)}
            (tmp / "s3_admin.json").write_text(json.dumps(s3_admin))

            s3_diag = {"access_key": secrets.token_hex(12), "secret_key": secrets.token_urlsafe(32)}
            (tmp / "s3_diagnosis.json").write_text(json.dumps(s3_diag))

            s3_config = {
                "identities": [
                    {
                        "name": "admin",
                        "credentials": [{"accessKey": s3_admin["access_key"], "secretKey": s3_admin["secret_key"]}],
                        "actions": ["Admin", "Read", "Write", "List", "Tagging"],
                    },
                    {
                        "name": "diagnosis",
                        "credentials": [{"accessKey": s3_diag["access_key"], "secretKey": s3_diag["secret_key"]}],
                        "actions": ["Read:agro-local", "Write:agro-local", "List:agro-local"],
                    },
                ]
            }
            (tmp / "s3_config.json").write_text(json.dumps(s3_config))

            for f in tmp.iterdir():
                f.chmod(0o644)

            # 2. Build Docker images
            print("Building Diagnosis container image...", flush=True)
            subprocess.check_call(
                ["docker", "build", "-q", "-f", str(ROOT / "services/diagnosis/Dockerfile"), "-t", diag_image, str(ROOT)],
                stdout=subprocess.DEVNULL,
            )

            print("Building Identity container image...", flush=True)
            subprocess.check_call(
                ["docker", "build", "-q", "-f", str(ROOT / "services/identity/Dockerfile"), "-t", id_image, str(ROOT)],
                stdout=subprocess.DEVNULL,
            )

            # 3. Start PostgreSQL container
            pg_container = f"{tag}-pg"
            containers.append(pg_container)
            subprocess.check_call([
                "docker", "run", "-d",
                "--name", pg_container,
                "--network", network,
                "--network-alias", "postgres",
                "-v", f"{tmp}:/secrets:ro",
                "-e", "POSTGRES_USER=postgres",
                "-e", "POSTGRES_DB=postgres",
                "-e", "POSTGRES_PASSWORD_FILE=/secrets/db_password",
                "postgres:16-alpine",
            ], stdout=subprocess.DEVNULL)

            # Wait for PostgreSQL
            for _ in range(30):
                probe = subprocess.run(["docker", "exec", pg_container, "pg_isready", "-U", "postgres"], capture_output=True)
                if probe.returncode == 0:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("PostgreSQL failed to become ready")

            # Create identity and diagnosis databases and roles
            init_sql = f"""
            CREATE ROLE identity LOGIN PASSWORD '{db_password}';
            CREATE DATABASE identity OWNER identity;
            CREATE ROLE diagnosis LOGIN PASSWORD '{db_password}';
            CREATE DATABASE diagnosis OWNER diagnosis;
            """
            subprocess.run(
                ["docker", "exec", "-i", pg_container, "psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1"],
                input=init_sql, text=True, check=True,
            )

            # 4. Start SeaweedFS container
            s3_container = f"{tag}-s3"
            containers.append(s3_container)
            subprocess.check_call([
                "docker", "run", "-d",
                "--name", s3_container,
                "--network", network,
                "--network-alias", "s3",
                "-u", "0:0",
                "-v", f"{tmp}/s3_config.json:/run/secrets/s3_config:ro",
                "chrislusf/seaweedfs:4.17",
                "server", "-dir=/data", "-ip=127.0.0.1", "-ip.bind=127.0.0.1",
                "-s3", "-s3.ip.bind=0.0.0.0", "-s3.config=/run/secrets/s3_config",
                "-master.volumeSizeLimitMB=64", "-volume.max=16", "-master.telemetry=false",
            ], stdout=subprocess.DEVNULL)

            # Wait for SeaweedFS S3
            time.sleep(2)

            # 5. Run migrations for Identity
            print("Applying Identity migrations (Alembic)...", flush=True)
            subprocess.check_call([
                "docker", "run", "--rm",
                "--network", network,
                "-v", f"{tmp}:/secrets:ro",
                "-e", "APP_ENV=local",
                "-e", "DB_HOST=postgres",
                "-e", "DB_PASSWORD_FILE=/secrets/db_password",
                "-e", "JWT_PRIVATE_KEY_PATH=/secrets/jwt_private_key.pem",
                "-e", "JWT_PUBLIC_KEY_PATH=/secrets/jwt_public_key.pem",
                "-e", "ALLOWED_ORIGINS=https://identity-test.example",
                id_image, "python", "-m", "app.migrate", "upgrade", "head",
            ], stdout=subprocess.DEVNULL)

            # Provision initial Admin account in Identity
            subprocess.check_call([
                "docker", "run", "--rm",
                "--network", network,
                "-v", f"{tmp}:/secrets:ro",
                "-e", "APP_ENV=local",
                "-e", "DB_HOST=postgres",
                "-e", "DB_PASSWORD_FILE=/secrets/db_password",
                "-e", "JWT_PRIVATE_KEY_PATH=/secrets/jwt_private_key.pem",
                "-e", "JWT_PUBLIC_KEY_PATH=/secrets/jwt_public_key.pem",
                "-e", "ALLOWED_ORIGINS=https://identity-test.example",
                id_image, "python", "-m", "app.cli", "create-admin",
                "--email", "admin@example.com",
                "--password", PASSWORD,
                "--name", "Administrator",
            ], stdout=subprocess.DEVNULL)

            # 6. Run migrations for Diagnosis
            print("Applying Diagnosis migrations (Alembic)...", flush=True)
            subprocess.check_call([
                "docker", "run", "--rm",
                "--network", network,
                "-v", f"{tmp}:/secrets:ro",
                "-e", "APP_ENV=local",
                "-e", "DB_HOST=postgres",
                "-e", "DB_PASSWORD_FILE=/secrets/db_password",
                diag_image, "python", "-m", "app.migrate", "upgrade", "head",
            ], stdout=subprocess.DEVNULL)

            # 7. Create private S3 bucket agro-local
            print("Initializing private S3 bucket agro-local...", flush=True)
            s3_setup_script = """
import json, time, boto3
from botocore.config import Config
from botocore.exceptions import ClientError
creds = json.loads(open('/secrets/s3_admin.json').read())
s3 = boto3.client('s3', endpoint_url='http://s3:8333', region_name='us-east-1',
                  aws_access_key_id=creds['access_key'], aws_secret_access_key=creds['secret_key'],
                  config=Config(connect_timeout=2, read_timeout=2, retries={'max_attempts': 0}, s3={'addressing_style': 'path'}))
for _ in range(30):
    try:
        s3.list_buckets()
        break
    except Exception:
        time.sleep(1)
try:
    s3.create_bucket(Bucket='agro-local', ACL='private')
except ClientError as e:
    pass
print('S3 bucket ready')
"""
            subprocess.check_call([
                "docker", "run", "--rm",
                "--network", network,
                "-v", f"{tmp}:/secrets:ro",
                diag_image, "python", "-c", s3_setup_script,
            ], stdout=subprocess.DEVNULL)

            # 8. Start Identity service
            id_svc = f"{tag}-identity"
            containers.append(id_svc)
            subprocess.check_call([
                "docker", "run", "-d",
                "--name", id_svc,
                "--network", network,
                "--network-alias", "identity",
                "-v", f"{tmp}:/secrets:ro",
                "-e", "APP_ENV=local",
                "-e", "DB_HOST=postgres",
                "-e", "DB_PASSWORD_FILE=/secrets/db_password",
                "-e", "JWT_PRIVATE_KEY_PATH=/secrets/jwt_private_key.pem",
                "-e", "JWT_PUBLIC_KEY_PATH=/secrets/jwt_public_key.pem",
                "-e", "ALLOWED_ORIGINS=https://identity-test.example",
                id_image,
            ], stdout=subprocess.DEVNULL)

            # 9. Start Diagnosis service
            diag_svc = f"{tag}-diagnosis"
            containers.append(diag_svc)
            subprocess.check_call([
                "docker", "run", "-d",
                "--name", diag_svc,
                "--network", network,
                "--network-alias", "diagnosis",
                "-v", f"{tmp}:/secrets:ro",
                "-e", "APP_ENV=local",
                "-e", "DB_HOST=postgres",
                "-e", "DB_PASSWORD_FILE=/secrets/db_password",
                "-e", "S3_ENDPOINT_URL=http://s3:8333",
                "-e", "S3_REGION=us-east-1",
                "-e", "S3_BUCKET=agro-local",
                "-e", "S3_CREDENTIALS_FILE=/secrets/s3_diagnosis.json",
                "-e", "JWT_PUBLIC_KEY_PATH=/secrets/jwt_public_key.pem",
                "-e", "CURSOR_SIGNING_KEY_FILE=/secrets/cursor_signing_key",
                diag_image,
            ], stdout=subprocess.DEVNULL)

            # 10. Start Nginx reverse proxy
            proxy_container = f"{tag}-proxy"
            containers.append(proxy_container)
            subprocess.check_call([
                "docker", "run", "-d",
                "--name", proxy_container,
                "--network", network,
                "--network-alias", "proxy",
                "-v", f"{ROOT}/infra/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro",
                "nginx:1.28-alpine",
            ], stdout=subprocess.DEVNULL)

            # Wait for services to settle
            time.sleep(2)

            # 11. Run Phase 1: Main Acceptance Suite
            common_runner = [
                "docker", "run", "--rm",
                "--network", network,
                "-v", f"{ROOT}:/app:ro",
                "-v", f"{tmp}:/secrets:ro",
                "-e", "APP_ENV=local",
                "-e", "DB_HOST=postgres",
                "-e", "DB_PASSWORD_FILE=/secrets/db_password",
                "-e", "S3_ENDPOINT_URL=http://s3:8333",
                "-e", "S3_REGION=us-east-1",
                "-e", "S3_BUCKET=agro-local",
                "-e", "S3_CREDENTIALS_FILE=/secrets/s3_diagnosis.json",
                "-e", "JWT_PUBLIC_KEY_PATH=/secrets/jwt_public_key.pem",
                "-e", "CURSOR_SIGNING_KEY_FILE=/secrets/cursor_signing_key",
                diag_image,
            ]

            subprocess.check_call([
                *common_runner,
                "python", "/app/scripts/check_diagnosis_acceptance.py",
                "--runner", "acceptance", "http://proxy:8080", "/secrets/db_password",
            ])

            # Obtain an auth token for fault injection tests
            login_output = subprocess.check_output([
                *common_runner,
                "python", "-c",
                """
import json, urllib.request
req = urllib.request.Request('http://proxy:8080/api/v1/auth/login',
    data=json.dumps({'email': 'admin@example.com', 'password': 'SyntheticPassword123!'}).encode('utf-8'),
    headers={'Content-Type': 'application/json', 'Origin': 'https://identity-test.example'}, method='POST')
with urllib.request.urlopen(req) as resp:
    print(json.loads(resp.read())['access_token'])
""",
            ], text=True).strip()
            auth_token = login_output

            # 12. Run Phase 2: S3 Fault Injection
            print("\n" + "=" * 70, flush=True)
            print("PHASE 2: S3 FAULT INJECTION", flush=True)
            print("=" * 70, flush=True)
            print("Stopping S3 container...", flush=True)
            subprocess.check_call(["docker", "stop", s3_container], stdout=subprocess.DEVNULL)

            subprocess.check_call([
                *common_runner,
                "python", "/app/scripts/check_diagnosis_acceptance.py",
                "--runner", "s3-down", "http://proxy:8080", "/secrets/db_password", auth_token,
            ])

            print("Restarting S3 container...", flush=True)
            subprocess.check_call(["docker", "start", s3_container], stdout=subprocess.DEVNULL)
            for _ in range(30):
                probe = subprocess.run(["docker", "exec", s3_container, "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:9333/cluster/status"], capture_output=True)
                if probe.returncode == 0:
                    break
                time.sleep(0.5)
            time.sleep(1)

            subprocess.check_call([
                *common_runner,
                "python", "/app/scripts/check_diagnosis_acceptance.py",
                "--runner", "s3-recovered", "http://proxy:8080", "/secrets/db_password", auth_token,
            ])

            # 13. Run Phase 3: SQL Fault Injection
            print("\n" + "=" * 70, flush=True)
            print("PHASE 3: SQL FAULT INJECTION", flush=True)
            print("=" * 70, flush=True)
            print("Stopping PostgreSQL container...", flush=True)
            subprocess.check_call(["docker", "stop", pg_container], stdout=subprocess.DEVNULL)

            subprocess.check_call([
                *common_runner,
                "python", "/app/scripts/check_diagnosis_acceptance.py",
                "--runner", "sql-down", "http://proxy:8080", "/secrets/db_password", auth_token,
            ])

            print("Restarting PostgreSQL container...", flush=True)
            subprocess.check_call(["docker", "start", pg_container], stdout=subprocess.DEVNULL)
            # Wait for PostgreSQL ready
            for _ in range(30):
                probe = subprocess.run(["docker", "exec", pg_container, "pg_isready", "-U", "postgres"], capture_output=True)
                if probe.returncode == 0:
                    break
                time.sleep(0.5)
            time.sleep(1)

            subprocess.check_call([
                *common_runner,
                "python", "/app/scripts/check_diagnosis_acceptance.py",
                "--runner", "sql-recovered", "http://proxy:8080", "/secrets/db_password", auth_token,
            ])

            # 14. Run Phase 4: Intent Reconciler
            print("\n" + "=" * 70, flush=True)
            print("PHASE 4: INTENT RECONCILER TEST", flush=True)
            print("=" * 70, flush=True)

            subprocess.check_call([
                *common_runner,
                "python", "/app/scripts/check_diagnosis_acceptance.py",
                "--runner", "reconcile", "http://proxy:8080", "/secrets/db_password", "/secrets/s3_admin.json",
            ])

            # 15. Architectural Boundary Verification
            print("\n" + "=" * 70, flush=True)
            print("PHASE 5: ARCHITECTURAL BOUNDARY VERIFICATION", flush=True)
            print("=" * 70, flush=True)
            print("Inspecting active containers in test network...", flush=True)
            net_inspect = json.loads(subprocess.check_output(["docker", "network", "inspect", network], text=True))
            attached_containers = net_inspect[0].get("Containers", {})
            container_names = [info["Name"] for info in attached_containers.values()]
            print(f"  Attached containers: {container_names}", flush=True)

            # Ensure zero rabbitmq, redis, ai_inference, notification containers
            forbidden = ["rabbit", "redis", "ai_inference", "notification", "mail"]
            for name in container_names:
                for f in forbidden:
                    assert f not in name.lower(), f"Forbidden component detected in test scope: {name}"

            print("  ✓ Zero broker (RabbitMQ), Redis, Email, or AI inference components present", flush=True)
            print("  ✓ Pure decoupled architecture: Diagnosis + Identity + PostgreSQL + S3 + Nginx", flush=True)

            print("\n" + "=" * 70, flush=True)
            print("ALL Task 8.2 ISOLATED ACCEPTANCE VERIFICATIONS PASSED!", flush=True)
            print("=" * 70, flush=True)

    finally:
        cleanup()
        # Clean up tagged test images
        subprocess.run(["docker", "rmi", "-f", diag_image, id_image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
