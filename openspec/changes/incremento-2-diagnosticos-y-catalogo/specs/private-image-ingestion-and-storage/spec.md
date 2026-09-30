# Spec Delta

## Purpose

Garantiza la ingesta validada, inspección binaria y almacenamiento privado de fotografías agrícolas en almacenamiento compatible con S3, asegurando descarga autorizada con aislamiento 404 y cabeceras privadas sin exposición pública de URLs.

## ADDED Requirements

### Requirement: Validación estricta y decodificación en memoria de imágenes
El sistema SHALL validar la imagen recibida mediante multipart/form-data en `POST /api/v1/diagnoses` antes de persistir cualquier registro en la base de datos o almacenamiento de objetos. La validación SHALL constatar: (1) que el tamaño del archivo no exceda los 10 MiB (`10,485,760 bytes`), respondiendo con código 413 si se supera; (2) que el formato real determinado por magic bytes corresponda a `image/jpeg`, `image/png` o `image/webp`, respondiendo con código 415 ante formatos no soportados; (3) que los bytes puedan ser decodificados efectivamente como imagen válida mediante biblioteca de procesamiento gráfico (Pillow), respondiendo con código 400 `INVALID_IMAGE` ante archivos corruptos; y (4) que las dimensiones decodificadas (`ancho * alto`) no superen los 24 megapíxeles (`24,000,000 px`), respondiendo con código 413 ante dimensiones excesivas. La solicitud SHALL NOT exigir la especificación manual obligatoria del cultivo por parte del usuario.

#### Scenario: Carga exitosa de imagen válida
- **WHEN** un usuario autenticado envía un archivo multipart de 2 MiB en formato JPEG válido de 1920x1080 píxeles
- **THEN** el sistema valida los magic bytes, decodifica exitosamente la imagen en memoria y procede con el almacenamiento y creación del diagnóstico

#### Scenario: Rechazo por exceso de tamaño de archivo (HTTP 413)
- **WHEN** un cliente envía un archivo que excede los 10 MiB (10,485,760 bytes)
- **THEN** el sistema rechaza la solicitud inmediatamente con código 413 `PAYLOAD_TOO_LARGE` sin persistir el archivo en S3

#### Scenario: Rechazo por formato no soportado (HTTP 415)
- **WHEN** un cliente envía un archivo con extensión `.jpg` pero cuyos bytes reales corresponden a un ejecutable, PDF o formato no soportado (ej. GIF o BMP)
- **THEN** el sistema detecta la discrepancia mediante inspección de magic bytes y rechaza la solicitud con código 415 `UNSUPPORTED_MEDIA_TYPE`

#### Scenario: Rechazo por imagen corrupta o dimensiones superiores a 24 megapíxeles
- **WHEN** un cliente envía un archivo JPEG con cabecera válida pero con stream de datos corrupto o con dimensiones de 6000x5000 píxeles (30 MP)
- **THEN** el sistema rechaza la solicitud con código 400 `INVALID_IMAGE` o 413 según corresponda, sin almacenar el objeto

#### Scenario: Ingesta agnóstica sin cultivo obligatorio
- **WHEN** el cliente envía la imagen sin incluir el parámetro `crop_code` en el cuerpo multipart
- **THEN** el sistema acepta la solicitud de diagnóstico conforme a RF-07 sin rechazar por ausencia de cultivo

### Requirement: Almacenamiento seguro y privado en bucket S3
El sistema SHALL persistir las fotografías validadas exclusivamente como objetos privados en un bucket de almacenamiento compatible con S3 (SeaweedFS / S3). El sistema SHALL generar una clave de objeto opaca con convención determinista por diagnóstico (`diagnoses/{diagnosis_id}/original.{ext}`). El sistema SHALL NOT almacenar los bytes binarios de las imágenes en las tablas de PostgreSQL. Las credenciales de acceso al bucket SHALL obtenerse de forma segregada a través de secretos inyectados por el entorno (`S3_CREDENTIALS_FILE`).

#### Scenario: Persistencia exclusiva como objeto privado en bucket S3
- **WHEN** una imagen pasa satisfactoriamente las validaciones de tamaño, formato y decodificación
- **THEN** el servicio sube el archivo al bucket S3 con su clave privada correspondiente y guarda únicamente la referencia (`object_key`) en la base de datos relacional

#### Scenario: Fallo de almacenamiento S3 produce error sin registrar diagnóstico corrupto
- **WHEN** ocurre una falla transitoria de red o indisponibilidad en el almacenamiento S3 durante la subida
- **THEN** la transacción se aborta, no se crea el diagnóstico en PostgreSQL y el sistema retorna un código 500/503 controlado sin datos huérfanos

### Requirement: Entrega privada y autenticada de imagen al propietario
El sistema SHALL permitir la descarga o visualización de la fotografía original asociada a un diagnóstico mediante el endpoint `GET /api/v1/diagnoses/{id}/image`. La solicitud SHALL requerir un token Bearer de usuario válido y comprobar que el `owner_id` del diagnóstico coincida con el identificador del usuario autenticado (`sub`). La respuesta SHALL transmitir los bytes de la imagen con la cabecera `Content-Type` correspondiente y la cabecera estricta `Cache-Control: private, no-store`. El sistema SHALL NOT retornar URLs públicas ni permitir el acceso anónimo o a través de redes de distribución de contenido (CDN) públicas.

#### Scenario: Propietario descarga su imagen original autenticado
- **WHEN** el usuario propietario del diagnóstico realiza una solicitud GET a `/api/v1/diagnoses/{id}/image` con su token Bearer
- **THEN** el sistema verifica la propiedad, recupera el objeto desde S3 y transmite los bytes de la imagen con código 200 y cabecera `Cache-Control: private, no-store`

#### Scenario: Intento de descarga por usuario ajeno devuelve 404 genérico
- **WHEN** un usuario autenticado A intenta acceder a la imagen de un diagnóstico perteneciente al usuario B
- **THEN** el sistema responde con código 404 genérico `RESOURCE_NOT_FOUND` idéntico al de un identificador inexistente, impidiendo determinar si la imagen o diagnóstico existen

#### Scenario: Cabecera Cache-Control privada sin caché compartida ni CDN
- **WHEN** se sirve cualquier imagen a través de `/api/v1/diagnoses/{id}/image`
- **THEN** la respuesta incluye obligatoriamente `Cache-Control: private, no-store` impidiendo que proxies intermedios o navegadores almacenen fotos de otros usuarios en caché compartida
