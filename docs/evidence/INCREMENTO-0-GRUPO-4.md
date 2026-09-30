# Incremento0 — grupo4: entorno integrado mínimo

Fecha:2026-09-29, America/Lima. Cambio `incremento-0-base-integrada`. Alcance4.1–4.9; sin aplicación de grupos5–7. Trabajo sin commit; [hashes](incremento-0-grupo-4-sha256.json).

## Ejecuciones reproducibles

- `python3 scripts/check_environment.py` desde copia limpia del workspace, sin secretos, venv, node_modules ni dist, con volúmenes nuevos: [salida y duración](incremento-0-grupo-4-checks.txt).
- Regresión de la capa anterior: `python3 scripts/check_persistence.py`, [salida](incremento-0-grupo-4-persistence-regression.txt).
- Contratos/OpenSpec y estado final: [verificaciones](incremento-0-grupo-4-validation.txt).

Build de frontend ejecuta npm ci desde lock, lint, tipos, prueba React de página y build antes de producir Nginx. Los cuatro servicios usan uv sync --locked e imágenes base fijadas por digest. El timeout de arranque es180s después de build; las ejecuciones registran duración observada, sin convertirla en SLO de producción.

## Criterios comprobados

| Tarea / requisito | Verificación | Artefacto |
| --- | --- | --- |
| 4.1 / ENV-01 | Preparador repetible, secretos conservados, config --quiet y rechazo de variables obligatorias ausentes; APIs rechazan APP_ENV ausente sin exponer valores | .env.example; prepare_local.py; app/run.py; check_environment.py |
| 4.2 / ENV-02, MIG-03, CTR-01 | Cuatro live200; ready200/503 según DB/head/S3; restauración200. OpenAPI generado contiene solo salud y coincide en métodos, IDs, respuestas y schemas con contrato; headers no-store/UUID | app/main.py, persistence.py, storage.py; check_runtime.py |
| 4.3 / ENV-01, CI-01 parcial | npm lock, lint/tipos, renderizado «Entorno técnico» sin upload/botón, build y entrega de HTML/assets | frontend; frontend.Dockerfile |
| 4.4 / ENV-03–04 | RabbitMQ/Redis/SeaweedFS versionados con digests; inicializador S3 repetido; Diagnosis upload/read; AI read permitido/write403; acceso anónimo denegado; interfaces alternativas no alcanzables | ADR-0003; Compose; S3 bootstrap; check_runtime.py |
| 4.5 / ENV-01–02 | Arranque limpio con dependencias de inicialización y migración dentro de180s; sin GPU, modelos, correo, Cloudflare ni opcionales | Compose y logs de aceptación |
| 4.6 / ENV-03, CTR-01 | Inspección real de puertos: solo Nginx/loopback; /internal, salud, AI y negocio404; API no-store y correlation_id; estáticos accesibles | nginx/default.conf; C4 local; check_environment.py |
| 4.7 / ENV-04 | Head de PostgreSQL, mensaje persistente en cola durable con confirm y objeto privado/checksum sobreviven down/recreación; comprobados antes de reinicializar/migrar | modos seed/recover de check_runtime.py |
| 4.8 / ENV-02 | PostgreSQL caído:ready503/live200; recupera200. Redis caído:Diagnosis ready200. S3 caído:solo Diagnosis ready503; recupera200. Broker/S3 se comprueban aparte | check_environment.py |
| 4.9 / ENV-01, CI-03 parcial | Comandos documentados ejecutados en proyecto aislado y copia limpia; auditoría del host y script conservados | DEVELOPMENT, README, evidencia |

La prueba de persistencia posterior vuelve a pasar cuatro conexiones propias y doce cruzadas rechazadas, migraciones repetibles/reversibles y fallos de credenciales/revisión. Los jobs schema-check se conservan en perfil explícito persistence-check; las APIs dependen directamente del éxito de su migración.

## Decisiones y límites

SeaweedFS4.17, fuente/licencia y motivo de sustitución de la propuesta MinIO en [ADR-0003](../adr/0003-entorno-local-y-almacenamiento.md). Master/filer/volume solo loopback dentro del servidor, S3 autenticado en red interna. Roles S3 separados: admin de inicialización, Diagnosis limitado a bucket, AI lectura; autorización por objeto/lease de negocio todavía pendiente.

RabbitMQ usa cola técnica de aceptación, confirms y cuerpo sintético, no eventos de diagnóstico. Redis solo se comprueba como dependencia prescindible; no hay fallback de catálogo implementado. La salud AI no prueba inferencia. Ningún tratamiento, modelo, dato de usuario ni dataset real participa.

Ocho operaciones internas de salud implementadas; diecinueve de negocio siguen contract-only. Grupo5 inventario, grupo6 CI y grupo7 cierre pendientes; CI remota no ejecutada. HTTP local no cumple dominio, TLS, Cloudflare o CDN. No se hace push, despliegue público, sincronización ni archivo OpenSpec.

La aceptación elimina únicamente su proyecto Docker y secretos temporales. La parada documentada del entorno del desarrollador conserva volúmenes. Auditoría histórica ENVIRONMENT y evidencia de grupos1–3 no se reescriben.
