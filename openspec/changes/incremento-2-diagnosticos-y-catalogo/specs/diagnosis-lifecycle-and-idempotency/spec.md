# Spec Delta

## Purpose

Define el ciclo de vida, estados y transiciones de los diagnósticos, el mecanismo atómico de idempotencia con retención de 24 horas y huella criptográfica SHA-256, el borrado lógico idempotente y la consulta paginada keyset con aislamiento estricto de recursos.

## ADDED Requirements

### Requirement: Creación idempotente de diagnósticos
El sistema SHALL procesar la creación de diagnósticos mediante `POST /api/v1/diagnoses` soportando el encabezado obligatorio `Idempotency-Key` (cadena ASCII imprimible de 1 a 128 caracteres). El sistema SHALL aislar las claves en un namespace compuesto por `(owner_id, "diagnosis_create", idempotency_key)`. Para cada solicitud, el sistema SHALL calcular la huella digital criptográfica `SHA-256(bytes_de_imagen)` excluyendo metadatos de transporte. Si una solicitud presenta una clave ya registrada dentro de la ventana de retención no deslizante de 24 horas (86,400 segundos) con la misma huella SHA-256, el sistema SHALL responder con código 202 devolviendo el identificador y fecha de creación originales junto al estado actual. Si se presenta la misma clave con una imagen distinta (huella discrepante), el sistema SHALL responder con código 409 `IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD`.

#### Scenario: Creación inicial exitosa con Idempotency-Key
- **WHEN** un usuario autenticado envía una imagen válida con un encabezado `Idempotency-Key` nuevo
- **THEN** el sistema persiste el diagnóstico en estado `PENDIENTE`, registra la clave con su huella SHA-256 y responde 202 con el identificador UUID y fecha de creación

#### Scenario: Reintento idéntico dentro de retención devuelve diagnóstico existente
- **WHEN** un cliente reenvía la misma solicitud con el mismo `Idempotency-Key` y exactamente la misma imagen dentro de las 24 horas posteriores
- **THEN** el sistema no duplica el diagnóstico ni sube una nueva imagen, respondiendo 202 con el `id` original y el estado actual

#### Scenario: Discrepancia de contenido bajo la misma clave produce conflicto 409
- **WHEN** un cliente envía una clave de idempotencia existente pero adjuntando una fotografía con bytes diferentes
- **THEN** el sistema rechaza la solicitud con código 409 `IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD` sin alterar el diagnóstico previo

#### Scenario: Clave reutilizada sobre recurso borrado durante retención
- **WHEN** un cliente reutiliza una clave de idempotencia cuyo diagnóstico asociado fue marcado con borrado lógico
- **THEN** el sistema responde con código 409 `IDEMPOTENCY_RESOURCE_DELETED` sin resucitar el registro

#### Scenario: Namespace independiente por usuario
- **WHEN** dos usuarios autenticados distintos A y B envían solicitudes con el mismo valor textual en `Idempotency-Key`
- **THEN** el sistema procesa ambas solicitudes como diagnósticos completamente independientes sin conflicto entre usuarios

### Requirement: Ciclo de vida y cancelación de diagnósticos
El sistema SHALL gestionar las transiciones de estado de los diagnósticos respetando las invariantes: `PENDIENTE → PROCESANDO → COMPLETADO | NO_CONCLUYENTE | FALLIDO` y `PENDIENTE → CANCELADO`. El sistema SHALL permitir al propietario autenticado cancelar un diagnóstico mediante `POST /api/v1/diagnoses/{id}/cancel`. La cancelación SHALL ser exitosa (código 200 con estado `CANCELADO`) únicamente si el diagnóstico se encuentra en estado `PENDIENTE`. Si el diagnóstico ya fue reclamado para procesamiento o alcanzó un estado terminal, el sistema SHALL rechazar la cancelación con código 409 `DIAGNOSIS_NOT_CANCELABLE`.

#### Scenario: Cancelación exitosa de diagnóstico en estado PENDIENTE
- **WHEN** el usuario propietario envía `POST /api/v1/diagnoses/{id}/cancel` para un diagnóstico en estado `PENDIENTE`
- **THEN** el sistema actualiza atómicamente el estado a `CANCELADO` y responde con código 200 y el objeto actualizado

#### Scenario: Rechazo de cancelación si el diagnóstico no está en PENDIENTE
- **WHEN** un usuario intenta cancelar un diagnóstico que ya se encuentra en estado `PROCESANDO`, `COMPLETADO`, `NO_CONCLUYENTE` o `FALLIDO`
- **THEN** el sistema rechaza la solicitud con código 409 `DIAGNOSIS_NOT_CANCELABLE`

#### Scenario: Intento de cancelación por usuario ajeno devuelve 404 genérico
- **WHEN** un usuario A intenta cancelar un diagnóstico perteneciente al usuario B
- **THEN** el sistema responde con código 404 genérico `RESOURCE_NOT_FOUND`

### Requirement: Borrado lógico y consulta de detalle con aislamiento estricto
El sistema SHALL permitir al propietario marcar un diagnóstico como eliminado mediante `DELETE /api/v1/diagnoses/{id}`, ejecutando un borrado lógico (`deleted_at = NOW()`) y respondiendo con código 204 sin contenido de manera idempotente. El sistema SHALL proporcionar el endpoint `GET /api/v1/diagnoses/{id}` para consultar el estado y metadatos de un diagnóstico propio. Ante solicitudes de consulta o borrado dirigidas a diagnósticos inexistentes, con borrado lógico o pertenecientes a otros usuarios, el sistema SHALL responder con código 404 genérico `RESOURCE_NOT_FOUND`.

#### Scenario: Borrado lógico propio devuelve 204 idempotente
- **WHEN** un usuario autenticado envía `DELETE /api/v1/diagnoses/{id}` para un diagnóstico que le pertenece
- **THEN** el sistema marca `deleted_at = NOW()` y responde con código 204; solicitudes DELETE subsecuentes sobre el mismo ID responden igualmente 204

#### Scenario: Consulta de detalle por el propietario devuelve estado y metadatos
- **WHEN** el propietario realiza `GET /api/v1/diagnoses/{id}` para un diagnóstico activo
- **THEN** el sistema retorna código 200 con el identificador, estado, fechas y metadatos del diagnóstico

#### Scenario: Consulta de detalle por usuario ajeno devuelve 404 genérico
- **WHEN** un usuario A consulta un diagnóstico del usuario B o un identificador borrado lógicamente
- **THEN** el sistema responde con código 404 genérico `RESOURCE_NOT_FOUND`

### Requirement: Consulta paginada del historial de diagnósticos
El sistema SHALL proporcionar al usuario autenticado el endpoint `GET /api/v1/diagnoses` para listar su historial de diagnósticos propios. La consulta SHALL excluir de forma obligatoria los registros con borrado lógico (`deleted_at IS NOT NULL`). La paginación SHALL utilizar estrategia keyset ordenada por `created_at DESC, id DESC`, admitiendo un parámetro `limit` (entero entre 1 y 100, valor por defecto 20) y un parámetro `cursor` opaco codificado. El sistema SHALL devolver la lista de diagnósticos (`items`) y un indicador `next_cursor` (o `null` si no hay más elementos).

#### Scenario: Consulta de primera página de historial propio
- **WHEN** un usuario autenticado solicita `GET /api/v1/diagnoses?limit=10`
- **THEN** el sistema responde 200 con hasta 10 diagnósticos ordenados cronológicamente descendente y un cursor opaco para continuar la paginación

#### Scenario: Navegación a siguiente página con cursor opaco
- **WHEN** el cliente solicita `GET /api/v1/diagnoses?cursor=<next_cursor>&limit=10`
- **THEN** el sistema valida el cursor y retorna los diagnósticos subsiguientes en el orden estipulado

#### Scenario: Validación de límites de paginación
- **WHEN** un cliente envía `limit=0`, `limit=150` o un cursor malformado
- **THEN** el sistema rechaza la solicitud con código 400 `INVALID_PAGINATION`
