"""Pruebas unitarias para validación extendida del manifiesto v2 y verificación de bytes."""
import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    Image = None  # type: ignore
    HAS_PIL = False

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("validate_dataset", ROOT / "scripts/validate_dataset.py")
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class TestDatasetValidationV2(unittest.TestCase):
    def setUp(self):
        self.schema, self.classes, self.sources = v.validate_inventory_v2()
        # Private in-memory fixtures; never promote the repository's real sources.
        self.sources['plantvillage']['eligibility'] = 'ELIGIBLE'
        self.sources['plantvillage']['license']['status'] = 'VERIFIED_FOR_PROJECT'
        for definition in self.classes.values():
            definition['definition_status'] = 'REVIEWED'

    def test_inventory_v2_structure(self):
        _, classes, sources = v.validate_inventory_v2()
        self.assertEqual(len(classes), 7)
        self.assertEqual(sources['plantvillage']['eligibility'], 'ELIGIBLE')
        self.assertTrue(all(s['eligibility'] == 'PENDING' for name, s in sources.items()
                            if name != 'plantvillage'))
        self.assertEqual({code for code, item in classes.items() if item['definition_status'] == 'REVIEWED'},
                         {'POTATO_EARLY_BLIGHT', 'POTATO_LATE_BLIGHT'})

    def test_manifest_v2_empty_allowed_for_initial_repo(self):
        count = v.validate_manifest_v2(
            ROOT / "ml/manifests/images.v2.csv",
            self.schema,
            self.classes,
            self.sources,
            allow_empty=True,
        )
        self.assertEqual(count, 0)

    def test_manifest_v2_valid_row(self):
        row = {
            "image_id": "pv_test_001",
            "sha256": hashlib.sha256(b"fake_image_bytes_1").hexdigest(),
            "crop_code": "POTATO",
            "class_code": "POTATO_EARLY_BLIGHT",
            "source": "plantvillage",
            "license": "CC-BY-SA-3.0",
            "capture_context": "CONTROLLED_LEAF",
            "label_quality": "REVIEWED",
            "split_group": "grp_pv_001",
            "split": "TRAIN",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "manifest.csv"
            with csv_path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.schema["required"])
                writer.writeheader()
                writer.writerow(row)

            with self.assertRaisesRegex(v.InventoryError, "--images-dir y --evidence"):
                v.validate_manifest_v2(csv_path, self.schema, self.classes, self.sources)

    def test_manifest_v2_rejects_synthetic_fixture(self):
        row = {
            "image_id": "synthetic_001",
            "sha256": hashlib.sha256(b"fake_synth").hexdigest(),
            "crop_code": "POTATO",
            "class_code": "POTATO_EARLY_BLIGHT",
            "source": "synthetic",
            "license": "CC-BY-SA-3.0",
            "capture_context": "SYNTHETIC",
            "label_quality": "SYNTHETIC",
            "split_group": "grp_synth_001",
            "split": "TRAIN",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "manifest.csv"
            with csv_path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.schema["required"])
                writer.writeheader()
                writer.writerow(row)

            with self.assertRaisesRegex(v.InventoryError, "fuente no elegible"):
                v.validate_manifest_v2(csv_path, self.schema, self.classes, self.sources)

    def test_manifest_v2_rejects_unadmitted_source(self):
        row = {
            "image_id": "pseg_001",
            "sha256": hashlib.sha256(b"pseg_bytes").hexdigest(),
            "crop_code": "POTATO",
            "class_code": "POTATO_EARLY_BLIGHT",
            "source": "plantseg",
            "license": "CC-BY-NC-4.0",
            "capture_context": "CONTROLLED_LEAF",
            "label_quality": "REVIEWED",
            "split_group": "grp_pseg_001",
            "split": "TRAIN",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "manifest.csv"
            with csv_path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.schema["required"])
                writer.writeheader()
                writer.writerow(row)

            with self.assertRaisesRegex(v.InventoryError, "fuente no elegible"):
                v.validate_manifest_v2(csv_path, self.schema, self.classes, self.sources)

    def test_manifest_v2_rejects_unreviewed_label(self):
        row = {
            "image_id": "pv_unrev_001",
            "sha256": hashlib.sha256(b"pv_unrev").hexdigest(),
            "crop_code": "POTATO",
            "class_code": "POTATO_EARLY_BLIGHT",
            "source": "plantvillage",
            "license": "CC-BY-SA-3.0",
            "capture_context": "CONTROLLED_LEAF",
            "label_quality": "SOURCE_ONLY",
            "split_group": "grp_001",
            "split": "TRAIN",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "manifest.csv"
            with csv_path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.schema["required"])
                writer.writeheader()
                writer.writerow(row)

            with self.assertRaisesRegex(v.InventoryError, "requiere revisión real"):
                v.validate_manifest_v2(csv_path, self.schema, self.classes, self.sources)

    def test_manifest_v2_rejects_partition_leakage(self):
        rows = [
            {
                "image_id": "pv_leak_1",
                "sha256": hashlib.sha256(b"b1").hexdigest(),
                "crop_code": "POTATO",
                "class_code": "POTATO_EARLY_BLIGHT",
                "source": "plantvillage",
                "license": "CC-BY-SA-3.0",
                "capture_context": "CONTROLLED_LEAF",
                "label_quality": "REVIEWED",
                "split_group": "shared_grp_1",
                "split": "TRAIN",
            },
            {
                "image_id": "pv_leak_2",
                "sha256": hashlib.sha256(b"b2").hexdigest(),
                "crop_code": "POTATO",
                "class_code": "POTATO_EARLY_BLIGHT",
                "source": "plantvillage",
                "license": "CC-BY-SA-3.0",
                "capture_context": "CONTROLLED_LEAF",
                "label_quality": "REVIEWED",
                "split_group": "shared_grp_1",  # Mismo grupo en split distinto
                "split": "TEST",
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "manifest.csv"
            with csv_path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.schema["required"])
                writer.writeheader()
                writer.writerows(rows)

            with self.assertRaisesRegex(v.InventoryError, "fuga split_group"):
                v.validate_manifest_v2(csv_path, self.schema, self.classes, self.sources)

    @unittest.skipUnless(HAS_PIL, "Pillow requerido para verificación de bytes")
    def test_manifest_v2_byte_equivalence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            img_dir = Path(temp_dir) / "images"
            img_dir.mkdir()

            im = Image.new("RGB", (32, 32), color=(100, 150, 200))
            img_file = img_dir / "pv_img_001.jpg"
            im.save(img_file, format="JPEG")
            actual_bytes = img_file.read_bytes()
            actual_hash = hashlib.sha256(actual_bytes).hexdigest()

            row = {
                "image_id": "pv_img_001",
                "sha256": actual_hash,
                "crop_code": "POTATO",
                "class_code": "POTATO_EARLY_BLIGHT",
                "source": "plantvillage",
                "license": "CC-BY-SA-3.0",
                "capture_context": "CONTROLLED_LEAF",
                "label_quality": "REVIEWED",
                "split_group": "grp_pv_001",
                "split": "TRAIN",
            }

            csv_path = Path(temp_dir) / "manifest.csv"
            with csv_path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.schema["required"])
                writer.writeheader()
                writer.writerow(row)

            proof = Path(temp_dir) / "permission.txt"
            proof.write_text("Comprobante sintético para prueba técnica")
            evidence_path = Path(temp_dir) / "g1.json"
            evidence_path.write_text(json.dumps({"schema_version": 1, "records": [{
                "image_id": row["image_id"], "sha256": row["sha256"],
                "decision": "ADMIT", "decision_by": "fixture-reviewer",
                "decision_at": "2026-11-19", "decision_reason": "fixture técnico solamente",
                "source": row["source"], "source_revision": self.sources[row["source"]]["version"],
                "split_group": row["split_group"], "relative_path": img_file.name,
                "source_label": "Potato___Early_blight", "class_code": row["class_code"],
                "crop_code": row["crop_code"],
                "rights": {"decision": "APPROVED", "allowed_uses": ["TRAINING"],
                           "reviewer": "fixture-reviewer", "reviewed_at": "2026-11-19",
                           "proof_path": proof.name, "attribution": "fixture", "restrictions": "fixture-only"},
                "label_review": {"decision": "APPROVED", "source_label": "Potato___Early_blight",
                                 "class_code": row["class_code"], "crop_code": row["crop_code"],
                                 "reviewer": "fixture-reviewer", "reviewed_at": "2026-11-19",
                                 "evidence_note": "etiqueta sintética revisada para prueba"}
            }]}))
            mappings = [{"source": "plantvillage", "class_code": row["class_code"],
                         "source_label": "Potato___Early_blight", "status": "APPROVED"}]
            count = v.validate_manifest_v2(csv_path, self.schema, self.classes, self.sources,
                                           images_dir=img_dir, evidence_path=evidence_path,
                                           mappings=mappings)
            self.assertEqual(count, 1)

            # El contenido local cambiado debe fallar aunque CSV y evidencia coincidan.
            img_file.write_bytes(actual_bytes + b"tampered")
            with self.assertRaisesRegex(v.InventoryError, "hash de bytes no coincide"):
                v.validate_manifest_v2(csv_path, self.schema, self.classes, self.sources,
                                       images_dir=img_dir, evidence_path=evidence_path,
                                       mappings=mappings)


if __name__ == "__main__":
    unittest.main()
