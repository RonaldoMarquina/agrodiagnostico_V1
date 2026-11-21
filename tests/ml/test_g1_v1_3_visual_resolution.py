"""Visual ambiguity is resolved by excluding whole candidate leaf groups."""

import csv
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.resolve_g1_v1_3_visual_pairs import resolve, sha


def write_rows(path, fields, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class TestVisualResolution(unittest.TestCase):
    def test_excludes_every_view_of_implicated_group(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "audit"
            source.mkdir()
            records = [
                dict(sha256="a" * 64, leaf_id="pv:leaf1", class_code="POTATO_HEALTHY",
                     decision="PENDING", decision_reason="VISUAL_PAIR_GROUP_REVIEW_PENDING"),
                dict(sha256="b" * 64, leaf_id="pv:leaf1", class_code="POTATO_HEALTHY",
                     decision="PENDING", decision_reason="ELIGIBLE_FOR_INTERNAL_VISUAL_REVIEW"),
                dict(sha256="c" * 64, leaf_id="pv:leaf2", class_code="POTATO_HEALTHY",
                     decision="PENDING", decision_reason="ELIGIBLE_FOR_INTERNAL_VISUAL_REVIEW"),
            ]
            write_rows(source / "registry.csv", list(records[0]), records)
            write_rows(source / "visual-pairs.csv", ["sha256_a", "sha256_b", "relation"],
                       [dict(sha256_a="a" * 64, sha256_b="d" * 64,
                             relation="HISTORICAL_PARTITION")])
            (source / "summary.json").write_text(json.dumps({
                "registry_sha256": sha(source / "registry.csv"),
                "visual_pairs_sha256": sha(source / "visual-pairs.csv"),
                "visual_pairs_for_review": 1,
            }))
            with redirect_stdout(StringIO()):
                resolve(source, root / "resolved")
            with (root / "resolved" / "registry.csv").open(newline="") as stream:
                result = {r["sha256"]: r for r in csv.DictReader(stream)}
            self.assertEqual(result["a" * 64]["decision"], "EXCLUDE")
            self.assertEqual(result["b" * 64]["decision"], "EXCLUDE")
            self.assertEqual(result["c" * 64]["decision"], "PENDING")
            self.assertEqual(json.loads((root / "resolved" / "summary.json").read_text())
                             ["newly_excluded_photos"], 2)


if __name__ == "__main__":
    unittest.main()
