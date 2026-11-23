# Tasks

> Estado actual: 23/23. Este cambio prepara compatibilidad y un EXTERNAL nuevo;
> no autoriza predicciones, evaluación G2 ni activación del worker. Sikkim no se
> vuelve a abrir. Los conteos publicados de fuentes candidatas no son conteos
> admitidos hasta completar la auditoría por archivo.

## 1. Evidencia del fallo y contrato v1.4.3

- [x] 1.1 Publicar el diagnóstico sanitizado que registra 360 `JPEG/RGB`, 2 `MPO/RGB` y el primer SHA-256/ruta/medidas rechazados, verificando que el expediente declara cero carga de modelo, predicciones y métricas nuevas sobre Sikkim
- [x] 1.2 Versionar el contrato de decodificación v1.4.3 con formatos, modos, frames, alpha, EXIF, límites, RGB 224×224 e ImageNet, y verificar que pesos, arquitectura, mapa, temperatura 0,50 y umbral 0,80 coinciden con el freeze v1.4.2
- [x] 1.3 Registrar en protocolo, ADR y documentación que Sikkim queda solo como evidencia histórica y probar que un manifiesto o comando v1.4.3 que lo referencia es rechazado antes de abrir imágenes

## 2. Decodificador compatible y regresión

- [x] 2.1 Refactorizar la identificación, verificación, selección de frame, orientación EXIF, composición de alpha y conversión RGB antes del resize/normalización; verificar unitariamente el orden y la salida 3×224×224 finita
- [x] 2.2 Añadir fixtures identificados para contenedores `JPEG`, `MPO`, `PNG`, `WEBP` y `TIFF` y modos `1`, `L`, `LA`, `P`, `RGB`, `RGBA`, `CMYK` e `I;16`; verificar conversión RGB y metadata detectada para cada combinación representativa
- [x] 2.3 Añadir pruebas negativas de extensión engañosa, formato/modo no admitido, corrupción, exceso de bytes/dimensiones, bomba de descompresión y PNG/WEBP/TIFF animado o multipágina; verificar rechazo estable antes de inferencia
- [x] 2.4 Añadir una regresión que compare v1.4.2 y v1.4.3 para fixtures RGB JPEG/PNG/WEBP y verificar tensores idénticos, resize bilineal 224×224, normalización ImageNet y aumentación solo en TRAIN
- [x] 2.5 Actualizar el lock y la guía reproducible del runtime si cambia alguna dependencia, y verificar instalación CPU limpia y suite focalizada sin descargas implícitas

## 3. Preflight completo previo al sello

- [x] 3.1 Implementar el preflight sin importación de modelo que coteja ruta, SHA-256, tamaño, formato, modo, dimensiones, frames, RGB, tensor y cardinalidad de cada fila; verificar con un lote fixture completamente válido
- [x] 3.2 Emitir registro JSONL por SHA y resumen hashado, y verificar que el conjunto de hashes coincide uno a uno con el manifiesto sin rutas privadas en la evidencia pública
- [x] 3.3 Implementar bloqueo de sello ante archivo ausente/extra/duplicado, hash mutado, decodificación fallida, reporte parcial o cardinalidad diferente; probar que no se generan sello, predicciones ni métricas
- [x] 3.4 Integrar la compuerta en los comandos de admisión/sellado y verificar que cualquier exclusión obliga a una revisión nueva del manifiesto y a repetir el preflight completo

## 4. Auditoría y admisión del EXTERNAL sustituto

- [x] 4.1 Descargar a almacenamiento privado la revisión exacta PLDD-UP v1 desde el origen oficial y registrar URL, DOI, versión, autores, CC BY 4.0, archivo fuente, tamaño y SHA-256; verificar que ninguna imagen se incorpora al repositorio ni se declara admitida por la licencia de portada solamente
- [x] 4.2 Inventariar los archivos originales EB/LB/Healthy de PLDD-UP, separando derivados y registrando por imagen hash, ruta, formato, modo, etiqueta, captura y unidad de independencia demostrable; verificar conteos reales y excluir dudas sin inventar planta/sesión
- [x] 4.3 Descargar y auditar en privado el `Raw_Dataset` de Pota-Toma-To v1 para negativos de tomate, excluyendo `Advanced_Processed_Dataset`; verificar versión, CC BY 4.0, hashes, originales, conteos y procedencia, descartar sus 435 archivos por falta de autor/URL/licencia por fotografía y registrar CornLeafDiseaseCollection v1 como sustituto primario sujeto a revisión y deduplicación
- [x] 4.4 Revisar equivalencias de etiquetas, calidad y ambigüedad de los cuatro estratos y registrar cada admisión/exclusión con motivo; verificar que “early/late blight” no se fuerza desde una etiqueta distinta sin evidencia
- [x] 4.5 Ejecutar deduplicación exacta y visual contra TRAIN/VAL y registros históricos sin abrir de nuevo Sikkim, y verificar que derivados, duplicados y grupos correlacionados no contribuyen a denominadores
- [x] 4.6 Entregar la tabla real fuente → estrato → originales → unidad independiente → admitidos/excluidos → bloqueo y verificar derechos aplicables por archivo antes de proponer el manifiesto EXTERNAL

## 5. G0, preflight real y preparación del siguiente ciclo

- [x] 5.1 Definir con los conteos admitidos los denominadores y límites enteros v1.4.3 para F1, recall por tizón, rechazo sano y rechazo de otro cultivo; registrar aprobación versionada del responsable y verificar que ocurre antes del sello
- [x] 5.2 Crear el manifiesto privado EXTERNAL nuevo con los cuatro estratos, procedencia y hashes, ejecutar el preflight sobre todos sus archivos y verificar reporte completo sin cargar pesos ni producir predicciones
- [x] 5.3 Sellar únicamente si derechos, etiquetas, independencia, deduplicación y preflight pasan; verificar hashes inmutables de fuente, manifiesto, reporte y sello y conservar G2 abierto
- [x] 5.4 Actualizar OpenSpec, README, AI_MODEL, Incrementos y evidencia con conteos y limitaciones reales, ejecutar validación estricta y pruebas pertinentes, y hacer commit local limpio sin abrir EXTERNAL para inferencia ni activar el worker
- [x] 5.5 Proponer en un cambio posterior la apertura única del nuevo EXTERNAL con el freeze derivado v1.4.3; verificar que este cambio termina sin predicciones, métricas G2 ni reutilización de Sikkim
