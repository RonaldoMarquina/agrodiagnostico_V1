# TEST sellado v1.3.2 — evaluación única e incumplimiento de rechazo sano

Fecha: **2026-11-22** (America/Lima). Estado: **G0 TEST incumplido; G2 y G3 abiertos**. El candidato quedó fijado antes de TEST en el commit local `94b3d422afe4008226a70623b96824ba003cf139` y en el [registro de congelamiento](../../ml/evaluation/freeze-record.v1.3.2.json), SHA-256 `d07dcc40376d4d74e581553c817e4610f7bf7716cae0d6af98a3919930141eb7`. Se ejecutó una sola vez el [evaluador preinscrito](../../scripts/evaluate_v13_sealed_test.py) con `ARGMAX_CONFIDENCE`, temperatura **1,25**, umbral **0,90**, pesos y preprocesado congelados. No hubo cambio de pesos, mapa, calibración ni configuración después de mirar TEST. El sello G1 conservó SHA-256 `4f0872f62b58b35df908de8dae3f0577dc425f871e0e74e7fbf26a1afe9489bc`.

## Trazabilidad de la única ejecución

El preflight anterior al commit examinó solo manifiesto y sello, sin inferir imágenes TEST. Después del commit se creó `.local/ml-v1.3.2/test-access-v1.3.2.json` con `STARTED_ONCE` **antes** de leer imágenes de TEST. Su SHA-256 es `84b187d60d9bec1cf41b56eedb89434995a28e9f198a44249722017559cc978a`. La ejecución evaluó las 272 fotos selladas de 68 grupos, verificó G1 completo y terminó con `test_evaluations=1` y `G0_TEST_FAILED_G2_OPEN`. Una repetición con este candidato queda bloqueada por la marca de acceso; el TEST ya no es independiente para elegir cambios.

| Archivo privado | SHA-256 |
| --- | --- |
| `.local/ml-v1.3.2/test-v1.3.2-once/test-report.json` | `7f0b829275d689b5beec0f6c9e2b471d53653881dc57fb52cce12ebc2aa11d41` |
| `.local/ml-v1.3.2/test-v1.3.2-once/test-predictions.jsonl` | `45df0b5db672a2be08beafc728caa1e7a4e844619cc041cd0f14f48cdf55f4c1` |
| `.local/ml-v1.3.2/test-v1.3.2-once/test-completion.json` | `9a01cfc295f163fb09ddf14c4e66d83831a12ec406f76a06f22b6738cc4f2902` |
| Pesos congelados | `a55fbcbfcfc6234b6c03b20c996440768fc4b7a897631a67a96c45c0e159e361` |

El reporte privado vincula el commit previo, código evaluador, protocolo, configuración, calibración, umbral, mapa de clases, informe G1, manifiesto, evidencia por imagen y sello mediante SHA-256. Las salidas por foto y por `leaf_id` quedan en el paquete privado; no se suben fotografías ni bytes de terceros.

## Métricas por estrato y puertas G0

| Estrato y métrica | Resultado TEST | Criterio G0 v1.3.2 | Decisión |
| --- | ---: | ---: | --- |
| Tizón temprano: recall visible | **79/80 = 0,9875** | ≥0,80 | Cumple |
| Tizón tardío: recall visible | **67/80 = 0,8375** | ≥0,80 | Cumple |
| F1 de tizón temprano | **158/163 = 0,9693** | ≥0,70 por clase | Cumple |
| F1 de tizón tardío | **134/154 = 0,8701** | ≥0,70 por clase | Cumple |
| F1 macro de los dos tizones | **0,9197** | ≥0,85 | Cumple |
| Cobertura de tizones | **148/160 = 0,9250** | ≥0,70 | Cumple |
| Error selectivo entre tizones publicados | **2/148 = 0,0135** | ≤0,10 | Cumple |
| Papa sana publicada como tizón | **8/32 = 0,2500** | **≤3/32** | **Falla** |
| Papa sana `NO_CONCLUYENTE` | **24/32 = 0,7500** | **≥29/32** | **Falla** |
| Otro cultivo publicado como tizón | **1/80 = 0,0125** | ≤0,05 | Cumple |
| Otro cultivo rechazado | **79/80 = 0,9875** | ≥0,95 | Cumple |
| ECE técnico en fotos de papa | **0,0442** | ≤0,15 | Cumple |

La aceptación errónea general por estrato negativo también falla para papa sana (**8/32 >0,10**) y cumple para otro cultivo (**1/80 ≤0,10**). El error selectivo definido en G0 usa solo fotos de los **dos tizones** en numerador y denominador; las ocho falsas publicaciones sanas se cuentan en su estrato negativo, no se esconden ni se duplican en esa tasa. El F1 visible sí incorpora como falsos positivos de enfermedad las publicaciones hechas sobre negativos. Brier técnico de papa: suma **28,2271** sobre **192** fotos, media **0,1470**.

### Matriz de confusión visible, con abstenciones

| Verdad (fotos / grupos) | Publica temprano | Publica tardío | `NO_CONCLUYENTE` |
| --- | ---: | ---: | ---: |
| Tizón temprano (80 / 20) | **79** | 0 | 1 |
| Tizón tardío (80 / 20) | 2 | **67** | 11 |
| Papa sana (32 / 8) | 1 | 7 | 24 |
| Otro cultivo (80 / 20) | 1 | 0 | 79 |

Las **12 abstenciones positivas** (1 temprano y 11 tardío) son falsos negativos para recall y permanecen en el denominador de cobertura. Ocho de ellas tenían argmax técnico correcto, pero no superaron la política visible. Cuatro de las ocho hojas sanas tuvieron al menos una falsa publicación; sus conteos por hoja fueron **3, 2, 2 y 1** fotos. Las otras cuatro hojas sanas tuvieron cuatro abstenciones cada una. Esto muestra dependencia entre vistas de una hoja y limita generalización; no se trata a las 32 fotos como 32 grupos independientes.

## CPU y límites

En las **272** imágenes TEST, la latencia de decodificación, preprocesado, modelo y decisión en CPU tuvo mediana **5,179 ms**, p95 **6,264 ms** y máximo **10,877 ms**. RSS máximo **350,625 MB**. Todos pasan el presupuesto de inferencia G0 (mediana ≤1.000 ms, p95 ≤2.500 ms, máximo ≤4.000 ms, RSS ≤1.024 MB). No es latencia HTTP → cola → Diagnosis; esa medición continúa pendiente. EXTERNAL no está disponible para este piloto y el resultado no acredita fotografías de campo de Ayacucho.

## Decisión

**No promover este candidato a G2, no integrarlo ni activar el worker real.** La falla de papa sana impide la revisión G2 aprobatoria pese a que F1, recall, cobertura, otro cultivo y CPU cumplen. Conservar el bundle y este TEST como evidencia histórica. Cualquier mejora futura requiere un nuevo ciclo con decisiones fijadas antes de entrenar y un TEST independiente nuevo; este TEST no se reutiliza para elegir pesos, umbral, arquitectura o política.
