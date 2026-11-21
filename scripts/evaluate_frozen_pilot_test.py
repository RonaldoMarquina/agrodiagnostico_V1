"""Evaluate the exact frozen v1.2.0 candidate on sealed TEST once."""

import argparse
import json
from pathlib import Path

from agro_ml.pilot_test_evaluation import evaluate_once


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--split-root", type=Path, required=True)
    parser.add_argument("--images-root", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected-seal-sha256", required=True)
    parser.add_argument("--expected-freeze-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate_once(args.freeze, args.split_root, args.images_root,
                                   args.evidence, args.expected_seal_sha256,
                                   args.expected_freeze_sha256, args.output_dir), sort_keys=True))


if __name__ == "__main__":
    main()
