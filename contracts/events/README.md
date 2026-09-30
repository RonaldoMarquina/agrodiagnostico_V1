# Eventos v1 y entrega futura

Contrato del grupo 2. Los schemas y fixtures se validan ahora; ningún broker, outbox, inbox, consumidor, reintento o lease se ejecuta aquí. [ADR-0002](../../docs/adr/0002-interfaces-y-eventos-v1.md) conserva las decisiones y [routing.json](routing.json) fija nombres y escenarios de aceptación futuros.

## Mensajes

| Evento | Productor → consumidor | Routing key | Cola durable / DLQ |
| --- | --- | --- | --- |
| DiagnosisRequested | Diagnosis → AI Inference | diagnosis.requested.v1 | ai_inference.diagnosis-requested.v1 / sufijo .dlq |
| DiagnosisAnalyzed | AI Inference → Diagnosis | diagnosis.analyzed.v1 | diagnosis.diagnosis-analyzed.v1 / sufijo .dlq |
| DiagnosisFinished | Diagnosis → Notification | diagnosis.finished.v1 | notification.diagnosis-finished.v1 / sufijo .dlq |

Exchange `agrodiagnostico.events`, tipo topic, durable; mensajes persistentes, publicación mandatory con confirms. Mensaje devuelto por falta de ruta, nack o timeout no marca outbox enviado, aunque haya confirmación de recepción del exchange. La configuración de colas/DLQ/retry y los ensayos con caídas pertenecen al incremento 3; el consumidor real de Notification y correo se completa en 5.

Todos llevan event_id UUID único por evento lógico, event_type exacto, schema_version numérico 1, occurred_at UTC Z, correlation_id UUID y payload cerrado. Un reenvío del mismo outbox conserva event_id, contenido y occurred_at. La correlación se conserva a través del flujo; no es credencial.

`DiagnosisRequested` lleva diagnosis_id, owner_id y object_key opaco `diagnoses/{uuid}/{uuid}`. No es URL ni concede acceso: el worker obtiene imagen a través de API interna autorizada y lease vigente. No registrar payloads completos.

`DiagnosisAnalyzed` lleva diagnosis_id y lease_token UUID de fencing, **sin autoridad de autenticación**. Variantes cerradas:

| outcome | Contenido | Alcance |
| --- | --- | --- |
| PREDICTION | crop_code POTATO/MAIZE, class_code candidato coherente, raw_score 0…1, model_id/model_version/dataset_version e inference_ms reales | Resultado técnico; Diagnosis decide publicación con clase soportada, calibración y catálogo |
| ABSTENTION | reason_code LOW_CONFIDENCE/UNSUPPORTED_CROP/BAD_IMAGE/UNSUPPORTED_CLASS; sin class_code ni raw_score | Cultivo puede ser null. Los cuatro metadatos de ejecución están todos presentes con valores reales, o todos null si no se ejecutó modelo |
| FAILURE | reason_code INFERENCE_ERROR/RETRIES_EXHAUSTED/IMAGE_UNAVAILABLE/PROCESSING_TIMEOUT; sin clase/score | Fallo definitivo, no un reintento transitorio. Misma regla de nulabilidad; no inventar modelo ni duración cero |

inference_ms cuenta milisegundos, entero no negativo. Cero es una medida real, null indica ausencia de ejecución. Los fixtures usan modelos `synthetic-test/fixture-1`, sin afirmar que existan artefactos de inferencia. `NO_CONCLUYENTE` nunca es class_code. El score no es certeza clínica. Eventos no contienen recomendaciones: son responsabilidad de Diagnosis y su catálogo.

`DiagnosisFinished` admite solamente COMPLETADO, NO_CONCLUYENTE o FALLIDO, más diagnosis_id y owner_id. CANCELADO no emite este evento ni aviso. El consumidor consulta detalles autorizados cuando se implemente; no infiere un diagnóstico desde el evento.

## Transacciones y confirmaciones

| Paso | Commit local requerido antes del siguiente efecto | Responsable / aceptación real |
| --- | --- | --- |
| Admisión | Solicitud PENDIENTE + outbox Requested en la misma transacción | Diagnosis / 2–3 |
| Publicación | Enviar outbox; marcar enviado solo tras confirm y ausencia de return; fallo conserva fila para reintentar | Publicadores / 3 |
| Análisis | Reclamo atómico autorizado; persistir resultado técnico + outbox Analyzed + deduplicación de trabajo en base AI antes de ACK Requested | AI / 3; modelo real / 4 |
| Publicación visible | Validar inbox/event_id, estado PROCESANDO y lease actual no vencido; resultado, snapshot/versiones y outbox Finished en la misma transacción con inbox | Diagnosis / 3–4 |
| Aviso | Inbox + aviso único en base Notification; ACK Finished tras commit; correo se procesa aparte | Notification / 5 |

La deduplicación usa `(consumer,event_id)` y restricciones de unicidad del efecto lógico. El token de lease protege generaciones distintas aunque reciban event_id distintos. Un lease obsoleto o estado terminal se ignora y audita sin alterar resultado ni crear Finished; el registro de descarte/dedupe se confirma antes de ACK. Cancelación/reclamo compiten con actualización atómica; una sola gana. No revertir terminales ni reactivar cancelados en replay.

Tres intentos totales para fallos temporales (inicial + dos con espera). El incremento 3 fijará esperas, timeout y recuperación de worker muerto; un error permanente no entra en bucle de reintentos. Mensajes inválidos o versión desconocida se aíslan en DLQ/cuarentena con causa segura, sin ejecutar negocio; confirmar persistencia del aislamiento antes de retirar el mensaje. Replay manual autorizado, auditado e idempotente. No se promete exactly-once físico.

## Escenarios pendientes de ejecución

[routing.json](routing.json) conserva duplicados, lease viejo, caída del publicador, caída antes/después de commit, versión desconocida, replay terminal, correo/Redis caídos y mensaje sin ruta. Las pruebas actuales verifican matriz y formas, **no prueban entrega ni atomicidad**. Incremento 3 debe probar todos los escenarios de transporte/concurrencia; el 5 completa aviso/correo. Caída de Redis o correo no revierte diagnósticos.

Cambios incompatibles, campos nuevos en formas cerradas o otra capacidad del modelo requieren nueva versión y revisión OpenSpec/ADR; desplegar consumidor compatible antes del nuevo productor, con convivencia de rutas/colas mientras drena v1. Versiones desconocidas nunca se interpretan como v1 por defecto.
