# Incremento 4 — PROTOCOLO-G0

Estado de decisión: **G0 de diseño aprobado por el responsable del proyecto el 2026-11-19**, protocolo v1.2.0. La [enmienda del ADR-0009](../adr/0009-modelo-validado-inferencia-y-politicas-de-publicacion.md) documenta el cambio de autoridad: el protocolo ya no exige aprobación formal docente. Derechos y revisión de imágenes seleccionadas corresponden a G1; resultados medidos de modelo real, a G2.

El JSON de G0 quedó congelado antes del entrenamiento: su campo `measured_results.status=NOT_MEASURED` registra **el estado al aprobar G0**, no el estado actual. Los resultados posteriores se conservan en el [reporte TEST](INCREMENTO-4-TEST-PILOTO-V1.2.md) y el [acta G2](INCREMENTO-4-APROBACION-G2-PILOTO.md), sin alterar el protocolo incluido en el bundle.

Registros de apoyo: [ficha de criterios aprobados](INCREMENTO-4-FICHA-G0.md), [matriz de procedencia y permisos](INCREMENTO-4-EXPEDIENTE-FUENTES.md) y [tabla de equivalencias candidatas](INCREMENTO-4-REVISION-TAXONOMIA-Y-MAPPINGS.md). El [expediente G1](INCREMENTO-4-G1-PILOTO-V1.2.md) acredita admisión del lote piloto con procedencia experta de etiquetas PlantVillage y control interno, sin nueva revisión agronómica independiente.

## Registro de evidencias independientes

| Evidencia | Registro disponible | Puerta y estado |
| --- | --- | --- |
| Política de fuentes | [Expediente de fuentes](INCREMENTO-4-EXPEDIENTE-FUENTES.md) y `ml/manifests/sources.v2.json` | **G0:** fuentes candidatas y regla de admisión documentadas; PlantVillage admitida para el lote piloto G1 |
| Criterios numéricos y aprobación | [Protocolo JSON v1.2.0](../../ml/evaluation/protocol-g0.v1.2.0.json) y [ADR-0009](../adr/0009-modelo-validado-inferencia-y-politicas-de-publicacion.md) | **G0 cerrado:** responsable, fecha, versión, justificación, límites y definiciones completos |
| Definiciones candidatas | [Taxonomía y mappings](INCREMENTO-4-REVISION-TAXONOMIA-Y-MAPPINGS.md) | **G0:** nombre candidato y exclusiones genéricas registrados; etiquetas del piloto con procedencia experta PlantVillage y control interno G1 |
| Permiso de imágenes seleccionadas | [Expediente G1](INCREMENTO-4-G1-PILOTO-V1.2.md) con registro privado por SHA-256 | **G1 del piloto cerrado:** derechos y selección verificados |
| Resultados medidos | [TEST único](INCREMENTO-4-TEST-PILOTO-V1.2.md) y [aprobación G2](INCREMENTO-4-APROBACION-G2-PILOTO.md) | **G2 cerrado para el piloto:** TEST cumple; EXTERNAL no disponible |

Una declaración de licencia de un repositorio no sustituye el permiso de las fotografías elegidas en G1. Los fixtures y las salidas de pruebas unitarias no son resultados medidos para G2. Cada puerta conserva evidencia separada; estas ausencias posteriores no se añaden como condiciones nuevas de G0.
La plantilla CSV solo define columnas: los registros completos y comprobantes del lote G1 se guardan en almacenamiento privado; no se publican fotos, rutas precisas ni datos personales en Git. Una fila con `decision=PENDING` no autoriza importación.

El responsable aprobó los mínimos de muestras/grupos por clase: TRAIN 150/50, VAL 40/20, TEST 30/15 y EXTERNAL 20/10 si se obtiene ese conjunto. También aprobó F1 macro VAL ≥ 0,80, F1 macro TEST ≥ 0,85, recall TEST ≥ 0,80 por clase, F1 TEST ≥ 0,70 por clase, FPR en negativos ≤ 0,05, rechazo de negativos ≥ 0,95 y ECE ≤ 0,15. El objetivo F1 macro EXTERNAL ≥ 0,75 sigue condicionado a un conjunto autorizado. El presupuesto **del modelo en CPU** es mediana ≤ 1000 ms, p95 ≤ 2500 ms, límite duro ≤ 4000 ms y RSS ≤ 1024 MB. El objetivo p95 ≤ 30 s es del **flujo completo** y no se ha medido.

Cobertura ≥ 0,70 = diagnósticos aceptados / imágenes válidas de las dos clases del piloto. Error selectivo ≤ 0,10 = diagnósticos aceptados incorrectos / diagnósticos aceptados; cero aceptados no cumple. Aceptación errónea de negativos ≤ 0,10 = negativos con diagnóstico aceptado de clase soportada / negativos evaluados; cero negativos no cumple. El FPR histórico ≤ 0,05 usa ese mismo cociente, por lo que es el límite efectivo más estricto y equivale a rechazo ≥ 0,95. Las abstenciones `NO_CONCLUYENTE` cuentan en el denominador de cobertura y en el denominador de recall de su clase como falsos negativos. Publicar numeradores, denominadores y resultados por clase. El umbral de confianza se seleccionará en VAL y se congelará antes de TEST; su valor observado sigue vacío por diseño. La [plantilla de aplicación](../../ml/evaluation/g0-application-record.template.json) deja vacíos los conteos observados y mediciones futuras.

La denominación candidata de `MAIZE_LEAF_BLIGHT` es **tizón foliar del norte**. `Corn rust leaf` (PlantDoc), `corn rust` (PlantSeg) y `Corn leaf blight` (PlantDoc) quedan `UNMAPPED`; una etiqueta genérica no autoriza inferir roya común ni tizón del norte. Las equivalencias fuera del piloto siguen provisionales; las dos equivalencias de PlantVillage admitidas para papa se sustentan en la procedencia experta de la fuente y el control interno G1.

Fuentes inventariadas: [PlantVillage del autor](https://huggingface.co/datasets/mohanty/PlantVillage) declara CC BY-SA 3.0 y quedó admitida únicamente para los archivos exactos del lote piloto G1; [PlantDoc](https://github.com/pratikkayal/PlantDoc-Dataset) publica CC BY 4.0, pero su README indica imágenes obtenidas de Internet y no acredita derechos individuales; [PlantSeg v7](https://zenodo.org/records/17719108) es candidato académico no comercial sujeto a revisar versión y permiso de cada imagen. [IP102](https://github.com/xpwu95/IP102) reserva el uso académico y pide contacto para otros fines; queda fuera de las dos clases del piloto de enfermedades y del alcance obligatorio V1. Ayacucho EXTERNAL requiere origen y permiso propios.

G0 v1.2.0 queda cerrado por [1.4](../../openspec/changes/incremento-4-datos-y-modelo-validado/tasks.md) como **protocolo de diseño**. Solo los dos tizones de papa son candidatos del piloto. G1 comprobó derechos, equivalencias y calidad del lote piloto; G2 midió TEST una vez y aprobó el bundle limitado. Si se cambia un criterio tras observar TEST, se registra otra versión y se repite la evaluación independiente.

La declaración anterior de 36/40 tareas completadas queda retirada. El estado verificable se mantiene en [tasks.md](../../openspec/changes/incremento-4-datos-y-modelo-validado/tasks.md). No archivar el cambio ni publicar capacidades ML como validadas.

## Enmienda aprobada v1.2.0

El responsable redujo el alcance antes del entrenamiento y de TEST a los dos tizones de papa en hoja previamente identificada. La auditoría de fuentes documenta grupos insuficientes para las siete clases previas. Las métricas selectivas se calculan sobre los dos tizones; los negativos admitidos provienen de otro cultivo y papa sana no se usa como negativo. Exactitud automática de cultivo queda fuera del piloto. G1 se cerró posteriormente para el [lote privado documentado](INCREMENTO-4-G1-PILOTO-V1.2.md). [Auditoría](INCREMENTO-4-FUENTES-PARA-COMPLETAR-G1.md) · [Protocolo](../../ml/evaluation/protocol-g0.v1.2.0.json).
