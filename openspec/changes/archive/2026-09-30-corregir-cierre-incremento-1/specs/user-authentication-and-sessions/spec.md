# Spec Delta

## MODIFIED Requirements

### Requirement: Rotación atómica de sesión y detección de reuso (Refresh)
El sistema SHALL permitir la rotación de sesiones activas mediante el endpoint `POST /api/v1/auth/refresh`. La solicitud SHALL requerir la cookie `__Secure-agro_refresh` vigente, el encabezado `X-CSRF-Token` coincidente con la sesión y un encabezado `Origin` autorizado. La operación SHALL ejecutarse de forma atómica en PostgreSQL mediante bloqueo pesimista de fila (`SELECT ... FOR UPDATE`). Si la sesión es válida y no ha sido rotada previamente, el sistema SHALL marcar la sesión actual con `rotated_at = NOW()`, generar una nueva sesión dentro del mismo `family_id` con nuevo hash SHA-256, y devolver atómicamente un nuevo `access_token` y una nueva cookie de refresh. Si el sistema detecta que el token presentado ya había sido rotado (`rotated_at IS NOT NULL`), SHALL identificar la condición de reuso malicioso, revocar inmediatamente todas las sesiones asociadas a ese `family_id` (`revoked_at = NOW()`), registrar el evento en `audit_logs` y responder con código 401.

El Origin SHALL compararse por esquema, host y puerto, sin aceptar otro origen por coincidencia de hostname. El CSRF SHALL estar ligado a la sesión de refresh; coincidencia entre cabecera y cookie arbitrarias no es suficiente. Estas comprobaciones SHALL aplicarse también a logout.

#### Scenario: Renovación exitosa de sesión entre instancias
- **WHEN** una instancia A emitió un login y el cliente presenta la cookie de refresh y X-CSRF-Token válidos ante una instancia B en `/api/v1/auth/refresh`
- **THEN** la instancia B bloquea atómicamente la fila en PostgreSQL, marca la rotación, persiste la nueva sesión en el mismo family_id y devuelve 200 con nuevo access_token y cookie rotada

#### Scenario: Falla de protección CSRF en refresh
- **WHEN** un cliente presenta la cookie de refresh pero omite o envía un `X-CSRF-Token` discrepante
- **THEN** el sistema rechaza la solicitud con código 403 y no emite nuevos tokens

#### Scenario: Detección de reuso de refresh token
- **WHEN** un cliente intenta usar un refresh token que ya había sido rotado previamente
- **THEN** el sistema detecta la condición de reuso, revoca atómicamente todas las sesiones pertenecientes a ese family_id en PostgreSQL, registra en audit_logs y responde 401

#### Scenario: CSRF ajeno a la sesión
- **WHEN** una solicitud presenta cookie y cabecera CSRF iguales pero no correspondientes al refresh
- **THEN** responde 403 sin rotar ni revocar la sesión

#### Scenario: Origin con esquema o puerto distinto
- **WHEN** Origin tiene el mismo host permitido pero distinto esquema o puerto no listado
- **THEN** responde 403 sin ejecutar login, refresh o logout
