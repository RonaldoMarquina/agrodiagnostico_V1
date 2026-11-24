# ADR-0014 — Servicio de notificaciones, contacto interno seguro y entrega desacoplada de correo

Fecha: 2026-11-23. Estado: adoptado para `incremento-5-notificaciones`.
Tarea: 1.1 de `incremento-5-notificaciones`.

## Contexto

Los incrementos 0 a 3 implementaron y verificaron los microservicios `identity`, `diagnosis` y la tubería asíncrona confiable de `ai_inference` (ADR-0004, ADR-0006, ADR-0007 y ADR-0008). En el cierre del Incremento 3, `diagnosis` ya publica eventos `DiagnosisFinished` v1 hacia el exchange durable `agrodiagnostico.events` y la cola `notification.diagnosis-finished.v1`, pero sin consumidor activo. Mientras tanto, `services/notification` únicamente expone `/health/live`, `/health/ready` y la migración base vacía `notification_0001`, sus operaciones de negocio permanecen en estado `contract-only` y la capacidad `notification-read` figura pendiente de contrato formal en `contracts/deferred-operations.json`.

Además, existen tres restricciones arquitectónicas que deben resolverse antes de escribir código:

1. `DiagnosisFinished` v1 transporta únicamente `{ diagnosis_id, owner_id, final_status }` sin dirección de correo electrónico, y los access tokens JWT de usuario contienen solo `sub` y `role`.
2. `AGENTS.md` prohíbe lecturas o escrituras cruzadas entre bases de datos de distintos servicios y prohíbe acoplar la disponibilidad del correo o Redis con el estado de los diagnósticos.
3. En `infra/rabbitmq/bootstrap.py`, `rabbit_notification` tiene `write: "^$"`, lo que le impide publicar descriptores DLQ en `agrodiagnostico.events` ante mensajes corruptos o versiones desconocidas.

Trazabilidad normativa: ADR-0002 (interfaces y eventos V1), ADR-0004 (identidad Ed25519), ADR-0006 (cursores HMAC y aislamiento), ADR-0008 (autenticación interna de servicio, outbox/inbox y cuarentena/DLQ), y los deltas OpenSpec de `incremento-5-notificaciones`:
- `specs/user-notifications-and-delivery/spec.md`
- `specs/reliable-diagnosis-event-delivery/spec.md`

## Alternativas consideradas

### A. Resolución de correo electrónico del destinatario
- **Alternativa A1 (descartada): Incluir `email` en un nuevo `DiagnosisFinished` v2.** Duplicaría PII en eventos, outbox de `diagnosis` y colas de RabbitMQ, y obligaría a `diagnosis` a conocer datos personales gestionados por `identity`.
- **Alternativa A2 (descartada): Leer la tabla `users` de `identity_db` desde `notification`.** Viola la propiedad exclusiva de datos y las pruebas de aislamiento PostgreSQL (`scripts/check_persistence.py`).
- **Alternativa A3 (descartada): Pedir al usuario que registre nuevamente su correo en `notification_preferences`.** Introduce fricción de UX y desincronización respecto a la cuenta real en `identity`.
- **Alternativa A4 (adoptada): Endpoint interno autenticado `GET /internal/users/{id}/contact` en `services/identity`.** Mantiene `identity` como fuente única de verdad del correo y estado activo de la cuenta, reutiliza el patrón Ed25519 interno de ADR-0008 y evita PII en RabbitMQ.

### B. Manejo de reintentos de correo frente al consumo AMQP
- **Alternativa B1 (descartada): Reencolar (`nack`/`requeue`) el mensaje `DiagnosisFinished` en RabbitMQ cuando falla SMTP.** Acoplaría la disponibilidad del proveedor de correo a la creación de avisos internos y podría provocar bucles de reentrega o duplicación.
- **Alternativa B2 (adoptada): Persistir aviso interno + intención de entrega de correo en la misma transacción antes del ACK y ejecutar entregas/reintentos en un barrido desacoplado sobre `notification_delivery_attempts`.** El aviso interno queda disponible de inmediato y el fallo de SMTP nunca bloquea el consumo ni afecta a `Diagnosis`.

### C. Política por defecto de `email_enabled`
- **Alternativa C1 (descartada): `email_enabled = true` por defecto.** Dispararía intentos de entrega de correo en cuentas que no lo solicitaron y exigiría infraestructura de correo activa incluso en despliegues mínimos.
- **Alternativa C2 (adoptada): `email_enabled = false` por defecto (opt-in explícito).** Un usuario sin fila previa en `notification_preferences` recibe `{"email_enabled": false}` en `GET` y puede activarlo con `PATCH` sin requerir provisión síncrona desde `identity`.

## Decisiones

### D1. Contratos antes del código y promoción verificada
1. Se añaden formalmente dos operaciones contractuales OpenAPI 3.1.1 (elevando el inventario total de 46 a 48 operaciones):
   - `PATCH /api/v1/notifications/{id}/read` (`notification_mark_read`) en `contracts/openapi/notification.openapi.json`.
   - `GET /internal/users/{id}/contact` (`identity_internal_user_contact`) en `contracts/openapi/identity.openapi.json`, referenciando el esquema cerrado `InternalUserContact` en `contracts/schemas/common.schema.json`.
2. `GET /api/v1/notification-preferences` y `PATCH /api/v1/notification-preferences` fijan explícitamente `email_enabled = false` como valor efectivo por defecto cuando no existe fila previa para el propietario; los avisos internos permanecen siempre activos y no desactivables.
3. Conforme a `AGENTS.md` y al precedente de ADR-0008 D1.4, las cinco operaciones del Incremento 5 (`notification_list`, `notification_mark_read`, `notification_get_preferences`, `notification_patch_preferences`, `identity_internal_user_contact`) permanecen en estado `contract-only` (`runtime_verified: false`) hasta que sus handlers y pruebas integradas sean implementados y verificados en los grupos posteriores del incremento.

### D2. Identidad interna de servicio para `GET /internal/users/{id}/contact`
1. `services/identity` expone `GET /internal/users/{id}/contact` únicamente en red interna; `infra/nginx/default.conf` conserva el bloqueo `location ^~ /internal { return 404; }`.
2. La autenticación exige `ServiceBearer` firmado con Ed25519 (`EdDSA`) mediante par de claves dedicado `notification-1` / `notification-1-key` registrado en `INTERNAL_SERVICE_KEYS_FILE` (`scripts/prepare_internal_keys.py` preserva idempotentemente las claves de `worker-1` y `worker-2`).
3. Claims obligatorios verificados en `identity`:
   - `iss`: `agrodiagnostico-internal`
   - `aud`: `identity-internal`
   - `sub`: `notification`
   - `instance_id`: coincidente con el `kid` registrado
   - `exp`: duración máxima de 60 segundos desde `iat`, sin periodo de gracia
   - `jti`: UUID válido
4. Respuestas contractuales:
   - `200`: `{"user_id": UUID, "email": Email, "active": boolean}` (`additionalProperties: false`).
   - `401`: credencial ausente, malformada, firma inválida o expirada.
   - `403`: token de usuario (`USER`/`ADMIN`) o token interno con `aud`/`sub` distinto de `identity-internal`/`notification`.
   - `404`: usuario inexistente (sin exponer metadatos ni contraseñas).
   - `503`: persistencia temporalmente no disponible.

### D3. Persistencia propia en `notification_db` (migración `notification_0002`)
`services/notification` es propietario exclusivo de sus tablas y migraciones Alembic (`0002_notification_domain.py`, reversible vía `downgrade`):
- `notifications`: `id` (UUID PK), `owner_id` (UUID), `diagnosis_id` (UUID UNIQUE), `final_status` (`COMPLETADO | NO_CONCLUYENTE | FALLIDO`), `created_at` (UTC), `read_at` (UTC nullable), `correlation_id` (UUID). Índice `(owner_id, created_at DESC, id DESC)`.
- `notification_preferences`: `owner_id` (UUID PK), `email_enabled` (boolean NOT NULL default `false`), `created_at` (UTC), `updated_at` (UTC).
- `notification_inbox`: PK compuesta `(consumer, event_id)`, `payload_hash` (SHA-256), `diagnosis_id` (UUID), `received_at` (UTC).
- `notification_delivery_attempts`: `id` (UUID PK), `notification_id` (FK a `notifications.id`, UNIQUE por canal `EMAIL`), `owner_id` (UUID), `channel` (`EMAIL`), `status` (`PENDING | SENT | FAILED_RETRYABLE | FAILED_PERMANENT | SKIPPED`), `attempt_count` (int), `max_attempts` (int default 3), `next_attempt_at` (UTC nullable), `last_error_code` (varchar seguro sin PII), `created_at`, `updated_at`, `sent_at` (UTC nullable).
- `notification_quarantine_messages` y `notification_dlq_outbox`: aislamiento seguro de mensajes inválidos o colisiones de `event_id` y publicación confirmada de descriptores hacia `diagnosis.finished.v1.dlq`.

### D4. API pública de notificaciones, cursores HMAC y lectura idempotente
1. `GET /api/v1/notifications`, `PATCH /api/v1/notifications/{id}/read`, `GET /api/v1/notification-preferences` y `PATCH /api/v1/notification-preferences` exigen `UserBearer` Ed25519 verificado únicamente con `jwt_public_key.pem` y responden siempre con `X-Correlation-ID` y `Cache-Control: private, no-store`.
2. `GET /api/v1/notifications` aplica paginación keyset `(created_at DESC, id DESC)` con `limit` 1..100 (defecto 20) y cursor opaco firmado HMAC-SHA256 usando `cursor_signing_key` con `purpose = user_notifications` ligado al `sub` del propietario (`400 INVALID_PAGINATION` ante cursor inválido, ajeno o de otro propósito).
3. `PATCH /api/v1/notifications/{id}/read` no requiere cuerpo JSON; ejecuta una actualización condicional `WHERE id = :id AND owner_id = :owner_id AND read_at IS NULL` para garantizar idempotencia estricta (preserva el primer `read_at` en llamadas repetidas) y responde `404` genérico para avisos ajenos o inexistentes (incluso para `ADMIN`).

### D5. Consumidor durable, permisos AMQP y adaptador de correo desacoplado
1. El proceso `notification-consumer` consume `notification.diagnosis-finished.v1`, valida estrictamente `DiagnosisFinished` v1 y confirma en una sola transacción `notification_inbox`, `notifications` y (solo si `email_enabled = true`) el registro `PENDING` en `notification_delivery_attempts` antes de enviar `basic.ack`.
2. Eventos duplicados por `event_id` o `diagnosis_id` son confirmados idempotentemente sin crear avisos ni nuevos intentos de correo. Eventos con versión desconocida, `final_status` fuera de enum (como `CANCELADO`), payload malformado o colisión de `event_id` con distinto contenido se aíslan en `notification_quarantine_messages` con descriptor en `notification_dlq_outbox` antes de emitir ACK.
3. En `infra/rabbitmq/bootstrap.py`, `rabbit_notification` actualiza su permiso `write` de `^$` a `^(agrodiagnostico\.events)$` exclusivamente para descriptores DLQ con publisher confirms, manteniendo `configure: "^$"` y `read` estrictamente acotado a `notification.diagnosis-finished.v1` y `notification.diagnosis-finished.v1.dlq`.
4. Un barrido periódico con `FOR UPDATE SKIP LOCKED` procesa `notification_delivery_attempts` vencidos consultando `GET /internal/users/{id}/contact` e invocando `EmailDeliveryAdapter` (`EMAIL_DELIVERY_MODE=memory|logging|smtp`, por defecto `logging` en desarrollo local). Ante errores transitorios de `identity` o SMTP reintenta con backoff hasta `max_attempts = 3`; ante cuenta inactiva o inexistente marca `SKIPPED`. Ningún fallo de entrega modifica el aviso interno ni el diagnóstico.

## Consecuencias

### Positivas
- Completa el cuarto microservicio núcleo V1 con los mismos estándares de seguridad, idempotencia, aislamiento de datos y trazabilidad que `identity` y `diagnosis`.
- Mantiene `DiagnosisFinished` v1 libre de PII y evita cualquier lectura cruzada entre bases de datos.
- Garantiza que caídas del proveedor de correo o de `identity` no degraden el flujo de diagnósticos ni impidan consultar avisos internos.
- Deja habilitado el contrato y el backend reales de notificaciones antes de integrar `gemini_assistant` y construir el frontend React completo.

### Negativas / Restricciones
- Introduce una llamada HTTP interna entre `notification-consumer` e `identity` únicamente para usuarios que activen `email_enabled = true`, gestionada con reintentos acotados y timeouts finitos.
- Amplía el permiso `write` de `rabbit_notification` en el exchange `agrodiagnostico.events` para soportar descriptores DLQ (requiere actualizar la prueba de topología AMQP conservando el aislamiento estricto de lectura).
- Mantiene las pruebas automatizadas de CI desacopladas de proveedores SMTP externos; la entrega real por SMTP requerirá configuración y evidencia explícitas en el entorno correspondiente.
