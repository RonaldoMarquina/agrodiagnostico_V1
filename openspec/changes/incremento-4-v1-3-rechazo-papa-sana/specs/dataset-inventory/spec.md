# Spec Delta

## ADDED Requirements

### Requirement: G1 independiente para el piloto v1.3.0
La admisión v1.3.0 SHALL registrar por archivo revisión de fuente, ruta, SHA-256, derecho aplicable, etiqueta, calidad, identificador verificable de hoja o planta, estrato y partición. SHALL mantener separados los dos tizones, papa sana y negativos de otros cultivos. SHALL rechazar fuentes pendientes, etiquetas dudosas, `fallback_*`, archivos sin permiso, duplicados exactos y pares visuales no resueltos. Los cuatro controles G3 y todas las vistas de sus tres grupos SHALL quedar fuera de TRAIN, VAL, TEST y EXTERNAL v1.3.0. Una etiqueta de procedencia experta de PlantVillage SHALL distinguirse de una nueva revisión agronómica independiente.

#### Scenario: Imagen sin permiso o grupo verificable
- **WHEN** un archivo carece de derecho aplicable o de identificador de grupo respaldado por la fuente
- **THEN** queda excluido o en cuarentena y no cuenta para los mínimos de G1.

#### Scenario: Grupo expuesto o compartido
- **WHEN** una foto propuesta para cualquier partición v1.3.0 pertenece a uno de los tres grupos G3 expuestos, o un `leaf_id`, SHA-256 o duplicado visual relaciona el nuevo TEST con TRAIN, VAL o TEST v1.2.0 abierto
- **THEN** la fila o el TEST propuesto se rechaza hasta resolver la fuga sin mover silenciosamente muestras entre particiones.

### Requirement: Nuevo TEST sellado
El ciclo v1.3.0 SHALL tener un TEST nuevo independiente para ambos tizones, papa sana y negativos de otros cultivos, con mínimos aprobados por estrato y sello verificable. Los datos TRAIN/VAL reutilizados SHALL pasar nueva admisión y comparación de grupos con el TEST. La apertura de TEST SHALL ocurrir únicamente después de congelar el nuevo bundle y umbral mediante VAL.

#### Scenario: Insuficiencia de grupos nuevos
- **WHEN** cualquiera de los cuatro estratos no alcanza los mínimos de fotos y grupos aprobados
- **THEN** G1 permanece abierto y no se acredita una evaluación independiente.
