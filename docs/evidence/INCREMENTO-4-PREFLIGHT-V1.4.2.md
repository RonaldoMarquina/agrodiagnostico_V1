# Preflight v1.4.2 — transferencia ImageNet

Fecha: 2026-11-23. Estado inicial: `PREFLIGHT_NOT_TRAINED`.

## Frontera heredada

v1.4.2 conserva G0/G1 v1.4.1, las cuatro clases técnicas, el sampler 80×4,
los aumentos exclusivos para papa sana en TRAIN, las dos clases publicables y
las mínimas VAL. El índice verificable está en
`ml/evaluation/v1.4.2-history-index.json`. No se reutilizan pesos ni
predicciones v1.4.1; su comparación será únicamente con el resumen agregado
fijado.

## Checkpoint preregistrado

- Proveedor: TorchVision 0.29.2+cpu.
- Enum: `MobileNet_V3_Small_Weights.IMAGENET1K_V1`.
- URL única permitida: `https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth`.
- Tamaño esperado: 10.306.551 bytes.
- SHA-256 esperado: `047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f`.
- Receta oficial: referencia TorchVision `mobilenet_v3_small`; 2.542.856 parámetros,
  acc@1 67,668 y acc@5 87,402 informados por el proveedor.

La descarga se ejecutó el 2026-11-23 a las 12:31:19 UTC. La URL final fue
idéntica a la solicitada. Se observaron exactamente 10.306.551 bytes y SHA-256
`047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f`.
La carga offline con `weights_only=True` confirmó todas las claves y dimensiones
del state dict oficial. El checkpoint quedó con permiso `0440` bajo una carpeta
privada `0550`; no se incorporó al repositorio. El expediente privado tiene
SHA-256 `9107d4ab3b8fc6c321e67c6af6ee9c8c1c331f7e2ec93b2d72c0990dfae86f30`.

## Preprocesado verificado

El contrato versionado `potato-v142-imagenet-compatible.json` comparte la misma
función entre TRAIN, VAL e inferencia: EXIF, RGB, resize bilineal directo
224×224 y normalización `[0.485, 0.456, 0.406] / [0.229, 0.224, 0.225]`.
No se afirma igualdad con el resize 256 + center crop 224 de referencia; esa
diferencia fue fijada antes de observar VAL.

## Aislamiento

La raíz privada v1.4.2 es distinta de v1.4.1. El paso de adquisición no monta
datos. El entrenamiento se ejecutará sin red y solo montará checkpoint,
TRAIN/VAL e imágenes correspondientes. Sikkim EXTERNAL y TEST histórico no se
montarán.

La compuerta real previa al entrenamiento produjo:

```json
{"base_weight_sha256":"047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f","external_accessed":false,"historical_test_accessed":false,"status":"PREFLIGHT_PASSED_NOT_TRAINED","train":{"groups":412,"photos":1623},"val":{"groups":126,"photos":496}}
```

Los commits históricos `7377819bec40d0c8c0ce3250e89164ee1adebf26` y
`e709f272fb5f07cd381b7583fdddc79b1c94fec5` se verificaron como objetos commit
en el host antes de transferir su lista exacta al contenedor sin herramientas
Git. El preflight no abrió imágenes ni creó una salida de entrenamiento.
