# Persistencia local — Incremento 0, grupo 3

Este documento describe la capa de persistencia del grupo3. El Compose actual añade APIs técnicas e infraestructura del grupo4: véase [DEVELOPMENT](DEVELOPMENT.md). schema_ready() ya se usa en readiness HTTP; Diagnosis comprueba también S3. Las rutas de negocio continúan contract-only.

## Versiones y propiedad

Python3.12, uv0.12.20, FastAPI0.141.1, SQLAlchemy2.1.1, Alembic1.20.0 y psycopg3.3.6. Cada servicio tiene su propio pyproject/uv.lock, historial y revisión `<servicio>_0001`. uv se instala en venv usando `tooling/uv.requirements.txt` con hashes. `sync --locked` rechaza un lock desactualizado. No hay instalaciones globales.

La imagen de PostgreSQL16 y Python3.12-bookworm están fijadas por los digests comprobados en `docker-compose.yml` e `infra/docker/persistence.Dockerfile`; son imágenes oficiales disponibles en este equipo, sin afirmar que sean la última revisión o una auditoría de vulnerabilidades. Actualizarlas exige revisar lock/digest y repetir las pruebas.

| Base y rol propietario | Revisión base | Tablas de aplicación iniciales |
| --- | --- | --- |
| identity | identity_0001 | Solo alembic_version |
| diagnosis | diagnosis_0001 | Solo alembic_version |
| ai_inference | ai_inference_0001 | Solo alembic_version |
| notification | notification_0001 | Solo alembic_version |

Roles sin superuser/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS ni membresías. CONNECT público revocado en las cuatro bases y en postgres/template1; permisos del schema public restringidos al dueño. No hay tablas compartidas ni seeds. Bootstrap rechaza dueño inesperado o membresía ajena, sin apropiarse de bases existentes. Credencial postgres solo en PostgreSQL y job bootstrap; cada migración recibe únicamente su secreto propio.

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
