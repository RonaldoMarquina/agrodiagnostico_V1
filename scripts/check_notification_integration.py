#!/usr/bin/env python3
"""End-to-End Integration Acceptance Suite for Notification service (Incremento 5, Task 7.1).

Verifies in an isolated disposable Compose project:
- Full stack via Nginx: Identity + Diagnosis + AI Inference (async-test) + Notification + Notification Consumer.
- External proxy isolation: /internal/users/{id}/contact -> 404; /api/v1/notifications -> 401.
- User registration/login, default email_enabled=false, strict PATCH validation, opt-in email_enabled=true.
- Real DiagnosisFinished v1 -> notification-consumer -> internal notification + Identity internal contact -> email SENT.
- Idempotent PATCH /api/v1/notifications/{id}/read preserving original read_at, 404 isolation, keyset pagination & foreign cursor 400.
- Internal Identity endpoint security: 401 missing, 403 user Bearer, 403 ai_inference worker, 200 notification-1, 404 missing UUID.
- Real RabbitMQ quarantine & DLQ publication on unknown schema_version and event_id collision.
- Durable retention when notification-consumer is stopped + SMTP delivery failure isolation (notification created, diagnosis untouched, attempt FAILED_RETRYABLE).
- Zero secret leaks and strict disposable cleanup.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import stat
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

from ci_support import ComposeEvidence  # noqa: E402


def http_json(url, method="GET", body=None, headers=None):
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
            raw = resp.read()
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            parsed = json.loads(raw) if raw and "application/json" in hdrs.get("content-type", "") else raw
            return resp.status, parsed, hdrs
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        hdrs = {k.lower(): v for k, v in exc.headers.items()}
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw.decode("utf-8", errors="replace")
        return exc.code, parsed, hdrs


def _minimal_png_bytes():
    import struct
    import zlib

    width, height = 16, 16
    raw = b"".join(b"\x00" + b"\x40\x90\x40" * width for _ in range(height))

    def chunk(tag, payload):
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _encode_multipart(field_name, filename, file_bytes, content_type="image/png"):
    boundary = f"----AgroNotifTest{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("ascii") + file_bytes + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, f"multipart/form-data; boundary={boundary}"


def _eventually(fn, timeout=30.0, interval=0.5, label="condition"):
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            val = fn()
            if val:
                return val
        except AssertionError as exc:
            last_err = exc
        time.sleep(interval)
    raise AssertionError(f"Timeout waiting for {label}: {last_err}")


def run_in_network_checks(proxy_url, identity_url, pg_host, rabbit_host, secrets_dir):
    import jwt
    import pika
    import psycopg

    secrets = Path(secrets_dir)
    notif_pw = (secrets / "notification_password").read_text().strip()
    diag_pw = (secrets / "diagnosis_password").read_text().strip()
    rabbit_pw = (secrets / "rabbit_password").read_text().strip()
    notif_priv = (secrets / "internal_notification_1_private_key.pem").read_text().strip()
    worker_priv = (secrets / "internal_worker_1_private_key.pem").read_text().strip()

    origin_hdr = {"Origin": "http://127.0.0.1:8080"}

    # 1. External proxy isolation
    st, _, _ = http_json(f"{proxy_url}/internal/users/{uuid.uuid4()}/contact")
    assert st == 404, f"Expected 404 on external /internal/users/*/contact, got {st}"
    st, body, hdrs = http_json(f"{proxy_url}/api/v1/notifications")
    assert st == 401 and hdrs.get("cache-control") == "private, no-store"
    uuid.UUID(hdrs["x-correlation-id"])
    print("[1/7] External proxy isolation and unauthenticated 401 PASS", flush=True)

    # 2. Register and login two real users via Identity
    def register_and_login(email, name):
        st_r, prof, _ = http_json(
            f"{proxy_url}/api/v1/auth/register",
            method="POST",
            body={"email": email, "password": "StrongPassword123!", "display_name": name},
        )
        assert st_r == 201, f"Register failed: {st_r} {prof}"
        st_l, sess, _ = http_json(
            f"{proxy_url}/api/v1/auth/login",
            method="POST",
            body={"email": email, "password": "StrongPassword123!"},
            headers=origin_hdr,
        )
        assert st_l == 200, f"Login failed: {st_l} {sess}"
        return prof["id"], sess["access_token"]

    user_a_id, tok_a = register_and_login("notif_a@example.test", "Usuario A")
    user_b_id, tok_b = register_and_login("notif_b@example.test", "Usuario B")
    hdr_a = {"Authorization": f"Bearer {tok_a}"}
    hdr_b = {"Authorization": f"Bearer {tok_b}"}
    print("[2/7] Real Identity register/login PASS", flush=True)

    # 3. Preferences default false, validation 400, opt-in true for user A only
    st, pref_a, _ = http_json(f"{proxy_url}/api/v1/notification-preferences", headers=hdr_a)
    assert st == 200 and pref_a == {"email_enabled": False}
    st_bad, _, _ = http_json(
        f"{proxy_url}/api/v1/notification-preferences",
        method="PATCH",
        body={"email_enabled": "true"},
        headers=hdr_a,
    )
    assert st_bad == 400
    st, pref_a2, _ = http_json(
        f"{proxy_url}/api/v1/notification-preferences",
        method="PATCH",
        body={"email_enabled": True},
        headers=hdr_a,
    )
    assert st == 200 and pref_a2 == {"email_enabled": True}
    st, pref_b, _ = http_json(f"{proxy_url}/api/v1/notification-preferences", headers=hdr_b)
    assert st == 200 and pref_b == {"email_enabled": False}
    print("[3/7] Notification preferences default=false and opt-in PATCH PASS", flush=True)

    # 4. Internal Identity contact endpoint auth matrix
    def sign_internal(priv, kid, inst, sub, aud):
        now = int(time.time())
        return jwt.encode(
            {
                "iss": "agrodiagnostico-internal",
                "aud": aud,
                "sub": sub,
                "instance_id": inst,
                "iat": now,
                "exp": now + 60,
                "jti": str(uuid.uuid4()),
            },
            priv,
            algorithm="EdDSA",
            headers={"kid": kid},
        )

    st, _, _ = http_json(f"{identity_url}/internal/users/{user_a_id}/contact")
    assert st == 401
    st, _, _ = http_json(f"{identity_url}/internal/users/{user_a_id}/contact", headers=hdr_a)
    assert st == 403
    worker_tok = sign_internal(worker_priv, "worker-1-key", "worker-1", "ai_inference", "identity-internal")
    st, _, _ = http_json(
        f"{identity_url}/internal/users/{user_a_id}/contact",
        headers={"Authorization": f"Bearer {worker_tok}"},
    )
    assert st == 403
    notif_tok = sign_internal(notif_priv, "notification-1-key", "notification-1", "notification", "identity-internal")
    st, contact, _ = http_json(
        f"{identity_url}/internal/users/{user_a_id}/contact",
        headers={"Authorization": f"Bearer {notif_tok}"},
    )
    assert st == 200 and contact == {"user_id": user_a_id, "email": "notif_a@example.test", "active": True}
    st, _, _ = http_json(
        f"{identity_url}/internal/users/{uuid.uuid4()}/contact",
        headers={"Authorization": f"Bearer {notif_tok}"},
    )
    assert st == 404
    print("[4/7] Internal Identity contact security matrix (401/403/200/404) PASS", flush=True)

    # 5. End-to-end Diagnosis -> DiagnosisFinished -> notification-consumer -> Notification API & email SENT
    png_bytes = _minimal_png_bytes()

    def upload_diagnosis(token, key_suffix):
        mp_body, mp_ct = _encode_multipart("image", f"leaf-{key_suffix}.png", png_bytes)
        st_u, res_u, _ = http_json(
            f"{proxy_url}/api/v1/diagnoses",
            method="POST",
            body=mp_body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": mp_ct,
                "Idempotency-Key": f"notif-e2e-{key_suffix}",
            },
        )
        assert st_u == 202, f"Upload failed: {st_u} {res_u}"
        return res_u["id"]

    diag_a1 = upload_diagnosis(tok_a, "a1")
    diag_a2 = upload_diagnosis(tok_a, "a2")
    diag_b1 = upload_diagnosis(tok_b, "b1")

    def wait_notifications(headers, expected_count):
        st_n, page, _ = http_json(f"{proxy_url}/api/v1/notifications", headers=headers)
        assert st_n == 200
        return page if len(page["items"]) >= expected_count else None

    page_a = _eventually(lambda: wait_notifications(hdr_a, 2), timeout=45, label="user A notifications")
    page_b = _eventually(lambda: wait_notifications(hdr_b, 1), timeout=45, label="user B notifications")
    assert {item["diagnosis_id"] for item in page_a["items"]} == {diag_a1, diag_a2}
    assert {item["diagnosis_id"] for item in page_b["items"]} == {diag_b1}

    # Keyset pagination limit=1 + foreign cursor 400
    st_p1, p1, _ = http_json(f"{proxy_url}/api/v1/notifications?limit=1", headers=hdr_a)
    assert st_p1 == 200 and len(p1["items"]) == 1 and p1["next_cursor"] is not None
    st_foreign_cur, _, _ = http_json(
        f"{proxy_url}/api/v1/notifications?cursor={p1['next_cursor']}", headers=hdr_b
    )
    assert st_foreign_cur == 400
    st_p2, p2, _ = http_json(
        f"{proxy_url}/api/v1/notifications?limit=1&cursor={p1['next_cursor']}", headers=hdr_a
    )
    assert st_p2 == 200 and len(p2["items"]) == 1 and p2["items"][0]["id"] != p1["items"][0]["id"]

    # Idempotent PATCH /read + 404 isolation
    notif_a_id = page_a["items"][0]["id"]
    st_r1, read1, _ = http_json(f"{proxy_url}/api/v1/notifications/{notif_a_id}/read", method="PATCH", headers=hdr_a)
    assert st_r1 == 200 and read1["read_at"] is not None
    time.sleep(0.05)
    st_r2, read2, _ = http_json(f"{proxy_url}/api/v1/notifications/{notif_a_id}/read", method="PATCH", headers=hdr_a)
    assert st_r2 == 200 and read2["read_at"] == read1["read_at"]
    st_rf, _, _ = http_json(f"{proxy_url}/api/v1/notifications/{notif_a_id}/read", method="PATCH", headers=hdr_b)
    assert st_rf == 404

    # Verify delivery attempts in PostgreSQL: user A SENT (2), user B 0
    def check_email_sent():
        with psycopg.connect(host=pg_host, dbname="notification", user="notification", password=notif_pw) as conn:
            sent_a = conn.execute(
                "SELECT count(*) FROM notification_delivery_attempts WHERE owner_id=%s AND status='SENT'",
                (user_a_id,),
            ).fetchone()[0]
            att_b = conn.execute(
                "SELECT count(*) FROM notification_delivery_attempts WHERE owner_id=%s",
                (user_b_id,),
            ).fetchone()[0]
            return sent_a == 2 and att_b == 0

    _eventually(check_email_sent, timeout=20, label="user A email SENT and user B 0 attempts")
    print("[5/7] E2E DiagnosisFinished -> notifications, keyset cursor, idempotent read, email SENT PASS", flush=True)

    # 6. Quarantine + DLQ publication on unknown version and event_id collision
    conn_params = pika.ConnectionParameters(
        host=rabbit_host,
        credentials=pika.PlainCredentials("agro_local", rabbit_pw),
        socket_timeout=10,
    )
    with pika.BlockingConnection(conn_params) as broker:
        ch = broker.channel()
        ch.confirm_delivery()
        bad_ver = {
            "event_id": str(uuid.uuid4()),
            "event_type": "DiagnosisFinished",
            "schema_version": 99,
            "occurred_at": "2026-11-23T19:00:00Z",
            "correlation_id": str(uuid.uuid4()),
            "payload": {"diagnosis_id": str(uuid.uuid4()), "owner_id": user_a_id, "final_status": "COMPLETADO"},
        }
        ch.basic_publish(
            exchange="agrodiagnostico.events",
            routing_key="diagnosis.finished.v1",
            body=json.dumps(bad_ver).encode("utf-8"),
            properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
            mandatory=True,
        )

        # Fetch an existing inbox event_id to inject an identity collision
        with psycopg.connect(host=pg_host, dbname="notification", user="notification", password=notif_pw) as conn:
            existing_evt_id = str(conn.execute("SELECT event_id FROM notification_inbox LIMIT 1").fetchone()[0])

        collision = {
            "event_id": existing_evt_id,
            "event_type": "DiagnosisFinished",
            "schema_version": 1,
            "occurred_at": "2026-11-23T19:05:00Z",
            "correlation_id": str(uuid.uuid4()),
            "payload": {"diagnosis_id": str(uuid.uuid4()), "owner_id": user_b_id, "final_status": "FALLIDO"},
        }
        ch.basic_publish(
            exchange="agrodiagnostico.events",
            routing_key="diagnosis.finished.v1",
            body=json.dumps(collision).encode("utf-8"),
            properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
            mandatory=True,
        )

    def check_quarantine_and_dlq():
        with psycopg.connect(host=pg_host, dbname="notification", user="notification", password=notif_pw) as conn:
            reasons = {
                r[0] for r in conn.execute("SELECT reason_code FROM notification_quarantine_messages").fetchall()
            }
            sent_dlq = conn.execute(
                "SELECT count(*) FROM notification_dlq_outbox WHERE sent_at IS NOT NULL"
            ).fetchone()[0]
        if not ({"UNSUPPORTED_SCHEMA_VERSION", "EVENT_ID_COLLISION"} <= reasons and sent_dlq >= 2):
            return False
        with pika.BlockingConnection(conn_params) as broker:
            q = broker.channel().queue_declare(queue="notification.diagnosis-finished.v1.dlq", passive=True)
            return q.method.message_count >= 2

    _eventually(check_quarantine_and_dlq, timeout=20, label="quarantine and DLQ publication")
    print("[6/7] Quarantine + confirmed DLQ descriptors on real RabbitMQ PASS", flush=True)

    # Persist disposable test state to file (never print JWTs to stdout)
    with psycopg.connect(host=pg_host, dbname="diagnosis", user="diagnosis", password=diag_pw) as conn:
        diag_status = conn.execute("SELECT status FROM diagnoses WHERE id=%s", (diag_a1,)).fetchone()[0]
        assert diag_status in ("COMPLETADO", "NO_CONCLUYENTE", "FALLIDO")
    state_file = Path("/test_state/state.json")
    state_file.write_text(json.dumps({"user_a_id": user_a_id, "tok_a": tok_a, "diag_a1": diag_a1}))


def run_smtp_failure_check(proxy_url, pg_host, rabbit_host, secrets_dir):
    import pika
    import psycopg

    from app.consumer import DiagnosisFinishedConsumer
    from app.persistence import get_sessionmaker

    state = json.loads(Path("/test_state/state.json").read_text())
    tok_a = state["tok_a"]

    secrets = Path(secrets_dir)
    notif_pw = (secrets / "notification_password").read_text().strip()
    diag_pw = (secrets / "diagnosis_password").read_text().strip()
    rabbit_pw = (secrets / "rabbit_password").read_text().strip()

    # Upload a fresh diagnosis while notification-consumer is stopped
    mp_body, mp_ct = _encode_multipart("image", "leaf-smtp-fail.png", _minimal_png_bytes())
    st_u, res_u, _ = http_json(
        f"{proxy_url}/api/v1/diagnoses",
        method="POST",
        body=mp_body,
        headers={
            "Authorization": f"Bearer {tok_a}",
            "Content-Type": mp_ct,
            "Idempotency-Key": "notif-e2e-smtp-fail",
        },
    )
    assert st_u == 202
    diag_id = res_u["id"]

    # Wait for diagnosis to reach terminal and Finished message to sit durably in queue
    conn_params = pika.ConnectionParameters(
        host=rabbit_host,
        credentials=pika.PlainCredentials("agro_local", rabbit_pw),
        socket_timeout=10,
    )

    def wait_queued_finished():
        with pika.BlockingConnection(conn_params) as broker:
            q = broker.channel().queue_declare(queue="notification.diagnosis-finished.v1", passive=True)
            return q.method.message_count >= 1

    _eventually(wait_queued_finished, timeout=40, label="durable Finished retention while consumer stopped")

    # Process message with EMAIL_DELIVERY_MODE=smtp pointing to closed local port -> SMTP_UNAVAILABLE
    os.environ["EMAIL_DELIVERY_MODE"] = "smtp"
    os.environ["SMTP_HOST"] = "127.0.0.1"
    os.environ["SMTP_PORT"] = "1"
    os.environ["SMTP_TIMEOUT_SECONDS"] = "1"
    from app.infrastructure.email import set_email_delivery_adapter

    set_email_delivery_adapter(None)
    consumer = DiagnosisFinishedConsumer(db_session_factory=get_sessionmaker())

    with pika.BlockingConnection(conn_params) as broker:
        ch = broker.channel()
        ch.confirm_delivery()
        method_frame, _props, body = ch.basic_get(queue="notification.diagnosis-finished.v1", auto_ack=False)
        assert method_frame is not None
        ok = consumer.process_message(ch, method_frame.delivery_tag, body, method_frame.routing_key, publish_channel=ch)
        assert ok is True

    # Verify notification persisted & queryable via Nginx, attempt FAILED_RETRYABLE, diagnosis untouched
    st_n, page, _ = http_json(f"{proxy_url}/api/v1/notifications", headers={"Authorization": f"Bearer {tok_a}"})
    assert st_n == 200
    matching = [item for item in page["items"] if item["diagnosis_id"] == diag_id]
    assert len(matching) == 1
    notif_id = matching[0]["id"]

    with psycopg.connect(host=pg_host, dbname="notification", user="notification", password=notif_pw) as conn:
        row = conn.execute(
            "SELECT status, attempt_count, last_error_code FROM notification_delivery_attempts WHERE notification_id=%s",
            (notif_id,),
        ).fetchone()
        assert row is not None and row[0] == "FAILED_RETRYABLE" and row[1] == 1 and row[2] == "SMTP_UNAVAILABLE", row

    with psycopg.connect(host=pg_host, dbname="diagnosis", user="diagnosis", password=diag_pw) as conn:
        d_status = conn.execute("SELECT status FROM diagnoses WHERE id=%s", (diag_id,)).fetchone()[0]
        assert d_status in ("COMPLETADO", "NO_CONCLUYENTE", "FALLIDO")

    print("[7/7] Durable retention without consumer + SMTP failure isolation without reverting Diagnosis PASS", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner")
    parser.add_argument("--smtp-failure-runner")
    parser.add_argument("--identity-url", default="http://identity:8000")
    parser.add_argument("--pg-host", default="postgres")
    parser.add_argument("--rabbit-host", default="rabbitmq")
    parser.add_argument("--secrets-dir")
    parser.add_argument("--user-a-id")
    parser.add_argument("--tok-a")
    args = parser.parse_args()

    if args.runner:
        run_in_network_checks(args.runner, args.identity_url, args.pg_host, args.rabbit_host, args.secrets_dir)
        return 0
    if args.smtp_failure_runner:
        run_smtp_failure_check(args.smtp_failure_runner, args.pg_host, args.rabbit_host, args.secrets_dir)
        return 0

    project = "agro-env-test-" + uuid.uuid4().hex[:12]
    started = time.monotonic()
    evidence = ComposeEvidence(project)
    with tempfile.TemporaryDirectory(prefix="agro-notif-e2e-") as tmp:
        tmp_path = Path(tmp)
        secrets_path = tmp_path / "secrets"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        config = tmp_path / "config.env"
        config.write_text(
            f"APP_ENV=local\nHTTP_PORT={port}\nS3_BUCKET=agro-local\nS3_REGION=us-east-1\n"
            f"PERSISTENCE_SECRETS_DIR={secrets_path}\nLOCAL_UID={os.getuid()}\nLOCAL_GID={os.getgid()}\n"
            f"ENABLE_SIMULATED_INFERENCE=true\nASYNC_CONSUMER_ENV=test\nEMAIL_DELIVERY_MODE=logging\n"
        )
        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in (
                "APP_ENV",
                "HTTP_PORT",
                "S3_BUCKET",
                "S3_REGION",
                "PERSISTENCE_SECRETS_DIR",
                "LOCAL_UID",
                "LOCAL_GID",
                "ENABLE_SIMULATED_INFERENCE",
                "ASYNC_CONSUMER_ENV",
                "EMAIL_DELIVERY_MODE",
            )
        }
        base = ["docker", "compose", "--env-file", str(config), "-p", project, "-f", str(ROOT / "docker-compose.yml")]
        tracked_secrets = []

        def run(cmd, expected=0, timeout=300):
            res = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
            combined = res.stdout + res.stderr
            evidence.record(combined, tracked_secrets)
            for sec in tracked_secrets:
                if sec and sec in combined:
                    raise RuntimeError("Secret leaked in command output")
            if res.returncode != expected:
                print(combined[-6000:], flush=True)
                raise RuntimeError(f"Command exited {res.returncode}: {cmd}")
            return res.stdout

        try:
            run(["python3", "scripts/prepare_local.py", "--directory", str(secrets_path)])
            assert stat.S_IMODE(secrets_path.stat().st_mode) == 0o700
            for p in secrets_path.iterdir():
                if p.name.endswith("_password") or p.name in ("rabbit_cookie", "cursor_signing_key"):
                    tracked_secrets.append(p.read_text().strip())
                elif p.name in ("s3_admin.json", "s3_ai.json", "s3_diagnosis.json"):
                    tracked_secrets.extend(json.loads(p.read_text()).values())

            run(base + ["--profile", "async-test", "build"], timeout=900)
            run(base + ["--profile", "async-test", "up", "-d", "--wait", "--wait-timeout", "180"], timeout=240)

            state_dir = tmp_path / "state"
            state_dir.mkdir(mode=0o700)
            runner_base = [
                *base,
                "run",
                "--rm",
                "--no-deps",
                "-e",
                "PYTHONPATH=/service",
                "-v",
                f"{ROOT}:/app:ro",
                "-v",
                f"{secrets_path}:/test_secrets:ro",
                "-v",
                f"{state_dir}:/test_state",
                "notification-consumer",
                "python",
                "/app/scripts/check_notification_integration.py",
            ]
            out1 = run(runner_base + ["--runner", "http://nginx:8080", "--secrets-dir", "/test_secrets"], timeout=180)
            print(out1, flush=True)

            # Stop notification-consumer to verify durable retention + SMTP failure isolation
            run(base + ["stop", "notification-consumer"])
            out2 = run(
                runner_base + ["--smtp-failure-runner", "http://nginx:8080", "--secrets-dir", "/test_secrets"],
                timeout=180,
            )
            print(out2, flush=True)
            run(base + ["logs", "--no-color"])
        finally:
            evidence.collect(base, env, tracked_secrets)
            run(base + ["--profile", "async-test", "down", "--volumes", "--remove-orphans", "--rmi", "local"], timeout=180)
            evidence.verify_cleanup()

    print(f"PASS notification-integration project={project} duration_seconds={round(time.monotonic() - started, 3)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
