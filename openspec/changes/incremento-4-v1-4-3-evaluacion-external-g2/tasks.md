# Tasks

## 1. Compuerta de apertura única

- [x] 1.1 Implementar la autorización v1.4.3 que verifica freeze, pesos, mapa, contrato de preprocesado, protocolo, manifiesto, preflight y sello por sus hashes antes de inferir; probar rechazo individual de cada mutación, conteo distinto, propósito incorrecto y referencia a Sikkim
- [x] 1.2 Implementar la resolución segura de las 350 rutas privadas y cotejo de tamaño/SHA-256 sin seguir enlaces ni salir de la raíz; probar archivo ausente, extra, duplicado, mutado y path traversal
- [x] 1.3 Implementar salida exclusiva con `access.json` atómico previo a inferencia y estados `STARTED`, `COMPLETED` o `FAILED_TECHNICAL`; probar que cualquier salida previa bloquea el reintento sin modificar evidencia

## 2. Inferencia y reporte congelados

- [x] 2.1 Implementar carga CPU independiente del bundle v1.4.2 y decodificación v1.4.3; verificar cuatro logits, modo evaluación, gradientes deshabilitados, MPO frame 0, RGB 224×224, ImageNet, temperatura 0,50 y umbral 0,80
- [x] 2.2 Implementar el mapeo visible que solo publica los dos tizones y transforma `POTATO_HEALTHY`, `OTHER_CROP` y baja confianza en `NO_CONCLUYENTE`; probar fronteras del umbral y abstención de tizón como falso negativo
- [x] 2.3 Implementar predicciones privadas y reporte con métricas por tizón, F1 macro, rechazos, matriz, latencia, RSS y hashes; probar denominadores 50/50/50/200 y todos los límites enteros aprobados
- [x] 2.4 Implementar decisión G2 por conjunción estricta y verificar ramas aprobada, criterio fallido, cardinalidad incompleta y error técnico, manteniendo worker y política inactivos

## 3. Verificación previa y apertura real

- [x] 3.1 Ejecutar suites focalizadas y OpenSpec estricto sin abrir EXTERNAL, documentar comandos/resultados y hacer un commit local del evaluador antes de la apertura; verificar que el commit contiene código y compuertas pero no predicciones
- [x] 3.2 Ejecutar exactamente una vez con red deshabilitada y entradas de solo lectura; verificar 350 predicciones, hashes congelados, cero entrenamiento/calibración/selección y salida inmutable
- [x] 3.3 Validar desde un proceso independiente los hashes de acceso, predicciones, reporte y decisión, y recomputar matriz/métricas para verificar coincidencia exacta

## 4. Evidencia y decisión G2

- [x] 4.1 Publicar evidencia sanitizada con numeradores/denominadores, F1 macro, recall de ambos tizones, rechazo sano/otro cultivo, abstenciones, matriz, latencia, memoria, hashes y limitaciones; verificar ausencia de rutas privadas e imágenes
- [x] 4.2 Registrar la decisión automática inicial: G2 aprobado solo si todos los criterios pasan o `OPEN_EXTERNAL_CRITERIA_FAILED` con cada incumplimiento si alguno falla; actualizar README, AI_MODEL, Incrementos y OpenSpec, ejecutar validación estricta/pruebas pertinentes y hacer commit local sin activar worker, política ni G3. El cierre administrativo posterior corresponde al grupo 5.

## 5. Cierre rechazado y modo demostración

- [x] 5.1 Registrar el acta terminal v1.4.3 con G2 `CLOSED_REJECTED_EXTERNAL`, G3 `CLOSED_NOT_PROMOTED_G2_REJECTED` y el incremento no aprobado para producción; verificar que referencia commits, bundle, sello, matriz, reportes y hashes sin modificar la evidencia histórica
- [x] 5.2 Implementar el adaptador `demo` de abstención contractual y la autorización adicional de arranque real; probar metadatos nulos, `UNSUPPORTED_CLASS`, ausencia de carga de bundle y rechazo de `real` cuando no existe autorización explícita
- [x] 5.3 Configurar el perfil Compose `demo` con un único worker de abstención sin volumen de modelo y mantener `ml-real` bloqueado por defecto; verificar perfiles `demo`, `async-test` y `ml-real` sin puertos internos ni activación simultánea implícita
- [x] 5.4 Registrar el catálogo como contenido histórico no publicable y la política v1.4.3 como no importada/inactiva; verificar hashes y que ningún artefacto atribuye soporte productivo a los dos tizones
- [x] 5.5 Publicar la evidencia final con matriz y límites incumplidos, actualizar README, AI_MODEL, Incrementos, operación y tareas históricas, ejecutar pruebas/OpenSpec estricto y crear un commit local limpio sin push
