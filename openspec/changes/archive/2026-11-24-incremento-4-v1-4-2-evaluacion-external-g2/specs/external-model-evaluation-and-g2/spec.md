# Spec Delta

## Purpose

Define la apertura única de un conjunto EXTERNAL sellado y la decisión G2
reproducible de un modelo congelado sin permitir que la evaluación independiente
se convierta en selección o ajuste del modelo.

## ADDED Requirements

### Requirement: La evaluación EXTERNAL usa únicamente artefactos congelados
El sistema SHALL autorizar la evaluación final solo cuando el bundle v1.4.2, sus
pesos, arquitectura, mapa de clases, preprocesado RGB 224×224 con normalización
ImageNet, temperatura 0,50 y umbral 0,80 coincidan con sus hashes congelados. El
manifiesto, sello, protocolo y archivo Sikkim SHALL coincidir con la evidencia G1.

#### Scenario: Todos los hashes coinciden
- **WHEN** se solicita `FINAL_EXTERNAL_EVALUATION` con el bundle y Sikkim sellados
- **THEN** el sistema autoriza el acceso únicamente para inferencia final

#### Scenario: Un artefacto cambió
- **WHEN** difiere cualquier hash, parámetro congelado, conteo o ruta del archivo fuente
- **THEN** el sistema rechaza la evaluación antes de leer bytes de imágenes

### Requirement: La apertura EXTERNAL es única y no selecciona parámetros
El sistema SHALL ejecutar como máximo una evaluación sobre las 362 imágenes
Sikkim admitidas, sin red, reentrenamiento, gradientes, calibración, búsqueda de
umbral, comparación de arquitecturas ni escritura sobre el bundle. El acceso
SHALL dejar un registro inmutable aunque la ejecución termine con error técnico.

#### Scenario: Primera apertura autorizada
- **WHEN** no existe un registro previo de apertura y pasan todas las compuertas
- **THEN** el sistema registra el inicio antes de inferir y procesa cada fila una sola vez

#### Scenario: Reintento posterior
- **WHEN** ya existe un registro de inicio o terminación para este bundle y sello
- **THEN** el sistema rechaza otra evaluación sin modificar la evidencia existente

### Requirement: El reporte EXTERNAL conserva resultados completos
El sistema SHALL reportar para los 362 casos F1 macro, precision/F1/recall por
tizón, abstenciones como falsos negativos, publicaciones erróneas de papa sana y
otro cultivo, matriz visible de confusión, latencia, memoria, hashes y
numeradores/denominadores. La unidad de independencia SHALL declararse como
imagen única y no como planta.

#### Scenario: Predicción no publicable o bajo umbral
- **WHEN** el argmax es `POTATO_HEALTHY` o `OTHER_CROP`, o la confianza calibrada no alcanza 0,80
- **THEN** el resultado visible es `NO_CONCLUYENTE` y una imagen de tizón cuenta como falso negativo

#### Scenario: Reporte completo
- **WHEN** termina la inferencia de las 362 filas
- **THEN** el reporte incluye los cuatro denominadores 42, 76, 50 y 194, la matriz y los hashes de entrada y salida

### Requirement: G2 se decide por conjunción estricta
El sistema SHALL cerrar G2 únicamente si F1 macro es al menos 0,75, recall de
tizón temprano es al menos 32/42, recall de tizón tardío es al menos 57/76,
publicaciones de tizón sobre papa sana son como máximo 5/50 con al menos 45/50
`NO_CONCLUYENTE`, y publicaciones de tizón sobre otro cultivo son como máximo
9/194. El worker real SHALL permanecer inactivo independientemente del resultado.

#### Scenario: Todos los límites se cumplen
- **WHEN** cada criterio externo evaluado es verdadero
- **THEN** el sistema registra G2 cerrado para el bundle exacto y conserva EXTERNAL como evidencia no reutilizable

#### Scenario: Falla al menos un límite
- **WHEN** cualquier criterio externo evaluado es falso o un denominador está incompleto
- **THEN** el sistema conserva el reporte, mantiene G2 abierto y no activa el worker real
