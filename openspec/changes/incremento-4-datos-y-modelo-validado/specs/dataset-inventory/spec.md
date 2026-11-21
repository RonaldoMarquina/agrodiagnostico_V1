## ADDED Requirements

### Requirement: DATA-04 Admisión y curación de imágenes reales
El proyecto SHALL admitir imágenes únicamente tras revisión documentada de permiso para el uso previsto, revisión exacta de fuente, etiquetas y correspondencia con códigos estables. Para el lote PlantVillage del piloto v1.2.0, la procedencia experta publicada por la fuente junto con control interno de calidad por archivo, revisión visual muestral de ambigüedad y exclusión individual de dudas SHALL satisfacer la revisión de etiqueta, conservando la distinción frente a una nueva evaluación agronómica independiente. SHALL verificar bytes, hash, decodificación y cantidades locales reales, conservando motivos de exclusión/cuarentena y responsable/fecha de decisión. Los inventarios previos SHALL permanecer trazables; un validador no SHALL otorgar permisos ni aprobación científica.

#### Scenario: Fuente pendiente o etiqueta no resuelta
- **WHEN** se intenta incluir imágenes de una fuente sin permiso demostrado o con correspondencia de etiqueta pendiente
- **THEN** la admisión falla y esas imágenes no pueden alimentar entrenamiento, calibración ni evaluación de aprobación

#### Scenario: Fuente priorizada por el responsable
- **WHEN** PlantVillage se prioriza como candidata inicial o PlantDoc/PlantSeg se proponen para evaluación complementaria
- **THEN** conservan estado pendiente hasta verificar revisión exacta, licencia aplicable, atribución, restricciones y derechos de las imágenes; la prioridad no concede permiso de uso ni convierte las dos etiquetas del piloto en clases soportadas

#### Scenario: Etiqueta genérica sin equivalencia específica
- **WHEN** una fuente presenta `Corn rust leaf`, `corn rust` o `Corn leaf blight` para los códigos históricos `MAIZE_COMMON_RUST` o `MAIZE_LEAF_BLIGHT`
- **THEN** el mapeo automático permanece `UNMAPPED`, la imagen no se incorpora por esa etiqueta y se exige revisión agronómica individual antes de una decisión de admisión

#### Scenario: Bytes corruptos o distintos
- **WHEN** el contenido no decodifica o no coincide con el hash declarado
- **THEN** se excluye del manifiesto admitido con motivo verificable sin corregir silenciosamente la evidencia

### Requirement: DATA-05 Particiones reales independientes y selladas
El proceso SHALL agrupar imágenes relacionadas entre todas las fuentes mediante procedencia, duplicados exactos y revisión de similitud visual antes de particionar. SHALL conservar en cuarentena casos sin separación fiable, aplicar augmentations solo a TRAIN y congelar hashes de TRAIN/VAL/TEST/EXTERNAL. TEST y EXTERNAL SHALL NOT usarse para seleccionar modelos, calibración o umbrales. Negativos autorizados SHALL tener manifiesto separado y cumplir la misma separación y privacidad sin crear enfermedades o clase NO_CONCLUYENTE.

#### Scenario: Casi duplicados en fuentes distintas
- **WHEN** revisión confirma que dos imágenes son vistas o derivados del mismo origen
- **THEN** comparten grupo global y no cruzan particiones aunque tengan distinto hash o fuente

#### Scenario: Modificación del test sellado
- **WHEN** cambia cualquier imagen, etiqueta o partición del test congelado
- **THEN** el control rechaza su uso como la misma versión y exige nuevo registro sin sobrescribir evidencia previa

#### Scenario: Nuevo ciclo tras ver resultados del TEST anterior
- **WHEN** un fallo de aceptación exige modificar el modelo o su regla de abstención
- **THEN** el TEST ya abierto no acredita independencia del nuevo ciclo; se prepara una colección TEST nueva, sin grupos usados para entrenar o ajustar ni imágenes expuestas por la aceptación, con derechos, revisión y sellado propios; papa sana permanece en manifiesto negativo separado y no se declara admitida por inventario o licencia pública solamente

#### Scenario: No hay evaluación externa
- **WHEN** no se dispone de imágenes autorizadas de Ayacucho
- **THEN** el reporte indica EXTERNAL no disponible y no atribuye generalización local demostrada
