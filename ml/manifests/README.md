# Inventario inicial v1

Consulta de fuentes: 2026-09-29. Tres fuentes **PENDING**, siete clases **CANDIDATE**, veintiún mapeos explícitos. No hay imágenes admitidas ni modelo evaluado. Los conteos locales por clase son `null` (no medidos); `images.v1.csv` contiene únicamente la cabecera, cuya ausencia de filas sí se comprueba. No confundir ese cero de filas con un conteo de fotografías en el equipo.

| Archivo | Uso |
| --- | --- |
| [sources.v1.json](sources.v1.json) | Autores, revisión, permisos, restricciones, cantidades, captura y pendientes por fuente |
| [taxonomy.v1.json](taxonomy.v1.json) | Siete códigos reservados, cultivo, definición pendiente y estado candidato |
| [label-mappings.v1.json](label-mappings.v1.json) | Correspondencias provisionales y etiquetas aún no mapeadas |
| [manifest-row.schema.json](manifest-row.schema.json) | JSON Schema 2020-12 aplicado a cada fila CSV |
| [images.v1.csv](images.v1.csv) | Manifiesto real inicial vacío; no contiene fixtures |
| [research-evidence.v1.json](research-evidence.v1.json) | Revisiones y consultas de metadatos que sustentan los conteos |

## Fuentes, versiones y permisos

- **PlantVillage:** repositorio de los autores y [distribución enlazada por ellos](https://huggingface.co/datasets/mohanty/PlantVillage), cuya tarjeta declara CC BY-SA 3.0. Se registra esa declaración, pendiente de revisar su alcance sobre la distribución elegida, atribución y derivados. El README publica 54.306 imágenes globales; no se suman variantes de color/gris/segmentación como fotografías independientes. [Referencia primaria](https://github.com/spMohanty/PlantVillage-Dataset).
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

Los códigos v1 quedan reservados: no cambiar cultivo/significado ni reciclar códigos retirados. Conservar mapas publicados y sus versiones; un cambio semántico requiere nuevo código, decisión revisada y actualización de contratos antes de consumidores. El validador detecta códigos repetidos, retirados activos y divergencias frente a contratos de eventos/HTTP. Las siete definiciones siguen pendientes de revisión; `NO_CONCLUYENTE` no entra en la taxonomía.

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
