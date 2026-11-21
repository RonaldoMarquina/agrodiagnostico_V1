# Incremento 4 — preparación de un nuevo ciclo para rechazar papa sana

Fecha: 2026-11-20. **G0 v1.3.0 aprobado por el responsable:** dos tizones publicables y papa sana como condición técnica de rechazo, con mínimos y límites fijados antes del entrenamiento. Este documento acompaña el [nuevo cambio OpenSpec](../../openspec/changes/incremento-4-v1-3-rechazo-papa-sana/proposal.md), el [protocolo aprobado](../../ml/evaluation/protocol-g0.v1.3.0.json) y la [preparación G1](INCREMENTO-4-G1-V1.3-PREPARACION.md). No hay imágenes nuevas admitidas ni resultados v1.3.0 medidos. G2 v1.2.0 y su TEST quedan como historial inmutable; G3 permanece abierto.

## Motivo verificable

En la [aceptación local](INCREMENTO-4-G3-ACEPTACION-LOCAL.md), cuatro fotografías originales de papa sana de la partición VAL histórica terminaron como `COMPLETADO/POTATO_LATE_BLIGHT` (4/4). Los otros cuatro negativos de tomate sí se rechazaron. El objetivo técnico `OTHER_CROP` entrenado con tomate no demostró rechazo de papa sana. No ajustar pesos, preprocesado, calibración ni umbral del bundle congelado usando estas fotografías y después acreditar su TEST anterior como independiente.

## Inventario disponible y sus límites

El lote privado PlantVillage `color` inventariado contiene **120 imágenes originales de papa sana en 30 `leaf_id`**: TRAIN histórico 80/20, VAL 24/6 y partición de inventario llamada TEST 16/4 (fotos/grupos). La aceptación expuso cuatro fotos de VAL, pertenecientes a **tres `leaf_id` con 12 fotos VAL en total**. La auditoría comparó los cuatro SHA-256 del informe privado G3 con `batch-v1/positives.csv`; los tres grupos tenían solo filas VAL. Los cuatro controles no se reutilizarán para entrenar, calibrar ni medir v1.3.0. Para impedir fuga entre vistas, **las 12 fotos de los tres grupos quedan excluidas de todas las particiones** mediante la [lista de exclusión](../../ml/manifests/g1-v1.3-exposure-blocklist.json). Las otras 12/3 de VAL son candidatas para VAL v1.3.0. Las 16/4 sanas de la partición inventariada **no formaron parte del TEST G2 v1.2.0**; son candidatas, nunca admitidas, para el nuevo TEST. Toda candidata requiere revisión por archivo de ruta, SHA-256, derechos, etiqueta, calidad y duplicados visuales. El TEST abierto de ambos tizones y tomate no puede reutilizarse como TEST independiente.

## Protocolo G0 v1.3.0 aprobado antes de entrenar

Se mantiene **entrada de hoja de papa identificada previamente y dos clases publicables**: `POTATO_EARLY_BLIGHT` y `POTATO_LATE_BLIGHT`. Papa sana seguirá **fuera de cobertura** y será un objetivo técnico de rechazo que produce `NO_CONCLUYENTE/UNSUPPORTED_CLASS`, nunca un diagnóstico «sana» ni uno de los dos tizones. G0 v1.3.0 conserva F1 macro TEST ≥ 0,85, recall por tizón ≥ 0,80, cobertura ≥ 0,70, error selectivo ≤ 0,10, FPR de negativos ≤ 0,05, calibración y presupuesto CPU de v1.2.0. Aplica mínimos 150 fotos/50 grupos TRAIN, 40/20 VAL y 30/15 TEST a **cada uno de los cuatro estratos**; FPR ≤ 0,05 y rechazo ≥ 0,95 a **cada negativo** por separado. El responsable aprobó esta aplicación por estrato el 2026-11-20. G0 v1.3.0 está cerrado; G1 continúa abierto. Un denominador cero nunca cumple.

El FPR de papa sana es **fotos válidas sanas con diagnóstico visible aceptado de uno de los dos tizones / total de fotos válidas sanas evaluadas**. El de otros cultivos conserva numerador y denominador propios. Para positivos, las abstenciones siguen siendo fallos de recall e integran el denominador de cobertura. Arquitectura, peso y umbral se seleccionarán únicamente con VAL admitida; se congelarán antes del nuevo TEST. Se reportarán numeradores, denominadores y resultados por estrato y clase.

## Déficit mínimo de datos por estrato

La primera tabla reproduce el cálculo **condicional anterior a la exclusión de los controles G3**, que el responsable citó como 190/100. Su premisa de trasladar las 12 fotos de esos grupos a TRAIN ya no es válida. `fotos/grupos` indica imágenes originales y `leaf_id` independientes. Ninguna fila acredita admisión G1.

| Estrato / partición | Candidatas tras nueva G1 | Mínimo propuesto | Déficit nuevo mínimo |
| --- | ---: | ---: | ---: |
| Papa sana TRAIN, hipótesis histórica con tres grupos G3 expuestos | 92/23 | 150/50 | **58/27** |
| Papa sana VAL, sin esos tres grupos | 12/3 | 40/20 | **28/17** |
| Papa sana TEST nuevo, 16/4 nunca evaluadas en G2 v1.2.0 | 16/4 | 30/15 | **14/11** |
| Tizón temprano TEST nuevo | 0/0; TEST previo 122/31 abierto | 30/15 | **30/15** |
| Tizón tardío TEST nuevo | 0/0; TEST previo 113/29 abierto | 30/15 | **30/15** |
| Otro cultivo TEST nuevo | 0/0; TEST previo 112/29 abierto | 30/15 | **30/15** |
| **Total condicional histórico antes de excluir controles** | | | **190 fotos / 100 grupos** |

**Cálculo operativo con la exclusión aprobada:** TRAIN sano conserva solo 80/20; requiere **70 fotos/30 grupos**. VAL sano conserva 12/3; requiere **28/17**. TEST sano candidato 16/4 requiere **14/11**. Los nuevos TEST de tizón temprano, tardío y otro cultivo requieren **30/15 cada uno**. Total mínimo: **202 fotos originales y 103 grupos independientes nuevos**. Es un faltante de inventario, no un cambio a los mínimos G0. Si las 16/4 candidatas de TEST sano no pasan G1, el faltante total sube a **218 fotos/107 grupos**. Cualquier otra exclusión o incompatibilidad de derechos aumenta el faltante.

TRAIN/VAL históricos de tizón temprano (541/136 y 165/42), tizón tardío (499/129 y 153/39) y tomate (503/127 y 150/38) superan los mínimos aprobados **solo si** pasan nueva admisión y comparación de grupos con TEST nuevo. El cálculo operativo excluye todos los grupos G3 expuestos de TRAIN, VAL y TEST. Ninguna fotografía queda admitida por este cálculo.

## Preparación de G1 y G2

1. Identificar imágenes nuevas o grupos no expuestos de **ambos tizones y papa sana** con derechos aplicables, etiquetas verificadas y grupos `leaf_id`/planta/sesión trazables. Auditar solapamiento de SHA-256 y similitud visual con el lote v1.2.0. Excluir los cuatro controles G3 **y sus tres grupos completos** de TRAIN, VAL, TEST y EXTERNAL; excluir del nuevo TEST todas las imágenes/grupos cuyo resultado de TEST v1.2.0 ya se conoce y todo grupo usado en TRAIN/VAL del nuevo modelo. Si no existe un TEST independiente suficiente, G1 permanece abierto.
2. Admitir y sellar nuevos TRAIN/VAL/TEST y negativos por estrato bajo G1 v1.3.0. La licencia publicada de PlantVillage no sustituye la revisión del archivo seleccionado. No importar fotografías de terceros sin derechos comprobados.
3. Comparar en CPU al menos dos enfoques de rechazo de papa sana usando el mismo G1 y presupuesto. El objetivo técnico de rechazo nunca se publica como enfermedad. Calibrar y congelar usando VAL; realizar una sola evaluación del TEST nuevo, registrar EXTERNAL como no disponible si sigue sin existir y someter el nuevo bundle a G2.
4. Repetir aceptación 9.1 con papa sana, ambos tizones, otros cultivos, permisos, catálogo e historial. G3 solo puede cerrarse si el nuevo bundle y la política pasan además los fallos y mediciones de 9.2 y la CI de 9.3.

No se ha elegido ni admitido una fuente adicional. El mínimo de TEST nuevo está aprobado en G0; los datos independientes que lo cubran siguen siendo bloqueo concreto de G1/G2, no motivo para rebajar criterios tras ver el fallo.
