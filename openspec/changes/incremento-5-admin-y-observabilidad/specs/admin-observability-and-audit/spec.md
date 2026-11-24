# admin-observability-and-audit Specification

## Purpose

Proveer al rol administrativo capacidades segregadas y solo lectura de auditoría, estadísticas de cuentas, métricas agregadas de diagnósticos, inventario honesto de modelos, monitoreo operativo con timeouts acotados y lectura administrativa explícita y auditada de fotografías, preservando la propiedad de datos de cada servicio y las garantías de seguridad y ML vigentes.

## ADDED Requirements

### Requirement: Consulta segregada de auditoría administrativa
El sistema SHALL exponer dos endpoints segregados por propietario de datos para consultar registros inmutables de auditoría: `GET /api/v1/admin/audit/identity` servido por `identity` sobre `audit_logs`, y `GET /api/v1/admin/audit/diagnosis` servido por `diagnosis` sobre `diagnosis_audit_logs`. Ambos endpoints SHALL exigir rol `ADMIN` (respondiendo `401` sin token válido y `403` para rol `USER`), ordenar de forma determinista por `created_at DESC, id DESC` mediante paginación keyset con cursor opaco firmado y ligado al actor y propósito de consulta (`limit` en rango `1..100`, valor por defecto `20`), admitir filtros acotados (`action`, `actor_id`, `target_id`, `from`, `to` en UTC, más `target_type` en `diagnosis`), e incluir `X-Correlation-ID` y `Cache-Control: private, no-store`. Ningún registro devuelto SHALL contener contraseñas en texto claro, hashes, tokens, claves privadas ni secretos de infraestructura.

#### Scenario: Administrador consulta auditoría de identidad con paginación y filtros
- **WHEN** un usuario autenticado con rol `ADMIN` consulta `GET /api/v1/admin/audit/identity` con `limit` válido y filtros opcionales (`action`, `actor_id`, `target_id`, `from`, `to`) y avanza con `next_cursor`
- **THEN** el servicio `identity` devuelve `200` con los registros de `audit_logs` en orden descendente determinista sin duplicados ni omisiones, excluyendo secretos y con `Cache-Control: private, no-store`

#### Scenario: Administrador consulta auditoría de diagnósticos con paginación y filtros
- **WHEN** un usuario autenticado con rol `ADMIN` consulta `GET /api/v1/admin/audit/diagnosis` con `limit` válido y filtros opcionales (`action`, `actor_id`, `target_type`, `target_id`, `from`, `to`)
- **THEN** el servicio `diagnosis` devuelve `200` con los registros de `diagnosis_audit_logs` correspondientes sin leer tablas de otros servicios

#### Scenario: Acceso denegado a auditoría para rol USER o cursor/filtros inválidos
- **WHEN** un usuario con rol `USER` invoca `GET /api/v1/admin/audit/identity` o `GET /api/v1/admin/audit/diagnosis`, o un `ADMIN` envía un cursor alterado, un `limit` fuera de `1..100` o un rango `from > to`
- **THEN** el sistema responde `403` para rol `USER` y `400` con el envelope de error estándar para parámetros o cursor inválidos

### Requirement: Estadísticas de cuentas y métricas agregadas de diagnósticos
El sistema SHALL exponer `GET /api/v1/admin/users/stats` en `identity` y `GET /api/v1/admin/metrics/summary` en `diagnosis`, ambos protegidos exclusivamente para rol `ADMIN` con `X-Correlation-ID` y `Cache-Control: private, no-store`. `GET /api/v1/admin/users/stats` SHALL devolver únicamente agregados reales calculados sobre la tabla `users` (`total`, `active`, `blocked`, `admins`, `users`). `GET /api/v1/admin/metrics/summary` SHALL aceptar un rango opcional `from`/`to` en UTC (acotado a un máximo de 90 días; por defecto últimos 30 días) y devolver el total de diagnósticos, conteos por cada estado oficial (`PENDIENTE`, `PROCESANDO`, `COMPLETADO`, `NO_CONCLUYENTE`, `FALLIDO`, `CANCELADO`), conteos por `inconclusive_reason_code`, confianza media real calculada únicamente sobre diagnósticos con `confidence_score` no nulo (`null` si no hay muestras) y una serie diaria ordenada por fecha UTC. Rangos con `from > to` o ventana superior a 90 días SHALL rechazarse con `400`.

#### Scenario: Administrador consulta estadísticas reales de cuentas
- **WHEN** un usuario con rol `ADMIN` consulta `GET /api/v1/admin/users/stats`
- **THEN** `identity` responde `200` con conteos exactos de usuarios totales, activos, bloqueados, administradores y usuarios estándar

#### Scenario: Administrador consulta métricas agregadas de diagnósticos por rango
- **WHEN** un usuario con rol `ADMIN` consulta `GET /api/v1/admin/metrics/summary` con rango `from`/`to` válido o por defecto
- **THEN** `diagnosis` responde `200` con totales por los 6 estados oficiales, desglose por `inconclusive_reason_code`, `average_confidence` real (`null` si no existen diagnósticos con confianza) y serie diaria ordenada

#### Scenario: Rango inválido o acceso no autorizado a estadísticas y métricas
- **WHEN** un usuario con rol `USER` invoca cualquiera de los dos endpoints o un `ADMIN` envía `from > to` o una ventana mayor a 90 días
- **THEN** el sistema responde `403` para rol `USER` y `400` con el envelope de error estándar para rangos inválidos

### Requirement: Inventario solo lectura de modelos activos e históricos
El sistema SHALL exponer `GET /api/v1/admin/models` en `diagnosis` exclusivamente para rol `ADMIN`, con carácter estrictamente de solo lectura y sin permitir activar, promover ni entrenar modelos desde la API. La respuesta SHALL separar explícitamente el estado real de autorización en runtime (`real_inference_authorized`, `active_model`, `runtime_status`) del inventario histórico agregado a partir de `diagnoses` (`historical_versions` agrupado por `model_id`, `model_version` y `dataset_version` con `diagnoses_count` y `last_used_at`). Mientras `REAL_INFERENCE_AUTHORIZED=false`, el endpoint SHALL reportar `real_inference_authorized = false`, `active_model = null` y `runtime_status = "INACTIVE_GATE_BLOCKED"` sin simular un modelo activo en producción.

#### Scenario: Consulta honesta con inferencia real no autorizada
- **WHEN** un usuario con rol `ADMIN` consulta `GET /api/v1/admin/models` en un entorno con `REAL_INFERENCE_AUTHORIZED=false`
- **THEN** `diagnosis` responde `200` indicando `real_inference_authorized = false`, `active_model = null`, `runtime_status = "INACTIVE_GATE_BLOCKED"` y la lista real de `historical_versions` observadas en `diagnoses` (o lista vacía si no existen registros)

#### Scenario: Usuario estándar intenta consultar inventario de modelos
- **WHEN** un usuario con rol `USER` consulta `GET /api/v1/admin/models`
- **THEN** el sistema responde `403` con el envelope de error estándar

### Requirement: Monitoreo operativo solo lectura con timeouts acotados
El sistema SHALL exponer `GET /api/v1/admin/system/status` en `diagnosis` exclusivamente para rol `ADMIN`, con `X-Correlation-ID` y `Cache-Control: private, no-store`. El endpoint SHALL evaluar en modo solo lectura la salud de los componentes internos mediante sondeo HTTP a `/health/ready` con timeout estricto de 2 segundos por dependencia (`identity`, `diagnosis`, `ai_inference`, `notification`, más la extensión opcional `assistant` cuando esté configurada), devolviendo para cada componente un estado normalizado (`OK`, `DEGRADED`, `DOWN` o `UNKNOWN`), `latency_ms` cuando aplique y si es opcional, junto con métricas locales de `diagnosis` (`outbox_pending_count` y `quarantine_count`) y `checked_at` en UTC. La indisponibilidad o timeout de un componente o la ausencia del perfil `assistant` SHALL reportarse dentro del payload `200` sin provocar error `500` ni bloquear el sondeo. El endpoint SHALL NOT invocar la Management API de RabbitMQ ni exponer credenciales, URLs con contraseñas o detalles internos sensibles.

#### Scenario: Monitoreo reporta estado agregado con dependencias sanas y extensión opcional ausente
- **WHEN** un usuario con rol `ADMIN` consulta `GET /api/v1/admin/system/status` mientras los servicios núcleo responden `200` en `/health/ready` y el perfil opcional `assistant` no está levantado
- **THEN** `diagnosis` responde `200` dentro del límite de tiempo con los servicios núcleo en `OK`, `assistant` marcado como opcional en estado `DOWN` o `UNKNOWN`, el estado global reflejando la salud del núcleo y los conteos reales de `outbox_pending_count` y `quarantine_count`

#### Scenario: Dependencia lenta excede timeout sin provocar fallo 500
- **WHEN** una dependencia sondeada excede el timeout de 2 segundos o rechaza conexión durante `GET /api/v1/admin/system/status`
- **THEN** `diagnosis` clasifica esa dependencia como `UNKNOWN` (timeout) o `DOWN` (error de conexión/HTTP) y devuelve `200` con el estado global degradado sin filtrar secretos ni fallar con `500`

#### Scenario: Acceso denegado a monitoreo para usuario estándar
- **WHEN** un usuario con rol `USER` invoca `GET /api/v1/admin/system/status`
- **THEN** el sistema responde `403` con el envelope de error estándar

### Requirement: Lectura administrativa explícita y auditada de fotografías
El sistema SHALL conservar la privacidad por defecto en la supervisión administrativa: `GET /api/v1/admin/diagnoses` SHALL continuar devolviendo únicamente metadatos sin URLs firmadas ni bytes de fotografía, y `GET /api/v1/diagnoses/{id}/image` SHALL mantener aislamiento estricto por propietario devolviendo `404` genérico incluso a usuarios con rol `ADMIN` sobre diagnósticos ajenos. Para la inspección explícita por soporte o administración, `diagnosis` SHALL exponer `GET /api/v1/admin/diagnoses/{id}/image` exclusivamente para rol `ADMIN` (`401` sin autenticación válida, `403` para rol `USER`). Antes de devolver los bytes de la fotografía con `Cache-Control: private, no-store` y `X-Correlation-ID`, el servicio SHALL confirmar que el diagnóstico y su objeto privado existen y SHALL persistir en `diagnosis_audit_logs` el asiento inmutable `ADMIN_VIEW_DIAGNOSIS_IMAGE` con `actor_id`, `target_type = "DIAGNOSIS"`, `target_id = id`, `correlation_id` y marca UTC. Si el diagnóstico no existe o la fotografía ya fue eliminada, el sistema SHALL responder `404` genérico sin registrar un acceso exitoso.

#### Scenario: Administrador realiza lectura explícita de fotografía con registro de auditoría obligatorio
- **WHEN** un usuario autenticado con rol `ADMIN` invoca `GET /api/v1/admin/diagnoses/{id}/image` sobre un diagnóstico existente cuya fotografía está almacenada en MinIO
- **THEN** `diagnosis` registra `ADMIN_VIEW_DIAGNOSIS_IMAGE` en `diagnosis_audit_logs` con el `actor_id` del administrador, `target_id = id` y `correlation_id`, y devuelve `200` con los bytes de la imagen, el `Content-Type` real, `Cache-Control: private, no-store` y `X-Correlation-ID`

#### Scenario: Ruta de propietario sigue aislada con 404 para ADMIN y listado administrativo no incluye imágenes
- **WHEN** un `ADMIN` consulta `GET /api/v1/diagnoses/{id}/image` sobre un diagnóstico de otro usuario o consulta `GET /api/v1/admin/diagnoses`
- **THEN** la ruta de propietario responde `404` genérico y el listado administrativo incluye solo metadatos sin bytes ni enlaces a imágenes

#### Scenario: Usuario estándar intenta usar ruta administrativa de fotografía o diagnóstico sin imagen
- **WHEN** un usuario con rol `USER` invoca `GET /api/v1/admin/diagnoses/{id}/image`, o un `ADMIN` invoca la ruta sobre un `id` inexistente o cuya imagen fue eliminada
- **THEN** el sistema responde `403` para rol `USER` y `404` genérico para recurso o fotografía inexistente sin emitir asiento exitoso de visualización
