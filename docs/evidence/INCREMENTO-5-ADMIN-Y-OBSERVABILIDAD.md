# Evidencia reproducible — Incremento 5: Administración, Observabilidad y Cierre Backend V1

Fecha: 2026-11-24

Cambio OpenSpec: `openspec/changes/incremento-5-admin-y-observabilidad`

Decisión arquitectónica: [ADR-0016](../adr/0016-observabilidad-auditoria-y-operaciones-admin.md)

## Resumen de alcance verificado

Se contrataron, implementaron y verificaron de extremo a extremo vía Nginx las **9 operaciones núcleo** pendientes del backend V1 (promoviendo el inventario de `48` a **`57/57` operaciones núcleo implementadas**, más `3/3` operaciones de extensión en `extensions/assistant/` = **`60` operaciones implementadas**), con cero migraciones SQL destructivas y conservando intacto el cierre experimental ML v1.4.3 (`REAL_INFERENCE_AUTHORIZED=false`):

| Servicio | Operación | Estado |
| --- | --- | --- |
| `identity` | `GET /api/v1/admin/users/stats` (`identity_admin_user_stats`) | `IMPLEMENTED` / `VERIFIED_E2E` |
| `identity` | `GET /api/v1/admin/audit/identity` (`identity_admin_list_audit`) | `IMPLEMENTED` / `VERIFIED_E2E` |
| `identity` | `PATCH /api/v1/admin/users/{id}/block` (anti auto-bloqueo `409` + `{reason}` opcional) | `IMPLEMENTED` / `VERIFIED_E2E` |
| `diagnosis` | `GET /api/v1/admin/metrics/summary` (`diagnosis_admin_metrics_summary`) | `IMPLEMENTED` / `VERIFIED_E2E` |
| `diagnosis` | `GET /api/v1/admin/audit/diagnosis` (`diagnosis_admin_list_audit`) | `IMPLEMENTED` / `VERIFIED_E2E` |
| `diagnosis` | `GET /api/v1/admin/models` (`diagnosis_admin_list_models`, solo lectura, gate bloqueado) | `IMPLEMENTED` / `VERIFIED_E2E` |
| `diagnosis` | `GET /api/v1/admin/system/status` (`diagnosis_admin_system_status`, sondeo `2 s`) | `IMPLEMENTED` / `VERIFIED_E2E` |
| `diagnosis` | `GET /api/v1/admin/diagnoses/{id}/image` (`diagnosis_admin_get_image`, patrón `D-19` auditado) | `IMPLEMENTED` / `VERIFIED_E2E` |
| `notification` | `PATCH /api/v1/notifications/read-all` (`notification_mark_all_read`) | `IMPLEMENTED` / `VERIFIED_E2E` |
| `notification` | `GET /api/v1/notifications/unread-count` (`notification_unread_count`) | `IMPLEMENTED` / `VERIFIED_E2E` |
| `assistant` (ext.) | `OPEN_AUDIT -> AUDIT` y `OPEN_MONITORING -> MONITORING` (`ADMIN`-only, `16/16` intents) | `IMPLEMENTED` / `VERIFIED_FAKE` |

## Comandos ejecutados y resultados

| Verificación | Comando | Resultado |
| --- | --- | --- |
| Contratos OpenAPI 3.1.1 y fixtures | `docker run --rm -v $PWD:/workspace -w /workspace agrodiagnostico-v1-notification:latest bash scripts/check_contracts.sh` | **PASS** — `57` ops núcleo, `3` ops extensión, `835` ejemplos embebidos; `23/23` tests OK (`11.790s`) |
| Pruebas unitarias Identity | `docker run --rm -v $PWD:/workspace -w /workspace/services/identity -e PYTHONPATH=/workspace/services/identity agrodiagnostico-v1-identity:latest python -m unittest discover -s tests -v` | **PASS** — `60` tests OK (`skipped=1` lock PG, `5.260s`) |
| Pruebas unitarias Diagnosis | `docker run --rm -v $PWD:/workspace -w /workspace/services/diagnosis -e PYTHONPATH=/workspace/services/diagnosis agrodiagnostico-v1-diagnosis:latest python -m unittest discover -s tests -v` | **PASS** — `273/274` OK (`5/5` en `test_admin_observability.py`; único error esperado dentro de contenedor sin CLI `docker`: `test_docker_compose_only_proxy_published_and_topology_complete`) |
| Pruebas unitarias Notification | `docker run --rm -v $PWD:/workspace -w /workspace/services/notification -e PYTHONPATH=/workspace/services/notification agrodiagnostico-v1-notification:latest python -m unittest discover -s tests -v` | **PASS** — `24/24` tests OK |
| Pruebas unitarias Assistant | `docker run --rm -v $PWD:/workspace -w /workspace/extensions/assistant -e PYTHONPATH=/workspace/extensions/assistant agrodiagnostico-v1-assistant:latest python -m unittest discover -s tests -v` | **PASS** — `25/25` tests OK (`0.130s`) |
| Salud OpenAPI backend (`identity`, `diagnosis`, `notification`) | `python /workspace/tests/backend/check_health.py` en cada contenedor | **PASS** — `3/3` OK en cada servicio |
| Aceptación integrada E2E (Admin/Observabilidad/D-19/Notification/Assistant) | `python3 scripts/check_admin_observability_integration.py` | **PASS 6/6** (`agro-env-test-a65c5243d3f5`, `47.869s`) |
| Regresión E2E Assistant | `python3 scripts/check_assistant_integration.py` | **PASS 6/6** (`agro-env-test-16bab1ef259e`, `40.731s`) |
| Regresión E2E Notification | `python3 scripts/check_notification_integration.py` | **PASS 7/7** (`agro-env-test-403fbb144a14`, `44.94s`) |
| Regresión E2E Entorno núcleo | `python3 scripts/check_environment.py` | **PASS** (`agro-env-test-c5fd7c4a14c6`, `127.614s`) |
| Controles CI, workflow, lint y OpenSpec | `python3 scripts/check_ci_tests.py && python3 scripts/check_ci_workflow.py && tooling/ci/.venv/bin/ruff check --select E9,F63,F7,F82 scripts services extensions tests infra && openspec validate --all --strict --no-interactive` | **PASS** — CI tests `10/10`, workflow PASS, ruff `All checks passed!`, OpenSpec `18/18` válidos |

## Invariantes de seguridad y alcance preservados

- **Sin cruces de bases de datos:** `audit/identity` consulta exclusivamente `identity.audit_logs`; `audit/diagnosis`, `metrics/summary`, `models` y `system/status` consultan únicamente tablas de `diagnosis` y `/health/ready` interno por HTTP solo lectura con timeout de `2 s`.
- **Patrón `D-19` (privacidad por defecto + lectura explícita auditada):** `GET /api/v1/admin/diagnoses` devuelve solo metadatos, `GET /api/v1/diagnoses/{id}/image` mantiene `404` genérico incluso para `ADMIN` sobre recursos ajenos, y `GET /api/v1/admin/diagnoses/{id}/image` exige rol `ADMIN`, persiste `ADMIN_VIEW_DIAGNOSIS_IMAGE` en `diagnosis_audit_logs` antes de transmitir bytes privados y responde `Cache-Control: private, no-store` + `X-Content-Type-Options: nosniff`.
- **Cierre ML v1.4.3 intacto:** `GET /api/v1/admin/models` reporta `real_inference_authorized = false`, `runtime_status = "INACTIVE_GATE_BLOCKED"` y `active_model = null` sin simular un modelo productivo ni habilitar entrenamiento/promoción desde la API.

## Corrección del plazo de monitoreo (2026-11-24)

El sondeo remoto usa ahora un cliente asíncrono con un plazo cancelable de 2 s por dependencia. El plazo abarca la conexión y el cuerpo. La regresión simula dos cuerpos lentos con un plazo de prueba de 0,5 s y comprueba su cancelación en paralelo, los dos estados `UNKNOWN` y el HTTP 200 del agregado.

- Instalación limpia del lock de Diagnosis con `uv sync --locked --offline`.
- `python -m unittest discover -s tests` desde `services/diagnosis`: **273 aprobadas y 2 omitidas**, de 275 casos.
- Aceptación E2E vía Nginx con el código corregido: **6/6** en `agro-env-test-a495c6ab64db`, 44,564 s incluida la limpieza.
- Ruff con las reglas de CI, configuración Compose de demo y asistente y OpenSpec estricto: válidos.

La [guía de integración frontend](../FRONTEND_INTEGRACION_DEMO.md) identifica las rutas que puede consumir el Paso 3B.

## Pendiente fuera de alcance de este cambio

- Construcción de la interfaz React V1.2 completa (`frontend/`, Paso 3B: 20 pantallas + widget conversacional `AT-20` + cola offline IndexedDB + fallback SPA en Nginx).
- Despliegue productivo con dominio real, Cloudflare Full (strict), TLS origen y CDN de estáticos, así como smoke manual real `VERIFIED_REAL` con `GEMINI_API_KEY`.
