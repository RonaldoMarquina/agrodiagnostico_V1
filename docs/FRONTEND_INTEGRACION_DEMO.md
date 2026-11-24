# Integración del frontend en modo demostración

El flujo disponible guarda la foto privada, registra la solicitud y recorre la cola hasta el historial. El worker `demo` emite una abstención y Diagnosis registra `NO_CONCLUYENTE` con `reason_code: UNSUPPORTED_CLASS`. La evaluación externa v1.4.3 concluyó con G2 rechazado y G3 sin promoción. [Acta de cierre](evidence/INCREMENTO-4-CIERRE-V1.4.3.md).

Para probar el recorrido local, prepara los secretos según la guía de desarrollo y arranca el stack con `docker compose --profile demo up -d --build --wait --wait-timeout 180`. El perfil necesita los publicadores y consumidores del stack para completar el ciclo. Usa únicamente el worker de demostración para este recorrido. [Preparación local](DEVELOPMENT.md#preparación-y-arranque-local) · [Operación de IA](operations/ai-model-operations.md).

## Endpoints disponibles

Las rutas de la tabla se resuelven en el mismo origen del frontend, a través de Nginx. Los endpoints de usuario requieren `Authorization: Bearer <access_token>`. El servidor genera `X-Correlation-ID` si falta y lo devuelve en la respuesta. Si el cliente lo envía, debe ser un UUID. [Inventario de operaciones](../contracts/operations.json) · [OpenAPI de Diagnosis](../contracts/openapi/diagnosis.openapi.json).

| Método y ruta | Respuesta y uso |
| --- | --- |
| `POST /api/v1/diagnoses` | `202` con `id`, `status` y `created_at`. Acepta la carga y encola la solicitud. |
| `GET /api/v1/diagnoses/{id}` | `200` con el detalle propio. Consultar durante el procesamiento y al abrir un resultado. |
| `GET /api/v1/diagnoses` | `200` con `{items, next_cursor}`. Historial propio de más reciente a más antiguo. `limit` de 1 a 100, por defecto 20. Tratar `cursor` como opaco y detener la paginación si `next_cursor` es `null`. |
| `GET /api/v1/diagnoses/{id}/image` | `200` binario con MIME real y `Cache-Control: private, no-store`. Usar fetch autenticado, crear una URL de objeto temporal para la vista y revocarla al cerrar o salir. |
| `POST /api/v1/diagnoses/{id}/cancel` | `200` si la cancelación gana mientras está `PENDIENTE`. Si cambió el estado, `409` y volver a consultar. |
| `DELETE /api/v1/diagnoses/{id}` | `204` sin cuerpo. El borrado lógico retira la entrada del historial. |
| `POST /api/v1/diagnoses/{id}/feedback` | `201` al crear, `200` al reemplazar. Envía `useful` booleano y un `comment` opcional de hasta 1000 caracteres. Disponible en `COMPLETADO` y `NO_CONCLUYENTE`. |
| `GET /api/v1/crops`, `GET /api/v1/crops/{code}/problems`, `GET /api/v1/problems/{code}/recommendations` | `200` con `{items}`. El inventario de catálogo es informativo. Las entradas de catálogo no habilitan diagnósticos en demo. |

Operaciones complementarias implementadas para las pantallas de V1:

| Pantalla | Rutas bajo `/api/v1` |
| --- | --- |
| Sesión y recuperación | `POST /auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/password-recovery` y `/auth/password-recovery/confirm`. Refresh y logout requieren cookie HttpOnly, `X-CSRF-Token` y origen permitido. Mantener el access token en memoria. |
| Cuenta | `GET/PATCH /profile`, `PUT /profile/password`. |
| Avisos y preferencias | `GET /notifications`, `PATCH /notifications/{id}/read`, `PATCH /notifications/read-all` con `{updated_count}`, `GET /notifications/unread-count` con `{unread_count}` y `GET/PATCH /notification-preferences`. |
| Cuentas y auditoría de Identity | `GET /admin/users`, `GET /admin/users/stats`, `GET /admin/audit/identity`, `PATCH /admin/users/{id}/block` y `/activate`. El bloqueo admite `reason` opcional y devuelve `409 SELF_BLOCK_NOT_ALLOWED` si el administrador intenta bloquear su propia cuenta. |
| Supervisión y auditoría de Diagnosis | `GET /admin/diagnoses`, `GET /admin/audit/diagnosis` y `GET /admin/diagnoses/{id}/image`. La vista de supervisión lista metadatos. Carga la foto solo tras una acción explícita en la interfaz, porque cada lectura administrativa queda auditada. |
| Métricas, modelos y monitoreo | `GET /admin/metrics/summary`, `GET /admin/models` y `GET /admin/system/status`. En demo, el inventario devuelve `INACTIVE_GATE_BLOCKED` con `active_model: null`. El monitoreo puede indicar `UNKNOWN` para dependencias que agotan el plazo. |
| Catálogo administrativo | `GET/POST /admin/{crops,problems,recommendations}` y sus `PATCH` por código o ID. |
| Asistente opcional | `POST /assistant/messages` con el perfil `assistant` configurado. `AUDIT` y `MONITORING` son destinos para rol `ADMIN` que se conectarán a las vistas del Paso 3B. |

Las rutas administrativas requieren `ADMIN`. La ruta de fotografía del propietario mantiene el aislamiento por cuenta incluso para ese rol. Las rutas `/internal/*`, `/health/*`, el broker y el almacenamiento privado quedan fuera del cliente. [Contratos de API](API_CONTRACTS.md) · [Evidencia de administración y observabilidad](evidence/INCREMENTO-5-ADMIN-Y-OBSERVABILIDAD.md).

### Carga y seguimiento

Envía `FormData` con un archivo en `image`. Acepta JPEG, PNG o WebP estáticos, hasta 10 MiB y 24 millones de píxeles decodificados. `identified_crop` es opcional y, si se incluye, el único valor admitido es `POTATO` como declaración del usuario. Deja que el navegador genere el delimitador multipart. Usa una `Idempotency-Key` por carga intencional y conserva durante los reintentos la misma clave, bytes y valor u omisión de `identified_crop`. La ventana del servidor es de 24 horas desde la primera aceptación. [Contrato de carga](../contracts/openapi/diagnosis.openapi.json) · [Implementación del fingerprint](../services/diagnosis/app/application/diagnoses.py).

Ejemplo de `202` inicial. Un replay puede devolver el estado actual con el mismo identificador.

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "status": "PENDIENTE",
  "created_at": "2026-11-24T15:00:00Z"
}
```

Consulta el detalle mientras el estado siga en `PENDIENTE` o `PROCESANDO`. Detén el sondeo al llegar a un estado terminal, salir de la pantalla o perder sesión. Si la espera se alarga, conserva el identificador y ofrece volver al historial. Utiliza siempre el estado del servidor.

| Estado | Presentación en la interfaz |
| --- | --- |
| `PENDIENTE` | «Solicitud recibida. En espera de procesamiento». Ofrecer cancelar. |
| `PROCESANDO` | «Solicitud en procesamiento». Mostrar progreso indeterminado. |
| `NO_CONCLUYENTE` | «Resultado no concluyente». Estado terminal con `reason_code`. En demo, usar el mensaje de abajo y mantener disponible el feedback. |
| `COMPLETADO` | Mostrar el resultado histórico que entregue la API y su recomendación versionada. Mostrar confianza estimada solo si viene informada. El worker demo no genera este estado. |
| `FALLIDO` | «No pudimos completar la solicitud». Estado terminal con `reason_code` operativo. |
| `CANCELADO` | «Solicitud cancelada». Estado terminal. |

### Resultado no concluyente y mensajes de demo

Coloca el texto «Modo demostración. El diagnóstico real no está habilitado» antes de la carga. En el detalle del resultado de demo usa «Resultado no concluyente. Tu solicitud recorrió el flujo de demostración». En esta variante se omite `result`. La pantalla omite enfermedad, probabilidad y recomendación. El cliente toma el modo de la configuración del entorno presentado. `UNSUPPORTED_CLASS` también existe fuera de demo y por sí solo no identifica el entorno.

Ejemplo de `GET /api/v1/diagnoses/{id}` con `200`:

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "status": "NO_CONCLUYENTE",
  "created_at": "2026-11-24T15:00:00Z",
  "updated_at": "2026-11-24T15:00:03Z",
  "reason_code": "UNSUPPORTED_CLASS"
}
```

Ejemplo de feedback disponible después de la abstención:

```json
{
  "useful": true,
  "comment": "El aviso de modo demostración fue claro."
}
```

Para otros registros, el contrato también permite `LOW_CONFIDENCE`, `UNSUPPORTED_CROP`, `BAD_IMAGE` y `CATALOG_UNAVAILABLE`. Muestra mensajes propios de cada motivo si corresponde y usa «No hay diagnóstico disponible» como texto genérico. El [esquema común](../contracts/schemas/common.schema.json) define las variantes de detalle, resumen y error.

## Errores y recuperación

| Estado HTTP | Código o condición | Acción de la interfaz |
| --- | --- | --- |
| `400` | `INVALID_REQUEST`, `INVALID_IMAGE`, `INVALID_PAGINATION` | Explicar el dato inválido, permitir escoger otra imagen o volver a la primera página. |
| `401` / `403` | Sesión ausente o vencida, permiso insuficiente o CSRF inválido | Recuperar sesión cuando corresponda. Mantener fuera de la vista las acciones administrativas si el rol carece de acceso. |
| `404` | Recurso ausente, ajeno o borrado | Mostrar «Recurso no encontrado». Aplicar el mismo mensaje para todos los casos de propiedad. |
| `409` | `IDEMPOTENCY_IN_PROGRESS`, `IDEMPOTENCY_CONFLICT`, `IDEMPOTENCY_RESOURCE_DELETED`, `DIAGNOSIS_NOT_CANCELABLE`, `FEEDBACK_NOT_ALLOWED` | Reintentar con la misma carga solo si sigue en curso. Ante conflicto o borrado, pedir una acción nueva explícita. En cancelación o feedback, actualizar el detalle. |
| `413` / `415` | Tamaño o formato inválido | Mostrar los límites y solicitar otra imagen. |
| `503` o fallo de red | Persistencia, almacenamiento, extensión o conexión temporalmente indisponible | Ofrecer reintento. Si la carga pudo haberse aceptado, reutilizar la clave y contenido originales. |

Ejemplo contractual del detalle ante un `404`:

```json
{
  "code": "NOT_FOUND",
  "message": "Recurso no encontrado.",
  "correlation_id": "22222222-2222-4222-8222-222222222222"
}
```

Conserva `correlation_id` para soporte si llega en el cuerpo o la cabecera. Trata un cuerpo ausente o no JSON del proxy como error HTTP recuperable según el estado, sin mostrar HTML ni datos internos.

## Qué falta para cerrar la entrega visual

1. **Frontend.** Sustituir la página técnica por rutas React con sesión y roles, carga/previsualización, detalle, historial, cancelación, borrado, feedback, avisos y preferencias. Conectar las pantallas administrativas a las rutas de la tabla. Modelar los estados como variantes de TypeScript y conservar HTTP, código y correlación en el cliente. Adaptar el diseño V1.2 al banner y a la abstención de demo. [Frontend actual](../frontend/README.md) · [Diseño V1.2](AgroDiagnostico_Diseno_Frontend_V1.2_Codex.md).
2. **Integración visual.** Probar en navegador real vía Nginx, con datos de prueba y dos cuentas, sesión y rutas directas, carga y replay sin duplicados, recorrido de la cola hasta `NO_CONCLUYENTE`, cancelación en carrera, 404 ajeno, historial y avisos. Verificar accesibilidad, vista móvil y casos de error. El `try_files` actual de Nginx devuelve 404 para rutas SPA profundas sin archivo. Falta habilitar su recarga directa conservando los bloqueos de API e internas. [Configuración Nginx](../infra/nginx/default.conf) · [Criterios de pruebas](TESTING.md).
3. **Exposición.** Preparar origen y dominio, acceso administrativo, DNS con proxy de Cloudflare, TLS hasta el origen en Full (strict) y redirección HTTPS. Verificar CDN de estáticos versionados y bypass de caché para API y fotos, servicios internos no accesibles desde Internet y smoke del flujo demo en el dominio. Guardar evidencia del navegador y del despliegue para la exposición. [Guía de despliegue](DEPLOYMENT.md).
