# Operación ML — demostración sin diagnóstico real

Estado terminal 2026-11-23: el ciclo v1.4.3 completó una evaluación EXTERNAL
independiente, pero falló cinco de seis criterios. El
[acta de cierre](../evidence/INCREMENTO-4-CIERRE-V1.4.3.md) registra G2
`CLOSED_REJECTED_EXTERNAL`, G3 `CLOSED_NOT_PROMOTED_G2_REJECTED` y modelo no
aprobado para producción. `ml-real` permanece apagado y bloqueado por
`REAL_INFERENCE_AUTHORIZED=false`; no se importa ni activa una política. No hay
fallback al simulador.

Para una demostración del flujo asíncrono sin fingir un diagnóstico, usar:

```bash
docker compose --env-file .env.example --profile demo up -d ai_inference-worker-demo
```

Ese worker no monta un modelo, no inspecciona la imagen y siempre emite
`ABSTENTION/UNSUPPORTED_CLASS`; Diagnosis termina en `NO_CONCLUYENTE`. Detenerlo
con `docker compose --profile demo stop ai_inference-worker-demo`. No arrancar
simultáneamente `async-test` ni `ml-real`.

El CLI de políticas permite dry-run/importación/activación/retiro auditados, pero las referencias textuales no son prueba de revisión humana. No importar políticas para fixtures en bases reales. Retirar una política histórica inactiva conserva el soporte de la activa. Las pruebas usan bases aisladas; esta corrección no ha modificado datos reales.

El catálogo conserva una guía revisada histórica, pero su
[`status`](../catalog/pilot-potato-guidance.v1.status.json) la declara no
publicable para v1.4.3 y sin clases productivas soportadas. No se importó para
este ciclo. Cualquier contenido que exista en una base de desarrollo debe
permanecer inactivo o retirarse mediante el flujo administrativo auditado.

La aceptación con mocks es solo técnica. No utilizarla para G3 ni citar sus tiempos como latencia del flujo real. Ningún bundle del ciclo vigente se importó como política activa y la promoción operativa quedó cancelada por el rechazo EXTERNAL.

## G0–G3, política y rollback

Los comandos de esta sección documentan el piloto histórico y su capacidad de
retiro. **No deben ejecutarse para activar v1.4.3.** El estado terminal vigente
está en `ml/evaluation/cycle-closure.v1.4.3.json` y la política en
`ml/evaluation/publication-status.v1.4.3.json`.

G0: leer [`protocol-g0.v1.2.0.json`](../../ml/evaluation/protocol-g0.v1.2.0.json) y la [ficha de aprobación](../evidence/INCREMENTO-4-FICHA-G0.md). G1: ejecutar `PYTHONPATH=ml/src python3 scripts/verify_plantvillage_pilot_g1.py .local/pv-g1/pilot-v1.2 .local/pv-g1/batch-v1`, conservar `g1-report.json` y `test-seal.json`. G2: ejecutar `python scripts/verify_pilot_g2_bundle.py --bundle .local/ml-pilot-v1.2/g2-bundle-v1/model-bundle.json --expected-sha256 93e2e65130a9c266be4bdba0262d1c98e30d0604f4d21466effba2d9c9ff0b41 --require-approval-record`; el acta G2 debe conservar SHA-256 `579404dfe711fcae00c5d8964db669b8a66477f853d48a1fed45f72946d165f9`.

El comando `python scripts/check_ml_real_acceptance.py --release-bundle <bundle-G2> --g2-approval <acta-G2> --policy-file <política-privada> --g1-directory <directorio-G1> --output-report <reporte-nuevo>` comprueba requisitos G3 y registra hashes, manifiestos, sello y comando sin secretos. Rechaza fixtures, G1/G2 alterados y rutas simbólicas. **No ejecuta la aceptación E2E ni aprueba G3**; el reporte deja `full_flow_result=NOT_EXECUTED`. La ejecución E2E de v1.2.0 se documenta [por separado](../evidence/INCREMENTO-4-G3-ACEPTACION-LOCAL.md) y falló en papa sana.

El procedimiento histórico preparaba una política privada desde el bundle aprobado mediante `python scripts/prepare_pilot_publication_policy.py --release-bundle <bundle-G2> --g2-approval <acta-G2> --actor <operador> --output <política-privada>`. Su importación y activación se ensayaron solo en una base efímera ya eliminada. **No ejecutar esos pasos con v1.4.3:** G3 terminó no promovido. La CLI y su auditoría se conservan para futuros ciclos aprobados; una clase sin orientación revisada sigue terminando en `NO_CONCLUYENTE/CATALOG_UNAVAILABLE`.

Para retiro: detener nuevos reclamos de `ml-real`, esperar o recuperar leases y ejecutar primero `python -m app.policy retire --policy-id <uuid> --actor <operador> --reason <motivo>` en dry-run; repetir con `--apply` para retirar. Si existe una versión previa **aprobada**, restaurar exactamente su bundle y ejecutar `activate` con su ID tras comprobar hashes, contrato y catálogo. Si no existe, mantener el consumidor real detenido y sin política activa; el sistema falla cerrado, sin reactivar la simulación. No reescribir diagnósticos terminales, snapshots de política/confianza, recomendaciones ni auditoría, ni hacer downgrade destructivo. El ensayo reproducible de versiones de prueba y concurrencia está en [evidencia](../evidence/INCREMENTO-4-POLITICA-Y-PREFLIGHT-G3.md).

## Preflight del worker CPU, sin consumir mensajes

El paquete privado está en `.local/ml-pilot-v1.2/g2-bundle-v1/` y no forma parte de Git. **Conservar una copia privada íntegra** de todos sus archivos y del acta; en un checkout nuevo faltará hasta que se restaure. El SHA-256 aprobado del manifiesto es `93e2e65130a9c266be4bdba0262d1c98e30d0604f4d21466effba2d9c9ff0b41` y el del acta es `579404dfe711fcae00c5d8964db669b8a66477f853d48a1fed45f72946d165f9`. El perfil monta ese directorio de solo lectura y desactiva la creación automática de la ruta ausente. Un SHA distinto, archivo faltante o acta alterada impide iniciar el consumidor.

Desde un checkout sin `.env`, validar la configuración con `docker compose --env-file .env.example --profile ml-real config`; el worker real no publica puertos, y el perfil `async-test` no queda incluido. Construir sin iniciar: `docker compose --env-file .env.example --profile ml-real build ai_inference-worker-real`. Para el chequeo sintético aislado, ejecutar `scripts/check_pilot_worker_runtime.py` con `APP_ENV=local`, `INFERENCE_MODE=real`, `MODEL_BUNDLE_PATH`, `MODEL_BUNDLE_SHA256` y `MODEL_APPROVAL_SHA256` fijados; la prueba no usa TEST ni atiende colas.

Una futura activación requeriría otro ciclo aprobado y una autorización explícita distinta; v1.4.3 no puede promoverse. El comando histórico `docker compose --profile ml-real up -d ai_inference-worker-real` debe fallar mientras `REAL_INFERENCE_AUTHORIZED=false`. Si en otro ciclo faltara el artefacto o fallara el SHA, se debe revisar la ruta privada y el acta, **sin cambiar el hash para hacer pasar el arranque**.
