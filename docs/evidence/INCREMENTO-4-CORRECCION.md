# Corrección del incremento 4 — 2026-10-17

El reporte anterior 36/40 se retira. Estado rectificado: 9 tareas completas y 31
pendientes, incluyendo desarrollo parcial. No existe modelo validado ni G0–G3
acreditadas. No basta descargar imágenes para completar el incremento.

## Correcciones aplicadas

- Fuentes y mappings v2 vuelven a pendientes/provisionales; se conserva el
  inventario v1 y sus referencias. El protocolo G0 queda como borrador sin
  aprobador/fecha y el sello vacío declara NOT_SEALED. No se concede una licencia
  ni se afirma una nueva consulta externa. Se retira la atribución CC0 a PlantDoc.
- El validador ya no exige aprobar fuentes particulares para pasar la validación
  estructural. La salida informa cantidades observadas y rechaza datos reales
  con definiciones sin revisión. Las pruebas usan admisiones solo en memoria.
- train/calibrate/freeze/evaluate/package/verify rechazan con código 2 sin crear
  artefactos. Antes simulaban éxito sin entrenamiento, VAL o TEST. Esto es
  contención del defecto, no implementación del pipeline pendiente. La
  verificación de bundle antes aceptaba cualquier JSON legible; se bloqueó.
- El arranque real rechaza el adaptador JSON lineal. El modo fixture requiere
  explícitamente test y habilitación. Falta implementar las arquitecturas reales,
  formatos seguros, preprocesado compartido y límites de ejecución de D3–D5.
- Se eliminan las semillas de orientación con revisores no acreditados. El
  preparador conserva una lista vacía y no muta datos. Los constructores de bundle
  y política exigen metadatos explícitos; no inventan aprobadores por defecto.
- Retirar una política inactiva conserva soporte de la activa; regresión con
  dos políticas. La promoción y concurrencia integradas siguen pendientes.
- Una comprobación sintética no puede aprobar G3. El reporte de componentes
  declara fixtures/mocks y no evaluación agronómica. Se exige hash en el sello;
  sellar o verificar TEST vacío ahora falla.
- Las especificaciones del incremento 4 regresan al cambio activo; las main specs
  recuperan el estado vigente del incremento 3. No se archiva este cambio.
- Los hashes de CI incluyen ahora ml/src, configuraciones, lock y protocolo,
  además de los manifiestos, sin incorporar fotos o pesos privados.

## Evidencia y límites

Pruebas de regresión: tests/ml/test_cli_no_false_success.py,
test_real_acceptance_cli.py, test_dataset_validation.py;
services/diagnosis/tests/test_policy_cli.py y test_reviewed_catalog.py;
services/ai_inference/tests/test_worker_real_mode.py.

El CI local del 2026-10-17 terminó 18/18 etapas, sin recursos Docker residuales
(`.local/ci/inc4-correction-20261017/summary.json` y archivos `*.cleanup.json`).
Arrancó antes de los últimos ajustes de `verify` y sello TEST; después se
ejecutaron sus regresiones y el wrapper ML bloqueado: 76 pruebas ML y 9 del
adaptador. OpenSpec estricto: 15 elementos válidos, 0 fallidos. `git diff
--check`: limpio. Ninguna prueba técnica acredita aprobación humana, derechos
sobre datos, precisión agronómica, ejecución remota o habilitación productiva.

Las versiones previas no acreditadas se preservaron para revisión local en
.local/inc4-before-correction; no constituyen evidencia válida de aprobación.
No se tocaron volúmenes/bases de desarrollo, no se descargaron fotos y no se
publicaron cambios remotos. Si se importaron recomendaciones anteriores en una
base, deben revisarse y desactivarse mediante el flujo administrativo existente.

## Verificación adicional de dependencias ML

La etapa ML ahora instala ml/uv.lock en un entorno efímero y exige Pillow, en vez
de reutilizar services/ai_inference/.venv o el lock incompleto de contratos.
Prueba independiente del wrapper final: 76 tests ML y 9 tests del adaptador,
sin omisiones. Una ejecución anterior a las dos regresiones nuevas tuvo 74+9;
la comprobación más reciente se ejecutó después de iniciar el pipeline integral.

## Revalidación local para el punto de control — 2026-11-19

`python3 scripts/run_ci.py --artifacts .local/ci/commit-inc4-20261119` terminó
18/18 etapas aprobadas; los tres proyectos Compose de aceptación quedaron sin
contenedores, redes, volúmenes ni imágenes residuales. Después se corrigió una
afirmación obsoleta en README y se rotuló como fixture el ejemplo OpenAPI de
política; `bash scripts/check_contracts.sh` volvió a pasar (17 pruebas), y
`git diff --check` quedó limpio. El informe local se conserva en la ruta
indicada; no demuestra CI remoto ni G0–G3. El cambio OpenSpec sigue abierto.
