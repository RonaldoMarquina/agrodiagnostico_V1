# Diagnosis — AgroDiagnóstico V1

Estado: persistencia y API de salud técnica implementadas; funciones de negocio pendientes. La presencia de `app/`, `migrations/` o Dockerfile no demuestra implementación.

Responsabilidad prevista: solicitudes, estados, referencias de imágenes privadas, resultados visibles, historial, catálogo revisado, feedback y outbox/inbox. Decide si el análisis puede publicarse y obtiene recomendaciones del catálogo. NO_CONCLUYENTE es un estado, no una clase. No guarda bytes de fotos en PostgreSQL.

El grupo 3 aporta dependencias bloqueadas, contenedor de migración y revisión Alembic independiente. El grupo 4 aporta API de salud y contenedor de runtime. Las funciones de dominio corresponden al incremento 2–3; no están terminadas.

Referencias: [arquitectura](../../docs/ARCHITECTURE.md), [inventario de interfaces](../../docs/API_CONTRACTS.md), [ADR de persistencia](../../docs/adr/0001-incremento-0-base-tecnica.md) y [tareas del Incremento 0](../../openspec/changes/archive/2026-09-30-incremento-0-base-integrada/tasks.md). Los comandos de persistencia se describen debajo; el servidor HTTP técnico se inicia mediante Compose según DEVELOPMENT.


## Dependencias y migración base

Python 3.12 (`>=3.12,<3.13`), uv 0.12.20; dependencias directas y transitivas bloqueadas en `uv.lock`. Desde la raíz:

```bash
python3 -m venv tooling/.venv
tooling/.venv/bin/python -m pip install --require-hashes -r tooling/uv.requirements.txt
tooling/.venv/bin/uv sync --project services/diagnosis --locked --no-dev --no-install-project
```

Esto crea únicamente entornos locales, sin modificar Python global. `uv lock` es una actualización deliberada; para reproducir se usa `sync --locked`. Se comprobó instalación/imports en entorno nuevo para cada servicio.

Desde esta carpeta y con DB_HOST/DB_PASSWORD_FILE configurados (DB_PORT opcional,5432), usar el Python de `.venv`:

```bash
.venv/bin/python -m app.migrate upgrade head
.venv/bin/python -m app.migrate current
.venv/bin/python -m app.migrate ready
```

La base/rol están fijados al dueño del servicio. `ready` devuelve0 solo si la revisión en PostgreSQL coincide con el único head del historial; es un prerrequisito de readiness, no un endpoint HTTP ni salud completa. Nunca crea tablas para corregir un fallo. Error devuelve1 con mensaje seguro, sin DSN ni credenciales.

La revisión base (`diagnosis_0001`) crea solo los metadatos `alembic_version`. La revisión de dominio (`diagnosis_0002`) implementa las tablas del Incremento 2:
- `crops`: Cultivos autorizados (`POTATO`, `MAIZE`).
- `problems`: Condiciones candidatas iniciales (`POTATO_HEALTHY`, `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT`, `MAIZE_HEALTHY`, `MAIZE_COMMON_RUST`, `MAIZE_LEAF_BLIGHT`, `MAIZE_GRAY_LEAF_SPOT`) con `model_supported=false`.
- `recommendations`: Recomendaciones versionadas e inmutables con fuentes y revisión humana (inicialmente sin semillas).
- `diagnoses`: Ciclo de vida, metadatos de imagen privada (`object_key`), snapshot de recomendación y tombstone (`deleted_at`).
- `idempotency_keys`: Idempotencia `(owner_id, scope, key)` con fingerprint SHA-256 y retención de 24h.
- `image_upload_intents`: Intenciones durables para carga a S3 y reconciliación sin huérfanos.
- `diagnosis_feedback`: Feedback útil/comentario 1:1 por diagnóstico.
- `diagnosis_audit_logs`: Auditoría transaccional exclusiva del servicio Diagnosis.

**Invariantes normativos**:
1. Ninguna condición candidata activa equivale a clase validada por el modelo de IA; todas arrancan con `model_supported=false`.
2. Un catálogo sin recomendaciones es un arranque técnicamente válido (`items: []`). No se incorporan tratamientos ni dosis sin un paquete formal de fuentes y revisión humana aprobada.

Repetir upgrade es seguro. `downgrade base` exige revisión explícita y solo se ensaya sobre bases efímeras; elimina las tablas de dominio y la marca de revisión, no volúmenes. Para cambios futuros, añadir revisiones nuevas, no reescribir la base.

## Operaciones de Negocio, Ciclo de Vida e Historial (Incremento 2)

- `POST /api/v1/diagnoses`: Acepta imagen multipart `image`, aplica validación estricta (JPEG/PNG/WebP, máx 10 MiB, máx 24 MP, decodificación completa `load()`), serialización no bloqueante con `pg_try_advisory_xact_lock`, retención de 24h e intención durable antes de subir a S3. Responde `202 Accepted` tras commit atómico.
  - *Invariante de estados*: En este incremento las cargas aceptadas quedan en `PENDIENTE` sin worker activo de inferencia. La transición y procesamiento asíncrono corresponden al Incremento 3, requiriendo outbox transaccional y backfill para publicar `DiagnosisRequested`.
- `POST /api/v1/diagnoses/{id}/cancel`: Cancelación atómica mediante `UPDATE` condicional de `PENDIENTE` no borrado a `CANCELADO` (200). Cualquier otro estado (`PROCESANDO`, `COMPLETADO`, `NO_CONCLUYENTE`, `FALLIDO`, `CANCELADO`) devuelve 409 `DIAGNOSIS_NOT_CANCELABLE`. Diagnóstico ajeno, inexistente o con tombstone devuelve 404 genérico. No emite `DiagnosisFinished`.
- `DELETE /api/v1/diagnoses/{id}`: Borrado lógico idempotente (`204 No Content` para primer borrado y repeticiones propias). No cancela trabajo, no altera estados terminales ni elimina el objeto físico en S3. Los recursos borrados lógicamente (`deleted_at IS NOT NULL`) quedan ocultos (404) en detalle, imagen, cancelación y feedback.
- `GET /api/v1/diagnoses/{id}`: Detalle privado que respeta las variantes contractuales de estado (`PENDIENTE`, `PROCESANDO`, `CANCELADO`, `NO_CONCLUYENTE`, `FALLIDO`, `COMPLETADO`). Acceso ajeno, inexistente o borrado responde 404 genérico.
- `GET /api/v1/diagnoses`: Historial paginado propio en orden `(created_at DESC, id DESC)`, excluyendo borrados lógicos. Utiliza cursores Base64URL protegidos con HMAC-SHA256 (`CURSOR_SIGNING_KEY_FILE`), ligados al solicitante y al endpoint. Cursores inválidos, alterados, ajenos o con clave rotada devuelven 400 `INVALID_PAGINATION`. Soporta ancla borrada lógicamente sin revelar el recurso eliminado.
- `GET /api/v1/admin/diagnoses`: Supervisión paginada exclusiva para rol `ADMIN` (USER 403, anónimo 401). Retorna metadatos mínimos sin imágenes ni datos personales de Identity, y audita la consulta en `diagnosis_audit_logs`.
- `GET /api/v1/diagnoses/{id}/image`: Entrega los bytes privados originales al propietario autenticado con `Content-Type` real y `Cache-Control: private, no-store`. Acceso ajeno, inexistente o con tombstone devuelve `404 NOT_FOUND` genérico (incluso con rol ADMIN).
- Reconciliación de intenciones: `python -m app.application.reconcile` limpia subidas huérfanas mediante `FOR UPDATE SKIP LOCKED` e invoca eliminación idempotente en S3.

[Operación con Docker, secretos y aceptación](../../docs/PERSISTENCE.md).


