# ADR-0008 — Flujo asíncrono confiable, identidad interna y leases de diagnóstico

Fecha: 2026-10-07. Estado: adoptado para `incremento-3-flujo-asincrono-confiable`.
Tarea: 1.1 de `incremento-3-flujo-asincrono-confiable`.

## Contexto

El Incremento 2 consolidó la ingesta privada de imágenes, el ciclo de vida inicial (`PENDIENTE`, `CANCELADO`), el catálogo candidato y el almacenamiento privado de fotos bajo claves del servidor `diagnoses/{id}/original.{ext}` (ADR-0006 y ADR-0007). Sin embargo, las solicitudes aceptadas con 202 permanecían indefinidamente en `PENDIENTE` al no existir un canal de procesamiento asíncrono ni integración con inferencia técnica.

El Incremento 3 implementa el flujo asíncrono desacoplado y confiable entre los servicios `Diagnosis` y `AI Inference` mediante RabbitMQ, asegurando tolerancia a caídas del broker y de procesos, deduplicación exacta, delimitación estricta de autoridad y leases temporales protegidos por identidad interna de servicio.

Trazabilidad normativa: ADR-0002 (interfaces y eventos V1), ADR-0004 (identidades y claves asimétricas), ADR-0006 y ADR-0007 (persistencia, idempotencia y almacenamiento privado), y los cinco deltas OpenSpec del Incremento 3:
- `specs/reliable-diagnosis-event-delivery/spec.md`
- `specs/internal-diagnosis-work-leases/spec.md`
- `specs/provisional-inference-worker/spec.md`
- `specs/diagnosis-lifecycle-and-idempotency/spec.md`
- `specs/continuous-integration-foundation/spec.md`

## Decisiones

### D1. Contratos antes del código y versionado explícito

1. **DiagnosisRequested v2**: Se crea la especificación `DiagnosisRequested.v2.schema.json` y su envelope versionado `envelope.v2.schema.json`. El esquema v2 mantiene los campos requeridos (`diagnosis_id`, `owner_id`, `object_key`) pero amplía el patrón de `object_key` para admitir de forma segura las claves reales persistidas por el Incremento 2 (`diagnoses/{UUID}/original.(jpg|png|webp)`) así como las claves UUID compuestas históricas (`diagnoses/{UUID}/{UUID}`).
2. **Preservación estricta de v1**: El esquema v1 (`DiagnosisRequested.v1.schema.json`) y sus fixtures permanecen inalterados. Los eventos `DiagnosisAnalyzed` y `DiagnosisFinished` continúan en la versión 1.
3. **Validadores independientes**: La emisión nueva genera exclusivamente eventos v2. Los consumidores soportan tanto v1 como v2 aplicando validadores estrictos independientes que rechazan URLs, traversal de directorios (`..`), querystrings y versiones desconocidas.
4. **Estado de operaciones**: Las tres operaciones internas de Diagnosis (`diagnosis_claim`, `diagnosis_renew`, `diagnosis_internal_image`) permanecen clasificadas como `contract-only` hasta su verificación y aceptación integral al cierre del incremento.

### D2. Identidad interna separada y frontera de servicio

1. **Par de claves dedicado**: La autenticación de servicios internos utiliza pares de claves Ed25519 independientes por instancia de worker AI, totalmente desacoplados de las claves de identidad de usuarios gestionadas por el servicio `Identity`.
2. **Registro de confianza en Diagnosis**: Diagnosis mantiene un registro estricto en memoria/configuración (`INTERNAL_SERVICE_KEYS`) mapeando `kid` a la clave pública autorizada, el principal (`ai_inference`) y el identificador de instancia (`instance_id`).
3. **Claims del token interno**:
   - `iss`: `agrodiagnostico-internal`
   - `aud`: `diagnosis-internal`
   - `sub`: `ai_inference`
   - `instance_id`: identificador único de la instancia del worker
   - `exp`: tiempo de expiración corto (máximo 60 segundos), sin tolerancia de gracia
   - `jti`: identificador único UUID para evitar reuso
4. **Derivación de lease_owner**: El servidor deriva `lease_owner` directamente del `instance_id` criptográficamente verificado en el token. No se aceptan identificadores de propietario suministrados arbitrariamente por cabeceras o cuerpo HTTP.
5. **Aislamiento de rutas y códigos de error**:
   - Peticiones anónimas o con firma/claims inválidos devuelven 401 `UNAUTHORIZED`.
   - Peticiones con tokens de usuario válidos (roles `USER` o `ADMIN`) en rutas `/internal/*` devuelven 403 `FORBIDDEN`.
   - Tokens internos presentados en rutas de usuario devuelven 403 `FORBIDDEN`.
   - Nginx mantiene la regla estricta de bloqueo devolviendo 404 a cualquier solicitud externa dirigida a `/internal/*`.

### D3. Datos y procesos por propietario

1. **Diagnosis**: Dueño exclusivo de sus tablas relacionales. Incorpora:
   - Tabla `diagnosis_outbox`: eventos a publicar con `event_id`, tipo, versión, routing key, payload envelope JSON, `created_at`, `available_at`, `sent_at` y claim de publicación.
   - Tabla `diagnosis_inbox`: deduplicación de eventos consumidos (`consumer`, `event_id`, `canonical_hash`, `processed_at`).
   - Columnas en `diagnoses`: `lease_owner`, `lease_token`, `lease_expires_at`, `attempt_count`, `processing_deadline_at`, y banderas de señalización.
   - Tabla `quarantine_messages`: aislamiento de mensajes malformados o con versiones no reconocidas.
2. **AI Inference**: Dueño exclusivo de su base de datos técnica independiente:
   - Tabla `inference_jobs`: seguimiento local por `diagnosis_id` e intento.
   - Tabla `inference_inbox`: deduplicación de `DiagnosisRequested`.
   - Tabla `inference_results`: almacenamiento técnico por `(diagnosis_id, lease_token)`.
   - Tabla `inference_outbox`: publicación de `DiagnosisAnalyzed`.
3. **Cero acceso cruzado**: Ningún servicio accede directa o indirectamente a la base de datos o almacenamiento privado del otro servicio.
4. **Procesos dedicados**: Los publicadores de outbox, los consumidores de eventos y los workers de inferencia se ejecutan como procesos de fondo desacoplados de los servidores HTTP de FastAPI.

### D4. Transaccionalidad outbox y transporte

1. **Ingesta con outbox atómico**: Al recibir una imagen válida en POST `/api/v1/diagnoses`, se persisten el diagnóstico (`PENDIENTE`), la clave de idempotencia y el evento `DiagnosisRequested` v2 en la tabla `diagnosis_outbox` dentro de la misma transacción SQL relacional. Si RabbitMQ está caído, la solicitud devuelve exitosamente 202 `Accepted`; el evento permanece durable en el outbox para su publicación posterior.
2. **Publicador desacoplado**: El publicador selecciona lotes de outbox mediante `SELECT ... FOR UPDATE SKIP LOCKED` con claim temporal y backoff, liberando la transacción antes de comunicarse con RabbitMQ. Publica con `mandatory=True` y `publisher_confirms`. Solo marca `sent_at` tras recibir confirmación positiva (`basic.ack`) y sin recepción de `basic.return`.
3. **Consumo con ACK tras commit**: Tanto en AI Inference como en Diagnosis, el mensaje consumido de RabbitMQ se procesa, se valida contra esquemas, se comprueba su inbox y se confirman las mutaciones de negocio y de outbox en la base de datos local **antes** de enviar el `basic.ack` a RabbitMQ. Si ocurre una caída antes del commit, la reentrega es tolerada; si ocurre entre commit y ACK, el inbox detecta el mensaje duplicado y emite ACK sin repetir efectos secundarios.

### D5. Topología de mensajería, cuarentena y replay operativo

1. **Exchange y colas**: Exchange topic durable `agrodiagnostico.events`.
   - `diagnosis.requested.v2` → cola durable `ai_inference.diagnosis-requested.v2`
   - `diagnosis.analyzed.v1` → cola durable `diagnosis.diagnosis-analyzed.v1`
   - `diagnosis.finished.v1` → cola durable `notification.diagnosis-finished.v1`
   - Cada cola cuenta con su respectiva cola de cartas muertas (DLQ) sufijada con `.dlq`.
2. **Aislamiento en cuarentena**: Mensajes con formato JSON corrupto, esquema inválido o versión desconocida se extraen del flujo de negocio y se registran en la tabla local de cuarentena guardando exclusivamente metadatos seguros (hash SHA-256, routing key, motivo de error y marcas de tiempo), sin almacenar cargas útiles arbitrarias que pudieran contener datos sensibles o credenciales. Tras persistir en cuarentena, se envía descriptor a la DLQ y se emite ACK al mensaje original.
3. **Replay operativo seguro**: La reactivación de mensajes válidos retenidos o fallidos se realiza exclusivamente mediante herramientas CLI ejecutadas localmente en el contenedor, exigiendo la especificación obligatoria de actor y motivo auditados. Se prohíbe la alteración del contenido de eventos bajo el mismo `event_id`.

### D6. Leases de trabajo, presupuesto de intentos y recuperación acotada

1. **Tiempos y configuración**:
   - Duración del lease inicial: 60 segundos.
   - Heartbeat de renovación: cada 20 segundos.
   - Deadline global de procesamiento: 300 segundos a partir del primer claim exitoso.
   - Presupuesto máximo: 3 generaciones de ejecución.
   - Esperas mínimas para recuperación: 5 segundos tras el primer vencimiento y 15 segundos tras el segundo.
   - Fuente de reloj: Reloj relacional del servidor PostgreSQL (`CURRENT_TIMESTAMP`), eliminando dependencias de sincronización de reloj entre hosts.
2. **Ciclo de vida y atomicidad**:
   - POST `/internal/diagnoses/{id}/claim` transiciona atómicamente de `PENDIENTE` a `PROCESANDO`, asigna un nuevo `lease_token` (UUID) y fija `lease_expires_at`.
   - Cancelación por usuario y reclamo por worker compiten sobre la misma fila en PostgreSQL: si gana la cancelación, el estado queda irreversiblemente en `CANCELADO` y el claim posterior recibe 409 `DIAGNOSIS_NOT_CLAIMABLE`.
   - Solicitudes `PENDIENTE` nunca reclamadas no están sujetas al deadline de 300 segundos: una caída prolongada del broker no cancela ni vence diagnósticos no iniciados.
3. **Fencing y renovación**:
   - POST `/internal/diagnoses/{id}/lease/renew` y GET `/internal/diagnoses/{id}/image` verifican que el estado sea `PROCESANDO`, que el `lease_owner` y `lease_token` coincidan, y que `CURRENT_TIMESTAMP < lease_expires_at`.
   - Si `CURRENT_TIMESTAMP >= lease_expires_at`, devuelve 409 `STALE_LEASE`.
   - La renovación nunca extiende la fecha de expiración más allá del `processing_deadline_at`.
4. **Recuperación acotada**:
   - Un proceso recuperador en Diagnosis inspecciona diagnósticos en `PROCESANDO` con lease vencido y espera superada.
   - Si `attempt_count < 3` y no se ha alcanzado el deadline, emite una nueva señal `DiagnosisRequested` v2 con nuevo `event_id` y `available_at` diferido.
   - Si se han agotado las 3 generaciones o se alcanza el deadline de 300 segundos, Diagnosis transiciona atómicamente a `FALLIDO` con `reason_code="PROCESSING_TIMEOUT"` y emite un único `DiagnosisFinished` v1.
5. **Borrado lógico y resultados tardíos**:
   - El borrado lógico de usuario (tombstone) no interrumpe el procesamiento técnico interno con lease vigente; oculta el recurso a rutas de usuario (404) y previene notificaciones futuras.
   - Resultados tardíos de workers que presentan tokens vencidos o intentan actualizar diagnósticos en estados terminales se descartan de forma auditada sin resucitar recursos ni alterar la base de datos.

### D7. Simulador provisional y política de publicación técnica

1. **Entorno exclusivo**: Al no contar aún con el modelo de visión entrenado y evaluado (previsto para el Incremento 4), el worker de AI Inference implementa un simulador determinista de análisis técnico activo **únicamente** cuando `APP_ENV=test` y la configuración de fixtures sintéticos está explícitamente habilitada.
2. **Prohibición en producción y desarrollo ordinario**: El simulador rechaza iniciar en cualquier otro entorno y no admite selección de escenarios mediante cabeceras o peticiones HTTP públicas. El worker en Compose normal permanece inactivo.
3. **Escenarios deterministas**:
   - `ABSTENTION`: Emite `DiagnosisAnalyzed` con `outcome="ABSTENTION"` y metadatos nulos; Diagnosis lo transiciona a `NO_CONCLUYENTE` con su `reason_code` correspondiente.
   - `FAILURE`: Emite `outcome="FAILURE"`; Diagnosis lo transiciona a `FALLIDO`.
   - `PREDICTION`: Solo bajo fixtures explícitos con cultivo, clase y catálogo activo aprobado conduce a `COMPLETADO`. Fuera de fixtures con soporte sintético, las semillas ordinarias mantienen `model_supported=false` y Diagnosis transiciona a `NO_CONCLUYENTE` con `UNSUPPORTED_CLASS`.

### D8. Solicitudes previas (backfill) y estrategia de despliegue

1. **Migraciones aditivas**: Las migraciones de esquema añaden tablas y columnas con valores por defecto y nulabilidad controlada, sin eliminar ni alterar datos o fotos preexistentes del Incremento 2.
2. **Herramienta CLI de backfill**: Se provee un comando `backfill_requested` con modo dry-run obligatorio por defecto, selección de lotes o IDs específicos y modo `--apply`. Genera a lo sumo un evento `DiagnosisRequested` v2 inicial para diagnósticos históricos en `PENDIENTE` que carecían de outbox, utilizando las claves de objeto reales existentes y generando correlaciones de recuperación auditadas.
3. **Estrategia de rollback**: En caso de reversión, los publicadores y consumidores se detienen primero, conservando íntegros los datos en PostgreSQL y el almacenamiento de objetos. Los esquemas y binarios mantienen retrocompatibilidad.

### D9. Evidencia integral y automatización en CI

1. **Etapa obligatoria `async-integration`**: Se integra en el pipeline de CI (`scripts/run_ci.py`, `tooling/ci/plan.json` y GitHub Actions) una etapa obligatoria que aprovisiona contenedores reales de PostgreSQL, SeaweedFS (S3), RabbitMQ, Nginx y dos instancias worker concurrentes para verificar el flujo extremo a extremo.
2. **Pruebas de tolerancia a fallos**: La suite valida la matriz completa de fallos: reentrega de duplicados, tokens de lease obsoletos, caídas de publicador y consumidor antes y después de confirmación/commit, aislamiento de versiones inválidas, y desconexiones de RabbitMQ.
3. **Límites documentados**: Se mantiene documentado que el consumo final de `DiagnosisFinished` y el envío de correos corresponden al Incremento 5.

## Consecuencias

### Positivas
- Resiliencia completa ante indisponibilidad temporal del broker de mensajería gracias al patrón Transactional Outbox.
- Eliminación de condiciones de carrera y dobles análisis mediante leases atómicos derivados de identidad verificada y fencing por tokens.
- Cumplimiento riguroso del principio de menor privilegio: ni el worker ni Diagnosis comparten acceso a bases de datos ni claves criptográficas de usuario.
- Trazabilidad y compatibilidad garantizada entre solicitudes con claves de imagen reales (`original.jpg`) y esquemas normativos v1 y v2.

### Negativas / Restricciones
- Mayor sobrecarga transaccional local en Diagnosis y AI Inference por el mantenimiento de tablas de outbox e inbox.
- Las colas y tablas de outbox requieren monitoreo periódico para detectar acumulación de mensajes no enviados o fallos repetidos.
- El tiempo de ejecución del pipeline de CI aumenta al requerir el levantamiento y validación concurrente de múltiples servicios en Docker.


## Precisiones del cierre (2026-10-09)

- El reclamo terminal conserva el código 409 `DIAGNOSIS_NOT_CLAIMABLE` y añade `details` con `field=status`, `code=TERMINAL`. Los conflictos sin esa señal se reentregan con espera; un timeout incierto nunca elimina la entrega.
- PostgreSQL `clock_timestamp()` decide vencimientos después del bloqueo de fila. La emisión de una señal de recuperación no desactiva el deadline: presupuesto y deadline se comprueban antes de la espera y la deduplicación de señales.
- La confirmación de Pika es el retorno sin excepción de `basic_publish` en modo confirms (valor `None`); NACK/return no confirman el outbox. Las actualizaciones de envío usan condición atómica sobre el token del publicador.
- La política de publicación sintética requiere entorno test y versión explícita; el umbral 0.9 es un fixture de aceptación y no un valor de producción ni una certeza calibrada.
