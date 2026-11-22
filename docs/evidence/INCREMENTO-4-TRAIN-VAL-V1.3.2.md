# Ciclo v1.3.2 — entrenamiento y selección con TRAIN/VAL

Fecha del expediente: **2026-11-22** (America/Lima). Este es el **corte anterior a TEST**, fijado en el commit `94b3d422afe4008226a70623b96824ba003cf139`: candidato congelado, G2/G3 abiertos y TEST todavía sin inferencia en ese momento. Después, [TEST se evaluó una sola vez y falló el rechazo sano](INCREMENTO-4-TEST-V1.3.2-UNICO.md). Esta evidencia usa el [G0 v1.3.2 aprobado](../../ml/evaluation/protocol-g0.v1.3.2.json) y el [G1 v1.3.1 admitido](INCREMENTO-4-G1-V1.3.1-ADMISION.md). Los resultados v1.2.0 y sus pesos no se modificaron.

## Datos, entrenamiento y trazabilidad

La red MobileNetV3-Small tiene **tres salidas técnicas**, en orden: `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT`, `POTATO_HEALTHY`. Solo las dos primeras son publicables. Las 503 fotos `OTHER_CROP` de TRAIN intervienen como *outlier exposure* sin crear una cuarta salida: la pérdida les pide distribución uniforme. La clase técnica sana con argmax produce siempre `NO_CONCLUYENTE`; una foto sana mal clasificada como tizón puede generar una falsa publicación y se cuenta como error. El modelo se inicializó aleatoriamente, con GroupNorm, semilla 42, preprocesado RGB 224 × 224, AdamW, 10 épocas, lote 16, pesos de clase `[1, 1, 6]`, peso de *outlier exposure* 1,0 y cuatro hilos CPU. La configuración exacta está en [`potato-v13-mobilenetv3-cpu.json`](../../ml/configs/potato-v13-mobilenetv3-cpu.json).

TRAIN: 541 fotos de tizón temprano, 499 de tardío, 80 sanas y 503 de otro cultivo, **1.623** en total. VAL: 165, 153, 28 y 150 respectivamente, **496** en total. Cada archivo usado en TRAIN/VAL fue comprobado contra derechos, decisión de admisión, etiqueta, grupo y SHA-256. El preflight verificó el hash del sello de TEST, sin decodificar ni inferir sus imágenes. Se leyó el manifiesto global `strata.csv` para separar filas por partición; solo se cargaron bytes de TRAIN y VAL. El script registra `test_evaluated=false`; este campo describe el alcance de la ejecución, no sustituye la auditoría del sello G1.

| Elemento | SHA-256 |
| --- | --- |
| Protocolo G0 v1.3.2 | `533a8daddba598d810cf6e46cb072a41c54ae5478bfd9ed131b39eb703bfb397` |
| Informe G1 | `71c4e34c60eb1b635da58af934b05fd1683728f895e955d8027f7652e91c7a75` |
| Sello TEST nuevo, sin evaluación | `4f0872f62b58b35df908de8dae3f0577dc425f871e0e74e7fbf26a1afe9489bc` |
| Manifiesto TRAIN extraído | `5c4436dfad44736c49d4eeb58b02c0109554923ade1e127e1e5167e592dd9274` |
| Manifiesto VAL extraído | `86140e52cec86973fc80c50eb12296664ec429a5a5cad19716849300b714c08a` |
| Configuración | `4b6236c5a86eb8a2d3fe2ac8e152f33e6c7b2efb504706208128d2f298daadf5` |
| Código de entrenamiento | `37cff72a92b464feed3c25b0b8409458a6bc077a20ddf7f69d6b816fd1bead68` |
| Lock ML | `e2962d266b7b1efde365bea3952cca71e66d15d338bc6ef0952c01bf4e2d100b` |

Entorno: Python 3.12.14; PyTorch 2.15.0+cpu; torchvision 0.29.2+cpu; Pillow 12.3.0; safetensors 0.8.0. Ejecución sin red en contenedor con 4 CPU y límite 4 GiB. Tiempo total 159,55 s; cada época, incluida VAL, tardó entre 15,50 y 16,30 s. RSS máximo de **entrenamiento**: 4.063,46 MB. El presupuesto G0 de 1.024 MB corresponde a **inferencia independiente**, medida abajo; el consumo de entrenamiento se publica por separado. La época 8 se eligió con VAL. El `experiment.json` privado registra tiempos, pérdida y RSS de cada época.

Hubo tres intentos de desarrollo, todos con TRAIN/VAL y sin TEST: una prueba inicial sin exposición a `OTHER_CROP` que no finalizó el registro y rechazaba mal ambos negativos; un segundo intento de cinco épocas que no cumplió el límite sano ni el de otro cultivo; y el intento seleccionado de diez épocas. La selección de hiperparámetros y época consumió VAL varias veces; por ello las cifras de VAL son de selección y no estiman generalización independiente.

La repetición determinista con la misma configuración produjo exactamente los mismos SHA-256 de pesos (`a55fbcbfcfc6234b6c03b20c996440768fc4b7a897631a67a96c45c0e159e361`), reporte VAL (`5c9baa2fc1c3f36fa0b25d0f55607975fb86bbbfa698cb985013db228a6585de`) y predicciones VAL (`db4d264df4330807528dd69acc8e56b72960b29a18f42b65dc53d11ba353b3de`). La repetición queda en `.local/ml-v1.3.2/mobilenetv3-ood-repeat/`; el intento elegido, en `.local/ml-v1.3.2/mobilenetv3-ood-run3/`. Los pesos y datos privados no se suben al repositorio.

## VAL y comparación de rechazo

Temperatura elegida con VAL: **1,25** por NLL técnico. Umbral visible: **0,90**. Ruta: `ARGMAX_CONFIDENCE`, que abstiene si el argmax es sana o la probabilidad de enfermedad no alcanza 0,90. Se comparó también `HEALTHY_GATE` con puerta sana 0,25, usando los **mismos pesos, logits calibrados, preprocesado, particiones y presupuesto**; ambas rutas empataron en el mejor punto de VAL. Se escogió la regla más simple. El reporte privado de comparación tiene SHA-256 `15274e8f69943f2c74027966b6f56b09a32509fa7deff890a7bbe4fb68b8bc77`; recalcula las rutas desde las probabilidades ya calibradas, por lo que su campo `temperature=1.0` representa ninguna *segunda* calibración. En el mismo contenedor CPU de cuatro hilos, sobre las 496 salidas VAL repetidas 20 veces, la decisión aislada tardó mediana/p95 **0,00134/0,00145 ms** con `ARGMAX_CONFIDENCE` y **0,00138/0,00145 ms** con `HEALTHY_GATE`, 9.920 decisiones por ruta. Ambas comparten la medición de preprocesado y modelo CPU descrita abajo; estos microtiempos no son latencia extremo a extremo.

| Métrica VAL | Resultado | Límite aplicado antes de TEST |
| --- | ---: | ---: |
| F1 macro visible de dos tizones | 0,9704 | ≥0,80 en VAL |
| Tizón temprano: verdaderos positivos / fotos; F1 | 161/165; 0,9877 | recall ≥0,80 usado conservadoramente |
| Tizón tardío: verdaderos positivos / fotos; F1 | 142/153; 0,9530 | recall ≥0,80 usado conservadoramente |
| Cobertura de positivos | 304/318 = 0,9560 | ≥0,70 |
| Error selectivo entre positivos aceptados | 1/304 = 0,0033 | ≤0,10 |
| Papa sana publicada como tizón | 2/28 = 0,0714 | ≤2/28, escala entera conservadora de 3/32 |
| Papa sana `NO_CONCLUYENTE` | 26/28 = 0,9286 | ≥26/28, escala entera conservadora de 29/32 |
| `OTHER_CROP` publicado como tizón | 0/150 = 0 | ≤0,05 |
| `OTHER_CROP` rechazado | 150/150 = 1 | ≥0,95 |
| ECE técnico en papa | 0,0224 | ≤0,15 |

De los 165 casos de tizón temprano, 3 se abstuvieron y 1 se publicó erróneamente como tardío; son **4 falsos negativos**. De los 153 tardíos, 11 se abstuvieron; son **11 falsos negativos**. Las abstenciones nunca se suman a aciertos visibles. Los falsos positivos del tardío incluyen la confusión temprana y las dos fotos sanas publicadas. Ambos conjuntos de métricas por clase y los numeradores/denominadores constan en `val-report.json` privado.

Se ejecutó el bundle histórico v1.2.0 **solo sobre este mismo VAL**, sin alterar sus pesos ni abrir su TEST: publicó 26/28 fotos sanas como tizón, 0/150 de otro cultivo, y acertó 307/316 diagnósticos positivos aceptados con cobertura 316/318. La comparación muestra una mejora de rechazo sano en este VAL, no una comparación independiente de generalización entre ciclos ni un resultado de TEST. Archivo privado `historical-v1.2-on-val.json`, SHA-256 `0f0b72c35a9b0515fee0dcb2b028c667cfb809fb944052cd0b772b6b3d74036e`.

## Congelamiento y carga independiente

El paquete privado `.local/ml-v1.3.2/frozen-mobilenetv3-candidate/` contiene pesos, configuración, preprocesado mediante configuración, protocolo G0, calibración, umbral, mapa técnico/publicable, reporte VAL, comparación histórica y medición CPU. `freeze.json` registra sus hashes, el sello G1 y el estado **`LOCKED_BEFORE_TEST_NOT_G2`**. Su SHA-256 es **`d07dcc40376d4d74e581553c817e4610f7bf7716cae0d6af98a3919930141eb7`**; el de pesos es `a55fbcbfcfc6234b6c03b20c996440768fc4b7a897631a67a96c45c0e159e361`. La carga en un proceso independiente verificó checksums, `state_dict` estricto, mapa de solo dos clases publicables y que el argmax sano nunca se publica. Una copia con `class-map.json` alterado fue rechazada con `ValueError: Frozen candidate altered or falsely approved`; el original no se tocó.

Inferencia CPU independiente en **100 imágenes de VAL**, 25 de cada estrato, con preprocesado y modelo: mediana **5,389 ms**, p95 **5,777 ms**, máximo **15,167 ms**, RSS **340 MB**, cuatro hilos. Cumple el presupuesto de inferencia G0 en esta muestra. No mide HTTP, cola, Diagnosis ni latencia extremo a extremo. EXTERNAL no está disponible. Este paquete aún **no es un release G2 ni una política activable**; faltan contrato de bundle/worker v1.3.2, TEST único nuevo y revisión G2.

## Reproducción local sin descargas implícitas

Requiere el G1 privado admitido, el bundle histórico v1.2.0 privado, `python:3.12-slim-bookworm` ya presente y `ml/.venv` previamente instalado desde `ml/uv.lock`. Elegir directorios de salida nuevos: los scripts rechazan sobrescritura. Desde la raíz del proyecto:

```bash
agro_py_path=/workspace/ml/.venv/lib/python3.12/site-packages:/workspace/ml/src:/workspace
agro_container=(docker run --rm --pull=never --network none --user "$(id -u):$(id -g)" --cpus=4 --memory=4g -v "$PWD:/workspace" -w /workspace -e "PYTHONPATH=$agro_py_path" -e OMP_NUM_THREADS=4 -e MKL_NUM_THREADS=4 -e "AGRO_GIT_HEAD=$(git rev-parse HEAD)" python:3.12-slim-bookworm python)
"${agro_container[@]}" scripts/train_v13_candidate.py ml/configs/potato-v13-mobilenetv3-cpu.json ml/evaluation/protocol-g0.v1.3.2.json ml/evaluation/protocol-g0.v1.3.1.json .local/pv-g1/g1-v1.3.1-admitted .local/ml-pilot-v1.2/g2-bundle-v1 .local/ml-v1.3.2/nueva-repeticion
"${agro_container[@]}" scripts/compare_v13_val_routes.py .local/ml-v1.3.2/nueva-repeticion ml/evaluation/protocol-g0.v1.3.2.json .local/ml-v1.3.2/nueva-repeticion/route-comparison.json
"${agro_container[@]}" scripts/freeze_v13_candidate.py create .local/ml-v1.3.2/nueva-repeticion ml/configs/potato-v13-mobilenetv3-cpu.json ml/evaluation/protocol-g0.v1.3.2.json .local/pv-g1/g1-v1.3.1-admitted .local/ml-v1.3.2/nuevo-congelado
"${agro_container[@]}" scripts/freeze_v13_candidate.py verify .local/ml-v1.3.2/nuevo-congelado
```

La ejecución repetida conservará pesos y predicciones bajo el entorno fijado; los hashes de `route-comparison.json` y `freeze.json` cambian con las mediciones de latencia y, en el segundo caso, el momento de creación. Los artefactos privados originales se preservan. **TEST no se ejecuta en estos comandos.**

La verificación independiente del paquete original usa su SHA publicado como raíz de confianza:

```bash
"${agro_container[@]}" scripts/freeze_v13_candidate.py verify .local/ml-v1.3.2/frozen-mobilenetv3-candidate --expected-sha256 d07dcc40376d4d74e581553c817e4610f7bf7716cae0d6af98a3919930141eb7
```

## Plan TEST registrado antes de abrirlo

La [copia versionada del registro de congelamiento](../../ml/evaluation/freeze-record.v1.3.2.json) tiene el mismo SHA-256 `d07dcc40376d4d74e581553c817e4610f7bf7716cae0d6af98a3919930141eb7` que `freeze.json` privado. Ella fija pesos, configuración, protocolo, calibración, umbral, mapa y sello. La política visible de este candidato es exactamente `ARGMAX_CONFIDENCE` con temperatura **1,25**, umbral **0,90** y dos salidas publicables; no se alterará para TEST. El contrato de política del servicio y su activación siguen pendientes para G2/G3.

El [evaluador de TEST](../../scripts/evaluate_v13_sealed_test.py) y su [puntuación fija](../../ml/src/agro_ml/v13_test_evaluation.py) quedaron preparados antes de TEST. Exigen los cuatro estratos completos **80/20, 80/20, 32/8 y 80/20** fotos/grupos, SHA del bundle y sello, derechos y etiquetas G1, y registran el intento único en `.local/ml-v1.3.2/test-access-v1.3.2.json` antes de inferir. Si el proceso falla, esa marca permanece y el comando no reintenta con otro directorio. Un preflight sin leer imágenes TEST devolvió `PREFLIGHT_ONLY_NO_TEST_IMAGES`, 272 filas y el SHA esperado. Las pruebas sintéticas de éxito, falsas aceptaciones sanas, rechazo de otro cultivo, abstenciones como falsos negativos y lote incompleto pasaron antes del commit.

Después del commit local, el único comando autorizado para consumir TEST es:

```bash
"${agro_container[@]}" scripts/evaluate_v13_sealed_test.py run .local/ml-v1.3.2/frozen-mobilenetv3-candidate .local/pv-g1/g1-v1.3.1-admitted .local/pv-g1/pilot-v1.2 .local/ml-v1.3.2/test-v1.3.2-once
```

El informe y las predicciones quedarán en el directorio privado indicado. El código calcula métricas y puertas sin buscar un umbral nuevo. Un incumplimiento conserva el mismo reporte y deja G2 abierto.
