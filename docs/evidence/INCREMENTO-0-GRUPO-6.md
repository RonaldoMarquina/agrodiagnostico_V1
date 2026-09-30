# Evidencia del grupo 6 — CI de aplicación

La ejecución local completa terminó con las 14 etapas aprobadas. Los tiempos, versiones, hashes y códigos de salida están en [summary.json](incremento-0-grupo-6/positive/summary.json); los logs contiguos documentan cada etapa. La suma de duraciones de etapas fue 246.138 segundos.

Se ejecutaron cinco regresiones en copias desechables: evento inválido, referencia HTTP rota, migración fallida, readiness fallido y timeout. Todas provocaron fallo global; el timeout produjo código 124 en su etapa. La limpieza se verificó en todos los casos. Véase [regressions.json](incremento-0-grupo-6/regressions/regressions.json) y los reportes individuales.

Comandos reproducibles: `bash scripts/prepare_ci.sh`, `python3 scripts/run_ci.py` y `python3 scripts/check_ci_regressions.py`. Consulte `docs/CI.md` para las opciones y requisitos del entorno.

Workflow remoto no ejecutado. Estos resultados prueban la reproducción local, no una ejecución en GitHub. No hubo publicación ni push. La auditoría del tooling npm conserva dos hallazgos altos y uno moderado en dependencias transitivas; véase [auditoría](incremento-0-grupo-6-tooling-audit.json). No se declara ausencia de vulnerabilidades ni aceptación de producción.
