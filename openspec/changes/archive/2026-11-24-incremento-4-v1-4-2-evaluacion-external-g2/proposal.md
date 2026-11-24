# Proposal

## Why

El candidato v1.4.2 cumplió todas las mínimas VAL y quedó congelado, pero no
puede aprobar G2 ni afirmar generalización hasta ejecutar exactamente una
evaluación sobre Sikkim EXTERNAL sellado. La apertura debe ser irreversible,
trazable y no debe convertir EXTERNAL en datos de selección.

## What Changes

- Autorizar una única apertura del manifiesto Sikkim sellado exclusivamente con
  el propósito `FINAL_EXTERNAL_EVALUATION` y el bundle v1.4.2 congelado.
- Verificar antes de inferir los hashes de bundle, pesos, configuración,
  preprocesado, calibración, umbral, manifiesto, sello, protocolo y archivo
  fuente.
- Ejecutar inferencia CPU sobre las 362 imágenes sin red, reentrenamiento,
  recalibración ni selección de parámetros.
- Publicar métricas con numeradores, denominadores, abstenciones, matriz de
  confusión, latencia, memoria y hashes.
- Cerrar G2 solo si se cumplen simultáneamente todos los límites externos
  aprobados; ante cualquier fallo conservar la evidencia, mantener G2 abierto y
  no activar el worker real.

## Capabilities

### New Capabilities

- `external-model-evaluation-and-g2`: apertura única de EXTERNAL sellado,
  evaluación inmutable del bundle congelado y decisión condicional de G2.

### Modified Capabilities

Ninguna.

## Impact

Afecta únicamente herramientas y evidencia privadas de `ml/`, pruebas de
compuertas y documentación del incremento 4. No modifica contratos HTTP ni de
eventos, no activa inferencia en Diagnosis y no cambia pesos o configuración del
modelo. Los artefactos privados de Sikkim y el bundle se montarán en solo
lectura; el reporte de una sola ejecución tendrá una salida nueva e inmutable.
