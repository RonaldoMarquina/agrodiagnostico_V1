# Spec Delta

## Purpose

Gobernar el ciclo v1.4.1 con cuatro salidas técnicas balanceadas, dos diagnósticos publicables y rechazo explícito de papa sana y otros cultivos sin usar TEST ni EXTERNAL para seleccionar la solución.

## ADDED Requirements

### Requirement: Frontera histórica de v1.4.0

El sistema de evidencias SHALL conservar v1.4.0 como ciclo TRAIN/VAL medido y no elegible porque su líder relativo publicó tizón en 83 de 150 imágenes `OTHER_CROP`, frente al máximo de 7 de 150. Sus pesos, configuraciones, manifiestos, predicciones, reportes y decisión `BLOCKED_NO_CANDIDATE_PASSES_VAL` SHALL permanecer inmutables y SHALL NOT actuar como bundle v1.4.1.

#### Scenario: Consulta del antecedente v1.4.0

- **WHEN** un revisor consulta la razón de v1.4.1
- **THEN** encuentra 83/150 publicaciones erróneas de otro cultivo, el máximo 7/150, los hashes de ambos candidatos v1.4.0 y la ausencia de bundle congelado

#### Scenario: Intento de sobrescribir evidencia

- **WHEN** una ejecución v1.4.1 intenta escribir sobre pesos, reportes o manifiestos v1.4.0
- **THEN** la operación se rechaza y crea artefactos bajo una identidad de ciclo distinta

### Requirement: G0 v1.4.1 previo al entrenamiento

G0 v1.4.1 SHALL fijar antes del entrenamiento cuatro clases técnicas PlantVillage: `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT`, `POTATO_HEALTHY` y `OTHER_CROP`. TRAIN SHALL contener respectivamente 541/136, 499/129, 80/20 y 503/127 fotos originales/grupos `leaf_id`; VAL SHALL conservar respectivamente 165/42, 153/39, 28/7 y 150/38. Los grupos y SHA-256 SHALL ser disjuntos entre TRAIN y VAL.

#### Scenario: Preflight conforme a G0

- **WHEN** se valida el manifiesto v1.4.1 antes de entrenar
- **THEN** reproduce 1.623 fotos / 412 grupos en TRAIN y 496 fotos / 126 grupos en VAL con los conteos por estrato fijados y sin solapamientos

#### Scenario: Otro cultivo ausente o mezclado

- **WHEN** TRAIN no contiene exactamente 503 imágenes / 127 grupos `OTHER_CROP`, una fila usa un grupo `fallback_*` o un grupo/hash cruza TRAIN y VAL
- **THEN** la compuerta bloquea el entrenamiento sin corregir conteos ni particiones silenciosamente

### Requirement: Muestreo balanceado por cuatro clases y grupos

Cada época v1.4.1 SHALL seleccionar exactamente 80 muestras de cada clase técnica, para 320 exposiciones totales, mediante clase → `leaf_id` → imagen original. La selección SHALL registrar semilla, originales y grupos disponibles/expuestos por clase y SHALL NOT contar vistas de una misma hoja como grupos independientes.

#### Scenario: Época balanceada reproducible

- **WHEN** dos ejecuciones usan el mismo manifiesto, configuración y semilla
- **THEN** producen el mismo orden de 320 exposiciones, 80 por clase, y el mismo expediente de originales y grupos

#### Scenario: Sampler inválido

- **WHEN** una clase está vacía, usa grupos no verificables o una época expone una cantidad distinta de 80 por clase
- **THEN** la ejecución falla antes de actualizar pesos y no presenta la época como válida

### Requirement: Separación entre salida técnica y diagnóstico publicable

El modelo SHALL producir cuatro puntuaciones técnicas, pero únicamente `POTATO_EARLY_BLIGHT` y `POTATO_LATE_BLIGHT` SHALL ser diagnósticos publicables. Si la decisión técnica selecciona `POTATO_HEALTHY` o `OTHER_CROP`, o ninguna enfermedad supera la política de confianza congelada, el resultado visible SHALL ser `NO_CONCLUYENTE` con un `reason_code` de rechazo; ninguna condición de rechazo SHALL aparecer como enfermedad o recomendación.

#### Scenario: Argmax de papa sana

- **WHEN** `POTATO_HEALTHY` es la salida técnica seleccionada
- **THEN** Diagnosis recibe una abstención técnica y publica `NO_CONCLUYENTE`, nunca `POTATO_HEALTHY`

#### Scenario: Argmax de otro cultivo

- **WHEN** `OTHER_CROP` es la salida técnica seleccionada
- **THEN** Diagnosis publica `NO_CONCLUYENTE` con motivo fuera de cobertura y no consulta catálogo de enfermedad

#### Scenario: Tizón por encima de umbral

- **WHEN** uno de los dos tizones es seleccionado y satisface calibración, umbral, política activa y catálogo revisado
- **THEN** puede publicarse únicamente ese tizón conforme a las compuertas existentes

### Requirement: Contrato de bundle de cuatro salidas

El contrato del bundle SHALL representar exactamente las cuatro salidas técnicas v1.4.1 y SHALL declarar por separado el conjunto publicable de exactamente dos tizones. La validación SHALL exigir preprocesado, calibración, política de rechazo y hashes congelados, y SHALL rechazar bundles o políticas que omitan una salida técnica, publiquen `POTATO_HEALTHY`/`OTHER_CROP` o atribuyan aprobación G2 inexistente.

#### Scenario: Bundle técnico válido antes de G2

- **WHEN** se valida un bundle congelado v1.4.1 con cuatro salidas, dos publicables, hashes completos y estado previo a EXTERNAL
- **THEN** el contrato lo acepta como candidato privado sin activarlo ni atribuirle aprobación G2

#### Scenario: Condición de rechazo publicable

- **WHEN** el mapa o política incluye `POTATO_HEALTHY` u `OTHER_CROP` entre las clases aprobadas para publicación
- **THEN** la validación contractual falla

### Requirement: Selección exclusiva con PlantVillage VAL

Pesos por época, estrategia de balance, calibración, ruta de rechazo y umbral SHALL seleccionarse únicamente con PlantVillage TRAIN/VAL v1.4.1. El TEST histórico y Sikkim EXTERNAL SHALL NOT participar en entrenamiento, calibración, selección ni desempate. Las métricas VAL SHALL contar la abstención de un tizón como falso negativo y SHALL conservar los mínimos v1.4.0: F1 macro ≥0,80; recall de cada tizón ≥0,80; cobertura ≥0,70; error selectivo ≤0,10; papa sana publicada ≤2/28; otro cultivo publicado ≤7/150; ECE ≤0,15.

#### Scenario: Selección conforme

- **WHEN** finaliza la comparación v1.4.1
- **THEN** el expediente demuestra que cada decisión proviene de TRAIN/VAL, publica numeradores y denominadores y solo declara elegible un candidato que satisface todas las mínimas

#### Scenario: Intento de usar evidencia sellada

- **WHEN** entrenamiento o selección intenta leer un SHA, ruta, predicción o métrica del TEST histórico o de Sikkim EXTERNAL
- **THEN** la compuerta rechaza la ejecución antes de leer bytes y conserva EXTERNAL sellado

### Requirement: Congelamiento previo a EXTERNAL

Un candidato v1.4.1 SHALL congelar pesos, configuración, mapa técnico/publicable, preprocesado, calibración, umbral, manifiestos, dependencias y comandos antes de solicitar acceso a EXTERNAL. Los criterios EXTERNAL y la unidad de independencia por imagen aprobados en G0 v1.4.0 SHALL permanecer sin cambios; un candidato que no supera VAL SHALL NOT habilitar EXTERNAL.

#### Scenario: Candidato VAL no elegible

- **WHEN** cualquier mínima VAL falla
- **THEN** no se crea un congelamiento habilitante, G2 permanece abierto y Sikkim continúa sellado

#### Scenario: Candidato VAL elegible

- **WHEN** todas las mínimas VAL pasan y la carga independiente reproduce todos los hashes
- **THEN** se registra un bundle congelado previo a EXTERNAL sin abrirlo ni evaluarlo automáticamente
