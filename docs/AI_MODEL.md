# Datos y modelo de IA

## Alcance previsto

| Cultivo | Condiciones candidatas |
| --- | --- |
| Papa | Sana; tizón temprano; tizón tardío o rancha |
| Maíz | Sano; roya común; tizón foliar; mancha gris foliar |

Las siete clases son el objetivo experimental, no una promesa de cobertura ya demostrada. Publica una clase solo después de acordar criterios con el docente y aportar métricas en un test independiente. Si alguna no cumple, desactívala en interfaz y catálogo y documenta la cobertura real. La etiqueta sana tampoco significa ausencia de todas las enfermedades o plagas.

## Responsabilidades

El modelo devuelve un identificador de clase estable, una puntuación y su versión, junto con datos técnicos de inferencia. Diagnosis aplica reglas de aceptación calibradas, decide `COMPLETADO` o `NO_CONCLUYENTE`, registra `reason_code` y consulta recomendaciones revisadas en el catálogo. Nunca toma una recomendación generada libremente por el modelo.

Tras aceptar y decodificar la carga, para cultivo ajeno, imagen visualmente defectuosa, múltiples plantas ambiguas o evidencia insuficiente, responde `NO_CONCLUYENTE` con ayuda de recaptura sin atribuir una enfermedad concreta. La puntuación visible se llama **confianza estimada**, no probabilidad clínica garantizada. No fijes un umbral arbitrario en producción.

## Inventario del dataset

Antes de entrenar, documenta para cada fuente: nombre/autor, permiso o licencia, fecha de acceso, etiquetas y definición diagnóstica, cantidades por clase, condiciones de captura, revisión de etiquetas, duplicados, exclusiones y restricciones de uso. PlantVillage, PlantDoc y PlantSeg tienen un inventario inicial de fuentes y etiquetas; siguen pendientes de admisión y la compatibilidad de permisos y etiquetas se decide antes de usar imágenes. Un conjunto de campo de Ayacucho con permisos adecuados se reserva para evaluación externa si se obtiene; su ausencia debe declararse.

El manifiesto versionado CSV o Parquet incluirá como mínimo `image_id`, `sha256`, `crop_code`, `class_code`, `source`, `license`, `capture_context`, `label_quality`, `split_group` y `split` (`TRAIN`, `VAL`, `TEST`, `EXTERNAL`). Define y congela los siete `class_code` antes de entrenar; nunca recicles un código retirado. Mantén imágenes privadas y ubicación precisa fuera del repositorio.

Divide por planta, sesión, sitio o fuente cuando existan imágenes relacionadas; evita que duplicados o vistas de la misma planta crucen particiones. Verifica corruptos, desbalance y coincidencias exactas/visuales. El test sellado no sirve para elegir hiperparámetros ni umbral. No pases fotos de producción a entrenamiento sin consentimiento, etiquetado y revisión posteriores.

## Protocolo experimental

1. Ejecuta una línea base reproducible en CPU: semilla, tamaño, preprocesado, particiones, entorno y métricas.
2. Compara al menos una alternativa viable bajo condiciones equivalentes; candidatos posibles incluyen ResNet, EfficientNet o MobileNet. Decide por resultados y costo de inferencia, no por popularidad.
3. En validación calibra puntuaciones y determina umbral de abstención según costo de errores y curva cobertura/error. Congela esa decisión antes de abrir el test.
4. En test informa accuracy, precision, recall y F1 por clase y macro, matriz de confusión, calibración, proporción de abstención, latencia y memoria. Evalúa ejemplos negativos/fuera de cobertura y conjunto externo separado si existe.
5. Publica un artefacto con `model_id`, versión, checksum de pesos, `dataset_version`, mapa de clases, preprocesado, métricas, fecha y entorno. Ejecuta regresión del artefacto cargado por el worker.

La RX 6700 XT del entorno disponible puede requerir compatibilidad particular para aceleración. El pipeline debe funcionar y medirse primero en CPU; GPU es una optimización condicionada a prueba real.

## Integración segura

En el incremento 3 se usa un adaptador provisional determinista para probar cola, estados, idempotencia e historial. Debe identificarse en logs, UI de prueba y evidencia como **simulación**, sin presentar su respuesta como diagnóstico. En el incremento 4 se sustituye por el artefacto evaluado sin alterar las reglas de autorización ni contratos sin cambio versionado.

Plagas requieren proyecto experimental separado: especies pertinentes, cajas anotadas, métricas AP/mAP/recall y aprobación de cobertura. Gemini puede explicar navegación, pero no producir el diagnóstico oficial ni autorizar acciones. Voz y PWA no alteran la decisión de IA.

## Precisiones de la fuente reconciliada

RF-07 y §8.21 exigen intentar identificar el cultivo sin selección manual obligatoria. Se compararán clasificación de cultivo y clases combinadas; no se inventará un cultivo para imágenes fuera de cobertura. RF-20/§8.34 conservan el feedback de utilidad en Diagnosis; «no útil» no equivale a etiqueta incorrecta ni autoriza entrenamiento. Véase [reconciliación](reference/RECONCILIACION-V1.md).

Los archivos corruptos, disfrazados, excesivos o no decodificables se rechazarán durante la validación HTTP antes de crear el diagnóstico/evento. Ese rechazo no es un resultado NO_CONCLUYENTE del modelo.

## Inventario inicial implementado — Incremento 0, grupo 5

El [inventario versionado](../ml/manifests/README.md) registra referencias primarias, revisiones, licencias declaradas, restricciones, conteos remotos y locales desconocidos. Distingue PlantSeg v5/v7 y sus permisos; no autoriza intercambiar versiones. Las siete clases siguen candidatas y la equivalencia «tizón foliar»/«Northern Leaf Blight» permanece provisional. Ayacucho externo no está disponible.

`bash scripts/check_dataset.sh` valida estructura, elegibilidad, correspondencia con contratos y separación por hash/grupo entre cada par de TRAIN/VAL/TEST/EXTERNAL, con positivos y negativos sintéticos. No modifica filas ni descarga imágenes. Manifiesto real inicialmente sin filas; fixtures separados no acreditan datos ni métricas.

La [política de cuarentena y agrupamiento](../ml/manifests/README.md#partición-cuarentena-y-privacidad) exige relacionar planta/sesión/sitio/fuente y copias entre fuentes antes de particionar. Sin separación fiable, excluir o mantener fuera del manifiesto admitido. El control automático no verifica bytes, etiquetas, consentimiento ni casi duplicados visuales; esa curación y el test sellado pertenecen al incremento 4. No hay entrenamiento ni reutilización automática de imágenes de usuarios. [Evidencia](evidence/INCREMENTO-0-GRUPO-5.md).
