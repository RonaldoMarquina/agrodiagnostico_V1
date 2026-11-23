# ADR 0012: `OTHER_CROP` como cuarta clase técnica en v1.4.1

- Fecha: 2026-11-23
- Estado: aceptado por el responsable del proyecto
- Protocolo: G0 v1.4.1

## Contexto

La comparación v1.4.0 seleccionada solo con VAL no produjo un candidato elegible. El líder publicó un tizón en 83/150 controles `OTHER_CROP`, frente al máximo de 7/150. Sikkim continuó sellado y los TEST históricos no participaron.

## Decisión

`OTHER_CROP` pasa a ser la cuarta salida técnica de MobileNetV3-Small, junto con tizón temprano, tizón tardío y papa sana. TRAIN incorpora sus 503 imágenes en 127 grupos y VAL conserva 150/38. El sampler elige por clase, `leaf_id` e imagen: 80 exposiciones por cada clase y 320 por época. Solo ambos tizones son publicables; un argmax `POTATO_HEALTHY` o `OTHER_CROP`, o una confianza inferior al umbral VAL, produce `NO_CONCLUYENTE`.

Pesos, calibración y umbral se seleccionan exclusivamente con TRAIN/VAL. Los pesos y predicciones v1.4.0 son evidencia histórica, no inicialización ni datos de selección. Los 68 grupos TEST históricos permanecen bloqueados. El manifiesto Sikkim conserva los hashes v1.4.0 y no puede abrirse antes de un congelamiento completo y revisión explícita.

## Consecuencias

La salida técnica no amplía el catálogo ni el alcance visible. Contratos y validadores deben probar cuatro logits pero exactamente dos diagnósticos publicables. G2 sigue abierto hasta superar VAL, congelar de forma verificable y, en otro paso autorizado, evaluar EXTERNAL una sola vez.
