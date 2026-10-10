#!/usr/bin/env python3
"""End-to-End Acceptance and Fault Matrix Test Suite for Incremento 3 (Tasks 8.1, 8.2, 8.3).

Verifies the complete asynchronous diagnosis architecture:
- PostgreSQL 16 + RabbitMQ 4.2 + SeaweedFS S3 + Identity + Diagnosis + AI Inference (2 Workers) + Nginx
- Task 8.1: Complete async flow across all three terminal states (COMPLETADO, NO_CONCLUYENTE, FALLIDO),
  JSON Schema validation (Requested v2, Analyzed v1, Finished v1) and OpenAPI contracts,
  durable Finished event accumulation in notification.diagnosis-finished.v1 without consumption.
- Task 8.2: Fault matrix from routing.json (AMQP duplicates deduplication, integrity collisions quarantine,
  stale lease 409, worker crash / lease recovery, invalid schema DLQ quarantine, terminal replay idempotency,
  broker down resilience, unroutable message return, claim/cancel race).
"""
import argparse
from datetime import datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import signal
import socket
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

from ci_support import ComposeEvidence, redact  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("async_acceptance")


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


# ==============================================================================
# RUNNER ACCEPTANCE SUITE (Executed inside runner container / on network)
# ==============================================================================

def run_acceptance_tests(proxy_url, pg_host, rabbit_host, secrets_dir):
    from cryptography.hazmat.primitives import serialization
    from jsonschema import Draft202012Validator
    import jwt
    import pika
    import psycopg

    from app.infrastructure.event_validation import (
        CONTRACTS_ROOT,
        _resolve_schema,
        get_analyzed_v1_validator,
        get_finished_v1_validator,
        get_v2_validator,
    )

    print("\n=======================================================", flush=True)
    print("STARTING INCREMENT 3 ASYNC ACCEPTANCE TEST SUITE", flush=True)
    print("=======================================================\n", flush=True)

    # Load OpenAPI and Event Validators
    diag_openapi = json.loads((CONTRACTS_ROOT / "openapi/diagnosis.openapi.json").read_text())
    val_requested_v2 = get_v2_validator()
    val_analyzed_v1 = get_analyzed_v1_validator()
    val_finished_v1 = get_finished_v1_validator()

    # 1. Prepare JWT Identities
    print("[1/10] Preparing real Ed25519 user identities...", flush=True)
    priv_key_pem = (Path(secrets_dir) / "jwt_private_key.pem").read_text()
    priv_key = serialization.load_pem_private_key(priv_key_pem.encode(), password=None)

    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    def make_user_token(uid, role="USER"):
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

    token_a = make_user_token(user_a_id)
    token_b = make_user_token(user_b_id)
    auth_a = {"Authorization": f"Bearer {token_a}"}
    auth_b = {"Authorization": f"Bearer {token_b}"}
    print("  ✓ Real Ed25519 tokens minted for User A and User B", flush=True)

    # 2. Database Seed for COMPLETADO Scenario (Potato Early Blight)
    print("[2/10] Seeding agricultural catalog problem support and recommendation in PostgreSQL...", flush=True)
    diag_pw = (Path(secrets_dir) / "diagnosis_password").read_text().strip()
    with psycopg.connect(host=pg_host, dbname="diagnosis", user="diagnosis", password=diag_pw) as conn:
        with conn.cursor() as cur:
            # Enable model_supported for POTATO_EARLY_BLIGHT
            cur.execute("UPDATE problems SET model_supported = TRUE WHERE code = 'POTATO_EARLY_BLIGHT'")
            # Check or insert active recommendation
            cur.execute("SELECT id FROM recommendations WHERE problem_code = 'POTATO_EARLY_BLIGHT' AND active = TRUE")
            rec_row = cur.fetchone()
            if not rec_row:
                rec_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO recommendations (
                        id, problem_code, version, title, summary,
                        cultural_practices, biological_control, preventive_measures, source_refs,
                        review_reference, reviewed_by, reviewed_at, active, created_at, updated_at
                    )
                    VALUES (
                        %s, 'POTATO_EARLY_BLIGHT', 1, 'FIXTURE SINTÉTICO', 'Prueba de transporte; sin orientación agronómica.',
                        '[]'::json, '[]'::json, '[]'::json, '["fixture://async-acceptance"]'::json,
                        'SYNTHETIC-ONLY', 'Automated test fixture', NOW(), TRUE, NOW(), NOW()
                    )
                """, (rec_id,))
        conn.commit()
    print("  ✓ Agricultural catalog problem and active recommendation configured", flush=True)

    # 3. Flujo 1: Carga -> Requested v2 -> Inferencia PREDICTION -> COMPLETADO (Task 8.1)
    print("[3/10] Executing Terminal Flow 1: PREDICTION -> COMPLETADO...", flush=True)
    # width=200 encodes PREDICTION fixture in simulator
    jpeg_bytes_pred = create_jpeg_bytes(width=200, height=200, color="green")
    mp_body_1, ct_1 = encode_multipart_form("image", "potato_leaf.jpg", jpeg_bytes_pred)
    idem_key_1 = str(uuid.uuid4())

    st, data_1, hdrs_1 = request_json(
        f"{proxy_url}/api/v1/diagnoses",
        method="POST",
        body=mp_body_1,
        headers={**auth_a, "Content-Type": ct_1, "Idempotency-Key": idem_key_1},
    )
    assert st == 202, f"Expected 202 Accepted, got {st}: {data_1}"
    diag_1_id = data_1["id"]
    assert data_1["status"] == "PENDIENTE"
    assert hdrs_1.get("cache-control") == "private, no-store"

    # Poll until background processing reaches COMPLETADO
    print(f"  Waiting for asynchronous pipeline to complete diagnosis {diag_1_id}...", flush=True)
    diag_1 = None
    for attempt in range(40):
        time.sleep(1.0)
        st, res, _ = request_json(f"{proxy_url}/api/v1/diagnoses/{diag_1_id}", headers=auth_a)
        assert st == 200, f"Expected 200, got {st}: {res}"
        if res["status"] == "COMPLETADO":
            diag_1 = res
            break
        elif res["status"] in ("NO_CONCLUYENTE", "FALLIDO"):
            raise AssertionError(f"Unexpected terminal status: {res['status']}")
    else:
        raise TimeoutError(f"Diagnosis {diag_1_id} did not reach COMPLETADO in time (status={res.get('status')})")

    assert diag_1["status"] == "COMPLETADO"
    assert "result" in diag_1
    res1 = diag_1["result"]
    assert res1["crop_code"] == "POTATO"
    assert res1["class_code"] == "POTATO_EARLY_BLIGHT"
    assert res1["raw_score"] is not None
    assert res1["recommendation"]["recommendation_id"] is not None
    assert res1["recommendation"]["text"] is not None

    # Validate diagnosis response conforms to OpenAPI schema
    raw_diag_schema = diag_openapi["paths"]["/api/v1/diagnoses/{id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    resolved_diag_schema = _resolve_schema(raw_diag_schema, CONTRACTS_ROOT / "openapi/diagnosis.openapi.json", CONTRACTS_ROOT)
    Draft202012Validator(resolved_diag_schema).validate(diag_1)
    print(f"  ✓ Diagnosis {diag_1_id} transitioned cleanly to COMPLETADO with immutable snapshot", flush=True)

    # 4. Flujo 2: Carga -> Requested v2 -> Inferencia ABSTENTION -> NO_CONCLUYENTE (Task 8.1)
    print("[4/10] Executing Terminal Flow 2: ABSTENTION -> NO_CONCLUYENTE...", flush=True)
    # width=201 encodes ABSTENTION fixture in simulator
    jpeg_bytes_abst = create_jpeg_bytes(width=201, height=200, color="yellow")
    mp_body_2, ct_2 = encode_multipart_form("image", "abstention_leaf.jpg", jpeg_bytes_abst)
    idem_key_2 = str(uuid.uuid4())

    st, data_2, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses",
        method="POST",
        body=mp_body_2,
        headers={**auth_a, "Content-Type": ct_2, "Idempotency-Key": idem_key_2},
    )
    assert st == 202, f"Expected 202 Accepted, got {st}: {data_2}"
    diag_2_id = data_2["id"]

    diag_2 = None
    for attempt in range(40):
        time.sleep(1.0)
        st, res, _ = request_json(f"{proxy_url}/api/v1/diagnoses/{diag_2_id}", headers=auth_a)
        assert st == 200
        if res["status"] == "NO_CONCLUYENTE":
            diag_2 = res
            break
        elif res["status"] in ("COMPLETADO", "FALLIDO"):
            raise AssertionError(f"Unexpected terminal status: {res['status']}")
    else:
        raise TimeoutError(f"Diagnosis {diag_2_id} did not reach NO_CONCLUYENTE in time (status={res.get('status')})")

    assert diag_2["status"] == "NO_CONCLUYENTE"
    assert diag_2["reason_code"] == "LOW_CONFIDENCE"
    print(f"  ✓ Diagnosis {diag_2_id} transitioned cleanly to NO_CONCLUYENTE (reason=LOW_CONFIDENCE)", flush=True)

    # 5. Flujo 3: Carga -> Requested v2 -> Inferencia FAILURE -> FALLIDO (Task 8.1)
    print("[5/10] Executing Terminal Flow 3: FAILURE -> FALLIDO...", flush=True)
    # width=202 encodes FAILURE fixture in simulator
    jpeg_bytes_fail = create_jpeg_bytes(width=202, height=200, color="red")
    mp_body_3, ct_3 = encode_multipart_form("image", "failure_leaf.jpg", jpeg_bytes_fail)
    idem_key_3 = str(uuid.uuid4())

    st, data_3, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses",
        method="POST",
        body=mp_body_3,
        headers={**auth_a, "Content-Type": ct_3, "Idempotency-Key": idem_key_3},
    )
    assert st == 202, f"Expected 202 Accepted, got {st}: {data_3}"
    diag_3_id = data_3["id"]

    diag_3 = None
    for attempt in range(40):
        time.sleep(1.0)
        st, res, _ = request_json(f"{proxy_url}/api/v1/diagnoses/{diag_3_id}", headers=auth_a)
        assert st == 200
        if res["status"] == "FALLIDO":
            diag_3 = res
            break
        elif res["status"] in ("COMPLETADO", "NO_CONCLUYENTE"):
            raise AssertionError(f"Unexpected terminal status: {res['status']}")
    else:
        raise TimeoutError(f"Diagnosis {diag_3_id} did not reach FALLIDO in time (status={res.get('status')})")

    assert diag_3["status"] == "FALLIDO"
    assert diag_3["reason_code"] == "INFERENCE_ERROR"
    print(f"  ✓ Diagnosis {diag_3_id} transitioned cleanly to FALLIDO (reason_code=INFERENCE_ERROR)", flush=True)

    # 6. Event Schema Contracts and Durable Finished Queue Verification (Task 8.1)
    print("[6/10] Validating event contracts and inspecting notification.diagnosis-finished.v1 queue...", flush=True)
    rabbit_pw = (Path(secrets_dir) / "rabbit_password").read_text().strip()
    credentials = pika.PlainCredentials("agro_local", rabbit_pw)
    conn_params = pika.ConnectionParameters(host=rabbit_host, credentials=credentials, socket_timeout=10)

    with pika.BlockingConnection(conn_params) as rabbit_conn:
        ch = rabbit_conn.channel()

        # Check notification queue: durable, accumulating finished events, no consumer
        message_count = 0
        consumer_count = 0
        for _ in range(15):
            q_dec = ch.queue_declare(queue="notification.diagnosis-finished.v1", durable=True, passive=True)
            message_count = q_dec.method.message_count
            consumer_count = q_dec.method.consumer_count
            if message_count >= 3:
                break
            time.sleep(1.0)

        print(f"  notification.diagnosis-finished.v1 status: messages={message_count}, consumers={consumer_count}", flush=True)
        assert message_count >= 3, f"Expected at least 3 accumulated Finished events, found {message_count}"
        assert consumer_count == 0, f"Expected 0 consumers on Finished queue in Incremento 3, found {consumer_count}"

        # Inspect outbox events from PostgreSQL to validate schemas
        with psycopg.connect(host=pg_host, dbname="diagnosis", user="diagnosis", password=diag_pw) as pg_conn:
            with pg_conn.cursor() as cur:
                cur.execute("SELECT envelope FROM diagnosis_outbox WHERE event_type = 'DiagnosisRequested'")
                req_envelopes = [row[0] for row in cur.fetchall()]
                cur.execute("SELECT envelope FROM diagnosis_outbox WHERE event_type = 'DiagnosisFinished'")
                fin_envelopes = [row[0] for row in cur.fetchall()]

        # Validate DiagnosisRequested v2
        assert len(req_envelopes) >= 3, f"Expected >= 3 Requested envelopes, got {len(req_envelopes)}"
        for env in req_envelopes:
            val_requested_v2.validate(env)

        # Validate DiagnosisFinished v1
        assert len(fin_envelopes) >= 3, f"Expected >= 3 Finished envelopes, got {len(fin_envelopes)}"
        for env in fin_envelopes:
            val_finished_v1.validate(env)

        # Validate DiagnosisAnalyzed v1 from ai_inference outbox
        ai_pw_path = Path(secrets_dir) / "ai_inference_password"
        if ai_pw_path.exists():
            ai_pw = ai_pw_path.read_text().strip()
            with psycopg.connect(host=pg_host, dbname="ai_inference", user="ai_inference", password=ai_pw) as ai_pg_conn:
                with ai_pg_conn.cursor() as cur:
                    cur.execute("SELECT envelope FROM inference_outbox WHERE event_type = 'DiagnosisAnalyzed'")
                    ana_envelopes = [row[0] for row in cur.fetchall()]
            assert len(ana_envelopes) >= 3, f"Expected >= 3 Analyzed envelopes, got {len(ana_envelopes)}"
            for env in ana_envelopes:
                val_analyzed_v1.validate(env)

    print("  ✓ Event envelopes and payloads conform strictly to JSON Schemas (Requested v2, Analyzed v1, Finished v1)", flush=True)
    print("  ✓ Durable Finished events remain accumulated without simulate Notification (pending Incremento 5)", flush=True)

    # Publish real broker deliveries, then observe consumer-owned persistence.
    import copy
    import pika
    credentials = pika.PlainCredentials("agro_local", (Path(secrets_dir) / "rabbit_password").read_text().strip())
    broker = pika.BlockingConnection(pika.ConnectionParameters(host=rabbit_host, credentials=credentials))
    channel = broker.channel()
    channel.confirm_delivery()

    def publish(envelope, routing_key="diagnosis.analyzed.v1"):
        channel.basic_publish(exchange="agrodiagnostico.events", routing_key=routing_key,
                              body=json.dumps(envelope).encode(), mandatory=True,
                              properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"))

    def query(sql, params=()):
        with psycopg.connect(host=pg_host, dbname="diagnosis", user="diagnosis", password=diag_pw) as connection:
            return connection.execute(sql, params).fetchone()[0]

    def eventually(check, label, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(0.25)
        raise AssertionError(label)

    original = ana_envelopes[0]
    event_id = original["event_id"]
    before = query("SELECT count(*) FROM diagnosis_outbox WHERE event_type='DiagnosisFinished'")
    publish(original)
    collision = copy.deepcopy(original)
    collision["correlation_id"] = str(uuid.uuid4())
    publish(collision)
    eventually(lambda: query("SELECT count(*) FROM diagnosis_quarantine_messages WHERE event_id=%s", (event_id,)) == 1,
               "Broker collision was not quarantined")
    assert query("SELECT count(*) FROM diagnosis_inbox WHERE event_id=%s", (event_id,)) == 1
    assert query("SELECT count(*) FROM diagnosis_outbox WHERE event_type='DiagnosisFinished'") == before
    unknown = copy.deepcopy(original)
    unknown["event_id"] = str(uuid.uuid4())
    unknown["schema_version"] = 99
    publish(unknown)
    eventually(lambda: query("SELECT count(*) FROM diagnosis_quarantine_messages WHERE event_id=%s", (unknown["event_id"],)) == 1,
               "Unknown version was not quarantined")
    try:
        publish(original, "acceptance.no.route")
    except pika.exceptions.UnroutableError:
        pass
    else:
        raise AssertionError("Mandatory unroutable publication was not returned")
    finished = channel.queue_declare(queue="notification.diagnosis-finished.v1", passive=True)
    assert finished.method.message_count >= 3, "Finished must remain durable without Notification consumer"
    broker.close()
    print("  ✓ Real AMQP duplicate, collision, unknown version, mandatory return and Finished retention", flush=True)

    # 8. Fault Matrix: Stale Lease 409 & Claim/Cancel Race (Task 8.2)
    print("[8/10] Testing fault matrix: Stale lease rejection (409) and Claim/Cancel exclusivity...", flush=True)
    # Stale Lease: Authenticated internal service call with invalid lease token returns 409 STALE_LEASE
    priv_w1_path = Path(secrets_dir) / "internal_worker_1_private_key.pem"
    if True:  # Required fixture: missing signing key must fail acceptance.
        priv_w1_pem = priv_w1_path.read_text().strip()
        priv_w1 = serialization.load_pem_private_key(priv_w1_pem.encode(), password=None)
        w1_payload = {
            "iss": "agrodiagnostico-internal",
            "aud": "diagnosis-internal",
            "sub": "ai_inference",
            "instance_id": "worker-1",
            "jti": str(uuid.uuid4()),
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
        }
        w1_token = jwt.encode(w1_payload, priv_w1, algorithm="EdDSA", headers={"kid": "worker-1-key"})
        st_renew, resp_renew, _ = request_json(
            f"http://diagnosis:8000/internal/diagnoses/{diag_1_id}/lease/renew",
            method="POST",
            body={"lease_token": str(uuid.uuid4())},
            headers={"Authorization": f"Bearer {w1_token}"},
        )
        assert st_renew == 409, f"Expected 409 STALE_LEASE, got {st_renew}: {resp_renew}"
        assert resp_renew.get("code") == "STALE_LEASE"
        print("  ✓ Internal stale lease renew rejected with 409 STALE_LEASE", flush=True)

    # External Cancel on terminal diagnosis: DIAGNOSIS_NOT_CANCELABLE (409)
    st, resp, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_1_id}/cancel",
        method="POST",
        headers=auth_a,
    )
    assert st == 409, f"Expected 409 CANCEL on terminal diagnosis, got {st}: {resp}"
    assert resp.get("code") == "DIAGNOSIS_NOT_CANCELABLE"

    # Multi-tenant isolation: User B cancel on User A's diagnosis returns 404
    st, resp, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{diag_1_id}/cancel",
        method="POST",
        headers=auth_b,
    )
    assert st == 404, f"Expected 404 for User B cancelling User A diagnosis, got {st}"

    # Claim/Cancel race on fresh PENDIENTE diagnosis:
    jpeg_bytes_race = create_jpeg_bytes(width=200, height=200, color="gray")
    mp_race, ct_race = encode_multipart_form("image", "race.jpg", jpeg_bytes_race)
    st, data_race, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses",
        method="POST",
        body=mp_race,
        headers={**auth_a, "Content-Type": ct_race, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert st == 202
    race_id = data_race["id"]

    # Cancel immediately
    st_cancel, resp_cancel, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses/{race_id}/cancel",
        method="POST",
        headers=auth_a,
    )
    # Either cancel wins (200) before worker claim or worker claimed it first (409)
    assert st_cancel in (200, 409), f"Expected 200 or 409 on cancel, got {st_cancel}: {resp_cancel}"
    if st_cancel == 200:
        assert resp_cancel["status"] == "CANCELADO"
        st_cancel_2, resp_cancel_2, _ = request_json(
            f"{proxy_url}/api/v1/diagnoses/{race_id}/cancel",
            method="POST",
            headers=auth_a,
        )
        assert st_cancel_2 == 409, f"Expected 409 on second Cancel, got {st_cancel_2}"
        assert resp_cancel_2.get("code") == "DIAGNOSIS_NOT_CANCELABLE"
    print("  ✓ Stale cancel and single-winner cancellation race verified", flush=True)

    # 9. Fault Matrix: Replay Operativo & Invariantes Terminales (Task 8.2)
    print("[9/10] Testing fault matrix: Replay operativo auditado sin revivir terminales...", flush=True)
    with psycopg.connect(host=pg_host, dbname="diagnosis", user="diagnosis", password=diag_pw) as pg_conn:
        with pg_conn.cursor() as cur:
            # Query outbox row for diag_1
            cur.execute("SELECT event_id, envelope FROM diagnosis_outbox WHERE diagnosis_id = %s AND event_type = 'DiagnosisRequested'", (diag_1_id,))
            row = cur.fetchone()
            assert row is not None, "Missing outbox row for diag_1"
            evt_id_1, env_1 = row

            completed = subprocess.run([
                sys.executable, "-m", "app.replay", "--actor", "async-acceptance",
                "--reason", "synthetic terminal redelivery", "--event-id", str(evt_id_1), "--apply",
            ], capture_output=True, text=True, timeout=20)
            assert completed.returncode == 0, completed.stderr
            eventually(lambda: query("SELECT count(*) FROM diagnosis_outbox WHERE event_id=%s AND sent_at IS NOT NULL", (evt_id_1,)) == 1,
                       "Replayed outbox was not confirmed by broker")
            assert query("SELECT count(*) FROM diagnosis_audit_logs WHERE action='OPERATIONAL_REPLAY'") >= 1

            # Verify terminal state unchanged (COMPLETADO never revives to PROCESANDO)
            cur.execute("SELECT status FROM diagnoses WHERE id = %s", (diag_1_id,))
            status_now = cur.fetchone()[0]
            assert status_now == "COMPLETADO", f"Expected COMPLETADO, got {status_now}"
    print("  ✓ Operational replay audit and terminal immutability verified", flush=True)

    # 10. Resilience: Broker Down Ingestion & Health Independence (Task 8.2)
    print("[10/10] Testing resilience: Ingestion and readiness with broker decoupled...", flush=True)
    # /health/ready relies solely on DB and S3
    st_ready, ready_data, _ = request_json(f"{proxy_url}/health/ready")
    # Through proxy /health returns 404 by default (blocked at edge)
    # Let's verify through proxy that external access to /health is blocked (404)
    assert st_ready == 404, f"Proxy must return 404 for /health, got {st_ready}"

    # Ingestion via proxy creates outbox in PostgreSQL transactionally
    jpeg_bytes_res = create_jpeg_bytes(width=200, height=200, color="purple")
    mp_res, ct_res = encode_multipart_form("image", "resilience.jpg", jpeg_bytes_res)
    st_res, data_res, _ = request_json(
        f"{proxy_url}/api/v1/diagnoses",
        method="POST",
        body=mp_res,
        headers={**auth_a, "Content-Type": ct_res, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert st_res == 202, f"Expected 202 Accepted, got {st_res}"
    res_id = data_res["id"]

    with psycopg.connect(host=pg_host, dbname="diagnosis", user="diagnosis", password=diag_pw) as pg_conn:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT status FROM diagnoses WHERE id = %s", (res_id,))
            assert cur.fetchone()[0] in ("PENDIENTE", "PROCESANDO", "COMPLETADO")
            cur.execute("SELECT count(*) FROM diagnosis_outbox WHERE diagnosis_id = %s", (res_id,))
            assert cur.fetchone()[0] >= 1, "Outbox event must be persisted transactionally"
    print("  ✓ Ingestion and outbox persistence verified; outage tested separately by orchestrator", flush=True)

    print("\n=======================================================", flush=True)
    print("BASE ASYNC FLOW VERIFIED; ORCHESTRATOR FAULT MATRIX FOLLOWS", flush=True)
    print("=======================================================\n", flush=True)


# ==============================================================================
# MAIN ORCHESTRATOR
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", help="Run acceptance tests against specified proxy URL")
    parser.add_argument("--pg-host", default="postgres", help="PostgreSQL host")
    parser.add_argument("--rabbit-host", default="rabbitmq", help="RabbitMQ host")
    parser.add_argument("--secrets-dir", default="/run/secrets", help="Secrets directory")
    args = parser.parse_args()

    # If --runner is passed, execute tests directly
    if args.runner:
        run_acceptance_tests(
            proxy_url=args.runner.rstrip("/"),
            pg_host=args.pg_host,
            rabbit_host=args.rabbit_host,
            secrets_dir=args.secrets_dir,
        )
        return

    # Otherwise, spin up isolated Compose / Docker acceptance environment
    tag = f"agro-acc3-{uuid.uuid4().hex[:8]}"
    project = f"agro-env-test-{uuid.uuid4().hex[:12]}"
    os.environ.setdefault("AGRO_CI_ARTIFACTS", str(ROOT / ".local/ci/async"))
    evidence = ComposeEvidence(project)
    print(f"Setting up isolated Increment 3 acceptance environment ({tag}, project={project})...", flush=True)

    tmp_dir = tempfile.TemporaryDirectory(prefix="agro-acc3-secrets-")
    secrets_path = Path(tmp_dir.name)
    secrets_path.chmod(0o755)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    config_env = secrets_path / "config.env"
    config_env.write_text(
        f"APP_ENV=local\nASYNC_CONSUMER_ENV=test\n"
        f"HTTP_PORT={port}\n"
        f"ENABLE_SIMULATED_INFERENCE=true\n"
        f"S3_BUCKET=agro-local\n"
        f"S3_REGION=us-east-1\n"
        f"PERSISTENCE_SECRETS_DIR={secrets_path}\n"
        f"LOCAL_UID={os.getuid()}\n"
        f"LOCAL_GID={os.getgid()}\n"
    )

    env = dict(os.environ)
    base_compose = [
        "docker", "compose",
        "--env-file", str(config_env),
        "-p", project,
        "-f", str(ROOT / "docker-compose.yml"),
    ]
    tracked_secrets = []

    def run_cmd(args, timeout=300):
        res = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
        out = res.stdout + res.stderr
        evidence.record(out, tracked_secrets)
        if res.returncode != 0:
            print(redact(out[-5000:], tracked_secrets), flush=True)
            raise RuntimeError(f"Command failed with exit code {res.returncode}: {' '.join(args[:4])}")
        return res.stdout

    def cleanup():
        print("\nCleaning up acceptance containers and network...", flush=True)
        try:
            for s in ["diagnosis-consumer", "ai_inference-worker-1", "ai_inference-publisher", "diagnosis-publisher", "ai_inference", "diagnosis"]:
                res_logs = subprocess.run(base_compose + ["logs", "--tail", "100", s], env=env, capture_output=True, text=True, timeout=10)
                if res_logs.stdout.strip():
                    print(f"--- Container logs: {s} ---:\n" + redact(res_logs.stdout[-6000:], tracked_secrets) + "\n-------------------------------------", flush=True)
        except Exception:
            pass
        try:
            evidence.collect(base_compose, env, tracked_secrets)
        except Exception:
            pass
        subprocess.run(base_compose + ["--profile", "async-test", "down", "-v", "--remove-orphans", "--rmi", "local"], env=env, timeout=120, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            tmp_dir.cleanup()
        except Exception:
            pass
        evidence.verify_cleanup()

    def interrupted(signum, frame):
        cleanup()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    try:
        # 1. Prepare persistence and local keys
        print("Preparing secrets and Ed25519 internal keys...", flush=True)
        subprocess.check_call(["python3", str(ROOT / "scripts/prepare_local.py"), "--directory", str(secrets_path)], stdout=subprocess.DEVNULL)
        for p in secrets_path.iterdir():
            if p.name.endswith("_password") or p.name in ("rabbit_cookie", "cursor_signing_key"):
                tracked_secrets.append(p.read_text().strip())
            elif p.name in ("s3_admin.json", "s3_ai.json", "s3_diagnosis.json"):
                tracked_secrets.extend(json.loads(p.read_text()).values())
            # Ensure secrets are world-readable for container mapped mounts
            p.chmod(0o644)
        secrets_path.chmod(0o755)

        # 2. Build images if necessary
        print("Building images with async-test profile...", flush=True)
        run_cmd(base_compose + ["--profile", "async-test", "build"], timeout=900)

        # 3. Boot containers and wait for health
        print("Booting containers and background processes...", flush=True)
        run_cmd(base_compose + ["--profile", "async-test", "up", "-d", "--wait", "--wait-timeout", "180"], timeout=240)
        print("  ✓ All services healthy and ready", flush=True)

        # 4. Verify that only proxy publishes host port
        ids = run_cmd(base_compose + ["ps", "-q"]).split()
        containers_info = json.loads(run_cmd(["docker", "inspect", *ids]))
        for c in containers_info:
            svc = c["Config"]["Labels"]["com.docker.compose.service"]
            bindings = c["HostConfig"]["PortBindings"] or {}
            if svc == "nginx":
                assert bindings == {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(port)}]}, f"Nginx bindings mismatch: {bindings}"
            else:
                assert not bindings, f"Service '{svc}' unexpectedly published ports to host: {bindings}"
        print("  ✓ Verified: only Nginx proxy publishes host port on loopback", flush=True)

        # 5. Execute acceptance test runner inside container network
        print("Executing Increment 3 Acceptance Test Suite inside container network...", flush=True)
        runner_cmd = [
            "docker", "compose",
            "--env-file", str(config_env),
            "-p", project,
            "-f", str(ROOT / "docker-compose.yml"),
            "run", "--rm",
            "-e", "PYTHONPATH=/service",
            "-v", f"{ROOT}:/app:ro",
            "-v", f"{secrets_path}:/test_secrets:ro",
            "diagnosis",
            "python3", "/app/scripts/check_async_acceptance.py",
            "--runner", "http://nginx:8080",
            "--pg-host", "postgres",
            "--rabbit-host", "rabbitmq",
            "--secrets-dir", "/test_secrets",
        ]
        out = run_cmd(runner_cmd, timeout=300)
        print(out, flush=True)
        probe = runner_cmd[:runner_cmd.index("python3")] + ["python3", "/app/scripts/async_outage_probe.py"]
        run_cmd(base_compose + ["stop", "rabbitmq", "redis"])
        outage = run_cmd(probe[:probe.index("run")+1] + ["--no-deps"] + probe[probe.index("run")+1:])
        print(outage, flush=True)
        outage_id = next(line.split("=", 1)[1] for line in outage.splitlines() if line.startswith("OUTAGE_DIAG="))
        run_cmd(base_compose + ["start", "rabbitmq", "redis"])
        print(run_cmd(probe + [outage_id], timeout=180), flush=True)
        state = secrets_path / "test-state"
        state.mkdir(mode=0o777)
        state.chmod(0o777)
        run_cmd(base_compose + ["stop", "ai_inference-worker-1", "ai_inference-worker-2"])
        crash_probe = base_compose + ["run", "--rm", "--no-deps", "-e", "PYTHONPATH=/service",
            "-v", f"{ROOT}:/app:ro", "-v", f"{secrets_path}:/test_secrets:ro",
            "-v", f"{state}:/test_state", "ai_inference-worker-1", "python3", "/app/scripts/async_worker_crash_probe.py"]
        race_probe = base_compose + ["run", "--rm", "--no-deps", "-e", "PYTHONPATH=/service",
            "-v", f"{ROOT}:/app:ro", "-v", f"{secrets_path}:/test_secrets:ro",
            "diagnosis", "python3", "/app/scripts/async_claim_cancel_probe.py"]
        print(run_cmd(race_probe, timeout=60), flush=True)
        print(run_cmd(crash_probe, timeout=200), flush=True)
        run_cmd(base_compose + ["start", "ai_inference-worker-1", "ai_inference-worker-2"])
        print(run_cmd(crash_probe + ["verify-file"], timeout=180), flush=True)
        run_cmd(base_compose + ["stop", "diagnosis-publisher"])
        publisher_probe = base_compose + ["run", "--rm", "--no-deps", "-e", "PYTHONPATH=/service",
            "-v", f"{ROOT}:/app:ro", "-v", f"{secrets_path}:/test_secrets:ro",
            "-v", f"{state}:/test_state", "diagnosis", "python3", "/app/scripts/async_publisher_crash_probe.py"]
        print(run_cmd(publisher_probe, timeout=90), flush=True)
        run_cmd(base_compose + ["start", "diagnosis-publisher"])
        print(run_cmd(publisher_probe + ["verify"], timeout=150), flush=True)
        run_cmd(base_compose + ["stop", "diagnosis-recovery", "ai_inference-worker-1", "ai_inference-worker-2"])
        recovery_probe = publisher_probe[:-1] + ["/app/scripts/async_recovery_probe.py"]
        print(run_cmd(recovery_probe, timeout=60), flush=True)
        print("\nIncrement 3 Acceptance Testing COMPLETED SUCCESSFULLY!", flush=True)

    finally:
        cleanup()


if __name__ == "__main__":
    main()
