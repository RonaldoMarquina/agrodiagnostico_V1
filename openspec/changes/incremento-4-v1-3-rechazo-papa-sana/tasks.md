# Tasks — ciclo v1.3.0

Estado al 2026-11-20: **1/19; G0 v1.3.0 cerrado, G1 abierto**. Las aprobaciones G0/G1/G2 v1.2.0 son históricas. El TEST conocido v1.2.0 y los cuatro controles sanos G3 solo justifican el nuevo ciclo. Los tres grupos de hoja de esos controles están excluidos de todas las particiones v1.3.0. No entrenar ni abrir TEST hasta cerrar G1 de esta versión.

## 1. G0 — protocolo aprobado

- [x] 1.1 Obtener aprobación explícita del responsable para G0 v1.3.0, incluidos mínimos por estrato, rechazo por estrato y presupuesto CPU; registrar fecha, versión y justificación antes de entrenar. Verificados [protocolo completo](../../../ml/evaluation/protocol-g0.v1.3.0.json) y [acta de decisión](../../../docs/evidence/INCREMENTO-4-G0-V1.3-APROBACION.md); G1 y resultados siguen abiertos.
- [ ] 1.2 Actualizar taxonomía y ADR para dos tizones publicables, `POTATO_HEALTHY` técnico y `OTHER_CROP` técnico; comprobar que ninguna pantalla o contrato trate papa sana como diagnóstico confirmado y que el catálogo no recomiende para ella.

## 2. G1 — imágenes y particiones nuevas

- [ ] 2.1 Auditar por SHA-256, ruta, licencia, etiqueta, calidad y `leaf_id` las 120 fotos sanas inventariadas; aplicar la [lista de exclusión de los tres grupos expuestos](../../../ml/manifests/g1-v1.3-exposure-blocklist.json) a todas las particiones y registrar admitidas, excluidas y pendientes. Verificar registro por archivo y procedencia experta distinguida de revisión independiente. [Preparación G1](../../../docs/evidence/INCREMENTO-4-G1-V1.3-PREPARACION.md) no acredita admisión.
- [ ] 2.2 Conseguir y admitir las fotos/grupos adicionales de papa sana para TRAIN/VAL según G0 aprobado; verificar mínimos por partición y ausencia de fuga entre grupos/pares visuales.
- [ ] 2.3 Conseguir y admitir un TEST independiente nuevo de ambos tizones y negativos `OTHER_CROP`; verificar fuente, derechos, etiquetas, grupos, SHA-256 y exclusión del TEST v1.2.0 abierto.
- [ ] 2.4 Completar el estrato sano del TEST nuevo, sellar los cuatro estratos y cerrar G1 solo si cada uno cumple mínimos y no solapa TRAIN, VAL, controles expuestos ni TEST histórico. Verificar sello y prueba negativa de alteración/fuga sin abrir TEST para selección.

## 3. Contratos y comportamiento técnico

- [ ] 3.1 Versionar contrato de bundle y política para cuatro objetivos técnicos con solo dos clases publicables; probar rechazo de mapas que publiquen `POTATO_HEALTHY` o `OTHER_CROP` y conservar compatibilidad de bundles v1.2.0.
- [ ] 3.2 Adaptar entrenamiento e inferencia CPU para objetivo sano, abstención `UNSUPPORTED_CLASS` y `OTHER_CROP/UNSUPPORTED_CROP`; probar predicciones sintéticas, errores y límites CPU sin presentarlas como rendimiento agronómico.
- [ ] 3.3 Integrar resultado de abstención con Diagnosis y contrato de eventos; probar propiedad, catálogo, historial y que `NO_CONCLUYENTE` no sea clase del modelo ni publicación de sana.

## 4. TRAIN/VAL y congelamiento

- [ ] 4.1 Entrenar candidatos solo con TRAIN G1 v1.3.0 y documentar semilla, hashes, arquitectura, dependencias, CPU/RAM y tiempo; verificar reproducción y registro de acceso sin TEST.
- [ ] 4.2 Comparar en VAL al menos dos rutas de rechazo con preprocesado/presupuesto iguales; registrar F1, recall, cobertura, error selectivo, FPR de sana y otro cultivo por separado, calibración y latencia con numeradores/denominadores.
- [ ] 4.3 Elegir pesos, calibración y umbral solo con VAL, congelar bundle, protocolo y manifiestos antes de TEST; verificar hashes, carga independiente preliminar y rechazo de alteraciones.

## 5. TEST nuevo y G2

- [ ] 5.1 Ejecutar una evaluación única del TEST v1.3.0 sellado y nuevo; publicar reporte por clase y estrato, abstenciones, confusión, ECE, latencia, memoria, numeradores/denominadores y comparación con G0 aprobado.
- [ ] 5.2 Verificar carga independiente y checksums del bundle; obtener revisión G2 explícita del responsable solo si se cumplen criterios, documentando EXTERNAL ausente y límites sin modificar resultados v1.2.0.

## 6. Repetición de aceptación y G3

- [ ] 6.1 Importar/activar política v1.3.0 auditada en aceptación aislada solo tras G2 y catálogo revisado; verificar `dry-run`, actor, motivo, rollback e historial inmutable.
- [ ] 6.2 Repetir 9.1 con hojas de ambos tizones, sanas, otro cultivo, autorización, estados y catálogo; verificar rechazo sano y conservar muestras/denominadores del recorrido real.
- [ ] 6.3 Repetir fallos/redelivery y mediciones de flujo completo/CPU para nuevo bundle; verificar resultado único, limpieza y diferencias frente a metas sin extrapolar a producción.
- [ ] 6.4 Ejecutar CI local y remota sobre la revisión que incorpore v1.3.0; registrar commit, URL, fecha, etapas y conclusión, incluidas limpieza y artefactos.
- [ ] 6.5 Revisar matriz G0–G3, README, Incrementos y OpenSpec con resultados reales; verificar `openspec validate --strict` y cerrar G3/9.1/9.4 del cambio anterior solo si todos los criterios pasan.
