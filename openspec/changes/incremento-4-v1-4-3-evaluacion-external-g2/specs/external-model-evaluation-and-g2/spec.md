# Spec Delta

## Purpose

Define la apertura única y auditable de un conjunto EXTERNAL sellado para
evaluar un modelo congelado y decidir G2 sin convertir los resultados externos
en datos de entrenamiento, calibración o selección.

## ADDED Requirements

### Requirement: La evaluación usa únicamente el freeze y el EXTERNAL sellados
El sistema SHALL autorizar la evaluación final v1.4.3 solo cuando el bundle,
pesos, arquitectura, mapa técnico, contrato de preprocesado RGB 224×224 con
normalización ImageNet, temperatura 0,50 y umbral 0,80 coincidan con el freeze
aprobado. El protocolo, manifiesto de 350 filas, preflight y sello SHALL
coincidir con sus hashes registrados y SHALL excluir Sikkim.

#### Scenario: Todos los artefactos coinciden
- **WHEN** se solicita `FINAL_EXTERNAL_EVALUATION` con los artefactos sellados
- **THEN** el sistema autoriza exclusivamente la inferencia final sobre las 350 filas

#### Scenario: Un artefacto o parámetro cambió
- **WHEN** difiere cualquier hash, conteo, parámetro congelado o aparece una referencia a Sikkim
- **THEN** el sistema rechaza la ejecución antes de leer imágenes para inferencia

### Requirement: La apertura EXTERNAL es única e irreversible
El sistema SHALL crear un registro de acceso exclusivo antes de la primera
inferencia y SHALL rechazar todo reintento para el mismo freeze y sello,
incluido después de un error técnico. La ejecución SHALL operar sin red,
entrenamiento, gradientes, recalibración, búsqueda de umbral o escritura sobre
los artefactos de entrada.

#### Scenario: Primera apertura autorizada
- **WHEN** pasan todas las compuertas y no existe un registro previo
- **THEN** el sistema registra `STARTED` antes de inferir y procesa cada fila una vez

#### Scenario: Ya existe evidencia de apertura
- **WHEN** existe un registro `STARTED`, `COMPLETED` o `FAILED_TECHNICAL` para el sello
- **THEN** el sistema rechaza otra ejecución sin modificar la evidencia previa

### Requirement: La decisión visible preserva la abstención
El sistema SHALL publicar únicamente `POTATO_EARLY_BLIGHT` o
`POTATO_LATE_BLIGHT` cuando la clase técnica ganadora sea publicable y alcance
confianza calibrada 0,80. `POTATO_HEALTHY`, `OTHER_CROP` y toda confianza menor
SHALL producir `NO_CONCLUYENTE`; una abstención sobre un tizón SHALL contar como
falso negativo para su recall.

#### Scenario: Clase técnica de rechazo
- **WHEN** la clase ganadora es `POTATO_HEALTHY` u `OTHER_CROP`
- **THEN** el resultado visible es `NO_CONCLUYENTE` aunque su confianza supere el umbral

#### Scenario: Tizón bajo el umbral
- **WHEN** una imagen de tizón no produce un diagnóstico publicable con confianza al menos 0,80
- **THEN** se registra una abstención y un falso negativo para ese tizón

### Requirement: El reporte conserva métricas y denominadores completos
El sistema SHALL reportar F1 macro de ambos tizones, precision, recall y F1 por
tizón, publicaciones erróneas sobre papa sana y otro cultivo, abstenciones,
matriz visible, latencia, memoria y hashes. Los denominadores SHALL ser 50 para
cada estrato de papa y 200 para otro cultivo, y la independencia SHALL
declararse únicamente por imagen única.

#### Scenario: Evaluación completa
- **WHEN** finaliza la inferencia de las 350 filas
- **THEN** el reporte incluye todos los numeradores, denominadores, matriz, hashes y limitaciones sin rutas privadas ni bytes de imágenes

#### Scenario: Cardinalidad incompleta
- **WHEN** faltan filas, hashes o resultados respecto del sello
- **THEN** el sistema no emite una decisión G2 aprobatoria

### Requirement: G2 se decide por conjunción estricta
El sistema SHALL cerrar G2 únicamente si F1 macro de ambos tizones es al menos
0,75, cada tizón tiene al menos 38/50 aciertos publicados, papa sana tiene como
máximo 5/50 publicaciones como tizón y al menos 45/50 `NO_CONCLUYENTE`, y otro
cultivo tiene como máximo 10/200 publicaciones como tizón. El worker y la
política real SHALL permanecer inactivos independientemente del resultado.

#### Scenario: Todos los límites se cumplen
- **WHEN** cada criterio aprobado es verdadero y la ejecución está completa
- **THEN** el sistema registra G2 cerrado para los hashes exactos evaluados

#### Scenario: Falla al menos un límite
- **WHEN** cualquier criterio es falso o la ejecución no está completa
- **THEN** el sistema conserva la evidencia, mantiene G2 abierto y no activa el worker ni la política real
