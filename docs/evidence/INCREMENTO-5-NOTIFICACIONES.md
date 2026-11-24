# Cierre del sub-incremento 5: Notificaciones y contacto interno

Fecha de cierre: 2026-11-23. Cambio OpenSpec archivado: [incremento-5-notificaciones](../../openspec/changes/archive/2026-11-23-incremento-5-notificaciones/tasks.md) (13/13 tareas completas; 2 capacidades sincronizadas en `openspec/specs/`, 15/15 specs válidas). Decisión arquitectónica: [ADR-0014](../adr/0014-notificaciones-y-contacto-interno.md).

## Alcance implementado y verificado

1. **Contratos formales y ADR-0014**:
   - Se formalizaron `PATCH /api/v1/notifications/{id}/read` (`notification_mark_read`) y `GET /internal/users/{id}/contact` (`identity_internal_user_contact`), completando **48/48 operaciones implementadas** en `contracts/operations.json`, `contracts/openapi/*.openapi.json` y `contracts/security-matrix.json`.
   - Default contractual de correo fijado en `email_enabled = false` (opt-in explícito); los avisos internos en plataforma permanecen siempre activos.
2. **Claves internas y contacto en `services/identity`**:
   - `scripts/prepare_internal_keys.py` genera de forma idempotente el par Ed25519 `notification-1` / `notification-1-key` (`principal = notification`) preservando `worker-1` y `worker-2`.
   - `GET /internal/users/{id}/contact` exige token interno Ed25519 (`iss = agrodiagnostico-internal`, `aud = identity-internal`, `sub = notification`, `jti` UUID, TTL `1..60 s`), rechaza tokens ausentes/expirados con `401`, rechaza Bearer de usuario o principal/audience incorrectos con `403`, devuelve `404` para usuarios inexistentes y expone solo `{ user_id, email, active }` con `Cache-Control: private, no-store`.
   - `get_current_user` rechaza explícitamente tokens emitidos por `agrodiagnostico-internal` (`403`) para evitar confusión de tokens internos/públicos.
3. **Persistencia y migración reversible en `services/notification`**:
   - 6 tablas propias en `notification_db` mediante la migración reversible `0002_notification_domain.py` (`notification_0002`): `notifications`, `notification_preferences`, `notification_inbox`, `notification_delivery_attempts`, `notification_quarantine_messages`, `notification_dlq_outbox`.
   - Aislamiento estricto por base de datos confirmado contra PostgreSQL 16 (conexión propia OK; 12 accesos cruzados denegados).
4. **API pública de `services/notification`**:
   - `GET /api/v1/notifications`: listado keyset `(created_at DESC, id DESC)` con cursor HMAC-SHA256 vinculado a `owner_id` y `purpose = user_notifications` (`400 INVALID_PAGINATION` ante cursor alterado, de otro usuario o de otro propósito).
   - `PATCH /api/v1/notifications/{id}/read`: idempotente sin cuerpo requerido; conserva el primer `read_at` UTC y devuelve `404 NOT_FOUND` genérico para avisos inexistentes o ajenos (incluido `ADMIN`).
   - `GET /api/v1/notification-preferences` y `PATCH /api/v1/notification-preferences`: lectura con default `email_enabled = false` y actualización parcial validada (booleano estricto).
5. **Consumidor `notification-consumer`, cuarentena DLQ y entrega de correo**:
   - `infra/rabbitmq/bootstrap.py` otorga a `rabbit_notification` permiso `write = ^(agrodiagnostico\.events)$` manteniendo `configure = ^$` y `read` acotado a `notification.diagnosis-finished.v1(.dlq)`.
   - `services/notification/app/consumer.py` consume `DiagnosisFinished` v1 con ACK manual post-commit, deduplicación `(consumer, event_id)`, unicidad por `diagnosis_id`, cuarentena + `notification_dlq_outbox` para mensajes malformados/versión desconocida/colisión/`CANCELADO` y señal `/tmp/notification_consumer_ready`.
   - Entrega desacoplada de correo (`memory`, `logging`, `smtp`) con reintentos acotados y backoff en `notification_delivery_attempts`; fallos de SMTP o de Identity nunca revierten diagnósticos ni pierden el aviso interno.
6. **Infraestructura Compose, Nginx y CI**:
   - `docker-compose.yml` añade `notification-consumer` con su clave privada dedicada (`internal_notification_1_private_key`), monta `internal_service_keys` en `identity` y `jwt_public_key` + `cursor_signing_key` en `notification`; únicamente `nginx` publica puertos.
   - `infra/nginx/default.conf` publica `/api/v1/notifications`, `/api/v1/notifications/` y `/api/v1/notification-preferences` hacia `notification:8000` y mantiene `/internal` bloqueado con `404`.
   - Se incorporó la etapa obligatoria `notification-integration` (`scripts/check_notification_integration.py`) en `tooling/ci/plan.json`, `scripts/check_ci_workflow.py` y `tests/ci/test_controls.py`.

## Pruebas reproducibles ejecutadas

| Verificación | Comando | Resultado |
| --- | --- | --- |
| Contratos OpenAPI, esquemas y topología AMQP (Python 3.12 en contenedor) | `docker run --rm -v "$PWD:/work:ro" -w /work -e PYTHONPATH=/work/.venv-contracts/lib/python3.12/site-packages:/work agrodiagnostico-v1-notification:latest python -c "..."` (`scripts/validate_contracts.py` + `unittest discover -s tests/contracts`) | **PASS**: 4 OpenAPI, 48 operaciones `implemented`, 652 ejemplos embebidos; `21/21` pruebas OK |
| Suite unitaria de `services/identity` (Python 3.12 en contenedor) | `unittest discover -s /work/services/identity/tests` en `agrodiagnostico-v1-identity:latest` | **PASS**: 56 pruebas ejecutadas (55 OK, 1 skipped de carrera PostgreSQL sin PG en unit test) |
| Suite unitaria de `services/notification` (Python 3.12 en contenedor) | `unittest discover -s /work/services/notification/tests` en `agrodiagnostico-v1-notification:latest` | **PASS**: 23/23 OK (modelos, auth/cursor, API pública, consumidor/cuarentena/correo) |
| Salud técnica y contratos OpenAPI en runtime (`identity` y `notification`) | `tests/backend/check_health.py` en contenedores `identity` y `notification` | **PASS**: 3/3 OK en ambos servicios |
| Persistencia real, aislamiento y migraciones reversibles PostgreSQL 16 | `python3 scripts/check_persistence.py` | **PASS** (`98.726 s`): `upgrade -> current -> repeat -> downgrade -> upgrade`, 4 conexiones propias, 12 accesos cruzados denegados |
| Aceptación integrada E2E de Notification vía Nginx | `python3 scripts/check_notification_integration.py` | **PASS** (`46.509 s`): 7 bloques E2E (aislamiento proxy `404`, registro/login real, preferencias default `false` y opt-in, matriz interna `401`/`403`/`200`/`404`, flujo `DiagnosisFinished` → aviso → paginación keyset → `read` idempotente → correo `SENT`, cuarentena/DLQ real en RabbitMQ, retención durable sin consumidor y fallo SMTP sin revertir diagnóstico) + teardown limpio sin residuos |
| Aceptación de entorno integrado Compose + Nginx | `python3 scripts/check_environment.py` | **PASS** (`126.6 s`): salud interna, rutas OpenAPI alineadas, bloqueo externo `404` de `/internal/users/*/contact` y `401` en `/api/v1/notifications` |
| Regresión de aceptación asíncrona completa (Incremento 3) | `python3 scripts/check_async_acceptance.py` | **PASS**: 10 comprobaciones base + matriz de fallos (caída broker/Redis, carreras claim/cancel, caídas worker/publisher, renovación de lease, recuperación PostgreSQL y retención durable sin consumidor) |
| Controles de CI, workflow y lint estático | `python3 scripts/check_ci_tests.py && python3 scripts/check_ci_workflow.py && tooling/ci/.venv/bin/ruff check --select E9,F63,F7,F82 scripts services tests infra` | **PASS**: 10/10 pruebas de CI, workflow alineado y `ruff` sin errores |
| Validación estricta OpenSpec | `openspec validate incremento-5-notificaciones --strict --no-interactive` | **PASS** |

## Límites y elementos pendientes declarados

- **Entorno Python del host**: el host local ejecuta Python 3.14.4 y carece de un binario local `python3.12` (los scripts `scripts/check_contracts.sh`, `scripts/check_service_locks.sh` y la comprobación de versión de `scripts/run_ci.py` exigen Python 3.12 en el PATH del host). Por ello, las pruebas unitarias y de contratos que requieren Python 3.12 se ejecutaron dentro de las imágenes Docker oficiales Python 3.12.14 del repositorio (`agrodiagnostico-v1-notification:latest` y `agrodiagnostico-v1-identity:latest`) con las dependencias fijadas por `uv.lock` y `.venv-contracts`, y las pruebas E2E/Compose/CI se ejecutaron directamente desde el host. No se declara ejecutado `scripts/run_ci.py` monolítico en el host ni GitHub Actions remoto.
- **Entrega SMTP real externa**: las pruebas verifican los modos `memory`, `logging` y fallo real de conexión `smtp` contra puerto no disponible sin afectar `Diagnosis` ni los avisos internos. No se ha configurado ni medido un proveedor SMTP productivo externo ni entregabilidad (SPF/DKIM/DMARC).
- **Pendientes fuera de este cambio**: interfaz React (`frontend/`), servicio opcional `services/optional/gemini_assistant/`, observabilidad/métricas (`audit`, `metrics`, `model-info` en `contracts/deferred-operations.json`), despliegue productivo con dominio real, HTTPS Full (strict), Cloudflare y CDN, y el modelo ML de producción (cierre experimental v1.4.3 mantenido intacto con `REAL_INFERENCE_AUTHORIZED=false`).
