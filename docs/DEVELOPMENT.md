# Desarrollo e incrementos

## Estado del repositorio

El grupo4 integra un entorno técnico local: página React servida por Nginx, cuatro APIs de salud, PostgreSQL, RabbitMQ, Redis y S3 privado. Las funciones de usuario, inferencia, curación real del dataset y CI remota siguen pendientes; el inventario inicial ya se verifica localmente. No hay respuestas de negocio simuladas. La auditoría del host se conserva en ENVIRONMENT.md.

## Preparación y arranque local

Requiere Docker/Compose y Python3.12. El build instala dependencias bloqueadas dentro de contenedores; no requiere GPU, modelo, correo o cuenta Cloudflare. Desde la raíz:

```bash
test -f .env || cp .env.example .env
python3 scripts/prepare_local.py
docker compose config --quiet
docker compose build
docker compose up -d --wait --wait-timeout 180
```

Abrir `http://127.0.0.1:8080` (o HTTP_PORT elegido). Solo Nginx publica puerto, ligado a loopback. `.env` contiene configuración local no secreta; archivos de secretos se generan en `.local/persistence/` ignorado por Git y excluido del build. El preparador conserva claves existentes. LOCAL_UID/GID deben coincidir con `id -u`/`id -g` para que las APIs lean archivos 0600; los valores de ejemplo son 1000. El directorio local de secretos queda en 0700. Solo `s3_config.json` usa 0644 dentro de ese directorio privado, porque Compose monta el archivo con el modo del host y SeaweedFS puede ejecutarse con UID mapeado en CI; los demás archivos quedan en 0600. Si se cambia S3_BUCKET, preparar con `python3 scripts/prepare_local.py --bucket <nombre>` y recrear S3 para cargar sus permisos. No usar imágenes/datos reales en este scaffold.

Variables locales obligatorias: APP_ENV=local, HTTP_PORT, S3_BUCKET, S3_REGION. PERSISTENCE_SECRETS_DIR puede cambiar la ruta de archivos; no poner contraseñas en `.env`. Dominio/TLS/Cloudflare/correo/observabilidad son parámetros futuros opcionales, no dependencias de arranque. Ausencia de variable obligatoria falla con su nombre, sin mostrar secretos. El presupuesto de180s se mide después del build, no es una garantía de rendimiento productivo. SeaweedFS del perfil técnico admite hasta 16 volúmenes de 64 MiB para superar la inicialización de almacenamiento observada en CI; este límite no es una capacidad de producción.

## Salud, migraciones y parada

```bash
docker compose exec -T identity python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/ready').status)"
docker compose run --rm --no-deps identity-migrate python -m app.migrate current
docker compose run --rm --no-deps identity-migrate python -m app.migrate upgrade head
docker compose down
```

Cambiar identity por diagnosis, ai_inference o notification para los demás servicios. Bootstrap y migraciones se ejecutan antes de cada API, sin create_all. Los jobs `<servicio>-schema-check` del grupo3 se mantienen en perfil `persistence-check`, invocables explícitamente; no son procesos permanentes. [Persistencia](PERSISTENCE.md) explica repetición y reversión segura.

Las APIs solo exponen internamente `/health/live`, `/health/ready` y OpenAPI generado. Live200 indica proceso; ready200 exige base en head y, en Diagnosis, bucket autorizado; ready503 no muestra causa sensible. Nginx no publica salud, /internal o AI y devuelve404 JSON/no-store para API pendiente. Redis caído no invalida Diagnosis; broker y correo no condicionan su readiness.

`down` conserva los volúmenes; un nuevo `up` recupera datos. No ejecutar `down -v` en el proyecto del desarrollador como parada normal. La aceptación usa otro nombre de proyecto y elimina únicamente sus recursos sintéticos.

## Aceptación técnica repetible

```bash
python3 scripts/check_environment.py
bash scripts/check_contracts.sh
```

La primera orden crea proyecto Docker, puerto loopback libre y secretos efímeros. Compila frontend con lint/tipos/prueba/build, comprueba APIs y OpenAPI de salud, puertos/rutas, permisos S3, migraciones, PostgreSQL/Redis/S3 caídos y recuperación, mensaje durable confirmado y objeto privado recuperados tras recrear contenedores. El perfil de prueba no usa credenciales productivas. La limpieza actúa solo sobre el proyecto generado, incluso ante fallo. Tests de infraestructura no acreditan flujo de diagnóstico, entrega outbox/inbox, fallback de catálogo ni calidad de modelo.

La prueba de página verifica el render React; el smoke comprueba que Nginx entrega HTML y assets. La CI de aplicación del grupo6 reutiliza estos comandos; véase [CI](CI.md) para ejecución local, reportes y regresiones. [Evidencia del grupo4](evidence/INCREMENTO-0-GRUPO-4.md), [decisión de S3](adr/0003-entorno-local-y-almacenamiento.md) y [topología local](c4/entorno-local.md).

## Plan de entregas

| Incremento | Implementación | Demostración mínima |
| --- | --- | --- |
| 0 | Repo, convenciones, Compose, CI, contratos base, migraciones, inventario de dataset, ADR de alcance | Entorno reproducible y validación de contratos |
| 1 | Identity, registro/login, refresh/logout, roles, recuperación de acceso y propiedad | Usuario A no accede al recurso de B |
| 2 | Diagnosis, objeto privado, validación, estados, catálogo, historial, borrado lógico | Carga válida e inválida; `202` con `PENDIENTE` |
| 3 | RabbitMQ, outbox, lease, worker provisional, inbox, reintentos, DLQ | Foto → cola → worker → resultado simulado marcado → historial, y fallos controlados |
| 4 | Datos curados, baseline, comparación, calibración, modelo versionado | Sustitución del provisional y reporte de prueba independiente |
| 5 | Notification, UI completa, monitoreo, seguridad, carga, backup/restore y despliegue | E2E con modelo real y evidencias de dominio, HTTPS y CDN |

No se implementan en el camino crítico Gemini, voz, PWA ni plagas. Se podrán desarrollar como cambios independientes cuando el cierre de V1 esté demostrado.

## Flujo de una tarea

1. Consulta la especificación vigente en `openspec/specs/`. Si aún está vacía, consulta la fuente V1 recibida y su reconciliación en `docs/reference/`; continúa el cambio activo del Incremento 0 sin crear otro por duplicado.
2. Crea o actualiza `openspec/changes/<nombre>/` mediante el flujo OpenSpec instalado; agrega propuesta, delta de capacidades, diseño cuando corresponda y tareas verificables.
3. Revisa el contrato externo antes de crear cliente/consumidor. Si cambia, versiona esquema y añade pruebas de compatibilidad.
4. Implementa en el servicio dueño, escribe migración, prueba casos normales, fallos y permisos.
5. Revisa `docs/` y C4/ADR, valida el cambio OpenSpec y archiva únicamente tras verificar implementación y pruebas.

La estructura específica de artefactos OpenSpec se deja a la versión del CLI instalada. El esquema `spec-driven` usa propuesta, deltas de especificación por capacidad, diseño y tareas; `openspec/specs/` recoge las capacidades aceptadas al archivar.

## Criterio de revisión de incremento

Registra commit, sistema, versiones, comandos, pruebas, evidencia, RF cubiertos y asuntos pendientes. Separa objetivos (por ejemplo p95) de resultados medidos. Un incremento no arrastra contratos rotos ni afirmaciones de cobertura de clases sin evaluación.

## Fuente y obligaciones reconciliadas

La fuente entregada para grupo 1 es [Definición Base V1](reference/Definicion_Base_AgroDiagnostico_V1_Limpia.docx), íntegramente extraída y contrastada en la [matriz](reference/RECONCILIACION-V1.md). El incremento 1 incluye cambio y recuperación completa de contraseña con adaptador de correo; el 2 conserva feedback de utilidad y objetivo de formatos HEIC/HEIF con conversor; el 4 valida cultivo automático; el 5 integra UI y lectura de avisos. No se adelantan estas implementaciones al Incremento 0. Los parámetros de producción y la cobertura ML siguen sujetos a pruebas.

Aceptación de persistencia: `python3 scripts/check_persistence.py`; crea y limpia únicamente su proyecto Docker efímero. La verificación ampliada está en check_environment.py.

## CI local de aplicación

```bash
bash scripts/prepare_ci.sh
python3 scripts/run_ci.py
```

El ejecutor verifica versiones y todas las etapas obligatorias, guarda evidencia en `.local/ci/<id>/` y limpia exclusivamente sus proyectos Docker. Instala tooling aislado; no cambia npm/Python/Docker globales. [Versiones y procedimiento](CI.md). La ejecución remota sigue pendiente hasta disponer de revisión publicada y enlace de GitHub Actions; no se hace push automáticamente.


## Corrección de Identity posterior al archivo del incremento 1

`python3 scripts/prepare_local.py` requiere OpenSSL y genera claves Ed25519 persistentes en el directorio privado de secretos. Reejecutarlo valida y conserva las claves existentes. Una pareja incompatible produce error; no se rota automáticamente. Compose monta `jwt_private_key.pem` y `jwt_public_key.pem` solo en Identity. Configura `ALLOWED_ORIGINS` como lista separada por comas de orígenes completos; por defecto incluye `http://127.0.0.1:8080` y `http://localhost:8080`. Si cambias HTTP_PORT, ajusta también esa lista.

Para aplicar el código corregido al entorno local: ejecutar `python3 scripts/prepare_local.py`, `docker compose build identity identity-migrate` y `docker compose up -d --wait --wait-timeout 180`. Revisar primero los cambios/migraciones y preservar respaldos si hay datos que conservar. La migración nueva es `identity_0003`; conserva auditoría anterior como legacy. Las sesiones con CSRF anterior requieren nuevo login. Cookies siguen siendo Secure: las pruebas HTTP de backend transfieren cookies explícitamente; no acreditan un flujo de navegador sin HTTPS.

Aceptación independiente: `python3 scripts/check_identity_integration.py`. Construye una imagen del código actual, usa DB/red/contenedores propios y los elimina al terminar. No usa credenciales ni bases del entorno local. El correo sigue siendo adaptador local/de prueba; no se anuncia entrega externa.
