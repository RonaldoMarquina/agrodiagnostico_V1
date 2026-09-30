#!/usr/bin/env python3
import argparse
from ci_support import cleanup

parser = argparse.ArgumentParser()
parser.add_argument('--artifacts', required=True)
args = parser.parse_args()
cleanup(args.artifacts)
print('PASS scoped CI cleanup')
