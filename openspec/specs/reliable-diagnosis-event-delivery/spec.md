# reliable-diagnosis-event-delivery Specification

## Purpose

Garantizar entrega recuperable e idempotente de eventos de diagnóstico mediante persistencia local y confirmaciones, sin depender de disponibilidad continua del broker.

## Requirements

### Requirement: Versionado compatible de solicitudes
El sistema SHALL emitir DiagnosisRequested v2 con claves privadas de objeto existentes o UUID/UUID y validar v1/v2 por separado. SHALL conservar inalterado v1; Analyzed y Finished SHALL seguir v1. No SHALL aceptar URLs, traversal, credenciales o bytes de fotografía.

#### Scenario: Clave existente
- **WHEN** se publica una solicitud cuya imagen tiene original.jpg, original.png u original.webp bajo UUID
- **THEN** el evento v2 valida y referencia el objeto existente sin copiar ni renombrar la imagen

#### Scenario: Convivencia
- **WHEN** llega un Requested v1 válido o v2 válido
- **THEN** el consumidor aplica su validador específico y conserva la deduplicación lógica

#### Scenario: Versión desconocida
- **WHEN** llega una versión no soportada
- **THEN** se aísla sin interpretar como v1 ni ejecutar negocio

### Requirement: Outbox recuperable y publicación confirmada
Cada productor SHALL persistir su efecto y outbox en una transacción propia. SHALL conservar event_id y envelope en reenvíos y marcar enviado solo con confirmación y ausencia de devolución por falta de ruta. Reintentos de transporte no SHALL consumir intentos de inferencia.

#### Scenario: Broker caído
- **WHEN** DB y S3 funcionan pero RabbitMQ no
- **THEN** la creación válida devuelve 202 con outbox pendiente y se publica al recuperar broker

#### Scenario: Return o nack
- **WHEN** una publicación recibe return, nack o timeout
- **THEN** no se marca enviada y sigue recuperable

#### Scenario: Crash tras confirm
- **WHEN** el publicador muere después del confirm y antes de marcar enviada
- **THEN** otro publicador reenvía el mismo evento sin duplicar el efecto lógico

#### Scenario: Commit falla
- **WHEN** no se confirma la transacción de negocio
- **THEN** no existe evento publicable de un efecto no confirmado

### Requirement: Consumo idempotente y ACK posterior al commit
Los consumidores SHALL confirmar deduplicación y efectos antes de ACK. SHALL controlar consumer/event_id y la unicidad por diagnóstico/generación. Mismo event_id con contenido diferente SHALL aislarse. Trabajo en curso no SHALL marcarse completado por recibir un duplicado.

#### Scenario: Crash antes de commit
- **WHEN** el consumidor cae antes del commit
- **THEN** la reentrega permite completar el trabajo sin pérdida

#### Scenario: Crash después de commit
- **WHEN** cae tras commit antes de ACK
- **THEN** la reentrega no repite resultado ni Finished

#### Scenario: Colisión de event_id
- **WHEN** dos mensajes tienen igual event_id y distinto contenido
- **THEN** se registra conflicto seguro sin sustituir el contenido previo

### Requirement: Aislamiento durable y replay auditado
Mensajes inválidos SHALL conservar metadatos seguros de cuarentena antes de ACK y un descriptor DLQ recuperable, sin copiar payloads arbitrarios a logs. Replay de eventos válidos SHALL requerir acceso operativo autorizado, actor y motivo auditados, conservar identidad del evento y respetar estados terminales.

#### Scenario: Cuarentena falla
- **WHEN** la persistencia de aislamiento falla
- **THEN** no se retira el mensaje mediante ACK

#### Scenario: DLQ temporalmente caída
- **WHEN** se confirmó cuarentena pero no se entrega descriptor
- **THEN** el outbox del descriptor permanece recuperable

#### Scenario: Replay terminal
- **WHEN** un operador reenvía un evento ya aplicado
- **THEN** no cambia el terminal ni duplica Finished

### Requirement: Topología durable y separación de dependencias
Colas y mensajes SHALL persistir al recrear broker sin borrar volúmenes. Finished SHALL almacenarse en su cola durable sin implementar consumidor Notification. Redis y correo no SHALL ser dependencias de aceptación de Diagnosis.

#### Scenario: Recreación
- **WHEN** se recrea RabbitMQ con su volumen
- **THEN** eventos confirmados pendientes siguen disponibles

#### Scenario: Notification ausente
- **WHEN** se publica Finished sin consumidor Notification activo
- **THEN** queda en cola y no se simula un aviso ni se revierte el diagnóstico

#### Scenario: Redis caído
- **WHEN** Redis no responde durante el flujo
- **THEN** diagnóstico, outbox e inbox conservan sus garantías
