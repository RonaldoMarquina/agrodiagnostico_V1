# Proposal

## Why

El Incremento 0 dejó la base técnica integrada (contenedores, bases de datos aisladas, contratos OpenAPI iniciales y CI remota), pero sin funcionalidad de negocio ni mecanismos reales de autenticación o persistencia de usuarios.
El Incremento 1 implementa la gestión integral de identidad y control de acceso: registro seguro de usuarios, autenticación mediante Argon2id y JWT asimétrico Ed25519 (EdDSA), arquitectura stateless para tokens de acceso con soporte multi-instancia horizontal detrás de balanceador Nginx (sin sticky sessions), gestión de sesiones compartidas en PostgreSQL con refresh tokens rotativos atómicos, detección de reuso por `family_id` y protección CSRF, administración de perfil, cambio y recuperación de contraseña con tokens hasheados de un solo uso y revocación de sesiones, autorización basada en roles (USER vs ADMIN), aislamiento de recursos (404 genérico para recursos ajenos) y supervisión administrativa de cuentas con revocación inmediata y registro inmutable de auditoría.

## What Changes

- **ADR-0004 de Seguridad Criptográfica y Arquitectura Multi-instancia**: Formalización de decisiones:
  - Firma asimétrica de access tokens exclusivamente con **Ed25519** (algoritmo JWT **EdDSA**) con clave privada en Identity y clave pública en servicios consumidores; clave privada nunca en repositorio.
  - Claims mínimos normativos: `sub`, `role`, `iss`, `aud`, `exp` (15 min), `iat`, `jti`.
  - Arquitectura stateless respecto al access token y compatible con balanceador Nginx sobre N instancias de Identity (`identity-1`, `identity-2`, etc.) sin afinidad de sesión ni estado en memoria.
  - Sesiones de refresh compartidas en PostgreSQL con `SHA-256(refresh_token)`, rotación atómica mediante bloqueo pesimista de fila (`SELECT ... FOR UPDATE`), linaje por `family_id` y revocación total de familia ante detección de reuso.
  - Cookie de sesión `__Secure-agro_refresh` (`HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/api/v1/auth`) y validación de `X-CSRF-Token` y `Origin`.
  - Tokens de recuperación de contraseña almacenados exclusivamente como `SHA-256(token)` con respuesta 202 genérica anti-enumeración.
  - Revocación inmediata de refresh sessions tras cambio de contraseña, restablecimiento y bloqueo de cuenta.
  - Tabla de auditoría `audit_logs` inmutable (solo INSERT).
- **Modelos y Persistencia en `services/identity`**: Migraciones de Alembic y tablas relacionales en PostgreSQL para usuarios (`users`), sesiones (`refresh_sessions` con índices en `token_hash`, `user_id`, `family_id` y `expires_at`), tokens de recuperación (`password_recovery_tokens`) y auditoría inmutable (`audit_logs`).
- **Autenticación y Ciclo de Sesiones**: Endpoints implementados para `POST /api/v1/auth/register` (creación exclusiva de `USER`, 409 genérico anti-enumeración `ACCOUNT_UNAVAILABLE`), `POST /api/v1/auth/login` (verificación Argon2id, validación de Origin, emisión de access token JWT y cookie `__Secure-agro_refresh` junto a `csrf_token`), `POST /api/v1/auth/refresh` (rotación atómica en PostgreSQL con detección de reuso y revocación familiar) y `POST /api/v1/auth/logout` (revocación de sesión en base de datos y eliminación de cookie).
- **Gestión de Perfil y Contraseña**: Endpoints para `GET /api/v1/profile` (consulta propia), `PATCH /api/v1/profile` (actualización exclusiva de `display_name`), `PUT /api/v1/profile/password` (cambio autenticado con verificación previa y revocación de sesiones activas) y flujo de recuperación `POST /api/v1/auth/password-recovery` (respuesta 202 genérica anti-enumeración, token temporal hasheado y adaptador de correo controlado) con confirmación `POST /api/v1/auth/password-recovery/confirm` (revocación de sesiones tras restablecimiento).
- **Autorización, Roles y Administración de Cuentas**:
  - Middleware/utilidad de verificación criptográfica de access tokens para proteger recursos propios.
  - Regla de aislamiento estricto: cualquier acceso a recursos inexistentes o ajenos retorna `404 Not Found` genérico idéntico para evitar enumeración.
  - Endpoints de administración con rol `ADMIN`: `GET /api/v1/admin/users`, `PATCH /api/v1/admin/users/{id}/block` (invalida inmediatamente todas las sesiones activas del usuario bloqueado) y `PATCH /api/v1/admin/users/{id}/activate`.
  - Provisión controlada del primer administrador vía script/comando administrativo CLI, prohibiendo registro público como ADMIN.
  - Registro de auditoría inmutable (`audit_logs`) para eventos de autenticación, cambios de credenciales y mutaciones administrativas, sin registrar contraseñas ni tokens en texto claro.
- **Actualización de Contratos**: Formalizar contratos OpenAPI para cambio de contraseña, confirmación de reset y administración de usuarios, sincronizando `deferred-operations.json`, `operations.json` y `security-matrix.json`.
- **Configuración de Proxy Nginx**: Enrutamiento balanceable sin sticky sessions de `/api/v1/auth/`, `/api/v1/profile` y `/api/v1/admin/` hacia el servicio `identity`.

## Capabilities

### New Capabilities
- `user-authentication-and-sessions`: Registro público de cuentas USER, autenticación con Argon2id, emisión de JWT Ed25519 y cookies seguras de refresh token en PostgreSQL con rotación atómica, detección de reuso familiar y cierre de sesión multi-instancia.
- `user-profile-and-password-management`: Consulta y actualización de perfil de usuario, cambio autenticado de contraseña y flujo completo de recuperación con tokens hasheados de un solo uso, revocación de sesiones activas y notificación.
- `role-authorization-and-user-administration`: Verificación de roles (USER vs ADMIN), validación de tokens de acceso inter-servicio, aislamiento de recursos con 404 genérico, administración de estado de usuarios (bloqueo/activación) con revocación inmediata y auditoría inmutable de eventos de seguridad.

### Modified Capabilities
*(Ninguna capacidad existente modifica sus requisitos base).*

## Impact

- **Servicios afectados**:
  - `services/identity`: Implementación completa de dominio, aplicación, persistencia compartida en PostgreSQL (tablas y migraciones Alembic), seguridad criptográfica (Argon2id, JWT Ed25519/EdDSA, cookies, CSRF) y rutas HTTP en FastAPI stateless.
  - `infra/nginx`: Configuración de enrutamiento y balanceo sin sticky sessions para las rutas públicas de identity.
  - `contracts/`: Actualización de contratos OpenAPI, matrices de seguridad e inventario de operaciones.
  - `docs/`: Nuevo `docs/adr/0004-seguridad-identidad-y-autorizacion.md` y actualización de `SECURITY.md`, `API_CONTRACTS.md` e `Incrementos.md`.
- **Dependencias Python**: `argon2-cffi`, `cryptography` y `pyjwt` en `services/identity/pyproject.toml`.
