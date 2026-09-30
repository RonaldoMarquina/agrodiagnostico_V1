FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never
COPY tooling/uv.requirements.txt /tmp/uv.requirements.txt
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/uv.requirements.txt
ARG SERVICE
WORKDIR /service
COPY services/${SERVICE}/pyproject.toml services/${SERVICE}/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY services/${SERVICE}/app ./app
COPY services/${SERVICE}/alembic.ini ./
COPY services/${SERVICE}/migrations ./migrations
ENV PATH="/service/.venv/bin:$PATH"
USER 10001:10001
CMD ["python", "-m", "app.migrate", "upgrade", "head"]
