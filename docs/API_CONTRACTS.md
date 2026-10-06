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
| POST | `/api/v1/diagnoses` | `multipart image` + `Idempotency-Key`; `202 {id,status,created_at}`; validar `400/401/409/413/415/503` |
| GET | `/api/v1/diagnoses` | Historial paginado propio, excluye borrado lógico |
| GET | `/api/v1/diagnoses/{id}` | Estado/detalle propio; `404` ajeno |
| POST | `/api/v1/diagnoses/{id}/cancel` | `200 CANCELADO` si sigue pendiente; `409` si ya empezó |
| DELETE | `/api/v1/diagnoses/{id}` | Borrado lógico propio; `204` idempotente |
| GET | `/api/v1/diagnoses/{id}/image` | Descarga de imagen original propia; `200` binario con no-store; `404` ajeno/borrado |
| GET | `/api/v1/crops` | Listado de cultivos activos del catálogo (POTATO, MAIZE) |
| GET | `/api/v1/crops/{code}/problems` | Condiciones candidatas activas de un cultivo |
| GET | `/api/v1/problems/{code}/recommendations` | Última versión aprobada y activa; lista vacía si no hay contenido |
| POST | `/api/v1/diagnoses/{id}/feedback` | Feedback útil/no útil propio (201 creación, 200 reemplazo); solo COMPLETADO o NO_CONCLUYENTE |
| GET/POST | `/api/v1/admin/crops` | Listar todos / crear cultivo en catálogo (ADMIN) |
| PATCH | `/api/v1/admin/crops/{code}` | Actualizar nombre y estado active de cultivo (ADMIN) |
| GET/POST | `/api/v1/admin/problems` | Listar todas / crear condición agrícola (ADMIN) |
| PATCH | `/api/v1/admin/problems/{code}` | Actualizar nombre y active de condición (ADMIN) |
| GET/POST | `/api/v1/admin/recommendations` | Listar / registrar versión inmutable con fuentes y revisión (ADMIN) |
| PATCH | `/api/v1/admin/recommendations/{id}` | Modificar exclusivamente active de una versión (ADMIN) |
| GET | `/api/v1/admin/diagnoses` | Supervisión paginada de metadatos de diagnósticos con cursor HMAC (ADMIN) |
| GET | `/api/v1/notifications` | Avisos propios paginados |
| GET/PATCH | `/api/v1/notification-preferences` | Preferencia propia email_enabled; avisos internos siempre activos |
| Pendiente | Notificaciones y métricas (incremento 5) | [Inventario con dueño e incremento](../contracts/deferred-operations.json) |

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

## Decisiones contractuales del Incremento 2 (Diagnósticos, Catálogo y Feedback)

Conforme a design.md y ADR-0006, se formalizan en OpenAPI 3.1 (`contracts/openapi/diagnosis.openapi.json`), `operations.json`, `security-matrix.json` y `http-scenarios.json` las 14 operaciones añadidas de Diagnosis (totalizando 46 operaciones contractuales):

| Operación | Método y ruta | Autorización | Escenario declarativo | Tarea de implementación |
| --- | --- | --- | --- | --- |
| `diagnosis_create` | POST `/api/v1/diagnoses` | USER | `idempotency-same`, `over-bytes`, etc. | 4.1, 4.2, 4.3, 4.4 |
| `diagnosis_list` | GET `/api/v1/diagnoses` | USER | `diagnosis-history-list` | 5.3 |
| `diagnosis_detail` | GET `/api/v1/diagnoses/{id}` | USER | `foreign-resource`, `missing-resource` | 5.2 |
| `diagnosis_cancel` | POST `/api/v1/diagnoses/{id}/cancel` | USER | `cancel-pending`, `cancel-after-claim` | 5.1 |
| `diagnosis_delete` | DELETE `/api/v1/diagnoses/{id}` | USER | `delete-repeated` | 5.2 |
| `diagnosis_own_image` | GET `/api/v1/diagnoses/{id}/image` | USER | `diagnosis-image-fetch` | 4.6 |
| `diagnosis_list_crops` | GET `/api/v1/crops` | USER | `catalog-crops-list` | 6.1 |
| `diagnosis_list_crop_problems` | GET `/api/v1/crops/{code}/problems` | USER | `catalog-crop-problems` | 6.1 |
| `diagnosis_get_problem_recommendations` | GET `/api/v1/problems/{code}/recommendations` | USER | `catalog-recommendations` | 6.1 |
| `diagnosis_admin_list_crops` | GET `/api/v1/admin/crops` | ADMIN | `admin-crops-list` | 6.2 |
| `diagnosis_admin_create_crop` | POST `/api/v1/admin/crops` | ADMIN | `admin-crops-create` | 6.2 |
| `diagnosis_admin_patch_crop` | PATCH `/api/v1/admin/crops/{code}` | ADMIN | `admin-crops-patch` | 6.2 |
| `diagnosis_admin_list_problems` | GET `/api/v1/admin/problems` | ADMIN | `admin-problems-list` | 6.2 |
| `diagnosis_admin_create_problem` | POST `/api/v1/admin/problems` | ADMIN | `admin-problems-create` | 6.2 |
| `diagnosis_admin_patch_problem` | PATCH `/api/v1/admin/problems/{code}` | ADMIN | `admin-problems-patch` | 6.2 |
| `diagnosis_admin_list_recommendations` | GET `/api/v1/admin/recommendations` | ADMIN | `admin-recommendations-list` | 6.3 |
| `diagnosis_admin_create_recommendation` | POST `/api/v1/admin/recommendations` | ADMIN | `admin-recommendations-create` | 6.3 |
| `diagnosis_admin_patch_recommendation` | PATCH `/api/v1/admin/recommendations/{id}` | ADMIN | `admin-recommendations-patch` | 6.3 |
| `diagnosis_admin_list_diagnoses` | GET `/api/v1/admin/diagnoses` | ADMIN | `admin-diagnoses-list` | 5.4 |
| `diagnosis_submit_feedback` | POST `/api/v1/diagnoses/{id}/feedback` | USER | `diagnosis-feedback-create`, `diagnosis-feedback-update` | 7.1, 7.2 |

- **Carga y fallos 503**: `POST /api/v1/diagnoses` añade respuestas 503 `STORAGE_UNAVAILABLE` y `PERSISTENCE_UNAVAILABLE` ante fallos transitorios en el almacenamiento de objetos o en el commit de persistencia.
- **Ciclo de vida y PENDIENTE sin worker**: En el Incremento 2 no existe worker de inferencia activo; las cargas aceptadas permanecen en `PENDIENTE`. Al habilitar el procesamiento en el Incremento 3, se requerirá un outbox transaccional y un proceso de backfill para publicar `DiagnosisRequested` y transicionar diagnósticos previos según la política que defina ese cambio.
- **Cancelación atómica y no revertible**: `POST /api/v1/diagnoses/{id}/cancel` actualiza condicionalmente filas propias en `PENDIENTE` no borradas hacia `CANCELADO` (200 `DiagnosisCancelled`). Una carrera concurrente otorga exactamente un éxito y 409 `DIAGNOSIS_NOT_CANCELABLE` a la solicitud competidora. Cualquier estado no cancelable (`PROCESANDO`, `COMPLETADO`, `NO_CONCLUYENTE`, `FALLIDO`, `CANCELADO`) responde 409. Recursos ajenos, inexistentes o con borrado lógico devuelven 404 genérico. La cancelación nunca emite evento `DiagnosisFinished`.
- **Borrado lógico vs. Cancelación**: `DELETE /api/v1/diagnoses/{id}` aplica borrado lógico idempotente (`204 No Content` para primer borrado y repeticiones propias). No cancela el diagnóstico, no altera estados terminales ni elimina el archivo en S3. Los tombstones (`deleted_at IS NOT NULL`) son completamente invisibles (404) en detalle, imagen, cancelación, feedback y listados.
- **Detalle contractual privado**: `GET /api/v1/diagnoses/{id}` devuelve únicamente metadatos según el estado:
  - `PENDIENTE`, `PROCESANDO`, `CANCELADO`: `{id, status, created_at, updated_at}`.
  - `NO_CONCLUYENTE`, `FALLIDO`: añade `reason_code` contractual.
  - `COMPLETADO`: añade `result` con `crop_code`, `class_code`, `raw_score`, snapshot del modelo y de la recomendación de catálogo aprobada.
  - Recursos ajenos, inexistentes o borrados devuelven 404 genérico (incluso para ADMIN en rutas de usuario).
- **Historial keyset y cursores HMAC**: `GET /api/v1/diagnoses` lista diagnósticos propios no borrados en orden `(created_at DESC, id DESC)`, con `limit` 1..100 (defecto 20). Los cursores son tokens Base64URL firmados con HMAC-SHA256 mediante clave estable externa (`CURSOR_SIGNING_KEY_FILE` / `CURSOR_SIGNING_KEY`), ligados al `sub` del principal, propósito `user_diagnoses`, `created_at` e `id`. Cursores alterados, de otro usuario, de otro endpoint, malformados o firmados con clave rotada devuelven 400 `INVALID_PAGINATION`. Si la fila ancla de un cursor fue borrada lógicamente después de su emisión, la paginación avanza forward de manera estable sin revelar el recurso eliminado.
- **Supervisión administrativa auditada**: `GET /api/v1/admin/diagnoses` exige rol `ADMIN` (USER recibe 403, anónimo 401). Devuelve metadatos mínimos paginados (`id`, `owner_id`, `status`, `created_at`, `updated_at`, `reason_code` opcional), con cursor HMAC independiente (`purpose: admin_supervision`), excluyendo diagnósticos borrados y sin filtrar imágenes, `object_key`, feedback ni datos de Identity. Toda consulta exitosa se audita en `diagnosis_audit_logs`.
- **Catálogo acotado V1 y arranque limpio**: Las consultas públicas de catálogo (`GET /api/v1/crops`, `GET /api/v1/crops/{code}/problems`, `GET /api/v1/problems/{code}/recommendations`) devuelven listas `{ items }` de entidades activas, sin cursor. Si el cultivo o condición padre no existe o está inactivo, responde 404 genérico. El catálogo arranca limpio sin recomendaciones precargadas (semilla `0002` solo crea `POTATO`, `MAIZE` y las 7 condiciones candidatas con `model_supported=false`). A la fecha del Incremento 2 no existe paquete agronómico revisado y aprobado oficialmente; este pendiente está registrado explícitamente y no bloquea el arranque técnico, pero prohíbe terminantemente atribuir recomendaciones clínicas o dosis a diagnósticos resueltos sin previo ingreso administrativo justificado.
- **Flujo de revisión agronómica y evidencias obligatorias**: En `POST /api/v1/admin/recommendations`, la creación de recomendaciones exige evidencia documental obligatoria:
  - `source_refs`: lista no vacía de referencias bibliográficas, institucionales o científicas contrastables (INIA, CIP, CIMMYT, FAO).
  - `review_reference`: identificador o código del expediente técnico/agronómico de revisión.
  - `reviewed_by`: identificador del revisor humano acreditado.
  - `reviewed_at`: marca de tiempo ISO 8601 UTC de la validación.
  La omisión o vacuidad de cualquiera de estos campos responde `400 CATALOG_REVIEW_REQUIRED`. El alta genera una nueva versión secuencial calculada bajo bloqueo de fila del problema padre (`version = MAX(version) + 1`).
- **Inmutabilidad y Preservación de Snapshots Históricos**: Una vez creada una recomendación, sus campos de texto y revisión son estrictamente inmutables; `PATCH /api/v1/admin/recommendations/{id}` únicamente permite conmutar `active: true|false`. Cuando un diagnóstico alcanza `COMPLETADO`, vincula la recomendación activa vigente y almacena un snapshot inmutable de `recommendation_id`, `catalog_version` y `recommendation_text`. Desactivar la recomendación, desactivar la condición/cultivo o publicar versiones posteriores no altera ni degrada la clave foránea, el snapshot textual ni la respuesta en `GET /api/v1/diagnoses/{id}` de diagnósticos completados con anterioridad.
- **Feedback propio y separación de entrenamiento**: `POST /api/v1/diagnoses/{id}/feedback` permite a usuarios autenticados valorar resultados de diagnósticos propios:
  - **Estados permitidos**: Únicamente `COMPLETADO` o `NO_CONCLUYENTE`. Cualquier otro estado (`PENDIENTE`, `PROCESANDO`, `CANCELADO`, `FALLIDO`) responde `409 FEEDBACK_NOT_ALLOWED`.
  - **Aislamiento y tombstones**: Recursos inexistentes, ajenos o con borrado lógico (`deleted_at IS NOT NULL`) responden `404 RESOURCE_NOT_FOUND` genérico sin revelar el estado del recurso (incluyendo solicitudes con rol `ADMIN` sobre recursos ajenos). Un usuario con rol `ADMIN` puede valorar únicamente sus propios diagnósticos.
  - **Creación y reemplazo**: La primera valoración responde `201 Created`; valoraciones subsecuentes sobre el mismo diagnóstico responden `200 OK`, actualizando `useful`, `comment` y `updated_at`, preservando inmutable `created_at`.
  - **Validación estricta y omisión de comentario**: El payload exige `useful` como booleano estricto (`true` o `false`; strings o enteros responden `400 INVALID_REQUEST`) y prohíbe campos extra. `comment` admite hasta 1000 caracteres. Si en una actualización se omite `comment` o se envía `null`, el comentario previo es eliminado (`null`).
  - **Serialización con DELETE**: Las operaciones sobre el diagnóstico y su feedback se serializan bajo bloqueo de fila (`FOR UPDATE`). Si el diagnóstico es borrado lógicamente, todo intento de valorar responde 404.
  - **Ausencia de eventos y pipelines**: El feedback opera exclusivamente como métrica operativa y de satisfacción. No emite eventos de dominio ni mensajes al broker, y no alimenta pipelines automáticos de re-entrenamiento ni ajuste de modelos ML.

## Identidad, cookies y CSRF

Registro crea USER y devuelve201 perfil sin sesión; duplicado409 genérico ACCOUNT_UNAVAILABLE. Password inicial12…128 caracteres, hashing Argon2id en implementación; login admite credenciales de 1…128 para error genérico. Perfil PATCH solo display_name, sin escalada de rol, cambio de email o password. Recuperación202 idéntico exista o no cuenta, sin devolver token. Confirmación y cambio de contraseña siguen obligatorios en incremento1.

Login valida Origin contra allowlist y devuelve access_token, token_type Bearer, expires_in y csrf_token ligado a sesión en JSON. Refresh exclusivamente cookie `__Secure-agro_refresh`, HttpOnly, Secure, SameSite=Lax, Path=/api/v1/auth, sin Domain. Login/refresh fijan cookie; refresh rota cookie y CSRF de manera atómica. Reutilizar refresh revoca familia. Refresh/logout exigen **cookie AND X-CSRF-Token AND Origin permitido**; ausencia/invalidez de identidad401, fallo CSRF/origen403. Logout revoca y borra cookie con Max-Age=0. No enviar cookie ni CSRF en eventos/logs.

El access bearer se usa en recursos propios; AI utiliza credencial de servicio con audience interna distinta, nunca bearer de usuario o lease como autorización. Firma, issuer/audience, duraciones reales, revocación de access y secretos se configuran mediante ADR de seguridad antes de implementar Identity. expires_in=600 en ejemplo es ilustrativo, no política de producción. Las pruebas de esquema no comprueban navegador, rotación ni RBAC en runtime; HTTP local del scaffold no demuestra sesiones Secure.

## Eventos y compatibilidad comprobable

[Contratos y transacciones](../contracts/events/README.md) fija routing y variantes PREDICTION/ABSTENTION/FAILURE. El envelope y payloads son cerrados; los campos de ejecución se admiten todos null cuando no hubo inferencia en abstención/fallo. No hay clases/score fabricados ni recomendaciones de AI. Un campo nuevo en esquema cerrado puede romper compatibilidad y exige revisar/versionar, aunque sea aditivo. Diagnóstico y eventos conservan versiones independientes del modelo.

Verificación local: `bash scripts/check_contracts.sh`. Valida referencias, estructura OpenAPI, ejemplos, formatos y negativos; la evidencia del grupo2 no acredita outbox/inbox, permisos, idempotencia ni límites de archivos funcionando. Sus pruebas reales permanecen en incrementos1–5.
