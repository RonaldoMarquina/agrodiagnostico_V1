# Corrección verificada del Incremento 1

Fecha: 2026-09-30. Cambio: `corregir-cierre-incremento-1`.

Este informe rectifica [la auditoría original](INCREMENTO-1-AUDIT.md). Se conserva el archivo OpenSpec original; sus casillas históricas no prueban por sí solas que la primera implementación cumplía los requisitos. Las correcciones se entregan en el árbol de trabajo, sin despliegue ni migración de la base local existente.

## Hallazgos y correcciones

| Hallazgo reproducido | Corrección | Verificación |
| --- | --- | --- |
| Compose no montaba claves JWT | Preparador Ed25519 idempotente, validación de pareja, secretos montados en Identity y fallo cerrado de arranque | TestKeyConfiguration, aceptación de procesos y arranque Compose |
| Origin aceptaba otro esquema/puerto por hostname | Comparación exacta con allowlist | Regresión unitaria y solicitudes reales por Nginx |
| CSRF arbitrario cookie=cabecera admitido | HMAC ligado al refresh y comparación constante | Regresión negativa sin rotar/revocar sesión y aceptación HTTP |
| Login bloqueado 403 y logout desconocido 204 | 401 genéricos según contrato; limpieza efectiva de cookies de error | Regresiones positivas/negativas |
| Correlación distinta entre cuerpo/cabecera | Middleware como autoridad única | Solicitudes con correlación válida, ausente e inválida |
| Auditoría sin USER_REGISTERED y contexto requerido | Helper transaccional, nombres normativos y migración identity_0003 | Eventos/UUID/rollback unitario, migración con fila histórica e inmutabilidad PostgreSQL |
| Simulación presentada como multi-instancia | Tres contenedores/procesos independientes con configuración común, PostgreSQL restringido y Nginx | `check_identity_integration.py` |
| Tests podían eliminar usuarios del entorno | Suite lógica siempre SQLite en memoria; aceptación usa recursos desechables propios | Inspección y ejecuciones sin usar DB_HOST/credenciales del desarrollador |

## Comandos y resultados observados

Ejecutados localmente durante la corrección; no constituyen una ejecución de CI remota ni un despliegue productivo.

1. Desde `services/identity/`: `env -u DB_HOST PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v`.
   - 47 casos: **46 aprobados y 1 omitido**. La omisión es la carrera PostgreSQL del antiguo test lógico; se ejecuta realmente en la aceptación siguiente.
   - Incluye rollback de registro si falla auditoría, claves preservadas y detección de pareja inválida.
2. `python3 scripts/check_identity_integration.py`.
   - **7 comprobaciones integradas aprobadas**, tres procesos independientes y rol PostgreSQL sin superusuario/creación de bases/roles.
   - Migración 0002→0003 conserva fila histórica sin inventar campos; aplicación repetida segura.
   - Login A → refresh B → logout C; refresh concurrente con exactamente un 200 y un 401; revocación de familia comprobada usando el token ganador.
   - Cambio/restablecimiento de contraseña y bloqueo administrativo revocan sesiones entre procesos. Token de restablecimiento de un solo uso.
   - Origin/CSRF, RBAC y auditoría append-only comprobados por HTTP/SQL. Se verifica también arranque fallido sin clave de firma.
   - Contenedores/red/imagen propios eliminados al terminar; no se utilizaron las bases del entorno del desarrollador.
3. `python3 scripts/check_environment.py`.
   - **Aprobado**, proyecto desechable `agro-env-test-d5261d322603`, duración local 126.928 segundos.
   - Preparación idempotente, arranque integrado, proxy, salud, configuración inválida, degradación/recuperación PostgreSQL/S3, persistencia de objetos/mensajes y ausencia de credenciales en logs.
4. `.venv-contracts/bin/python scripts/validate_contracts.py` y `.venv-contracts/bin/python -m unittest discover -s tests/contracts -p 'test_*.py' -v`.
   - **11/11 pruebas**; 401 ejemplos, 4 OpenAPI, 32 operaciones y 5 esquemas validados.
5. `python3 scripts/check_ci_tests.py`, `python3 scripts/check_ci_workflow.py`, `tooling/ci/.venv/bin/ruff check --select E9,F63,F7,F82 scripts services tests infra` y `git diff --check`.
   - **6/6 controles CI**, workflow y lint aprobados; sin errores de espacios en diff.
6. `openspec validate --all --strict --no-interactive`.
   - **Aprobado** antes de sincronización; se repite tras el archivo del correctivo.

La CI incorpora unitarios de Identity en `backend` y la nueva etapa obligatoria `identity-integration` (15 etapas en total). No se afirma que la CI remota ni el pipeline completo de 15 etapas hayan corrido en esta revisión.

## Límites y operación

- Las pruebas de correo usan adaptador en memoria. La aceptación entre procesos introduce un token de recuperación sintético por fixture SQL en su DB desechable; no agrega endpoints de prueba ni demuestra entrega externa de correo.
- Las cookies continúan Secure. El cliente de aceptación HTTP las transfiere explícitamente; no acredita un flujo de navegador sin HTTPS.
- Los registros históricos se preservan con `legacy=true`; los campos que antes no existían quedan null. No se puede reconstruir su correlación original.
- Tras desplegar este cambio, los clientes con CSRF de la versión anterior requieren nuevo login. Se conserva la validez breve del access token conforme ADR-0004.
- No se midieron rendimiento, capacidad ni garantías productivas. El incremento 2 y su implementación permanecen separados.
- Aplicación local y migraciones: [DEVELOPMENT](../DEVELOPMENT.md). Decisiones: [ADR-0005](../adr/0005-correccion-identidad-y-evidencia.md).


## Aceptación final de persistencia y cierre

`python3 scripts/check_persistence.py`: **aprobado**, proyecto desechable `agro-mig-test-5b47e4dd79f7`, 92.832 segundos. Verificó upgrade/current/repetición/downgrade/upgrade con roles restringidos, claves incorrectas, revisión ausente/incorrecta, rollback de migración fallida, cuatro conexiones propias y doce conexiones cruzadas denegadas. Comprobó persistencia tras recreación, fallo de prerequisito que bloquea schema-check, recuperación y limpieza sin credenciales en logs.

La ejecución anterior de esta aceptación perdió su sesión/log temporal antes de poder registrar la salida final; se repitió esta comprobación para cerrar la evidencia. Su log completo se conserva junto a este informe. Las restantes comprobaciones se resumen a partir de las salidas observadas durante la sesión original; no se fabricaron logs retrospectivos.

Las dos especificaciones modificadas están sincronizadas conservando los escenarios previos. El correctivo se archiva en `openspec/changes/archive/2026-09-30-corregir-cierre-incremento-1/`; el archivo original y el cambio del incremento 2 permanecen separados.
