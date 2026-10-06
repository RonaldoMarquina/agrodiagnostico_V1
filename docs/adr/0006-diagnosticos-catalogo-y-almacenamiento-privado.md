# ADR-0006 — Diagnósticos, catálogo candidato y almacenamiento privado de imágenes

Fecha: 2026-10-01. Estado: adoptado para `incremento-2-diagnosticos-y-catalogo`.
Tarea: 1.1 de `incremento-2-diagnosticos-y-catalogo`.

> Rectificación vigente de validación y valores contractuales: [ADR-0007](0007-correccion-cierre-incremento-2.md).

## Contexto

El Incremento 1 implementó autenticación, sesiones, roles y tokens asimétricos Ed25519 en Identity (ADR-0004 y ADR-0005). El servicio Diagnosis únicamente expone salud técnica y una sonda de almacenamiento.

El Incremento 2 habilita la carga privada de imágenes, ciclo de vida inicial de diagnósticos, catálogo agrícola y feedback, preservando la frontera arquitectónica con inferencia y colas (Incremento 3 y 4). Es necesario formalizar las decisiones de persistencia relacional, almacenamiento de objetos S3, concurrencia, idempotencia, verificación criptográfica local y versionado de catálogo, sin asumir transacciones distribuidas ni inventar recomendaciones agronómicas no aprobadas.

Trazabilidad normativa: ADR-0002 (interfaces, estados y eventos V1), ADR-0004 (Ed25519 e identidades) y los deltas OpenSpec del Incremento 2 (`private-image-ingestion-and-storage`, `diagnosis-lifecycle-and-idempotency`, `agricultural-catalog-and-feedback`).

## Decisiones

### 1. Alcance de Diagnosis en Incremento 2 vs Incremento 3

- En el Incremento 2, los diagnósticos creados permanecen en estado `PENDIENTE` salvo que el usuario los cancele.
- No se implementa broker de mensajería (RabbitMQ), outbox/inbox, claim, lease, workers ni transiciones por análisis técnico. Esos mecanismos pertenecen al Incremento 3.
- No se implementan endpoints públicos de simulación de inferencia. Las pruebas de estados terminales (`COMPLETADO`, `NO_CONCLUYENTE`) y variantes contractuales utilizan fixtures internos y bases de datos aisladas de prueba.
- Los eventos (`DiagnosisRequested`, `DiagnosisAnalyzed`, `DiagnosisFinished`) permanecen definidos en contratos pero no son emitidos en este incremento.

### 2. Autenticación local, roles y autorización

- Diagnosis verifica tokens JWT asimétricos localmente mediante el algoritmo EdDSA sobre la curva Ed25519, utilizando exclusivamente la clave pública cargada desde `JWT_PUBLIC_KEY_PATH`. Diagnosis **nunca** recibe la clave privada ni realiza consultas HTTP o lecturas a la base de datos de Identity.
- Se exigen y validan los claims normativos del ADR-0004: `sub` (UUID de usuario), `role` (`USER` o `ADMIN`), `iss` (`agrodiagnostico-identity`), `aud` (`agrodiagnostico-api`), `exp`, `iat` y `jti` (UUID único).
- Toda ruta de negocio de Diagnosis exige Bearer token válido y devuelve la cabecera `Cache-Control: private, no-store`.
- Sobre común de errores contractual `{code, message, correlation_id, details?}`. `X-Correlation-ID` es validado como UUID o generado si falta, devolviendo 400 si se envía un valor no UUID.
- Propiedad estricta: los recursos de usuario (`/api/v1/diagnoses/{id}`, `/image`, `/cancel`, `/feedback`) exigen que `owner_id == sub`. Un rol `ADMIN` en rutas de usuario no elude la comprobación de propiedad y recibe un 404 genérico si el recurso pertenece a otro usuario o no existe.

### 3. Ingesta de imágenes y decodificación estricta

- Se acepta exactamente un archivo multipart en el campo `image`. Cualquier campo extra, multipart múltiple o ausencia de campo `image` devuelve 400. No se exige selección manual de cultivo (`crop_code`).
- Límite real de archivo: máximo 10 MiB (10,485,760 bytes exactos). Los bytes se cuentan en streaming durante la lectura incremental, sin confiar en la cabecera `Content-Length`. Exceder el límite devuelve 413 `PAYLOAD_TOO_LARGE`.
- Límite de transporte multipart: configurado a 11 MiB en FastAPI y Nginx para alojar los delimitadores y cabeceras multipart sin alterar el límite útil del archivo.
- Formatos permitidos: JPEG, PNG y WebP comprobados mediante inspección de bytes y estructura. Formatos no soportados (como GIF, ejecutables o HEIC/HEIF) devuelven 415 `UNSUPPORTED_MEDIA_TYPE` independientemente de la extensión o `Content-Type` declarado. HEIC/HEIF queda pendiente de conversor seguro para V1.
- Decodificación completa de píxeles: se invoca `Image.load()` de Pillow tras verificar integridad. Límite máximo de 24,000,000 píxeles decodificados (24 MP). Descompresiones excesivas (decompression bomb) devuelven 413 `PAYLOAD_TOO_LARGE`. Imágenes corruptas o animadas/multiframe devuelven 400 `INVALID_IMAGE`.
- Archivos temporales: uso de spool privado y acotado, eliminado automáticamente al finalizar la petición HTTP. Ningún archivo rechazado se persiste en S3 ni en PostgreSQL.

### 4. Almacenamiento S3, idempotencia relacional y protocolo de intenciones

- Almacenamiento privado: los bytes de la imagen se guardan únicamente en el servicio S3 (SeaweedFS en desarrollo local) bajo claves generadas por el servidor: `diagnoses/{uuid}/original.{ext}`. PostgreSQL almacena exclusivamente la referencia `object_key` y metadatos. No se exponen URLs públicas ni firmadas a los clientes.
- Idempotencia: cabecera `Idempotency-Key` (ASCII imprimible 1..128). Namespace relacional `(owner_id, 'diagnosis_create', key)`. Fingerprint: SHA-256 de los bytes exactos de la imagen. Ventana de retención fija de 86,400 segundos (24 horas) no deslizante.
- Concurrencia: serialización mediante bloqueo advisory PostgreSQL (`pg_advisory_xact_lock`) calculado con hash determinista de 64 bits de `(owner_id, scope, key)`. Si otra solicitud idéntica está en progreso, devuelve 409 `IDEMPOTENCY_IN_PROGRESS`.
- Replay:
  - Misma clave e imagen idéntica durante retención: 202 `Accepted` con los datos originales del diagnóstico sin re-subir objeto ni duplicar registros.
  - Misma clave con imagen distinta durante retención: 409 `IDEMPOTENCY_CONFLICT`.
  - Misma clave sobre diagnóstico con borrado lógico (tombstone) durante retención: 409 `IDEMPOTENCY_RESOURCE_DELETED`.
  - Expiración (`now >= expires_at`): se permite crear un nuevo diagnóstico y actualizar la clave de idempotencia sin borrar el diagnóstico previo.
- Protocolo de intenciones para evitar huérfanos sin 2PC:
  1. Adquirir advisory lock del namespace; verificar replay o expiración.
  2. Registrar intención durable `image_upload_intents` (id, object_key, created_at) en transacción SQL separada.
  3. En la transacción principal, bloquear la intención con `SELECT ... FOR UPDATE`; si no existe, abortar.
  4. Subir el objeto a S3.
  5. Insertar `diagnoses`, insertar/actualizar `idempotency_keys` y eliminar la intención en el mismo commit relacional.
  6. Si ocurre fallo en S3 o commit, se intenta compensación inmediata (delete en S3 bajo verificación de que ningún diagnóstico lo referencia).
  7. Un comando de mantenimiento periódico (`reconcile_upload_intents`) recupera intenciones huérfanas mediante `FOR UPDATE SKIP LOCKED`, confirma la ausencia de diagnóstico asociado, elimina el objeto en S3 de forma idempotente y borra la intención.

### 5. Ciclo de vida, borrado lógico y cursores de paginación

- Transiciones permitidas en V1: `PENDIENTE → PROCESANDO → COMPLETADO | NO_CONCLUYENTE | FALLIDO` y `PENDIENTE → CANCELADO`. Las transiciones terminales son irreversibles.
- Cancelación: `POST /api/v1/diagnoses/{id}/cancel` actualiza atómicamente diagnósticos en `PENDIENTE` no borrados a `CANCELADO` devolviendo 200. Cualquier otro estado devuelve 409 `DIAGNOSIS_NOT_CANCELABLE`. La cancelación no emite `DiagnosisFinished`.
- Borrado lógico: `DELETE /api/v1/diagnoses/{id}` es idempotente y devuelve 204 tanto en la primera llamada como en repeticiones del propietario, conservando tombstone (`deleted_at`). No cancela el trabajo de fondo ni borra físicamente la foto. El recurso borrado queda oculto con 404 en GET detalle, imagen, cancelación y feedback.
- Paginación keyset: orden estable `(created_at DESC, id DESC)`, límite 1..100 (por defecto 20).
- Cursores autenticados: payload Base64URL protegido con HMAC-SHA256 utilizando una clave secreta independiente (`CURSOR_SIGNING_KEY_FILE`). El payload contiene versión, propósito del endpoint (`user_diagnoses` o `admin_diagnoses`), `sub`, `created_at` e `id`. Cursores alterados, manipulados o cruzados entre endpoints/usuarios devuelven 400 `INVALID_PAGINATION`. La paginación continúa funcionando de forma estable aunque el registro ancla haya sido borrado lógicamente.
- Supervisión administrativa: `GET /api/v1/admin/diagnoses` exige rol `ADMIN` y expone exclusivamente metadatos (`id`, `owner_id`, `status`, `created_at`, `updated_at`, `reason_code`). No incluye `object_key`, imágenes, feedback ni datos de Identity. Cada consulta exitosa registra un log de auditoría.

### 6. Catálogo candidato, versiones inmutables y auditoría

- Taxonomía V1: cultivos `POTATO` y `MAIZE`. Condiciones candidatas (tipo `HEALTHY` o `DISEASE`): `POTATO_HEALTHY`, `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT`, `MAIZE_HEALTHY`, `MAIZE_COMMON_RUST`, `MAIZE_LEAF_BLIGHT`, `MAIZE_GRAY_LEAF_SPOT`.
- Las semillas de base de datos se configuran con `model_supported=false`. El estado activo representa visibilidad administrativa y no acredita validación del modelo de IA. No se introducen plagas ni cultivos ajenos mediante CRUD.
- Recomendaciones inmutables: identificadas por UUID y versión entera incremental (`MAX(version) + 1` bloqueando la fila de condición).
- No se insertan recomendaciones agronómicas semilla sin paquete de fuentes y revisión humana comprobable. El sistema arranca válidamente con recomendaciones vacías (`items: []`).
- Publicación administrativa: exige `source_refs`, `review_reference`, `reviewed_by` y `reviewed_at`. La ausencia de estos campos devuelve 400 `CATALOG_REVIEW_REQUIRED`. El contenido y la versión son inmutables; `PATCH` solo permite activar o desactivar la versión.
- Auditoría transaccional: cada mutación administrativa se registra en `diagnosis_audit_logs` (actor, acción, destino, correlación, timestamp UTC) en la misma transacción relacional.

### 7. Feedback de usuario

- `POST /api/v1/diagnoses/{id}/feedback` permitido únicamente sobre diagnósticos propios no borrados en estado `COMPLETADO` o `NO_CONCLUYENTE`. Otros estados devuelven 409 `FEEDBACK_NOT_ALLOWED`.
- Cuerpo cerrado: `{ useful: boolean, comment?: string }` (comentario máx. 1000 caracteres; si se omite en una actualización, elimina el comentario previo).
- Un único registro por diagnóstico (`UNIQUE(diagnosis_id)`): primer envío devuelve 201 `Created`; envíos posteriores actualizan y devuelven 200 `OK`.
- Los datos de feedback sirven únicamente como métrica de calidad del servicio; **nunca** alimentan automáticamente reentrenamientos de ML ni generan eventos de pipeline.

## Consecuencias y mitigaciones

- **Latencia de transacciones relacionales durante S3**: Se aplican timeouts estrictos (conexión 2s, lectura 5s) y locks advisory acotados para evitar retención prolongada de conexiones de base de datos.
- **Limpieza de objetos huérfanos diferida**: El protocolo de intenciones durables tolera fallos de nodo o reinicios, garantizando que el comando de reconciliación elimine objetos huérfanos sin borrar imágenes de diagnósticos activos.
- **Catálogo inicialmente vacío**: El arranque con `items: []` en recomendaciones refleja la ausencia de contenido revisado por agrónomos, protegiendo al usuario de orientaciones no validadas.
- **Paginación opaca segura**: Los cursores HMAC previenen ataques de enumeración y fugas de IDs internos entre usuarios.
