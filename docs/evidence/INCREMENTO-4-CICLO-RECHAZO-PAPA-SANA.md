# Incremento 4 — preparación de un nuevo ciclo para rechazar papa sana

Fecha: 2026-11-20. **Decisión de alcance del responsable:** preparar una nueva versión tras el fallo de aceptación del bundle G0 v1.2.0. Este documento es una propuesta técnica para **G0 v1.3.0**, todavía sin aprobación de un protocolo completo, imágenes nuevas admitidas, modelo reentrenado ni resultados medidos. El G2 v1.2.0 y su TEST quedan como historial inmutable; G3 permanece abierto.

## Motivo verificable

En la [aceptación local](INCREMENTO-4-G3-ACEPTACION-LOCAL.md), cuatro fotografías originales de papa sana de la partición VAL histórica terminaron como `COMPLETADO/POTATO_LATE_BLIGHT` (4/4). Los otros cuatro negativos de tomate sí se rechazaron. El objetivo técnico `OTHER_CROP` entrenado con tomate no demostró rechazo de papa sana. No ajustar pesos, preprocesado, calibración ni umbral del bundle congelado usando estas fotografías y después acreditar su TEST anterior como independiente.

## Inventario disponible y sus límites

El lote privado PlantVillage `color` inventariado contiene **120 imágenes originales de papa sana en 30 `leaf_id`**: TRAIN histórico 80/20, VAL 24/6 y TEST 16/4 (fotos/grupos). La aceptación ya expuso cuatro fotos VAL. Son conteos de inventario, **no admisión G1 de papa sana**; se deben verificar ruta, SHA-256, licencia aplicable a cada archivo, etiqueta, calidad y duplicados visuales antes de incorporarlas. No se convierten automáticamente en grupos independientes nuevos. El TEST histórico de ambos tizones se abrió una vez para G2 v1.2.0 y sus resultados se conocen. No puede volver a usarse como TEST independiente de un modelo cambiado a raíz del fallo G3. Las fotografías de papa sana de la aceptación tampoco pueden contarse como evaluación independiente futura.

## Protocolo v1.3.0 por definir y aprobar antes de entrenar

Se mantiene **entrada de hoja de papa identificada previamente y dos clases publicables**: `POTATO_EARLY_BLIGHT` y `POTATO_LATE_BLIGHT`. Papa sana seguirá siendo **fuera de cobertura**, nunca un diagnóstico «sana» ni `NO_CONCLUYENTE` como clase del modelo. La versión propuesta incorporará papa sana como estrato negativo propio, separado de otros cultivos, con rechazo medido por estrato y `reason_code` contractual. La propuesta hereda F1 macro TEST ≥ 0,85, recall por tizón ≥ 0,80, cobertura ≥ 0,70, error selectivo ≤ 0,10, FPR de negativos ≤ 0,05, calibración y presupuesto CPU de v1.2.0; el responsable debe fijar y aprobar por escrito los mínimos de fotos/grupos por estrato y confirmar el límite por estrato antes de entrenar. Sin esos campos, G0 v1.3.0 permanece abierto. Un denominador cero nunca cumple.

El cálculo propuesto de FPR para papa sana es **papa sana con diagnóstico aceptado de uno de los dos tizones / total de fotos de papa sana evaluadas**. El de otros cultivos conserva su propio numerador y denominador. Para positivos, las abstenciones siguen siendo fallos de recall y se incluyen en el denominador de cobertura. La selección de arquitectura, peso y umbral se hará únicamente con VAL nueva; se congelarán antes del nuevo TEST. Se reportarán numeradores, denominadores y resultados por estrato y clase, sin modificar el criterio después de ver TEST.

## Preparación de G1 y G2

1. Identificar imágenes nuevas o grupos no expuestos de **ambos tizones y papa sana** con derechos aplicables, etiquetas verificadas y grupos `leaf_id`/planta/sesión trazables. Auditar solapamiento de SHA-256 y similitud visual con el lote v1.2.0. Conservar los cuatro controles de papa sana ya expuestos fuera del futuro TEST; excluir del nuevo TEST todas las imágenes/grupos cuyo resultado de TEST v1.2.0 ya se conoce y todo grupo usado en TRAIN/VAL del nuevo modelo. Si no existe un TEST independiente suficiente, no entrenar con intención de aprobar G2.
2. Admitir y sellar nuevos TRAIN/VAL/TEST y negativos por estrato bajo G1 v1.3.0. La licencia publicada de PlantVillage no sustituye la revisión del archivo seleccionado. No importar fotografías de terceros sin derechos comprobados.
3. Comparar en CPU al menos dos enfoques de rechazo de papa sana usando el mismo G1 y presupuesto. El objetivo técnico de rechazo nunca se publica como enfermedad. Calibrar y congelar usando VAL; realizar una sola evaluación del TEST nuevo, registrar EXTERNAL como no disponible si sigue sin existir y someter el nuevo bundle a G2.
4. Repetir aceptación 9.1 con papa sana, ambos tizones, otros cultivos, permisos, catálogo e historial. G3 solo puede cerrarse si el nuevo bundle y la política pasan además los fallos y mediciones de 9.2 y la CI de 9.3.

No se ha elegido ni admitido una fuente adicional ni se ha definido el tamaño del TEST nuevo. Estos son bloqueos concretos de G1/G2 del siguiente ciclo, no motivos para rebajar los criterios tras ver el fallo.
