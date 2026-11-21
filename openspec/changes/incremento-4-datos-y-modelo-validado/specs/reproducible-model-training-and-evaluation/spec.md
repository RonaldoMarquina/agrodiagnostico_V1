## Purpose

Establecer evidencia reproducible de entrenamiento, identificación de cultivo, calibración y evaluación independiente antes de aprobar clases y artefactos para usuarios.

## ADDED Requirements

### Requirement: Protocolo aprobado antes de experimentar
El proyecto SHALL registrar criterios definidos y aprobados por el responsable del proyecto antes del entrenamiento con datos reales o la selección de candidatos: definición de clases/cultivos candidatos, política de admisión, mínimos por clase y grupo, métricas y límites por clase, negativos, abstención, calibración y recursos. SHALL conservar responsable, fecha, versión y justificación de cambios. Valores ausentes SHALL bloquear experimentación de aprobación, sin umbrales productivos inventados. G0 acredita el diseño del protocolo; derechos y revisión de imágenes concretas pertenecen a G1 y resultados medidos a G2.

#### Scenario: Criterios incompletos
- **WHEN** falta un criterio de aceptación o su aprobación
- **THEN** las herramientas pueden probarse con fixtures pero ningún experimento se presenta como modelo aprobado

#### Scenario: Protocolo de diseño completo aprobado por el responsable
- **WHEN** el responsable registra los dos tizones candidatos del piloto, política de admisión, mínimos, métricas y presupuestos, incluidos cobertura ≥ 0,70 y error selectivo ≤ 0,10 con numeradores y denominadores, y deja fecha, versión y justificación
- **THEN** G0 puede cerrarse como protocolo de diseño sin atribuir aprobación a un docente, admitir imágenes ni afirmar resultados alcanzados

#### Scenario: Definiciones de aceptación y abstención
- **WHEN** una imagen válida de las dos clases del piloto recibe NO_CONCLUYENTE o no recibe diagnóstico aceptado
- **THEN** permanece en el denominador de cobertura y de recall de su clase, sin contar como acierto ni crear una octava clase; el error selectivo no cumple si no hay aceptados

#### Scenario: Negativos con dos límites aprobados
- **WHEN** se evalúan negativos fuera de las dos clases del piloto
- **THEN** se informa el cociente de diagnósticos aceptados de clase soportada sobre negativos evaluados; rige el límite histórico ≤ 0,05, que también satisface el nuevo máximo ≤ 0,10, y cero negativos no acredita el criterio

### Requirement: Comparación reproducible y selección independiente
El entrenamiento SHALL ejecutarse en CPU con datos admitidos y registrar versión de datos, código, entorno, semillas, preprocesado y configuración. Para G0 v1.2.0 SHALL comparar dos clasificadores de los tizones de papa (MobileNetV3 y ResNet18), con el mismo TRAIN/VAL, preprocesado y presupuesto CPU; el cultivo es una identificación previa del usuario y no una cabeza automática. La selección SHALL usar solo VAL e informar F1 macro, recall por clase, cobertura, error selectivo, abstención, rechazo de negativos y latencia. La calibración y condiciones de abstención SHALL congelarse antes de abrir TEST.

El umbral de publicación SHALL elegirse sobre VAL, registrar su justificación y cobertura/abstención, y congelarse antes de abrir TEST. Un score o confianza estimada SHALL NOT presentarse como probabilidad de diagnóstico correcto sin validación específica.

#### Scenario: Repetición de experimento
- **WHEN** se repite una ejecución con el mismo manifiesto, configuración y entorno
- **THEN** se obtienen resultados dentro de tolerancias documentadas, con versiones y diferencias registradas

#### Scenario: Intento de ajustar con test
- **WHEN** resultados de TEST motivan cambios de modelo o umbral
- **THEN** se registra un nuevo ciclo y ese test no puede acreditarse como evaluación independiente del modelo ajustado

#### Scenario: Corrección del rechazo de papa sana tras G3 fallido
- **WHEN** una aceptación integrada revela falsos diagnósticos de tizón en papa sana fuera del piloto
- **THEN** el bundle y TEST anteriores permanecen históricos, el nuevo protocolo define papa sana como estrato negativo medible, se admiten imágenes y grupos independientes en G1, se elige el rechazo con VAL y se exige un TEST nuevo y no expuesto antes de una nueva aprobación G2; la decisión de preparar la versión no sustituye su aprobación formal por el responsable

### Requirement: Evaluación por clase y cobertura honesta
La evaluación SHALL informar cantidades, accuracy, precision, recall y F1 por clase y macro, confusión, rechazo de entrada ajena, calibración, cobertura/error, abstención, falsos aceptados en negativos, incertidumbre, latencia y memoria con hardware. SHALL aplicar criterios congelados a TEST independiente y EXTERNAL si existe, sin ocultar fallos bajo promedios. Papa sana queda fuera del piloto y no forma parte de los negativos G1 admitidos; su rechazo no SHALL afirmarse medido sin una colección autorizada separada.

La cobertura selectiva SHALL ser diagnósticos aceptados entre imágenes válidas de las dos clases del piloto; el error selectivo SHALL ser diagnósticos aceptados incorrectos entre diagnósticos aceptados. Precision y F1 visibles SHALL usar verdaderos y falsos positivos de diagnósticos aceptados, no de predicciones técnicas ocultas por abstención; los falsos negativos SHALL incluir esas abstenciones. El recall de cada clase SHALL usar todas sus imágenes válidas como denominador. La aceptación errónea de negativos SHALL usar todos los negativos evaluados como denominador. Cada reporte SHALL publicar numeradores, denominadores y resultados por clase; denominadores cero SHALL impedir acreditar el criterio correspondiente.

#### Scenario: Clase que no cumple
- **WHEN** una clase falla criterios o carece de muestras independientes suficientes
- **THEN** queda no soportada aunque otras clases aprueben y se registra su exclusión

### Requirement: Aprobación de release y cierre real
Un release SHALL vincular pesos/checksums, preprocesado, mapa, dataset, entorno, evaluación, calibración y revisión humana. El cierre SHALL exigir modelo real aprobado para ambos tizones de papa, con papa sana y maíz excluidos y aceptación integrada real. No SHALL suplirse con fixtures ni CI técnico.

#### Scenario: Ningún modelo cumple
- **WHEN** no existe release que supere criterios o falta aprobación
- **THEN** la promoción y el cierre permanecen pendientes, aunque el código y CI estén completos
