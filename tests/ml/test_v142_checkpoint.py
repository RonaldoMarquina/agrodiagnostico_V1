from __future__ import annotations

import io
from pathlib import Path
import tempfile
import unittest

import torch
from torchvision.models import mobilenet_v3_small

from agro_ml.v142_checkpoint import (
    OFFICIAL_FILENAME, OFFICIAL_URL, V142CheckpointError,
    acquire_checkpoint, sha256_file, validate_checkpoint_file,
    validate_download_identity,
)


class _Response:
    status = 200
    headers = {}

    def __init__(self, body: bytes, final_url: str = OFFICIAL_URL):
        self._stream = io.BytesIO(body)
        self._final_url = final_url

    def getcode(self):
        return self.status

    def geturl(self):
        return self._final_url

    def read(self, size: int):
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _Opener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        return self.response


class _Exploit:
    def __reduce__(self):
        return (print, ("must never execute",))


class V142CheckpointTests(unittest.TestCase):
    def test_only_exact_official_identity_is_accepted(self):
        validate_download_identity(OFFICIAL_URL, OFFICIAL_URL, OFFICIAL_FILENAME)
        for requested, final, name in (
            ("https://example.test/model.pth", OFFICIAL_URL, OFFICIAL_FILENAME),
            (OFFICIAL_URL, "https://cdn.example.test/model.pth", OFFICIAL_FILENAME),
            (OFFICIAL_URL, OFFICIAL_URL, "renamed.pth"),
        ):
            with self.subTest(requested=requested, final=final, name=name), \
                    self.assertRaises(V142CheckpointError):
                validate_download_identity(requested, final, name)

    def test_partial_download_is_rejected_without_materializing_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terms = root / "terms.md"; terms.write_text("academic only")
            output = root / "private"
            with self.assertRaises(V142CheckpointError):
                acquire_checkpoint(output, terms, opener=_Opener(_Response(b"partial")))
            self.assertFalse(output.exists())
            self.assertEqual([], list(root.glob("*.partial")))

    def test_safe_loader_rejects_nonfinite_incomplete_and_pickle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / OFFICIAL_FILENAME
            valid = mobilenet_v3_small(weights=None).state_dict()
            candidates = []
            incomplete = dict(valid); incomplete.pop(next(iter(incomplete))); candidates.append(incomplete)
            nonfinite = dict(valid); key = next(iter(nonfinite)); nonfinite[key] = torch.full_like(nonfinite[key], float("nan")); candidates.append(nonfinite)
            candidates.append({"state": valid, "exploit": _Exploit()})
            for candidate in candidates:
                torch.save(candidate, path)
                with self.subTest(keys=len(candidate)), self.assertRaises(V142CheckpointError):
                    validate_checkpoint_file(path, expected_sha256=sha256_file(path),
                                             expected_size=path.stat().st_size)


if __name__ == "__main__":
    unittest.main()
