# Resultado TRAIN/VAL v1.4.1

Fecha: 2026-11-23. Decisión: `BLOCKED_NO_CANDIDATE_PASSES_VAL`.

El código, protocolo, contratos, configuración y expediente G1 se fijaron antes de entrenar en el commit local `7377819bec40d0c8c0ce3250e89164ee1adebf26`. El contenedor se ejecutó sin red, con una vista de 2.119 bytes originales exclusivamente TRAIN/VAL; Sikkim y los TEST históricos no fueron montados ni leídos. Tampoco se reutilizaron pesos o predicciones v1.4.0.

MobileNetV3-Small se inicializó aleatoriamente y entrenó 10 épocas con GroupNorm. Cada época tuvo 320 exposiciones: 80 de cada una de las cuatro clases técnicas, elegidas clase → `leaf_id` → imagen. Solo papa sana recibió aumentos conservadores TRAIN. El expediente privado registra semilla 42, pérdidas, exposición efectiva, dependencias, CPU, RAM y tiempos.

La época 9 fue seleccionada únicamente con las 496 imágenes VAL. Calibración por temperatura `0,8` y umbral `0,70`:

| Criterio VAL | Resultado | Mínimo/máximo | Estado |
| --- | ---: | ---: | --- |
| F1 macro de tizones | 0,8002 | ≥ 0,80 | cumple |
| Recall tizón temprano | 107/165 = 0,6485 | ≥ 0,80 | **falla** |
| Recall tizón tardío | 129/153 = 0,8431 | ≥ 0,80 | cumple |
| Cobertura | 255/318 = 0,8019 | ≥ 0,70 | cumple |
| Error selectivo | 19/255 = 0,0745 | ≤ 0,10 | cumple |
| Papa sana publicada como tizón | 9/28 | ≤ 2/28 | **falla** |
| Otro cultivo publicado como tizón | 7/150 | ≤ 7/150 | cumple |
| ECE cuatro clases | 0,0338 | ≤ 0,15 | cumple |

La matriz visible registra, por filas reales:

- tizón temprano: 107 temprano, 18 tardío, 40 `NO_CONCLUYENTE`;
- tizón tardío: 1 temprano, 129 tardío, 23 `NO_CONCLUYENTE`;
- papa sana: 9 tardío y 19 `NO_CONCLUYENTE`;
- otro cultivo: 7 tardío y 143 `NO_CONCLUYENTE`.

Latencia CPU de inferencia aislada: mediana 4,3204 ms, p95 5,0939 ms y máximo 5,907 ms; RSS máximo del proceso 3.840,99 MB. El reporte privado tiene SHA-256 `7331a6d75434423a17c7a1ba5ac84ea9139a6327e34ea1d3c5d18cee901aab3f` y los pesos `5be4672b75b0149a85f9a6828a073fed1cd6b1147630ac2504acf21f5ee60105`.

Como fallaron recall temprano y rechazo sano, no se congeló bundle, no se autorizó EXTERNAL, G2 permanece abierto y el worker no cambia.
