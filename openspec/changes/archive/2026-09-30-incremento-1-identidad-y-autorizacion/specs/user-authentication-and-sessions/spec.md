# Spec Delta

## Purpose

Proporciona registro público de cuentas de usuario, autenticación segura con Argon2id, emisión stateless de JWT Ed25519, sesiones compartidas en PostgreSQL con rotación atómica, y detección de reuso de credenciales compatible con múltiples instancias.

## ADDED Requirements

### Requirement: Registro público de usuarios
El sistema SHALL permitir el registro de nuevos usuarios asignando de forma predeterminada el rol `USER`. La solicitud SHALL requerir un correo electrónico válido, una contraseña de entre 12 y 128 caracteres y un nombre visible (`display_name`). Si la solicitud incluye un rol u otros campos no permitidos, el sistema SHALL rechazarla con código 400. Si el correo electrónico ya se encuentra registrado, el sistema SHALL responder con código 409 y mensaje genérico `ACCOUNT_UNAVAILABLE` sin revelar la existencia previa de la cuenta. El registro exitoso SHALL responder con código 201 y el perfil creado, sin iniciar sesión automáticamente.

#### Scenario: Registro exitoso
- **WHEN** un cliente envía una solicitud POST a `/api/v1/auth/register` con correo no registrado, contraseña válida y display_name
- **THEN** el sistema persiste al usuario con rol `USER`, almacena la contraseña hasheada con Argon2id y responde 201 con los datos públicos del perfil sin tokens de sesión

#### Scenario: Intento de escalada de rol en registro
- **WHEN** un cliente envía una solicitud POST a `/api/v1/auth/register` incluyendo el campo `role: "ADMIN"`
- **THEN** el sistema rechaza la solicitud con código 400 y código de error `INVALID_REQUEST` sin crear el usuario

#### Scenario: Correo duplicado en registro
- **WHEN** un cliente envía una solicitud POST a `/api/v1/auth/register` con un correo electrónico previamente registrado
- **THEN** el sistema responde 409 con el código `ACCOUNT_UNAVAILABLE` y mensaje neutro sin confirmar los datos de la cuenta existente

### Requirement: Autenticación segura de usuarios (Login)
El sistema SHALL autenticar a usuarios existentes mediante correo electrónico y contraseña verificados con Argon2id. Si la cuenta está bloqueada o las credenciales no coinciden, el sistema SHALL retornar código 401 genérico sin distinguir entre usuario inexistente o contraseña incorrecta. La solicitud SHALL validar el encabezado `Origin` contra la lista de orígenes permitidos. Ante autenticación exitosa, el sistema SHALL emitir en el cuerpo JSON un token de acceso (`access_token`) con formato JWT firmado asimétricamente con Ed25519 (algoritmo EdDSA) con claims mínimos `sub`, `role`, `iss`, `aud`, `exp` (15 minutos), `iat` y `jti`. Asimismo, SHALL generar un refresh token aleatorio seguro (256 bits), almacenar en PostgreSQL únicamente su hash `SHA-256(refresh_token)` con un `family_id` único, e inyectar el valor real en la cookie `__Secure-agro_refresh` con atributos `HttpOnly`, `Secure`, `SameSite=Lax` y `Path=/api/v1/auth` junto a un token CSRF devuelto en el JSON.

#### Scenario: Inicio de sesión exitoso
- **WHEN** un usuario activo envía credenciales válidas y encabezado Origin permitido a `/api/v1/auth/login`
- **THEN** el sistema responde 200 con `access_token` JWT Ed25519 (15 min), `csrf_token`, `token_type: Bearer`, tiempo de expiración y la cookie `__Secure-agro_refresh` persistida en PostgreSQL como hash

#### Scenario: Credenciales inválidas o cuenta inexistente
- **WHEN** un cliente envía credenciales erróneas a `/api/v1/auth/login`
- **THEN** el sistema responde 401 genérico con código `INVALID_CREDENTIALS` sin indicar qué campo falló

#### Scenario: Intento de login con cuenta bloqueada
- **WHEN** un usuario con estado `BLOCKED` intenta iniciar sesión con credenciales correctas
- **THEN** el sistema deniega el acceso con código 401 genérico e impide la emisión de tokens y cookies

### Requirement: Rotación atómica de sesión y detección de reuso (Refresh)
El sistema SHALL permitir la rotación de sesiones activas mediante el endpoint `POST /api/v1/auth/refresh`. La solicitud SHALL requerir la cookie `__Secure-agro_refresh` vigente, el encabezado `X-CSRF-Token` coincidente con la sesión y un encabezado `Origin` autorizado. La operación SHALL ejecutarse de forma atómica en PostgreSQL mediante bloqueo pesimista de fila (`SELECT ... FOR UPDATE`). Si la sesión es válida y no ha sido rotada previamente, el sistema SHALL marcar la sesión actual con `rotated_at = NOW()`, generar una nueva sesión dentro del mismo `family_id` con nuevo hash SHA-256, y devolver atómicamente un nuevo `access_token` y una nueva cookie de refresh. Si el sistema detecta que el token presentado ya había sido rotado (`rotated_at IS NOT NULL`), SHALL identificar la condición de reuso malicioso, revocar inmediatamente todas las sesiones asociadas a ese `family_id` (`revoked_at = NOW()`), registrar el evento en `audit_logs` y responder con código 401.

#### Scenario: Renovación exitosa de sesión entre instancias
- **WHEN** una instancia A emitió un login y el cliente presenta la cookie de refresh y X-CSRF-Token válidos ante una instancia B en `/api/v1/auth/refresh`
- **THEN** la instancia B bloquea atómicamente la fila en PostgreSQL, marca la rotación, persiste la nueva sesión en el mismo family_id y devuelve 200 con nuevo access_token y cookie rotada

#### Scenario: Falla de protección CSRF en refresh
- **WHEN** un cliente presenta la cookie de refresh pero omite o envía un `X-CSRF-Token` discrepante
- **THEN** el sistema rechaza la solicitud con código 403 y no emite nuevos tokens

#### Scenario: Detección de reuso de refresh token
- **WHEN** un cliente intenta usar un refresh token que ya había sido rotado previamente
- **THEN** el sistema detecta la condición de reuso, revoca atómicamente todas las sesiones pertenecientes a ese family_id en PostgreSQL, registra en audit_logs y responde 401

### Requirement: Cierre seguro de sesión (Logout)
El sistema SHALL permitir el cierre de sesión mediante `POST /api/v1/auth/logout`. La solicitud SHALL exigir la cookie `__Secure-agro_refresh`, el encabezado `X-CSRF-Token` correspondiente y Origin permitido. El sistema SHALL marcar la sesión como revocada (`revoked_at = NOW()`) en PostgreSQL compartido y SHALL limpiar la cookie en la respuesta estableciendo `Max-Age=0`, respondiendo con código 204 sin contenido.

#### Scenario: Cierre de sesión exitoso procesado por cualquier instancia
- **WHEN** un cliente autenticado envía POST a `/api/v1/auth/logout` con cookie válida, CSRF y Origin ante cualquier instancia de Identity
- **THEN** el sistema revoca la sesión en PostgreSQL compartido, envía la cabecera Set-Cookie con Max-Age=0 y retorna código 204

#### Scenario: Logout sin cookie o con cookie inválida
- **WHEN** un cliente realiza POST a `/api/v1/auth/logout` sin la cookie `__Secure-agro_refresh` o con un hash inexistente
- **THEN** el sistema rechaza la solicitud con código 401
