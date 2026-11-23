from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_v143_sources import VisualIndex  # noqa: E402
from prepare_v143_external import choose  # noqa: E402


def candidate(sha: str, visual_group: str, dhash: str) -> dict[str, object]:
    return {
        "sha256": sha,
        "visual_group": visual_group,
        "dhash64": dhash,
        "decision": "CANDIDATE_PENDING_INTERNAL_REVIEW",
    }


class TestV143Selection(unittest.TestCase):
    def test_visual_group_is_unique_across_separate_strata(self) -> None:
        visual = VisualIndex()
        selected_groups: set[str] = set()
        first = choose(
            [candidate("a" * 64, "visual:shared", "0000000000000000")],
            1,
            visual,
            set(),
            selected_groups,
            set(),
        )
        second = choose(
            [
                candidate("b" * 64, "visual:shared", "ffffffffffffffff"),
                candidate("c" * 64, "visual:other", "ffffffffffffffff"),
            ],
            1,
            visual,
            set(),
            selected_groups,
            set(),
        )
        self.assertEqual(first[0]["sha256"], "a" * 64)
        self.assertEqual(second[0]["sha256"], "c" * 64)
        self.assertEqual(selected_groups, {"visual:shared", "visual:other"})

    def test_cross_label_visual_group_is_never_selected(self) -> None:
        selected = choose(
            [
                candidate("d" * 64, "visual:conflict", "1111111111111111"),
                candidate("e" * 64, "visual:valid", "2222222222222222"),
            ],
            1,
            VisualIndex(),
            set(),
            set(),
            {"visual:conflict"},
        )
        self.assertEqual(selected[0]["sha256"], "e" * 64)


if __name__ == "__main__":
    unittest.main()
