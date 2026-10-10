# Cierre del incremento 3: flujo asíncrono confiable

Fecha de revisión: 2026-10-09. Cambio archivado: [incremento-3-flujo-asincrono-confiable](../../openspec/changes/archive/2026-10-09-incremento-3-flujo-asincrono-confiable/tasks.md), 33/33 tareas completas y cinco capacidades sincronizadas.

## Correcciones de revisión

- El worker conserva mensajes ante timeout incierto, errores HTTP transitorios, lease ocupado y fallos de imagen/inferencia. La reentrega tiene espera; el presupuesto pertenece a Diagnosis.
- La deduplicación usa evento/hash y generación, sin descartar una generación nueva por existir un resultado anterior. El token local protege la confirmación y el heartbeat renueva por HTTP.
- El recuperador aplica deadline y presupuesto incluso si ya emitió una señal. Conserva los bloqueos hasta confirmar las transiciones y sus eventos.
- Los publicadores reconocen correctamente el retorno `None` de Pika tras confirmación; el token condiciona atómicamente la actualización del outbox. Los descriptores DLQ también requieren confirms.
- Los consumidores reconectan tras interrupciones y conservan mensajes no confirmados. Las sesiones de publicadores y recuperador se cierran en cada ciclo.
- Los workers sintéticos pertenecen exclusivamente al perfil `async-test`. La publicación de una predicción exige una política sintética explícita y versión permitida; el umbral de prueba no expresa calibración agronómica.
- La aceptación dejó de insertar directamente filas de evidencia: publica duplicados/colisiones por AMQP, ejecuta el replay operativo y detiene procesos y dependencias reales. El catálogo de prueba contiene texto sintético sin tratamientos inventados.
- Se alinearon contratos, inventario, rutas esperadas y dependencias del CI. Las tres operaciones internas están implementadas; los ejemplos JSON permanecen declarativos.

## Pruebas reproducibles

Comando integral: `python3 scripts/run_ci.py --artifacts .local/ci/cierre-inc3-final-20261009-b`.

La etapa `async-integration` ejecuta `python3 scripts/check_async_acceptance.py`. Construye las imágenes del checkout y prepara PostgreSQL, RabbitMQ, S3, Nginx y dos workers en un proyecto desechable. Comprueba:

1. Carga y flujo Requested → claim → Analyzed → Finished para COMPLETADO, NO_CONCLUYENTE y FALLIDO sintéticos, con eventos validados contra JSON Schema.
2. Duplicado, colisión de identidad, versión desconocida, mensaje sin ruta y retención durable de Finished sin consumidor Notification.
3. Lease obsoleto, aislamiento de propietario y cuatro carreras reales claim/cancel con barrera y un ganador.
4. Parada de RabbitMQ y Redis: Diagnosis sigue aceptando, conserva PENDIENTE/outbox y completa después del reinicio.
5. Muerte del proceso worker antes del claim, después del claim, antes del commit y después del commit antes del ACK; recuperación con un resultado lógico por diagnóstico.
6. Ejecución prolongada con renovación real del lease por HTTP.
7. Muerte del publicador antes del confirm y después del confirm antes del commit de envío; redelivery y un único Finished.
8. Recuperadores simultáneos en PostgreSQL, agotamiento del presupuesto, deadline después de señal previa y carrera de resultado tardío contra recuperación.
9. Limpieza comprobada de contenedores, redes, volúmenes e imágenes del proyecto aislado; un residuo hace fallar la aceptación.

Los casos de agotamiento/deadline preparan estados sintéticos vencidos en PostgreSQL y ejecutan el recuperador real; no representan mediciones de latencia ni disponibilidad de producción. Las pruebas de los servicios complementan la aceptación con rollback, errores de persistencia, firmas y claims inválidos, política de publicación, soporte del catálogo y fencing. Los procesos de fault injection viven exclusivamente en `scripts/async_*_probe.py`; no agregan endpoints ni controles públicos de fallo al producto.

## Estado de verificación

**CI local: 17/17 etapas aprobadas**, incluida limpieza estricta de todos los proyectos aislados. [Informe con versiones, tiempos y hashes](INCREMENTO-3-CI-LOCAL.json). [Checkpoints de aceptación asíncrona](INCREMENTO-3-E2E.txt).

El backend ejecutó 47 pruebas de Identity, 213 de Diagnosis y 47 de AI, además de las comprobaciones de salud de los cuatro servicios. Contratos: 17 pruebas. También pasaron las integraciones completas de los incrementos anteriores.

Los hashes del informe corresponden al código probado antes de sincronizar y archivar OpenSpec; el archivo posterior solo cambia planificación, especificaciones y documentación. La validación estricta de OpenSpec se repitió después de sincronizar y archivar: 14/14 especificaciones aprobadas y ningún cambio activo. Se comprobó que los hashes de implementación coinciden con el informe del CI. No se ha ejecutado GitHub Actions remoto para este cierre.

## Límites

No existe modelo ML entrenado o calibrado en este incremento. No se activan semillas ordinarias como clases validadas. Notification, correo, métricas de producción, GPU, entrenamiento y despliegue público continúan pendientes. La validación local no acredita una ejecución remota de GitHub Actions. No se ejecuta backfill sobre datos reales ni se migran los volúmenes de desarrollo durante estas pruebas.

## Correctivo de CI remoto — 2026-10-10

La ejecución GitHub Actions `38023116598` falló en la prueba de topología
`test_docker_compose_only_proxy_published_and_topology_complete`: invocaba
Compose sin configuración explícita y dependía del `.env` local, ausente en un
checkout limpio. La reproducción sin variables confirmó el rechazo de
interpolación de `APP_ENV` obligatorio.

La prueba ahora utiliza `.env.example` versionado para ambas consultas de
Compose y un entorno limitado a PATH/HOME, sin heredar perfiles ni opciones de
simulación del desarrollador. Solo renderiza configuración; no inicia servicios
ni requiere secretos reales. Se conservan las comprobaciones de puertos,
procesos, perfil aislado y simulación desactivada por defecto.

Verificación del correctivo: las 213 pruebas de Diagnosis aprobaron en una copia
de los archivos versionados con el correctivo, sin `.env`, usando el entorno
Python local de Diagnosis. Se inyectaron `ENABLE_SIMULATED_INFERENCE=true` y
`COMPOSE_PROFILES=async-test` en el proceso padre para comprobar el aislamiento.
Log local: `.local/ci/inc3-compose-fix/diagnosis-clean.log`. No se repitió el
pipeline integral; los 17/17 anteriores son evidencia histórica. La nueva
validación remota queda pendiente del push de este correctivo.
