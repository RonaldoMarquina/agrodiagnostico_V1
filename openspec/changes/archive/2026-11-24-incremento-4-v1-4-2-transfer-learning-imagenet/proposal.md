# Proposal

## Why

El candidato aleatorio v1.4.1 no fue elegible en VAL: obtuvo recall temprano 107/165 y publicó tizón en 9/28 papas sanas. Antes de cambiar datos, G0 o criterios, v1.4.2 debe comprobar si una inicialización oficial ImageNet y un ajuste en dos fases mejoran ambas condiciones usando exactamente el mismo TRAIN/VAL y sin abrir evidencia final.

## What Changes

- Conservar G0/G1 v1.4.1, sus límites, manifiestos y topología de cuatro clases sin cambios.
- Conservar los commits `7377819` y `e709f27`, pesos, predicciones y resultado v1.4.1 como evidencia histórica de la inicialización aleatoria; no reentrenarla ni sobrescribirla.
- Registrar antes de entrenar la procedencia de `MobileNet_V3_Small_Weights.IMAGENET1K_V1`: versión de TorchVision, URL oficial, receta, transformaciones, licencia del código, condiciones derivadas de ImageNet, tamaño y SHA-256 verificado del archivo descargado explícitamente.
- Bloquear el entrenamiento si la descarga no coincide con `mobilenet_v3_small-047dcff4.pth` y el SHA-256 completo esperado, o si el expediente de términos no limita el uso al ámbito admitido.
- Entrenar un candidato MobileNetV3-Small de cuatro salidas mediante una fase de cabeza congelando el backbone y una fase posterior de fine tuning con tasa baja, siempre con sampler 80×4 y aumentos únicamente para `POTATO_HEALTHY` TRAIN.
- Seleccionar época, calibración y umbral solo con las 496 filas VAL y comparar con v1.4.1 únicamente mediante su resumen histórico fijado.
- Mantener Sikkim EXTERNAL sellado, TEST histórico inaccesible, dos diagnósticos publicables y todas las mínimas VAL vigentes.

## Capabilities

### New Capabilities

- `transfer-learning-model-selection`: procedencia verificable de pesos oficiales, entrenamiento de cabeza/fine tuning, comparación VAL contra una línea base histórica y congelamiento condicionado sin acceso a TEST/EXTERNAL.

### Modified Capabilities

Ninguna. G0, inventario de datos, diagnósticos publicables y contratos externos permanecen sin cambios.

## Impact

La futura implementación afectará registros privados de pesos base, configuración y validadores ML, construcción/carga segura de MobileNetV3-Small, comandos offline de entrenamiento, pruebas y expediente TRAIN/VAL. No cambia OpenAPI ni eventos, no descarga durante el proceso de entrenamiento, no abre Sikkim, no reutiliza TEST, no activa el worker y no altera los commits históricos.
