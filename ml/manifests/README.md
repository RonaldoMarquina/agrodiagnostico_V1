> Estado actual: v1.2.0 y v1.3.2 son históricos; v1.3.2 fue evaluado y no aprobado. En [v1.4.0](../../docs/evidence/INCREMENTO-4-G0-G1-V1.4.0-MATERIALIZACION.md), G0/G1 están cerrados. El manifiesto privado PlantVillage contiene solo TRAIN/VAL con `leaf_id`; Sikkim v1 contiene 362 archivos sellados solo como EXTERNAL, con unidad de independencia limitada a imagen única. Los registros están en `.local/ml-v1.4.0/` y permanecen fuera de Git. No se ha entrenado ni abierto EXTERNAL para modelado.

> Protocolo vigente para el ciclo nuevo: [G0 v1.4.0](../evaluation/protocol-g0.v1.4.0.json). El [sello EXTERNAL](../evaluation/external-seal.v1.4.0.json) y las [decisiones visuales](sikkim-v1-visual-decisions.json) son públicas y sanitizadas; el manifiesto por archivo es privado. Los protocolos y resultados anteriores permanecen inmutables.

El lote v1.3.1 usa [equivalencias G1 fijadas](g1-v1.3.1-source-labels.json) y un [verificador independiente](../../scripts/verify_g1_v1_3_1.py). `POTATO_HEALTHY` y `OTHER_CROP` son objetivos técnicos de rechazo; la taxonomía, bundle, política y contratos de inferencia v1.3.1 siguen pendientes en la tarea 1.2/3.1. El manifiesto de admisión **no** activa esas clases como diagnósticos publicables. El TEST sellado está reservado para una sola evaluación después de congelar pesos y umbral con VAL.

# Inventario inicial v1

Actualización de diseño v2: `MAIZE_LEAF_BLIGHT` se denomina **tizón foliar del norte**; `Corn rust leaf`, `corn rust` y `Corn leaf blight` están `UNMAPPED` en [`label-mappings.v2.json`](label-mappings.v2.json). El responsable reservó este vocabulario históricamente; G0 v1.2.0 solo incluye dos tizones de papa; equivalencias de imágenes y derechos siguen pendientes en G1, por lo que no es una clase soportada. Los conteos v1 de abajo son metadatos históricos de etiquetas originales y no acreditan equivalencia ni admisión. Véase el [protocolo G0](../evaluation/protocol-g0.v1.2.0.json).

Consulta de fuentes: 2026-09-29. Tres fuentes **PENDING**, siete códigos históricos (dos clases candidatas del piloto), veintiún mapeos de inventario. No hay imágenes admitidas ni modelo evaluado. Los conteos locales por clase son `null` (no medidos); `images.v1.csv` contiene únicamente la cabecera, cuya ausencia de filas sí se comprueba. No confundir ese cero de filas con un conteo de fotografías en el equipo.

| Archivo | Uso |
| --- | --- |
| [sources.v1.json](sources.v1.json) | Autores, revisión, permisos, restricciones, cantidades, captura y pendientes por fuente |
| [taxonomy.v1.json](taxonomy.v1.json) | Siete códigos reservados, cultivo, definición pendiente y estado candidato |
| [label-mappings.v1.json](label-mappings.v1.json) | Correspondencias provisionales y etiquetas aún no mapeadas |
| [manifest-row.schema.json](manifest-row.schema.json) | JSON Schema 2020-12 aplicado a cada fila CSV |
| [images.v1.csv](images.v1.csv) | Manifiesto real inicial vacío; no contiene fixtures |
| [research-evidence.v1.json](research-evidence.v1.json) | Revisiones y consultas de metadatos que sustentan los conteos |

## Fuentes, versiones y permisos

- **PlantVillage:** repositorio de los autores y [distribución de la cuenta del autor, revisión `9e97599868962bd0079b8db4b7f1efa9185fa1e7`](https://huggingface.co/datasets/mohanty/PlantVillage/commit/9e97599868962bd0079b8db4b7f1efa9185fa1e7), con configuración candidata `color`. Su tarjeta declara CC BY-SA 3.0 y el artículo original aclara una condición sobre algoritmos entrenados. La revisión, ruta y SHA-256 vinculan el lote color seleccionado a la licencia común. La matriz de fuentes recoge la atribución y condiciones de publicación del modelo. El README publica 54.306 imágenes globales; no se suman variantes de color/gris/segmentación como fotografías independientes. [Referencia primaria](https://github.com/spMohanty/PlantVillage-Dataset).
- **PlantDoc:** se inventaría Cropped-PlantDoc para clasificación, separado del repositorio de detección. Su [README](https://github.com/pratikkayal/PlantDoc-Dataset) reporta 2.598 puntos globales y su [licencia](https://github.com/pratikkayal/PlantDoc-Dataset/blob/5467f6012d78d1c446145d5f582da6096f852ae8/LICENSE.txt) declara CC BY 4.0. Los conteos de carpetas son metadatos del repositorio, no una reconciliación de ese total ni una auditoría de derechos de fotografías recopiladas de Internet.
- **PlantSeg:** el [README](https://github.com/tqwei05/PlantSeg) enlaza [v5](https://zenodo.org/records/14935094), cuyos metadatos declaran CC BY 4.0. La [v7](https://zenodo.org/records/17719108) declara CC BY-NC 4.0. Se sigue v7 como candidata, conservando el contraste; ningún permiso se traslada entre versiones. Las etiquetas proceden del código de los autores en revisión fijada y requieren comprobar correspondencia con el archivo v7 antes de importar. El README expresa un total superior a 11.400; se conserva como descripción, no como total exacto de v7.

`DECLARED_BY_PUBLISHER` distingue una declaración pública de `VERIFIED_FOR_PROJECT`. Ninguna fuente está autorizada para el entrenamiento por este inventario. Para admitirla se requiere evidencia aplicable a la revisión y uso previstos, resolución de restricciones y revisión documentada; no basta cambiar una casilla. Sin permiso demostrado permanece `PENDING` o `EXCLUDED`. La comprobación automática valida presencia y coherencia de evidencia; no certifica derechos de terceros.

## Cantidades y etiquetas candidatas

Valores siguientes: entradas de archivos de imagen en metadatos remotos; no bytes descargados, imágenes decodificadas o clases clínicamente revisadas. Para PlantVillage se consultó por separado el árbol de cada carpeta (respuesta `truncated=false`); se descartaron los árboles recursivos generales truncados. Para PlantDoc se contó el árbol completo de la revisión fijada, sumando `train/` y `test/`, extensiones `.jpg`, `.jpeg`, `.png` sin distinguir mayúsculas. Los URL exactos y métodos están en el JSON. Repetir la consulta es una acción manual, no parte del validador ni de CI.

| Clase candidata | PlantVillage remoto | PlantDoc remoto | PlantSeg remoto | Local, todas las fuentes |
| --- | ---: | ---: | --- | --- |
| POTATO_HEALTHY | 152 | Desconocido, sin mapeo | Desconocido, sin mapeo | No medido |
| POTATO_EARLY_BLIGHT | 1000 | 117 | No medido | No medido |
| POTATO_LATE_BLIGHT | 1000 | 105 | No medido | No medido |
| MAIZE_HEALTHY | 1162 | Desconocido, sin mapeo | Desconocido, sin mapeo | No medido |
| MAIZE_COMMON_RUST | 1192 | 116 | No medido | No medido |
| MAIZE_LEAF_BLIGHT | 985 | 192 | No medido | No medido |
| MAIZE_GRAY_LEAF_SPOT | 513 | 68 | No medido | No medido |

Las cifras se asocian a etiquetas originales exactas en `sources.v1.json`. Las correspondencias, incluso «rust» → «roya común», necesitan revisión. «Northern Leaf Blight» no redefine automáticamente «tizón foliar» de V1. `UNMAPPED` no significa que una clase nunca pueda existir en la fuente. Las demás etiquetas de los datasets quedan fuera de este inventario V1. Ayacucho externo está **UNAVAILABLE**: sin datos ni permisos entregados; no se declara evaluación externa.

## Contrato CSV

UTF-8, cabecera única con exactamente estos campos (orden libre): `image_id`, `sha256`, `crop_code`, `class_code`, `source`, `license`, `capture_context`, `label_quality`, `split_group`, `split`. Cada fila se transforma en un objeto JSON para validar el esquema y luego se comprueban integridad, elegibilidad y fugas globales. No se admiten campos adicionales de bytes, coordenadas o identificadores de usuario. SHA-256 es hexadecimal minúsculo de 64 caracteres; IDs/grupos son opacos sin rutas. `source` referencia una entrada del inventario y `license` debe coincidir con ella.

Particiones: `TRAIN`, `VAL`, `TEST`, `EXTERNAL`. `label_quality=REVIEWED` se exige a filas reales; las no revisadas se conservan fuera del manifiesto admitido. `SOURCE_ONLY` existe en el esquema para expresar procedencia, pero no supera la admisión real. Los fixtures usan `SYNTHETIC` en un modo interno exclusivo de pruebas: el CLI de manifiestos reales los rechaza. El inventario inicial vacío puede pasar su verificación documental; un CSV vacío pasado expresamente con `--manifest` falla.

Los códigos v1 quedan reservados: no cambiar cultivo/significado ni reciclar códigos retirados. Conservar mapas publicados y sus versiones; un cambio semántico requiere nuevo código, decisión revisada y actualización de contratos antes de consumidores. El validador detecta códigos repetidos, retirados activos y divergencias frente a contratos de eventos/HTTP. Las dos definiciones del piloto están revisadas con procedencia experta de PlantVillage y control interno; otras equivalencias permanecen pendientes. `NO_CONCLUYENTE` no entra en la taxonomía.

## Partición, cuarentena y privacidad

Antes de ingresar fotos reales (incremento 4):

1. Verificar permiso, revisión exacta, integridad de bytes/decodificación, etiqueta y cultivo; registrar responsable, fecha y motivo de exclusión o admisión en registro privado de curación.
2. Construir grupos por planta, sesión y sitio, y por fuente cuando falten metadatos más precisos. Usar identificadores opacos globales: recortes, vistas, variantes y copias entre fuentes de un mismo origen pertenecen al mismo componente de relaciones. No asignar un grupo nuevo por fila para aparentar independencia.
3. Comparar hashes entre **todas** las fuentes. Duplicados exactos dentro de una partición se revisan para conservar una muestra o justificar su uso; entre particiones se rechazan. Los grupos relacionados no cruzan TRAIN/VAL/TEST/EXTERNAL. Si no puede demostrarse separación, mantener en cuarentena o excluir; no inventar un grupo independiente.
4. Ejecutar el validador sobre el manifiesto conjunto, nunca solo archivos por fuente aislados. Detecta los seis pares de particiones, tanto por hash como por grupo, informa la causa y sale con código 1 sin mover ni editar filas. Un grupo repetido dentro de la misma partición puede ser válido.
5. La cuarentena no es una quinta partición entrenable: va fuera de `images.v1.csv`, en almacenamiento privado con motivo, procedencia y decisión de revisión. Liberarla requiere permisos/etiquetado/agrupamiento revisados y nueva versión. No se implementa ingestión o traslado automático.
6. Detección de casi duplicados, revisión visual y particiones definitivas pertenecen al incremento 4. El validador no lee fotografías ni verifica que los hashes declarados correspondan a bytes; tampoco detecta grupos omitidos. Congelar y sellar TEST/EXTERNAL antes de ajustar modelos; no usar esos conjuntos para calibrar umbrales.

No guardar imágenes de usuarios ni ubicación precisa en Git; no entrenar automáticamente con imágenes o feedback. Consentimiento explícito para el uso previsto, permisos, revisión y curación posteriores son requisitos distintos; la validación del CSV no los concede.

## Verificación local

Desde la raíz: `bash scripts/check_dataset.sh`. Python 3.12, entorno efímero y dependencias del lock existente `contracts/tooling/requirements.lock`; no modifica herramientas globales. Solo la instalación de dependencias necesita red (o caché); la validación y pruebas son offline, sin GPU, fotos ni pesos.

Con JSON Schema instalado desde ese lock en un entorno aislado: `python scripts/validate_dataset.py --manifest /ruta/privada/manifiesto.csv`. No usar fixtures para entrenamiento. [Evidencia](../../docs/evidence/INCREMENTO-0-GRUPO-5.md).

## Puerta G1 v2 para filas reales

Los CSV [`images.v2.csv`](images.v2.csv) y [`negatives.v2.csv`](negatives.v2.csv) del repositorio contienen solo cabeceras. Una copia privada versionada contiene las filas propuestas; el CSV negativo conserva las nueve columnas propias y **no** incluye `class_code` ni `NO_CONCLUYENTE`. Una fila no vacía requiere `--images-dir` y `--evidence`; sin ellos el validador falla. No descarga imágenes ni decide derechos por ser pública una fuente.

Copiar [`g1-private-record.template.json`](g1-private-record.template.json) a una carpeta privada fuera de Git. En `records` registrar por cada imagen: `image_id`, `sha256`, `source`, `source_revision` exacta de `sources.v2.json`, `relative_path` dentro de la raíz privada, `split_group`, `decision` (`ADMIT`, `EXCLUDE`, `PENDING`), `decision_by`, `decision_at` y `decision_reason`. Solo las decisiones `ADMIT` pueden entrar en un CSV. Cada `ADMIT` añade `rights` con `decision: APPROVED`, `allowed_uses` (`TRAINING` para TRAIN o `EVALUATION` para VAL/TEST/EXTERNAL), `proof_path` relativo al registro privado, `reviewer`, `reviewed_at`, `attribution` y `restrictions`. El comprobante debe existir y contener bytes; una licencia aplicable al lote puede servir de comprobante común cuando cada fila vincula los bytes mediante revisión, ruta original y SHA-256.

Para una imagen positiva añadir `source_label`, `class_code`, `crop_code` y `label_review` con `decision: APPROVED`, esos tres valores, `reviewer`, `reviewed_at` y `evidence_note`. La definición de clase y la equivalencia exacta de `label-mappings.v2.json` también deben figurar como `REVIEWED` y `APPROVED` con evidencia de procedencia experta de la fuente y control interno de calidad/ambigüedad, o con revisión especializada independiente si se dispone de ella. Para un negativo añadir `category_review` con `decision: APPROVED`, `negative_category`, `quality_decision: INCLUDE_AS_NEGATIVE`, `ambiguity_note`, `reviewer`, `reviewed_at` y `evidence_note`; no asignar una clase de enfermedad. Las decisiones excluidas o pendientes conservan motivo y responsable en el registro privado y se omiten de los CSV.

Comando desde la raíz, solo después de reunir evidencia y actualizar inventarios con decisiones reales:

```bash
ml/.venv/bin/python scripts/validate_dataset.py --v2 \
  --manifest /ruta/privada/images.v3.csv \
  --negative-manifest /ruta/privada/negatives.v3.csv \
  --images-dir /ruta/privada/images \
  --evidence /ruta/privada/g1-review.v1.json \
  --report /ruta/privada/g1-validation.v1.json
```

El reporte nuevo contiene hashes de ambos CSV y del registro, conteos de positivos por clase/contexto y negativos por categoría/contexto, con estado `VALIDATED_ROWS_NOT_G1_APPROVAL`. Guardar versiones sucesivas sin sobrescribir decisiones o reportes. La herramienta exige fuente `ELIGIBLE` con licencia `VERIFIED_FOR_PROJECT`, permiso por imagen, revisión exacta, bytes/hash/decodificación y ausencia de fugas entre positivos y negativos. La comprobación automática sola no cierra G1: el lote piloto cerró además con [revisión documental y control interno](../../docs/evidence/INCREMENTO-4-G1-PILOTO-V1.2.md), mínimos, agrupamiento y TEST sellado. No usar TEST para elegir umbrales o modelos.

El entorno `ml/.venv` debe instalarse mediante el lock de [`ml/`](../README.md); la validación de bytes necesita Pillow. El verificador de inventario v1 del incremento 0 usa otro lock y no acredita filas v2.
