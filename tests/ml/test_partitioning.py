"""Pruebas unitarias para particionado, verificación de fugas en 6 pares, sello y auditoría."""
import copy
import io
import itertools
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

from agro_ml.data.partitioning import (
    PARTITIONS,
    PartitionError,
    PartitionLeakageError,
    SealTamperedError,
    audit_test_access,
    compute_split_digest,
    seal_test_partitions,
    verify_partition_leakage,
    verify_test_partition_seal,
)
from agro_ml.data.preprocessing import apply_transforms


class TestPartitioningAndSeals(unittest.TestCase):
    def setUp(self):
        self.sample_records = [
            {
                "image_id": f"img_{i}",
                "sha256": f"hash_{i:04d}" + "a" * 60,
                "crop_code": "POTATO",
                "class_code": "POTATO_EARLY_BLIGHT",
                "split_group": f"grp_{i // 2}",
                "split": "TRAIN" if i < 10 else ("VAL" if i < 14 else ("TEST" if i < 18 else "EXTERNAL")),
            }
            for i in range(20)
        ]

    def test_verify_leakage_clean_passes(self):
        # El conjunto de setUp no tiene fugas
        verify_partition_leakage(self.sample_records)

    def test_all_six_partition_pairs_leakage_detected(self):
        # Probar exhaustivamente los 6 pares de particiones
        pairs = list(itertools.combinations(PARTITIONS, 2))
        self.assertEqual(len(pairs), 6)

        for p_a, p_b in pairs:
            # Prueba fuga por split_group
            with self.subTest(pair=(p_a, p_b), leak_type="split_group"):
                records = copy.deepcopy(self.sample_records)
                rec_a = next(r for r in records if r["split"] == p_a)
                rec_b = next(r for r in records if r["split"] == p_b)
                rec_b["split_group"] = rec_a["split_group"]

                with self.assertRaises(PartitionLeakageError):
                    verify_partition_leakage(records)

            # Prueba fuga por sha256
            with self.subTest(pair=(p_a, p_b), leak_type="sha256"):
                records = copy.deepcopy(self.sample_records)
                rec_a = next(r for r in records if r["split"] == p_a)
                rec_b = next(r for r in records if r["split"] == p_b)
                rec_b["sha256"] = rec_a["sha256"]

                with self.assertRaises(PartitionLeakageError):
                    verify_partition_leakage(records)

    def test_seal_test_partitions_creation_and_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            seal_file = Path(temp_dir) / "seal.json"
            seal = seal_test_partitions(self.sample_records, seal_file)

            self.assertTrue(seal_file.is_file())
            self.assertEqual(seal.test_count, 4)
            self.assertEqual(seal.external_count, 2)
            self.assertTrue(len(seal.test_seal) == 64)

            # Verificación positiva
            verified = verify_test_partition_seal(self.sample_records, seal_file)
            self.assertTrue(verified)

    def test_empty_test_cannot_be_sealed_or_verified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            seal_file = Path(temp_dir) / "seal.json"
            without_test = [r for r in self.sample_records if r["split"] != "TEST"]
            with self.assertRaises(PartitionError):
                seal_test_partitions(without_test, seal_file)
            self.assertFalse(seal_file.exists())
            seal_file.write_text('{"test_seal":"","test_count":0}', encoding="utf-8")
            with self.assertRaises(SealTamperedError):
                verify_test_partition_seal(without_test, seal_file)

    def test_seal_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            seal_file = Path(temp_dir) / "seal.json"
            seal_test_partitions(self.sample_records, seal_file)

            # Alteración 1: cambiar una etiqueta en TEST
            tampered_records_1 = copy.deepcopy(self.sample_records)
            for r in tampered_records_1:
                if r["split"] == "TEST":
                    r["class_code"] = "POTATO_LATE_BLIGHT"
                    break
            with self.assertRaises(SealTamperedError):
                verify_test_partition_seal(tampered_records_1, seal_file)

            # Alteración 2: eliminar un elemento de TEST
            tampered_records_2 = [r for r in self.sample_records if r["image_id"] != "img_15"]
            with self.assertRaises(SealTamperedError):
                verify_test_partition_seal(tampered_records_2, seal_file)

            # Alteración 3: cambiar hash de una imagen en TEST
            tampered_records_3 = copy.deepcopy(self.sample_records)
            for r in tampered_records_3:
                if r["split"] == "TEST":
                    r["sha256"] = "f" * 64
                    break
            with self.assertRaises(SealTamperedError):
                verify_test_partition_seal(tampered_records_3, seal_file)

    def test_audit_test_access_logging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            seal_file = Path(temp_dir) / "seal.json"
            audit_log = Path(temp_dir) / "audit.log"
            seal_test_partitions(self.sample_records, seal_file)

            entry = audit_test_access(
                split="TEST",
                purpose="Evaluación formal de aprobación G2",
                caller="evaluator_cli",
                records=self.sample_records,
                seal_path=seal_file,
                audit_log_path=audit_log,
            )

            self.assertTrue(entry["seal_verified"])
            self.assertEqual(entry["split"], "TEST")
            self.assertEqual(entry["sample_count"], 4)
            self.assertTrue(audit_log.is_file())

            # Verificar que el log contiene la línea JSON
            log_lines = audit_log.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(log_lines), 1)
            parsed = json.loads(log_lines[0])
            self.assertEqual(parsed["caller"], "evaluator_cli")

    @unittest.skipUnless(HAS_PIL, "Pillow requerido para transformaciones")
    def test_augmentations_strictly_prohibited_outside_train(self):
        # Crear bytes de imagen sintética
        buf = io.BytesIO()
        im = Image.new("RGB", (256, 256), color=(100, 200, 100))
        im.save(buf, format="JPEG")
        raw_bytes = buf.getvalue()

        # TRAIN con aumentación: PERMITIDO
        features_train = apply_transforms(raw_bytes, split="TRAIN", augment=True)
        self.assertEqual(len(features_train), 64)

        # VAL con aumentación: PROHIBIDO
        with self.assertRaisesRegex(ValueError, "prohibidas en partición 'VAL'"):
            apply_transforms(raw_bytes, split="VAL", augment=True)

        # TEST con aumentación: PROHIBIDO
        with self.assertRaisesRegex(ValueError, "prohibidas en partición 'TEST'"):
            apply_transforms(raw_bytes, split="TEST", augment=True)

        # EXTERNAL con aumentación: PROHIBIDO
        with self.assertRaisesRegex(ValueError, "prohibidas en partición 'EXTERNAL'"):
            apply_transforms(raw_bytes, split="EXTERNAL", augment=True)

        # VAL y TEST sin aumentación: PERMITIDO (transformación determinista)
        features_val = apply_transforms(raw_bytes, split="VAL", augment=False)
        features_test = apply_transforms(raw_bytes, split="TEST", augment=False)
        self.assertEqual(len(features_val), 64)
        self.assertEqual(len(features_test), 64)


if __name__ == "__main__":
    unittest.main()
