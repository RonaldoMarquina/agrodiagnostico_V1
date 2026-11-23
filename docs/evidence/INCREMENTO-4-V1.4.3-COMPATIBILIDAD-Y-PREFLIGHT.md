# Compatibilidad operativa y preflight v1.4.3

Fecha: 2026-11-23. Estado: decodificador y compuerta implementados; EXTERNAL
nuevo admitido por archivo, con preflight completo y sellado. G0 v1.4.3 fue
aprobado por el responsable antes del sello; todavía no se ha abierto para
inferencia.

## Diagnóstico inmutable del fallo v1.4.2

La inspección se limitó a SHA-256 y metadatos de decodificación de las 362
entradas Sikkim ya selladas. No cargó el modelo, no produjo logits,
predicciones o métricas y no reconstruyó resultados parciales.

| Formato detectado | Modo | Archivos |
| --- | --- | ---: |
| JPEG | RGB | 360 |
| MPO | RGB | 2 |

La primera incompatibilidad estaba en el índice 127:

- ruta registrada: `Potato_Field_Dataset/potato (36).JPG`;
- SHA-256: `8e0993659311bde40bca316cb6f6721055eb76a1e012a3d970c511551cb2297f`;
- dimensiones: 6000×4000;
- contenedor real/modo: `MPO/RGB`.

La extensión `.JPG` no describía el contenedor real. Los 362 objetos podían
convertirse a RGB, pero la allowlist v1.4.2 rechazaba `MPO` antes de esa
conversión. La causa no fue `CMYK`, `RGBA`, `P` ni TIFF.

Sikkim conserva estado `FAILED_TECHNICAL` y queda prohibido como EXTERNAL,
TEST o entrada G2 v1.4.3. La prueba negativa v1.4.3 bloquea referencias a su
nombre, DOI y hashes antes del acceso a archivos.

## Contrato implementado

El contrato
[`potato-v143-operational-compatible.json`](../../ml/preprocessing/potato-v143-operational-compatible.json)
admite JPEG, MPO, PNG, TIFF y WEBP y los modos `1`, `L`, `LA`, `P`, `RGB`,
`RGBA`, `CMYK` e `I;16`. La secuencia es:

1. límite de bytes e identificación desde contenido;
2. verificación completa y política de frames;
3. frame 0 determinista para MPO;
4. rechazo de PNG/WEBP animado y TIFF multipágina;
5. orientación EXIF y alpha sobre blanco;
6. conversión explícita a RGB;
7. resize bilineal 224×224 y normalización ImageNet.

El contrato conserva exactamente:

- freeze v1.4.2 `07ef4eac80f59b7ca1fc42031092f3353e7e2dd89d6c8c8c17fda4865c85110a`;
- pesos `e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c`;
- MobileNetV3-Small y mapa técnico de cuatro clases;
- temperatura `0,50` y umbral `0,80`.

## Preflight previo al sello

`scripts/preflight_v143_external.py` recorre todas las filas admitidas sin
importar ni cargar pesos. Verifica procedencia mínima, licencia, ruta segura,
SHA-256, tamaño, formato, modo, frames, RGB y tensor finito 3×224×224. Solo si
todo el lote pasa escribe atómicamente `compatibility.jsonl` y
`preflight-summary.json`; un fallo no deja salida que pueda confundirse con un
preflight completo.

`scripts/seal_v143_external.py` exige manifiesto sin cambios, preflight completo
y aprobación del responsable con conteos y límites enteros exactos. El sello
declara `SEALED_NOT_OPENED_FOR_EVALUATION`; no evalúa ni calcula métricas.

## Pruebas ejecutadas

Entorno temporal limpio Python 3.12.14 creado desde `ml/uv.lock`, CPU:

```text
python -m unittest tests.ml.test_v143_preprocessing -v
Ran 9 tests — OK

python -m unittest tests.ml.test_v142_transfer tests.ml.test_v142_external tests.ml.test_torch_cpu_smoke -v
Ran 26 tests — OK
```

Las pruebas cubren un MPO real de dos frames, todos los formatos/modos
admitidos, alpha, regresión tensorial RGB v1.4.2, entradas corruptas o
multiframe, cardinalidad completa, hashes, veto Sikkim y sello condicionado.
No cambió ninguna dependencia del lock.

## Auditoría de fuentes y decisiones por archivo

La revisión exacta de **PLDD-UP v1**, DOI `10.17632/3j4nfkvp2n.1`, verificó
los tres ZIP oficiales y sus SHA-256. Sus 15.519 archivos decodificaron, pero
la licencia de portada no se tomó como admisión automática. El inventario
privado por SHA produjo:

| Decisión PLDD-UP | Archivos |
| --- | ---: |
| Candidatos antes de revisión interna | 12.420 |
| Dimensiones fuera del contrato | 2.608 |
| Filas excluidas por hash repetido | 469 |
| Cercanos visuales a TRAIN/VAL | 22 |

El inventario completo tiene SHA-256
`1e7970be9ceb0fc777c25b1ec763159fe292b34b4d5b6b291b8d8dfcd479c715`.
Se declararon únicamente imágenes únicas; PLDD-UP no aporta identificador de
planta o sesión.

El `Raw_Dataset` de **Pota-Toma-To v1** contenía 435 JPEG/RGB y su copia
procesada otros 435 derivados. Fue excluido entero: los directorios crudos se
identifican como resultados de Google Search y la descripción interna solo
declara agregación desde repositorios públicos, sin autor, URL ni licencia por
fotografía. Su inventario de exclusión tiene SHA-256
`c29f05aff7d6750e9a365cba232db96302022107e1ab4a6809d17db0b607a80a`.

El sustituto `OTHER_CROP` es **CornLeafDiseaseCollection v1**, DOI
`10.17632/w56xxnykcc.1`. Los autores declaran capturas propias en tres
plantaciones de Manabí y publican por archivo hash, etiqueta, bloque, variedad
y ubicación bajo CC BY 4.0. Se verificaron 1.079/1.079 JPEG/RGB; 38 archivos
correspondientes a 19 hashes repetidos quedaron excluidos. El inventario tiene
SHA-256 `911de6ada87ba64365b3a6bf6ccec6a1f38bfe9594a79d6457c68ae93f15e1b2`.

La revisión interna de hojas de contacto excluyó 42 imágenes de papa por
síntomas ambiguos, desenfoque o manchas incompatibles con el estrato sano. El
registro privado de exclusiones por SHA-256 tiene hash
`08be58381efd042a7ecea8a190fcfcdd7fb565213e87137d2707d7e29b7a5f50`.
No fue una nueva revisión agronómica independiente. Además se excluyeron 117
grupos visuales PLDD-UP que mezclaban etiquetas; ningún grupo contribuye a más
de una fila admitida.

## Manifiesto admitido y preflight real

| Fuente | Estrato | Admitidas | Unidad demostrable |
| --- | --- | ---: | --- |
| PLDD-UP v1 | `POTATO_EARLY_BLIGHT` | 50 | imagen única |
| PLDD-UP v1 | `POTATO_LATE_BLIGHT` | 50 | imagen única |
| PLDD-UP v1 | `POTATO_HEALTHY` | 50 | imagen única |
| CornLeafDiseaseCollection v1 | `OTHER_CROP` | 200 | imagen única |

Las 350 filas tienen SHA-256 y grupo visual únicos, licencia, origen, etiqueta,
decisión y motivo; la distancia dHash mínima entre pares es 7 con umbral de
exclusión ≤6. El manifiesto privado tiene SHA-256
`20e0ba6729d08920cae3b93d914ddbaaed6c44c1f3ef6dc8b5c661700bd5e9d1`.
La unidad no se presenta como independencia por planta o sesión.

El preflight recorrió 350/350 archivos: 347 `JPEG`, 3 `MPO`, todos `RGB`; para
los tres MPO eligió el frame 0. Resultado:

- `preflight-summary.json`:
  `3104fe4b42cd2166e11bea50ac1af82a2a2d9709b2043285154a86c8df8ab050`;
- `compatibility.jsonl`:
  `0e821b81fe83615d106c45b7ee5514678f3a689a7477c3c24cefaae6d79ffcc4`;
- contrato de preprocesado:
  `76debfc7c16b9d8b9567fca95012e091d0379e4d622ac21b871e9ead9ba0befb`.

El resumen declara `model_loaded=false`, `predictions_generated=false`,
`metrics_generated=false`, `external_opened_for_evaluation=false` y
`sikkim_reused=false`.

## G0 v1.4.3 aprobado y sello emitido

El [protocolo aprobado](../../ml/evaluation/protocol-g0.v1.4.3.json) conserva
F1 macro ≥0,75 y fija, a partir de los denominadores admitidos:

- recall por cada tizón ≥38/50; la abstención cuenta como falso negativo;
- papa sana publicada como tizón ≤5/50 y rechazada ≥45/50;
- otro cultivo publicado como tizón ≤10/200.

Estas cifras son criterios, no resultados obtenidos. Pesos,
arquitectura, temperatura `0,50` y umbral `0,80` siguen congelados.

El protocolo tiene SHA-256
`e5d9288c6cc7c78263d29bd311d9257df503dc39abc3eda4427ada51eee842b7`.
El sello privado y su
[copia sanitizada](../../ml/evaluation/external-seal.v1.4.3.json) tienen SHA-256
`d0c76dc4b9d398cb779d71f82e9baaa250ea8a097a2d2b3ad1a8bf89efade7d1`.
Su estado es `SEALED_NOT_OPENED_FOR_EVALUATION`, con
`opened_for_evaluation=false` y `sikkim_reused=false`.

## Estado de la compuerta

La admisión, el preflight, la aprobación y el sello están completos. El cambio
separado `incremento-4-v1-4-3-evaluacion-external-g2` controla la apertura
única. A esta altura no existen predicciones ni métricas nuevas, G2 sigue
abierto y el worker real continúa inactivo.
