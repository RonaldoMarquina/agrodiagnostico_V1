# Auditoría de Verificación — Incremento 1: Identidad y Autorización

**Fecha:** 2026-09-30  
**Alcance:** Grupos 1 al 7 del Incremento 1 (Registro, sesiones, roles, perfil, cambio y recuperación de contraseña, autorización).  
**Estado de este informe:** evidencia histórica rectificada. La revisión posterior encontró fallos de seguridad/configuración y pruebas insuficientes para acreditar procesos independientes. El texto y las salidas siguientes describen lo registrado entonces, no certifican el estado actual. El cierre corregido se documenta en [INCREMENTO-1-CORRECCION.md](INCREMENTO-1-CORRECCION.md).

---

## 1. Resumen Ejecutivo y Decisiones Arquitectónicas Cumplidas

En cumplimiento estricto de las 12 decisiones arquitectónicas del usuario y los principios de `AGENTS.md` y `docs/adr/0004-seguridad-identidad-y-autorizacion.md`:

1. **JWT Asimétrico Ed25519 (EdDSA):**
   - Algoritmo de firma definitivo: `EdDSA` sobre curva `Ed25519`.
   - Servicio emisor (`identity`) firma access tokens de vida corta (15 min) con clave privada.
   - Las instancias o servicios consumidores verifican mediante clave pública sin requerir clave privada.
   - Claims normativos obligatorios: `sub`, `role`, `iss`, `aud`, `exp`, `iat`, `jti`.
   - Ninguna clave privada almacenada en el repositorio (generación/inyección vía variables de entorno).

2. **Arquitectura Stateless y Horizontalmente Escalable (Multi-instancia Nginx):**
   - Ningún estado de sesión o token en memoria local del proceso (prohibidos diccionarios globales o sticky sessions).
   - Nginx configurado como balanceador sin afinidad de sesión hacia el upstream `identity_backend`.
   - Cualquier petición (Login en instancia A, Refresh en B, Logout en C) es resuelta idénticamente gracias a la persistencia compartida en PostgreSQL.

3. **Refresh Sessions con Hash Criptográfico SHA-256:**
   - La tabla `refresh_sessions` en PostgreSQL nunca almacena tokens en texto claro.
   - Se genera token aleatorio criptográfico (`secrets.token_urlsafe(48)`) y se almacena `SHA-256(token)`.
   - Cookie `__Secure-agro_refresh` enviada con flags `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/api/v1/auth`.
   - Índices obligatorios creados para: `token_hash`, `user_id`, `family_id`, `expires_at`.

4. **Rotación Atómica y Detección de Reuso (Family ID):**
   - Endpoint `POST /api/v1/auth/refresh` implementa rotación atómica mediante `SELECT ... FOR UPDATE` a nivel de fila en PostgreSQL.
   - Detección de reuso malicioso: si una sesión ya rotada es presentada nuevamente, se revoca inmediatamente toda la familia de sesiones (`family_id`), se emite alerta en `audit_logs` y se fuerza nuevo login.
   - Verificado con prueba concurrente de condición de carrera con hilos simultáneos contra PostgreSQL.

5. **Protección CSRF y Validación de Origin:**
   - Operaciones autenticadas por cookie (`refresh`, `logout`) exigen coincidencia entre cookie `csrf_token` y encabezado `X-CSRF-Token`.
   - Validación estricta del encabezado `Origin` contra `ALLOWED_ORIGINS` configurados.

6. **Recuperación y Cambio de Contraseña Seguros:**
   - `POST /api/v1/auth/password-recovery` responde siempre con código genérico `202 Accepted` para prevenir enumeración de cuentas.
   - Token de recuperación almacenado exclusivamente como `SHA-256(token)` con expiración de 1 hora.
   - Tanto `PUT /api/v1/profile/password` como `POST /api/v1/auth/password-recovery/confirm` revocan inmediatamente todas las sesiones de refresh activas del usuario en PostgreSQL y registran el evento en `audit_logs`.

7. **RBAC, Bloqueo Administrativo y Aislamiento 404:**
   - Control de acceso por roles (`USER`, `ADMIN`).
   - Política de respuesta `404 Not Found` genérica ante intentos de acceso a recursos ajenos o inexistentes para evitar fuga de metadatos.
   - Endpoint `PATCH /api/v1/admin/users/{id}/block` cambia el estado a `BLOCKED`, revoca inmediatamente todas las sesiones de refresh activas y registra auditoría.

8. **Auditoría Inmutable (`audit_logs`):**
   - Registro de seguridad append-only (solo `INSERT`).
   - Bloqueo de `UPDATE` y `DELETE` en la tabla `audit_logs` protegido a nivel de base de datos mediante función y trigger PostgreSQL (`audit_logs_immutable`).
   - Eventos registrados: login exitoso/fallido, logout, rotación, detección de reuso, cambio/recuperación de contraseña, bloqueo/activación de usuario y aprovisionamiento inicial de ADMIN.

9. **Aprovisionamiento Inicial:**
   - Comando CLI seguro `python -m app.cli create-admin` para aprovisionar el primer administrador sin rutas HTTP no autenticadas ni credenciales hardcodeadas.

---

## 2. Inventario de Operaciones y Contratos OpenAPI Promocionados

Con la culminación del Incremento 1, las 12 operaciones de negocio de identidad fueron promovidas de `contract-only` a `implemented` en `contracts/openapi/identity.openapi.json` y `contracts/operations.json`:

| Operación | Método | Ruta | Estado | Autorización |
| --- | --- | --- | --- | --- |
| `identity_live` | GET | `/health/live` | `implemented` | Red interna |
| `identity_ready` | GET | `/health/ready` | `implemented` | Red interna |
| `identity_register` | POST | `/api/v1/auth/register` | `implemented` | Pública |
| `identity_login` | POST | `/api/v1/auth/login` | `implemented` | Pública |
| `identity_refresh` | POST | `/api/v1/auth/refresh` | `implemented` | Cookie + CSRF |
| `identity_logout` | POST | `/api/v1/auth/logout` | `implemented` | Cookie + CSRF |
| `identity_get_profile` | GET | `/api/v1/profile` | `implemented` | Bearer USER/ADMIN |
| `identity_patch_profile` | PATCH | `/api/v1/profile` | `implemented` | Bearer USER/ADMIN |
| `identity_start_recovery` | POST | `/api/v1/auth/password-recovery` | `implemented` | Pública |
| `identity_change_password` | PUT | `/api/v1/profile/password` | `implemented` | Bearer USER/ADMIN |
| `identity_confirm_recovery` | POST | `/api/v1/auth/password-recovery/confirm` | `implemented` | Pública |
| `identity_admin_list_users` | GET | `/api/v1/admin/users` | `implemented` | Bearer ADMIN |
| `identity_admin_block_user` | PATCH | `/api/v1/admin/users/{id}/block` | `implemented` | Bearer ADMIN |
| `identity_admin_activate_user` | PATCH | `/api/v1/admin/users/{id}/activate` | `implemented` | Bearer ADMIN |

**Total de operaciones en el sistema:** 32 (20 implementadas, 12 pendientes de incrementos futuros).

---

## 3. Evidencias de Ejecución

### 3.1 Validación de Contratos OpenAPI y Pruebas de Contrato

Comando:
```bash
.venv-contracts/bin/python scripts/validate_contracts.py
.venv-contracts/bin/python -m unittest discover -s tests/contracts -p 'test_*.py' -v
```

Salida:
```json
{"embedded_examples": 401, "openapi": 4, "operations": 32, "schemas": 5}
```
```text
test_broken_reference_fixture_rejected (test_contracts.Contracts.test_broken_reference_fixture_rejected) ... ok
test_cli_fails_for_broken_reference_in_actual_operation (test_contracts.Contracts.test_cli_fails_for_broken_reference_in_actual_operation) ... ok
test_deferred_inventory_has_owner_before_consumers (test_contracts.Contracts.test_deferred_inventory_has_owner_before_consumers) ... ok
test_event_routing_and_future_guarantees (test_contracts.Contracts.test_event_routing_and_future_guarantees) ... ok
test_health_status_per_service (test_contracts.Contracts.test_health_status_per_service) ... ok
test_package_and_all_embedded_examples (test_contracts.Contracts.test_package_and_all_embedded_examples) ... ok
test_pagination_bounds_and_invalid_cursors (test_contracts.Contracts.test_pagination_bounds_and_invalid_cursors) ... ok
test_positive_and_negative_fixtures (test_contracts.Contracts.test_positive_and_negative_fixtures) ... ok
test_reference_boundaries (test_contracts.Contracts.test_reference_boundaries) ... ok
test_security_matrix (test_contracts.Contracts.test_security_matrix) ... ok
test_upload_contract_and_idempotency_examples (test_contracts.Contracts.test_upload_contract_and_idempotency_examples) ... ok

----------------------------------------------------------------------
Ran 11 tests in 6.997s

OK
```

### 3.2 Migraciones de Base de Datos (Alembic)

Migración `0002_identity_domain.py` aplicada contra PostgreSQL:
```text
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 0001 -> 0002, identity domain models and security triggers
Current head: identity_0002
```

Tablas e Índices verificados en `agro_dev`:
- `users` (id, email UNIQUE, password_hash, display_name, role, status, created_at, updated_at).
- `refresh_sessions` (id, user_id, family_id, token_hash, created_at, expires_at, rotated_at, revoked_at, replaced_by_session_id, created_ip, user_agent).
  - Índices: `ix_refresh_sessions_token_hash`, `ix_refresh_sessions_user_id`, `ix_refresh_sessions_family_id`, `ix_refresh_sessions_expires_at`.
- `password_recovery_tokens` (id, user_id, token_hash, created_at, expires_at, used_at).
  - Índices: `ix_password_recovery_tokens_token_hash`, `ix_password_recovery_tokens_user_id`.
- `audit_logs` (id, event_type, actor_id, target_id, ip_address, user_agent, details, created_at).
  - Trigger: `trg_audit_logs_immutable` activo que lanza excepción en cualquier intento de UPDATE o DELETE.

### 3.3 Suite Completa de Pruebas de Identity (Docker + PostgreSQL Compartido)

Comando ejecutado contra el contenedor PostgreSQL:
```bash
docker compose run --rm -v ./services/identity/tests:/service/tests:ro \
  -e TEST_POSTGRES_URL="postgresql+psycopg://postgres:postgres@postgres:5432/agro_dev" \
  identity python -m unittest discover -s tests -v
```

Salida:
```text
test_admin_activate_user (test_admin_api.TestAdminApi.test_admin_activate_user) ... ok
test_admin_block_unknown_user_returns_404 (test_admin_api.TestAdminApi.test_admin_block_unknown_user_returns_404) ... ok
test_admin_block_user_and_revokes_sessions (test_admin_api.TestAdminApi.test_admin_block_user_and_revokes_sessions) ... ok
test_admin_list_users (test_admin_api.TestAdminApi.test_admin_list_users) ... ok
test_cli_initial_admin_creation (test_admin_api.TestAdminApi.test_cli_initial_admin_creation) ... Successfully provisioned initial administrator: superadmin@example.com
Notice: Administrator account already exists.
ok
test_rbac_denies_regular_user_access_to_admin_endpoints (test_admin_api.TestAdminApi.test_rbac_denies_regular_user_access_to_admin_endpoints) ... ok
test_login_flow_and_audit (test_auth_api.TestAuthApi.test_login_flow_and_audit) ... ok
test_login_origin_validation (test_auth_api.TestAuthApi.test_login_origin_validation) ... ok
test_logout_flow (test_auth_api.TestAuthApi.test_logout_flow) ... ok
test_refresh_rotation_and_reuse_detection (test_auth_api.TestAuthApi.test_refresh_rotation_and_reuse_detection) ... ok
test_register_duplicate_returns_409 (test_auth_api.TestAuthApi.test_register_duplicate_returns_409) ... ok
test_register_rejects_extra_fields (test_auth_api.TestAuthApi.test_register_rejects_extra_fields) ... ok
test_register_rejects_short_password (test_auth_api.TestAuthApi.test_register_rejects_short_password) ... ok
test_register_success (test_auth_api.TestAuthApi.test_register_success) ... ok
test_in_memory_sender (test_email.TestEmailSender.test_in_memory_sender) ... ok
test_logging_sender (test_email.TestEmailSender.test_logging_sender) ... ok
test_admin_block_revokes_sessions_across_instances (test_multi_instance.TestMultiInstance.test_admin_block_revokes_sessions_across_instances)
Login on identity-1. ... ok
test_concurrent_refresh_race_condition (test_multi_instance.TestMultiInstance.test_concurrent_refresh_race_condition)
Two simultaneous refresh calls with the exact same token arriving at identity-1 and identity-2. ... ok
test_multi_instance_login_refresh_logout_lifecycle (test_multi_instance.TestMultiInstance.test_multi_instance_login_refresh_logout_lifecycle)
Flow: ... ok
test_password_change_revokes_sessions_across_instances (test_multi_instance.TestMultiInstance.test_password_change_revokes_sessions_across_instances)
Login on identity-1. ... ok
test_password_recovery_revokes_sessions_across_instances (test_multi_instance.TestMultiInstance.test_password_recovery_revokes_sessions_across_instances)
Login on identity-1. ... ok
test_reuse_detection_and_full_family_revocation_across_instances (test_multi_instance.TestMultiInstance.test_reuse_detection_and_full_family_revocation_across_instances)
Token rotated at identity-1. ... ok
test_change_password_and_revokes_sessions (test_profile_api.TestProfileApi.test_change_password_and_revokes_sessions) ... ok
test_get_profile_requires_auth (test_profile_api.TestProfileApi.test_get_profile_requires_auth) ... ok
test_get_profile_success (test_profile_api.TestProfileApi.test_get_profile_success) ... ok
test_password_recovery_full_flow (test_profile_api.TestProfileApi.test_password_recovery_full_flow) ... ok
test_patch_profile_display_name (test_profile_api.TestProfileApi.test_patch_profile_display_name) ... ok
test_patch_profile_rejects_unmodifiable_fields (test_profile_api.TestProfileApi.test_patch_profile_rejects_unmodifiable_fields) ... ok
test_argon2id_hash_and_verify (test_security.TestSecurity.test_argon2id_hash_and_verify) ... ok
test_hash_password_rejects_invalid_policy (test_security.TestSecurity.test_hash_password_rejects_invalid_policy) ... ok
test_password_policy_bounds (test_security.TestSecurity.test_password_policy_bounds) ... ok
test_secure_token_and_sha256_hash (test_security.TestSecurity.test_secure_token_and_sha256_hash) ... ok
test_create_and_decode_token (test_tokens.TestTokens.test_create_and_decode_token) ... ok
test_public_key_only_verifier (test_tokens.TestTokens.test_public_key_only_verifier) ... ok
test_tampered_token_rejected (test_tokens.TestTokens.test_tampered_token_rejected) ... ok
test_token_expiration (test_tokens.TestTokens.test_token_expiration) ... ok
test_wrong_issuer_or_audience_rejected (test_tokens.TestTokens.test_wrong_issuer_or_audience_rejected) ... ok
test_wrong_key_rejected (test_tokens.TestTokens.test_wrong_key_rejected) ... ok

----------------------------------------------------------------------
Ran 38 tests in 3.711s

OK
```

### 3.4 Configuración de Nginx Reverse Proxy

Verificación de sintaxis de Nginx:
```bash
docker run --rm -v $(pwd)/infra/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro nginx:alpine nginx -t
```
Salida:
```text
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

Rutas públicas e intermedias configuradas hacia `identity_backend`:
- `/api/v1/auth/` -> `http://identity_backend/api/v1/auth/`
- `/api/v1/profile` -> `http://identity_backend/api/v1/profile`
- `/api/v1/admin/` -> `http://identity_backend/api/v1/admin/`
- Encabezados propagados: `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`, `Origin`.

---

## 4. Estado de Conclusión de Incremento 1

Todas las tareas 1.1 a 7.3 de `openspec/changes/incremento-1-identidad-y-autorizacion/tasks.md` han sido ejecutadas, validadas y comprobadas con pruebas reproducibles. El Incremento 1 queda formalmente concluido y listo para sincronización de especificaciones y archivo según el flujo OpenSpec.
