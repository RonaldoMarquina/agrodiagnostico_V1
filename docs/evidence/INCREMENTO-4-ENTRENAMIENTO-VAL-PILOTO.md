# Incremento 4 — entrenamiento y selección en VAL del piloto v1.2.0

Fecha local: 2026-11-19 (America/Lima). Este expediente registra el entrenamiento y la selección en VAL, durante los cuales no se leyó TEST. Posteriormente se hizo [una evaluación independiente del TEST sellado](INCREMENTO-4-TEST-PILOTO-V1.2.md) y se [aprobó G2 para el bundle restringido](INCREMENTO-4-APROBACION-G2-PILOTO.md). EXTERNAL no existe y no se activó inferencia real para usuarios.

## Datos, código y entorno

Se usaron solo `train-positives.csv` (1.040 imágenes de tizones), `train-negatives.csv` (503 hojas de tomate), `val-positives.csv` (318 imágenes de tizones) y `val-negatives.csv` (150 hojas de tomate) del [lote privado G1](INCREMENTO-4-G1-PILOTO-V1.2.md). El objetivo técnico `OTHER_CROP` sirve para rechazar negativos; no es una tercera enfermedad ni un estado `NO_CONCLUYENTE`. Papa sana, maíz y fotografías de campo no están en estos experimentos. La carga [valida derechos, etiqueta, SHA-256 y bytes](../../ml/src/agro_ml/pilot_training.py) de cada fila TRAIN/VAL y rechaza cualquier split distinto. Los experimentos comparten **semilla 42**, grupos, preprocesado 224×224 RGB con media/desviación normalizadas según las configuraciones, GroupNorm, tres épocas, batch 16, AdamW con tasa 0,001, cuatro hilos CPU y pesos iniciales aleatorios sin descarga.

| Entrada privada | SHA-256 |
| --- | --- |
| Registro G1 por imagen | `8ed8d874fdce503fc639ee320789f694083468e24cbb59800a8b75050e93eaa5` |
| TRAIN positivos | `42a60655b520250c36f07e0d581c59d25a3528f63fbe77d52afe8b9baf985eae` |
| TRAIN negativos | `2eafdb9fd75810355d77713f32518bf3c2c5b3546dae89da30dbe110fc5f55d2` |
| VAL positivos | `373aba5a6d55db34c5412503365d57d3a44ed8a233f362843c3aba1ddec9502c` |
| VAL negativos | `a5d036d5f404916d4b1129fbec12fbe6d62938aca7f9a002374106cdf2ee23d3` |

Revisión Git `6b1f32931e64d9513dd9be998c99d8312379488b` con árbol de trabajo **modificado**; el SHA-256 exacto del código de entrenamiento es `85aeba3ef4b7af719ab2f36e1dc3ccd64a61ea81ac8da4bfbd75ab4ab469f969`, el de preprocesado `67c8c1de3ec52dd9d41ef3954b68af6084ce6c4396e8c0eae22cecdcb1f381fb` y el de `ml/uv.lock` `e2962d266b7b1efde365bea3952cca71e66d15d338bc6ef0952c01bf4e2d100b`. CPU AMD Ryzen 7 5800XT, 16 hilos lógicos y 30.974 MB de RAM; contenedor limitado a cuatro CPU y 4 GB. Python 3.12.14, PyTorch 2.15.0+cpu, torchvision 0.29.2+cpu, Pillow 12.3.0 y safetensors 0.8.0. La configuración exacta y versiones están en cada `experiment.json` privado.

Configuración MobileNetV3-Small [`pilot-mobilenetv3-gn.v1.json`](../../ml/configs/pilot-mobilenetv3-gn.v1.json), SHA-256 `2bfaf38622ace3f49fa02f93d4534ce815650e4ce421fd3a02e8abdb007b5e41`; configuración ResNet18 [`pilot-resnet18-gn.v1.json`](../../ml/configs/pilot-resnet18-gn.v1.json), SHA-256 `dfad92bb4fc5642aac0b32e7adf0b5fa0bd968dd34ae701d2c09f303d0d669c9`. Solo difiere la arquitectura; ambos usan el mismo presupuesto de épocas, hilos y memoria, aunque los tiempos reales difieren.

## Ensayos y comparación real

Se descartaron los ensayos diagnósticos `mobilenet-run2` (64 px, BatchNorm, F1 macro VAL 0,329) y `mobilenet-224-run1/run2` (224 px, BatchNorm, F1 macro VAL 0,3248/0,3416): la inferencia en modo evaluación colapsó a una clase o el extractor fijo no aprendió. La variante final usa GroupNorm para mantener normalización consistente entre entrenamiento e inferencia. Estos ensayos de ajuste se decidieron exclusivamente con VAL; incrementan el riesgo de sobreajuste a esta partición y TEST sigue reservado para evaluar después del congelamiento.

| Arquitectura final | Época elegida en VAL | F1 macro VAL | Recall temprano / tardío | Cobertura | Error selectivo | Abstenciones | Negativos aceptados | p95 CPU en 318 positivos VAL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MobileNetV3-Small + GroupNorm | 3 | 0,9684 | 0,9758 / 0,9542 | 316/318 = 0,9937 | 9/316 = 0,0285 | 2/318 | 0/150 | 6,30 ms |
| ResNet18 + GroupNorm | 3 | 0,8825 | 0,8000 / 0,9281 | 303/318 = 0,9528 | 29/303 = 0,0957 | 15/318 | 43/150 = 0,2867 | 17,00 ms |

MobileNetV3 fue elegido **solo en VAL**: supera las metas de selección VAL de F1 macro ≥ 0,80, cobertura ≥ 0,70, error ≤ 0,10 y FPR efectivo de negativos ≤ 0,05; ResNet18 incumple el último límite. Ambos reportes incluyen precisión, recall, F1, soporte, verdaderos/falsos positivos y falsos negativos por clase, matriz de confusión y numeradores/denominadores. Los reportes privados son `mobilenet-gn-final/val-report.json` (SHA-256 `da757446952116fae5ab953486d021e463fa8267a4053544dc34ffb331ce1a32`) y `resnet18-gn-final/val-report.json` (SHA-256 `385a14400623f02e2465be45b2d86300c2d0ca522446aceb4a886d7cd11831ed`).

En MobileNetV3, el tiempo por época **incluida la evaluación VAL** fue 11,369; 11,866 y 12,012 segundos; duración total 37,687 segundos y RSS máximo de entrenamiento 2.973,94 MB. En ResNet18 fueron 61,485; 64,206 y 64,701 segundos; total 201,117 segundos y RSS máximo 2.789,93 MB. La repetición `mobilenet-gn-repeat` con idéntico código, configuración, semilla y manifiestos produjo exactamente el mismo SHA-256 de pesos `0fbd26d4c8a1854a964c67c86bcfd40d61d639ede348a9a22519d3af1cf198a1` y las mismas métricas de VAL; tiempos y RSS variaron. Ese peso sigue siendo **candidato no aprobado G2**.

## Calibración y congelamiento antes de TEST

La [selección](../../ml/src/agro_ml/pilot_selection.py) ajustó Platt logit con regularización por clase usando solo los scores de VAL, eligió el umbral común 0,50 en VAL y lo guardó como umbral por clase. El rechazo técnico se produce también cuando `OTHER_CROP` supera a la clase candidata. Tras calibrar, el F1 macro visible VAL permanece 0,9684; ECE de candidatos positivos válidos = 0,0213 y ECE con negativos = 0,0153. Se conservaron 316/318 diagnósticos aceptados, 9 errores entre aceptados y 0/150 falsos aceptados de negativos. Una respuesta abstinente cuenta como fallo de recall de su clase. La confianza calibrada no garantiza corrección individual.

El registro privado `selection-v2/freeze.json` quedó en estado `LOCKED_BEFORE_TEST`, digest integral `2d0116f745f778dbc5152674bf0670d08b5e5ba2d8a224b7aa73179d4aa6c452` y SHA-256 del archivo `db2618a90f7a8f8b6afaaafbf1fabbc94dafa2dc31a165efbda3e4d548954534`. Vincula pesos, configuración, protocolo G0 v1.2.0, calibración, umbrales, reportes VAL, código, lock, registro G1 y hashes de manifiestos TRAIN/VAL. La verificación del congelamiento pasó; la alteración de una copia de `config.json` fue rechazada por el futuro control de acceso a TEST. **No se invocó un cargador de TEST.** El estado `g2_approval` permanece `null`.

En un proceso CPU limpio, 100 inferencias repetidas sobre la primera imagen positiva de VAL dieron mediana 5,013 ms, p95 5,264 ms, máximo 5,490 ms y RSS máximo 349,03 MB. Es una comprobación de recursos del modelo en una imagen fija, no una medición del flujo completo ni una estimación de generalización a campo. El archivo privado `selected-inference-cpu-v2.json` conserva su SHA de muestra y congelamiento.

## Reproducción offline

Desde la raíz, con la imagen `python:3.12-slim-bookworm` ya presente localmente y el entorno ML bloqueado instalado en `ml/.venv/lib/python3.12/site-packages`, ejecutar sin red (sustituir el directorio de salida por uno nuevo en cada corrida):

```bash
agro_head="$(git rev-parse HEAD)"
docker run --rm --pull=never --network none --user "$(id -u):$(id -g)" --cpus=4 --memory=4g \
  -v "$PWD:/workspace" -w /workspace \
  -e PYTHONPATH=/workspace/ml/.venv/lib/python3.12/site-packages:/workspace/ml/src \
  -e OMP_NUM_THREADS=4 -e MKL_NUM_THREADS=4 -e AGRO_GIT_HEAD="$agro_head" -e AGRO_GIT_DIRTY=1 \
  python:3.12-slim-bookworm python scripts/run_pilot_training.py \
  --config ml/configs/pilot-mobilenetv3-gn.v1.json \
  --split-root .local/pv-g1/pilot-v1.2 --images-root .local/pv-g1/batch-v1 \
  --evidence .local/pv-g1/pilot-v1.2/evidence.json \
  --output-dir .local/ml-pilot-v1.2/otra-corrida-mobile
```

Para repetir la comparación completa, sustituir el directorio móvil anterior por `.local/ml-pilot-v1.2/reproduccion-mobile` y ejecutar además:

```bash
agro_head="$(git rev-parse HEAD)"
docker run --rm --pull=never --network none --user "$(id -u):$(id -g)" --cpus=4 --memory=4g \
  -v "$PWD:/workspace" -w /workspace \
  -e PYTHONPATH=/workspace/ml/.venv/lib/python3.12/site-packages:/workspace/ml/src \
  -e OMP_NUM_THREADS=4 -e MKL_NUM_THREADS=4 -e AGRO_GIT_HEAD="$agro_head" -e AGRO_GIT_DIRTY=1 \
  python:3.12-slim-bookworm python scripts/run_pilot_training.py \
  --config ml/configs/pilot-resnet18-gn.v1.json \
  --split-root .local/pv-g1/pilot-v1.2 --images-root .local/pv-g1/batch-v1 \
  --evidence .local/pv-g1/pilot-v1.2/evidence.json \
  --output-dir .local/ml-pilot-v1.2/reproduccion-resnet

docker run --rm --pull=never --network none --user "$(id -u):$(id -g)" --cpus=4 --memory=4g \
  -v "$PWD:/workspace" -w /workspace \
  -e PYTHONPATH=/workspace/ml/.venv/lib/python3.12/site-packages:/workspace/ml/src \
  python:3.12-slim-bookworm python scripts/select_pilot_candidate.py \
  --mobilenet-dir .local/ml-pilot-v1.2/reproduccion-mobile \
  --mobilenet-config ml/configs/pilot-mobilenetv3-gn.v1.json \
  --resnet-dir .local/ml-pilot-v1.2/reproduccion-resnet \
  --resnet-config ml/configs/pilot-resnet18-gn.v1.json \
  --protocol ml/evaluation/protocol-g0.v1.2.0.json \
  --output-dir .local/ml-pilot-v1.2/reproduccion-seleccion

docker run --rm --pull=never --network none --user "$(id -u):$(id -g)" --cpus=4 --memory=4g \
  -v "$PWD:/workspace" -w /workspace \
  -e PYTHONPATH=/workspace/ml/.venv/lib/python3.12/site-packages:/workspace/ml/src \
  python:3.12-slim-bookworm python scripts/measure_pilot_inference.py \
  --freeze .local/ml-pilot-v1.2/reproduccion-seleccion/freeze.json \
  --val-positives .local/pv-g1/pilot-v1.2/val-positives.csv \
  --images-root .local/pv-g1/batch-v1 \
  --evidence .local/pv-g1/pilot-v1.2/evidence.json \
  --iterations 100 --output .local/ml-pilot-v1.2/reproduccion-inferencia.json
```

Los directorios de salida deben ser nuevos y el entorno ML bloqueado debe estar instalado previamente; los comandos usan la imagen local y `--network none`, sin descargar datos ni pesos. El directorio `.local/` y sus artefactos no se suben a Git.

## Límite de esta evidencia

VAL procede de la misma distribución controlada PlantVillage que TRAIN, aunque los `leaf_id` y SHA-256 estén separados. El resultado puede ser optimista para fotografías reales; Ayacucho EXTERNAL sigue sin conjunto autorizado. El negativo probado es tomate sano, no papa sana ni otros fondos. El rechazo de papa sana y la robustez ante ambigüedad visual no están demostrados por estas métricas. La calibración y la selección utilizaron VAL; TEST se abrió una sola vez después del congelamiento sin reajuste. G2 aprobó el bundle restringido, pero el worker real sigue inactivo.
