# Tasks

## 1. Contratos OpenAPI, Dependencias y Modelos de Diagnosis

- [ ] 1.1 Formalizar en `contracts/openapi/diagnosis.openapi.json` los contratos para `POST /api/v1/diagnoses/{id}/feedback`, `GET/POST /api/v1/admin/crops`, `GET/POST /api/v1/admin/problems`, `GET/POST /api/v1/admin/recommendations` y `GET /api/v1/admin/diagnoses`, actualizando `contracts/operations.json`, `contracts/security-matrix.json` y `contracts/deferred-operations.json`, y verificar con `scripts/validate_contracts.py`.
- [ ] 1.2 Agregar la dependencia `pillow` a `services/diagnosis/pyproject.toml`, regenerar `uv.lock` y verificar la instalación limpia en el entorno.
- [ ] 1.3 Definir los modelos SQLAlchemy en `services/diagnosis/app/domain/models.py` (`Diagnosis`, `IdempotencyKey`, `Crop`, `Problem`, `Recommendation`, `DiagnosisFeedback`), y verificar consistencia de relaciones, claves e índices.
- [ ] 1.4 Crear la migración Alembic `0002_diagnosis_domain_and_seeds.py` con tablas, restricciones y datos semilla iniciales de papa y maíz, y verificar su aplicación contra PostgreSQL (`agro_dev`).

## 2. Ingesta y Validación de Imágenes, y Adaptador S3

- [ ] 2.1 Implementar el módulo de validación gráfica en memoria en `services/diagnosis/app/infrastructure/image_validation.py` (inspección de magic bytes JPEG/PNG/WebP, límite de 10 MiB, decodificación PIL y límite de 24 MP), y verificar con pruebas unitarias de casos válidos, corruptos, no soportados y sobredimensionados.
- [ ] 2.2 Implementar el cliente y repositorio de almacenamiento de objetos en `services/diagnosis/app/infrastructure/s3_storage.py` (subida privada con clave `diagnoses/{id}/original.{ext}` y recuperación de stream con credenciales de `S3_CREDENTIALS_FILE`), y verificar con pruebas de integración contra el contenedor S3/SeaweedFS.
- [ ] 2.3 Implementar el endpoint `GET /api/v1/diagnoses/{id}/image` con verificación de propiedad Bearer (`owner_id == sub`), cabecera `Cache-Control: private, no-store` y respuesta 404 genérica ante recursos ajenos o inexistentes, y verificar con pruebas de entrega autorizada y denegación.

## 3. Idempotencia y Creación de Diagnósticos

- [ ] 3.1 Implementar el servicio de idempotencia transaccional en `services/diagnosis/app/application/idempotency.py` (namespace `owner_id + operation + key`, fingerprint SHA-256 de bytes de imagen y retención de 24h), y verificar con pruebas unitarias y de concurrencia.
- [ ] 3.2 Implementar el endpoint `POST /api/v1/diagnoses` que valida la imagen multipart, aplica idempotencia, almacena el objeto en S3, persiste el registro en estado `PENDIENTE` y devuelve HTTP 202 con el identificador UUID, y verificar con pruebas de carga válida, reintentos con misma y distinta imagen, y rechazos 400/413/415.

## 4. Ciclo de Vida, Cancelación y Consulta de Historial

- [ ] 4.1 Implementar el endpoint de cancelación `POST /api/v1/diagnoses/{id}/cancel` (válida únicamente en `PENDIENTE`, conflicto 409 si ya no es cancelable y 404 para ajenos), y verificar con pruebas de cancelación exitosa y rechazo por estado.
- [ ] 4.2 Implementar el borrado lógico idempotente `DELETE /api/v1/diagnoses/{id}` (`deleted_at = NOW()`, HTTP 204) y la consulta de detalle `GET /api/v1/diagnoses/{id}` con aislamiento 404, y verificar con pruebas de borrado y consulta.
- [ ] 4.3 Implementar el endpoint de historial `GET /api/v1/diagnoses` con paginación keyset (`created_at DESC, id DESC`), cursor opaco codificado y filtro de exclusión de registros eliminados, y verificar con pruebas de ordenamiento, límites y paginación multicursor.

## 5. Catálogo Agrícola, Administración y Feedback

- [ ] 5.1 Implementar endpoints de consulta de catálogo para usuarios (`GET /api/v1/crops`, `GET /api/v1/crops/{code}/problems`, `GET /api/v1/problems/{code}/recommendations`), y verificar con pruebas de lectura de semillas de papa y maíz.
- [ ] 5.2 Implementar los endpoints administrativos de catálogo bajo `/api/v1/admin/crops`, `/admin/problems` y `/admin/recommendations` protegidos con rol `ADMIN`, y verificar permisos exclusivos y denegación 403 a usuarios con rol `USER`.
- [ ] 5.3 Implementar el endpoint `POST /api/v1/diagnoses/{id}/feedback` para registrar utilidad (`useful: boolean` y comentario opcional) con validación de propiedad y verificación de que no dispare reentrenamiento de modelos, y verificar con pruebas de feedback propio y rechazo 404 ajeno.

## 6. Integración en Nginx, Pruebas E2E y Verificación

- [ ] 6.1 Configurar el proxy inverso Nginx (`infra/nginx/default.conf`) para enrutar `/api/v1/diagnoses` y `/api/v1/crops` hacia `diagnosis_backend`, propagando cabeceras y límites de cuerpo hasta 10 MiB, y verificar sintaxis con `nginx -t`.
- [ ] 6.2 Implementar pruebas de integración completas del microservicio `diagnosis` abarcando el flujo completo: autenticación con JWT Ed25519 emitido por `identity`, ingesta de foto, S3 privado, idempotencia, historial paginado, cancelación y feedback.
- [ ] 6.3 Promocionar operaciones en contratos OpenAPI, ejecutar suite de pruebas de backend y validación de contratos, y registrar la evidencia en `docs/evidence/INCREMENTO-2-AUDIT.md`.
