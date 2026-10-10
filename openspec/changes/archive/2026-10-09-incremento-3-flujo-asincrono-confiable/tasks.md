# Tasks

Implementación para Antigravity. Ejecutar en orden de dependencias; cada casilla incluye su evidencia mínima. No marcar una tarea por crear archivos o por mocks cuando exige procesos/DB/broker reales. La simulación aislada es el alcance conservador de esta propuesta; no habilitarla para usuarios ni inventar valores productivos.

## 1. Decisiones y contratos antes de consumidores

- [x] 1.1 Registrar ADR-0008 con D1–D9: versión Requested, identidad interna, propiedad de datos, estados/leases, presupuesto, cuarentena, backfill y simulación aislada; verificar trazabilidad con los cinco deltas y ausencia de contradicciones con ADR-0002/0006/0007.
- [x] 1.2 Crear Requested v2 y su envelope versionado, preservar v1 y definir rutas/colas v2; actualizar routing.json, fixtures y validadores para claves actuales y UUID/UUID. Verificar v1 y v2 positivos y rechazos de URL/traversal/versión desconocida, sin relajar validadores de Analyzed/Finished v1.
- [x] 1.3 Completar OpenAPI de claim/renew/imagen interna con identidad, códigos exactos 400/401/403/404/409/503 y ejemplos; actualizar matrices HTTP/seguridad sin promover implementación. Ejecutar validación de contratos y documentar orden consumidor-antes-productor en contracts/events/README.md.

## 2. Persistencia durable por servicio

- [x] 2.1 Añadir migración/modelos Diagnosis para outbox/inbox, correlación, lease, contador, deadline y señalización única por generación; probar restricciones de unicidad y upgrade sobre datos del incremento 2 sin alterar imágenes, propiedad, estados ni fechas previas. Documentar esquema y rollback conservador.
- [x] 2.2 Añadir migración/modelos AI para trabajos, reclamo local de ejecución, inbox, resultados y outbox por diagnosis/lease; probar sesiones independientes, restricciones, upgrade/reinicio y downgrade/re-upgrade solo aislados; demostrar que no conecta con la base Diagnosis.
- [x] 2.3 Añadir persistencia de cuarentena y auditoría operativa en cada consumidor; probar rollback ante fallo de auditoría/commit y ausencia de payloads arbitrarios o secretos en logs. Documentar campos conservados y cómo se reconstruye un mensaje inválido sin replay ciego.

## 3. Autenticación interna y leases

- [x] 3.1 Preparar claves Ed25519 dedicadas por instancia, registro público de confianza y JWT internos conforme D2, con dependencias bloqueadas; probar claims, fechas, kid, firma, instancia ajena, USER/ADMIN válidos 403 y JWT interno rechazado en rutas de usuario. Documentar preparación, rotación y permisos de secretos.
- [x] 3.2 Implementar claim atómico y derivación de lease_owner; probar dos workers y carrera claim/cancel sobre PostgreSQL con una sola transición, error 409 exacto y un incremento de contador. Mantener CANCELADO sin Finished; cubrir inexistente y lease vigente.
- [x] 3.3 Implementar renew e imagen interna con owner/token, tiempo de DB y deadline; probar frontera now==expires_at, token antiguo, worker ajeno, tombstone, DB/S3 caídos, no-store y bytes exactos. Verificar /internal sigue 404 mediante Nginx y ninguna URL firmada se entrega.
- [x] 3.4 Incorporar configuración validada de lease/heartbeat/esperas/deadline y documentar valores locales 60/20 s, 5/15 s, 300 s y tres generaciones; probar configuración inválida, renovación limitada por deadline y que PENDIENTE sin primer claim no expira por esa política.

## 4. Topología y publicadores

- [x] 4.1 Aprovisionar topología durable para Requested v1/v2, Analyzed v1, Finished v1 y DLQ con credenciales de mínimos permisos por servicio, bootstrap separado; probar reconexión/redeclaración idempotente, permisos negativos y persistencia tras recrear broker sin borrar volumen. Documentar cola Finished sin consumidor hasta incremento 5.
- [x] 4.2 Implementar repositorio/publicador outbox en cada servicio con claim durable expirante, backoff, mandatory y confirms, sin transacción SQL abierta esperando broker; probar publicadores concurrentes, return/nack/timeout y crash tras confirm antes de sent_at con redelivery real y envelope inmutable.
- [x] 4.3 Integrar outbox Requested v2 en la transacción existente de creación Diagnosis; probar 202 con broker caído, replay sin evento adicional, conflicto/tombstone sin evento, fallo de commit después de S3 y conservación del reconciliador. Documentar qué garantiza 202.
- [x] 4.4 Implementar backfill CLI dry-run/IDs/lotes/--apply y auditoría; probar doble ejecución, concurrencia con cancelación/publicación, correlación histórica ausente y claves legacy sin mover objetos. Documentar que nunca ejecuta datos reales en el perfil de simulación.

## 5. Worker provisional durable

- [x] 5.1 Añadir dependencias bloqueadas de AMQP, HTTP, JWT y JSON Schema en AI; implementar consumo Requested v1/v2 con validación previa y dedupe por evento/hash; probar versiones inválidas, ID repetido con distinto contenido y ausencia de acceso directo a S3/tablas ajenas. Documentar contrato de trabajo y ACK.
- [x] 5.2 Implementar reclamo local exclusivo, claim HTTP e imagen interna, recuperación de timeout incierto y exclusión entre dos instancias; probar worker muerto antes/después de claim, delivery duplicado en curso y pérdida de lease sin ejecutar dos trabajos para la misma generación.
- [x] 5.3 Implementar escenarios deterministas del simulador solo en APP_ENV=test con fixtures explícitos y recursos aislados; probar ABSTENTION/FAILURE/PREDICTION sintético y rechazo de arranque normal, configuración incompleta y selección por HTTP público. Documentar claramente que no existe modelo real.
- [x] 5.4 Confirmar resultado técnico, inbox completado y outbox Analyzed en una transacción antes de ACK; probar crash antes/tras commit y antes de ACK, dos event_id para misma generación y metadatos null sin modelo. Verificar que fallos temporales no crean un segundo presupuesto de tres reintentos dentro del lease.

## 6. Decisión visible y recuperación

- [x] 6.1 Implementar consumidor Analyzed con validación, hash/inbox, fencing y decisión propia de Diagnosis; probar ABSTENTION->NO_CONCLUYENTE, FAILURE->FALLIDO, clase no soportada y catálogo ausente. COMPLETADO solo con soporte/política/catálogo de fixture explícito; seeds normales siguen model_supported=false.
- [x] 6.2 Confirmar estado, snapshot/versiones, inbox y Finished/outbox atómicamente; probar rollback si falla Finished, duplicates por event_id y por diagnosis/lease, historial/feedback de estados terminales y preservación del snapshot al editar catálogo. Documentar invariantes de finalización.
- [x] 6.3 Implementar recuperador de leases con señal única por generación, esperas y tres intentos máximos; probar worker muerto, segundo/tercer intento, deadline, agotamiento, falta de primer claim y carrera resultado/recuperador sobre PostgreSQL. Verificar terminal PROCESSING_TIMEOUT y un único Finished al expirar presupuesto.
- [x] 6.4 Probar descarte auditado de resultados tardíos, terminales y tokens viejos, incluida reentrega con nuevo event_id; demostrar que no resucita CANCELADO/tombstone ni se consume presupuesto por redelivery de transporte. Documentar conteos esperados de filas/eventos.

## 7. Cuarentena, replay y operación

- [x] 7.1 Implementar cuarentena transaccional y descriptor DLQ por outbox para schema inválido/versión desconocida/colisión; probar fallo de persistencia sin ACK y DLQ indisponible con descriptor recuperable, sin logs de payloads ni credenciales.
- [x] 7.2 Implementar CLI de replay para eventos válidos con privilegio operativo, actor y motivo auditados, sin edición de envelope; probar ejecución denegada sin contexto requerido, idempotencia, replay terminal y reconstrucción explícita de inválidos. Documentar runbook sin endpoint público ni purgas automáticas.
- [x] 7.3 Integrar procesos Compose separados y perfil async-test aislado; probar arranque normal sin simulador, dos workers, solo proxy publicado y API Diagnosis disponible con broker/Redis caídos cuando DB/S3 funcionan. Documentar readiness por proceso, cierre ordenado y conservación de trabajos al parar.

## 8. Aceptación completa y cierre

- [x] 8.1 Crear aceptación desde checkout limpio con PostgreSQL/RabbitMQ/S3/Nginx reales y dos workers, sin imágenes Docker preexistentes; ejecutar carga->Requested->claim->Analyzed->Finished para fixtures de los tres terminales y validar respuestas/eventos contra contratos. Verificar Finished durable sin simular aviso Notification.
- [x] 8.2 Ejecutar matriz de fallos de routing.json pertinente a incremento 3: duplicados, lease viejo, crashes antes/después de commit/confirm/ACK, versión desconocida, replay terminal, Redis/broker caídos y mensaje sin ruta; añadir muerte de worker y carrera claim/cancel. Conservar evidence reproducible y dejar email-down como pendiente de incremento 5.
- [x] 8.3 Añadir async-integration como etapa CI obligatoria con timeout, artefactos sanitizados y limpieza propia; probar controles contra omisión/noop y ejecutar pipeline global conservando identity-integration/diagnosis-integration y pruebas de persistencia/entorno.
- [x] 8.4 Promover solo las tres operaciones internas realmente verificadas y escenarios ejecutados, actualizar documentación de estado/evidencia y vincular ADR-0008; verificar regresiones de incrementos anteriores y OpenSpec estricto. Sincronizar y archivar solo cuando todas las tareas tengan evidencia, diferenciando CI local/remoto y simulación/modelo real.

## 9. Correcciones de revisión antes del archivo

- [x] 9.1 Corregir redelivery ante errores HTTP y generaciones posteriores; verificar fencing y renovación del worker.
- [x] 9.2 Aplicar deadline incluso después de señalizar recuperación y conservar bloqueos hasta commit.
- [x] 9.3 Aislar simulación al perfil de prueba y aplicar política sintética explícita de publicación.
- [x] 9.4 Sustituir evidencias simuladas por pruebas del broker, replay y fallos reales; ejecutar CI completo antes del archivo.

## Evidencia del cierre

Revisión y cierre: 2026-10-09. CI local: 17/17 etapas aprobadas. Véanse [informe de cierre](../../../../docs/evidence/INCREMENTO-3-CIERRE.md), [informe CI](../../../../docs/evidence/INCREMENTO-3-CI-LOCAL.json) y [checkpoints E2E](../../../../docs/evidence/INCREMENTO-3-E2E.txt). Cinco capacidades sincronizadas; simulación aislada, modelo real y CI remoto pendientes.
