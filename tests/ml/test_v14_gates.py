"""Pruebas offline de procedencia, aislamiento y métricas G0 v1.4.0."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "src"))

from agro_ml.v14_gates import (
    EXTERNAL_COUNTS,
    PROVENANCE_FIELDS,
    V14GateError,
    authorize_external_access,
    build_external_seal,
    calculate_external_metrics,
    validate_external_registry,
    validate_plantvillage_train_val,
    validate_provenance_record,
    verify_external_seal,
    verify_pretraining_gate,
)


HEX = "a" * 64


def external_records():
    rows = []
    serial = 0
    for code, count in EXTERNAL_COUNTS.items():
        for _ in range(count):
            digest = f"{serial:064x}"
            serial += 1
            rows.append({
                "image_id": f"sikkim:{digest}",
                "sha256": digest,
                "source_id": "sikkim-solanaceae-v1",
                "source_revision": "10.17632/4wz7zbk635.1",
                "source_url": "https://data.mendeley.com/datasets/4wz7zbk635/1",
                "author": "Kishor Chettri; Sikkim University",
                "license": "CC-BY-4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
                "source_path": f"private/{serial}.jpg",
                "split": "EXTERNAL",
                "split_group": f"sikkim-image:{digest}",
                "decision": "ADMIT_EXTERNAL",
                "decision_reason": "fixture de compuerta, no rendimiento",
                "rights_proof_path": "source-proof.json",
                "source_label": code,
                "stratum_code": code,
                "independence_unit": "UNIQUE_IMAGE_ONLY_NOT_PLANT",
            })
    return rows


def plantvillage_records():
    layout = {
        ("POTATO_EARLY_BLIGHT", "TRAIN"): (541, 136),
        ("POTATO_EARLY_BLIGHT", "VAL"): (165, 42),
        ("POTATO_LATE_BLIGHT", "TRAIN"): (499, 129),
        ("POTATO_LATE_BLIGHT", "VAL"): (153, 39),
        ("POTATO_HEALTHY", "TRAIN"): (80, 20),
        ("POTATO_HEALTHY", "VAL"): (28, 7),
        ("OTHER_CROP", "VAL"): (150, 38),
    }
    rows = []
    serial = 10000
    for (code, split), (photos, groups) in layout.items():
        for index in range(photos):
            digest = f"{serial:064x}"
            serial += 1
            group = f"pv:{code}:{split}:{index % groups}"
            rows.append({
                "image_id": f"plantvillage:{digest}",
                "sha256": digest,
                "source_id": "plantvillage",
                "source_revision": "9e97599868962bd0079b8db4b7f1efa9185fa1e7",
                "source_url": "https://huggingface.co/datasets/mohanty/PlantVillage/commit/9e97599868962bd0079b8db4b7f1efa9185fa1e7",
                "author": "Mohanty; Hughes; Salathe",
                "license": "CC-BY-SA-3.0",
                "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
                "source_path": f"raw/color/{code}/{serial}.jpg",
                "split": split,
                "split_group": group,
                "decision": "ADMIT_TRAIN_VAL",
                "decision_reason": "fixture de compuerta, no rendimiento",
                "rights_proof_path": "rights.md",
                "source_label": code,
                "stratum_code": code,
            })
    return rows


def external_results_at_boundary():
    rows = []
    for index in range(42):
        rows.append({"stratum_code": "POTATO_EARLY_BLIGHT",
                     "published_diagnosis": "POTATO_EARLY_BLIGHT" if index < 32 else None,
                     "final_state": "COMPLETADO" if index < 32 else "NO_CONCLUYENTE"})
    for index in range(76):
        rows.append({"stratum_code": "POTATO_LATE_BLIGHT",
                     "published_diagnosis": "POTATO_LATE_BLIGHT" if index < 57 else None,
                     "final_state": "COMPLETADO" if index < 57 else "NO_CONCLUYENTE"})
    for index in range(50):
        rows.append({"stratum_code": "POTATO_HEALTHY",
                     "published_diagnosis": "POTATO_EARLY_BLIGHT" if index < 5 else None,
                     "final_state": "COMPLETADO" if index < 5 else "NO_CONCLUYENTE"})
    for index in range(194):
        rows.append({"stratum_code": "OTHER_CROP",
                     "published_diagnosis": "POTATO_LATE_BLIGHT" if index < 9 else None,
                     "final_state": "COMPLETADO" if index < 9 else "NO_CONCLUYENTE"})
    return rows


class TestV14Provenance(unittest.TestCase):
    def test_each_required_provenance_field_is_enforced(self):
        base = external_records()[0]
        for field in PROVENANCE_FIELDS:
            with self.subTest(field=field):
                candidate = deepcopy(base)
                candidate[field] = ""
                with self.assertRaisesRegex(V14GateError, field):
                    validate_provenance_record(candidate)

    def test_public_url_does_not_replace_license_or_author_or_hash(self):
        base = external_records()[0]
        for field, value in (("license", "PUBLIC"), ("author", ""),
                             ("source_url", ""), ("sha256", "unknown")):
            with self.subTest(field=field):
                candidate = deepcopy(base)
                candidate[field] = value
                with self.assertRaises(V14GateError):
                    validate_provenance_record(candidate)


class TestV14TopologyAndSeal(unittest.TestCase):
    def setUp(self):
        self.external = external_records()
        self.manifest = b"fixture manifest; not agronomic evidence\n"
        self.seal = build_external_seal(self.external, self.manifest, protocol_sha256=HEX)

    def test_external_in_train_or_val_is_rejected(self):
        for split in ("TRAIN", "VAL"):
            with self.subTest(split=split):
                rows = deepcopy(self.external)
                rows[0]["split"] = split
                with self.assertRaisesRegex(V14GateError, "Sikkim fuera de EXTERNAL"):
                    validate_external_registry(rows)

    def test_manifest_or_record_change_breaks_seal(self):
        with self.assertRaisesRegex(V14GateError, "manifiesto EXTERNAL cambió"):
            verify_external_seal(self.external, self.manifest + b"tampered", self.seal)
        rows = deepcopy(self.external)
        rows[0]["decision_reason"] = "changed after seal"
        with self.assertRaisesRegex(V14GateError, "filas EXTERNAL cambiaron"):
            verify_external_seal(rows, self.manifest, self.seal)

    def test_external_is_never_available_to_selection(self):
        frozen = {
            "status": "FROZEN", "bundle_sha256": HEX, "configuration_sha256": HEX,
            "preprocessing_sha256": HEX, "class_map_sha256": HEX,
            "calibration_sha256": HEX, "threshold": {"selected_on": "VAL", "value": 0.9},
        }
        for purpose in ("TRAIN", "VAL", "CALIBRATION", "ARCHITECTURE_SELECTION",
                        "BALANCE_SELECTION", "THRESHOLD_SELECTION"):
            with self.subTest(purpose=purpose), self.assertRaisesRegex(V14GateError, "prohibido"):
                authorize_external_access(purpose, self.external, self.manifest, self.seal, frozen)

    def test_external_requires_complete_freeze(self):
        with self.assertRaisesRegex(V14GateError, "aún no congelado"):
            authorize_external_access("FINAL_EXTERNAL_EVALUATION", self.external,
                                      self.manifest, self.seal, None)
        incomplete = {"status": "FROZEN", "bundle_sha256": HEX,
                      "threshold": {"selected_on": "VAL", "value": 0.9}}
        with self.assertRaisesRegex(V14GateError, "configuration_sha256"):
            authorize_external_access("FINAL_EXTERNAL_EVALUATION", self.external,
                                      self.manifest, self.seal, incomplete)

    def test_complete_freeze_allows_only_final_external_evaluation(self):
        frozen = {
            "status": "FROZEN", "bundle_sha256": HEX, "configuration_sha256": HEX,
            "preprocessing_sha256": HEX, "class_map_sha256": HEX,
            "calibration_sha256": HEX, "threshold": {"selected_on": "VAL", "value": 0.9},
        }
        authorize_external_access("FINAL_EXTERNAL_EVALUATION", self.external,
                                  self.manifest, self.seal, frozen)

    def test_plantvillage_test_fallback_and_other_crop_train_rejected(self):
        rows = plantvillage_records()
        validate_plantvillage_train_val(rows)
        with self.assertRaisesRegex(V14GateError, "TEST histórico"):
            validate_plantvillage_train_val(rows, blocked_test_groups={rows[0]["split_group"]})
        for field, value, message in (
            ("split_group", "fallback_1", "fallback"),
            ("split", "TEST", "no permitido"),
        ):
            changed = deepcopy(rows)
            changed[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(V14GateError, message):
                validate_plantvillage_train_val(changed)
        changed = deepcopy(rows)
        changed[-1]["split"] = "TRAIN"
        with self.assertRaisesRegex(V14GateError, "no permitido"):
            validate_plantvillage_train_val(changed)

    def test_pretraining_gate_needs_both_admitted_manifests_and_matching_seal(self):
        protocol = {"protocol_version": "1.4.0", "status": "APPROVED_G0_DESIGN",
                    "gates": {"G0": "CLOSED_APPROVED"}}
        verify_pretraining_gate(plantvillage_records(), self.external, self.manifest,
                                self.seal, protocol, protocol_sha256=HEX)
        changed_seal = deepcopy(self.seal)
        changed_seal["protocol_sha256"] = "b" * 64
        with self.assertRaisesRegex(V14GateError, "protocolo aprobado"):
            verify_pretraining_gate(plantvillage_records(), self.external, self.manifest,
                                    changed_seal, protocol, protocol_sha256=HEX)


class TestV14ExternalMetrics(unittest.TestCase):
    def test_integer_boundaries_and_denominators_pass(self):
        report = calculate_external_metrics(external_results_at_boundary())
        self.assertTrue(all(report["criteria"].values()))
        self.assertEqual(report["true_positive"]["POTATO_EARLY_BLIGHT"], 32)
        self.assertEqual(report["true_positive"]["POTATO_LATE_BLIGHT"], 57)
        self.assertEqual(report["healthy_published_blight"], {"numerator": 5, "denominator": 50})
        self.assertEqual(report["healthy_no_concluyente"], {"numerator": 45, "denominator": 50})
        self.assertEqual(report["other_crop_published_blight"], {"numerator": 9, "denominator": 194})

    def test_abstention_failure_and_wrong_blight_are_false_negatives(self):
        for final_state, diagnosis in (("NO_CONCLUYENTE", None), ("FALLIDO", None),
                                       ("COMPLETADO", "POTATO_LATE_BLIGHT")):
            with self.subTest(final_state=final_state, diagnosis=diagnosis):
                rows = external_results_at_boundary()
                rows[0] = {"stratum_code": "POTATO_EARLY_BLIGHT",
                           "published_diagnosis": diagnosis, "final_state": final_state}
                report = calculate_external_metrics(rows)
                self.assertEqual(report["true_positive"]["POTATO_EARLY_BLIGHT"], 31)
                self.assertFalse(report["criteria"]["early_recall"])

    def test_incomplete_fixed_denominator_is_rejected(self):
        with self.assertRaisesRegex(V14GateError, "denominadores"):
            calculate_external_metrics(external_results_at_boundary()[:-1])


if __name__ == "__main__":
    unittest.main()
