# ADR-0009 — Modelo validado, inferencia real y políticas de publicación

Fecha: 2026-10-10. Estado: adoptado para `incremento-4-datos-y-modelo-validado`.
Tarea: 1.1 de `incremento-4-datos-y-modelo-validado`.

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

1. **Separación de roles**: El agente de desarrollo implementa herramientas automatizadas, pruebas, validadores y reportes reproducibles; el responsable del proyecto y los asesores agronómicos/docentes aportan las decisiones de permisos legales de fuentes, revisión de etiquetas botánicas y aprobación de criterios de aceptación. Ningún valor o firma humana se genera ficticiamente.
2. **Definición de compuertas (Gates)**:
   - **G0 (Protocolo y Criterios)**: Documento formal fechado y aprobado antes de entrenar modelos de selección: definición inequívoca de las 7 clases candidatas (incluyendo resolución de `MAIZE_LEAF_BLIGHT` y royas), conteos mínimos por partición y clase, métricas objetivo por clase y macro, límites de error admisible, abstención, comportamiento en negativos y presupuesto de recursos CPU (latencia y memoria).
   - **G1 (Datos y Particiones Curadas)**: Fuentes formalmente admitidas con licencias verificadas, dataset curado localmente, duplicados y similares agrupados globalmente, particiones selladas (TRAIN, VAL, TEST, EXTERNAL) con hashes inmutables y manifiesto de negativos independiente.
   - **G2 (Evaluación Independiente y Artefacto)**: Evaluación estricta en TEST/EXTERNAL sin reutilización para sintonía; reporte completo de métricas por clase y cultivo; bundle empaquetado e inmutable con checksums de pesos y manifiestos revisado por el proyecto. Cobertura mínima obligatoria para ambos cultivos (papa y maíz).
   - **G3 (Aceptación Real Integrada)**: Validación E2E en entorno multi-contenedor con worker real (`ml-real`), catálogo agrícola revisado, políticas activadas y verificación de resiliencia.
3. **Bloqueo ante puertas no superadas**: La falta de cumplimiento de una compuerta impide promover el modelo o cerrar el incremento. La infraestructura puede verificarse con fixtures tensoriales explícitos, pero un fixture jamás acredita la superación de una compuerta ni la validez de un modelo agronómico.

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
   - Define: `policy_id`, `version`, tupla admitida (`model_version`, `dataset_version`), digest SHA-256 del bundle, lista de clases autorizadas, parámetros de calibración escalar por clase, umbrales mínimos de publicación, referencia de aprobación docente y metadatos de auditoría.
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
   - Se establece un script de aceptación real (`scripts/check_ml_acceptance.py`) que opera exclusivamente sobre datos y modelos autorizados, verificando el flujo E2E real, latencias en CPU, consumo de memoria y concordancia de diagnósticos con el catálogo agrícola.
3. **Conservación de todas las etapas previas**:
   - Se preservan íntegramente las etapas `lint`, `contracts`, `identity-integration`, `diagnosis-integration` y `async-integration`, garantizando cero regresiones en la infraestructura local y de integración continua.

---

## Matriz de Requisitos RF-07, RF-08 y RF-09

| Requisito Original | Definición V1 Reconciliada | Capacidad OpenSpec Afectada | Criterio de Aceptación / Verificación | Evidencia Reproducible |
| :--- | :--- | :--- | :--- | :--- |
| **RF-07** | El sistema intentará identificar automáticamente el cultivo presente en la fotografía sin exigir selección manual previa. Cultivo ajeno produce abstención. | `validated-model-inference` / `reproducible-model-training-and-evaluation` | Comparación experimental en VAL de clasificación directa vs jerárquica. Imágenes no reconocidas como papa o maíz generan `NO_CONCLUYENTE` con `reason_code=UNSUPPORTED_CROP`. Cero campos de cultivo en API de carga multipart. | Reporte experimental en VAL; pruebas unitarias e integración en `tests/dataset/` y `services/ai_inference/tests/test_worker_inference.py`. |
| **RF-08** | Para cultivos soportados se analizará la imagen mediante un modelo versionado para identificar una de las 7 condiciones visuales previstas, sujeta a validación por clase. | `dataset-inventory` / `reproducible-model-training-and-evaluation` / `model-publication-policy` | Protocolo G0 con métricas independientes por clase. Clases sin datos suficientes o que no alcancen el umbral quedan no soportadas (`UNSUPPORTED_CLASS`). El cierre de incremento exige cobertura verificada en ambos cultivos. | Protocolo G0 aprobado; manifiesto curado G1; informe de evaluación independiente G2; matriz de confusión en TEST; `Problem.model_supported` sincronizado por política. |
| **RF-09** | El sistema mostrará el diagnóstico probable acompañado del nivel de confianza generado por el modelo (confianza estimada), sin presentarlo como certeza clínica. | `model-publication-policy` / `validated-model-inference` | Calibración escalar en VAL a partir de `raw_score`. Diagnóstico visible expone `estimated_confidence` y snapshot de política. Textos en interfaz y contratos declaran el resultado como orientación diagnóstica probable. | Contrato OpenAPI actualizado; fixtures de respuesta; validación de esquema en `tests/contracts/test_contracts.py`; snapshot inmutable en `DiagnosisFinished`. |

---

## Coherencia con ADR-0008 e Invariantes del Sistema

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
