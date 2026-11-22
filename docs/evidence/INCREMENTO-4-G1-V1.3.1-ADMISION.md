# G1 v1.3.1 — admisión y nuevo TEST sellado

> Estado posterior: [G0 v1.3.2](INCREMENTO-4-G0-V1.3.2-APROBACION.md) reutilizó este mismo G1 sin alterar imágenes, particiones, informe ni sello. Tras congelar el candidato, [TEST se evaluó una vez](INCREMENTO-4-TEST-V1.3.2-UNICO.md) y falló el rechazo sano; G2 sigue abierto. El texto inferior describe el cierre G1 antes de esa evaluación.

Fecha: **2026-11-21** (America/Lima). Estado: **G1 cerrado para el lote privado v1.3.1**, después de la [aprobación explícita G0](INCREMENTO-4-G0-V1.3.1-APROBACION.md). El cierre acredita procedencia, derechos, revisión interna, grupos y particiones; **no acredita rendimiento de un modelo**. No hubo entrenamiento, selección de umbral, inferencia ni evaluación del nuevo TEST.

## Fuente, revisión y exclusiones

Distribución PlantVillage del autor, configuración `color`, revisión `9e97599868962bd0079b8db4b7f1efa9185fa1e7`, archivo ZIP SHA-256 `fba30c6a7965e49be94b47a62f8aff6cfb1c35c27f475f22092b56db41745e84`, declaración de derechos SHA-256 `9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb`. La declaración publicada aplica CC BY-SA 3.0 al lote y condición ShareAlike para algoritmos entrenados; cada registro privado vincula la licencia al archivo mediante revisión, ruta original y SHA-256. Se conservan atribución y restricciones. No se publican imágenes de terceros en Git.

El inventario de 858 candidatos excluyó 12 fotos/3 hojas sanas expuestas en G3 y 106 tomates sin `leaf_id` verificable. La inspección de 11 pares visuales llevó a excluir conservadoramente 48 fotos/12 grupos candidatos completos; [decisiones por par](INCREMENTO-4-G1-V1.3.1-REVISION-PREPARATORIA.md). Tras esas exclusiones, el registro de auditoría registra **166 `EXCLUDE` y 692 `PENDING`**; `PENDING` es estado del inventario previo, no del manifiesto admitido. La selección final usa 140 fotos sanas/35 hojas y 80 fotos/20 hojas nuevas para cada uno de los otros tres estratos de TEST. Las etiquetas son las curadas por expertos según PlantVillage, más control visual interno de calidad y ambigüedad. Las hojas sanas 35.0, 36.0 y 37.0 tienen marcas leves anotadas; no se atribuye una nueva evaluación agronómica especializada. La [tabla de equivalencias fijada](../../ml/manifests/g1-v1.3.1-source-labels.json) vincula únicamente cuatro etiquetas originales a los cuatro estratos técnicos; solo los dos tizones son publicables.

## Manifiestos admitidos

Salida privada: `.local/pv-g1/g1-v1.3.1-admitted/`. `g1-report.json` SHA-256 `71c4e34c60eb1b635da58af934b05fd1683728f895e955d8027f7652e91c7a75`; `strata.csv` SHA-256 `3c74f6ebb846eb8dd8e2460d96e8043135db8a93cb28ee56f171f2cd3796eb53`; `evidence.json` SHA-256 `8c62ca2e4663e1ba27d897c6f2b8a55f64de24e85c562588cef2545f67cfe3eb`; tabla de equivalencias SHA-256 `e1181607bc2982f25bfb6939e512990fd777b205e9e0b496daf943883b095d2c`. Cada una de las **2.391 filas `ADMIT`** conserva fuente, revisión, ruta original y privada, SHA-256 de bytes, licencia y prueba, etiqueta original, estrato, `leaf_id` como `split_group`, partición, decisión, motivo y revisión. Los cuatro CSV por estrato son idénticos a sus respectivas filas del manifiesto conjunto. No hay duplicados SHA. El [estado de puertas separado](../../ml/evaluation/gate-status.v1.3.1.json) registra G1 cerrado sin alterar el protocolo G0 ya aprobado; sus campos `gates` eran una instantánea en G0.

| Estrato | TRAIN fotos/grupos | VAL fotos/grupos | TEST nuevo fotos/grupos | Mínimos G0 |
| --- | ---: | ---: | ---: | --- |
| Tizón temprano | 541/136 | 165/42 | 80/20 | Cumple |
| Tizón tardío | 499/129 | 153/39 | 80/20 | Cumple |
| Papa sana | 80/20 | 28/7 | 32/8 | Cumple exactamente |
| Otro cultivo | 503/127 | 150/38 | 80/20 | Cumple |

Total: **2.391 fotos originales y 606 grupos**. El TEST nuevo comprende **272 fotos/68 grupos** y está sellado en `.local/pv-g1/g1-v1.3.1-admitted/test-seal.json`, SHA-256 `4f0872f62b58b35df908de8dae3f0577dc425f871e0e74e7fbf26a1afe9489bc`. No hay `leaf_id` entre TRAIN, VAL y TEST; tampoco grupos G3 expuestos ni hashes/grupos del TEST v1.2.0 en el TEST nuevo. El sello se verificó sin usar imágenes para selección de modelo. El paquete privado y el sello deben permanecer intactos; cualquier exclusión posterior obliga a reabrir G1 y recalcular mínimos antes de entrenar.

Comandos reproducibles desde raíz, con fuentes privadas ya fijadas y sin descargas implícitas:

```bash
python3 scripts/finalize_g1_v1_3_1.py .local/pv-g1 .local/pv-g1/pilot-v1.2 .local/pv-g1/g1-v1.3-pair-resolution .local/pv-g1/g1-v1.3-review-candidates .local/pv-g1/g1-v1.3.1-plan-verified ml/evaluation/protocol-g0.v1.3.1.json .local/pv-g1/g1-v1.3.1-admitted
python3 scripts/verify_g1_v1_3_1.py .local/pv-g1/g1-v1.3.1-admitted .local/pv-g1/pilot-v1.2 ml/evaluation/protocol-g0.v1.3.1.json
```

La segunda orden verificó de nuevo hashes de los 2.391 archivos, derechos, etiquetas, mínimos, evidencia por archivo, separación, exclusión histórica y sello; resultado `VERIFIED`. Los tests negativos comprueban fuga entre particiones, repetición de SHA y reutilización del TEST histórico. G2 y G3 siguen abiertos. EXTERNAL no está disponible; los resultados futuros no deben extrapolarse a fotografías de campo.
