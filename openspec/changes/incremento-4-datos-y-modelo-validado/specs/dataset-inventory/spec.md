## ADDED Requirements

### Requirement: DATA-04 Admisión y curación de imágenes reales
El proyecto SHALL admitir imágenes únicamente tras revisión documentada de permiso para el uso previsto, revisión exacta de fuente, etiquetas y correspondencia con códigos estables. SHALL verificar bytes, hash, decodificación y cantidades locales reales, conservando motivos de exclusión/cuarentena y responsable/fecha de decisión. Los inventarios previos SHALL permanecer trazables; un validador no SHALL otorgar permisos ni aprobación científica.

#### Scenario: Fuente pendiente o etiqueta no resuelta
- **WHEN** se intenta incluir imágenes de una fuente sin permiso demostrado o con correspondencia de etiqueta pendiente
- **THEN** la admisión falla y esas imágenes no pueden alimentar entrenamiento, calibración ni evaluación de aprobación

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

#### Scenario: No hay evaluación externa
- **WHEN** no se dispone de imágenes autorizadas de Ayacucho
- **THEN** el reporte indica EXTERNAL no disponible y no atribuye generalización local demostrada
