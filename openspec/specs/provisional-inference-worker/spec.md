# provisional-inference-worker Specification

## Purpose

Verificar el recorrido técnico completo con un worker durable y fixtures aislados, sin presentar simulación como inferencia real ni introducir contenido agronómico no revisado.

## Requirements

### Requirement: Simulación aislada y explícita
El worker provisional SHALL ejecutarse solo en entorno test aislado con fixtures habilitados explícitamente. SHALL rechazar iniciar como simulador fuera de ese entorno; no SHALL existir selección pública de escenarios ni activación en Compose normal.

#### Scenario: Arranque ordinario
- **WHEN** se inicia Compose normal
- **THEN** no procesa imágenes con un modelo simulado

#### Scenario: Simulación fuera de tests
- **WHEN** se habilita simulador fuera de APP_ENV=test o sin habilitación de fixtures
- **THEN** el proceso rechaza iniciar

#### Scenario: Escenario público
- **WHEN** un cliente añade un campo o cabecera para forzar una predicción
- **THEN** no habilita ni altera un escenario del simulador

### Requirement: Trabajo técnico durable y datos propios
AI SHALL obtener imagen solo por la API interna con identidad/lease, y confirmar resultado técnico, deduplicación y outbox Analyzed en su propia base antes de ACK Requested. SHALL impedir ejecución simultánea del mismo trabajo y no leer tablas de Diagnosis o S3 directamente.

#### Scenario: Crash del worker
- **WHEN** el proceso cae tras claim o durante análisis
- **THEN** la señal y datos durables permiten recuperación acotada por lease

#### Scenario: Commit técnico incierto
- **WHEN** AI confirma resultado pero pierde la conexión antes de ACK
- **THEN** la reentrega conserva una sola salida lógica para diagnosis/lease

#### Scenario: Fallo temporal
- **WHEN** un intento encuentra un fallo temporal
- **THEN** se programa recuperación sin ACK de trabajo incompleto ni bucle adicional que exceda tres generaciones

### Requirement: Resultados técnicos sin certeza inventada
Fixtures SHALL cubrir ABSTENTION, FAILURE y PREDICTION sintético. Sin ejecución de modelo SHALL usar metadatos null, no ceros/versiones ficticias reales. Diagnosis SHALL decidir el estado visible y requerir soporte, política y catálogo para COMPLETADO; no SHALL activar soporte del modelo en semillas ordinarias.

#### Scenario: Abstención
- **WHEN** un fixture produce ABSTENTION con motivo admitido y metadatos null
- **THEN** Diagnosis publica NO_CONCLUYENTE y Finished

#### Scenario: Fallo definitivo
- **WHEN** un fixture produce FAILURE autorizado con lease vigente
- **THEN** Diagnosis publica FALLIDO y Finished

#### Scenario: Predicción sin soporte
- **WHEN** llega predicción para clase no soportada
- **THEN** Diagnosis no publica COMPLETADO y conserva NO_CONCLUYENTE/UNSUPPORTED_CLASS

#### Scenario: Predicción con catálogo ausente
- **WHEN** el fixture tiene soporte/política pero no recomendación aprobada activa
- **THEN** se publica NO_CONCLUYENTE/CATALOG_UNAVAILABLE

#### Scenario: Camino completado sintético
- **WHEN** un fixture aislado satisface soporte/política y catálogo sintético
- **THEN** se prueba COMPLETADO con snapshot inmutable y Finished, sin atribuir validez agronómica al resultado

#### Scenario: Política de fixture ausente o versión desconocida
- **WHEN** una predicción tiene catálogo activo pero carece de política de prueba explícita para su versión
- **THEN** Diagnosis publica NO_CONCLUYENTE/UNSUPPORTED_CLASS sin recomendación visible

#### Scenario: Score bajo la condición del fixture
- **WHEN** una predicción de versión sintética permitida no alcanza el umbral de prueba
- **THEN** Diagnosis publica NO_CONCLUYENTE/LOW_CONFIDENCE, sin atribuir calibración de producción al umbral
