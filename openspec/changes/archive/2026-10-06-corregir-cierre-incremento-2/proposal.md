## Why
La auditoría reprodujo publicación de recomendaciones inválidas y aceptación de multipart incompleto. El E2E no forma parte del CI y las carreras SQL no tienen evidencia simultánea.

## What Changes
- Validación cerrada de catálogo y finalización multipart obligatoria.
- Aceptación aislada reproducible y carreras reales PostgreSQL obligatorias en CI.
- Alinear OpenSpec con los valores vigentes de OpenAPI, sin alterar eventos ni estados.

## Capabilities
### Modified Capabilities
- `agricultural-catalog-and-feedback`: validación estructural completa.
- `private-image-ingestion-and-storage`: multipart completo y código IMAGE_TOO_LARGE.
- `diagnosis-lifecycle-and-idempotency`: claves y errores conforme a contratos actuales.
- `continuous-integration-foundation`: aceptación Diagnosis obligatoria.

## Impact
Diagnosis, pruebas, CI y documentación. Sin migraciones, entrenamiento ni worker.
