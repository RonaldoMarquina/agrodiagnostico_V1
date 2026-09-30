#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"'
npm ci --prefix tooling/ci --ignore-scripts --no-audit --no-fund
python3 -m venv tooling/ci/.venv
tooling/ci/.venv/bin/python -m pip --disable-pip-version-check install --quiet --require-hashes -r tooling/ci/requirements.lock
python3 - <<'PY'
import hashlib, io, json, pathlib, tarfile, urllib.request
root = pathlib.Path('tooling/ci')
config = json.loads((root/'tools.json').read_text())['actionlint']
with urllib.request.urlopen(config['url'], timeout=60) as response:
    data = response.read()
assert hashlib.sha256(data).hexdigest() == config['sha256'], 'actionlint checksum mismatch'
with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
    content = archive.extractfile('actionlint').read()
(root/'bin').mkdir(exist_ok=True)
path = root/'bin/actionlint'
path.write_bytes(content)
path.chmod(0o755)
PY
