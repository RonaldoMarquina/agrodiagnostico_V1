## Purpose

Procesar imágenes con artefactos reales aprobados identificando cultivo y resultados técnicos, conservando seguridad, recuperación e idempotencia del flujo asíncrono existente.

## ADDED Requirements

### Requirement: Carga verificada y sin fallback sintético
El worker real SHALL verificar integridad, procedencia autorizada, compatibilidad, límites y mapa de un release inmutable antes de consumir trabajo. SHALL NOT descargar pesos por solicitud ni ejecutar código arbitrario del paquete. Artefacto ausente o inválido SHALL impedir consumo sin activar simulación; simulación SHALL continuar exclusiva de pruebas explícitas.

#### Scenario: Artefacto alterado
- **WHEN** el checksum, mapa o formato del release no coincide con lo aprobado
- **THEN** el worker no reclama trabajo y emite un diagnóstico operativo sin secretos

#### Scenario: Arranque sin pesos
- **WHEN** el modo real no dispone de su release
- **THEN** no produce resultados inventados y los trabajos permanecen durables para procesamiento posterior

### Requirement: Entrada de papa identificada y abstención evaluada
La entrada del piloto SHALL exigir que el usuario identifique previamente una hoja de papa y producir resultados técnicos contractuales solo para tizón temprano o tardío. SHALL abstenerse con motivo aplicable ante cultivo ajeno, papa sana, calidad visual insuficiente o evidencia insuficiente conforme controles evaluados. SHALL NOT inventar cultivo, enfermedad ni recomendaciones. NO_CONCLUYENTE SHALL seguir siendo estado de Diagnosis, no clase entrenable.

#### Scenario: Imagen dentro de cobertura
- **WHEN** una imagen identificada como hoja de papa satisface controles técnicos del release
- **THEN** se emite predicción con cultivo POTATO y una de las dos clases candidatas compatibles, raw_score y metadatos reales para decisión posterior de Diagnosis

#### Scenario: Imagen fuera de cobertura o ambigua
- **WHEN** los controles evaluados rechazan un cultivo ajeno o una imagen visualmente ambigua
- **THEN** se emite abstención con motivo contractual y sin clase atribuida; cultivo desconocido permanece null

### Requirement: Durabilidad durante inferencia real
El worker SHALL mantener renovación de lease durante cómputo, tiempo de ejecución acotado, acceso a foto por API interna e identidad propia. SHALL conservar fencing y transacción resultado/inbox/outbox previa al ACK, sin acceder directamente a tablas de Diagnosis ni su almacenamiento. No SHALL convertir errores transitorios en éxito o reintentar fuera del presupuesto vigente.

#### Scenario: Resultado posterior a pérdida de lease
- **WHEN** termina la inferencia tras perder la generación válida
- **THEN** no se publica un resultado visible tardío ni se sobrescribe otro terminal

#### Scenario: Redelivery tras commit técnico
- **WHEN** se reentrega trabajo ya confirmado por el worker real
- **THEN** se conserva un resultado lógico y no se duplica la finalización

### Requirement: Metadatos fieles de ejecución
Los resultados SHALL conservar identidad de release/dataset y duración medida; raw_score SHALL mantener su semántica técnica sin presentarse como confianza calibrada. Sin ejecución, metadatos SHALL cumplir nulabilidad conjunta del contrato; ningún resultado SHALL usar versiones sintéticas como modelo real.

#### Scenario: Rechazo previo a ejecutar modelo
- **WHEN** se produce abstención sin ejecutar el modelo
- **THEN** se usan metadatos null conforme Analyzed y no una duración o versión ficticia
