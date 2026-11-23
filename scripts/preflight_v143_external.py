#!/usr/bin/env python3
"""Decodifica completamente un candidato EXTERNAL v1.4.3 sin inferencia."""

import argparse
import json
from pathlib import Path
import sys

from agro_ml.v143_external_admission import V143AdmissionError, run_preflight


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--images-root", required=True)
    parser.add_argument("--contract", default="ml/preprocessing/potato-v143-operational-compatible.json")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        report = run_preflight(Path(args.manifest), Path(args.images_root),
                               Path(args.contract), Path(args.output_dir))
    except (V143AdmissionError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"V143_EXTERNAL_PREFLIGHT_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
