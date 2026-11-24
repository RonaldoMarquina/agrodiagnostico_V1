# Proposal

## Why

El núcleo de AgroDiagnóstico V1 ya tiene implementados `identity`, `diagnosis` y la tubería asíncrona de `ai_inference`, pero `services/notification` sigue únicamente con endpoints técnicos de salud (`/health/live`, `/health/ready`) y los eventos `DiagnosisFinished` v1 se acumulan sin consumidor en RabbitMQ. Completar el servicio de notificaciones cierra el último microservicio núcleo del backend antes de integrar `gemini_assistant` y construir el frontend React completo.

## What Changes

- Formalizar un ADR (`docs/adr/0014-notificaciones-y-contacto-interno.md`) que fija el modelo de datos de `services/notification`, el default `email_enabled = false`, la resolución interna segura de correo electrónico desde `services/identity`, el adaptador de correo desacoplado y el manejo de cuarentena/DLQ.
- Contratar en OpenAPI 3.1.1 y promover a `implemented` las operaciones de negocio de `services/notification`:
  - `GET /api/v1/notifications` (paginación keyset con cursor HMAC ligado al propietario).
  - `PATCH /api/v1/notifications/{id}/read` (nuevo contrato promovido desde `contracts/deferred-operations.json`; idempotente, sin body requerido).
  - `GET /api/v1/notification-preferences` y `PATCH /api/v1/notification-preferences` (default `email_enabled = false`, actualización parcial validada).
- Contratar e implementar en `services/identity` la operación interna `GET /internal/users/{id}/contact` protegida con `ServiceBearer` Ed25519 (`aud = identity-internal`, `sub = notification`, nunca expuesta por Nginx), devolviendo únicamente `{ user_id, email, active }`.
- Implementar persistencia propia en `notification_db` (migración Alembic `notification_0002`): avisos internos, inbox deduplicado, preferencias de usuario, intentos de entrega de correo, auditoría/cuarentena de mensajes inválidos y outbox de descriptores DLQ.
- Implementar el consumidor durable `notification-consumer` que procesa `notification.diagnosis-finished.v1` de forma idempotente (1 aviso interno por diagnóstico terminal `COMPLETADO | NO_CONCLUYENTE | FALLIDO`, nunca `CANCELADO`), aplica ACK solo tras commit local y ejecuta intentos/reintentos acotados de correo mediante adaptador desacoplado (`memory`/`logging` en desarrollo/CI y `smtp` configurable) sin afectar nunca el estado del diagnóstico ni del aviso interno.
- Habilitar el permiso `write` sobre `agrodiagnostico.events` para `rabbit_notification` (exclusivamente para descriptores DLQ, conservando aislamiento de colas), añadir `notification-consumer` y secretos requeridos en `docker-compose.yml`, y exponer `/api/v1/notifications` y `/api/v1/notification-preferences` a través de `infra/nginx/default.conf`.
- Añadir pruebas unitarias, de contratos, de persistencia/migraciones y de aceptación integrada extremo a extremo (`DiagnosisFinished` -> aviso interno -> consulta/lectura/preferencias -> reintento/fallo de correo sin regresión en `Diagnosis`).

### Fuera de alcance

- Interfaz React / frontend de notificaciones (se integrará en el cambio del frontend completo).
- Servicio opcional `gemini_assistant`, voz, PWA y detector de plagas.
- Operaciones administrativas diferidas (`audit`, `metrics`, `model-info`) y despliegue público con Cloudflare/TLS/CDN.
- Cambio alguno al estado del ciclo ML v1.4.3 (`REAL_INFERENCE_AUTHORIZED=false` y catálogo histórico permanecen intactos).

## Capabilities

### New Capabilities

- `user-notifications-and-delivery`: Gestión de avisos internos idempotentes generados desde `DiagnosisFinished` v1, consulta paginada propia con cursor HMAC, marcado idempotente de lectura, preferencias de correo (`email_enabled` con default `false`), resolución interna segura de contacto en `identity` e intentos/reintentos desacoplados de envío de correo.

### Modified Capabilities

- `reliable-diagnosis-event-delivery`: Habilita el consumidor durable `notification-consumer` sobre `notification.diagnosis-finished.v1` con cuarentena y descriptores DLQ para `rabbit_notification`, preservando el desacoplamiento total entre `Diagnosis` y cualquier fallo de `Notification`, Redis o proveedor de correo.

## Impact

- **Contratos:** `contracts/openapi/notification.openapi.json`, `contracts/openapi/identity.openapi.json`, `contracts/schemas/common.schema.json`, `contracts/operations.json`, `contracts/security-matrix.json`, `contracts/deferred-operations.json`, `contracts/http-scenarios.json`, `contracts/events/routing.json`, `scripts/validate_contracts.py` y `tests/contracts/`.
- **Servicios:** `services/notification/` (API, modelos, migración `notification_0002`, consumidor AMQP, adaptador de correo, dependencias `pyjwt`, `cryptography`, `pika`, `httpx` en `pyproject.toml`/`uv.lock` y pruebas) y `services/identity/` (endpoint interno `/internal/users/{id}/contact` + verificación Ed25519 interna + pruebas).
- **Infraestructura y operación:** `infra/rabbitmq/bootstrap.py`, `infra/nginx/default.conf`, `docker-compose.yml`, `scripts/prepare_internal_keys.py`, `scripts/check_service_locks.sh`, `scripts/check_async_acceptance.py` y `scripts/check_environment.py`.
- **Documentación:** `docs/adr/0014-notificaciones-y-contacto-interno.md` (previo a implementación) y actualización posterior al cierre verificado en `docs/API_CONTRACTS.md`, `docs/Incrementos.md` y evidencia en `docs/evidence/`.
