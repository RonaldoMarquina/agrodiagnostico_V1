#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Python 3.12 required"'

export CUDA_VISIBLE_DEVICES=""
export TORCH_DEVICE="cpu"
export APP_ENV="test"

# Always install the ML lock: a developer's AI environment can lack Pillow and
# silently skip image tests. Never reuse its unrelated dependencies.
ml_check_dir="$(mktemp -d "${TMPDIR:-/tmp}/agro-ml-runtime.XXXXXXXX")"
trap 'rm -rf -- "$ml_check_dir"' EXIT
python3 -m venv "$ml_check_dir/tools"
"$ml_check_dir/tools/bin/python" -m pip --disable-pip-version-check install --quiet --require-hashes -r tooling/uv.requirements.txt
UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT="$ml_check_dir/ml" \
  "$ml_check_dir/tools/bin/uv" sync --project ml --locked --no-dev
"$ml_check_dir/ml/bin/python" -c 'from PIL import Image; import jsonschema, torch, torchvision, safetensors, agro_ml; assert not torch.cuda.is_available()'
"$ml_check_dir/ml/bin/agro-ml" --help >/dev/null
PYTHONPATH="$PWD/ml/src:$PWD/services/ai_inference" \
  "$ml_check_dir/ml/bin/python" scripts/check_ml_runtime.py
