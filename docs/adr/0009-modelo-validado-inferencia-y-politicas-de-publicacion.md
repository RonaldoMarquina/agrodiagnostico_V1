# ADR-0009 — Modelo validado, inferencia real y políticas de publicación

Fecha: 2026-10-10. Estado: adoptado para `incremento-4-datos-y-modelo-validado`.
Tarea: 1.1 de `incremento-4-datos-y-modelo-validado`.

> Vigente desde la enmienda G0 v1.2.0 del 2026-11-19: piloto de hoja de papa identificada previamente, solo tizón temprano y tardío. Las secciones originales de siete clases, maíz y cultivo automático son historial sustituido por la enmienda final. [G1 del lote piloto](../evidence/INCREMENTO-4-G1-PILOTO-V1.2.md) cerró con procedencia experta PlantVillage y control interno. [Dos clasificadores directos se compararon en VAL](../evidence/INCREMENTO-4-ENTRENAMIENTO-VAL-PILOTO.md) y uno se congeló antes de TEST; [G2 aprobó el bundle restringido](../evidence/INCREMENTO-4-APROBACION-G2-PILOTO.md). G3 sigue pendiente.

## Contexto

El Incremento 3 consolidó el flujo asíncrono desacoplado y confiable entre los servicios `Diagnosis` y `AI Inference` mediante RabbitMQ, leases con tokens Ed25519 internos, persistencia transaccional en PostgreSQL, deduplicación en inbox y cuarentena (ADR-0008). Sin embargo, la inferencia en dicho incremento operó exclusivamente bajo un simulador determinista (`ENABLE_SIMULATED_INFERENCE=true`), sin datos reales ni modelo agronómico validado.

El Incremento 4 aborda la transición hacia un soporte diagnóstico real y verificable: selección y curación de fuentes de datos autorizadas, particiones independientes selladas, entrenamiento reproducible en CPU, comparación de arquitecturas (incluyendo identificación automática de cultivo según RF-07), calibración escalar compatible con el contrato `DiagnosisAnalyzed.v1`, artefactos de modelo inmutables (`model-bundle.v1`), políticas de publicación versionadas en Diagnosis (`publication-policy.v1`) y evolución aditiva del detalle de diagnóstico para trazabilidad y confianza estimada (RF-09).

Trazabilidad normativa: ADR-0002 (interfaces y eventos V1), ADR-0004 (identidades y claves asimétricas), ADR-0006 y ADR-0007 (persistencia, idempotencia y catálogo), ADR-0008 (flujo asíncrono y leases), y las cinco especificaciones OpenSpec del Incremento 4:
- `specs/dataset-inventory/spec.md` (DATA-04, DATA-05)
- `specs/reproducible-model-training-and-evaluation/spec.md`
- `specs/validated-model-inference/spec.md`
- `specs/model-publication-policy/spec.md`
- `specs/continuous-integration-foundation/spec.md`

## Decisiones

### D1. Puertas de evidencia (G0–G3) y delimitación de responsabilidades

1. **Separación de roles**: El agente de desarrollo implementa herramientas automatizadas, pruebas, validadores y reportes reproducibles; el responsable del proyecto define y aprueba G0. La revisión de derechos y etiquetas de imágenes seleccionadas se documenta en G1. Ningún valor o firma humana se genera ficticiamente.
2. **Definición de compuertas (Gates)**:
   - **G0 (Protocolo y Criterios)**: Documento de diseño fechado, versionado y aprobado por el responsable antes de entrenar con datos reales: definición de las 7 clases candidatas (incluyendo denominación de `MAIZE_LEAF_BLIGHT` y exclusión de royas genéricas), política de admisión, conteos mínimos por partición y clase, métricas objetivo por clase y macro, límites de cobertura, error selectivo, abstención, comportamiento en negativos y presupuesto CPU. G0 no acredita imágenes ni resultados.
   - **G1 (Datos y Particiones Curadas)**: Fuentes formalmente admitidas con licencias verificadas, dataset curado localmente, duplicados y similares agrupados globalmente, particiones selladas (TRAIN, VAL, TEST, EXTERNAL) con hashes inmutables y manifiesto de negativos independiente.
   - **G2 (Evaluación Independiente y Artefacto)**: Evaluación estricta en TEST/EXTERNAL sin reutilización para sintonía; reporte completo de métricas por clase y cultivo; bundle empaquetado e inmutable con checksums de pesos y manifiestos revisado por el proyecto. Cobertura mínima obligatoria para ambos cultivos (papa y maíz).
   - **G3 (Aceptación Real Integrada)**: Validación E2E en entorno multi-contenedor con worker real (`ml-real`), catálogo agrícola revisado, políticas activadas y verificación de resiliencia.
3. **Bloqueo ante puertas no superadas**: La falta de cumplimiento de una compuerta impide promover el modelo o cerrar el incremento. La infraestructura puede verificarse con fixtures tensoriales explícitos, pero un fixture jamás acredita la superación de una compuerta ni la validez de un modelo agronómico.

Enmienda aprobada por el responsable (2026-11-19, protocolo G0 v1.1.0): se elimina la condición de aprobación formal docente que figuraba en la planificación anterior. Justificación: el responsable del proyecto asume explícitamente la autoridad sobre los criterios de diseño antes del entrenamiento; la revisión especializada de imágenes y etiquetas sigue siendo una evidencia distinta de G1. Se fijan cobertura ≥ 0,70 (diagnósticos aceptados / imágenes válidas de siete clases), error selectivo ≤ 0,10 (aceptados incorrectos / aceptados; cero aceptados no cumple) y aceptación errónea de negativos ≤ 0,10 (negativos con clase soportada aceptada / negativos evaluados). Se conservan FPR ≤ 0,05 y rechazo ≥ 0,95 previamente aprobados para esos mismos negativos, por ser más estrictos; cero negativos no acredita el criterio. Las abstenciones permanecen en el denominador de cobertura y recall por clase como falsos negativos. Umbral seleccionado en VAL y congelado antes de TEST. Se publicarán numeradores, denominadores y resultados por clase. `MAIZE_LEAF_BLIGHT` se denomina «tizón foliar del norte» y las etiquetas genéricas `Corn rust leaf`, `corn rust` y `Corn leaf blight` quedan sin mapeo automático. **G0 cerrado como diseño**; derechos y revisión de imágenes seleccionadas siguen pendientes en G1 y resultados medidos en G2. No existe una aprobación especializada de las equivalencias agronómicas ni se declara tal revisión.

### D2. Curación de datos, inventario versionado y particiones selladas

1. **Preservación del inventario histórico**: Los artefactos `v1` de `ml/manifests/` (`sources.v1.json`, `taxonomy.v1.json`, `label-mappings.v1.json`, `images.v1.csv`) permanecen inalterados como evidencia histórica. Se produce una versión `v2` coherente que refleja admisiones reales y curación de bytes.
2. **Admisión estricta**: Ninguna imagen se descarga ni incorpora al dataset de entrenamiento sin verificación de titularidad, licencia compatible con el uso previsto y atribución documentada.
3. **Almacenamiento privado de imágenes**: Los bytes de las fotografías y sus rutas precisas permanecen fuera del repositorio Git en almacenamiento privado. Los reportes y manifiestos emplean identificadores opacos (`image_id`) y digests criptográficos (`sha256`), sin exponer URLs públicas ni coordenadas geográficas sensibles.
4. **Agrupamiento global de componentes relacionados**: Imágenes provenientes de la misma planta, sesión, entorno o duplicados entre fuentes distintas se agrupan bajo un único `split_group`. Ningún grupo puede cruzarse entre TRAIN, VAL, TEST y EXTERNAL. Las transformaciones de aumento (*augmentations*) se aplican única y exclusivamente a la partición TRAIN tras la partición.
5. **Sellado inmutable de evaluación**: Los conjuntos TEST y EXTERNAL se congelan con checksums SHA-256 inmutables y registro de auditoría de acceso. Cualquier alteración invalida la evaluación y exige un nuevo ciclo.
6. **Manifiesto de negativos independiente**: Casos fuera de cobertura (otros cultivos, suelo, hojas sintéticas, objetos) se registran en un manifiesto separado (`negatives.v2.csv`) bajo las mismas reglas de privacidad y particionado, sin contaminar la taxonomía oficial de 7 clases candidatas.

### D3. Experimentos reproducibles, identificación de cultivo y ejecución CPU

1. **Entorno reproducible en CPU**: El pipeline de ML se construye y ejecuta en CPU con dependencias bloqueadas en `ml/pyproject.toml` / `uv.lock`. La reproducibilidad se garantiza fijando semillas deterministas, registrando versiones de software, commit Git, hardware y tiempos de ejecución.
2. **Identificación automática de cultivo (RF-07)**:
   - Se evalúan y comparan en la partición VAL dos enfoques arquitecturales bajo igualdad de datos y presupuesto:
     - Enfoque A: Clasificación directa multi-clase conjunta de (cultivo, patología).
     - Enfoque B: Detección jerárquica en dos etapas (primero identificación de cultivo; segundo clasificación patológica condicional).
   - La selección se realiza en VAL según los criterios acordados en G0. Imágenes con cultivo ajeno o desconocido deben producir abstención técnica (`NO_CONCLUYENTE`, `reason_code=UNSUPPORTED_CROP`), sin forzar la asignación a una de las clases de papa o maíz.
3. **Procedencia de pesos preentrenados**: De emplearse arquitecturas estándar (e.g. ResNet, MobileNet, EfficientNet), los pesos iniciales deben contar con licencia permisiva compatible, procedencia verificada y checksum SHA-256 verificado antes de iniciar el ajuste.

### D4. Calibración compatible con contratos y preservación de `raw_score`

1. **Invarianza de `DiagnosisAnalyzed.v1`**: El evento `DiagnosisAnalyzed.v1` mantiene intacta su semántica y esquema JSON:
   - `crop`: código de cultivo (`POTATO`, `MAIZE` o `null`)
   - `technical_class`: código de clase técnica candidata o `null`
   - `raw_score`: puntuación numérica generada por el modelo (float entre 0.0 y 1.0)
   - `model_version`: versión del modelo de inferencia
   - `dataset_version`: versión del dataset utilizado
2. **Calibración escalar por clase**: En la partición VAL se ajusta una función de calibración escalar determinista (e.g., mapeo isotónico o escalado Platt) por cada clase aprobada, mapeando `raw_score` a una **confianza estimada** calibrada.
3. **Frontera de decisión**:
   - `AI Inference` efectúa el cómputo técnico, validando umbrales técnicos de calidad visual y cultivo, emitiendo `PREDICTION`, `ABSTENTION` (con `reason_code` como `LOW_CONFIDENCE`, `UNSUPPORTED_CROP`, `BAD_IMAGE`) o `FAILURE` (`INFERENCE_ERROR`).
   - `Diagnosis` evalúa la tupla (`model_version`, `dataset_version`) contra la política de publicación activa, aplica la calibración escalar, verifica el umbral de aceptación de la política y el estado del catálogo agrícola para determinar el resultado visible final (`COMPLETADO` vs `NO_CONCLUYENTE`).

### D5. Artefacto inmutable y worker real desacoplado

1. **Contrato `model-bundle.v1.schema.json`**:
   - Define la estructura del artefacto de entrega de ML: `bundle_id`, `model_id`, `model_version`, `dataset_version`, arquitectura de red, mapa de clases contractuales, preprocesamiento exigido (dimensiones, normalización, canales), parámetros de rechazo y calibración, checksums SHA-256 de los pesos y manifiestos de entrenamiento, y referencia al acta de revisión G2.
2. **Carga segura y defensiva**:
   - El worker carga los tensores empleando mecanismos seguros (e.g. `weights_only=True` de PyTorch o `safetensors`), prohibiendo estrictamente la importación dinámica o ejecución de código Python arbitrario empaquetado en el bundle.
   - Valida rutas, tamaños de tensores, ausencia de valores no finitos (`NaN`, `Inf`) y consistencia con el esquema antes de iniciar el consumo de eventos.
3. **Aislamiento de perfiles Compose**:
   - Perfil `async-test`: Mantiene el simulador sintético para pruebas rápidas de transporte, concurrencia y matrices de fallo de colas del Incremento 3.
   - Perfil `ml-real`: Monta en modo de solo lectura el bundle autorizado, desactiva absolutamente cualquier fallback a simulación y exige validación de integridad al arranque. Si el artefacto falta o está corrupto, el worker rehúsa iniciar el consumo de AMQP sin afectar la disponibilidad de la API de Diagnosis.
4. **Respeto a leases y recursos**:
   - La inferencia se ejecuta con límites estrictos de tiempo y memoria en CPU, ejecutando heartbeats independientes para evitar la pérdida del lease en Diagnosis.

### D6. Política propia de Diagnosis y soporte efectivo del catálogo

1. **Contrato `publication-policy.v1.schema.json`**:
   - Define: `policy_id`, `version`, tupla admitida (`model_version`, `dataset_version`), digest SHA-256 del bundle, lista de clases autorizadas, parámetros de calibración escalar por clase, umbrales mínimos de publicación, referencia de aprobación del responsable del proyecto y metadatos de auditoría.
2. **Administración operativa inmutable**:
   - Las políticas se gestionan mediante comandos CLI administrativos protegidos con modo `dry-run` por defecto. La activación o retiro de una política genera un registro de auditoría transaccional inmutable (`diagnosis_audit_logs`) y actualiza el campo `Problem.model_supported` del catálogo agrícola en la misma transacción de PostgreSQL.
   - No se expone ningún endpoint HTTP público ni privilegios PATCH que permitan alterar el soporte del modelo sin trazabilidad.
3. **Evolución aditiva de contratos HTTP**:
   - El esquema del recurso `/api/v1/diagnoses/{id}` evoluciona de manera aditiva y retrocompatible:
     - Nuevos campos opcionales: `estimated_confidence` (float calibrado) y `policy_snapshot` (`policy_id`, `policy_version`, `policy_digest`).
     - Se preserva el campo técnico `raw_score` inalterado.
     - Diagnósticos históricos previos al Incremento 4 mantienen `estimated_confidence: null` y `policy_snapshot: null` sin recálculos anacrónicos.
4. **Snapshot en evento de finalización**:
   - Al alcanzar un estado terminal (`COMPLETADO`, `NO_CONCLUYENTE`, `FALLIDO`), el evento `DiagnosisFinished.v1` y la fila en PostgreSQL guardan un snapshot inmutable de la política activa, garantizando que futuras actualizaciones del catálogo o retiro de políticas no alteren la auditoría histórica.

### D7. Pruebas técnicas y aceptación real independiente

1. **Integración en CI (`ml-contracts-and-runtime`)**:
   - Se incorpora una etapa obligatoria en `tooling/ci/plan.json` que valida contratos JSON Schema (`model-bundle.v1`, `publication-policy.v1`), migraciones de base de datos de Diagnosis, y carga de un fixture tensorial mínimo en CPU sin requerir GPUs ni descargar datasets privados de gran tamaño.
2. **Comando de aceptación real desacoplado**:
   - Se establece un script de aceptación real (`scripts/check_ml_real_acceptance.py`) que deberá operar sobre datos y modelos autorizados, verificando el flujo E2E real, latencias en CPU, consumo de memoria y concordancia de diagnósticos con el catálogo agrícola. Su implementación actual no acredita G3.
3. **Conservación de todas las etapas previas**:
   - Se preservan íntegramente las etapas `lint`, `contracts`, `identity-integration`, `diagnosis-integration` y `async-integration`, garantizando cero regresiones en la infraestructura local y de integración continua.

---

## Matriz de Requisitos RF-07, RF-08 y RF-09

| Requisito Original | Definición V1 Reconciliada | Capacidad OpenSpec Afectada | Criterio de Aceptación / Verificación | Evidencia Reproducible |
| :--- | :--- | :--- | :--- | :--- |
| **RF-07** | El sistema intentará identificar automáticamente el cultivo presente en la fotografía sin exigir selección manual previa. Cultivo ajeno produce abstención. | `validated-model-inference` / `reproducible-model-training-and-evaluation` | Comparación experimental en VAL de clasificación directa vs jerárquica. Imágenes no reconocidas como papa o maíz generan `NO_CONCLUYENTE` con `reason_code=UNSUPPORTED_CROP`. Cero campos de cultivo en API de carga multipart. | Reporte experimental en VAL pendiente; pruebas técnicas en `tests/dataset/` no acreditan reconocimiento agronómico. |
| **RF-08** | Para cultivos soportados se analizará la imagen mediante un modelo versionado para identificar una de las 7 condiciones visuales previstas, sujeta a validación por clase. | `dataset-inventory` / `reproducible-model-training-and-evaluation` / `model-publication-policy` | Protocolo G0 con métricas independientes por clase. Clases sin datos suficientes o que no alcancen el umbral quedan no soportadas (`UNSUPPORTED_CLASS`). El cierre de incremento exige cobertura verificada en ambos cultivos. | Protocolo G0 aprobado; manifiesto curado G1; informe de evaluación independiente G2; matriz de confusión en TEST; `Problem.model_supported` sincronizado por política. |
| **RF-09** | El sistema mostrará el diagnóstico probable acompañado del nivel de confianza generado por el modelo (confianza estimada), sin presentarlo como certeza clínica. | `model-publication-policy` / `validated-model-inference` | Calibración escalar en VAL a partir de `raw_score`. Diagnóstico visible expone `estimated_confidence` y snapshot de política. Textos en interfaz y contratos declaran el resultado como orientación diagnóstica probable. | Contrato OpenAPI actualizado; fixtures de respuesta; validación de esquema en `tests/contracts/test_contracts.py`; snapshot inmutable en `DiagnosisFinished`. |

---

## Coherencia con ADR-0008 e Invariantes del Sistema

Revisión documental 2026-11-19: D1–D7 y la matriz RF-07/08/09 se contrastaron con [ADR-0008](0008-flujo-asincrono-confiable-y-leases-internos.md) y el cambio activo. ADR-0009 añade artefactos y políticas propios de cada servicio; no cambia la propiedad de datos, los estados terminales ni la autorización de usuarios o de rutas internas. G0 de diseño se aprobó por la enmienda anterior; las pruebas de modelo real permanecen pendientes. Se corrigieron referencias a archivos de aceptación y pruebas inexistentes, sin convertir expectativas de la matriz en evidencia alcanzada.

1. **Propiedad de Datos**:
   - `Diagnosis` sigue siendo dueño exclusivo de la base de datos `diagnosis`, añadiendo las tablas `publication_policies` y columnas de trazabilidad mediante migraciones Alembic aditivas.
   - `AI Inference` mantiene su base de datos `ai_inference` para trabajos y auditoría técnica de inferencia.
   - Se mantiene la prohibición absoluta de lectura/escritura directa entre bases de datos de servicios distintos.
2. **Máquina de Estados Inmutable**:
   - Se preserva el flujo unidireccional:
     $$\text{PENDIENTE} \longrightarrow \text{PROCESANDO} \longrightarrow \{\text{COMPLETADO} \mid \text{NO\_CONCLUYENTE} \mid \text{FALLIDO}\}$$
     $$\text{PENDIENTE} \longrightarrow \text{CANCELADO}$$
   - Las transiciones terminales continúan siendo estrictamente irreversibles.
   - `NO_CONCLUYENTE` se mantiene como un estado de abstención del ciclo de vida y no como una clase de la taxonomía del modelo.
3. **Seguridad y Autorización**:
   - Todas las llamadas entre el worker AI y Diagnosis continúan requiriendo tokens JWT firmados con Ed25519 e identificador de instancia validado.
   - El proxy Nginx continúa bloqueando de manera estricta cualquier intento de acceso externo a rutas `/internal/*`.
   - Se mantiene la regla de que solicitudes de un usuario sobre diagnósticos pertenecientes a otros devuelven HTTP 404 genérico.

---

## Consecuencias y Mitigación de Riesgos

- **Riesgo**: Homogeneidad de fondos en datasets de laboratorio (e.g. PlantVillage) genera sesgo y pobre generalización.
  - *Mitigación*: Agrupamiento estricto por procedencia, evaluación obligatoria contra imágenes de campo y manifiesto de negativos; no declarar generalización a campo abierto si no existe conjunto EXTERNAL verificado.
- **Riesgo**: Modelo en CPU excede el presupuesto de tiempo y provoca expiración del lease en Diagnosis.
  - *Mitigación*: Heartbeat concurrente desacoplado en el worker; optimización de cuantización o arquitecturas ligeras (MobileNetV3); límites de tiempo de inferencia acordados en G0.
- **Riesgo**: Reemplazo de política en caliente con diagnósticos en curso.
  - *Mitigación*: Transacción atómica de finalización que evalúa la política activa al momento del commit del resultado y serialización en PostgreSQL para evitar estados inconsistentes.

## Enmienda G0 v1.2.0 — 2026-11-19

El responsable del proyecto aprobó antes de entrenar o abrir TEST un piloto de hoja de papa previamente identificada, con `POTATO_EARLY_BLIGHT` y `POTATO_LATE_BLIGHT` como clases candidatas. La [auditoría reproducible de fuentes](../evidence/INCREMENTO-4-FUENTES-PARA-COMPLETAR-G1.md) muestra que faltan grupos verificables de hoja, planta o sesión para completar las siete clases previas. Papa sana, maíz, cultivo automático y plagas quedan fuera del piloto.

Se mantienen mínimos por clase y partición, revisión de etiquetas, negativos, abstención, cobertura ≥ 0,70, error selectivo ≤ 0,10, FPR en negativos ≤ 0,05, calibración, presupuesto CPU y evaluación. F1 macro y cobertura se calcularán sobre los dos tizones. Los negativos G1 se seleccionaron de hojas de tomate PlantVillage con `leaf_id`; papa sana no se usa como negativo. La exactitud de identificación automática de cultivo anterior no aplica al piloto, pues el usuario identifica previamente papa. G1 se cerró después para [el lote documentado](../evidence/INCREMENTO-4-G1-PILOTO-V1.2.md), con procedencia experta de etiquetas y control interno de calidad; no hubo nueva evaluación agronómica independiente. G2 conserva los resultados medidos pendientes. [Protocolo aprobado](../../ml/evaluation/protocol-g0.v1.2.0.json).

## Decisión experimental del piloto — 2026-11-19

Por el alcance de dos tizones y la entrada `identified_crop=POTATO`, la arquitectura jerárquica de cultivo no corresponde al experimento real. Se compararon MobileNetV3-Small y ResNet18 como clasificadores directos con objetivo técnico `OTHER_CROP` para rechazo, bajo el mismo preprocesado y presupuesto CPU; ninguno produce una clase publicada adicional. La [evidencia VAL](../evidence/INCREMENTO-4-ENTRENAMIENTO-VAL-PILOTO.md) seleccionó MobileNetV3 y congeló pesos, configuración y umbral calibrado antes de TEST. Esta decisión se tomó con VAL y conserva TEST sellado. No sustituye la evaluación independiente ni aprueba G2; el contrato de bundle y worker real siguen pendientes.

## Enmienda de aprobación G2 — 2026-11-19

El responsable del proyecto aprobó G2 tras la carga independiente del [bundle privado restringido](../evidence/INCREMENTO-4-APROBACION-G2-PILOTO.md), SHA-256 `93e2e65130a9c266be4bdba0262d1c98e30d0604f4d21466effba2d9c9ff0b41`, vinculado al TEST único que cumple G0 v1.2.0. El mapa publicable contiene solo `POTATO_EARLY_BLIGHT` y `POTATO_LATE_BLIGHT` para hoja de papa previamente identificada. `OTHER_CROP` es rechazo técnico, no clase publicada; por ello el contrato del piloto exige `identified_crop=POTATO` sin `crop_detection_threshold` automático. EXTERNAL no existe, el rechazo de papa sana no está medido y la latencia de flujo completo sigue pendiente. El bundle aprobado no activa por sí mismo worker, política, catálogo ni G3.

## Decisión de preparar G0 v1.3.0 — 2026-11-20

La [aceptación integrada local](../evidence/INCREMENTO-4-G3-ACEPTACION-LOCAL.md) publicó erróneamente como tizón tardío cuatro de cuatro fotos originales de papa sana usadas como control de alcance. G3 v1.2.0 **no se aprobó**. El responsable eligió una nueva versión con rechazo verificable de papa sana. La [propuesta técnica](../evidence/INCREMENTO-4-CICLO-RECHAZO-PAPA-SANA.md) conserva las dos enfermedades publicables y plantea papa sana como negativo separado, sin diagnóstico «sana». Los mínimos por estrato y el protocolo completo v1.3.0 aún requieren definición y aprobación del responsable antes de entrenar. G1 debe admitir imágenes y grupos concretos y aportar un TEST independiente nuevo; el TEST v1.2.0 ya abierto no podrá acreditarlo. G2 v1.2.0 se conserva como historia inmutable, sin promover su política fuera del entorno efímero de aceptación.

## Reducción G0 v1.3.1 — 2026-11-21; aprobada y G1 cerrado

El [inventario G1](../evidence/INCREMENTO-4-G1-V1.3-INVENTARIO-2026-11-21.md) constató 140 fotos/35 grupos sanos no expuestos en PlantVillage, frente a 220/85 exigidos por G0 v1.3.0 para TRAIN/VAL/TEST. El responsable [aprobó expresamente](../evidence/INCREMENTO-4-G0-V1.3.1-APROBACION.md) reducir **solo** papa sana a 80/20 TRAIN, 28/7 VAL y 32/8 TEST; los otros tres estratos, métricas y presupuesto CPU permanecen iguales. La reducción disminuye la diversidad independiente para medir rechazo sano y consume todo el lote disponible. Tras revisar procedencia experta, calidad interna, derechos, etiquetas y grupos, [G1 v1.3.1 se cerró](../evidence/INCREMENTO-4-G1-V1.3.1-ADMISION.md) con TEST nuevo sellado. La admisión no acredita eficacia ni autorización de política; G2 y G3 permanecen abiertos. G0 v1.3.0 y toda evidencia v1.2.0 permanecen intactos.

## Criterio G0 v1.3.2 — 2026-11-21; aprobado antes del entrenamiento

El responsable [aprobó G0 v1.3.2](../evidence/INCREMENTO-4-G0-V1.3.2-APROBACION.md) sobre el lote G1 ya sellado: papa sana conserva TRAIN 80/20, VAL 28/7, TEST 32/8 y total 140/35. Su TEST exige máximo tres diagnósticos visibles de tizón y mínimo 29 estados finales `NO_CONCLUYENTE` sobre las mismas 32 fotos selladas. Para `OTHER_CROP` permanecen FPR ≤0,05 y rechazo ≥0,95; los dos tizones, el límite general de aceptación errónea, calibración y CPU mantienen sus criterios. Un estado `FALLIDO` no satisface el mínimo sano de `NO_CONCLUYENTE`. La [verificación G1](../../scripts/verify_g0_v1_3_2.py) acredita que mínimos, hashes, derechos y sello no cambiaron; G1 permanece cerrado. Ocho hojas sanas independientes con vistas relacionadas limitan la generalización, y EXTERNAL sigue ausente. Esta decisión no mide rendimiento ni autoriza G2/G3.

## Selección TRAIN/VAL v1.3.2 — 2026-11-22; G2 pendiente

Con [G0/G1 cerrados](../evidence/INCREMENTO-4-TRAIN-VAL-V1.3.2.md), se entrenó MobileNetV3-Small con tres salidas técnicas (`POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT`, `POTATO_HEALTHY`) y *outlier exposure* de `OTHER_CROP` TRAIN sin cuarta salida. Dos rutas de abstención se compararon bajo los mismos pesos, VAL, preprocesado y CPU; `ARGMAX_CONFIDENCE` y `HEALTHY_GATE` empataron en VAL. Se congeló la regla más simple con temperatura 1,25 y umbral 0,90. El argmax sano nunca se publica; las falsas aceptaciones de fotos sanas se cuentan separadamente. El paquete privado con SHA-256 de `freeze.json` `d07dcc40376d4d74e581553c817e4610f7bf7716cae0d6af98a3919930141eb7` tiene estado `LOCKED_BEFORE_TEST_NOT_G2`, pasó carga independiente y rechazó un mapa alterado. No se abrió TEST ni se integró el worker; la política y el bundle de servicio v1.3.2 siguen pendientes antes de G2/G3. La comparación con v1.2 se limitó al mismo VAL y no modifica el bundle histórico.
