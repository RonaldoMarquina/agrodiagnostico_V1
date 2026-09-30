# Spec Delta

## Purpose

Estructura el catálogo agronómico versionado de cultivos, problemas y recomendaciones preventivas para papa y maíz, proporciona endpoints administrativos protegidos para su actualización controlada y habilita la captura de retroalimentación de agricultores sin reentrenamiento automático.

## ADDED Requirements

### Requirement: Catálogo agronómico estructurado y versionado
El sistema SHALL mantener en la base de datos de `diagnosis` un catálogo agronómico relacional compuesto por cultivos (`crops`), problemas fitosanitarios (`problems`) y recomendaciones preventivas versionadas (`recommendations`). El sistema SHALL incluir semillas iniciales homologadas para papa (*Solanum tuberosum*) y maíz (*Zea mays*) junto a las clases candidatas fitosanitarias de V1. Las recomendaciones SHALL contener buenas prácticas culturales, biológicas y preventivas generales aprobadas, prohibiendo expresamente la inclusión de dosis o tratamientos químicos específicos sin validación institucional. Cada recomendación SHALL registrar un número de versión entero incremental (`version >= 1`).

#### Scenario: Semillas iniciales disponibles para consulta
- **WHEN** se inicializa o migra la base de datos de diagnosis
- **THEN** la base de datos cuenta con registros activos para papa y maíz con sus problemas candidatos y recomendaciones preventivas iniciales (versión 1)

#### Scenario: Consulta de catálogo de cultivos y problemas
- **WHEN** un usuario autenticado realiza una solicitud GET para listar cultivos o problemas fitosanitarios activos
- **THEN** el sistema responde con código 200 y el listado de elementos activos con sus códigos normalizados y nombres comunes

#### Scenario: Versionado inmutable de recomendaciones en diagnósticos
- **WHEN** se asocia una recomendación a un diagnóstico resuelto
- **THEN** el sistema vincula la versión específica vigente de la recomendación, garantizando que actualizaciones posteriores de la recomendación no modifiquen retroactivamente el texto entregado al agricultor

### Requirement: Gestión administrativa del catálogo por rol ADMIN
El sistema SHALL restringir la creación y modificación de elementos del catálogo a usuarios que presenten un token JWT válido con rol `ADMIN`. El sistema SHALL proporcionar endpoints administrativos bajo `/api/v1/admin/crops`, `/api/v1/admin/problems` y `/api/v1/admin/recommendations` para consultar, crear o modificar el estado de cada entidad. Toda solicitud proveniente de un usuario con rol `USER` o sin autenticación SHALL ser rechazada con código 403 `FORBIDDEN` o 401 `UNAUTHORIZED`.

#### Scenario: Administrador registra nuevo problema o recomendación
- **WHEN** un usuario con rol `ADMIN` envía `POST /api/v1/admin/problems` o `/api/v1/admin/recommendations` con datos válidos
- **THEN** el sistema persiste la nueva entidad en la base de datos de diagnosis y responde con código 201

#### Scenario: Usuario con rol USER tiene acceso denegado a rutas administrativas
- **WHEN** un usuario con rol `USER` intenta enviar una solicitud a cualquier endpoint bajo `/api/v1/admin/crops`, `/admin/problems` o `/admin/recommendations`
- **THEN** el sistema rechaza la solicitud con código 403 `FORBIDDEN` sin alterar los datos del catálogo

### Requirement: Captura de retroalimentación de usuario (Feedback)
El sistema SHALL proporcionar el endpoint `POST /api/v1/diagnoses/{id}/feedback` para que el agricultor propietario califique la utilidad del diagnóstico. La solicitud SHALL requerir autenticación Bearer de usuario y un cuerpo JSON con el campo booleano obligatorio `useful` y un campo opcional `comment` (hasta 1000 caracteres). El sistema SHALL verificar que el diagnóstico pertenezca al usuario autenticado (`owner_id == sub`); ante diagnósticos ajenos o inexistentes, SHALL responder con código 404 genérico `RESOURCE_NOT_FOUND`. El sistema SHALL almacenar el feedback exclusivamente como métrica de calidad y satisfacción, prohibiendo normativamente su inyección o uso para el reentrenamiento automático de modelos de aprendizaje automático.

#### Scenario: Propietario califica con feedback un diagnóstico propio
- **WHEN** el propietario autenticado envía `POST /api/v1/diagnoses/{id}/feedback` con `useful: true` y un comentario
- **THEN** el sistema registra el feedback asociado al diagnóstico, confirma con código 201 o 200 y almacena los datos para análisis de calidad

#### Scenario: Intento de calificar diagnóstico ajeno devuelve 404 genérico
- **WHEN** un usuario autenticado A intenta enviar feedback sobre un diagnóstico perteneciente al usuario B
- **THEN** el sistema responde con código 404 genérico `RESOURCE_NOT_FOUND` sin registrar ninguna retroalimentación

#### Scenario: Aislamiento del feedback frente a reentrenamiento de modelos
- **WHEN** se almacena un registro de feedback en la base de datos
- **THEN** los datos quedan restringidos a métricas y auditoría, sin generar eventos de ingesta ni alimentar pipelines automáticos de entrenamiento ML
