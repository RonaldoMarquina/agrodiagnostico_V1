#!/usr/bin/env python3
"""Adquiere el único checkpoint oficial preregistrado para v1.4.2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))

from agro_ml.v142_checkpoint import acquire_checkpoint


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--terms", type=Path, default=ROOT / "docs/evidence/IMAGENET-V1.4.2-TERMS.md")
    args = parser.parse_args()
    print(json.dumps(acquire_checkpoint(args.output_root, args.terms), indent=2, sort_keys=True))
