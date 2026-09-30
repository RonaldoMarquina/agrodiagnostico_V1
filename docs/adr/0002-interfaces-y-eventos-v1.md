# ADR-0002 — Interfaces, concurrencia y eventos V1

Fecha: 2026-09-28. Estado: decisiones adoptadas y contratos validados en el grupo 2; ejecución de negocio pendiente de sus incrementos.
Tarea: 1.3 de `incremento-0-base-integrada`.

## Contexto

Fuente entregada y discrepancias resueltas: [reconciliación](../reference/RECONCILIACION-V1.md), especialmente REC-02…09, REC-11…16. Secciones 2.5, 3 (RF), 5, 6.2–6.7, 7.7–7.12, 8.21/8.29, 9.9/9.12 y 10.5/10.8/10.23–31. Diseño D4 y deltas CTR-01…04. No hay contratos existentes ni consumidores implementados a los que romper compatibilidad.

## Decisión de interfaz HTTP

OpenAPI 3.1 y componentes comunes; JSON Schema 2020-12 para eventos, validadores bloqueados en implementación. Cada operación indica propietario, seguridad, errores, ejemplos e incremento. Comparar OpenAPI generado solo con el subconjunto realmente implementado (salud en 0). Un esquema no demuestra permisos en ejecución.

Se conserva el inventario local bajo `/api/v1/`: `/auth/*`, `/profile`, `/diagnoses`, `/notifications` y `/notification-preferences`. Las rutas del DOCX son conceptuales y ajustables (§6.2.2 P515): `/users/me` corresponde a `/profile`; forgot corresponde a password-recovery; estado puede consultarse en detalle sin ruta duplicada; preferencias se mantienen en el nombre local. No crear aliases innecesarios. La tabla de [API_CONTRACTS](../API_CONTRACTS.md) conserva las operaciones adicionales obligatorias y sus incrementos: cambio/confirmación de contraseña, feedback, lectura de aviso y administración. El grupo 1 no fija sus payloads ni crea handlers.

UUID para identificadores, fechas UTC, `X-Correlation-ID` y errores `{code,message,correlation_id,details?}`. Recursos propios requieren identidad y propiedad; ajeno/inexistente responde 404 genérico. ADMIN solo por rutas autorizadas y auditadas. Claim/renew/imagen interna requieren identidad de servicio, no basta conocer un ID o lease. Datos privados no entran en caché compartida.

Carga multipart con imagen, sin cultivo manual obligatorio (RF-07). Bytes, formato real y decodificación se validarán antes de persistir/publicar: fallo de transporte/archivo inválido devuelve 4xx sin evento; una imagen decodificable pero agronómicamente insuficiente puede terminar NO_CONCLUYENTE tras análisis. Objetivo de formatos V1: JPEG/PNG/WebP/HEIC/HEIF, estos últimos tras conversor y E2E. 10 MiB/24 MP son propuestas de configuración inicial, no cifras productivas probadas.

### Paginación e idempotencia propuestas

| Aspecto | Decisión para redactar el contrato | Verificación futura |
| --- | --- | --- |
| Paginación | Cursor opaco, límite inicial 20/máximo 100; orden estable por fecha e ID, filtros explícitos | Límites inválidos rechazados, cursor inválido, orden sin duplicación y aislamiento A/B |
| Clave de carga | Namespace propietario + operación + Idempotency-Key | Dos usuarios no comparten resultado por una clave igual |
| Misma clave/contenido | Fingerprint de bytes y campos semánticos; mismo diagnóstico e ID durante retención | Reenvío tras timeout no duplica fila/evento |
| Misma clave/distinto contenido | Conflicto 409, sin modificar diagnóstico previo | Ninguna transición o evento adicional |
| Retención | Propuesta local 24 h parametrizada; transcurrida la retención la clave puede iniciar solicitud nueva | Frontera temporal definida y comprobada antes de integrar clientes |

Estos valores son decisiones propuestas del diseño para el grupo 2, no valores aprobados por mediciones de producción. Los contratos deberán declarar los límites efectivos y la política de expiración; no extrapolar a retención de fotos, sesiones o backups. Autenticación usa tokens firmados, refresh revocable y cookie segura/CSRF según el flujo probado; algoritmo, issuer/audience y expiraciones requieren ADR de seguridad antes del incremento 1.

## Estados, lease y propiedad de decisión

Transiciones permitidas: `PENDIENTE → PROCESANDO → COMPLETADO | NO_CONCLUYENTE | FALLIDO`; `PENDIENTE → CANCELADO`. Claim y cancel compiten mediante actualización atómica: una sola gana. Terminales no se revierten; recuperación/replay no los revive. Diagnosis es dueño del estado visible y aplica clase soportada, confianza calibrada y catálogo versionado. AI solo produce análisis técnico. «NO CONCLUYENTE» es etiqueta humana; `NO_CONCLUYENTE` es estado técnico, nunca clase.

`lease_token` identifica una generación de reclamo (fencing). Se propone UUID opaco junto con owner y vencimiento. No es Access Token, Refresh Token ni credencial de servicio, y no autoriza por sí mismo. Operaciones internas requieren identidad de servicio y validación del lease vigente. Diagnosis ignora y audita análisis con token obsoleto o estado incompatible. Los eventos no llevan credenciales, URLs firmadas, bytes de fotografías ni contraseñas. Esta distinción resuelve la aparente contradicción con la prohibición de «tokens».

## Eventos y análisis normalizado

| Evento v1 | Emisor → consumidor | Campos mínimos y efecto |
| --- | --- | --- |
| DiagnosisRequested | Diagnosis → AI | diagnosis_id, owner_id, object_key privado; señal de trabajo, no permiso autónomo de lectura |
| DiagnosisAnalyzed | AI → Diagnosis | diagnosis_id, lease_token, crop_code, class_code?, raw_score?, outcome, reason_code?, model_id, model_version, dataset_version, inference_ms; análisis técnico, nunca recomendación |
| DiagnosisFinished | Diagnosis → Notification | diagnosis_id, owner_id, final_status: COMPLETADO, NO_CONCLUYENTE o FALLIDO; el resultado ya fue confirmado |

Envelope: event_id, event_type, schema_version, occurred_at, correlation_id, payload. `FALLIDO` se incluye conforme a §6.7 P739; RF-18 enumera un mínimo de avisos sin prohibir ese terminal. CANCELADO no genera Finished y nunca aviso de éxito.

Las variantes semánticas de `outcome` se documentan ahora; los literales y discriminadores definitivos se congelan en JSON Schema del grupo 2:

| Variante | Contenido exigido | Decisión posible de Diagnosis |
| --- | --- | --- |
| Predicción técnica | Clase/cultivo coherentes, score [0,1], versión real y duración | COMPLETADO solo con clase validada y política calibrada; en otro caso NO_CONCLUYENTE con motivo |
| Abstención técnica | Motivo de imagen/cobertura insuficiente; clase y score ausentes si no hay predicción; cultivo desconocido representable | NO_CONCLUYENTE con reason_code y recaptura; sin tratamiento específico |
| Fallo técnico definitivo | Motivo técnico general sin secretos; no inventar score/clase/modelo ejecutado | FALLIDO al validar lease, estado y política de intentos |

Para variantes sin cultivo o ejecución de modelo, el contrato deberá admitir explícitamente `null` en los campos requeridos que no se conozcan (crop_code y metadatos de modelo/duración según variante), distinguiendo ausencia de ejecución de valor cero. Nunca usar una versión inventada ni una clase NO_CONCLUYENTE. Un fallo transitorio se reintenta según política antes de producir resultado definitivo.

Mapeo de §8.29: crop → crop_code; predicted_class → class_code; confidence → raw_score; model_name → model_id; model_version se conserva; inference_time → inference_ms con unidad explícita; status → outcome técnico, no estado final de Diagnosis. `capability` corresponde implícitamente a clasificación de enfermedades en el evento v1 obligatorio; integrar otra capacidad exige revisar/versionar el contrato. dataset_version y lease_token añaden trazabilidad y concurrencia sin delegar la decisión de negocio a AI.

## Entrega y compatibilidad

Propuesta de exchange durable `agrodiagnostico.events`, routing `diagnosis.requested.v1`, `diagnosis.analyzed.v1`, `diagnosis.finished.v1`, colas por consumidor y DLQ. Se documenta aquí; no se configura broker en grupo 1.

Diagnosis confirma solicitud/outbox en una transacción. AI confirma análisis técnico/outbox en su base antes de ACK. Diagnosis confirma inbox, resultado, versión/snapshot y Finished/outbox en una transacción. Notification confirma deduplicación y aviso local antes de ACK; correo se intenta aparte. Los publicadores marcan entregado solo con confirmación del broker. Deduplicación por `(consumer,event_id)` y protección por diagnosis/lease impiden efectos lógicos repetidos; no se promete entrega exactamente una vez.

Tres intentos totales: inicial y hasta dos reintentos con espera para fallos temporales. Errores definitivos no se reintentan. Versiones incompatibles o payload inválido se aíslan sin ejecutar efectos; DLQ y replay autorizado no revierten terminales. Redis o correo caídos no modifican diagnósticos. Cambios incompatibles de significado/campos requieren nueva versión, revisión de ADR/OpenSpec y despliegue compatible.

## Matriz de garantías por incremento

| Garantía | Propietario | Incremento y verificación prevista |
| --- | --- | --- |
| Esquemas, ejemplos, índice contract-only/implemented | Contracts y servicios | 0/grupo 2: positivos/negativos y referencias |
| Auth, sesiones, roles, cambio y recuperación de contraseña | Identity | 1: tokens inválidos/revocados, RBAC, recuperación completa |
| Carga privada, límites, formatos, no cultivo obligatorio | Diagnosis | 2: 202 y rechazos sin evento, A/B 404, conversor/E2E |
| Estados, historial, cancelación, feedback, catálogo/snapshot | Diagnosis | 2–3: carrera y terminal irreversible, feedback propio y sin entrenar |
| Claim, lease, outbox/inbox, ACK/confirms, DLQ | Diagnosis + AI | 3: worker muerto, broker caído, duplicados y lease antiguo; simulación marcada |
| Cultivo automático, clase soportada, abstención calibrada, versiones | ML + AI + Diagnosis | 4: test independiente y fuera de cobertura; sin inventar métricas |
| Finished idempotente, lectura/preferencias/correo | Notification | 5: duplicado, fallo proveedor, acceso ajeno denegado |
| Supervisión, UI, métricas, recuperación, TLS/CDN | Servicios dueños + infra | 5: autorización, backup/restore, carga y CF-01…06 |

## Alternativas y consecuencias

- Copiar todas las rutas conceptuales y crear aliases: descartado porque §6.2.2 permite ajuste y no hay clientes existentes. Se conserva cada capacidad en el inventario.
- Usar lease_token como bearer: descartado; confunde concurrencia con autorización y permitiría acceso indebido.
- AI publica diagnóstico final/recomendaciones: descartado; rompe propiedad de Diagnosis y el catálogo revisado.
- ACK antes de commit o publicación directa sin outbox: descartado; permite pérdida ante caída.
- Exactly-once como supuesto del broker: descartado; redelivery obliga a consumidores idempotentes.
- No base técnica para AI: descartado conforme al ADR-0001; persistencia local del análisis/outbox protege recuperación.

Consecuencias: mayor disciplina de versionado, fixtures y estados por variante; persistencia técnica adicional y consistencia eventual. La deduplicación no elimina físicamente mensajes repetidos. Los parámetros locales necesitan validación antes de producción. El grupo 1 decide y documenta, pero no prueba todavía estas garantías en ejecución.

## Verificación documental

Coherencia revisada con los cinco estados de flujo más CANCELADO, las tres relaciones emisor/consumidor de §6.6–6.7, §6.8 (datos técnicos de AI), §8.29 (normalización) y los deltas CTR. La matriz cubre cada garantía y su incremento; REC-02…16 documentan ajustes. Las pruebas de contrato y del sistema se ejecutarán en las tareas/incrementos indicados. Evidencia del grupo 1 en [informe](../evidence/INCREMENTO-0-GRUPO-1.md).


## Concreción contractual del grupo 2 (2026-09-28)

Las propuestas anteriores se concretaron en [contracts](../../contracts/README.md), conservando la decisión histórica del grupo1. OpenAPI3.1.1 y JSON Schema2020-12; 27 operaciones contract-only. Se adoptan para el contrato inicial paginación20/máximo100, 10485760 bytes/24000000 píxeles y retención de idempotencia86400s no deslizante. Un cambio de esos valores anunciados exige actualizar contrato y consumidores; siguen sin medición productiva. Al expirar puede crearse otro ID; con tombstone dentro de retención409, sin resurrección; aceptación concurrente409 reintentable. Fingerprint de bytes, único campo image.

Se fija registro USER sin sesión, perfil PATCH display_name, password inicial12…128, cookie refresh HttpOnly/Secure/SameSite=Lax/Path=/api/v1/auth sin Domain, Origin permitido en login/refresh/logout y token CSRF ligado a sesión en refresh/logout. No fija algoritmo, duraciones de sesión ni configuración productiva: permanecen en ADR de seguridad previo a incremento1. Los fixtures no son credenciales válidas.

Se fijan literales PREDICTION, ABSTENTION y FAILURE; versiones/duración todos reales o todos null si no hubo ejecución en las dos últimas variantes. Payload cerrado y taxonomía candidata coherente; sin clase/score en abstención/fallo. [Entrega](../../contracts/events/README.md) fija colas y DLQ, mandatory+confirms, ACK tras commit y matrices de escenarios pendientes. No se agregan implementaciones de negocio ni se afirma entrega probada.

Verificación reproducible: `bash scripts/check_contracts.sh`; evidencia independiente del grupo1 en [grupo2](../evidence/INCREMENTO-0-GRUPO-2.md). La matriz de garantías de este ADR sigue asignando runtime a los incrementos correspondientes.
