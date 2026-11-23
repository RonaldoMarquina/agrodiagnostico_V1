# Evaluación EXTERNAL v1.4.2 — fallo técnico inmutable

Fecha: 2026-11-23. Resultado: `FAILED_TECHNICAL_NO_COMPLETE_METRICS`.

## Ejecución única

El preflight verificó el bundle `07ef4eac…110a`, los 362 registros del
manifiesto, el sello, protocolo y ZIP Sikkim. Después se creó el registro de
acceso y comenzó la única evaluación autorizada, en contenedor CPU sin red y
con todas las entradas montadas en solo lectura.

La ejecución terminó a los 2,999 segundos con:

```text
ValueError: Formato de imagen no permitido
```

El preprocesado congelado admite JPEG, PNG y WEBP después de verificar el
formato real. Al menos un objeto del lote sellado no satisface esa allowlist.
No se cambió el preprocesado RGB 224×224, la normalización ImageNet, los pesos,
la temperatura 0,50 ni el umbral 0,80. No se reintentó.

## Evidencia conservada

- Registro privado `access.json`: SHA-256
  `5c30483aefda269c648cedca5690115bbe0f0f7e65fef1b4e06304cc30dd3585`.
- Estado: `FAILED_TECHNICAL`.
- Freeze: `07ef4eac80f59b7ca1fc42031092f3353e7e2dd89d6c8c8c17fda4865c85110a`.
- Pesos: `e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c`.
- Manifiesto: `3c8d95e9e4d198dedf821133cb4d5f0c119a327b496396c25d4b71a493580992`.
- Sello: `ab0e7e7c8a28a70a5bce4fd6424912454e2a31b31f463406233d811ed3f9a69a`.
- ZIP: `5288c8f9d4628049ae1f827c961dc3df97167de294cec020cbce0bc19b2574dc`.

No se generaron `predictions.jsonl`, reporte métrico ni matriz de confusión.
El contador de predicciones persistidas es cero; la cantidad procesada en
memoria antes del fallo no fue registrada y no se reconstruye abriendo el lote
otra vez.

## Decisión G2

Los denominadores 42/76/50/194 están incompletos. Por tanto F1 macro, recalls,
rechazo sano, rechazo de otro cultivo, abstenciones, matriz, latencia completa y
memoria no son métricas válidas y figuran como `null`. Ningún criterio puede
acreditarse.

G2 permanece `OPEN_EXTERNAL_TECHNICAL_FAILURE`. El worker continúa
`INACTIVE_NOT_AUTHORIZED` y la política real `INACTIVE_NOT_IMPORTED`.

La apertura única quedó consumida. Corregir formatos o preprocesado y volver a
usar Sikkim cambiaría el ciclo después de observar EXTERNAL; no está autorizado.
Una continuación legítima requiere una decisión explícita y un nuevo ciclo con
evaluación independiente.
