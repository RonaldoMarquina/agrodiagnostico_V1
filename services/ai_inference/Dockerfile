FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never
COPY tooling/uv.requirements.txt /tmp/uv.requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/uv.requirements.txt
WORKDIR /service
COPY services/ai_inference/pyproject.toml services/ai_inference/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY services/ai_inference/app ./app
COPY contracts ./contracts
COPY services/ai_inference/alembic.ini ./
COPY services/ai_inference/migrations ./migrations
ENV PATH="/service/.venv/bin:$PATH"
CMD ["python", "-m", "app.run"]
