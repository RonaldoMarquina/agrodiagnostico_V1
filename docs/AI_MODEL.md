# Datos y modelo de IA

> Estado terminal 2026-11-23: el candidato v1.4.2, operado bajo el protocolo
> v1.4.3, superó su selección interna en VAL pero falló la evaluación EXTERNAL
> independiente. El [cierre v1.4.3](evidence/INCREMENTO-4-CIERRE-V1.4.3.md)
> registra G2 `CLOSED_REJECTED_EXTERNAL` y G3
> `CLOSED_NOT_PROMOTED_G2_REJECTED`. No hay modelo aprobado para usuarios: el
> worker real y la política están inactivos; el perfil `demo` siempre devuelve
> `NO_CONCLUYENTE` sin cargar pesos.
>
> Resultado EXTERNAL: [350/350 casos evaluados una sola vez](evidence/INCREMENTO-4-EXTERNAL-V1.4.3-UNICO.md)
> con el freeze intacto. Solo cumplió recall temprano; fallaron F1 macro,
> recall tardío y rechazo de papa sana/otro cultivo. El lote no se reutiliza.

## Alcance previsto

| Cultivo | Condiciones candidatas |
| --- | --- |
| Papa | Sana; tizón temprano; tizón tardío o rancha |
| Maíz | Sano; roya común; tizón foliar del norte; mancha gris foliar |

El objetivo experimental G0 v1.2.0 son los dos tizones de papa en hoja previamente identificada. Papa sana, maíz, cultivo automático y plagas quedan fuera del piloto. Publica una clase solo después de aplicar los criterios definidos y aprobados por el responsable del proyecto antes del entrenamiento y aportar métricas en un test independiente. Si alguna no cumple, desactívala en interfaz y catálogo y documenta la cobertura real. La etiqueta sana tampoco significa ausencia de todas las enfermedades o plagas.

## Responsabilidades

El modelo devuelve un identificador de clase estable, una puntuación y su versión, junto con datos técnicos de inferencia. Diagnosis aplica reglas de aceptación calibradas, decide `COMPLETADO` o `NO_CONCLUYENTE`, registra `reason_code` y consulta recomendaciones revisadas en el catálogo. Nunca toma una recomendación generada libremente por el modelo.

Tras aceptar y decodificar la carga, para cultivo ajeno, imagen visualmente defectuosa, múltiples plantas ambiguas o evidencia insuficiente, responde `NO_CONCLUYENTE` con ayuda de recaptura sin atribuir una enfermedad concreta. La puntuación visible se llama **confianza estimada**, no probabilidad clínica garantizada. No fijes un umbral arbitrario en producción.

## Inventario del dataset

Antes de entrenar, documenta para cada fuente: nombre/autor, permiso o licencia, fecha de acceso, etiquetas y definición diagnóstica, cantidades por clase, condiciones de captura, revisión de etiquetas, duplicados, exclusiones y restricciones de uso. En v1.4.1, PlantVillage `color` aporta cuatro clases técnicas a TRAIN/VAL; sano y otro cultivo se transforman en abstención visible. Sikkim v1 se conserva solo como evidencia histórica del fallo técnico y no puede reutilizarse. El candidato EXTERNAL v1.4.3 usa PLDD-UP para tres estratos de papa y CornLeafDiseaseCollection para `OTHER_CROP`; ambos declaran CC BY 4.0 y fueron auditados por archivo. Su unidad es imagen única, sin independencia demostrada por planta o sesión. Pota-Toma-To fue descartado por falta de procedencia y derechos por fotografía. PlantDoc y PlantSeg siguen pendientes de admisión.

El manifiesto versionado CSV o Parquet incluirá como mínimo `image_id`, `sha256`, `crop_code`, `class_code`, `source`, `license`, `capture_context`, `label_quality`, `split_group` y `split` (`TRAIN`, `VAL`, `TEST`, `EXTERNAL`). Define y congela los dos `class_code` activos antes de entrenar; nunca recicles un código retirado. Mantén imágenes privadas y ubicación precisa fuera del repositorio.

Desde v1.4.3, todo candidato EXTERNAL debe decodificarse por completo antes
del sello. Se registran contenedor, modo, dimensiones, frames, conversión RGB y
tensor finito por SHA-256, sin cargar el modelo. MPO usa de forma determinista
el frame 0; una animación o archivo multipágina no autorizado bloquea el lote.
El preflight no acredita etiquetas, derechos ni rendimiento: esas compuertas
siguen siendo independientes.

Divide por planta, sesión, sitio o fuente cuando existan imágenes relacionadas; evita que duplicados o vistas de la misma planta crucen particiones. Verifica corruptos, desbalance y coincidencias exactas/visuales. El test sellado no sirve para elegir hiperparámetros ni umbral. No pases fotos de producción a entrenamiento sin consentimiento, etiquetado y revisión posteriores.

## Protocolo experimental

1. Ejecuta una línea base reproducible en CPU: semilla, tamaño, preprocesado, particiones, entorno y métricas.
2. Compara al menos una alternativa viable bajo condiciones equivalentes; candidatos posibles incluyen ResNet, EfficientNet o MobileNet. Decide por resultados y costo de inferencia, no por popularidad.
3. En validación calibra puntuaciones y determina umbral de abstención según costo de errores y curva cobertura/error. Congela esa decisión antes de abrir el test.
4. En test informa accuracy, precision, recall y F1 por clase y macro, matriz de confusión, calibración, proporción de abstención, latencia y memoria. Evalúa ejemplos negativos/fuera de cobertura y conjunto externo separado si existe.
5. Publica un artefacto con `model_id`, versión, checksum de pesos, `dataset_version`, mapa de clases, preprocesado, métricas, fecha y entorno. Ejecuta regresión del artefacto cargado por el worker.

La RX 6700 XT del entorno disponible puede requerir compatibilidad particular para aceleración. El pipeline debe funcionar y medirse primero en CPU; GPU es una optimización condicionada a prueba real.

## Integración segura

En el incremento 3 se usa un adaptador provisional determinista para probar cola, estados, idempotencia e historial. Debe identificarse en logs, UI de prueba y evidencia como **simulación**, sin presentar su respuesta como diagnóstico. El artefacto evaluado en el incremento 4 no fue aprobado para campo y no sustituye al simulador en producción. El modo de demostración es un adaptador distinto, sin modelo, que se abstiene siempre; no altera las reglas de autorización ni los contratos.

Plagas requieren proyecto experimental separado: especies pertinentes, cajas anotadas, métricas AP/mAP/recall y aprobación de cobertura. Gemini puede explicar navegación, pero no producir el diagnóstico oficial ni autorizar acciones. Voz y PWA no alteran la decisión de IA.

## Precisiones de la fuente reconciliada

RF-07 y §8.21 pertenecen al alcance general previo. Para G0 v1.2.0, el usuario identifica previamente la hoja de papa; el piloto evalúa rechazo de entradas fuera de cobertura. RF-20/§8.34 conservan el feedback de utilidad en Diagnosis; «no útil» no equivale a etiqueta incorrecta ni autoriza entrenamiento. Véase [reconciliación](reference/RECONCILIACION-V1.md).

Los archivos corruptos, disfrazados, excesivos o no decodificables se rechazarán durante la validación HTTP antes de crear el diagnóstico/evento. Ese rechazo no es un resultado NO_CONCLUYENTE del modelo.

## Inventario inicial implementado — Incremento 0, grupo 5

El [inventario versionado](../ml/manifests/README.md) registra referencias primarias, revisiones, licencias declaradas, restricciones, conteos remotos y locales desconocidos. Distingue PlantSeg v5/v7 y sus permisos; no autoriza intercambiar versiones. Solo los dos tizones de papa son candidatos del piloto; los otros códigos son historial fuera de alcance. El responsable propuso denominar `MAIZE_LEAF_BLIGHT` «tizón foliar del norte»; las etiquetas específicas «Northern Leaf Blight» permanecen provisionales y las genéricas de roya/tizón no se mapean automáticamente. Ayacucho externo no está disponible.

`bash scripts/check_dataset.sh` valida estructura, elegibilidad, correspondencia con contratos y separación por hash/grupo entre cada par de TRAIN/VAL/TEST/EXTERNAL, con positivos y negativos sintéticos. No modifica filas ni descarga imágenes. El lote real admitido está en manifiestos privados G1; los fixtures separados no acreditan datos ni métricas agronómicas.

La [política de cuarentena y agrupamiento](../ml/manifests/README.md#partición-cuarentena-y-privacidad) exige relacionar planta/sesión/sitio/fuente y copias entre fuentes antes de particionar. Sin separación fiable, excluir o mantener fuera del manifiesto admitido. El control automático no verifica bytes, etiquetas, consentimiento ni casi duplicados visuales; esa curación y el test sellado pertenecen al incremento 4. No hay entrenamiento ni reutilización automática de imágenes de usuarios. [Evidencia](evidence/INCREMENTO-0-GRUPO-5.md).

## Estado histórico y cierre del incremento 4

G0 de diseño v1.2.0 aprobado por el responsable el 2026-11-19 ([protocolo histórico](../ml/evaluation/protocol-g0.v1.2.0.json)); G1/G2 de ese piloto cerrados y [bundle de dos tizones](evidence/INCREMENTO-4-APROBACION-G2-PILOTO.md) histórico. El [G0 v1.3.0](../ml/evaluation/protocol-g0.v1.3.0.json) fue aprobado el 2026-11-20 y luego sustituido para este ciclo por v1.3.2; [G1 v1.3.1](evidence/INCREMENTO-4-G1-V1.3.1-ADMISION.md) quedó cerrado, pero G2/G3 siguen abiertos por el [fallo TEST](evidence/INCREMENTO-4-TEST-V1.3.2-UNICO.md). El [recorrido técnico PyTorch CPU](evidence/INCREMENTO-4-CPU-SMOKE.md) usa fixtures geométricos y conserva una alternativa jerárquica histórica limitada a `VAL_FIXTURE`. El [lote privado G1 v1.2.0](evidence/INCREMENTO-4-G1-PILOTO-V1.2.md) tiene derechos y procedencia experta de PlantVillage con control interno de calidad; no hubo nueva revisión agronómica independiente. El experimento real TRAIN/VAL v1.2.0 usó clasificadores directos; el v1.3.2 usó MobileNetV3-Small con rechazo técnico de papa sana. El [runtime histórico del worker](evidence/INCREMENTO-4-WORKER-CPU-PREPARADO.md) se probó en aceptación aislada; v1.3.2 no se ha integrado.

El [paquete ML](../ml/README.md) permite entrenar y evaluar en CPU con manifiestos locales explícitos. Los comandos históricos de candidato con fixtures no constituyen resultados agronómicos. En el piloto, [dos clasificadores no jerárquicos se entrenaron y compararon con TRAIN/VAL admitidos](evidence/INCREMENTO-4-ENTRENAMIENTO-VAL-PILOTO.md); MobileNetV3 fue seleccionado y congelado con calibración/umbral de VAL. [TEST se evaluó una sola vez](evidence/INCREMENTO-4-TEST-PILOTO-V1.2.md) y ambos tizones cumplieron los límites numéricos. [G2 aprobó el bundle](evidence/INCREMENTO-4-APROBACION-G2-PILOTO.md) para este alcance; esto no prueba generalización a campo ni activa el worker real.

El [preflight G3](evidence/INCREMENTO-4-POLITICA-Y-PREFLIGHT-G3.md) verificó hashes del bundle, acta y dataset G1 sin volver a evaluar TEST. La [prueba integrada posterior](evidence/INCREMENTO-4-G3-ACEPTACION-LOCAL.md) publicó orientación revisada y activó la política únicamente en un proyecto Compose efímero, ya eliminado. El rechazo de papa sana falló y `G3=NOT_APPROVED`. Los ciclos posteriores terminaron en la evaluación EXTERNAL v1.4.3: el [acta terminal](evidence/INCREMENTO-4-CIERRE-V1.4.3.md) rechaza el modelo para campo, bloquea `ml-real`, deja la política sin importar y conserva el catálogo como histórico no publicable. La [guía operativa](operations/ai-model-operations.md) describe el modo demo y conserva los comandos anteriores solo como referencia histórica.
