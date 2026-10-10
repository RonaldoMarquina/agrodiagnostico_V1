# Persistencia local — Incremento 0, grupo 3

Este documento describe la capa de persistencia del grupo3. El Compose actual añade APIs técnicas e infraestructura del grupo4: véase [DEVELOPMENT](DEVELOPMENT.md). schema_ready() ya se usa en readiness HTTP; Diagnosis comprueba también S3. Las rutas de negocio continúan contract-only.

## Versiones y propiedad

Python3.12, uv0.12.20, FastAPI0.141.1, SQLAlchemy2.1.1, Alembic1.20.0 y psycopg3.3.6. Cada servicio tiene su propio pyproject/uv.lock, historial y revisión `<servicio>_0001`. uv se instala en venv usando `tooling/uv.requirements.txt` con hashes. `sync --locked` rechaza un lock desactualizado. No hay instalaciones globales.

La imagen de PostgreSQL16 y Python3.12-bookworm están fijadas por los digests comprobados en `docker-compose.yml` e `infra/docker/persistence.Dockerfile`; son imágenes oficiales disponibles en este equipo, sin afirmar que sean la última revisión o una auditoría de vulnerabilidades. Actualizarlas exige revisar lock/digest y repetir las pruebas.

| Base y rol propietario | Revisión base / actual | Tablas de aplicación |
| --- | --- | --- |
| identity | identity_0003 | alembic_version, users, refresh_sessions, password_recovery_tokens, audit_logs |
| diagnosis | diagnosis_0003 | alembic_version, crops, problems, recommendations, diagnoses, idempotency_keys, image_upload_intents, diagnosis_feedback, diagnosis_audit_logs, diagnosis_outbox, diagnosis_inbox, diagnosis_quarantine_messages |
| ai_inference | ai_inference_0002 | alembic_version, inference_jobs, inference_inbox, inference_results, inference_outbox, inference_quarantine_messages, inference_audit_logs |
| notification | notification_0001 | Solo alembic_version |

Roles sin superuser/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS ni membresías. CONNECT público revocado en las cuatro bases y en postgres/template1; permisos del schema public restringidos al dueño. No hay tablas compartidas ni llaves foráneas cruzadas entre servicios. Bootstrap rechaza dueño inesperado o membresía ajena, sin apropiarse de bases existentes. Credencial postgres solo en PostgreSQL y job bootstrap; cada migración recibe únicamente su secreto propio.

## Persistencia Asíncrona, Leases y Cuarentena (Incremento 3)

### Diagnosis (`diagnosis_0003`)
- **Columnas de lease y ciclo asíncrono en `diagnoses`**:
  - `correlation_id`: Identificador de correlación de la solicitud o del backfill de recuperación.
  - `lease_owner`: Identificador de la instancia worker verificado mediante JWT interno.
  - `lease_token`: Token UUID único de la generación de trabajo en curso.
  - `lease_expires_at`: Expiración temporal según el reloj relacional de PostgreSQL.
  - `attempt_count`: Contador de generaciones de ejecución consumidas (máximo 3).
  - `processing_deadline_at`: Límite máximo de procesamiento (300s desde primer claim).
  - `recovery_signaled_at`: Marca temporal de señalización de recuperación.
- **Tablas durables**:
  - `diagnosis_outbox`: Registro transaccional de eventos salientes (`DiagnosisRequested` v2, `DiagnosisFinished` v1) con `UNIQUE(diagnosis_id, event_type, attempt_number)` e `ix_diagnosis_outbox_publishable`.
  - `diagnosis_inbox`: Deduplicación de eventos consumidos (`DiagnosisAnalyzed` v1) con `UNIQUE(consumer, event_id)` e índice por diagnóstico y lease.
  - `diagnosis_quarantine_messages`: Aislamiento seguro de mensajes corruptos o no conformes sin almacenar cargas útiles crudas.

### AI Inference (`ai_inference_0002`)
- **Tablas de dominio técnico**:
  - `inference_jobs`: Seguimiento de trabajos por diagnóstico (`UNIQUE(diagnosis_id)`), estado y reclamo local exclusivo.
  - `inference_inbox`: Deduplicación de eventos entrantes (`DiagnosisRequested` v1/v2) con `UNIQUE(consumer, event_id)`.
  - `inference_results`: Resultados del análisis técnico con `UNIQUE(diagnosis_id, lease_token)`.
  - `inference_outbox`: Registro transaccional de eventos salientes (`DiagnosisAnalyzed` v1) con `UNIQUE(diagnosis_id, lease_token)` e `ix_inference_outbox_publishable`.
  - `inference_quarantine_messages`: Aislamiento seguro de mensajes defectuosos.
  - `inference_audit_logs`: Registro transaccional de auditoría operativa con sanitización de credenciales.

### Políticas de Cuarentena y Rollback
Para la especificación detallada de los campos conservados en cuarentena, el protocolo de reconstrucción segura de mensajes sin replay ciego y la política de rollback conservador ante contingencias, consultar [Operación de Cuarentena y Reconstrucción](operations/quarantine-and-reconstruction.md).

## Dominio de Diagnosis y Catálogo Candidato (Incremento 2)

La revisión `diagnosis_0002` crea las 8 tablas de dominio del servicio Diagnosis:
1. `crops`: Catálogo de cultivos autorizados (`POTATO`, `MAIZE`).
2. `problems`: Condiciones candidatas (`HEALTHY` y `DISEASE`), asociadas a su cultivo, con `model_supported=false`.
3. `recommendations`: Versiones inmutables de recomendaciones agronómicas (`UNIQUE(problem_code, version)`), con fuentes y referencias de revisión humana.
4. `diagnoses`: Ciclo de vida del diagnóstico, referencia S3 privada `object_key` (sin bytes de imagen en PostgreSQL), snapshot de recomendación y tombstone de borrado lógico `deleted_at`.
5. `idempotency_keys`: Namespace de idempotencia `(owner_id, scope, key)` con fingerprint SHA-256 de la imagen y expiración de 24 horas.
6. `image_upload_intents`: Intenciones durables para el protocolo de subida a S3 y reconciliación sin huérfanos.
7. `diagnosis_feedback`: Registro 1:1 de utilidad y comentarios sobre diagnósticos completados o no concluyentes.
8. `diagnosis_audit_logs`: Auditoría transaccional exclusiva del servicio Diagnosis (actor, acción, destino, correlación, timestamp UTC).

### Semillas candidatas e invariantes
- **Taxonomía V1**: Se insertan los cultivos `POTATO` y `MAIZE`, junto a las siete condiciones contractuales: `POTATO_HEALTHY`, `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT`, `MAIZE_HEALTHY`, `MAIZE_COMMON_RUST`, `MAIZE_LEAF_BLIGHT` y `MAIZE_GRAY_LEAF_SPOT`.
- **Invariante de validación**: Ninguna condición candidata activa equivale a clase validada por el modelo de IA; todas inician estrictamente con `model_supported=false`.
- **Invariante de recomendaciones**: El catálogo arranca sin recomendaciones agronómicas semilla (`items: []`). Un catálogo sin recomendaciones es un arranque técnicamente válido. No se insertan tratamientos ni dosis sin un paquete formal de fuentes y revisión humana documentada.

### Comandos de migración reproducibles para Diagnosis
```bash
docker compose run --rm --no-deps diagnosis-migrate python -m app.migrate current
docker compose run --rm --no-deps diagnosis-migrate python -m app.migrate upgrade head
docker compose run --rm --no-deps diagnosis-migrate python -m app.migrate ready
```

## Ingesta, S3, Idempotencia y Reconciliación (Incremento 2)

### Protocolo de carga e intenciones durables
1. **Validación multipart y límites**:
   - Único campo `image` obligatorio en `multipart/form-data`; cualquier campo o archivo adicional devuelve `400 INVALID_REQUEST`.
   - Límite real del archivo: exactamente 10 MiB (10,485,760 bytes). Superar este límite devuelve `413 IMAGE_TOO_LARGE`.
   - Margen de transporte multipart: 11 MiB (11,534,336 bytes).
   - Formatos permitidos: JPEG, PNG y WebP decodificables; detectados por número mágico y validación profunda Pillow con decodificación de píxeles (`load()`).
   - Máximo 24 megapíxeles (24,000,000 píxeles decodificados). Píxeles excesivos o avisos/errores de descompresión disparan `413 IMAGE_TOO_LARGE`.
   - Archivos multifotograma o animados son rechazados con `400 INVALID_IMAGE`.
   - Archivos corruptos tras cabecera válida devuelven `400 INVALID_IMAGE`.
   - Formatos no admitidos (GIF, BMP, TIFF, ejecutables) o HEIC/HEIF devuelven `415 UNSUPPORTED_MEDIA_TYPE`. El soporte y conversión HEIC/HEIF permanece pendiente para V1.
   - No se anuncia sanitización EXIF no ejecutada; se conserva el archivo original privado para fingerprint SHA-256 y descarga por su propietario.

2. **Idempotencia con bloqueo advisory no bloqueante**:
   - Clave obligatoria `Idempotency-Key` (patrón `^[A-Za-z0-9._:-]{1,128}$`).
   - Serialización mediante `SELECT pg_try_advisory_xact_lock(:lock_id)` derivado de `(owner_id, scope, key)`. Si el bloqueo no se adquiere de inmediato, devuelve `409 IDEMPOTENCY_IN_PROGRESS`.
   - Retención de 24 horas no deslizante (`expires_at = first_accepted_at + 86400s`).
   - Replay idéntico durante retención devuelve `202 Accepted` con ID, fecha original y estado actual, sin duplicar registros ni subidas a S3.
   - Clave repetida con contenido diferente devuelve `409 IDEMPOTENCY_CONFLICT`.
   - Clave asociada a un diagnóstico con borrado lógico (`deleted_at IS NOT NULL`) devuelve `409 IDEMPOTENCY_RESOURCE_DELETED` durante retención, sin resucitar el recurso.
   - Al expirar (`now >= expires_at`), se permite una nueva generación atómica conservando el diagnóstico previo.
   - Separación estricta por usuario: claves idénticas entre usuarios distintos operan en namespaces aislados.

3. **Reconciliador de intenciones huérfanas (`reconcile_upload_intents`)**:
   - Comando de mantenimiento: `python -m app.application.reconcile`
   - Ejecuta consulta bajo transacción con `FOR UPDATE SKIP LOCKED`, lo que garantiza que no colisiona con subidas en curso ni bloquea otros procesos.
   - Para cada intención: verifica si algún diagnóstico en PostgreSQL referencia `object_key` o `diagnosis_id`.
   - Si existe referencia: conserva el objeto en S3 y retira la intención residual.
   - Si no existe referencia: elimina el objeto en S3 (ausencia cuenta como éxito idempotente) y luego elimina la intención de la base de datos.
   - Si la eliminación en S3 falla: la intención se preserva en PostgreSQL para reintentarse en ejecuciones posteriores.
   - Límites: procesamiento por lotes acotados (`batch_size=100`) con reintentos y timeouts acotados.

4. **Entrega privada al propietario**:
   - `GET /api/v1/diagnoses/{id}/image`:
     - Exige Bearer token válido y propiedad estricta.
     - Devuelve bytes originales con `Content-Type` real y cabecera `Cache-Control: private, no-store`.
     - Si el recurso es ajeno, inexistente o tiene tombstone (`deleted_at`), responde un `404 NOT_FOUND` genérico idéntico.
     - Usuarios con rol `ADMIN` en esta ruta de usuario están sujetos a la misma comprobación de propiedad (reciben 404 si la imagen no les pertenece).



## Preparación y ejecución

Desde la raíz del repositorio, con Docker y Compose:

```bash
test -f .env || cp .env.example .env
python3 scripts/prepare_local.py
docker compose config --quiet
docker compose build
docker compose up -d identity-schema-check diagnosis-schema-check ai_inference-schema-check notification-schema-check
docker compose wait identity-schema-check diagnosis-schema-check ai_inference-schema-check notification-schema-check
```

El preparador crea `.local/persistence/` ignorado por Git, directorio0700 y archivos0600, sin mostrar ni reemplazar secretos existentes. Para proyecto aislado, exportar PERSISTENCE_SECRETS_DIR con ruta absoluta a otro directorio y usar siempre `docker compose -p <nombre>`; el script de aceptación lo hace automáticamente.

Compose no publica puertos. PostgreSQL vive en red interna y volumen nombrado por proyecto. Cadena: PostgreSQL saludable → bootstrap terminado con0 → migración propia terminada con0 → comprobación de head. Jobs son one-shot, `restart: no`; su salida no equivale a un servidor en ejecución. Las APIs del grupo4 exigen éxito de la migración antes de arrancar y comprueban el head en cada sondeo. Los jobs schema-check se mantienen en el perfil persistence-check para invocación explícita.

Los secretos locales de Compose son archivos montados; por conservar permisos0600, los jobs técnicos se ejecutan como root dentro del contenedor para leerlos. Eso no concede privilegios PostgreSQL: cada job conecta con su rol restringido. No se monta socket Docker ni directorios del host con escritura en esos jobs. No copiar esta política local como decisión de usuario de las futuras APIs productivas.

Para repetir bootstrap y una migración (ejemplo Identity):

```bash
docker compose run --rm --no-deps db-bootstrap
docker compose run --rm --no-deps identity-migrate python -m app.migrate upgrade head
docker compose run --rm --no-deps identity-migrate python -m app.migrate current
docker compose run --rm --no-deps identity-migrate python -m app.migrate ready
```

`--no-deps` supone PostgreSQL ya iniciado y bootstrap realizado. Fallo de configuración/conexión/migración termina1 y no imprime DSN, SQL ni contraseñas. `ready` solo lee la revisión: devuelve1 si falta, es distinta, hay varios heads o falla conexión; nunca usa `create_all` ni corrige el esquema. `current` informa revisión pero no reemplaza `ready` como aceptación.

## Parada, recuperación y reversión

`docker compose --profile persistence-check down` retira también los jobs de comprobación invocados explícitamente y conserva el volumen. Volver a arrancar usa los mismos secretos y no borra datos. No usar `down -v` en el proyecto de desarrollo como procedimiento normal. No cambiar el secreto postgres de un volumen existente esperando que initdb rote la contraseña: requiere procedimiento explícito de rotación. El bootstrap actualiza las contraseñas de los roles de servicio desde sus archivos al repetirse.

Una migración fallida bloquea el job dependiente. Corregir configuración/revisión, repetir upgrade y ready. Si quedó un job fallido, recrear únicamente ese job y su comprobación; no borrar volúmenes. El test demuestra corrección/repetición con esos recursos aislados.

Solo sobre un proyecto efímero puede ensayarse `python -m app.migrate downgrade base`, seguido de `upgrade head`; la herramienta exige destino explícito. En evolución real revisar reversibilidad, backup y compatibilidad de código antes de downgrade. No reescribir una revisión base aplicada.

## Aceptación reproducible

```bash
python3 scripts/check_persistence.py
```

Crea un nombre de proyecto aleatorio `agro-mig-test-*`, secretos efímeros y volumen propio. Comprueba bootstrap dos veces, roles/propiedad, cuatro conexiones propias y doce cruzadas rechazadas, upgrade/current/segundo upgrade/downgrade/upgrade, ausencia de tablas de dominio, contraseña inválida, head ausente/desconocido, migración SQL fallida y rollback, bloqueo del job dependiente y recuperación. Busca secretos en salidas y logs. La limpieza elimina solo el proyecto aleatorio de la prueba, incluso al fallar; conserva imágenes/caché de build.

No requiere puertos al host, credenciales productivas, GPU, modelos ni datos reales. Cada comando tiene timeout; build admite600s y otras operaciones120–180s, sin promesas de rendimiento productivo. Los fallos intencionales se inyectan en copias temporales, nunca en revisiones originales.

La prueba de Python usa los mismos módulos de configuración/migración de cada servicio y PostgreSQL real. No verifica HTTP200/503 ni S3: esos casos pertenecen al grupo4. [Evidencia del grupo3](evidence/INCREMENTO-0-GRUPO-3.md).

Referencias: [sincronización bloqueada uv](https://docs.astral.sh/uv/concepts/projects/sync/), [Alembic](https://alembic.sqlalchemy.org/en/latest/cookbook.html), [privilegios PostgreSQL16](https://www.postgresql.org/docs/16/sql-grant.html). Se adopta migración explícita; no la alternativa de crear tablas automáticamente.

Verificación independiente de los cuatro locks/imports desde entornos nuevos: `bash scripts/check_service_locks.sh`. Instala uv bloqueado en venv efímero y limpia solo sus entornos.
