# Incremento 0 — grupo 7: aceptación integrada

Inicio UTC: 2026-09-30T16:06:33Z. Fin UTC: 2026-09-30T16:10:49Z. Cambio `incremento-0-base-integrada`.

## Resultado y procedencia

Las 14 etapas locales finalizaron con código 0. Duración acumulada de etapas: 250.395 segundos. [Resumen con versiones, tiempos y hashes](incremento-0-grupo-7/positive/summary.json), [comandos y procedencia](incremento-0-grupo-7/provenance.json), [salida del ejecutor](incremento-0-grupo-7/driver.log).

El repositorio original no tiene HEAD. Se copiaron los archivos admitidos por Git a un repositorio temporal, se creó únicamente allí la revisión `9591699f572444ffe3c2c4669b1e2100edd27b9f` y se hizo `git clone --no-local` a otro directorio. `git status --porcelain` estaba vacío antes de instalar. No se copiaron secretos, node_modules, venv ni datos/modelos privados. Esa revisión temporal identifica la prueba; no es un commit del proyecto ni una revisión publicada. La instantánea y su checkout se eliminaron al terminar.

Se ejecutaron `bash scripts/prepare_ci.sh` y `python3 scripts/run_ci.py --artifacts <directorio nuevo>` desde ese checkout. Los verificadores generaron secretos, proyectos y volúmenes nuevos; recrearon recursos para comprobar persistencia y eliminaron únicamente sus recursos de prueba. Los dos reportes `*.cleanup.json` contienen listas vacías de contenedores, volúmenes, redes e imágenes. Se reutilizó el daemon/caché de imágenes del host; no se afirma una máquina sin caché.

[Reproductor usado](incremento-0-grupo-7/reproduce.py): ejecutarlo desde la raíz con runtimes de `tooling/ci/tools.json`, Docker y acceso a dependencias; elegir rutas de artefactos nuevas en el script para no sobrescribir una ejecución previa. La preparación y cada etapa conservan código y duración. Las correcciones documentales finales y la excepción de logs en `.gitignore` son posteriores al checkout; el código probado no cambió.

## Matriz requisito → prueba → resultado → artefacto

Los comandos exactos están en [matrix.json](incremento-0-grupo-7/matrix.json); los códigos y duraciones se conservan en summary.json.

| Requisito | Prueba / revisión | Resultado | Artefacto |
| --- | --- | --- | --- |
| ENV-01 | Configuración ausente rechazada, build y página técnica; arranque limpio | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/environment.log) |
| ENV-02 | Salud de cuatro APIs; DB/S3 degradados y recuperados; Redis prescindible | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/environment.log) |
| ENV-03 | Solo proxy loopback, rutas internas rechazadas, S3 privado y AI sin escritura | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/environment.log) |
| ENV-04 | Recreación conserva head, mensaje confirmado y objeto/checksum | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/environment.log) |
| CTR-01 | Cuatro OpenAPI, inventario, referencias y ejemplos; salud real en environment | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/contracts.log) |
| CTR-02 | Casos contractuales de acceso, errores, idempotencia y seguridad; runtime de negocio pendiente | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/contracts.log) |
| CTR-03 | Tres eventos v1, variantes y rechazo de campos/estados prohibidos | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/contracts.log) |
| CTR-04 | Routing y matrices de entrega revisados; ejecución de outbox/inbox/lease pendiente del incremento 3 | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/contracts.log) |
| MIG-01 | Cuatro historiales; upgrade/current/repetición/downgrade/upgrade sin dominio | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/persistence.log) |
| MIG-02 | Cuatro conexiones propias, doce cruzadas rechazadas y roles restringidos | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/persistence.log) |
| MIG-03 | Revisión/credencial inválidas fallan; job dependiente bloqueado; readiness en environment | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/persistence.log) |
| DATA-01 | Fuentes, licencia/elegibilidad pendiente y cantidades desconocidas explícitas | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/dataset.log) |
| DATA-02 | Siete clases candidatas y manifiesto de diez campos; fixtures positivos/negativos | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/dataset.log) |
| DATA-03 | Rechazo de fugas por hash/grupo entre particiones; sin mutación ni datos privados | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/dataset.log) |
| CI-01 | 14 etapas locales aprobadas; regresiones verificadas en grupo 6; ejecución remota pendiente | parcial: remoto pendiente | [log](incremento-0-grupo-7/positive/workflow.log) |
| CI-02 | Timeout, redacción y limpieza; cinco regresiones del grupo 6 y limpieza real de esta ejecución | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/ci-tests.log) |
| CI-03 | Trazabilidad, límites y revisión documental; validación estricta final adjunta | verificado dentro del alcance del Incremento 0 | [log](incremento-0-grupo-7/positive/openspec.log) |

Los negativos de evento inválido, referencia rota, migración fallida, readiness fallido y timeout se conservan en [grupo 6](incremento-0-grupo-6/regressions/regressions.json), sin repetirlos ni presentarlos como ejecutados en esta nueva prueba. Todos fallaron globalmente como se esperaba, con limpieza verificada. Los negativos técnicos de configuración, permisos y degradación sí se repitieron en esta aceptación.

## Coherencia y conservación

Se revisaron la reconciliación V1, ADR-0001/0002/0003, C4 local, API_CONTRACTS, inventario HTTP, matrices de seguridad/entrega, documentación operativa y los cinco deltas. Se aclaró que el encabezado de correlación de entrada pertenece a operaciones de negocio contratadas; salud genera su UUID y no declara ese parámetro. Se actualizaron encabezados históricos de ADR y estados de avance. Ocho operaciones de salud implementadas y diecinueve de negocio contract-only permanecen coherentes. No se modificaron contratos, migraciones ni comportamiento de aplicación.

Se permitió conservar los logs sanitizados de `docs/evidence/` en Git, antes excluidos por `*.log`. Se completó el índice narrativo del grupo 6 usando sus reportes existentes. [Comparación de integridad](incremento-0-grupo-7/preservation.json) contra la instantánea previa: auditoría, fuente DOCX, workflow Copilot y evidencia previa intactos. No se reescribió la estructura existente.

## Pendientes y condición de cierre

**Workflow remoto no ejecutado.** `git ls-remote origin` terminó 0 sin referencias publicadas; no hay revisión ni ID/enlace de ejecución de GitHub Actions. CI-01 queda parcialmente verificado en su dimensión remota y 7.3 permanece pendiente. No se hizo push, publicación, sincronización de specs ni archivo. La preparación de sincronización/archivo queda condicionada a resolver esta aceptación pendiente.

RF-01…RF-28 no se declaran satisfechos por estas pruebas técnicas. No se midieron precisión, recall, F1, calibración, cobertura real por clase, robustez de cultivo, latencia de inferencia, capacidad concurrente, disponibilidad, RPO/RTO ni SLO de producción. Los tiempos del runner son tiempos de pruebas locales.

Incrementos pendientes: 1 identidad/sesiones/autorización; 2 imágenes/diagnósticos/catálogo/historial/feedback; 3 entrega outbox/inbox, lease y worker; 4 datos autorizados, cultivo automático, entrenamiento y evaluación; 5 avisos, interfaz final, operación, recuperación y despliegue público con dominio/HTTPS/Cloudflare/CDN. HEIC/HEIF sigue pendiente de conversión y E2E. Las siete clases son candidatas; no hay dataset admitido ni entrenamiento, imágenes de usuarios o diagnóstico real.

Persisten los hallazgos documentados del tooling npm (dos altos y uno moderado en dependencias incluidas); véase [auditoría del grupo 6](incremento-0-grupo-6-tooling-audit.json). Esta aceptación no certifica seguridad de producción.
