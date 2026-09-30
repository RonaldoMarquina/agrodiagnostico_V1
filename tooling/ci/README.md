# Herramientas de CI

`tools.json` fija runtimes, commits de actions oficiales y URL/checksum de actionlint. `package-lock.json` fija OpenSpec y npm aislados; `requirements.lock` fija Ruff y hashes de sus distribuciones. El resto de herramientas/dependencias se instala desde los locks existentes de contratos, servicios y frontend.

Desde la raíz: `bash scripts/prepare_ci.sh`, luego `python3 scripts/run_ci.py`. No instalar globalmente. El plan es obligatorio: todas sus etapas deben terminar con salida cero para aprobar. `scripts/check_ci_workflow.py` rechaza IDs ausentes/duplicados y comprueba las referencias de actions, permisos y hooks de limpieza/artefactos, además de ejecutar actionlint.

La actualización de una herramienta requiere revisar versiones, integridades, compatibilidad y repetir los checks afectados; no ejecutar actualizaciones automáticas en cada build. npm 12.1.0 se usa únicamente en este tooling, compatible con Node 24.21.0; el npm global del equipo se conserva. La actualización redujo avisos del paquete, pero npm audit aún reporta dos de severidad alta y uno moderado en dependencias incluidas por npm (brace-expansion, undici, ip-address). No se presentan como corregidos ni como dependencias del producto desplegado. [Registro](../../docs/evidence/incremento-0-grupo-6-tooling-audit.json).

No descargar datasets, pesos ni conectar credenciales de producción. Operación, límites y regresiones: [docs/CI.md](../../docs/CI.md).
