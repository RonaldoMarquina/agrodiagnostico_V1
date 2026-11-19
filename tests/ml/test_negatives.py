"""Pruebas unitarias para el manifiesto de negativos autorizados y aislamiento de grupos."""
import csv
import hashlib
from pathlib import Path
import tempfile
import unittest

from agro_ml.data.negatives import (
    NEGATIVE_CSV_HEADERS,
    NegativeRecord,
    NegativeValidationError,
    load_negatives_manifest,
    validate_negatives,
)

ROOT = Path(__file__).resolve().parents[2]


class TestNegativesManifest(unittest.TestCase):
    def test_repo_negatives_v2_csv_loads_cleanly(self):
        records = load_negatives_manifest(ROOT / "ml/manifests/negatives.v2.csv")
        self.assertEqual(len(records), 0)
        count = validate_negatives(records, allow_empty=True)
        self.assertEqual(count, 0)

    def test_valid_negatives_across_allowed_categories(self):
        records = [
            NegativeRecord(
                image_id="neg_001",
                sha256=hashlib.sha256(b"tomato_leaf_1").hexdigest(),
                negative_category="OTHER_CROP",
                source="plantvillage",
                license="CC-BY-SA-3.0",
                capture_context="CONTROLLED_LEAF",
                split_group="grp_neg_tomato_1",
                split="TRAIN",
                notes="Hoja de tomate para evaluar rechazo RF-07",
            ),
            NegativeRecord(
                image_id="neg_002",
                sha256=hashlib.sha256(b"soil_background_1").hexdigest(),
                negative_category="BACKGROUND",
                source="plantdoc",
                license="CC0-1.0",
                capture_context="FIELD",
                split_group="grp_neg_bg_1",
                split="VAL",
                notes="Fondo inerte de suelo agrícola",
            ),
            NegativeRecord(
                image_id="neg_003",
                sha256=hashlib.sha256(b"ambiguous_leaf_1").hexdigest(),
                negative_category="AMBIGUOUS_LEAF",
                source="plantdoc",
                license="CC0-1.0",
                capture_context="FIELD",
                split_group="grp_neg_ambig_1",
                split="TEST",
                notes="Follaje marchito no identificable para BAD_IMAGE",
            ),
        ]
        count = validate_negatives(records)
        self.assertEqual(count, 3)

    def test_reject_forbidden_categories_and_no_concluyente(self):
        for bad_category in ["NO_CONCLUYENTE", "POTATO_EARLY_BLIGHT", "MAIZE_DISEASE", "UNKNOWN_CATEGORY"]:
            with self.subTest(category=bad_category):
                record = NegativeRecord(
                    image_id="bad_neg",
                    sha256=hashlib.sha256(b"bad").hexdigest(),
                    negative_category=bad_category,
                    source="plantvillage",
                    license="CC-BY-SA-3.0",
                    capture_context="CONTROLLED_LEAF",
                    split_group="grp_bad",
                    split="TRAIN",
                    notes="Inválido",
                )
                with self.assertRaises(NegativeValidationError):
                    validate_negatives([record])

    def test_reject_internal_partition_leakage(self):
        records = [
            NegativeRecord(
                image_id="neg_leak_1",
                sha256=hashlib.sha256(b"n1").hexdigest(),
                negative_category="OTHER_CROP",
                source="plantvillage",
                license="CC-BY-SA-3.0",
                capture_context="CONTROLLED_LEAF",
                split_group="shared_grp_neg",
                split="TRAIN",
                notes="Train",
            ),
            NegativeRecord(
                image_id="neg_leak_2",
                sha256=hashlib.sha256(b"n2").hexdigest(),
                negative_category="OTHER_CROP",
                source="plantvillage",
                license="CC-BY-SA-3.0",
                capture_context="CONTROLLED_LEAF",
                split_group="shared_grp_neg",
                split="TEST",
                notes="Fuga de grupo a TEST",
            ),
        ]
        with self.assertRaises(Exception):
            validate_negatives(records)

    def test_reject_cross_leakage_with_positive_dataset(self):
        pos_hash = hashlib.sha256(b"positive_potato_leaf").hexdigest()
        pos_records = [
            {
                "image_id": "pv_pos_1",
                "sha256": pos_hash,
                "split_group": "pos_group_123",
                "split": "TRAIN",
            }
        ]

        # Caso 1: Negativo con mismo hash que positivo
        rec_hash_conflict = NegativeRecord(
            image_id="neg_conflict_1",
            sha256=pos_hash,
            negative_category="OTHER_CROP",
            source="plantvillage",
            license="CC-BY-SA-3.0",
            capture_context="CONTROLLED_LEAF",
            split_group="grp_neg_diff",
            split="TRAIN",
            notes="Conflicto de hash con positivo",
        )
        with self.assertRaisesRegex(NegativeValidationError, "Conflicto grave: hash"):
            validate_negatives([rec_hash_conflict], positive_records=pos_records)

        # Caso 2: Negativo con mismo split_group que positivo
        rec_group_conflict = NegativeRecord(
            image_id="neg_conflict_2",
            sha256=hashlib.sha256(b"diff_bytes").hexdigest(),
            negative_category="OTHER_CROP",
            source="plantvillage",
            license="CC-BY-SA-3.0",
            capture_context="CONTROLLED_LEAF",
            split_group="pos_group_123",
            split="TRAIN",
            notes="Conflicto de grupo con positivo",
        )
        with self.assertRaisesRegex(NegativeValidationError, "Conflicto grave: split_group"):
            validate_negatives([rec_group_conflict], positive_records=pos_records)


if __name__ == "__main__":
    unittest.main()
