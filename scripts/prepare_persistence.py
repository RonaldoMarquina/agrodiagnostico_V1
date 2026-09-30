#!/usr/bin/env python3
"""Create local-only secret files once; never print or replace existing values."""
import argparse
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser()
parser.add_argument('--directory', type=Path, default=Path('.local/persistence'))
args = parser.parse_args()
args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
for name in ['postgres', 'identity', 'diagnosis', 'ai_inference', 'notification']:
    path = args.directory / (name + '_password')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if not path.is_file() or not path.read_text().strip():
            raise SystemExit('Existing secret file is invalid: ' + path.name)
        continue
    with os.fdopen(fd, 'w') as out:
        out.write(secrets.token_urlsafe(32) + '\n')
print('Local persistence secrets prepared; existing values preserved.')
