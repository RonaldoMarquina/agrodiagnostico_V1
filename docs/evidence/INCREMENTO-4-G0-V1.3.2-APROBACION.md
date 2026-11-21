# G0 v1.3.2 — criterios de rechazo sano aprobados antes de entrenar

Fecha: **2026-11-21** (America/Lima). El responsable del proyecto aprobó expresamente G0 v1.3.2 con la distribución real de papa sana y dos límites TEST por conteo. [Protocolo aprobado](../../ml/evaluation/protocol-g0.v1.3.2.json), SHA-256 `533a8daddba598d810cf6e46cb072a41c54ae5478bfd9ed131b39eb703bfb397`. La decisión precede al entrenamiento v1.3.x y a toda evaluación del TEST nuevo. Es una **meta**, no un resultado medido.

| Papa sana | Fotos originales mínimas | Grupos `leaf_id` independientes mínimos |
| --- | ---: | ---: |
| TRAIN | 80 | 20 |
| VAL | 28 | 7 |
| TEST nuevo sellado | 32 | 8 |
| Total | 140 | 35 |

La distribución se fijó a partir del [lote G1 v1.3.1 admitido](INCREMENTO-4-G1-V1.3.1-ADMISION.md), con hoja verificable, exclusión de grupos expuestos y separación entre particiones. El G1 existente tiene exactamente esos conteos; no se reabre, reparte de nuevo ni vuelve a sellar. Su reporte privado SHA-256 es `71c4e34c60eb1b635da58af934b05fd1683728f895e955d8027f7652e91c7a75` y el sello TEST SHA-256 es `4f0872f62b58b35df908de8dae3f0577dc425f871e0e74e7fbf26a1afe9489bc`.

## Criterios TEST nuevos de papa sana

- **Publicación errónea ≤3/32:** numerador = fotos sanas selladas cuyo resultado **visible final** publica `POTATO_EARLY_BLIGHT` o `POTATO_LATE_BLIGHT`; denominador = las **32** fotos sanas selladas. Corresponde a una tasa máxima de **0,09375**.
- **`NO_CONCLUYENTE` ≥29/32:** numerador = fotos sanas selladas cuyo estado visible final es exactamente `NO_CONCLUYENTE`; denominador = las mismas **32** fotos. Corresponde a una tasa mínima de **0,90625**. Un resultado `FALLIDO` u otra salida sin tizón no satisface este mínimo.
- Las **32 respuestas** deben estar disponibles en una única evaluación posterior al congelamiento del bundle y umbral con VAL. Una exclusión posterior al sello o un resultado ausente impide acreditar estos criterios; no se ajusta el denominador para obtener una tasa favorable. Publicar también resultados por las ocho hojas, además de por foto.

Para `OTHER_CROP` siguen FPR ≤0,05 y rechazo sin diagnóstico visible de tizón ≥0,95; el límite general de aceptación errónea ≤0,10 también sigue vigente. Los dos tizones conservan F1, recall, cobertura y error selectivo anteriores; calibración, CPU y latencia de flujo completo no cambian. El umbral se elige con VAL antes de TEST. Si una foto sana recibe `NO_CONCLUYENTE`, no es un acierto de clase de enfermedad ni un diagnóstico de sanidad. Solo los dos tizones son publicables.

**Límite de inferencia:** las 32 fotos de TEST proceden de solo ocho hojas, con varias vistas relacionadas por hoja y de la misma distribución PlantVillage. Cumplir 29/32 no demostraría generalización a campo; EXTERNAL sigue no disponible. G2 y G3 permanecen abiertos, el bundle v1.2.0 y sus resultados históricos intactos.

Verificación reproducible, sin inferencia ni lectura del TEST para elegir un modelo:

```bash
python3 scripts/verify_g0_v1_3_2.py ml/evaluation/protocol-g0.v1.3.2.json ml/evaluation/protocol-g0.v1.3.1.json .local/pv-g1/g1-v1.3.1-admitted .local/pv-g1/pilot-v1.2
```

Resultado local: `G0_V1_3_2_APPROVED_G1_REUSED`, 2.391 fotos/606 grupos. El verificador comprueba que mínimos, estratos, otros umbrales y presupuesto CPU no se alteraron; vuelve a verificar bytes, permisos, grupos y sello del G1 privado bajo su protocolo original. El [estado de puertas v1.3.2](../../ml/evaluation/gate-status.v1.3.2.json) conserva esa relación sin modificar la evidencia histórica.
