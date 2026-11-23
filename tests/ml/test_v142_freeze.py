from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agro_ml.v142_freeze import V142FreezeError, verify_freeze


class V142FreezeTests(unittest.TestCase):
    def test_freeze_digest_and_missing_artifact_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = {"schema_version": 1, "cycle_version": "1.4.2",
                      "status": "FROZEN_VAL_PASSED_EXTERNAL_NOT_OPENED",
                      "base_checkpoint": {"sha256": "047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f",
                                          "redistributed": False},
                      "file_sha256": {"missing": "0" * 64}}
            from agro_ml.v142_freeze import _canonical
            import hashlib
            record["freeze_digest"] = hashlib.sha256(_canonical(record)).hexdigest()
            (root / "freeze.json").write_text(json.dumps(record))
            with self.assertRaises(V142FreezeError):
                verify_freeze(root, load_model=False)
            record["status"] = "changed"
            (root / "freeze.json").write_text(json.dumps(record))
            with self.assertRaises(V142FreezeError):
                verify_freeze(root, load_model=False)


if __name__ == "__main__":
    unittest.main()
