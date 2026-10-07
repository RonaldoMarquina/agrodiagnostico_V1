# Corrección del cierre del incremento 2

Fecha: 2026-10-06. Cambio archivado: [corregir-cierre-incremento-2](../../openspec/changes/archive/2026-10-06-corregir-cierre-incremento-2/tasks.md), 6/6 tareas completas y cuatro deltas sincronizados. Complementa la auditoría histórica, sin modificar su archivo OpenSpec.

## Hallazgos corregidos

- Catálogo: cuerpos POST cerrados, listas y elementos estrictos, límites OpenAPI, fuentes no vacías y revisión UTC. Fuente vacía devuelve 400 CATALOG_REVIEW_REQUIRED; elementos numéricos/campos extra devuelven 400 INVALID_REQUEST. Ningún rechazo crea recomendación o auditoría.
- Ingesta: multipart debe terminar y contener un archivo image. Truncamiento o parte sin filename devuelve 400 INVALID_REQUEST antes de crear diagnóstico, intención u objeto.
- CI: etapa obligatoria diagnosis-integration ejecuta el E2E. Controles rechazan omitirla o sustituirla por true. El script construye imágenes del checkout con etiquetas propias; no depende de imágenes locales preexistentes. Limpia contenedores, volúmenes anónimos asociados, red, etiquetas y secretos temporales.
- Concurrencia: conexiones independientes contra PostgreSQL, barreras y sincronización explícita. Idempotencia devuelve 409 mientras otra carga mantiene el lock y conserva un único diagnóstico; cancelación produce 200/409; versiones simultáneas distintas y consecutivas; feedback produce 201/200, una fila y contenido de la última actualización.
- OpenSpec alineado con la interfaz HTTP actual mediante ADR-0007. Se conservan IMAGE_TOO_LARGE, la expresión de Idempotency-Key y códigos 404 específicos existentes, siempre genéricos respecto a propiedad. Se corrigen enlaces y párrafos de estado desactualizados.

## Verificación ejecutada

| Comando | Resultado |
| --- | --- |
| `PYTHONPATH=services/diagnosis .local/diagnosis_venv/bin/python -m unittest discover -s services/diagnosis/tests` | 115 pruebas PASS; incluye matrices negativas nuevas |
| `.venv-contracts/bin/python -m unittest discover -s tests/contracts` | 11 pruebas PASS |
| `.venv-contracts/bin/python scripts/validate_contracts.py` | 608 ejemplos, 4 OpenAPI, 46 operaciones y 5 schemas |
| `python3 scripts/check_ci_tests.py` | 7 controles PASS |
| `python3 scripts/check_ci_workflow.py` | PASS, incluido actionlint |
| `python3 scripts/check_acceptance_incremento2.py` | 10 fases E2E y 4 verificaciones PostgreSQL simultáneas PASS; entorno desechable |
| `openspec validate --all --strict --no-interactive` | 12 elementos PASS |
| Ruff E9,F63,F7,F82 y `git diff --check` | PASS |

Los entornos Python locales son auxiliares. El CI instala dependencias bloqueadas mediante scripts/check_service_locks.sh y el E2E construye desde Dockerfiles/locks versionados. El registro E2E reproducido se conserva en INCREMENTO-2-CORRECCION-E2E.txt.

## Límites

El 2026-10-07 se ejecutó el pipeline global local completo: 16/16 etapas PASS. Se corrigió una expectativa histórica del smoke: GET /api/v1/diagnoses sin credenciales debe devolver 401, mientras rutas internas permanecen en 404. [Informe con versiones, tiempos y hashes del código probado](INCREMENTO-2-CI-LOCAL.json). Comando: `python3 scripts/run_ci.py --artifacts .local/ci/cierre-inc2-final-20261007`. No se ha verificado una ejecución remota de GitHub Actions para este correctivo: publicar está pendiente de autenticación. No se aplicaron migraciones a la base local de desarrollo. PostgreSQL y S3 de aceptación son desechables; las pruebas de concurrencia de la capa de aplicación usan un adaptador de almacenamiento controlado para retener el lock, mientras el E2E usa S3 real.

El E2E original rotula su fase 10 como fault injection, pero esa fase demuestra reconciliación de un huérfano: los fallos de S3 se cubren en la suite aislada de Diagnosis, no mediante caída real de S3 en este correctivo. La prueba unitaria de cancelación repetida fue renombrada para no presentarla como carrera real.

No hay inferencia real, worker ni entrenamiento. El catálogo no recibe contenido agronómico de producción. Las recomendaciones de aceptación son fixtures explícitamente sintéticos.
