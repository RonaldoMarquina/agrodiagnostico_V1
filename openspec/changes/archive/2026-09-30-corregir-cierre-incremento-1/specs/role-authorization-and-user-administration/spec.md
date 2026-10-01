# Spec Delta

## MODIFIED Requirements

### Requirement: Registro inmutable de auditoría de seguridad
El sistema SHALL tratar la tabla de auditoría `audit_logs` como un registro inmutable de solo inserción (INSERT), prohibiendo operaciones de modificación (UPDATE) o eliminación (DELETE) a través de la aplicación. Los eventos auditados SHALL incluir normativamente: `USER_REGISTERED`, `LOGIN_SUCCESS`, `LOGIN_FAILED`, `LOGOUT`, `PASSWORD_CHANGED`, `PASSWORD_RECOVERY_REQUESTED`, `PASSWORD_RECOVERY_CONFIRMED`, `REFRESH_TOKEN_REUSE_DETECTED`, `USER_BLOCKED`, `USER_ACTIVATED` y `INITIAL_ADMIN_PROVISIONED`. Cada fila SHALL registrar `actor_id` (o nulo en caso de acciones anónimas), `action`, `target_id`, `correlation_id` y marca de tiempo UTC. El sistema SHALL asegurar que ningún registro contenga contraseñas en texto claro, hashes de contraseñas ni tokens sensibles.

Los registros previos a la corrección SHALL conservarse sin inventar actores, destinos o correlaciones ausentes. La migración SHALL distinguir registros heredados incompletos; los nuevos eventos SHALL exigir correlación y acción normativa, conservando la auditoría atómica con la mutación.

#### Scenario: Registro inmutable de auditoría tras evento de seguridad
- **WHEN** se produce una mutación de seguridad (ej. cambio de contraseña, bloqueo de cuenta o reuso de token de refresco)
- **THEN** el sistema inserta una fila en `audit_logs` con acción, actor, objetivo, correlación y fecha UTC, sin permitir alteraciones posteriores

#### Scenario: Migración de auditoría histórica incompleta
- **WHEN** se migra una base con filas de auditoría del incremento 1 original
- **THEN** se conservan intactas como heredadas y las nuevas filas incluyen campos normativos sin permitir UPDATE/DELETE
