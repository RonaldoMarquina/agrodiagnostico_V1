# Spec Delta

## Purpose

Establecer un ciclo independiente que detecte hojas de papa sana como condición fuera de las dos enfermedades publicables, con rechazo medible antes de reintentar la aceptación integrada.

## ADDED Requirements

### Requirement: G0 v1.3.0 previo a los experimentos
El proyecto SHALL versionar y obtener aprobación del responsable para los mínimos de imágenes y grupos por estrato, las métricas, los límites de rechazo y el presupuesto CPU antes de entrenar o abrir el nuevo TEST. La elección de preparar este ciclo SHALL NOT contar como aprobación del protocolo numérico propuesto.

#### Scenario: Protocolo todavía propuesto
- **WHEN** G0 v1.3.0 no tiene aprobación explícita del responsable
- **THEN** ningún entrenamiento real ni apertura del nuevo TEST puede acreditarse para esta versión.

### Requirement: Papa sana como objetivo técnico de rechazo
El piloto SHALL conservar solo `POTATO_EARLY_BLIGHT` y `POTATO_LATE_BLIGHT` como diagnósticos publicables. Una predicción técnica `POTATO_HEALTHY` SHALL producir `NO_CONCLUYENTE` con un `reason_code` contractual de clase fuera de cobertura; SHALL NOT publicar `POTATO_HEALTHY` como diagnóstico ni afirmar ausencia de enfermedad. Los negativos de otros cultivos SHALL permanecer separados.

#### Scenario: Hoja sana rechazada
- **WHEN** el objetivo técnico seleccionado es `POTATO_HEALTHY`
- **THEN** el resultado visible es `NO_CONCLUYENTE` y no existe clase de enfermedad publicada.

#### Scenario: Cultivo ajeno rechazado
- **WHEN** el objetivo técnico seleccionado es un cultivo ajeno
- **THEN** el resultado visible es `NO_CONCLUYENTE` con motivo de cultivo no soportado.

### Requirement: Evaluación independiente del rechazo
La selección de arquitectura, calibración y umbral SHALL usar solo TRAIN y VAL admitidos. El bundle y la política SHALL quedar congelados antes de abrir un TEST nuevo, sin reutilizar como TEST independiente las imágenes o grupos expuestos en el ciclo v1.2.0. La evaluación SHALL publicar numeradores, denominadores y tasas de falsas aceptaciones por separado para papa sana y otros cultivos, además de recall, cobertura, error selectivo y abstenciones de las dos enfermedades. El TEST SHALL ejecutarse una sola vez por bundle congelado.

#### Scenario: Negativo aceptado erróneamente
- **WHEN** una hoja sana recibe un diagnóstico visible de cualquiera de los dos tizones
- **THEN** incrementa el numerador de falsa aceptación de papa sana, aunque el objetivo técnico o la puntuación bruta difieran.

#### Scenario: Abstención positiva
- **WHEN** una imagen válida de tizón recibe `NO_CONCLUYENTE`
- **THEN** cuenta como fallo en el recall de ese tizón y permanece en el denominador de cobertura.

### Requirement: Aprobación G2 nueva antes de repetir G3
La activación de una política v1.3.0 SHALL exigir evaluación del TEST nuevo contra G0 v1.3.0, carga independiente del bundle, revisión G2 del responsable y catálogo revisado. El resultado v1.2.0 SHALL conservarse como evidencia histórica y no acreditar el rechazo v1.3.0.

#### Scenario: Bundle histórico
- **WHEN** solo existe la aprobación G2 v1.2.0
- **THEN** G3 permanece abierto y la política v1.3.0 no se activa para usuarios.
