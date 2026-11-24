## ADDED Requirements

### Requirement: Lectura masiva idempotente y contador de avisos no leídos propios
El sistema SHALL exponer `PATCH /api/v1/notifications/read-all` y `GET /api/v1/notifications/unread-count` para usuarios autenticados activos, aplicando aislamiento estricto por `owner_id == sub` e incluyendo `X-Correlation-ID` y `Cache-Control: private, no-store` en toda respuesta. `PATCH /api/v1/notifications/read-all` SHALL operar sin requerir cuerpo JSON, actualizar atómicamente únicamente los avisos propios con `read_at IS NULL` fijando `read_at` en UTC, conservar inmutable el `read_at` de los avisos ya leídos y responder `200` con `{"updated_count": <entero >= 0>}`. Invocaciones repetidas sin nuevos avisos pendientes SHALL ser idempotentes devolviendo `{"updated_count": 0}`. `GET /api/v1/notifications/unread-count` SHALL responder `200` con `{"unread_count": <entero >= 0>}` contando únicamente los avisos propios con `read_at IS NULL`. Toda invocación sin autenticación válida SHALL responder `401`.

#### Scenario: Lectura masiva idempotente de avisos propios
- **WHEN** un usuario autenticado con 2 avisos no leídos y 1 aviso ya leído invoca `PATCH /api/v1/notifications/read-all` dos veces consecutivas
- **THEN** la primera llamada responde `200` con `{"updated_count": 2}` preservando el `read_at` previo del aviso ya leído, y la segunda llamada responde `200` con `{"updated_count": 0}`

#### Scenario: Consulta de contador de avisos no leídos propios
- **WHEN** un usuario autenticado consulta `GET /api/v1/notifications/unread-count` antes y después de marcar avisos como leídos
- **THEN** el sistema devuelve `200` con el conteo exacto de avisos propios con `read_at IS NULL`, descendiendo a `0` tras `read-all`

#### Scenario: Aislamiento entre propietarios en lectura masiva y contador
- **WHEN** el usuario A invoca `PATCH /api/v1/notifications/read-all` mientras el usuario B tiene avisos no leídos
- **THEN** los avisos del usuario B permanecen intactos y el contador `GET /api/v1/notifications/unread-count` del usuario B no se ve alterado

#### Scenario: Acceso sin autenticación a lectura masiva o contador
- **WHEN** una solicitud sin token JWT válido invoca `PATCH /api/v1/notifications/read-all` o `GET /api/v1/notifications/unread-count`
- **THEN** el sistema responde `401` con el envelope de error estándar
