# Incremento 0 — grupo 3: persistencia aislada y migraciones base

Fecha: 2026-09-29, America/Lima. Cambio `incremento-0-base-integrada`; tareas 3.1–3.5 terminadas. Avance16/38. Trabajo sin commit; hashes en [manifiesto](incremento-0-grupo-3-sha256.json). Auditoría y evidencias anteriores conservadas.

## Comandos y resultados

- `bash scripts/check_service_locks.sh`: cuatro entornos limpios, instalación bloqueada e imports FastAPI/SQLAlchemy/Alembic/psycopg. [Salida y duración](incremento-0-grupo-3-locks.txt).
- `python3 scripts/check_persistence.py`: PostgreSQL real en proyecto efímero, éxito y limpieza de su volumen/red/contenedores. [Salida y duración](incremento-0-grupo-3-checks.txt).
- OpenSpec estricto y estado final: [salida](incremento-0-grupo-3-openspec.txt).

Entorno: host Python3.12.3, Docker29.1.3, Compose2.40.3 según auditoría vigente; uv0.12.20 instalado aislado. Dependencias directas FastAPI0.141.1, SQLAlchemy2.1.1, Alembic1.20.0 y psycopg3.3.6, cierre transitivo por servicio. Imágenes PostgreSQL16-alpine y Python3.12-slim-bookworm fijadas por digest en Compose/Dockerfile; no se afirma versión más reciente ni evaluación productiva.

## Trazabilidad

| Tarea / requisito | Resultado comprobado | Implementación/prueba |
| --- | --- | --- |
| 3.1 / MIG-01, CI-01 parcial | Cuatro instalaciones limpias con locks independientes e imports exitosos; ninguna instalación global | services/*/pyproject.toml y uv.lock; tooling/uv.requirements.txt; check_service_locks.sh |
| 3.2 / MIG-02, ENV-04 parcial | Bootstrap limpio y repetido; cuatro roles sin superuser/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS; bases propias y permisos restringidos | infra/postgres/bootstrap.py; docker-compose.yml; check_databases.py |
| 3.3 / MIG-01 | Cada servicio pasa upgrade head, current, repetición sin cambio, downgrade base y upgrade; solo alembic_version | Cuatro historiales Alembic y pruebas contra PostgreSQL |
| 3.4 / MIG-02–03 | Cuatro conexiones propias exitosas, doce cruzadas rechazadas por permisos; contraseña errónea produce1, sin credenciales en salidas/logs | check_databases.py y check_persistence.py |
| 3.5 / MIG-03 | Head ausente/desconocido rechaza readiness de esquema; fallo SQL rollback conserva revisión previa y nuevo head pendiente; job fallido bloquea dependiente; corrección permite repetir | app/persistence.py y app/migrate.py por servicio; cadena Compose y fixture temporal |
| Conservación de datos | Heads presentes después de down/up de PostgreSQL, antes de reaplicar bootstrap/migraciones; limpieza solo al terminar proyecto efímero | check_persistence.py |

Los fallos SQL se inyectan en copias temporales con revisión nueva que ejecuta división por cero. No se cambian las revisiones del repositorio ni se escriben tablas de dominio. La matriz4×4 usa autenticación real y distingue rechazo de permisos de un fallo de conectividad.

## Alcance y pendientes

`schema_ready()` es un prerrequisito real de persistencia, no el endpoint HTTP completo. El grupo4 conectará esa comprobación a readiness, añadirá dependencia S3 de Diagnosis y probará200/503. Las 27 operaciones contract-only siguen sin handlers; no hay frontend, broker, S3, autenticación, inferencia, entrenamiento ni entrega de eventos ejecutados por este grupo.

Compose no publica puertos. Jobs de servicio reciben solo su secreto; el bootstrap privilegiado es separado. Los archivos de secreto son locales y quedan fuera de Git/build; usuario root de jobs técnicos permite leer los archivos0600 montados y no implica rol PostgreSQL privilegiado. Esa política local no define el usuario de futuras APIs productivas.

Grupos4–7 pendientes. No se ejecutó CI remota ni se hizo push/despliegue/sincronización/archivo OpenSpec. No se declaran RF ni métricas de producto cumplidos. [Procedimiento de operación y reversión](../PERSISTENCE.md).
