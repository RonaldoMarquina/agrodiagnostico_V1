# Contratos de API y eventos

Los contratos iniciales del grupo 2 están en [contracts](../contracts/README.md): cuatro OpenAPI 3.1.1, componentes comunes y tres eventos JSON Schema 2020-12. Este documento explica su semántica; no sustituye esos archivos. El grupo4 implementa las ocho operaciones internas de salud; las diecinueve operaciones de negocio siguen **contract-only**. Actualiza OpenSpec, ADR cuando corresponda y pruebas al cambiar una interfaz.

## Convenciones comunes

- API pública bajo `/api/v1/`, JSON UTF-8 salvo carga multipart. El cliente envía token de acceso según el contrato de Identity; el refresh token rotativo utiliza cookie segura y protección CSRF si corresponde.
- Fechas en UTC, identificadores UUID, errores `{code, message, correlation_id, details?}` sin trazas internas ni datos ajenos.
- Define en OpenAPI paginación, filtros, manejo de cookie, esquema de error, límites y expiración; evita que frontend y backend infieran formatos distintos.
- Toda lectura de recurso propio verifica `owner_id`. Para recursos inexistentes o ajenos devuelve 404 genérico. Rutas administrativas aplican rol ADMIN y auditoría.
- Para reintentos de carga, `Idempotency-Key` se asocia al propietario y la operación. Documenta en OpenAPI tratamiento de clave reutilizada con contenido distinto y plazo de retención.

## HTTP público previsto

| Método | Ruta | Función y respuesta clave |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | Registro; `201` o error controlado |
| POST | `/api/v1/auth/login` | Sesión; `200` o `401` genérico |
| POST | `/api/v1/auth/refresh` | Rotación de sesión |
| POST | `/api/v1/auth/logout` | Revocación |
| GET/PATCH | `/api/v1/profile` | Perfil propio; PATCH solo display_name |
| POST | `/api/v1/auth/password-recovery` | Inicio sin enumerar cuentas; 202 genérico |
| POST | `/api/v1/diagnoses` | `multipart image` + `Idempotency-Key`; `202 {id,status,created_at}`; validar `400/401/413/415` |
| GET | `/api/v1/diagnoses` | Historial paginado propio, excluye borrado lógico |
| GET | `/api/v1/diagnoses/{id}` | Estado/detalle propio; `404` ajeno |
| POST | `/api/v1/diagnoses/{id}/cancel` | `200 CANCELADO` si sigue pendiente; `409` si ya empezó |
| DELETE | `/api/v1/diagnoses/{id}` | Borrado lógico propio; `204` idempotente |
| GET | `/api/v1/notifications` | Avisos propios paginados |
| GET/PATCH | `/api/v1/notification-preferences` | Preferencia propia email_enabled; avisos internos siempre activos |
| Pendiente | Administración (sin wildcard ejecutable) | [Inventario con dueño e incremento](../contracts/deferred-operations.json) |

La operación de reclamo `/internal/diagnoses/{id}/claim` está restringida a identidad de servicio, nunca al cliente ni a Internet. Se contratan POST `/internal/diagnoses/{id}/lease/renew`, GET `/internal/diagnoses/{id}/image` y GET `/api/v1/diagnoses/{id}/image`. Reclamo/renovación devuelven lease_owner, lease_token y expires_at; renovación usa body lease_token, imagen interna usa X-Lease-Token. Identidad AI obligatoria independientemente del lease; obsoleto responde 409 STALE_LEASE. Ninguna ruta entrega URL pública permanente de fotografías.

## Envelope de eventos

Todo evento JSON versionado contiene `event_id`, `event_type`, `schema_version`, `occurred_at`, `correlation_id` y `payload`. El consumidor rechaza o aísla versiones incompatibles y deduplica por `consumer + event_id`. Publicar con confirms y marcar el outbox entregado solo tras confirmación. ACK del consumidor después de commit local.

| Evento | Emisor → consumidor | Payload mínimo |
| --- | --- | --- |
| `DiagnosisRequested` v1 | Diagnosis → AI | `diagnosis_id`, `owner_id`, `object_key` privado |
| `DiagnosisAnalyzed` v1 | AI → Diagnosis | `diagnosis_id`, `lease_token`, `crop_code`, `class_code?`, `raw_score?`, `outcome`, `reason_code?`, `model_id`, `model_version`, `dataset_version`, `inference_ms` |
| `DiagnosisFinished` v1 | Diagnosis → Notification | `diagnosis_id`, `owner_id`, `final_status` (`COMPLETADO`, `NO_CONCLUYENTE` o `FALLIDO`) |

Los campos de envelope acompañan cada payload. Los contratos exactos se guardan como JSON Schema versionado con ejemplos válidos/inválidos. Los mensajes solo llevan referencias privadas, sin imagen binaria, contraseñas o tokens. Un resultado `DiagnosisAnalyzed` de lease antiguo no sobrescribe un resultado actual; duplicados no crean resultados ni avisos adicionales.

## Compatibilidad

Un cambio que altere el significado de un campo o elimine uno requerido exige propuesta OpenSpec, ADR cuando impacte arquitectura, nueva versión del esquema y despliegue compatible entre productores/consumidores. Guarda pruebas de contrato para cada servicio y cliente. La base de datos también requiere migración cuando corresponda.

## Reconciliación con la fuente V1

Referencia: [matriz REC-01…20](reference/RECONCILIACION-V1.md) y [ADR de interfaces](adr/0002-interfaces-y-eventos-v1.md). El DOCX §6.2.2 declara sus rutas conceptuales ajustables. Se mantienen `/profile`, `/auth/password-recovery` y `/notification-preferences` como nombres del inventario local; no se exige implementar aliases. Las rutas iniciales están fijadas en OpenAPI; las obligaciones adicionales de la tabla siguiente conservan contrato pendiente antes de sus consumidores.

La carga no exigirá cultivo manual (RF-07). AI intentará inferirlo y podrá comunicar cultivo desconocido sin inventar una especie. `NO_CONCLUYENTE` es el identificador técnico de la etiqueta «NO CONCLUYENTE». El `lease_token` del evento es un identificador de concurrencia sin autoridad propia; la prohibición de tokens se refiere a credenciales de autenticación.

| Operación de la fuente | Correspondencia/obligación conservada | Responsable / antes de consumidor |
| --- | --- | --- |
| GET/PUT `/api/v1/users/me` (§6.2.2) | GET/PATCH `/api/v1/profile`; semántica de actualización parcial | Identity / incremento 1 |
| POST `/auth/password/forgot` | POST `/auth/password-recovery` bajo `/api/v1` | Identity / 1 |
| POST `/auth/password/reset`, PUT `/users/me/password` | Confirmación segura y cambio autenticado obligatorios; ruta/payload por contratar | Identity / 1 |
| GET `/diagnoses/{id}/status` | Estado incluido en GET detalle; no obliga endpoint duplicado | Diagnosis / 2 |
| RF-20, §8.34 | Feedback útil/no útil propio, sin generar etiquetas ML; ruta/payload por contratar | Diagnosis / 2; UI / 5 |
| PATCH `/notifications/{id}/read` | Lectura de aviso propio obligatoria en interfaz futura | Notification / 5 |
| GET/PATCH `/notifications/preferences` | GET/PATCH `/notification-preferences` bajo `/api/v1` | Notification / 5 |
| `/admin/users`, block/activate (§6.2.2) | Gestión de usuarios con RBAC y auditoría; contrato previo al consumidor | Identity / 1 |
| `/admin/diagnoses`, crops/problems/recommendations (§6.3.2) | Supervisión y CRUD/activación; plagas solo experimentales | Diagnosis / 2; UI / 5 |
| Auditoría/métricas/estado/modelo (RF-25…28) | Inventario pendiente con servicio dueño; sin acceso público a AI | Servicios dueños / 1–5 |

Las omisiones quedan registradas como obligaciones, no como eliminación del alcance. El grupo 2 cubre las operaciones iniciales especificadas en sus tareas; las adicionales deberán contratarse antes de sus consumidores en los incrementos indicados. El cierre de V1 no puede omitirlas. La recuperación de acceso del incremento 1 puede usar un adaptador de correo controlado sin esperar al flujo de avisos de diagnósticos del incremento 5.


## Decisiones contractuales del grupo 2

[Inventario completo](../contracts/operations.json), [matriz de seguridad](../contracts/security-matrix.json) y [casos HTTP declarativos](../contracts/http-scenarios.json). Salud GET `/health/live` y `/health/ready` de cada servicio está implementada y es interna; live 200 `{status: alive, service}`, ready 200 `ready` o 503 `not_ready`. No expone excepciones. La readiness técnica sigue D2 y no acredita modelo cargado en Incremento 0.

Los identificadores son UUID y las fechas RFC3339 en UTC con sufijo Z. En las operaciones de negocio contratadas, X-Correlation-ID opcional de solicitud debe ser UUID o devuelve 400; si falta el servidor genera uno y lo devuelve. Las operaciones técnicas de salud no declaran ese parámetro de entrada y generan su propio UUID de respuesta. Respuestas con X-Correlation-ID y Cache-Control `private, no-store`. Errores cerrados, details opcional solo con field/code seguros, nunca valores de credenciales o trazas. Error 404 idéntico para ajeno/inexistente; consultas excluyen borrados.

Paginación keyset: created_at DESC, id DESC; cursor opaco ligado a usuario y consulta, sin filtros adicionales iniciales. limit por defecto20, mínimo1 y máximo100; cursor/límite inválido400. next_cursor es null al terminar. El índice expone el dueño de cada operación y su incremento funcional.

Carga inicial: un campo multipart image, sin cultivo manual, máximo **10485760 bytes (10 MiB)** y **24000000 píxeles decodificados**; JPEG/PNG/WebP. Exceso413, formato no admitido415, corrupto/no decodificable400 antes de crear fila/evento. HEIC/HEIF se mantiene como objetivo V1 pendiente de conversor y E2E; no se anuncia soporte actual. Son parámetros contractuales iniciales, no límites productivos medidos; cambiar límites visibles exige revisión coordinada del contrato/configuración.

Idempotencia: clave ASCII de 1…128 caracteres; namespace propietario+operación+clave, fingerprint SHA-256 de bytes exactos de imagen (excluye filename, boundary y MIME declarado). No se admiten otros campos semánticos. Retención no deslizante de **86400 segundos**, desde primera aceptación. Antes del vencimiento la misma carga devuelve202 con mismo id/created_at y estado actual; contenido distinto409. En `now >= expires_at`, nueva solicitud con nuevo ID. Otro propietario tiene namespace independiente. Borrado durante retención devuelve409 IDEMPOTENCY_RESOURCE_DELETED sin resucitar recurso; aceptación concurrente no resuelta409 IDEMPOTENCY_IN_PROGRESS. La infraestructura podrá configurar la retención, pero debe conservar este valor anunciado o versionar/documentar el cambio antes del consumidor; no define retención de fotos ni sesiones.

Cancelación solo gana en PENDIENTE; después del reclamo o ante cualquier terminal devuelve409. DELETE propio devuelve204, también si ya existe tombstone; ajeno/nunca existente404. Borrado lógico no cancela inferencia ni revierte terminal. Detalle contiene recomendación versionada de catálogo solo en COMPLETADO, motivo obligatorio en NO_CONCLUYENTE/FALLIDO; los ejemplos son sintéticos sin tratamientos.

## Identidad, cookies y CSRF

Registro crea USER y devuelve201 perfil sin sesión; duplicado409 genérico ACCOUNT_UNAVAILABLE. Password inicial12…128 caracteres, hashing Argon2id en implementación; login admite credenciales de 1…128 para error genérico. Perfil PATCH solo display_name, sin escalada de rol, cambio de email o password. Recuperación202 idéntico exista o no cuenta, sin devolver token. Confirmación y cambio de contraseña siguen obligatorios en incremento1.

Login valida Origin contra allowlist y devuelve access_token, token_type Bearer, expires_in y csrf_token ligado a sesión en JSON. Refresh exclusivamente cookie `__Secure-agro_refresh`, HttpOnly, Secure, SameSite=Lax, Path=/api/v1/auth, sin Domain. Login/refresh fijan cookie; refresh rota cookie y CSRF de manera atómica. Reutilizar refresh revoca familia. Refresh/logout exigen **cookie AND X-CSRF-Token AND Origin permitido**; ausencia/invalidez de identidad401, fallo CSRF/origen403. Logout revoca y borra cookie con Max-Age=0. No enviar cookie ni CSRF en eventos/logs.

El access bearer se usa en recursos propios; AI utiliza credencial de servicio con audience interna distinta, nunca bearer de usuario o lease como autorización. Firma, issuer/audience, duraciones reales, revocación de access y secretos se configuran mediante ADR de seguridad antes de implementar Identity. expires_in=600 en ejemplo es ilustrativo, no política de producción. Las pruebas de esquema no comprueban navegador, rotación ni RBAC en runtime; HTTP local del scaffold no demuestra sesiones Secure.

## Eventos y compatibilidad comprobable

[Contratos y transacciones](../contracts/events/README.md) fija routing y variantes PREDICTION/ABSTENTION/FAILURE. El envelope y payloads son cerrados; los campos de ejecución se admiten todos null cuando no hubo inferencia en abstención/fallo. No hay clases/score fabricados ni recomendaciones de AI. Un campo nuevo en esquema cerrado puede romper compatibilidad y exige revisar/versionar, aunque sea aditivo. Diagnóstico y eventos conservan versiones independientes del modelo.

Verificación local: `bash scripts/check_contracts.sh`. Valida referencias, estructura OpenAPI, ejemplos, formatos y negativos; la evidencia del grupo2 no acredita outbox/inbox, permisos, idempotencia ni límites de archivos funcionando. Sus pruebas reales permanecen en incrementos1–5.
