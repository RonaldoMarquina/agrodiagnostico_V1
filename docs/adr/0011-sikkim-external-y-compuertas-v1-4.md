# ADR 0011: Sikkim v1 como EXTERNAL sellado en el ciclo v1.4.0

- Fecha: 2026-11-22
- Estado: aceptado por el responsable del proyecto
- Decisión relacionada: G0 v1.4.0

## Contexto

El TEST v1.3.2 demostró que el candidato anterior no rechazaba papa sana: publicó tizón en 8/32 controles y produjo solo 24/32 `NO_CONCLUYENTE`. Ese TEST, su bundle y su reporte son evidencia histórica inmutable y no pueden usarse para seleccionar cambios del ciclo siguiente.

PlantVillage dispone de grupos `leaf_id` verificables para continuar la selección con TRAIN/VAL. Sikkim Solanaceae Leaf Image Dataset v1 aporta fotografías de campo con licencia declarada CC BY 4.0 y cuatro estratos útiles, pero no proporciona identidad verificable por planta, hoja, sesión o parcela.

## Decisión

1. PlantVillage `color`, revisión `9e97599868962bd0079b8db4b7f1efa9185fa1e7`, es la única fuente de TRAIN/VAL v1.4.0. TRAIN contiene las tres clases técnicas; `OTHER_CROP` se conserva solo en VAL para medir rechazo.
2. Sikkim v1, DOI `10.17632/4wz7zbk635.1`, se admite únicamente como una partición EXTERNAL sellada de 362 archivos: 42 tizón temprano, 76 tardío, 50 papa sana y 194 de otro cultivo.
3. La unidad declarada de Sikkim es el archivo único por SHA-256. No se afirma independencia por planta, hoja, sesión, parcela ni región.
4. EXTERNAL no puede ser leído por entrenamiento, VAL, calibración ni selección de arquitectura, balance, hiperparámetros o umbral. La evaluación final requiere pesos, configuración, preprocesado, mapa, calibración y umbral seleccionados en VAL y congelados con SHA-256.
5. El manifiesto EXTERNAL se verifica por hash de bytes y hash canónico de todas sus filas. Un cambio posterior rompe el sello.

## Evidencia de datos y derechos

El ZIP fijado tiene SHA-256 `5288c8f9d4628049ae1f827c961dc3df97167de294cec020cbce0bc19b2574dc`. Cada registro privado conserva ruta, hash, etiqueta de la fuente, decisión, atribución, licencia, URL de la fuente y comprobante común. Una URL pública sin autor, licencia aplicable y hash no supera la admisión.

Los 362 SHA-256 son únicos y no coinciden exactamente con las 6.059 imágenes PlantVillage locales. dHash (64 bits, BILINEAR, distancia ≤6) produjo 20 alertas cruzadas; la inspección lado a lado mostró escenas/hojas distintas. Dentro de Sikkim se registraron 37 pares perceptuales; varios parecen relacionados o derivados. Se retienen porque el denominador G0 está fijado por archivos únicos de la distribución, pero la correlación se declara como limitación y prohíbe interpretar los resultados como evidencia por planta.

## Consecuencias

- G1 puede cerrar por procedencia, derechos, separación, conteos y sello; no acredita rendimiento.
- G2 permanece abierto hasta entrenar/seleccionar con PlantVillage y ejecutar una única evaluación EXTERNAL posterior al congelamiento.
- Un fallo EXTERNAL no puede corregirse con Sikkim; exige otro ciclo y otro conjunto final independiente.
- El worker no se activa por el cierre de G0/G1.
