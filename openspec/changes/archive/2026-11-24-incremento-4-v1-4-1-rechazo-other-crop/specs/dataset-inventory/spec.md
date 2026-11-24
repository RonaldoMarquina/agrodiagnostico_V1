# Spec Delta

## ADDED Requirements

### Requirement: DATA-04 Topología PlantVillage v1.4.1 de cuatro clases técnicas

El inventario SHALL registrar `OTHER_CROP` como estrato técnico de rechazo, no como enfermedad soportada ni como sustituto de `NO_CONCLUYENTE`. Para v1.4.1 SHALL admitir de la revisión PlantVillage fijada 503 imágenes / 127 grupos en TRAIN y 150 imágenes / 38 grupos en VAL, además de los estratos de papa ya admitidos. Cada fila SHALL conservar SHA-256, etiqueta fuente, licencia aplicable, ruta, decisión y `leaf_id`; TRAIN y VAL SHALL permanecer disjuntos por SHA-256 y grupo.

#### Scenario: Inventario v1.4.1 completo

- **WHEN** se materializa el manifiesto PlantVillage v1.4.1
- **THEN** `OTHER_CROP` reproduce 503/127 en TRAIN y 150/38 en VAL, sin `fallback_*`, sin duplicados y sin grupos compartidos

#### Scenario: Estado visible de otro cultivo

- **WHEN** un consumidor consulta la taxonomía del ciclo
- **THEN** `OTHER_CROP` figura como salida técnica no publicable que deriva a `NO_CONCLUYENTE`, y no como octava enfermedad o recomendación de catálogo

### Requirement: DATA-05 Aislamiento de evidencia no seleccionable

El manifiesto v1.4.1 SHALL derivarse únicamente de PlantVillage TRAIN/VAL ya admitido. SHALL excluir todo archivo, hash, grupo, predicción o métrica del TEST histórico y de Sikkim EXTERNAL; el sello EXTERNAL v1.4.0 SHALL permanecer inmutable hasta que exista un bundle v1.4.1 completamente congelado.

#### Scenario: Derivación permitida

- **WHEN** el validador compara v1.4.1 con el expediente G1 previo
- **THEN** cada fila se resuelve a una imagen PlantVillage admitida y su partición/grupo original, sin incorporar nuevas fuentes

#### Scenario: Mezcla con TEST o EXTERNAL

- **WHEN** una fila v1.4.1 referencia el TEST histórico o Sikkim, o el sello EXTERNAL cambia
- **THEN** la admisión G1 v1.4.1 falla antes del entrenamiento
