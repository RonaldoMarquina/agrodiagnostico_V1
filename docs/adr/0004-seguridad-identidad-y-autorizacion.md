# ADR-0004 — Seguridad criptográfica, identidad y autorización multi-instancia

Fecha: 2026-09-30. Estado: Decisión adoptada para el Incremento 1.
Contexto: Cumple la reserva explícita de [ADR-0002](0002-interfaces-y-eventos-v1.md) (líneas 30 y 101), que postergó la fijación del algoritmo de firma, tiempos de expiración, estructura de tokens y política de cookies para antes del Incremento 1. Resuelve las garantías funcionales de RF-01, RF-02, RF-03, RF-04, RF-21 y RF-25 según la [reconciliación V1](../reference/RECONCILIACION-V1.md).

---

## 1. Contexto y Objetivos

El servicio `identity` es el responsable de autenticar usuarios, gestionar sesiones, emitir credenciales de acceso y autorizar operaciones administrativas. Para soportar alta disponibilidad y escalabilidad horizontal, el servicio debe ser desplegable en múltiples instancias (`identity-1`, `identity-2`, `identity-N`) detrás de un balanceador Nginx sin requerir afinidad de sesión (*sticky sessions*).

Queda explícitamente prohibido almacenar sesiones, tokens de refresco, revocaciones o estado de autenticación en memoria del proceso, diccionarios globales o almacenamiento local por instancia.

---

## 2. Decisiones Arquitectónicas

### 2.1 JWT Asimétrico: Ed25519 (Algoritmo EdDSA)

Se adopta exclusivamente **Ed25519** (algoritmo JWT `EdDSA`). Se descarta definitivamente el uso de RS256 o esquemas simétricos HS256.

- **Firma**: El servicio `identity` firma los tokens de acceso (`access_token`) con su clave privada asimétrica Ed25519. La clave privada se inyecta exclusivamente mediante secretos del entorno (`/run/secrets/jwt_private_key.pem`) y **NUNCA** se almacena en el repositorio Git.
- **Verificación**: Todas las demás instancias de `identity` y los servicios consumidores (`diagnosis`, `notification`) verifican la firma y autenticidad del token localmente utilizando la clave pública Ed25519 (`/run/secrets/jwt_public_key.pem`). Esto permite una verificación completamente *stateless*, rápida y sin llamadas síncronas de red entre servicios.
- **Claims mínimos normativos**:
  - `sub`: Identificador UUID del usuario (cadena UUID v4).
  - `role`: Rol del usuario (`USER` o `ADMIN`).
  - `iss`: Emisor normativo (`agrodiagnostico-identity`).
  - `aud`: Audiencia normativa (`agrodiagnostico-api`).
  - `exp`: Timestamp Unix UTC de expiración. Tiempo de vida corto: **15 minutos** (900 segundos).
  - `iat`: Timestamp Unix UTC de emisión.
  - `jti`: Identificador UUID único del token para trazabilidad.

### 2.2 Arquitectura Stateless y Compatibilidad Multi-instancia

```
                       Nginx / Balanceador
                                |
             +------------------+------------------+
             |                                     |
             v                                     v
       identity-1                            identity-2
             \                                     /
              \                                   /
               v                                 v
             PostgreSQL compartido (base "identity")
```

- Las instancias `identity-1`, `identity-2`, `identity-N` comparten:
  1. La misma base de datos PostgreSQL `identity`.
  2. La misma configuración criptográfica (par de claves Ed25519, `iss`, `aud`).
- Cualquier solicitud puede llegar a cualquier instancia de forma indistinta:
  - `LOGIN` puede procesarse en `identity-1`.
  - `REFRESH` subsiguiente puede procesarse en `identity-2`.
  - `LOGOUT` puede procesarse en `identity-3`.
- No se permite afinidad de sesión (*sticky sessions*) en Nginx.

### 2.3 Sesiones de Refresco (Refresh Sessions) en PostgreSQL

Las sesiones de refresco se gestionan de forma compartida y persistente en la tabla `refresh_sessions` de PostgreSQL:

- **Hash seguro**: El refresh token en texto plano nunca se guarda en la base de datos. El cliente recibe un token aleatorio criptográficamente seguro (32 bytes / 256 bits codificados en base64url) y en PostgreSQL se almacena exclusivamente su hash: `SHA-256(refresh_token)`.
- **Estructura de la tabla `refresh_sessions`**:
  - `id`: UUID (Clave primaria).
  - `user_id`: UUID (Clave foránea hacia `users.id` con `ON DELETE CASCADE`).
  - `family_id`: UUID (Identificador del linaje o familia de rotación de la sesión).
  - `token_hash`: VARCHAR(64) (Hash SHA-256 del refresh token, con índice único).
  - `created_at`: TIMESTAMP WITH TIME ZONE (UTC).
  - `expires_at`: TIMESTAMP WITH TIME ZONE (UTC, expiración máxima de 7 días).
  - `rotated_at`: TIMESTAMP WITH TIME ZONE (UTC, nullable).
  - `revoked_at`: TIMESTAMP WITH TIME ZONE (UTC, nullable).
  - `replaced_by_session_id`: UUID (nullable, apunta a la sesión sucesora dentro de la misma familia).
  - `created_ip`: VARCHAR(45) (nullable, IP cliente).
  - `user_agent`: TEXT (nullable, agente de usuario).
- **Índices obligatorios**:
  - `ix_refresh_sessions_token_hash` (UNIQUE sobre `token_hash`).
  - `ix_refresh_sessions_user_id` (sobre `user_id`).
  - `ix_refresh_sessions_family_id` (sobre `family_id`).
  - `ix_refresh_sessions_expires_at` (sobre `expires_at`).

### 2.4 Rotación Atómica con Detección de Reuso (Token Family)

Para evitar condiciones de carrera cuando dos solicitudes de refresh con el mismo token llegan en paralelo a distintas instancias de Identity (ej. `identity-1` y `identity-2`), la rotación se ejecuta en una transacción atómica con bloqueo pesimista de fila (`SELECT ... FOR UPDATE`):

```
                       Petición POST /api/v1/auth/refresh
                                       |
                                       v
                     BEGIN TRANSACTION (en PostgreSQL)
                                       |
                                       v
                 SELECT * FROM refresh_sessions WHERE token_hash = ?
                               FOR UPDATE
                                       |
            +--------------------------+--------------------------+
            |                                                     |
    Sesión válida                              Token ya rotado
    (rotated_at IS NULL y                      (rotated_at IS NOT NULL)
     revoked_at IS NULL y                      o revocada previamente
     now() < expires_at)                                  |
            |                                             v
            v                                      REUSE DETECTED
  1. rotated_at = now()                                   |
  2. replaced_by = nueva_sesion                           v
  3. INSERT nueva_sesion (mismo family_id)      1. UPDATE refresh_sessions
  4. COMMIT TRANSACTION                            SET revoked_at = now()
  5. Retornar nuevo JWT + Cookie                   WHERE family_id = ?
                                                2. INSERT audit_logs
                                                   (REFRESH_TOKEN_REUSE_DETECTED)
                                                3. COMMIT TRANSACTION
                                                4. Retornar 401 UNAUTHORIZED
```

Si un token que ya fue rotado vuelve a presentarse (indicio de interceptación o reproducción maliciosa), el sistema invalida de forma inmediata todas las sesiones activas asociadas a ese `family_id` y fuerza al usuario legítimo a volver a autenticarse.

### 2.5 Cookies Seguras y Protección CSRF

- **Cookie de refresco**: Se nombra estrictamente `__Secure-agro_refresh`. Se emite con los atributos:
  - `HttpOnly`: Impide acceso vía JavaScript (mitigación XSS).
  - `Secure`: Solo se transmite por HTTPS (en desarrollo local con HTTP plano, configurable vía `COOKIE_SECURE=false`).
  - `SameSite=Lax`: Previene envío en solicitudes entre sitios cruzados de terceros.
  - `Path=/api/v1/auth`: Restringe la cookie únicamente a las rutas de autenticación.
  - Sin atributo `Domain` (fijado al host emisor).
- **Protección CSRF**:
  - Toda sesión genera un `csrf_token` criptográficamente seguro (mínimo 32 caracteres) devuelto en el cuerpo JSON de login y refresh.
  - Los endpoints que leen la cookie de sesión (`POST /api/v1/auth/refresh` y `POST /api/v1/auth/logout`) exigen la presencia del encabezado `X-CSRF-Token`, el cual debe coincidir con el token CSRF esperado para la sesión.
  - Validación del encabezado `Origin`: Se rechaza con código 403 cualquier solicitud a estos endpoints cuyo `Origin` no pertenezca a la lista blanca de orígenes autorizados (`ALLOWED_ORIGINS`).

### 2.6 Recuperación de Contraseña con Tokens Hasheados

- **Hash del token temporal**: El token de recuperación nunca se almacena en plano.
  1. Se genera un token criptográfico seguro de un solo uso (`secrets.token_urlsafe(32)`).
  2. En la base de datos se guarda exclusivamente `SHA-256(token)`.
  3. El token en texto plano se envía al usuario mediante el adaptador de correo.
- **Estructura de la tabla `password_recovery_tokens`**:
  - `id`: UUID (PK).
  - `user_id`: UUID (FK a `users.id` con `ON DELETE CASCADE`).
  - `token_hash`: VARCHAR(64) (UNIQUE sobre el hash SHA-256).
  - `created_at`: TIMESTAMP WITH TIME ZONE (UTC).
  - `expires_at`: TIMESTAMP WITH TIME ZONE (UTC, vigencia máxima de 30 minutos).
  - `used_at`: TIMESTAMP WITH TIME ZONE (UTC, nullable).
- **Protección contra enumeración**: `POST /api/v1/auth/password-recovery` responde SIEMPRE con código 202 (`RecoveryAccepted`) y mensaje estándar idéntico tanto si el correo existe como si no existe.

### 2.7 Revocación de Sesiones en Cambio y Recuperación de Contraseña

Tanto el cambio voluntario de contraseña (`PUT /api/v1/profile/password`) como el restablecimiento mediante token de recuperación (`POST /api/v1/auth/password-recovery/confirm`) ejecutan una revocación inmediata de las sesiones de refresco del usuario en PostgreSQL:

```sql
UPDATE refresh_sessions
SET revoked_at = NOW()
WHERE user_id = :user_id AND revoked_at IS NULL;
```

Esta acción se audita en `audit_logs`.

### 2.8 Bloqueo de Cuentas por ADMIN y Manejo de la Ventana de Access Tokens

Cuando un administrador ejecuta `PATCH /api/v1/admin/users/{id}/block`:
1. Actualiza `users.status = 'BLOCKED'`.
2. Revoca atómicamente todas sus refresh sessions en PostgreSQL (`revoked_at = NOW()`).
3. Inserta registro en `audit_logs` con el `actor_id` del administrador.

**Manejo de la ventana de vida del Access Token**:
Dado que la arquitectura es *stateless* para los access tokens (evitando consultas a base de datos en cada petición para no introducir cuellos de botella ni estado en memoria), los access tokens ya emitidos conservan validez técnica hasta su expiración (máximo 15 minutos). Al expirar, cualquier intento de renovación mediante refresh token fallará inmediatamente al encontrar la sesión revocada o la cuenta bloqueada en PostgreSQL. Las operaciones de identidad (perfil, cambio de contraseña) consultan el estado del usuario en base de datos y rechazan de inmediato a usuarios con estado `BLOCKED`.

### 2.9 Registro Inmutable de Auditoría (`audit_logs`)

La tabla `audit_logs` opera como un registro de solo inserción (*append-only*). Las operaciones normales de `UPDATE` o `DELETE` están prohibidas en el código de la aplicación.

- **Estructura de la tabla `audit_logs`**:
  - `id`: UUID (PK).
  - `actor_id`: UUID (nullable, ID del usuario o administrador que realizó la acción).
  - `action`: VARCHAR(80) (identificador normativo del evento).
  - `target_id`: UUID (nullable, ID de la entidad afectada).
  - `correlation_id`: UUID (correlación de la solicitud HTTP).
  - `details`: JSONB (metadatos contextuales seguros; **prohibido incluir contraseñas, hashes ni tokens**).
  - `created_at`: TIMESTAMP WITH TIME ZONE (UTC).
- **Eventos normativos mínimos**:
  - `USER_REGISTERED`
  - `LOGIN_SUCCESS`
  - `LOGIN_FAILED`
  - `LOGOUT`
  - `PASSWORD_CHANGED`
  - `PASSWORD_RECOVERY_REQUESTED`
  - `PASSWORD_RECOVERY_CONFIRMED`
  - `REFRESH_TOKEN_REUSE_DETECTED`
  - `USER_BLOCKED`
  - `USER_ACTIVATED`
  - `INITIAL_ADMIN_PROVISIONED`

---

## 3. Consecuencias y Garantías

- **Escalabilidad horizontal completa**: Cualquier número de instancias de `identity` puede desplegarse tras Nginx; no se requieren sticky sessions.
- **Seguridad en capas**:
  - Contraseñas protegidas con Argon2id (`m=65536, t=3, p=4`).
  - Tokens de acceso Ed25519 con verificación descentralizada.
  - Refresh tokens y recovery tokens almacenados exclusivamente como hashes SHA-256.
  - Detección de reuso atómica y revocación de familias completas de sesiones.
- **Aislamiento de recursos**: Mantiene la política de 404 genérico en todos los servicios ante recursos ajenos o inexistentes.
