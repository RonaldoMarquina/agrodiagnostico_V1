#!/usr/bin/env python3
"""Congela el candidato v1.4.2 que pasó VAL sin abrir EXTERNAL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))

from agro_ml.v142_freeze import freeze_candidate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--preprocessing", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--frozen-at")
    args = parser.parse_args()
    print(json.dumps(freeze_candidate(args.candidate, args.output, plan=args.plan,
                                      preprocessing=args.preprocessing, protocol=args.protocol,
                                      checkpoint_root=args.checkpoint_root,
                                      frozen_at=args.frozen_at), indent=2, sort_keys=True))
