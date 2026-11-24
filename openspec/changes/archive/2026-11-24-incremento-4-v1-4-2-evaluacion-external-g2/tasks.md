# Tasks

## 1. Compuerta de apertura única

- [x] 1.1 Implementar la autorización v1.4.2 que verifica freeze, pesos, configuración, mapa, preprocesado, calibración, umbral, protocolo, manifiesto, sello y ZIP por sus hashes antes de leer imágenes; probar rechazo de cada mutación y de propósitos distintos de `FINAL_EXTERNAL_EVALUATION`
- [x] 1.2 Implementar salida exclusiva con `access.json` escrito atómicamente antes de inferir y estados `STARTED`, `COMPLETED` o `FAILED_TECHNICAL`; probar que cualquier salida previa bloquea el reintento sin modificar evidencia
- [x] 1.3 Implementar resolución segura de las 362 rutas dentro del ZIP sellado, sin extracción persistente, y probar rechazo de path traversal, entrada ausente/duplicada, directorio, tamaño o SHA distintos

## 2. Evaluador y reporte EXTERNAL

- [x] 2.1 Implementar carga CPU independiente del bundle congelado y verificar cuatro logits, modo evaluación, gradientes deshabilitados, RGB 224×224, normalización ImageNet, temperatura 0,50, umbral 0,80 y mapa visible de solo dos tizones
- [x] 2.2 Implementar inferencia secuencial sobre las 362 filas y salida privada por hash con probabilidades, argmax, publicación/abstención y latencias; probar que papa sana, otro cultivo y baja confianza producen `NO_CONCLUYENTE`
- [x] 2.3 Completar métricas EXTERNAL con precision/recall/F1 por tizón, F1 macro, abstenciones como falsos negativos, negativos publicados, matriz visible, latencia de inferencia y recorrido, RSS y hashes; probar denominadores exactos 42/76/50/194 y casos frontera de todos los criterios
- [x] 2.4 Implementar la decisión automática que solo marca G2 cerrado cuando pasan los seis criterios y siempre mantiene el worker inactivo; probar ramas aprobada, fallida, denominador incompleto y error técnico

## 3. Preflight y ejecución única real

- [x] 3.1 Ejecutar pruebas focalizadas y OpenSpec estricto sin montar imágenes Sikkim; registrar comandos y resultados, hacer commit local del evaluador antes de abrir EXTERNAL y verificar árbol limpio sin push
- [ ] 3.2 Ejecutar una sola vez en contenedor sin red con bundle, manifiesto, sello y ZIP montados en solo lectura; verificar 362 predicciones, ausencia de escritura en entradas, cero entrenamiento/calibración/selección y finalización inmutable
- [ ] 3.3 Validar en un proceso independiente hashes de acceso, predicciones y reporte, recomputar métricas desde predicciones y confirmar que coinciden exactamente antes de publicar el resultado

## 4. Evidencia y estado G2

- [ ] 4.1 Publicar evidencia sanitizada con F1 macro, recall 42/76, rechazos 50/194, abstenciones, matriz, latencia, memoria, hashes y limitación de independencia por imagen; verificar que no contiene rutas privadas ni bytes de imágenes
- [x] 4.2 Registrar el acta G2 vinculada al freeze y reporte: cerrar solo si todos los criterios pasan o mantener abierto señalando cada fallo; verificar explícitamente worker y política real inactivos
- [x] 4.3 Actualizar README, AI_MODEL, Incrementos y OpenSpec con el resultado real, ejecutar validación estricta y pruebas pertinentes, y hacer commit local final sin push

## Bloqueo tras la única apertura — 2026-11-23

La ejecución real creó `access.json` y terminó `FAILED_TECHNICAL` al encontrar un
formato no permitido por el preprocesado congelado. No produjo las 362
predicciones ni métricas completas. Por ello 3.2, 3.3 y 4.1 permanecen abiertas;
no se reintenta ni se reinterpretan como completadas. G2 permanece abierto y el
worker/política real siguen inactivos.
