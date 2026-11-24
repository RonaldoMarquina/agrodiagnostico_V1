# Spec Delta

## Purpose

Establecer un ciclo independiente que detecte hojas de papa sana como condición fuera de las dos enfermedades publicables, con rechazo medible antes de reintentar la aceptación integrada.

## ADDED Requirements

### Requirement: G0 v1.3.2 previo a los experimentos
El proyecto SHALL versionar y obtener aprobación del responsable para los mínimos de imágenes y grupos por estrato, las métricas, los límites de rechazo y el presupuesto CPU antes de entrenar o abrir el nuevo TEST. La elección de preparar este ciclo SHALL NOT contar como aprobación del protocolo numérico propuesto.

#### Scenario: Protocolo todavía propuesto
- **WHEN** G0 v1.3.0 no tiene aprobación explícita del responsable
- **THEN** ningún entrenamiento real ni apertura del nuevo TEST puede acreditarse para esta versión.

#### Scenario: Reducción v1.3.1 propuesta tras el inventario
- **WHEN** el inventario G1 demuestra que los mínimos sanos de v1.3.0 no son alcanzables y se propone una tabla v1.3.1
- **THEN** esa tabla permanece abierta hasta la aprobación numérica explícita del responsable; ninguna imagen se declara admitida por cambiar el protocolo y el TEST histórico no se reutiliza.

#### Scenario: Tabla v1.3.1 aprobada y admisión individual
- **WHEN** el responsable aprueba la tabla reducida antes de entrenar y G1 comprueba derechos, etiquetas, bytes, grupos y mínimos por estrato
- **THEN** G0 v1.3.1 puede cerrarse y G1 puede admitir archivos y sellar un TEST nuevo; los resultados de G2 y la política de producción permanecen pendientes.

#### Scenario: Criterios sanos v1.3.2 antes de entrenar
- **WHEN** el responsable aprueba sobre el lote G1 sellado 80/20 TRAIN, 28/7 VAL y 32/8 TEST de papa sana, con máximo 3/32 publicaciones erróneas de tizón y mínimo 29/32 `NO_CONCLUYENTE`
- **THEN** el protocolo v1.3.2 se congela antes del entrenamiento y la evaluación; G1 puede conservarse cerrado si sus manifiestos, grupos y sello siguen verificables y los demás mínimos no cambian.

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

Para G0 v1.3.2, el TEST sano SHALL evaluar las 32 fotos selladas de ocho grupos: como máximo tres fotos pueden publicar cualquiera de los dos tizones y al menos 29 SHALL terminar exactamente en `NO_CONCLUYENTE`. Una salida ausente, `FALLIDO` o excluida después del sello SHALL NOT contarse como `NO_CONCLUYENTE` ni reducir el denominador de 32. `OTHER_CROP` SHALL conservar FPR ≤0,05 y rechazo de diagnóstico visible de tizón ≥0,95. Las métricas de tizones, calibración y CPU SHALL conservar sus límites v1.3.1. Los resultados se publicarán también por grupo de hoja.

#### Scenario: Negativo aceptado erróneamente
- **WHEN** una hoja sana recibe un diagnóstico visible de cualquiera de los dos tizones
- **THEN** incrementa el numerador de falsa aceptación de papa sana, aunque el objetivo técnico o la puntuación bruta difieran.

#### Scenario: Abstención positiva
- **WHEN** una imagen válida de tizón recibe `NO_CONCLUYENTE`
- **THEN** cuenta como fallo en el recall de ese tizón y permanece en el denominador de cobertura.

#### Scenario: Resultado sano distinto de abstención
- **WHEN** una de las 32 fotos sanas selladas termina en `FALLIDO` sin publicar tizón
- **THEN** no aumenta el numerador de publicación errónea, pero tampoco el numerador mínimo de 29 `NO_CONCLUYENTE`.

### Requirement: Aprobación G2 nueva antes de repetir G3
La activación de una política v1.3.2 SHALL exigir evaluación del TEST nuevo contra G0 v1.3.2, carga independiente del bundle, revisión G2 del responsable y catálogo revisado. El resultado v1.2.0 SHALL conservarse como evidencia histórica y no acreditar el rechazo v1.3.2.

#### Scenario: Bundle histórico
- **WHEN** solo existe la aprobación G2 v1.2.0
- **THEN** G3 permanece abierto y la política v1.3.2 no se activa para usuarios.
