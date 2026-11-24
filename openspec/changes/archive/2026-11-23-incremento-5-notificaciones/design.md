# Design

## Context

Véase `proposal.md` para la motivación y alcance. Actualmente `services/notification/` únicamente implementa `/health/live`, `/health/ready`, la migración base vacía `notification_0001` y dependencias mínimas (`fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `psycopg`). Mientras tanto, `services/diagnosis/` ya publica `DiagnosisFinished` v1 en `agrodiagnostico.events` hacia la cola durable `notification.diagnosis-finished.v1`, pero con `0` consumidores activos y con `rabbit_notification` restringido a `write: "^$"` en `infra/rabbitmq/bootstrap.py`.

Por su parte, `DiagnosisFinished` v1 transporta exclusivamente `{ diagnosis_id, owner_id, final_status }` (sin `email`), los tokens de acceso emitidos por `services/identity` contienen únicamente `sub` y `role` (Ed25519), y `AGENTS.md` prohíbe lecturas cruzadas entre bases de datos de distintos servicios. Además, `infra/nginx/default.conf` responde `404 NOT_IMPLEMENTED` para cualquier ruta `/api/v1/notifications*` y `scripts/validate_contracts.py` valida el estado `implemented`/`contract-only` contra `contracts/operations.json`.

## Goals / Non-Goals

**Goals:**
- Completar el cuarto microservicio núcleo (`services/notification`) respetando el mismo rigor de aislamiento, seguridad, idempotencia y observabilidad de `identity` y `diagnosis`.
- Cerrar el contrato completo de notificaciones (incluyendo `PATCH /api/v1/notifications/{id}/read`) y del contacto interno en `identity` antes de integrar consumidores.
- Garantizar entrega at-least-once tolerante a redelivery y crashes (`inbox` + unicidad por `diagnosis_id` + ACK tras commit) y cuarentena/DLQ durable.
- Desacoplar completamente el envío de correo electrónico del aviso interno y de `Diagnosis`, con adaptadores intercambiables (`memory`/`logging`/`smtp`) y reintentos acotados.

**Non-Goals:**
- Construir pantallas React de notificaciones o modificar `frontend/` (pertenece al cambio del frontend completo).
- Enviar correo real a Internet desde la suite de CI automatizada (la CI usa adaptadores deterministas sin dependencia de red externa; `smtp` se prueba contra servidor/mock local o en configuración explícita).
- Alterar el esquema de `DiagnosisFinished` v1 (no se añade PII al evento) ni modificar `services/ai_inference` ni el estado del ciclo ML v1.4.3.

## Decisions

### 1. Resolución de correo electrónico vía `GET /internal/users/{id}/contact` en `identity`
- **Decisión:** Exponer en `services/identity` la operación interna `GET /internal/users/{id}/contact` protegida por `ServiceBearer` Ed25519 (`iss = agrodiagnostico-internal`, `aud = identity-internal`, `sub = notification`, TTL máximo 60 s, registro de confianza `INTERNAL_SERVICE_KEYS_FILE`), devolviendo únicamente `{ user_id, email, active }`. En `infra/nginx/default.conf` sigue bloqueada por `location ^~ /internal { return 404; }`.
- **Alternativas descartadas:**
  - *Añadir `email` a `DiagnosisFinished` v2:* rompe compatibilidad de evento, duplica PII en el broker/outbox y obliga a `diagnosis` a conocer emails de usuarios.
  - *Leer la tabla `users` de `identity_db` desde `notification`:* viola la propiedad estricta de datos de `AGENTS.md` y el aislamiento de credenciales PostgreSQL verificado en `check_persistence.py`.
  - *Guardar el email dentro de `notification_preferences`:* obliga al usuario a volver a introducir su correo y genera desincronización con `identity`.
- **Justificación:** Reutiliza exactamente el patrón probado de `ADR-0008` (`scripts/prepare_internal_keys.py` añade el par Ed25519 `notification-1` / `notification-1-key` con `principal = notification` en `internal_service_keys.json` y se monta `internal_notification_1_private_key` en `notification-consumer` e `internal_service_keys` en `identity`).

### 2. Modelo de datos propio en `notification_db` (migración `notification_0002`)
- **Decisión:** Crear las siguientes tablas propias en `services/notification/migrations/versions/0002_notification_domain.py` con `upgrade` y `downgrade` limpios:
  - `notifications`: `id` (UUID PK), `owner_id` (UUID indexado), `diagnosis_id` (UUID UNIQUE), `final_status` (check `COMPLETADO | NO_CONCLUYENTE | FALLIDO`), `created_at` (UTC), `read_at` (UTC nullable), `correlation_id` (UUID). Índice compuesto `(owner_id, created_at DESC, id DESC)` para paginación keyset eficiente.
  - `notification_preferences`: `owner_id` (UUID PK), `email_enabled` (bool NOT NULL default `false`), `created_at` (UTC), `updated_at` (UTC).
  - `notification_inbox`: `(consumer, event_id)` PK compuesta, `payload_hash` (SHA-256 hex), `diagnosis_id` (UUID), `received_at` (UTC). Detecta duplicados exactos y colisiones de identidad (`event_id` repetido con distinto hash).
  - `notification_delivery_attempts`: `id` (UUID PK), `notification_id` (FK a `notifications.id`, UNIQUE por canal `EMAIL`), `owner_id` (UUID), `channel` (`EMAIL`), `status` (`PENDING | SENT | FAILED_RETRYABLE | FAILED_PERMANENT | SKIPPED`), `attempt_count` (int), `max_attempts` (int default 3), `next_attempt_at` (UTC nullable), `last_error_code` (varchar seguro, sin PII ni trazas), `created_at` / `updated_at` / `sent_at` (UTC).
  - `notification_quarantine_messages` y `notification_dlq_outbox`: mismo patrón durable de `diagnosis` para aislar mensajes malformados, versiones desconocidas o colisiones de `event_id` y publicar descriptores DLQ con publisher confirms.
- **Alternativas descartadas:**
  - *Reintentar correo bloqueando el hilo del consumidor AMQP con `nack`/`requeue`:* acoplaría fallos de SMTP al consumo de la cola principal y bloquearía la creación de avisos internos de otros usuarios.
- **Justificación:** Separar la creación transaccional del aviso interno (en el consumo de `DiagnosisFinished`) del ciclo de intentos/reintentos de `notification_delivery_attempts` asegura que el aviso interno esté disponible al instante incluso si SMTP o `identity` fallan.

### 3. Default `email_enabled = false` y semántica idempotente de `PATCH /api/v1/notifications/{id}/read`
- **Decisión:**
  - Un usuario sin fila en `notification_preferences` recibe `{"email_enabled": false}` en `GET` (sin necesitar provisión previa desde `identity`) y no dispara entregas de correo hasta que haga opt-in explícito con `PATCH`.
  - `PATCH /api/v1/notifications/{id}/read` no exige cuerpo (rechaza campos inesperados si llega payload no vacío), verifica `owner_id == principal.id` (404 genérico si no coincide o no existe, incluso para `ADMIN`), y ejecuta actualización condicional `WHERE id = :id AND owner_id = :owner_id AND read_at IS NULL` seguida de lectura para preservar inmutable el primer `read_at`.
- **Justificación:** Evita crear un acoplamiento de provisión de usuarios entre `identity` y `notification` y simplifica el consumo desde el futuro frontend.

### 4. Paginación keyset con cursor HMAC independiente
- **Decisión:** Reutilizar el patrón de `services/diagnosis/app/infrastructure/cursor.py` montando el secreto existente `cursor_signing_key` en `notification`, pero con `purpose = "user_notifications"` ligado al `sub` del usuario, `created_at` e `id`.
- **Justificación:** Impide que un cursor de `diagnosis` o de otro usuario sea aceptado en `GET /api/v1/notifications` (responde `400 INVALID_PAGINATION`).

### 5. Topología RabbitMQ, `notification-consumer` y permiso `write` acotado para DLQ
- **Decisión:**
  - En `infra/rabbitmq/bootstrap.py`, actualizar `rabbit_notification.write` de `"^$"` a `r"^(agrodiagnostico\.events)$"`, manteniendo `configure: "^$"` y `read` estrictamente limitado a `notification.diagnosis-finished.v1` y `notification.diagnosis-finished.v1.dlq`.
  - Añadir en `docker-compose.yml` el servicio `notification-consumer` (`python -m app.consumer`) que ejecuta en bucle tanto el consumo de `notification.diagnosis-finished.v1` (creación de aviso + cola de intento de correo si `email_enabled = true` + publicación de descriptores DLQ pendientes) como un barrido periódico de `notification_delivery_attempts` vencidos (`PENDING`/`FAILED_RETRYABLE` con `FOR UPDATE SKIP LOCKED`, hasta 3 intentos con backoff).
  - En `services/notification/app/infrastructure/email.py`, proveer `EmailDeliveryAdapter` con modos `EMAIL_DELIVERY_MODE=memory|logging|smtp` (default seguro `logging` en local Compose, `memory` en pruebas unitarias, `smtp` configurable con `SMTP_HOST`, `SMTP_PORT`, TLS y secretos externos en producción).
- **Alternativas descartadas:**
  - *Mantener `rabbit_notification` en `write: "^$"` sin publicación DLQ:* obligaría a descartar silenciosamente mensajes venenosos o depender de reencolado infinito; usar el mismo patrón de cuarentena + DLQ que `diagnosis` y `ai_inference` mantiene consistencia operativa.

### 6. Compatibilidad con pruebas de aceptación existentes (`check_async_acceptance.py` y `check_environment.py`)
- **Decisión:** Actualizar las verificaciones existentes que asumían `0` consumidores sobre `notification.diagnosis-finished.v1` para que validen el comportamiento real:
  - En `tests/contracts/test_rabbit_topology.py`: verificar permiso `write` en `agrodiagnostico.events` (y denegación en otros exchanges) más aislamiento estricto de `read`.
  - En `scripts/check_async_acceptance.py`: comprobar tanto la retención durable cuando `notification-consumer` está detenido como el consumo idempotente de `DiagnosisFinished` cuando está activo.
  - Añadir una suite de aceptación dedicada (`scripts/check_notification_integration.py`) que pruebe extremo a extremo vía Nginx + RabbitMQ + Postgres + Identity + Diagnosis + Notification (incluyendo fallo de correo, reintento, aislamiento entre usuarios y no regresión en `Diagnosis`).

## Risks / Trade-offs

- **[Cambio de permiso AMQP en `rabbit_notification`] →** Mitigación: `rabbit-bootstrap` es idempotente y reaplica permisos al arrancar; actualizar `test_rabbit_topology.py` con pruebas negativas estrictas para confirmar que `rabbit_notification` sigue sin poder leer colas de `diagnosis` o `ai_inference` ni escribir en otros exchanges.
- **[Dependencia temporal de `identity` al enviar correo] →** Mitigación: la llamada a `GET /internal/users/{id}/contact` ocurre únicamente dentro del flujo desacoplado de `notification_delivery_attempts` (nunca bloquea el commit del aviso interno ni el ACK de `DiagnosisFinished`). Si `identity` falla o devuelve `5xx`/timeout, el intento pasa a `FAILED_RETRYABLE` con backoff y reintento acotado; si el usuario está inactivo o no existe (`404`/`active=false`), pasa a `SKIPPED` sin reintentos inútiles.
- **[Dependencias nuevas en `services/notification/pyproject.toml`] →** Mitigación: regenerar `services/notification/uv.lock` de forma reproducible y validar con `bash scripts/check_service_locks.sh` y `docker compose build notification notification-consumer`.
- **[Regresión en `check_contracts.py` y `check_persistence.py`] →** Mitigación: promover las 4 operaciones de `notification` + 1 operación interna de `identity` (total 48 operaciones) de forma sincronizada en OpenAPI, `operations.json`, `security-matrix.json`, `deferred-operations.json`, `validate_contracts.py` y `tests/contracts/test_contracts.py`, y validar `upgrade -> downgrade -> upgrade` de `notification_0002` con `scripts/check_persistence.py`.

## Migration Plan

1. **Pre-implementación:** Crear `docs/adr/0014-notificaciones-y-contacto-interno.md` y actualizar contratos (`contracts/`), `scripts/validate_contracts.py` y pruebas de contratos (`bash scripts/check_contracts.sh`).
2. **Claves internas y dependencias:** Extender `scripts/prepare_internal_keys.py` de forma idempotente (conservando las claves existentes `worker-1`/`worker-2` y añadiendo `notification-1` si falta, actualizando `internal_service_keys.json` sin regenerar claves ya existentes), y actualizar `services/notification/pyproject.toml` + `uv.lock`.
3. **Migración de esquema:** Aplicar `notification_0002` sobre `notification_db` (tablas nuevas, sin tocar datos de otros servicios; reversible limpiamente vía `downgrade`).
4. **Despliegue local / Rollback:** Levantar `rabbit-bootstrap`, `notification-migrate`, `identity`, `notification`, `notification-consumer` y `nginx`. En caso de rollback, detener `notification-consumer` deja los eventos `DiagnosisFinished` retenidos de forma durable en `notification.diagnosis-finished.v1` sin pérdida de diagnósticos.
