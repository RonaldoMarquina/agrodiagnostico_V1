## Purpose

Controlar qué resultados reales puede publicar Diagnosis mediante políticas inmutables respaldadas por evaluación, manteniendo catálogo revisado y trazabilidad histórica.

## ADDED Requirements

### Requirement: Promoción explícita y auditada de políticas
Diagnosis SHALL gestionar políticas inmutables que vinculen versión exacta de modelo/dataset, digest de artefacto, clases aprobadas, calibración, umbrales y evidencia de revisión. Importación y activación SHALL ser operaciones explícitas auditadas, con previsualización sin cambios por defecto y validación previa. La política activa SHALL determinar soporte efectivo del catálogo, sin permitir modificación pública de model_supported ni aprobación mediante semillas.

#### Scenario: Promoción sin evidencia
- **WHEN** una política carece de evaluación, aprobación o vínculo verificable al release
- **THEN** se rechaza y no cambia soporte ni política activa

#### Scenario: Fallo de auditoría
- **WHEN** falla la auditoría de activación o retiro
- **THEN** no se confirma la mutación ni el cambio de soporte

### Requirement: Publicación condicionada por versión y catálogo
Diagnosis SHALL publicar COMPLETADO solo con política activa compatible, clase aprobada, score suficiente y catálogo activo con recomendación revisada. SHALL responder NO_CONCLUYENTE con UNSUPPORTED_CLASS por versión/clase no autorizada, LOW_CONFIDENCE por score insuficiente o CATALOG_UNAVAILABLE por ausencia de recomendación, conservando precedencia contractual vigente. AI no SHALL decidir publicación ni recomendaciones.

#### Scenario: Predicción de versión desconocida
- **WHEN** una predicción identifica una tupla de modelo/dataset no autorizada
- **THEN** no se publica COMPLETADO aunque tenga score alto y catálogo disponible

#### Scenario: Score justo en la frontera
- **WHEN** la puntuación calibrada alcanza exactamente el mínimo aprobado de la clase y los demás requisitos se cumplen
- **THEN** se acepta según regla inclusiva documentada; un valor inferior se abstiene

#### Scenario: Retiro concurrente
- **WHEN** retiro de política y finalización compiten
- **THEN** se serializa su decisión; una finalización posterior al retiro no usa esa política y un terminal previo no se modifica

### Requirement: Trazabilidad de confianza e historia
Diagnosis SHALL conservar raw_score, confianza estimada calibrada y snapshot de política/versiones junto al snapshot de catálogo para nuevos resultados evaluados. SHALL distinguir puntuación técnica de confianza estimada, sin afirmar certeza clínica. Lectura de resultados históricos SHALL seguir siendo compatible sin recalibrarlos ni inventar política anterior.

#### Scenario: Cambio de política
- **WHEN** se activa otra política o se retira una versión
- **THEN** resultados ya terminales conservan su contenido, versiones y confianza originales

#### Scenario: Resultado histórico sin política
- **WHEN** se consulta un resultado previo a esta capacidad
- **THEN** continúa legible sin atribuirle validación o calibración que no tuvo
