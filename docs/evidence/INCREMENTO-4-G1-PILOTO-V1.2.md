# G1 del piloto de dos tizones de papa

19 de noviembre de 2026. Protocolo aprobado G0 v1.2.0. **G1 cerrado para este lote y estas dos clases.** Las rutas de imágenes, manifiestos y el registro por archivo se conservan en `.local/pv-g1/pilot-v1.2/`, fuera de Git. No se ejecutó entrenamiento ni evaluación de TEST.

## Procedencia, derechos y revisión

Se utilizó únicamente la distribución `color` de PlantVillage publicada por la cuenta del autor, revisión `9e97599868962bd0079b8db4b7f1efa9185fa1e7`. El preparador anterior verificó los SHA-256 de `README.md`, `data.zip`, `color_train.txt` y `leaf-map.json`. El expediente de origen vincula cada ruta y SHA-256 al lote declarado CC BY-SA 3.0. La atribución, ShareAlike y la condición publicada para algoritmos entrenados se registran en [el expediente de fuentes](INCREMENTO-4-EXPEDIENTE-FUENTES.md). Las únicas equivalencias positivas aprobadas para este piloto son `Potato___Early_blight` → `POTATO_EARLY_BLIGHT` y `Potato___Late_blight` → `POTATO_LATE_BLIGHT`. [Distribución fijada](https://huggingface.co/datasets/mohanty/PlantVillage/commit/9e97599868962bd0079b8db4b7f1efa9185fa1e7) · [Documentación original de la curación experta](https://arxiv.org/pdf/1511.08060).

La documentación original, sección *Technical validation*, indica que expertos en patología vegetal establecieron los estados de las hojas y que PlantVillage incorporó solo hojas identificadas por esos expertos. El proyecto acepta esa **proveniencia experta de PlantVillage + control interno de calidad**. Codex no realizó una nueva evaluación agronómica independiente. El control interno verificó decodificación, SHA-256, dimensiones y contraste de los 2.358 archivos seleccionados y comparó duplicados exactos y candidatos visuales con el lote inventariado. La inspección visual muestral previa cubrió cinco imágenes por etiqueta; dos imágenes de tizón tardío con signos dudosos se excluyeron por SHA-256. La revisión interna no confirma por sí misma la etiología de cada fotografía. [Método reproducible](../../scripts/admit_plantvillage_pilot_g1.py).

El manifiesto separado de negativos contiene únicamente hojas `Tomato___healthy` con `leaf_id` publicado y categoría `OTHER_CROP`. **Papa sana no se usó como negativo.** Los permisos y el control interno se registran por SHA-256 en el expediente privado. PlantDoc, PlantSeg y otras clases de PlantVillage permanecen fuera de esta admisión.

## Particiones y mínimos

Cada grupo es el `leaf_id` publicado con prefijo de fuente. Ninguna fila seleccionada usa un identificador `fallback_*`. Las vistas de una hoja comparten partición. Los manifiestos privados positivos y negativos se dividen en TRAIN, VAL y TEST. El validador v2 comprobó bytes, permiso, revisión, fuente, etiqueta y separación. El verificador confirmó ausencia de SHA-256 repetidos, `leaf_id` entre particiones y parejas visuales marcadas que permanezcan seleccionadas. El control visual usa dHash a distancia ≤ 6, por lo que esta comprobación acredita los pares detectados con ese método y la separación por hoja. [Verificador](../../scripts/verify_plantvillage_pilot_g1.py).

| Clase | TRAIN fotos/grupos | VAL fotos/grupos | TEST sellado fotos/grupos | Mínimos TRAIN, VAL, TEST |
| --- | ---: | ---: | ---: | --- |
| Tizón temprano de papa | 541/136 | 165/42 | 122/31 | 150/50, 40/20, 30/15 |
| Tizón tardío de papa | 499/129 | 153/39 | 113/29 | 150/50, 40/20, 30/15 |
| Negativo de otro cultivo, tomate | 503/127 | 150/38 | 112/29 | Manifiesto separado |

Se admitieron 1.593 positivos y 765 negativos. Se excluyeron 527 rutas con motivo y SHA-256 en el registro privado. Los motivos son 482 sin `leaf_id`, 39 parejas visuales por resolver, 4 duplicados exactos y 2 dudas visuales internas de tizón tardío (`00a66ec071c874a29abd2d5e886fe272d7906f32c32d1af9c8ecc6af9c349cdd` y `01dd20dcb5cad712b50235237997c6d10f23fe0c7225e5ea7dcd510efae7982c`). La revisión visual muestral y el control de contraste/dimensiones no encontraron otros archivos que requirieran exclusión.

| Archivo privado | SHA-256 |
| --- | --- |
| `positives.csv` | `1ac9dffd54a80cfc932eace3594ec01db2ff70e03dea5ed39855a04f5250c8b3` |
| `negatives.csv` | `543941c5b9ea06cab42796474a33dce5281fa11b3f1c198ae2e746ef10547d9e` |
| `exclusions.csv` | `f7ccb8addaa1adb604e677c3193f8074fc8f2fa0886266b1166d542d8997f519` |
| `evidence.json` | `8ed8d874fdce503fc639ee320789f694083468e24cbb59800a8b75050e93eaa5` |
| `test-seal.json` | `3f89a833ad38782f7d7139283ef444321d139a8798e8d6fec8053e3e79819e07` |

El sello registra protocolo `1.2.0`, 347 filas de TEST entre positivos y negativos, y digest de su contenido. Una segunda ejecución verificó el mismo sello sin modificarlo. El verificador comprueba también los bytes exactos de los CSV materializados; una alteración inocua de `test-positives.csv` en una copia privada fue rechazada. Las rutas privadas `train-*.csv`, `val-*.csv` y `test-*.csv` materializan cada partición. La selección del modelo y del umbral corresponde a VAL. TEST permanece reservado para G2 después de congelar modelo y calibración.

Para verificar el lote desde la raíz, ejecutar `python3 scripts/validate_dataset.py --v2 --manifest .local/pv-g1/pilot-v1.2/positives.csv --negative-manifest .local/pv-g1/pilot-v1.2/negatives.csv --images-dir .local/pv-g1/batch-v1 --evidence .local/pv-g1/pilot-v1.2/evidence.json` y `PYTHONPATH=ml/src python3 scripts/verify_plantvillage_pilot_g1.py .local/pv-g1/pilot-v1.2 .local/pv-g1/batch-v1`. El reporte privado `g1-report.json` contiene conteos y hashes. Los mínimos de ambas clases pasan. G2 aún no tiene rendimiento agronómico medido ni aprobación de release.
