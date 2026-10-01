# Proposal

## Why

Tras el Incremento 1, Diagnosis todavía expone solo salud. El Incremento 2 habilita carga privada, consulta y administración del dominio con contratos verificables, conservando la separación entre un registro de diagnóstico y un resultado de inferencia. El implementador debe poder ejecutar tareas sin inventar reglas de negocio, recomendaciones agronómicas ni garantías transaccionales entre PostgreSQL y S3.

## What Changes

- Ingesta autenticada de un único campo multipart `image`, sin cultivo manual obligatorio: JPEG/PNG/WebP, máximo 10,485,760 bytes y 24,000,000 píxeles decodificados. HEIC/HEIF sigue pendiente de conversor y E2E para V1; inicialmente devuelve 415.
- Almacenamiento privado mediante la configuración S3 existente, entrega al propietario y recuperación de objetos huérfanos mediante intenciones de carga durables. No se promete una transacción distribuida S3/PostgreSQL.
- Creación `PENDIENTE`, idempotencia por propietario/operación/clave durante 86,400 segundos no deslizantes, cancelación atómica, borrado lógico idempotente, detalle e historial keyset con cursores ligados a principal y operación.
- Verificación local Ed25519 con clave pública, errores y correlación conformes a los contratos; ninguna lectura de tablas de Identity.
- Catálogo de `POTATO` y `MAIZE`, con las siete clases candidatas contractuales, incluidas las condiciones sanas. Ser candidato o estar activo en el catálogo no acredita validación del modelo.
- Consultas de catálogo autenticadas y administración mediante GET/POST/PATCH explícitos; versiones inmutables de recomendaciones y auditoría propia de Diagnosis. Solo se publica contenido con fuentes y aprobación registradas. No se inventan recomendaciones semilla: sin evidencia aprobada la consulta devuelve una lista vacía.
- Supervisión administrativa paginada de metadatos de diagnósticos, sin acceso adicional a fotos ajenas.
- Feedback único y actualizable por diagnóstico propio, únicamente en `COMPLETADO` o `NO_CONCLUYENTE`, sin uso automático para entrenamiento.
- Integración de todas las rutas en Nginx, secretos públicos y de cursor en Compose, pruebas por grupo y evidencia reproducible.

El alcance implementable termina en creación, consulta, cancelación y administración. Broker, outbox/inbox, claim/lease, transiciones por análisis y worker pertenecen al Incremento 3; el modelo validado al 4. En este incremento los nuevos diagnósticos permanecen pendientes salvo cancelación. Las pruebas de resultados finales usan fixtures internos, nunca un endpoint público que simule inferencia.

## Capabilities

### New Capabilities

- `private-image-ingestion-and-storage`: carga limitada, decodificación real, almacenamiento privado, recuperación de cargas interrumpidas y entrega autorizada.
- `diagnosis-lifecycle-and-idempotency`: autenticación de Diagnosis, creación idempotente, cancelación, tombstones, historial y supervisión administrativa auditada.
- `agricultural-catalog-and-feedback`: catálogo candidato coherente con contratos, publicación revisada y versionada, administración y feedback propio.

### Modified Capabilities

Ninguna. Se aplican las capacidades vigentes de autenticación, autorización y contratos sin cambiar sus requisitos.

## Impact

- `services/diagnosis/`: API, aplicación, persistencia, validadores y adaptadores; dependencias bloqueadas de imágenes, multipart y verificación JWT Ed25519.
- Base propia `diagnosis`: diagnósticos, claves de idempotencia, intenciones de carga, catálogo, versiones, feedback y auditoría. Sin claves foráneas a tablas de otros servicios.
- `contracts/`: ampliar OpenAPI y esquemas, operaciones, matriz de seguridad, escenarios y pendientes exclusivamente del incremento; conservar nombres y comportamiento ya contratados.
- `docker-compose.yml`, preparación local y Nginx: verificación con clave pública, secreto de cursor, bucket configurado, rutas específicas y límite de transporte con margen multipart.
- `docs/`: ADR de decisiones de Diagnosis, operación, seguridad, catálogo y evidencia; sincronización de deltas y archivo solo al completar implementación y verificaciones.
