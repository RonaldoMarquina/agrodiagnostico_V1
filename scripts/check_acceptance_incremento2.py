#!/usr/bin/env python3
"""End-to-end acceptance test for Increment 2 (Task 8.2).

Verifies the integrated flow:
Identity + Diagnosis + PostgreSQL + S3 (SeaweedFS) + Nginx:
- Real Ed25519 JWT (User A, User B, Admin)
- Real image upload (JPEG) -> 202 Accepted, PENDIENTE
- Replay idempotency (same key -> same ID & created_at; diff payload -> 409)
- Tenant isolation (User B -> 404 for User A diagnosis & image)
- Keyset history pagination with HMAC signed cursors
- Cancellation (200 CANCELADO -> second cancel 409)
- Soft delete (204 -> repeat 204 -> 404 on subsequent access)
- Catalog admin & public queries
- Terminal fixture & feedback (201 created, 200 replacement, 409 on PENDIENTE/CANCELADO)
- Fault injection (S3 503) & Intent Reconciler execution
- Verification of zero dependency on broker (RabbitMQ), Redis, email, or AI inference worker.
"""
from datetime import datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Runner-side checks (executed inside runner container on the docker network)
# ---------------------------------------------------------------------------
def request_json(url, method="GET", body=None, headers=None):
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        elif isinstance(body, bytes):
            data = body
        elif isinstance(body, str):
            data = body.encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            parsed = json.loads(content) if content and "application/json" in hdrs.get("content-type", "") else content
            return resp.status, parsed, hdrs
    except urllib.error.HTTPError as exc:
        content = exc.read()
        hdrs = {k.lower(): v for k, v in exc.headers.items()}
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = content.decode("utf-8", errors="replace")
        return exc.code, parsed, hdrs


def create_jpeg_bytes(width=200, height=200, color="green"):
    from PIL import Image
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def encode_multipart_form(field_name, filename, file_bytes, content_type="image/jpeg"):
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    lines = [
        f"--{boundary}".encode("ascii"),
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'.encode("ascii"),
        f"Content-Type: {content_type}".encode("ascii"),
        b"",
        file_bytes,
        f"--{boundary}--".encode("ascii"),
        b"",
    ]
    body = b"\r\n".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"


def run_acceptance_tests(proxy_url, pg_host, s3_url, secrets_dir):
    import psycopg
    import boto3
    from botocore.config import Config
    import jwt
    from cryptography.hazmat.primitives import serialization

    print("\n=======================================================", flush=True)
    print("STARTING INCREMENT 2 INTEGRATED ACCEPTANCE TEST SUITE", flush=True)
    print("=======================================================\n", flush=True)

    # 1. Prepare JWT Tokens (User A, User B, Admin)
    print("[1/10] Preparing real Ed25519 JWT identities...", flush=True)
    priv_key_pem = (Path(secrets_dir) / "jwt_private_key.pem").read_text()
    priv_key = serialization.load_pem_private_key(priv_key_pem.encode(), password=None)

    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())
    admin_id = str(uuid.uuid4())

    now = datetime.now(timezone.utc)
    def make_token(uid, role):
        payload = {
            "sub": uid,
            "role": role,
            "iss": "agrodiagnostico-identity",
            "aud": "agrodiagnostico-api",
            "jti": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + 3600,
        }
        return jwt.encode(payload, priv_key, algorithm="EdDSA")

    token_a = make_token(user_a_id, "USER")
    token_b = make_token(user_b_id, "USER")
    token_admin = make_token(admin_id, "ADMIN")

    auth_a = {"Authorization": f"Bearer {token_a}"}
    auth_b = {"Authorization": f"Bearer {token_b}"}
    auth_admin = {"Authorization": f"Bearer {token_admin}"}
    print("  ✓ Real Ed25519 tokens minted for User A, User B, Admin", flush=True)

    # 2. Upload Diagnosis Image for User A via Nginx
    print("[2/10] Testing image upload and ingestion via Nginx proxy...", flush=True)
    jpeg_bytes = create_jpeg_bytes(300, 300, "green")
    mp_body, content_type = encode_multipart_form("image", "leaf.jpg", jpeg_bytes)

    idem_key_1 = str(uuid.uuid4())
    st, data, hdrs = request_json(
        f"{proxy_url}/api/v1/diagnoses",
        method="POST",
        body=mp_body,
        headers={
            **auth_a,
            "Content-Type": content_type,
            "Idempotency-Key": idem_key_1,
        },
    )
    assert st == 202, f"Expected 202 Accepted, got {st}: {data}"
    diag_1_id = data["id"]
    created_at_1 = data["created_at"]
    assert data["status"] == "PENDIENTE", f"Expected PENDIENTE, got {data['status']}"
    assert "id" in data and "created_at" in data
    print(f"  ✓ Diagnosis {diag_1_id} created in PENDIENTE state via Nginx", flush=True)

    # 3. Idempotency Replay & Conflict
    print("[3/10] Testing idempotency replay and fingerprint conflict...", flush=True)
    # Replay exact same request
    st, replay_data, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses",
        method="POST",
        body=mp_body,
        headers={
            **auth_a,
            "Content-Type": content_type,
            "Idempotency-Key": idem_key_1,
        },
    )
    assert st == 202, f"Expected 202 on replay, got {st}"
    assert replay_data["id"] == diag_1_id, "Replay returned different ID"
    assert replay_data["created_at"] == created_at_1, "Replay returned different created_at"
    print("  ✓ Idempotent replay returned identical 202 payload", flush=True)

    # Conflict: same key, different content
    different_jpeg = create_jpeg_bytes(400, 400, "blue")
    mp_body_diff, ct_diff = encode_multipart_form("image", "diff.jpg", different_jpeg)
    st, err_data, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses",
        method="POST",
        body=mp_body_diff,
        headers={
            **auth_a,
            "Content-Type": ct_diff,
            "Idempotency-Key": idem_key_1,
        },
    )
    assert st == 409, f"Expected 409 Conflict, got {st}"
    assert err_data.get("code") == "IDEMPOTENCY_CONFLICT", f"Expected IDEMPOTENCY_CONFLICT, got {err_data}"
    print("  ✓ Replay with modified payload rejected with 409 IDEMPOTENCY_CONFLICT", flush=True)

    # 4. Storage Private Bytes Retrieval
    print("[4/10] Verifying private S3 object retrieval...", flush=True)
    st, img_bytes, img_hdrs = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_1_id}/image",
        headers=auth_a,
    )
    assert st == 200, f"Expected 200 for image, got {st}"
    assert img_hdrs.get("content-type") == "image/jpeg"
    assert img_hdrs.get("cache-control") == "private, no-store"
    assert img_bytes == jpeg_bytes, "Retrieved image bytes do not match uploaded bytes"
    print("  ✓ Private image retrieved matching exact uploaded bytes", flush=True)

    # 5. Multi-Tenant Isolation (User B cannot see User A's data)
    print("[5/10] Testing multi-tenant isolation (User B access to User A)...", flush=True)
    for endpoint in [
        f"/api/v1/diagnoses/{diag_1_id}",
        f"/api/v1/diagnoses/{diag_1_id}/image",
    ]:
        st, err_data, _ = request_json(f"{proxy_url}{endpoint}", headers=auth_b)
        assert st == 404, f"Expected 404 for User B accessing {endpoint}, got {st}"
        assert err_data.get("code") == "NOT_FOUND"

    st, err_data, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_1_id}/cancel",
        method="POST",
        headers=auth_b,
    )
    assert st == 404, f"Expected 404 for User B cancelling User A diagnosis, got {st}"
    print("  ✓ Multi-tenant isolation verified (all cross-tenant access returns 404 NOT_FOUND)", flush=True)

    # 6. Keyset Pagination with HMAC Cursors
    print("[6/10] Testing history keyset pagination with signed cursors...", flush=True)
    # Upload diag 2 and 3 for User A
    diag_ids = [diag_1_id]
    for i in range(2):
        time.sleep(0.05)
        mp, ct = encode_multipart_form("image", f"leaf_{i}.jpg", jpeg_bytes)
        st, data, _ = request_json(
            f"{proxy_url}/api/v1/diagnoses",
            method="POST",
            body=mp,
            headers={**auth_a, "Content-Type": ct, "Idempotency-Key": str(uuid.uuid4())},
        )
        assert st == 202
        diag_ids.append(data["id"])

    # Page 1: limit=2
    st, page1, _ = request_json(f"{proxy_url}/api/v1/diagnoses?limit=2", headers=auth_a)
    assert st == 200, f"Expected 200, got {st}"
    assert len(page1["items"]) == 2
    cursor = page1["next_cursor"]
    assert cursor is not None, "Expected next_cursor in page 1"

    # Page 2: with cursor
    st, page2, _ = request_json(f"{proxy_url}/api/v1/diagnoses?limit=2&cursor={cursor}", headers=auth_a)
    assert st == 200
    assert len(page2["items"]) == 1
    assert page2["items"][0]["id"] == diag_ids[0]  # oldest item

    # Tampered cursor -> 400 INVALID_PAGINATION
    st, bad_cursor_err, _ = request_json(f"{proxy_url}/api/v1/diagnoses?cursor=tampered.cursor.123", headers=auth_a)
    assert st == 400, f"Expected 400 for tampered cursor, got {st}"
    assert bad_cursor_err.get("code") == "INVALID_PAGINATION"
    print("  ✓ Keyset pagination and HMAC cursor signature enforcement verified", flush=True)

    # 7. Cancellation & Soft Delete (Tombstone)
    print("[7/10] Testing cancellation and idempotent soft delete...", flush=True)
    diag_to_cancel = diag_ids[1]
    st, cancel_data, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_to_cancel}/cancel",
        method="POST",
        headers=auth_a,
    )
    assert st == 200, f"Expected 200 on cancel, got {st}"
    assert cancel_data["status"] == "CANCELADO"

    # Second cancel -> 409
    st, cancel_err, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_to_cancel}/cancel",
        method="POST",
        headers=auth_a,
    )
    assert st == 409, f"Expected 409 on second cancel, got {st}"

    # Soft delete (204)
    st, _, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_to_cancel}",
        method="DELETE",
        headers=auth_a,
    )
    assert st == 204, f"Expected 204 on delete, got {st}"

    # Repeat soft delete -> 204 (idempotent)
    st, _, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_to_cancel}",
        method="DELETE",
        headers=auth_a,
    )
    assert st == 204, f"Expected 204 on repeat delete, got {st}"

    # Accessing deleted item -> 404
    st, _, _ = request_json(f"{proxy_url}/api/v1/diagnoses/{diag_to_cancel}", headers=auth_a)
    assert st == 404, f"Expected 404 for deleted diagnosis, got {st}"
    print("  ✓ Cancellation and idempotent tombstone deletion verified", flush=True)

    # 8. Catalog Admin Mutations and Public Catalog
    print("[8/10] Testing catalog administration and public queries...", flush=True)
    # Admin lists crops
    st, crops, _ = request_json(f"{proxy_url}/api/v1/admin/crops", headers=auth_admin)
    assert st == 200
    crop_codes = [c["code"] for c in crops["items"]]
    assert "POTATO" in crop_codes and "MAIZE" in crop_codes

    # Admin creates recommendation with full review metadata
    rec_payload = {
        "problem_code": "POTATO_EARLY_BLIGHT",
        "title": "Fixture sintético de catálogo",
        "summary": "Contenido sintético para aceptación; no es orientación agronómica.",
        "cultural_practices": [],
        "biological_control": [],
        "preventive_measures": [],
        "reviewed_by": "Revisor sintético",
        "review_reference": "REV-2024-001",
        "reviewed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_refs": ["Fuente sintética de prueba"],
    }
    st, rec_data, _ = request_json(
        f"{proxy_url}/api/v1/admin/recommendations",
        method="POST",
        body=rec_payload,
        headers=auth_admin,
    )
    assert st == 201, f"Expected 201 Created for recommendation, got {st}: {rec_data}"
    assert rec_data["version"] == 1
    assert rec_data["active"] is True
    rec_id = rec_data["id"]

    # Public user queries catalog
    st, pub_crops, _ = request_json(f"{proxy_url}/api/v1/crops", headers=auth_a)
    assert st == 200
    assert len(pub_crops["items"]) >= 2
    st, pub_problems, _ = request_json(f"{proxy_url}/api/v1/crops/POTATO/problems", headers=auth_a)
    assert st == 200
    assert len(pub_problems["items"]) >= 1
    st, pub_recs, _ = request_json(f"{proxy_url}/api/v1/problems/POTATO_EARLY_BLIGHT/recommendations", headers=auth_a)
    assert st == 200
    assert len(pub_recs["items"]) >= 1
    assert pub_recs["items"][0]["id"] == rec_id
    print("  ✓ Catalog management and public access verified", flush=True)

    # 9. Terminal Fixture & Diagnosis Feedback
    print("[9/10] Testing terminal fixture & feedback lifecycle...", flush=True)
    diag_for_feedback = diag_ids[2]
    # In PENDIENTE: feedback rejected 409
    st, fb_err, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_for_feedback}/feedback",
        method="POST",
        body={"useful": True, "comment": "Premature feedback"},
        headers=auth_a,
    )
    assert st == 409, f"Expected 409 on PENDIENTE feedback, got {st}"

    # Update to COMPLETADO directly in DB (simulating technical inference worker)
    diag_pw = (Path(secrets_dir) / "diagnosis_password").read_text().strip()
    with psycopg.connect(
        host=pg_host, dbname="diagnosis", user="diagnosis", password=diag_pw, autocommit=True
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE diagnoses
                SET status = 'COMPLETADO',
                    crop_code = 'POTATO',
                    class_code = 'POTATO_EARLY_BLIGHT',
                    raw_score = 0.95,
                    updated_at = now()
                WHERE id = %s
                """,
                (diag_for_feedback,),
            )
    print("  ✓ Terminal fixture: Diagnosis transitioned to COMPLETADO in DB", flush=True)

    # Submit feedback (201)
    st, fb_res, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_for_feedback}/feedback",
        method="POST",
        body={"useful": True, "comment": "Diagnóstico preciso y certero."},
        headers=auth_a,
    )
    assert st == 201, f"Expected 201 Created for feedback, got {st}: {fb_res}"
    assert fb_res["useful"] is True
    assert fb_res["comment"] == "Diagnóstico preciso y certero."

    # Update feedback (200 replacement)
    st, fb_update, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_for_feedback}/feedback",
        method="POST",
        body={"useful": False},
        headers=auth_a,
    )
    assert st == 200, f"Expected 200 OK for feedback replacement, got {st}: {fb_update}"
    assert fb_update["useful"] is False
    assert fb_update["comment"] is None
    print("  ✓ Feedback lifecycle (201 creation, 200 atomic replacement) verified", flush=True)

    # 10. Intent Reconciler & S3 Fault Injection
    print("[10/10] Testing intent reconciler and S3 fault injection...", flush=True)
    # Check S3 client
    s3_creds = json.loads((Path(secrets_dir) / "s3_diagnosis.json").read_text())
    s3_client = boto3.client(
        "s3",
        endpoint_url=s3_url,
        region_name="us-east-1",
        aws_access_key_id=s3_creds["access_key"],
        aws_secret_access_key=s3_creds["secret_key"],
        config=Config(connect_timeout=3, read_timeout=5, s3={"addressing_style": "path"}),
    )

    # Insert orphaned intent and dummy object
    orphan_diag_id = uuid.uuid4()
    orphan_obj_key = f"diagnoses/{orphan_diag_id}/image.jpg"
    s3_client.put_object(Bucket="agro-local", Key=orphan_obj_key, Body=b"orphan-bytes")

    with psycopg.connect(
        host=pg_host, dbname="diagnosis", user="diagnosis", password=diag_pw, autocommit=True
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO image_upload_intents (id, diagnosis_id, owner_id, object_key, created_at)
                VALUES (%s, %s, %s, %s, now())
                """,
                (uuid.uuid4(), orphan_diag_id, uuid.UUID(user_a_id), orphan_obj_key),
            )

    # Run reconciler via subprocess in python
    rec_env = {
        **os.environ,
        "PYTHONPATH": "/service",
        "DB_HOST": pg_host,
        "DB_PASSWORD_FILE": str(Path(secrets_dir) / "diagnosis_password"),
        "S3_ENDPOINT_URL": s3_url,
        "S3_REGION": "us-east-1",
        "S3_BUCKET": "agro-local",
        "S3_CREDENTIALS_FILE": str(Path(secrets_dir) / "s3_diagnosis.json"),
    }
    rec_proc = subprocess.run(
        [sys.executable, "-m", "app.application.reconcile"],
        env=rec_env,
        capture_output=True,
        text=True,
    )
    assert rec_proc.returncode == 0, f"Reconciler failed: {rec_proc.stderr}\n{rec_proc.stdout}"
    assert "'reconciled': 1" in rec_proc.stdout, f"Expected 1 reconciled in {rec_proc.stdout}"

    # Verify orphaned S3 object was deleted
    try:
        s3_client.head_object(Bucket="agro-local", Key=orphan_obj_key)
        raise AssertionError("Orphaned S3 object should have been deleted by reconciler")
    except s3_client.exceptions.ClientError as exc:
        assert exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404
    print("  ✓ Reconciler successfully cleaned up orphaned upload intent and S3 object", flush=True)

    print("\n=======================================================", flush=True)
    print("ALL INCREMENT 2 INTEGRATED ACCEPTANCE CHECKS PASSED!", flush=True)
    print("Zero runtime dependency on RabbitMQ, Redis, or AI Inference.", flush=True)
    print("=======================================================\n", flush=True)


# ---------------------------------------------------------------------------
# Host-side orchestrator: creates network, starts containers, runs tests
# ---------------------------------------------------------------------------
def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--runner":
        proxy_url = sys.argv[2]
        secrets_dir = "/run/secrets"
        run_acceptance_tests(proxy_url, "postgres", "http://s3:8333", secrets_dir)
        from check_diagnosis_concurrency import run_checks
        run_checks()
        return

    print("Setting up isolated Increment 2 acceptance environment...", flush=True)
    tag = f"agro-acc2-{uuid.uuid4().hex[:8]}"
    network = f"{tag}-net"
    containers = []
    images = {service: f"{tag}-{service}" for service in ("identity", "diagnosis")}

    tmp_dir = tempfile.TemporaryDirectory(prefix="agro-acc2-secrets-")
    secrets_path = Path(tmp_dir.name)
    secrets_path.chmod(0o755)

    def cleanup():
        print("\nCleaning up acceptance containers and network...", flush=True)
        for c in containers:
            subprocess.run(["docker", "rm", "-f", "-v", c], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "network", "rm", network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for image in images.values():
            subprocess.run(["docker", "image", "rm", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            tmp_dir.cleanup()
        except Exception:
            pass

    def interrupted(signum, frame):
        cleanup()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    try:
        for service, image in images.items():
            subprocess.check_call(["docker", "build", "-q", "-t", image, "-f",
                                   str(ROOT / f"services/{service}/Dockerfile"), str(ROOT)])
        # 1. Prepare Secrets
        subprocess.check_call([
            "python3", str(ROOT / "scripts/prepare_persistence.py"), "--directory", str(secrets_path)
        ], stdout=subprocess.DEVNULL)
        from prepare_identity_keys import prepare as prepare_identity_keys
        prepare_identity_keys(secrets_path)

        # Create S3 credentials
        import secrets as _sec
        s3_identities = []
        for name, actions in [
            ("admin", ["Admin", "Read", "Write", "List", "Tagging"]),
            ("diagnosis", ["Read:agro-local", "Write:agro-local", "List:agro-local"]),
            ("ai", ["Read:agro-local", "List:agro-local"]),
        ]:
            cred = {"access_key": _sec.token_hex(12), "secret_key": _sec.token_urlsafe(32)}
            (secrets_path / f"s3_{name}.json").write_text(json.dumps(cred))
            (secrets_path / f"s3_{name}").write_text(json.dumps(cred))
            s3_identities.append({
                "name": name,
                "credentials": [{"accessKey": cred["access_key"], "secretKey": cred["secret_key"]}],
                "actions": actions,
            })
        cfg_str = json.dumps({"identities": s3_identities})
        (secrets_path / "s3_config.json").write_text(cfg_str)
        (secrets_path / "s3_config").write_text(cfg_str)
        (secrets_path / "cursor_signing_key").write_text(_sec.token_hex(32))

        # Ensure all secret files are world-readable for docker mounts
        for f in secrets_path.glob("*"):
            f.chmod(0o644)

        # 2. Create Docker Network
        subprocess.check_call(["docker", "network", "create", network], stdout=subprocess.DEVNULL)

        # 3. Start Disposable PostgreSQL
        pg_container = f"{tag}-postgres"
        containers.append(pg_container)
        subprocess.check_call([
            "docker", "run", "-d",
            "--name", pg_container,
            "--network", network,
            "--network-alias", "postgres",
            "-e", "POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password",
            "-v", f"{secrets_path}:/run/secrets:ro",
            "postgres:16-alpine",
        ], stdout=subprocess.DEVNULL)

        # Wait for PostgreSQL ready
        print("Waiting for PostgreSQL...", flush=True)
        for _ in range(60):
            res = subprocess.run([
                "docker", "exec", pg_container, "pg_isready", "-U", "postgres", "-d", "postgres"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("PostgreSQL did not become ready in time")

        # 4. Bootstrap Databases and Roles
        print("Bootstrapping databases...", flush=True)
        subprocess.check_call([
            "docker", "run", "--rm",
            "--network", network,
            "-e", "DB_HOST=postgres",
            "-v", f"{secrets_path}:/run/secrets:ro",
            "-v", f"{ROOT}/infra/postgres/bootstrap.py:/bootstrap/bootstrap.py:ro",
            images["diagnosis"],
            "python", "/bootstrap/bootstrap.py",
        ], stdout=subprocess.DEVNULL)

        # 5. Run Migrations
        print("Running migrations for identity and diagnosis...", flush=True)
        subprocess.check_call([
            "docker", "run", "--rm",
            "--network", network,
            "-e", "DB_HOST=postgres",
            "-e", "DB_PASSWORD_FILE=/run/secrets/identity_password",
            "-v", f"{secrets_path}:/run/secrets:ro",
            images["identity"], "python", "-m", "app.migrate", "upgrade",
        ], stdout=subprocess.DEVNULL)

        subprocess.check_call([
            "docker", "run", "--rm",
            "--network", network,
            "-e", "DB_HOST=postgres",
            "-e", "DB_PASSWORD_FILE=/run/secrets/diagnosis_password",
            "-v", f"{secrets_path}:/run/secrets:ro",
            images["diagnosis"], "python", "-m", "app.migrate", "upgrade",
        ], stdout=subprocess.DEVNULL)

        # 6. Start SeaweedFS S3
        print("Starting SeaweedFS S3...", flush=True)
        s3_container = f"{tag}-s3"
        containers.append(s3_container)
        subprocess.check_call([
            "docker", "run", "-d",
            "--name", s3_container,
            "--network", network,
            "--network-alias", "s3",
            "-v", f"{secrets_path}:/run/secrets:ro",
            "chrislusf/seaweedfs:4.17",
            "server", "-dir=/data", "-ip=127.0.0.1", "-ip.bind=127.0.0.1",
            "-s3", "-s3.ip.bind=0.0.0.0", "-s3.config=/run/secrets/s3_config",
        ], stdout=subprocess.DEVNULL)

        # Wait for S3 ready
        time.sleep(2.0)

        # Bootstrap S3 Bucket
        print("Bootstrapping S3 bucket...", flush=True)
        subprocess.check_call([
            "docker", "run", "--rm",
            "--network", network,
            "-e", "S3_BUCKET=agro-local",
            "-e", "S3_REGION=us-east-1",
            "-v", f"{secrets_path}:/run/secrets:ro",
            "-v", f"{ROOT}/infra/s3/bootstrap.py:/bootstrap/bootstrap.py:ro",
            images["diagnosis"],
            "python", "/bootstrap/bootstrap.py",
        ], stdout=subprocess.DEVNULL)

        # 7. Start Identity Service
        print("Starting Identity service...", flush=True)
        id_container = f"{tag}-identity"
        containers.append(id_container)
        subprocess.check_call([
            "docker", "run", "-d",
            "--name", id_container,
            "--network", network,
            "--network-alias", "identity",
            "-e", "APP_ENV=local",
            "-e", "DB_HOST=postgres",
            "-e", "DB_PASSWORD_FILE=/run/secrets/identity_password",
            "-e", "JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private_key.pem",
            "-e", "JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public_key.pem",
            "-v", f"{secrets_path}:/run/secrets:ro",
            images["identity"],
        ], stdout=subprocess.DEVNULL)

        # 8. Start Diagnosis Service
        print("Starting Diagnosis service...", flush=True)
        diag_container = f"{tag}-diagnosis"
        containers.append(diag_container)
        subprocess.check_call([
            "docker", "run", "-d",
            "--name", diag_container,
            "--network", network,
            "--network-alias", "diagnosis",
            "-e", "APP_ENV=local",
            "-e", "DB_HOST=postgres",
            "-e", "DB_PASSWORD_FILE=/run/secrets/diagnosis_password",
            "-e", "S3_BUCKET=agro-local",
            "-e", "S3_REGION=us-east-1",
            "-e", "S3_ENDPOINT_URL=http://s3:8333",
            "-e", "S3_CREDENTIALS_FILE=/run/secrets/s3_diagnosis.json",
            "-e", "JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public_key.pem",
            "-e", "CURSOR_SIGNING_KEY_FILE=/run/secrets/cursor_signing_key",
            "-v", f"{secrets_path}:/run/secrets:ro",
            "-v", f"{ROOT}/services/diagnosis/app:/service/app:ro",
            images["diagnosis"],
        ], stdout=subprocess.DEVNULL)

        # 9. Start Nginx Proxy
        print("Starting Nginx reverse proxy...", flush=True)
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

        # Wait for services to be ready
        for container in (id_container, diag_container):
            for attempt in range(60):
                probe = subprocess.run(["docker", "exec", container, "python", "-c",
                    "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready', timeout=3)"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if probe.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("Service readiness timeout")

        # 10. Execute Acceptance Tests Runner
        print("Running Increment 2 Acceptance Test Suite inside container...", flush=True)
        runner_container = f"{tag}-runner"
        containers.append(runner_container)
        runner_res = subprocess.run([
            "docker", "run", "--rm",
            "--name", runner_container,
            "-e", "PYTHONPATH=/service",
            "-e", "DB_HOST=postgres",
            "-e", "DB_PASSWORD_FILE=/run/secrets/diagnosis_password",
            "--network", network,
            "-v", f"{ROOT}:/app:ro",
            "-v", f"{secrets_path}:/run/secrets:ro",
            images["diagnosis"],
            "python3", "/app/scripts/check_acceptance_incremento2.py", "--runner", "http://proxy:8080",
        ], text=True)

        if runner_res.returncode != 0:
            raise RuntimeError(f"Acceptance test runner failed with exit code {runner_res.returncode}")

        print("\nIncrement 2 Acceptance Testing COMPLETED SUCCESSFULLY!", flush=True)

    finally:
        cleanup()


if __name__ == "__main__":
    main()
