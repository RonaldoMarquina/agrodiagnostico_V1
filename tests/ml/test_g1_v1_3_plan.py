"""A v1.3 TEST candidate must not reuse hashes or groups across gates."""

import unittest

from scripts.plan_g1_v1_3_1 import verify_isolation


class TestG1V131Plan(unittest.TestCase):
    def test_independent_groups_pass(self):
        rows = [
            {"sha256": "a" * 64, "split_group": "pv:leaf1", "split": "TRAIN"},
            {"sha256": "b" * 64, "split_group": "pv:leaf1", "split": "TRAIN"},
            {"sha256": "c" * 64, "split_group": "pv:leaf2", "split": "TEST"},
        ]
        self.assertEqual(verify_isolation(rows, set(), set()), 2)

    def test_cross_split_leaf_rejected(self):
        rows = [
            {"sha256": "a" * 64, "split_group": "pv:leaf1", "split": "TRAIN"},
            {"sha256": "b" * 64, "split_group": "pv:leaf1", "split": "TEST"},
        ]
        with self.assertRaisesRegex(ValueError, "crosses partitions"):
            verify_isolation(rows, set(), set())

    def test_historical_test_sha_and_group_rejected(self):
        row = {"sha256": "a" * 64, "split_group": "pv:leaf2", "split": "TEST"}
        with self.assertRaisesRegex(ValueError, "historical TEST"):
            verify_isolation([row], {"a" * 64}, set())
        with self.assertRaisesRegex(ValueError, "historical TEST"):
            verify_isolation([row], set(), {"pv:leaf2"})


if __name__ == "__main__":
    unittest.main()
