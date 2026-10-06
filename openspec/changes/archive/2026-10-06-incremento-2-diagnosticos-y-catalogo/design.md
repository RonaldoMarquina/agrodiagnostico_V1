# Design

## Context

Diagnosis solo tiene salud, una migración base y una sonda S3. La base y usuario PostgreSQL se llaman `diagnosis`; no se introduce `agro_dev`. Compose ya inyecta `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` y `S3_CREDENTIALS_FILE`; `.env.example` usa `agro-local`. Nginx dirige actualmente todo `/api/v1/admin/` a Identity. Los contratos usan `POTATO` y `MAIZE`, no `CORN`.

Referencias normativas: ADR-0002 (interfaces/estados), ADR-0004 (Ed25519), contratos HTTP/eventos vigentes y las tres especificaciones de este cambio. Motivación y alcance en proposal.md.

## Goals / Non-Goals

**Goals:** definir decisiones suficientes para implementar por grupos con pruebas positivas, negativas y de concurrencia, sin depender de inferencia ni de contenido agronómico no aprobado.

**Non-Goals:** implementar broker/outbox/inbox, claim/lease o resultados técnicos; entrenar; crear UI final; aprobar contenido agronómico automáticamente; definir retención productiva de fotos. El borrado lógico no implica borrado físico ni cancelación. La limpieza descrita aquí solo elimina cargas sin diagnóstico asociado.

## Decisions

### 1. Contratos antes de consumidores

Conservar las operaciones existentes de carga, historial, detalle, DELETE, cancelación e imagen. Para campos/respuestas existentes prevalece su contrato: replay 202 con ID/created_at originales y estado actual, conflicto de contenido `IDEMPOTENCY_CONFLICT`, concurrencia `IDEMPOTENCY_IN_PROGRESS`, tombstone `IDEMPOTENCY_RESOURCE_DELETED`. Todos los 409 usan el sobre común. Extender el contrato de carga con 503 `STORAGE_UNAVAILABLE` y `PERSISTENCE_UNAVAILABLE`; una respuesta incierta se resuelve reintentando con la misma clave.

Inventario adicional a formalizar en el grupo 1:

| Ruta | Métodos | Autorización / efecto |
| --- | --- | --- |
| `/api/v1/crops` | GET | Bearer, cultivos activos |
| `/api/v1/crops/{code}/problems` | GET | Bearer, condiciones candidatas activas del cultivo activo |
| `/api/v1/problems/{code}/recommendations` | GET | Bearer, última versión aprobada y activa del problema activo; `items: []` si no existe |
| `/api/v1/admin/crops` | GET, POST | ADMIN, listar incluyendo inactivos / crear |
| `/api/v1/admin/crops/{code}` | PATCH | ADMIN, nombre y estado; código inmutable |
| `/api/v1/admin/problems` | GET, POST | ADMIN, listar / crear condición |
| `/api/v1/admin/problems/{code}` | PATCH | ADMIN, nombre y estado; código, cultivo y tipo inmutables |
| `/api/v1/admin/recommendations` | GET, POST | ADMIN, listar versiones / crear versión nueva |
| `/api/v1/admin/recommendations/{id}` | PATCH | ADMIN, cambiar solo `active` de una versión |
| `/api/v1/admin/diagnoses` | GET | ADMIN, supervisión paginada de metadatos |
| `/api/v1/diagnoses/{id}/feedback` | POST | Bearer propietario, crear 201 o reemplazar 200 |

GET de catálogo devuelve `{items}` sin cursor (catálogo acotado V1); GET administrativo de diagnósticos usa `{items,next_cursor}`. POST de catálogo devuelve 201; PATCH 200. Identificador desconocido/inactivo en consultas públicas: 404 genérico. Payload inválido: 400; código duplicado: 409 `CATALOG_CONFLICT`; contenido de recomendación sin evidencia de revisión: 400 `CATALOG_REVIEW_REQUIRED`. Esquemas cerrados, límites de texto explícitos y ejemplos positivos/negativos se fijan en 1.2 antes de handlers. Catálogo administrativo no incluye DELETE físico. No agregar aliases.

Se descarta cambiar silenciosamente códigos ya contratados o promover operaciones a implemented antes de probarlas. Actualizar también `security-matrix.json`, `http-scenarios.json` y entradas pertinentes de `deferred-operations.json`.

### 2. Identidad, errores y secretos

Verificar exclusivamente EdDSA/Ed25519 localmente, con claims obligatorios `sub`, `role`, `iss`, `aud`, `exp`, `iat`, `jti`; validar UUID de sub/jti, rol USER/ADMIN, issuer/audience del ADR-0004 y caducidad. Ausencia/token inválido devuelve 401; USER en administración 403. ADMIN no omite propiedad en rutas de usuario. Diagnosis recibe solo clave pública (`JWT_PUBLIC_KEY_PATH`), nunca la privada ni acceso a tablas de Identity. Se conserva la ventana stateless de access tokens de 15 minutos del ADR-0004; no se promete revocación inmediata interservicio.

Añadir dependencias bloqueadas de Pillow, python-multipart y PyJWT con soporte criptográfico Ed25519, siguiendo versiones compatibles del repositorio. Preparación local y Compose deben permitir que Identity firme y Diagnosis verifique la misma pareja sin generar claves durante cada arranque. Secreto separado `CURSOR_SIGNING_KEY_FILE`, compartido por instancias de Diagnosis y externo a Git. Ausencia de configuración impide habilitar rutas de negocio; nunca fallback inseguro.

Middleware y manejadores conservan `{code,message,correlation_id,details?}`, UUID de correlación de entrada o 400, y `Cache-Control: private, no-store`. Traducir validaciones a las respuestas contractuales; no filtrar errores de SQL, S3 o JWT.

### 3. Ingesta limitada y decodificación efectiva

Aceptar exactamente un archivo `image`; rechazar partes adicionales y campos inesperados con 400. Contar bytes reales de archivo incrementalmente, sin confiar en Content-Length; detener en 10,485,761 bytes. El límite del archivo sigue siendo 10 MiB. Fijar límite inicial de transporte multipart de 11 MiB en aplicación y Nginx, con límites de cabeceras/partes; es margen técnico local, no aumento del archivo anunciado.

El parser puede usar spool temporal acotado, privado y eliminado al cerrar la solicitud; no persistir fotos inválidas en S3 ni tablas de negocio. No prometer que UploadFile evita siempre disco. Inspeccionar formato real JPEG/PNG/WebP, verificar integridad y reabrir para decodificar píxeles con `load()`; `verify()` aislado no basta. Comprobar ancho por alto y tratar avisos/errores de decompression bomb como 413. Corrupto 400 `INVALID_IMAGE`, formato no soportado 415, exceso 413. Rechazar imágenes animadas/multiframe con 400 `INVALID_IMAGE` en este incremento para mantener acotada la decodificación. Probar MIME/extensión engañosos sin confiar en ellos.

Se conserva el original privado para el fingerprint y entrega; no publicar EXIF ni nombre original como metadatos de API/logs. Una política posterior de transformación o eliminación de metadatos requiere decisión documentada; no anunciar sanitización que no se ejecuta. HEIC/HEIF sigue pendiente V1, con rechazo 415 actual.

### 4. S3, idempotencia y recuperación

Usar bucket y endpoint de entorno, sin hardcode de bucket ni credenciales. Clave `diagnoses/{uuid}/original.{ext}`, UUID generado por servidor, extensión derivada de formato real. Adaptador con put/get/delete, tiempos de espera y reintentos acotados. No URLs públicas ni firmadas para usuarios.

La unicidad `(owner_id,scope,key)` y la transacción relacional protegen diagnosis/idempotencia. Scope `diagnosis_create`, SHA-256 de bytes originales, ASCII imprimible 1..128, retención desde primera aceptación. `now >= expires_at` permite nueva generación sin borrar el diagnóstico anterior. Tombstone antes de comparar hash devuelve `IDEMPOTENCY_RESOURCE_DELETED` durante retención. Serializar el namespace con bloqueo advisory PostgreSQL no bloqueante por hash estable de propietario/scope/clave; nunca usar `hash()` de Python. Colisión solo provoca conflicto reintentable. Contención devuelve 409 `IDEMPOTENCY_IN_PROGRESS`. El bloqueo se mantiene hasta finalizar la transacción; índices UNIQUE siguen siendo defensa adicional. Se descarta Redis como autoridad de idempotencia.

S3 no participa en el commit SQL. Protocolo:

1. Tras validar y obtener el bloqueo de namespace, consultar replay/expiración antes de subir nada.
2. Para una carga nueva, crear una intención durable `image_upload_intents` con UUID de diagnóstico, object_key y fecha, en transacción separada, sin guardar bytes ni credenciales. No es un diagnóstico aceptado.
3. La transacción de creación bloquea la fila de intención antes de invocar S3; si ya no existe, aborta sin subir. Mantener ese bloqueo durante put y commit; timeouts acotados evitan espera indefinida.
4. Tras put confirmado, insertar diagnosis y crear/reemplazar idempotencia, y eliminar la intención en el mismo commit. Solo entonces devolver 202.
5. Ante fallo, rollback conserva la intención durable. Intentar compensación después de comprobar bajo bloqueo que no existe diagnóstico referenciando el objeto. Si el commit fue incierto o PostgreSQL está inaccesible, no borrar a ciegas: devolver error controlado y reconciliar cuando vuelva la base.
6. Un comando de mantenimiento reintenta intenciones mediante `FOR UPDATE SKIP LOCKED`. Revalida ausencia de referencia; elimina el objeto (ausente cuenta como éxito) y luego la intención. Si hay diagnóstico referenciado, conserva el objeto y retira solo la intención. Si falla delete/DB, deja evidencia durable para reintentar. Caída después de delete y antes del commit es segura por delete idempotente. El mismo bloqueo de intención impide limpiar una subida activa; una petición cuya intención fue limpiada debe abortar antes de put.

La intención evita depender de memoria para compensación; no se promete ausencia instantánea de huérfanos tras una caída. Probar interrupción tras put, commit incierto, fallo de compensación, carrera con limpiador y repetición de limpieza. El comando opera solo sobre intenciones conocidas, nunca sobre objetos de diagnósticos borrados lógicamente. Documentar su ejecución y monitorización local; producción no queda operada por esta especificación.

### 5. Estado, propiedad y cursores

UPDATE condicional cancela solo PENDIENTE no borrado; terminales, incluido CANCELADO, devuelven 409. DELETE propio conserva tombstone y devuelve siempre 204; ajeno/nunca existente 404. GET detalle/imagen, cancel y feedback sobre borrado devuelven 404. El borrado no cancela trabajo ni revierte terminal.

Historial por `(created_at DESC,id DESC)`, limit 1..100/default 20, exclusión de borrados y owner obligatorio. Cursor Base64URL con payload versionado y MAC HMAC-SHA256 sobre bytes canónicos: versión, propósito de endpoint, principal solicitante, created_at e id. Validar MAC, tipos, versión y principal/propósito antes de consultar; inválido, alterado o ajeno produce el mismo 400 `INVALID_PAGINATION`. No necesita que la fila ancla siga visible: permite paginar aunque haya sido borrada. Se descarta Base64 sin autenticación porque no acredita pertenencia. Rotar secreto invalida cursores, que se reinician desde primera página.

GET admin/diagnoses incluye únicamente id, owner_id, status, created_at, updated_at y reason_code cuando corresponda; excluye borrados, object_key, imágenes, feedback y datos de Identity. Sin filtros adicionales en esta versión. Mismos límites y orden, propósito de cursor distinto y ligado al administrador. Auditar lectura de supervisión con actor/correlación/fecha, sin volcar resultados.

### 6. Catálogo candidato, aprobación y versiones

`crops` con códigos POTATO y MAIZE. `problems` representa condiciones candidatas con tipo HEALTHY o DISEASE, no plagas. Semillas exactas de los contratos: POTATO_HEALTHY, POTATO_EARLY_BLIGHT, POTATO_LATE_BLIGHT, MAIZE_HEALTHY, MAIZE_COMMON_RUST, MAIZE_LEAF_BLIGHT, MAIZE_GRAY_LEAF_SPOT. Estado activo es visibilidad administrativa; `model_supported=false` para todas inicialmente y no editable por estas APIs. No introducir nuevas clases/cultivos por CRUD fuera de esa taxonomía V1; POST permite registrar códigos permitidos aún ausentes, duplicados 409. Cambiar taxonomía o validar el modelo pertenece a otro cambio.

Migrar identidad/códigos/nombres de cultivos y condiciones, sin inventar nombres científicos de patógenos o textos de tratamiento. No incluir recomendaciones agronómicas en seeds salvo paquete con fuentes y evidencia de aprobación comprobables. Arranque sin ese paquete es válido y devuelve recomendaciones vacías; disponibilidad de contenido agronómico aprobado se declara pendiente. Pruebas usan textos inequívocamente sintéticos en bases aisladas, nunca semillas productivas.

Una recomendación es una versión UUID inmutable, con problem_code, version entero incremental, title, summary, cultural_practices, biological_control, preventive_measures, source_refs, review_reference, reviewed_by, reviewed_at y active. POST requiere contenido, referencias y evidencia de revisión declarada por ADMIN; backend registra además al actor y fecha de alta y valida forma/presencia, sin afirmar validación científica automática. No acepta dosis o tratamientos específicos en el paquete inicial. La revisión de fuentes es humana y previa a publicación.

POST para un problema existente bloquea su fila, calcula MAX(version)+1 y crea una versión nueva, UNIQUE(problem_code,version). El contenido, problema y número de versión no se pueden modificar con PATCH; PATCH solo active. Consulta pública devuelve la versión aprobada activa de mayor número, respetando estado activo del cultivo/problema. Desactivar no borra versiones; snapshot de diagnósticos existentes no cambia. Diagnóstico conserva FK a versión y snapshot del contenido publicado al completarse en Incremento 3; probar aquí la estructura e inmutabilidad con fixture terminal. No implementar transición de resultados para facilitar la prueba.

Auditoría en tabla propia `diagnosis_audit_logs`, solo inserción, con actor, acción, destino, correlation_id y UTC, sin textos de feedback ni secretos. Mutaciones de catálogo y auditoría en la misma transacción. No reutilizar ni consultar auditoría de Identity.

### 7. Feedback

POST propio no borrado, únicamente COMPLETADO o NO_CONCLUYENTE; otros estados 409 `FEEDBACK_NOT_ALLOWED`. Cuerpo cerrado `{useful: boolean, comment?: string}` con booleano estricto, máximo 1000 caracteres; omisión elimina comentario previo. Un registro UNIQUE(diagnosis_id), owner derivado del diagnóstico. Primer envío 201, posteriores reemplazan útil/comentario y devuelven 200; serializar sobre diagnosis para evitar duplicados y competir correctamente con DELETE. Respuesta cerrada `{diagnosis_id,useful,comment,created_at,updated_at}` con comment null si omitido. Nunca alimenta entrenamiento ni emite eventos ML. Fixtures terminales aislados permiten probarlo antes de tener worker.

### 8. Integración y frontera con incremento 3

Nginx define upstream diagnosis_backend y rutas para diagnoses, crops, problems, admin/crops, admin/problems, admin/recommendations y admin/diagnoses, con límites de path que eviten capturar nombres parecidos. Conservar admin/users en Identity y bloquear internal/health. Propagar Authorization y correlación, aplicar no-store a respuestas de API y comprobar flujo real por proxy además de nginx -t.

No emitir eventos en Incremento 2. Antes de admitir procesamiento en Incremento 3, diagnosis y outbox deben confirmarse juntos; la transición de datos pendientes previos requiere migración/backfill idempotente de DiagnosisRequested, excluyendo cancelados/borrados según política que ese cambio fije. No afirmar entrega garantizada para solicitudes de este incremento. Las rutas internas existentes siguen contract-only.

## Risks / Trade-offs

- Transacciones abiertas durante S3: timeouts y bloqueo por intención/namespace acotados; medir antes de producción, no inventar latencias.
- Recuperación eventual de cargas: comando durable obligatorio y pruebas de caídas; no confundirlo con retención física de fotos aceptadas.
- Catálogo sin aprobación disponible: arrancar con taxonomía candidata y recomendaciones vacías; declarar pendiente contenido revisado.
- Tokens stateless: una cuenta bloqueada puede mantener acceso en Diagnosis hasta expirar el access token; conservar política ADR-0004 y explicarla en seguridad.
- Catálogo pequeño: GET sin paginación es suficiente para taxonomía V1 fija; ampliar alcance exige revisar contratos.

## Migration Plan

1. Registrar ADR de Diagnosis (usar siguiente número libre), formalizar contratos y matrices antes de consumidores.
2. Añadir dependencias, configuración y migraciones en base diagnosis: dominio, intenciones, auditoría, restricciones y seeds candidatos. Probar upgrade desde 0001 y arranque limpio; downgrade solo en DB desechable.
3. Implementar por tareas con pruebas al terminar cada grupo; actualizar documentación operacional junto al cambio pertinente.
4. Integrar proxy/Compose y aceptación aislada. Promover únicamente operaciones verificadas; conservar pendientes internos/ML/contenido aprobado que no exista.
5. Registrar evidencia, actualizar estado real, sincronizar tres deltas y archivar solo con tareas cumplidas. Si una migración con datos reales requiere reversión, preservar copia y aplicar corrección hacia adelante, sin downgrade destructivo automático.
