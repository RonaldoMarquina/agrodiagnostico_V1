# Proposal

## Why
El incremento 2 acepta diagnósticos privados que permanecen PENDIENTE; RabbitMQ solo tiene infraestructura técnica y AI Inference solo salud. Antes de integrar un modelo real necesitamos demostrar entrega recuperable, reclamo exclusivo y resultados idempotentes ante caídas y duplicados.

## What Changes
- Confirmar diagnóstico, idempotencia y outbox Requested en una transacción; publicar con confirmación y consumir con ACK después de persistencia.
- Implementar identidad de servicio independiente de usuarios, claim/renew/imagen interna y recuperación acotada con fencing.
- Incorporar outbox/inbox y trabajo durable en las bases propias de Diagnosis y AI, aislamiento de mensajes inválidos y replay operativo auditado.
- Ejecutar el worker provisional solo con fixtures en un entorno aislado de aceptación; desactivado en el arranque normal. Este es el supuesto conservador de planificación comunicado al usuario, no una autorización para simulación visible en desarrollo ordinario.
- **Cambio de versión contractual:** introducir DiagnosisRequested v2 para aceptar las claves privadas realmente persistidas por el incremento 2; preservar v1 sin modificarlo. Analyzed y Finished continúan en v1.
- Probar las tres variantes terminales únicamente con fixtures inequívocamente sintéticos, y mantener Notification/correo para el incremento 5.
- Añadir aceptación asíncrona obligatoria en CI sin sustituir las verificaciones de los incrementos 1 y 2.

## Capabilities

### New Capabilities
- `reliable-diagnosis-event-delivery`: publicación recuperable, inbox, cuarentena y replay.
- `internal-diagnosis-work-leases`: identidad interna, reclamo, fencing y recuperación.
- `provisional-inference-worker`: trabajo técnico durable y simulación aislada sin modelo real.

### Modified Capabilities
- `diagnosis-lifecycle-and-idempotency`: creación con outbox y transiciones asíncronas sin revertir terminales.
- `continuous-integration-foundation`: aceptación asíncrona obligatoria y evidencia de fallos reales.

## Impact
Servicios Diagnosis y AI Inference, migraciones propias, dependencias bloqueadas de mensajería/validación/HTTP, contratos HTTP y eventos, preparación de secretos y topología RabbitMQ, Compose, pruebas y documentación operativa. Sin acceso cruzado a tablas, entrenamiento, contenido agronómico de producción, frontend final ni envío de avisos. La propuesta no implementa ni promueve todavía operaciones a implemented.
