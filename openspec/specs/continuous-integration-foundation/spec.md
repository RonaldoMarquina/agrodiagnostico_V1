# continuous-integration-foundation Specification

## Purpose

Detectar fallos de integración y contratos en cada cambio con comprobaciones reproducibles, preservando evidencia y separando CI de aplicación de la preparación del agente.

## Requirements

### Requirement: CI-01 Verificación reproducible de aplicación
La CI SHALL ejecutarse en pull requests y cambios de la rama principal con versiones y dependencias bloqueadas. SHALL comprobar lint, tipos del frontend, pruebas técnicas backend/frontend, contratos y sus ejemplos, deltas OpenSpec, inventario de datos, migraciones, builds y smoke Compose. SHALL conservar el workflow de preparación de Copilot y no exigir credenciales de producción, GPU, datasets reales ni pesos.

#### Scenario: Ejecución limpia
- **WHEN** se ejecuta CI desde checkout limpio con configuración efímera de prueba
- **THEN** todas las comprobaciones se ejecutan sin pasos vacíos, sin ignorar errores ni omitir suites obligatorias, y la misma secuencia puede repetirse localmente con comandos documentados.

#### Scenario: Regresión intencional en copia desechable
- **WHEN** se introduce por separado un evento inválido, una referencia HTTP rota, un fallo de migración o un fallo de readiness
- **THEN** el control correspondiente termina con error y el resultado global de CI es fallido en cada caso.

### Requirement: CI-02 Evidencia segura y recursos aislados
Cada ejecución SHALL tener timeout, proyecto Compose aislado, limpieza incluso al fallar y artefactos con resultados de pruebas, versiones, revisión del código y logs sanitizados. SHALL NOT publicar secretos, credenciales, fotos ni payloads sensibles; SHALL preservar evidencias históricas del equipo.

#### Scenario: Fallo del smoke
- **WHEN** un servicio no alcanza readiness dentro del timeout
- **THEN** se guardan reportes y logs útiles sin secretos, la ejecución falla y se eliminan exclusivamente contenedores y volúmenes efímeros de esa ejecución.

### Requirement: CI-03 Alcance honesto de aceptación
La evidencia SHALL vincular cada requisito ENV, CTR, MIG, CI y DATA con comando, resultado y artefacto. SHALL diferenciar verificación contractual, prueba técnica real y funcionalidad pendiente; SHALL NOT marcar RF-01…RF-28 ni métricas V1 como satisfechos sin su fuente y pruebas pertinentes.

#### Scenario: Informe final del incremento
- **WHEN** se revisa la evidencia de cierre
- **THEN** incluye casos positivos y negativos del Incremento 0 y enumera como pendientes el flujo de diagnóstico, autorización de negocio, métricas ML y despliegue público.

### Requirement: Aceptación obligatoria de Diagnosis
El CI SHALL construir desde el checkout y ejecutar aceptación aislada del incremento 2 con PostgreSQL, S3 y proxy, incluyendo carreras reales de cancelación, idempotencia, versiones y feedback. Un fallo SHALL impedir éxito del CI y los recursos SHALL limpiarse.
#### Scenario: Regresión de Diagnosis
- **WHEN** falla aceptación o una carrera relacional
- **THEN** la etapa obligatoria diagnosis-integration falla y el pipeline no declara éxito

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
