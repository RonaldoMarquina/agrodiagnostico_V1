FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
COPY tooling/uv.requirements.txt /tmp/uv.requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/uv.requirements.txt
WORKDIR /checks
COPY tooling/integration/pyproject.toml tooling/integration/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
ENV PATH="/checks/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY infra/s3/bootstrap.py /bootstrap.py
COPY tests/integration /checks/tests
COPY contracts /checks/contracts
CMD ["python", "/bootstrap.py"]
