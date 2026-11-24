# gemini-assistant Specification

## Purpose

Proveer una extensión de asistente conversacional textual desacoplada en español para orientación de uso, explicación de conceptos de la plataforma y navegación controlada, operando bajo el principio «Gemini interpreta; AgroDiagnóstico autoriza», completamente separada de la inferencia fitosanitaria oficial y sin condicionar la disponibilidad del núcleo.

## Requirements

### Requirement: Autenticación obligatoria y validación estricta de entrada
El sistema SHALL exigir una sesión de usuario autenticada válida mediante token JWT Ed25519 emitido por Identity antes de invocar cualquier proveedor del asistente en `POST /api/v1/assistant/messages`. La solicitud SHALL aceptar únicamente un objeto JSON cerrado con `message` obligatorio (cadena no vacía tras recortar espacios y longitud máxima `ASSISTANT_MAX_INPUT_CHARS`, inicialmente 2000 caracteres), rechazando campos adicionales, cuerpos vacíos, excedentes de tamaño de transporte o cabeceras de correlación inválidas antes de invocar al proveedor. Toda respuesta SHALL incluir `X-Correlation-ID` y `Cache-Control: private, no-store`.

#### Scenario: Acceso sin JWT o con token expirado o inválido
- **WHEN** una solicitud a `POST /api/v1/assistant/messages` llega sin cabecera `Authorization`, con token malformado, expirado, de emisor/audiencia inválidos o con token interno de servicio
- **THEN** el sistema responde `401` con el envelope de error estándar sin invocar al proveedor del asistente ni emitir acción

#### Scenario: Solicitud con esquema inválido o excedente de tamaño
- **WHEN** un usuario autenticado envía cuerpo vacío, espacios en blanco, campos no permitidos (como `role`, `user_id` o `permissions`), `message` superior al límite permitido o un payload HTTP superior al límite de transporte
- **THEN** el sistema responde `400` (o `413` al superar el límite de transporte) con el envelope de error estándar sin invocar al proveedor del asistente

#### Scenario: Límite de tasa excedido por identidad
- **WHEN** un usuario autenticado supera el presupuesto configurado de solicitudes dentro de la ventana de rate limit
- **THEN** el sistema responde `429` con el envelope de error estándar sin invocar al proveedor ni emitir acción

### Requirement: Navegación controlada y registro cerrado de intenciones
El sistema SHALL mantener un registro cerrado `intent -> target -> roles -> availability` y emitir acciones `{"type": "NAVIGATE", "target": "<TARGET>"}` únicamente cuando la salida del proveedor valide contra el esquema interno cerrado, corresponda a un intent de navegación habilitado y el usuario tenga autorización efectiva. Navegar SHALL NOT ejecutar mutaciones ni operaciones de negocio (como crear diagnósticos, modificar perfil o alterar catálogo). Destinos diferidos o no publicados (`OPEN_AUDIT`, `OPEN_MONITORING`) SHALL permanecer marcados como no disponibles y nunca SHALL emitir una acción ejecutable.

#### Scenario: Navegación autorizada para usuario estándar
- **WHEN** un usuario autenticado con rol `USER` envía «Llévame a mi historial», «Quiero hacer un nuevo diagnóstico» o «Quiero modificar mi perfil»
- **THEN** el sistema responde `200` con `status = "SUCCESS"`, el intent normalizado correspondiente (`OPEN_HISTORY`, `OPEN_NEW_DIAGNOSIS` o `OPEN_PROFILE`) y `action = {"type": "NAVIGATE", "target": "<TARGET>"}`, sin crear diagnósticos ni modificar datos

#### Scenario: Navegación administrativa autorizada para ADMIN sobre recurso disponible
- **WHEN** un usuario autenticado con rol `ADMIN` solicita gestión de usuarios, catálogo fitosanitario, recomendaciones o supervisión de diagnósticos
- **THEN** el sistema responde `200` con `status = "SUCCESS"`, el intent administrativo normalizado y el target autorizado correspondiente

#### Scenario: Destino administrativo diferido o no disponible
- **WHEN** un usuario con rol `ADMIN` solicita auditoría (`OPEN_AUDIT`) o monitoreo (`OPEN_MONITORING`) mientras sus capacidades siguen diferidas
- **THEN** el sistema no emite ninguna acción ejecutable (`action = null`) y devuelve una respuesta segura indicando indisponibilidad o ausencia del destino

#### Scenario: Solicitud ambigua o salida inválida del proveedor
- **WHEN** el mensaje del usuario es ambiguo o el proveedor devuelve un intent desconocido, una URL externa, SQL, múltiples acciones incompatibles o un JSON malformado
- **THEN** ante ambigüedad responde `200` con `status = "CLARIFICATION_REQUIRED"` y `action = null`, y ante salida inválida del proveedor rechaza la salida con `503` seguro y sin acción ejecutable

### Requirement: Autorización RBAC independiente del proveedor
El sistema SHALL evaluar el rol efectivo verificado desde el JWT localmente después de la interpretación del proveedor y SHALL denegar cualquier intención no autorizada independientemente de lo que proponga el proveedor o de intentos de manipulación de instrucciones (prompt injection).

#### Scenario: Usuario estándar solicita intención administrativa
- **WHEN** un usuario con rol `USER` solicita gestión de usuarios, catálogo, recomendaciones o supervisión, o el proveedor devuelve un intent administrativo para dicho usuario
- **THEN** el sistema responde `403` con el envelope de error estándar y sin acción ejecutable

#### Scenario: Intento de prompt injection para escalar privilegios
- **WHEN** un usuario con rol `USER` envía instrucciones intentando sobrescribir el prompt del sistema, asumir rol `ADMIN` o ejecutar mutaciones
- **THEN** el sistema conserva el rol verificado del JWT, deniega cualquier intento administrativo (`403`) o lo rechaza como fuera de alcance (`OUT_OF_SCOPE`) sin ejecutar mutaciones ni conceder privilegios

### Requirement: Separación estricta de la inferencia fitosanitaria oficial y explicaciones aprobadas
El asistente SHALL NOT realizar diagnósticos fitosanitarios, identificar enfermedades o plagas, emitir certezas clínicas ni modificar estados, resultados, políticas de publicación, catálogo o puertas de calidad del pipeline ML (`REAL_INFERENCE_AUTHORIZED=false`). Para los intents de explicación (`EXPLAIN_CONFIDENCE`, `EXPLAIN_DIAGNOSIS_STATUS`, `EXPLAIN_PHOTO_GUIDELINES`, `EXPLAIN_APP_USAGE`), el sistema SHALL responder `200` con `status = "SUCCESS"`, `action = null` y contenido aprobado por AgroDiagnóstico coherente con los estados oficiales (`PENDIENTE`, `PROCESANDO`, `COMPLETADO`, `NO_CONCLUYENTE`, `FALLIDO`, `CANCELADO`).

#### Scenario: Explicación de estado, confianza o guía fotográfica
- **WHEN** un usuario autenticado pregunta «¿Qué significa no concluyente?», «¿Qué significa la confianza?» o «¿Cómo tomo una buena fotografía?»
- **THEN** el sistema responde `200` con `status = "SUCCESS"`, `action = null` y la explicación aprobada sin afirmar certeza clínica ni inventar porcentajes o diagnósticos

#### Scenario: Solicitud de diagnóstico o modificación de resultado
- **WHEN** un usuario pide que el asistente identifique una enfermedad, recomiende dosis/tratamientos o modifique el resultado de un diagnóstico
- **THEN** el sistema responde `200` con `status = "OUT_OF_SCOPE"`, `action = null` y recuerda que el asistente no sustituye el flujo oficial ni a un profesional agronómico

### Requirement: Degradación segura y aislamiento desacoplado del núcleo
La capacidad del asistente SHALL operar como extensión desacoplada activable explícitamente mediante perfil de despliegue y desactivada por defecto (`ASSISTANT_ENABLED = false`). Su ausencia, desactivación, falta de credenciales, timeout o fallo del proveedor SHALL devolver respuestas de error controladas (`503` o `504` sin detalles crudos del proveedor) y nunca SHALL impedir el arranque, la salud ni el funcionamiento de Identity, Diagnosis, AI Inference, Notification o la navegación manual. En modo `gemini`, el sistema SHALL NOT sustituir silenciosamente el proveedor real por un proveedor falso.

#### Scenario: Asistente desactivado, perfil inactivo o credenciales ausentes
- **WHEN** el perfil de despliegue del asistente no está activo, `ASSISTANT_ENABLED = false` o falta `GEMINI_API_KEY` en modo `gemini`
- **THEN** los cuatro servicios núcleo y Nginx arrancan y operan con normalidad, y las llamadas a `POST /api/v1/assistant/messages` devuelven `503` controlado con envelope de error estándar sin filtrar secretos

#### Scenario: Timeout o fallo externo del proveedor
- **WHEN** el proveedor externo excede `ASSISTANT_TIMEOUT_SECONDS` o falla tras los reintentos acotados configurados
- **THEN** el sistema responde `504` (ante timeout) o `503` (ante error externo) sin acción ejecutable y sin degradar la disponibilidad del resto de la plataforma

### Requirement: Privacidad, redacción de secretos y telemetría segura
El sistema SHALL NOT conectar el servicio del asistente a las bases de datos, broker ni almacenamiento privado del núcleo, SHALL NOT persistir mensajes conversacionales por defecto ni transmitir al proveedor externo tokens, contraseñas, claves privadas o datos de otros usuarios. Si se detectan patrones de secretos o credenciales en el mensaje del usuario, el sistema SHALL rechazar o redactar el dato antes de invocar al proveedor. Los logs estructurados y métricas técnicas SHALL registrar únicamente metadatos seguros (`correlation_id`, rol, intent normalizado, estado/decisión, latencia y clase de error), sin prompts completos, texto del usuario, tokens ni respuestas crudas del proveedor.

#### Scenario: Mensaje de usuario contiene un secreto o token
- **WHEN** un usuario envía un mensaje que incluye un JWT (`eyJ...`), clave de API (`AIza...`), bloque PEM o credencial tipo `Bearer ...`
- **THEN** el sistema impide su transmisión al proveedor externo (rechazando con mensaje seguro o redactando antes de procesar) y nunca escribe el secreto en logs ni en la respuesta

#### Scenario: Observabilidad sin fuga de datos sensibles
- **WHEN** se procesa una solicitud exitosa o fallida del asistente
- **THEN** los logs estructurados contienen únicamente `correlation_id`, rol, intent normalizado, decisión, latencia y clase de error, excluyendo el texto del usuario, tokens JWT, `GEMINI_API_KEY` y la salida cruda del proveedor
