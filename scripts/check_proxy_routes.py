#!/usr/bin/env python3
"""Verification of Nginx reverse proxy routes, limits, prefix isolation, and blocked endpoints.

Covers Task 8.1 of OpenSpec Incremento 2:
- Upstream diagnosis_backend and identity_backend routing.
- Exact routes: diagnoses, crops, problems, admin/crops, admin/problems, admin/recommendations,
  admin/diagnoses routed to Diagnosis.
- admin/users preserved to Identity.
- client_max_body_size 11m: exact 10 MiB body allowed; >11 MiB rejected with 413.
- Prefix isolation: /api/v1/diagnoses_extra, /api/v1/crops_extra, /api/v1/admin/extra return 404 NOT_IMPLEMENTED.
- Blocked routes: /internal, /health, /ai return 404.
- Correlation ID propagation and security headers.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


class MockHandler(BaseHTTPRequestHandler):
    backend = os.environ.get("MOCK_BACKEND", "unknown")

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._read_body()
        self._handle()

    def do_PATCH(self):
        self._read_body()
        self._handle()

    def do_DELETE(self):
        self._handle()

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        remaining = length
        while remaining > 0:
            chunk = min(remaining, 65536)
            _ = self.rfile.read(chunk)
            remaining -= chunk

    def _handle(self):
        cid = self.headers.get("X-Correlation-ID", "")
        data = json.dumps({
            "backend": self.backend,
            "path": self.path,
            "method": self.command,
            "correlation_id": cid,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "private, no-store")
        if cid:
            self.send_header("X-Correlation-ID", cid)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


def run_internal_server():
    server = HTTPServer(("0.0.0.0", 8000), MockHandler)
    server.serve_forever()


def request(url, method="GET", body=None, headers=None):
    req_headers = headers or {}
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            return resp.status, data, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        data = exc.read()
        return exc.code, data, dict(exc.headers)


def run_runner_checks(proxy_url):
    print("Running proxy routing test cases from runner container...", flush=True)

    # 1. Identity routes
    for path in ["/api/v1/auth/login", "/api/v1/profile", "/api/v1/admin/users", "/api/v1/admin/users/123"]:
        st, data, hdrs = request(f"{proxy_url}{path}")
        assert st == 200, f"Expected 200 for {path}, got {st}"
        payload = json.loads(data)
        assert payload["backend"] == "identity", f"Expected identity backend for {path}, got {payload['backend']}"
    print("  ✓ Identity routes (/auth/, /profile, /admin/users) routed correctly to identity_backend", flush=True)

    # 2. Diagnosis routes
    diagnosis_paths = [
        ("/api/v1/diagnoses", "GET"),
        ("/api/v1/diagnoses/123", "GET"),
        ("/api/v1/diagnoses/123/image", "GET"),
        ("/api/v1/diagnoses/123/cancel", "POST"),
        ("/api/v1/diagnoses/123/feedback", "POST"),
        ("/api/v1/crops", "GET"),
        ("/api/v1/crops/POTATO/problems", "GET"),
        ("/api/v1/problems/POTATO_EARLY_BLIGHT/recommendations", "GET"),
        ("/api/v1/admin/crops", "GET"),
        ("/api/v1/admin/crops/POTATO", "PATCH"),
        ("/api/v1/admin/problems", "GET"),
        ("/api/v1/admin/problems/POTATO_EARLY_BLIGHT", "PATCH"),
        ("/api/v1/admin/recommendations", "GET"),
        ("/api/v1/admin/recommendations/123", "PATCH"),
        ("/api/v1/admin/diagnoses", "GET"),
    ]
    for path, method in diagnosis_paths:
        st, data, hdrs = request(f"{proxy_url}{path}", method=method)
        assert st == 200, f"Expected 200 for {method} {path}, got {st}"
        payload = json.loads(data)
        assert payload["backend"] == "diagnosis", f"Expected diagnosis backend for {path}, got {payload['backend']}"
    print("  ✓ Diagnosis routes (diagnoses, crops, problems, admin catalog/diagnoses) routed correctly to diagnosis_backend", flush=True)

    # 3. Prefix isolation
    invalid_paths = [
        "/api/v1/diagnoses_invalid",
        "/api/v1/diagnoses_other/123",
        "/api/v1/crops_invalid",
        "/api/v1/crops_extra/POTATO",
        "/api/v1/admin/crops_invalid",
        "/api/v1/admin/users_invalid",
        "/api/v1/admin/unknown_resource",
        "/api/v1/nonexistent",
    ]
    for path in invalid_paths:
        st, data, hdrs = request(f"{proxy_url}{path}")
        assert st == 404, f"Expected 404 for invalid prefix path {path}, got {st}"
        payload = json.loads(data)
        assert payload.get("code") == "NOT_IMPLEMENTED", f"Expected NOT_IMPLEMENTED for {path}, got {payload}"
    print("  ✓ Prefix isolation prevents accidental route capture (returns 404 NOT_IMPLEMENTED)", flush=True)

    # 4. Blocked internal and monitoring routes
    blocked_paths = [
        "/internal",
        "/internal/diagnoses/123/claim",
        "/internal/diagnoses/123/image",
        "/health",
        "/health/live",
        "/health/ready",
        "/ai",
        "/ai/status",
    ]
    for path in blocked_paths:
        st, data, _ = request(f"{proxy_url}{path}")
        assert st == 404, f"Expected 404 for blocked route {path}, got {st}"
    print("  ✓ Internal (/internal, /health, /ai) routes strictly blocked (404)", flush=True)

    # 5. Exact 10 MiB upload payload allowed (fits in 11 MiB client_max_body_size)
    ten_mib = 10 * 1024 * 1024
    body_10mib = b"X" * ten_mib
    st, data, hdrs = request(
        f"{proxy_url}/api/v1/diagnoses",
        method="POST",
        body=body_10mib,
        headers={"Content-Type": "application/octet-stream", "Content-Length": str(ten_mib)},
    )
    assert st == 200, f"Expected 200 for exact 10 MiB upload, got {st}"
    print("  ✓ Exact 10 MiB upload permitted through proxy (within 11 MiB transport limit)", flush=True)

    # 6. Over 11 MiB payload rejected with 413 Payload Too Large
    eleven_point_five_mib = int(11.5 * 1024 * 1024)
    st, data, hdrs = request(
        f"{proxy_url}/api/v1/diagnoses",
        method="POST",
        body=b"X" * 1024,
        headers={"Content-Type": "application/octet-stream", "Content-Length": str(eleven_point_five_mib)},
    )
    assert st == 413, f"Expected 413 for >11 MiB upload, got {st}"
    print("  ✓ >11 MiB transport body rejected with 413 Request Entity Too Large", flush=True)

    # 7. Correlation ID propagation
    custom_cid = str(uuid.uuid4())
    st, data, hdrs = request(f"{proxy_url}/api/v1/crops", headers={"X-Correlation-ID": custom_cid})
    assert st == 200
    payload = json.loads(data)
    assert payload["correlation_id"] == custom_cid
    assert hdrs.get("X-Correlation-ID") == custom_cid
    assert hdrs.get("Cache-Control") == "private, no-store"
    print("  ✓ X-Correlation-ID and Cache-Control headers verified end-to-end", flush=True)

    print("\nALL Task 8.1 proxy verification checks PASSED successfully!", flush=True)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        run_internal_server()
        return

    if len(sys.argv) > 1 and sys.argv[1] == "--runner":
        proxy_url = sys.argv[2]
        run_runner_checks(proxy_url)
        return

    print("Verifying Nginx reverse proxy routes with isolated Docker environment (Task 8.1)...", flush=True)
    tag = f"agro-proxy-test-{uuid.uuid4().hex[:8]}"
    network = f"{tag}-net"
    containers = []

    def cleanup():
        for c in containers:
            subprocess.run(["docker", "rm", "-f", c], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "network", "rm", network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def interrupted(signum, frame):
        cleanup()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    try:
        # Create isolated Docker network
        subprocess.check_call(["docker", "network", "create", network], stdout=subprocess.DEVNULL)

        # 1. Start Mock Identity Backend
        id_container = f"{tag}-identity"
        containers.append(id_container)
        subprocess.check_call([
            "docker", "run", "-d",
            "--name", id_container,
            "--network", network,
            "--network-alias", "identity",
            "-e", "MOCK_BACKEND=identity",
            "-v", f"{ROOT}:/app:ro",
            "python:3.12-slim-bookworm",
            "python3", "/app/scripts/check_proxy_routes.py", "--server"
        ], stdout=subprocess.DEVNULL)

        # 2. Start Mock Diagnosis Backend
        diag_container = f"{tag}-diagnosis"
        containers.append(diag_container)
        subprocess.check_call([
            "docker", "run", "-d",
            "--name", diag_container,
            "--network", network,
            "--network-alias", "diagnosis",
            "-e", "MOCK_BACKEND=diagnosis",
            "-v", f"{ROOT}:/app:ro",
            "python:3.12-slim-bookworm",
            "python3", "/app/scripts/check_proxy_routes.py", "--server"
        ], stdout=subprocess.DEVNULL)

        # 3. Start Nginx Proxy with repository's exact default.conf
        proxy_container = f"{tag}-proxy"
        containers.append(proxy_container)
        subprocess.check_call([
            "docker", "run", "-d",
            "--name", proxy_container,
            "--network", network,
            "--network-alias", "proxy",
            "-v", f"{ROOT}/infra/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro",
            "nginx:1.28-alpine"
        ], stdout=subprocess.DEVNULL)

        # 4. Wait for proxy ready
        time.sleep(1.0)

        # 5. Run test runner inside container on the same network
        runner_container = f"{tag}-runner"
        containers.append(runner_container)
        run_res = subprocess.run([
            "docker", "run", "--rm",
            "--name", runner_container,
            "--network", network,
            "-v", f"{ROOT}:/app:ro",
            "python:3.12-slim-bookworm",
            "python3", "/app/scripts/check_proxy_routes.py", "--runner", "http://proxy:8080"
        ], text=True)

        if run_res.returncode != 0:
            raise RuntimeError(f"Proxy check failed with exit code {run_res.returncode}")

    finally:
        cleanup()


if __name__ == "__main__":
    main()
