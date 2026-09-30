# Spec Delta

## Purpose

Establece el control de acceso basado en roles (USER y ADMIN), la verificación stateless de tokens Ed25519, el aislamiento estricto de recursos con respuesta 404 genérica, la gestión administrativa de cuentas con revocación de sesiones y la auditoría inmutable de eventos de seguridad.

## ADDED Requirements

### Requirement: Verificación de roles y autorización inter-servicio
El sistema SHALL validar la autenticidad y vigencia de las solicitudes que incluyan el encabezado `Authorization: Bearer <JWT>`. Los tokens de acceso emitidos por el servicio de identidad SHALL estar firmados asimétricamente con Ed25519 (algoritmo `EdDSA`) e incluir los claims mínimos `sub` (identificador UUID del usuario), `role` (`USER` o `ADMIN`), `iss` (`agrodiagnostico-identity`), `aud` (`agrodiagnostico-api`), `exp` (15 minutos), `iat` y `jti`. Los servicios e instancias que reciben solicitudes autenticadas SHALL verificar criptográficamente la firma del token mediante la clave pública correspondiente sin requerir consultas de red ni acceso a base de datos. Si el token está expirado, alterado o carece de firma válida, el sistema SHALL rechazar la solicitud con código 401. Las rutas bajo `/api/v1/admin/*` SHALL exigir el rol `ADMIN`, rechazando a usuarios con rol `USER` con código 403 `FORBIDDEN`.

#### Scenario: Validación exitosa de token y autorización de usuario
- **WHEN** un cliente presenta un token de acceso válido firmado con Ed25519 con rol `USER` en una ruta de usuario
- **THEN** el servicio valida la firma y vigencia localmente con la clave pública, extrae la identidad del usuario y procesa la solicitud

#### Scenario: Acceso denegado a ruta administrativa para usuario ordinario
- **WHEN** un usuario con rol `USER` intenta acceder a una ruta administrativa bajo `/api/v1/admin/*`
- **THEN** el sistema rechaza la solicitud con código 403 y mensaje de permiso denegado

#### Scenario: Token expirado o con firma alterada
- **WHEN** un cliente envía un token cuya fecha de expiración ha vencido o cuya firma no coincide con la clave pública Ed25519
- **THEN** el sistema rechaza la solicitud con código 401 `UNAUTHORIZED`

### Requirement: Aislamiento estricto de recursos y respuesta 404 genérica
El sistema SHALL garantizar que los usuarios solo puedan acceder a los recursos que les pertenecen verificando que el `owner_id` del recurso coincida con el `sub` del token de acceso autenticado. Cuando un usuario solicite un recurso inexistente o perteneciente a otro usuario, el sistema SHALL retornar un código de estado `404 Not Found` con mensaje y estructura genéricos idénticos a los de un recurso no encontrado, impidiendo que usuarios no autorizados deduzcan la existencia o identificadores de recursos ajenos.

#### Scenario: Acceso a recurso ajeno devuelve 404 genérico
- **WHEN** un usuario A autenticado intenta consultar o modificar un recurso cuyo propietario es el usuario B
- **THEN** el sistema responde con código 404 genérico `RESOURCE_NOT_FOUND` idéntico al que devolvería si el identificador no existiera en la base de datos

### Requirement: Administración de cuentas de usuario por Administrador con revocación de sesiones
El sistema SHALL proporcionar al usuario con rol `ADMIN` endpoints para consultar la lista de usuarios y modificar su estado operativo. Mediante `GET /api/v1/admin/users`, el administrador SHALL obtener un listado paginado con los atributos públicos y estado (`ACTIVE` o `BLOCKED`) de los usuarios. Mediante `PATCH /api/v1/admin/users/{id}/block`, el administrador SHALL poder bloquear una cuenta; ante esta acción, el sistema SHALL actualizar el estado del usuario a `BLOCKED`, revocar inmediatamente todas las refresh sessions activas asociadas a dicho usuario en PostgreSQL (`revoked_at = NOW()`), e insertar el evento en `audit_logs`. Mediante `PATCH /api/v1/admin/users/{id}/activate`, el administrador SHALL poder reactivar una cuenta previamente bloqueada registrando la acción en `audit_logs`.

#### Scenario: Administrador consulta lista de usuarios
- **WHEN** un administrador autenticado realiza un GET a `/api/v1/admin/users`
- **THEN** el sistema devuelve código 200 con la lista paginada de usuarios incluyendo identificador, email, nombre visible, rol, estado y fecha de registro

#### Scenario: Administrador bloquea cuenta y revoca sesiones en PostgreSQL
- **WHEN** un administrador envía un PATCH a `/api/v1/admin/users/{id}/block` para un usuario existente
- **THEN** el sistema actualiza el estado del usuario a `BLOCKED`, revoca atómicamente todas sus refresh sessions en PostgreSQL, registra en `audit_logs` y responde con código 200

#### Scenario: Usuario con rol USER intenta bloquear cuenta
- **WHEN** un usuario con rol `USER` envía un PATCH a `/api/v1/admin/users/{id}/block`
- **THEN** el sistema rechaza la solicitud con código 403

### Requirement: Provisión controlada del primer administrador
El sistema SHALL impedir la creación de usuarios con rol `ADMIN` a través de los formularios o endpoints de registro público. La creación del usuario administrador inicial SHALL realizarse exclusivamente mediante un procedimiento administrativo controlado fuera de la API pública (script CLI de inicialización), verificando credenciales seguras y registrando la acción en el log de auditoría.

#### Scenario: Creación de administrador por comando seguro CLI
- **WHEN** un operador ejecuta el comando CLI de provisión administrativa con las credenciales y correo definidos en las variables de entorno seguras
- **THEN** el sistema crea la cuenta con rol `ADMIN`, contraseña hasheada con Argon2id y registra la provisión en el registro de auditoría

### Requirement: Registro inmutable de auditoría de seguridad
El sistema SHALL tratar la tabla de auditoría `audit_logs` como un registro inmutable de solo inserción (INSERT), prohibiendo operaciones de modificación (UPDATE) o eliminación (DELETE) a través de la aplicación. Los eventos auditados SHALL incluir normativamente: `USER_REGISTERED`, `LOGIN_SUCCESS`, `LOGIN_FAILED`, `LOGOUT`, `PASSWORD_CHANGED`, `PASSWORD_RECOVERY_REQUESTED`, `PASSWORD_RECOVERY_CONFIRMED`, `REFRESH_TOKEN_REUSE_DETECTED`, `USER_BLOCKED`, `USER_ACTIVATED` y `INITIAL_ADMIN_PROVISIONED`. Cada fila SHALL registrar `actor_id` (o nulo en caso de acciones anónimas), `action`, `target_id`, `correlation_id` y marca de tiempo UTC. El sistema SHALL asegurar que ningún registro contenga contraseñas en texto claro, hashes de contraseñas ni tokens sensibles.

#### Scenario: Registro inmutable de auditoría tras evento de seguridad
- **WHEN** se produce una mutación de seguridad (ej. cambio de contraseña, bloqueo de cuenta o reuso de token de refresco)
- **THEN** el sistema inserta una fila en `audit_logs` con acción, actor, objetivo, correlación y fecha UTC, sin permitir alteraciones posteriores
