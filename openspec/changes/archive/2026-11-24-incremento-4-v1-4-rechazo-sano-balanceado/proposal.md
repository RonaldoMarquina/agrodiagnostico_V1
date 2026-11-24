# Proposal

## Why

El candidato v1.3.2 alcanzó las métricas de los dos tizones, pero el TEST independiente publicó tizón en 8/32 fotos sanas y solo rechazó 24/32, frente a los límites fijados de 3/32 y 29/32. El ciclo queda evaluado y no aprobado; v1.4.0 necesita corregir el desequilibrio de entrenamiento y medir la generalización una sola vez en fotografías de campo externas después del congelamiento.

## What Changes

- Conservar v1.3.2, sus commits `94b3d42` y `5f2d623`, bundle, TEST y reporte como evidencia histórica inmutable; no cambiar el umbral 0,90 ni volver a evaluar ese TEST.
- Mantener PlantVillage `color` únicamente en TRAIN/VAL, con separación por `leaf_id`, derechos y hashes ya trazables. No usar Sikkim para completar, aumentar o seleccionar esas particiones.
- Incorporar Sikkim Solanaceae Leaf Image Dataset v1, DOI `10.17632/4wz7zbk635.1`, bajo CC BY 4.0, exclusivamente como EXTERNAL sellado: 42 imágenes de tizón temprano, 76 de tizón tardío, 50 de papa sana y 194 de tomate/pimiento como `OTHER_CROP`. Su unidad declarada es la imagen única; la fuente no permite afirmar independencia por planta.
- Fijar G0 v1.4.0 antes del entrenamiento con F1 macro EXTERNAL ≥0,75; recall EXTERNAL ≥0,75 para cada tizón —mínimo 32/42 temprano y 57/76 tardío—; máximo 5/50 sanas publicadas como tizón, mínimo 45/50 sanas en `NO_CONCLUYENTE` y máximo 9/194 de otro cultivo publicadas como tizón. Una abstención sobre un tizón cuenta como falso negativo para su recall.
- Preparar entrenamiento balanceado entre `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT` y `POTATO_HEALTHY`, mediante ponderación de clases o muestreo balanceado documentado; aplicar aumentos de papa sana solo en TRAIN.
- Seleccionar arquitectura, calibración, política de rechazo y umbral únicamente con TRAIN/VAL admitidos. Congelar el bundle antes de abrir EXTERNAL y evaluarlo una sola vez, sin ajustar después pesos, calibración, preprocesado ni umbral con sus resultados.
- Mantener como únicas clases publicables los dos tizones. Papa sana y otro cultivo siguen siendo condiciones técnicas de rechazo que deben terminar en `NO_CONCLUYENTE` cuando la política funciona.
- Rechazar cualquier fotografía obtenida de búsquedas web si no registra licencia aplicable, autor, enlace de origen y SHA-256; una URL pública por sí sola no acredita derechos ni procedencia.

## Capabilities

### New Capabilities

- `balanced-potato-rejection-cycle`: gobierno de v1.4.0, balance de entrenamiento, aumentos restringidos a TRAIN, selección exclusiva con VAL, congelamiento y evaluación única con Sikkim EXTERNAL.

### Modified Capabilities

- `dataset-inventory`: inventario y admisión por archivo y grupo para TRAIN/VAL y por imagen única para Sikkim EXTERNAL, con derechos, hashes, deduplicación y separación explícita de toda evidencia histórica.

## Impact

La futura implementación afectará inventarios y manifiestos privados en `ml/`, entrenamiento y evaluación CPU, contratos del bundle y política, y el adaptador de `services/ai_inference/` únicamente después de G2. Esta propuesta no entrena, no abre EXTERNAL y no activa el worker. Antes de entrenar aún se deben materializar el expediente por archivo de Sikkim, admitirlo para evaluación, sellar EXTERNAL y versionar el protocolo G0 aprobado sin modificar la evidencia histórica.
