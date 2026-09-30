# Design

## Context

El servicio `services/diagnosis` actualmente solo expone los endpoints técnicos de salud (`/health/live` y `/health/ready`). La infraestructura Docker Compose ya cuenta con el contenedor de almacenamiento compatible con S3 (`s3-1` SeaweedFS) y credenciales segregadas en `.local/persistence/s3_diagnosis.json`, además de la base de datos PostgreSQL `diagnosis` creada con usuario restringido.

Para implementar el Incremento 2, `diagnosis` debe gestionar la ingesta de fotos, la persistencia privada en S3, la máquina de estados de diagnósticos, la idempotencia estricta, el catálogo agrícola y el feedback, interactuando con los JWT asimétricos Ed25519 establecidos en el Incremento 1.

## Goals / Non-Goals

**Goals:**
- Validación multicapa en memoria de imágenes multipart (inspección de magic bytes, límite de 10 MiB, decodificación PIL y límite de 24 MP).
- Almacenamiento privado en bucket S3 con entrega autenticada en `GET /api/v1/diagnoses/{id}/image` con cabecera `Cache-Control: private, no-store`.
- Manejo atómico de idempotencia mediante `Idempotency-Key` (retención de 24h, fingerprint SHA-256 de bytes de imagen y namespace por usuario).
- Ciclo de vida del diagnóstico (`PENDIENTE`, cancelación, borrado lógico con tombstone y detalle con aislamiento 404).
- Paginación keyset con cursor opaco para el historial propio en `GET /api/v1/diagnoses`.
- Modelado relacional del catálogo agrícola (`crops`, `problems`, `recommendations`), migración de semillas iniciales y CRUD administrativo protegido con rol `ADMIN`.
- Endpoint `POST /api/v1/diagnoses/{id}/feedback` para registrar utilidad sin conexión a pipelines de reentrenamiento.

**Non-Goals:**
- Integración con el broker RabbitMQ ni procesamiento en segundo plano (reservado para Incremento 3).
- Inferencia técnica o ejecución de modelos PyTorch (reservado para Incrementos 3 y 4).
- Reentrenamiento automático de modelos con imágenes de usuarios o feedback (prohibido normativamente en `AGENTS.md`).
- Generación de URLs públicas o permanentes para fotografías (prohibido por ADR-0002).

## Decisions

### 1. Validación de Imágenes Multicapa en Memoria
- **Decisión:** Validar el archivo en el stream de memoria antes de tocar disco o S3:
  1. *Magic bytes sniffing:* Comprobación de firmas binarias iniciales (`\xff\xd8\xff` para JPEG, `\x89PNG\r\n\x1a\n` para PNG, `RIFF....WEBP` para WebP). Rechazo 415 si discrepa.
  2. *Límite de tamaño:* Comprobación de `content-length` y tamaño real de bytes (`<= 10,485,760 bytes`). Rechazo 413 si excede.
  3. *Decodificación con Pillow:* Apertura en memoria `Image.open(io.BytesIO(data))` estableciendo `Image.MAX_IMAGE_PIXELS = 24_000_000`. Verificación de integridad `img.verify()` y dimensiones (`width * height <= 24,000,000`). Rechazo 400 por corrupción y 413 por megapíxeles excesivos.
- **Alternativa descartada:** Guardar en disco temporal del contenedor antes de validar -> Descartada por riesgo de acumulación de archivos maliciosos y consumo innecesario de I/O.

### 2. Estructura y Clave de Objetos en S3
- **Decisión:** Almacenar los objetos bajo el patrón determinista:
  `diagnoses/{diagnosis_id}/original.{ext}`
  en el bucket privado `agro-diagnoses-private`.
- **Alternativa descartada:** Usar el nombre original del archivo subido por el cliente -> Descartada por riesgo de colisiones, inyección de rutas (path traversal) y filtración de metadatos del cliente.

### 3. Persistencia Atómica de Idempotencia en PostgreSQL
- **Decisión:** Almacenar el registro de idempotencia en la tabla `idempotency_keys` dentro de la misma base de datos `diagnosis`:
  - Columnas: `(id, owner_id, scope, idempotency_key, payload_hash, resource_id, created_at, expires_at)`.
  - Índice UNIQUE sobre `(owner_id, scope, idempotency_key)`.
  - Durante `POST /api/v1/diagnoses`, se ejecuta dentro de una transacción de PostgreSQL: si la clave existe y no ha expirado, se compara `payload_hash` con el hash SHA-256 de los bytes de imagen. Si coincide, devuelve 202 con el `resource_id` previo; si difiere, lanza 409 `IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD`.
- **Alternativa descartada:** Almacenar claves en Redis en memoria -> Descartada para mantener atomicidad transaccional con la creación del diagnóstico y consistencia entre múltiples instancias de diagnosis.

### 4. Paginación Keyset con Cursor Opaco
- **Decisión:** El historial `GET /api/v1/diagnoses` implementa paginación keyset basada en tupla `(created_at, id)`:
  - Orden: `created_at DESC, id DESC`.
  - Filtro para página siguiente: `WHERE (created_at, id) < (cursor_created_at, cursor_id) AND deleted_at IS NULL AND owner_id = :current_user`.
  - Cursor: Serialización JSON codificada en Base64 URL-safe conteniendo `{ "t": "<iso_timestamp>", "id": "<uuid>" }`.
- **Alternativa descartada:** Paginación por offset (`OFFSET n LIMIT m`) -> Descartada por degradación cuadrática de rendimiento en tablas grandes y saltos de filas al insertar nuevos diagnósticos.

### 5. Catálogo Agrícola y Versionado de Recomendaciones
- **Decisión:** Separar cultivos, problemas y recomendaciones en tablas normalizadas:
  - `crops`: código mnemónico (ej. `POTATO`, `CORN`), nombre común, nombre científico, estado activo.
  - `problems`: código (ej. `POTATO_LATE_BLIGHT`), código de cultivo FK, nombre común, nombre científico, tipo de problema (`DISEASE`, `PEST`), estado activo.
  - `recommendations`: ID UUID, problema FK, versión entera (`version = 1`), título, resumen, prácticas culturales, control biológico, medidas preventivas, estado activo.
  - Las recomendaciones nunca incluyen dosis químicas arbitrarias. Los diagnósticos vinculan la recomendación específica por versión para asegurar inmutabilidad histórica.

### 6. Autorización Descentralizada por Clave Pública Ed25519
- **Decisión:** El microservicio `diagnosis` valida el encabezado `Authorization: Bearer <token>` utilizando la clave pública Ed25519 del sistema de identidad (inyectada por variable de entorno o archivo de configuración seguro):
  - Verifica firma EdDSA, issuer (`agrodiagnostico-identity`), audience (`agrodiagnostico-api`) y expiración.
  - Extrae `sub` como `owner_id` y `role` para autorizar rutas administrativas (`ADMIN`).
  - Cero consultas HTTP a `identity` durante la validación de tokens de acceso.

## Risks / Trade-offs

- **[Riesgo de Decompression Bomb en imágenes]** → *Mitigación:* Se valida primero el tamaño en bytes (10 MiB) y se configura `Image.MAX_IMAGE_PIXELS = 24_000_000` en Pillow antes de abrir la imagen.
- **[Riesgo de Latencia de Red con S3 durante la Carga]** → *Mitigación:* Se valida completamente la imagen en memoria antes de invocar `boto3.put_object()`. Si S3 falla, la transacción relacional se revierte automáticamente y se responde 503 sin dejar registros huérfanos.
- **[Riesgo de Peticiones Concurrentes con la Misma Idempotency-Key]** → *Mitigación:* La restricción de unicidad relacional `(owner_id, scope, idempotency_key)` y transacciones con aislamiento garantizan que solo una petición inserte el diagnóstico y las concurrentes capturen la condición de carrera respondiendo 409 `IDEMPOTENCY_IN_PROGRESS`.
