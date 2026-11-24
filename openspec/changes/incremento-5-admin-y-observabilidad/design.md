# Design — Incremento 5: Administración, Observabilidad y Cierre Backend V1

## Context

El núcleo backend de AgroDiagnóstico V1 dispone actualmente de 48 operaciones OpenAPI implementadas (`identity`, `diagnosis`, `ai_inference` y `notification`) y 3 operaciones en la extensión opcional `extensions/assistant/`. Sin embargo, al auditar `docs/AgroDiagnostico_Diseno_Frontend_V1.2_Codex.md` (20 pantallas completas) contra los contratos actuales se identificaron las últimas capacidades backend pendientes antes de construir la UI React:

1. Las 3 capacidades marcadas históricamente en `contracts/deferred-operations.json`: `audit`, `metrics` y `model-info`, además de un punto único solo lectura de estado del sistema (`system/status`).
2. La lectura administrativa explícita y auditada de fotografías (`D-19`) para la pantalla de detalle/supervisión administrativa, sin romper la regla de que `/api/v1/admin/diagnoses` devuelve solo metadatos ni el aislamiento `404` de `/api/v1/diagnoses/{id}/image`.
3. Dos endpoints de ergonomía en `notification` (`read-all` y `unread-count`) para la campana del header y el centro de notificaciones, y dos refuerzos en `identity` (`GET /api/v1/admin/users/stats`, bloqueo con motivo opcional y regla anti auto-bloqueo `409 SELF_BLOCK_NOT_ALLOWED`).
4. Habilitar `OPEN_AUDIT` y `OPEN_MONITORING` en `extensions/assistant/` ahora que los destinos backend pasan a existir.

Todas las tablas requeridas (`users`, `audit_logs` en `identity`; `diagnoses`, `diagnosis_audit_logs`, `diagnosis_outbox`, `diagnosis_quarantine_messages`, `publication_policies` en `diagnosis`; `notifications` en `notification`) ya existen en PostgreSQL.

## Goals / Non-Goals

**Goals:**
- Publicar y contratar formalmente las 9 operaciones núcleo nuevas (llevando `contracts/operations.json` de 48 a 57 operaciones) bajo OpenAPI 3.1.1, matriz de seguridad y validador de contratos sin deuda oculta.
- Respetar estrictamente la propiedad de datos por servicio: ninguna consulta lee ni escribe tablas de otro microservicio.
- Mantener cero migraciones destructivas de base de datos, aprovechando los esquemas e índices ya desplegados en PostgreSQL.
- Preservar la privacidad por defecto y trazabilidad forense de imágenes (`ADMIN_VIEW_DIAGNOSIS_IMAGE` en `diagnosis_audit_logs`).
- Preservar intacto el cierre ML v1.4.3 (`REAL_INFERENCE_AUTHORIZED=false`), exponiendo honestamente en `GET /api/v1/admin/models` que no existe modelo activo autorizado en producción.
- Garantizar sondeo acotado (`2 s`), seguro y no bloqueante en `GET /api/v1/admin/system/status`.
- Habilitar los 16/16 intents del registro del asistente para `ADMIN`/`USER` sin relajar RBAC.

**Non-Goals:**
- Implementar pantallas React ni cambios en `frontend/` (reservado para el siguiente cambio Paso 3B).
- Modificar `services/ai_inference/`, entrenar modelos, cambiar umbrales o autorizar inferencia real (`REAL_INFERENCE_AUTHORIZED` sigue en `false`).
- Crear un servicio centralizado de auditoría o unificar bases de datos; la segregación `audit/identity` + `audit/diagnosis` preserva los límites de microservicios y la UI puede mostrar pestañas o combinar en cliente.
- Exponer la Management API de RabbitMQ, métricas Prometheus públicas o credenciales de infraestructura.

## Decisions

### D1. ADR-0016 y cero migraciones de esquema
Se documentará la decisión en `docs/adr/0016-observabilidad-auditoria-y-operaciones-admin.md`.
- `identity.audit_logs` ya dispone de `id`, `actor_id`, `target_id`, `action`, `correlation_id`, `legacy`, `details` (JSONB) y `created_at`. El motivo opcional de bloqueo (`reason`) se guarda en `details` (`{"reason": "..."}`) sin alterar columnas.
- `diagnosis.diagnosis_audit_logs` ya dispone de `id`, `actor_id`, `action`, `target_type`, `target_id`, `correlation_id`, `details` (JSONB) y `created_at`. El evento `ADMIN_VIEW_DIAGNOSIS_IMAGE` se inserta reutilizando exactamente esta tabla inmutable.
- `diagnosis.diagnoses` ya almacena `status`, `inconclusive_reason_code`, `confidence_score`, `model_id`, `model_version`, `dataset_version` y `created_at`.
- `notification.notifications` ya almacena `owner_id` y `read_at`.

### D2. Identidad: `users/stats`, `audit/identity` y protección de `block_user`
- **`GET /api/v1/admin/users/stats` (`identity_admin_user_stats`):** Agregación `COUNT(*)` condicional en una sola consulta SQL sobre `users` devolviendo `{"total", "active", "blocked", "admins", "users"}`.
- **`GET /api/v1/admin/audit/identity` (`identity_admin_list_audit`):** Paginación keyset `(created_at DESC, id DESC)` reutilizando el helper de cursor firmado HMAC ya existente en `identity` (con propósito exclusivo `"admin_identity_audit"` ligado al `actor_id`). Filtros opcionales: `action`, `actor_id` (UUID), `target_id` (UUID), `from` y `to` (ISO-8601 UTC, validando `from <= to`). Los registros proyectan únicamente campos seguros (`id`, `action`, `actor_id`, `target_id`, `correlation_id`, `legacy`, `details` sanitizado/seguro, `created_at`) excluyendo explícitamente `ip_address`/`user_agent` si no aportan o asegurando que nunca contengan tokens/contraseñas.
- **`PATCH /api/v1/admin/users/{id}/block`:**
  - Verifica primero `target_user_id == actor.user_id`; si coincide devuelve `409 Conflict` con `code = "SELF_BLOCK_NOT_ALLOWED"` antes de mutar nada.
  - Acepta cuerpo ausente/vacío (compatibilidad total con pruebas y clientes existentes) **o** objeto JSON cerrado `{"reason": "..."}` (`extra="forbid"`, `reason` trimmed `5..300` caracteres). Cualquier campo extra o `reason` fuera de longitud devuelve `400`.
  - Si se proporciona `reason`, se guarda en `audit_logs.details = {"reason": reason}` dentro de la misma transacción del bloqueo y revocación de `refresh_sessions`.

### D3. Diagnóstico: `metrics/summary`, `audit/diagnosis` y `models`
- **`GET /api/v1/admin/metrics/summary` (`diagnosis_admin_metrics_summary`):**
  - Parámetros opcionales `from` y `to` (ISO-8601 UTC). Si ambos faltan, usa los últimos 30 días UTC (`[now - 30d, now]`). Si falta solo uno, calcula el extremo faltante a 30 días sin exceder 90 días. Rechaza con `400` si `from > to` o `(to - from) > 90 días`.
  - Ejecuta agregaciones reales sobre `diagnoses` filtrando por `created_at` en el rango:
    - `total`: total de diagnósticos en el rango.
    - `by_status`: diccionario completo con las 6 claves oficiales (`PENDIENTE`, `PROCESANDO`, `COMPLETADO`, `NO_CONCLUYENTE`, `FALLIDO`, `CANCELADO`) inicializadas en `0`.
    - `by_inconclusive_reason`: conteos por `inconclusive_reason_code` (solo sobre `NO_CONCLUYENTE` con código no nulo).
    - `average_confidence`: promedio real (`AVG(confidence_score)`) redondeado a 4 decimales o `null` si no hay filas con `confidence_score IS NOT NULL`.
    - `daily_series`: arreglo ordenado ascendentemente por fecha `YYYY-MM-DD` (UTC) con `date`, `total`, `completed`, `inconclusive`, `failed`.
- **`GET /api/v1/admin/audit/diagnosis` (`diagnosis_admin_list_audit`):**
  - Paginación keyset `(created_at DESC, id DESC)` con cursor HMAC (`purpose = "admin_diagnosis_audit"`, ligado a `actor_id`, `limit` `1..100`, default `20`).
  - Filtros opcionales: `action`, `actor_id` (UUID), `target_type`, `target_id` (UUID), `from`, `to` (`from <= to`).
- **`GET /api/v1/admin/models` (`diagnosis_admin_list_models`):**
  - Estrictamente de solo lectura.
  - Lee `REAL_INFERENCE_AUTHORIZED` desde la configuración de entorno de `diagnosis` (por defecto `false`, alineado con `.env.example` y `docker-compose.yml`).
  - Devuelve:
    - `real_inference_authorized`: booleano real (`false` en V1 actual).
    - `runtime_status`: `"INACTIVE_GATE_BLOCKED"` cuando `real_inference_authorized=false`, o `"AUTHORIZED"` si algún entorno futuro lo autoriza tras aprobar G2.
    - `active_model`: `null` cuando `real_inference_authorized=false` (nunca inventa un modelo activo).
    - `active_policy_version`: versión de política de publicación vigente desde `publication_policies` (si existe).
    - `historical_versions`: filas agrupadas desde `diagnoses WHERE model_id IS NOT NULL` por `(model_id, model_version, dataset_version)` con `diagnoses_count` y `last_used_at`, ordenadas por `last_used_at DESC`.

### D4. Monitoreo operativo solo lectura (`GET /api/v1/admin/system/status`)
- Reside en `diagnosis` como agregador solo lectura sobre la red interna `application`, usando `httpx.AsyncClient` con `timeout=2.0` segundos por petición y ejecución concurrente (`asyncio.gather`) para que el tiempo total no exceda ~2.2 s incluso si varios servicios están lentos.
- URLs internas configurables por variables de entorno en `diagnosis` (`IDENTITY_HEALTH_URL`, `AI_INFERENCE_HEALTH_URL`, `NOTIFICATION_HEALTH_URL`, `ASSISTANT_HEALTH_URL`) apuntando exclusivamente a `/health/ready` sin credenciales embebidas.
- Para `diagnosis` mismo, evalúa su propio chequeo de readiness local (DB + RabbitMQ/MinIO) sin auto-llamada HTTP recursiva.
- Clasificación determinista por servicio:
  - `OK`: HTTP `200` y body `status == "ready"` (o `"ok"`).
  - `DEGRADED`: HTTP `200` con estado degradado o HTTP `503` con respuesta estructurada de dependencia parcial.
  - `DOWN`: error de conexión/DNS o HTTP 5xx inesperado.
  - `UNKNOWN`: `httpx.TimeoutException` al superar los `2.0 s`.
- `assistant` se marca con `optional: true`; su ausencia (perfil Compose inactivo) reporta `status: "DOWN"` o `"UNKNOWN"` sin degradar `overall_status` del núcleo.
- `overall_status`: `"OK"` si todos los servicios núcleo (`identity`, `diagnosis`, `ai_inference`, `notification`) están en `"OK"`; `"DEGRADED"` si alguno del núcleo está en `"DEGRADED"`/`"UNKNOWN"` o hay servicios núcleo caídos parcialmente; `"DOWN"` si todos los del núcleo sondeados fallan.
- Métricas locales de `diagnosis`: `outbox_pending_count` (`COUNT(*)` en `diagnosis_outbox WHERE published_at IS NULL`) y `quarantine_count` (`COUNT(*)` en `diagnosis_quarantine_messages`).

### D5. Lectura administrativa explícita y auditada de fotografía (`D-19`)
- Ruta: `GET /api/v1/admin/diagnoses/{id}/image` (`diagnosis_admin_get_image`), protegida por `require_admin`.
- Flujo seguro:
  1. Busca el diagnóstico por `id`. Si no existe o no tiene `image_object_key` (o la imagen ya fue eliminada por retención), responde `404` genérico (`RESOURCE_NOT_FOUND`).
  2. Recupera los bytes desde MinIO (`object_storage.get_bytes(image_object_key)`). Si el objeto ya no existe en MinIO, responde `404` genérico.
  3. Inserta en `diagnosis_audit_logs` el asiento `ADMIN_VIEW_DIAGNOSIS_IMAGE` con `actor_id = admin.user_id`, `target_type = "DIAGNOSIS"`, `target_id = diagnosis.id`, `correlation_id`, `details = {"owner_id": str(diagnosis.owner_id), "status": diagnosis.status}` y hace `commit` **antes** de entregar la respuesta binaria.
  4. Devuelve `Response(content=image_bytes, media_type=diagnosis.image_content_type)` con cabeceras `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff` y `X-Correlation-ID`.
- `/api/v1/diagnoses/{id}/image` NO cambia (sigue verificando `owner_id == current_user.user_id` y devolviendo `404` incluso a `ADMIN`).
- `/api/v1/admin/diagnoses` NO cambia (sigue devolviendo solo metadatos).

### D6. Notificaciones (`read-all`, `unread-count`) y Asistente (`OPEN_AUDIT`, `OPEN_MONITORING`)
- **`services/notification/`:**
  - `PATCH /api/v1/notifications/read-all`: `UPDATE notifications SET read_at = :now WHERE owner_id = :owner_id AND read_at IS NULL` devolviendo `rowcount` como `{"updated_count": rowcount}`. Sin cuerpo JSON requerido.
  - `GET /api/v1/notifications/unread-count`: `SELECT COUNT(*) FROM notifications WHERE owner_id = :owner_id AND read_at IS NULL` devolviendo `{"unread_count": count}`.
  - Ambas rutas aplican `Cache-Control: private, no-store` y `X-Correlation-ID`.
- **`extensions/assistant/`:**
  - En `app/domain/registry.py`, cambiar `available=True` para `OPEN_AUDIT` (`target="AUDIT"`, `allowed_roles=frozenset({"ADMIN"})`) y `OPEN_MONITORING` (`target="MONITORING"`, `allowed_roles=frozenset({"ADMIN"})`).
  - Actualizar `FakeAssistantAdapter` y pruebas unitarias/integración para verificar `200 NAVIGATE` con `ADMIN` y `403 FORBIDDEN` con `USER`, conservando además una prueba unitaria de regresión que valide que cualquier intent con `available=False` en el registro sigue retornando `action=None`.

### D7. Enrutamiento Nginx y contratos OpenAPI
- En `infra/nginx/default.conf`:
  - `/api/v1/admin/users` (prefijo ya existente hacia `identity`, cubre `/api/v1/admin/users/stats` y `/api/v1/admin/users/{id}/block`; verificar que coincida exactamente).
  - Añadir bloque explícito `/api/v1/admin/audit/identity` → `identity`.
  - Añadir bloques explícitos `/api/v1/admin/audit/diagnosis`, `/api/v1/admin/metrics/summary`, `/api/v1/admin/models`, `/api/v1/admin/system/status` → `diagnosis` (junto con `/api/v1/admin/diagnoses` que ya cubre `/api/v1/admin/diagnoses/{id}/image`).
  - `/api/v1/notifications` ya enruta a `notification`, cubriendo `/api/v1/notifications/read-all` y `/api/v1/notifications/unread-count`.
  - Mantener `/internal` y `/health` bloqueados externamente con `404` y `Cache-Control: private, no-store` sin caché de proxy en `/api/v1/*`.
- En `contracts/`:
  - Registrar las 9 operaciones nuevas en `identity.openapi.json` (+2), `diagnosis.openapi.json` (+5), `notification.openapi.json` (+2), `contracts/operations.json` (total 57 operaciones núcleo), `contracts/security-matrix.json` y actualizar la nota de `audit`, `metrics` y `model-info` en `contracts/deferred-operations.json` (preservando su invariante histórico `status: "pending-contract"` exigido por `test_deferred_inventory_has_owner_before_consumers`, mientras el inventario oficial de `operations.json` las promueve a `implemented` al cierre).

## Risks / Trade-offs

- **Riesgo: Latencia acumulada en `GET /api/v1/admin/system/status` si una dependencia se cuelga.**
  - *Mitigación:* Sondeo concurrente con `asyncio.gather` y timeout estricto de `2.0 s` por dependencia (connect + read), devolviendo `UNKNOWN` sin bloquear ni generar `500`.
- **Riesgo: Ruptura de clientes existentes que invocan `PATCH /api/v1/admin/users/{id}/block` sin cuerpo JSON.**
  - *Mitigación:* El cuerpo `{reason}` es estrictamente opcional (`body: BlockUserRequest | None = None`), preservando 100 % la compatibilidad con llamadas sin payload y con las pruebas del Incremento 1/2.
- **Riesgo: Fuga de fotografía o acceso no auditado en `D-19`.**
  - *Mitigación:* El registro `ADMIN_VIEW_DIAGNOSIS_IMAGE` se persiste y confirma en `diagnosis_audit_logs` antes de retornar el binario; si falla la auditoría, no se entregan bytes. Además se mantiene `Cache-Control: private, no-store` y pruebas negativas para `USER` (`403`) y ruta de propietario (`404`).
- **Riesgo: Confundir versiones históricas en `GET /api/v1/admin/models` con un modelo productivo activo.**
  - *Mitigación:* Campos explícitamente separados (`real_inference_authorized`, `runtime_status`, `active_model: null` vs `historical_versions`) y pruebas automatizadas verificando `REAL_INFERENCE_AUTHORIZED=false`.

## Migration Plan

1. **Sin migraciones SQL destructivas:** No se requieren nuevas revisiones de Alembic porque todas las tablas e índices necesarios ya están aplicados en PostgreSQL.
2. **Despliegue ordenado:**
   - Publicar ADR-0016 y contratos OpenAPI (`contract-only` al inicio).
   - Implementar y probar unitariamente `identity`, `diagnosis`, `notification` y `extensions/assistant`.
   - Actualizar `infra/nginx/default.conf`, `docker-compose.yml` y `.env.example` (variables de URL interna `/health/ready` y `REAL_INFERENCE_AUTHORIZED` en `diagnosis`).
   - Ejecutar la nueva verificación integrada E2E `scripts/check_admin_observability_integration.py` más la regresión de `check_environment.py`, `check_notification_integration.py` y `check_assistant_integration.py`.
   - Promover las 9 operaciones a `implemented` en `contracts/operations.json`, validar contratos (`scripts/validate_contracts.py` + `tests/contracts`) y registrar evidencia en `docs/evidence/INCREMENTO-5-ADMIN-Y-OBSERVABILIDAD.md`.
3. **Rollback:** Al ser puramente aditivo y sin cambios de esquema en BD, revertir el despliegue restaura las 48 operaciones previas sin pérdida de datos ni migraciones inversas.
