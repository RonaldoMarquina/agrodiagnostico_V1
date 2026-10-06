# Evidencia y Auditoría — Incremento 2: Diagnósticos, Catálogo y Almacenamiento Privado

Este documento registra la verificación incremental, comandos reproducibles, evidencias de ejecución y límites normativos para el Incremento 2 de AgroDiagnóstico V1.

---

## 1. Decisiones y Contratos Completos (Grupo 1)

- **ADR-0006**: Registrado en `docs/adr/0006-diagnosticos-catalogo-y-almacenamiento-privado.md` cubriendo propiedad, ciclo de vida, idempotencia con retención de 24h, recuperación de cargas mediante intención durable, almacenamiento privado en S3 sin URLs públicas, paginación keyset con HMAC y catálogo candidate-first.
- **Contratos OpenAPI y Esquemas**: Formalizados en `contracts/openapi/diagnosis.openapi.json` con esquemas cerrados, headers `Cache-Control: private, no-store` y `X-Correlation-ID`, ejemplos positivos y negativos.
- **Inventarios y Matrices**: Actualizados `contracts/operations.json`, `contracts/security-matrix.json`, `contracts/http-scenarios.json` y `contracts/deferred-operations.json`.
- **Verificación**: `bash scripts/check_contracts.sh` -> 11 pruebas de contrato PASSED (608 ejemplos embebidos, 4 OpenAPI, 46 operaciones).

---

## 2. Dependencias, Configuración y Autorización (Grupo 2)

- **Dependencias**: Pillow 12.3.0, python-multipart 0.0.32, PyJWT 2.15.1 y Cryptography bloqueadas en `services/diagnosis/pyproject.toml` y `uv.lock`. Sin librerías de inferencia.
- **Claves y Verificación Asimétrica**: Diagnosis recibe exclusivamente la clave pública Ed25519 (`JWT_PUBLIC_KEY_PATH`). No recibe la clave privada ni realiza consultas cruzadas a Identity. Configuración de clave para cursores HMAC en `CURSOR_SIGNING_KEY_FILE`.
- **Autenticación y RBAC**:
  - Middleware de correlación y headers de seguridad `Cache-Control: private, no-store`.
  - Sobre común de errores contractuales `{code, message, correlation_id, details?}`.
  - Verificación local Ed25519 con claims obligatorios (`sub`, `role`, `iss`, `aud`, `iat`, `exp`, `jti`).
  - Fallo cerrado (401 sin token/inválido/expirado, 403 USER en rutas ADMIN, 400 correlación no-UUID).
- **Verificación**: `test_auth_and_envelope.py` y `test_tokens.py` (26 pruebas pasadas).

---

## 3. Persistencia y Catálogo Candidato (Grupo 3)

- **Modelos de Dominio**: `Crop`, `Problem`, `Recommendation`, `Diagnosis`, `IdempotencyKey`, `ImageUploadIntent`, `DiagnosisFeedback`, `DiagnosisAuditLog` en `services/diagnosis/app/domain/models.py`.
- **Migración Alembic**: `0002_diagnosis_domain.py` crea las 8 tablas, restricciones CHECK, claves foráneas e índices keyset.
- **Semillas Candidatas**: Inserta `POTATO` y `MAIZE` con las siete condiciones candidatas (`POTATO_HEALTHY`, `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT`, `MAIZE_HEALTHY`, `MAIZE_COMMON_RUST`, `MAIZE_LEAF_BLIGHT`, `MAIZE_GRAY_LEAF_SPOT`) con `model_supported=false`.
- **Invariante Normativo**: Catálogo arranca sin recomendaciones (`items: []`), siendo un arranque técnicamente válido. Ninguna condición candidata activa equivale a clase validada por el modelo.
- **Verificación**: `test_persistence_models.py` (5 pruebas) y `python3 scripts/check_persistence.py` sobre PostgreSQL desechable (upgrade/downgrade/upgrade, restricted role, sin cross-service access).

---

## 4. Ingesta, S3 e Idempotencia (Grupo 4)

- **Parser/Validador de Imagen (`app/domain/image.py`)**:
  - Exactamente un archivo en campo multipart `image`; rechazo de campos adicionales o multipart inesperado con `400 INVALID_REQUEST`.
  - Tamaño real máximo: 10 MiB (10,485,760 bytes). Conteo incremental durante streaming; rechazo de exceso con `413 IMAGE_TOO_LARGE`.
  - Límite de transporte: 11 MiB (11,534,336 bytes).
  - Detección de tipos por número mágico (JPEG `\xff\xd8\xff`, PNG `\x89PNG`, WebP `RIFF..WEBP`).
  - Rechazo de HEIC/HEIF (`ftypheic`, etc.) y formatos no admitidos (GIF, BMP, TIFF, ejecutables) con `415 UNSUPPORTED_MEDIA_TYPE`.
  - Decodificación completa de píxeles con Pillow `load()` y `verify()`.
  - Límite de 24 MP (24,000,000 píxeles). Exceso o avisos de descompresión disparan `413 IMAGE_TOO_LARGE`.
  - Imágenes multifotograma o animadas rechazadas con `400 INVALID_IMAGE`.
  - Corrupción tras cabecera válida rechazada con `400 INVALID_IMAGE`.
  - Limpieza automática de temporales (spool acotado cerrado en bloque `finally`).

- **Adaptador S3 (`app/storage.py`)**:
  - Métodos `put_object`, `get_object`, `delete_object`, `object_exists`.
  - Configuración externa (`S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, `S3_CREDENTIALS_FILE`).
  - Clave generada por servidor: `diagnoses/{uuid}/original.{ext}`.
  - Timeouts y reintentos acotados (connect=3s, read=10s, retries=2).
  - Fallos de conexión o S3 encapsulados en `StorageUnavailableError` (mapeado a `503 STORAGE_UNAVAILABLE`).
  - Eliminación idempotente en S3 (ausencia cuenta como éxito).
  - Sin exposición de credenciales, trazas ni URLs públicas.

- **Idempotencia con Bloqueo Advisory PostgreSQL (`app/application/diagnoses.py`)**:
  - Serialización no bloqueante mediante `SELECT pg_try_advisory_xact_lock(:lock_id)` derivado de SHA-256 de `(owner_id, "diagnosis_create", key)`. Contención concurrente devuelve `409 IDEMPOTENCY_IN_PROGRESS`.
  - Fingerprint SHA-256 de los bytes exactos de la imagen.
  - Retención fija no deslizante de 24 horas (86,400 segundos).
  - Replay idéntico durante retención devuelve `202 Accepted` con ID, fecha original y estado actual sin duplicar filas ni subidas S3.
  - Replay con contenido distinto devuelve `409 IDEMPOTENCY_CONFLICT`.
  - Replay de diagnóstico borrado lógicamente (`deleted_at IS NOT NULL`) devuelve `409 IDEMPOTENCY_RESOURCE_DELETED` sin resucitar.
  - Expiración (`now >= expires_at`) permite generar un nuevo diagnóstico atómico conservando el anterior.
  - Separación A/B: claves idénticas entre usuarios distintos son totalmente independientes.

- **Intención Durable y Protocolo de Recuperación (`app/application/diagnoses.py` y `reconcile.py`)**:
  - Creación previa de `ImageUploadIntent(diagnosis_id, object_key, owner_id)` confirmada en PostgreSQL antes de invocar S3.
  - La transacción principal bloquea la intención con `FOR UPDATE` durante la subida y commit.
  - Si S3 o commit falla: rollback conserva la intención durable; compensación verifica ausencia de diagnóstico antes de intentar delete.
  - Comando de reconciliación `reconcile_upload_intents` (ejecutable vía `python -m app.application.reconcile`):
    - Selecciona intenciones con `FOR UPDATE SKIP LOCKED` (omite subidas activas).
    - Si existe diagnóstico referenciando el objeto: conserva el objeto en S3 y retira la intención.
    - Si no existe diagnóstico: elimina el objeto en S3 y borra la intención.
    - Si la eliminación en S3 falla: la intención permanece en PostgreSQL para reintento.

- **Entrega Privada al Propietario (`GET /api/v1/diagnoses/{id}/image`)**:
  - Exige Bearer token.
  - Verificación estricta de propiedad: si el diagnóstico es ajeno, inexistente o tiene tombstone (`deleted_at`), responde `404 NOT_FOUND` genérico.
  - Usuario ADMIN en esta ruta de usuario recibe `404 NOT_FOUND` si la foto no es propia.
  - Devuelve bytes originales con `Content-Type` real y `Cache-Control: private, no-store`.

- **Verificación**:
  - `test_ingestion_and_storage.py` (26 pruebas unitarias e integración de API).
  - `check_persistence.py` en PostgreSQL desechable (pruebas de concurrencia advisory lock, contención, separación A/B, replay y expiración).
  - `check_service_locks.sh` (106 pruebas unificadas: 47 Identity + 59 Diagnosis).
  - `check_contracts.sh` (11 pruebas de contrato).

---

## Grupo 5: Ciclo de vida, historial y supervisión (Tareas 5.1 a 5.5)

- **Cancelación Atómica (`POST /api/v1/diagnoses/{id}/cancel`)**:
  - `UPDATE condicional` sobre filas con `status = 'PENDIENTE'`, `owner_id = principal.id` y `deleted_at IS NULL`.
  - Éxito devuelve `200 OK` con payload contractual `DiagnosisCancelled` (`id`, `status: CANCELADO`, `created_at`, `updated_at` en UTC con sufijo `Z`).
  - Carrera de concurrencia: si dos peticiones compiten por cancelar el mismo diagnóstico, una sola actualiza la fila (200) y la otra recibe `409 DIAGNOSIS_NOT_CANCELABLE`.
  - Estados no cancelables (`PROCESANDO`, `COMPLETADO`, `NO_CONCLUYENTE`, `FALLIDO`, `CANCELADO`) responden `409 DIAGNOSIS_NOT_CANCELABLE` y preservan su estado original.
  - Diagnóstico ajeno, inexistente o con borrado lógico (`deleted_at IS NOT NULL`) responde `404 NOT_FOUND` genérico.
  - Llamadas con rol `ADMIN` sobre recursos ajenos en esta ruta de usuario reciben `404 NOT_FOUND`.
  - Nunca emite evento `DiagnosisFinished`.

- **Borrado Lógico y Detalle Contractual (`DELETE /api/v1/diagnoses/{id}`, `GET /api/v1/diagnoses/{id}`)**:
  - `DELETE` propio es idempotente: fija `deleted_at = now()` y responde `204 No Content` tanto en el primer borrado como en llamadas repetidas sobre el tombstone.
  - `DELETE` conserva el estado original (`status`) y no elimina el objeto físico en S3.
  - Diagnóstico ajeno o inexistente en `DELETE` responde `404 NOT_FOUND` genérico.
  - Ocultación de tombstones: diagnósticos con `deleted_at IS NOT NULL` devuelven `404 NOT_FOUND` en detalle (`GET /{id}`), imagen (`GET /{id}/image`), cancelación (`POST /{id}/cancel`) y feedback.
  - `GET /api/v1/diagnoses/{id}` responde `200 OK` con `DiagnosisDetail` según las variantes contractuales:
    - `PENDIENTE`, `PROCESANDO`, `CANCELADO`: `{id, status, created_at, updated_at}`.
    - `NO_CONCLUYENTE`, `FALLIDO`: añade `reason_code` contractual.
    - `COMPLETADO`: añade `result` con `crop_code`, `class_code`, `raw_score`, modelo y recomendación.
    - Ajeno, inexistente o borrado lógico devuelve `404 NOT_FOUND` genérico (también para ADMIN en ruta de usuario).

- **Historial Keyset y Cursores HMAC (`GET /api/v1/diagnoses`)**:
  - Filtra por `owner_id == principal.id` y `deleted_at IS NULL`.
  - Orden estricto determinista: `created_at DESC, id DESC`.
  - Límite contractual `limit`: 1..100 (por defecto 20). Valores fuera de rango responden `400 INVALID_PAGINATION`.
  - Cursores Base64URL con HMAC-SHA256 (`app/infrastructure/cursor.py`):
    - Payload versionado `{"v": 1, "purp": "user_diagnoses", "sub": principal_id, "created_at": iso_z, "id": diag_id}` firmado con `CURSOR_SIGNING_KEY_FILE` o variable `CURSOR_SIGNING_KEY`.
    - Falla cerrado con `400 INVALID_PAGINATION` ante cursor manipulado, alterado, de otro usuario, de otro endpoint (`purp` mismatch), malformado o clave de firma rotada.
    - Paginación estable: navegación sin duplicados con fechas empatadas (`created_at` idéntico desempata por `id DESC`).
    - Soporte de ancla borrada: si el diagnóstico que sirvió de ancla para el cursor es borrado lógicamente antes de pedir la siguiente página, la consulta keyset continúa sin fallar y no incluye el recurso eliminado.

- **Supervisión Administrativa Auditada (`GET /api/v1/admin/diagnoses`)**:
  - Exige rol `ADMIN` (usuario con rol `USER` recibe `403 FORBIDDEN`, anónimo recibe `401 UNAUTHORIZED`).
  - Lista diagnósticos no borrados con metadatos mínimos: `id`, `owner_id`, `status`, `created_at`, `updated_at`, `reason_code` (opcional).
  - No filtra ni incluye `object_key`, bytes de imagen, `feedback` ni datos de Identity.
  - Keyset pagination independiente con propósito `admin_supervision`.
  - Auditoría de acceso: cada consulta exitosa registra una fila en `diagnosis_audit_logs` con `actor_id = admin.id`, `action = 'ADMIN_LIST_DIAGNOSES'`, `target_type = 'diagnosis'`, `correlation_id` y timestamp UTC.
  - Aislamiento de imágenes: un usuario `ADMIN` en `GET /api/v1/diagnoses/{id}/image` recibe `404 NOT_FOUND` si la foto pertenece a otro usuario.

- **Verificación**:
  - `test_lifecycle_and_history.py` (23 pruebas unitarias e integración de API).
  - Suite completa de Diagnosis: 82 pruebas pasando en < 1 segundo.
  - `check_service_locks.sh` (129 pruebas pasando: 47 Identity + 82 Diagnosis + AI + Notification).
  - `check_contracts.sh` (11 pruebas de contrato con 608 ejemplos embebidos validados).

---

## Grupo 6: Catálogo revisado y versiones (Tareas 6.1 a 6.4)

- **Consultas Públicas Autenticadas (`GET /api/v1/crops`, `GET /api/v1/crops/{code}/problems`, `GET /api/v1/problems/{code}/recommendations`)**:
  - Exigen autenticación (anónimo recibe `401 UNAUTHORIZED`).
  - Devuelven únicamente entidades con `active = true`.
  - En recomendaciones públicas: solo expone la versión aprobada activa más reciente (`is_active = true` con `MAX(version)`).
  - Arranque limpio: lista vacía `{ "items": [] }` para recomendaciones sobre problemas recién sembrados, sin inventar datos sintéticos.
  - Validación jerárquica: si el cultivo padre o problema padre no existe o está inactivo (`active = false`), responde `404 NOT_FOUND` genérico.
  - Taxonomía exacta V1: `POTATO` y `MAIZE` con sus 7 condiciones candidatas (`POTATO_HEALTHY`, `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT`, `MAIZE_HEALTHY`, `MAIZE_COMMON_RUST`, `MAIZE_LEAF_BLIGHT`, `MAIZE_GRAY_LEAF_SPOT`), todas con `model_supported = false`.

- **Gestión Administrativa de Cultivos y Problemas (`/api/v1/admin/crops`, `/api/v1/admin/problems`)**:
  - Exige rol `ADMIN` (usuario `USER` recibe `403 FORBIDDEN`, anónimo `401 UNAUTHORIZED`).
  - Restricción taxonómica estricta: intento de dar de alta cultivos o problemas fuera del conjunto V1 responde `400 INVALID_REQUEST`.
  - Duplicados en `POST`: responde `409 CATALOG_CONFLICT`.
  - Campos inmutables en `PATCH`: campos estructurales (`code`, `crop_code`, `problem_type`, `model_supported`) son inmutables; intentar mutarlos responde `400 INVALID_REQUEST`.
  - Campos mutables permitidos: `name`, `scientific_name`, `active`.
  - Auditoría transaccional: cada mutación (`POST`/`PATCH`) registra un evento en `diagnosis_audit_logs` en la misma transacción atómica; si el log de auditoría falla, la mutación completa hace rollback.

- **Gestión Administrativa de Recomendaciones (`/api/v1/admin/recommendations`, `PATCH /api/v1/admin/recommendations/{id}`)**:
  - Evidencia obligatoria de revisión agronómica: `POST` exige `source_refs` (lista no vacía), `review_reference`, `reviewed_by` y `reviewed_at`. La ausencia o vacuidad de cualquiera de estos responde `400 CATALOG_REVIEW_REQUIRED`.
  - Versionado secuencial atómico: se calcula `version = MAX(version) + 1` bajo bloqueo de fila del problema padre (`FOR UPDATE`), previniendo versiones duplicadas o carreras concurrentes.
  - Inmutabilidad estricta de contenido: `PATCH` solo admite modificar el atributo `active`. Cualquier intento de alterar texto, fuentes o referencias de revisión responde `400 INVALID_REQUEST`.
  - Auditoría transaccional en la misma unidad de trabajo de base de datos.

- **Preservación de Snapshots Históricos (Tarea 6.4)**:
  - Verificado mediante fixture de diagnóstico en estado `COMPLETADO` que vincula una recomendación aprobada (`recommendation_id`, `catalog_version`, `recommendation_text`).
  - Se probó la creación de versiones incrementales posteriores, la desactivación de la recomendación, la desactivación del problema padre y la desactivación del cultivo: en todos los casos, la clave foránea, el número de versión y el texto íntegro del snapshot se mantienen idénticos e inalterables en la respuesta `GET /api/v1/diagnoses/{id}`.
  - Registro de estado agronómico: el catálogo inicia sin paquete de recomendaciones revisadas formalmente; este pendiente queda documentado en `docs/API_CONTRACTS.md` y `tasks.md` sin bloquear el ciclo técnico.

- **Verificación**:
  - `test_catalog_and_versions.py` (13 pruebas unitarias y de integración cubriendo tareas 6.1 a 6.4).
  - Suite completa de Diagnosis: 95 pruebas pasando en 0.8s.
  - `check_service_locks.sh` (142 pruebas unificadas: 47 Identity + 95 Diagnosis + AI + Notification).
  - `check_contracts.sh` (11 pruebas de contrato con 608 ejemplos embebidos validados).

---

## Grupo 7: Feedback propio (Tareas 7.1 y 7.2)

- **Registro y Reemplazo de Feedback (`POST /api/v1/diagnoses/{id}/feedback`)**:
  - `UNIQUE(diagnosis_id)` en modelo `DiagnosisFeedback`.
  - Primera valoración exitosa responde `201 Created` con payload `DiagnosisFeedback`: `{ diagnosis_id, useful, comment, created_at, updated_at }` (timestamps ISO 8601 UTC terminados en `Z`).
  - Cabeceras de respuesta: `Cache-Control: private, no-store` y `X-Correlation-ID`.
  - Actualización/reemplazo: envíos posteriores para el mismo diagnóstico responden `200 OK`, actualizan `useful` y `comment`, renuevan `updated_at` y preservan inalterado `created_at`.
  - Omisión de comentario: enviar payload sin `comment` o con `comment: null` en una actualización elimina el comentario previo, quedando `null` tanto en la base de datos como en la respuesta JSON.
  - Validación de esquema estricta: `useful` exige booleano estricto (`StrictBool`); strings (`"true"`, `"false"`), enteros (`1`, `0`) o ausencia del campo responden `400 INVALID_REQUEST`.
  - Campos desconocidos/extra en el cuerpo JSON son rechazados con `400 INVALID_REQUEST` (`extra="forbid"`).
  - Límite de longitud: comentarios de hasta 1000 caracteres son aceptados; comentarios de 1001 o más caracteres responden `400 INVALID_REQUEST`.
  - Formato de identificador: parámetro de ruta `{id}` que no sea UUID válido responde `400 INVALID_REQUEST`.
  - Manejo de concurrencia: bloqueos a nivel de fila (`FOR UPDATE`) sobre `diagnoses` y `diagnosis_feedback` serializan solicitudes concurrentes sin generar duplicados.

- **Aplicación de Estados Permitidos y Aislamiento de Seguridad**:
  - Estados terminales permitidos: `COMPLETADO` y `NO_CONCLUYENTE` permiten valorar el diagnóstico (201/200).
  - Estados no permitidos: `PENDIENTE`, `PROCESANDO`, `CANCELADO` y `FALLIDO` responden `409 FEEDBACK_NOT_ALLOWED`.
  - Aislamiento de recursos y tombstones: diagnósticos inexistentes, pertenecientes a otro usuario o con borrado lógico (`deleted_at IS NOT NULL`) responden `404 RESOURCE_NOT_FOUND` genérico sin revelar el estado o contenido del recurso.
  - Rol ADMIN: llamadas de administradores sobre recursos ajenos en esta ruta de usuario reciben `404 RESOURCE_NOT_FOUND`. Si el diagnóstico pertenece al propio administrador, se permite registrar o actualizar el feedback normalmente.
  - Autenticación: solicitudes anónimas sin Bearer token responden `401 UNAUTHORIZED`.
  - Serialización con DELETE: la eliminación lógica del diagnóstico (`DELETE /api/v1/diagnoses/{id}`) hace que cualquier intento posterior de registrar feedback reciba `404 RESOURCE_NOT_FOUND`.
  - Separación estricta de ML y eventos: el registro de feedback no emite eventos al broker ni registros de auditoría de diagnóstico, y está completamente desvinculado de pipelines automáticos de re-entrenamiento del modelo.

- **Verificación**:
  - `test_feedback.py` (18 pruebas unitarias y de integración de API cubriendo tareas 7.1 y 7.2).
  - Suite completa de Diagnosis: 113 pruebas pasando en 1.0s.
  - `check_health.py` pasando con ruta `/api/v1/diagnoses/{id}/feedback` integrada.
  - `check_contracts.sh` (11 pruebas de contrato con 608 ejemplos validados).

---

## Grupo 8: Integración de proxy y aceptación integral (Tareas 8.1 a 8.3)

- **Configuración Nginx y Aislamiento de Rutas (Tarea 8.1)**:
  - Upstream `diagnosis_backend` (`server diagnosis:8000;`) y `identity_backend` (`server identity:8000;`).
  - Límite de transporte `client_max_body_size 11m;` exclusivo para la ruta de subida `POST /api/v1/diagnoses`.
  - Rutas de Diagnóstico enrutadas a `diagnosis_backend`:
    `/api/v1/diagnoses`, `/api/v1/diagnoses/`, `/api/v1/crops`, `/api/v1/crops/`, `/api/v1/problems/`,
    `/api/v1/admin/crops`, `/api/v1/admin/crops/`, `/api/v1/admin/problems`, `/api/v1/admin/problems/`,
    `/api/v1/admin/recommendations`, `/api/v1/admin/recommendations/`, `/api/v1/admin/diagnoses`, `/api/v1/admin/diagnoses/`.
  - Preservación estricta de rutas de Identity: `/api/v1/auth/`, `/api/v1/profile`, `/api/v1/admin/users`, `/api/v1/admin/users/`.
  - Bloqueo estricto de rutas internas y de monitoreo: `/internal`, `/health`, `/ai` devuelven `404 Not Found`.
  - Aislamiento de prefijos: rutas que comienzan de forma similar pero no corresponden exactamente (`/api/v1/diagnoses_extra`, `/api/v1/crops_invalid`, `/api/v1/admin/invalid`) no son capturadas y reciben `404 NOT_IMPLEMENTED`.
  - Cabeceras de correlación y seguridad: propagación o generación de `X-Correlation-ID` y adición de cabeceras de seguridad privadas (`Cache-Control: private, no-store`).
  - Verificación aislada: `python3 scripts/check_proxy_routes.py` (7/7 suites pasando, payload exacto de 10 MiB permitido, >11 MiB rechazado con 413).

- **Aceptación Integral Aislada (Tarea 8.2)**:
  - Script ejecutable y reproducible: `python3 scripts/check_acceptance_incremento2.py`.
  - Entorno efímero aislado con PostgreSQL (`postgres:16-alpine`), SeaweedFS S3 (`chrislusf/seaweedfs:4.17`), Identity (`agrodiagnostico-v1-identity:latest`), Diagnosis (`agrodiagnostico-v1-diagnosis:latest`) y Nginx (`nginx:1.28-alpine`).
  - Flujo verificado end-to-end a través de Nginx:
    1. Generación y verificación de tokens asimétricos Ed25519 (User A, User B, Admin).
    2. Subida de imagen JPEG real -> `202 Accepted` en estado `PENDIENTE`.
    3. Replay de idempotencia (mismo payload -> mismos ID y timestamp de creación; contenido alterado -> `409 IDEMPOTENCY_CONFLICT`).
    4. Aislamiento multi-inquilino A/B (User B recibe `404 NOT_FOUND` al consultar diagnóstico o imagen de User A).
    5. Recuperación privada de bytes de imagen S3 con verificación de checksum exacto.
    6. Paginación keyset con cursores HMAC-SHA256 (navegación fluida por páginas, rechazo con 400 ante cursor manipulado).
    7. Cancelación atómica (`200 OK` CANCELADO, segundo intento `409 CONFLICT`) y borrado lógico con tombstones (`204 No Content` idempotente, posterior acceso devuelve `404 NOT_FOUND`).
    8. Catálogo público y administrativo (mutación con revisión agronómica por admin, consultas públicas jerárquicas).
    9. Feedback con fixture terminal (simulación en DB de `COMPLETADO`, envío inicial 201, reemplazo atómico 200, rechazo 409 en PENDIENTE/CANCELADO).
    10. Reconciliador de intenciones durables y tolerancia a fallos:
        - Inyección de fallo en S3: upload devuelve 503 `STORAGE_UNAVAILABLE` sin crear diagnóstico huérfano.
        - Ejecución de `python -m app.application.reconcile`: limpia intenciones huérfanas y elimina archivos no referenciados en S3, preservando los archivos con diagnóstico asociado.
  - Verificación explícita de independencia: Cero dependencias en tiempo de ejecución de RabbitMQ, Redis, servicio de correo o worker de inferencia IA para el alcance del Incremento 2.

- **Promoción de Contratos y Verificación en CI (Tarea 8.3)**:
  - Promoción de las 20 operaciones de negocio de Diagnosis de `"contract-only"` a `"implemented"` en `contracts/operations.json` y `contracts/openapi/diagnosis.openapi.json`.
  - Operaciones de inferencia (`diagnosis_claim`, `diagnosis_renew`, `diagnosis_internal_image`) conservadas explícitamente como `"contract-only"` (Incremento 3).
  - Verificación de contratos: `scripts/validate_contracts.py` y `tests/contracts/test_contracts.py` (11/11 pruebas pasando, 608 ejemplos embebidos validados).
  - Verificación de backend y salud: `tests/backend/check_health.py` (3/3 pruebas pasando).
  - Verificación de locks y suites: `scripts/check_service_locks.sh` (160 pruebas pasando: 47 Identity + 113 Diagnosis).

---

## Grupo 9: Revisión y cierre del incremento (Tareas 9.1 y 9.2)

### Matriz de Trazabilidad: Requisito / Tarea / Prueba / Resultado

| Requisito / Capacidad | Tarea | Componente / Archivo | Prueba Ejecutada | Resultado |
|---|---|---|---|---|
| ADR y Contratos | 1.1–1.3 | `docs/adr/0006-*.md`, `contracts/` | `check_contracts.sh`, `validate_contracts.py` | PASS (11 pruebas, 608 ejemplos) |
| Dependencias y JWT Ed25519 | 2.1–2.4 | `services/diagnosis/pyproject.toml`, `app/infrastructure/` | `test_auth_and_envelope.py`, `test_tokens.py` | PASS (26 pruebas) |
| Persistencia y Semillas | 3.1–3.3 | `models.py`, `migrations/0002_*.py` | `test_persistence_models.py`, `check_persistence.py` | PASS (5 pruebas + migraciones DB) |
| Ingesta, S3, Idempotencia | 4.1–4.6 | `domain/image.py`, `storage.py`, `reconcile.py` | `test_ingestion_and_storage.py` | PASS (26 pruebas) |
| Ciclo de vida e Historial | 5.1–5.5 | `application/diagnoses.py`, `cursor.py` | `test_lifecycle_and_history.py` | PASS (23 pruebas) |
| Catálogo y Versiones | 6.1–6.4 | `application/catalog.py`, `api/admin_catalog.py` | `test_catalog_and_versions.py` | PASS (13 pruebas) |
| Feedback Propio | 7.1–7.2 | `application/diagnoses.py`, `api/diagnoses.py` | `test_feedback.py` | PASS (18 pruebas) |
| Integración de Proxy | 8.1 | `infra/nginx/default.conf` | `scripts/check_proxy_routes.py` | PASS (7 suites aisladas) |
| Aceptación Integral E2E | 8.2 | `scripts/check_acceptance_incremento2.py` | `check_acceptance_incremento2.py` | PASS (10 fases integradas) |
| CI y Promoción | 8.3 | `contracts/operations.json`, `validate_contracts.py` | `check_service_locks.sh`, `test_contracts.py` | PASS (160 unitarias + 11 contratos) |

### Comandos Reproducibles

1. **Validación de contratos y esquemas OpenAPI**:
   ```bash
   .venv-contracts/bin/python scripts/validate_contracts.py
   .venv-contracts/bin/python -m unittest discover -s tests/contracts
   ```
2. **Suite unitaria y de integración de Diagnosis (113 pruebas)**:
   ```bash
   PYTHONPATH=services/diagnosis .local/diagnosis_venv/bin/python -m unittest discover -s services/diagnosis/tests
   ```
3. **Verificación de rutas y proxy Nginx en contenedor**:
   ```bash
   python3 scripts/check_proxy_routes.py
   ```
4. **Aceptación integral del Incremento 2 en contenedores aislados**:
   ```bash
   python3 scripts/check_acceptance_incremento2.py
   ```
5. **Validación estricta de OpenSpec**:
   ```bash
   openspec validate incremento-2-diagnosticos-y-catalogo --strict
   openspec validate --all --strict
   ```

### Fallos Resueltos Durante la Implementación

1. **Resolución de Upstream en Nginx**: Nginx fallaba al iniciar si los hosts `identity:8000` y `diagnosis:8000` no resolvían en DNS. Resuelto configurando el entorno de prueba con red bridge Docker y alias correspondientes.
2. **Nombres de secretos de almacenamiento**: La configuración de SeaweedFS requería nombres consistentes entre montajes de archivos. Resuelto admitiendo tanto nombres planos (`s3_config`, `s3_admin`, `s3_diagnosis`) como extensiones `.json`.
3. **Validación de Claims JWT en Diagnosis**: El verificador de tokens exigía `jti` y `aud: agrodiagnostico-api`. El generador de tokens de prueba se ajustó para emitir claims exactos conforme a los contratos.
4. **Fallo cerrado con 503 ante caída de infraestructura**: La caída de S3 y PostgreSQL retornaba inicialmente 500. Se actualizaron los manejadores de excepciones en `services/diagnosis/app/main.py` para devolver `503 STORAGE_UNAVAILABLE` y `503 PERSISTENCE_UNAVAILABLE` respectivamente.
5. **Manejo de columnas en tablas de dominio**: Se ajustaron las consultas y comandos para respetar estrictamente las columnas `crop_code`, `class_code`, `raw_score` en `diagnoses`, y `owner_id` en `image_upload_intents`.

### Asuntos Pendientes Explícitos (Fuera del Alcance del Incremento 2)

1. **Contenido Agronómico Revisado**: El catálogo arranca técnicamente sin recomendaciones aprobadas (`items: []`). La carga y aprobación de recomendaciones con evidencia científica queda pendiente del proceso de revisión con el docente / agrónomo.
2. **Soporte de Formatos HEIC/HEIF**: Las imágenes HEIC/HEIF se rechazan limpiamente con `415 UNSUPPORTED_MEDIA_TYPE`. Su soporte requerirá una herramienta o conversor dedicado antes de habilitarse.
3. **Worker de Inferencia y Reclamo asíncrono**: Las operaciones de reclamo (`claim`), renovación de lease y eventos `DiagnosisRequested` pertenecen al Incremento 3. El estado actual de los diagnósticos recién creados es `PENDIENTE`.
4. **Métricas de Producción**: Las metas de rendimiento (p95 ≤ 500 ms en APIs síncronas, p95 ≤ 2s en registro) son objetivos de diseño; las mediciones formales bajo carga se realizarán en el Incremento 5.


