# G0 v1.3.1 — aprobación del responsable

> Versión histórica: [G0 v1.3.2](INCREMENTO-4-G0-V1.3.2-APROBACION.md) conserva los mínimos y cambia únicamente el criterio TEST de papa sana antes de entrenar. El protocolo v1.3.1 y su hash permanecen como evidencia de la aprobación anterior.

Fecha: **2026-11-21** (America/Lima). El responsable respondió expresamente **«Apruebo exactamente esta tabla»** a la propuesta de mínimos para papa sana TRAIN **80 fotos/20 hojas**, VAL **28/7** y TEST nuevo **32/8**. El [protocolo v1.3.1](../../ml/evaluation/protocol-g0.v1.3.1.json), SHA-256 `b906af38323103144de780e24a1289ff69a84ef0661cc5e30aa941b5842ba7a1`, registra esta aprobación, la fecha, el rol y el motivo basado en el [inventario G1](INCREMENTO-4-G1-V1.3-INVENTARIO-2026-11-21.md). **G0 v1.3.1 queda cerrado.**

Los mínimos de TRAIN/VAL/TEST para `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT` y `OTHER_CROP` permanecen respectivamente **150/50, 40/20 y 30/15** fotos/grupos. No cambian F1, recall, FPR, rechazo, cobertura, error selectivo, calibración ni presupuesto CPU. Solo los dos tizones son publicables; papa sana y otro cultivo son objetivos técnicos de rechazo. El TEST v1.2.0, sus resultados y G0 v1.3.0 permanecen históricos.

La reducción responde a 140 fotos sanas/35 grupos no expuestos; consume toda esa disponibilidad. El TEST sano nuevo tiene ocho hojas independientes y cuatro vistas por hoja, de modo que su precisión estadística y validez externa son limitadas. La aprobación de G0 no equivale a admisión de imágenes ni a rendimiento medido. [Evidencia separada de G1](INCREMENTO-4-G1-V1.3.1-ADMISION.md).
