# Design

## Context

El Incremento 0 estableció el andamiaje técnico inicial (Docker Compose, PostgreSQL por servicio, Nginx y CI). `services/identity` dispone de base de datos dedicada y migración base vacía (`identity_0001`), pero carece de modelos de dominio, hashing de contraseñas, emisión de tokens y control de sesiones. Los contratos OpenAPI (`identity.openapi.json`) tienen 7 operaciones de negocio en estado `contract-only` y 3 operaciones diferidas en `deferred-operations.json` que deben formalizarse.
Ver motivación y alcance en `proposal.md`, especificaciones en `specs/**/*.md` y directrices normativas en [ADR-0004](file:///home/ronaldo/Documentos/agrodiagnostico_V1/docs/adr/0004-seguridad-identidad-y-autorizacion.md).

## Goals / Non-Goals

**Goals:**
- Implementar almacenamiento seguro de contraseñas con Argon2id (`m=65536, t=3, p=4`).
- Implementar autenticación basada en JWT asimétrico exclusivamente con **Ed25519** (algoritmo **EdDSA**) para access tokens de corta duración (15 min), con clave privada protegida en Identity y clave pública en servicios consumidores.
- Diseñar una arquitectura completamente stateless para el access token, soportando escalado horizontal en múltiples instancias (`identity-1`, `identity-2`, `identity-N`) detrás de Nginx sin afinidad de sesión (*sticky sessions*).
- Prohibir estrictamente el almacenamiento de sesiones, revocaciones o estado de autenticación en memoria del proceso, diccionarios globales o almacenamiento local por instancia.
- Utilizar PostgreSQL como la única fuente compartida de verdad para las sesiones de refresco (`refresh_sessions`).
- Almacenar los refresh tokens y tokens de recuperación exclusivamente como hashes criptográficos `SHA-256`, nunca en texto plano.
- Implementar rotación atómica de refresh tokens mediante transacción y bloqueo pesimista de fila (`SELECT ... FOR UPDATE`), garantizando detección de reuso con revocación inmediata de toda la familia (`family_id`).
- Proteger las operaciones de sesión contra CSRF mediante la combinación de cookie `__Secure-agro_refresh` (`HttpOnly; Secure; SameSite=Lax; Path=/api/v1/auth`), token `csrf_token` devuelto en el cuerpo, validación del encabezado `X-CSRF-Token` y verificación de `Origin`.
- Revocar atómicamente todas las refresh sessions activas del usuario ante cambio de contraseña, restablecimiento exitoso o bloqueo administrativo de cuenta.
- Implementar la tabla `audit_logs` como registro inmutable (solo INSERT, sin UPDATE ni DELETE) para todos los eventos críticos de seguridad.
- Implementar el comando CLI de provisión segura para la cuenta `ADMIN` inicial.
- Proveer suites de pruebas unitarias y de integración que verifiquen el funcionamiento multi-instancia y concurrente sobre PostgreSQL compartido.

**Non-Goals:**
- Pantallas o componentes de interfaz de usuario en React (reservado para el Incremento 5).
- Integración con proveedores externos de correo en la nube (se emplea un adaptador controlado local/mock desacoplado).
- Lógica de diagnóstico, carga de imágenes o procesamiento con modelos de IA (reservados para Incrementos 2, 3 y 4).

## Decisions

### 1. Esquema Criptográfico de Access Tokens: Ed25519 (EdDSA) Definitivo
- **Decisión**: Se fija exclusivamente **Ed25519** (algoritmo `EdDSA`). Se descarta definitivamente RS256 y esquemas simétricos HS256.
- **Razón**: Ed25519 ofrece claves de 32 bytes y firmas de 64 bytes altamente compactas, excelente velocidad de firma y verificación, e inmunidad natural contra ataques de canal lateral. Solo `identity` almacena la clave privada (`/run/secrets/jwt_private_key.pem`, nunca en Git); los demás servicios solo requieren la clave pública (`/run/secrets/jwt_public_key.pem`).
- **Claims normativos mínimos**:
  - `sub`: UUID del usuario.
  - `role`: `USER` o `ADMIN`.
  - `iss`: `agrodiagnostico-identity`.
  - `aud`: `agrodiagnostico-api`.
  - `exp`: Timestamp Unix UTC (15 minutos / 900 s).
  - `iat`: Timestamp Unix UTC.
  - `jti`: UUID único por token.

### 2. Arquitectura Stateless y Compatibilidad Multi-instancia sin Sticky Sessions
- **Decisión**: El servicio Identity es completamente stateless respecto a los access tokens. Ninguna instancia (`identity-1`, `identity-2`, `identity-N`) retiene estado en memoria local, variables globales ni cachés en proceso.
- **Razón**: Permite balancear peticiones HTTP desde Nginx mediante round-robin o least-connections sin necesidad de afinidad de sesión (*sticky sessions*). Una petición de login puede ser atendida por `identity-1`, un refresh subsiguiente por `identity-2` y un logout por `identity-3`, operando sin discrepancias gracias al estado compartido en PostgreSQL.

### 3. Modelo y Persistencia de Refresh Sessions en PostgreSQL
- **Decisión**: La tabla `refresh_sessions` en PostgreSQL es la única fuente de verdad compartida. El refresh token en plano se envía al cliente en la cookie `__Secure-agro_refresh`; en PostgreSQL se almacena exclusivamente `SHA-256(refresh_token)`.
- **Estructura de `refresh_sessions`**:
  - `id`: UUID (PK).
  - `user_id`: UUID (FK a `users.id` con `ON DELETE CASCADE`).
  - `family_id`: UUID (linaje de rotación).
  - `token_hash`: VARCHAR(64) (UNIQUE sobre hash SHA-256).
  - `created_at`: TIMESTAMP WITH TIME ZONE (UTC).
  - `expires_at`: TIMESTAMP WITH TIME ZONE (UTC, 7 días).
  - `rotated_at`: TIMESTAMP WITH TIME ZONE (UTC nullable).
  - `revoked_at`: TIMESTAMP WITH TIME ZONE (UTC nullable).
  - `replaced_by_session_id`: UUID (nullable, FK auto-referencial hacia `refresh_sessions.id`).
  - `created_ip`: VARCHAR(45) (nullable).
  - `user_agent`: TEXT (nullable).
- **Índices**: `token_hash` (único), `user_id`, `family_id`, `expires_at`.

### 4. Rotación Atómica con Bloqueo Pesimista y Detección de Reuso
- **Decisión**: `POST /api/v1/auth/refresh` ejecuta una transacción atómica con `SELECT ... FOR UPDATE` sobre la fila de la sesión identificada por `token_hash`.
  - Si la sesión es válida (`rotated_at IS NULL`, `revoked_at IS NULL`, no expirada):
    - Marca `rotated_at = NOW()`.
    - Inserta nueva fila en `refresh_sessions` con el mismo `family_id`.
    - Actualiza `replaced_by_session_id`.
    - Commit de la transacción.
    - Emite nuevo access token y nueva cookie.
  - Si la sesión ya fue rotada (`rotated_at IS NOT NULL`):
    - Condición: **REUSE DETECTED**.
    - Revoca inmediatamente todas las sesiones de la familia: `UPDATE refresh_sessions SET revoked_at = NOW() WHERE family_id = :family_id`.
    - Inserta evento `REFRESH_TOKEN_REUSE_DETECTED` en `audit_logs`.
    - Responde 401 obligando a reiniciar sesión.
- **Razón**: Previene condiciones de carrera si dos peticiones con el mismo token llegan en paralelo a distintas instancias, garantizando aislamiento Serializable/Read Committed con bloqueo a nivel de fila.

### 5. Cookies Seguras y Validación CSRF / Origin
- **Decisión**:
  - Cookie: `__Secure-agro_refresh` con `HttpOnly`, `SameSite=Lax`, `Path=/api/v1/auth`. En desarrollo HTTP se configura `COOKIE_SECURE=false`.
  - CSRF: Toda sesión devuelve un `csrf_token` en JSON. En `POST /api/v1/auth/refresh` y `POST /api/v1/auth/logout`, se exige el encabezado `X-CSRF-Token` con valor idéntico al token ligado a la sesión.
  - Origin: Verificación estricta contra `ALLOWED_ORIGINS` para mitigar ataques cross-site.

### 6. Recuperación de Contraseña con Tokens Hasheados (SHA-256)
- **Decisión**:
  - `PasswordRecoveryToken` almacena únicamente `SHA-256(token)` con `id`, `user_id`, `token_hash`, `created_at`, `expires_at` (30 min) y `used_at`.
  - `POST /api/v1/auth/password-recovery` responde siempre 202 genérico con mensaje estándar.
  - `POST /api/v1/auth/password-recovery/confirm` valida el hash, actualiza contraseña con Argon2id, marca `used_at = NOW()`, revoca todas las sesiones activas del usuario en PostgreSQL y audita la acción.

### 7. Revocación de Sesiones ante Cambio de Contraseña y Bloqueo de Cuentas
- **Decisión**:
  - Cambio voluntario (`PUT /api/v1/profile/password`): actualiza contraseña con Argon2id y revoca todas las refresh sessions del usuario en PostgreSQL.
  - Bloqueo administrativo (`PATCH /api/v1/admin/users/{id}/block`): cambia estado a `BLOCKED`, revoca todas las refresh sessions en PostgreSQL y audita.
  - Ventana de access token: Al ser stateless, el access token expira naturalmente en su ventana corta (máximo 15 minutos). Toda renovación posterior es rechazada de inmediato al consultar la base de datos compartida.

### 8. Registro Inmutable de Auditoría (`audit_logs`)
- **Decisión**: La tabla `audit_logs` en PostgreSQL es de solo inserción (*append-only*).
  - Campos: `id UUID`, `actor_id UUID nullable`, `action VARCHAR(80)`, `target_id UUID nullable`, `correlation_id UUID`, `details JSONB`, `created_at UTC`.
  - Eventos mínimos: `USER_REGISTERED`, `LOGIN_SUCCESS`, `LOGIN_FAILED`, `LOGOUT`, `PASSWORD_CHANGED`, `PASSWORD_RECOVERY_REQUESTED`, `PASSWORD_RECOVERY_CONFIRMED`, `REFRESH_TOKEN_REUSE_DETECTED`, `USER_BLOCKED`, `USER_ACTIVATED`, `INITIAL_ADMIN_PROVISIONED`.

## Risks / Trade-offs

- **[Riesgo] Concurrencia en refresh distribuido** → *Mitigación*: `SELECT ... FOR UPDATE` a nivel de fila en PostgreSQL compartido garantiza atomicidad sin bloqueos a nivel de tabla ni carreras entre instancias.
- **[Riesgo] Exposición de clave privada Ed25519** → *Mitigación*: Exclusiva de `identity` mediante Docker secrets (`/run/secrets/jwt_private_key.pem`), con permisos de lectura restringidos y excluida de Git.
- **[Riesgo] Ventana de vida de 15 min tras bloqueo** → *Mitigación*: TTL corto de 15 minutos para tokens de acceso; revocación inmediata del refresh token impide la prolongación de la sesión. Operaciones sensibles de perfil validan estado en PostgreSQL.

## Migration Plan

1. **ADR y Contratos**: Formalizado en `docs/adr/0004-seguridad-identidad-y-autorizacion.md` y actualización de contratos OpenAPI en `contracts/`.
2. **Migración PostgreSQL**: Crear migración `identity_0002_domain.py` con las 4 tablas e índices requeridos.
3. **Criptografía y Dominio**: Implementar hashing Argon2id, JWT Ed25519 (EdDSA), adaptador de correo y modelos.
4. **Endpoints y Atomicidad**: Implementar endpoints HTTP stateless con rotación atómica y protección CSRF.
5. **Pruebas Multi-instancia**: Implementar tests que validen el flujo cruzado entre instancias lógicas (login en A, refresh en B, concurrencia y detección de reuso).
