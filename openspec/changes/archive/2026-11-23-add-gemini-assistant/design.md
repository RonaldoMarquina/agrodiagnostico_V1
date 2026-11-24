# Design

## Context

Los cuatro servicios núcleo (`identity`, `diagnosis`, `ai_inference`, `notification`) están implementados y verificados con 48/48 operaciones contractuales, mientras `frontend/` contiene todavía únicamente la pantalla técnica base del Incremento 0 (`App.tsx`, 13 líneas, sin autenticación ni enrutador). Véase `proposal.md` para la motivación y el alcance.

Restricciones vigentes del repositorio que condicionan este diseño:
- `AGENTS.md` establece cuatro servicios núcleo con propiedad estricta de datos; `services/optional/` está fuera del MVP obligatorio y no puede ser dependencia del arranque principal.
- `openspec/specs/integrated-development-environment/spec.md` exige que el arranque por defecto de `docker-compose.yml` funcione sin servicios opcionales ni credenciales externas, y que solo `nginx` publique puertos en loopback.
- `scripts/validate_contracts.py` exige exactamente cuatro documentos OpenAPI núcleo en `contracts/openapi/*.openapi.json` y verifica su consistencia contra `contracts/operations.json`.
- El cierre experimental ML v1.4.3 mantiene `REAL_INFERENCE_AUTHORIZED=false` y catálogo histórico sin promoción; el asistente no puede tocar `services/ai_inference/`, `services/diagnosis/` ni `ml/`.
- `docs/GEMINI_ASSISTANT_CONTRACT_V1.md` define 10 invariantes (`INV-01`..`INV-10`), 16 intents conceptuales y la matriz de aceptación `AT-01`..`AT-24`, solicitando adaptar nombres, códigos y ubicación a las convenciones reales del repositorio mediante ADR.

## Goals / Non-Goals

**Goals:**
- Aislamiento completo del asistente como extensión sin estado orientada a dominio (`extensions/assistant/`) activada solo mediante `docker compose --profile assistant`.
- Frontera de confianza estricta: verificación local de JWT Ed25519, validación de entrada/secretos, rate limit local por identidad, validación cerrada de salida del proveedor, autorización RBAC independiente y contenido aprobado local para explicaciones.
- Contrato OpenAPI 3.1.1 de extensión (`contracts/openapi/extensions/assistant.openapi.json`) formalizado y validado automáticamente sin romper ni mezclar las 48 operaciones núcleo.
- Integración Nginx con resolución dinámica (`http://assistant:8000`) para que la ausencia de `assistant` en el perfil por defecto nunca impida iniciar Nginx y devuelva `503 ASSISTANT_UNAVAILABLE`.
- Separación explícita entre verificación determinista (`FakeAssistantAdapter` → `VERIFIED_FAKE`), pruebas del adaptador `GeminiAdapter` con transporte HTTP simulado y prueba manual opt-in real (`VERIFIED_REAL` solo con `GEMINI_API_KEY`).

**Non-Goals:**
- Interfaz conversacional React y guards de router cliente (`AT-20` UI): quedan para el siguiente incremento de Frontend completo (Paso 3), cuando existan login, sesión, enrutador y pantallas reales.
- Persistencia de conversaciones, base de datos propia, RAG, streaming SSE/WebSocket, envío de fotografías al proveedor o capacidad de voz (`AT-24`).
- Modificación de `services/identity/`, `services/diagnosis/`, `services/ai_inference/`, `services/notification/` o `ml/`.

## Decisions

### D1. Ubicación física, nomenclatura orientada a dominio y aislamiento de red (ADR-0015)
- **Decisión:** Implementar el asistente como extensión FastAPI sin estado en `extensions/assistant/`, declarada en `docker-compose.yml` con el nombre de servicio `assistant` bajo `profiles: [assistant]`, sin puertos publicados y conectada únicamente a las redes `application` (para recibir tráfico de `nginx`) y `edge` (para permitir HTTPS saliente hacia `generativelanguage.googleapis.com` cuando `ASSISTANT_PROVIDER=gemini`). **No** se conecta a la red `persistence`. El placeholder histórico vacío `services/optional/gemini_assistant/.gitkeep` se retira de forma controlada al crear `extensions/assistant/`.
- **Alternativas descartadas:**
  - *Mantener `services/optional/gemini_assistant/`:* acopla la ruta tanto a una condición de despliegue («optional», que pertenece a perfiles/feature flags y no a la taxonomía del código) como a un proveedor específico («gemini», cuando `GeminiAdapter` es solo un adaptador intercambiable).
  - *Colocarlo en `services/assistant/`:* lo situaría al mismo nivel que `identity`, `diagnosis`, `ai_inference` y `notification`, difuminando la regla de 4 microservicios núcleo de la definición base y de `docs/GEMINI_ASSISTANT_CONTRACT_V1.md`.
  - *Embeber el adaptador dentro de `services/diagnosis` o `services/identity`:* acoplaría el egreso externo de Gemini a un servicio núcleo con acceso a PostgreSQL/S3/claves privadas de firma, debilitando `INV-05`, `INV-06` e `INV-09`.
  - *Dejarlo solo en `application` (`internal: true`):* impediría llamadas HTTPS salientes a la API real de Gemini en modo `gemini`. Conectar `application` + `edge` sin `ports:` mantiene el aislamiento de entrada (solo vía Nginx) y el aislamiento físico de `persistence` (sin acceso a PostgreSQL, RabbitMQ, Redis ni S3).

### D2. Enrutamiento Nginx tolerante a perfil inactivo
- **Decisión:** Configurar en `infra/nginx/default.conf` una ubicación `location = /api/v1/assistant/messages` con `client_max_body_size 16k`, `resolver 127.0.0.11 valid=10s ipv6=off;`, destino en variable `set $assistant_upstream http://assistant:8000; proxy_pass $assistant_upstream;` y `proxy_intercept_errors off;` junto con `error_page 502 503 504 = @assistant_unavailable;` únicamente cuando Nginx no pueda conectar con el upstream (por ejemplo, si el perfil `assistant` no está levantado). El bloque `@assistant_unavailable` devuelve JSON `503` con el envelope estándar `{"code":"ASSISTANT_UNAVAILABLE","message":"El asistente no está disponible en este momento. Puedes continuar usando la navegación manual.","correlation_id":"$correlation_header"}` y `Cache-Control: private, no-store`.
- **Alternativas descartadas:**
  - *`upstream assistant_backend { server assistant:8000; }` estático:* provoca fallo fatal al arrancar Nginx (`host not found in upstream`) cuando `--profile assistant` no está activo, rompiendo `check_environment.py`, `check_async_acceptance.py` y `check_notification_integration.py`.
  - *Devolver `404 NOT_IMPLEMENTED` cuando está apagado:* contradice `INV-09` y `AT-21` que esperan `503` degradado con guía de navegación manual.

### D3. Contrato OpenAPI de extensión y alineación de errores HTTP
- **Decisión:**
  - Crear `contracts/openapi/extensions/assistant.openapi.json` (OpenAPI 3.1.1 JSON, siguiendo el formato del repositorio) con `/health/live`, `/health/ready` y `POST /api/v1/assistant/messages` (`operationId: assistant_send_message`, `x-owner: assistant`, `x-extension: true`), más el inventario `contracts/extensions-operations.json` y `contracts/extensions-security-matrix.json`.
  - Mantener `contracts/openapi/*.openapi.json` con exactamente los 4 documentos núcleo y `contracts/operations.json` con las 48 operaciones núcleo intactas. Extender `scripts/validate_contracts.py` para validar además cualquier documento bajo `contracts/openapi/extensions/*.openapi.json` contra `extensions-operations.json` y reportar `extension_operations` por separado.
  - Alinear errores al envelope `contracts/schemas/common.schema.json#/$defs/Error` (`{code, message, correlation_id, details?}`):
    - `200`: `AssistantResponse` (`{request_id, status, intent, message, action}`) para `SUCCESS`, `CLARIFICATION_REQUIRED` y `OUT_OF_SCOPE`.
    - `400 INVALID_REQUEST`: JSON inválido, cuerpo vacío, campos extra, `message` vacío o > `ASSISTANT_MAX_INPUT_CHARS`, o `X-Correlation-ID` inválido (reemplazando la propuesta `422` del borrador para mantener consistencia total con Identity/Diagnosis/Notification).
    - `401 UNAUTHORIZED`: JWT ausente, inválido, expirado o token interno de servicio.
    - `403 FORBIDDEN`: intención administrativa solicitada por `USER` (RBAC independiente).
    - `413 PAYLOAD_TOO_LARGE`: cuerpo HTTP excede el límite de transporte (`16 KiB`).
    - `429 RATE_LIMITED`: excede `ASSISTANT_RATE_LIMIT` (incluye `Retry-After`).
    - `500 INTERNAL_ERROR`: fallo interno imprevisto sin fuga de trazas.
    - `503 ASSISTANT_UNAVAILABLE`: `ASSISTANT_ENABLED=false`, proveedor `gemini` sin `GEMINI_API_KEY`/`GEMINI_MODEL`, error del proveedor o salida inválida/malformada del proveedor.
    - `504 ASSISTANT_TIMEOUT`: vencimiento de `ASSISTANT_TIMEOUT_SECONDS`.
- **Alternativas descartadas:**
  - *Usar `.yaml` en `contracts/openapi/gemini_assistant.yaml`:* rompería la convención JSON 3.1.1 y el validador offline `validate_contracts.py` (que exige 4 documentos núcleo `.openapi.json`).
  - *Añadir `assistant_send_message` a `contracts/operations.json` (49 operaciones):* mezclaría una extensión opcional con el inventario obligatorio V1.

### D4. Registro cerrado de intenciones, estados y contenidos aprobados
- **Decisión:** Definir un registro inmutable en `extensions/assistant/app/domain/registry.py` con los 16 intents de `docs/GEMINI_ASSISTANT_CONTRACT_V1.md`:
  - **USER y ADMIN (navegación, `available = True`):** `OPEN_NEW_DIAGNOSIS -> NEW_DIAGNOSIS`, `OPEN_HISTORY -> HISTORY`, `OPEN_RESULTS -> RESULTS`, `OPEN_NOTIFICATIONS -> NOTIFICATIONS`, `OPEN_PROFILE -> PROFILE`, `OPEN_HELP -> HELP`.
  - **USER y ADMIN (explicación aprobada, `target = None`, `available = True`):** `EXPLAIN_CONFIDENCE`, `EXPLAIN_DIAGNOSIS_STATUS` (parámetro opcional `status` validado contra el enum cerrado `{PENDIENTE, PROCESANDO, COMPLETADO, NO_CONCLUYENTE, FALLIDO, CANCELADO}`), `EXPLAIN_PHOTO_GUIDELINES`, `EXPLAIN_APP_USAGE`.
  - **ADMIN únicamente (navegación, `available = True`):** `OPEN_USER_MANAGEMENT -> USER_MANAGEMENT`, `OPEN_PHYTOSANITARY_CATALOG -> PHYTOSANITARY_CATALOG`, `OPEN_RECOMMENDATIONS -> RECOMMENDATIONS`, `OPEN_DIAGNOSIS_SUPERVISION -> DIAGNOSIS_SUPERVISION`.
  - **ADMIN únicamente (diferidos, `available = False`):** `OPEN_AUDIT -> AUDIT` (`deferred: audit`), `OPEN_MONITORING -> MONITORING` (`deferred: metrics/model-info`). Cuando un `USER` los solicita recibe `403 FORBIDDEN`; cuando un `ADMIN` los solicita, al estar `available = False`, el servicio responde `200` con `status = "OUT_OF_SCOPE"` (o `UNAVAILABLE` sin acción — fijamos `503 ASSISTANT_UNAVAILABLE` o `200 OUT_OF_SCOPE` con `action = null`: elegir `200` con `status = "OUT_OF_SCOPE"`, `intent = "OPEN_AUDIT" | "OPEN_MONITORING"`, `action = null` y mensaje claro indicando que el módulo aún no está publicado en esta versión, evitando confundir módulo diferido con caída del proveedor y satisfaciendo AT-09 «Sin acción; rechazo o indisponibilidad según caso»).
- Para todos los intents de explicación (`EXPLAIN_*`), el texto final devuelto al usuario **procede siempre de plantillas aprobadas locales en español** (nunca texto libre no verificado del LLM), garantizando `INV-08` e `INV-10` (sin garantías de certeza, sin porcentajes inventados, sin tratamientos ni diagnósticos fitosanitarios).

### D5. Abstracción de proveedores (`AssistantProvider`), `GeminiAdapter` y salida estructurada
- **Decisión:**
  - Definir `AssistantProvider.interpret(message: str, safe_context: SafeContext) -> AssistantCandidate` donde `AssistantCandidate` es un modelo Pydantic estricto (`extra="forbid"`) con `{disposition: "INTENT" | "CLARIFICATION_REQUIRED" | "OUT_OF_SCOPE", intent: str | None, parameters: dict, message: str}`.
  - `FakeAssistantAdapter`: determinista por reglas en español para los 16 intents, ambigüedad, fuera de alcance (diagnóstico/dosis/tratamientos) y ganchos de prueba únicamente en tests unitarios/inyectables (nunca activables por el usuario vía HTTP) para simular salida malformada, URL, SQL, timeout o propuesta de intent administrativo para `USER` (`AT-11`, `AT-12`, `AT-15`).
  - `GeminiAdapter`: cliente HTTP explícito sobre `httpx` contra la API REST oficial de Google Gemini (`https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent`) usando `generationConfig.responseMimeType = "application/json"` y `responseSchema` cerrado (sin ejecución automática de herramientas), enviando la clave exclusivamente en cabecera `x-goog-api-key` (nunca en query string para evitar fugas en URLs/logs), con `systemInstruction` fija, `maxOutputTokens = ASSISTANT_MAX_OUTPUT_TOKENS`, timeout total acotado por `ASSISTANT_TIMEOUT_SECONDS` (defecto `10 s`) y `ASSISTANT_MAX_RETRIES` (defecto `1`, solo en errores transitorios 429/5xx de red dentro del presupuesto de tiempo). Modelo configurable vía `GEMINI_MODEL` (defecto configurable `gemini-2.5-flash`, documentado como sujeto a comprobación con cuenta real en AT-23).
  - **Sin fallback silencioso:** Si `ASSISTANT_PROVIDER=gemini` y falta `GEMINI_API_KEY` o `GEMINI_MODEL`, `/health/ready` y `POST /api/v1/assistant/messages` devuelven `503` (jamás cae silenciosamente a `fake`).
- **Alternativas descartadas:**
  - *Dependencia pesada de SDK con auto-tool-calling:* añade superficie innecesaria y riesgo de ejecución automática no deseada; usar `httpx` (ya estándar en todo el monorepo) con `responseSchema` estricto simplifica auditoría, timeout total, testing con `httpx.MockTransport` y mantiene `uv.lock` liviano y determinista.

### D6. Seguridad, redacción de secretos, rate limit y telemetría
- **Decisión:**
  - **JWT:** Reutilizar el patrón Ed25519 verificado en `services/notification/app/infrastructure/tokens.py` (`jwt_public_key.pem`, `EdDSA`, `iss = agrodiagnostico-identity`, `aud = agrodiagnostico-api`, `sub` UUID, `role in {USER, ADMIN}`). Rechazar tokens sin firma, expirados o emitidos por `agrodiagnostico-internal` (`401`).
  - **Detección de secretos en entrada:** Antes de invocar al proveedor, inspeccionar `message` con detectores deterministas (JWT `eyJ...`, claves Google `AIza...`, cabeceras `Bearer ...`, bloques `-----BEGIN ... PRIVATE KEY-----`, patrones `password=`/`api_key=`/`secret=`). Si se detecta un secreto, rechazar la solicitud antes de llamar al proveedor devolviendo `400 INVALID_REQUEST` (`code = "SENSITIVE_INPUT_REJECTED"`, mensaje seguro indicando no incluir tokens ni credenciales) y nunca registrar el texto en logs (`AT-19`, `INV-05`).
  - **Rate limit por identidad:** Ventana deslizante en memoria indexada por `sub` (configurable vía `ASSISTANT_RATE_LIMIT`, ej. `20/60s` por defecto), protegida con `threading.Lock`, respondiendo `429 RATE_LIMITED` con `Retry-After` sin tocar Redis ni `persistence`.
  - **Observabilidad segura:** Logs JSON estructurados con `correlation_id`, `role`, `intent`, `decision`, `http_status`, `latency_ms`, `provider`, `error_class` (jamás `message`, prompt, salida cruda del proveedor, JWT ni `GEMINI_API_KEY`). Contadores en memoria expuestos solo internamente si se requieren en pruebas (sin etiqueta `user_id`), sin degradar `/health/ready` del núcleo.

## Risks / Trade-offs

- **[Riesgo] Límite de tasa en memoria no compartido entre múltiples réplicas** → *Mitigación:* En V1 (`docker-compose.yml`) corre una única instancia opcional; se documenta en ADR-0015 que en despliegues horizontales el rate limit debe complementarse en Nginx/Cloudflare edge.
- **[Riesgo] `frontend/` aún no tiene UI conversacional ni enrutador (Paso 3)** → *Mitigación:* Se deja explícitamente documentado que `AT-20` (guards cliente en React) corresponde al incremento de Frontend completo; el backend congela ya el contrato `target` cerrado y validado para que el cliente React solo mapee `target -> ruta real`.
- **[Riesgo] `AT-23` requiere `GEMINI_API_KEY` y acceso externo autorizados** → *Mitigación:* Separar estrictamente `VERIFIED_FAKE` (CI determinista), pruebas unitarias de `GeminiAdapter` con `httpx.MockTransport` y el script opt-in `scripts/check_gemini_real_smoke.py` (`VERIFIED_REAL` solo si se ejecuta con credencial real), reportando honestamente el estado alcanzado sin falsificar verificación real.
- **[Riesgo] Errores de resolución DNS en Nginx si `assistant` está apagado** → *Mitigación:* Verificar en `scripts/check_assistant_integration.py` ambos escenarios: stack núcleo sin `--profile assistant` (Nginx arranca sano y devuelve `503 ASSISTANT_UNAVAILABLE` en `/api/v1/assistant/messages`) y stack con `--profile assistant` (flujo completo E2E `200`/`401`/`403`/`400`/`429`).

## Migration Plan

- **Sin migraciones de base de datos:** `assistant` es completamente sin estado y no añade tablas, usuarios PostgreSQL ni colas RabbitMQ.
- **Despliegue / activación:**
  1. Arranque núcleo habitual (`docker compose up`): no inicia `assistant`, no requiere `GEMINI_API_KEY` y devuelve `503 ASSISTANT_UNAVAILABLE` ante llamadas al asistente.
  2. Arranque con asistente en modo prueba/demo: `ASSISTANT_ENABLED=true ASSISTANT_PROVIDER=fake docker compose --profile assistant up`.
  3. Arranque con Gemini real (requiere credencial externa autorizada en archivo secreto local o variable): `ASSISTANT_ENABLED=true ASSISTANT_PROVIDER=gemini GEMINI_MODEL=gemini-2.5-flash docker compose --profile assistant up`.
- **Rollback:** Detener el perfil (`docker compose --profile assistant stop assistant`) o fijar `ASSISTANT_ENABLED=false`; los cuatro servicios núcleo continúan operando sin impacto ni limpieza de datos.
