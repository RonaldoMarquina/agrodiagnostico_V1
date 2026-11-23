# Tasks

## 1. Frontera histórica e inventario reproducible

- [ ] 1.1 Crear un índice inmutable del ciclo v1.3.2 que referencie los commits `94b3d42` y `5f2d623`, bundle, configuración, TEST y reporte con sus SHA-256, y verificar que registra 8/32 publicaciones sanas erróneas, 24/32 rechazos y estado no aprobado sin ejecutar nuevamente TEST
- [x] 1.2 Verificar por manifiesto que PlantVillage TRAIN/VAL conserva sus `leaf_id`, hashes, derechos y separación histórica, y probar que ningún `fallback_*` o grupo del TEST v1.3.2 puede incorporarse a v1.4.0
- [x] 1.3 Auditar el depósito primario Sikkim v1 y verificar DOI `10.17632/4wz7zbk635.1`, CC BY 4.0, ZIP SHA-256 `5288c8f9d4628049ae1f827c961dc3df97167de294cec020cbce0bc19b2574dc`, 42 temprano, 76 tardío, 50 sanas, 194 de otro cultivo, 362 hashes únicos, cero duplicados exactos y resolución visual de las alertas dHash
- [x] 1.4 Materializar el registro privado de las 362 imágenes Sikkim con ruta, SHA-256, etiqueta fuente, identidad por imagen, decisión, licencia, atribución y comprobante, y verificar que reproduce los conteos y no afirma independencia por planta
- [x] 1.5 Añadir pruebas negativas para impedir imágenes de búsquedas web sin licencia aplicable, autor, enlace original y SHA-256, y documentar que una URL pública no acredita derechos

## 2. Protocolo G0 v1.4.0

- [x] 2.1 Registrar la aprobación del responsable del 22 de noviembre de 2026 para PlantVillage TRAIN/VAL, Sikkim EXTERNAL y los límites: F1 macro ≥0,75; recall temprano ≥32/42; recall tardío ≥57/76; sanas publicadas ≤5/50 y rechazadas ≥45/50; otro cultivo publicado ≤9/194
- [x] 2.2 Versionar el protocolo ejecutable G0 v1.4.0 y alinear ADR, taxonomía y documentación, verificando hashes y referencias cruzadas y conservando intactos protocolos y resultados históricos
- [x] 2.3 Implementar la compuerta que bloquee entrenamiento mientras PlantVillage TRAIN/VAL y Sikkim EXTERNAL no estén admitidos, separados y sellados, y verificar casos positivos y negativos automatizados
- [x] 2.4 Probar el cálculo G0 con denominadores fijos, incluyendo abstención de tizón como falso negativo, confusión entre tizones, fallos de inferencia y límites enteros 32/42, 57/76, 5/50, 45/50 y 9/194

## 3. Admisión G1 y aislamiento de EXTERNAL

- [x] 3.1 Admitir por referencia inmutable PlantVillage únicamente para TRAIN/VAL y verificar que las tres clases técnicas y `OTHER_CROP` de validación conservan los manifiestos, grupos y hashes aprobados
- [x] 3.2 Admitir Sikkim únicamente como EXTERNAL y verificar por archivo licencia CC BY 4.0, atribución, etiqueta, ruta, SHA-256 y decisión sin crear identificadores de planta o sesión
- [x] 3.3 Reproducir la deduplicación exacta y perceptual de Sikkim contra sí mismo y las 6.059 imágenes locales, y verificar que las 20 alertas dHash quedan identificadas y resueltas visualmente sin excluir falsos duplicados
- [x] 3.4 Sellar las 362 imágenes Sikkim como una sola partición EXTERNAL con SHA-256 del manifiesto y controles de acceso, y verificar que entrenamiento, VAL, calibración, comparación y selección de umbral no pueden leerlas
- [x] 3.5 Documentar la revisión G1 con conteos, derechos, hashes, limitación de independencia por imagen y sello EXTERNAL, y cerrar G1 solo si el validador reproduce toda la topología G0

## 4. Entrenamiento balanceado y aumentos seguros

- [x] 4.1 Extender la configuración reproducible para tres clases técnicas, ponderación de pérdida y muestreo balanceado consciente de `leaf_id`, y verificar que cada ejecución registra semilla, conteos originales, pesos o probabilidades y exposición efectiva por clase
- [x] 4.2 Implementar aumentos configurables de `POTATO_HEALTHY` exclusivamente en TRAIN con vínculo al original y `leaf_id`, y verificar que no elevan conteos de originales/grupos y que VAL/EXTERNAL rechazan cualquier aumento
- [x] 4.3 Añadir pruebas del cargador y sampler que demuestren balance efectivo sin tratar vistas de una misma hoja como grupos independientes, incluyendo clases minoritarias, semillas repetibles y configuraciones inválidas
- [ ] 4.4 Documentar comandos CPU sin descargas implícitas para entrenar, reanudar y auditar cada estrategia, y verificar con fixtures que no existe acceso a EXTERNAL ni se presentan fixtures como rendimiento agronómico

## 5. Comparación exclusiva con PlantVillage TRAIN/VAL

- [x] 5.1 Entrenar los candidatos aprobados usando solo PlantVillage TRAIN, registrando dependencias, manifiestos, semillas, CPU/RAM, tiempos y memoria, y verificar que el log no contiene rutas ni hashes Sikkim
- [x] 5.2 Evaluar candidatos solo con PlantVillage VAL y comparar F1/recall de tizones, cobertura, error selectivo, rechazo sano, rechazo de otro cultivo, calibración, latencia y memoria con numeradores y denominadores, verificando igualdad de particiones y presupuesto
- [ ] 5.3 Seleccionar arquitectura, balance, calibración, política de rechazo y umbral únicamente con VAL, y verificar que `POTATO_HEALTHY` y `OTHER_CROP` nunca son diagnósticos publicables y que una abstención de tizón cuenta como falso negativo
- [ ] 5.4 Congelar el candidato v1.4.0 con pesos, configuración, mapa, preprocesado, calibración, umbral, manifiestos, dependencias y comandos, y verificar carga independiente y coincidencia de todos los SHA-256 antes de habilitar EXTERNAL
- [x] 5.5 Publicar el expediente TRAIN/VAL y la decisión de congelamiento, verificando que compara estrategias, conserva limitaciones y no contiene predicciones ni métricas Sikkim

## 6. EXTERNAL único y revisión G2

- [ ] 6.1 Ejecutar una sola evaluación de Sikkim EXTERNAL con el bundle congelado y verificar mediante registro transaccional que el manifiesto no se abrió antes ni se evalúa una segunda vez
- [ ] 6.2 Generar el reporte EXTERNAL con F1 macro de los tizones, recall 32/42 y 57/76, sanas publicadas y rechazadas sobre 50, otro cultivo publicado sobre 194, matriz de confusión, abstenciones, calibración, latencia y memoria, verificando todos los numeradores y denominadores contra G0
- [ ] 6.3 Declarar en el reporte que la unidad es imagen única y que no existe independencia verificada por planta, y verificar que ninguna conclusión atribuye generalización por planta, parcela, sesión, Ayacucho u otras enfermedades
- [ ] 6.4 Registrar v1.4.0 como aprobado o no aprobado sin ajustar pesos, calibración ni umbral con EXTERNAL, y verificar que un solo criterio fallido mantiene G2 abierto y bloquea promoción
- [ ] 6.5 Si todos los criterios pasan, validar carga privada independiente y obtener revisión G2 del responsable con versión y hashes; verificar que la aprobación no activa automáticamente el worker

## 7. Integración condicionada y aceptación

- [ ] 7.1 Integrar el bundle v1.4.0 en modo inactivo solo después de G2, y verificar que el adaptador publica únicamente los dos tizones y transforma papa sana, otro cultivo y baja confianza en `NO_CONCLUYENTE` con `reason_code`
- [ ] 7.2 Probar activación, retiro y rollback auditados sin modificar el historial de bundles, y verificar concurrencia con diagnósticos en curso y conservación de la política previamente activa
- [ ] 7.3 Ejecutar aceptación end-to-end y G3 con controles distintos de Sikkim EXTERNAL, verificando acceso, redelivery, latencia, memoria y ausencia de recomendaciones no revisadas antes de declarar el incremento listo para publicación
