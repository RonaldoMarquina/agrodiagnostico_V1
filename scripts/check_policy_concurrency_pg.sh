#!/usr/bin/env bash
set -euo pipefail

# Disposable database only. Never connects to the project's running database.
agro_pg_suffix="$(date +%s)-$$"
agro_pg_network="agro-policy-test-${agro_pg_suffix}"
agro_pg_container="agro-policy-pg-${agro_pg_suffix}"
cleanup() {
  docker rm -f "$agro_pg_container" >/dev/null 2>&1 || true
  docker network rm "$agro_pg_network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$agro_pg_network" >/dev/null
docker run --rm -d --name "$agro_pg_container" --network "$agro_pg_network" \
  -e POSTGRES_USER=policy_test -e POSTGRES_PASSWORD=policy_test \
  -e POSTGRES_DB=policy_test postgres:16-alpine >/dev/null
for attempt in $(seq 1 40); do
  if docker exec "$agro_pg_container" pg_isready -U policy_test -d policy_test >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
docker exec "$agro_pg_container" pg_isready -U policy_test -d policy_test >/dev/null

docker run --rm --network "$agro_pg_network" -v "$PWD:/workspace" -w /workspace \
  -e TEST_POLICY_PG_URL="postgresql+psycopg://policy_test:policy_test@${agro_pg_container}/policy_test" \
  -e PYTHONPATH=/workspace/services/diagnosis/.venv/lib/python3.12/site-packages:/workspace/services/diagnosis \
  python:3.12-slim python -m unittest \
  services.diagnosis.tests.test_policy_concurrency_pg -v
