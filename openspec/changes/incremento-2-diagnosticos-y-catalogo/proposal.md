# Proposal

## Why

Una vez completada la infraestructura base y la autenticación de usuarios en el Incremento 1, AgroDiagnóstico V1 requiere habilitar el núcleo del negocio agrícola: la carga segura de fotografías de cultivos de papa y maíz en almacenamiento privado de objetos, la creación y gestión del ciclo de vida de los diagnósticos con garantías de idempotencia y paginación, la estructuración de un catálogo agronómico revisado y versionado, y la captura de retroalimentación de los agricultores.

Este cambio implementa las capacidades esenciales del servicio `diagnosis`, permitiendo a los usuarios autenticados subir imágenes, consultar su historial y recomendaciones sin depender aún de la inferencia en tiempo real ni exponer fotografías en redes públicas.

## What Changes

- **Ingesta y Validación de Imágenes:** Validación estricta en memoria de imágenes multipart (inspección de magic bytes para JPEG, PNG, WebP; límite de tamaño de 10 MiB; decodificación con Pillow y límite dimensional de 24 megapíxeles). Sin campo obligatorio de cultivo manual (RF-07).
- **Almacenamiento Privado S3/SeaweedFS:** Persistencia de fotos exclusivamente como objetos privados en bucket S3 con credenciales segregadas; nunca almacenamiento de bytes binarios en PostgreSQL.
- **Entrega Privada de Imágenes (`GET /api/v1/diagnoses/{id}/image`):** Descarga de fotos reservada exclusivamente al propietario autenticado con cabecera `Cache-Control: private, no-store`; respuesta 404 genérica ante recursos inexistentes o ajenos.
- **Idempotencia de Carga (`Idempotency-Key`):** Tratamiento atómico de solicitudes duplicadas mediante clave ASCII (1..128 caracteres), namespace `(owner_id, "diagnosis_create", key)`, fingerprint `SHA-256(bytes_de_imagen)` y retención no deslizante de 24 horas (86,400 segundos).
- **Máquina de Estados y Ciclo de Vida de Diagnósticos:** Creación en estado inicial `PENDIENTE`, cancelación con `POST /api/v1/diagnoses/{id}/cancel` (válida únicamente en `PENDIENTE`), borrado lógico idempotente (`DELETE /api/v1/diagnoses/{id}`) y consulta de detalle.
- **Historial Paginado:** Endpoint `GET /api/v1/diagnoses` con paginación keyset (`created_at DESC, id DESC`), cursor opaco y límite configurable (1..100, default 20), excluyendo registros con borrado lógico.
- **Catálogo Agrícola Versionado:** Estructura relacional de cultivos (`crops`: `POTATO`, `CORN`), problemas fitosanitarios (`problems`) y recomendaciones preventivas (`recommendations`) con semillas iniciales revisadas (sin dosis químicas no validadas).
- **Gestión Administrativa del Catálogo:** Endpoints de consulta y mutación bajo `/api/v1/admin/crops`, `/admin/problems` y `/admin/recommendations` protegidos con rol `ADMIN`.
- **Retroalimentación de Usuario (Feedback):** Endpoint `POST /api/v1/diagnoses/{id}/feedback` para registrar utilidad (`useful: boolean`, comentario opcional), prohibiendo expresamente su uso para reentrenamiento automático de modelos.

## Capabilities

### New Capabilities

- `private-image-ingestion-and-storage`: Ingesta multipart de imágenes de cultivos (JPEG/PNG/WebP, máx 10 MiB), validación de decodificación y píxeles (máx 24 MP) con Pillow, almacenamiento privado en bucket S3/SeaweedFS y entrega privada autorizada con `Cache-Control: private, no-store`.
- `diagnosis-lifecycle-and-idempotency`: Creación y ciclo de vida del diagnóstico (`PENDIENTE`, cancelación, borrado lógico), protección por `Idempotency-Key` (retención 24h, fingerprint SHA-256), consulta paginada keyset del historial y aislamiento estricto 404 para recursos ajenos o inexistentes.
- `agricultural-catalog-and-feedback`: Modelado y persistencia del catálogo agrícola versionado (cultivos papa/maíz, problemas y recomendaciones preventivas), semillas iniciales, administración CRUD restringida al rol ADMIN y registro de feedback del usuario (`useful: boolean`) sin reentrenamiento automático.

### Modified Capabilities

<!-- Ninguna especificación existente cambia de comportamiento; se incorporan nuevas capacidades de dominio para el microservicio diagnosis. -->

## Impact

- **Código y Servicio:** Implementación en `services/diagnosis/` (modelos SQLAlchemy, endpoints FastAPI, adaptadores de almacenamiento S3, dependencias de autenticación JWT y validadores de imágenes).
- **Dependencias:** Incorporación de `pillow` en `services/diagnosis/pyproject.toml` para decodificación y verificación dimensional de imágenes.
- **Base de Datos:** Nueva migración Alembic en `services/diagnosis/migrations/versions/` para tablas `diagnoses`, `idempotency_keys`, `crops`, `problems`, `recommendations` y `diagnosis_feedback`, junto a semillas de catálogo.
- **Contratos:** Promoción e incorporación de contratos en `contracts/openapi/diagnosis.openapi.json`, `contracts/operations.json` y `contracts/deferred-operations.json`.
- **Infraestructura:** Conexión del servicio diagnosis con el almacenamiento S3/SeaweedFS (`s3-1`) y enrutamiento en Nginx (`/api/v1/diagnoses`).
