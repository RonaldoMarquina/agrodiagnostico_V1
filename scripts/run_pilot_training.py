"""Explicit CPU TRAIN/VAL experiment for the admitted potato pilot."""
import argparse
import json
from pathlib import Path

from agro_ml.pilot_training import run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--split-root", type=Path, required=True)
    parser.add_argument("--images-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.config, arguments.split_root, arguments.images_root,
                         arguments.evidence, arguments.output_dir), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
