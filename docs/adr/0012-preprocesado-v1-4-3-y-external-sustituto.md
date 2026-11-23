# ADR 0012: Preprocesado v1.4.3 y EXTERNAL sustituto

- Fecha: 2026-11-23
- Estado: aceptado por el responsable del proyecto
- Decisión relacionada: ciclo OpenSpec v1.4.3

## Contexto

La apertura única de Sikkim v1.4.2 terminó antes de producir métricas porque
dos archivos eran `MPO/RGB` y la allowlist congelada solo reconocía JPEG, PNG y
WEBP. Reintentar Sikkim después de cambiar el preprocesado reutilizaría la misma
evaluación independiente y no está autorizado.

## Decisión

1. v1.4.3 conserva los pesos, arquitectura, mapa, temperatura 0,50 y umbral
   0,80 de v1.4.2; solo versiona la compatibilidad de decodificación.
2. El decodificador identifica el contenedor por bytes. MPO usa siempre el
   frame primario 0 y se registra como MPO, no como JPEG.
3. Toda entrada autorizada se orienta por EXIF, compone transparencia sobre
   blanco y se convierte explícitamente a RGB antes del resize 224×224 y la
   normalización ImageNet.
4. Un futuro EXTERNAL debe completar un preflight de todos sus archivos antes
   del sello. El preflight no puede cargar el modelo ni producir predicciones o
   métricas.
5. Sikkim queda exclusivamente como evidencia histórica del fallo técnico. El
   EXTERNAL sustituto puede combinar fuentes si cada archivo conserva origen,
   licencia, etiqueta, SHA-256, decisión y estrato.
6. Los denominadores y límites enteros se aprueban después de la auditoría y
   antes del sello. La evaluación independiente será otro cambio posterior.

## Consecuencias

- El bundle derivado tendrá un hash de contrato distinto aunque los pesos sean
  idénticos.
- Aceptar más contenedores no significa aceptar cualquier archivo que Pillow
  pueda abrir; formatos, modos y frames permanecen en una lista finita.
- Una incompatibilidad descubierta en el preflight se corrige creando una nueva
  revisión del manifiesto antes del sello, sin consumir una evaluación.
- G2/G3 y el worker real permanecen abiertos/inactivos hasta una nueva
  evaluación independiente completa.
