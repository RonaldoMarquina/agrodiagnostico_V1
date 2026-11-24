# balanced-potato-rejection-cycle Specification

## Purpose

Gobernar un nuevo ciclo que equilibre las tres clases técnicas en PlantVillage TRAIN/VAL y mida una sola vez la generalización y el rechazo en Sikkim EXTERNAL después de congelar toda decisión del modelo.

## ADDED Requirements

### Requirement: Cierre histórico inmutable de v1.3.2

El sistema de evidencias SHALL registrar v1.3.2 como ciclo evaluado y no aprobado para publicación porque 8 de 32 imágenes de papa sana recibieron un diagnóstico de tizón y 24 de 32 terminaron en `NO_CONCLUYENTE`, incumpliendo respectivamente los límites de máximo 3 de 32 y mínimo 29 de 32. Los commits `94b3d42` y `5f2d623`, el bundle, el TEST, el reporte y el umbral 0,90 SHALL permanecer inmutables y el TEST v1.3.2 SHALL NOT volver a ejecutarse.

#### Scenario: Consulta de la decisión histórica

- **WHEN** un revisor consulta el expediente v1.3.2
- **THEN** encuentra el resultado no aprobado, los numeradores y denominadores de papa sana, los dos commits y los hashes del bundle, TEST y reporte sin alteraciones

#### Scenario: Intento de optimizar con TEST histórico

- **WHEN** un operador intenta cambiar el umbral, pesos, calibración o configuración usando el TEST v1.3.2, o solicita reevaluarlo
- **THEN** el proceso rechaza la operación y conserva ese TEST únicamente como evidencia histórica

### Requirement: Protocolo G0 v1.4.0 previo al entrenamiento

G0 v1.4.0 SHALL fijar antes del entrenamiento PlantVillage como única fuente de TRAIN/VAL con separación por `leaf_id`, y Sikkim v1 como única fuente de EXTERNAL sellado con independencia declarada solo por imagen única. Sikkim SHALL NOT participar en entrenamiento, VAL, calibración, selección de arquitectura, selección de estrategia de balance ni selección de umbral.

#### Scenario: Configuración conforme a G0

- **WHEN** un operador valida la configuración del ciclo antes de entrenar
- **THEN** la configuración referencia PlantVillage TRAIN/VAL y Sikkim EXTERNAL por manifiestos y hashes distintos, y no ofrece ninguna ruta de Sikkim hacia selección

#### Scenario: Intento de mezclar Sikkim con selección

- **WHEN** un comando de entrenamiento, validación, calibración o selección incluye cualquier SHA-256 del manifiesto Sikkim
- **THEN** la compuerta G0 rechaza la ejecución antes de leer la imagen

### Requirement: Criterios externos congelados

La evaluación Sikkim EXTERNAL SHALL exigir F1 macro de los dos tizones ≥0,75; recall de tizón temprano ≥0,75 con mínimo 32 aciertos de 42; recall de tizón tardío ≥0,75 con mínimo 57 aciertos de 76; máximo 5 de 50 imágenes sanas publicadas como tizón; mínimo 45 de 50 imágenes sanas como `NO_CONCLUYENTE`; y máximo 9 de 194 imágenes de otro cultivo publicadas como tizón. Una abstención sobre un tizón SHALL contar como falso negativo para el recall de su clase.

#### Scenario: Cálculo de recall con abstención

- **WHEN** una imagen externa de tizón termina en `NO_CONCLUYENTE`
- **THEN** el reporte la cuenta en el denominador fijo de su clase y como falso negativo, nunca como diagnóstico acertado

#### Scenario: Evaluación de rechazo sano y otro cultivo

- **WHEN** se evalúan los estratos `POTATO_HEALTHY` y `OTHER_CROP`
- **THEN** el reporte conserva denominadores 50 y 194, publica los numeradores de tizones erróneos y compara respectivamente contra 5 y 9

### Requirement: Entrenamiento efectivo balanceado

El entrenamiento v1.4.0 SHALL usar como clases técnicas `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT` y `POTATO_HEALTHY`, con ponderación de clases o muestreo balanceado consciente de `leaf_id` para impedir que las imágenes sanas queden dominadas por los tizones. La estrategia, los conteos admitidos, la exposición efectiva por clase, la semilla y su justificación SHALL quedar en la configuración y evidencia del experimento.

#### Scenario: Configuración de balance válida

- **WHEN** se prepara un candidato con PlantVillage TRAIN admitido
- **THEN** la configuración demuestra cómo equilibra las tres clases técnicas sin tratar imágenes derivadas o vistas de una misma hoja como grupos independientes

#### Scenario: Entrenamiento sin balance explícito

- **WHEN** un comando de entrenamiento no declara ponderación de clases ni muestreo balanceado verificable
- **THEN** el candidato no puede registrarse como candidato v1.4.0

### Requirement: Aumentos de papa sana restringidos a TRAIN

Todo aumento aplicado a `POTATO_HEALTHY` SHALL ejecutarse únicamente durante TRAIN. Cada imagen derivada SHALL conservar la referencia al archivo original y a su `leaf_id`; las derivaciones SHALL NOT incrementar el número declarado de fotos originales o grupos independientes. VAL y EXTERNAL SHALL contener únicamente archivos originales admitidos y SHALL NOT recibir aumentos.

#### Scenario: Derivación sana durante TRAIN

- **WHEN** el cargador genera una transformación de una imagen sana admitida en TRAIN
- **THEN** registra la transformación bajo el mismo `leaf_id` y no modifica los conteos de originales ni grupos

#### Scenario: Aumento solicitado fuera de TRAIN

- **WHEN** una configuración intenta aumentar una imagen de VAL o EXTERNAL
- **THEN** la validación falla antes de entrenar o evaluar

### Requirement: Selección exclusiva con TRAIN y VAL

La arquitectura, estrategia de balance, hiperparámetros, calibración y umbral de publicación v1.4.0 SHALL seleccionarse exclusivamente con PlantVillage TRAIN/VAL. El bundle, mapa de clases, preprocesado, calibración y umbral SHALL congelarse y recibir hashes antes de abrir Sikkim EXTERNAL.

#### Scenario: Comparación de candidatos

- **WHEN** se comparan arquitecturas o políticas de rechazo
- **THEN** la decisión usa únicamente métricas de VAL y registra todos los candidatos comparables bajo los mismos manifiestos y presupuesto

#### Scenario: Acceso prematuro a EXTERNAL

- **WHEN** un proceso de selección intenta leer Sikkim EXTERNAL antes del congelamiento
- **THEN** el acceso es rechazado y el ciclo no puede promoverse a evaluación

### Requirement: Semántica de publicación del piloto

Solo `POTATO_EARLY_BLIGHT` y `POTATO_LATE_BLIGHT` SHALL ser diagnósticos publicables. Una predicción técnica `POTATO_HEALTHY`, una imagen `OTHER_CROP` o una predicción que incumpla la política de confianza SHALL producir `NO_CONCLUYENTE` con un `reason_code` apropiado y SHALL NOT publicarse como enfermedad.

#### Scenario: Papa sana reconocida

- **WHEN** el candidato técnico determina `POTATO_HEALTHY`
- **THEN** Diagnosis recibe una abstención publicable como `NO_CONCLUYENTE`, nunca un diagnóstico de papa sana ni de tizón

#### Scenario: Cultivo fuera del piloto

- **WHEN** una imagen admitida como `OTHER_CROP` llega a evaluación
- **THEN** el resultado esperado es `NO_CONCLUYENTE` y cualquier tizón publicado cuenta como aceptación errónea

### Requirement: Evaluación única con Sikkim EXTERNAL

Después del congelamiento, v1.4.0 SHALL ejecutar como máximo una evaluación sobre Sikkim EXTERNAL sellado: 42 imágenes de tizón temprano, 76 de tizón tardío, 50 de papa sana y 194 de otro cultivo. El reporte SHALL publicar numeradores, denominadores, F1 macro, recall por tizón, matriz de confusión, abstenciones, rechazos, calibración, latencia y memoria, y SHALL declarar que la independencia está demostrada por imagen única pero no por planta. Ningún fallo SHALL corregirse con EXTERNAL.

#### Scenario: Todos los criterios de G0 se cumplen

- **WHEN** la única evaluación EXTERNAL satisface todos los límites congelados
- **THEN** el bundle y reporte quedan disponibles para revisión G2 sin activar automáticamente el worker

#### Scenario: Algún criterio de G0 falla

- **WHEN** la única evaluación EXTERNAL incumple cualquier límite congelado
- **THEN** el ciclo se registra como no aprobado, G2 permanece abierto y no se ajusta el candidato con esas imágenes
