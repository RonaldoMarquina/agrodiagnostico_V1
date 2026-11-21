# Ficha de criterios G0 aprobados por el responsable

**AgroDiagnóstico V1 · Incremento 4 · 2026-11-19 · protocolo v1.2.0.** El responsable del proyecto aprobó el [protocolo de diseño G0](../../ml/evaluation/protocol-g0.v1.2.0.json). La [enmienda del ADR-0009](../adr/0009-modelo-validado-inferencia-y-politicas-de-publicacion.md) registra por qué se eliminó la condición de aprobación docente. Esta ficha documenta metas fijadas antes del entrenamiento; los [resultados TEST](INCREMENTO-4-TEST-PILOTO-V1.2.md) y la [aprobación G2](INCREMENTO-4-APROBACION-G2-PILOTO.md) constan por separado. No acredita una revisión agronómica nueva.

## Alcance definido

Dos clases candidatas: tizón temprano y tardío de papa en hoja previamente identificada como papa. Papa sana, maíz, detección automática de cultivo y plagas quedan fuera del piloto. Las dos equivalencias exactas de PlantVillage se admitieron con [procedencia experta y control interno](INCREMENTO-4-G1-PILOTO-V1.2.md), sin nueva revisión agronómica independiente. Las etiquetas genéricas de roya y tizón quedan sin mapeo automático. PlantDoc y PlantSeg siguen como complementos condicionales sin imágenes admitidas. Plagas quedan fuera del núcleo inicial.

## Cifras aprobadas como metas de diseño antes de medir

| Medida | Propuesta inicial | Condición de medición |
| --- | --- | --- |
| F1 macro de las dos clases del piloto | **≥ 0,85** | TEST independiente, sellado antes de seleccionar modelos/umbrales |
| Recall de cada clase | **≥ 0,80** | Cada una de las dos clases del piloto en TEST; informar soporte y fallos individuales |
| F1 macro de fotografías reales | **≥ 0,75 como objetivo** | EXTERNAL independiente y autorizado, solo si se obtiene; informar cada clase |
| Latencia p95 del diagnóstico completo | **≤ 30 segundos como objetivo** | Flujo de solicitud a resultado visible; carga y hardware por acordar |
| Mínimos por clase y partición | TRAIN **150 imágenes/50 grupos**; VAL **40/20**; TEST **30/15**; EXTERNAL **20/10** si existe | Particiones de imágenes autorizadas y grupos independientes; conteos observados en G1 |
| Selección y desempeño adicional | F1 macro VAL **≥ 0,80**; F1 TEST por clase **≥ 0,70**; identificación automática de cultivo fuera del piloto | Evaluación según partición indicada y soporte por clase |
| Rechazo y calibración | FPR en negativos **≤ 0,05**; rechazo de negativos **≥ 0,95**; ECE **≤ 0,15** | Negativos autorizados y resultados de G2; no son resultados ya medidos |
| Cobertura selectiva | **≥ 0,70** | Diagnósticos aceptados / imágenes válidas de las dos clases del piloto; NO_CONCLUYENTE cuenta como abstención |
| Error selectivo | **≤ 0,10** | Diagnósticos aceptados incorrectos / diagnósticos aceptados; cero aceptados no cumple |
| Aceptación errónea de negativos | **≤ 0,10**, con límite efectivo FPR **≤ 0,05** | Negativos con diagnóstico de clase soportada aceptado / negativos evaluados; cero negativos no cumple |
| Presupuesto del modelo en CPU | Mediana **≤ 1000 ms**; p95 **≤ 2500 ms**; límite duro **≤ 4000 ms**; RSS **≤ 1024 MB** | Medición reproducible del modelo; distinta de p95 del flujo completo |

Informar además accuracy, precision, F1 por clase, matriz de confusión, calibración, proporción de `NO_CONCLUYENTE`, falsos aceptados de negativos, latencia y memoria CPU. Publicar **numeradores, denominadores y resultados por clase**, contando abstenciones como falsos negativos en recall de la clase verdadera. Elegir y justificar umbral de confianza en VAL, congelarlo antes de TEST y registrar cobertura/abstención; **no hay umbral numérico prefijado**. Una confianza calculada no es garantía de diagnóstico correcto.

## Estado de puertas

**G0: cerrado como diseño aprobado por el responsable. G1: cerrado para el lote piloto. G2: aprobado para el bundle restringido tras TEST independiente.** El modelo y umbral se eligieron en VAL antes de TEST. Si una cifra cambia tras observar TEST, se versiona el protocolo y se usa un nuevo conjunto independiente; no se ajusta el criterio para aparentar cumplimiento.

La [plantilla de aplicación](../../ml/evaluation/g0-application-record.template.json) sigue vacía como plantilla reutilizable; las mediciones reales y el acta G2 se conservan en sus expedientes separados. Los conteos y exclusiones G1 se conservan en el [expediente del lote](INCREMENTO-4-G1-PILOTO-V1.2.md). Los mínimos y presupuesto aprobados permanecen inmutables en el [protocolo](../../ml/evaluation/protocol-g0.v1.2.0.json).

La auditoría de fuentes y la decisión de reducción constan en [el expediente](INCREMENTO-4-FUENTES-PARA-COMPLETAR-G1.md) y [ADR-0009](../adr/0009-modelo-validado-inferencia-y-politicas-de-publicacion.md).
