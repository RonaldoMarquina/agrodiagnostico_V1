# Evaluación EXTERNAL única v1.4.3

Fecha: 2026-11-23. Resultado: ejecución técnica completa; criterios G0
incumplidos; **G2 abierto**. El worker real y la política permanecen inactivos.

## Invariantes de la apertura

- commit previo: `3930efa`;
- sello: `d0c76dc4b9d398cb779d71f82e9baaa250ea8a097a2d2b3ad1a8bf89efade7d1`;
- freeze: `07ef4eac80f59b7ca1fc42031092f3353e7e2dd89d6c8c8c17fda4865c85110a`;
- pesos: `e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c`;
- preprocesado: RGB 224×224, normalización ImageNet y decodificador v1.4.3;
- temperatura `0,50`, umbral `0,80`;
- 350/350 predicciones, red deshabilitada, CPU, sin entrenamiento,
  recalibración o selección;
- inicio `2026-11-23T22:32:16.112029Z` y fin
  `2026-11-23T22:32:27.154862Z`;
- Sikkim no se montó ni reutilizó.

La ejecución fue única. La salida privada quedó inmutable y un proceso distinto
recalculó las métricas desde las predicciones con estado
`EXTERNAL_OUTPUT_VERIFIED`. No se autoriza reintento.

## Resultados

| Criterio | Medido | Límite | Estado |
| --- | ---: | ---: | --- |
| F1 macro de tizones | 0,2937 | ≥0,75 | Falla |
| Recall temprano | 40/50 = 0,80 | ≥38/50 | Cumple |
| Recall tardío | 10/50 = 0,20 | ≥38/50 | Falla |
| Sana publicada como tizón | 44/50 | ≤5/50 | Falla |
| Sana `NO_CONCLUYENTE` | 6/50 | ≥45/50 | Falla |
| Otro cultivo publicado como tizón | 126/200 | ≤10/200 | Falla |

Por clase publicable:

| Clase | TP | FP | FN | Precision | Recall | F1 | Abstenciones |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Tizón temprano | 40 | 196 | 10 | 0,1695 | 0,80 | 0,2797 | 8 |
| Tizón tardío | 10 | 5 | 40 | 0,6667 | 0,20 | 0,3077 | 11 |

Las abstenciones de tizón forman parte de `FN`. El gran número de falsos
positivos tempranos incluye 29 tardíos, 44 sanas y 123 imágenes de otro
cultivo.

## Matriz visible

Filas: etiqueta real. Columnas: temprano, tardío, `NO_CONCLUYENTE`.

| Estrato real | Temprano | Tardío | `NO_CONCLUYENTE` |
| --- | ---: | ---: | ---: |
| Tizón temprano | 40 | 2 | 8 |
| Tizón tardío | 29 | 10 | 11 |
| Papa sana | 44 | 0 | 6 |
| Otro cultivo | 123 | 3 | 74 |

Abstenciones totales: 99, distribuidas como 8 temprano, 11 tardío, 6 sana y
74 otro cultivo.

## Rendimiento técnico

| Medición | Mediana | p95 | Máximo |
| --- | ---: | ---: | ---: |
| Inferencia | 4,5249 ms | 5,1391 ms | 10,2520 ms |
| Recorrido por imagen | 19,5756 ms | 179,6654 ms | 199,6986 ms |

RSS máximo: 594,54 MB. Runtime: AMD Ryzen 7 5800XT, Python 3.12.14,
PyTorch 2.15.0+cpu, torchvision 0.29.2+cpu, cuatro hilos.

## Integridad

| Artefacto | SHA-256 |
| --- | --- |
| Predicciones privadas | `ddfb1938f6fc883483248d0c1237bb9cd8a55eb684c5c03a9451d1fb5166a6bb` |
| Reporte privado | `09ac3b9b16f303dadc21b87772af03dbcfd0154aba792bfde9b48ba1544607ea` |
| Decisión privada | `6d45ca104a2e797130e1fdf5e74d5f99eefd7cb5eba9fa393e4925776583d48e` |

El [resumen sanitizado](../../ml/evaluation/external-report.v1.4.3.summary.json)
no contiene rutas privadas ni imágenes. La unidad de independencia demostrada
es imagen única, no planta o sesión; las fuentes no representan Ayacucho.

## Decisión G2

La decisión automática es `OPEN_EXTERNAL_CRITERIA_FAILED`. Solo el recall de
tizón temprano cumplió. El bundle v1.4.2/v1.4.3 no se aprueba para publicación,
no se importa política y no se activa el worker. Una mejora exige otro ciclo,
selección exclusivamente en TRAIN/VAL y un EXTERNAL nuevo independiente; este
lote no puede reutilizarse para ajustar ni volver a medir.
