# Incrementos de AgroDiagnóstico V1

Estado actual: estructura y auditoría del equipo disponibles; grupos 1–7 del Incremento 0 completados (reconciliación, ADR, contratos, persistencia, entorno técnico integrado, inventario inicial y CI local). OpenSpec registra 38/38 tareas; la aplicación de negocio y la curación real de datos siguen pendientes para incrementos posteriores. CI remota aprobada.

| Incremento | Resultado previsto | Estado |
| --- | --- | --- |
| 0 | Entorno Compose, contratos HTTP/eventos, migraciones base, CI e inventario de datos | Verificado: grupos 1–7 terminados; 8 operaciones de salud implementadas; 19 contract-only |
| 1 | Registro, sesiones, roles, perfil, cambio y recuperación de contraseña, autorización | Pendiente |
| 2 | Imágenes privadas, validación y formatos, diagnósticos, catálogo, historial, feedback | Pendiente |
| 3 | RabbitMQ, outbox/inbox, lease, worker provisional e idempotencia | Pendiente; resultados simulados, no diagnósticos reales |
| 4 | Dataset autorizado, cultivo automático, entrenamiento, evaluación y modelo validado | Pendiente; siete clases candidatas |
| 5 | Notificaciones, lectura de avisos, interfaz final, observabilidad, recuperación, pruebas y despliegue con dominio, HTTPS, Cloudflare y CDN | Pendiente |

Gemini, voz, PWA y detector de plagas son extensiones posteriores opcionales.

La [fuente V1](reference/Definicion_Base_AgroDiagnostico_V1_Limpia.docx) se interpreta junto con la [reconciliación](reference/RECONCILIACION-V1.md). Consulta [DEVELOPMENT](DEVELOPMENT.md) para el proceso y [tasks.md](../openspec/changes/incremento-0-base-integrada/tasks.md) para el avance verificable; una carpeta o contrato previsto no acredita funcionalidad.

Aceptación integrada local del grupo 7: 7.1–7.4 verificadas, incluida CI remota. [Evidencia](evidence/INCREMENTO-0-GRUPO-7.md). No se sincroniza ni archiva el cambio.

Historial de corrección: [primera ejecución fallida 36743640034](https://github.com/RonaldoMarquina/agrodiagnostico_V1/actions/runs/36743640034). [Evidencia](evidence/INCREMENTO-0-GRUPO-7-REMOTO.md).

Estado final del Incremento 0: [Application CI 36749372314 aprobada](https://github.com/RonaldoMarquina/agrodiagnostico_V1/actions/runs/36749372314) sobre `97472b1`. [Evidencia](evidence/INCREMENTO-0-GRUPO-7-REMOTO.md).
