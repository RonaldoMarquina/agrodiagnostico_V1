#!/usr/bin/env python3
"""Recomputa en otro proceso la evidencia EXTERNAL v1.4.3."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml/src"))
from agro_ml.v143_external_evaluation import verify_completed_output

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
result = verify_completed_output(args.output)
print(json.dumps({"status": "EXTERNAL_OUTPUT_VERIFIED",
                  "g2": result["decision"]["status"],
                  "macro_f1": result["report"]["macro_f1"]}, sort_keys=True))
