"""Negative controls for independent G1 group and historical TEST checks."""

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from scripts.verify_g1_v1_3_1 import check_isolation
from agro_ml.data.partitioning import seal_test_partitions, verify_test_partition_seal, SealTamperedError


class TestG1V131Verifier(unittest.TestCase):
    def test_distinct_leaf_groups_pass(self):
        rows = [
            {"sha256": "a", "split_group": "pv:leaf-a", "split": "TRAIN"},
            {"sha256": "b", "split_group": "pv:leaf-b", "split": "TEST"},
        ]
        self.assertEqual(check_isolation(rows, [], set()), 2)

    def test_cross_partition_leaf_is_rejected(self):
        rows = [
            {"sha256": "a", "split_group": "pv:same-leaf", "split": "TRAIN"},
            {"sha256": "b", "split_group": "pv:same-leaf", "split": "TEST"},
        ]
        with self.assertRaisesRegex(ValueError, "crosses partitions"):
            check_isolation(rows, [], set())

    def test_historical_test_and_exposed_group_are_rejected(self):
        row = {"sha256": "b", "split_group": "pv:leaf-b", "split": "TEST"}
        with self.assertRaisesRegex(ValueError, "historical TEST"):
            check_isolation([row], [{"sha256": "z", "split_group": "pv:leaf-b"}], set())
        with self.assertRaisesRegex(ValueError, "exposed"):
            check_isolation([row], [], {"pv:leaf-b"})

    def test_duplicate_sha_is_rejected(self):
        rows = [
            {"sha256": "a", "split_group": "pv:leaf-a", "split": "TRAIN"},
            {"sha256": "a", "split_group": "pv:leaf-b", "split": "TRAIN"},
        ]
        with self.assertRaisesRegex(ValueError, "Duplicate SHA"):
            check_isolation(rows, [], set())

    def test_modified_test_row_breaks_seal(self):
        records = [{"image_id": "a", "sha256": "a" * 64, "class_code": "POTATO_HEALTHY",
                    "split_group": "pv:leaf-a", "split": "TEST"}]
        with TemporaryDirectory() as temporary:
            seal = Path(temporary) / "test-seal.json"
            seal_test_partitions(records, seal, protocol_version="1.3.1")
            self.assertTrue(verify_test_partition_seal(records, seal))
            tampered = [dict(records[0], class_code="POTATO_LATE_BLIGHT")]
            with self.assertRaises(SealTamperedError):
                verify_test_partition_seal(tampered, seal)


if __name__ == "__main__":
    unittest.main()
