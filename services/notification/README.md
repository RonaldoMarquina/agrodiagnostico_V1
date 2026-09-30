# Notification — AgroDiagnóstico V1

Estado: persistencia y API de salud técnica implementadas; funciones de negocio pendientes. La presencia de `app/`, `migrations/` o Dockerfile no demuestra implementación.

Responsabilidad prevista: avisos internos, preferencias, estado de lectura e intentos de entrega por correo. Consume DiagnosisFinished de forma idempotente. Un fallo de correo no modifica ni revierte un diagnóstico.

El grupo 3 aporta dependencias bloqueadas, contenedor de migración y revisión Alembic independiente. El grupo 4 aporta API de salud y contenedor de runtime. Las funciones de dominio corresponden al incremento 5; no están terminadas.

Referencias: [arquitectura](../../docs/ARCHITECTURE.md), [inventario de interfaces](../../docs/API_CONTRACTS.md), [ADR de persistencia](../../docs/adr/0001-incremento-0-base-tecnica.md) y [tareas actuales](../../openspec/changes/incremento-0-base-integrada/tasks.md). Los comandos de persistencia se describen debajo; el servidor HTTP técnico se inicia mediante Compose según DEVELOPMENT.


## Dependencias y migración base

Python 3.12 (`>=3.12,<3.13`), uv 0.12.20; dependencias directas y transitivas bloqueadas en `uv.lock`. Desde la raíz:

```bash
python3 -m venv tooling/.venv
tooling/.venv/bin/python -m pip install --require-hashes -r tooling/uv.requirements.txt
tooling/.venv/bin/uv sync --project services/notification --locked --no-dev --no-install-project
```

Esto crea únicamente entornos locales, sin modificar Python global. `uv lock` es una actualización deliberada; para reproducir se usa `sync --locked`. Se comprobó instalación/imports en entorno nuevo para cada servicio.

Desde esta carpeta y con DB_HOST/DB_PASSWORD_FILE configurados (DB_PORT opcional,5432), usar el Python de `.venv`:

```bash
.venv/bin/python -m app.migrate upgrade head
.venv/bin/python -m app.migrate current
.venv/bin/python -m app.migrate ready
```

La base/rol están fijados al dueño del servicio. `ready` devuelve0 solo si la revisión en PostgreSQL coincide con el único head del historial; es un prerrequisito de readiness, no un endpoint HTTP ni salud completa. Nunca crea tablas para corregir un fallo. Error devuelve1 con mensaje seguro, sin DSN ni credenciales.

La revisión base crea solo los metadatos `alembic_version`, sin tablas o seeds de dominio. Repetir upgrade es seguro. `downgrade base` exige revisión explícita y solo se ensaya sobre bases efímeras; elimina la marca de revisión, no volúmenes. Para cambios futuros, añadir revisiones nuevas, no reescribir la base.

[Operación con Docker, secretos y aceptación](../../docs/PERSISTENCE.md). El contenedor de migración usa solo la credencial de este servicio; bootstrap usa un job separado con credencial privilegiada. Las APIs de salud ya se ejecutan en grupo4; negocio sigue pendiente.

Salud integrada: GET /health/live y /health/ready internos, sin publicación por Nginx. La preparación, configuración APP_ENV y ejecución se detallan en [DEVELOPMENT](../../docs/DEVELOPMENT.md). No hay endpoints de negocio implementados.
