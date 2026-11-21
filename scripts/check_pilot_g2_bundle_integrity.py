"""Tamper checks on temporary copies of a real private G2 bundle only."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

import jsonschema

from agro_ml.pilot_release import digest, load_pilot_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    load_pilot_bundle(args.bundle, args.expected_sha256, require_approval_record=True)
    names = ("pilot-weights.safetensors", "config.json", "calibration.json",
             "thresholds.json", "test-report.json", "g2-approval.json", "model-bundle.json",
             "weights_missing", "weights_symlink", "path_traversal", "incompatible_format")
    results = {}
    for name in names:
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "release"
            shutil.copytree(args.bundle.parent, copy)
            target = copy / name
            modified_manifest = name in {"path_traversal", "incompatible_format"}
            if modified_manifest:
                target = copy / "model-bundle.json"
                value = json.loads(target.read_text(encoding="utf-8"))
                if name == "path_traversal":
                    value["weights"]["filename"] = "../config.json"
                else:
                    value["weights"]["format"] = "torchscript"
                target.write_text(json.dumps(value), encoding="utf-8")
            elif name == "model-bundle.json":
                value = json.loads(target.read_text(encoding="utf-8"))
                value["class_map"]["1"]["class_code"] = "MAIZE_HEALTHY"
                target.write_text(json.dumps(value), encoding="utf-8")
            elif name == "weights_missing":
                (copy / "pilot-weights.safetensors").unlink()
            elif name == "weights_symlink":
                (copy / "pilot-weights.safetensors").unlink()
                (copy / "pilot-weights.safetensors").symlink_to("config.json")
            elif name == "g2-approval.json":
                value = json.loads(target.read_text(encoding="utf-8"))
                value["bundle_sha256"] = "0" * 64
                target.write_text(json.dumps(value), encoding="utf-8")
            else:
                with target.open("ab") as stream:
                    stream.write(b"TAMPER")
            try:
                load_pilot_bundle(copy / "model-bundle.json",
                                  digest(copy / "model-bundle.json") if modified_manifest else args.expected_sha256,
                                  require_approval_record=not modified_manifest)
            except (ValueError, FileNotFoundError, jsonschema.exceptions.ValidationError):
                results[name] = "REJECTED"
            else:
                raise AssertionError("Alteración aceptada: " + name)
    print(json.dumps(results, sort_keys=True))


if __name__ == "__main__":
    main()
