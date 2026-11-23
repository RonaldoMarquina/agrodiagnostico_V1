# Evidencia G0/G1 v1.4.1

Fecha: 2026-11-23. Estado: G0 y G1 cerrados; entrenamiento aún no ejecutado en este corte.

El responsable aprobó G0 v1.4.1 tras el fallo VAL v1.4.0 de 83/150 publicaciones de tizón sobre `OTHER_CROP` (máximo 7). El protocolo fijado tiene SHA-256 `a6efb7041bc958549df4bce602aa0b083336b9bb6e7470325a55588bd8123c93`.

El manifiesto privado se materializó por referencia desde el expediente PlantVillage admitido. Conserva SHA-256, revisión, licencia, ruta original, etiqueta, decisión y `leaf_id` por archivo. Su SHA-256 es `b16533a8cdce48463c1fd8d43e451a696cddfc6860244a7c10157eaa5a0db884`.

| Estrato | TRAIN fotos/grupos | VAL fotos/grupos |
| --- | ---: | ---: |
| Tizón temprano | 541/136 | 165/42 |
| Tizón tardío | 499/129 | 153/39 |
| Papa sana | 80/20 | 28/7 |
| Otro cultivo | 503/127 | 150/38 |
| Total | 1.623/412 | 496/126 |

No hay grupos cruzados, `fallback_*`, SHA duplicados, filas TEST ni filas Sikkim. Los 68 grupos de TEST histórico están bloqueados. La materialización no leyó registros EXTERNAL: solo comparó el hash público del manifiesto Sikkim (`3c8d95e9e4d198dedf821133cb4d5f0c119a327b496396c25d4b71a493580992`) y su sello (`ab0e7e7c8a28a70a5bce4fd6424912454e2a31b31f463406233d811ed3f9a69a`) con la compuerta padre.

El plan usa inicialización aleatoria sin descargas, GroupNorm, cuatro logits y sampler 80×4. `POTATO_HEALTHY` y `OTHER_CROP` son clases técnicas de rechazo, nunca diagnósticos publicables. Sikkim y TEST continúan cerrados.
