"""Contrato de decodificación y preflight completo v1.4.3."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageOps
import torch
from torchvision.transforms.functional import pil_to_tensor

from agro_ml.data.tensor_preprocessing import (
    MAX_IMAGE_BYTES,
    TensorSpec,
    decode_image_to_rgb,
    image_to_tensor,
)
from agro_ml.v143_external_admission import (
    V143AdmissionError,
    run_preflight,
    seal_external,
    verify_preflight,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "ml/preprocessing/potato-v143-operational-compatible.json"


def encoded(mode: str, fmt: str, *, color=None, transparency: bool = False) -> bytes:
    if color is None:
        color = {
            "1": 1,
            "L": 80,
            "LA": (80, 128),
            "P": 1,
            "RGB": (200, 30, 10),
            "RGBA": (200, 30, 10, 128),
            "CMYK": (0, 200, 200, 0),
            "I;16": 4096,
        }[mode]
    image = Image.new(mode, (240, 220), color)
    if mode == "P":
        palette = [255, 255, 255, 200, 30, 10] + [0] * (768 - 6)
        image.putpalette(palette)
        if transparency:
            image.info["transparency"] = 0
    stream = io.BytesIO()
    image.save(stream, format=fmt)
    return stream.getvalue()


def mpo_bytes() -> bytes:
    first = Image.new("RGB", (240, 220), (230, 20, 10))
    second = Image.new("RGB", (240, 220), (10, 20, 230))
    stream = io.BytesIO()
    first.save(stream, format="MPO", save_all=True, append_images=[second])
    return stream.getvalue()


def animated_bytes(fmt: str) -> bytes:
    first = Image.new("RGB", (240, 220), "red")
    second = Image.new("RGB", (240, 220), "blue")
    stream = io.BytesIO()
    first.save(stream, format=fmt, save_all=True, append_images=[second], duration=50)
    return stream.getvalue()


def legacy_rgb_tensor(raw: bytes, spec: TensorSpec) -> torch.Tensor:
    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        rgb = ImageOps.exif_transpose(image).convert("RGB")
        resized = rgb.resize((spec.width, spec.height), Image.Resampling.BILINEAR)
        tensor = pil_to_tensor(resized).to(dtype=torch.float32).div_(255.0)
    mean = torch.tensor(spec.mean, dtype=torch.float32).view(3, 1, 1)
    std = torch.tensor(spec.std, dtype=torch.float32).view(3, 1, 1)
    return ((tensor - mean) / std).contiguous()


class V143DecoderTests(unittest.TestCase):
    def setUp(self):
        self.spec = TensorSpec(224, 224, 200, 6000)

    def test_every_admitted_format_and_mode_converts_to_rgb(self):
        fixtures = (
            ("JPEG", "RGB", encoded("RGB", "JPEG")),
            ("JPEG", "CMYK", encoded("CMYK", "JPEG")),
            ("PNG", "1", encoded("1", "PNG")),
            ("PNG", "L", encoded("L", "PNG")),
            ("PNG", "LA", encoded("LA", "PNG")),
            ("PNG", "P", encoded("P", "PNG", transparency=True)),
            ("PNG", "RGBA", encoded("RGBA", "PNG")),
            ("TIFF", "I;16", encoded("I;16", "TIFF")),
            ("TIFF", "RGB", encoded("RGB", "TIFF")),
            ("WEBP", "RGB", encoded("RGB", "WEBP")),
        )
        for expected_format, expected_mode, raw in fixtures:
            with self.subTest(format=expected_format, mode=expected_mode):
                rgb, metadata = decode_image_to_rgb(raw, self.spec)
                tensor = image_to_tensor(raw, self.spec, split="EXTERNAL")
                self.assertEqual("RGB", rgb.mode)
                self.assertEqual((expected_format, expected_mode),
                                 (metadata.format, metadata.mode))
                self.assertEqual((1, 0), (metadata.frames, metadata.selected_frame))
                self.assertEqual((3, 224, 224), tuple(tensor.shape))
                self.assertTrue(bool(torch.isfinite(tensor).all()))

    def test_mpo_selects_first_frame_deterministically(self):
        raw = mpo_bytes()
        first, metadata = decode_image_to_rgb(raw, self.spec)
        second, repeated = decode_image_to_rgb(raw, self.spec)
        self.assertEqual(("MPO", "RGB", 2, 0),
                         (metadata.format, metadata.mode, metadata.frames,
                          metadata.selected_frame))
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertEqual(metadata, repeated)
        red, _, blue = first.getpixel((100, 100))
        self.assertGreater(red, blue * 5)

    def test_alpha_is_composited_on_white(self):
        raw = encoded("RGBA", "PNG", color=(255, 0, 0, 0))
        rgb, _ = decode_image_to_rgb(raw, self.spec)
        self.assertEqual((255, 255, 255), rgb.getpixel((0, 0)))

    def test_rgb_regression_is_identical_to_v142_geometry(self):
        for fmt in ("JPEG", "PNG", "WEBP"):
            with self.subTest(format=fmt):
                raw = encoded("RGB", fmt)
                self.assertTrue(torch.equal(
                    legacy_rgb_tensor(raw, self.spec),
                    image_to_tensor(raw, self.spec, split="EXTERNAL"),
                ))

    def test_ambiguous_or_invalid_inputs_fail_before_tensor(self):
        for fmt in ("PNG", "WEBP", "TIFF"):
            with self.subTest(multiframe=fmt), self.assertRaisesRegex(
                    ValueError, "animada|multipágina"):
                image_to_tensor(animated_bytes(fmt), self.spec, split="EXTERNAL")
        unsupported = io.BytesIO()
        Image.new("RGB", (240, 220)).save(unsupported, format="GIF")
        with self.assertRaisesRegex(ValueError, "Formato"):
            image_to_tensor(unsupported.getvalue(), self.spec, split="EXTERNAL")
        unsupported_mode = io.BytesIO()
        Image.new("F", (240, 220)).save(unsupported_mode, format="TIFF")
        with self.assertRaisesRegex(ValueError, "Modo"):
            image_to_tensor(unsupported_mode.getvalue(), self.spec, split="EXTERNAL")
        too_large = io.BytesIO()
        Image.new("RGB", (6001, 200)).save(too_large, format="PNG")
        with self.assertRaisesRegex(ValueError, "Dimensiones"):
            image_to_tensor(too_large.getvalue(), self.spec, split="EXTERNAL")
        for raw in (b"not-an-image", b"x" * (MAX_IMAGE_BYTES + 1)):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                image_to_tensor(raw, self.spec, split="EXTERNAL")


def manifest_row(path: Path, source_path: str, stratum: str, index: int) -> dict:
    raw = path.read_bytes()
    return {
        "image_id": f"external-{index:03d}",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "file_size": len(raw),
        "source_id": "fixture-independent-v1",
        "source_version": "1",
        "source_url": "https://example.invalid/dataset/1",
        "license": "CC BY 4.0",
        "license_evidence_url": "https://example.invalid/dataset/1#license",
        "source_path": source_path,
        "source_label": stratum,
        "stratum_code": stratum,
        "capture_origin": "fixture generated by test",
        "independence_unit": "UNIQUE_FIXTURE",
        "label_review": "TEST_FIXTURE_ONLY",
        "decision": "ADMITTED",
        "decision_reason": "valid contract fixture",
    }


class V143PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.images = self.root / "images"
        self.images.mkdir()
        self.rows = []
        for index, (stratum, fmt) in enumerate((
            ("POTATO_EARLY_BLIGHT", "JPEG"),
            ("POTATO_LATE_BLIGHT", "PNG"),
            ("POTATO_HEALTHY", "WEBP"),
            ("OTHER_CROP", "TIFF"),
        )):
            relative = f"source/{index}.{fmt.lower()}"
            target = self.images / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(encoded("RGB", fmt))
            self.rows.append(manifest_row(target, relative, stratum, index))
        self.manifest = self.root / "manifest.jsonl"
        self.write_manifest(self.rows)

    def tearDown(self):
        self.temporary.cleanup()

    def write_manifest(self, rows):
        self.manifest.write_text("".join(
            json.dumps(row, sort_keys=True) + "\n" for row in rows
        ), encoding="utf-8")

    def test_preflight_decodes_every_file_without_model_or_metrics(self):
        output = self.root / "preflight"
        report = run_preflight(self.manifest, self.images, CONTRACT, output)
        self.assertEqual(4, report["record_count"])
        self.assertTrue(report["all_files_decoded"])
        self.assertFalse(report["model_loaded"])
        self.assertFalse(report["predictions_generated"])
        self.assertFalse(report["metrics_generated"])
        self.assertEqual(report, verify_preflight(self.manifest, CONTRACT, output))
        records = [json.loads(line) for line in
                   (output / "compatibility.jsonl").read_text().splitlines()]
        self.assertEqual({row["sha256"] for row in self.rows},
                         {row["sha256"] for row in records})
        self.assertFalse(any("source_path" in row for row in records))

    def test_any_invalid_file_blocks_all_output(self):
        cases = []
        mutated = [dict(row) for row in self.rows]
        mutated[0]["sha256"] = "a" * 64
        cases.append(mutated)
        duplicate = [dict(row) for row in self.rows]
        duplicate[1]["sha256"] = duplicate[0]["sha256"]
        cases.append(duplicate)
        missing = [dict(row) for row in self.rows]
        missing[0]["source_path"] = "missing.jpg"
        cases.append(missing)
        for index, rows in enumerate(cases):
            with self.subTest(index=index):
                self.write_manifest(rows)
                output = self.root / f"failed-{index}"
                with self.assertRaises((V143AdmissionError, ValueError)):
                    run_preflight(self.manifest, self.images, CONTRACT, output)
                self.assertFalse(output.exists())

    def test_sikkim_is_rejected_before_image_access(self):
        rows = [dict(row) for row in self.rows]
        rows[0]["source_id"] = "Sikkim-v1"
        rows[0]["source_path"] = "file-that-does-not-exist.jpg"
        self.write_manifest(rows)
        with self.assertRaisesRegex(V143AdmissionError, "Sikkim"):
            run_preflight(self.manifest, self.images, CONTRACT, self.root / "blocked")

    def test_seal_requires_complete_unchanged_preflight_and_approval(self):
        preflight = self.root / "preflight"
        report = run_preflight(self.manifest, self.images, CONTRACT, preflight)
        approval = self.root / "approval.json"
        approval.write_text(json.dumps({
            "cycle_version": "1.4.3",
            "status": "APPROVED_BY_PROJECT_OWNER",
            "approved_at": "2026-11-23",
            "justification": "fixture contract boundary",
            "counts_by_stratum": report["counts_by_stratum"],
            "external_criteria": {
                "macro_f1_min": 0.75,
                "recall_min_by_blight": 0.75,
                "healthy_false_publication_max": 0,
                "healthy_rejection_min": 1,
                "other_crop_false_publication_max": 0,
            },
        }), encoding="utf-8")
        seal_path = self.root / "seal.json"
        seal = seal_external(self.manifest, CONTRACT, preflight, approval, seal_path)
        self.assertEqual("SEALED_NOT_OPENED_FOR_EVALUATION", seal["status"])
        self.assertFalse(seal["opened_for_evaluation"])
        self.assertEqual("e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c",
                         seal["weights_sha256"])
        changed = [dict(row) for row in self.rows]
        changed[0]["decision_reason"] = "changed after preflight"
        self.write_manifest(changed)
        with self.assertRaisesRegex(V143AdmissionError, "hashes|alterad"):
            seal_external(self.manifest, CONTRACT, preflight, approval, self.root / "other.json")


if __name__ == "__main__":
    unittest.main()
