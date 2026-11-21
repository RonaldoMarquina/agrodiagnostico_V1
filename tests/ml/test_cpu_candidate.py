"""Candidato CPU local: software con fixtures, sin admisión G1 ni release G2."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from agro_ml.cpu_candidate import evaluate_val, package_candidate, read_manifest, train
from agro_ml.models.architectures import CLASS_MAPPING
from agro_ml.smoke import fixture_image


class TestCpuCandidate(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        self.config = Path(__file__).resolve().parents[2] / "ml/configs/cpu-candidate.v1.json"
        self.train_manifest = self._manifest("TRAIN", 0)
        self.val_manifest = self._manifest("VAL", 1)

    def _manifest(self, split, variant):
        records = []
        for label in (0, 3):
            raw = fixture_image(label, variant=variant)
            name = f"{split.lower()}-{label}.png"
            (self.images / name).write_bytes(raw)
            records.append({"relative_path": name, "sha256": hashlib.sha256(raw).hexdigest(),
                            "class_code": CLASS_MAPPING[label]["class_code"],
                            "split_group": f"{split}-{label}"})
        path = self.root / f"{split.lower()}.json"
        path.write_text(json.dumps({"schema_version": 1, "scope": "FIXTURE_ONLY",
                                    "dataset_version": "0.0.0-fixture", "split": split,
                                    "records": records}), encoding="utf-8")
        return path

    def test_train_evaluate_package_cpu_candidate_without_g2(self):
        first = train(self.config, self.train_manifest, self.images, self.root / "first")
        second = train(self.config, self.train_manifest, self.images, self.root / "second")
        self.assertEqual(first["weights_sha256"], second["weights_sha256"])
        self.assertEqual(first["status"], "FIXTURE_ONLY")
        checkpoint = Path(first["checkpoint"])
        metadata = json.loads(checkpoint.read_text())
        self.assertEqual(metadata["base_weights"]["source"], "RANDOM_INITIALIZATION")
        self.assertFalse(metadata["base_weights"]["downloaded"])
        self.assertEqual(metadata["runtime"]["device"], "cpu")
        evaluation = self.root / "val-report.json"
        result = evaluate_val(checkpoint, self.train_manifest, self.val_manifest, self.images, evaluation)
        second_evaluation = self.root / "second-val-report.json"
        evaluate_val(Path(second["checkpoint"]), self.train_manifest, self.val_manifest,
                     self.images, second_evaluation)
        self.assertEqual(evaluation.read_bytes(), second_evaluation.read_bytes())
        self.assertEqual(result["scope"], "VAL_ONLY")
        report = json.loads(evaluation.read_text())
        self.assertEqual(report["status"], "FIXTURE_ONLY")
        self.assertIsNone(report["selected_for_release"])
        self.assertIsNone(report["approval"])
        self.assertEqual(report["metrics"]["dataset_split"], "VAL")
        self.assertIsNone(report["metrics"]["selective_coverage"])  # Sin decisión de publicación.
        package = self.root / "candidate.zip"
        package_candidate(checkpoint, evaluation, package, self.train_manifest, self.val_manifest, self.images)
        with zipfile.ZipFile(package) as archive:
            index = json.loads(archive.read("candidate-index.json"))
            self.assertEqual(index["status"], "FIXTURE_ONLY")
            self.assertIsNone(index["approval"])
            self.assertEqual(set(archive.namelist()), {
                "candidate-checkpoint.json", "candidate-weights.safetensors",
                "candidate-evaluation.json", "candidate-index.json"})

    def test_cli_commands_execute_without_test_or_release(self):
        checkpoint_dir = self.root / "cli-candidate"
        commands = [
            ["cpu-train", "--config", str(self.config), "--manifest", str(self.train_manifest),
             "--images-root", str(self.images), "--output-dir", str(checkpoint_dir)],
            ["cpu-evaluate-val", "--checkpoint", str(checkpoint_dir / "candidate-checkpoint.json"),
             "--train-manifest", str(self.train_manifest), "--val-manifest", str(self.val_manifest),
             "--images-root", str(self.images), "--output", str(self.root / "cli-val.json")],
            ["cpu-package-candidate", "--checkpoint", str(checkpoint_dir / "candidate-checkpoint.json"),
             "--evaluation", str(self.root / "cli-val.json"), "--train-manifest", str(self.train_manifest),
             "--val-manifest", str(self.val_manifest), "--images-root", str(self.images),
             "--output", str(self.root / "cli-candidate.zip")],
        ]
        for command in commands:
            with self.subTest(command=command[0]):
                completed = subprocess.run([sys.executable, "-m", "agro_ml.cli", *command],
                                           capture_output=True, text=True, check=True)
                self.assertIn("FIXTURE_ONLY", completed.stdout)
        self.assertTrue((self.root / "cli-candidate.zip").is_file())

    def test_fixture_generator_produces_local_manifests_only(self):
        output = self.root / "generated"
        completed = subprocess.run([sys.executable, "-m", "agro_ml.cli", "cpu-fixture-data",
                                    "--output-dir", str(output)], capture_output=True, text=True, check=True)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "FIXTURE_ONLY")
        for split in ("TRAIN", "VAL"):
            document, samples, _, _ = read_manifest(Path(result["manifests"][split]),
                                                     Path(result["images_root"]), split)
            self.assertEqual(document["scope"], "FIXTURE_ONLY")
            self.assertEqual(len(samples), 2)

    def test_rejects_test_split_and_train_val_leakage(self):
        result = train(self.config, self.train_manifest, self.images, self.root / "candidate")
        checkpoint = Path(result["checkpoint"])
        test_doc = json.loads(self.val_manifest.read_text())
        test_doc["split"] = "TEST"
        self.val_manifest.write_text(json.dumps(test_doc))
        with self.assertRaisesRegex(ValueError, "Partición"):
            evaluate_val(checkpoint, self.train_manifest, self.val_manifest, self.images, self.root / "no.json")
        test_doc["split"] = "VAL"
        test_doc["records"][0]["split_group"] = "TRAIN-0"
        self.val_manifest.write_text(json.dumps(test_doc))
        with self.assertRaisesRegex(ValueError, "Fuga"):
            evaluate_val(checkpoint, self.train_manifest, self.val_manifest, self.images, self.root / "no.json")
        self.assertFalse((self.root / "no.json").exists())

    def test_rejects_unverified_image_and_tampered_weights(self):
        document = json.loads(self.train_manifest.read_text())
        document["scope"] = "G1_ADMITTED"
        document["g1_evidence_ref"] = "fixture-claim"
        self.train_manifest.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "derechos o revisión"):
            train(self.config, self.train_manifest, self.images, self.root / "not-admitted")
        self.assertFalse((self.root / "not-admitted").exists())
        document["scope"] = "FIXTURE_ONLY"
        self.train_manifest.write_text(json.dumps(document))
        result = train(self.config, self.train_manifest, self.images, self.root / "candidate")
        checkpoint = Path(result["checkpoint"])
        weights = checkpoint.with_name("candidate-weights.safetensors")
        weights.write_bytes(weights.read_bytes() + b"tamper")
        with self.assertRaisesRegex(ValueError, "Pesos alterados"):
            evaluate_val(checkpoint, self.train_manifest, self.val_manifest, self.images, self.root / "no.json")

    def test_package_rejects_edited_val_metric(self):
        result = train(self.config, self.train_manifest, self.images, self.root / "candidate")
        checkpoint = Path(result["checkpoint"])
        evaluation = self.root / "val-report.json"
        evaluate_val(checkpoint, self.train_manifest, self.val_manifest, self.images, evaluation)
        report = json.loads(evaluation.read_text())
        report["metrics"]["accuracy"] = 1.0
        evaluation.write_text(json.dumps(report), encoding="utf-8")
        output = self.root / "false-metrics.zip"
        with self.assertRaisesRegex(ValueError, "alterada"):
            package_candidate(checkpoint, evaluation, output,
                              self.train_manifest, self.val_manifest, self.images)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
