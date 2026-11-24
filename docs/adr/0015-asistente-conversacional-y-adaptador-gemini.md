# ADR-0015 — Extensión de asistente conversacional y adaptador Gemini

Fecha: 2026-11-23. Estado: adoptado para `add-gemini-assistant`.  
Tarea: 1.1 de `add-gemini-assistant`.

## Contexto

Los cuatro servicios núcleo de AgroDiagnóstico V1 (`identity`, `diagnosis`, `ai_inference` y `notification`) se encuentran implementados y verificados con 48/48 operaciones contractuales. El cierre experimental de IA v1.4.3 dejó `REAL_INFERENCE_AUTHORIZED=false` y el catálogo histórico sin promoción productiva, y la interfaz `frontend/` conserva aún el entorno técnico inicial del Incremento 0 a la espera del incremento completo de Frontend.

La definición base del proyecto (`Definicion_Base_AgroDiagnostico_V1.docx`, secciones 8.23–8.28, 9.20–9.24 y 10.41–10.44) y la especificación de entrada `docs/GEMINI_ASSISTANT_CONTRACT_V1.md` establecen la incorporación de un asistente conversacional textual en español para experiencia de usuario, explicación de conceptos de la plataforma y navegación controlada, bajo el principio rector **«Gemini interpreta; AgroDiagnóstico autoriza»**.

Restricciones arquitectónicas previas que condicionan esta decisión:
1. `AGENTS.md` y la definición base establecen cuatro microservicios núcleo (`identity`, `diagnosis`, `ai_inference`, `notification`) con propiedad estricta de datos; la capacidad de asistencia debe mantenerse separada de la inferencia fitosanitaria oficial y no puede condicionar el arranque del núcleo.
2. `openspec/specs/integrated-development-environment/spec.md` exige que el arranque por defecto de `docker-compose.yml` funcione sin servicios externos, sin credenciales Gemini y publicando únicamente `nginx` en loopback.
3. `scripts/validate_contracts.py` exige exactamente cuatro documentos OpenAPI núcleo (`contracts/openapi/*.openapi.json`) alineados con las 48 operaciones de `contracts/operations.json`.
4. La carpeta histórica `services/optional/gemini_assistant/.gitkeep` existía desde el Incremento 0 como marcador previo a la integración, pero al convertirse en una extensión integrada del repositorio requiere una ubicación profesional orientada a dominio y desacoplada del proveedor.

Trazabilidad normativa: ADR-0002 (interfaces V1), ADR-0004 (JWT Ed25519), ADR-0009/0012 (cierre experimental ML v1.4.3), ADR-0014 (notificaciones), `docs/GEMINI_ASSISTANT_CONTRACT_V1.md` (`INV-01`..`INV-10`, `AT-01`..`AT-24`) y el delta OpenSpec `openspec/changes/add-gemini-assistant/specs/gemini-assistant/spec.md`.

## Alternativas consideradas

### A. Ubicación física y nomenclatura del servicio
- **Alternativa A1 (descartada): Conservar `services/optional/gemini_assistant/`.** Mezcla en el nombre del directorio una política de despliegue («optional», que corresponde a perfiles y feature flags) con un proveedor concreto («gemini», cuando `GeminiAdapter` es solo un adaptador intercambiable).
- **Alternativa A2 (descartada): Colocarlo en `services/assistant/`.** Lo situaría al mismo nivel que los cuatro microservicios núcleo (`identity`, `diagnosis`, `ai_inference`, `notification`), difuminando la frontera arquitectónica de 4 servicios núcleo y arriesgando acoplamiento con scripts que asumen servicios núcleo bajo `services/`.
- **Alternativa A3 (descartada): Embeber el adaptador dentro de `services/diagnosis` o `services/identity`.** Introduciría egreso HTTP externo y credenciales de Gemini en un servicio núcleo con acceso a PostgreSQL, S3 o claves privadas de emisión de JWT, debilitando `INV-05`, `INV-06` e `INV-09`.
- **Alternativa A4 (adoptada): Extensión FastAPI sin estado en `extensions/assistant/` activable mediante `--profile assistant` (servicio Compose `assistant`).** Preserva `services/` estrictamente para los 4 servicios núcleo, desacopla el nombre de dominio del proveedor externo y retira de forma controlada el placeholder vacío `services/optional/gemini_assistant/.gitkeep` (dejando intactos `services/optional/voice/` y `services/optional/pest_detector/` por estar fuera de alcance).

### B. Integración con Google Gemini
- **Alternativa B1 (descartada): SDK con ejecución automática de herramientas (auto tool-calling).** Aumenta la superficie de dependencias y el riesgo de invocar funciones antes de validar esquema y autorización local.
- **Alternativa B2 (adoptada): Cliente HTTP explícito sobre `httpx` contra la API REST oficial de Gemini con `responseMimeType = "application/json"` y `responseSchema` cerrado.** Reutiliza `httpx` (ya estándar en el monorepo), deshabilita cualquier ejecución automática de herramientas, permite control estricto de timeouts/reintentos, envía `x-goog-api-key` únicamente por cabecera (nunca en query string) y habilita pruebas deterministas mediante `httpx.MockTransport`.

### C. Enrutamiento en Nginx cuando `--profile assistant` está inactivo
- **Alternativa C1 (descartada): Bloque `upstream assistant_backend { server assistant:8000; }` estático.** Causa fallo fatal al iniciar Nginx cuando `--profile assistant` no está activo, rompiendo el entorno núcleo por defecto.
- **Alternativa C2 (adoptada): Resolución DNS dinámica con `resolver 127.0.0.11 valid=10s ipv6=off;` y `set $assistant_upstream http://assistant:8000;` más fallback `@assistant_unavailable` devolviendo `503 ASSISTANT_UNAVAILABLE`.** Garantiza arranque sano de Nginx sin el perfil `assistant` y degradación segura uniforme (`INV-09`, `AT-21`).

### D. Código HTTP ante errores de validación de entrada
- **Alternativa D1 (descartada): Responder `422 Unprocessable Entity` como proponía el borrador.** Introduciría una divergencia con los 4 servicios núcleo (`identity`, `diagnosis`, `notification`), que utilizan `400 INVALID_REQUEST` con el envelope `common.schema.json#/$defs/Error`.
- **Alternativa D2 (adoptada): Unificar validación de esquema y entrada en `400 INVALID_REQUEST` (más `413 PAYLOAD_TOO_LARGE` para exceso de tamaño de transporte).** Cumple `docs/GEMINI_ASSISTANT_CONTRACT_V1.md` §2 y §6.3 («ajustar a las convenciones reales del repositorio» y «no crear un segundo estándar incompatible»).

## Decisiones

### D1. Aislamiento de extensión, redes y secretos
1. `extensions/assistant/` es un servicio FastAPI sin estado, sin base de datos propia, sin migraciones y sin acceso a PostgreSQL, RabbitMQ, Redis ni S3.
2. En `docker-compose.yml`, el servicio `assistant` se declara bajo `profiles: [assistant]`, sin puertos publicados (`ports` ausente), conectado únicamente a las redes `application` (tráfico desde `nginx`) y `edge` (egreso HTTPS hacia Gemini cuando `ASSISTANT_PROVIDER=gemini`). **Nunca** se conecta a la red `persistence` (cumplimiento físico de `INV-06`).
3. Monta exclusivamente la clave pública `jwt_public_key` (`read-only`) para verificar tokens de usuario y recibe `GEMINI_API_KEY` solo vía entorno o secreto de backend cuando se habilita modo real.

### D2. Contratos OpenAPI 3.1.1 de extensión sin alterar el inventario núcleo
1. Se crea `contracts/openapi/extensions/assistant.openapi.json` con tres operaciones:
   - `GET /health/live` (`assistant_live`, interna)
   - `GET /health/ready` (`assistant_ready`, interna; devuelve `503` si `ASSISTANT_ENABLED=false` o si falta `GEMINI_API_KEY`/`GEMINI_MODEL` en modo `gemini`)
   - `POST /api/v1/assistant/messages` (`assistant_send_message`, pública bajo Nginx, `UserBearer`)
2. Se añaden `contracts/extensions-operations.json`, `contracts/extensions-security-matrix.json` y los esquemas cerrados (`AssistantIntent`, `AssistantNavigationTarget`, `AssistantMessageRequest`, `AssistantAction`, `AssistantResponse`) en `contracts/schemas/common.schema.json`.
3. `contracts/openapi/*.openapi.json` conserva los 4 documentos núcleo y `contracts/operations.json` conserva sus 48 operaciones intactas; `scripts/validate_contracts.py` valida ambos conjuntos de forma independiente. Las tres operaciones de `assistant` nacen en estado `contract-only` (`runtime_verified: false`) y se promueven a `implemented` únicamente tras superar la aceptación integrada.

### D3. Contrato HTTP, envelope de error y códigos de estado
1. `POST /api/v1/assistant/messages` acepta únicamente `{"message": "<texto>"}` (`additionalProperties: false`, obligatorio no vacío tras `strip()`, máximo `ASSISTANT_MAX_INPUT_CHARS = 2000`, límite de transporte HTTP `16 KiB` en Nginx y FastAPI).
2. Toda respuesta incluye `X-Correlation-ID` (UUID eco o generado) y `Cache-Control: private, no-store`.
3. Códigos contractuales:
   - `200`: `AssistantResponse` (`{request_id, status, intent, message, action}`) para `SUCCESS`, `CLARIFICATION_REQUIRED` y `OUT_OF_SCOPE`.
   - `400 INVALID_REQUEST` / `SENSITIVE_INPUT_REJECTED`: esquema inválido, cuerpo vacío, campos extra, longitud excedida, `X-Correlation-ID` inválido o secreto detectado en la entrada.
   - `401 UNAUTHORIZED`: JWT ausente, inválido, expirado o token interno de servicio.
   - `403 FORBIDDEN`: intención administrativa solicitada por un usuario con rol `USER` (RBAC independiente).
   - `413 PAYLOAD_TOO_LARGE`: cuerpo excede el límite de transporte.
   - `429 RATE_LIMITED`: cuota por identidad excedida (incluye cabecera `Retry-After`).
   - `500 INTERNAL_ERROR`: fallo interno imprevisto sin detalles crudos.
   - `503 ASSISTANT_UNAVAILABLE`: servicio desactivado (`ASSISTANT_ENABLED=false`), perfil inactivo, credenciales ausentes en modo `gemini`, error externo o salida inválida del proveedor.
   - `504 ASSISTANT_TIMEOUT`: agotamiento de `ASSISTANT_TIMEOUT_SECONDS`.

### D4. Registro cerrado de intenciones y explicaciones aprobadas
Se fija un registro cerrado inmutable de 16 intents (`intent -> target -> roles -> availability`):
- **USER y ADMIN (`available = True`, navegación):** `OPEN_NEW_DIAGNOSIS -> NEW_DIAGNOSIS`, `OPEN_HISTORY -> HISTORY`, `OPEN_RESULTS -> RESULTS`, `OPEN_NOTIFICATIONS -> NOTIFICATIONS`, `OPEN_PROFILE -> PROFILE`, `OPEN_HELP -> HELP`.
- **USER y ADMIN (`available = True`, explicación aprobada con `action = null`):** `EXPLAIN_CONFIDENCE`, `EXPLAIN_DIAGNOSIS_STATUS` (parámetro opcional `status` validado contra `{PENDIENTE, PROCESANDO, COMPLETADO, NO_CONCLUYENTE, FALLIDO, CANCELADO}`), `EXPLAIN_PHOTO_GUIDELINES`, `EXPLAIN_APP_USAGE`.
- **ADMIN únicamente (`available = True`, navegación):** `OPEN_USER_MANAGEMENT -> USER_MANAGEMENT`, `OPEN_PHYTOSANITARY_CATALOG -> PHYTOSANITARY_CATALOG`, `OPEN_RECOMMENDATIONS -> RECOMMENDATIONS`, `OPEN_DIAGNOSIS_SUPERVISION -> DIAGNOSIS_SUPERVISION`.
- **ADMIN únicamente (`available = False`, diferidos hasta contratar `audit`/`metrics`/`model-info`):** `OPEN_AUDIT -> AUDIT`, `OPEN_MONITORING -> MONITORING`. Para `USER` responden `403 FORBIDDEN`; para `ADMIN` responden `200` con `status = "OUT_OF_SCOPE"` y `action = null` (cumpliendo `AT-09` sin emitir targets inexistentes).

Todas las respuestas de `EXPLAIN_*` provienen exclusivamente de plantillas aprobadas locales en español coherentes con el cierre histórico ML v1.4.3 (`REAL_INFERENCE_AUTHORIZED=false`), nunca de afirmaciones clínicas libres generadas por el modelo externo (`INV-08`, `INV-10`).

### D5. Adaptadores de proveedor y prohibición de fallback silencioso
1. `AssistantProvider.interpret(message, safe_context) -> AssistantCandidate` desacopla el dominio del proveedor.
2. `FakeAssistantAdapter` provee interpretación determinista en español para pruebas automatizadas (`VERIFIED_FAKE`) y demos controladas.
3. `GeminiAdapter` invoca `https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent` con `responseSchema` cerrado, `systemInstruction` fija, `maxOutputTokens = ASSISTANT_MAX_OUTPUT_TOKENS`, `x-goog-api-key` en cabecera, timeout total acotado (`ASSISTANT_TIMEOUT_SECONDS`, defecto `10 s`) y reintentos acotados (`ASSISTANT_MAX_RETRIES`, defecto `1` solo ante fallos transitorios dentro del presupuesto).
4. En modo `ASSISTANT_PROVIDER=gemini`, la ausencia de `GEMINI_API_KEY` o `GEMINI_MODEL` o un fallo del proveedor **nunca** activa `FakeAssistantAdapter` de forma silenciosa; el sistema degrada devolviendo `503` o `504`.

### D6. Frontera de seguridad, privacidad y telemetría
1. Verificación JWT Ed25519 independiente con `jwt_public_key.pem` (`iss = agrodiagnostico-identity`, `aud = agrodiagnostico-api`, `sub` UUID, `role in {USER, ADMIN}`); tokens de servicio internos se rechazan con `401`.
2. Detección previa de secretos en la entrada (`eyJ...`, `AIza...`, `Bearer ...`, bloques `PRIVATE KEY`, patrones `password=`/`api_key=`/`secret=`): rechaza con `400 SENSITIVE_INPUT_REJECTED` antes de invocar al proveedor (`AT-19`).
3. Rate limiter por identidad (`sub`) en memoria con ventana deslizante (`ASSISTANT_RATE_LIMIT`, por defecto `20/60s`) sin dependencia de Redis.
4. Logs estructurados con únicamente `correlation_id`, `role`, `intent`, `decision`, `http_status`, `latency_ms`, `provider` y `error_class`, prohibiendo registrar el mensaje del usuario, prompts, tokens, `GEMINI_API_KEY` o salida cruda del proveedor.

### D7. Alcance diferido y clasificación de evidencia
1. La interfaz conversacional React y guards de navegación cliente (`AT-20` UI) quedan explícitamente para el incremento de Frontend completo (Paso 3), cuando existan login, sesión y enrutador real.
2. La capacidad de voz (`AT-24`) permanece diferida.
3. Las evidencias distinguirán estrictamente `IMPLEMENTED`, `VERIFIED_FAKE`, `VERIFIED_REAL` (solo si el operador ejecuta `scripts/check_gemini_real_smoke.py` con `GEMINI_API_KEY` autorizada) y `DEFERRED`.

## Consecuencias

### Positivas
- Mantiene la arquitectura núcleo de 4 microservicios limpia e intacta bajo `services/` mientras ubica las capacidades extensibles en `extensions/` con nombres de dominio independientes del proveedor.
- Garantiza aislamiento físico de datos (`persistence` inaccesible), autorización independiente del modelo y degradación segura `503`/`504` sin afectar diagnósticos ni pruebas existentes.
- Congela un contrato OpenAPI 3.1.1 cerrado y verificado para el futuro cliente React del Paso 3.

### Negativas / Restricciones
- El limitador de tasa en memoria es local a la instancia de `assistant`; en despliegues horizontales con múltiples réplicas deberá complementarse en Nginx o Cloudflare edge.
- `OPEN_AUDIT` y `OPEN_MONITORING` permanecen sin acción ejecutable hasta que las capacidades administrativas diferidas (`audit`, `metrics`, `model-info`) se contraten e implementen.
- La certificación `VERIFIED_REAL` (`AT-23`) depende de ejecutar el smoke opt-in con una `GEMINI_API_KEY` válida y salida a Internet autorizada; la CI determinista valida únicamente `VERIFIED_FAKE` y `GeminiAdapter` con transporte HTTP simulado.
