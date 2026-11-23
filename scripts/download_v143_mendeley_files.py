#!/usr/bin/env python3
"""Descarga verificable y reanudable de archivos Mendeley a almacenamiento privado."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(row: dict[str, object], output: Path) -> tuple[str, str]:
    details = row["content_details"]
    assert isinstance(details, dict)
    expected = str(details["sha256_hash"])
    size = int(details["size"])
    url = str(details["download_url"])
    suffix = Path(str(row["filename"])).suffix.lower() or ".bin"
    parsed = urlparse(url)
    if (parsed.scheme, parsed.netloc) != ("https", "data.mendeley.com") or not parsed.path.startswith(
        "/public-files/datasets/"
    ):
        raise ValueError(f"URL de descarga no pertenece a Mendeley Data: {row['filename']}")
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise ValueError(f"SHA-256 oficial inválido: {row['filename']}")
    target = output / f"{expected}{suffix}"
    if target.is_file() and target.stat().st_size == size and sha256_file(target) == expected:
        return expected, "VERIFIED_EXISTING"
    request = Request(url, headers={"User-Agent": "AgroDiagnostico-v1.4.3-audit/1"})
    with tempfile.NamedTemporaryFile(prefix="download-", dir=output, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        digest = hashlib.sha256()
        written = 0
        try:
            with urlopen(request, timeout=120) as response:
                while block := response.read(1024 * 1024):
                    temporary.write(block)
                    digest.update(block)
                    written += len(block)
            temporary.flush()
            os.fsync(temporary.fileno())
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
    if written != size or digest.hexdigest() != expected:
        temporary_path.unlink(missing_ok=True)
        raise ValueError(f"contenido distinto del manifiesto oficial: {row['filename']}")
    os.chmod(temporary_path, 0o600)
    temporary_path.replace(target)
    return expected, "DOWNLOADED_AND_VERIFIED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    metadata = json.loads(Path(args.metadata).read_text())
    rows = [
        row for row in metadata["files"]
        if row.get("content_details", {}).get("content_type", "").startswith("image/")
    ]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    completed = 0
    states: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download, row, output): row for row in rows}
        for future in as_completed(futures):
            _, state = future.result()
            states[state] = states.get(state, 0) + 1
            completed += 1
            if completed % 50 == 0 or completed == len(rows):
                print(f"DOWNLOAD_PROGRESS {completed}/{len(rows)}", flush=True)
    print(json.dumps({"status": "VERIFIED", "files": len(rows), "states": states}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
