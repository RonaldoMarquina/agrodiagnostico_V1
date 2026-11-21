#!/usr/bin/env python3
"""Publish the reviewed two-class guidance through Diagnosis admin HTTP API.

Dry-run by default. Only loopback acceptance environments are permitted here.
The admin token is read from a private file and never printed or persisted.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
from urllib.parse import urlencode, urlsplit
import urllib.request


PILOT_CODES = {"POTATO_EARLY_BLIGHT", "POTATO_LATE_BLIGHT"}
PROHIBITED = re.compile(
    r"\b(?:fungicida|herbicida|insecticida)\b|\b\d+(?:[.,]\d+)?\s*(?:ml|cc|g|kg|l|ppm)\s*(?:/|por)\s*\w+",
    re.IGNORECASE,
)


def load_guidance(path: Path) -> tuple[dict, str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("GUIDANCE_FILE_MISSING")
    content = path.read_bytes()
    package = json.loads(content)
    if (package.get("schema_version") != 1
            or package.get("catalog_content_version") != "1.0.0"
            or package.get("scope") != "G0-1.2.0-POTATO-BLIGHTS"
            or not package.get("reviewed_by")
            or not package.get("reviewed_at")
            or not package.get("review_reference")):
        raise ValueError("GUIDANCE_REVIEW_MISSING")
    rows = package.get("recommendations")
    if not isinstance(rows, list) or {row.get("problem_code") for row in rows} != PILOT_CODES or len(rows) != 2:
        raise ValueError("GUIDANCE_SCOPE_INVALID")
    allowed = {item["url"] for item in package.get("sources", [])}
    if len(allowed) != 2:
        raise ValueError("GUIDANCE_SOURCES_INVALID")
    for row in rows:
        text = " ".join(str(row.get(field, "")) for field in ("title", "summary"))
        text += " " + " ".join(str(item) for field in (
            "cultural_practices", "biological_control", "preventive_measures")
            for item in row.get(field, []))
        if PROHIBITED.search(text):
            raise ValueError("GUIDANCE_TREATMENT_NOT_ALLOWED")
        if (not row.get("summary") or not row.get("cultural_practices")
                or not row.get("preventive_measures")
                or not row.get("source_refs")
                or not set(row["source_refs"]).issubset(allowed)):
            raise ValueError("GUIDANCE_CONTENT_INCOMPLETE")
    return package, hashlib.sha256(content).hexdigest()


def _request(base: str, path: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base + path, data=data, method="GET" if payload is None else "POST",
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/json", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, json.loads(response.read())


def publish(base: str, token_file: Path, package: dict, apply: bool) -> list[dict]:
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("LOCAL_ACCEPTANCE_URL_REQUIRED")
    if token_file.is_symlink() or not token_file.is_file() or stat.S_IMODE(token_file.stat().st_mode) & 0o077:
        raise ValueError("PRIVATE_ADMIN_TOKEN_FILE_REQUIRED")
    token = token_file.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("EMPTY_ADMIN_TOKEN")
    results = []
    for row in package["recommendations"]:
        code = row["problem_code"]
        payload = {**row, "review_reference": package["review_reference"],
                   "reviewed_by": package["reviewed_by"],
                   "reviewed_at": package["reviewed_at"], "active": True}
        _, current = _request(base, "/api/v1/admin/recommendations?" + urlencode({"problem_code": code}), token)
        expected = {key: value for key, value in payload.items() if key != "active"}
        existing = current.get("items", [])
        if existing:
            latest = existing[0]
            if any(latest.get(key) != value for key, value in expected.items()):
                raise ValueError("EXISTING_GUIDANCE_DIFFERS: " + code)
            results.append({"class_code": code, "action": "ALREADY_PRESENT", "version": latest["version"]})
            continue
        if apply:
            status, created = _request(base, "/api/v1/admin/recommendations", token, payload)
            if status != 201 or any(created.get(key) != value for key, value in expected.items()):
                raise ValueError("GUIDANCE_PUBLICATION_FAILED: " + code)
            results.append({"class_code": code, "action": "CREATED", "version": created["version"]})
        else:
            results.append({"class_code": code, "action": "DRY_RUN"})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--guidance-file", type=Path, default=Path("docs/catalog/pilot-potato-guidance.v1.json"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    package, digest = load_guidance(args.guidance_file)
    result = publish(args.base_url.rstrip("/"), args.token_file, package, args.apply)
    print(json.dumps({"mode": "APPLIED" if args.apply else "DRY_RUN",
                      "catalog_content_sha256": digest, "results": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
