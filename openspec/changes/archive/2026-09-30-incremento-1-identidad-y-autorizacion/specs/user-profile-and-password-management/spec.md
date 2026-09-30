# Spec Delta

## Purpose

Permite a los usuarios consultar y actualizar la información de su perfil, cambiar su contraseña de manera autenticada revocando sesiones activas e iniciar y completar la recuperación segura de acceso mediante tokens hasheados de un solo uso y notificaciones.

## ADDED Requirements

### Requirement: Consulta y actualización de perfil propio
El sistema SHALL permitir al usuario autenticado consultar los datos de su perfil mediante `GET /api/v1/profile` y actualizar parcialmente su información mediante `PATCH /api/v1/profile`. Ambas operaciones SHALL requerir un token de acceso de usuario válido (`UserBearer`). La consulta SHALL devolver `id`, `email`, `display_name`, `role` y `created_at`. La actualización mediante PATCH SHALL admitir únicamente la modificación del campo `display_name` (de 1 a 100 caracteres). Si la solicitud PATCH intenta modificar campos no permitidos como `email`, `role` o `password`, el sistema SHALL rechazar la solicitud con código 400 sin aplicar cambios.

#### Scenario: Consulta de perfil exitosa
- **WHEN** un usuario autenticado realiza una solicitud GET a `/api/v1/profile` con su Bearer token válido
- **THEN** el sistema responde 200 con el objeto de perfil que contiene su identificador UUID, email, display_name, role y fecha de creación

#### Scenario: Actualización de display_name
- **WHEN** un usuario autenticado envía PATCH a `/api/v1/profile` con un nuevo `display_name`
- **THEN** el sistema actualiza el nombre visible en la base de datos y responde 200 con el perfil actualizado

#### Scenario: Intento de modificación de campos no editables
- **WHEN** un usuario envía PATCH a `/api/v1/profile` intentando modificar el campo `role` o `email`
- **THEN** el sistema rechaza la solicitud con código 400 y código de error `INVALID_REQUEST` sin alterar los datos del usuario

### Requirement: Cambio autenticado de contraseña con revocación de sesiones
El sistema SHALL permitir al usuario autenticado cambiar su contraseña mediante el endpoint `PUT /api/v1/profile/password`. La solicitud SHALL requerir un token de acceso válido (`UserBearer`) y un cuerpo JSON con la contraseña actual (`current_password`) y la nueva contraseña (`new_password`) de entre 12 y 128 caracteres. El sistema SHALL verificar que la contraseña actual sea correcta contra el hash Argon2id; de no coincidir, SHALL rechazar la solicitud con código 400 o 401 genérico `INVALID_CREDENTIALS`. Ante una solicitud válida, el sistema SHALL calcular el nuevo hash Argon2id, persistirlo, revocar atómicamente en PostgreSQL todas las refresh sessions activas del usuario (`revoked_at = NOW()`), registrar el evento en `audit_logs` y responder con código 200.

#### Scenario: Cambio de contraseña exitoso con revocación de sesiones
- **WHEN** un usuario autenticado envía su contraseña actual correcta y una nueva contraseña válida que cumple las políticas
- **THEN** el sistema actualiza el hash Argon2id en PostgreSQL, revoca todas sus refresh sessions activas, registra la auditoría inmutable y responde 200

#### Scenario: Contraseña actual incorrecta
- **WHEN** un usuario autenticado envía una contraseña actual que no coincide con su hash registrado
- **THEN** el sistema rechaza la solicitud con código de error de credenciales inválidas y mantiene inalteradas la contraseña y las sesiones

### Requirement: Flujo de recuperación de contraseña con token hasheado de un solo uso
El sistema SHALL proporcionar un flujo seguro de recuperación de contraseña en dos pasos. En el primer paso, `POST /api/v1/auth/password-recovery`, el cliente proporciona el correo electrónico. El sistema SHALL responder SIEMPRE con código 202 genérico (`RecoveryAccepted`) sin confirmar si la cuenta existe o no. Si la cuenta existe y está activa, el sistema SHALL generar un token temporal criptográficamente seguro de un solo uso, almacenar en PostgreSQL únicamente su hash `SHA-256(token)` y fecha de expiración (máximo 30 minutos), y despachar el token en texto plano a través del adaptador de correo. En el segundo paso, `POST /api/v1/auth/password-recovery/confirm`, el cliente envía el token en texto plano y la nueva contraseña (12 a 128 caracteres). El sistema SHALL verificar el hash del token contra `password_recovery_tokens`, comprobar su vigencia y que `used_at IS NULL`, actualizar la contraseña con Argon2id, marcar `used_at = NOW()`, revocar atómicamente todas las refresh sessions del usuario en PostgreSQL, registrar el evento en `audit_logs` y responder 200.

#### Scenario: Solicitud de recuperación sin enumeración de cuentas
- **WHEN** un cliente envía una solicitud POST a `/api/v1/auth/password-recovery` con cualquier correo electrónico
- **THEN** el sistema responde con código 202 y el mensaje estándar "Si la cuenta existe, recibirá instrucciones de recuperación.", despachando el mensaje con el token solo si la cuenta existe y guardando únicamente el hash SHA-256 en la base de datos

#### Scenario: Confirmación exitosa de restablecimiento de contraseña
- **WHEN** un cliente presenta un token de recuperación vigente y no consumido junto a una nueva contraseña válida en `/api/v1/auth/password-recovery/confirm`
- **THEN** el sistema actualiza el hash de la contraseña, marca el token como consumido, revoca todas las refresh sessions del usuario en PostgreSQL, inserta registro en audit_logs y responde con código 200

#### Scenario: Intento con token de recuperación expirado o reutilizado
- **WHEN** un cliente intenta confirmar un restablecimiento con un token ya consumido o cuya vigencia ha expirado
- **THEN** el sistema rechaza la operación con código 400 y código de error `INVALID_TOKEN` sin modificar la contraseña
