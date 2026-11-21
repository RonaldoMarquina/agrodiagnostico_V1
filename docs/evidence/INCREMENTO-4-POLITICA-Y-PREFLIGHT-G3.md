# Incremento 4 — política y preflight G3 (2026-11-20)

## Alcance y artefactos

Tareas 7.2, 7.4, 8.2 y 8.3. El bundle G2 aprobado conserva SHA-256 `93e2e65130a9c266be4bdba0262d1c98e30d0604f4d21466effba2d9c9ff0b41`; acta G2 `579404dfe711fcae00c5d8964db669b8a66477f853d48a1fed45f72946d165f9`; reporte G1 `cfdf69cf04e813b0e98070a4048bd5ed174eafc36cc7012838e9e2e141655d75`; sello TEST `3f89a833ad38782f7d7139283ef444321d139a8798e8d6fec8053e3e79819e07`. El borrador privado `.local/ml-pilot-v1.2/policy-draft-v1.json` tiene SHA-256 `2e3dee4d6444f5218115146c713a193b72aa3f15a2029fb997618f3ca4c2ed35` e ID `379be27f-e05a-487f-8bae-1dfd9644eedd`. **No se importó ni activó** en la base real.

## Política y finalización

`app.policy import|activate|retire` exige actor y motivo, usa dry-run por defecto y registra auditoría en la misma transacción que la mutación. La importación del piloto exige bundle y acta G2 de hash exacto y compara tupla modelo/dataset, mapa de dos clases, calibración y umbral. La migración `diagnosis_0007` impide dos políticas activas. Un advisory lock transaccional compartido para la decisión de publicación y exclusivo para activar/retirar serializa incluso el caso sin política previa. Diagnosis conserva en la transacción de `DiagnosisFinished` el estado, snapshot de política/confianza, catálogo, inbox, outbox y auditoría. La calibración G0 v1.2.0 usa Platt sobre `logit(raw_score)`, igual que el bundle; sin recomendación revisada devuelve `NO_CONCLUYENTE/CATALOG_UNAVAILABLE`.

Se probó importación inválida, evidencia G2 faltante, repetición, fallo de auditoría, actualización atómica y dry-run. Una comprobación con el **bundle y acta privados reales** en SQLite temporal devolvió `DRY_RUN`, `policies=0`, `audit=0`. La carrera real en PostgreSQL temporal (`bash scripts/check_policy_concurrency_pg.sh`) pasó tanto para activación como retiro mientras un diagnóstico finalizaba. El diagnóstico quedó `COMPLETADO` con política anterior, confianza, catálogo y un único inbox/outbox; el cambio posterior no reescribió el histórico. Se ejecutó `test_operational_rollback_rehearsal.py` con releases de prueba: rollback a versión previa conserva snapshots y auditoría; sin previa, la publicación falla cerrada y no se habilita simulación. Son fixtures de software, no orientación agronómica ni activación real.

## Preflight del lote G1/G2

Comando ejecutado con entorno Python 3.12 aislado y directorios privados:

```bash
python scripts/check_ml_real_acceptance.py --release-bundle .local/ml-pilot-v1.2/g2-bundle-v1/model-bundle.json --g2-approval .local/ml-pilot-v1.2/g2-bundle-v1/g2-approval.json --policy-file .local/ml-pilot-v1.2/policy-draft-v1.json --g1-directory .local/pv-g1/pilot-v1.2 --output-report .local/ml-pilot-v1.2/g3-preflight-v1.json
```

Reporte privado SHA-256 `0eb90de847d28b4d9a2dca417eb4e5da9b72f036d54a36cabaa60d0cba330d9e`: `PREREQUISITES_VERIFIED_G3_PENDING`, `g3_status=NOT_APPROVED`, `catalog_review=NOT_VERIFIED`, `policy_activation=NOT_PERFORMED`, `full_flow_result=NOT_EXECUTED`, `test_reopened=false`. Incluye hashes de manifiestos TRAIN/VAL/TEST, reporte G1, sello TEST, bundle, acta, política y reporte TEST G2. El comando carga el bundle, pero no lee fotos TEST ni calcula nuevas métricas. Pruebas negativas rechazan fixture, bundle alterado y manifiesto alterado; la escritura de reporte es atómica de creación única, con limpieza del directorio temporal y sin argumentos secretos persistidos.

Comandos de pruebas ejecutados:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace -e PYTHONPATH=/workspace/services/diagnosis/.venv/lib/python3.12/site-packages:/workspace/services/diagnosis:/workspace/ml/.venv/lib/python3.12/site-packages:/workspace/ml/src:/workspace/scripts python:3.12-slim python -m unittest services.diagnosis.tests.test_policy_cli services.diagnosis.tests.test_publication_policy_engine services.diagnosis.tests.test_publication_policy_migration services.diagnosis.tests.test_operational_rollback_rehearsal tests.ml.test_real_acceptance_cli
bash scripts/check_policy_concurrency_pg.sh
```

Resultados: **38 pruebas** de CLI, motor, migración, rollback y preflight; **2 carreras PostgreSQL**; todas pasan. El script PostgreSQL crea y destruye su propia red y base, sin tocar los contenedores del proyecto.

## Pendiente para G3

- **7.5:** fuentes y contenido de orientación para ambos tizones, revisión humana identificada, versión y aprobación publicadas en catálogo. No se han inventado dosis, tratamientos ni recomendaciones.
- **9.1:** entorno de aceptación aislado con política y catálogo revisado, carga real de hoja de papa identificada, rechazo de entradas fuera del piloto, abstención/predicción, historial y 404 ajeno. La política real continúa inactiva.
- **9.2:** pruebas de restart, heartbeat, lease obsoleto y redelivery con runtime real; medir p95 de flujo completo y RAM bajo carga definida.
- **9.3:** CI completo local y ejecución remota identificada de la revisión publicada.
- **9.4:** matriz G0–G3, revisión de evidencia integrada, sincronización OpenSpec y archivo solo tras aprobación G3.

EXTERNAL de Ayacucho sigue no disponible. Ningún fixture acredita rendimiento agronómico o sustituye 7.5/G3.
