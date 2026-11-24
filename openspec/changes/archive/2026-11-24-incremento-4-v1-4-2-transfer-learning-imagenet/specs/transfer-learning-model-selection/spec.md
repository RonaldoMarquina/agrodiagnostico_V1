# Spec Delta

## Purpose

Gobernar una comparación reproducible de transferencia ImageNet frente al ciclo aleatorio v1.4.1, con pesos de procedencia verificable y selección exclusiva mediante PlantVillage VAL.

## ADDED Requirements

### Requirement: Procedencia y admisión de pesos base

Antes de entrenar, el sistema SHALL descargar explícitamente desde la URL oficial fijada el artefacto `MobileNet_V3_Small_Weights.IMAGENET1K_V1` y SHALL registrar enumeración, versión de TorchVision, URL final, nombre, tamaño, SHA-256 completo, receta, transformaciones de referencia, fecha, licencia del código y condiciones advertidas para modelos preentrenados y ImageNet. El entrenamiento SHALL ejecutarse sin red y SHALL cargar únicamente el archivo privado admitido en modo de solo lectura. Una URL, nombre o prefijo de hash no SHALL sustituir la verificación del SHA-256 completo.

#### Scenario: Peso oficial admitido

- **WHEN** la descarga desde `download.pytorch.org` termina y nombre, tamaño y SHA-256 completo coinciden con el registro aprobado
- **THEN** la compuerta crea un expediente de procedencia inmutable y permite que el preflight offline lo considere como única inicialización preentrenada

#### Scenario: Peso distinto o términos ausentes

- **WHEN** cambia cualquier byte, la URL final no es la fijada, el artefacto no es un `state_dict` seguro o falta el registro de términos aplicables
- **THEN** la compuerta rechaza el peso antes de construir el candidato y no inicia entrenamiento

### Requirement: Frontera histórica y G0 sin cambios

El ciclo v1.4.2 SHALL conservar sin modificación G0/G1 v1.4.1, los commits `7377819` y `e709f27`, sus artefactos privados y su resultado `BLOCKED_NO_CANDIDATE_PASSES_VAL`. La línea base aleatoria SHALL participar solo mediante el resumen histórico fijado; sus pesos o predicciones SHALL NOT inicializar, entrenar, calibrar ni seleccionar v1.4.2.

#### Scenario: Comparación histórica permitida

- **WHEN** se genera la comparación VAL v1.4.2
- **THEN** reproduce los hashes y métricas publicadas de v1.4.1 sin reejecutar ni sobrescribir ese ciclo

#### Scenario: Intento de mutar el antecedente

- **WHEN** una ejecución intenta escribir bajo las raíces v1.4.1 o cargar sus pesos/predicciones
- **THEN** falla antes de actualizar parámetros y conserva intacta la evidencia histórica

### Requirement: Transferencia de cuatro clases en dos fases

El candidato SHALL producir las cuatro clases técnicas vigentes y SHALL mantener como publicables únicamente ambos tizones. SHALL usar el manifiesto TRAIN v1.4.1, sampler clase → `leaf_id` → imagen con 80 muestras por clase y 320 por época, y aumentos conservadores únicamente para `POTATO_HEALTHY` TRAIN. Primero SHALL ajustar una cabeza nueva de cuatro salidas con el backbone congelado; después SHALL realizar fine tuning parcial con una tasa menor y sin actualizar estadísticas BatchNorm con lotes pequeños.

#### Scenario: Fase de cabeza

- **WHEN** se ejecuta la fase inicial
- **THEN** solo la cabeza nueva recibe gradientes, cada época registra 80×4 exposiciones y el backbone conserva el hash derivado de los pesos admitidos

#### Scenario: Fine tuning controlado

- **WHEN** comienza la segunda fase
- **THEN** únicamente los bloques aprobados y la cabeza reciben gradientes con las tasas fijadas, BatchNorm permanece congelado y el expediente identifica por época la fase y parámetros entrenables

#### Scenario: Rechazo técnico visible

- **WHEN** el argmax calibrado corresponde a `POTATO_HEALTHY` o `OTHER_CROP`
- **THEN** el resultado es `NO_CONCLUYENTE`; ninguna de esas salidas se convierte en diagnóstico publicable

### Requirement: Selección exclusiva mediante VAL

Arquitectura/configuración, época, calibración y umbral SHALL seleccionarse únicamente con las 496 filas VAL vigentes. Un candidato SHALL ser elegible solo si satisface simultáneamente F1 macro ≥0,80, recall de cada tizón ≥0,80, cobertura ≥0,70, error selectivo ≤0,10, papa sana publicada ≤2/28, otro cultivo publicado ≤7/150 y ECE ≤0,15. Las abstenciones de tizones SHALL contar como falsos negativos.

#### Scenario: Transferencia elegible

- **WHEN** una época y política seleccionadas en VAL satisfacen todas las mínimas
- **THEN** el sistema puede congelar un candidato privado previo a EXTERNAL con procedencia del peso base y todos sus hashes

#### Scenario: Mejora parcial no elegible

- **WHEN** mejora respecto a v1.4.1 pero falla al menos una mínima vigente
- **THEN** registra `BLOCKED_NO_CANDIDATE_PASSES_VAL`, no congela un bundle habilitante y no autoriza EXTERNAL

### Requirement: Aislamiento de TEST y Sikkim

El proceso de adquisición SHALL tener red solo para obtener el peso oficial y SHALL NOT montar datos agronómicos. Preflight, entrenamiento, calibración y selección SHALL ejecutarse sin red y sin rutas, manifiestos, bytes, hashes, predicciones ni métricas del TEST histórico o de Sikkim EXTERNAL.

#### Scenario: Entrenamiento aislado

- **WHEN** se inicia cualquier fase de entrenamiento o selección
- **THEN** solo están montados el peso base admitido, TRAIN/VAL PlantVillage y una salida nueva v1.4.2

#### Scenario: Evidencia protegida disponible

- **WHEN** el contenedor detecta un montaje o referencia de TEST o Sikkim
- **THEN** el preflight falla antes de leer bytes y no crea artefactos de candidato
