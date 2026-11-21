# Acta de G0 v1.3.0 — aprobado por el responsable

**Fecha de decisión:** 2026-11-20 (America/Lima). **Responsable:** responsable del proyecto AgroDiagnóstico V1. **Estado:** `APPROVED_G0_DESIGN`; G1 v1.3.0 abierto, G2 sin resultados y G3 abierto. La decisión explícita del responsable en la conversación del 2026-11-20 aprueba los mínimos y límites del protocolo propuesto, el nuevo TEST independiente y el rechazo de papa sana **antes de cualquier entrenamiento v1.3.0**.

**Artefacto aprobado:** [`protocol-g0.v1.3.0.json`](../../ml/evaluation/protocol-g0.v1.3.0.json), SHA-256 `f29025940e4f1adf73b955048ec36172e8a23135f28ec20b14ccfb6dc7e0d198`. Sustituye v1.2.0 **solo para el nuevo ciclo**; no edita su bundle, TEST, reporte ni aprobación G2. Justificación: [G3 local](INCREMENTO-4-G3-ACEPTACION-LOCAL.md) publicó 4/4 controles de papa sana como tizón tardío. Esos controles motivan el nuevo diseño y quedan fuera de entrenamiento, selección de umbrales y medición v1.3.0.

## Criterios aprobados

- Entrada: foto de hoja de papa previamente identificada. **Diagnósticos publicables:** solo `POTATO_EARLY_BLIGHT` y `POTATO_LATE_BLIGHT`. `POTATO_HEALTHY` es condición técnica de rechazo: `NO_CONCLUYENTE/UNSUPPORTED_CLASS`, nunca tizón ni afirmación de sanidad. `OTHER_CROP` termina como `NO_CONCLUYENTE/UNSUPPORTED_CROP`.
- **Por cada uno de cuatro estratos** (dos tizones, papa sana y otro cultivo): TRAIN ≥150 fotos originales/50 grupos independientes; VAL ≥40/20; TEST nuevo ≥30/15. EXTERNAL, si llega a existir autorizado, ≥20/10. `leaf_id` debe ser verificable, sin `fallback_*` supuesto independiente; SHA-256 y pares visuales se revisan entre versiones.
- VAL: F1 macro ≥0,80. TEST nuevo: F1 macro ≥0,85, recall de cada tizón ≥0,80 y F1 por tizón ≥0,70. EXTERNAL: objetivo F1 macro ≥0,75 si se dispone de él.
- Cobertura ≥0,70 = diagnósticos visibles aceptados de los dos tizones ÷ todas las fotos válidas de esos tizones. Error selectivo ≤0,10 = diagnósticos visibles aceptados incorrectos ÷ todos los aceptados de esas fotos; cero aceptados no cumple. Las abstenciones positivas permanecen en el denominador de cobertura y son fallos del recall de su clase.
- Para **papa sana y otro cultivo por separado**, FPR ≤0,05 = fotos válidas del estrato con diagnóstico visible de un tizón ÷ total de fotos válidas evaluadas del mismo estrato; rechazo ≥0,95 es el complemento. El límite adicional de aceptación errónea ≤0,10 no relaja el FPR más estricto. Un denominador cero no cumple.
- Calibración ECE ≤0,15. Umbral y calibración elegidos solo en VAL, congelados antes de TEST. Reportar numeradores, denominadores, matriz de confusión, abstenciones, métricas por clase/estrato, latencia y memoria.
- CPU: mediana ≤1000 ms, p95 ≤2500 ms, límite ≤4000 ms y RSS ≤1024 MB. Objetivo de flujo completo p95 ≤30 s. Estos son **criterios**, no mediciones v1.3.0.

## Separación de puertas y estimación de datos

El cálculo previo de **190 fotos/100 grupos** era un faltante condicional de inventario que suponía reutilizar las 12 fotos de tres grupos expuestos en G3; **no es un umbral G0 ni acredita admisión**. La decisión actual prohíbe usar los cuatro controles en cualquier etapa v1.3.0. Para evitar fuga entre vistas de la misma hoja, la [lista G1 de exclusión](../../ml/manifests/g1-v1.3-exposure-blocklist.json) aparta los tres grupos completos: 12 fotos. Con esa exclusión, el [faltante operativo mínimo](INCREMENTO-4-CICLO-RECHAZO-PAPA-SANA.md) es **202 fotos originales/103 grupos** si todas las demás candidatas pasan G1. Los mínimos por partición aprobados no cambian.

G0 se cierra por definición y aprobación del protocolo. **G1** todavía exige derechos aplicables por archivo, etiquetas y calidad revisadas, grupos sin fuga, negativos separados y nuevo TEST sellado. **G2** exige entrenamiento/VAL y evaluación única de ese TEST. **9.1, 9.4 y G3** siguen abiertos hasta aceptación independiente; CI remota exitosa de v1.2.0 no sustituye esa evidencia.
