# Proposal

> Estado vigente 2026-11-21: [G0 v1.3.2 aprobado](../../../docs/evidence/INCREMENTO-4-G0-V1.3.2-APROBACION.md) fija el conteo de rechazo sano sobre el [G1 v1.3.1 admitido y sellado](../../../docs/evidence/INCREMENTO-4-G1-V1.3.1-ADMISION.md). G1 sigue cerrado tras [revalidación](../../../scripts/verify_g0_v1_3_2.py); no hay entrenamiento ni evaluación TEST v1.3.2. La nota siguiente conserva la secuencia anterior.

> Actualización del 2026-11-21: el inventario G1 motivó una [tabla reducida G0 v1.3.1 aprobada](../../../docs/evidence/INCREMENTO-4-G0-V1.3.1-APROBACION.md). [G1 v1.3.1 cerró](../../../docs/evidence/INCREMENTO-4-G1-V1.3.1-ADMISION.md) tras admisión individual y sello de TEST. Las referencias inferiores a v1.3.0 conservan la decisión histórica; v1.2.0 permanece inalterado. No se entrenó ni evaluó TEST nuevo.

## Why

La aceptación real del piloto G0 v1.2.0 publicó como tizón tardío cuatro de cuatro controles de papa sana. G3 no puede cerrarse con ese bundle: el rechazo de una hoja de papa fuera de las dos enfermedades publicables necesita datos, criterios y evaluación independientes.

## What Changes

- G0 v1.3.0 quedó aprobado por el responsable el **2026-11-20**, antes de entrenar, con dos clases publicables y `POTATO_HEALTHY` como objetivo técnico de rechazo. La salida visible de ese objetivo será `NO_CONCLUYENTE`, sin afirmar que la planta esté sana.
- Exigir mínimos por fotos y grupos para papa sana y para negativos de otros cultivos, resultados por estrato y límite de falsas aceptaciones por estrato. Conservar los umbrales de calidad y presupuesto CPU de v1.2.0 salvo cambio aprobado expresamente.
- Admitir nuevos datos TRAIN/VAL y un TEST nuevo, sellado y sin grupos expuestos, con derechos, etiquetas, `leaf_id` y duplicados revisados. Los cuatro controles sanos G3 y las otras fotos de sus tres grupos quedan excluidos de toda partición v1.3.0. El TEST v1.2.0 y el bundle G2 permanecen históricos e inmutables.
- Comparar alternativas y fijar pesos, calibración y umbral con VAL; evaluar el TEST nuevo una sola vez y solicitar una nueva aprobación G2 antes de repetir 9.1/G3.

## Capabilities

### New Capabilities

- `potato-healthy-rejection`: protocolo G0 v1.3.0, salida técnica de papa sana fuera de cobertura, selección y evaluación independiente del rechazo.

### Modified Capabilities

- `dataset-inventory`: admisión y particiones del ciclo v1.3.0 con negativos separados por estrato y TEST nuevo independiente del ciclo v1.2.0.

## Impact

La futura implementación afectará manifiestos y validadores en `ml/`, entrenamiento/evaluación CPU, contrato de bundle y adaptador real en `services/ai_inference/`, y pruebas de Diagnosis, catálogo y flujo integrado. No cambia propiedad de datos, estados ni eventos versionados sin una modificación contractual explícita. Esta propuesta no admite imágenes, no entrena ni activa políticas.
