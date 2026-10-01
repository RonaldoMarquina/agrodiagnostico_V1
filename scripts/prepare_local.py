#!/usr/bin/env python3
"""Generate local secrets and server credentials; preserve existing values."""
import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from prepare_identity_keys import prepare as prepare_identity_keys

parser = argparse.ArgumentParser()
parser.add_argument('--directory', type=Path, default=Path('.local/persistence'))
parser.add_argument('--bucket', default='agro-local')
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', args.bucket):
    raise SystemExit('configuration_invalid: S3_BUCKET')
subprocess.run(['python3', 'scripts/prepare_persistence.py', '--directory', str(args.directory)], check=True)
# File-backed Compose secrets retain the host mode. Keep the source directory
# private even if the S3 server runs under a mapped UID inside Docker.
args.directory.chmod(0o700)
prepare_identity_keys(args.directory)


def store(name, content):
    path = args.directory / name
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text()
    with os.fdopen(fd, 'w') as out:
        out.write(content + '\n')
    return content


identities = []
for name, actions in [('admin', ['Admin', 'Read', 'Write', 'List', 'Tagging']),
                      ('diagnosis', ['Read:'+args.bucket, 'Write:'+args.bucket, 'List:'+args.bucket]),
                      ('ai', ['Read:'+args.bucket, 'List:'+args.bucket])]:
    credential = json.loads(store('s3_' + name + '.json', json.dumps({'access_key': secrets.token_hex(12), 'secret_key': secrets.token_urlsafe(32)})))
    identities.append({'name': name, 'credentials': [{'accessKey': credential['access_key'], 'secretKey': credential['secret_key']}], 'actions': actions})
# Derived config uses persistent values and explicit bucket permissions; replacement is local and atomic.
config = args.directory / 's3_config.json'
fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as out:
    json.dump({'identities': identities}, out)
# Only S3 mounts this file. A mapped container UID must be able to read it;
# the private host directory still prevents access through the source path.
config.chmod(0o644)
rabbit_password = store('rabbit_password', secrets.token_hex(24)).strip()
store('rabbit_cookie', secrets.token_hex(32))
store('rabbit.conf', 'default_user = agro_local\ndefault_pass = ' + rabbit_password + '\nloopback_users.guest = true\n')
print('Local configuration prepared; no secret values printed.')
