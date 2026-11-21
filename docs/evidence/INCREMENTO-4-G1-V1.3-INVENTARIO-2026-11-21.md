# G1 v1.3.0 — inventario de candidatos y fuentes, sin admisión

> Actualización posterior del 2026-11-21: los 11 pares visuales se resolvieron por exclusión conservadora de sus grupos y se preparó una [revisión visual y partición candidata para G0 v1.3.1](INCREMENTO-4-G1-V1.3.1-REVISION-PREPARATORIA.md). Los conteos de pares pendientes de esta página son la instantánea **anterior** a esa resolución; ninguna imagen se ha admitido aún.

Fecha: **2026-11-21** (America/Lima). Estado: **G1 abierto; cero imágenes admitidas y cero particiones v1.3.0 selladas**. No se entrenó, evaluó ni abrió el TEST nuevo. El bundle, TEST y resultados v1.2.0 siguen como evidencia histórica.

## Registro reproducible por archivo

Se auditó la distribución PlantVillage `color` de la cuenta del autor, revisión `9e97599868962bd0079b8db4b7f1efa9185fa1e7` ([fuente y licencia CC BY-SA 3.0](https://huggingface.co/datasets/mohanty/PlantVillage)). El ZIP local fijado tiene SHA-256 `fba30c6a7965e49be94b47a62f8aff6cfb1c35c27f475f22092b56db41745e84`; `leaf-map.json`, `3b4b253683c6911744959a3870a92509b1faa1ee34e9f8585e21d0fe6337a25b`; `splits/color_train.txt`, `c43e0205b321d1c929116f5df1842348ac1e5c4861306e081416785d3c439dbd`; y el **manifiesto oficial** `splits/color_test.txt`, `7a7257dcb5f9456feae6ae81248d29c28f45dc4cd41a00c13a5c5c198c5f2f8b`. La licencia del lote se vincula a cada archivo por revisión, ruta y SHA-256; las obligaciones de atribución y ShareAlike, incluida la condición publicada para algoritmos entrenados, constan en el [expediente de fuentes](INCREMENTO-4-EXPEDIENTE-FUENTES.md). Esta trazabilidad de derechos no basta por sí sola para admitir una foto.

Comando, desde la raíz del proyecto, sin descargas ni acceso a modelos:

```bash
python3 scripts/audit_plantvillage_g1_v1_3.py \
  .local/pv-g1 .local/pv-g1/pilot-v1.2 \
  .local/pv-g1/audit-v1.3-20261121-final
```

El archivo privado `.local/pv-g1/audit-v1.3-20261121-final/registry.csv` contiene **858 filas**, una por foto examinada: fuente, revisión, partición original del autor, ruta, SHA-256 de los bytes originales, licencia y comprobante, `leaf_id` del mapa publicado, etiqueta fuente y objetivo técnico, partición candidata, revisión de calidad/etiqueta, decisión y motivo. SHA-256 del registro: `42dd34db9a9c814db6f18035bf55f167fa90e7f7ad4a7337ef296f1e46d1bfdd`. El archivo privado `visual-pairs.csv`, SHA-256 `add00903d247ad5e0babde45318ff8ad3c4faf8d5fa2c89dfaca14f1f24ef823`, identifica **11 pares** de dHash ≤ 6 entre grupos candidatos o con particiones históricas. Es una cola de revisión, no un juicio agronómico ni prueba de duplicación. Los 2.358 archivos del lote admitido v1.2.0 se usaron únicamente como referencia de hashes y pares; sus 347 archivos de TEST no se cuentan como TEST nuevo.

**Decisiones actuales:** 118 `EXCLUDE` (12 fotos de los tres grupos sanos G3 expuestos y 106 tomates sin `leaf_id` verificable); 740 `PENDING` por revisión visual interna y partición definitiva. Ninguna fila dice `ADMIT`. Los 11 pares pendientes afectan 13 fotos del candidato de tizón tardío y una de tizón temprano, con posibles repeticiones en la cola; por prudencia, el conteo limpio de abajo aparta el **grupo completo** de cualquier foto con par sin resolver. La procedencia experta de etiquetas PlantVillage está documentada; esta auditoría solo efectuó decodificación, dimensiones, contraste, SHA-256, grupo y cribado dHash. **No se hizo una nueva revisión agronómica independiente ni una inspección visual completa por archivo.**

## Conteos reales por estrato y partición candidata

Formato `fotos/grupos leaf_id distintos`. `TRAIN/VAL/TEST histórico` son datos del ciclo v1.2.0 o del inventario previo, **no admisiones v1.3.0**. `TEST autor` es la parte `color_test.txt` nunca usada por el G2 v1.2.0; sigue siendo candidata y no hay sello de TEST v1.3.0.

| Estrato | TRAIN previo reutilizable solo tras readmisión | VAL previo reutilizable solo tras readmisión | TEST previo no usado en G2 v1.2.0 | TEST autor: inventariado → con grupo → sin par pendiente | Mínimos G0 por TRAIN / VAL / TEST |
| --- | ---: | ---: | ---: | ---: | --- |
| `POTATO_EARLY_BLIGHT` | 541/136 | 165/42 | TEST v1.2.0 **122/31 excluido del nuevo TEST** | 164/41 → 164/41 → **160/40** | 150/50; 40/20; 30/15 |
| `POTATO_LATE_BLIGHT` | 499/129 | 153/39 | TEST v1.2.0 **113/29 excluido del nuevo TEST** | 212/53 → 212/53 → **168/42** | 150/50; 40/20; 30/15 |
| `POTATO_HEALTHY` | 80/20 | 12/3 tras excluir 12 fotos/3 grupos G3 | 16/4 de `color_train`, no evaluado en G2; candidato, no sellado | 32/8 → 32/8 → **32/8** | 150/50; 40/20; 30/15 |
| `OTHER_CROP` (tomate sano) | 503/127 | 150/38 | TEST v1.2.0 **112/29 excluido del nuevo TEST** | 330/56 → 224/56 → **224/56** | 150/50; 40/20; 30/15 |

Los archivos del `TEST autor` pertenecen a rutas distintas de `color_train.txt`; en estas cuatro etiquetas, los `leaf_id` verificables tampoco se solapan con el split de entrenamiento del autor. El cribado comparó hashes y dHash contra TRAIN, VAL y TEST históricos, y rechazó los grupos expuestos G3. Los conteos limpios **no son aprobaciones de etiquetas ni fotos admitidas**. La asignación final requiere nueva revisión de calidad/ambigüedad, resolución de pares, readmisión de TRAIN/VAL, selección de negativos y sello que impida fugas entre particiones.

La cifra **202 fotos/103 grupos** del protocolo era el faltante operativo del inventario anterior, que no incluía este `color_test.txt` del autor. El nuevo inventario tiene **632 fotos/158 grupos** con `leaf_id` verificable en el split del autor; tras apartar por grupo los pares visuales pendientes, **584/146** quedan mecánicamente despejadas pero aún sin admisión. Las nuevas candidaturas de los dos tizones y otro cultivo pueden cubrir los mínimos de sus TEST si pasan G1. Aun usando las **140 fotos/35 grupos** de papa sana que quedan en PlantVillage tras la exclusión G3 (108/27 en `color_train` y 32/8 en `color_test`), los tres mínimos sanos suman **220 fotos/85 grupos**. Por tanto faltan **al menos 80 fotos originales en 50 grupos sanos demostrables** de otra procedencia, antes de cualquier exclusión adicional; es un límite inferior sujeto a una nueva asignación por grupo, no un lote ya admisible. Si se conservan las particiones sanas previas sin reasignar, el faltante operativo sería mayor. El cómputo agregado de fotos de otras clases no resuelve el déficit sano.

## Fuentes adicionales evaluadas para papa sana

| Distribución exacta | Derechos y etiqueta | Grupos originales comprobables | Decisión actual |
| --- | --- | --- | --- |
| [Irish Potato Imagery Dataset, Zenodo 8286529, v01](https://zenodo.org/records/8286529) | API de la versión: CC BY 4.0; el editor declara 20.438 JPG sanos y validación por patólogos en su [artículo](https://pmc.ncbi.nlm.nih.gov/articles/PMC12020891/). Índice ZIP privado de `healthy.zip` (SHA-256 `bc5801f0e48d0dfc4bfcdb3e2760e159f503f628cf3f9d6e892c39c3970e9382`) confirma 20.438 nombres JPG únicos del tipo `healthyNNN.jpg`; también contiene metadatos `__MACOSX`. | **0 demostrados para G1**: el número de archivo no identifica hoja, planta ni sesión. El artículo menciona un mapeo de nombres originales, pero no se localizó en la distribución examinada. | `PENDING_GROUP_PROOF`; no se descargó ni admitió el lote de fotos. Solicitar al autor la tabla de captura/IDs, o verificar otra publicación original. |
| [Irish Potato Leaf Image Dataset, Zenodo 17553016, v1](https://zenodo.org/records/17553016) | API: CC BY 4.0; seis ZIP de papa sana, entre otros. El índice remoto de `HEALTHY_6.zip` contiene 665 JPG `healthy5001.jpg`…`healthy5665.jpg`. | **0 demostrados**: numeración secuencial sin relación de planta/hoja publicada. Posible relación con el dataset anterior todavía sin resolver; no contar como fotos independientes de él. | `PENDING_GROUP_AND_PROVENANCE_PROOF`. |
| [Potato Leaf Disease Dataset, Mendeley d5b3fzpw3g, v1](https://data.mendeley.com/datasets/d5b3fzpw3g/1) | CC BY 4.0; el editor declara 804 originales en **seis clases en total** y 2.400 tras aumentación. No publica en la ficha cuántos originales sanos ni una tabla que una derivados con originales. | **0 demostrados**. | `PENDING_ORIGINAL_AND_GROUP_PROOF`; no confundir derivados con fotos originales. |
| [Potato Leaf data set, Zenodo 7938231, v1](https://zenodo.org/records/7938231) | API: `cc-by`; CSV descargado y fijado por SHA-256 `eb2b340d306c82e890e131352fbd34e30e37b08b61be58b8f9e750d249b123f8`. | **110 IDs `Plant_no` distintos** en 110 filas de mediciones. | `PENDING_LABEL_AND_INPUT_MATCH`: el editor describe segmentación/biomasa, no certifica `POTATO_HEALTHY`; las fotos son de plantas completas. Ningún grupo cuenta para el estrato sano hasta resolver ambos puntos. |

No se fuerza `image_id = leaf_id` ni se cuentan ZIP grandes como grupos independientes. La condición de licencia del editor y los derechos de un archivo finalmente seleccionado se registrarán por separado. Tampoco se ha medido rendimiento agronómico con estas fuentes.

## Estado de las tareas

- **2.1 abierta:** el registro cubre SHA, derechos de lote y `leaf_id` de 120 fotos sanas del inventario inicial; excluye 12/3 G3. Falta resolver revisión visual/ambigüedad por archivo y dictar admisión de las 108 restantes.
- **2.2 abierta:** faltan al menos 80 fotos/50 grupos sanos admisibles y una asignación TRAIN/VAL que cumpla mínimos tras exclusiones.
- **2.3 abierta:** hay candidatos nuevos para los TEST de ambos tizones y otro cultivo, pero faltan revisión, selección final, readmisión y sello.
- **2.4 abierta; G1 abierto:** faltan TEST sano completo, cuatro manifiestos nuevos validados, exclusiones resueltas y sello. **0/4 estratos admitidos para v1.3.0**.

Prueba local: `python3 -m unittest tests.ml.test_g1_v1_3_inventory -v` (rechazos de grupo expuesto, `leaf_id` ausente y fuente alterada). El registro privado y esta nota permiten continuar sin abrir el TEST ni modificar G0 v1.3.0.
