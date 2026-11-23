#!/usr/bin/env python3
"""Ejecuta una única evaluación EXTERNAL sellada del bundle v1.4.2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))

from agro_ml.v142_external import evaluate_once, preflight


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        freeze, _, rows = preflight(args.bundle, args.manifest, args.seal, args.protocol,
                                    args.archive, purpose="FINAL_EXTERNAL_EVALUATION")
        print(json.dumps({"status": "PREFLIGHT_PASSED_EXTERNAL_NOT_OPENED",
                          "freeze_digest": freeze["freeze_digest"], "rows": len(rows)}, sort_keys=True))
    else:
        result = evaluate_once(args.bundle, args.manifest, args.seal, args.protocol,
                               args.archive, args.output)
        print(json.dumps({"status": result["access"]["status"],
                          "g2": result["decision"]["status"],
                          "criteria": result["report"]["criteria"]}, sort_keys=True))
