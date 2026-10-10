## ADDED Requirements

### Requirement: Aceptación asíncrona obligatoria
El CI SHALL conservar las etapas existentes y agregar async-integration obligatoria con PostgreSQL, RabbitMQ y S3 reales, dos workers y fixtures aislados. SHALL verificar contratos, autorización, concurrencia, crashes, recuperación, DLQ y replay, conservando evidencia sanitizada y limpieza aun al fallar.

#### Scenario: Flujo completo
- **WHEN** se ejecuta aceptación desde checkout limpio sin GPU, pesos ni correo
- **THEN** la carga atraviesa Requested, claim, Analyzed y Finished con estados de fixture verificables

#### Scenario: Fallo de garantías
- **WHEN** fallan dedupe, fencing, recuperación o rechazo de credenciales
- **THEN** el pipeline falla sin omitir la etapa ni sustituirla por noop

#### Scenario: Limpieza
- **WHEN** termina o falla la aceptación
- **THEN** solo se eliminan recursos de esa ejecución y quedan resultados, versiones y hashes

#### Scenario: Alcance honesto
- **WHEN** se cierra el incremento
- **THEN** la evidencia distingue simulación de modelo real y conserva Notification/correo y métricas de producción como pendientes
