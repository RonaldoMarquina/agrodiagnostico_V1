"""Select and freeze a candidate using VAL only; this command never opens TEST."""
import argparse
import json
from pathlib import Path

from agro_ml.pilot_selection import compare_calibrate_freeze


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mobilenet-dir", required=True, type=Path)
    parser.add_argument("--mobilenet-config", required=True, type=Path)
    parser.add_argument("--resnet-dir", required=True, type=Path)
    parser.add_argument("--resnet-config", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(compare_calibrate_freeze(args.mobilenet_dir, args.mobilenet_config,
                                             args.resnet_dir, args.resnet_config,
                                             args.protocol, args.output_dir), sort_keys=True))


if __name__ == "__main__":
    main()
