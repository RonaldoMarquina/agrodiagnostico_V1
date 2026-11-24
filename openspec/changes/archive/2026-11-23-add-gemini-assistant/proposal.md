# Proposal

## Why

Los cuatro servicios núcleo de AgroDiagnóstico V1 (`identity`, `diagnosis`, `ai_inference` y `notification`) ya están implementados y verificados con 48/48 operaciones contractuales, y la definición base del proyecto (secciones 8.23–8.28, 9.20–9.24 y 10.41–10.44) junto con `docs/GEMINI_ASSISTANT_CONTRACT_V1.md` contemplan un asistente conversacional en español como extensión de experiencia de usuario, explicación y navegación controlada. Incorporar el backend del asistente ahora como extensión aislada y sin estado en `extensions/assistant/` permite formalizar su contrato, políticas de autorización independiente y adaptadores (`fake` y `gemini` real) antes de construir la interfaz React completa en el siguiente incremento, desacoplando la ruta del proveedor y garantizando que el asistente nunca realice diagnósticos fitosanitarios oficiales ni afecte la disponibilidad del núcleo.

## What Changes

- **ADR arquitectónico (`docs/adr/0015-asistente-conversacional-y-adaptador-gemini.md`):** Formaliza la ubicación del servicio como extensión de experiencia de usuario desacoplada y sin estado en `extensions/assistant/` (retirando el placeholder histórico `services/optional/gemini_assistant/.gitkeep`), activable mediante el perfil Docker Compose `--profile assistant`, manteniendo `services/` reservado a los cuatro microservicios núcleo en el arranque por defecto, la frontera de confianza («Gemini interpreta; AgroDiagnóstico autoriza»), la política cerrada de intents/targets, la degradación segura y la privacidad.
- **Contrato formal OpenAPI 3.1.1 de extensión (`contracts/openapi/extensions/assistant.openapi.json`) y extensión de validación (`scripts/validate_contracts.py`, `tests/contracts/`):** Contrata `POST /api/v1/assistant/messages` (`operationId: assistant_send_message`) y salud interna (`/health/live`, `/health/ready`) reutilizando el envelope de error estándar (`contracts/schemas/common.schema.json#/$defs/Error`), cabeceras `X-Correlation-ID` y `Cache-Control: private, no-store`, esquema cerrado de entrada/salida y matriz de seguridad de extensiones (`contracts/extensions-operations.json`, `contracts/extensions-security-matrix.json`), sin alterar las 48 operaciones núcleo existentes.
- **Extensión `extensions/assistant/` (FastAPI, Python 3.12, `uv.lock`):**
  - Verificación independiente de JWT Ed25519 emitidos por `identity` (`jwt_public_key.pem`, `iss = agrodiagnostico-identity`, `aud = agrodiagnostico-api`), middleware de correlación y límite de tamaño de transporte (`413`) más validación cerrada de esquema (`400`, longitud máxima `ASSISTANT_MAX_INPUT_CHARS = 2000`).
  - Sanitización/rechazo de secretos detectados en la entrada antes de invocar al proveedor y limitador de tasa por identidad (`ASSISTANT_RATE_LIMIT`, respuesta `429`).
  - Registro cerrado `intent -> target -> roles -> availability` con los 16 intents de `docs/GEMINI_ASSISTANT_CONTRACT_V1.md`, distinguiendo explícitamente los 14 habilitados (navegación sobre capacidades existentes + 4 explicaciones aprobadas) de los 2 diferidos (`OPEN_AUDIT`, `OPEN_MONITORING`, con `available = false` mientras sus APIs administrativas sigan diferidas en `contracts/deferred-operations.json`).
  - Interfaz `AssistantProvider` con `FakeAssistantAdapter` (determinista para pruebas/CI, nunca silencioso en modo real) y `GeminiAdapter` (integración real contra Gemini API con salida estructurada controlada, timeout finito `504`, reintentos acotados y sin ejecución automática de herramientas).
  - Contenidos aprobados locales para `EXPLAIN_CONFIDENCE`, `EXPLAIN_DIAGNOSIS_STATUS`, `EXPLAIN_PHOTO_GUIDELINES` y `EXPLAIN_APP_USAGE` alineados con los estados oficiales y el cierre histórico v1.4.3 (`REAL_INFERENCE_AUTHORIZED=false`).
  - Logs estructurados sin PII/secretos/prompts crudos y métricas técnicas en memoria sin degradar la readiness del núcleo.
- **Infraestructura de despliegue condicional en Compose y Nginx:**
  - Añadir el servicio `assistant` en `docker-compose.yml` bajo `profiles: [assistant]`, sin puertos publicados, sin conexión a la red `persistence` (aislamiento físico de PostgreSQL/RabbitMQ/Redis/S3), montando únicamente `jwt_public_key` y credencial opcional `GEMINI_API_KEY` vía archivo o variable de entorno cuando se habilite modo real.
  - Enrutar `POST /api/v1/assistant/messages` en `infra/nginx/default.conf` mediante resolución DNS dinámica (`127.0.0.11`, destino `http://assistant:8000`) y fallback `503 ASSISTANT_UNAVAILABLE` cuando `--profile assistant` no esté activo, garantizando que el arranque núcleo por defecto y las pruebas existentes no requieran la extensión ni credenciales Gemini.
- **Pruebas unitarias, integración E2E determinista y smoke opcional real:**
  - Suite unitaria completa cubriendo AT-01..AT-19 y AT-21..AT-22 (incluyendo RBAC independiente, prompt injection, salida malformada/URL/SQL del proveedor, rate limit, timeout, sanitización de secretos y `GeminiAdapter` con transporte HTTP simulado).
  - Script de aceptación integrada `scripts/check_assistant_integration.py` (proyecto Compose desechable con `--profile assistant` y verificación de degradación `503` sin perfil) más smoke manual opt-in `scripts/check_gemini_real_smoke.py` para AT-23 cuando el operador aporte `GEMINI_API_KEY` autorizada.
- **Alcance diferido explícitamente (fuera de este cambio):**
  - Interfaz conversacional React y guards de router cliente (AT-20 UI): se implementan en el siguiente incremento de Frontend completo (`frontend/` aún contiene solo la pantalla técnica base del Incremento 0 sin autenticación ni enrutador).
  - Capacidad de voz (AT-24): permanece diferida (`services/optional/voice/` no se modifica en este cambio).
  - Persistencia de historial conversacional, RAG, streaming o envío de imágenes al proveedor: excluidos por invariantes de V1.

## Capabilities

### New Capabilities
- `gemini-assistant`: Extensión de asistente conversacional textual desacoplada en español para experiencia de usuario, explicación y navegación controlada, autenticada mediante JWT de Identity, con validación estricta de salida del proveedor, autorización RBAC independiente, degradación segura y separación total de la inferencia fitosanitaria oficial.

### Modified Capabilities
<!-- Ninguna capacidad núcleo existente modifica sus requisitos normativos; el perfil por defecto conserva su comportamiento intacto. -->

## Impact

- **Nueva extensión:** `extensions/assistant/` (paquete FastAPI, `pyproject.toml`, `uv.lock`, `Dockerfile` y pruebas) y retiro controlado del placeholder vacío `services/optional/gemini_assistant/.gitkeep`.
- **Contratos y validación:** Nuevo `contracts/openapi/extensions/assistant.openapi.json`, `contracts/extensions-operations.json` y `contracts/extensions-security-matrix.json`; actualización retrocompatible de `scripts/validate_contracts.py` y `tests/contracts/`.
- **Infraestructura:** `docker-compose.yml` (servicio `assistant` bajo `profiles: [assistant]` sin `persistence`), `infra/nginx/default.conf` (resolución dinámica + fallback `503`), `.env.example` (variables de activación deshabilitadas por defecto `ASSISTANT_ENABLED=false`).
- **Verificación y documentación:** `docs/adr/0015-asistente-conversacional-y-adaptador-gemini.md`, `scripts/check_assistant_integration.py`, `scripts/check_gemini_real_smoke.py`, `docs/API_CONTRACTS.md`, `docs/Incrementos.md`, `openspec/config.yaml` (nota de contexto `extensions/`) y evidencia en `docs/evidence/`.
- **Sin impacto en núcleo ni ML:** No se modifican `services/identity/`, `services/diagnosis/`, `services/ai_inference/`, `services/notification/`, `frontend/` ni los artefactos/gates del cierre ML v1.4.3 (`REAL_INFERENCE_AUTHORIZED=false`).
