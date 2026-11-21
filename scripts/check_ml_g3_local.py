#!/usr/bin/env python3
"""Isolated real-worker acceptance, using G1 VAL images and the pinned G2 release.

Never opens TEST image bytes, changes production data, or approves G3 by itself.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid

import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_async_acceptance import request_json  # noqa: E402
from ci_support import ComposeEvidence, redact  # noqa: E402
from publish_pilot_guidance import load_guidance, publish  # noqa: E402
from ml_g3_fault_probe import probe as fault_probe  # noqa: E402

BUNDLE_SHA = "93e2e65130a9c266be4bdba0262d1c98e30d0604f4d21466effba2d9c9ff0b41"
ACTA_SHA = "579404dfe711fcae00c5d8964db669b8a66477f853d48a1fed45f72946d165f9"
POLICY_ID = "379be27f-e05a-487f-8bae-1dfd9644eedd"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def multipart(image: bytes, crop: str) -> tuple[bytes, str]:
    boundary = "agro-g3-" + uuid.uuid4().hex
    body = b"\r\n".join([
        ("--" + boundary).encode(),
        b'Content-Disposition: form-data; name="identified_crop"', b"", crop.encode(),
        ("--" + boundary).encode(),
        b'Content-Disposition: form-data; name="image"; filename="leaf.jpg"',
        b"Content-Type: image/jpeg", b"", image,
        ("--" + boundary + "--").encode(), b"",
    ])
    return body, "multipart/form-data; boundary=" + boundary


def select_images() -> list[dict]:
    private = ROOT / ".local/pv-g1"
    admitted = private / "pilot-v1.2"
    batch = private / "batch-v1"
    evidence = {entry["sha256"]: entry for entry in json.loads(
        (admitted / "evidence.json").read_text())["records"]}
    samples = []
    for code in ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"):
        candidates = sorted((row for row in rows(admitted / "val-positives.csv")
                             if row["class_code"] == code), key=lambda item: item["sha256"])
        for row in candidates[:4]:
            proof = evidence[row["sha256"]]
            if (proof["decision"] != "ADMIT" or proof["rights"]["decision"] != "APPROVED"
                    or proof["label_review"]["decision"] != "APPROVED"):
                raise ValueError("G1_VAL_IMAGE_NOT_ADMITTED")
            samples.append({"kind": "positive", "expected_class": code,
                            "sha256": row["sha256"], "path": batch / proof["relative_path"]})
    negatives = sorted(rows(admitted / "val-negatives.csv"), key=lambda item: item["sha256"])
    for row in negatives[:4]:
        proof = evidence[row["sha256"]]
        if proof["decision"] != "ADMIT" or proof["rights"]["decision"] != "APPROVED":
            raise ValueError("G1_VAL_NEGATIVE_NOT_ADMITTED")
        samples.append({"kind": "other_crop", "expected_class": None,
                        "sha256": row["sha256"], "path": batch / proof["relative_path"]})
    # Potato healthy and maize are outside G1: these original PlantVillage files
    # are used solely for an out-of-scope safety check, never for training or G2.
    candidates = rows(batch / "positives.csv")
    for label, split, kind in (("Potato___healthy", "VAL", "potato_healthy"),
                               ("Corn_(maize)___healthy", "", "maize_declared")):
        subset = sorted((row for row in candidates if row["source_label"] == label
                         and row["split"] == split), key=lambda item: item["sha256"])
        for row in subset[:4 if kind == "potato_healthy" else 1]:
            samples.append({"kind": kind, "expected_class": None,
                            "sha256": row["sha256"], "path": batch / row["relative_path"]})
    if len(samples) != 17:
        raise ValueError("INSUFFICIENT_DETERMINISTIC_VAL_SAMPLES")
    for sample in samples:
        if sha256(sample["path"]) != sample["sha256"]:
            raise ValueError("ACCEPTANCE_IMAGE_SHA_MISMATCH")
    return samples


def token(private_key: str, role: str, user_id: uuid.UUID) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(user_id), "role": role,
                       "iss": "agrodiagnostico-identity", "aud": "agrodiagnostico-api",
                       "jti": str(uuid.uuid4()), "iat": now, "exp": now + 3600},
                      private_key, algorithm="EdDSA")


def percentiles(values: list[float]) -> dict:
    ordered = sorted(values)
    return {"n": len(ordered), "median_seconds": ordered[(len(ordered)-1)//2],
            "p95_seconds": ordered[math.ceil(.95*len(ordered))-1],
            "max_seconds": ordered[-1]}


def main() -> int:
    run_id = uuid.uuid4().hex[:12]
    output = ROOT / ".local/ml-pilot-v1.2" / ("g3-local-" + run_id)
    output.mkdir(parents=True, exist_ok=False)
    os.environ["AGRO_CI_ARTIFACTS"] = str(output)
    project = "agro-env-test-" + run_id
    evidence = ComposeEvidence(project)
    report = {"run_id": run_id, "project": project, "started_at": datetime.now(timezone.utc).isoformat(),
              "bundle_sha256": BUNDLE_SHA, "g2_approval_sha256": ACTA_SHA,
              "policy_id": POLICY_ID, "g3_status": "NOT_APPROVED", "test_images_read": False,
              "sampling": "first four SHA-256 sorted VAL entries per class and negative category;"
                          " four original potato healthy VAL files; one maize declared crop",
              "steps": [], "results": [], "status": "FAILED"}
    report["cpu"] = {"architecture": platform.machine(), "logical_cores": os.cpu_count(),
                     "model": next((line.split(":", 1)[1].strip() for line in
                                    Path("/proc/cpuinfo").read_text().splitlines()
                                    if line.startswith("model name")), "unavailable")}
    report["request_concurrency"] = 2
    with tempfile.TemporaryDirectory(prefix="agro-g3-local-") as temporary:
        secrets = Path(temporary) / "secrets"
        secrets.mkdir(mode=0o700)
        config = Path(temporary) / "config.env"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        fault_mode = os.environ.get("AGRO_G3_FAULT_PROBES") == "1"
        config.write_text(
            f"APP_ENV=local\nASYNC_CONSUMER_ENV=local\nENABLE_SIMULATED_INFERENCE=false\n"
            f"HTTP_PORT={port}\nS3_BUCKET=agro-local\nS3_REGION=us-east-1\n"
            f"PERSISTENCE_SECRETS_DIR={secrets}\nLOCAL_UID={os.getuid()}\nLOCAL_GID={os.getgid()}\n"
            + ("REAL_WORKER_HEARTBEAT_SECONDS=0.1\n" if fault_mode else ""))
        base = ["docker", "compose", "--env-file", str(config), "-p", project,
                "-f", str(ROOT / "docker-compose.yml")]
        tracked = []

        def run(args, *, timeout=900):
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
            combined = result.stdout + result.stderr
            evidence.record(combined, tracked)
            if result.returncode:
                raise RuntimeError("COMMAND_FAILED: " + args[-1] + " " + redact(combined[-1200:], tracked))
            return result.stdout

        try:
            if sha256(ROOT / ".local/ml-pilot-v1.2/g2-bundle-v1/model-bundle.json") != BUNDLE_SHA:
                raise ValueError("BUNDLE_SHA_MISMATCH")
            if sha256(ROOT / ".local/ml-pilot-v1.2/g2-bundle-v1/g2-approval.json") != ACTA_SHA:
                raise ValueError("G2_ACTA_SHA_MISMATCH")
            guidance, content_sha = load_guidance(ROOT / "docs/catalog/pilot-potato-guidance.v1.json")
            report["catalog_content_sha256"] = content_sha
            samples = select_images()
            report["selected_sha256"] = [{"kind": row["kind"], "sha256": row["sha256"]}
                                         for row in samples]
            run(["python3", "scripts/prepare_local.py", "--directory", str(secrets)])
            for path in secrets.iterdir():
                if path.name.endswith("_password") or path.name in ("rabbit_cookie", "cursor_signing_key"):
                    tracked.append(path.read_text().strip())
                path.chmod(0o644)
            secrets.chmod(0o755)
            compose_config = json.loads(run(base + ["--profile", "ml-real", "config", "--format", "json"]))
            worker_env = compose_config["services"]["ai_inference-worker-real"]["environment"]
            trust = json.loads((secrets / "internal_service_keys.json").read_text())
            if trust[worker_env["INTERNAL_WORKER_KID"]]["instance_id"] != worker_env["INTERNAL_WORKER_INSTANCE_ID"]:
                raise ValueError("REAL_WORKER_INTERNAL_IDENTITY_NOT_TRUSTED")
            run(base + ["--profile", "ml-real", "build"], timeout=1200)
            report["steps"].append("BUILD_ML_REAL")
            run(base + ["up", "-d", "--wait", "--wait-timeout", "180"], timeout=300)
            report["steps"].append("BOOT_NO_REAL_WORKER")
            private_key = (secrets / "jwt_private_key.pem").read_text()
            owner_id, other_id, admin_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            owner = token(private_key, "USER", owner_id)
            other = token(private_key, "USER", other_id)
            admin = token(private_key, "ADMIN", admin_id)
            token_file = Path(temporary) / "admin.token"
            token_file.write_text(admin)
            token_file.chmod(0o600)
            base_url = f"http://127.0.0.1:{port}"
            dry = publish(base_url, token_file, guidance, False)
            if any(item["action"] != "DRY_RUN" for item in dry):
                raise AssertionError("Catalog not empty before publication")
            published = publish(base_url, token_file, guidance, True)
            if {item["action"] for item in published} != {"CREATED"}:
                raise AssertionError("Catalog publication incomplete")
            report["catalog_versions"] = {item["class_code"]: item["version"] for item in published}
            report["steps"].append("CATALOG_PUBLISHED_BY_ADMIN_API")

            policy_root = ROOT / ".local/ml-pilot-v1.2"
            policy_cmd = base + ["run", "--rm", "--no-deps",
                                 "-v", f"{policy_root / 'g2-bundle-v1'}:/models/release:ro",
                                 "-v", f"{policy_root / 'policy-draft-v1.json'}:/policy.json:ro",
                                 "diagnosis", "python", "-m", "app.policy", "import",
                                 "--policy-file", "/policy.json", "--release-bundle", "/models/release/model-bundle.json",
                                 "--g2-approval", "/models/release/g2-approval.json",
                                 "--actor", "G3_LOCAL_ACCEPTANCE", "--reason", "G3 isolated " + run_id]
            if json.loads(run(policy_cmd))["mode"] != "DRY_RUN":
                raise AssertionError("Policy import preview failed")
            if json.loads(run(policy_cmd + ["--apply"]))["mode"] != "APPLIED":
                raise AssertionError("Policy import failed")
            activate = base + ["run", "--rm", "--no-deps", "diagnosis", "python", "-m",
                               "app.policy", "activate", "--policy-id", POLICY_ID,
                               "--actor", "G3_LOCAL_ACCEPTANCE", "--reason", "G3 isolated " + run_id]
            if json.loads(run(activate))["mode"] != "DRY_RUN":
                raise AssertionError("Policy activation preview failed")
            if json.loads(run(activate + ["--apply"]))["mode"] != "APPLIED":
                raise AssertionError("Policy activation failed")
            report["steps"].append("G2_POLICY_IMPORTED_AND_ACTIVATED_ISOLATED")
            run(base + ["--profile", "ml-real", "up", "-d", "--wait", "--wait-timeout", "180",
                        "ai_inference-worker-real"], timeout=300)
            report["steps"].append("REAL_WORKER_STARTED")

            auth_owner = {"Authorization": "Bearer " + owner}
            auth_other = {"Authorization": "Bearer " + other}
            first_id = None

            def diagnose(sample):
                image = sample["path"].read_bytes()
                crop = "MAIZE" if sample["kind"] == "maize_declared" else "POTATO"
                body, content_type = multipart(image, crop)
                started = time.monotonic()
                code, created, _ = request_json(
                    base_url + "/api/v1/diagnoses", "POST", body,
                    {**auth_owner, "Content-Type": content_type, "Idempotency-Key": str(uuid.uuid4())})
                item = {"kind": sample["kind"], "image_sha256": sample["sha256"],
                        "http_create": code, "diagnosis_id": created.get("id")}
                if crop == "MAIZE":
                    item["expected_http_rejection"] = code == 400
                    return item
                if code != 202:
                    item["error"] = "UPLOAD_NOT_ACCEPTED"
                    return item
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    st, detail, _ = request_json(
                        base_url + "/api/v1/diagnoses/" + created["id"], headers=auth_owner)
                    if st != 200:
                        item["error"] = "DETAIL_UNAVAILABLE"
                        break
                    if detail["status"] in {"COMPLETADO", "NO_CONCLUYENTE", "FALLIDO"}:
                        item.update({"status": detail["status"], "reason_code": detail.get("reason_code"),
                                     "class_code": (detail.get("result") or {}).get("class_code"),
                                     "policy_id": (detail.get("result") or {}).get("policy_id"),
                                     "elapsed_seconds": round(time.monotonic()-started, 3),
                                     "catalog_version": ((detail.get("result") or {}).get("recommendation") or {}).get("catalog_version")})
                        break
                    time.sleep(.3)
                else:
                    item["error"] = "TERMINAL_TIMEOUT"
                return item

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(diagnose, sample) for sample in samples]
                for future in as_completed(futures):
                    item = future.result()
                    report["results"].append(item)
                    if item.get("diagnosis_id") and first_id is None:
                        first_id = item["diagnosis_id"]
            if first_id:
                report["other_owner_detail_http"] = request_json(
                    base_url + "/api/v1/diagnoses/" + first_id, headers=auth_other)[0]
                report["other_owner_image_http"] = request_json(
                    base_url + "/api/v1/diagnoses/" + first_id + "/image", headers=auth_other)[0]
            history_code, history, _ = request_json(base_url + "/api/v1/diagnoses", headers=auth_owner)
            report["owner_history_http"] = history_code
            report["owner_history_count"] = len(history.get("items", [])) if isinstance(history, dict) else None
            latencies = [row["elapsed_seconds"] for row in report["results"] if "elapsed_seconds" in row]
            report["full_flow_latency"] = percentiles(latencies) if latencies else None
            container = run(base + ["ps", "-q", "ai_inference-worker-real"]).strip()
            peak = run(["docker", "exec", container, "cat", "/sys/fs/cgroup/memory.peak"]).strip()
            report["worker_peak_memory_bytes"] = int(peak)
            positives = [row for row in report["results"] if row["kind"] == "positive"]
            report["positive_correct_accepted"] = {
                code: sum(row.get("status") == "COMPLETADO" and row.get("class_code") == code
                          for row in positives if row["image_sha256"] in
                          {item["sha256"] for item in samples if item["expected_class"] == code})
                for code in ("POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT")}
            report["other_crop_false_accepted"] = sum(
                row.get("status") == "COMPLETADO" for row in report["results"]
                if row["kind"] == "other_crop")
            report["potato_healthy_false_accepted"] = sum(
                row.get("status") == "COMPLETADO" for row in report["results"]
                if row["kind"] == "potato_healthy")
            report["full_flow_pass"] = (
                all(report["positive_correct_accepted"].values())
                and report["other_crop_false_accepted"] == 0
                and report["potato_healthy_false_accepted"] == 0
                and all(row.get("expected_http_rejection") for row in report["results"]
                        if row["kind"] == "maize_declared")
                and report.get("other_owner_detail_http") == 404
                and report.get("other_owner_image_http") == 404
                and history_code == 200)
            report["steps"].append("HTTP_QUEUE_REAL_WORKER_DIAGNOSIS_HISTORY")
            if fault_mode:
                fault_probe(base, run, report, base_url, owner, samples[0], secrets, multipart)
                report["steps"].append("REAL_WORKER_RESTART_HEARTBEAT_REDELIVERY_STALE_LEASE")
            report["status"] = "OBSERVED"
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            report["error"] = redact(str(exc)[:1200], tracked)
        finally:
            try:
                evidence.collect(base, os.environ, tracked)
                subprocess.run(base + ["--profile", "ml-real", "down", "--volumes", "--remove-orphans",
                                       "--rmi", "local"], cwd=ROOT, capture_output=True, text=True, timeout=240,
                               check=True)
                evidence.verify_cleanup()
                report["cleanup"] = "PASS"
            except Exception as exc:
                report["cleanup"] = "FAILED: " + type(exc).__name__
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            (output / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
            print(json.dumps({"report": str(output / "summary.json"), "status": report["status"],
                              "full_flow_pass": report.get("full_flow_pass"), "cleanup": report["cleanup"]}))
    return 0 if report["status"] == "OBSERVED" and report["cleanup"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
