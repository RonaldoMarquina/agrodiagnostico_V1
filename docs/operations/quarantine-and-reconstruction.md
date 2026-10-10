# Operación de Cuarentena, Reconstrucción de Mensajes y Rollback Conservador

Este documento describe la persistencia durable de mensajes en cuarentena, las políticas de auditoría operativa, el procedimiento de reconstrucción segura de mensajes y la estrategia de rollback conservador para el Incremento 3.

---

## 1. Persistencia de Cuarentena y Campos Conservados

Cuando un consumidor de eventos (en `Diagnosis` o `AI Inference`) intercepta un mensaje que no puede procesar debido a errores de esquema, versión desconocida, colisión de integridad o JSON malformado, el mensaje es aislado en la tabla local de cuarentena (`diagnosis_quarantine_messages` o `inference_quarantine_messages`).

### Campos conservados en las tablas de cuarentena

| Campo | Tipo | Propósito |
| --- | --- | --- |
| `id` | UUID | Identificador único del registro de cuarentena. |
| `consumer` | String(50) | Nombre del consumidor que interceptó el fallo (ej. `diagnosis_consumer`, `ai_inference_worker`). |
| `routing_key` | String(100) | Clave de enrutamiento con la que llegó el mensaje (ej. `diagnosis.requested.v2`). |
| `message_hash` | String(64) | Hash SHA-256 de los bytes exactos recibidos en el transporte. |
| `error_reason` | String(255) | Código del motivo del aislamiento (ej. `INVALID_SCHEMA`, `UNKNOWN_SCHEMA_VERSION`, `INTEGRITY_CONFLICT`). |
| `diagnosis_id` | UUID (nullable) | Identificador del diagnóstico, únicamente si pudo extraerse y validarse formalmente como UUID. |
| `event_id` | UUID (nullable) | Identificador del evento, únicamente si pudo extraerse y validarse formalmente como UUID. |
| `created_at` | DateTime (tz) | Marca temporal UTC en la que se registró el aislamiento. |
| `descriptor_sent_at` | DateTime (tz, nullable) | Marca temporal UTC en la que el descriptor seguro fue emitido a la cola DLQ. |

### Garantías de seguridad y privacidad
- **Cero payloads arbitrarios**: Las tablas de cuarentena **nunca** almacenan los bytes o el contenido crudo del mensaje. Esto evita que contraseñas, secretos, tokens o datos confidenciales queden retenidos en la base de datos o expuestos a operadores.
- **Identificación criptográfica**: El campo `message_hash` permite correlacionar el mensaje aislado con logs de transporte o trazabilidad de red de manera determinista sin exponer su contenido.
- **ACK tras confirmación de cuarentena**: El mensaje defectuoso solo se retira del broker (`basic.ack`) una vez que el registro de cuarentena se ha confirmado en PostgreSQL. Si la base de datos falla, el mensaje no se confirma y el consumidor reintenta o suspende el consumo de forma segura.

---

## 2. Reconstrucción de Mensajes Inválidos sin Replay Ciego

### Principio: Prohibición de Replay Ciego (`Blind Replay`)
Un mensaje en cuarentena fue rechazado porque violó una regla de integridad o contrato técnico. **Reinyectar directamente los mismos bytes crudos al broker está estrictamente prohibido**, ya que provocará un bucle de fallos repetidos o posibles corrupciones de estado en los consumidores downstream.

### Procedimiento de Análisis y Reconstrucción
1. **Inspección de diagnóstico**:
   - Consultar la tabla de cuarentena filtrando por `consumer` y `created_at`.
   - Inspeccionar el `error_reason` y el `message_hash`.
   - Verificar si el descriptor llegó a la DLQ correspondiente (`*.dlq`).
2. **Determinación de causa raíz**:
   - **Caso A (Versión desconocida o desfase de despliegue)**: El productor emitió un evento válido de una versión nueva (ej. `v2`), pero el consumidor aún no ha sido actualizado.
     - *Solución*: Desplegar la versión compatible del consumidor. Una vez actualizado, el consumidor podrá procesar eventos de esa versión.
   - **Caso B (Contrato o payload corrupto)**: El emisor construyó un JSON malformado o con tipos inválidos.
     - *Solución*: Identificar el error en el emisor y desplegar el fix de código en el productor.
3. **Reconstrucción segura de la intención de negocio**:
   - Para reanudar el flujo de un diagnóstico afectado cuyo mensaje original era inválido:
     - Si el diagnóstico legítimo sigue en `PENDIENTE` en `Diagnosis`, el recuperador o la herramienta CLI de backfill puede emitir una nueva señal `DiagnosisRequested` v2 formalmente válida, con un **nuevo `event_id`** y validada contra el esquema JSON antes de insertarse en el outbox.
     - Si se trata de un evento previamente válido retenido temporalmente por fallos de infraestructura, la CLI de replay operativo autorizada se encarga de reinsertar el evento preservando su `event_id` original y su envelope inmutable, auditando de manera estricta el actor y el motivo.

---

## 3. Rollback Conservador de Persistencia

### Principio de Cambios Aditivos
Las migraciones del Incremento 3 (`diagnosis_0003` y `ai_inference_0002`) son estrictamente aditivas:
- Añaden nuevas columnas con valores por defecto o nulabilidad controlada (`attempt_count`, `lease_owner`, `lease_token`, etc.).
- Crean tablas independientes para outbox, inbox, cuarentena y auditoría.
- No alteran, borran ni renombbran ninguna tabla, columna, archivo S3 ni registro del Incremento 2.

### Política ante Incidentes en Producción
Si tras el despliegue del Incremento 3 se detectan problemas en el procesamiento asíncrono:
1. **Detención de procesos asíncronos**:
   - Detener los contenedores o procesos de los workers (`ai_inference_worker`), publicadores de outbox (`diagnosis_publisher`, `inference_publisher`) y consumidores (`diagnosis_consumer`).
   - Mantener activas las APIs HTTP (`Diagnosis`, `Identity`, etc.).
2. **Preservación absoluta del esquema**:
   - **NO ejecutar `alembic downgrade` sobre bases de datos en vivo**.
   - Ejecutar un downgrade eliminaría las columnas de leases y las tablas de outbox e inbox, lo cual destruiría irreversiblemente el estado de diagnósticos en vuelo, causaría pérdida de eventos confirmados y rompería la idempotencia si el broker aún contiene mensajes.
3. **Reversión a binarios compatibles**:
   - Si es necesario, desplegar una revisión anterior de los binarios que ignore las columnas adicionales. Al ser las columnas `nullable=True` o con `server_default`, las versiones previas pueden coexistir sin errores de consulta SQL.
4. **Uso de `downgrade`**:
   - El comando `python -m app.migrate downgrade base` está reservado **exclusivamente** para pipelines de integración continua (CI) y bases de datos efímeras aisladas de pruebas.

