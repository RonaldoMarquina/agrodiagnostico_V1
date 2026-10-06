# ADR-0007 — Corrección del cierre del incremento 2

Fecha: 2026-10-06. Estado: adoptado. Complementa ADR-0006.

## Contexto
La auditoría posterior encontró validación incompleta del catálogo y multipart, discrepancias documentales y ausencia del E2E en CI. El archivo original permanece como evidencia histórica.

## Decisión
Se preserva la interfaz OpenAPI implementada: Idempotency-Key cumple `^[A-Za-z0-9._:-]{1,128}$`; tamaño excesivo usa `IMAGE_TOO_LARGE`; detalle, imagen, cancelación y borrado usan `NOT_FOUND`, feedback usa `RESOURCE_NOT_FOUND`. Todos los 404 de propiedad mantienen aislamiento genérico. Se rectifican las expresiones anteriores de ADR-0006 y OpenSpec; no se introducen cambios de estado, eventos ni propiedad de datos.

Catálogo administrativo valida cuerpos cerrados, tipos estrictos, longitudes y listas. Fuentes vacías o evidencia inválida producen `CATALOG_REVIEW_REQUIRED`; otros defectos estructurales producen `INVALID_REQUEST`. Multipart debe terminar y contener exactamente un archivo image; rechazo ocurre antes de persistencia.

CI construye imágenes del checkout en etiquetas aisladas, ejecuta aceptación y carreras con conexiones PostgreSQL independientes y limpia recursos. No depende de imágenes locales construidas manualmente. El worker, broker, modelo y contenido agronómico continúan fuera de este correctivo.

## Consecuencias
Entradas inválidas antes aceptadas se rechazan. No requiere migraciones. La nueva etapa de CI consume tiempo Docker adicional; fallar cualquier verificación impide declarar éxito.
