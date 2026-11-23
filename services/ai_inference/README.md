# AI Inference — AgroDiagnóstico V1

Estado: persistencia y API de salud técnica implementadas; funciones de negocio pendientes. La presencia de `app/`, `migrations/` o Dockerfile no demuestra implementación.

Responsabilidad prevista: trabajos y análisis técnicos, versiones del modelo y outbox técnico. No decide el resultado publicable ni genera recomendaciones. Su base es técnica; no duplica datos de negocio de Diagnosis. El arranque inicial no requiere GPU ni pesos.

El grupo 3 aporta dependencias bloqueadas, contenedor de migración y revisión Alembic independiente. El grupo 4 aporta API de salud y contenedor de runtime. Las funciones de dominio corresponden al incremento 3 (simulación) y 4 (modelo evaluado); no están terminadas.

Referencias: [arquitectura](../../docs/ARCHITECTURE.md), [inventario de interfaces](../../docs/API_CONTRACTS.md), [ADR de persistencia](../../docs/adr/0001-incremento-0-base-tecnica.md) y [tareas del Incremento 0](../../openspec/changes/archive/2026-09-30-incremento-0-base-integrada/tasks.md). Los comandos de persistencia se describen debajo; el servidor HTTP técnico se inicia mediante Compose según DEVELOPMENT.


## Dependencias y migración base

Python 3.12 (`>=3.12,<3.13`), uv 0.12.20; dependencias directas y transitivas bloqueadas en `uv.lock`. Desde la raíz:

```bash
python3 -m venv tooling/.venv
tooling/.venv/bin/python -m pip install --require-hashes -r tooling/uv.requirements.txt
tooling/.venv/bin/uv sync --project services/ai_inference --locked --no-dev --no-install-project
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


## Modos de Ejecución del Worker Asíncrono (Incremento 4)

El worker asíncrono (`app.worker`) procesa eventos `DiagnosisRequested` (v1 y v2) consumiendo de RabbitMQ, reclamando diagnósticos en `Diagnosis` vía API interna, obteniendo la imagen por lease token y produciendo eventos `DiagnosisAnalyzed` (v1).

Dispone de tres perfiles de ejecución estrictamente aislados:

### 1. Perfil de demostración seguro (`demo`)

- **Adaptador**: `DemoUnavailableInferenceAdapter`, sin pesos ni bundle.
- **Resultado**: siempre `ABSTENTION/UNSUPPORTED_CLASS`; Diagnosis lo publica
  como `NO_CONCLUYENTE` y no registra metadatos de un modelo inexistente.
- **Activación explícita**:
  ```bash
  docker compose --profile demo up -d ai_inference-worker-demo
  ```
- No es el simulador de pruebas y no representa rendimiento agronómico.

### 2. Perfil de Prueba (`async-test`)
- **Adaptador**: `SimulatedInferenceAdapter`.
- **Doble guardia mandatoria**: Requiere explícitamente `APP_ENV=test` y `ENABLE_SIMULATED_INFERENCE=true`. En cualquier otro entorno falla inmediatamente al arranque.
- **Uso**: Pruebas de integración automatizadas y suites de CI.
- **Activación**:
  ```bash
  docker compose --profile async-test up -d ai_inference-worker-1
  ```

### 3. Perfil real bloqueado (`ml-real`)

`INFERENCE_MODE=real` exige `REAL_INFERENCE_AUTHORIZED=true`, además de los
SHA-256 del bundle y del acta G2 fijados al arranque. El valor distribuido es
`false`: el ciclo v1.4.3 fue rechazado externamente y no autoriza cambiarlo.
Valida esquema, acta, hashes, pesos `safetensors`, mapa de solo dos tizones y
preprocesado antes de abrir RabbitMQ; una ausencia o corrupción impide el consumo.
Cada inferencia se ejecuta en un proceso CPU separado con límite de 20 segundos,
manteniendo el heartbeat del lease en el proceso del worker. El valor
`identified_crop=POTATO` viaja desde `DiagnosisRequested` v2 al adaptador;
sin esa identificación o con cultivo ajeno se abstiene sin ejecutar el modelo.
El adaptador JSON histórico permanece únicamente para fixtures bajo doble guardia.

El perfil está **sin activar y bloqueado**. G2 cerró rechazado, G3 no fue
promovido y no existe política de publicación activa. La preparación técnica
histórica no autoriza diagnósticos para usuarios.
Ver [operación del modelo](../../docs/operations/ai-model-operations.md).

`INFERENCE_MODE=fixture` sirve únicamente para pruebas con APP_ENV=test y
ENABLE_SIMULATED_INFERENCE=true. No es un fallback de producción.
