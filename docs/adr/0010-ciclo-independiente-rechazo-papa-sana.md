# ADR-0010 — Ciclo independiente para rechazo de papa sana

Fecha: 2026-11-20 (America/Lima). Estado: **G0 v1.3.0 aprobado; implementación y G1 pendientes**. Responsable de la decisión: responsable del proyecto. Sustento: [aceptación G3 local](../evidence/INCREMENTO-4-G3-ACEPTACION-LOCAL.md), [expediente de datos](../evidence/INCREMENTO-4-CICLO-RECHAZO-PAPA-SANA.md), [acta G0](../evidence/INCREMENTO-4-G0-V1.3-APROBACION.md) y [cambio OpenSpec](../../openspec/changes/incremento-4-v1-3-rechazo-papa-sana/proposal.md).

## Contexto y decisión

El bundle aprobado G2 v1.2.0 publicó 4/4 controles de papa sana como `POTATO_LATE_BLIGHT` en la aceptación local. El responsable eligió iniciar un ciclo nuevo de rechazo verificable de papa sana. Se propone mantener dos enfermedades publicables y añadir `POTATO_HEALTHY` como objetivo **técnico**, cuyo resultado visible es `NO_CONCLUYENTE/UNSUPPORTED_CLASS`; la clase sana no certifica ausencia de enfermedad. `OTHER_CROP` sigue como rechazo técnico separado. Esta decisión conserva la propiedad del resultado visible en Diagnosis y los estados/eventos existentes; la futura evolución del bundle se definirá en contrato versionado.

La aplicación a papa sana y a otros cultivos de mínimos 150/50 TRAIN, 40/20 VAL y 30/15 TEST, así como FPR ≤ 0,05 por estrato, está fijada en el [G0 v1.3.0 aprobado](../../ml/evaluation/protocol-g0.v1.3.0.json). El responsable aprobó expresamente el protocolo completo el **2026-11-20**, antes de entrenar o abrir el nuevo TEST. La cifra 190 fotos/100 grupos era un déficit condicional de inventario calculado antes de excluir los controles G3; la exclusión de sus tres grupos eleva el faltante operativo a 202 fotos/103 grupos sin cambiar los mínimos G0.

## Consecuencias

- G1 v1.3.0 requiere admisión por archivo y un TEST nuevo independiente para ambos tizones y ambos estratos negativos; el TEST y bundle v1.2.0 no se modifican ni se reutilizan para elegir cambios.
- Los 4 controles sanos expuestos y las otras fotos de sus tres `leaf_id` quedan fuera de **todo TRAIN, VAL, TEST y EXTERNAL v1.3.0**; no se usarán para entrenar, elegir umbrales ni medir.
- Contrato de bundle, adaptador y pruebas deberán distinguir cuatro objetivos técnicos de dos diagnósticos publicables. `NO_CONCLUYENTE` continúa como estado.
- G2 v1.3.0 y G3 requieren nueva evaluación y aceptación. La CI técnica v1.2.0, aunque pase, no cierra G3.

## Alternativas consideradas

Un umbral de confianza único sobre las dos clases existentes no demostró rechazo de papa sana en G3; reajustarlo con esos cuatro controles contaminaría la independencia del TEST histórico. Un detector de fuera de distribución separado sigue siendo alternativa comparable en VAL v1.3.0, bajo el mismo presupuesto y nuevo G1. Publicar `POTATO_HEALTHY` como diagnóstico se descarta porque el piloto no valida ausencia de todas las enfermedades.
