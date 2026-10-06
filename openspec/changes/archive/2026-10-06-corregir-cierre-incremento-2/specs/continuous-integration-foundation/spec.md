## ADDED Requirements
### Requirement: Aceptación obligatoria de Diagnosis
El CI SHALL construir desde el checkout y ejecutar aceptación aislada del incremento 2 con PostgreSQL, S3 y proxy, incluyendo carreras reales de cancelación, idempotencia, versiones y feedback. Un fallo SHALL impedir éxito del CI y los recursos SHALL limpiarse.
#### Scenario: Regresión de Diagnosis
- **WHEN** falla aceptación o una carrera relacional
- **THEN** la etapa obligatoria diagnosis-integration falla y el pipeline no declara éxito
