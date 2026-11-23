from copy import deepcopy
import json
from pathlib import Path
import unittest

from agro_ml.v141_gates import EXPECTED, V141GateError, validate_train_val, verify_pretraining_gate

ROOT = Path(__file__).resolve().parents[2]


def rows():
    result, serial = [], 1
    for code, splits in EXPECTED.items():
        for split, (photos, groups) in splits.items():
            for index in range(photos):
                digest = f"{serial:064x}"
                serial += 1
                result.append({
                    "image_id": f"plantvillage:{digest}", "sha256": digest,
                    "source_id": "plantvillage",
                    "source_revision": "9e97599868962bd0079b8db4b7f1efa9185fa1e7",
                    "source_url": "https://huggingface.co/datasets/mohanty/PlantVillage",
                    "author": "PlantVillage authors", "license": "CC-BY-SA-3.0",
                    "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
                    "source_path": f"raw/{digest}.jpg", "split": split,
                    "split_group": f"pv:{code}:{split}:{index % groups}",
                    "decision": "ADMIT_TRAIN_VAL", "decision_reason": "fixture",
                    "rights_proof_path": "rights.md", "source_label": code,
                    "stratum_code": code,
                })
    return result


class V141GatesTests(unittest.TestCase):
    def test_exact_topology_includes_other_train_and_val(self):
        report = validate_train_val(rows())
        self.assertEqual({"photos": 1623, "groups": 412}, report["totals"]["TRAIN"])
        self.assertEqual({"photos": 496, "groups": 126}, report["totals"]["VAL"])
        self.assertEqual(503, report["classes"]["OTHER_CROP"]["TRAIN"]["photos"])

    def test_rejects_fallback_test_sikkim_overlap_and_missing_other(self):
        base = rows()
        cases = []
        changed = deepcopy(base); changed[0]["split_group"] = "fallback_1"; cases.append(changed)
        changed = deepcopy(base); changed[0]["split"] = "TEST"; cases.append(changed)
        changed = deepcopy(base); changed[0]["source_id"] = "sikkim-solanaceae-v1"; cases.append(changed)
        changed = deepcopy(base); changed[-1]["sha256"] = changed[0]["sha256"]; cases.append(changed)
        cases.append(base[:-1])
        for candidate in cases:
            with self.subTest(case=len(candidate)), self.assertRaises(V141GateError):
                validate_train_val(candidate)

    def test_gate_rejects_parent_seal_or_history_mutation(self):
        protocol = json.loads((ROOT / "ml/evaluation/protocol-g0.v1.4.1.json").read_text())
        history = json.loads((ROOT / "ml/evaluation/v1.4.0-history-index.json").read_text())
        parent = json.loads((ROOT / "ml/evaluation/gate-status.v1.4.0.json").read_text())
        verify_pretraining_gate(protocol, history, rows(), parent)
        for obj, key in ((parent, "external_seal_sha256"),):
            changed = deepcopy(obj); changed[key] = "0" * 64
            with self.assertRaises(V141GateError):
                verify_pretraining_gate(protocol, history, rows(), changed)
        changed_history = deepcopy(history)
        changed_history["comparison"]["other_crop_published"] = 7
        with self.assertRaises(V141GateError):
            verify_pretraining_gate(protocol, changed_history, rows(), parent)


if __name__ == "__main__":
    unittest.main()
