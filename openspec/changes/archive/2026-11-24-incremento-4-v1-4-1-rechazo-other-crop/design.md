# Design: ciclo v1.4.1 con rechazo aprendido de otro cultivo

## Context

Véase [proposal.md](proposal.md) para la motivación. v1.4.0 entrenó tres salidas técnicas y usó `OTHER_CROP` solo en VAL. El líder ponderado satisfizo F1, recall, cobertura, error selectivo, rechazo sano y calibración, pero publicó tizón en 83/150 controles de otro cultivo; por ello no fue congelado y Sikkim nunca se abrió.

El expediente G1 v1.3.1 ya contiene 503 imágenes / 127 grupos PlantVillage `OTHER_CROP` en TRAIN y 150/38 en VAL, con derechos, revisión y separación por `leaf_id`. v1.4.0 excluyó deliberadamente las 503 filas TRAIN al materializar su manifiesto. v1.4.1 las reincorpora por referencia verificada, sin descargar datos ni admitir una fuente nueva.

El sello Sikkim existente está ligado por hash al protocolo v1.4.0. Conservarlo sellado significa no reescribirlo para aparentar un nuevo conjunto; v1.4.1 referenciará el mismo sello y sus criterios, y una compuerta de ciclo separada vinculará el futuro bundle v1.4.1 antes de autorizar la única evaluación externa.

## Goals / Non-Goals

**Goals:**

- Materializar G0/G1 v1.4.1 antes de cualquier nuevo entrenamiento.
- Entrenar cuatro salidas técnicas balanceadas por clase y `leaf_id`.
- Mantener dos clases publicables y convertir las otras dos en abstención visible.
- Hacer que bundle, política y validadores expresen la diferencia entre clase técnica y diagnóstico publicable.
- Preservar la frontera física y lógica de Sikkim y del TEST histórico durante toda la selección.

**Non-Goals:**

- Cambiar los límites VAL o EXTERNAL para facilitar aprobación.
- Reutilizar pesos v1.4.0 como inicialización o ajustar con sus predicciones.
- Añadir `OTHER_CROP` al catálogo, a la interfaz como diagnóstico o a eventos como enfermedad.
- Abrir Sikkim, reejecutar TEST v1.3.2 o activar el worker en la fase de materialización.
- Incorporar nuevas fuentes, recolección personal o imágenes de búsquedas web.

## Decisions

### 1. v1.4.1 es un ciclo nuevo, no una mutación de v1.4.0

El protocolo, manifiesto, configuración, candidatos y reportes usarán versión/raíces privadas v1.4.1. La evidencia v1.4.0 se validará por hash y permanecerá de solo lectura. Se elige este enfoque frente a “reanudar” el candidato ponderado porque la dimensión de salida cambia de tres a cuatro y la comparación debe comenzar desde inicialización aleatoria bajo un G0 previo.

### 2. El manifiesto v1.4.1 deriva del G1 ya admitido

La materialización leerá el paquete privado G1 v1.3.1, verificará su reporte, evidencia y derechos y seleccionará:

| Estrato técnico | TRAIN fotos/grupos | VAL fotos/grupos |
| --- | ---: | ---: |
| `POTATO_EARLY_BLIGHT` | 541/136 | 165/42 |
| `POTATO_LATE_BLIGHT` | 499/129 | 153/39 |
| `POTATO_HEALTHY` | 80/20 | 28/7 |
| `OTHER_CROP` | 503/127 | 150/38 |
| **Total** | **1.623/412** | **496/126** |

El validador exigirá los mismos SHA, etiquetas, licencias y decisiones del expediente de origen, bloqueará los 68 grupos TEST históricos y rechazará `fallback_*`, SHA repetidos o grupos cruzados. Esta derivación es preferible a copiar o relabelar archivos porque conserva la decisión G1 por imagen.

### 3. Sikkim conserva el sello v1.4.0 sin reescritura

G0 v1.4.1 incluirá el SHA-256 del manifiesto y del sello Sikkim ya aprobados, además del hash del protocolo v1.4.0 al que pertenece el sello. La compuerta previa al entrenamiento comprobará esos metadatos sin montar ni leer el manifiesto o los bytes externos en el contenedor de entrenamiento. Más adelante, una autorización EXTERNAL v1.4.1 deberá verificar tanto el sello original intacto como un `freeze.json` v1.4.1 completo.

La alternativa de volver a sellar los mismos archivos con otro protocolo se descarta porque produciría dos sellos aparentemente independientes sobre el mismo conjunto y debilitaría la trazabilidad de la apertura única.

### 4. MobileNetV3-Small produce cuatro logits desde inicialización aleatoria

La capa final tendrá índices estables para temprano, tardío, sano y otro cultivo. No se reutilizarán pesos v1.4.0 porque la salida y la distribución supervisada cambian. El preprocesado, GroupNorm, semilla y presupuesto CPU permanecerán fijados para hacer comparable el nuevo expediente con el antecedente, sin usarlo como datos de selección.

### 5. Sampler clase → leaf_id → imagen, 80 por clase

Cada época tendrá 320 exposiciones. Para cada clase se barajan grupos con semilla determinista y se elige una imagen original dentro del grupo; si hay menos de 80 grupos, se recorren ciclos de grupos antes de repetirlos. Esto expone los 20 grupos sanos cuatro veces, mientras que temprano, tardío y otro cultivo pueden seleccionar 80 grupos distintos por época. Se registrarán exposiciones, grupos únicos y originales únicos.

Se descarta muestreo uniforme por imagen porque volvería a favorecer clases/grupos con más vistas. Los aumentos conservadores existentes permanecen limitados a `POTATO_HEALTHY` TRAIN y no crean grupos. `OTHER_CROP` no recibe aumentos específicos en esta versión.

### 6. Política visible basada en publicabilidad, no en el nombre del logit

La decisión toma probabilidades calibradas de cuatro salidas. Un argmax no publicable (`POTATO_HEALTHY` u `OTHER_CROP`) produce abstención técnica. Un argmax de tizón solo es publicable si supera el umbral VAL congelado y las compuertas de política/catálogo. La métrica de recall de un tizón cuenta toda abstención como falso negativo.

Se usará `UNSUPPORTED_CROP` para `OTHER_CROP` y `LOW_CONFIDENCE` o el motivo técnico estable correspondiente para sano/baja confianza, sin convertir `NO_CONCLUYENTE` en clase del modelo.

### 7. Contrato ML retrocompatible con condición v1.4.1

`model-bundle.v1.schema.json` conservará su versión de esquema y agregará `OTHER_CROP` al dominio técnico de `class_map`. Para bundles gobernados por G0 `1.4.1`, una condición JSON Schema exigirá:

- cuatro entradas técnicas, validadas además por código para asegurar el conjunto exacto y sin duplicados;
- `publishable_classes` con exactamente los dos tizones;
- una política de rechazo que transforme cualquier argmax no publicable o confianza insuficiente en abstención;
- hashes de configuración, calibración, umbral, preprocesado, manifiestos y congelamiento.

`publication-policy.v1.schema.json` añadirá una condición G0 `1.4.1` que permita aprobar como máximo y exactamente cuando G2 corresponda los dos tizones, nunca sano u otro cultivo. Los eventos no cambian: `OTHER_CROP` no sale del adaptador como diagnóstico; se publica una abstención técnica ya admitida por los contratos actuales.

### 8. Selección restringida a PlantVillage VAL

Cada época se evalúa en las mismas 496 filas VAL. Temperatura, ruta y umbral se buscan solo allí y se aplican las mínimas ya fijadas: F1 macro 0,80; recall por tizón 0,80; cobertura 0,70; error selectivo 0,10; sano ≤2/28; otro cultivo ≤7/150; ECE 0,15. Se conserva una sola estrategia de balance aprobada —sampler de cuatro clases—; “selección de pesos” significa seleccionar la época/estado del modelo exclusivamente con VAL, no reutilizar candidatos v1.4.0.

El contenedor de TRAIN/VAL montará solo archivos PlantVillage permitidos. Un escaneo de logs y artefactos verificará que no contengan rutas, hashes, predicciones o métricas Sikkim.

### 9. Congelamiento y acceso externo siguen separados

Solo un candidato que satisfaga todas las mínimas VAL puede generar un bundle congelado. La carga independiente debe verificar pesos, mapa de cuatro logits, conjunto publicable, configuración, calibración, umbral y hashes. El congelamiento únicamente vuelve al candidato elegible para una revisión de apertura; no abre Sikkim ni aprueba G2 automáticamente.

## Risks / Trade-offs

- **`OTHER_CROP` reúne múltiples cultivos y condiciones** → se presenta como objetivo técnico heterogéneo de rechazo, no como clase agronómica, y se mantienen métricas separadas de publicación errónea.
- **503 imágenes pueden concentrarse en 127 hojas** → el sampler opera por `leaf_id` y reporta grupos expuestos para evitar que más vistas aparenten mayor independencia.
- **Cuatro clases pueden reducir recall de tizones** → las mínimas de recall y cobertura no cambian; si fallan, no se congela ni se abre EXTERNAL.
- **Extender un schema v1 puede aceptar `OTHER_CROP` en bundles antiguos** → las condiciones por `g0_protocol_version` y validadores semánticos exigen cuatro salidas solo en v1.4.1 y preservan fixtures históricos.
- **El sello EXTERNAL referencia v1.4.0** → se conserva como evidencia primaria y v1.4.1 añade un vínculo de ciclo; nunca se altera el sello para aparentar datos nuevos.
- **Un mejor VAL puede no generalizar** → Sikkim permanece como evaluación final única y no seleccionable; sus criterios y limitación por imagen siguen iguales.

## Migration Plan

1. Crear el protocolo G0 v1.4.1 y ADR de la decisión, referenciando el fallo 83/150 y el sello Sikkim intacto.
2. Extender contratos ML y validadores con fixtures positivos/negativos de cuatro salidas y dos publicables.
3. Materializar el manifiesto PlantVillage v1.4.1 desde G1 v1.3.1, verificar conteos/grupos/derechos y cerrar G1 v1.4.1 sin abrir EXTERNAL.
4. Implementar y probar modelo, métricas y sampler de cuatro clases con fixtures; ejecutar preflight estricto.
5. Hacer commit local del protocolo, contratos, código y G1 antes de entrenar.
6. Entrenar desde cero usando solo TRAIN y seleccionar época/calibración/umbral con VAL.
7. Si VAL falla, registrar el ciclo sin congelar; si pasa, congelar y presentar el expediente antes de solicitar apertura EXTERNAL.

Rollback antes de entrenar consiste en no ejecutar v1.4.1 y conservar v1.4.0 como último expediente medido. Rollback después de entrenar consiste en no promover el bundle; nunca se restaura v1.4.0 como aprobado ni se modifica el sello externo.
