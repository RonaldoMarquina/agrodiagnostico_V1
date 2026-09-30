# Tasks

## 1. Decisiones Arquitectónicas, ADR y Contratos OpenAPI de Identidad

- [x] 1.1 Redactar y verificar `docs/adr/0004-seguridad-identidad-y-autorizacion.md` formalizando Ed25519 (EdDSA) definitivo, arquitectura stateless multi-instancia sin sticky sessions, persistencia compartida en PostgreSQL de RefreshSession, tokens hasheados con SHA-256, rotación atómica y auditoría inmutable, asegurando coherencia con ADR-0002.
- [x] 1.2 Formalizar en `contracts/openapi/identity.openapi.json` los contratos para cambio de contraseña (`PUT /api/v1/profile/password`), confirmación de recuperación (`POST /api/v1/auth/password-recovery/confirm`) y administración de cuentas (`GET /api/v1/admin/users`, `PATCH /api/v1/admin/users/{id}/block`, `PATCH /api/v1/admin/users/{id}/activate`), actualizando `deferred-operations.json`, `operations.json` y `security-matrix.json`.

## 2. Persistencia, Modelos Relacionales y Migraciones de Identity

- [x] 2.1 Agregar dependencias de seguridad criptográfica (`argon2-cffi`, `cryptography` y `pyjwt`) a `services/identity/pyproject.toml` y regenerar `services/identity/uv.lock` verificando la instalación limpia.
- [x] 2.2 Definir los modelos SQLAlchemy en `services/identity/app/domain/models.py` (`User`, `RefreshSession` con todos los campos e índices obligatorios: `token_hash`, `user_id`, `family_id`, `expires_at`, `PasswordRecoveryToken` y `AuditLog`), verificando consistencia de tipos.
- [x] 2.3 Crear la migración Alembic `0002_identity_domain.py` en `services/identity/migrations/versions/` y verificar su aplicación correcta contra PostgreSQL compartido mediante `python -m app.migrate up`.

## 3. Criptografía, Utilidades de Tokens y Adaptador de Correo

- [x] 3.1 Implementar el módulo de hashing con Argon2id y funciones SHA-256 para tokens en `services/identity/app/infrastructure/security.py`, y verificar con pruebas unitarias de hashing y verificación.
- [x] 3.2 Implementar el gestor de tokens JWT asimétricos con Ed25519 (algoritmo EdDSA) y claims normativos (`sub`, `role`, `iss`, `aud`, `exp`, `iat`, `jti`) en `services/identity/app/infrastructure/tokens.py`, y verificar con pruebas unitarias de emisión y verificación con clave pública.
- [x] 3.3 Implementar el adaptador de notificaciones/correo en `services/identity/app/infrastructure/email.py` con interfaz desacoplada y adaptador local/mock para recuperación de contraseñas, y verificar su funcionamiento con pruebas unitarias.

## 4. Autenticación, Sesiones y Registro de Usuarios

- [x] 4.1 Implementar el endpoint `POST /api/v1/auth/register` asignando rol USER por defecto, rechazando campos restringidos (400) y respondiendo conflicto genérico 409 `ACCOUNT_UNAVAILABLE` ante duplicados, y verificar mediante tests unitarios y de integración.
- [x] 4.2 Implementar el endpoint `POST /api/v1/auth/login` con validación de Origin, emisión de access token JWT Ed25519 (15 min), cookie `__Secure-agro_refresh` persistida en PostgreSQL como `SHA-256(refresh_token)` y `csrf_token`, y verificar con tests para credenciales correctas, erróneas y cuentas bloqueadas.
- [x] 4.3 Implementar el endpoint `POST /api/v1/auth/refresh` con rotación atómica en PostgreSQL (`SELECT ... FOR UPDATE`), verificación de `X-CSRF-Token` y detección de reuso con revocación de toda la familia (`family_id`), y verificar con tests de rotación válida y detección de reuso malicioso.
- [x] 4.4 Implementar el endpoint `POST /api/v1/auth/logout` con revocación de sesión en PostgreSQL compartido y expiración de cookie (`Max-Age=0`), y verificar con tests de logout exitoso y rechazo sin sesión.

## 5. Perfil de Usuario, Cambio y Recuperación de Contraseña

- [x] 5.1 Implementar `GET /api/v1/profile` y `PATCH /api/v1/profile` (actualización exclusiva de `display_name`) protegidos con Bearer token, y verificar con tests de consulta propia, actualización parcial y rechazo de campos no modificables.
- [x] 5.2 Implementar `PUT /api/v1/profile/password` autenticado con verificación de contraseña actual, actualización de hash Argon2id y revocación obligatoria de todas las refresh sessions del usuario en PostgreSQL, y verificar con tests de cambio y revocación.
- [x] 5.3 Implementar `POST /api/v1/auth/password-recovery` (respuesta 202 genérica anti-enumeración y token hasheado en PostgreSQL) y `POST /api/v1/auth/password-recovery/confirm` (validación de token hasheado, actualización de contraseña, revocación de sesiones en PostgreSQL y auditoría), y verificar el flujo completo de recuperación.

## 6. Roles, Autorización, Administración de Cuentas y Auditoría

- [x] 6.1 Implementar la dependencia de autorización (`get_current_user`, `require_role`) y la política de respuesta 404 genérica ante recursos ajenos o inexistentes, y verificar con pruebas de aislamiento A/B y control de acceso RBAC.
- [x] 6.2 Implementar endpoints administrativos `GET /api/v1/admin/users`, `PATCH /api/v1/admin/users/{id}/block` (cambio de estado a BLOCKED y revocación inmediata de todas las refresh sessions activas en PostgreSQL) y `PATCH /api/v1/admin/users/{id}/activate`, y verificar acceso exclusivo ADMIN y denegación USER.
- [x] 6.3 Implementar el comando CLI de aprovisionamiento seguro de cuenta ADMIN inicial (`services/identity/app/cli.py`) y el registro inmutable de eventos de seguridad en `audit_logs` (solo INSERT), y verificar la creación del admin y los registros de auditoría generados.

## 7. Integración en Nginx, Pruebas Multi-instancia y Verificación

- [x] 7.1 Configurar Nginx para balanceo y proxy de `/api/v1/auth/`, `/api/v1/profile` y `/api/v1/admin/` hacia las instancias de Identity sin requerir sticky sessions, y verificar el enrutamiento y encabezados mediante pruebas de integración local.
- [x] 7.2 Implementar pruebas de integración multi-instancia y de concurrencia sobre PostgreSQL compartido: login en instancia A y refresh en B; logout en instancia C; concurrencia de dos refresh simultáneos con el mismo token; detección de reuso y revocación total de `family_id`; y revocación de sesiones tras cambio de contraseña, restablecimiento y bloqueo administrativo.
- [x] 7.3 Promocionar operaciones en contratos OpenAPI, ejecutar la suite completa de pruebas de backend, migraciones y análisis estático de `services/identity`, y registrar la evidencia en `docs/evidence/INCREMENTO-1-AUDIT.md`.
