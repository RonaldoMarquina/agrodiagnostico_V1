# Evidencia de cierre: Extensión de Asistente Conversacional y Adaptador Gemini

Fecha: 2026-11-23. Cambio OpenSpec archivado: [add-gemini-assistant](../../openspec/changes/archive/2026-11-23-add-gemini-assistant/tasks.md) (10/10 tareas completas; capacidad `gemini-assistant` sincronizada en `openspec/specs/`, 16/16 specs válidas). Decisión arquitectónica: [ADR-0015](../adr/0015-asistente-conversacional-y-adaptador-gemini.md).

## Clasificación de estado por capacidad

| Capacidad / verificación | Estado | Detalle |
| --- | --- | --- |
| Backend sin estado `extensions/assistant/` (`POST /api/v1/assistant/messages`, `/health/live`, `/health/ready`) | **IMPLEMENTED** | FastAPI Python 3.12 (`uv.lock`), JWT Ed25519, límite `413`, esquema cerrado `400`, detector de secretos `AT-19`, rate limit `429`, 16 intents, RBAC independiente `403`, degradación `503`/`504`, logs JSON sin PII/secretos. |
| Flujo determinista completo y E2E vía Nginx (`FakeAssistantAdapter`, con y sin `--profile assistant`) | **VERIFIED_FAKE** | 25/25 pruebas unitarias + 6/6 bloques E2E en Compose desechable (`scripts/check_assistant_integration.py`) con JWT reales de `identity` (`USER` y `ADMIN`) y verificación de aislamiento de red y cero mutaciones. |
| Adaptador real `GeminiAdapter` (`httpx` REST + `responseSchema` cerrado + `x-goog-api-key` en cabecera) | **IMPLEMENTED** *(transporte simulado verificado; `VERIFIED_REAL` pendiente de `GEMINI_API_KEY`)* | Verificado en pruebas unitarias con `httpx.MockTransport` (éxito estructurado, reintento `503`, timeout `504`, JSON malformado, no fuga de clave). El smoke en vivo `scripts/check_gemini_real_smoke.py` (`AT-23`) no se ejecutó por ausencia de `GEMINI_API_KEY` en el entorno y queda disponible para ejecución explícita del operador. |
| Destinos administrativos `OPEN_AUDIT` y `OPEN_MONITORING` (`AT-09`) | **DEFERRED** | Registrados en `INTENT_REGISTRY` con `available = False`; para `USER` responden `403 FORBIDDEN` y para `ADMIN` responden `200 OUT_OF_SCOPE` con `action = null`. |
| Interfaz conversacional React y guards cliente (`AT-20` UI) | **DEFERRED** | Corresponde al incremento de Frontend completo (Paso 3); `frontend/` conserva el entorno técnico base del Incremento 0. |
| Capacidad de voz (`AT-24`) | **DEFERRED** | Fuera de alcance V1 (`services/optional/voice/` intacto). |

## Decisiones ADR-0015 aplicadas

- **Ubicación profesional orientada a dominio:** `extensions/assistant/` (servicio Compose `assistant` bajo `profiles: [assistant]`), retirando el placeholder vacío `services/optional/gemini_assistant/.gitkeep` y manteniendo `services/` reservado exclusivamente a los 4 microservicios núcleo (`identity`, `diagnosis`, `ai_inference`, `notification`).
- **Aislamiento físico:** `assistant` no tiene puertos publicados y solo se conecta a `application` y `edge` (sin `persistence`); verificado en runtime que no puede conectar con `postgres:5432`.
- **Enrutamiento Nginx tolerante a perfil inactivo:** `location = /api/v1/assistant/messages` usa `resolver 127.0.0.11`, `client_max_body_size 16k` y fallback `@assistant_unavailable` (`503 ASSISTANT_UNAVAILABLE`) cuando `--profile assistant` no está levantado.
- **Contratos de extensión separados:** `contracts/openapi/extensions/assistant.openapi.json`, `contracts/extensions-operations.json` y `contracts/extensions-security-matrix.json` (3 operaciones promovidas a `implemented` / `runtime_verified: true`), preservando intactas las 48 operaciones núcleo en `contracts/operations.json`.
- **Cierre ML v1.4.3 intacto:** no se modificó `services/ai_inference/`, `services/diagnosis/`, `ml/` ni `REAL_INFERENCE_AUTHORIZED=false`.

## Inventario de intents (16 registrados)

- **Habilitados USER y ADMIN (navegación, 6):** `OPEN_NEW_DIAGNOSIS -> NEW_DIAGNOSIS`, `OPEN_HISTORY -> HISTORY`, `OPEN_RESULTS -> RESULTS`, `OPEN_NOTIFICATIONS -> NOTIFICATIONS`, `OPEN_PROFILE -> PROFILE`, `OPEN_HELP -> HELP`.
- **Habilitados USER y ADMIN (explicación aprobada local, `action = null`, 4):** `EXPLAIN_CONFIDENCE`, `EXPLAIN_DIAGNOSIS_STATUS` (`PENDIENTE | PROCESANDO | COMPLETADO | NO_CONCLUYENTE | FALLIDO | CANCELADO`), `EXPLAIN_PHOTO_GUIDELINES`, `EXPLAIN_APP_USAGE`.
- **Habilitados ADMIN únicamente (navegación, 4):** `OPEN_USER_MANAGEMENT -> USER_MANAGEMENT`, `OPEN_PHYTOSANITARY_CATALOG -> PHYTOSANITARY_CATALOG`, `OPEN_RECOMMENDATIONS -> RECOMMENDATIONS`, `OPEN_DIAGNOSIS_SUPERVISION -> DIAGNOSIS_SUPERVISION`.
- **Diferidos ADMIN (`available = False`, `action = null`, 2):** `OPEN_AUDIT`, `OPEN_MONITORING`.

## Pruebas reproducibles ejecutadas

| Verificación | Comando | Resultado |
| --- | --- | --- |
| Validación de contratos núcleo + extensión y topología AMQP (Python 3.12 en contenedor) | `scripts/validate_contracts.py` + `unittest discover -s tests/contracts -v` | **PASS**: 4 OpenAPI núcleo (`48` ops), 1 OpenAPI extensión (`3` ops `implemented`), 694 ejemplos; `22/22` OK |
| Suite unitaria completa de `extensions/assistant/` (Python 3.12 en contenedor) | `python -m unittest discover -s /service/tests -v` en `agrodiagnostico-v1-assistant:latest` | **PASS**: `25/25` OK (`0.099 s`) — seguridad, JWT Ed25519, `413`, secretos `AT-19`, rate limit `429`, telemetría segura, 16 intents, RBAC `403`, prompt injection `AT-10`/`AT-11`, `AT-12`, `FakeAssistantAdapter`, `GeminiAdapter` (`httpx.MockTransport`), API E2E `AT-01`..`AT-19`, `AT-21` |
| Validación de configuración Compose y aislamiento de red/puertos | `docker compose -f docker-compose.yml [--profile assistant] --env-file .env.example config --quiet` + build `assistant nginx` | **PASS**: `assistant` sin `ports`, redes `['application', 'edge']`, sin `persistence` |
| Aceptación integrada E2E vía Nginx (`VERIFIED_FAKE`) | `python3 scripts/check_assistant_integration.py` | **PASS** (`41.172 s`, `project=agro-env-test-64e706f19639`): 6/6 bloques (degradación `503` sin perfil, JWT reales `USER`/`ADMIN`, aislamiento de red, navegación/explicaciones/RBAC/prompt injection/diferidos, `400`/`413`/`429`/`AT-19`, cero mutaciones en BD y cero fugas en logs + teardown limpio) |
| Regresión núcleo entorno integrado | `python3 scripts/check_environment.py` | **PASS** (`126.086 s`, `project=agro-env-test-0e693b813b2b`) |
| Regresión núcleo notificaciones E2E | `python3 scripts/check_notification_integration.py` | **PASS** (`44.633 s`, `project=agro-env-test-b7082e37a847`, 7/7 bloques) |
| Controles de CI, lint y OpenSpec | `python3 scripts/check_ci_tests.py`, `ruff check`, `git diff --check`, `openspec validate add-gemini-assistant --strict --no-interactive` | **PASS** |

## Operación y activación

- **Arranque núcleo habitual (sin asistente):** `docker compose up -d` — no requiere `GEMINI_API_KEY`; cualquier llamada a `/api/v1/assistant/messages` responde `503 ASSISTANT_UNAVAILABLE`.
- **Arranque con asistente en modo prueba determinista:** `ASSISTANT_ENABLED=true ASSISTANT_PROVIDER=fake docker compose --profile assistant up -d`
- **Arranque con Gemini real (requiere clave autorizada fuera de Git):** `ASSISTANT_ENABLED=true ASSISTANT_PROVIDER=gemini GEMINI_MODEL=gemini-2.5-flash GEMINI_API_KEY=<clave> docker compose --profile assistant up -d`
- **Smoke manual real (`AT-23`, `VERIFIED_REAL`):** `GEMINI_API_KEY=<clave> python3 scripts/check_gemini_real_smoke.py` (ejecutar con Python 3.12 dentro de `agrodiagnostico-v1-assistant:latest` o un entorno Python 3.12 con `httpx`/`pydantic`). Sin `GEMINI_API_KEY`, el script sale con código `2` (`SKIPPED_NO_CREDENTIALS`).

## Límites declarados

- **Integración Gemini en vivo (`AT-23`):** no ejecutada en este cierre por no disponer de `GEMINI_API_KEY` autorizada en el entorno local; no se declara `VERIFIED_REAL`.
- **Entorno Python del host:** el host usa Python 3.14.4 sin binario `python3.12` local; las validaciones de contratos y pruebas unitarias Python 3.12 se ejecutaron dentro de las imágenes Docker oficiales Python 3.12.14 del repositorio.
- **Rate limit en memoria:** adecuado para instancia única en Compose; en despliegue multi-réplica debe complementarse con limitación en Nginx o Cloudflare edge.
- **GitHub Actions remoto y despliegue productivo:** pendientes de autorización explícita de push/despliegue.
