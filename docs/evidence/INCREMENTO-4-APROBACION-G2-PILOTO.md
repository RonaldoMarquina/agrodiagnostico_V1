# Incremento 4 — aprobación G2 del bundle del piloto v1.2.0

Decisión del **responsable del proyecto**, registrada el 2026-11-19 en America/Lima (`2026-11-20T04:23:31.237194Z`), tras comprobar la carga independiente exigida por 5.5. Identificador: `G2-POTATO-BLIGHTS-2026-11-19-001`. Protocolo de diseño: **G0 v1.2.0**. El acta privada `.local/ml-pilot-v1.2/g2-bundle-v1/g2-approval.json` tiene SHA-256 `579404dfe711fcae00c5d8964db669b8a66477f853d48a1fed45f72946d165f9`. El usuario aprobó expresamente registrar G2 si la carga independiente pasaba; no se atribuye una firma docente ni revisión agronómica nueva.

## Artefacto aprobado y carga independiente

Bundle privado `.local/ml-pilot-v1.2/g2-bundle-v1/model-bundle.json`, contrato [`model-bundle.v1`](../../contracts/ml/model-bundle.v1.schema.json), **SHA-256 `93e2e65130a9c266be4bdba0262d1c98e30d0604f4d21466effba2d9c9ff0b41`**. Identidad `agrodiagnostico-potato-blights-mobilenetv3-small`, versión `0.1.0-pilot`, dataset `1.2.0-pv-color`. El manifiesto contiene digests de ambos componentes de TRAIN, VAL y TEST, y digests combinados de cada partición. También vincula pesos `safetensors`, configuración, preprocesado, calibración, umbral, protocolo G0, congelamiento, reporte TEST y lock de dependencias.

La carga en **otro proceso CPU sin red** verificó el SHA registrado, esquema, pesos y tensores finitos, hashes de cada componente, manifiestos contra congelamiento y reporte TEST, preprocesado idéntico, calibración Platt por clase y umbral **0,50**. La inferencia de comprobación usó una imagen **sintética** y produjo tres salidas técnicas: los índices 0 y 1 pueden mapear únicamente a `POTATO_EARLY_BLIGHT` y `POTATO_LATE_BLIGHT`; el índice 2 `OTHER_CROP` solo permite rechazo y nunca es clase publicada. El bundle exige `identified_crop=POTATO`. Siete alteraciones en copias temporales (pesos, configuración, calibración, umbrales, reporte, mapa y acta) fueron rechazadas. La comprobación sintética verifica carga e integridad, no rendimiento agronómico.

## Resultado TEST vinculado

El [reporte TEST único](INCREMENTO-4-TEST-PILOTO-V1.2.md) tiene SHA-256 `b10a6654d64c56e6967f51de28ede65924813b5da8684319ffc16788d71e4e96`. F1 macro **0,9317**; recall temprano **116/122 = 0,9508** y tardío **103/113 = 0,9115**; cobertura **235/235 = 1,0000**; error selectivo **16/235 = 0,0681**; negativos aceptados **0/112**. ECE 0,0366 y Brier binario 12,91077799/235 = 0,054939. Los criterios numéricos G0 v1.2.0 se cumplen. El modelo y umbral se eligieron en VAL antes de abrir TEST y no se ajustaron con TEST.

## Límites de la aprobación

G2 aprueba **solo el artefacto de inferencia para diferenciar dos tizones en una hoja de papa previamente identificada**. **EXTERNAL no existe** para este piloto; no se ha medido generalización a Ayacucho ni fotografías reales independientes. Papa sana, maíz, identificación automática de cultivo y plagas quedan fuera; no se ha medido rechazo de papa sana. La latencia p95 del **flujo completo** sigue pendiente aunque el cómputo CPU aislado se midió. G2 no aprueba recomendaciones del catálogo, no activa política de publicación ni habilita el worker real. G3 y las tareas **6.1–6.4** siguen abiertas para integrar y probar el bundle de forma segura.

Comandos de reproducción sin leer de nuevo TEST: [`build_pilot_g2_bundle.py`](../../scripts/build_pilot_g2_bundle.py), [`verify_pilot_g2_bundle.py`](../../scripts/verify_pilot_g2_bundle.py), [`record_pilot_g2_approval.py`](../../scripts/record_pilot_g2_approval.py) y [`check_pilot_g2_bundle_integrity.py`](../../scripts/check_pilot_g2_bundle_integrity.py). El acta es inmutable: esos comandos de creación fallan si la salida o el acta ya existen. Para verificar el artefacto final:

```bash
docker run --rm --pull=never --network none --user "$(id -u):$(id -g)" --cpus=4 --memory=4g \
  -v "$PWD:/workspace" -w /workspace \
  -e PYTHONPATH=/workspace/ml/.venv/lib/python3.12/site-packages:/workspace/ml/src \
  python:3.12-slim-bookworm python scripts/verify_pilot_g2_bundle.py \
  --bundle .local/ml-pilot-v1.2/g2-bundle-v1/model-bundle.json \
  --expected-sha256 93e2e65130a9c266be4bdba0262d1c98e30d0604f4d21466effba2d9c9ff0b41 \
  --require-approval-record
```
