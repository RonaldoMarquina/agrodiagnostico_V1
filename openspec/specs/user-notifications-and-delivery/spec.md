# user-notifications-and-delivery Specification

## Purpose

Proveer avisos internos idempotentes y entregas de correo opcionales y desacopladas a los usuarios autenticados cuando sus diagnósticos alcanzan un estado terminal notificable, preservando el aislamiento entre servicios y entre propietarios.

## Requirements

### Requirement: Creación idempotente de avisos internos desde DiagnosisFinished
El sistema SHALL consumir eventos `DiagnosisFinished` v1 válidos desde la cola durable de notificaciones y crear exactamente un aviso interno por diagnóstico terminal notificable (`COMPLETADO`, `NO_CONCLUYENTE` o `FALLIDO`), confirmando deduplicación y persistencia en la misma transacción antes de emitir ACK. Un evento duplicado, reentregado tras fallo previo al ACK o repetido para el mismo `diagnosis_id` SHALL NOT crear avisos adicionales ni emitir nuevos intentos de correo. Los diagnósticos `CANCELADO` o eventos con esquema o versión inválida SHALL aislarse en cuarentena con descriptor DLQ recuperable sin generar avisos.

#### Scenario: Primer evento terminal válido
- **WHEN** llega un evento `DiagnosisFinished` v1 válido con `final_status` en `COMPLETADO`, `NO_CONCLUYENTE` o `FALLIDO` para un diagnóstico aún sin aviso
- **THEN** el sistema persiste el registro de inbox y el aviso interno con `read_at = null` en la misma transacción y emite ACK únicamente después del commit

#### Scenario: Redelivery o duplicado por event_id o diagnosis_id
- **WHEN** llega nuevamente un `DiagnosisFinished` v1 con el mismo `event_id` o para un `diagnosis_id` que ya generó aviso
- **THEN** el sistema no crea un segundo aviso ni duplica entregas de correo y confirma el mensaje de manera idempotente

#### Scenario: Colisión de event_id o payload inválido
- **WHEN** llega un mensaje con versión desconocida, `final_status` fuera de enum o el mismo `event_id` con contenido distinto al ya procesado
- **THEN** el sistema aísla metadatos seguros en cuarentena, registra un descriptor DLQ recuperable y no crea ni modifica avisos internos

### Requirement: Consulta paginada y aislamiento de avisos propios
El sistema SHALL exponer `GET /api/v1/notifications` para usuarios autenticados activos, devolviendo únicamente los avisos propios ordenados por `created_at DESC, id DESC` mediante paginación keyset con cursor opaco firmado y ligado al propietario y propósito de consulta. El parámetro `limit` SHALL aceptar valores entre 1 y 100 con valor por defecto 20. Toda respuesta SHALL incluir `X-Correlation-ID` y `Cache-Control: private, no-store`.

#### Scenario: Listado paginado propio
- **WHEN** un usuario autenticado consulta `GET /api/v1/notifications` con `limit` válido y avanza usando `next_cursor`
- **THEN** recibe únicamente sus avisos sin duplicados ni omisiones en orden descendente por `(created_at, id)` hasta obtener `next_cursor = null`

#### Scenario: Cursor alterado o de otro propietario
- **WHEN** un usuario envía un `cursor` malformado, expirado, perteneciente a otro usuario o generado para otro endpoint, o un `limit` fuera del rango `1..100`
- **THEN** el sistema responde `400` con el envelope de error estándar sin revelar datos ajenos

#### Scenario: Acceso sin autenticación válida
- **WHEN** una solicitud sin token válido o con token expirado invoca rutas de notificaciones o preferencias
- **THEN** el sistema responde `401` con el envelope de error estándar

### Requirement: Marcado idempotente de lectura de avisos propios
El sistema SHALL exponer `PATCH /api/v1/notifications/{id}/read` para que un usuario autenticado marque como leído un aviso propio sin requerir cuerpo JSON. La primera invocación SHALL establecer `read_at` en UTC y devolver `200` con el recurso actualizado; invocaciones repetidas sobre el mismo aviso ya leído SHALL ser idempotentes, devolver `200` y conservar inmutable el `read_at` original. Recursos ajenos o inexistentes SHALL devolver `404` genérico.

#### Scenario: Primera lectura de aviso propio
- **WHEN** el propietario invoca `PATCH /api/v1/notifications/{id}/read` sobre un aviso con `read_at = null`
- **THEN** el sistema persiste `read_at` en UTC y devuelve `200` con el aviso actualizado

#### Scenario: Reintento idempotente de lectura
- **WHEN** el propietario vuelve a invocar `PATCH /api/v1/notifications/{id}/read` sobre un aviso ya leído
- **THEN** el sistema devuelve `200` preservando exactamente el valor previo de `read_at`

#### Scenario: Recurso ajeno o inexistente
- **WHEN** un usuario (incluido rol `ADMIN`) invoca `PATCH /api/v1/notifications/{id}/read` sobre un identificador inexistente o de otro propietario
- **THEN** el sistema responde `404` genérico sin revelar si el recurso existe

### Requirement: Preferencias de correo por usuario con opt-in por defecto
El sistema SHALL exponer `GET /api/v1/notification-preferences` y `PATCH /api/v1/notification-preferences` para usuarios autenticados. Los avisos internos SHALL permanecer siempre activos y no desactivables. Para usuarios sin preferencia registrada previamente, `GET /api/v1/notification-preferences` SHALL devolver `email_enabled = false`. `PATCH` SHALL exigir un objeto JSON cerrado no vacío con `email_enabled` booleano estricto y persistir la preferencia del propietario para futuros eventos sin alterar diagnósticos ni avisos ya emitidos.

#### Scenario: Lectura inicial con default opt-in
- **WHEN** un usuario autenticado sin preferencia guardada consulta `GET /api/v1/notification-preferences`
- **THEN** el sistema responde `200` con `{"email_enabled": false}`

#### Scenario: Actualización válida de preferencia
- **WHEN** un usuario autenticado envía `PATCH /api/v1/notification-preferences` con `{"email_enabled": true}`
- **THEN** el sistema persiste el cambio y responde `200` con `{"email_enabled": true}`, aplicando la preferencia a entregas posteriores

#### Scenario: Payload inválido en PATCH
- **WHEN** un usuario envía `{}` vacío, campos no permitidos o `email_enabled` no booleano
- **THEN** el sistema responde `400` con el envelope de error estándar sin modificar preferencias

### Requirement: Resolución interna segura de contacto y entrega de correo desacoplada
Cuando un aviso interno se crea para un propietario con `email_enabled = true`, el sistema SHALL programar y registrar intentos de entrega de correo de forma desacoplada mediante un adaptador configurable, resolviendo el correo del usuario únicamente a través del endpoint interno `GET /internal/users/{id}/contact` de `identity` autenticado con credencial de servicio firmada y audience interna dedicada. El endpoint interno SHALL permanecer inaccesible desde el proxy público y rechazar tokens de usuario o credenciales no autorizadas (`401`/`403`). Un fallo de red, indisponibilidad de `identity`, cuenta inactiva o error del proveedor de correo SHALL registrarse en los intentos de entrega con reintentos acotados y nunca SHALL revertir, bloquear ni modificar el aviso interno ni el diagnóstico.

#### Scenario: Resolución interna autorizada y envío exitoso
- **WHEN** `email_enabled = true` para el propietario de un `DiagnosisFinished` v1 y `identity` responde `200` con usuario activo y correo válido ante credencial de servicio autorizada
- **THEN** el sistema registra el intento de entrega, invoca el adaptador de correo sin exponer credenciales en logs y marca el envío como entregado

#### Scenario: Fallo del proveedor de correo o de contacto interno
- **WHEN** el proveedor de correo falla o `identity` no está disponible temporalmente durante el envío
- **THEN** el aviso interno permanece persistido y consultable, el diagnóstico no sufre modificación alguna y el intento fallido queda registrado para reintento acotado posterior

#### Scenario: Protección del endpoint interno de contacto
- **WHEN** se intenta acceder a `GET /internal/users/{id}/contact` desde el proxy externo, sin autenticación, con Bearer de usuario o con una credencial de servicio con audience o principal incorrectos
- **THEN** el proxy devuelve `404` externamente y `identity` rechaza llamadas internas no autorizadas con `401` o `403` sin filtrar correos ni existencia de cuentas
