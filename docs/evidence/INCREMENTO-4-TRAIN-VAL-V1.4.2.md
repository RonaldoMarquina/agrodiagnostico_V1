# Resultado TRAIN/VAL v1.4.2 — transferencia ImageNet

Fecha: 2026-11-23. Alcance: selección exclusiva con PlantVillage TRAIN/VAL.
Sikkim EXTERNAL y TEST histórico no se montaron ni se abrieron.

## Resultado

La única corrida preregistrada completó HEAD 3 épocas y FINE_TUNE 12 épocas,
con 320 exposiciones por época (80 por cada clase técnica). La época 13 de
FINE_TUNE fue seleccionada únicamente por VAL. Temperatura 0,50 y umbral 0,80.

| Criterio VAL | Resultado | Límite | Estado |
| --- | ---: | ---: | --- |
| F1 macro de tizones | 0,9919 | ≥ 0,80 | cumple |
| Recall temprano | 164/165 = 0,9939 | ≥ 0,80 | cumple |
| Recall tardío | 149/153 = 0,9739 | ≥ 0,80 | cumple |
| Cobertura | 313/318 = 0,9843 | ≥ 0,70 | cumple |
| Error selectivo | 0/313 = 0 | ≤ 0,10 | cumple |
| Sana publicada como tizón | 0/28 | ≤ 2/28 | cumple |
| Otro cultivo publicado como tizón | 0/150 | ≤ 7/150 | cumple |
| ECE cuatro clases | 0,0069 | ≤ 0,15 | cumple |

Matriz visible: temprano 164 temprano/1 abstención; tardío 149 tardío/4
abstenciones; papa sana 28 abstenciones; otro cultivo 150 abstenciones. No hubo
confusión publicada entre tizones ni falsos aceptados de los estratos de
rechazo. Latencia CPU batch 1: mediana 4,4429 ms, p95 4,8259 ms y máximo
5,4777 ms. Pico RSS del proceso: 3.383,52 MB.

## Métricas por época

| Época | Fase | Pérdida | F1 macro | Recall temprano | Recall tardío | Sana pub. | Otro pub. | Umbral |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | HEAD | 0,57297 | 0,9367 | 0,8182 | 0,9542 | 0 | 0 | 0,85 |
| 2 | HEAD | 0,12562 | 0,9439 | 0,8909 | 0,9085 | 1 | 0 | 0,95 |
| 3 | HEAD | 0,07822 | 0,9887 | 0,9879 | 0,9739 | 0 | 0 | 0,65 |
| 4 | FINE_TUNE | 0,05729 | 0,9805 | 0,9758 | 0,9542 | 0 | 0 | 0,90 |
| 5 | FINE_TUNE | 0,03762 | 0,9798 | 0,9939 | 0,9281 | 0 | 0 | 0,90 |
| 6 | FINE_TUNE | 0,04506 | 0,9781 | 0,9939 | 0,9216 | 0 | 0 | 0,95 |
| 7 | FINE_TUNE | 0,03350 | 0,9885 | 0,9939 | 0,9608 | 0 | 0 | 0,85 |
| 8 | FINE_TUNE | 0,04380 | 0,9783 | 1,0000 | 0,9281 | 0 | 0 | 0,85 |
| 9 | FINE_TUNE | 0,03306 | 0,9885 | 0,9939 | 0,9608 | 0 | 0 | 0,85 |
| 10 | FINE_TUNE | 0,03387 | 0,9885 | 0,9939 | 0,9608 | 0 | 0 | 0,90 |
| 11 | FINE_TUNE | 0,02311 | 0,9820 | 0,9818 | 0,9477 | 0 | 0 | 0,95 |
| 12 | FINE_TUNE | 0,01650 | 0,9871 | 0,9818 | 0,9673 | 0 | 0 | 0,95 |
| 13 | FINE_TUNE | 0,02958 | 0,9919 | 0,9939 | 0,9739 | 0 | 0 | 0,80 |
| 14 | FINE_TUNE | 0,01841 | 0,9888 | 0,9818 | 0,9739 | 0 | 0 | 0,95 |
| 15 | FINE_TUNE | 0,01624 | 0,9903 | 0,9879 | 0,9739 | 0 | 0 | 0,95 |

## Integridad y congelamiento

- Peso ajustado: `e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c`.
- Reporte VAL: `1852cfe94f70a48a113704be707f19fc06dd02a1616f128966a8d06e2389f5f9`.
- Experimento privado: `085e84aadecb8184d3e353dbef247f15c37b5ab28c528a40a4c9afe26d497db8`.
- Freeze privado: `07ef4eac80f59b7ca1fc42031092f3353e7e2dd89d6c8c8c17fda4865c85110a`.
- La carga independiente verificó todos los hashes y el mapa: sano, otro
  cultivo y baja confianza producen `NO_CONCLUYENTE`.

El bundle está congelado solo como candidato pre-EXTERNAL. G2 permanece abierto,
Sikkim sigue sellado, TEST histórico permanece intacto y el worker real no se
activó. El uso está limitado a investigación/educación académica no comercial.

Verificación posterior al congelamiento: el sello Sikkim conserva SHA-256
`ab0e7e7c8a28a70a5bce4fd6424912454e2a31b31f463406233d811ed3f9a69a`.
Los tres artefactos TEST v1.3.2 conservan, respectivamente,
`7f0b829275d689b5beec0f6c9e2b471d53653881dc57fb52cce12ebc2aa11d41`,
`45df0b5db672a2be08beafc728caa1e7a4e844619cc041cd0f14f48cdf55f4c1`
y `9a01cfc295f163fb09ddf14c4e66d83831a12ec406f76a06f22b6738cc4f2902`,
iguales a su evidencia histórica.

La comparación con v1.4.1 usa únicamente su resumen fijado SHA-256
`d63d1424…6a6e3f`; no cargó pesos ni predicciones históricas. Es una comparación
de configuraciones completas, no una ablación causal aislada de ImageNet.
