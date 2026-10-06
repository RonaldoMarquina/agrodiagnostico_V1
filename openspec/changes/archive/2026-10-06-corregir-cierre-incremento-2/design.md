## Context
La suite existente pasa aunque acepta source_refs vacío, elementos numéricos y multipart truncado. El script E2E depende de imágenes Docker preexistentes.
## Goals / Non-Goals
Corregir cinco hallazgos de auditoría y demostrar carreras con sesiones PostgreSQL independientes. No introducir inferencia ni alterar el archivo histórico.
## Decisions
Validar cuerpos administrativos contra modelos estrictos equivalentes a OpenAPI antes de mutar; evidencia inválida devuelve CATALOG_REVIEW_REQUIRED. Exigir callback final de multipart y archivo image. Mantener IMAGE_TOO_LARGE y regex de clave vigentes; documentar NOT_FOUND en rutas actuales y RESOURCE_NOT_FOUND en feedback. Construir imágenes aisladas desde el checkout para E2E. Ejecutar carreras SQL con barreras y conexiones independientes, junto al E2E.
## Risks / Trade-offs
Se rechazan entradas antes aceptadas que violan el contrato. Docker requiere acceso al daemon e imágenes base. Las pruebas solo usan infraestructura desechable.
