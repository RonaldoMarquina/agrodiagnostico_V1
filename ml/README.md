# ML — incremento 4, piloto de dos tizones

## Ciclo v1.3.2: candidato TRAIN/VAL congelado

El [expediente de entrenamiento v1.3.2](../docs/evidence/INCREMENTO-4-TRAIN-VAL-V1.3.2.md) registra un MobileNetV3-Small de tres salidas técnicas, dos publicables, entrenado con TRAIN G1 v1.3.1 y seleccionado solo con VAL. `POTATO_HEALTHY` con argmax se abstiene; `OTHER_CROP` participa solo como negativo de entrenamiento y evaluación. El paquete privado quedó congelado con pesos, calibración, umbral y hashes antes de [evaluar TEST una sola vez](../docs/evidence/INCREMENTO-4-TEST-V1.3.2-UNICO.md). **G0 TEST falló en rechazo de papa sana; G2 permanece abierto.** No integrar ni activar este candidato. Los comandos reproducibles no descargan datos ni pesos. La evidencia histórica v1.2.0 que sigue abajo no se modifica.

G1 del piloto dispone de un dataset privado admitido. [MobileNetV3-Small y ResNet18 se entrenaron y compararon en TRAIN/VAL reales](../docs/evidence/INCREMENTO-4-ENTRENAMIENTO-VAL-PILOTO.md); el candidato seleccionado se congeló antes de [una evaluación del TEST sellado](../docs/evidence/INCREMENTO-4-TEST-PILOTO-V1.2.md) que cumple límites numéricos. El [bundle de dos tizones está aprobado G2](../docs/evidence/INCREMENTO-4-APROBACION-G2-PILOTO.md) y su adaptador está preparado en el worker, pero no se ha activado una política ni el perfil real. G0 de diseño corresponde al [protocolo v1.2.0](evaluation/protocol-g0.v1.2.0.json).

El recorrido histórico con fixtures gráficos usa MobileNetV3-Small conjunta y ResNet18 jerárquica; solo demuestra funcionamiento técnico. El experimento real del piloto usa **dos clasificadores no jerárquicos**, MobileNetV3-Small y ResNet18, sobre las mismas particiones y preprocesado, con pesos iniciales aleatorios y artefactos `safetensors`. Los clasificadores lineales históricos y los archivos JSON con extensión de pesos siguen siendo fixtures heredados. [Evidencia de fixtures](../docs/evidence/INCREMENTO-4-CPU-SMOKE.md).

La CLI `smoke-train`, `smoke-infer`, `smoke-compare`, `smoke-evaluate` y `smoke-package` trabaja solo con fixtures gráficos y marca sus artefactos `FIXTURE_ONLY`. La evaluación técnica usa `VAL_FIXTURE`. Los comandos heredados de release `train`, `calibrate`, `freeze`, `evaluate`, `package` y `verify` continúan devolviendo código 2; el flujo real de bundle usa los scripts independientes descritos abajo. Ninguno activa el worker.

## Experimento real TRAIN/VAL del piloto v1.2.0

Con G1 cerrado, `scripts/run_pilot_training.py` acepta exclusivamente los cuatro manifiestos privados TRAIN/VAL, verifica derechos, etiquetas, SHA-256 y bytes, y entrena en CPU sin descargas. `scripts/select_pilot_candidate.py` compara las arquitecturas, calibra y congela el candidato con umbral seleccionado en VAL. `scripts/measure_pilot_inference.py` mide CPU sobre una imagen fija de VAL. Los comandos completos, versiones, hashes, métricas y límites constan en el [expediente de entrenamiento](../docs/evidence/INCREMENTO-4-ENTRENAMIENTO-VAL-PILOTO.md). Estos tres scripts rechazan TEST. `scripts/evaluate_frozen_pilot_test.py` abrió el TEST sellado una sola vez después del congelamiento y produjo el [reporte independiente](../docs/evidence/INCREMENTO-4-TEST-PILOTO-V1.2.md). `scripts/build_pilot_g2_bundle.py`, `scripts/verify_pilot_g2_bundle.py` y `scripts/record_pilot_g2_approval.py` empaquetaron, cargaron y registraron el [release privado aprobado G2](../docs/evidence/INCREMENTO-4-APROBACION-G2-PILOTO.md) sin volver a leer TEST. El worker real está preparado y apagado; G3 sigue pendiente.

## Candidato CPU reproducible (tarea 2.3)

`cpu-train`, `cpu-evaluate-val` y `cpu-package-candidate` operan con imágenes locales y manifiestos JSON explícitos; el último **recalcula VAL** antes de archivar y rechaza un reporte editado. La configuración versionada [`cpu-candidate.v1.json`](configs/cpu-candidate.v1.json) fija semilla, tamaño, épocas, tasa y pesos base `RANDOM_INITIALIZATION`; los constructores usan `weights=None`, CPU y `safetensors`. Un manifiesto declara `schema_version: 1`, `scope: FIXTURE_ONLY` o `G1_ADMITTED`, `dataset_version`, `split: TRAIN|VAL` y filas `relative_path`, `sha256`, `class_code`, `split_group`. En `G1_ADMITTED` exige referencias G1 de derechos y revisión por imagen; el [lote piloto](../docs/evidence/INCREMENTO-4-G1-PILOTO-V1.2.md) aporta esa evidencia privada. Los comandos rechazan rutas fuera de la raíz privada, hashes alterados, grupos que cruzan TRAIN/VAL y cualquier intento de evaluar TEST. El paquete de candidato no cumple `model-bundle.v1` ni obtiene G2.

Recorrido ejecutable con **fixtures geométricos** desde la raíz; instala `uv==0.12.20` con hashes en un entorno temporal y luego usa el lock ML:

```bash
agro_candidate_dir="$(mktemp -d)"
python3 -m venv "$agro_candidate_dir/tools"
"$agro_candidate_dir/tools/bin/python" -m pip install --require-hashes -r tooling/uv.requirements.txt
UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT="$agro_candidate_dir/env" "$agro_candidate_dir/tools/bin/uv" sync --project ml --locked --no-dev
agro_ml_bin="$agro_candidate_dir/env/bin/agro-ml"
"$agro_ml_bin" cpu-fixture-data --output-dir "$agro_candidate_dir/data"
"$agro_ml_bin" cpu-train --config ml/configs/cpu-candidate.v1.json --manifest "$agro_candidate_dir/data/train.json" --images-root "$agro_candidate_dir/data/images" --output-dir "$agro_candidate_dir/model"
"$agro_ml_bin" cpu-evaluate-val --checkpoint "$agro_candidate_dir/model/candidate-checkpoint.json" --train-manifest "$agro_candidate_dir/data/train.json" --val-manifest "$agro_candidate_dir/data/val.json" --images-root "$agro_candidate_dir/data/images" --output "$agro_candidate_dir/val-report.json"
"$agro_ml_bin" cpu-package-candidate --checkpoint "$agro_candidate_dir/model/candidate-checkpoint.json" --evaluation "$agro_candidate_dir/val-report.json" --train-manifest "$agro_candidate_dir/data/train.json" --val-manifest "$agro_candidate_dir/data/val.json" --images-root "$agro_candidate_dir/data/images" --output "$agro_candidate_dir/candidate.zip"
```

`uv sync` instala dependencias bloqueadas de forma explícita; ningún comando de modelo descarga pesos o datos. La prueba de instalación limpia usa `bash scripts/check_ml_runtime.sh`. Los resultados de este ejemplo son exclusivamente de software con `FIXTURE_ONLY`.

Pruebas técnicas: `bash scripts/check_ml_runtime.sh`. No acreditan G2/G3. El worker real carga el bundle privado G2 solo en el perfil `ml-real`; ese perfil permanece apagado. `fixture` exige APP_ENV=test y ENABLE_SIMULATED_INFERENCE=true. El simulador del incremento 3 mantiene sus restricciones.

El motor `agro_ml.evaluation.metrics.generate_evaluation_report` calcula métricas de entradas suministradas, se verifica con fixtures y produjo reportes reales de VAL y TEST. Con máscara de abstención, una predicción técnica acertada publicada como `NO_CONCLUYENTE` cuenta como falso negativo y no como acierto visible; reporta numeradores/denominadores de cobertura, error selectivo y negativos. Sin aceptados, el error selectivo es `null`; sin negativos, su FPR es `null`, por lo que ninguno acredita el límite G0. Si una clase no tiene muestras, los macros son `null`. El evaluador de TEST añade Brier, calibración por intervalos, entropía y margen desde las salidas reales, y memoria medida. La tarea 5.3 está cerrada; el comando heredado de release `evaluate` permanece bloqueado hasta la aprobación G2.

## Comprobación G0–G3 y preflight de aceptación

G0 aprobado: [`protocol-g0.v1.2.0.json`](evaluation/protocol-g0.v1.2.0.json) y [ficha](../docs/evidence/INCREMENTO-4-FICHA-G0.md). G1 admitido: `PYTHONPATH=ml/src python3 scripts/verify_plantvillage_pilot_g1.py .local/pv-g1/pilot-v1.2 .local/pv-g1/batch-v1`; conservar su reporte y sello TEST. G2 aprobado: verificar el bundle sin abrir imágenes con:

```bash
python scripts/verify_pilot_g2_bundle.py --bundle .local/ml-pilot-v1.2/g2-bundle-v1/model-bundle.json --expected-sha256 93e2e65130a9c266be4bdba0262d1c98e30d0604f4d21466effba2d9c9ff0b41 --require-approval-record
```

El preflight G3 requiere **ese** bundle y acta G2, política propuesta y el directorio G1 privado. Compara los hashes del reporte G1, manifiestos TRAIN/VAL/TEST y sello; carga el bundle de forma independiente pero no lee imágenes TEST ni consume colas. El reporte es de creación única para preservar evidencia:

```bash
python scripts/check_ml_real_acceptance.py --release-bundle .local/ml-pilot-v1.2/g2-bundle-v1/model-bundle.json --g2-approval .local/ml-pilot-v1.2/g2-bundle-v1/g2-approval.json --policy-file .local/ml-pilot-v1.2/policy-draft-v1.json --g1-directory .local/pv-g1/pilot-v1.2 --output-report .local/ml-pilot-v1.2/g3-preflight-<nueva-ejecucion>.json
```

`PREREQUISITES_VERIFIED_G3_PENDING` significa que todavía faltan catálogo revisado, política activada y recorrido real HTTP → cola → worker → Diagnosis → historial. El preflight **no aprueba G3**. Los comandos de promoción, retiro y rollback están en [operación](../docs/operations/ai-model-operations.md). [Evidencia de la ejecución](../docs/evidence/INCREMENTO-4-POLITICA-Y-PREFLIGHT-G3.md).
