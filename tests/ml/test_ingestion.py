"""Pruebas unitarias de ingestión segura de imágenes y cuarentena."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    Image = None  # type: ignore
    HAS_PIL = False

from agro_ml.data.ingestion import (
    ImageIngestionService,
    PathTraversalError,
    QuarantineRecord,
)

ROOT = Path(__file__).resolve().parents[2]


def create_test_image(size=(32, 32), color=(120, 200, 80), img_format="JPEG") -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format=img_format)
    return buf.getvalue()


@unittest.skipUnless(HAS_PIL, "Pillow (PIL) no disponible en este entorno")
class TestImageIngestion(unittest.TestCase):
    def setUp(self):
        self.sources_doc = json.loads((ROOT / "ml/manifests/sources.v2.json").read_text(encoding="utf-8"))
        self.label_mappings_doc = json.loads((ROOT / "ml/manifests/label-mappings.v2.json").read_text(encoding="utf-8"))
        self.taxonomy_doc = json.loads((ROOT / "ml/manifests/taxonomy.v2.json").read_text(encoding="utf-8"))
        # Explicit in-memory admission fixture: does not approve the real inventory.
        for source in self.sources_doc['sources']:
            if source['source_id'] == 'plantvillage':
                source['eligibility'] = 'ELIGIBLE'
                source['license']['status'] = 'SYNTHETIC_ONLY'
        for mapping in self.label_mappings_doc['mappings']:
            if mapping['source'] == 'plantvillage' and mapping['source_label']:
                mapping['status'] = 'APPROVED'
        self.service = ImageIngestionService(
            sources_doc=self.sources_doc,
            label_mappings_doc=self.label_mappings_doc,
            taxonomy_doc=self.taxonomy_doc,
        )

    def test_ingest_valid_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            img_rel = "potato_early_blight_01.jpg"
            img_path = base / img_rel
            img_path.write_bytes(create_test_image())

            record = self.service.ingest_single_image(
                base_dir=base,
                relative_path=img_rel,
                source="plantvillage",
                source_label="Potato___Early_blight",
            )
            self.assertIsNotNone(record)
            self.assertEqual(record.crop_code, "POTATO")
            self.assertEqual(record.class_code, "POTATO_EARLY_BLIGHT")
            self.assertEqual(record.source, "plantvillage")
            self.assertEqual(record.license, "CC-BY-SA-3.0")
            self.assertEqual(record.capture_context, "CONTROLLED_LEAF")
            self.assertEqual(record.label_quality, "REVIEWED")
            self.assertEqual(record.width, 32)
            self.assertEqual(record.height, 32)
            self.assertEqual(len(record.sha256), 64)
            self.assertEqual(len(self.service.quarantine), 0)

    def test_path_traversal_detection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir) / "source_subdir"
            base.mkdir()
            outside_file = Path(temp_dir) / "outside.jpg"
            outside_file.write_bytes(create_test_image())

            # Intento con ../
            record = self.service.ingest_single_image(
                base_dir=base,
                relative_path="../outside.jpg",
                source="plantvillage",
                source_label="Potato___Early_blight",
            )
            self.assertIsNone(record)
            self.assertEqual(len(self.service.quarantine), 1)
            self.assertEqual(self.service.quarantine[0].reason_code, "PATH_TRAVERSAL_ATTEMPT")

    def test_corrupt_bytes_quarantine(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            corrupt_file = base / "corrupt.jpg"
            corrupt_file.write_bytes(b"\xFF\xD8\xFF\xE0" + b"CorruptGarbageDataNotAnImage" * 10)

            record = self.service.ingest_single_image(
                base_dir=base,
                relative_path="corrupt.jpg",
                source="plantvillage",
                source_label="Potato___Early_blight",
            )
            self.assertIsNone(record)
            self.assertEqual(len(self.service.quarantine), 1)
            self.assertEqual(self.service.quarantine[0].reason_code, "DECODE_ERROR")
            self.assertIsNotNone(self.service.quarantine[0].sha256)

    def test_truncated_bytes_quarantine(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            valid_bytes = create_test_image(size=(100, 100))
            # Truncar los bytes a la mitad
            truncated_file = base / "truncated.jpg"
            truncated_file.write_bytes(valid_bytes[: len(valid_bytes) // 3])

            record = self.service.ingest_single_image(
                base_dir=base,
                relative_path="truncated.jpg",
                source="plantvillage",
                source_label="Potato___Early_blight",
            )
            self.assertIsNone(record)
            self.assertEqual(len(self.service.quarantine), 1)
            self.assertEqual(self.service.quarantine[0].reason_code, "DECODE_ERROR")

    def test_unadmitted_source_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            img_file = base / "leaf.jpg"
            img_file.write_bytes(create_test_image())

            # 'plantseg' está EXCLUDED en sources.v2.json
            record = self.service.ingest_single_image(
                base_dir=base,
                relative_path="leaf.jpg",
                source="plantseg",
                source_label="Potato___Early_blight",
            )
            self.assertIsNone(record)
            self.assertEqual(len(self.service.quarantine), 1)
            self.assertEqual(self.service.quarantine[0].reason_code, "UNADMITTED_SOURCE")

    def test_unmapped_label_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            img_file = base / "tomato.jpg"
            img_file.write_bytes(create_test_image())

            # 'Tomato___healthy' no está en label-mappings.v2.json
            record = self.service.ingest_single_image(
                base_dir=base,
                relative_path="tomato.jpg",
                source="plantvillage",
                source_label="Tomato___healthy",
            )
            self.assertIsNone(record)
            self.assertEqual(len(self.service.quarantine), 1)
            self.assertEqual(self.service.quarantine[0].reason_code, "UNMAPPED_LABEL")

    def test_file_size_limits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            tiny_file = base / "tiny.jpg"
            tiny_file.write_bytes(b"short")

            record = self.service.ingest_single_image(
                base_dir=base,
                relative_path="tiny.jpg",
                source="plantvillage",
                source_label="Potato___Early_blight",
            )
            self.assertIsNone(record)
            self.assertEqual(len(self.service.quarantine), 1)
            self.assertEqual(self.service.quarantine[0].reason_code, "FILE_SIZE_LIMIT")

    def test_quarantine_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            corrupt_file = base / "bad.jpg"
            corrupt_file.write_bytes(b"\x00" * 200)

            self.service.ingest_single_image(
                base_dir=base,
                relative_path="bad.jpg",
                source="plantvillage",
                source_label="Potato___Early_blight",
            )
            out_json = base / "quarantine.json"
            self.service.export_quarantine(out_json)
            self.assertTrue(out_json.is_file())
            data = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 2)
            self.assertEqual(data["quarantined_total"], 1)
            self.assertEqual(data["records"][0]["reason_code"], "DECODE_ERROR")


if __name__ == "__main__":
    unittest.main()
