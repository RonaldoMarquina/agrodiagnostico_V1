# Design

## Context

Base inspeccionada: Diagnosis confirma imagen, diagnóstico e idempotencia; no tiene outbox ni columnas de lease. `services/ai_inference/app/main.py` solo ofrece salud. El broker Compose existe pero no tiene consumidores de negocio. Hay 16 etapas de CI local en el cierre anterior; eso no demuestra CI remoto aprobado.

Los contratos internos ya fijan POST `/internal/diagnoses/{id}/claim`, POST `/internal/diagnoses/{id}/lease/renew` y GET `/internal/diagnoses/{id}/image`. Claim no tiene cuerpo; owner deriva de identidad verificada. La clave real de objeto es `diagnoses/{uuid}/original.jpg|png|webp`, incompatible con Requested v1 (`diagnoses/{uuid}/{uuid}`). Los contratos deben resolverse antes del primer consumidor.

## Goals / Non-Goals

**Goals:** tolerancia verificable a redelivery, caída de procesos y broker; un único efecto lógico; autoridad de estado en Diagnosis; contratos verificables y migración segura desde incremento 2.

**Non-Goals:** modelo real, GPU, entrenamiento, contenido agronómico, notificaciones, correo, frontend final, métricas de producción y promesas de disponibilidad multinodo. El perfil de simulación solo opera sobre bases/objetos sintéticos aislados. No se habilita simulación en el Compose normal.

## Decisions

### D1. Contratos antes del código y versionado explícito

Adoptar ADR-0008 durante implementación, sin modificar ADR históricos. Requested v2 conserva los campos de v1 pero admite únicamente los dos formatos generados por servidor: `diagnoses/{UUID}/{UUID}` y `diagnoses/{UUID}/original.(jpg|png|webp)`; se valida cada UUID, sin traversal, URL o query. Crear `DiagnosisRequested.v2.schema.json` y envelope compatible con versiones discriminadas sin relajar el envelope v1. Emisión nueva solo v2; lectura de v1 y v2 con validadores separados. Mantener fixtures y contratos v1 intactos. Analyzed y Finished permanecen v1.

Alternativas descartadas: ampliar v1 silenciosamente contradice la regla vigente de compatibilidad; renombrar/copiar todas las fotos aceptadas introduce un protocolo S3 innecesario. El worker no usa object_key para acceder directamente a S3: es referencia técnica, no credencial. Actualizar `contracts/events/README.md`, routing, matrices HTTP/seguridad, índices y validadores que hoy asumen solo v1. Promover las tres operaciones internas solo después de aceptación.

### D2. Identidad interna separada

JWT Ed25519 con claves dedicadas por instancia worker, nunca la clave de usuarios de Identity. Registro de confianza en Diagnosis: kid -> clave pública + principal ai_inference + instance_id autorizado. El worker monta solo su privada; Diagnosis solo públicas. JWT exige iss=`agrodiagnostico-internal`, aud=`diagnosis-internal`, sub=`ai_inference`, instance_id registrado, iat/exp numéricos y jti UUID. Vigencia local máxima 60 s; sin tolerancia al vencimiento. Validar firma, algoritmo, kid y correspondencia de instancia; lease_owner deriva de instance_id, jamás del body/header arbitrario.

401 para ausente/inválido; un token de usuario reconocido y válido recibe 403 en rutas internas. Un JWT interno no autoriza rutas de usuario. Renovación recibe LeaseRenew; imagen recibe X-Lease-Token. Errores, correlación y no-store siguen el contrato, agregando 503 de DB/S3. Claim vigente/terminal devuelve 409 DIAGNOSIS_NOT_CLAIMABLE; renovación/imagen no vigentes 409 STALE_LEASE; UUID desconocido 404 NOT_FOUND. Nginx continúa devolviendo 404 a /internal/*. Alternativa de secreto bearer estático descartada por no identificar instancias ni caducar.

### D3. Datos y procesos por propietario

Diagnosis: outbox (event_id, tipo/versión, routing, envelope JSON, created_at, available_at, sent_at, claim de publicación), inbox (consumer,event_id, hash canónico, resultado aplicado/descartado), lease_owner/token/expires_at, attempt_count, processing_deadline_at, correlation_id original, marca de señal de recuperación y auditoría segura. Unicidades: emisión inicial Requested por diagnóstico, recuperación por generación expirada, Finished por diagnóstico. No registrar payloads en logs.

AI: tabla de trabajos por diagnosis_id con intento/lease vigente y reclamo local de ejecución; resultados por (diagnosis_id,lease_token), inbox y outbox Analyzed únicos por esa generación. Cada servicio migra únicamente su base; ningún ORM consulta tablas de otro servicio. Añadir procesos separados para publicadores, consumidor de Diagnosis, worker AI y recuperación Diagnosis; reutilizan la imagen y módulos del servicio dueño. No lanzar consumidores como tareas background por cada réplica HTTP.

### D4. Transacciones y transporte

Creación: preservar intención S3 y bloqueo idempotente existentes; insertar outbox Requested v2 junto con diagnosis e idempotencia y eliminar intención en el mismo commit. Replay no crea evento ni objeto. Un broker caído no impide 202 si DB y S3 están disponibles. Commit fallido conserva el protocolo de reconciliación.

Publicador: seleccionar lotes con claim durable y expiración, sin mantener una transacción SQL abierta esperando RabbitMQ. Publicar persistente, mandatory y confirms. Marcar sent_at solo tras confirm y ausencia de return; return/nack/timeout conserva pendiente. Después de crash entre confirm y sent_at, reenviar exactamente event_id/envelope/occurred_at originales. Reintentos de transporte ilimitados con backoff acotado mientras exista la fila; nunca consumir presupuesto de ejecución por una caída del broker.

Consumidor AI: validar antes de efectos; ante Requested, adquirir reclamo local exclusivo por diagnóstico y reclamar por API. Guardar generación obtenida; un timeout incierto de claim no se reintenta ciegamente mientras pueda existir lease: esperar expiración y recuperación. Otro delivery para trabajo en curso no ejecuta análisis paralelo ni recibe ACK prematuro. Resultado técnico + outbox Analyzed + inbox completado se confirman juntos antes de ACK. Estado terminal/no reclamable definitivo permite registrar descarte y ACK; conflicto de lease vigente ajeno requiere espera/reentrega acotada, no marcar trabajo completado.

Consumidor Diagnosis: validar evento, inbox y generación con actualización condicional en transacción; comparar tiempo de DB y no occurred_at del emisor. Commit de resultado visible, snapshot cuando corresponde, inbox y Finished/outbox antes de ACK. Distintos event_id para mismo lease no generan efectos repetidos. Mismo event_id con contenido distinto se aísla como conflicto de integridad. Token viejo, lease vencido o terminal: auditar descarte y deduplicar antes de ACK.

### D5. Topología y mensajes inválidos

Exchange topic durable `agrodiagnostico.events`. Mantener rutas/colas v1 de routing.json; añadir `diagnosis.requested.v2` -> `ai_inference.diagnosis-requested.v2` y DLQ `.dlq`. Consumir Requested v1/v2 y Analyzed v1. Declarar cola durable Finished v1 aunque Notification no tenga consumidor todavía; no drenar sus mensajes con un consumidor ficticio. Single-node local prueba persistencia, no HA. Usuarios de broker por servicio, permisos mínimos de lectura/escritura y bootstrap privilegiado separado.

Backoff de entrega por fallo de DB/HTTP evita bucle inmediato de nack; suspender consumo/reconectar con espera sin ACK, conservando mensaje en broker. Para mensajes inválidos, persistir en cuarentena local metadatos seguros (hash, motivo, routing, IDs solo si válidos) y outbox de descriptor DLQ; no copiar bytes arbitrarios con posibles secretos. ACK del original solo después de commit de cuarentena; el descriptor se entrega a DLQ mediante confirms. No depender de dead-letter automático para la garantía de no pérdida. Eventos válidos recuperables permanecen en outbox original; inválidos requieren reconstrucción explícita, no replay ciego de bytes.

CLI operativa de replay dentro del contenedor dueño, sin endpoint público, exige actor y motivo, registra auditoría antes de programar reenvío. Conserva event_id y envelope de eventos válidos; se prohíbe editar contenido conservando event_id. Repetir replay de terminal no modifica estado. Documentar privilegio de ejecución y uso; no prometer autorización por un simple campo actor.

### D6. Lease, presupuesto y recuperación

Valores de aceptación/local propuestos, configurables y NO calibrados para producción: lease 60 s, heartbeat 20 s, deadline de procesamiento 300 s desde primer claim, máximo 3 generaciones; espera mínima para reclamos segundo/tercero 5/15 s después de expiración anterior. Fuente temporal: reloj PostgreSQL. Tests usan reloj controlado o duraciones acotadas sin sleeps extensos. Config inválida (heartbeat >= lease, límites no positivos, deadline menor que lease) impide iniciar workers.

Claim PENDIENTE cambia a PROCESANDO, incrementa attempt_count y genera UUID; recuperación de PROCESANDO solo si expiró, pasó espera y quedan presupuesto/deadline. Claim y cancelación compiten sobre la misma fila. Renovar conserva token y nunca extiende más allá de deadline. `now == expires_at` ya está vencido. PENDIENTE no tiene deadline de procesamiento: broker caído no condena solicitudes todavía no reclamadas.

Fallos temporales de ejecución: el worker persiste causa segura, deja de renovar y permite recuperación después de vencimiento/espera. Cada nueva generación consume exactamente un intento; no existe un bucle adicional de tres intentos dentro de cada generación. Fallo definitivo emite Analyzed FAILURE inmediatamente. Un fallo temporal, incluso durante el tercer lease vigente, conserva la entrega y deja de renovar: Diagnosis es la autoridad del contador. La muerte del worker, el deadline alcanzado o el tercer lease vencido se resuelven por Diagnosis a FALLIDO/PROCESSING_TIMEOUT con auditoría y Finished atómicos. El worker no infiere el presupuesto global a partir de sus reintentos locales.

Recuperador Diagnosis periódico (local 1 s) emite una nueva señal Requested con event_id nuevo por generación expirada, unicidad SQL y available_at tras espera. No revierte PROCESANDO a PENDIENTE. Si presupuesto/deadline agotado, finaliza en vez de reenviar. Un análisis que compite con recuperación solo gana si mantiene generación vigente y tiempo válido. Terminal jamás revive.

Borrado lógico conserva semántica del incremento 2: no cancela trabajo ni elimina bytes. Acceso interno puede continuar para tombstone con identidad y lease válidos; accesos de usuario siguen 404. Finished no vuelve visible el diagnóstico borrado; futura Notification deberá consultar visibilidad antes de avisar.

### D7. Simulador y política de publicación

Perfil exclusivo `async-test`, recursos nuevos con nombre aislado y configuración explícita de fixtures. El simulador rechaza iniciar fuera de APP_ENV=test o sin bandera de fixtures; no acepta escenarios por cabecera/body público. Escenarios deterministas definidos por harness y datos sintéticos: ABSTENTION sin modelo con metadatos null, FAILURE técnico, y PREDICTION con artefacto sintético claramente identificado exclusivamente en fixtures. No introducir un campo simulated en eventos v1 cerrados.

Diagnosis es quien decide: ABSTENTION -> NO_CONCLUYENTE con motivo; FAILURE -> FALLIDO; PREDICTION requiere soporte de clase, política calibrada y catálogo aprobado activo para COMPLETADO. En este incremento solo los fixtures habilitan soporte/política/versiones sintéticas para probar ese camino. Valores productivos no existen: una predicción fuera de fixture carece de soporte y termina NO_CONCLUYENTE/UNSUPPORTED_CLASS; si existe soporte pero falta catálogo -> CATALOG_UNAVAILABLE. Conservar snapshot inmutable. No simular recomendaciones científicas ni versiones de modelo reales. El worker normal permanece deshabilitado hasta incremento 4; publicadores pueden conservar trabajos reales sin procesarlos.

### D8. Solicitudes previas y despliegue

Migraciones aditivas sin borrar datos ni fotos. Cargas nuevas reciben outbox; para PENDIENTE previos sin señal inicial, CLI backfill con dry-run por defecto, lote e IDs explícitos, modo --apply y auditoría. Usa la clave real del objeto, genera nueva correlación de recuperación si no existe la original sin atribuirla al request histórico, y crea máximo un Requested v2 inicial por diagnóstico. Revalida bajo lock estado y ausencia de evento; incluye tombstones porque borrado no cancela, mostrando esa condición en dry-run. Nunca ejecutar backfill real dentro del perfil sintético.

Orden: ADR/contratos, migraciones, credenciales/topología, consumidores compatibles v1/v2, publicadores, señalización de solicitudes nuevas, aceptación aislada; backfill operativo solo explícito. Rollback: detener consumidores/publicadores y conservar tablas/outbox/trabajos; revertir binarios compatibles sin borrar mensajes. Downgrade destructivo únicamente en DB aislada de tests; no presentar downgrade con datos vivos como seguro.

### D9. Evidencia y CI

Nueva etapa `async-integration` además de identity-integration y diagnosis-integration, con control contra omisión/noop. E2E vía Nginx, PostgreSQL/RabbitMQ/S3 reales y dos instancias worker. Casos de fallos instrumentados en pruebas, nunca endpoints de fallo públicos. Evidencia requisito/tarea/comando/resultado, conteos SQL, versiones y hashes. Conservar pendientes email-down/Notification del incremento 5, sin marcar todas las entradas routing.json como cumplidas.

## Risks / Trade-offs

- Duplicados físicos -> unicidad SQL, inbox y fencing; no prometer exactly-once de transporte.
- Cola Finished sin consumidor -> cola durable e inspección de acumulación, sin purga/TTL que pierda avisos antes de incremento 5; declarar capacidad operativa pendiente de producción.
- Simulación confundida con inferencia -> perfil aislado y rechazo explícito fuera de tests; seeds normales model_supported=false.
- Cambio de esquema Requested -> v2, convivencia de lectores v1/v2 y pruebas independientes de versiones.
- Locks y sesiones durante trabajo externo -> reclamos cortos y tiempos acotados; pruebas de crash/reclamación y de commit incierto.
- Relojes/heartbeats -> tiempo de DB como autoridad y pruebas de fronteras; valores de producción deberán medirse antes de despliegue.

## Migration Plan

Implementar y probar upgrade/restart sobre una base con diagnósticos del incremento 2, y upgrade/downgrade/re-upgrade solo con fixtures. Ejecutar backfill dos veces y en carrera con cancelación para demostrar ausencia de duplicados. Mantener el archivo del incremento 2 intacto; sincronizar únicamente deltas implementados y archivar incremento 3 después de evidencia completa, sin certificar inferencia real.
