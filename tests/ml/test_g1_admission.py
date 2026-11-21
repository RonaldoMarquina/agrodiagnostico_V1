"""G1 admission gates exercised only with generated pictures and invented fixture proofs."""

import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("validate_dataset_g1", ROOT / "scripts/validate_dataset.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class TestPrivateAdmission(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        self.proof = self.root / "fixture-proof.txt"
        self.proof.write_text("Prueba inventada; no es permiso de una fotografía real.")
        self.schema, self.classes, self.sources = validator.validate_inventory_v2()
        self.sources["plantvillage"]["eligibility"] = "ELIGIBLE"
        self.sources["plantvillage"]["license"]["status"] = "VERIFIED_FOR_PROJECT"
        self.classes["POTATO_EARLY_BLIGHT"]["definition_status"] = "REVIEWED"
        self.mappings = [{"source": "plantvillage", "class_code": "POTATO_EARLY_BLIGHT",
                          "source_label": "Potato___Early_blight", "status": "APPROVED"}]
        self.positive, self.pos_evidence = self._record("pos-1", "TRAIN", positive=True)
        self.negative, self.neg_evidence = self._record("neg-1", "VAL", positive=False)
        self.positive_path = self.root / "positives.csv"
        self.negative_path = self.root / "negatives.csv"
        self.evidence_path = self.root / "g1-private.json"
        self._write()

    def _record(self, name, split, *, positive):
        image = Image.new("RGB", (32, 32), color=(120, 90, 30) if positive else (20, 150, 60))
        path = self.images / f"{name}.png"
        image.save(path)
        common = {"image_id": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "source": "plantvillage", "license": "CC-BY-SA-3.0",
                  "capture_context": "CONTROLLED_LEAF", "split_group": f"group-{name}", "split": split}
        row = dict(common)
        evidence = {key: common[key] for key in ("image_id", "sha256", "source", "split_group")}
        evidence.update({"source_revision": self.sources["plantvillage"]["version"],
                         "relative_path": path.name,
                         "decision": "ADMIT", "decision_by": "fixture-reviewer",
                         "decision_at": "2026-11-19", "decision_reason": "fixture técnico solamente",
                         "rights": {"decision": "APPROVED", "allowed_uses": ["TRAINING", "EVALUATION"],
                                    "reviewer": "fixture-reviewer", "reviewed_at": "2026-11-19",
                                    "proof_path": self.proof.name, "attribution": "generated fixture",
                                    "restrictions": "fixture-only"}})
        review = {"decision": "APPROVED", "reviewer": "fixture-reviewer",
                  "reviewed_at": "2026-11-19", "evidence_note": "synthetic shape"}
        if positive:
            row.update({"crop_code": "POTATO", "class_code": "POTATO_EARLY_BLIGHT",
                        "label_quality": "REVIEWED"})
            evidence.update({"crop_code": row["crop_code"], "class_code": row["class_code"],
                             "source_label": "Potato___Early_blight"})
            review.update({"source_label": evidence["source_label"],
                           "crop_code": row["crop_code"], "class_code": row["class_code"]})
            evidence["label_review"] = review
        else:
            row.update({"negative_category": "OTHER_CROP", "notes": "fixture"})
            review["negative_category"] = row["negative_category"]
            review["quality_decision"] = "INCLUDE_AS_NEGATIVE"
            review["ambiguity_note"] = "patrón generado; solo prueba técnica"
            evidence["category_review"] = review
        return row, evidence

    def _write(self):
        with self.positive_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.schema["required"])
            writer.writeheader()
            writer.writerow(self.positive)
        from agro_ml.data.negatives import NEGATIVE_CSV_HEADERS
        with self.negative_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=NEGATIVE_CSV_HEADERS)
            writer.writeheader()
            writer.writerow(self.negative)
        self.evidence_path.write_text(json.dumps({"schema_version": 1,
                                                  "records": [self.pos_evidence, self.neg_evidence]}))

    def _positive(self):
        return validator.validate_manifest_v2(self.positive_path, self.schema, self.classes,
                                             self.sources, images_dir=self.images,
                                             evidence_path=self.evidence_path, mappings=self.mappings,
                                             allow_empty=False)

    def _negative(self):
        return validator.validate_negative_manifest_v2(self.negative_path, self.positive_path,
                                                       self.sources, images_dir=self.images,
                                                       evidence_path=self.evidence_path, allow_empty=False)

    def test_reviewed_local_fixtures_pass_both_independent_gates(self):
        self.assertEqual(self._positive(), 1)
        self.assertEqual(self._negative(), 1)
        report = validator.build_g1_validation_report(self.positive_path, self.negative_path,
                                                       self.evidence_path, 1, 1)
        self.assertEqual(report["status"], "VALIDATED_ROWS_NOT_G1_APPROVAL")
        self.assertEqual(report["positive_by_class"], {"POTATO_EARLY_BLIGHT": 1})
        self.assertEqual(report["negative_by_category"], {"OTHER_CROP": 1})
        self.assertEqual(report["positive_by_context"], {"CONTROLLED_LEAF": 1})

    def test_pending_source_and_unreviewed_mapping_are_rejected(self):
        self.sources["plantvillage"]["eligibility"] = "PENDING"
        with self.assertRaisesRegex(validator.InventoryError, "fuente no elegible"):
            self._positive()
        with self.assertRaisesRegex(validator.InventoryError, "fuente pendiente"):
            self._negative()
        self.sources["plantvillage"]["eligibility"] = "ELIGIBLE"
        self.mappings[0]["status"] = "PROVISIONAL"
        with self.assertRaisesRegex(validator.InventoryError, "equivalencia de etiqueta no aprobada"):
            self._positive()

    def test_missing_or_wrong_rights_rejected_for_both_manifests(self):
        for target, check in ((self.pos_evidence, self._positive),
                              (self.neg_evidence, self._negative)):
            original = copy.deepcopy(target["rights"])
            for change, match in (({"decision": "PENDING"}, "sin permiso"),
                                  ({"allowed_uses": []}, "permiso no cubre"),
                                  ({"proof_path": "missing.txt"}, "No such file")):
                with self.subTest(image=target["image_id"], change=change):
                    target["rights"] = {**original, **change}
                    self._write()
                    with self.assertRaisesRegex((validator.InventoryError, OSError), match):
                        check()
            target["rights"] = original
        self._write()

    def test_label_and_negative_category_review_rejected_if_missing(self):
        self.pos_evidence["label_review"]["decision"] = "PENDING"
        self._write()
        with self.assertRaisesRegex(validator.InventoryError, "sin revisión"):
            self._positive()
        self.pos_evidence["label_review"]["decision"] = "APPROVED"
        self.neg_evidence["category_review"]["negative_category"] = "BACKGROUND"
        self._write()
        with self.assertRaisesRegex(validator.InventoryError, "categoría negativa no revisada"):
            self._negative()
        self.neg_evidence["category_review"]["negative_category"] = "OTHER_CROP"
        self.neg_evidence["category_review"].pop("ambiguity_note")
        self._write()
        with self.assertRaisesRegex(validator.InventoryError, "calidad/ambigüedad"):
            self._negative()

    def test_changed_bytes_and_wrong_revision_rejected(self):
        self.pos_evidence["source_revision"] = "mutable-main"
        self._write()
        with self.assertRaisesRegex(validator.InventoryError, "revisión de fuente"):
            self._positive()
        self.pos_evidence["source_revision"] = self.sources["plantvillage"]["version"]
        self._write()
        image_path = self.images / "pos-1.png"
        image_path.write_bytes(image_path.read_bytes() + b"tampered")
        with self.assertRaisesRegex(validator.InventoryError, "hash de bytes"):
            self._positive()

    def test_negative_cross_overlap_and_invalid_license_rejected(self):
        self.negative["split_group"] = self.positive["split_group"]
        self.neg_evidence["split_group"] = self.negative["split_group"]
        self._write()
        with self.assertRaisesRegex(ValueError, "split_group"):
            self._negative()
        self.negative["split_group"] = "group-neg-1"
        self.neg_evidence["split_group"] = self.negative["split_group"]
        self.negative["license"] = "CC0-1.0"
        self._write()
        with self.assertRaisesRegex(validator.InventoryError, "licencia no coincide"):
            self._negative()

    def test_negative_hash_and_id_overlap_rejected_even_with_same_split(self):
        self.negative["split"] = "TRAIN"
        self.negative["sha256"] = self.positive["sha256"]
        self._write()
        with self.assertRaisesRegex(ValueError, "hash"):
            self._negative()
        self.negative["sha256"] = self.neg_evidence["sha256"]
        self.negative["image_id"] = self.positive["image_id"]
        self._write()
        with self.assertRaisesRegex(ValueError, "image_id"):
            self._negative()

    def test_negative_is_never_a_diagnostic_class(self):
        self.neg_evidence["class_code"] = "POTATO_EARLY_BLIGHT"
        self._write()
        with self.assertRaisesRegex(validator.InventoryError, "no puede tener clase"):
            self._negative()


if __name__ == "__main__":
    unittest.main()
