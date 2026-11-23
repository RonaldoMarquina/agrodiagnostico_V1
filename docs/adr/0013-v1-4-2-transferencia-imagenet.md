# ADR 0013: transferencia ImageNet aislada para v1.4.2

- Estado: aceptado antes del entrenamiento
- Fecha: 2026-11-23
- Responsable: responsable del proyecto AgroDiagnóstico V1

## Contexto

v1.4.1 mantuvo cuatro clases técnicas y el sampler 80×4, pero su modelo con
inicialización aleatoria no cumplió VAL: recall de tizón temprano 107/165 y
9/28 hojas sanas publicadas como tizón. El ciclo terminó sin bundle congelado.
G0, G1, los conteos y las mínimas no cambian para v1.4.2.

## Decisión

Comparar el resumen histórico inmutable de v1.4.1 con un MobileNetV3-Small
inicializado exclusivamente desde el checkpoint oficial TorchVision
`MobileNet_V3_Small_Weights.IMAGENET1K_V1`. El archivo se descarga en un paso
explícito, se verifica por tamaño y SHA-256 completo y después el entrenamiento
opera sin red. HEAD ajusta solo la cabeza durante 3 épocas; FINE_TUNE ajusta la
cabeza y los últimos tres bloques durante 12 épocas, conservando BatchNorm
congelado. La arquitectura produce cuatro logits, pero solo ambos tizones son
publicables.

El preprocesado compartido conserva el contrato v1.4.1: EXIF, RGB, resize
directo 224×224 y normalización ImageNet. Se registra que la transformación de
referencia de esos pesos usa resize 256 y center crop 224; la diferencia
geométrica queda fijada antes del entrenamiento y la selección sigue siendo
exclusivamente mediante VAL.

## Derechos y límites

El código de TorchVision usa BSD-3-Clause. Esa licencia no se atribuye al
checkpoint ni a ImageNet. ImageNet permite el uso de sus imágenes para
investigación y educación no comercial y no garantiza derechos sobre cada
imagen. Por prudencia, el ciclo y cualquier bundle resultante quedan limitados
a investigación/educación académica no comercial. El checkpoint no se
redistribuye en Git ni con los artefactos del proyecto.

## Consecuencias

- Sikkim EXTERNAL y TEST históricos permanecen desmontados y sellados.
- Los commits `7377819` y `e709f27`, G0/G1 y el resultado v1.4.1 se verifican por
  hash y no se reescriben.
- Solo se congela un candidato si todas las mínimas VAL vigentes pasan.
- Esta comparación evalúa configuraciones completas (GroupNorm aleatorio frente
  a BatchNorm preentrenado), no demuestra causalidad aislada de la
  inicialización.
