#!/usr/bin/env python3
"""Sella un EXTERNAL v1.4.3 únicamente después del preflight completo."""

import argparse
import json
from pathlib import Path
import sys

from agro_ml.v143_external_admission import V143AdmissionError, seal_external


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--contract", default="ml/preprocessing/potato-v143-operational-compatible.json")
    parser.add_argument("--preflight-dir", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        seal = seal_external(Path(args.manifest), Path(args.contract), Path(args.preflight_dir),
                             Path(args.approval), Path(args.output))
    except (V143AdmissionError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"V143_EXTERNAL_SEAL_FAILED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(seal, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
