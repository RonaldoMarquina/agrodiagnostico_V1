# Proposal

## Why

El EXTERNAL sustituto v1.4.3 ya cuenta con 350 imágenes admitidas, preflight
completo, límites aprobados y sello inmutable, pero G2 sigue abierto hasta
ejecutar una única evaluación con el freeze v1.4.2 y el decodificador compatible
v1.4.3. La apertura debe ser irreversible, verificable y ajena a cualquier
selección de parámetros.

## What Changes

- Autorizar una sola apertura del EXTERNAL v1.4.3 sellado con propósito
  `FINAL_EXTERNAL_EVALUATION`.
- Verificar antes de inferir los hashes de bundle, pesos, contrato de
  preprocesado, protocolo, manifiesto, preflight y sello.
- Evaluar las 350 imágenes en CPU, sin red, entrenamiento, recalibración ni
  cambio de temperatura o umbral.
- Publicar métricas, numeradores, denominadores, abstenciones, matriz visible,
  latencia, memoria y hashes de la ejecución.
- Cerrar G2 solo si se cumplen simultáneamente todos los límites aprobados; un
  fallo conserva la evidencia y mantiene G2 y el worker real abiertos/inactivos.
- Mantener Sikkim fuera de la ejecución y de toda evidencia nueva.

## Capabilities

### New Capabilities

- `external-model-evaluation-and-g2`: apertura única de un EXTERNAL sellado,
  evaluación inmutable de un freeze y decisión G2 por conjunción estricta.

### Modified Capabilities

Ninguna.

## Impact

Afecta herramientas privadas de `ml/`, pruebas de compuertas, evidencia del
incremento 4 y documentación de estado. No modifica contratos HTTP o eventos,
no cambia el modelo congelado y no activa inferencia real, política ni G3.
