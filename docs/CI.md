# CI de aplicación — Incremento 0

El workflow [application-ci.yml](../.github/workflows/application-ci.yml) se ejecuta en pull requests y push a `main`, separado del workflow de preparación Copilot, que se conserva. No publica imágenes, no despliega ni requiere secretos de producción, GPU o datasets. La ejecución remota se comprueba únicamente cuando exista una revisión publicada; reproducir los comandos localmente no acredita GitHub Actions.

## Herramientas y permisos

Ubuntu 24.04, Python 3.12.3, Node 24.21.0, npm **12.1.0 aislado**, OpenSpec 1.13.2, Docker Engine 29.1.3, Compose 2.40.3, Ruff 0.12.12 y actionlint 1.7.7. El npm global auditado del equipo no se cambia. La versión aislada es compatible con Node 24.21 y se instala desde `tooling/ci/package-lock.json`. Locks existentes por servicio, frontend y validadores se reutilizan. Python usa venv y hashes; actionlint se descarga del release con SHA-256 comprobado. No hay instalación global.

Las actions de checkout, Python, Node, Docker, Compose y artefactos se fijan por commit SHA completo, consultado en sus repositorios oficiales. [Registro de versiones y revisiones](../tooling/ci/tools.json). El runner Ubuntu y su kernel son infraestructura administrada por GitHub; el workflow no afirma fijar su imagen interna exacta. El ejecutor comprueba versiones de runtimes, registra las observadas y falla si no coinciden (acepta el sufijo de paquete de Compose, conservando versión 2.40.3).

Permiso global `contents: read`, credenciales de checkout no persistidas, sin `pull_request_target`, sin secretos productivos ni runner del desarrollador. Límite del job: 60 minutos; cada comando tiene timeout propio en el [plan](../tooling/ci/plan.json). Compose usa el constructor local clásico con `DOCKER_BUILDKIT=0`, sin depender de un buildx sin fijar; solo builds locales de aceptación.

## Reproducción local

Linux x86_64 con los runtimes indicados y Docker accesible. Desde la raíz:

```bash
bash scripts/prepare_ci.sh
python3 scripts/run_ci.py
```

La preparación instala herramientas en `tooling/ci/` ignoradas donde corresponde, usando locks y hashes. No reinstala Docker ni altera configuración del daemon local. `run_ci.py` antepone el npm/OpenSpec aislado al PATH de sus hijos y crea `.local/ci/<id-único>/`. Para elegir destino: `python3 scripts/run_ci.py --artifacts .local/ci/mi-ejecucion`; debe ser una ruta nueva para no sobrescribir evidencia anterior.

Etapas obligatorias: workflow/plan, lint Python, pruebas de controles CI, contratos HTTP/eventos, inventario del dataset, locks/imports y pruebas técnicas backend, instalación/lint/tipos/prueba/build frontend, OpenSpec estricto, migraciones e integración Compose. No hay opción de omitir una etapa y conservar estado aprobado. Un plan incompleto, suite vacía, comando fallido o timeout hace fallar el resultado global. Los comandos individuales ya documentados permanecen disponibles; su éxito aislado no se presenta como CI completa.

## Reportes y limpieza

`summary.json` registra resultado global, pasos previstos/ejecutados, códigos, duraciones, versiones, revisión Git o «sin commit» y hashes de archivos de implementación. Cada etapa conserva su log. Los dos verificadores Compose registran proyecto, diagnóstico de estado/logs y un JSON de limpieza con contenedores, redes, volúmenes e imágenes propias restantes. Las imágenes externas fijadas y cachés de build pueden permanecer; no son datos de aceptación ni se ejecuta un prune global.

Cada proyecto usa nombre aleatorio `agro-mig-test-<id>` o `agro-env-test-<id>`, puerto disponible y credenciales generadas en directorio efímero. La recolección elimina valores conocidos de secretos antes de escribir; no exporta `.env`, archivos de credenciales ni configuración expandida. En salidas de comandos se rechaza una fuga de credenciales. Los logs no contienen fotografías ni eventos reales.

Los verificadores limpian en `finally`; el runner ejecuta limpieza adicional y GitHub tiene un paso `if: always()` independiente. El respaldo solo actúa sobre los proyectos registrados y sus etiquetas exactas, y sobre imágenes con el prefijo aleatorio propio; no borra el proyecto del desarrollador ni contenedores ajenos. Un timeout devuelve 124, permite que el proceso hijo recoja diagnóstico y limpie, y conserva el fallo global. Interrupciones TERM se canalizan a limpieza; si el host o daemon desaparece, el workflow no promete limpieza imposible y sus recursos deben revisarse.

El upload también usa `always()`, conserva reportes siete días y falla si faltan artefactos. Solo adjunta el directorio de reportes, nunca `.local/persistence/`. En local, los reportes permanecen para revisión; no se envían a ningún servicio.

## Regresiones reproducibles

```bash
python3 scripts/check_ci_regressions.py
```

Crea copias desechables sin secretos, datos ni dependencias de aplicación; reutiliza las herramientas bloqueadas. Ejecuta el mismo pipeline completo sobre cada mutación independiente:

| Caso | Mutación en la copia | Fallo esperado |
| --- | --- | --- |
| invalid-event | Eliminar event_id de fixture declarado válido | Etapa contracts, salida global no cero |
| broken-http-reference | Referencia de salud a esquema inexistente | Etapa contracts, salida global no cero |
| failed-migration | Revisión base que lanza error al subir | Etapa persistence, salida global no cero |
| failed-readiness | Host de DB de Identity API inexistente; migraciones intactas | Etapa environment, Compose no alcanza salud |
| timeout | Misma degradación, presupuesto de etapa reducido a 45 s | Etapa environment, salida 124 y fallo global |

Para repetir uno: `python3 scripts/check_ci_regressions.py --case failed-readiness`. Todos restauran los archivos de la copia antes de eliminarla; jamás mutan originales. Los casos tardíos repiten checks anteriores y pueden tardar varios minutos. El reporte exige la etapa fallida esperada, salida global no cero y JSON de limpieza vacío de recursos; no acepta fallos ajenos al caso como evidencia válida.

## Límites

Esta CI verifica base técnica, contratos e inventario; no acredita autenticación de negocio, diagnósticos, inferencia, precisión ML ni despliegue. Grupo 7 conserva la aceptación global y comprobación remota. Las vulnerabilidades reportadas por un registro externo se revisan aparte: validar locks no equivale a un análisis de seguridad completo ni a ausencia de avisos.

## Aceptación remota del Incremento 0

[Application CI 36749372314](https://github.com/RonaldoMarquina/agrodiagnostico_V1/actions/runs/36749372314) aprobó sobre `97472b1`, incluidos controles, limpieza y artefacto. [Evidencia y fallos previos](evidence/INCREMENTO-0-GRUPO-7-REMOTO.md).
