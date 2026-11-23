# Tasks

## 1. Frontera histórica y reutilización de G0/G1

- [x] 1.1 Crear el índice v1.4.2 que referencie por hash G0/G1 v1.4.1, `7377819`, `e709f27` y `train-val-result.v1.4.1.json`, y verificar que una mutación o ausencia bloquea el ciclo
- [x] 1.2 Registrar en ADR y evidencia que G0, conteos, cuatro clases, sampler, aumentos, publicabilidad y mínimas VAL no cambian, y verificar OpenSpec estricto sin modificar artefactos v1.4.1
- [x] 1.3 Implementar una raíz privada v1.4.2 distinta y probar que no puede escribir bajo salidas, pesos, predicciones o reportes v1.4.1

## 2. Procedencia y admisión del checkpoint ImageNet

- [x] 2.1 Implementar el comando explícito de adquisición que solo permita la URL oficial `mobilenet_v3_small-047dcff4.pth`, TLS verificado y destino temporal, y probar rechazo de host, redirección final, nombre y descarga parcial distintos
- [x] 2.2 Descargar el checkpoint antes de entrenar y registrar URL solicitada/final, fecha, TorchVision `0.29.2+cpu`, enum `IMAGENET1K_V1`, receta, transformación de referencia, tamaño y SHA-256 completo; verificar `10.306.551` bytes y `047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f`
- [x] 2.3 Registrar BSD-3-Clause para el código TorchVision y las advertencias/condiciones derivadas de modelos preentrenados e ImageNet, limitar el uso a investigación/educación no comercial y verificar que el registro no atribuye licencia BSD al checkpoint ni autoriza redistribución
- [x] 2.4 Implementar validación offline con `weights_only=True`, mapa CPU y claves/dimensiones esperadas; probar rechazo de pickle ejecutable, tensor no finito, clasificador o backbone incompleto y SHA alterado
- [x] 2.5 Mover el checkpoint admitido a almacenamiento privado de solo lectura y generar su expediente inmutable; verificar que el entrenamiento falla si hay red, si el peso no está montado o si difiere del registro

## 3. Candidato transferido de cuatro salidas

- [x] 3.1 Construir MobileNetV3-Small con el checkpoint completo BatchNorm, reemplazar después la cabeza por cuatro salidas ordenadas y verificar que temprano/tardío son las únicas publicables y sano/otro producen abstención
- [x] 3.2 Implementar fase HEAD de 3 épocas con backbone y BatchNorm congelados, AdamW `lr=1e-3` solo para la cabeza y sampler 80×4; probar parámetros entrenables, hash del backbone y 320 exposiciones por época
- [x] 3.3 Implementar fase FINE_TUNE de 12 épocas descongelando únicamente los últimos tres bloques y la cabeza, con `lr=1e-5`/`1e-4` y BatchNorm congelado; probar grupos del optimizador, modos train/eval y ausencia de gradientes fuera del alcance
- [x] 3.4 Reutilizar exactamente el preprocesado v1.4.1 y aumentos solo para `POTATO_HEALTHY` TRAIN, y probar que `OTHER_CROP`, VAL, TEST y EXTERNAL nunca reciben aumento ni transformación seleccionada con datos
- [x] 3.5 Adaptar checkpoints, carga segura, métricas y comandos CPU a ambas fases, y verificar reanudación determinista por reinicio, semilla, dependencias, pérdidas, tiempos, memoria y exposición efectiva

## 4. Preflight aislado y commit previo

- [x] 4.1 Validar los manifiestos privados existentes con 1.623/412 TRAIN y 496/126 VAL, incluido `OTHER_CROP` 503/127 y 150/38, y probar rechazo de filas, grupos o SHA distintos sin volver a admitir datos
- [x] 4.2 Implementar la compuerta que prohíbe rutas, montajes, hashes, predicciones o métricas de Sikkim y TEST histórico, y probar que falla antes de leer bytes protegidos
- [x] 4.3 Ejecutar pruebas de procedencia, carga segura, cuatro logits, abstención, fases, sampler, aumentos, manifiestos y aislamiento; verificar contratos/OpenSpec sin cambios HTTP o de eventos
- [x] 4.4 Presentar el expediente exacto del checkpoint y el diseño ejecutable al responsable, hacer commit local de código/configuración/evidencia antes de entrenar y registrar su hash sin push

## 5. Entrenamiento y selección exclusiva con VAL

- [ ] 5.1 Ejecutar una sola corrida pre-registrada HEAD+FINE_TUNE usando solo TRAIN, checkpoint admitido y contenedor sin red; verificar 15 épocas, 320 exposiciones por época, cuatro clases y cero acceso histórico/EXTERNAL
- [ ] 5.2 Evaluar cada época solo sobre las 496 filas VAL y seleccionar época, temperatura y umbral con los límites vigentes; verificar numeradores/denominadores, matriz, abstenciones, ECE, latencia y memoria
- [ ] 5.3 Comparar contra v1.4.1 únicamente mediante su resumen histórico fijado, y verificar que no se cargaron pesos/predicciones previos ni se reoptimizó su política
- [ ] 5.4 Publicar el expediente TRAIN/VAL v1.4.2 con recall temprano/tardío, sano ≤2/28, otro cultivo ≤7/150 y restantes mínimas, dejando explícito todo incumplimiento sin ajustar tasas, épocas o política después de ver VAL

## 6. Congelamiento condicionado sin abrir EXTERNAL

- [ ] 6.1 Si todas las mínimas pasan, congelar checkpoint base, pesos ajustados, configuración, mapa, preprocesado, fases, calibración, umbral, manifiestos, dependencias y comandos; si alguna falla, registrar `BLOCKED_NO_CANDIDATE_PASSES_VAL` sin bundle habilitante
- [ ] 6.2 Validar carga independiente y todos los SHA-256 del candidato congelado, y probar que sano, otro cultivo y baja confianza nunca producen diagnósticos publicables
- [ ] 6.3 Actualizar OpenSpec, README, AI_MODEL e Incrementos con el resultado real y verificar que Sikkim sigue sellado, TEST intacto, G2 abierto y worker inactivo
