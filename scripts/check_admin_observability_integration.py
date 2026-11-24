#!/usr/bin/env python3
"""End-to-End Integration Acceptance Suite for Incremento 5 — Admin, Observability & Notification UX (ADR-0016).

Verifies in an isolated disposable Compose project via Nginx:
1. Core stack WITHOUT --profile assistant:
   - GET /api/v1/admin/system/status returns 200 with overall_status=OK (core 4 services OK, optional assistant DOWN/UNKNOWN).
2. Identity admin endpoints via Nginx:
   - GET /api/v1/admin/users/stats (exact counts + 403 for USER).
   - PATCH /api/v1/admin/users/{id}/block: 409 SELF_BLOCK_NOT_ALLOWED on self, 400 on short reason, 200 with valid reason persisted in audit_logs.details.
   - GET /api/v1/admin/audit/identity: keyset pagination, action filter, reason visibility, 400 tampered cursor, 403 USER.
3. Diagnosis observability & D-19 audited image read via Nginx:
   - Upload real PNG as USER; GET /api/v1/admin/metrics/summary (6 statuses, daily_series, 400 invalid range, 403 USER).
   - GET /api/v1/admin/models honors REAL_INFERENCE_AUTHORIZED=false (active_model=null, runtime_status=INACTIVE_GATE_BLOCKED).
   - D-19: /api/v1/admin/diagnoses metadata-only; /api/v1/diagnoses/{id}/image returns 404 to ADMIN on foreign resource;
     /api/v1/admin/diagnoses/{id}/image returns 403 to USER, 200 binary with private, no-store & nosniff to ADMIN,
     and persists ADMIN_VIEW_DIAGNOSIS_IMAGE verifiable via GET /api/v1/admin/audit/diagnosis.
4. Notification UX endpoints via Nginx:
   - GET /api/v1/notifications/unread-count & PATCH /api/v1/notifications/read-all (idempotency, owner isolation, 401 unauth).
5. Assistant extension (--profile assistant):
   - GET /api/v1/admin/system/status reports assistant=OK.
   - OPEN_AUDIT -> AUDIT and OPEN_MONITORING -> MONITORING return 200 NAVIGATE for ADMIN and 403 for USER.
6. Proxy isolation (/internal, /health -> 404), zero secret leaks, and strict disposable cleanup.
"""
import json
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ci_support import ComposeEvidence  # noqa: E402


def http_request(url, method="GET", body=None, headers=None):
    req_headers = {}
    if headers:
        req_headers.update(headers)
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        elif isinstance(body, bytes):
            data = body
        elif isinstance(body, str):
            data = body.encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            hdrs = {k.lower(): v for k, v in resp.headers.items()}
            if raw and "application/json" in hdrs.get("content-type", ""):
                parsed = json.loads(raw)
            else:
                parsed = raw
            return resp.status, parsed, hdrs
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        hdrs = {k.lower(): v for k, v in exc.headers.items()}
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw.decode("utf-8", errors="replace")
        return exc.code, parsed, hdrs


def _minimal_png_bytes() -> bytes:
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


def _encode_multipart(field_name: str, filename: str, file_bytes: bytes, content_type: str = "image/png"):
    boundary = f"----AgroObsTest{uuid.uuid4().hex}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("ascii") + file_bytes + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, f"multipart/form-data; boundary={boundary}"


def main():
    project = "agro-env-test-" + uuid.uuid4().hex[:12]
    started = time.monotonic()
    evidence = ComposeEvidence(project)

    with tempfile.TemporaryDirectory(prefix="agro-obs-e2e-") as tmp:
        tmp_path = Path(tmp)
        secrets_path = tmp_path / "secrets"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        proxy_url = f"http://127.0.0.1:{port}"
        origin_hdr = {"Origin": proxy_url}

        config = tmp_path / "config.env"
        config.write_text(
            f"APP_ENV=local\nHTTP_PORT={port}\nS3_BUCKET=agro-local\nS3_REGION=us-east-1\n"
            f"PERSISTENCE_SECRETS_DIR={secrets_path}\nLOCAL_UID={os.getuid()}\nLOCAL_GID={os.getgid()}\n"
            f"ALLOWED_ORIGINS={proxy_url}\nREAL_INFERENCE_AUTHORIZED=false\n"
            f"ASSISTANT_ENABLED=true\nASSISTANT_PROVIDER=fake\nASSISTANT_RATE_LIMIT=30/60s\n"
        )
        scrub_keys = {
            "APP_ENV",
            "HTTP_PORT",
            "S3_BUCKET",
            "S3_REGION",
            "PERSISTENCE_SECRETS_DIR",
            "LOCAL_UID",
            "LOCAL_GID",
            "ALLOWED_ORIGINS",
            "REAL_INFERENCE_AUTHORIZED",
            "ASSISTANT_ENABLED",
            "ASSISTANT_PROVIDER",
            "GEMINI_API_KEY",
            "ASSISTANT_RATE_LIMIT",
        }
        env = {k: v for k, v in os.environ.items() if k not in scrub_keys}
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

        def psql_query(db_name: str, sql: str) -> str:
            out = run(
                base
                + [
                    "exec",
                    "-T",
                    "postgres",
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    db_name,
                    "-tAc",
                    sql,
                ]
            )
            return out.strip()

        try:
            run(["python3", "scripts/prepare_local.py", "--directory", str(secrets_path)])
            assert stat.S_IMODE(secrets_path.stat().st_mode) == 0o700
            for p in secrets_path.iterdir():
                if p.name.endswith("_password") or p.name in ("rabbit_cookie", "cursor_signing_key"):
                    tracked_secrets.append(p.read_text().strip())
                elif p.name in ("s3_admin.json", "s3_ai.json", "s3_diagnosis.json"):
                    tracked_secrets.extend(json.loads(p.read_text()).values())

            run(base + ["--profile", "assistant", "build", "identity", "diagnosis", "ai_inference", "notification", "assistant", "nginx"], timeout=900)
            run(base + ["up", "-d", "--wait", "--wait-timeout", "180"], timeout=240)

            # 1. Proxy isolation + real Identity register/login
            assert http_request(f"{proxy_url}/internal/users/{uuid.uuid4()}/contact")[0] == 404
            assert http_request(f"{proxy_url}/health/ready")[0] == 404

            def register_user(email: str, name: str) -> str:
                st, prof, _ = http_request(
                    f"{proxy_url}/api/v1/auth/register",
                    method="POST",
                    body={"email": email, "password": "StrongPassword123!", "display_name": name},
                )
                assert st == 201, (st, prof)
                return prof["id"]

            def login_user(email: str) -> str:
                st, sess, _ = http_request(
                    f"{proxy_url}/api/v1/auth/login",
                    method="POST",
                    body={"email": email, "password": "StrongPassword123!"},
                    headers=origin_hdr,
                )
                assert st == 200, (st, sess)
                return sess["access_token"]

            user_id = register_user("obs_user@example.test", "Agricultor Obs")
            user2_id = register_user("obs_user2@example.test", "Agricultor Dos")
            admin_id = register_user("obs_admin@example.test", "Admin Obs")
            psql_query("identity", f"UPDATE users SET role = 'ADMIN' WHERE id = '{admin_id}';")

            user_tok = login_user("obs_user@example.test")
            user2_tok = login_user("obs_user2@example.test")
            admin_tok = login_user("obs_admin@example.test")
            tracked_secrets.extend([user_tok, user2_tok, admin_tok])
            user_hdr = {"Authorization": f"Bearer {user_tok}"}
            user2_hdr = {"Authorization": f"Bearer {user2_tok}"}
            admin_hdr = {"Authorization": f"Bearer {admin_tok}"}
            print("[1/6] Core stack up, proxy isolation, and real Identity tokens PASS", flush=True)

            # 2. Identity stats, anti-self-block 409, block with reason, and audit/identity
            assert http_request(f"{proxy_url}/api/v1/admin/users/stats", headers=user_hdr)[0] == 403
            st, stats, hdrs = http_request(f"{proxy_url}/api/v1/admin/users/stats", headers=admin_hdr)
            assert st == 200 and stats == {"total": 3, "active": 3, "blocked": 0, "admins": 1, "users": 2}, (st, stats)
            assert hdrs.get("cache-control") == "private, no-store"

            st, self_blk, _ = http_request(
                f"{proxy_url}/api/v1/admin/users/{admin_id}/block",
                method="PATCH",
                body={"reason": "Intento de auto bloqueo"},
                headers=admin_hdr,
            )
            assert st == 409 and self_blk["code"] == "SELF_BLOCK_NOT_ALLOWED", (st, self_blk)

            st_bad_reason, _, _ = http_request(
                f"{proxy_url}/api/v1/admin/users/{user2_id}/block",
                method="PATCH",
                body={"reason": "abc"},
                headers=admin_hdr,
            )
            assert st_bad_reason == 400, st_bad_reason

            block_reason = "Prueba E2E de bloqueo auditado"
            st_blk, blk_body, _ = http_request(
                f"{proxy_url}/api/v1/admin/users/{user2_id}/block",
                method="PATCH",
                body={"reason": block_reason},
                headers=admin_hdr,
            )
            assert st_blk == 200 and blk_body["status"] == "BLOCKED", (st_blk, blk_body)

            st, stats2, _ = http_request(f"{proxy_url}/api/v1/admin/users/stats", headers=admin_hdr)
            assert st == 200 and stats2["blocked"] == 1 and stats2["active"] == 2, stats2

            assert http_request(f"{proxy_url}/api/v1/admin/audit/identity", headers=user_hdr)[0] == 403
            st, aud_id, hdrs = http_request(
                f"{proxy_url}/api/v1/admin/audit/identity?action=USER_BLOCKED&limit=10",
                headers=admin_hdr,
            )
            assert st == 200 and len(aud_id["items"]) >= 1, (st, aud_id)
            assert any((item.get("details") or {}).get("reason") == block_reason for item in aud_id["items"]), aud_id
            assert hdrs.get("cache-control") == "private, no-store"
            assert http_request(f"{proxy_url}/api/v1/admin/audit/identity?cursor=tampered.cursor", headers=admin_hdr)[0] == 400

            # Reactivate user2 so notification isolation check works with user2 token
            st_act, _, _ = http_request(
                f"{proxy_url}/api/v1/admin/users/{user2_id}/activate",
                method="PATCH",
                headers=admin_hdr,
            )
            assert st_act == 200
            print("[2/6] Identity stats, anti-self-block 409, reason audit, and audit/identity PASS", flush=True)

            # 3. Diagnosis upload + metrics/summary + models + system/status (assistant inactive) + D-19 audited image
            png_bytes = _minimal_png_bytes()
            mp_body, mp_ct = _encode_multipart("image", "hoja.png", png_bytes, "image/png")
            st_up, up_body, _ = http_request(
                f"{proxy_url}/api/v1/diagnoses",
                method="POST",
                body=mp_body,
                headers={
                    **user_hdr,
                    "Content-Type": mp_ct,
                    "Idempotency-Key": f"obs-e2e-{uuid.uuid4().hex}",
                },
            )
            assert st_up == 202, (st_up, up_body)
            diag_id = up_body["id"]

            assert http_request(f"{proxy_url}/api/v1/admin/metrics/summary", headers=user_hdr)[0] == 403
            st_m, metrics, _ = http_request(f"{proxy_url}/api/v1/admin/metrics/summary", headers=admin_hdr)
            assert st_m == 200 and metrics["total"] >= 1, (st_m, metrics)
            assert set(metrics["by_status"].keys()) == {
                "PENDIENTE",
                "PROCESANDO",
                "COMPLETADO",
                "NO_CONCLUYENTE",
                "FALLIDO",
                "CANCELADO",
            }
            assert len(metrics["daily_series"]) >= 1
            assert http_request(
                f"{proxy_url}/api/v1/admin/metrics/summary?from=2026-11-23T00:00:00Z&to=2026-11-20T00:00:00Z",
                headers=admin_hdr,
            )[0] == 400

            assert http_request(f"{proxy_url}/api/v1/admin/models", headers=user_hdr)[0] == 403
            st_mod, models_body, _ = http_request(f"{proxy_url}/api/v1/admin/models", headers=admin_hdr)
            assert st_mod == 200, (st_mod, models_body)
            assert models_body["real_inference_authorized"] is False
            assert models_body["runtime_status"] == "INACTIVE_GATE_BLOCKED"
            assert models_body["active_model"] is None

            assert http_request(f"{proxy_url}/api/v1/admin/system/status", headers=user_hdr)[0] == 403
            st_sys, sys_body, _ = http_request(f"{proxy_url}/api/v1/admin/system/status", headers=admin_hdr)
            assert st_sys == 200 and sys_body["overall_status"] == "OK", (st_sys, sys_body)
            svc_map = {s["name"]: s for s in sys_body["services"]}
            for core_name in ("identity", "diagnosis", "ai_inference", "notification"):
                assert svc_map[core_name]["status"] == "OK", (core_name, svc_map)
            assert svc_map["assistant"]["optional"] is True
            assert svc_map["assistant"]["status"] in ("DOWN", "UNKNOWN"), svc_map["assistant"]

            # D-19 privacy by default + explicit audited read
            st_list, list_body, _ = http_request(f"{proxy_url}/api/v1/admin/diagnoses", headers=admin_hdr)
            assert st_list == 200 and all("object_key" not in i and "image_url" not in i for i in list_body["items"])
            assert http_request(f"{proxy_url}/api/v1/diagnoses/{diag_id}/image", headers=admin_hdr)[0] == 404
            assert http_request(f"{proxy_url}/api/v1/admin/diagnoses/{diag_id}/image", headers=user_hdr)[0] == 403

            img_cid = str(uuid.uuid4())
            st_img, img_raw, img_hdrs = http_request(
                f"{proxy_url}/api/v1/admin/diagnoses/{diag_id}/image",
                headers={**admin_hdr, "X-Correlation-ID": img_cid},
            )
            assert st_img == 200 and img_raw == png_bytes, (st_img, len(img_raw) if isinstance(img_raw, bytes) else img_raw)
            assert img_hdrs.get("cache-control") == "private, no-store"
            assert img_hdrs.get("x-content-type-options") == "nosniff"
            assert img_hdrs.get("x-correlation-id") == img_cid

            assert http_request(f"{proxy_url}/api/v1/admin/audit/diagnosis", headers=user_hdr)[0] == 403
            st_da, diag_aud, _ = http_request(
                f"{proxy_url}/api/v1/admin/audit/diagnosis?action=ADMIN_VIEW_DIAGNOSIS_IMAGE&target_id={diag_id}",
                headers=admin_hdr,
            )
            assert st_da == 200 and len(diag_aud["items"]) == 1, (st_da, diag_aud)
            entry = diag_aud["items"][0]
            assert entry["actor_id"] == admin_id and entry["target_type"] == "DIAGNOSIS" and entry["correlation_id"] == img_cid
            print("[3/6] Diagnosis metrics, models (gate blocked), system/status, D-19 audited image & audit/diagnosis PASS", flush=True)

            # 4. Notification unread-count & read-all via Nginx
            assert http_request(f"{proxy_url}/api/v1/notifications/unread-count")[0] == 401
            assert http_request(f"{proxy_url}/api/v1/notifications/read-all", method="PATCH")[0] == 401

            for owner, diag_ref in [(user_id, str(uuid.uuid4())), (user_id, str(uuid.uuid4())), (user2_id, str(uuid.uuid4()))]:
                psql_query(
                    "notification",
                    f"INSERT INTO notifications (id, owner_id, diagnosis_id, final_status, correlation_id, created_at) "
                    f"VALUES ('{uuid.uuid4()}', '{owner}', '{diag_ref}', 'NO_CONCLUYENTE', '{uuid.uuid4()}', NOW());",
                )

            st_c1, c1, _ = http_request(f"{proxy_url}/api/v1/notifications/unread-count", headers=user_hdr)
            assert st_c1 == 200 and c1 == {"unread_count": 2}, (st_c1, c1)
            st_c2, c2, _ = http_request(f"{proxy_url}/api/v1/notifications/unread-count", headers=user2_hdr)
            assert st_c2 == 200 and c2 == {"unread_count": 1}, (st_c2, c2)

            st_ra1, ra1, _ = http_request(f"{proxy_url}/api/v1/notifications/read-all", method="PATCH", headers=user_hdr)
            assert st_ra1 == 200 and ra1 == {"updated_count": 2}, (st_ra1, ra1)
            st_ra2, ra2, _ = http_request(f"{proxy_url}/api/v1/notifications/read-all", method="PATCH", headers=user_hdr)
            assert st_ra2 == 200 and ra2 == {"updated_count": 0}, (st_ra2, ra2)

            assert http_request(f"{proxy_url}/api/v1/notifications/unread-count", headers=user_hdr)[1] == {"unread_count": 0}
            assert http_request(f"{proxy_url}/api/v1/notifications/unread-count", headers=user2_hdr)[1] == {"unread_count": 1}
            print("[4/6] Notification unread-count, idempotent read-all, and owner isolation PASS", flush=True)

            # 5. Start --profile assistant -> system/status sees assistant OK + OPEN_AUDIT/OPEN_MONITORING enabled
            run(base + ["--profile", "assistant", "up", "-d", "--wait", "--wait-timeout", "120", "assistant"], timeout=180)
            st_sys2, sys_body2, _ = http_request(f"{proxy_url}/api/v1/admin/system/status", headers=admin_hdr)
            assert st_sys2 == 200 and sys_body2["overall_status"] == "OK", (st_sys2, sys_body2)
            svc_map2 = {s["name"]: s for s in sys_body2["services"]}
            assert svc_map2["assistant"]["status"] == "OK", svc_map2["assistant"]

            for msg, exp_intent, exp_target in [
                ("Abrir auditoría", "OPEN_AUDIT", "AUDIT"),
                ("Muéstrame el estado del sistema", "OPEN_MONITORING", "MONITORING"),
            ]:
                st_a, b_a, _ = http_request(
                    f"{proxy_url}/api/v1/assistant/messages",
                    method="POST",
                    body={"message": msg},
                    headers=admin_hdr,
                )
                assert st_a == 200 and b_a["status"] == "SUCCESS" and b_a["intent"] == exp_intent, (st_a, b_a)
                assert b_a["action"] == {"type": "NAVIGATE", "target": exp_target}, b_a

                st_u, b_u, _ = http_request(
                    f"{proxy_url}/api/v1/assistant/messages",
                    method="POST",
                    body={"message": msg},
                    headers=user_hdr,
                )
                assert st_u == 403 and b_u["code"] == "FORBIDDEN", (st_u, b_u)
            print("[5/6] Assistant enabled in system/status + OPEN_AUDIT/OPEN_MONITORING RBAC PASS", flush=True)

            # 6. Verify no secrets leaked in logs
            run(base + ["--profile", "assistant", "logs", "--no-color", "identity", "diagnosis", "notification", "assistant"])
            print("[6/6] Clean logs with zero secret leaks PASS", flush=True)
        finally:
            evidence.collect(base + ["--profile", "assistant"], env, tracked_secrets)
            run(base + ["--profile", "assistant", "down", "--volumes", "--remove-orphans", "--rmi", "local"], timeout=180)
            evidence.verify_cleanup()

    print(
        f"PASS admin-observability-integration project={project} duration_seconds={round(time.monotonic() - started, 3)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
