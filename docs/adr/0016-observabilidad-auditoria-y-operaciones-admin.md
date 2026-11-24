# ADR-0016 — Observabilidad operativa, auditoría segregada y operaciones administrativas de cierre V1

Fecha: 2026-11-23. Estado: adoptado para `incremento-5-admin-y-observabilidad`.

Tarea: 1.1 de `incremento-5-admin-y-observabilidad`.

## Contexto

Con el cierre de `incremento-5-notificaciones` (48/48 operaciones núcleo en `contracts/operations.json`) y la extensión opcional `extensions/assistant/` (`3/3` operaciones en `contracts/extensions-operations.json`), el análisis del diseño objetivo del Frontend V1.2 (`docs/AgroDiagnostico_Diseno_Frontend_V1.2_Codex.md`, 20 pantallas completas) confirmó que faltaban por contratar e implementar nueve operaciones backend necesarias antes de construir la interfaz React definitiva:

1. Las tres capacidades mantenidas históricamente en `contracts/deferred-operations.json`: `audit`, `metrics` y `model-info`, junto con una vista agregada solo lectura de salud operativa (`system/status`).
2. La decisión de diseño `D-19` sobre acceso administrativo a fotografías de diagnósticos sin comprometer la privacidad por defecto.
3. Dos operaciones de ergonomía en `notification` (`read-all` y `unread-count`) para la campana y el centro de notificaciones, y dos refuerzos en `identity` (`users/stats`, protección contra auto-bloqueo y motivo opcional de bloqueo en auditoría).
4. La habilitación en `extensions/assistant/` de los dos últimos intents diferidos (`OPEN_AUDIT` y `OPEN_MONITORING`) para rol `ADMIN`.

Restricciones arquitectónicas previas que rigen esta decisión:
1. Cada servicio (`identity`, `diagnosis`, `ai_inference`, `notification`) es propietario exclusivo de sus tablas en PostgreSQL; ninguna operación puede leer ni escribir tablas de otro servicio (`AGENTS.md`, ADR-0001).
2. El cierre experimental de IA v1.4.3 dejó `REAL_INFERENCE_AUTHORIZED=false` y G2 rechazado (`docs/evidence/INCREMENTO-4-CIERRE-V1.4.3.md`); ninguna pantalla ni API administrativa puede simular un modelo productivo activo ni activar/entrenar modelos desde la UI.
3. El proxy Nginx no debe exponer `/internal/*` ni `/health/*`, y ninguna fotografía privada puede entregarse por URL pública ni cachearse en proxy/CDN (`Cache-Control: private, no-store`).

Trazabilidad normativa: ADR-0002 (contratos V1), ADR-0004 (JWT Ed25519 y RBAC), ADR-0006 (diagnósticos, catálogo y almacenamiento privado), ADR-0009/0012 (cierre ML v1.4.3), ADR-0014 (notificaciones), ADR-0015 (extensión de asistente) y las especificaciones delta de `openspec/changes/incremento-5-admin-y-observabilidad/specs/`.

## Alternativas consideradas

### A. Consulta de auditoría administrativa
- **Alternativa A1 (descartada): Unificar `audit_logs` y `diagnosis_audit_logs` en una consulta SQL cruzada o un quinto microservicio de auditoría.** Rompería el aislamiento de datos entre `identity` y `diagnosis` o introduciría un servicio extra fuera del presupuesto operativo de V1.
- **Alternativa A2 (adoptada): Endpoints segregados por servicio dueño — `GET /api/v1/admin/audit/identity` en `identity` y `GET /api/v1/admin/audit/diagnosis` en `diagnosis`.** Respeta el 100 % de los límites de microservicios, reutiliza las tablas inmutables existentes sin migraciones y permite que el frontend presente pestañas separadas o una vista unificada en cliente.

### B. Acceso administrativo a fotografías (`D-19`)
- **Alternativa B1 (descartada): Incluir URLs firmadas o imágenes directamente en `GET /api/v1/admin/diagnoses` o permitir que `ADMIN` lea `GET /api/v1/diagnoses/{id}/image`.** Violaría la privacidad por defecto, expondría fotografías masivamente durante la supervisión y rompería la invariante de aislamiento estricto (`404` en ruta de propietario).
- **Alternativa B2 (descartada): Prohibir totalmente la inspección de imágenes al administrador.** Impediría validar casos de soporte o calidad fotográfica en la pantalla administrativa de detalle.
- **Alternativa B3 (adoptada): Patrón de industria *privacidad por defecto + lectura explícita auditada*.** `GET /api/v1/admin/diagnoses` sigue devolviendo solo metadatos, `GET /api/v1/diagnoses/{id}/image` sigue respondiendo `404` incluso a `ADMIN` sobre recursos ajenos, y se expone `GET /api/v1/admin/diagnoses/{id}/image` (solo `ADMIN`) que registra obligatoriamente `ADMIN_VIEW_DIAGNOSIS_IMAGE` en `diagnosis_audit_logs` antes de transmitir el binario privado con `Cache-Control: private, no-store`.

### C. Monitoreo operativo (`GET /api/v1/admin/system/status`)
- **Alternativa C1 (descartada): Consultar la Management API de RabbitMQ o métricas internas con credenciales desde el backend público.** Aumentaría superficie de ataque, requeriría propagar credenciales de broker a la API y arriesgaría fugas de configuración.
- **Alternativa C2 (adoptada): Agregador solo lectura en `diagnosis` que sondea concurrentemente `/health/ready` de los servicios internos con timeout estricto de `2 s` y lee conteos locales de `diagnosis_outbox` (`sent_at IS NULL`) y `diagnosis_quarantine_messages`.** Devuelve siempre `200` con clasificación `OK | DEGRADED | DOWN | UNKNOWN`, sin propagar secretos ni fallar con `500` cuando un componente (o el perfil opcional `assistant`) está detenido o lento.

## Decisiones

### D1. Cero migraciones destructivas de base de datos
Todas las capacidades nuevas se construyen sobre tablas ya migradas y en producción local:
- `identity`: `users`, `refresh_sessions`, `audit_logs` (`details` JSONB almacena `{"reason": "..."}` cuando el administrador indica motivo en un bloqueo).
- `diagnosis`: `diagnoses` (`status`, `reason_code`, `calibrated_confidence`, `raw_score`, `model_id`, `model_version`, `dataset_version`, `object_key`, `deleted_at`, `created_at`), `publication_policies`, `diagnosis_audit_logs` (recibe el evento inmutable `ADMIN_VIEW_DIAGNOSIS_IMAGE`), `diagnosis_outbox` (`sent_at IS NULL`) y `diagnosis_quarantine_messages`.
- `notification`: `notifications` (`owner_id`, `read_at`).

### D2. Nueve operaciones núcleo nuevas (total 57 operaciones núcleo + 3 de extensión)
Todas las operaciones públicas nuevas exigen `UserBearer` JWT Ed25519 y emiten `X-Correlation-ID` y `Cache-Control: private, no-store`:

1. **Identity (+2 operaciones y refuerzo de `block`):**
   - `GET /api/v1/admin/users/stats` (`identity_admin_user_stats`, `ADMIN`): conteos exactos `total`, `active`, `blocked`, `admins`, `users`.
   - `GET /api/v1/admin/audit/identity` (`identity_admin_list_audit`, `ADMIN`): paginación keyset HMAC `(created_at DESC, id DESC)` con `limit` `1..100` (defecto `20`) y filtros `action`, `actor_id`, `target_id`, `from`, `to` (UTC), excluyendo contraseñas, hashes y tokens.
   - `PATCH /api/v1/admin/users/{id}/block` (existente reforzada): rechaza auto-bloqueo (`actor_id == target_id`) con `409 SELF_BLOCK_NOT_ALLOWED`; acepta cuerpo opcional cerrado `{"reason": "..."}` (`5..300` caracteres) manteniendo compatibilidad cuando se invoca sin cuerpo.
2. **Diagnosis (+5 operaciones):**
   - `GET /api/v1/admin/metrics/summary` (`diagnosis_admin_metrics_summary`, `ADMIN`): ventana UTC `from`/`to` (máximo 90 días, defecto 30 días), totales por los 6 estados oficiales, desglose por `reason_code` en `NO_CONCLUYENTE`, `average_confidence` real calculado sobre `COALESCE(calibrated_confidence, raw_score)` (`null` si no hay muestras) y `daily_series` ordenada por fecha UTC.
   - `GET /api/v1/admin/audit/diagnosis` (`diagnosis_admin_list_audit`, `ADMIN`): paginación keyset HMAC sobre `diagnosis_audit_logs` con filtros `action`, `actor_id`, `target_type`, `target_id`, `from`, `to`.
   - `GET /api/v1/admin/models` (`diagnosis_admin_list_models`, `ADMIN`, solo lectura): expone `real_inference_authorized` desde configuración real (`false` en V1), `runtime_status` (`INACTIVE_GATE_BLOCKED` cuando es `false`), `active_model: null`, `active_policy_version` y `historical_versions` reales agrupadas desde `diagnoses`.
   - `GET /api/v1/admin/system/status` (`diagnosis_admin_system_status`, `ADMIN`, solo lectura): sondea `/health/ready` de `identity`, `ai_inference`, `notification` y `assistant` (`optional: true`) con timeout `2 s` por servicio, evalúa el readiness local de `diagnosis` y reporta `outbox_pending_count` y `quarantine_count`.
   - `GET /api/v1/admin/diagnoses/{id}/image` (`diagnosis_admin_get_image`, `ADMIN`): confirma existencia de diagnóstico no borrado y objeto en MinIO, persiste `ADMIN_VIEW_DIAGNOSIS_IMAGE` en `diagnosis_audit_logs` antes de devolver el binario con `Cache-Control: private, no-store` y `X-Content-Type-Options: nosniff`; devuelve `404` genérico si no existe o fue borrado.
3. **Notification (+2 operaciones):**
   - `PATCH /api/v1/notifications/read-all` (`notification_mark_all_read`, `USER`/`ADMIN` sobre recursos propios): actualización atómica idempotente sin cuerpo requerido devolviendo `{"updated_count": N}` sin alterar avisos ya leídos ni de otros usuarios.
   - `GET /api/v1/notifications/unread-count` (`notification_unread_count`, `USER`/`ADMIN` sobre recursos propios): devuelve `{"unread_count": N}`.

### D3. Habilitación de `OPEN_AUDIT` y `OPEN_MONITORING` en `extensions/assistant/`
Al quedar contratadas e implementadas las capacidades backend de auditoría y monitoreo:
- Se actualiza `AssistantResponse` en `contracts/schemas/common.schema.json` retirando `OPEN_AUDIT` y `OPEN_MONITORING` de la restricción `action = null` (conservándola para los 4 intents `EXPLAIN_*` y estados `CLARIFICATION_REQUIRED`/`OUT_OF_SCOPE`).
- En `extensions/assistant/app/domain/registry.py`, `OPEN_AUDIT -> AUDIT` y `OPEN_MONITORING -> MONITORING` pasan a `available = True` exclusivamente para rol `ADMIN` (`USER` continúa recibiendo `403 FORBIDDEN`).

### D4. Inventario histórico de diferidos y ciclo de promoción contractual
Las 9 operaciones nacen con `x-status: "contract-only"` en el Grupo 1 y solo se promueven a `"implemented"` en el Grupo 6 tras superar las pruebas unitarias e integración E2E vía Nginx (`scripts/check_admin_observability_integration.py`). Las entradas `audit`, `metrics` y `model-info` en `contracts/deferred-operations.json` actualizan sus notas indicando las rutas formales contratadas, preservando el invariante histórico exigido por `test_deferred_inventory_has_owner_before_consumers`.

## Consecuencias

### Positivas
- Completa el 100 % del contrato backend requerido por las 20 pantallas del Frontend V1.2 sin inventar datos ni alterar los límites de microservicios.
- Mantiene intacto el cierre experimental de IA v1.4.3 (`REAL_INFERENCE_AUTHORIZED=false`) y la privacidad por defecto de fotografías de agricultores.
- Desbloquea los 16/16 intents del asistente conversacional para el panel administrativo.

### Negativas / Restricciones
- La auditoría queda repartida en dos endpoints (`audit/identity` y `audit/diagnosis`); el cliente web debe ofrecer selector de fuente o vista combinada en memoria.
- Cada sondeo HTTP remoto se cancela al agotar su plazo de `2 s`, incluida la lectura del cuerpo. La latencia total también depende de las comprobaciones locales y de los conteos de la base de Diagnosis.
