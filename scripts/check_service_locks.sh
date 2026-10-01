#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"'
check_dir="$(mktemp -d "${TMPDIR:-/tmp}/agro-service-locks.XXXXXXXX")"
trap 'rm -rf -- "$check_dir"' EXIT
python3 -m venv "$check_dir/tools"
"$check_dir/tools/bin/python" -m pip --disable-pip-version-check install --quiet --require-hashes -r tooling/uv.requirements.txt
for service in identity diagnosis ai_inference notification; do
  UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT="$check_dir/$service" \
    "$check_dir/tools/bin/uv" sync --project "services/$service" --locked --no-dev --no-install-project
  "$check_dir/$service/bin/python" -c 'import fastapi, sqlalchemy, alembic, psycopg; print("imports_ok")'
  PYTHONPATH="$PWD/services/$service" "$check_dir/$service/bin/python" tests/backend/check_health.py
  if [[ "$service" == "identity" ]]; then
    (cd services/identity && PYTHONDONTWRITEBYTECODE=1 "$check_dir/$service/bin/python" -m unittest discover -s tests -v)
  fi
done
