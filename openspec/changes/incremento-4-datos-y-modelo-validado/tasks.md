# Tasks

Plan para Antigravity. Estado rectificado el 2026-10-15: las casillas abiertas incluyen herramientas parciales y aprobaciones sin evidencia; una prueba con fixtures no completa la tarea real. Leer design.md D1–D7 y los cinco deltas antes de aplicar. G0/G1/G2/G3 son puertas verificables, no valores ficticios de aprobación. El responsable del proyecto aporta decisiones de permisos y revisión docente/agronómica; el agente prepara herramientas y evidencia, sin suplantar aprobaciones.

Dependencias: grupo 1 define G0; grupo 3 cierra G1; grupos 4–5 requieren G0/G1 para experimentos reales; grupo 5 cierra G2; grupo 9 cierra G3. Herramientas de 2–8 pueden desarrollarse con fixtures mientras faltan datos, respetando contratos, pero ninguna tarea de datos, entrenamiento real o aprobación puede marcarse cumplida por un fixture. No ejecutar tareas de producción ni descargas masivas durante la planificación.

## 1. Selección y aprobación de datos y criterios

- [ ] 1.1 Registrar ADR-0009 para D1–D7 y matriz RF-07/08/09 → capacidad → evidencia; verificar coherencia con ADR-0008 y ausencia de cambios en propiedad de datos, estados o autorización.
- [ ] 1.2 Preparar expediente de cada fuente candidata con revisión exacta, uso previsto, permiso/atribución, restricciones y responsable; obtener revisión del proyecto y registrar admitida/pendiente/excluida con evidencia, sin descargar imágenes de fuentes no admitidas.
- [ ] 1.3 Obtener revisión de las siete definiciones y mappings (especialmente MAIZE_LEAF_BLIGHT y roya), conservar códigos reservados y documentar etiquetas excluidas; verificar correspondencia cultivo/clase contra contratos y evidencia fechada de revisión.
- [ ] 1.4 Preparar y obtener aprobación docente del protocolo G0 con mínimos por clase/grupo, métricas y límites de aceptación, cobertura/error/abstención/negativos/calibración y presupuesto CPU; verificar campos numéricos completos, responsable/fecha y versión antes del primer experimento de selección. No marcar por crear una plantilla vacía.
- [x] 1.5 Documentar disponibilidad o ausencia del conjunto externo autorizado de Ayacucho y de revisión de catálogo para clases candidatas; verificar evidencia de disponibilidad o límites explícitos sin prometer validación externa.

## 2. Contratos y herramientas reproducibles

- [x] 2.1 Definir contratos versionados de bundle y política en contracts/ml según D5/D6, incluyendo aprobación y calibración escalar compatible con raw_score; probar fixtures válidos y rechazo de hashes/mapas/versiones/rangos inválidos con validador de contratos.
- [x] 2.2 Fijar evolución aditiva del resultado HTTP para confianza estimada y snapshot de política, manteniendo históricos y raw_score; actualizar esquemas compartidos, OpenAPI, ejemplos/inventario y cliente tipado, verificando respuestas nuevas/antiguas y que Analyzed v1 no cambia semántica.
- [ ] 2.3 Crear paquete ML CPU con dependencias bloqueadas y comandos de entrenamiento/evaluación/empaquetado, procedencia de pesos base y configuración versionada; comprobar instalación desde cero, importación y ejecución mínima sin GPU ni descarga implícita, y documentar comandos.

## 3. Curación y particiones reales

- [x] 3.1 Implementar importación explícita desde fuente admitida o ruta privada con límites, resolución segura de rutas, decodificación y hash de bytes; probar archivos válidos, corruptos, traversal y fuente pendiente, dejando cuarentena/decisiones y sin fotos en Git.
- [x] 3.2 Implementar inventario de duplicados exactos y candidatos visuales entre fuentes, revisión y grupos globales de relaciones; probar copias, recortes/vistas relacionados, grupo fuente conservador y reporte de incertidumbre sin declarar independencia automática.
- [ ] 3.3 Extender validación de manifiesto real sin debilitar DATA-01…03, producir versiones nuevas y registro privado de admisión/exclusión; verificar conteos reales por clase/contexto, equivalencia con bytes y rechazo de etiquetas no revisadas o fixtures como datos reales.
- [x] 3.4 Implementar particionado por grupos y sello de TEST/EXTERNAL con registro de accesos; probar los seis pares de particiones, casi duplicados revisados, alteración del sello y augmentations exclusivas de TRAIN, documentando reproducción sin copiar fotos a reportes.
- [ ] 3.5 Construir manifiesto separado de negativos autorizados y revisión de calidad/ambigüedad, con separación global de grupos; verificar casos fuera de cultivo/cobertura sin añadir clases al contrato V1.
- [ ] 3.6 Ejecutar curación y particionado de datos reales tras admisión; entregar G1 con hashes, cantidades, revisiones y mínimos G0 satisfechos, o registrar bloqueos y mantener tarea pendiente. Verificar manifiesto conjunto mediante herramientas de 3.1–3.5.

## 4. Entrenamiento y comparación

- [ ] 4.1 Implementar preprocesado único reutilizable entre entrenamiento/inferencia, transformaciones TRAIN y medición CPU; probar forma/color/orientación, entradas inválidas y equivalencia de tensor para el mismo archivo, documentando límites.
- [ ] 4.2 Implementar línea base conjunta cultivo/clase con configuración/semillas, checkpoints y procedencia de pesos; probar ejecución mínima reproducible con datos sintéticos rotulados sin confundirla con entrenamiento real.
- [ ] 4.3 Implementar alternativa viable de cultivo más clasificación y controles de rechazo de dominio/calidad; probar cultivo desconocido/ambiguo y selección por VAL, sin inferir rechazo válido solo por argmax de siete clases.
- [ ] 4.4 Ejecutar línea base real sobre G1 con G0 aprobado y registrar métricas VAL, hardware, tiempo, memoria, versiones y comandos; verificar repetición dentro de tolerancias del protocolo y que TEST no se usa.
- [ ] 4.5 Ejecutar alternativa real bajo particiones/presupuesto comparables y seleccionar por criterios G0 en VAL; entregar comparación trazable y justificación sin afirmar aún aprobación sobre test.

## 5. Calibración, evaluación y release

- [ ] 5.1 Implementar calibración escalar por clase y umbrales de publicación a partir de raw_score en VAL, junto con parámetros de rechazo técnico; probar score bajo/igual/superior al umbral, valores no finitos y ausencia de calibrador sin fallback al 0.9 sintético.
- [ ] 5.2 Congelar modelo, calibración, umbrales y protocolo antes de abrir TEST; verificar registro/hash y control de acceso, documentando que cambios motivados por TEST exigen otro ciclo independiente.
- [ ] 5.3 Implementar reporte de accuracy, precision/recall/F1 por clase/macro, cultivo, confusión, calibración, cobertura/error, abstención, negativos, incertidumbre, latencia y memoria; comprobar cálculos con casos conocidos y tamaños cero sin producir métricas ficticias.
- [ ] 5.4 Ejecutar evaluación real en TEST y EXTERNAL si está disponible; contrastar cada criterio G0 y registrar clases aprobadas/excluidas y límites, sin ocultar fallo de clase en promedios ni alegar generalización no medida.
- [ ] 5.5 Empaquetar pesos/preprocesado/mapa/versiones/checksums/evaluación y obtener revisión G2; verificar esquema y carga independiente, cobertura de ambos cultivos y aprobación explícita de reducción de clases si corresponde. Si ningún modelo cumple, mantener tarea y cierre pendientes.

## 6. Worker con artefacto real

- [ ] 6.1 Implementar cargador seguro de bundle autorizado e inmutable y adaptador de inferencia; probar checksum erróneo, rutas peligrosas, formato incompatible, tensores no finitos y ausencia de pesos sin ejecución arbitraria ni descarga por solicitud.
- [ ] 6.2 Sustituir llamada directa al simulador por adaptador seleccionado al arranque, manteniendo su doble guardia; probar modo real con runtime CPU y fixture tensorial, rechazo de fallback y metadatos reales/null según ejecución.
- [ ] 6.3 Integrar cómputo acotado con heartbeat independiente y persistencia existente; probar timeout, pérdida de lease, redelivery y crash antes/después de commit con un resultado lógico, conservando presupuesto de recuperación y permisos internos.
- [ ] 6.4 Añadir perfil ml-real con release de solo lectura y arranque validado previo a consumo; probar Compose desde checkout sin .env, aislamiento de async-test, ausencia de puertos internos y falta/corrupción de artefacto. Documentar activación, parada y diagnóstico operativo.

## 7. Políticas de publicación en Diagnosis

- [x] 7.1 Añadir migración aditiva de políticas inmutables, activación y snapshot/confianza de resultado; probar upgrade e históricos sin calibración inventada, rollback aislado y prohibición de reescribir terminales, documentando límites de downgrade.
- [ ] 7.2 Implementar importación/activación/retiro por CLI con dry-run por defecto, actor/motivo y auditoría transaccional; probar política inválida, evidencia ausente, repetición, fallo de auditoría y actualización atómica de soporte, conservando prohibición de PATCH público.
- [x] 7.3 Integrar decisión por tupla exacta modelo/dataset y política activa, calibración/umbral y catálogo revisado; probar versiones desconocidas/retiradas, clase no aprobada, score frontera, catálogo ausente y precedencia vigente de reason_code.
- [ ] 7.4 Serializar retiro/activación contra finalización y guardar snapshot de política/confianza junto al catálogo en transacción de Finished; probar concurrencia PostgreSQL, rollback e historia inmutable tras cambios, documentando trazabilidad.
- [ ] 7.5 Publicar orientación del catálogo para clases admitidas mediante revisión humana y APIs existentes, sin dosis/tratamientos inventados; verificar fuentes/aprobación y que ausencia de contenido revisado mantiene CATALOG_UNAVAILABLE.

## 8. CI y operación verificables

- [x] 8.1 Incorporar etapa obligatoria ml-contracts-and-runtime en plan y controles CI con fixture tensorial identificado; comprobar fallo ante paquete/política corruptos, checkout limpio, locks y conservación de todas las etapas anteriores sin GPU/dataset privado.
- [ ] 8.2 Implementar comando de aceptación real separado que exija release/dataset aprobados y conserve hashes/comandos/reportes sin secretos; probar rechazo de fixture como evidencia real, artefacto alterado y limpieza de recursos propios.
- [ ] 8.3 Documentar en ml/README, AI_MODEL y operación los comandos de G0–G3, promoción/retirada y rollback de D7/Migration Plan; ejecutar ensayo con release de prueba, verificando que ausencia de versión previa nunca activa simulación ni borra historia.

## 9. Aceptación integrada y cierre

- [ ] 9.1 Ejecutar aceptación con release real G2 y catálogo revisado: carga sin cultivo manual para ambos cultivos, predicción/abstención, negativos, estado/historial y propietario ajeno 404; conservar evidencia real sin selección pública de escenarios ni fixtures agronómicos inventados.
- [ ] 9.2 Repetir fallos representativos con runtime real (restart, heartbeat, lease obsoleto, redelivery) y medir latencia/memoria CPU bajo carga definida; verificar un resultado lógico y reportar diferencias frente a metas, sin prometer capacidad no medida.
- [ ] 9.3 Ejecutar CI completo local y registrar ejecución remota sobre revisión publicada; verificar todas las etapas y limpieza, diferenciando resultados técnicos de G2/G3 y sin marcar éxito remoto por ejecución local.
- [ ] 9.4 Revisar G0–G3 y matriz requisito/evidencia, actualizar README/Incrementos y límites de cobertura, sincronizar deltas y archivar solo con aceptación real aprobada; verificar OpenSpec estricto y tareas completas sin pendientes humanos ocultos. Incremento 5 permanece separado.


## Corrección de la revisión (2026-10-15)

Se retira el conteo anterior 36/40. Una casilla reabierta puede conservar código parcial;
no se descarta ese trabajo, pero no acredita el criterio completo.

- 1.2–1.4: fuentes y mappings pendientes; protocolo numérico es borrador sin aprobación.
- 2.3, 4.1–4.3, 5.1–5.5, 6.1–6.4: implementar pipeline y runtime reales, compartir
  preprocesado, corregir formatos/arquitecturas y medir; la CLI hoy rechaza operaciones
  de release y el modo real no arranca. No basta aportar imágenes.
- 3.3 y 3.5: no hay conteos, negativos ni revisión real demostrados.
- 7.2 y 7.4: corregido retiro de política inactiva con regresión; aún se requiere
  completar validación de promociones y concurrencia real antes de cerrar estas tareas.
- 7.5: retiradas semillas de recomendaciones y revisores no acreditados; esperar paquete revisado.
- 8.2 y 9.1–9.4: componentes con mocks no son G3; CI local histórico no acredita CI
  remoto ni evaluación agronómica. Repetir aceptación completa al disponer de implementación y datos.

Ver [evidencia de corrección](../../../docs/evidence/INCREMENTO-4-CORRECCION.md).
