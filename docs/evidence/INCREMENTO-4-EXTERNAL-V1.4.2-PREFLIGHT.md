# Preflight de evaluación EXTERNAL v1.4.2

Fecha: 2026-11-23. Estado: `READY_EXTERNAL_NOT_OPENED`.

## Identidades fijadas

- Freeze: `07ef4eac80f59b7ca1fc42031092f3353e7e2dd89d6c8c8c17fda4865c85110a`.
- Pesos: `e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c`.
- Manifiesto Sikkim: `3c8d95e9e4d198dedf821133cb4d5f0c119a327b496396c25d4b71a493580992`.
- Sello Sikkim: `ab0e7e7c8a28a70a5bce4fd6424912454e2a31b31f463406233d811ed3f9a69a`.
- Protocolo G0: `e3dad24755550c574f33c5fa5b736eec639c9a36b054fcb3fee9e2c3e96550af`.
- ZIP original: `5288c8f9d4628049ae1f827c961dc3df97167de294cec020cbce0bc19b2574dc`.

El evaluador no acepta parámetros alternativos. Usa cuatro logits, temperatura
0,50, umbral 0,80 y el preprocesado congelado EXIF/RGB/resize bilineal directo
224×224/normalización ImageNet. Solo ambos tizones son publicables.

## Pruebas antes de abrir EXTERNAL

Se ejecutaron 23 pruebas en la imagen CPU del proyecto con `--network none`,
sin montar el ZIP ni el manifiesto Sikkim. Cubren freeze, sello, hashes,
propósito, salida exclusiva, rutas ZIP, publicación/abstención, denominadores,
casos frontera y decisión G2. Resultado: `OK`.

OpenSpec estricto: válido. No se ejecutó inferencia EXTERNAL, no se creó
`access.json` real y G2 continúa abierto. El siguiente paso exige commit local
de este evaluador y después una única apertura en una raíz privada nueva.

Commit local previo a la apertura:
`28d281262608d315c085d973e6e66b25e403a0de`. No se realizó push.
