# Incremento 4 — EVALUACION-G2

Actualización vigente del 2026-11-19: existen [entrenamiento y métricas reales de VAL](INCREMENTO-4-ENTRENAMIENTO-VAL-PILOTO.md), congelamiento previo, [una evaluación real del TEST sellado](INCREMENTO-4-TEST-PILOTO-V1.2.md) y [bundle aprobado G2](INCREMENTO-4-APROBACION-G2-PILOTO.md) tras carga independiente. Ambos tizones cumplen los criterios numéricos G0. EXTERNAL no existe; worker, política de publicación y G3 siguen pendientes. El texto inferior conserva el estado histórico de la corrección anterior.

Estado rectificado: 2026-10-15.

G2 PENDIENTE. No existe release real evaluado/aprobado. Las funciones matemáticas y tests de fixtures no completan congelamiento, evaluación ni aprobación. CLI train/calibrate/freeze/evaluate/package devuelve código 2 sin crear artefactos de éxito hasta completar el pipeline real. No basta descargar imágenes.

La declaración anterior de 36/40 tareas completadas queda retirada. El estado verificable se mantiene en [tasks.md](../../openspec/changes/incremento-4-datos-y-modelo-validado/tasks.md). No archivar el cambio ni publicar capacidades ML como validadas.

## Resultados medidos

El texto de este párrafo corresponde al 2026-10-15: en esa fecha no existían reportes TEST/EXTERNAL ni medición del flujo completo. Los umbrales del [protocolo G0 v1.2.0](../../ml/evaluation/protocol-g0.v1.2.0.json) fueron metas aprobadas antes del entrenamiento. El reporte TEST actual conserva hash de manifiesto y artefacto, numeradores, denominadores, matriz, abstenciones, CPU, comando y fecha. EXTERNAL y el p95 del flujo completo siguen sin medición; G2 se cerró posteriormente con 5.5 para el alcance restringido.

El motor técnico corrigió el caso de predicción candidata correcta publicada como `NO_CONCLUYENTE`: el resultado visible cuenta como abstención y falso negativo para recall de su clase. Sus pruebas con fixtures cubren ese caso y los denominadores cero. La [tarea 5.3](../../openspec/changes/incremento-4-datos-y-modelo-validado/tasks.md) quedó cerrada con el reporte real TEST; en este lote no hubo abstenciones de casos positivos.
