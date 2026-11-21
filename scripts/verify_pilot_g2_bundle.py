"""Independent CPU load and fixture inference of the private pilot bundle."""
import argparse
import json
from pathlib import Path

from agro_ml.pilot_release import load_pilot_bundle, synthetic_inference_check


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--require-approval-record", action="store_true")
    args = parser.parse_args()
    model, bundle, report = load_pilot_bundle(args.bundle, args.expected_sha256,
                                               require_approval_record=args.require_approval_record)
    result = synthetic_inference_check(model, bundle)
    result.update({"bundle_sha256": args.expected_sha256,
                   "test_report_sha256": bundle["artifact_checksums"]["test_report_sha256"],
                   "g0_numeric_pass": report["g0_numeric_pass"],
                   "approval_record_required": args.require_approval_record})
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
