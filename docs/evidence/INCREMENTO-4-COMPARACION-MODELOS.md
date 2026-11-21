# Incremento 4 — COMPARACION-MODELOS

Actualización vigente del 2026-11-19: [comparación real en VAL](INCREMENTO-4-ENTRENAMIENTO-VAL-PILOTO.md) de MobileNetV3-Small y ResNet18 con los mismos TRAIN/VAL, preprocesado y presupuesto CPU. MobileNetV3 fue elegido y congelado antes de [TEST único](INCREMENTO-4-TEST-PILOTO-V1.2.md); su [bundle G2](INCREMENTO-4-APROBACION-G2-PILOTO.md) quedó aprobado para el piloto restringido. EXTERNAL no está disponible. La comparación histórica con fixtures descrita debajo no decidió G2.

Estado rectificado: 2026-10-15.

Comparación real PENDIENTE. Los clasificadores lineales históricos son fixtures. Desde 2026-11-19 hay un [smoke CPU con MobileNetV3-Small y ResNet18 jerárquica](INCREMENTO-4-CPU-SMOKE.md), pero solo compara patrones geométricos en `VAL_FIXTURE`: el conjunto acertó 1/7 etiquetas positivas y no rechazó el negativo; la alternativa acertó 7/7 y rechazó 1/1 negativo. La selección técnica de umbral usa esa misma VAL_FIXTURE; esos ocho patrones no son una prueba independiente. No existe comparación experimental válida sobre TRAIN/VAL autorizados ni selección de release. Los conteos no acreditan precisión ni rendimiento agronómico.

La declaración anterior de 36/40 tareas completadas queda retirada. El estado verificable se mantiene en [tasks.md](../../openspec/changes/incremento-4-datos-y-modelo-validado/tasks.md). No archivar el cambio ni publicar capacidades ML como validadas.
