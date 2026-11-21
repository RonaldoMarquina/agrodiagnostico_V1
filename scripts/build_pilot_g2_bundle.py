"""Stage the real frozen pilot bundle before independent G2 verification."""
import argparse
import json
from pathlib import Path

from agro_ml.pilot_release import build_pilot_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--expected-review-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--approved-at", required=True)
    args = parser.parse_args()
    print(json.dumps(build_pilot_bundle(args.review_dir, args.freeze, args.experiment,
                                         args.expected_review_sha256, args.output_dir,
                                         args.approval_id, args.approved_at), sort_keys=True))


if __name__ == "__main__":
    main()
