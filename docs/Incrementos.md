# Incrementos de AgroDiagnóstico V1

Estado actual: incrementos 0–2 implementados. El cierre del incremento 2 tiene un correctivo posterior a la auditoría; véase la evidencia de corrección. Los incrementos 3–5 siguen pendientes.

| Incremento | Resultado previsto | Estado |
| --- | --- | --- |
| 0 | Entorno Compose, contratos HTTP/eventos, migraciones base, CI e inventario de datos | Verificado: grupos 1–7 terminados; 8 operaciones de salud implementadas; 19 contract-only |
| 1 | Registro, sesiones, roles, perfil, cambio y recuperación de contraseña, autorización | Implementado y revisado mediante correctivo posterior; 12 operaciones de identidad. Véase evidencia INCREMENTO-1-CORRECCION |
| 2 | Imágenes privadas, validación y formatos, diagnósticos, catálogo, historial, feedback | Implementado; cierre original rectificado por [corrección](evidence/INCREMENTO-2-CORRECCION.md). 20 operaciones de negocio de Diagnosis |
| 3 | RabbitMQ, outbox/inbox, lease, worker provisional e idempotencia | Pendiente; resultados simulados, no diagnósticos reales |
| 4 | Dataset autorizado, cultivo automático, entrenamiento, evaluación y modelo validado | Pendiente; siete clases candidatas |
| 5 | Notificaciones, lectura de avisos, interfaz final, observabilidad, recuperación, pruebas y despliegue con dominio, HTTPS, Cloudflare y CDN | Pendiente |

Gemini, voz, PWA y detector de plagas son extensiones posteriores opcionales.

La [fuente V1](reference/Definicion_Base_AgroDiagnostico_V1_Limpia.docx) se interpreta junto con la [reconciliación](reference/RECONCILIACION-V1.md). Consulta [DEVELOPMENT](DEVELOPMENT.md) para el proceso y [tasks.md](../openspec/changes/archive/2026-09-30-incremento-0-base-integrada/tasks.md) para el avance verificable; una carpeta o contrato previsto no acredita funcionalidad.

Aceptación integrada local del grupo 7: 7.1–7.4 verificadas, incluida CI remota. [Evidencia](evidence/INCREMENTO-0-GRUPO-7.md). Los cinco deltas están sincronizados en `openspec/specs/` y el cambio está archivado.

Estado final del Incremento 1: Grupos 1–7 concluidos y verificados (38/38 pruebas de identidad, contratos OpenAPI y pruebas multi-instancia contra PostgreSQL). [Evidencia](evidence/INCREMENTO-1-AUDIT.md). Las 12 operaciones de negocio del servicio identity han sido implementadas; los tres deltas están sincronizados en `openspec/specs/` y el cambio está archivado en [tasks.md](../openspec/changes/archive/2026-09-30-incremento-1-identidad-y-autorizacion/tasks.md). Los incrementos 3–5 permanecen pendientes.

El cierre original del Incremento 1 fue rectificado tras revisión. [Corrección y límites verificados](evidence/INCREMENTO-1-CORRECCION.md): configuración Ed25519, Origin/CSRF, respuestas, correlación, auditoría y aceptación de procesos independientes. El archivo original se conserva como histórico.

Cierre histórico del Incremento 2: Grupos 1–9 concluidos y verificados (113 pruebas unitarias e integración de Diagnosis, aceptación integral E2E en contenedores aislados vía Nginx, 20 operaciones promovidas a implementadas, 0 dependencias en tiempo de ejecución de RabbitMQ/Redis/AI). [Evidencia](evidence/INCREMENTO-2-AUDIT.md). Tareas archivadas en [tasks.md](../openspec/changes/archive/2026-10-06-incremento-2-diagnosticos-y-catalogo/tasks.md). Los incrementos 3–5 permanecen pendientes.

La auditoría posterior y sus correcciones se registran en [INCREMENTO-2-CORRECCION](evidence/INCREMENTO-2-CORRECCION.md). El archivo original conserva su contexto histórico.

CI de cierre del incremento 2 (2026-10-07): 16/16 etapas locales aprobadas, incluidas persistencia, entorno Compose e integraciones Identity/Diagnosis. [Informe](evidence/INCREMENTO-2-CI-LOCAL.json). La verificación remota de este correctivo queda pendiente de publicación autenticada.
