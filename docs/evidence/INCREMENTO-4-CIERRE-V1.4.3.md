# Cierre del ciclo de IA v1.4.3

Fecha de decisión: 2026-11-23. Responsable: responsable del proyecto.

Estado terminal: **evaluación externa completada y modelo no aprobado para
producción**. La validación interna en VAL permitió congelar el candidato, pero
no demostró generalización de campo. La evaluación EXTERNAL independiente
falló cinco de seis criterios. G2 queda `CLOSED_REJECTED_EXTERNAL`; G3 queda
`CLOSED_NOT_PROMOTED_G2_REJECTED`.

Este cierre no reabre el lote, no cambia el bundle, no recalibra ni inicia otro
ciclo de mejora dentro del incremento. Los commits históricos `3930efa` y
`e5ca418`, el sello, los reportes y los hashes se conservan intactos.

## Resultado EXTERNAL y límites

| Criterio | Resultado | Límite | Decisión |
| --- | ---: | ---: | --- |
| F1 macro de ambos tizones | 0,2937 | ≥ 0,75 | Incumple |
| Recall tizón temprano | 40/50 = 0,80 | ≥ 38/50 | Cumple |
| Recall tizón tardío | 10/50 = 0,20 | ≥ 38/50 | Incumple |
| Papa sana publicada como tizón | 44/50 | ≤ 5/50 | Incumple |
| Papa sana como `NO_CONCLUYENTE` | 6/50 | ≥ 45/50 | Incumple |
| Otro cultivo publicado como tizón | 126/200 | ≤ 10/200 | Incumple |

Matriz, por etiqueta real y resultado visible:

| Real | Tizón temprano | Tizón tardío | `NO_CONCLUYENTE` |
| --- | ---: | ---: | ---: |
| Tizón temprano | 40 | 2 | 8 |
| Tizón tardío | 29 | 10 | 11 |
| Papa sana | 44 | 0 | 6 |
| Otro cultivo | 123 | 3 | 74 |

Abstenciones totales: 99. RSS máximo: 594,54 MB. Inferencia: mediana
4,5249 ms, p95 5,1391 ms y máximo 10,2520 ms. Recorrido por imagen: mediana
19,5756 ms, p95 179,6654 ms y máximo 199,6986 ms.

## Integridad histórica

| Referencia | SHA-256 |
| --- | --- |
| Protocolo G0 v1.4.3 | `e5d9288c6cc7c78263d29bd311d9257df503dc39abc3eda4427ada51eee842b7` |
| Resultado TRAIN/VAL interno | `ad2231e31a5e6de93391fd2e7026d458134ab8cb41f315b3e44f29dbc19d4ec7` |
| Sello EXTERNAL | `d0c76dc4b9d398cb779d71f82e9baaa250ea8a097a2d2b3ad1a8bf89efade7d1` |
| Freeze del bundle | `07ef4eac80f59b7ca1fc42031092f3353e7e2dd89d6c8c8c17fda4865c85110a` |
| Pesos | `e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c` |
| Predicciones privadas | `ddfb1938f6fc883483248d0c1237bb9cd8a55eb684c5c03a9451d1fb5166a6bb` |
| Reporte privado | `09ac3b9b16f303dadc21b87772af03dbcfd0154aba792bfde9b48ba1544607ea` |
| Decisión privada | `6d45ca104a2e797130e1fdf5e74d5f99eefd7cb5eba9fa393e4925776583d48e` |

El [reporte EXTERNAL original](INCREMENTO-4-EXTERNAL-V1.4.3-UNICO.md) y la
decisión automática `OPEN_EXTERNAL_CRITERIA_FAILED` permanecen como evidencia
del instante de evaluación. El
[acta terminal](../../ml/evaluation/cycle-closure.v1.4.3.json) añade la decisión
administrativa posterior sin reescribirlos.

## Estado operativo

- `ml-real` continúa apagado y requiere `REAL_INFERENCE_AUTHORIZED=true`; para
  este ciclo esa autorización es `false` y no debe concederse.
- No se importó ni activó una política de publicación v1.4.3.
- El catálogo revisado queda histórico y no publicable; no declara clases de
  producción soportadas.
- El perfil explícito `demo` usa un adaptador sin pesos que siempre produce
  `ABSTENTION/UNSUPPORTED_CLASS`; Diagnosis lo convierte en
  `NO_CONCLUYENTE`. No es una predicción ni reutiliza el simulador.

## Pendientes que no se ocultan

Las tareas históricas 9.1 y 9.4 del cambio original permanecen sin marcar. 9.1
exige aceptación integrada con un release real aprobado, condición que este
ciclo no satisface. 9.4 exige archivar solo con aceptación real aprobada. Por
ello el ciclo queda cerrado como rechazado, pero el cambio original no se puede
archivar como incremento productivo. Un futuro modelo requeriría otro cambio,
otros datos de selección y una evaluación independiente; no forma parte de
este cierre.

## Verificación del cierre

- `openspec validate incremento-4-v1-4-3-evaluacion-external-g2 --strict`:
  válido.
- Suite completa de AI Inference dentro de la imagen construida desde el lock
  del servicio: 72/72 pruebas aprobadas. Incluye abstención demo, evento
  contractual, metadatos nulos,
  rechazo del flag de simulación y bloqueo de `real` sin autorización.
- `docker compose ... config --format json` para los perfiles por separado:
  el stack predeterminado no incluye workers; `demo` incluye solo
  `ai_inference-worker-demo` sin volumen ni puertos; `async-test` incluye solo
  los dos workers sintéticos; `ml-real` incluye solo el worker real, sin
  puertos y con `REAL_INFERENCE_AUTHORIZED=false`.
- Los tres registros JSON nuevos pasaron parseo estricto y el código Python
  modificado pasó compilación de bytecode.
