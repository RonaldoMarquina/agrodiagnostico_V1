## ADDED Requirements

### Requirement: CI técnica de ML sin datos privados
El CI SHALL conservar etapas existentes y agregar validación de contratos ML, integridad de artefactos, runtime CPU y políticas con fixtures explícitos. SHALL ejecutarse desde checkout limpio sin .env, GPU, imágenes privadas ni pesos productivos. Un fixture SHALL NOT acreditarse como evaluación agronómica.

#### Scenario: Paquete corrupto o política inválida
- **WHEN** una prueba detecta aceptación de pesos alterados, mapa incompatible o política sin evidencia
- **THEN** falla la etapa obligatoria y el pipeline completo no declara éxito

#### Scenario: Checkout limpio
- **WHEN** se ejecuta el pipeline sin configuración local ni dataset
- **THEN** se comprueban runtime y reglas técnicas con fixtures aislados sin omitir etapas existentes

### Requirement: Evidencia experimental separada del CI
El cierre del incremento de modelo SHALL requerir aceptación adicional con release real aprobado y datos autorizados, resultados por ambos tizones de papa, negativos, catálogo revisado, acceso privado, leases y redelivery. SHALL registrar revisión de código, hashes de artefactos/datos, comandos, entorno y resultados; SHALL distinguir CI local/remoto de aprobación experimental.

#### Scenario: CI verde sin dataset aprobado
- **WHEN** pasan pruebas técnicas pero no existe evaluación real aprobada
- **THEN** se conserva el incremento pendiente de cierre y no se anuncia modelo validado

#### Scenario: Aceptación integrada real
- **WHEN** se ejecuta la aceptación con datos y release aprobados
- **THEN** una carga autorizada atraviesa el worker real hasta resultado/historial coherente, con abstención en casos rechazados y 404 genérico para otro propietario
