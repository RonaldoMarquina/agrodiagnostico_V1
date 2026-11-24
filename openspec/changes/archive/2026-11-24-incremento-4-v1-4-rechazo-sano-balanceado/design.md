# Design: ciclo v1.4.0 con rechazo sano balanceado y EXTERNAL Sikkim

## Context

v1.3.2 se congeló antes de TEST y fue evaluado una sola vez. Publicó un tizón en 8/32 controles sanos y produjo `NO_CONCLUYENTE` en 24/32, frente a límites predefinidos de 3/32 y 29/32. Por ello no está aprobado para publicación. Los commits `94b3d42` y `5f2d623`, el bundle, el TEST, el reporte y el umbral 0,90 son evidencia histórica inmutable y ese TEST no volverá a ejecutarse.

v1.4.0 corrige el desequilibrio entre las 80 fotos sanas de TRAIN y las más de mil fotos sumadas de los dos tizones, sin optimizar retrospectivamente con TEST. PlantVillage permanece en TRAIN/VAL con separación por `leaf_id`; la generalización se medirá después del congelamiento en un EXTERNAL de campo independiente por archivo, no por planta.

### Auditoría de Sikkim v1 al 22 de noviembre de 2026

Se auditó el depósito primario **Sikkim Solanaceae Leaf Image Dataset**, versión 1, DOI `10.17632/4wz7zbk635.1`, publicado bajo CC BY 4.0. El depósito describe fotografías RGB adquiridas en campo en Sikkim y advierte que no ofrece particiones independientes verificadas por planta ni diagnósticos confirmados en laboratorio.

| Evidencia | Resultado verificado |
| --- | --- |
| Archivo publicado | `Sikkim Solanaceae Leaf Image Dataset.zip`, 170.561.971 bytes |
| SHA-256 del ZIP | `5288c8f9d4628049ae1f827c961dc3df97167de294cec020cbce0bc19b2574dc`, coincide con el metadato del depósito |
| Papa | 168 imágenes: 42 `Early Blight`, 76 `Late Blight`, 50 `Healthy`; 168/168 nombres presentes en `Annotations.xlsx` |
| Otro cultivo | 194 imágenes de tomate y pimiento en once carpetas etiquetadas; se usarán solo como `OTHER_CROP` |
| Integridad | 362/362 imágenes decodificables y 362 SHA-256 únicos |
| Duplicados exactos | 0 internos y 0 frente a las 6.059 imágenes locales inventariadas |
| Similitud visual cruzada | dHash con umbral 6 señaló 20 imágenes frente a las 6.059 PlantVillage locales; la revisión visual descartó que fueran el mismo archivo o escena |
| Similitud interna | 37 pares Sikkim quedaron registrados como potencialmente correlacionados o derivados; se conservan como archivos SHA únicos, sin afirmar independencia por planta |
| Unidad de independencia | Imagen única identificada por ruta y SHA-256; no existe identificador de planta, sesión o parcela |

La licencia del depósito se conservará como comprobante común del lote y cada fila la vinculará con DOI, versión, ruta y SHA-256. No se encontró contenido marcado como perteneciente a terceros dentro del archivo, pero se conservará la atribución a Kishor Chettri y el enlace a CC BY 4.0. Una fotografía de una búsqueda web nunca será admisible sin licencia aplicable, autor, enlace de origen y hash registrados.

### Topología de datos v1.4.0

- **TRAIN/VAL:** únicamente PlantVillage `color`, revisión fijada, con los manifiestos y `leaf_id` verificables. Las tres clases técnicas son `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT` y `POTATO_HEALTHY`; `OTHER_CROP` se conserva en VAL para medir rechazo, no como enfermedad publicable.
- **EXTERNAL:** únicamente Sikkim v1. Sus 362 imágenes originales se sellarán juntas y no podrán usarse en entrenamiento, VAL, calibración, selección de arquitectura, selección de estrategia de balance ni selección de umbral.
- **TEST histórico:** el TEST v1.3.2 permanece cerrado como evidencia. v1.4.0 no crea ni reutiliza otro TEST interno; su compuerta post-congelamiento es EXTERNAL Sikkim.

## Goals / Non-Goals

### Goals

- Mantener v1.3.2 como resultado histórico no aprobado y evitar cualquier optimización retrospectiva.
- Equilibrar efectivamente las tres clases técnicas durante TRAIN sin inventar grupos nuevos.
- Limitar los aumentos sanos a TRAIN y conservar su genealogía de `leaf_id`.
- Elegir arquitectura, balance, calibración y umbral solo con PlantVillage TRAIN/VAL.
- Medir una sola vez generalización y rechazo en Sikkim EXTERNAL después de congelar el bundle.
- Reportar resultados por imagen y declarar expresamente que no demuestran independencia o generalización por planta.

### Non-Goals

- Recolectar fotografías propias o usar fotografías encontradas en búsquedas web sin expediente completo.
- Mezclar Sikkim con TRAIN/VAL o usarlo para corregir una decisión del modelo.
- Afirmar independencia por planta, parcela o sesión en Sikkim.
- Modificar el bundle, TEST, umbral o reporte v1.3.2.
- Añadir diagnósticos publicables distintos de los dos tizones.

## Decisions

### 1. Frontera histórica estricta

v1.3.2 queda cerrado como ciclo evaluado y no aprobado. Sus artefactos se validarán por hash, nunca se reescribirán ni se volverá a ejecutar su TEST. Su fallo justifica un nuevo ciclo, pero sus predicciones no participan en la selección v1.4.0.

### 2. G0 v1.4.0 aprobado antes de entrenar

El responsable del proyecto aprobó el 22 de noviembre de 2026 la separación PlantVillage TRAIN/VAL y Sikkim EXTERNAL, junto con los límites externos siguientes:

| Criterio EXTERNAL | Límite aprobado | Denominador fijo |
| --- | ---: | ---: |
| F1 macro de los dos tizones | ≥ 0,75 | 42 temprano + 76 tardío |
| Recall de tizón temprano | ≥ 0,75 y mínimo 32 aciertos | 42 |
| Recall de tizón tardío | ≥ 0,75 y mínimo 57 aciertos | 76 |
| Papa sana publicada como tizón | máximo 5 | 50 |
| Papa sana en `NO_CONCLUYENTE` | mínimo 45 | 50 |
| Otro cultivo publicado como tizón | máximo 9 | 194 |

Una abstención en una imagen de tizón cuenta como falso negativo para el recall de su clase. El F1 macro externo se calcula sobre los dos diagnósticos publicables; una confusión entre tizones cuenta simultáneamente como falso negativo de la clase real y falso positivo de la publicada. Los reportes incluirán numeradores, denominadores y cualquier fallo de decodificación o inferencia sin retirar casos del denominador de forma silenciosa.

### 3. Derechos y trazabilidad por archivo

El archivo completo Sikkim v1 se fija por DOI, versión y SHA-256. Cada imagen tendrá ruta original, SHA-256, etiqueta fuente, decisión, licencia CC BY 4.0, atribución y referencia al comprobante común. Cualquier diferencia entre el hash publicado del ZIP y el descargado bloquea la admisión. La política de fuentes prohíbe imágenes web sin los cuatro elementos mínimos: licencia, autor, URL original y hash.

### 4. Independencia limitada a imagen única

Cada fila EXTERNAL usará una identidad estable derivada de su SHA-256. Esto evita contar dos veces el mismo archivo, pero no equivale a un `leaf_id` ni demuestra plantas independientes. Como todas las imágenes Sikkim están en una única partición EXTERNAL, no se crearán particiones internas que aparenten separación por planta.

### 5. Balance consciente de grupos en PlantVillage

TRAIN tendrá las tres clases técnicas. La implementación comparará, bajo los mismos manifiestos y presupuesto, ponderación de pérdida y muestreo balanceado por clase consciente de `leaf_id`, siempre que ambas estrategias sean viables. No se muestrearán como independientes varias vistas de la misma hoja. Se registrarán pesos, probabilidades de muestreo, exposición efectiva, semilla y conteos originales.

### 6. Aumentos sanos solamente en TRAIN

Las transformaciones de papa sana serán deterministas respecto de semilla/configuración y se aplicarán únicamente en TRAIN. Cada derivación permanecerá vinculada al original y a su `leaf_id`; nunca incrementará las cifras de originales o grupos. VAL y EXTERNAL usarán bytes originales y preprocesado de inferencia, sin aumentos estocásticos.

### 7. Selección y congelamiento exclusivamente con VAL

Arquitectura, balance, calibración, umbral y política de rechazo se seleccionarán solo con PlantVillage TRAIN/VAL. Antes de abrir EXTERNAL se congelarán pesos, mapa, preprocesado, calibración, umbral, manifiestos, dependencias y comandos con hashes. El proceso de selección no tendrá una ruta de lectura hacia EXTERNAL.

### 8. Apertura única de EXTERNAL y promoción

Sikkim EXTERNAL se sellará antes del entrenamiento y se abrirá una sola vez después del congelamiento. Un incumplimiento de cualquiera de los seis límites de G0 registrará v1.4.0 como no aprobado y no permitirá ajustes con esas imágenes. El cumplimiento habilitará revisión G2, pero no activará automáticamente el worker; integración y G3 siguen siendo compuertas separadas.

## Risks / Trade-offs

- **No hay identificadores de planta en Sikkim** → se publicarán resultados por imagen y esta limitación; no se calcularán ni prometerán intervalos por planta.
- **Varias imágenes podrían corresponder a una misma planta desconocida** → no se subdividirá Sikkim ni se lo usará para selección; el resultado se tratará como evidencia externa correlacionada potencialmente.
- **Cambio de dominio PlantVillage → Sikkim** → es intencional para medir generalización, pero un fallo no se corregirá con EXTERNAL; requerirá otro ciclo y otro conjunto final independiente.
- **Desbalance persistente por pocos grupos sanos en TRAIN** → se compararán ponderación y muestreo por `leaf_id`, con aumentos sanos solo en TRAIN y decisión basada en VAL.
- **Falsos positivos de dHash por forma de hoja** → SHA-256 decide duplicado exacto; toda coincidencia perceptual requiere revisión visual documentada antes de excluir.
- **Licencia de depósito frente a contenido de terceros** → se admite únicamente la revisión fijada y se bloquea cualquier archivo marcado como tercero o sin relación demostrable con el lote CC BY 4.0.

## Migration Plan

1. Verificar por hash el expediente v1.3.2 y mantenerlo en solo lectura.
2. Materializar el expediente Sikkim por archivo, reproducir conteos, hashes y revisión de duplicados, y registrar atribución CC BY 4.0.
3. Versionar el protocolo G0 v1.4.0 aprobado y validar que bloquea entrenamiento mientras EXTERNAL no esté admitido y sellado.
4. Reutilizar por referencia inmutable PlantVillage TRAIN/VAL, verificar `leaf_id` y cerrar G1 sin mezclar Sikkim.
5. Sellar Sikkim EXTERNAL y restringirlo a la evaluación posterior al congelamiento.
6. Entrenar y comparar balance, arquitectura, calibración y umbral solo con TRAIN/VAL.
7. Congelar el candidato y ejecutar EXTERNAL una sola vez.
8. Registrar G2; integrar y activar únicamente tras las compuertas posteriores.

Rollback antes de activación consiste en no promover el bundle v1.4.0 y conservar la política actual. Los ciclos históricos y el resultado EXTERNAL no se eliminan ni se sustituyen.
