# dataset-inventory Specification

## Purpose

Hacer trazables las fuentes y etiquetas candidatas antes de admitir datos al entrenamiento, conservando explícitas las incógnitas legales, diagnósticas y de cobertura.

## Requirements

### Requirement: DATA-01 Fuentes y elegibilidad documentadas
El inventario SHALL registrar PlantVillage, PlantDoc y PlantSeg como candidatos a examinar, sin declarar su licencia compatible por su nombre. Cada entrada SHALL incluir identificador, versión si se conoce, autor, referencia verificable, fecha de consulta o estado no consultado, licencia/permiso y evidencia, restricciones, condiciones de captura, revisión de etiquetas, duplicados, exclusiones y cantidades por etiqueta con origen del conteo. Los valores desconocidos SHALL ser explícitos y no ceros inventados. Una fuente sin permiso demostrado SHALL quedar pendiente o excluida para entrenamiento.

#### Scenario: Fuente sin licencia verificada
- **WHEN** se registra una fuente candidata sin evidencia de permiso
- **THEN** figura pendiente y no puede marcarse elegible; no se descargan imágenes automáticamente.

#### Scenario: Inventario sin datos locales
- **WHEN** no hay dataset autorizado ni conjunto de Ayacucho disponible
- **THEN** el inventario declara cantidades locales no medidas y conjunto externo no disponible, sin filas de imágenes ficticias ni afirmación de validación externa.

### Requirement: DATA-02 Taxonomía candidata y manifiesto validable
El inventario SHALL proponer siete códigos estables para las clases candidatas del README con cultivo, nombre, definición pendiente o respaldada y mapeo de etiquetas de origen. SHALL distinguir candidata de soportada y no usar NO_CONCLUYENTE como clase. El contrato de manifiesto SHALL incluir image_id, sha256, crop_code, class_code, source, license, capture_context, label_quality, split_group y split, con TRAIN, VAL, TEST o EXTERNAL como particiones admitidas.

#### Scenario: Validación de manifiesto sintético
- **WHEN** se validan fixtures claramente sintéticos y variantes con hash inválido, clase desconocida, cultivo incompatible o campo requerido ausente
- **THEN** los fixtures válidos pasan y las variantes inválidas fallan, sin contabilizar los fixtures como imágenes disponibles o métricas reales.

### Requirement: DATA-03 Prevención de fuga y privacidad
El inventario SHALL definir agrupamiento por planta/sesión/sitio/fuente según metadatos, detección de duplicados y exclusión o cuarentena de casos sin separación confiable. El validador SHALL rechazar hashes idénticos o split_group compartidos entre particiones. La detección visual de casi duplicados y la curación real SHALL quedar identificadas como trabajo del incremento de datos. Imágenes de usuarios y ubicaciones precisas SHALL NOT incorporarse al repositorio ni al entrenamiento por defecto.

#### Scenario: Fuga entre particiones
- **WHEN** fixtures del manifiesto repiten un sha256 o split_group entre TRAIN y TEST, o entre cualquier par de particiones
- **THEN** la validación falla y señala el conflicto sin corregir silenciosamente la partición ni afirmar que este control detecta todos los casi duplicados.

#### Scenario: Candidaturas sin validación del modelo
- **WHEN** se publica el inventario inicial
- **THEN** las siete clases siguen siendo candidatas, no se publican métricas ni umbrales y no se entrena ni se reutilizan fotos de producción.
