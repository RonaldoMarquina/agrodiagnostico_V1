## MODIFIED Requirements

### Requirement: Administración de cuentas de usuario por Administrador con revocación de sesiones
El sistema SHALL proporcionar al usuario con rol `ADMIN` endpoints para consultar la lista de usuarios y modificar su estado operativo. Mediante `GET /api/v1/admin/users`, el administrador SHALL obtener un listado paginado con los atributos públicos y estado (`ACTIVE` o `BLOCKED`) de los usuarios. Mediante `PATCH /api/v1/admin/users/{id}/block`, el administrador SHALL poder bloquear una cuenta distinta a la propia; el sistema SHALL rechazar con código `409` (`SELF_BLOCK_NOT_ALLOWED`) cualquier intento de un administrador de bloquear su propia cuenta (`actor_id == target_id`). El endpoint `PATCH /api/v1/admin/users/{id}/block` SHALL aceptar opcionalmente un cuerpo JSON cerrado `{"reason": "<texto>"}` con motivo entre 5 y 300 caracteres tras recortar espacios (manteniendo compatibilidad cuando se invoca sin cuerpo) y rechazar con `400` cuerpos malformados, campos adicionales o motivos fuera de rango. Ante un bloqueo válido, el sistema SHALL actualizar el estado del usuario a `BLOCKED`, revocar inmediatamente todas las refresh sessions activas asociadas a dicho usuario en PostgreSQL (`revoked_at = NOW()`), e insertar el evento `USER_BLOCKED` en `audit_logs` incluyendo `reason` en `details` cuando haya sido provisto. Mediante `PATCH /api/v1/admin/users/{id}/activate`, el administrador SHALL poder reactivar una cuenta previamente bloqueada registrando la acción `USER_ACTIVATED` en `audit_logs`.

#### Scenario: Administrador consulta lista de usuarios
- **WHEN** un administrador autenticado realiza un GET a `/api/v1/admin/users`
- **THEN** el sistema devuelve código 200 con la lista paginada de usuarios incluyendo identificador, email, nombre visible, rol, estado y fecha de registro

#### Scenario: Administrador bloquea cuenta y revoca sesiones en PostgreSQL
- **WHEN** un administrador envía un PATCH a `/api/v1/admin/users/{id}/block` para un usuario existente distinto de sí mismo (sin cuerpo o con motivo válido)
- **THEN** el sistema actualiza el estado del usuario a `BLOCKED`, revoca atómicamente todas sus refresh sessions en PostgreSQL, registra `USER_BLOCKED` en `audit_logs` y responde con código 200

#### Scenario: Administrador intenta bloquearse a sí mismo
- **WHEN** un administrador autenticado envía un PATCH a `/api/v1/admin/users/{id}/block` donde `{id}` coincide con su propio `sub`
- **THEN** el sistema rechaza la operación con código `409` (`SELF_BLOCK_NOT_ALLOWED`) sin modificar el estado de la cuenta ni revocar sus sesiones

#### Scenario: Bloqueo con motivo registrado en auditoría y validación de motivo inválido
- **WHEN** un administrador envía `PATCH /api/v1/admin/users/{id}/block` con `{"reason": "Actividad sospechosa confirmada"}` o con un cuerpo inválido (como `{"reason": "abc"}` o campos no permitidos)
- **THEN** con motivo válido persiste `reason` en `audit_logs.details` junto con el evento `USER_BLOCKED`, y con cuerpo inválido responde `400` con el envelope de error estándar sin bloquear la cuenta

#### Scenario: Usuario con rol USER intenta bloquear cuenta
- **WHEN** un usuario con rol `USER` envía un PATCH a `/api/v1/admin/users/{id}/block`
- **THEN** el sistema rechaza la solicitud con código 403
