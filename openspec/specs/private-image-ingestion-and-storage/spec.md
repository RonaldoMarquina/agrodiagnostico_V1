# private-image-ingestion-and-storage Specification

## Purpose

Garantiza carga limitada y decodificada de imágenes, almacenamiento privado y entrega por propietario, con recuperación segura de cargas interrumpidas entre objetos y persistencia relacional.

## Requirements

### Requirement: Validación efectiva y límites de imágenes
POST /api/v1/diagnoses SHALL aceptar exactamente un archivo multipart image, sin exigir cultivo manual. SHALL limitar archivo a 10485760 bytes reales y 24000000 píxeles, permitir JPEG/PNG/WebP decodificables y rechazar archivos corruptos, animados/multiframe o partes adicionales. Límite de transporte SHALL permitir un archivo máximo con sobre multipart ordinario (configuración inicial 11 MiB); no SHALL confiar en Content-Length o MIME/extensión declarados. No SHALL persistir diagnósticos u objetos de imágenes rechazadas.

#### Scenario: Archivo válido en frontera
- **WHEN** se envía por proxy un JPEG/PNG/WebP válido de exactamente 10485760 bytes y no más de 24000000 píxeles con un único campo image
- **THEN** supera validación de tamaño y formato sin exigir crop_code

#### Scenario: Bytes o píxeles excesivos
- **WHEN** el archivo excede el límite real de bytes o dimensiones, aunque Content-Length sea ausente o engañoso
- **THEN** devuelve 413 PAYLOAD_TOO_LARGE sin persistir diagnóstico ni objeto

#### Scenario: Formato no soportado
- **WHEN** bytes reales corresponden a GIF, ejecutable, HEIC/HEIF u otro formato no admitido, cualquiera sea su nombre o MIME declarado
- **THEN** devuelve 415 UNSUPPORTED_MEDIA_TYPE; HEIC/HEIF sigue pendiente de conversor y E2E para V1

#### Scenario: Corrupción tras cabecera válida
- **WHEN** cabeceras parecen válidas pero la decodificación completa falla, o la imagen es multiframe
- **THEN** devuelve 400 INVALID_IMAGE sin almacenar imagen

#### Scenario: Multipart inesperado
- **WHEN** hay más de un archivo, campos adicionales o no existe image
- **THEN** devuelve 400 contractual sin crear diagnóstico

### Requirement: Objetos privados con recuperación durable
Las fotos aceptadas SHALL almacenarse solo en objetos privados y PostgreSQL SHALL guardar referencias/metadatos, nunca bytes. Credenciales/bucket SHALL provenir del entorno existente. Una aceptación 202 SHALL tener objeto confirmado y diagnóstico/idempotencia confirmados. Las cargas interrumpidas SHALL poder reconciliarse tras reinicio mediante registro durable; el rollback SQL no SHALL presentarse como eliminación automática de S3.

#### Scenario: Persistencia exitosa
- **WHEN** la carga se confirma
- **THEN** la foto queda privada bajo clave generada por servidor y la base conserva referencia sin URL pública ni nombre original del cliente

#### Scenario: S3 indisponible
- **WHEN** S3 falla durante la subida
- **THEN** devuelve 503 STORAGE_UNAVAILABLE sin diagnóstico aceptado; cualquier carga parcial o incierta queda recuperable

#### Scenario: Fallo de commit después de subir
- **WHEN** S3 recibió la foto pero falla o es incierto el commit relacional
- **THEN** responde error controlado de persistencia y conserva información durable para reconciliar; no borra el objeto hasta comprobar que ningún diagnóstico lo referencia

#### Scenario: Limpieza repetida o interrumpida
- **WHEN** el mantenimiento reintenta una carga huérfana tras caída o fallo de delete
- **THEN** puede eliminarla idempotentemente sin afectar cargas activas ni objetos referenciados, y conserva la intención si vuelve a fallar

### Requirement: Entrega privada al propietario
GET /api/v1/diagnoses/{id}/image SHALL exigir Bearer, propiedad y diagnóstico no borrado. SHALL devolver bytes originales con Content-Type real y Cache-Control private, no-store, sin URLs públicas ni redirecciones firmadas. ADMIN en esta ruta SHALL respetar la misma propiedad.

#### Scenario: Descarga propia
- **WHEN** el propietario pide su foto no borrada
- **THEN** recibe 200 con bytes originales, Content-Type y no-store

#### Scenario: Aislamiento de imagen
- **WHEN** se solicita foto ajena, inexistente o borrada
- **THEN** recibe 404 RESOURCE_NOT_FOUND genérico, incluso si el solicitante tiene ADMIN

#### Scenario: Acceso anónimo
- **WHEN** se accede sin autenticación a la API o directamente al objeto privado
- **THEN** la API devuelve 401 y el almacenamiento no entrega la imagen anónimamente

