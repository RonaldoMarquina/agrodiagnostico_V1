"""Admission audit must reject exposed groups and unverifiable leaf identity."""

import csv
from contextlib import redirect_stdout
import hashlib
from io import BytesIO
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import audit_plantvillage_g1_v1_3 as audit


def digest(data):
    return hashlib.sha256(data).hexdigest()


def jpeg(seed):
    image = Image.new("RGB", (160, 160))
    image.putdata([((235 - seed * 3, 240 - seed * 2, 230 - seed)
                    if ((i % 160) // 20 + (i // 160) // 20 + seed) % 2
                    else (15 + seed, 20 + seed, 10 + seed)) for i in range(160 * 160)])
    stream = BytesIO()
    image.save(stream, format="JPEG")
    return stream.getvalue()


class TestG1V13Inventory(unittest.TestCase):
    def build_fixture(self, root):
        source, historical = root / "source", root / "historical"
        source.mkdir()
        historical.mkdir()
        rows = {
            "raw/color/Potato___healthy/exposed.jpg": jpeg(1),
            "raw/color/Potato___healthy/eligible.jpg": jpeg(2),
            "raw/color/Tomato___healthy/unmapped.jpg": jpeg(3),
        }
        with zipfile.ZipFile(source / "data.zip", "w") as archive:
            for path, raw in rows.items():
                archive.writestr(path, raw)
        (source / "README.md").write_text("CC BY-SA 3.0\n")
        (source / "color_train.txt").write_text(
            "raw/color/Potato___healthy/exposed.jpg\n")
        (source / "color_test.txt").write_text(
            "raw/color/Potato___healthy/eligible.jpg\n"
            "raw/color/Tomato___healthy/unmapped.jpg\n")
        (source / "leaf-map.json").write_text(json.dumps({
            "exposed": ["Potato___healthy:::11.0"],
            "eligible": ["Potato___healthy:::99.0"],
        }))
        for split in ("train", "val", "test"):
            for kind in ("positives", "negatives"):
                with (historical / f"{split}-{kind}.csv").open("w", newline="") as file:
                    csv.DictWriter(file, fieldnames=["sha256", "split_group"]).writeheader()
        pins = {name: digest((source / name).read_bytes())
                for name in ("README.md", "data.zip", "color_train.txt", "leaf-map.json")}
        return source, historical, pins, digest((source / "color_test.txt").read_bytes())

    def test_exposed_and_unmapped_never_admitted(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source, historical, pins, test_pin = self.build_fixture(root)
            with patch.object(audit, "PIN", pins), patch.object(audit, "TEST_PIN", test_pin):
                with redirect_stdout(StringIO()):
                    audit.register(source, root / "result", historical)
            with (root / "result" / "registry.csv").open(newline="") as file:
                rows = {Path(r["source_path"]).stem: r for r in csv.DictReader(file)}
            self.assertEqual(rows["exposed"]["decision_reason"], "G3_EXPOSED_GROUP")
            self.assertEqual(rows["unmapped"]["decision_reason"], "NO_VERIFIABLE_LEAF_ID")
            self.assertEqual(rows["eligible"]["decision"], "PENDING")
            self.assertEqual(rows["eligible"]["leaf_id"], "Potato___healthy:::99.0")
            self.assertEqual(rows["eligible"]["license"], "CC-BY-SA-3.0")
            self.assertFalse((root / "result" / "test-seal.json").exists())

    def test_pinned_source_change_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source, historical, pins, test_pin = self.build_fixture(root)
            (source / "README.md").write_text("rights changed")
            with patch.object(audit, "PIN", pins), patch.object(audit, "TEST_PIN", test_pin):
                with self.assertRaisesRegex(ValueError, "Pinned source changed"):
                    audit.register(source, root / "result", historical)
            self.assertFalse((root / "result").exists())

    def test_source_split_leaf_leakage_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source, historical, pins, test_pin = self.build_fixture(root)
            leaf_map = json.loads((source / "leaf-map.json").read_text())
            leaf_map["eligible"] = ["Potato___healthy:::11.0"]
            (source / "leaf-map.json").write_text(json.dumps(leaf_map))
            pins["leaf-map.json"] = digest((source / "leaf-map.json").read_bytes())
            with patch.object(audit, "PIN", pins), patch.object(audit, "TEST_PIN", test_pin):
                with self.assertRaisesRegex(ValueError, "leaf groups overlap"):
                    audit.register(source, root / "result", historical)
            self.assertFalse((root / "result").exists())


if __name__ == "__main__":
    unittest.main()
