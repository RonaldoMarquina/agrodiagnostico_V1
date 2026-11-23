# Runbook TRAIN/VAL v1.4.1

Todos los comandos se ejecutan sin red y sin montar Sikkim ni TEST. El contenedor recibe únicamente el repositorio, el manifiesto G1 y los bytes PlantVillage admitidos.

## Preflight y pruebas

```bash
docker run --rm --network none --user 1000:1000 -v "$PWD:/workspace" -w /workspace agrodiagnostico-v1-ai_inference-worker-real:latest /service/ml/.venv/bin/python -m unittest tests.ml.test_v141_gates tests.ml.test_v141_training tests.contracts.test_ml_v141_contracts
```

## Entrenamiento desde cero

```bash
AGRO_GIT_HEAD=$(git rev-parse HEAD)
docker run --rm --network none --user 1000:1000 -e AGRO_GIT_HEAD="$AGRO_GIT_HEAD" -v "$PWD:/workspace" -w /workspace agrodiagnostico-v1-ai_inference-worker-real:latest /service/ml/.venv/bin/python scripts/train_v141_candidate.py --plan ml/configs/potato-v141-four-class-cpu.plan.json --protocol ml/evaluation/protocol-g0.v1.4.1.json --gate-status ml/evaluation/gate-status.v1.4.1.json --private-g1 .local/ml-v1.4.1 --images-root .local/pv-g1/g1-v1.3.1-admitted/images --output .local/ml-v1.4.1-train-val/candidate
```

El proceso es deliberadamente de una sola ejecución desde cero. Ante interrupción no se carga estado de optimizador no verificable: se reanuda como reinicio determinista en una salida nueva, con el mismo commit y semilla, cambiando únicamente `--output` a `.local/ml-v1.4.1-train-val/candidate-restart-1`. La salida incompleta se conserva para auditoría hasta comparar su expediente.

La auditoría exige 1.623 originales TRAIN, 496 VAL, 320 exposiciones por época (80 por clase), cero acceso EXTERNAL/TEST y el hash del commit previo al entrenamiento. El manifiesto y el log deben contener únicamente `TRAIN`/`VAL`; el contenedor se ejecuta con `--network none` y sin montajes separados de Sikkim o TEST.
