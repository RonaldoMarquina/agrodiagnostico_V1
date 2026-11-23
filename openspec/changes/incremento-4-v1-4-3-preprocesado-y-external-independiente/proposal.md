# Proposal

## Why

La única apertura de Sikkim del ciclo v1.4.2 terminó antes de producir métricas
porque Pillow identificó dos objetos como contenedor `MPO` aunque su modo de
color era `RGB`; el preprocesado congelado solo admitía `JPEG`, `PNG` y `WEBP`.
Antes de sellar otra evaluación independiente se necesita un contrato de
decodificación verificable y un preflight completo que impida descubrir
incompatibilidades después de consumir la apertura.

## What Changes

- Crear el ciclo v1.4.3 sin alterar los pesos, la arquitectura
  MobileNetV3-Small, la temperatura 0,50 ni el umbral 0,80 de v1.4.2.
- Versionar un decodificador que valide el contenedor, el modo de color y la
  política de frames, aplique orientación EXIF, convierta explícitamente a
  `RGB` y recién después haga resize 224×224 y normalización ImageNet.
- Probar cada formato y modo admitido, los rechazos de entradas corruptas,
  animadas o multipágina no autorizadas, y la equivalencia tensorial de las
  imágenes RGB que ya eran compatibles.
- Incorporar un preflight obligatorio que decodifique todos los archivos de un
  futuro EXTERNAL y registre por SHA-256 formato, modo, dimensiones, frames y
  resultado tensorial antes de permitir su sellado, sin cargar el modelo ni
  calcular predicciones.
- Conservar Sikkim y su ejecución v1.4.2 únicamente como evidencia histórica
  del fallo técnico; prohibir su reuso como EXTERNAL, TEST o entrada G2 de
  v1.4.3.
- Auditar y admitir una fuente EXTERNAL nueva e independiente con versión,
  procedencia, licencia aplicable, hashes, etiquetas, unidad real de
  independencia, duplicados y conteos. Definir y aprobar sus denominadores
  exactos antes del sello y de cualquier inferencia.

## Capabilities

### New Capabilities

- `ml-preprocessing-and-external-admission`: decodificación segura y
  determinista a RGB, preflight completo previo al sello y admisión trazable de
  un EXTERNAL independiente no reutilizado para selección.

### Modified Capabilities

Ninguna. El inventario vigente ya exige procedencia, licencia, hashes,
agrupamiento y prevención de fugas; este cambio los aplica al nuevo EXTERNAL
sin relajar esos requisitos.

## Impact

Afecta al preprocesado y herramientas privadas de `ml/`, validadores de
manifiestos/sellos, pruebas y evidencia del incremento 4. El bundle v1.4.3
tendrá un contrato de preprocesado nuevo, pero reutilizará exactamente los
pesos, arquitectura, calibración y umbral congelados de v1.4.2. No modifica las
APIs HTTP ni los eventos, no activa el worker real y no autoriza todavía una
evaluación: primero deben pasar el preflight, la auditoría legal/técnica y la
aprobación de los conteos y límites del nuevo EXTERNAL.
