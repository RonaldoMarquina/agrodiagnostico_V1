# G0 v1.3.1 — propuesta de reducción del estrato papa sana

> **Actualización 2026-11-21:** el responsable [aprobó exactamente esta tabla](INCREMENTO-4-G0-V1.3.1-APROBACION.md). Las referencias inferiores a estado pendiente describen la propuesta antes de esa decisión; la [admisión G1 posterior](INCREMENTO-4-G1-V1.3.1-ADMISION.md) se documenta por separado.

Fecha de propuesta: **2026-11-21** (America/Lima). **Estado: pendiente de aprobación explícita del responsable del proyecto.** [Protocolo propuesto](../../ml/evaluation/protocol-g0.v1.3.1.json). G0 v1.3.0, su aprobación del 2026-11-20 y el bundle/TEST/resultados v1.2.0 permanecen históricos e intactos. No se entrenó ni se abrió un TEST v1.3.1.

## Motivo y tabla propuesta

El [inventario G1 reproducible](INCREMENTO-4-G1-V1.3-INVENTARIO-2026-11-21.md) halló 140 fotos originales de papa sana en 35 `leaf_id` publicados de PlantVillage `color` tras excluir las 12 fotos/3 grupos expuestos en G3. La parte `color_test.txt` oficial aporta 32 fotos/8 grupos sanos y grupos nuevos de ambos tizones y tomate. Ninguna fuente adicional examinada acredita a la vez la etiqueta sana y el grupo independiente. La tabla v1.3.0 exige 220/85 en las tres particiones sanas y no es realizable con este lote.

| Estrato técnico | TRAIN fotos/grupos | VAL fotos/grupos | TEST nuevo fotos/grupos | Cambio frente a G0 v1.3.0 |
| --- | ---: | ---: | ---: | --- |
| `POTATO_EARLY_BLIGHT` | ≥150/50 | ≥40/20 | ≥30/15 | Sin cambio |
| `POTATO_LATE_BLIGHT` | ≥150/50 | ≥40/20 | ≥30/15 | Sin cambio |
| `POTATO_HEALTHY` | **≥80/20** | **≥28/7** | **≥32/8** | Antes ≥150/50, ≥40/20, ≥30/15 |
| `OTHER_CROP` | ≥150/50 | ≥40/20 | ≥30/15 | Sin cambio |

La propuesta reserva los 80/20 sanos previamente inventariados en TRAIN; combina 12/3 de VAL no expuestos con 16/4 candidatos nunca evaluados del antiguo `color_train` para VAL 28/7; reserva 32/8 del `color_test.txt` del autor para el **nuevo** TEST. El TEST v1.2.0 abierto y los tres grupos G3 siguen excluidos. Esta asignación es todavía **candidata**, sujeta a revisión por archivo, derechos, etiquetas, pares visuales y validación de ausencia de fuga. No hay manifiestos v1.3.1 admitidos ni sello.

## Criterios conservados y pérdida de capacidad

Se conservan sin modificación: solo dos tizones publicables; `POTATO_HEALTHY` como rechazo técnico `NO_CONCLUYENTE` y `OTHER_CROP` por separado; F1, recall, cobertura, error selectivo, FPR ≤0,05 y rechazo ≥0,95 por estrato negativo, ECE, CPU, numeradores/denominadores, umbral elegido en VAL y congelado antes de TEST, evaluación única y EXTERNAL no disponible. No se relaja ningún umbral de rendimiento para hacer pasar un resultado.

La reducción sana deja **menos diversidad independiente**: TRAIN pasa de ≥50 a ≥20 hojas, VAL de ≥20 a ≥7 y TEST de ≥15 a ≥8. Con 32 fotos sanas en TEST, una falsa publicación de tizón supone 1/32 = 0,03125; dos suponen 2/32 = 0,0625 e incumplen FPR ≤0,05. Las cuatro vistas por hoja están correlacionadas: el tamaño efectivo de TEST son solo ocho hojas, por lo que un resultado favorable no prueba rechazo robusto fuera de PlantVillage ni generalización en campo. El lote sano propuesto usa **las 140 fotos/35 grupos completos**, sin margen para descartar otra hoja o foto y seguir cumpliendo todos los mínimos. Si la revisión excluye más datos, G1 no puede cerrarse con esta tabla; hace falta otra fuente o una decisión nueva, antes de entrenar.

## Decisión pendiente

El responsable debe aprobar o corregir expresamente **la tabla numérica por estrato y partición** antes de considerar G0 v1.3.1 cerrado. La instrucción de preparar una propuesta no se interpreta como aprobación de estos números. Hasta esa decisión: G0 v1.3.1 abierto; revisión G1 preparatoria permitida; ninguna admisión final, entrenamiento, selección con TEST ni activación de política. El [expediente de revisión privada](INCREMENTO-4-G1-V1.3-INVENTARIO-2026-11-21.md) distingue candidatos, exclusiones y aprobaciones pendientes.
