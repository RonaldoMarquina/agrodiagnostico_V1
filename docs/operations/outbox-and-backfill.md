# Topología de Mensajería, Publicadores Outbox y Backfill

Este documento define la operación de la topología RabbitMQ, el funcionamiento del Transactional Outbox y el procedimiento operativo de backfill para solicitudes históricas de diagnóstico.

---

## 1. Topología RabbitMQ y Credenciales de Mínimos Permisos (Task 4.1)

### 1.1 Configuración de Exchange y Colas
La mensajería asíncrona de AgroDiagnóstico utiliza un exchange principal durable de tipo `topic`:
- **Exchange**: `agrodiagnostico.events` (durable, no auto-delete).
- **Colas principales y DLQs** (durables, sin expiración automática):

| Evento | Routing Key | Cola Principal | Cola de Cartas Muertas (DLQ) |
|---|---|---|---|
| `DiagnosisRequested` v1 | `diagnosis.requested.v1` | `ai_inference.diagnosis-requested.v1` | `ai_inference.diagnosis-requested.v1.dlq` |
| `DiagnosisRequested` v2 | `diagnosis.requested.v2` | `ai_inference.diagnosis-requested.v2` | `ai_inference.diagnosis-requested.v2.dlq` |
| `DiagnosisAnalyzed` v1 | `diagnosis.analyzed.v1` | `diagnosis.diagnosis-analyzed.v1` | `diagnosis.diagnosis-analyzed.v1.dlq` |
| `DiagnosisFinished` v1 | `diagnosis.finished.v1` | `notification.diagnosis-finished.v1` | `notification.diagnosis-finished.v1.dlq` |

### 1.2 Invariante de la Cola `DiagnosisFinished` sin Consumidor
> **IMPORTANTE**: La cola `notification.diagnosis-finished.v1` se aprovisiona con durabilidad estricta. Durante el Incremento 3, los eventos `DiagnosisFinished` emitidos por `diagnosis` se publican y acumulan durablemente en dicha cola sin un consumidor activo, hasta que el servicio `services/notification` sea implementado en el **Incremento 5**. Está prohibido drenar o descartar estos mensajes mediante consumidores simulados o falsos.

### 1.3 Credenciales y Aislamiento por Mínimos Permisos
Cada servicio cuenta con un usuario propio en RabbitMQ gestionado por el script privilegiado de inicialización (`infra/rabbitmq/bootstrap.py`):
- **`rabbit_diagnosis`**:
  - `configure`: `^$` (no puede alterar topología)
  - `write`: `^(agrodiagnostico\.events)$` (solo publica a exchange autorizado)
  - `read`: `^(diagnosis\.diagnosis-analyzed\.v1|diagnosis\.diagnosis-analyzed\.v1\.dlq)$` (no puede leer colas de `ai_inference` ni `notification`)
- **`rabbit_ai_inference`**:
  - `configure`: `^$`
  - `write`: `^(agrodiagnostico\.events)$`
  - `read`: `^(ai_inference\.diagnosis-requested\.v1|ai_inference\.diagnosis-requested\.v1\.dlq|ai_inference\.diagnosis-requested\.v2|ai_inference\.diagnosis-requested\.v2\.dlq)$` (no puede leer colas de `diagnosis` ni `notification`)
- **`rabbit_notification`**:
  - `configure`: `^$`
  - `write`: `^$` (consumidor de solo lectura, no puede publicar eventos)
  - `read`: `^(notification\.diagnosis-finished\.v1|notification\.diagnosis-finished\.v1\.dlq)$`

---

## 2. Repositorio y Publicador Transactional Outbox (Task 4.2)

### 2.1 Protocolo de Reclamo y Publicación
Para desacoplar la base de datos relacional de la disponibilidad de la red del broker:
1. **Reclamo corto con `SKIP LOCKED`**:
   - Se seleccionan filas con `sent_at IS NULL AND available_at <= now AND (claim_expires_at IS NULL OR claim_expires_at < now)`.
   - Se asigna un `claim_token` UUID y un `claim_expires_at = now + 30s`.
   - **La transacción SQL se confirma inmediatamente**, liberando los bloqueos a nivel de fila antes de iniciar llamadas de red a RabbitMQ.
2. **Publicación con confirmaciones (`publisher_confirms`) y `mandatory=True`**:
   - Cada mensaje se publica con `delivery_mode=2` (persistente) y `mandatory=True`.
   - Si se recibe confirmación positiva (`basic.ack`) y el mensaje no fue devuelto, se actualiza `sent_at = now` en una transacción SQL corta e independiente.
   - Si el mensaje no tiene ruta de destino (`basic.return`), se programa reintento con backoff y no se marca como enviado.
   - Si ocurre un error de transporte, timeout o `nack`, se libera el claim y se programa reintento con backoff exponencial.

### 2.2 Tolerancia a Caídas y Sobreescritura Inmutable
Si un publicador muere inmediatamente después de que RabbitMQ confirma la recepción pero antes de confirmar `sent_at` en PostgreSQL:
- Al expirar el lease del claim (`now >= claim_expires_at`), otro publicador re-reclama la fila.
- El reenvío utiliza **exactamente el mismo envelope inmutable** (`event_id`, `occurred_at`, `correlation_id` y `payload` originales).
- El receptor detecta el `event_id` duplicado en su tabla de `inbox` y lo procesa de forma idempotente sin repetir efectos de negocio.

---

## 3. Garantías de HTTP 202 Accepted en Creación de Diagnósticos (Task 4.3)

Al invocar `POST /api/v1/diagnoses`:
- Se suben los bytes validados al almacenamiento privado S3.
- Se insertan en la **misma transacción atómica de PostgreSQL**:
  1. El registro del diagnóstico en estado `PENDIENTE`.
  2. El registro de `idempotency_keys`.
  3. El evento `DiagnosisRequested` v2 en la tabla `diagnosis_outbox`.
  4. La eliminación de la intención de carga temporal (`ImageUploadIntent`).

### 3.1 Qué garantiza el 202 Accepted
- **Persistencia garantizada**: La imagen está íntegra en S3, el diagnóstico está confirmado en PostgreSQL y el evento está duradero en el outbox.
- **Independencia del Broker**: La respuesta 202 se emite exitosamente **incluso si RabbitMQ está completamente caído**, ya que el evento reposa en el outbox esperando a que el broker se recupere.

### 3.2 Qué NO garantiza el 202 Accepted
- No garantiza conectividad inmediata ni entrega inmediata al broker.
- No garantiza inicio ni finalización inmediata del análisis de visión por el worker.

---

## 4. Herramienta CLI de Backfill para Diagnósticos Históricos (Task 4.4)

Para diagnósticos creados en incrementos anteriores que quedaron en `PENDIENTE` sin evento en `diagnosis_outbox`, se provee la herramienta CLI:

```bash
# Modo dry-run por defecto (inspección segura, sin mutaciones)
python -m app.backfill --batch-size 50

# Modo de aplicación con confirmación
python -m app.backfill --apply --batch-size 50

# Modo filtrado por IDs específicos
python -m app.backfill --apply --ids "uuid-1,uuid-2"
```

### 4.1 Invariantes Operativas del Backfill
1. **Modo Seguro por Defecto**: La ejecución sin la bandera `--apply` opera estrictamente en `dry-run`, realizando `rollback` de la sesión y emitiendo un informe JSON con los candidatos detectados.
2. **Idempotencia Estricta**: Ejecutar el backfill dos veces es seguro. La segunda pasada encuentra 0 candidatos y no produce filas duplicadas en el outbox.
3. **Concurrencia con Cancelación**: Si un usuario canceló el diagnóstico (`CANCELADO`), el backfill lo ignora bajo bloqueo a nivel de fila.
4. **Tratamiento de Tombstones**: Los diagnósticos con borrado lógico (`deleted_at IS NOT NULL`) son incluidos en el backfill porque el borrado lógico no cancela el trabajo técnico; se reportan con `is_tombstone: true` y se auditan.
5. **Conservación de Claves de Objeto**: Emite `DiagnosisRequested` v2 utilizando la clave original existente del objeto (ej. `diagnoses/{uuid}/original.jpg` o `diagnoses/{uuid}/{uuid}`) sin mover ni renombrar archivos en S3.
6. **Prohibición en Perfil de Simulación**: El backfill falla de forma cerrada (`fails closed`) si se intenta ejecutar sobre datos reales dentro del perfil de pruebas o simulación sintética (`ASYNC_SIMULATION_PROFILE=true` fuera de `APP_ENV=test`).

