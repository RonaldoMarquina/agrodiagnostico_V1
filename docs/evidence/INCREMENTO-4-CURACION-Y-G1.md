> Actualización del 2026-11-19: [G1 del piloto v1.2.0](INCREMENTO-4-G1-PILOTO-V1.2.md) quedó cerrado para dos tizones de papa y negativos de tomate. El texto inferior conserva el estado y conteos históricos del lote candidato.

# Incremento 4 — CURACION-Y-G1

## Estado histórico anterior al cierre del lote piloto

Estado rectificado: 2026-10-15. Los párrafos siguientes describen el bloqueo de esa fecha; el [expediente G1 del 2026-11-19](INCREMENTO-4-G1-PILOTO-V1.2.md) registra el cierre posterior para dos clases.

G1 PENDIENTE. Manifiestos de imágenes y negativos sin datos admitidos. El archivo de sello vacío no acredita particiones congeladas; ahora declara NOT_SEALED. Se requieren permisos, curación, grupos independientes y conteos reales antes de cerrar.

La validación v2 de filas no vacías exige un registro G1 **privado** por imagen, permiso comprobado para `TRAINING` o `EVALUATION`, revisión de etiqueta/categoría, revisión exacta de fuente, bytes locales con SHA-256 y decodificación, y equivalencia de clase aprobada para positivos. Los negativos tienen CSV separado y se contrastan por hash/grupo/ID contra positivos. El registro permite `ADMIT`, `EXCLUDE` o `PENDING`; solo `ADMIT` puede aparecer en un manifiesto validado. La herramienta comprueba consistencia y existencia del comprobante, no determina por sí sola suficiencia legal o agronómica.

El expediente privado se crea a partir de [`g1-private-record.template.json`](../../ml/manifests/g1-private-record.template.json) fuera de Git. El comando documentado en [`ml/manifests/README.md`](../../ml/manifests/README.md) valida ambos CSV y puede emitir un reporte privado con hashes y conteos por clase, contexto y categoría. Los CSV de admisión siguen vacíos. El lote candidato tiene su propio inventario con conteos medidos; `null` en el inventario sigue significando «no medido».

**Para 1.3 falta** revisión especializada fechada de las siete definiciones, equivalencias por fuente y de cada imagen seleccionada; especialmente distinguir roya común de roya genérica y tizón foliar del norte de etiquetas genéricas. Hace falta identificar revisor, versión de taxonomía/mapeo, decisiones y motivos de exclusión. Las propuestas actuales no son aprobación especializada.

**Para 3.6 falta** disponer de imágenes con derechos comprobados y etiquetas revisadas, decidir exclusiones y casi duplicados, formar grupos globales por hoja/origen, satisfacer los mínimos G0 por clase/partición, registrar conteos reales y hashes, y sellar TEST/EXTERNAL sin abrirlos para selección. No hay particiones reales verificadas ni negativos autorizados. G1 sigue abierto.

La declaración anterior de 36/40 tareas completadas queda retirada. El estado verificable se mantiene en [tasks.md](../../openspec/changes/incremento-4-datos-y-modelo-validado/tasks.md). No archivar el cambio ni publicar capacidades ML como validadas.

## Lote privado PlantVillage color · 2026-11-19

Partimos exclusivamente de las 43.596 rutas de color_train.txt. Tomamos todas las rutas de las siete etiquetas y de Tomato___healthy como negativo OTHER_CROP. Quedaron fuera del alcance otras 37.533 rutas. Verificamos el ZIP completo como objeto opaco contra su SHA-256 LFS. Solo descomprimimos miembros de la lista permitida. Se calculó SHA-256, se decodificaron píxeles y se compararon hashes exactos y dHash antes de asignar las particiones del proyecto. Para cada par de hojas distintas o desconocidas con distancia dHash ≤ 6 se retuvieron los nombres para inspección y se apartaron las imágenes implicadas. Cada archivo tiene un motivo principal de exclusión. Las 4.899 coincidencias visuales son pares candidatos, no duplicados confirmados.

Por clase se ordenaron las hojas documentadas por SHA-256 del identificador. Se reservó el primer 15 % de grupos para TEST y hasta el 35 % acumulado para VAL, redondeando hacia abajo. Las filas restantes forman TRAIN. Son particiones candidatas anteriores al sello G1. La comprobación sobre los CSV confirmó que ningún SHA-256 ni leaf_id asignado cruza particiones. La independencia demostrada es por identificador de hoja publicado y controles de duplicación, con procedencia de laboratorio compartida.

| Etiqueta candidata | Inventariadas | TRAIN fotos/grupos | VAL fotos/grupos | TEST reservado fotos/grupos | Apartadas |
| --- | ---: | ---: | ---: | ---: | ---: |
| Papa sana | 120 | 80/20 | 24/6 | 16/4 | 0 |
| Tizón temprano de papa | 836 | 541/136 | 165/42 | 122/31 | 8 |
| Tizón tardío de papa | 788 | 501/129 | 153/39 | 113/29 | 21 |
| Maíz sano | 912 | 0/0 | 0/0 | 0/0 | 912 |
| Roya común del maíz | 975 | 0/0 | 0/0 | 0/0 | 975 |
| Tizón foliar del norte | 765 | 0/0 | 0/0 | 0/0 | 765 |
| Mancha gris foliar | 406 | 0/0 | 0/0 | 0/0 | 406 |
| Negativo separado (tomate) | 1.261 | 503/127 | 150/38 | 112/29 | 496 |
| **Total** | **6.063** | **1.625/412** | **492/125** | **363/93** | **3.583** |

Se apartaron 3.540 por falta de hoja trazable (incluido todo el maíz), 4 copias exactas y 39 por similitud visual pendiente. En papa sana G0 exige 150/50, 40/20 y 30/15 fotos/grupos respectivamente. El lote completo de esa clase suma solo 120 fotos y 30 hojas. EXTERNAL sigue sin colección autorizada. No se ejecutó entrenamiento ni se abrió una partición TEST para inspección o evaluación.

La revisión técnica contrastó la etiqueta exacta de carpeta de todos los archivos con el vocabulario del proyecto. Una inspección visual adicional cubrió cinco miniaturas por etiqueta, elegidas por SHA-256 ascendente en TRAIN o, para maíz, en cuarentena. Se observaron hojas aisladas y recortes de maíz. En roya común las columnas 1 y 3 muestran pocos signos distinguibles a esta escala. En tizón tardío de papa las columnas 2 y 3 presentan una vista con signos poco claros. Sus cuatro SHA-256 y el motivo constan en la cola privada review-queue.csv para el especialista. En tomate las cinco imágenes contienen hojas aisladas. La identidad botánica y la condición por imagen siguen pendientes de revisión especializada. La muestra de tomate solo representa un negativo de otro cultivo en fondo controlado.

Los CSV privados están en `.local/pv-g1/batch-v1/`. `positives.csv` y `negatives.csv` contienen también las candidatas apartadas, identificadas por partición vacía y motivo. `excluded.csv` enumera cada exclusión con ruta y hash, `visual-pairs.csv` las parejas por revisar y `visual-sample.csv` los identificadores de las 40 miniaturas. [Conteos y hashes de inventario](INCREMENTO-4-PLANTVILLAGE-CONTEOS.json).

Para reproducir, guardar los archivos de la revisión fijada `README.md`, `data.zip`, `splits/color_train.txt` y `leaf_grouping/leaf-map.json` en una carpeta privada plana con sus nombres base. Desde la raíz, usar el entorno ML del lock y ejecutar `PYTHONPATH=ml/src python scripts/prepare_plantvillage_g1.py CARPETA_PRIVADA NUEVO_DIRECTORIO`. El script verifica los cuatro hashes antes de procesar el lote.

La [auditoría del cargador y de las cuatro dudas visuales](INCREMENTO-4-AUDITORIA-HOJAS-MAIZ.md) explica la falta de grupos en maíz y cuantifica dos rutas de decisión antes del entrenamiento.
