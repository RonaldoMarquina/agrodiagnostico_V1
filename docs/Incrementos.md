# Incrementos de AgroDiagnóstico V1

Estado actual: incrementos 0–3 implementados y verificados. Los ciclos v1.2.0 y v1.3.2 del incremento 4 son históricos; v1.3.2 falló el rechazo sano con **8/32 falsas publicaciones y 24/32 abstenciones**. Para [v1.4.0](evidence/INCREMENTO-4-G0-G1-V1.4.0-MATERIALIZACION.md), G0/G1 están cerrados: PlantVillage se limita a TRAIN/VAL y Sikkim v1 está sellado solo como EXTERNAL. Todavía no se entrenó ni se evaluó EXTERNAL; G2/G3 y la activación siguen pendientes. Incremento 5 pendiente.

| Incremento | Resultado previsto | Estado |
| --- | --- | --- |
| 0 | Entorno Compose, contratos HTTP/eventos, migraciones base, CI e inventario de datos | Verificado: grupos 1–7 terminados; 8 operaciones de salud implementadas; 19 contract-only |
| 1 | Registro, sesiones, roles, perfil, cambio y recuperación de contraseña, autorización | Implementado y revisado mediante correctivo posterior; 12 operaciones de identidad. Véase evidencia INCREMENTO-1-CORRECCION |
| 2 | Imágenes privadas, validación y formatos, diagnósticos, catálogo, historial, feedback | Implementado; cierre original rectificado por [corrección](evidence/INCREMENTO-2-CORRECCION.md). 20 operaciones de negocio de Diagnosis |
| 3 | RabbitMQ, outbox/inbox, lease, worker provisional e idempotencia | Verificado y archivado; CI local 17/17. [Evidencia](evidence/INCREMENTO-3-CIERRE.md). Resultados sintéticos, sin modelo real |
| 4 | Piloto de dos tizones de papa, datos autorizados, entrenamiento, evaluación y modelo validado | En desarrollo. v1.2.0 y v1.3.2 son históricos; [TEST v1.3.2 falló](evidence/INCREMENTO-4-TEST-V1.3.2-UNICO.md) en papa sana. [Ciclo v1.4.0](../openspec/changes/incremento-4-v1-4-rechazo-sano-balanceado/tasks.md): G0/G1 cerrados, PlantVillage TRAIN/VAL verificado y Sikkim EXTERNAL sellado; entrenamiento, G2, G3 e integración pendientes. |
| 5 | Notificaciones, lectura de avisos, interfaz final, observabilidad, recuperación, pruebas y despliegue con dominio, HTTPS, Cloudflare y CDN | Pendiente |

Gemini, voz, PWA y detector de plagas son extensiones posteriores opcionales.

La [fuente V1](reference/Definicion_Base_AgroDiagnostico_V1_Limpia.docx) se interpreta junto con la [reconciliación](reference/RECONCILIACION-V1.md). Consulta [DEVELOPMENT](DEVELOPMENT.md) para el proceso y [tasks.md](../openspec/changes/archive/2026-09-30-incremento-0-base-integrada/tasks.md) para el avance verificable; una carpeta o contrato previsto no acredita funcionalidad.

Aceptación integrada local del grupo 7: 7.1–7.4 verificadas, incluida CI remota. [Evidencia](evidence/INCREMENTO-0-GRUPO-7.md). Los cinco deltas están sincronizados en `openspec/specs/` y el cambio está archivado.

Estado final del Incremento 1: Grupos 1–7 concluidos y verificados (38/38 pruebas de identidad, contratos OpenAPI y pruebas multi-instancia contra PostgreSQL). [Evidencia](evidence/INCREMENTO-1-AUDIT.md). Las 12 operaciones de negocio del servicio identity han sido implementadas; los tres deltas están sincronizados en `openspec/specs/` y el cambio está archivado en [tasks.md](../openspec/changes/archive/2026-09-30-incremento-1-identidad-y-autorizacion/tasks.md). Ese era el estado al cerrar este incremento; véase la tabla vigente.

El cierre original del Incremento 1 fue rectificado tras revisión. [Corrección y límites verificados](evidence/INCREMENTO-1-CORRECCION.md): configuración Ed25519, Origin/CSRF, respuestas, correlación, auditoría y aceptación de procesos independientes. El archivo original se conserva como histórico.

Cierre histórico del Incremento 2: Grupos 1–9 concluidos y verificados (113 pruebas unitarias e integración de Diagnosis, aceptación integral E2E en contenedores aislados vía Nginx, 20 operaciones promovidas a implementadas, 0 dependencias en tiempo de ejecución de RabbitMQ/Redis/AI). [Evidencia](evidence/INCREMENTO-2-AUDIT.md). Tareas archivadas en [tasks.md](../openspec/changes/archive/2026-10-06-incremento-2-diagnosticos-y-catalogo/tasks.md). Ese era el estado al cerrar este incremento; véase la tabla vigente.

La auditoría posterior y sus correcciones se registran en [INCREMENTO-2-CORRECCION](evidence/INCREMENTO-2-CORRECCION.md). El archivo original conserva su contexto histórico.

CI de cierre del incremento 2 (2026-10-07): 16/16 etapas locales aprobadas, incluidas persistencia, entorno Compose e integraciones Identity/Diagnosis. [Informe](evidence/INCREMENTO-2-CI-LOCAL.json). La verificación remota de este correctivo queda pendiente de publicación autenticada.

Cierre del incremento 3 (2026-10-09): 33/33 tareas, cinco capacidades sincronizadas y [CI local completo](evidence/INCREMENTO-3-CI-LOCAL.json). [Tareas archivadas](../openspec/changes/archive/2026-10-09-incremento-3-flujo-asincrono-confiable/tasks.md). La comprobación remota de GitHub Actions permanece pendiente; el siguiente incremento es el 4 (datos autorizados y modelo validado).

Estado del incremento 4 rectificado el 2026-10-15: se retira la declaración de 36/40 completadas y la aceptación real. Actualización del 2026-11-19: el responsable aprobó G0 como protocolo de diseño y se cerró G1 para el lote privado de dos tizones y negativos de tomate, con procedencia experta de etiquetas PlantVillage y control interno de calidad. Persisten entrenamiento, evaluación G2 y aceptación G3. No archivar.
