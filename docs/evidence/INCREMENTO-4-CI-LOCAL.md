# Incremento 4 — CI local completa

Ejecución local del 2026-11-20 sobre el árbol de trabajo previo al commit. Comando: `PATH=/tmp/agro-ci-python3123/bin:/tmp/agro-ci-bin:$PATH python3 scripts/run_ci.py`, después de `bash scripts/prepare_ci.sh` con las versiones fijadas. El directorio privado `.local/ci/1c17293861aa4872a472cbb6f0d29108` contiene logs y `summary.json`, SHA-256 `31fff78a0e5d55e1f7d009b98955034d33d3dfdd0357c18fb39e472c00015fd4`. Resultado `passed`: **18/18 etapas**, todas con código 0, sin `cleanup_error`.

Versiones verificadas por el runner: Python 3.12.3, Node 24.21.0, npm 12.1.0, OpenSpec 1.13.2, Docker 29.1.3 y Compose 2.40.3. Python 3.12.3 se extrajo de la imagen oficial `python:3.12.3-slim-bookworm` a `/tmp`; npm 12.1.0 se instaló en `/tmp`. No se modificaron las herramientas globales. El runner registró el HEAD de partida `6b1f32931e64d9513dd9be998c99d8312379488b` y los SHA-256 de archivos permitidos del árbol de trabajo; los cambios aún no estaban confirmados en ese HEAD.

Etapas aprobadas: `workflow`, `python-lint`, `ci-tests`, `contracts`, `dataset`, `ml-contracts-and-runtime`, `backend`, `frontend-install`, `frontend-lint`, `frontend-types`, `frontend-tests`, `frontend-build`, `openspec`, `persistence`, `environment`, `identity-integration`, `diagnosis-integration` y `async-integration`. `git diff --check` y `openspec validate --all --strict --no-interactive` también pasaron (15 elementos OpenSpec, cero fallos).

Antes de esta corrida, dos fallos de integración de pruebas se corrigieron: import del preflight G3 bajo los paquetes `app` de servicios distintos, y activación de política en un fixture antes de crear sus clases de catálogo. Las etapas ML y backend se repitieron por separado y pasaron antes de la CI completa. Esto acredita las comprobaciones técnicas locales; **no aprueba G3** ni corrige la falsa aceptación de papa sana del bundle v1.2.0.

**Estado al terminar esta corrida local:** 9.3 permanecía abierta porque faltaba publicar el commit y registrar una ejecución remota identificada. El responsable publicó `bda7eb3` posteriormente; la [evidencia remota](INCREMENTO-4-CI-REMOTA-BDA7EB3.md) cierra 9.3, sin cerrar G3.
