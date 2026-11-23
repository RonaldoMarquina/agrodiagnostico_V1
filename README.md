# AgroDiagnóstico V1

Plataforma web de apoyo para analizar fotografías. El piloto de modelo real se limita a hoja de papa previamente identificada por el usuario. Muestra una condición visual probable solo cuando la clase está validada y la evidencia es suficiente. En los demás casos devuelve **NO_CONCLUYENTE** y orienta al usuario para repetir la fotografía. No reemplaza una evaluación profesional.

> Estado: incrementos 0–3 implementados y verificados. Incremento 4 en desarrollo. [v1.4.2](docs/evidence/INCREMENTO-4-TRAIN-VAL-V1.4.2.md) cumplió VAL y fue congelado; tras el fallo técnico histórico de Sikkim, [v1.4.3](docs/evidence/INCREMENTO-4-V1.4.3-COMPATIBILIDAD-Y-PREFLIGHT.md) corrigió el decodificador y selló sin abrir un EXTERNAL sustituto de 350 imágenes. **G2/G3 permanecen abiertos y el worker real apagado.** Sikkim no se reintenta y no se autoriza uso comercial. Incremento 5 pendiente.

## Alcance del piloto G0 v1.2.0

| Entrada | Clases candidatas |
| --- | --- |
| Hoja de papa identificada previamente por el usuario | Tizón temprano, tizón tardío o rancha |

El piloto aprobado G0 v1.2.0 evalúa tizón temprano y tardío en una hoja de papa previamente identificada. Los siete códigos originales se conservan como historial. La interfaz declarará como soportadas únicamente las clases que superen los criterios definidos y aprobados por el responsable del proyecto antes del entrenamiento y la evaluación independiente. Gemini, voz, PWA y detección de plagas quedan como extensiones posteriores.

## Arquitectura prevista

- React + TypeScript para la interfaz de usuario y administración.
- FastAPI, SQLAlchemy y Alembic para los servicios Identity, Diagnosis, AI Inference y Notification.
- PostgreSQL para datos transaccionales, RabbitMQ para eventos, Redis para caché y almacenamiento compatible con S3 para imágenes privadas.
- PyTorch para el modelo versionado; Docker Compose y Nginx para integración local.
- Dominio real, Cloudflare, HTTPS con TLS hasta el origen y CDN para recursos estáticos en producción.

## Organización

```text
agrodiagnostico_V1/
├── AGENTS.md                 # instrucciones para agentes de desarrollo
├── README.md                 # entrada al proyecto
├── CONTRIBUTING.md           # colaboración y revisión
├── docs/                     # diseño y procedimientos
├── openspec/                 # requisitos vigentes y propuestas de cambio
├── contracts/                # OpenAPI y esquemas de eventos versionados
├── frontend/                 # aplicación React
├── services/                 # identity, diagnosis, ai_inference, notification
├── ml/                       # manifiestos, entrenamiento, evaluación y modelos
├── infra/                    # proxy, contenedores, Cloudflare y observabilidad
└── tests/                    # integración, E2E, seguridad, fallos y carga
```

Las carpetas opcionales pueden existir desde el inicio sin cargarse en el entorno principal. Los documentos de este paquete describen el diseño previsto; se actualizarán cuando el código y las pruebas lo confirmen.

## Desarrollo por incrementos

0. Repositorio, entorno, contratos, CI e inventario de datos.
1. Identidad, sesiones y autorización.
2. Carga privada, diagnóstico, catálogo, estados e historial.
3. Cola, outbox, worker provisional e idempotencia con prueba integral.
4. Dataset, entrenamiento, evaluación y sustitución por modelo validado.
5. Notificaciones, interfaz completa, observabilidad, pruebas, recuperación y despliegue con dominio, HTTPS y CDN.

El worker provisional **no produce diagnósticos reales**. Los comandos comprobados del entorno técnico están en [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Documentación

| Documento | Tema |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Reglas de trabajo para Codex y otros agentes |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Responsabilidades, datos y flujo asíncrono |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Incrementos y entorno de desarrollo |
| [docs/TESTING.md](docs/TESTING.md) | Matriz de aceptación y medición |
| [docs/SECURITY.md](docs/SECURITY.md) | Control de acceso, imágenes, secretos |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Dominio, Cloudflare, TLS, CDN y operación |
| [docs/AI_MODEL.md](docs/AI_MODEL.md) | Dataset, evaluación, abstención y versiones |
| [docs/API_CONTRACTS.md](docs/API_CONTRACTS.md) | Inventario de contratos HTTP y eventos |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Flujo de propuestas, revisión y cierre |

Los requisitos vigentes de los incrementos implementados están en `openspec/specs/`; los cambios nuevos se proponen en `openspec/changes/`. La fuente V1 entregada es [Definición Base del Proyecto – AgroDiagnóstico V1](docs/reference/Definicion_Base_AgroDiagnostico_V1_Limpia.docx), identificada por revisión y hash en la [reconciliación documental](docs/reference/RECONCILIACION-V1.md). Si hay discrepancias, detener el cambio y registrar la decisión antes de actualizar especificaciones, contratos y código.

## Estado documental actual

Los grupos 1–7 del [Incremento 0](openspec/changes/archive/2026-09-30-incremento-0-base-integrada/tasks.md) están cerrados: fuente reconciliada, ADR y [contratos verificables](contracts/README.md), 38/38 tareas. Al cierre del incremento 0 había ocho operaciones de salud implementadas y diecinueve de negocio contract-only. Compose integra las cuatro APIs técnicas, página React/Nginx, PostgreSQL, RabbitMQ, Redis y S3 privado. El inventario inicial y la CI de aplicación están verificados localmente; CI remota aprobada en la ejecución 36749372314. Ese era el alcance histórico del incremento 0; el estado posterior se detalla al final de esta sección. Véanse [incrementos](docs/Incrementos.md), [ADR de base](docs/adr/0001-incremento-0-base-tecnica.md), [ADR de interfaces](docs/adr/0002-interfaces-y-eventos-v1.md) y [evidencia documental](docs/evidence/INCREMENTO-0-GRUPO-1.md).

La [versión legible de la fuente](docs/reference/Definicion_Base_AgroDiagnostico_V1_Limpia.md) conserva el documento de origen. Sus ejemplos, alternativas y diferencias se interpretan mediante la reconciliación; no prueban capacidades implementadas.

Validación de contratos: `bash scripts/check_contracts.sh` (Python 3.12, venv efímero y lock con hashes). [Evidencia del grupo 2](docs/evidence/INCREMENTO-0-GRUPO-2.md).

Persistencia local: [operación y límites](docs/PERSISTENCE.md). Aceptación: `python3 scripts/check_persistence.py`. [Evidencia del grupo 3](docs/evidence/INCREMENTO-0-GRUPO-3.md).


## Entorno técnico local

```bash
test -f .env || cp .env.example .env
python3 scripts/prepare_local.py
docker compose config --quiet
docker compose build
docker compose up -d --wait --wait-timeout 180
```

Abrir `http://127.0.0.1:8080`. Solo se ofrece la página técnica, sin carga o diagnósticos. Verifica LOCAL_UID/GID y configuración en [DEVELOPMENT](docs/DEVELOPMENT.md). Parada conservando datos: `docker compose down`. Aceptación aislada: `python3 scripts/check_environment.py`. [Evidencia del grupo4](docs/evidence/INCREMENTO-0-GRUPO-4.md).

Inventario del dataset: [fuentes, cantidades, taxonomía y límites](ml/manifests/README.md). Verificación: `bash scripts/check_dataset.sh`. El lote privado PlantVillage v1.2.0 pasó G1 y se usó en entrenamiento y evaluación documentados; las otras fuentes siguen pendientes. Papa sana fue admitida como estrato técnico de rechazo en [G1 v1.3.1](docs/evidence/INCREMENTO-4-G1-V1.3.1-ADMISION.md); su rechazo **falló** en el [TEST v1.3.2](docs/evidence/INCREMENTO-4-TEST-V1.3.2-UNICO.md).

CI de aplicación: [workflow y reproducción local](docs/CI.md), con `bash scripts/prepare_ci.sh` y `python3 scripts/run_ci.py`. [Evidencia del grupo 6](docs/evidence/INCREMENTO-0-GRUPO-6.md).

Aceptación integrada local del grupo 7: 7.1–7.4 verificadas, incluida la CI remota. [Evidencia](docs/evidence/INCREMENTO-0-GRUPO-7.md). Los cinco deltas ya están sincronizados y el cambio se encuentra archivado.

Historial de corrección: [primera ejecución fallida 36743640034](https://github.com/RonaldoMarquina/agrodiagnostico_V1/actions/runs/36743640034). [Evidencia](docs/evidence/INCREMENTO-0-GRUPO-7-REMOTO.md).

Cierre de tareas del Incremento 0: [Application CI aprobada](https://github.com/RonaldoMarquina/agrodiagnostico_V1/actions/runs/36749372314) sobre `97472b1`. [Evidencia remota](docs/evidence/INCREMENTO-0-GRUPO-7-REMOTO.md). Los cinco deltas se sincronizaron y el cambio se archivó el 2026-09-30.


Estado posterior del Incremento 1: Identity implementa las 12 operaciones de negocio; la revisión posterior al archivo exigió un correctivo de claves, Origin/CSRF, auditoría y evidencia multi-instancia. El estado vigente y sus límites están en [INCREMENTO-1-CORRECCION](docs/evidence/INCREMENTO-1-CORRECCION.md). Las referencias previas al Incremento 0 son históricas. Diagnosis implementa los incrementos 2 y 3. El Incremento 4 tiene [G0 aprobado como diseño](docs/evidence/INCREMENTO-4-PROTOCOLO-G0.md), [G1 cerrado para el piloto v1.2.0](docs/evidence/INCREMENTO-4-G1-PILOTO-V1.2.md), [bundle piloto aprobado G2](docs/evidence/INCREMENTO-4-APROBACION-G2-PILOTO.md), [catálogo revisado](docs/evidence/INCREMENTO-4-CATALOGO-PILOTO-V1.md) y [aceptación integrada local fallida](docs/evidence/INCREMENTO-4-G3-ACEPTACION-LOCAL.md). G3 y la activación para usuarios siguen pendientes. Véanse las [tareas del ciclo histórico](openspec/changes/incremento-4-datos-y-modelo-validado/tasks.md) y el [ciclo v1.3.2 con TEST fallido](openspec/changes/incremento-4-v1-3-rechazo-papa-sana/tasks.md). El incremento 5 permanece separado.
