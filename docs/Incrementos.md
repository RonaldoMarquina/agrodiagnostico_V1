# Incrementos de AgroDiagnóstico V1

Estado actual: estructura y auditoría del equipo disponibles; grupos 1–7 del Incremento 0 completados (reconciliación, ADR, contratos, persistencia, entorno técnico integrado, inventario inicial y CI local). OpenSpec registra 38/38 tareas; la aplicación de negocio y la curación real de datos siguen pendientes para incrementos posteriores. CI remota aprobada.

| Incremento | Resultado previsto | Estado |
| --- | --- | --- |
| 0 | Entorno Compose, contratos HTTP/eventos, migraciones base, CI e inventario de datos | Verificado: grupos 1–7 terminados; 8 operaciones de salud implementadas; 19 contract-only |
| 1 | Registro, sesiones, roles, perfil, cambio y recuperación de contraseña, autorización | Verificado: grupos 1–7 terminados; 12 operaciones de identidad implementadas; Ed25519 asimétrico, PostgreSQL compartido, rotación atómica y auditoría inmutable |
| 2 | Imágenes privadas, validación y formatos, diagnósticos, catálogo, historial, feedback | Pendiente |
| 3 | RabbitMQ, outbox/inbox, lease, worker provisional e idempotencia | Pendiente; resultados simulados, no diagnósticos reales |
| 4 | Dataset autorizado, cultivo automático, entrenamiento, evaluación y modelo validado | Pendiente; siete clases candidatas |
| 5 | Notificaciones, lectura de avisos, interfaz final, observabilidad, recuperación, pruebas y despliegue con dominio, HTTPS, Cloudflare y CDN | Pendiente |

Gemini, voz, PWA y detector de plagas son extensiones posteriores opcionales.

La [fuente V1](reference/Definicion_Base_AgroDiagnostico_V1_Limpia.docx) se interpreta junto con la [reconciliación](reference/RECONCILIACION-V1.md). Consulta [DEVELOPMENT](DEVELOPMENT.md) para el proceso y [tasks.md](../openspec/changes/archive/2026-09-30-incremento-0-base-integrada/tasks.md) para el avance verificable; una carpeta o contrato previsto no acredita funcionalidad.

Aceptación integrada local del grupo 7: 7.1–7.4 verificadas, incluida CI remota. [Evidencia](evidence/INCREMENTO-0-GRUPO-7.md). Los cinco deltas están sincronizados en `openspec/specs/` y el cambio está archivado.

Estado final del Incremento 1: Grupos 1–7 concluidos y verificados (38/38 pruebas de identidad, contratos OpenAPI y pruebas multi-instancia contra PostgreSQL). [Evidencia](evidence/INCREMENTO-1-AUDIT.md). Las 12 operaciones de negocio del servicio identity han sido implementadas; los tres deltas están sincronizados en `openspec/specs/` y el cambio está archivado en [tasks.md](../openspec/changes/archive/2026-09-30-incremento-1-identidad-y-autorizacion/tasks.md). Los incrementos 2–5 permanecen pendientes.
