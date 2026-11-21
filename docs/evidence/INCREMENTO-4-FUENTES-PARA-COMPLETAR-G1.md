> Nota posterior: el responsable aprobó G0 v1.2.0 el 2026-11-19 como piloto de dos tizones de papa. Este expediente conserva el análisis que justificó reducir el alcance. [Decisión](../adr/0009-modelo-validado-inferencia-y-politicas-de-publicacion.md).

# ¿Qué fuentes pueden completar las clases pendientes de G1?

Evaluación documental del 19 de noviembre de 2026. Se mantiene G0 v1.1.0 aprobado y G1 abierto. Se consultaron fichas de autores, índices de archivos y anotaciones de texto. El aporte al déficit se calcula sobre fotos con clase compatible y grupo verificable que podrían separarse por partición. La admisión de imágenes, el entrenamiento y el acceso a TEST quedan fuera de esta evaluación.

Cada clase de maíz necesita **220 fotos y 85 grupos** (TRAIN 150/50, VAL 40/20, TEST reservado 30/15). Papa sana necesita **100 fotos y 55 grupos adicionales** (70/30, 16/14, 14/11), suponiendo que se conserven las 120 fotos y 30 hojas candidatas de PlantVillage. En total faltan como mínimo **980 fotos y 395 grupos sumados por clase**. EXTERNAL de Ayacucho se evalúa aparte. [Auditoría del lote actual](INCREMENTO-4-AUDITORIA-HOJAS-MAIZ.md) · [Protocolo vigente](../../ml/evaluation/protocol-g0.v1.json).

| Fuente, versión y licencia declarada | Clases aprovechables para el déficit | Grupos demostrables con los metadatos consultados | Cantidad faltante que podría cubrir | Bloqueo |
| --- | --- | --- | --- | --- |
| Rabbany et al., Bangladesh, Mendeley v1, CC BY 4.0 | Maíz sano, roya común y mancha gris. El tizón del norte aparece en la descripción, sin carpeta o anotación específica | 0 con vínculo verificable de archivo a hoja, planta o sesión | Techo de 119/220 sanas, 135/220 de roya, 90/220 de mancha gris y 0/220 de tizón del norte, tras apartar duplicados por hash y el conflicto de clase. Ninguna cuota de grupos acreditada | Nombres secuenciales, subtipo de tizón sin resolver y un mismo contenido en dos clases. [Depósito v1](https://data.mendeley.com/datasets/sb4wwjs8bz/1) |
| Craze, colección In-field, Sudáfrica, Kaggle v4, CC BY-NC-SA 4.0 | Mancha gris, tizón del norte, roya común. La correspondencia de `NoFoliarSymptoms` con sano requiere revisión | Un bloque identificable de lugar y fecha para 308 rutas de Cedara. El README permite situar otra captura en Baynesfield. Independencia de las demás tomas por demostrar | Por cantidad de fotos con una sola etiqueta, hasta **220/220** de mancha gris, **140/220** de tizón del norte, **107/220** de roya y, si se confirma la equivalencia, **220/220** sanas. Los bloques identificados no acreditan 85 grupos por clase | Falta la correspondencia completa con la captura. Hay coocurrencias. Debe comprobarse la compatibilidad del uso previsto con las condiciones no comerciales y de compartir igual. [Distribución v4](https://www.kaggle.com/datasets/hamishcrazeai/maize-in-field-dataset/versions/4) · [Artículo de los autores](https://doi.org/10.3390/plants11151942) |
| Laizer et al., Tanzania, Zenodo versión 01, CC BY 4.0 | Papa sana. El depósito también distingue tizón temprano y tardío de papa | 0 grupos de sanas vinculados a los archivos en el índice publicado. Se documentan capturas mediante Open Data Kit (ODK) y una tabla de correspondencias | Hay volumen para **100/100** fotos sanas adicionales. Queda por identificar un mínimo de **55 grupos** distribuibles | El ZIP de sanas usa un número por foto. Hace falta recuperar el cruce de captura y comprobar si admite agrupación por planta o sesión. [Depósito](https://zenodo.org/records/8286529) · [Licencia registrada](https://api.datacite.org/dois/10.5281/zenodo.8286529) · [Método y tabla 1](https://doi.org/10.1016/j.dib.2025.111549) |
| Banu y Deb, Bangladesh, BARI, Mendeley v1, CC BY 4.0 | Papa sana (`Healthy`) | 0 grupos trazables. El índice distingue originales y aumentos mediante el prefijo del nombre | **16/100** sanas marcadas como originales en el ZIP, incluso antes de deduplicar. Insuficiente para aportar 55 grupos | Número por archivo sin clave de captura. El volumen de imágenes aumentadas sobrestima la oferta real. [Depósito v1](https://data.mendeley.com/datasets/d5b3fzpw3g/1) |

Los techos por fuente son alternativas de selección. Sumarlos antes de comprobar los cruces entre fuentes y las relaciones entre vistas inflaría el aporte. **Ninguna combinación examinada acredita hoy las cinco cuotas de fotos y grupos.**

## Verificación del DOI de maíz solicitado

En `10.17632/sb4wwjs8bz.1` se enumeraron las siete subcarpetas de `RAW_Image`. Por carpeta se contaron los archivos y los valores distintos de `content_details.sha256_hash` publicados por Mendeley. Son hashes declarados por el repositorio. No se recalcularon sobre fotos. [Árbol de carpetas v1](https://data.mendeley.com/public-api/datasets/sb4wwjs8bz/folders/1) · [Ejemplo de índice RAW para mancha gris](https://data.mendeley.com/public-api/datasets/sb4wwjs8bz/files?folder_id=2ae7835c-7e82-4fa3-aa2f-99aca8dae125&version=1).

| Carpeta RAW exacta | Archivos | Hashes distintos dentro de la clase | Decisión de inventario |
| --- | ---: | ---: | --- |
| `Healthy_Leaf` | 120 | 119 | Candidata a maíz sano. Incluye seis HEIC |
| `Common_Rust` | 135 | 135 | Candidata a roya común. El CSV de anotación solo tiene cabecera |
| `Gray_Leaf_Spot` | 100 | 91 | 90 contenidos candidatos tras apartar el hash compartido |
| `Corn_Leaf_Blight` | 220 | 216 | Genérica. Las 200 filas del CSV anotan `CornLeafBlight`; ninguna distingue norte o sur |
| `Bacterial_Leaf_Streak` | 100 | 95 | Fuera de la cobertura positiva. Incluye el conflicto con mancha gris |
| `Eyespot` | 115 | 109 | Fuera de la cobertura positiva |
| `Maize_Streak_Disease` | 210 | 206 | Fuera de la cobertura positiva |

Los 1.000 archivos RAW corresponden a 970 hashes globales. `Gray_Leaf_Spot/IMG_411.jpeg` y `Bacterial_Leaf_Streak/IMG_115.jpeg` tienen el mismo SHA-256, `1b6f8ca82b6883511234440b725eabd21d9cc55a5f924aa2461764bfeb4b85c0`. Se apartan ambas etiquetas de ese contenido. Las carpetas de conversiones, aumentos y anotaciones se excluyeron del conteo de originales. El texto de `corn.pptx` describe la numeración de las imágenes. Los siete CSV de anotación contienen nombre de imagen, etiqueta, dimensiones y coordenadas de caja. Ninguno identifica hoja, planta o sesión. Para reconsiderar el lote haría falta un cruce original con la captura y, para acreditar tizón del norte, un subtipo respaldado por archivo.

## Comprobaciones de las otras colecciones

**Maíz de Sudáfrica.** La versión 4 publica 2.355 rutas distintas en `Kaggle Dataset/Database.csv` (SHA-256 `9379d3df7fe528c2ab4e302ab76bb49cb94948405042b94224c97f90796aeb5d`). El README identifica las fotos como originales de alta resolución. Para cada columna se contaron filas con indicador 1 y, por separado, filas donde ese era el único indicador activo. El artículo usa un subconjunto de 2.332 imágenes y describe aumentos por rotación/reflejo y versiones segmentadas. Esas variantes quedan fuera del cálculo. [CSV v4](https://www.kaggle.com/api/v1/datasets/download/hamishcrazeai/maize-in-field-dataset?datasetVersionNumber=4&filename=Kaggle%20Dataset%2FDatabase.csv) · [README v4](https://www.kaggle.com/api/v1/datasets/download/hamishcrazeai/maize-in-field-dataset?datasetVersionNumber=4&filename=Kaggle%20Dataset%2FReadMe.txt).

| Etiqueta del CSV | Fotos que la incluyen | Fotos con esa única etiqueta |
| --- | ---: | ---: |
| GLS | 1.084 | 630 |
| NCLB | 554 | 140 |
| CR | 300 | 107 |
| NoFoliarSymptoms | 285 | 232 |
| PLS | 493 | 149 |
| SR | 39 | 7 |
| Other | 324 | 49 |
| UnidentifiedDisease | 332 | 150 |

El prefijo `2019-03-13--Cedara-(DKB)-` permite mantener juntas 308 rutas. Entre ellas hay 61 GLS, 22 NCLB, 24 CR y 49 sin síntomas foliares con etiqueta única. Es un bloque conservador de captura. El ejemplo del README vincula el archivo de ID 1220 a Baynesfield el 24 de marzo de 2009. El CSV le asigna simultáneamente GLS y NCLB, por lo que se excluye de los techos de etiqueta única. Un identificador de imagen, una hora distinta o el sufijo de una cámara tampoco demuestran hojas distintas. El artículo atribuye la anotación de origen a fitopatólogos. Esta evaluación del proyecto solo cotejó metadatos.

**Papa de Tanzania.** La tabla 1 de los autores registra 20.947 sanas, 17.808 de tizón temprano y 21.016 de tizón tardío antes de la limpieza. Publicaron 20.438, 17.772 y 20.499 respectivamente. El directorio central de `healthy.zip` contiene 20.438 JPG de datos y 20.438 entradas JPG auxiliares de macOS (`._*`). No contiene tabla de captura. La publicación describe una correspondencia entre nombre original, nombre nuevo y GPS. El siguiente paso para conservar las siete clases es obtener ese cruce con identificadores de sesión o planta y comprobar que las vistas repetidas quedan juntas. Basta un extracto seudonimizado que permita auditarlo. El GPS exacto de las fincas resulta innecesario para esta decisión. [Archivos del depósito](https://zenodo.org/api/records/8286529/files) · [Publicación de los autores](https://doi.org/10.1016/j.dib.2025.111549).

**Papa de BARI.** Los autores declaran 804 capturas originales entre seis clases y 2.400 imágenes tras aumento. El directorio central del único ZIP de v1 contiene 2.351 entradas. El desglose por nombres `orig_*` / `aug_*` es Healthy **16/376**, Fungal Late Blight **20/372**, Bacterial Soft Rot **7/390**, Viral Leaf Roll **33/361**, Viral PVX **6/381** y Viral PVY **2/387**. Son 84 archivos marcados como originales. La distribución consultada no permite repartir los 804 originales declarados entre clases. El índice se puede verificar leyendo el directorio central del ZIP con ID `3696ddd4-6e96-4682-b778-5187d088f624`, sin extraer fotos. [Índice de archivos v1](https://data.mendeley.com/public-api/datasets/d5b3fzpw3g/files?folder_id=root&version=1).

## Recomendación para el responsable

Para conservar las siete clases, priorizar el cruce ODK de Tanzania para papa sana y los registros de captura de Pretoria y Bangladesh para maíz. Habría que asignar los grupos completos a una sola partición, resolver las etiquetas ambiguas y verificar los permisos de los lotes. Ninguna foto de estos depósitos cuenta como admitida.

Con la evidencia disponible, se recomendó **proponer v1.2.0 como piloto limitado a diferenciar tizón temprano y tardío en papa previamente identificada**. Las dos clases ya superan los mínimos de cantidad en el inventario candidato. Conservar los mínimos por clase, las reglas de abstención y el presupuesto de CPU. Documentar antes del entrenamiento los nuevos denominadores de F1 macro y cobertura sobre dos clases, la validación de negativos (incluidos maíz y papa sana) y el cambio al requisito de una enfermedad por cultivo. Se perderían la salida «papa sana», todo diagnóstico de maíz, la validación del cultivo automático entre papa y maíz y la comparabilidad directa con la evaluación de siete clases. Requiere decisión expresa del responsable antes de entrenar o abrir TEST. La revisión de etiquetas, negativos y particiones reales seguiría pendiente incluso bajo el piloto.
