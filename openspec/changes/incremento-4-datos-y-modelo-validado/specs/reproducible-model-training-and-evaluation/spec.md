## Purpose

Establecer evidencia reproducible de entrenamiento, identificación de cultivo, calibración y evaluación independiente antes de aprobar clases y artefactos para usuarios.

## ADDED Requirements

### Requirement: Protocolo aprobado antes de experimentar
El proyecto SHALL registrar criterios acordados con el docente antes de seleccionar o entrenar candidatos: definición de clases/cultivos, mínimos por clase y grupo, métricas y límites por clase, negativos, abstención, calibración y recursos. SHALL conservar responsable, fecha y versión. Valores ausentes SHALL bloquear experimentación de aprobación, sin umbrales productivos inventados.

#### Scenario: Criterios incompletos
- **WHEN** falta un criterio de aceptación o su aprobación
- **THEN** las herramientas pueden probarse con fixtures pero ningún experimento se presenta como modelo aprobado

### Requirement: Comparación reproducible y selección independiente
El entrenamiento SHALL ejecutarse en CPU con datos admitidos y registrar versión de datos, código, entorno, semillas, preprocesado y configuración. SHALL comparar una línea base y al menos una alternativa de cultivo/clasificación con particiones y presupuesto comparables, seleccionando solo en validación. La calibración y condiciones de abstención SHALL congelarse antes de abrir test.

#### Scenario: Repetición de experimento
- **WHEN** se repite una ejecución con el mismo manifiesto, configuración y entorno
- **THEN** se obtienen resultados dentro de tolerancias documentadas, con versiones y diferencias registradas

#### Scenario: Intento de ajustar con test
- **WHEN** resultados de TEST motivan cambios de modelo o umbral
- **THEN** se registra un nuevo ciclo y ese test no puede acreditarse como evaluación independiente del modelo ajustado

### Requirement: Evaluación por clase y cobertura honesta
La evaluación SHALL informar cantidades, accuracy, precision, recall y F1 por clase y macro, confusión, calidad de identificación de cultivo, calibración, cobertura/error, abstención, falsos aceptados en negativos, incertidumbre, latencia y memoria con hardware. SHALL aplicar criterios congelados a test independiente y EXTERNAL si existe, sin ocultar fallos bajo promedios. La clase sana no SHALL equivaler a ausencia de toda enfermedad.

#### Scenario: Clase que no cumple
- **WHEN** una clase falla criterios o carece de muestras independientes suficientes
- **THEN** queda no soportada aunque otras clases aprueben y se registra su exclusión

### Requirement: Aprobación de release y cierre real
Un release SHALL vincular pesos/checksums, preprocesado, mapa, dataset, entorno, evaluación, calibración y revisión humana. El cierre SHALL exigir modelo real aprobado con cobertura para ambos cultivos, aceptación explícita de clases excluidas si no aprueban las siete y aceptación integrada real. No SHALL suplirse con fixtures ni CI técnico.

#### Scenario: Ningún modelo cumple
- **WHEN** no existe release que supere criterios o falta aprobación
- **THEN** la promoción y el cierre permanecen pendientes, aunque el código y CI estén completos
