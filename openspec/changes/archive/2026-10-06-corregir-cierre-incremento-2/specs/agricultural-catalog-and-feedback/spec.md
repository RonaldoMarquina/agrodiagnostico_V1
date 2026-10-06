## MODIFIED Requirements

### Requirement: Catálogo candidato coherente con contratos
Diagnosis SHALL mantener cultivos POTATO y MAIZE y las siete condiciones candidatas contractuales: POTATO_HEALTHY, POTATO_EARLY_BLIGHT, POTATO_LATE_BLIGHT, MAIZE_HEALTHY, MAIZE_COMMON_RUST, MAIZE_LEAF_BLIGHT y MAIZE_GRAY_LEAF_SPOT. SHALL distinguir HEALTHY de DISEASE; activo no SHALL significar clase de modelo validada. Las semillas SHALL tener model_supported=false. No SHALL introducir plagas ni clases ajenas a la taxonomía V1 por administración.

#### Scenario: Arranque de catálogo
- **WHEN** se aplica la migración en una base limpia
- **THEN** existen los dos cultivos y siete condiciones candidatas, incluidas las sanas, sin afirmar soporte validado del modelo

#### Scenario: Consulta autenticada
- **WHEN** el usuario consulta GET /api/v1/crops o GET /api/v1/crops/{code}/problems
- **THEN** recibe 200 con items activos y sus códigos/nombres/condición candidata; padre desconocido o inactivo devuelve 404

### Requirement: Recomendaciones revisadas con versiones inmutables
Diagnosis SHALL publicar únicamente recomendaciones con fuentes y evidencia registrada de revisión. POST administrativo SHALL exigir source_refs, review_reference, reviewed_by y reviewed_at junto al contenido; el backend valida presencia/forma y registra autor administrativo, sin afirmar revisión científica automática. Seeds no SHALL inventar recomendaciones o aprobación. Versiones SHALL tener UUID y número incremental por problema; contenido y versión SHALL ser inmutables. GET /api/v1/problems/{code}/recommendations SHALL devolver la última versión aprobada activa como items o lista vacía, respetando estado del cultivo/problema. Diagnósticos resueltos SHALL conservar referencia/snapshot de la versión publicada.

#### Scenario: No hay contenido aprobado
- **WHEN** no existe paquete revisado ni versión activa aprobada para un problema activo
- **THEN** el sistema arranca normalmente y la consulta devuelve 200 con items vacío, sin fabricar orientación

#### Scenario: Publicación sin evidencia
- **WHEN** ADMIN envía una recomendación sin fuentes o datos de aprobación requeridos
- **THEN** recibe 400 CATALOG_REVIEW_REQUIRED y no se publica contenido

#### Scenario: Estructura inválida
- **WHEN** una publicación tiene campos extra, listas fuera de límites, elementos no textuales o fuentes vacías
- **THEN** devuelve 400 sin publicar; evidencia inválida usa CATALOG_REVIEW_REQUIRED

#### Scenario: Versiones concurrentes
- **WHEN** dos publicaciones válidas crean versiones del mismo problema
- **THEN** ambas versiones reciben números distintos y crecientes sin sobrescribir contenido previo

#### Scenario: Preservación histórica
- **WHEN** se publica una nueva versión o se desactiva una recomendación, problema o cultivo
- **THEN** el texto y referencia ya asociados a un diagnóstico resuelto permanecen intactos

### Requirement: Administración explícita y auditada del catálogo
El sistema SHALL ofrecer GET/POST en /api/v1/admin/crops, /api/v1/admin/problems y /api/v1/admin/recommendations; PATCH en /api/v1/admin/crops/{code}, /api/v1/admin/problems/{code} y /api/v1/admin/recommendations/{id}. SHALL exigir ADMIN, responder 401 anónimo y 403 USER. POST SHALL responder 201; PATCH 200. Códigos duplicados SHALL devolver 409 CATALOG_CONFLICT. Códigos/cultivo/tipo y model_supported no SHALL modificarse por PATCH; recomendaciones solo permiten PATCH de active. No SHALL existir borrado físico administrativo. Mutación y auditoría propia SHALL confirmarse atómicamente.

#### Scenario: Actualización autorizada
- **WHEN** ADMIN modifica nombre/estado permitido de un cultivo o condición
- **THEN** obtiene 200 y se registra actor, acción, destino, correlación y UTC en auditoría de Diagnosis
#### Scenario: Campos inmutables
- **WHEN** se intenta editar código, cultivo, tipo, soporte del modelo o contenido de una versión por PATCH
- **THEN** obtiene 400 sin alterar entidad ni historia

#### Scenario: Rol insuficiente
- **WHEN** USER o anónimo intenta consultar o mutar catálogo administrativo
- **THEN** recibe 403 o 401 respectivamente sin cambios

#### Scenario: Auditoría falla
- **WHEN** no puede persistirse la auditoría de una mutación
- **THEN** no se confirma la mutación y no se devuelve éxito

### Requirement: Feedback único y actualizable sobre resultado propio
POST /api/v1/diagnoses/{id}/feedback SHALL requerir diagnóstico propio no borrado en COMPLETADO o NO_CONCLUYENTE y cuerpo cerrado con useful booleano estricto y comment opcional de máximo 1000 caracteres. SHALL crear un único registro por diagnóstico con 201; envíos posteriores SHALL reemplazar valoración/comentario con 200, conservando created_at y actualizando updated_at. Omitir comment SHALL eliminar el comentario previo. Otros estados SHALL devolver 409 FEEDBACK_NOT_ALLOWED; ajeno/inexistente/borrado SHALL devolver 404 genérico antes de revelar estado. Los datos no SHALL alimentar automáticamente entrenamiento ni generar eventos ML.

#### Scenario: Primera valoración y reemplazo
- **WHEN** el propietario valora un resultado permitido y luego cambia useful omitiendo comment
- **THEN** recibe 201 seguido de 200, existe una sola valoración y su comentario queda null

#### Scenario: Valoración concurrente
- **WHEN** llegan valoraciones simultáneas para el mismo diagnóstico permitido
- **THEN** se serializan sin duplicados y la última operación aplicada determina el contenido almacenado

#### Scenario: Estado no permitido
- **WHEN** el propietario valora PENDIENTE, PROCESANDO, CANCELADO o FALLIDO no borrado
- **THEN** recibe 409 FEEDBACK_NOT_ALLOWED sin crear feedback

#### Scenario: Recurso ajeno o borrado
- **WHEN** el usuario intenta valorar un ID ajeno, inexistente o eliminado
- **THEN** obtiene 404 RESOURCE_NOT_FOUND sin revelar estado ni registrar feedback

#### Scenario: Payload inválido
- **WHEN** useful no es booleano, hay campos extra o comment supera 1000 caracteres
- **THEN** devuelve 400 contractual sin modificar valoración

#### Scenario: Separación de entrenamiento
- **WHEN** se confirma un feedback válido
- **THEN** queda disponible solo como métrica de calidad, sin eventos ni ingesta automática de entrenamiento

