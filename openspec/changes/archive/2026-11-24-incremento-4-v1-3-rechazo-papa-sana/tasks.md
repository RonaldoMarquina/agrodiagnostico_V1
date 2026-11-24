# Tasks — ciclo v1.3.2 (v1.3.0 y v1.3.1 históricos)

Estado al 2026-11-22: **11/21; G0 v1.3.2 aprobado, G1 v1.3.1 cerrado y TEST único evaluado con fallo de rechazo sano**. Las aprobaciones G0/G1/G2 v1.2.0 son históricas. El TEST conocido v1.2.0 y los cuatro controles sanos G3 solo justificaron este ciclo; sus tres grupos de hoja quedaron excluidos. El [expediente TRAIN/VAL](../../../docs/evidence/INCREMENTO-4-TRAIN-VAL-V1.3.2.md) acredita 4.1–4.3. El [TEST v1.3.2 único](../../../docs/evidence/INCREMENTO-4-TEST-V1.3.2-UNICO.md) registró **8/32** falsas publicaciones sanas y **24/32** `NO_CONCLUYENTE`, frente a ≤3/32 y ≥29/32: G2/G3 permanecen abiertos. No reutilizar este TEST para seleccionar arquitectura, umbral, pesos o política.

## 1. G0 — protocolo aprobado

- [x] 1.1 Obtener aprobación explícita del responsable para G0 v1.3.0, incluidos mínimos por estrato, rechazo por estrato y presupuesto CPU; registrar fecha, versión y justificación antes de entrenar. Verificados [protocolo completo](../../../ml/evaluation/protocol-g0.v1.3.0.json) y [acta de decisión](../../../docs/evidence/INCREMENTO-4-G0-V1.3-APROBACION.md); G1 y resultados siguen abiertos.
- [ ] 1.2 Actualizar taxonomía y ADR para dos tizones publicables, `POTATO_HEALTHY` técnico y `OTHER_CROP` técnico; comprobar que ninguna pantalla o contrato trate papa sana como diagnóstico confirmado y que el catálogo no recomiende para ella.
- [x] 1.3 Obtener aprobación explícita de la [tabla G0 v1.3.1](../../../docs/evidence/INCREMENTO-4-G0-V1.3.1-APROBACION.md) antes de admitir definitivamente el lote reducido, entrenar o sellar TEST; conservar v1.3.0 y v1.2.0 históricos y registrar la pérdida de diversidad independiente.
- [x] 1.4 Versionar y aprobar G0 v1.3.2 antes de entrenar: conservar mínimos sanos 80/20, 28/7 y 32/8, fijar TEST sano en máximo 3/32 diagnósticos visibles de tizón y mínimo 29/32 `NO_CONCLUYENTE`, mantener FPR ≤0,05 y rechazo ≥0,95 para `OTHER_CROP` y todos los demás límites. [Acta, protocolo y revalidación G1](../../../docs/evidence/INCREMENTO-4-G0-V1.3.2-APROBACION.md) con hashes; no medir TEST ni presentar metas como resultados.

## 2. G1 — imágenes y particiones nuevas

- [x] 2.1 Auditar por SHA-256, ruta, licencia, etiqueta, calidad y `leaf_id` las fotos sanas de la revisión fijada; aplicar la [lista de exclusión de los tres grupos expuestos](../../../ml/manifests/g1-v1.3-exposure-blocklist.json) a todas las particiones y registrar admitidas, excluidas y pendientes. [Auditoría](../../../docs/evidence/INCREMENTO-4-G1-V1.3-INVENTARIO-2026-11-21.md) y [admisión por archivo](../../../docs/evidence/INCREMENTO-4-G1-V1.3.1-ADMISION.md) separan procedencia experta y control interno de una revisión agronómica independiente.
- [x] 2.2 Conseguir y admitir las fotos/grupos de papa sana para TRAIN/VAL según [G0 v1.3.1 aprobado](../../../docs/evidence/INCREMENTO-4-G0-V1.3.1-APROBACION.md): 80/20 y 28/7. [Verificador independiente](../../../scripts/verify_g1_v1_3_1.py) confirma grupos y pares visuales resueltos por exclusión.
- [x] 2.3 Conseguir y admitir un TEST independiente nuevo de ambos tizones y negativos `OTHER_CROP`: 80/20 cada uno desde `color_test.txt` oficial. [Expediente G1](../../../docs/evidence/INCREMENTO-4-G1-V1.3.1-ADMISION.md) registra derechos, etiquetas, grupos, SHA-256 y exclusión del TEST v1.2.0 abierto.
- [x] 2.4 Completar el estrato sano del TEST nuevo (32/8), sellar los cuatro estratos y cerrar G1 solo si cada uno cumple mínimos y no solapa TRAIN, VAL, controles expuestos ni TEST histórico. [Sello y verificación independiente](../../../docs/evidence/INCREMENTO-4-G1-V1.3.1-ADMISION.md), con pruebas negativas de fuga y alteración. TEST no se usó para selección.

## 3. Contratos y comportamiento técnico

- [ ] 3.1 Versionar contrato de bundle y política para cuatro objetivos técnicos con solo dos clases publicables; probar rechazo de mapas que publiquen `POTATO_HEALTHY` o `OTHER_CROP` y conservar compatibilidad de bundles v1.2.0.
- [ ] 3.2 Adaptar entrenamiento e inferencia CPU para objetivo sano, abstención `UNSUPPORTED_CLASS` y `OTHER_CROP/UNSUPPORTED_CROP`; probar predicciones sintéticas, errores y límites CPU sin presentarlas como rendimiento agronómico.
- [ ] 3.3 Integrar resultado de abstención con Diagnosis y contrato de eventos; probar propiedad, catálogo, historial y que `NO_CONCLUYENTE` no sea clase del modelo ni publicación de sana.

## 4. TRAIN/VAL y congelamiento

- [x] 4.1 Entrenar candidatos solo con TRAIN G1 v1.3.1 bajo G0 v1.3.2 y documentar semilla, hashes, arquitectura, dependencias, CPU/RAM y tiempo; verificar reproducción y registro de acceso sin TEST. [Entrenamiento y repetición bit a bit](../../../docs/evidence/INCREMENTO-4-TRAIN-VAL-V1.3.2.md): pesos, reporte y predicciones VAL con SHA idénticos; TEST sin inferencia.
- [x] 4.2 Comparar en VAL al menos dos rutas de rechazo con preprocesado/presupuesto iguales; registrar F1, recall, cobertura, error selectivo, FPR de sana y otro cultivo por separado, calibración y latencia con numeradores/denominadores. [Comparación de argmax y puerta sana](../../../docs/evidence/INCREMENTO-4-TRAIN-VAL-V1.3.2.md) bajo los mismos pesos y VAL, con latencia de decisión y CPU del modelo medidas.
- [x] 4.3 Elegir pesos, calibración y umbral solo con VAL, congelar bundle, protocolo y manifiestos antes de TEST; verificar hashes, carga independiente preliminar y rechazo de alteraciones. [Congelamiento privado y verificación](../../../docs/evidence/INCREMENTO-4-TRAIN-VAL-V1.3.2.md), SHA-256 de `freeze.json` `d07dcc40376d4d74e581553c817e4610f7bf7716cae0d6af98a3919930141eb7`. Es candidato offline, no release G2 ni bundle integrado al worker.

## 5. TEST nuevo y G2

- [x] 5.1 Ejecutar una evaluación única del TEST G1 v1.3.1 sellado contra G0 v1.3.2; publicar por clase y estrato, incluidas ≤3/32 publicaciones erróneas sanas y ≥29/32 `NO_CONCLUYENTE` como criterios, abstenciones, confusión, ECE, latencia, memoria, numeradores/denominadores y grupos. No ajustar el modelo con TEST. [Reporte único](../../../docs/evidence/INCREMENTO-4-TEST-V1.3.2-UNICO.md): las metas sanas **fallaron**; esta casilla acredita ejecutar y publicar la evaluación, no aprobar G0 TEST ni G2.
- [ ] 5.2 Verificar carga independiente y checksums del bundle; obtener revisión G2 explícita del responsable solo si se cumplen criterios, documentando EXTERNAL ausente y límites sin modificar resultados v1.2.0.

## 6. Repetición de aceptación y G3

- [ ] 6.1 Importar/activar política v1.3.2 auditada en aceptación aislada solo tras G2 y catálogo revisado; verificar `dry-run`, actor, motivo, rollback e historial inmutable.
- [ ] 6.2 Repetir 9.1 con hojas de ambos tizones, sanas, otro cultivo, autorización, estados y catálogo; verificar rechazo sano y conservar muestras/denominadores del recorrido real.
- [ ] 6.3 Repetir fallos/redelivery y mediciones de flujo completo/CPU para nuevo bundle; verificar resultado único, limpieza y diferencias frente a metas sin extrapolar a producción.
- [ ] 6.4 Ejecutar CI local y remota sobre la revisión que incorpore v1.3.2; registrar commit, URL, fecha, etapas y conclusión, incluidas limpieza y artefactos.
- [ ] 6.5 Revisar matriz G0–G3, README, Incrementos y OpenSpec con resultados reales; verificar `openspec validate --strict` y cerrar G3/9.1/9.4 del cambio anterior solo si todos los criterios pasan.
