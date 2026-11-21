# Incremento 4 — evaluación única de TEST del piloto v1.2.0

Fecha de cierre de evaluación: 2026-11-19, America/Lima (`2026-11-20T04:06:27Z`). Se evaluó **una vez** el TEST G1 sellado con el candidato MobileNetV3-Small congelado en VAL. El registro privado `.local/ml-pilot-v1.2/test-one-shot-v1/test-access.json` quedó `COMPLETED`. El reporte privado `test-report.json` tiene SHA-256 `b10a6654d64c56e6967f51de28ede65924813b5da8684319ffc16788d71e4e96`. No se ajustaron pesos, hiperparámetros, calibración ni umbral con TEST.

## Procedencia y método

El congelamiento previo tiene SHA-256 `db2618a90f7a8f8b6afaaafbf1fabbc94dafa2dc31a165efbda3e4d548954534` y estado `LOCKED_BEFORE_TEST`. El sello G1 tiene SHA-256 `3f89a833ad38782f7d7139283ef444321d139a8798e8d6fec8053e3e79819e07`. La evaluación verificó ambos, los manifiestos materializados contra el sello, derechos, revisión, SHA-256 y bytes por imagen. TEST contiene 122 casos de tizón temprano, 113 de tizón tardío y 112 negativos de tomate, 347 imágenes en total. Manifiestos TEST: positivos SHA-256 `463a423915a0185418e41a2e864f1c13ec21e26bbc49d4b8913c8e2fdc926b24`; negativos `ccfb20f34441071cb0a1d9ebc41487db5f7089979f4c3de451ec2b0db4a5d5c5`.

Se cargaron los pesos congelados SHA-256 `0fbd26d4c8a1854a964c67c86bcfd40d61d639ede348a9a22519d3af1cf198a1`, la configuración `2bfaf38622ace3f49fa02f93d4534ce815650e4ce421fd3a02e8abdb007b5e41`, calibración `8f3b69f7dc7051510894be8cd06b0b141cef31d77d871ff4315616f60e69cc3c` y umbrales `5a6c6154ef3ba101a9dca8e873480913d007830ffb3638a6e7ef24c8d9b40e57`. El mapa visible contiene solo `POTATO_EARLY_BLIGHT` y `POTATO_LATE_BLIGHT`; `OTHER_CROP` es un objetivo técnico de rechazo. Umbral fijo por clase: **0,50**, seleccionado en VAL. El [código de evaluación](../../ml/src/agro_ml/pilot_test_evaluation.py) produjo el reporte con SHA-256 de código `0c78a2ebf5a061359d6da1724533b88a3d68ddbdcc4b5b023858c2e9a4f1bbfc`.

## Resultados publicados

Matriz de confusión con filas de verdad y columnas de diagnóstico visible:

| Verdad | Tizón temprano | Tizón tardío | NO_CONCLUYENTE | Total |
| --- | ---: | ---: | ---: | ---: |
| Tizón temprano | 116 | 6 | 0 | 122 |
| Tizón tardío | 10 | 103 | 0 | 113 |
| Otro cultivo, tomate | 0 | 0 | 112 | 112 |

| Clase válida | Precision | Recall | F1 | Aceptados | Abstenciones | Falsos negativos |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Tizón temprano | 116/126 = 0,9206 | 116/122 = 0,9508 | 232/248 = 0,9355 | 122/122 | 0/122 | 6/122; por abstención 0/122 |
| Tizón tardío | 103/109 = 0,9450 | 103/113 = 0,9115 | 206/222 = 0,9279 | 113/113 | 0/113 | 10/113; por abstención 0/113 |

La precisión y F1 de las dos clases se calculan sobre las imágenes válidas del piloto; los falsos aceptados de negativos se informan por separado (0 para cada clase). Una predicción candidata correcta publicada `NO_CONCLUYENTE` habría contado como falso negativo de su clase; el cálculo se probó con casos sintéticos y en este TEST ocurrió **0 veces**. No se atribuyó una clase diagnóstica a los negativos.

Accuracy visible: **219/235 = 0,9319**. Precision macro 0,9328, recall macro 0,9312 y F1 macro **0,9317**; las medias macro promedian las dos tasas por clase de la tabla. Cobertura: **235/235 = 1,0000**. Abstenciones de positivos: **0/235 = 0**. Error selectivo: **16/235 = 0,0681**. Negativos aceptados: **0/112 = 0**, rechazo de negativos **112/112 = 1,0000**. Estos denominadores distinguen imágenes válidas de las dos clases y negativos fuera de cobertura.

Calibración Platt ajustada solo en VAL: ECE de candidatos de imágenes válidas **0,0366 sobre 235**; ECE de diagnósticos aceptados también 0,0366 sobre 235. El reporte privado guarda por intervalo sus conteos, aciertos y suma de confianza. Brier binario de corrección de diagnóstico aceptado: **12,91077799/235 = 0,054939**. Brier de softmax técnico sin calibrar, con dos tizones y `OTHER_CROP`: **26,95734667/347 = 0,077687**; son métricas con objetivos distintos. Entropía media técnica 0,092413 y margen medio 0,943641, ambos sobre 347 salidas.

En CPU, 347 inferencias medidas incluyeron decodificación, preprocesado y llamada al modelo: mediana 5,1254 ms, p95 5,8262 ms, máximo 9,9617 ms y RSS máximo 350,71 MB. El subconjunto de 235 positivos tuvo mediana 5,08 ms y p95 5,81 ms. Se usó el mismo entorno offline limitado a cuatro CPU y 4 GB descrito en el [expediente de entrenamiento](INCREMENTO-4-ENTRENAMIENTO-VAL-PILOTO.md). **No** son tiempos del flujo HTTP, cola, almacenamiento y publicación; el p95 completo de 30 s permanece sin medir.

## Contraste con G0 v1.2.0

| Criterio | Límite | Resultado TEST | Estado |
| --- | ---: | ---: | --- |
| F1 macro | ≥ 0,85 | 0,9317 | Cumple |
| Recall tizón temprano | ≥ 0,80 | 116/122 = 0,9508 | Cumple |
| Recall tizón tardío | ≥ 0,80 | 103/113 = 0,9115 | Cumple |
| Cobertura | ≥ 0,70 | 235/235 = 1,0000 | Cumple |
| Error selectivo | ≤ 0,10 | 16/235 = 0,0681 | Cumple |
| FPR de negativos | ≤ 0,05 | 0/112 = 0 | Cumple |

También cumplen F1 por clase ≥ 0,70, ECE ≤ 0,15 y el presupuesto CPU individual: mediana ≤ 1000 ms, p95 ≤ 2500 ms, máximo ≤ 4000 ms y RSS ≤ 1024 MB. El reporte privado conserva cada límite, valor y veredicto. **EXTERNAL no existe para este piloto**: no hay medición en fotografías reales independientes ni evidencia de generalización a Ayacucho. Papa sana tampoco fue negativo admitido; su rechazo no está medido. El porcentaje de cobertura sobre las dos clases PlantVillage no debe extrapolarse a otras enfermedades, condiciones de captura o usuarios.

## Reproducción y siguiente puerta

Comando ejecutado una vez, desde la raíz, con la imagen local `python:3.12-slim-bookworm` y dependencias ML bloqueadas ya instaladas:

```bash
docker run --rm --pull=never --network none --user "$(id -u):$(id -g)" --cpus=4 --memory=4g \
  -v "$PWD:/workspace" -w /workspace \
  -e PYTHONPATH=/workspace/ml/.venv/lib/python3.12/site-packages:/workspace/ml/src \
  python:3.12-slim-bookworm python scripts/evaluate_frozen_pilot_test.py \
  --freeze .local/ml-pilot-v1.2/selection-v2/freeze.json \
  --split-root .local/pv-g1/pilot-v1.2 --images-root .local/pv-g1/batch-v1 \
  --evidence .local/pv-g1/pilot-v1.2/evidence.json \
  --expected-seal-sha256 3f89a833ad38782f7d7139283ef444321d139a8798e8d6fec8053e3e79819e07 \
  --expected-freeze-sha256 db2618a90f7a8f8b6afaaafbf1fabbc94dafa2dc31a165efbda3e4d548954534 \
  --output-dir .local/ml-pilot-v1.2/test-one-shot-v1
```

La ruta de salida existente impide una segunda ejecución allí. La carpeta privada `.local/ml-pilot-v1.2/g2-review-v1/` fue el expediente previo a G2; `review-manifest.json` tiene SHA-256 `e9b26a24537f1d30da90a5aaab813166279f901370fa4bd2ebfe5ff589169f77`. Posteriormente se construyó y [aprobó el bundle G2](INCREMENTO-4-APROBACION-G2-PILOTO.md) con SHA-256 `93e2e65130a9c266be4bdba0262d1c98e30d0604f4d21466effba2d9c9ff0b41`. Esa aprobación no habilita por sí sola el worker real.
