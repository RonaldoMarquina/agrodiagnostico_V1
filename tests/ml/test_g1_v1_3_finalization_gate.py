"""No G1 admission or TEST seal may occur under a proposed numeric protocol."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.finalize_g1_v1_3_1 import finalize, require_approved_protocol


class TestFinalizationGate(unittest.TestCase):
    def test_proposed_protocol_rejected_before_output(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            protocol = root / "protocol.json"
            protocol.write_text('{"protocol_version":"1.3.1","status":"PROPOSED_AWAITING_PROJECT_OWNER_APPROVAL"}')
            output = root / "g1"
            with self.assertRaisesRegex(ValueError, "not approved"):
                finalize(root / "missing-source", root / "missing-old", root / "missing-resolution",
                         root / "missing-review", root / "missing-plan", protocol, output)
            self.assertFalse(output.exists())

    def test_false_owner_approval_rejected(self):
        candidate = {"protocol_version": "1.3.1", "status": "APPROVED_G0_DESIGN",
                     "gates": {"G0": "CLOSED_APPROVED"}, "approved_at": "2026-11-21",
                     "approval": {"approved_by_role": "PROJECT_OWNER", "approved_at": "2026-11-21"}}
        with self.assertRaisesRegex(ValueError, "lacks explicit owner approval evidence"):
            require_approved_protocol(candidate)


if __name__ == "__main__":
    unittest.main()
