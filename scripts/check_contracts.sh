#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Se requiere Python 3.12"'
contract_env="$(mktemp -d "${TMPDIR:-/tmp}/agro-contracts.XXXXXXXX")"
trap 'rm -rf -- "$contract_env"' EXIT
python3 -m venv "$contract_env/venv"
"$contract_env/venv/bin/python" -m pip --disable-pip-version-check install --quiet --require-hashes -r contracts/tooling/requirements.lock
"$contract_env/venv/bin/python" scripts/validate_contracts.py
"$contract_env/venv/bin/python" - <<'PYTEST'
import unittest
suite = unittest.defaultTestLoader.discover('tests/contracts', pattern='test_*.py')
if suite.countTestCases() == 0:
    raise SystemExit('No se encontraron pruebas de contrato')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
PYTEST
