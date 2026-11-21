> Alcance actual: G0 v1.2.0 aprueba únicamente los dos tizones de papa para el piloto. Las referencias a siete clases y maíz en esta evidencia describen el inventario o trabajo histórico. [G1 del lote piloto](INCREMENTO-4-G1-PILOTO-V1.2.md) se cerró después de estas pruebas CPU con fixtures. [Decisión](../adr/0009-modelo-validado-inferencia-y-politicas-de-publicacion.md).

# Incremento 4 — recorrido técnico CPU con fixtures

Estado de estas pruebas: 2026-11-19. **G0 de diseño aprobado por el responsable; G2 y G3 pendientes.** El lote G1 se admitió por evidencia separada. Estas pruebas CPU no miden diagnóstico agronómico ni admiten fuentes o imágenes por sí mismas.

## Qué se ejecutó

- El paquete `ml/` se instaló desde `ml/uv.lock` en un entorno limpio de `/tmp`, con Python 3.12, PyTorch `2.15.0+cpu`, TorchVision `0.29.2+cpu` y safetensors `0.8.0`. `torch.cuda.is_available()` devolvió `False`.
- `smoke-train` generó imágenes geométricas rotuladas como fixtures, entrenó cabezas tensoriales en CPU, guardó pesos `safetensors`, verificó SHA-256, recargó el modelo y ejecutó `smoke-infer`. `weights=None` en ambos constructores impide descargas implícitas de pesos base; el manifiesto registra inicialización aleatoria y `approval: null`.
- El preprocesado tensorial común convirtió bytes decodificados con orientación EXIF a RGB, normalizó CHW y produjo el mismo tensor en TRAIN sin aumentación, VAL e INFERENCE. La aumentación exige TRAIN y semilla. Se midió solo tiempo de preprocesado en fixture; el presupuesto G0 está aprobado como meta y no se ha medido con un modelo agronómico.
- La alternativa jerárquica usa una cabeza de cultivo con salida `OTHER` separada de las siete clases de condición y abstiene ante rechazo o ambigüedad. La política técnica se seleccionó sobre `VAL_FIXTURE` y tiene `approval: null`.

Comandos reproducibles desde la raíz, con `uv==0.12.20` instalado:

```bash
UV_PROJECT_ENVIRONMENT=/tmp/agro-ml-cpu uv sync --project ml --locked --no-dev
/tmp/agro-ml-cpu/bin/agro-ml smoke-train --config ml/configs/cpu-smoke.v1.json --architecture mobilenet_v3_small --output-dir /tmp/agro-joint
/tmp/agro-ml-cpu/bin/agro-ml smoke-train --config ml/configs/cpu-smoke.v1.json --architecture resnet18_hierarchical --output-dir /tmp/agro-hierarchical
/tmp/agro-ml-cpu/bin/agro-ml smoke-infer --checkpoint /tmp/agro-joint/fixture-checkpoint.json --fixture-label 0
/tmp/agro-ml-cpu/bin/agro-ml smoke-compare --joint /tmp/agro-joint/fixture-checkpoint.json --hierarchical /tmp/agro-hierarchical/fixture-checkpoint.json
/tmp/agro-ml-cpu/bin/agro-ml smoke-evaluate --checkpoint /tmp/agro-hierarchical/fixture-checkpoint.json --output /tmp/agro-hierarchical/fixture-evaluation.json
/tmp/agro-ml-cpu/bin/agro-ml smoke-package --checkpoint /tmp/agro-hierarchical/fixture-checkpoint.json --evaluation /tmp/agro-hierarchical/fixture-evaluation.json --output /tmp/agro-hierarchical-fixture.zip
bash scripts/check_ml_runtime.sh
```

En la ejecución local, los pesos de ambos modelos cambiaron y sus hashes se reprodujeron en dos corridas con la misma semilla/configuración. En `VAL_FIXTURE`, el modelo conjunto aceptó 7/7 patrones positivos, acertó su etiqueta en 1/7 y rechazó 0/1 negativo; la alternativa jerárquica aceptó y acertó 7/7 positivos y rechazó 1/1 negativo. La alternativa optimizó sus tres cabezas con un lote de ocho patrones de entrenamiento; su umbral de cultivo se eligió únicamente sobre ocho variantes de validación. Este conjunto minúsculo comparte el generador con TRAIN y sirve para probar el software, **no para estimar Accuracy/F1 agronómico ni generalización**. La comparación devuelve `selected_for_release: null`; ningún modelo se promueve por estos conteos.

`smoke-evaluate` genera un reporte reproducible con las ocho decisiones `VAL_FIXTURE`; `smoke-package` vuelve a evaluarlas, comprueba que el reporte coincide con los pesos y guarda ambos en un ZIP marcado `FIXTURE_ONLY`. Este ZIP no cumple el contrato `model-bundle.v1`, no lleva aprobación y no puede activar el worker real.

## Límite para las tareas

El preprocesado tensorial y la línea base conjunta de 4.1–4.2 cuentan con código y pruebas técnicas. La alternativa jerárquica tiene un mecanismo técnico ejecutable, pero 4.3 permanece abierta hasta demostrar viabilidad y rechazo sobre VAL autorizada; los umbrales de VAL_FIXTURE no sirven para datos reales. El identificador interno `resnet18_hierarchical` tampoco está representado como tipo de modelo en `model-bundle.v1`; antes de empaquetar esa alternativa como release hay que fijar un contrato versionado de topología. El worker real y el bundle G2 pertenecen a 6.1–6.2/5.5 y tampoco se activaron. `tests/ml/test_torch_cpu_smoke.py` prueba hash alterado, entradas inválidas, orientación/color, reproducibilidad, ausencia de descarga, rechazo ante `OTHER`/ambigüedad y que una VAL_FIXTURE sin cobertura de ambos cultivos no produce política.

## Candidato CPU y reporte — actualización del 2026-11-19

La tarea 2.3 dispone de [comandos reproducibles](../../ml/README.md#candidato-cpu-reproducible-tarea-23) para generar fixtures, entrenar una MobileNetV3-Small candidata en CPU, evaluar solo VAL y empaquetar pesos `safetensors` con hashes. El manifiesto local explicita `FIXTURE_ONLY` o requiere referencias G1 por imagen; la verificación de derechos de imágenes reales sigue en 3.3/G1. El paquete de candidato no es `model-bundle.v1`, no lleva aprobación ni abre TEST. El empaquetador recalcula VAL y rechaza métricas editadas. Se usó `weights=None`, sin descarga de pesos base; la procedencia aleatoria queda en el checkpoint.

El motor de métricas ahora informa resultados **visibles**: si se publica `NO_CONCLUYENTE`, la predicción técnica acertada cuenta como abstención y falso negativo de la clase verdadera. Las pruebas comprueban numeradores/denominadores de cobertura, error selectivo y negativos, así como cero aceptados y cero negativos. 5.3 sigue abierta hasta integrar un reporte real con hardware y procedencia G2. `bash scripts/check_ml_runtime.sh` instaló el lock en un entorno limpio y pasó **107 pruebas ML + 9 del adaptador**. Es verificación técnica local, no rendimiento agronómico ni CI remota.
