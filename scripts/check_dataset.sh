#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Se requiere Python 3.12"'
dataset_env="$(mktemp -d "${TMPDIR:-/tmp}/agro-dataset.XXXXXXXX")"
trap 'rm -rf -- "$dataset_env"' EXIT
python3 -m venv "$dataset_env/venv"
# Reutiliza el lock existente de JSON Schema; no cambia herramientas globales.
"$dataset_env/venv/bin/python" -m pip --disable-pip-version-check install --quiet --require-hashes -r contracts/tooling/requirements.lock
"$dataset_env/venv/bin/python" scripts/validate_dataset.py
"$dataset_env/venv/bin/python" - <<'PY'
import unittest
suite = unittest.defaultTestLoader.discover('tests/dataset', pattern='test_*.py')
if suite.countTestCases() == 0:
    raise SystemExit('No se encontraron pruebas del dataset')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
