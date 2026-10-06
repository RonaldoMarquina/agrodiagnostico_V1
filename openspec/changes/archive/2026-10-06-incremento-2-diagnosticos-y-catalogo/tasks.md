# Tasks

Guía de ejecución para Antigraviti: implementar este cambio con `openspec-apply-change`, siguiendo design.md y los tres deltas. Cada casilla requiere código/artefacto y verificación indicada; no marcar por existencia de archivos. Registrar comandos, resultados y límites por grupo en `docs/evidence/INCREMENTO-2-AUDIT.md`. Si surge una contradicción normativa o cambia el alcance, devolverla a planificación antes de improvisar comportamiento. No modificar trabajo ajeno.

Orden: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7. Grupo 8 integra los anteriores y grupo 9 verifica/cierra. No implementar inferencia, broker, outbox, claim/lease ni UI final. Fixtures terminales solo en pruebas aisladas. El catálogo puede arrancar sin recomendaciones aprobadas; eso no acredita contenido agronómico revisado disponible.

## 1. Decisiones y contratos completos

- [x] 1.1 Registrar un ADR de Diagnosis con el siguiente número libre en `docs/adr/`, tomando las decisiones de design.md: alcance 2/3, propiedad, idempotencia/expiración, recuperación S3, cursor autenticado, catálogo/versiones/feedback y supervisión. Verificar trazabilidad con ADR-0002/0004 y los tres deltas; no redefinir estados/eventos vigentes.
- [x] 1.2 Formalizar todos los métodos/rutas de la tabla de design.md en `contracts/openapi/diagnosis.openapi.json` y esquemas asociados: consultas públicas del catálogo, GET/POST/PATCH administrativos, supervisión y feedback; definir payloads cerrados, límites de texto, respuestas y ejemplos positivos/negativos. Conservar contratos existentes, `MAIZE`, `IDEMPOTENCY_CONFLICT` y DELETE propio 204 repetible; añadir errores de infraestructura, catálogo y feedback. Verificar referencias y ejemplos con `bash scripts/check_contracts.sh` antes de handlers.
- [x] 1.3 Actualizar únicamente entradas del incremento en `contracts/operations.json`, `security-matrix.json`, `http-scenarios.json` y `deferred-operations.json`; mantener operaciones nuevas como contract-only y escenarios sin ejecución como no verificados. Actualizar `docs/API_CONTRACTS.md`; verificar que cada operación del inventario tiene autorización, escenario y tarea de implementación.

## 2. Dependencias, configuración y autorización

- [x] 2.1 Incorporar Pillow, python-multipart y verificación PyJWT/Ed25519 con dependencias bloqueadas en `services/diagnosis/pyproject.toml` y `uv.lock`; comprobar instalación limpia con lock y ausencia de dependencias de inferencia.
- [x] 2.2 Preparar configuración local/Compose para firma en Identity y verificación con la misma clave pública en Diagnosis; añadir secreto separado `CURSOR_SIGNING_KEY_FILE`, estable entre instancias y externo a Git. Reutilizar base diagnosis y S3_BUCKET/ENDPOINT/REGION/CREDENTIALS existentes. Verificar Compose, fallo cerrado sin clave/configuración y que Diagnosis no recibe clave privada; documentar preparación/rotación en `docs/DEVELOPMENT.md` sin volcar secretos.
- [x] 2.3 Implementar autenticación local y RBAC de Diagnosis conforme ADR-0004; probar token válido, ausencia, firma alterada, algoritmo incorrecto, issuer/audience erróneos, expiración, claims faltantes, UUID/rol inválidos, 403 USER en admin y ausencia de consultas a Identity. Documentar ventana stateless de 15 minutos en `docs/SECURITY.md`.
- [x] 2.4 Implementar sobre común de errores, validación/propagación X-Correlation-ID y no-store en respuestas de negocio, incluidos errores. Probar entradas inválidas con 400 contractual, ausencia de filtración de excepciones/credenciales y respuestas 401/403/404 coherentes con esquemas.

## 3. Persistencia y catálogo candidato

- [x] 3.1 Definir modelos de Diagnosis, IdempotencyKey, ImageUploadIntent, Crop, Problem, Recommendation, DiagnosisFeedback y auditoría propia; incluir tombstone, FK/snapshot de recomendación, campos necesarios para variantes de detalle, UNIQUE de idempotencia/versión/feedback e índices keyset. Verificar restricciones y relaciones contra PostgreSQL, sin FK ni consultas a datos de otros servicios; no implementar lease/outbox todavía.
- [x] 3.2 Crear migración posterior a 0001 para tablas/índices/restricciones y seeds `POTATO`/`MAIZE` con las siete condiciones contractuales HEALTHY/DISEASE y `model_supported=false`; no insertar recomendaciones sin evidencia aprobada. Probar upgrade desde 0001, instalación limpia, downgrade/re-upgrade solo en base desechable y rechazo de duplicados/inconsistencias.
- [x] 3.3 Documentar esquema, migración y límites en `docs/PERSISTENCE.md` y `services/diagnosis/README.md`; verificar comandos reproducibles con base/usuario diagnosis. Documentar que ninguna condición candidata activa equivale a clase validada y que catálogo sin recomendaciones es un arranque válido.

## 4. Ingesta, S3 e idempotencia

- [x] 4.1 Implementar parser/validador acotado: único campo image, tamaño real máximo 10 MiB, transporte 11 MiB, JPEG/PNG/WebP, integridad y decodificación completa, máximo 24 MP, rechazo multiframe y limpieza de temporales. Probar límites exactos y +1, Content-Length ausente/engañoso, partes extra, corrupción posterior a cabecera, bomba de píxeles, MIME/extensión falsos y HEIC/HEIF 415, sin diagnóstico/objeto aceptado ante rechazo.
- [x] 4.2 Implementar adaptador S3 put/get/delete con configuración existente, clave generada por servidor, timeouts y reintentos acotados. Verificar integración con SeaweedFS, bytes privados recuperados y denegación anónima; no emitir URL pública, credenciales ni nombres originales.
- [x] 4.3 Implementar idempotencia con bloqueo advisory no bloqueante de namespace y restricción UNIQUE, fingerprint SHA-256, retención no deslizante y reemplazo atómico al expirar. Probar con conexiones PostgreSQL independientes: replay idéntico, contenido distinto, separación A/B, contención 409, frontera exacta now >= expires_at, tombstone 409 y nueva generación sin borrar diagnóstico anterior.
- [x] 4.4 Implementar intención durable y protocolo de carga/commit/compensación descrito en design.md; unirlo a POST diagnoses, con 202 solo tras commit del diagnóstico e idempotencia. Probar S3 caído, subida exitosa seguida de fallo SQL, commit incierto y replay tras timeout: ningún diagnóstico aceptado sin objeto y ninguna eliminación ciega de objeto referenciado.
- [x] 4.5 Implementar comando de reconciliación de intenciones con bloqueo SKIP LOCKED y delete idempotente. Probar caída tras put, fallo de compensación, reinicio, limpiador concurrente con subida, intención limpiada antes de put y objeto referenciado conservado; la intención permanece si la limpieza falla. Documentar comando, reintentos y límites en `docs/PERSISTENCE.md`, verificándolo contra S3/PostgreSQL aislados.
- [x] 4.6 Implementar GET diagnoses/{id}/image con propiedad y exclusión de tombstone. Probar bytes/Content-Type/no-store, 401 y 404 idéntico para ajeno/inexistente/borrado, incluyendo ADMIN en ruta de usuario. Documentar formatos y límites efectivos sin anunciar sanitización EXIF ni soporte HEIC/HEIF.


## 5. Ciclo de vida, historial y supervisión

- [x] 5.1 Implementar cancelación mediante UPDATE condicional de PENDIENTE no borrado. Probar cancelación 200, carrera de dos cancelaciones con un solo éxito, 409 para todos los estados restantes incluido CANCELADO y 404 ajeno/inexistente/borrado; no generar DiagnosisFinished.
- [x] 5.2 Implementar DELETE propio idempotente 204 y detalle contractual. Probar DELETE repetido, 404 ajeno/nunca existente, ocultación de tombstones en detalle/imagen/cancel/feedback, y conservación de estado/objeto; comprobar variantes terminales con fixtures sin crear endpoint de simulación.
- [x] 5.3 Implementar cursores HMAC versionados ligados a principal/propósito e historial keyset, limit 1..100/default 20. Probar empate de fechas, paginación sin duplicados, inserciones entre páginas, ancla borrada, cursor malformado/alterado/ajeno/de otro endpoint y rotación de secreto; todos los cursores inválidos devuelven 400 INVALID_PAGINATION.
- [x] 5.4 Implementar GET admin/diagnoses con campos mínimos de design.md, paginación, exclusión de borrados y auditoría de lectura. Probar ADMIN 200, USER 403, anónimo 401 y ausencia de imágenes/object_key/feedback/datos Identity; comprobar que no concede acceso a fotos ajenas.
- [x] 5.5 Actualizar documentación de estados y supervisión en `docs/API_CONTRACTS.md` y `services/diagnosis/README.md`; contrastar ejemplos con pruebas. Explicitar PENDIENTE sin worker, borrado diferente de cancelación y necesidad de outbox/backfill al habilitar procesamiento en Incremento 3.

## 6. Catálogo revisado y versiones

- [x] 6.1 Implementar consultas públicas autenticadas de cultivos/condiciones/recomendaciones: solo activos y última versión aprobada activa, lista vacía sin contenido aprobado y 404 para padre desconocido/inactivo. Probar taxonomía exacta, HEALTHY, model_supported=false, no publicación de inactivos y ausencia de recomendaciones inventadas en seeds.
- [x] 6.2 Implementar GET/POST/PATCH de cultivos y condiciones, limitados a taxonomía V1, campos mutables definidos y auditoría propia en la misma transacción. Probar ADMIN/USER/anónimo, duplicados 409, cambios de código/cultivo/tipo o model_supported rechazados y rollback de mutación si falla auditoría.
- [x] 6.3 Implementar GET/POST/PATCH de recomendaciones: revisión/fuentes obligatorias, POST crea versión incremental bajo bloqueo y PATCH solo active. Probar creación concurrente sin versiones duplicadas, rechazo de edición de contenido y evidencia ausente, selección de última versión activa y auditoría transaccional. Usar textos sintéticos solo en fixtures aislados.
- [x] 6.4 Verificar con fixture COMPLETADO que nueva versión, desactivación de recomendación/cultivo/problema no alteran FK/snapshot ni respuesta histórica del diagnóstico. Documentar proceso humano de revisión, referencias de aprobación y estado del contenido disponible en `docs/API_CONTRACTS.md`; si no hay paquete aprobado, registrar ese pendiente sin bloquear arranque técnico ni atribuir aprobación.

## 7. Feedback propio

- [x] 7.1 Implementar POST feedback con UNIQUE(diagnosis_id), serialización con DELETE, booleano estricto y comentario de hasta 1000 caracteres. Probar 201 inicial, 200 de reemplazo, omisión de comentario, concurrencia sin duplicación y payload inválido 400.
- [x] 7.2 Aplicar estados permitidos COMPLETADO/NO_CONCLUYENTE; probar 409 PENDIENTE/PROCESANDO/CANCELADO/FALLIDO y 404 ajeno/inexistente/borrado, incluidos permisos ADMIN propios. Verificar ausencia de eventos/pipelines de entrenamiento y documentar semántica en `docs/API_CONTRACTS.md`; usar fixtures terminales aislados.

## 8. Integración de proxy y aceptación integral

- [x] 8.1 Configurar upstream Diagnosis y rutas de diagnoses/crops/problems y admin/crops/problems/recommendations/diagnoses, preservando admin/users en Identity; límite de transporte 11 MiB y cabeceras privadas/correlación. Verificar nginx -t y solicitudes reales de cada familia por proxy, incluyendo coincidencias de prefijo, rutas internas bloqueadas y archivo válido de exactamente 10 MiB.
- [x] 8.2 Ejecutar aceptación aislada Identity + Diagnosis + PostgreSQL + S3 + Nginx: JWT real, carga, replay, A/B, historial, cancelación, tombstone, catálogo/admin y feedback con fixture terminal. Inyectar fallos S3/SQL y ejecutar reconciliador; comprobar que no se requiere broker, Redis, correo ni inferencia para este alcance. Documentar comando de reproducción y resultados.
- [x] 8.3 Integrar pruebas Diagnosis en CI y comparación de OpenAPI generado contra operaciones implementadas. Ejecutar suite pertinente de backend, contratos y regresión de integración/persistencia; promover solo operaciones y escenarios realmente verificados, dejando claim/lease/imagen interna contract-only. Conservar reportes reproducibles.

## 9. Revisión y cierre del incremento

- [x] 9.1 Consolidar evidencia en `docs/evidence/INCREMENTO-2-AUDIT.md` con matriz requisito/tarea/prueba, comandos, resultados, fallos resueltos y pendientes (contenido aprobado, HEIC/HEIF, worker y métricas no medidas). Actualizar README, `docs/Incrementos.md`, DEVELOPMENT y TESTING para que describan exactamente lo ejecutable.
- [x] 9.2 Revisar implementación contra contratos y tres deltas; ejecutar `openspec validate incremento-2-diagnosticos-y-catalogo --strict` y confirmar que ninguna casilla se cerró solo por documentación. Sincronizar deltas y archivar por las skills instaladas únicamente tras cumplir las tareas y verificaciones, conservando pendientes de V1 explícitos.
