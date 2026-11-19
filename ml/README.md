# ML — incremento 4 en corrección

No hay dataset admitido ni modelo real validado. Las fuentes/mappings v2 están pendientes de revisión y G0 es un borrador sin aprobación docente.

El código actual contiene herramientas y clasificadores lineales de prueba; no implementa MobileNet/ResNet ni carga pesos PyTorch reales. Las extensiones de sus archivos históricos de fixture no acreditan el formato safetensors. No usar estos archivos como releases.

La CLI `train`, `calibrate`, `freeze`, `evaluate`, `package` y `verify` devuelve código 2 sin declarar éxito: el pipeline real y la verificación independiente del release están pendientes, además de G0/G1. Esto impide declarar entrenamiento/evaluación o integridad G2 cuando no se comprobaron. El sellado de TEST rechaza un manifiesto sin muestras TEST. No basta descargar imágenes para desbloquearlo.

Pruebas técnicas: `bash scripts/check_ml_runtime.sh`. No acreditan G2/G3. El worker rechaza `INFERENCE_MODE=real`; `fixture` exige APP_ENV=test y ENABLE_SIMULATED_INFERENCE=true. El simulador del incremento 3 mantiene sus restricciones.

La aceptación real permanece pendiente; `scripts/check_ml_real_acceptance.py` no declara G3 aprobado por su comprobación sintética. Consultar [tareas](../openspec/changes/incremento-4-datos-y-modelo-validado/tasks.md) y [estado](../docs/evidence/INCREMENTO-4-ACEPTACION-INTEGRADA.md).
