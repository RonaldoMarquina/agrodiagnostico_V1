# TRAIN/VAL v1.4.0 — comparación balanceada y decisión de no congelar

Fecha: **2026-11-22** (America/Lima). Alcance: **PlantVillage TRAIN/VAL únicamente**. Estado: **dos candidatos evaluados; ninguno elegible; bundle no congelado; EXTERNAL no abierto**.

## Ejecución fijada

El código y el plan ejecutados están fijados por el commit local `bd9df36cf0573730ea37704987cedd7f2177a5a8`. Ambos candidatos usaron MobileNetV3-Small con inicialización aleatoria, GroupNorm, semilla 42, 10 épocas, cuatro hilos CPU y el mismo preprocesado. No hubo pesos descargados ni red.

- Protocolo G0 SHA-256: `e3dad24755550c574f33c5fa5b736eec639c9a36b054fcb3fee9e2c3e96550af`.
- Plan SHA-256: `04a45a9425b99ca47e9048c5d91ac42f1fe65565a2381e18413a39ae6e20f263`.
- Manifiesto G1 PlantVillage SHA-256: `b7bcdc87b1ae252c55370b1354c579c4b0fa80da962ce47b83c7a28ca66824e1`.
- Manifiesto TRAIN derivado SHA-256: `b1d4b3fc51b4ff8b7883d798b06151e0c00c08d446d336104397cc74659244c5`.
- Manifiesto VAL derivado SHA-256: `ad03daf0105262564b40018b90b4ca07ecb7e214b6af5853df8a552b55f08d8b`.
- Expediente comparativo privado `.local/ml-v1.4.0-train-val/comparison.json`, SHA-256 `06500735222e3534af7e5631e690470a331fccbe73f641354378451409c035ec`.

Los contenedores se ejecutaron con `--network none`. Solo se montaron el código, el plan, el protocolo, el estado G1, el manifiesto y comprobante PlantVillage y los bytes locales referenciados por ese manifiesto. El manifiesto y los bytes Sikkim no se montaron. La búsqueda posterior no encontró rutas, nombres ni hashes Sikkim en los expedientes de los candidatos.

Una primera corrida detectó que el desempate provisional podía preferir la abstención total cuando ningún punto cumplía todas las mínimas. Esa salida quedó en cuarentena privada y no participa en esta comparación. El selector se corrigió para minimizar primero el incumplimiento normalizado de las mínimas y aplicar las prioridades después; las dos corridas oficiales se repitieron desde el commit fijado.

## Estrategias y exposición efectiva

1. `weighted-cross-entropy-full-train`: los 1.120 originales se recorrieron una vez por época, con pesos `N/(K*n_clase)` de 0,6900800986, 0,7481629927 y 4,6666666667. Cada época expuso 541/136 imágenes/grupos de tizón temprano, 499/129 de tizón tardío y 80/20 de papa sana.
2. `group-aware-balanced-sampler`: cada época seleccionó clase, `leaf_id` y luego una vista original. Expuso exactamente 80 muestras por clase y 240 totales. En cada época usó 80 grupos distintos de temprano, 80 de tardío y los 20 grupos sanos cuatro veces cada uno; nunca contó una vista aumentada como original o grupo.

Solo las muestras `POTATO_HEALTHY` de TRAIN recibieron flip, rotación y jitter conservador deterministas. VAL permaneció sin aumentos. La semilla de cada vista y la exposición por original/grupo están en `experiment.json` de cada candidato.

## Pérdida y recursos

| Estrategia | Pérdida media por época (1→10) | Tiempo total | Pico RSS entrenamiento | Latencia CPU VAL mediana / p95 / máx. |
| --- | --- | ---: | ---: | ---: |
| Ponderada | 1,1231; 0,7116; 0,4813; 0,3158; 0,1933; 0,1825; 0,1369; 0,1491; 0,1008; 0,1063 | 90,80 s | 1.583,67 MB | 4,12 / 4,41 / 4,91 ms |
| Sampler por grupo | 1,1483; 1,0720; 0,7793; 0,6022; 0,4641; 0,2946; 0,4002; 0,2066; 0,2705; 0,1059 | 29,39 s | 2.990,46 MB | 4,05 / 4,65 / 5,36 ms |

Entorno: AMD Ryzen 7 5800XT, Python 3.12.14, PyTorch 2.15.0+cpu, torchvision 0.29.2+cpu, Pillow 12.3.0 y safetensors 0.8.0. El RSS corresponde al proceso completo de entrenamiento, incluidos tensores TRAIN/VAL residentes; no sustituye la medición de memoria de un bundle independiente.

## Resultados VAL seleccionados

| Métrica | Ponderada, época 10 | Sampler, época 10 | Mínimo VAL |
| --- | ---: | ---: | ---: |
| F1 macro de tizones | **0,8075** | 0,7856 | ≥0,80 |
| Recall temprano | **142/165 = 0,8606** | **154/165 = 0,9333** | ≥0,80 |
| Recall tardío | **135/153 = 0,8824** | 110/153 = 0,7190 | ≥0,80 |
| Cobertura de tizones | **284/318 = 0,8931** | **268/318 = 0,8428** | ≥0,70 |
| Error selectivo | **7/284 = 0,0246** | **4/268 = 0,0149** | ≤0,10 |
| Papa sana publicada como tizón | **1/28** | 5/28 | ≤2/28 |
| Otro cultivo publicado como tizón | 83/150 | 82/150 | ≤7/150 |
| ECE técnico | **0,0166** | **0,0173** | ≤0,15 |

La opción ponderada seleccionó temperatura 1,50, ruta `ARGMAX_CONFIDENCE` y umbral 0,90. La opción balanceada seleccionó temperatura 1,25, la misma ruta y umbral 0,90. Las abstenciones de tizones se contabilizaron como falsos negativos en recall y F1.

Matrices visibles, filas reales y columnas temprano / tardío / `NO_CONCLUYENTE`:

| Estrato real | Ponderada | Sampler por grupo |
| --- | --- | --- |
| Tizón temprano | 142 / 4 / 19 | 154 / 1 / 10 |
| Tizón tardío | 3 / 135 / 15 | 3 / 110 / 40 |
| Papa sana | 0 / 1 / 27 | 0 / 5 / 23 |
| Otro cultivo | 39 / 44 / 67 | 12 / 70 / 68 |

Pesos y reportes privados:

| Estrategia | Pesos SHA-256 | Reporte VAL SHA-256 | Configuración SHA-256 |
| --- | --- | --- | --- |
| Ponderada | `fea1fae23b20432f17b46c53a57bd2b486f388a428c84e0ca44171dc20ccd947` | `4fcd4fe37ba2219d4e82528d0d2b6a2e15a8e35f318f7ea8c1e1276eb9b01783` | `8bcfc2336db3dc314a64d90db85a2fdb2bd01769d7071130b9f9c8677065d347` |
| Sampler | `5a2827817de5c5edc15b2ec23f90fedafb85e6b6bedb92e63e3877cf17f4da4c` | `b09a3e58ca39b96e7245112babe84df57b5b7ead27bde9e67058cabd05dc3130` | `4d860a1b56b89cd8d909b8a25b0557796301675b5d4b36718d9b5c9a3051cafc` |

## Decisión

La estrategia ponderada es el **líder relativo**, pero no es un candidato ganador elegible: falla el rechazo de otro cultivo por 76 publicaciones sobre el máximo permitido. El sampler falla rechazo sano, F1 macro, recall tardío y rechazo de otro cultivo. El resultado formal es `BLOCKED_NO_CANDIDATE_PASSES_VAL`.

No se creó `freeze.json`, bundle, calibración o umbral promovible; G2 permanece abierto. Sikkim EXTERNAL sigue sellado y no puede abrirse con estos artefactos. Corregir este bloqueo requiere un nuevo plan previo a EXTERNAL —por ejemplo, una estrategia de rechazo fuera de distribución aprendida sin usar Sikkim— y otra comparación exclusivamente en TRAIN/VAL.
