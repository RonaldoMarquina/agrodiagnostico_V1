"""Pruebas unitarias para validación extendida del manifiesto v2 y verificación de bytes."""
import copy
import csv
import hashlib
import importlib.util
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
        self.assertTrue(all(s['eligibility'] == 'PENDING' for s in sources.values()))
        self.assertTrue(all(c['definition_status'] == 'PENDING_REVIEW' for c in classes.values()))

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

            count = v.validate_manifest_v2(csv_path, self.schema, self.classes, self.sources)
            self.assertEqual(count, 1)

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

            # Debe pasar con byte_equivalence
            count = v.validate_manifest_v2(csv_path, self.schema, self.classes, self.sources, images_dir=img_dir)
            self.assertEqual(count, 1)

            # Si el hash en el CSV es erróneo, debe fallar
            bad_row = dict(row)
            bad_row["sha256"] = "0" * 64
            with csv_path.open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.schema["required"])
                writer.writeheader()
                writer.writerow(bad_row)

            with self.assertRaisesRegex(v.InventoryError, "hash de bytes no coincide"):
                v.validate_manifest_v2(csv_path, self.schema, self.classes, self.sources, images_dir=img_dir)


if __name__ == "__main__":
    unittest.main()
