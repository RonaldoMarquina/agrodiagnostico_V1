# Runbook Operativo: Replay Seguro y Reconstrucción de Cuarentena

En conformidad con ADR-0008 (D5), las tareas 7.1 y 7.2 del Incremento 3, y las políticas de auditoría operativa de AgroDiagnóstico V1.

---

## 1. Principios de Seguridad y Aislamiento

1. **Cero Endpoints HTTP Públicos**:
   - Las operaciones de replay y reconstrucción **no están expuestas** en ninguna API HTTP (ni externa ni interna).
   - Se ejecutan exclusivamente mediante herramientas CLI locales dentro del contenedor del servicio correspondiente (`services/diagnosis`).
2. **Contexto Obligatorio y Auditoría Estricta**:
   - Todo comando de replay o reconstrucción exige `--actor` (identificador o correo del operador) y `--reason` (ticket de incidencia o motivo operativo).
   - La ejecución es **denegada de inmediato** si cualquiera de estos dos parámetros falta o está en blanco.
   - Cada intento y efecto se registra de manera transaccional en `DiagnosisAuditLog` (`action="OPERATIONAL_REPLAY"` o `"EXPLICIT_RECONSTRUCTION"`) antes de efectuar cualquier mutación.
3. **Inmutabilidad Absoluta del Envelope en Replays Válidos**:
   - Al reenviar un evento existente, el `event_id`, los metadatos y el cuerpo JSON (`envelope`) permanecen estrictamente inmutables.
   - Está prohibido modificar la carga útil de un evento conservando su `event_id`.
4. **Idempotencia y Protección de Estados Terminales**:
   - Si un diagnóstico ya se encuentra en un estado terminal (`COMPLETADO`, `NO_CONCLUYENTE`, `FALLIDO` o `CANCELADO`), el replay **no altera** dicho estado terminal ni emite un segundo evento `DiagnosisFinished`. El comando registra la auditoría y reporta `SKIPPED_TERMINAL`.
5. **Prohibición de Replay Ciego y Prohibición de Purgas Automáticas**:
   - **No purgas automáticas**: Ni las tablas de cuarentena (`diagnosis_quarantine_messages`, `inference_quarantine_messages`) ni las colas DLQ (`*.dlq`) deben purgarse automáticamente mediante scripts, TTLs silenciosos o borrados masivos. Toda entrada en cuarentena es evidencia de una anomalía o incompatibilidad que debe investigarse.
   - **No replay ciego**: Un mensaje en cuarentena falló por esquema inválido, versión desconocida o corrupción. Reinyectar directamente los mismos bytes corruptos al broker provocaría bucles de fallo o envenenamiento de colas. La recuperación exige **reconstrucción explícita**.

---

## 2. Procedimientos de Operación

### 2.1 Replay de Evento Válido por `event-id`

Se utiliza cuando un evento formalmente válido quedó retenido o se perdió en el broker tras una partición de red antes de confirmarse.

```bash
# Paso 1: Ejecución en modo seguro (dry-run por defecto)
python -m app.replay \
  --actor "operador.infra@example.com" \
  --reason "Incidencia INC-104: Partición de red recuperada" \
  --event-id "a632748d-863d-4c2c-9128-96bbaba591d8"

# Salida esperada en dry-run:
# {
#   "mode": "DRY-RUN",
#   "action": "REPLAY",
#   "status": "DRY_RUN",
#   "event_id": "a632748d-863d-4c2c-9128-96bbaba591d8",
#   "diagnosis_id": "e5234ba0-3119-4edd-978a-11d15690406e",
#   "details": {
#     "event_type": "DiagnosisRequested",
#     "routing_key": "diagnosis.requested.v2",
#     "envelope_preserved": true
#   }
# }

# Paso 2: Aplicar la reactivación en la base de datos
python -m app.replay \
  --actor "operador.infra@example.com" \
  --reason "Incidencia INC-104: Partición de red recuperada" \
  --event-id "a632748d-863d-4c2c-9128-96bbaba591d8" \
  --apply
```

Efecto del comando:
- Restablece `sent_at = NULL`, `claim_token = NULL` y `available_at = CURRENT_TIMESTAMP`.
- El publicador de outbox recogerá el evento en su siguiente lote y lo publicará con confirmación en RabbitMQ.

---

### 2.2 Replay por `diagnosis-id`

Útil cuando se conoce el identificador del diagnóstico pero no el UUID específico del evento en outbox:

```bash
python -m app.replay \
  --actor "operador.infra@example.com" \
  --reason "Reintento de despacho para diagnóstico rezagado" \
  --diagnosis-id "e5234ba0-3119-4edd-978a-11d15690406e" \
  --apply
```

---

### 2.3 Reconstrucción Explícita de Mensaje en Cuarentena

Si un evento emitido fue corrupto o rechazado por esquema inválido, y el diagnóstico afectado permanece en estado `PENDIENTE`:

1. **Inspeccionar la entrada de cuarentena en PostgreSQL**:
   ```sql
   SELECT id, consumer, routing_key, message_hash, error_reason, diagnosis_id, created_at, descriptor_sent_at
   FROM diagnosis_quarantine_messages
   WHERE diagnosis_id = 'e5234ba0-3119-4edd-978a-11d15690406e';
   ```
2. **Ejecutar la reconstrucción explícita**:
   ```bash
   python -m app.replay \
     --actor "ingeniero.calidad@example.com" \
     --reason "Reconstrucción tras corrección de contrato en productor" \
     --reconstruct-quarantine-id "7b64da16-e71e-4d5d-ab8d-50c1fe51ff14" \
     --apply
   ```

Efecto del comando:
- Verifica que el diagnóstico esté en `PENDIENTE`.
- Genera un **nuevo `event_id`** (UUID) formalmente independiente.
- Construye un envelope `DiagnosisRequested` v2 válido utilizando la imagen y propietario legítimos del diagnóstico.
- Valida el envelope contra `DiagnosisRequested.v2.schema.json`.
- Inserta el nuevo evento en `diagnosis_outbox` y audita la reconstrucción en `diagnosis_audit_logs`.

---

## 3. Matriz de Comportamiento ante Fallos Operativos

| Situación | Comportamiento del CLI | Efecto en la Base de Datos |
| :--- | :--- | :--- |
| **Omisión de `--actor` o `--reason`** | Error de validación; código de salida `1`. | Ninguno (ejecución abortada). |
| **Diagnóstico en estado terminal (`COMPLETADO`, etc.)** | Informa `SKIPPED_TERMINAL`; salida `0`. | Auditoría registrada; el estado y el outbox no se alteran. |
| **Reconstrucción de diagnóstico que ya no está en `PENDIENTE`** | Informa `SKIPPED_NOT_PENDING`; salida `0`. | Auditoría registrada; no se genera ningún evento nuevo. |
| **Modo dry-run (sin `--apply`)** | Simula la operación e informa `DRY_RUN`. | Rollback automático; no se aplica ninguna mutación. |
| **Fallo de conexión a la base de datos** | Captura excepción y código de salida `1`. | Rollback garantizado por el manejador transaccional. |

---

## 4. Auditoría y Trazabilidad

Todas las ejecuciones quedan registradas en `diagnosis_audit_logs` con las siguientes características:
- `actor_id`: `00000000-0000-0000-0000-000000000002` (operador de sistema).
- `action`: `"OPERATIONAL_REPLAY"` o `"EXPLICIT_RECONSTRUCTION"`.
- `target_type`: `"diagnosis_outbox"` o `"diagnosis_quarantine"`.
- `details`: Contiene el operador real, motivo textual, IDs de eventos y diagnósticos involucrados, y la bandera de aplicación.

