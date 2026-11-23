# Tasks

## 1. Frontera histórica y protocolo G0 v1.4.1

- [x] 1.1 Crear un índice inmutable de v1.4.0 con los commits `bd9df36` y `c0973c5`, hashes de candidatos/reportes/manifiestos y decisión `BLOCKED_NO_CANDIDATE_PASSES_VAL`, y verificar que registra 83/150 para el líder, máximo 7/150 y ausencia de bundle congelado sin reejecutar entrenamiento
- [x] 1.2 Versionar `protocol-g0.v1.4.1.json` con cuatro clases técnicas, conteos TRAIN/VAL, sampler 80×4, dos clases publicables, mínimas VAL heredadas y criterios EXTERNAL intactos, y verificar que referencia el sello Sikkim original sin modificarlo
- [x] 1.3 Registrar en ADR y documentación la aprobación del responsable del 23 de noviembre de 2026, la causa 83/150 y la prohibición de usar TEST/EXTERNAL para seleccionar, y verificar referencias, fechas y hashes con OpenSpec estricto
- [x] 1.4 Implementar el estado de compuertas v1.4.1 que bloquee entrenamiento hasta G0/G1 y contratos válidos, y probar rechazo de protocolo anterior, conteos incompletos, sello alterado y evidencia v1.4.0 mutable

## 2. Contratos de cuatro salidas y dos diagnósticos

- [x] 2.1 Extender `model-bundle.v1.schema.json` para representar `OTHER_CROP`, cuatro salidas técnicas exactas y `publishable_classes` con solo los dos tizones bajo G0 1.4.1, y verificar fixtures positivos y rechazo de mapas incompletos, duplicados o con rechazo publicable
- [x] 2.2 Extender `publication-policy.v1.schema.json` para G0 1.4.1 sin aprobar `POTATO_HEALTHY` ni `OTHER_CROP`, y verificar que las políticas históricas siguen validando y una política v1.4.1 insegura falla
- [x] 2.3 Actualizar validadores, fixtures y documentación de contratos ML para distinguir salida técnica de diagnóstico visible, y ejecutar `scripts/check_contracts.sh` comprobando que no cambian OpenAPI ni eventos públicos

## 3. Manifiesto y admisión G1 v1.4.1

- [x] 3.1 Materializar por referencia el manifiesto privado PlantVillage v1.4.1 desde G1 v1.3.1 y verificar 541/136, 499/129, 80/20 y 503/127 en TRAIN, más 165/42, 153/39, 28/7 y 150/38 en VAL
- [x] 3.2 Validar por archivo SHA-256, fuente, licencia, etiqueta, decisión y `leaf_id`, y probar rechazo de `fallback_*`, duplicados, grupos cruzados, filas TEST, Sikkim y archivos sin derecho aprobado
- [x] 3.3 Verificar que los 68 grupos TEST históricos siguen bloqueados y que el sello/manifiesto Sikkim conserva exactamente sus hashes v1.4.0 sin montarse ni abrirse, registrando la evidencia G1 v1.4.1
- [x] 3.4 Cerrar G1 v1.4.1 solo si reproduce 1.623 fotos/412 grupos TRAIN y 496/126 VAL y todas las pruebas de separación pasan; actualizar tareas y documentación sin declarar entrenamiento ejecutado

## 4. Modelo, sampler y métricas de cuatro clases

- [x] 4.1 Generalizar MobileNetV3-Small, mapa y carga segura a cuatro logits con inicialización aleatoria, y probar que solo los índices de ambos tizones pueden producir una predicción publicable
- [x] 4.2 Implementar el sampler determinista clase → `leaf_id` → imagen con 80 muestras por cada clase y 320 por época, y probar semillas repetibles, exposición de grupos, clases minoritarias y configuraciones inválidas
- [x] 4.3 Adaptar calibración, matriz de confusión y métricas VAL a cuatro logits, y probar que sano/otro cultivo se cuentan como rechazo y toda abstención de tizón como falso negativo
- [x] 4.4 Conservar aumentos conservadores únicamente para `POTATO_HEALTHY` TRAIN con linaje SHA/grupo, y probar que `OTHER_CROP`, VAL, TEST y EXTERNAL no reciben aumentos estocásticos
- [x] 4.5 Documentar comandos CPU sin descargas implícitas para preflight, entrenamiento, reanudación y auditoría v1.4.1, y verificar con fixtures que el contenedor no tiene rutas ni montajes TEST/EXTERNAL

## 5. Entrenamiento y selección exclusiva con VAL

- [ ] 5.1 Hacer un commit local previo al entrenamiento con protocolo, contratos, G1, configuración y código verificados, y registrar su hash en el expediente sin hacer push ni abrir EXTERNAL
- [ ] 5.2 Entrenar desde cero el candidato de cuatro clases usando solo las 1.623 filas TRAIN y 320 exposiciones por época, registrando semilla, manifiestos, dependencias, CPU/RAM, tiempos, pérdidas y exposición efectiva; verificar ausencia de rutas/hashes Sikkim en logs
- [ ] 5.3 Seleccionar época, temperatura, ruta y umbral solo con las 496 filas VAL, y verificar F1 macro ≥0,80, recall por tizón ≥0,80, cobertura ≥0,70, error ≤0,10, sano ≤2/28, otro cultivo ≤7/150 y ECE ≤0,15 con numeradores/denominadores
- [ ] 5.4 Comparar v1.4.1 con v1.4.0 únicamente como evidencia histórica agregada, sin reutilizar pesos/predicciones para selección, y publicar matriz, abstenciones, latencia y memoria dejando explícita cualquier mínima fallida

## 6. Congelamiento previo a EXTERNAL

- [ ] 6.1 Si todas las mínimas VAL pasan, congelar pesos, configuración, mapa técnico/publicable, preprocesado, calibración, umbral, manifiestos, dependencias y comandos; si alguna falla, registrar `BLOCKED_NO_CANDIDATE_PASSES_VAL` sin crear autorización EXTERNAL
- [ ] 6.2 Validar carga independiente del bundle candidato y coincidencia de todos los SHA-256, y probar que sano/otro cultivo/baja confianza producen abstención y nunca un diagnóstico publicable
- [ ] 6.3 Publicar el expediente TRAIN/VAL v1.4.1 y actualizar OpenSpec, README, AI_MODEL e Incrementos, verificando que no contiene predicciones ni métricas Sikkim y que G2 sigue abierto antes de la revisión externa

## 7. EXTERNAL y G2 condicionados

- [ ] 7.1 Habilitar una única apertura transaccional de Sikkim solo para un bundle v1.4.1 completamente congelado, y probar que toda apertura previa, repetida o con hash distinto se rechaza
- [ ] 7.2 Ejecutar una sola evaluación EXTERNAL y generar métricas con los denominadores G0 existentes, verificando F1/recall de tizones, rechazo sano/otro cultivo, calibración, latencia, memoria y limitación de independencia por imagen
- [ ] 7.3 Registrar v1.4.1 aprobado o no aprobado sin ajustar con EXTERNAL y obtener revisión G2 solo si todos los criterios pasan; verificar que el resultado no activa automáticamente el worker

## 8. Integración posterior a G2

- [ ] 8.1 Integrar el bundle en modo inactivo únicamente después de G2, y probar que el adaptador solo emite ambos tizones o abstención con `reason_code`, sin exponer las clases técnicas de rechazo
- [ ] 8.2 Ejecutar activación, retiro, rollback y aceptación G3 con controles distintos de Sikkim, verificando auditoría, concurrencia, redelivery, acceso, latencia, memoria y catálogo revisado antes de declarar el incremento publicable
