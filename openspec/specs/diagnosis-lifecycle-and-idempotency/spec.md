# diagnosis-lifecycle-and-idempotency Specification

## Purpose

Define creación idempotente, cancelación, borrado lógico, historial privado y supervisión administrativa de diagnósticos, con autorización, outbox transaccional y finalización asíncrona verificable.

## Requirements

### Requirement: Autenticación y respuestas privadas de Diagnosis
Diagnosis SHALL aplicar la verificación local Ed25519 y roles de la capacidad vigente de autorización, sin consultar datos de Identity. Toda ruta de negocio SHALL exigir Bearer válido y devolver respuestas con correlación y Cache-Control private, no-store; los errores SHALL usar el sobre común contractual. ADMIN SHALL respetar propiedad en rutas de usuario.

#### Scenario: Token inválido o incompleto
- **WHEN** el token está ausente, expirado, alterado o tiene algoritmo, claims, issuer o audience inválidos
- **THEN** Diagnosis rechaza con 401 sin ejecutar la operación

#### Scenario: Correlación inválida
- **WHEN** la solicitud contiene X-Correlation-ID que no es UUID
- **THEN** responde 400 contractual sin exponer errores internos

### Requirement: Creación idempotente de diagnósticos
POST /api/v1/diagnoses SHALL aceptar Idempotency-Key obligatorio de 1..128 caracteres que cumpla ^[A-Za-z0-9._:-]+$, namespace propietario/diagnosis_create/clave y fingerprint SHA-256 de bytes exactos de imagen. Retención SHALL ser 86400 segundos desde primera aceptación, no deslizante. La aceptación SHALL confirmar diagnosis, idempotencia y un outbox DiagnosisRequested v2 en una transacción antes de 202. La respuesta no SHALL esperar al broker o inferencia. Replay no SHALL crear evento adicional.

#### Scenario: Primera aceptación
- **WHEN** el propietario envía imagen válida y clave nueva
- **THEN** recibe 202 con UUID, created_at y estado PENDIENTE tras persistencia exitosa

#### Scenario: Replay idéntico
- **WHEN** reenvía misma clave e imagen dentro de retención
- **THEN** recibe 202 con ID/created_at originales y estado actual sin nueva fila ni subida

#### Scenario: Conflicto de contenido
- **WHEN** reutiliza clave vigente con bytes distintos para un diagnóstico no borrado
- **THEN** recibe 409 IDEMPOTENCY_CONFLICT sin alterar el previo

#### Scenario: Carga concurrente
- **WHEN** otra solicitud mantiene en curso la misma clave del propietario
- **THEN** la concurrente recibe 409 IDEMPOTENCY_IN_PROGRESS reintentable y no duplica diagnóstico ni objeto aceptado

#### Scenario: Separación por usuario
- **WHEN** A y B usan el mismo texto de clave
- **THEN** sus solicitudes son independientes sin compartir resultados

#### Scenario: Reutilización en frontera de expiración
- **WHEN** now es igual o posterior a expires_at y se envía una imagen válida con esa clave
- **THEN** puede aceptarse un nuevo ID y retención, conservando el diagnóstico anterior y con una única nueva aceptación ante concurrencia

#### Scenario: Replay de recurso eliminado
- **WHEN** se reutiliza durante retención la clave de un diagnóstico con tombstone
- **THEN** recibe 409 IDEMPOTENCY_RESOURCE_DELETED, sin resurrección, incluso si el contenido difiere

### Requirement: Cancelación atómica y terminales irreversibles
El sistema SHALL conservar PENDIENTE -> PROCESANDO -> COMPLETADO | NO_CONCLUYENTE | FALLIDO y PENDIENTE -> CANCELADO como invariantes. Reclamo y aplicación de análisis SHALL respetar identidad interna, lease vigente y deduplicación; solo Diagnosis decide la transición visible. POST /api/v1/diagnoses/{id}/cancel SHALL cambiar atómicamente PENDIENTE no borrado a CANCELADO y responder 200. Cualquier otro estado SHALL devolver 409 DIAGNOSIS_NOT_CANCELABLE. No SHALL emitir DiagnosisFinished por cancelación.

#### Scenario: Carrera de cancelaciones
- **WHEN** dos solicitudes cancelan simultáneamente el mismo PENDIENTE propio
- **THEN** solo una cambia el estado y devuelve 200; la otra devuelve 409

#### Scenario: Estado no cancelable
- **WHEN** se cancela PROCESANDO, COMPLETADO, NO_CONCLUYENTE, FALLIDO o CANCELADO
- **THEN** devuelve 409 y conserva el estado

#### Scenario: Cancelación no autorizada o borrada
- **WHEN** el ID es ajeno, inexistente o borrado
- **THEN** devuelve 404 NOT_FOUND genérico

### Requirement: Tombstone idempotente y detalle privado
DELETE /api/v1/diagnoses/{id} SHALL conservar tombstone de propiedad y devolver 204 tanto en primer borrado como en repeticiones propias. Ajeno o nunca existente SHALL devolver 404. Borrado no SHALL cancelar, alterar estado terminal ni borrar físicamente la foto. GET detalle SHALL respetar variantes contractuales; detalle, imagen, cancelación y feedback SHALL ocultar borrados con 404.

#### Scenario: Borrado repetido propio
- **WHEN** el propietario repite DELETE sobre su tombstone
- **THEN** obtiene 204 sin alterar estado ni borrar objeto físico

#### Scenario: Detalle y aislamiento
- **WHEN** el propietario consulta un diagnóstico no borrado
- **THEN** recibe 200 con estado/metadatos y resultado únicamente cuando corresponda al contrato

#### Scenario: Recurso ajeno o eliminado
- **WHEN** se consulta un ID ajeno, inexistente o borrado, incluso con ADMIN en ruta de usuario
- **THEN** obtiene el mismo 404 genérico sin revelar su existencia

### Requirement: Historial keyset y cursores ligados a solicitante
GET /api/v1/diagnoses SHALL listar solo propios no borrados, orden created_at DESC, id DESC, limit 1..100/default 20 y respuesta items/next_cursor. El cursor SHALL estar protegido contra alteración y ligado al principal y propósito de endpoint. Cursor inválido/ajeno o límite inválido SHALL devolver 400 INVALID_PAGINATION.

#### Scenario: Paginación estable
- **WHEN** el usuario recorre páginas con fechas empatadas e inserciones posteriores
- **THEN** recibe orden estable sin duplicados y next_cursor null al terminar

#### Scenario: Ancla borrada
- **WHEN** se borra el diagnóstico que originó un cursor válido antes de pedir la página siguiente
- **THEN** el cursor sigue permitiendo continuar sin exponer el diagnóstico borrado

#### Scenario: Cursor no autorizado o manipulado
- **WHEN** se usa un cursor alterado, de otro principal/endpoint, malformado o firmado con clave retirada
- **THEN** recibe 400 INVALID_PAGINATION genérico sin revelar propietario

### Requirement: Supervisión administrativa limitada y auditada
GET /api/v1/admin/diagnoses SHALL exigir ADMIN, listar diagnósticos no borrados con id, owner_id, status, created_at, updated_at y reason_code cuando corresponda, y aplicar paginación/cursores anteriores con propósito independiente. No SHALL incluir imágenes, object_key, feedback ni datos personales obtenidos de Identity. Toda consulta exitosa SHALL auditar actor, acción, correlación y UTC sin copiar resultados; no concede acceso adicional a imágenes ajenas.

#### Scenario: Supervisión autorizada
- **WHEN** ADMIN consulta el listado
- **THEN** obtiene 200 con metadatos paginados y queda una auditoría propia de Diagnosis

#### Scenario: Supervisión denegada
- **WHEN** USER o una solicitud anónima consulta supervisión
- **THEN** obtiene respectivamente 403 o 401 sin datos de otros usuarios

### Requirement: Recuperación explícita de solicitudes previas
Un backfill operativo SHALL ofrecer dry-run por defecto e IDs/lotes explícitos; aplicación autorizada SHALL crear como máximo una señal inicial para cada PENDIENTE sin outbox, revalidando bajo concurrencia. SHALL preservar objeto, propiedad, created_at y terminales. No SHALL procesar datos reales con el simulador.

#### Scenario: Repetición y carrera
- **WHEN** se ejecuta dos veces el backfill y compite con cancelación o creación de outbox
- **THEN** no duplica señales iniciales, no revive CANCELADO y conserva todos los diagnósticos previos

#### Scenario: Correlación histórica ausente
- **WHEN** una solicitud previa no conserva correlation_id original
- **THEN** la recuperación registra una correlación nueva y su origen operativo sin inventar la correlación histórica

### Requirement: Decisión y finalización atómicas
Diagnosis SHALL validar generación vigente y política antes de confirmar inbox, estado visible, snapshot si corresponde y Finished/outbox en una transacción. CANCELADO no SHALL emitir Finished. Un resultado descartado SHALL quedar auditado sin alterar terminales.

#### Scenario: Resultado contra recuperación
- **WHEN** compiten resultado y recuperación de lease con dos transacciones reales
- **THEN** solo el resultado con generación/tiempo válidos puede aplicarse y existe como máximo un Finished lógico

#### Scenario: Fallo al persistir Finished
- **WHEN** falla la inserción del outbox de finalización
- **THEN** no se confirma estado visible ni inbox y no se hace ACK de Analyzed
