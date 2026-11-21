# Incremento 4 — aceptación integrada local del piloto G0 v1.2.0

Fecha de ejecución: 2026-11-20 UTC. Estado: **G3 no aprobado**. Se usó el bundle G2 privado congelado (SHA-256 `93e2e65130a9c266be4bdba0262d1c98e30d0604f4d21466effba2d9c9ff0b41`), sin cambiar pesos, calibración ni umbral 0,50 y sin leer bytes de TEST. El informe íntegro privado `.local/ml-pilot-v1.2/g3-local-2ddfce8615f1/summary.json` tiene SHA-256 `bebaeff285c8987107ab99032d618ed581fdec45045fb05df5c26cf3b23a3449`.

## Entorno y ejecución

`python3 scripts/check_ml_g3_local.py` construyó el perfil `ml-real` y levantó un proyecto Docker Compose aislado. Publicó las dos orientaciones versionadas del [catálogo revisado](INCREMENTO-4-CATALOGO-PILOTO-V1.md) mediante la API administrativa (versión 1 por clase). Importó y activó la política G2 con actor `G3_LOCAL_ACCEPTANCE` y motivo identificado **solo en esa base efímera**. Pasó por carga HTTP, RabbitMQ, worker de inferencia real, Diagnosis e historial. El informe registra los SHA-256 de las imágenes seleccionadas. La política y los contenedores se eliminaron al finalizar; la limpieza fue `PASS`. No se activó el worker real para usuarios.

La primera ejecución aislada (`g3-local-41f67b47793d`) detectó HTTP 401 al reclamar trabajos porque el `INTERNAL_WORKER_INSTANCE_ID` del perfil real no coincidía con su clave del registro de confianza local. Se corrigió el valor de Compose a `worker-1` y la segunda ejecución completó el flujo. Esa primera ejecución no acredita aceptación.

| Comprobación en la segunda ejecución | Resultado observado |
| --- | --- |
| Tizón temprano, cuatro muestras SHA-ordenadas de VAL admitida | 4/4 `COMPLETADO` con clase correcta |
| Tizón tardío, cuatro muestras SHA-ordenadas de VAL admitida | 4/4 `COMPLETADO` con clase correcta |
| Otros cultivos, cuatro negativos admitidos de VAL | 0/4 aceptados; 4/4 `NO_CONCLUYENTE/UNSUPPORTED_CROP` |
| Maíz declarado en la carga | HTTP 400 |
| Acceso ajeno a detalle e imagen | HTTP 404 en ambos |
| Historial del propietario | HTTP 200; 16 diagnósticos |
| **Papa sana fuera del piloto, cuatro fotografías originales de VAL** | **4/4 publicadas erróneamente como `POTATO_LATE_BLIGHT`** |

Las cuatro imágenes de papa sana procedían de la misma revisión original de PlantVillage, pero **no estaban admitidas en G1 v1.2.0** y solo se usaron como control de alcance en esta aceptación; no se entrenó ni se recalibró con ellas. Este control muestra que el bundle y la política actuales no satisfacen el rechazo de papa sana exigido por 9.1 y la especificación. No extrapolamos 4/4 a una tasa poblacional. Tampoco sustituimos el TEST sellado de G2 por esta muestra de VAL. El responsable decidió preparar una **nueva versión con rechazo verificable de papa sana**; G0/G1/G2 v1.2.0 y el bundle permanecen como historial, no como base para una aprobación G3.

La concurrencia fue de dos solicitudes. Entre 16 diagnósticos terminales, la latencia completa observada fue mediana 13,249 s, p95 15,459 s y máximo 15,459 s, frente al objetivo p95 ≤ 30 s. El pico de memoria cgroup del worker fue 593.117.184 bytes (565,6 MiB). Estas son medidas locales; la matriz de fallos y una segunda medición figuran abajo. EXTERNAL no está disponible, por lo que no se acredita generalización a fotografías de campo.

## Matriz de fallos con el worker real — 9.2

`AGRO_G3_FAULT_PROBES=1 python3 scripts/check_ml_g3_local.py` produjo el informe privado `.local/ml-pilot-v1.2/g3-local-df6aef7a4d22/summary.json`, SHA-256 `47d28ab4582bd5f4f6045464b6f06ceaa2fa42eb398a19f88b38e560e5c9d8a0`. Estado `OBSERVED`, `fault_matrix_pass=true` y limpieza `PASS`. Se utilizó el mismo bundle congelado y fotos de VAL admitidas; TEST no se abrió. El ambiente usó un AMD Ryzen 7 5800XT (16 hilos lógicos) y dos solicitudes concurrentes; el heartbeat se aceleró a 0,1 s **solo en el entorno de prueba** para observar renovaciones. El valor operativo por defecto sigue siendo 20 s.

| Fallo o medición | Resultado observado |
| --- | --- |
| Worker detenido, solicitud HTTP aceptada y después reinicio | `PENDIENTE` antes de arrancar; `COMPLETADO` después |
| Heartbeat durante inferencia real | 50 vencimientos de lease distintos observados antes del terminal |
| Redelivery del mismo `DiagnosisRequested.v2` con publicación confirmada | Cola final 0 mensajes, 1 consumidor; inbox AI 1, resultado AI 1, outbox AI 1 y `DiagnosisFinished` 1 |
| Renovación con token obsoleto, después de reclamar otra solicitud | Reclamo HTTP 200; renovación HTTP 409 `STALE_LEASE`; no se afirmó resultado de esa segunda solicitud |
| Carga normal del mismo recorrido | 16 terminales, mediana 13,478 s, p95 15,153 s, máximo 15,153 s; pico cgroup del worker 594.051.072 bytes (566,5 MiB) |

El p95 observado queda bajo la meta de flujo completo ≤ 30 s. El pico de memoria **del contenedor** queda bajo 1024 MiB, pero no es una medida de RSS del proceso ni una promesa de capacidad en otro hardware o concurrencia. La primera repetición de la sonda falló por una sangría del propio código y se corrigió; la segunda confundió el retorno `None` de Pika con una publicación no confirmada. La corrida anterior a esta tabla probó 51 renovaciones y 409, pero no acreditó redelivery. Solo el informe final con confirmación y cola drenada acredita 9.2. Las cuatro falsas aceptaciones de papa sana persistieron (4/4) en la corrida final y siguen bloqueando 9.1/G3.

## Estado de tareas

- **7.5 cerrada:** fuentes, revisión del responsable, contenido sin productos ni dosis y publicación vía API administrativa verificadas en el proyecto aislado.
- **9.1 abierta:** falla el rechazo de papa sana; G3 no aprobado.
- **9.2 cerrada:** fallos con runtime real y mediciones locales documentados arriba; no acreditan G3 por sí solos.
- **9.3 abierta:** [CI local completa 18/18](INCREMENTO-4-CI-LOCAL.md); falta ejecución remota identificada de esta revisión. El responsable hará el `git push` tras el commit de Codex.
- **9.4 abierta:** requiere 9.1–9.3, revisión G3 y cierre sin pendientes.

El plan correctivo añade 10.1–10.4 al cambio OpenSpec; con 7.5 y 9.2 cerradas el avance pasa a **37/44**. Las cuatro tareas nuevas siguen abiertas hasta nueva aprobación G0, admisión G1, evaluación G2 y repetición de 9.1.
