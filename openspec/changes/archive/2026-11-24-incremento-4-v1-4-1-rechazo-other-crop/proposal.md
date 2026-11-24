# Proposal

## Why

La comparación v1.4.0 dejó a su líder relativo con 83/150 imágenes `OTHER_CROP` publicadas como tizón, frente al máximo VAL de 7/150. Como `OTHER_CROP` solo participaba en VAL, el modelo no aprendió esa condición de rechazo; v1.4.1 debe incorporarla como cuarta clase técnica usando exclusivamente los datos PlantVillage TRAIN ya admitidos antes de volver a entrenar.

## What Changes

- Conservar v1.4.0 como ciclo medido y no elegible, incluidos sus pesos, reportes, manifiestos y decisión `BLOCKED_NO_CANDIDATE_PASSES_VAL`; no reetiquetar ni sobrescribir esa evidencia.
- Versionar G0 v1.4.1 antes del entrenamiento con cuatro clases técnicas: `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT`, `POTATO_HEALTHY` y `OTHER_CROP`.
- Admitir en TRAIN las 503 imágenes originales / 127 grupos `leaf_id` de otro cultivo de PlantVillage y conservar separadas las 150 imágenes / 38 grupos de VAL.
- Entrenar MobileNetV3-Small con un sampler consciente de `leaf_id`, exactamente 80 muestras por cada clase técnica y 320 muestras por época.
- Mantener como únicos diagnósticos publicables los dos tizones; `POTATO_HEALTHY` y `OTHER_CROP` son logits técnicos de rechazo y se transforman en `NO_CONCLUYENTE`, nunca en clases visibles.
- Seleccionar pesos, calibración, ruta de rechazo y umbral exclusivamente con PlantVillage TRAIN/VAL. Mantener los mínimos VAL y los criterios EXTERNAL aprobados en v1.4.0 salvo nueva decisión explícita previa al entrenamiento.
- Extender el contrato del bundle para representar cuatro salidas técnicas y distinguirlas de las dos clases publicables, con pruebas que rechacen políticas capaces de publicar `POTATO_HEALTHY` u `OTHER_CROP`.
- Conservar Sikkim EXTERNAL sellado y sin acceso durante entrenamiento, calibración o selección. El TEST histórico v1.3.2 tampoco participa en la solución.

## Capabilities

### New Capabilities

- `four-class-potato-rejection-cycle`: gobierno G0 v1.4.1, entrenamiento balanceado de cuatro clases técnicas, selección exclusiva con VAL, contrato técnico/publicable y congelamiento previo a cualquier apertura de EXTERNAL.

### Modified Capabilities

- `dataset-inventory`: admitir `OTHER_CROP` de PlantVillage como clase técnica de rechazo en TRAIN y VAL con conteos y grupos fijados, sin convertirla en diagnóstico soportado ni mezclar Sikkim.

## Impact

La implementación futura afectará el protocolo y estado de compuertas en `ml/evaluation/`, manifiestos privados PlantVillage, configuración y sampler en `ml/`, el esquema `contracts/ml/model-bundle.v1.schema.json`, validadores y pruebas de contratos, ADR/evidencias y las tareas del incremento 4. No cambia los contratos HTTP o eventos públicos, no entrena en esta propuesta, no abre Sikkim, no reusa el TEST histórico y no activa el worker real.
