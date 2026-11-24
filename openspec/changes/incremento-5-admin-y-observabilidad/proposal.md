# Proposal

## Why

El diseño del Frontend V1.2 (`docs/AgroDiagnostico_Diseno_Frontend_V1.2_Codex.md`) contempla 20 pantallas completas (incluidas las 8 pantallas administrativas y la campana/lectura masiva de notificaciones), pero el backend actual mantiene todavía diferidas las últimas tres capacidades de `contracts/deferred-operations.json` (`audit`, `metrics`, `model-info`), además de `read-all`/`unread-count` en `notification`, la protección contra auto-bloqueo de `ADMIN` en `identity` y la lectura administrativa auditada de fotografía (`D-19`). Completar este backend operativo ahora (Paso 3A) cierra el 100 % de los RF (`RF-01`..`RF-28`) con datos reales sin migraciones riesgosas y desbloquea los dos últimos intents diferidos del asistente (`OPEN_AUDIT`, `OPEN_MONITORING`), permitiendo que el siguiente cambio de Frontend V1.2 (Paso 3B) conecte las 20 pantallas contra contratos reales y verificados.

## What Changes

- **ADR arquitectónico (`docs/adr/0016-observabilidad-auditoria-y-operaciones-admin.md`):** Formaliza las nuevas operaciones administrativas segregadas por propietario de datos (sin cruces entre bases de datos), la lectura administrativa auditada de fotografía (`GET /api/v1/admin/diagnoses/{id}/image` bajo patrón *privacidad por defecto + lectura explícita auditada*), la política de estado real de modelos respetando `REAL_INFERENCE_AUTHORIZED=false`, el monitoreo solo lectura con timeouts acotados (`2 s`, `UNKNOWN` ante timeout, sin credenciales de infraestructura) y las mejoras de UX en `notification` e `identity`.
- **Contratos OpenAPI 3.1.1 actualizados (+9 operaciones núcleo, de 48 a 57 operaciones en `contracts/operations.json`):**
  - **Identity (+2):** `GET /api/v1/admin/users/stats` (`identity_admin_user_stats`) y `GET /api/v1/admin/audit/identity` (`identity_admin_list_audit`); además se refuerza `PATCH /api/v1/admin/users/{id}/block` impidiendo auto-bloqueo de `ADMIN` (`409 SELF_BLOCK_NOT_ALLOWED`) y admitiendo cuerpo opcional `{reason}` (5..300 caracteres) persistido en `audit_logs.details`.
  - **Diagnosis (+5):** `GET /api/v1/admin/metrics/summary` (`diagnosis_admin_metrics_summary`), `GET /api/v1/admin/audit/diagnosis` (`diagnosis_admin_list_audit`), `GET /api/v1/admin/models` (`diagnosis_admin_list_models`), `GET /api/v1/admin/system/status` (`diagnosis_admin_system_status`) y `GET /api/v1/admin/diagnoses/{id}/image` (`diagnosis_admin_get_image` con asiento obligatorio `ADMIN_VIEW_DIAGNOSIS_IMAGE` en `diagnosis_audit_logs`).
  - **Notification (+2):** `PATCH /api/v1/notifications/read-all` (`notification_mark_all_read`) y `GET /api/v1/notifications/unread-count` (`notification_unread_count`).
  - **Validación y limpieza de diferidos:** Actualizar `contracts/schemas/common.schema.json`, `contracts/operations.json`, `contracts/security-matrix.json`, `contracts/deferred-operations.json` (documentando `audit`, `metrics` y `model-info` como contratados/implementados), `scripts/validate_contracts.py` y `tests/contracts/`.
- **Implementación en los servicios propietarios (sin cruces de BD ni nuevas migraciones destructivas):**
  - `services/identity/`: endpoints `stats` y `audit/identity` (paginación keyset sobre `audit_logs` excluyendo secretos/tokens), regla anti auto-bloqueo y registro opcional de `reason` en `block_user`.
  - `services/diagnosis/`: `metrics/summary` (conteo por estado, serie diaria acotada, confianza media real sobre resultados existentes), `audit/diagnosis` (paginación keyset HMAC sobre `diagnosis_audit_logs`), `models` (separando estado activo real con `REAL_INFERENCE_AUTHORIZED=false` y versiones históricas derivadas de `diagnoses`), `system/status` (sondeo interno solo lectura con `httpx` y timeout de `2 s` sobre `/health/ready` de `identity`, `diagnosis`, `ai_inference`, `notification`, `assistant` más conteo local de cuarentena/outbox pendiente, sin exponer secretos ni Management API de RabbitMQ) y `admin/diagnoses/{id}/image` (binario privado `Cache-Control: private, no-store` con asiento obligatorio en `diagnosis_audit_logs`).
  - `services/notification/`: `PATCH /api/v1/notifications/read-all` (actualización atómica idempotente `WHERE owner_id = :sub AND read_at IS NULL` devolviendo `{updated_count}`) y `GET /api/v1/notifications/unread-count` (`{unread_count}`).
  - `extensions/assistant/`: habilitar `OPEN_AUDIT -> AUDIT` y `OPEN_MONITORING -> MONITORING` en `INTENT_REGISTRY` para rol `ADMIN` (16/16 intents activos; `USER` sigue recibiendo `403 FORBIDDEN`).
- **Infraestructura Nginx y verificación E2E:**
  - Enrutar las nuevas rutas `/api/v1/admin/audit/identity`, `/api/v1/admin/users/stats`, `/api/v1/admin/audit/diagnosis`, `/api/v1/admin/metrics/summary`, `/api/v1/admin/models`, `/api/v1/admin/system/status`, `/api/v1/notifications/read-all` y `/api/v1/notifications/unread-count` en `infra/nginx/default.conf`, manteniendo `/internal` y `/health` bloqueados con `404`.
  - Añadir pruebas unitarias positivas/negativas en los 4 componentes y suite integrada E2E `scripts/check_admin_observability_integration.py` (proyecto Compose desechable vía Nginx) + regresión de suites existentes.

## Capabilities

### New Capabilities
- `admin-observability-and-audit`: Consulta administrativa segregada de auditoría (`identity` y `diagnosis`), estadísticas de cuentas, métricas de diagnósticos, inventario honesto de modelos activos e históricos, monitoreo operativo solo lectura con degradación `UNKNOWN` y lectura administrativa explícita y auditada de fotografías.

### Modified Capabilities
- `role-authorization-and-user-administration`: Refuerzo de `PATCH /api/v1/admin/users/{id}/block` impidiendo auto-bloqueo de `ADMIN` y registrando motivo opcional en `audit_logs`.
- `user-notifications-and-delivery`: Adición de `PATCH /api/v1/notifications/read-all` y `GET /api/v1/notifications/unread-count` con aislamiento estricto por propietario.
- `gemini-assistant`: Habilitación de los destinos administrativos `OPEN_AUDIT` y `OPEN_MONITORING` para rol `ADMIN` al quedar publicadas sus capacidades backend (16/16 intents disponibles).

## Impact

- **Servicios núcleo modificados:** `services/identity/`, `services/diagnosis/`, `services/notification/` (reutilizando las tablas ya existentes `audit_logs`, `diagnosis_audit_logs`, `diagnoses`, `diagnosis_quarantine_messages`, `publication_policies`, `users` y `notifications`).
- **Extensión modificada:** `extensions/assistant/` (`app/domain/registry.py` y pruebas).
- **Contratos e infraestructura:** `contracts/openapi/{identity,diagnosis,notification}.openapi.json`, `contracts/schemas/common.schema.json`, `contracts/operations.json`, `contracts/security-matrix.json`, `contracts/deferred-operations.json`, `scripts/validate_contracts.py`, `infra/nginx/default.conf`, `docker-compose.yml` (variables de URL interna de solo lectura para `system/status` en `diagnosis`).
- **Sin impacto en ML ni Frontend:** No se modifica `frontend/` (reservado para el Paso 3B), `services/ai_inference/` ni los artefactos/gates del cierre ML v1.4.3 (`REAL_INFERENCE_AUTHORIZED=false`).
