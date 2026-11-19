"""Regression: unfinished ML commands cannot manufacture successful releases."""
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from agro_ml import cli


class TestNoFalseSuccess(unittest.TestCase):
    def test_release_commands_refuse_without_writing_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(config="ml/configs/baseline_mobilenetv3.json",
                                   output_dir=directory, output=str(root / "report.json"),
                                   freeze=None, test_manifest=str(root / "missing.csv"),
                                   weights=str(root / "absent.safetensors"))
            for name in ("train", "calibrate", "freeze", "evaluate", "package"):
                with self.subTest(command=name), contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(getattr(cli, "cmd_" + name)(args), 2)
                    self.assertIn("ML_PIPELINE_NOT_READY", error.getvalue())
                    self.assertEqual(list(root.iterdir()), [])

    def test_verify_does_not_accept_readable_but_unverified_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle.json"
            bundle.write_text('{"bundle_id":"fixture"}', encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(cli.cmd_verify(SimpleNamespace(bundle=str(bundle))), 2)
            self.assertIn("ML_PIPELINE_NOT_READY", error.getvalue())
