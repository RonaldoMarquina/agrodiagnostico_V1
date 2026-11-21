# G1 v1.3.1 — revisión interna y partición candidata

> **Actualización 2026-11-21:** el responsable [aprobó G0 v1.3.1](INCREMENTO-4-G0-V1.3.1-APROBACION.md) y el lote pasó la [admisión final y verificación independiente G1](INCREMENTO-4-G1-V1.3.1-ADMISION.md). Este expediente conserva el estado preparatorio previo a la aprobación.

Fecha: **2026-11-21** (America/Lima). Protocolo [G0 v1.3.1 propuesto](INCREMENTO-4-G0-V1.3.1-PROPUESTA.md), **sin aprobación numérica todavía**. Por ello este expediente **no admite imágenes, no sella TEST y no cierra G1**. Los datos, bundle, TEST y resultados v1.2.0 se mantienen históricos e intactos. No hubo entrenamiento ni inferencia.

## Resolución conservadora de pares visuales

El [inventario de la distribución fijada](INCREMENTO-4-G1-V1.3-INVENTARIO-2026-11-21.md) produjo 11 pares dHash ≤6 que requerían resolución. Se inspeccionaron visualmente las dos vistas de cada par; al no poder acreditar identidad de hoja distinta solo con parecido visual, la decisión de G1 fue **excluir el grupo candidato completo de ambos lados** de cada par. No se alteró ninguna fila histórica v1.2.0. Esto resolvió los 11 pares con 12 grupos candidatos excluidos (11 de tizón tardío y uno de tizón temprano), 48 fotos adicionales. La nueva instantánea privada `.local/pv-g1/g1-v1.3-pair-resolution/registry.csv` contiene **166 `EXCLUDE` y 692 `PENDING`**, cero `ADMIT`; SHA-256 `872607900e50e225980ac381234de22df54fb9e5249b87ce699ac90283bd3a13`. Decisión por par y motivo: `pair-decisions.csv`, SHA-256 `95ef38663c4434ee8e7d10ee3acee1c261b9efee91d35d0257fb601325d88d7e`. Comando reproducible:

```bash
python3 scripts/resolve_g1_v1_3_visual_pairs.py \
  .local/pv-g1/audit-v1.3-20261121-final \
  .local/pv-g1/g1-v1.3-pair-resolution
```

Esta exclusión es deliberadamente más estricta que una apreciación subjetiva de similitud. Sus grupos no entran en el TEST candidato, ni se reasignan a TRAIN/VAL para compensar cifras. Los 12/3 sanos expuestos por G3 y 106 tomates sin `leaf_id` siguen excluidos por sus motivos previos.

## Revisión de calidad y etiquetas

Se inspeccionaron las **140 fotos sanas/35 hojas** restantes y una selección previa a cualquier modelo de **20 grupos** nuevos por estrato de tizón temprano, tardío y otro cultivo (**80 fotos** cada uno). La selección de grupos usa el orden SHA-256 de su `leaf_id`, nunca el aspecto de un resultado del modelo. El índice privado `.local/pv-g1/g1-v1.3-review-candidates/index.json` enlaza cada foto con su hoja de revisión visual; SHA-256 `19fa874c4d331a45e21bead529d3649f7d9ab27f5df0babaaae038b085d3460c`. El registro por archivo `visual-review.json` conserva SHA-256, ruta, revisión, licencia, grupo, etiqueta original, hoja revisada, observación de ambigüedad, responsable y decisión **`PENDING_G0_V1_3_1_APPROVAL`** para las **380 fotos**; SHA-256 `19e6505fc8aa2d7221524f35efe448667a5e9adb86f57339302af9d9b40d7649`.

La etiqueta proviene de la curación experta publicada por PlantVillage; Codex realizó revisión **interna visual de calidad y concordancia aparente**, sin nueva evaluación agronómica especializada. Los 140 casos sanos son hojas legibles sin lesiones evidentes de tizón en las hojas de revisión; las hojas `35.0`, `36.0` y `37.0` muestran daños o marcas leves, expresamente anotados por grupo, y conservan la etiqueta experta de origen. Las muestras de tizones muestran síntomas visibles compatibles a nivel de control interno, sin atribuir identificación causal independiente; las 80 hojas de otro cultivo corresponden visualmente a tomate. Si una revisión posterior cuestiona cualquiera de esas etiquetas, la foto o su grupo debe salir y la tabla G0 puede dejar de ser alcanzable.

La revisión de derechos sigue ligada a la [distribución PlantVillage del autor](https://huggingface.co/datasets/mohanty/PlantVillage), licencia **CC BY-SA 3.0**, revisión fijada, ruta y SHA-256 de cada archivo. El comprobante común se aplica al lote exacto; no se exige una carta por foto. Se conserva atribución y la condición publicada para algoritmos entrenados. La licencia, la etiqueta experta y el control visual interno son tres evidencias distintas.

## Partición candidata, aún sin manifiestos admitidos

El plan privado `.local/pv-g1/g1-v1.3.1-plan-verified/candidate-partitions.csv`, SHA-256 `017c0c74738736b43b8d67780b63a5309889be1b7665ae21543cc2a285de066b`, contiene **2.391 fotos originales/606 grupos** con fuente, ruta, SHA-256 comprobado contra el ZIP, licencia, etiqueta, `leaf_id`, partición candidata y evidencia de revisión. Todas las filas permanecen `PENDING_G0_V1_3_1_APPROVAL`. TRAIN/VAL de tizones y otro cultivo son candidatos reutilizados del lote v1.2.0 y requieren **readmisión v1.3.1**, no se cuentan como ya admitidos. Papa sana usa 80/20 del antiguo TRAIN, 12/3 no expuestos del antiguo VAL más 16/4 no evaluados del antiguo inventario TEST para el nuevo VAL, y 32/8 del `color_test.txt` oficial para el nuevo TEST. El TEST v1.2.0 abierto no aporta ninguna fila.

| Estrato | TRAIN candidato fotos/grupos | VAL candidato fotos/grupos | TEST nuevo candidato fotos/grupos | Mínimos propuestos satisfechos |
| --- | ---: | ---: | ---: | --- |
| `POTATO_EARLY_BLIGHT` | 541/136 | 165/42 | 80/20 | Sí, como plan |
| `POTATO_LATE_BLIGHT` | 499/129 | 153/39 | 80/20 | Sí, como plan |
| `POTATO_HEALTHY` | 80/20 | 28/7 | 32/8 | Sí, **sin margen de exclusión** |
| `OTHER_CROP` | 503/127 | 150/38 | 80/20 | Sí, como plan |

El verificador del plan confirmó **cero SHA-256 repetidos, cero `leaf_id` entre TRAIN/VAL/TEST, cero hashes o grupos del TEST v1.2.0 en el TEST nuevo, cero grupos G3 expuestos y bytes originales sin cambios**. Los 11 pares visuales están resueltos por exclusión de grupos antes de contar. No se calculó ninguna predicción, métrica de modelo ni umbral con estas imágenes.

## Condiciones pendientes para G1

1. **Aprobación explícita de la tabla G0 v1.3.1 por el responsable.** Hasta entonces v1.3.0 sigue siendo el último G0 numérico aprobado y el plan de 2.391 filas no es entrenable.
2. Convertir el plan en registros G1 `ADMIT` por archivo con derechos, revisión de etiqueta y calidad verificables, y manifiestos separados para los dos tizones, papa sana técnica y `OTHER_CROP`. Verificar sus bytes y el contrato v1.3.1 sin alterar el validador histórico v1.2.0.
3. Sellar el **nuevo** TEST de cuatro estratos después de validar los mínimos aprobados y la ausencia de fuga; conservar el sello privado y evitar cualquier uso para elegir pesos, arquitectura o umbral.

El comando `scripts/finalize_g1_v1_3_1.py` está preparado para comprobar de nuevo derechos, revisión, bytes, mínimos y aislamiento, generar manifiestos privados separados por estrato y sellar TEST **solo si** el JSON G0 pasa a `APPROVED_G0_DESIGN` con fecha y evidencia explícita de la aprobación del responsable. Su ejecución con el protocolo aún propuesto termina antes de escribir salida con `G0 v1.3.1 numeric table is not approved`; esa negativa se verificó el 2026-11-21. No se ha ejecutado una admisión positiva sobre el lote real.

Pruebas preparatorias: `python3 -m unittest tests.ml.test_g1_v1_3_inventory tests.ml.test_g1_v1_3_visual_resolution tests.ml.test_g1_v1_3_plan tests.ml.test_g1_v1_3_finalization_gate -v` (9 pruebas). El plan es reproducible con `scripts/prepare_g1_v1_3_review.py` y `scripts/plan_g1_v1_3_1.py`, partiendo de los archivos privados fijados. Los artefactos `.local/` no se suben a Git.
