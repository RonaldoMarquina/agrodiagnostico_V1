# Spec Delta

## MODIFIED Requirements

### Requirement: Topología durable y separación de dependencias
Colas y mensajes SHALL persistir al recrear broker sin borrar volúmenes. `DiagnosisFinished` v1 SHALL entregarse a través de su cola durable `notification.diagnosis-finished.v1` al consumidor durable `notification-consumer`, otorgando al usuario de broker de `notification` permisos de lectura únicamente sobre sus colas y escritura únicamente sobre el exchange de eventos para descriptores DLQ, sin acceso a colas de otros servicios. La caída o retraso de `Notification`, Redis o el proveedor de correo no SHALL impedir la aceptación ni la finalización de diagnósticos en `Diagnosis`.

#### Scenario: Recreación
- **WHEN** se recrea RabbitMQ con su volumen
- **THEN** eventos confirmados pendientes siguen disponibles en sus colas durables

#### Scenario: Notification ausente
- **WHEN** se publica `DiagnosisFinished` v1 sin consumidor `notification-consumer` activo
- **THEN** el mensaje permanece durable en su cola y no se simula un aviso ni se revierte el diagnóstico

#### Scenario: Consumo durable de Notification
- **WHEN** `Diagnosis` publica `DiagnosisFinished` v1 con `notification-consumer` activo
- **THEN** el evento se consume de forma idempotente para crear el aviso interno y, si llega un mensaje inválido, se aísla en cuarentena con descriptor DLQ sin afectar a `Diagnosis`

#### Scenario: Fallo de correo no revierte diagnóstico
- **WHEN** el proveedor de correo falla al procesar un `DiagnosisFinished` v1
- **THEN** el aviso interno se conserva y el diagnóstico mantiene intacto su estado terminal

#### Scenario: Redis caído
- **WHEN** Redis no responde durante el flujo
- **THEN** diagnóstico, outbox, inbox y notificaciones conservan sus garantías
