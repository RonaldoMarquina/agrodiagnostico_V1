# Design — ciclo G0 v1.3.0 aprobado

> Estado vigente 2026-11-21: [G0 v1.3.2](../../../docs/evidence/INCREMENTO-4-G0-V1.3.2-APROBACION.md) sustituye el criterio TEST de papa sana antes de entrenar; [G1 v1.3.1](../../../docs/evidence/INCREMENTO-4-G1-V1.3.1-ADMISION.md) sigue cerrado con el mismo sello. El diseño histórico de v1.3.0 y la decisión v1.3.1 se conservan abajo.

> Actualización del 2026-11-21: [G0 v1.3.1 aprobado](../../../docs/evidence/INCREMENTO-4-G0-V1.3.1-APROBACION.md) reduce **solo** mínimos de papa sana tras el inventario real G1. [G1 v1.3.1 cerrado](../../../docs/evidence/INCREMENTO-4-G1-V1.3.1-ADMISION.md) admite el lote privado y sella un nuevo TEST. D2 y el resto del diseño conservan el protocolo v1.3.0 histórico; para el ciclo nuevo manda v1.3.1. No se ha entrenado ni evaluado TEST nuevo.

Fecha: 2026-11-20 (America/Lima). Estado: **G0 v1.3.0 aprobado por el responsable; G1 abierto**. Véanse [proposal.md](proposal.md), las dos especificaciones delta y el [protocolo aprobado](../../../ml/evaluation/protocol-g0.v1.3.0.json). La aprobación fija mínimos y límites antes del entrenamiento; no admite imágenes ni acredita resultados.

## Context

El bundle G2 v1.2.0 y su TEST ya abierto quedan históricos. En G3 local, 4/4 controles de papa sana se publicaron como tizón tardío. La revisión de SHA-256 y `leaf_id` identifica tres hojas expuestas que suman 12 fotos del inventario VAL de papa sana. El contrato `DiagnosisAnalyzed.v1` ya contempla `ABSTENTION/UNSUPPORTED_CLASS`; el contrato actual del bundle y su adaptador real aceptan solo dos tizones más `OTHER_CROP`, por lo que la futura versión exige evolución contractual explícita.

## Goals / Non-Goals

**Goals:** medir rechazo de papa sana por separado, preservar dos enfermedades publicables y obtener un TEST v1.3.0 independiente. Mantener G0, G1, G2 y G3 como puertas separadas.

**Non-Goals:** declarar una planta sana, añadir maíz o plagas, entrenar con fotos de usuarios, modificar el bundle o los resultados v1.2.0, activar una política real en esta fase de diseño.

## Decisions

### D1. Objetivo técnico de papa sana

G0 fija cuatro estratos técnicos: `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT`, `POTATO_HEALTHY` y `OTHER_CROP`. El mapa publicable sigue teniendo solo los dos tizones. La condición técnica de papa sana se transforma en abstención `UNSUPPORTED_CLASS`; `OTHER_CROP`, en `UNSUPPORTED_CROP`. Diagnosis conserva el control final de publicación, política y catálogo. Se compararán implementaciones de rechazo bajo el mismo TRAIN/VAL, preprocesado y presupuesto, siempre conservando la distinción medible de papa sana; su selección se hará únicamente con VAL. Los cuatro controles G3 no participan en esa comparación.

### D2. G0 numérico antes de entrenar

El [protocolo aprobado](../../../ml/evaluation/protocol-g0.v1.3.0.json) hereda sin reducir F1, recall, cobertura, error selectivo, calibración y CPU de v1.2.0. Aplica a **cada** estrato, incluidos papa sana y otro cultivo, los mínimos de 150 fotos/50 grupos en TRAIN, 40/20 en VAL y 30/15 en TEST; EXTERNAL 20/10 si se dispone de uno autorizado. Fija FPR ≤ 0,05 y rechazo ≥ 0,95 **por cada estrato negativo**, además del agregado. El límite 0,10 de aceptación errónea sigue registrado, pero gobierna el 0,05 más estricto. El responsable aprobó estos mínimos y límites el 2026-11-20; no se ajustarán tras ver el nuevo TEST.

La cobertura se calcula como diagnósticos aceptados de cualquiera de los tizones / fotos válidas de ambos tizones; el error selectivo, como diagnósticos aceptados incorrectos / diagnósticos aceptados de esas fotos. Recall por clase cuenta toda abstención como falso negativo. FPR de cada negativo usa diagnósticos visibles de tizón / total de fotos válidas de ese estrato; denominador cero o cero aceptados para error selectivo no cumple. La elección de umbral y calibración usa VAL; se congelan antes de TEST.

### D3. Admisión y separación de grupos

G1 v1.3.0 revisará cada foto mediante revisión de distribución, ruta y SHA-256, licencia aplicable, etiqueta original, control interno de calidad y `leaf_id` publicado. La procedencia experta de PlantVillage se registra como tal, sin afirmar nueva validación agronómica independiente. Los pares visuales y grupos entre versiones se auditan. Los cuatro controles G3 quedan excluidos de todo entrenamiento, selección de umbral y evaluación; para impedir fuga entre vistas de la misma hoja se excluyen sus **tres grupos completos: 12 fotos** de todas las particiones v1.3.0, según la [lista de exclusión](../../../ml/manifests/g1-v1.3-exposure-blocklist.json). Las otras 12/3 del antiguo inventario VAL son candidatas para VAL tras revisión. Las 16/4 del antiguo inventario TEST de papa sana **no eran el TEST G2 v1.2.0** ni se abrieron en esa evaluación; son candidatas, no admitidas, para TEST nuevo tras revisar fuga y permisos. Ningún grupo del TEST ya abierto v1.2.0 puede servir como nuevo TEST. Si los datos nuevos no bastan, G1 permanece abierto.

### D4. Contratos, evaluación y promoción

La implementación posterior versionará el bundle y su política de rechazo para los cuatro objetivos técnicos; el validador deberá impedir que `POTATO_HEALTHY` o `OTHER_CROP` entren en el mapa publicable. `DiagnosisAnalyzed.v1` puede transportar abstención `UNSUPPORTED_CLASS`, sujeto a pruebas de compatibilidad. La evaluación reportará F1/recall por enfermedad, confusión, abstenciones, cobertura, error selectivo, ECE, latencia, memoria y FPR por cada negativo con numeradores/denominadores. Tras congelar bundle, protocolo y manifiestos se ejecutará un solo TEST nuevo. G2 del responsable y prueba G3 posterior son necesarias antes de activar otra política.

### D5. Criterio G0 v1.3.2 sobre el G1 ya sellado

El responsable aprobó el 2026-11-21 los mínimos reales sanos 80/20 TRAIN, 28/7 VAL y 32/8 TEST (total 140/35), basados en hojas verificables disponibles. El TEST sano exige como máximo **3/32** diagnósticos visibles de tizón y al menos **29/32** estados finales `NO_CONCLUYENTE`. `FALLIDO` no cuenta como abstención. Las 32 fotos permanecen en el denominador; el reporte separa fotos y ocho hojas. Los límites históricos FPR ≤0,05 y rechazo ≥0,95 se aplican a `OTHER_CROP`, y el límite general de aceptación errónea ≤0,10 sigue vigente. F1, recall, cobertura, error selectivo, ECE, CPU y p95 del flujo mantienen los valores v1.3.1.

El [G1 v1.3.1](../../../docs/evidence/INCREMENTO-4-G1-V1.3.1-ADMISION.md) permanece cerrado porque el nuevo protocolo no altera particiones ni mínimos. La [revalidación](../../../scripts/verify_g0_v1_3_2.py) compara hashes del protocolo anterior, reporte privado y sello; después verifica los archivos G1. No vuelve a sellar TEST ni consulta predicciones. G2/G3 siguen abiertos. Las cuatro vistas por hoja y ocho hojas sanas de TEST limitan la inferencia de generalización.

## Riesgos / Trade-offs

- **Insuficiencia de imágenes sanas y TEST nuevo** → mantener G1 abierto y buscar fuente original con derechos, etiquetas y grupos verificables; no reducir mínimos después del fallo.
- **Fotos del mismo dominio con apariencia repetida** → revisar SHA-256, `leaf_id` y pares visuales entre versiones; excluir dudas.
- **Proveniencia experta sin validación en campo de Ayacucho** → reportar EXTERNAL no disponible y no extrapolar generalización.
- **Cuatro salidas técnicas confundidas con cuatro diagnósticos** → contrato de mapa publicable y pruebas de abstención obligatorios.

## Migration Plan

1. G0 v1.3.0 aprobado por el responsable el 2026-11-20 con fecha, versión, mínimos y justificación registrados.
2. Completar G1 con derechos, etiquetas, grupos, exclusión de controles G3 y nuevo TEST sellado. No entrenar antes.
3. Evolucionar contratos y adaptador, comparar en TRAIN/VAL, congelar bundle y umbral.
4. Abrir TEST v1.3.0 una vez, decidir G2 y repetir aceptación 9.1/G3 solo si procede.
5. Activar política v1.3.0 mediante CLI auditada únicamente tras G2 y catálogo revisado. Retirar con rollback de política si falla; no sobrescribir historiales ni artefactos v1.2.0.

## Datos faltantes exactos

Para el ciclo vigente v1.3.2, los mínimos de fotos y grupos ya están cubiertos por G1 v1.3.1. El texto inferior registra el déficit histórico anterior a su admisión.

El [expediente de déficit](../../../docs/evidence/INCREMENTO-4-CICLO-RECHAZO-PAPA-SANA.md) conserva el **límite inferior condicional histórico** de 190 fotos originales y 100 grupos nuevos, calculado antes de excluir los controles G3. Con la exclusión de las 12 fotos de sus tres grupos completos, el **faltante mínimo operativo** es 202 fotos originales y 103 grupos, bajo las mismas hipótesis de admisión y reutilización auditada de TRAIN/VAL. Esta corrección de inventario no modifica ningún mínimo G0 aprobado. Ningún archivo del déficit está admitido por este diseño.
