# Design

## Context

El inventario `ml/manifests/` tiene fuentes PENDING, siete códigos CANDIDATE y un CSV sin imágenes admitidas. El validador comprueba estructura y separación por hash/grupo declarado, no bytes ni casi duplicados. `ml/datasets/` y `ml/models/` contienen estructura, no entrenamiento. El worker llama directamente al simulador y su arranque exige test; Diagnosis admite únicamente la versión sintética con umbral de fixture 0.9. `Problem.model_supported` inicia false y no es editable por API. Analyzed v1 transporta clase, cultivo, raw_score y versiones, no logits ni recomendaciones. Ver motivación en proposal.md.

## Goals / Non-Goals

**Goals:** poder reproducir una evaluación y asociar cada resultado publicado a pesos, datos, preprocesado, calibración, política y catálogo revisados. Preservar el flujo durable y contratos de autorización.

**Non-Goals:** prometer precisión antes de medir, automatizar aprobación experta, convertir feedback en etiquetas o completar interfaz/despliegue del incremento 5.

## Decisions

### D1. Puertas de evidencia y responsabilidades

El usuario confirmó incluir selección y aprobación como primeras tareas. Codex implementa herramientas y aporta reportes técnicos; el responsable del proyecto define y aprueba los criterios de diseño G0. La verificación de permisos y etiquetas de imágenes concretas corresponde a G1. No se inventan firmas ni se aprueba una fuente cambiando un booleano.

G0: protocolo de diseño fechado, versionado y aprobado por el responsable antes de entrenar con datos reales: dos tizones candidatos de papa, política de admisión, mínimos de muestras/grupos por partición y clase, métricas por clase y rechazo de negativos, límites de cobertura/error/abstención, negativos, calibración y presupuesto CPU/latencia/memoria. El responsable aprueba los valores del protocolo v1.2.0; G0 no acredita datos ni resultados. G1: derechos y revisión de imágenes seleccionadas, fuentes admitidas y dataset curado con particiones selladas. G2: resultados medidos en evaluación independiente y paquete revisado. G3: aceptación real e integración con catálogo revisado. Si una puerta no se cumple, tareas dependientes permanecen abiertas; puede avanzar infraestructura con fixtures, nunca declarar modelo validado. El cierre exige soporte aprobado para los dos tizones de papa; la reducción a dos clases ya tiene aprobación explícita del responsable y registro de exclusiones. Si ningún candidato cumple, no cerrar.

Enmienda prospectiva del 2026-11-20: la aceptación real del bundle v1.2.0 encontró cuatro falsas aceptaciones de papa sana en cuatro controles. El responsable eligió preparar G0 v1.3.0 para rechazarla. Esta elección no aprueba los parámetros de la nueva versión ni extiende G1/G2 v1.2.0. El nuevo ciclo conservará las dos clases publicables y añadirá papa sana como estrato negativo fuera de cobertura; requerirá derechos y grupos revisados, umbrales por estrato aprobados antes de entrenar y un TEST nuevo no expuesto para ambos tizones y negativos. El TEST anterior ya abierto no puede aprobar un modelo modificado por este hallazgo. [Plan y déficit](../../../docs/evidence/INCREMENTO-4-CICLO-RECHAZO-PAPA-SANA.md).

Decisión del responsable (2026-11-19, protocolo v1.2.0): en TEST independiente se exige F1 macro ≥ 0,85 y recall ≥ 0,80 para cada una de las dos clases del piloto, con abstenciones como falsos negativos. En fotografías reales independientes, si se dispone de un conjunto autorizado, el objetivo inicial es F1 macro ≥ 0,75 y resultados por clase. Cobertura ≥ 0,70 significa diagnósticos aceptados entre imágenes válidas de las dos clases del piloto; error selectivo ≤ 0,10 significa aceptados incorrectos entre aceptados, y no cumple con denominador cero. La aceptación errónea de negativos ≤ 0,10 usa negativos evaluados como denominador; el límite anterior FPR ≤ 0,05 y rechazo ≥ 0,95 usan la misma población y siguen siendo el criterio efectivo más estricto. Se publicarán numeradores, denominadores y valores por clase, además de accuracy, precision, confusión, latencia y proporción de NO_CONCLUYENTE. La meta p95 ≤ 30 s corresponde al flujo completo y no se ha medido. El umbral de publicación se seleccionará y justificará en VAL, se congelará antes de TEST y no se interpretará como probabilidad de diagnóstico correcto. El 87 % histórico no es criterio G0. Estas metas aprobadas no son resultados; derechos de imágenes pertenecen a G1 y resultados a G2. Si se revisan criterios tras ver TEST, esa evaluación no puede reutilizarse para acreditar el modelo ajustado.

### D2. Datos y particiones

Conservar inventario v1 histórico y producir una nueva versión coherente de fuentes, taxonomía, mappings y manifiesto; no modificar significados de códigos. Admisión por revisión exacta, uso previsto, atribución y evidencia aplicable a imágenes. La prioridad de investigación no admite automáticamente PlantVillage/PlantDoc/PlantSeg: se revisan en G0/G1. Guardar bytes y localización privada fuera de Git; resolver image_id/hash mediante índice privado sin URL pública ni coordenadas en reportes.

El responsable prioriza la distribución PlantVillage publicada por su autor como candidata inicial de entrenamiento, con su declaración CC BY-SA 3.0 y atribución; PlantDoc es candidato complementario para evaluación en condiciones más reales, con declaración CC BY 4.0 en su repositorio pero derechos de fotografías obtenidas de Internet por verificar. PlantSeg se considera solo para uso académico no comercial, sujeto a versión, permiso aplicable y derechos de cada imagen. Ninguna prioridad equivale a admisión: registrar URL, revisión exacta, licencia declarada, atribución, restricciones y decisión humana antes de incorporar bytes. Ayacucho sería EXTERNAL independiente si se obtiene permiso; hasta entonces no hay medición de generalización local. IP102 queda fuera de las dos clases del piloto de enfermedades y se reserva para investigar plagas en un cambio posterior. La tabla de equivalencias por fuente excluye etiquetas dudosas o no equivalentes: `Corn rust leaf`, `corn rust` y `Corn leaf blight` quedan `UNMAPPED`, aunque se conserve su texto original para revisión. Los siete códigos permanecen en el inventario histórico; solo los dos tizones de papa son candidatos del piloto y ninguno es publicable antes de G2.

Ingestión explícita de fuentes autorizadas, límite de archivos/bytes, rutas seguras, decodificación y hash real. Cuarentena privada y registro de decisiones. Agrupar componentes relacionados globalmente entre fuentes mediante metadatos, hash y búsqueda de similares revisada; un algoritmo perceptual no acredita independencia por sí solo. Si solo se conoce la fuente, agrupar conservadoramente por fuente; no relajar agrupamiento para conseguir cantidades. Augmentations solo TRAIN y después de dividir. TEST/EXTERNAL inmutables con checksum y registro de acceso. Negativos de otros cultivos/objetos/calidad/ambigüedad en manifiesto separado autorizado y relacionado con los mismos grupos; no introducir NO_CONCLUYENTE ni nuevas enfermedades en taxonomía v1.

### D3. Experimentos reproducibles del piloto de papa

Crear paquete ML aislado con lock CPU y comandos de curación, partición, entrenamiento, calibración, evaluación y empaquetado. Mantener CI sin GPU. Pesos preentrenados, si se usan, requieren procedencia/licencia y checksum; descargas explícitas fuera de ejecución del servicio.

Comparar dos alternativas de clasificación y rechazo para los dos tizones de papa, usando mismos datos, presupuesto y protocolo. La elección se hace en VAL por criterios G0, no usando TEST. Registrar configuración, semilla, commit, dependencias, hardware, tiempos y tolerancias de reproducibilidad; no exigir bit a bit entre hardware distinto. El artefacto final encapsula todos los componentes elegidos y su preprocesado. Fuera de dominio/imagen ambigua requiere mecanismo evaluado de rechazo: argmax entre dos tizones no demuestra rechazo de imágenes ajenas.

### D4. Calibración compatible con Analyzed v1

Mantener `raw_score` como puntuación técnica de la clase ganadora, no renombrarla como probabilidad clínica ni sobrescribirla con confianza calibrada. Ajustar en VAL una función versionada por clase de ese score (por ejemplo calibración escalar) y umbrales que Diagnosis pueda reproducir desde el payload actual. Elegir método en validación y medir limitaciones; no exigir temperature scaling de logits que Analyzed v1 no transporta. Si la evidencia exige otro payload, detener integración y proponer versión nueva antes de implementarlo.

AI aplica controles técnicos de cultivo/calidad con parámetros del artefacto; emite PREDICTION, ABSTENTION o FAILURE contractual. Diagnosis conserva la decisión de publicación y calibración final. BAD_IMAGE se reserva a bytes decodificables de calidad visual insuficiente; archivos inválidos siguen rechazándose antes del diagnóstico. Reportar accuracy, precision/recall/F1 por clase y macro, confusión, calibración, cobertura/error, abstención y falsos aceptados en negativos, tamaños e incertidumbre. No ocultar clases fallidas en promedios. Selección/ajuste solo TRAIN/VAL; si TEST inspira cambios, ese conjunto deja de ser evaluación independiente y se documenta nuevo ciclo con test no usado.

### D5. Artefacto inmutable y worker real

Contrato propuesto `contracts/ml/model-bundle.v1.schema.json`: schema_version, model_id, model_version, dataset_version, checksums de pesos y manifiestos, arquitectura permitida, class_map, preprocesado, componentes de rechazo, versiones de entorno y referencia de evaluación/aprobación. El checksum vincula bytes pero no confiere confianza: el paquete debe provenir del repositorio privado de releases autorizado. Cargar tensores con mecanismo seguro, sin imports/código arbitrario aportado por el paquete; validar rutas, tamaños, finitud, dimensiones y mapa. Nunca descargar pesos al recibir solicitudes.

Introducir adaptador real y selección explícita de modo al arranque. El simulador mantiene doble guardia test y habilitación; perfil `async-test` conserva aceptación del incremento 3. Perfil propuesto `ml-real` requiere montaje de release aprobado de solo lectura, sin fallback sintético. Cargar y comprobar antes de consumir; artefacto ausente/corrupto/incompatible impide iniciar consumo. API sigue disponible y outbox conserva trabajo. Inferencia acotada sin bloquear heartbeat; timeout/recuperación respetan presupuesto de Diagnosis. Se mantienen identidad interna, acceso a foto por lease, fencing y transacción de resultado/outbox antes de ACK.

### D6. Política propia de Diagnosis y soporte efectivo

Contrato propuesto `contracts/ml/publication-policy.v1.schema.json`: policy_id/version, tupla exacta modelo/dataset, digest del bundle, clases aprobadas, calibradores/umbrales, referencias de G0/G2 y revisión. Importación CLI operativa con dry-run por defecto, aplicación explícita, actor/motivo y auditoría atómica; no añadir endpoint público ni permitir PATCH de model_supported. Validar coeficientes finitos, rangos y compatibilidad del mapa; rechazo si falta evidencia. Diagnosis almacena políticas inmutables y activa una versión; activar/retirar actualiza soporte efectivo de catálogo en la misma transacción. Soporte de catálogo describe política activa, no clases candidatas ni recomendaciones aprobadas automáticamente.

Añadir a resultado snapshot de policy_id/version/digest y confianza calibrada, sin alterar raw_score ni snapshots de catálogo. Evolución del contrato de detalle: campos aditivos opcionales para nuevos resultados, históricos sin política permanecen legibles y no se recalibran. Registrar migración propia de Diagnosis y actualizar esquemas compartidos/OpenAPI/fixtures/cliente tipado antes de integrar. Analyzed v1, Requested v2 y Finished v1 permanecen sin campos nuevos. Evaluar exactamente versión permitida; desconocida/retirada o clase no validada produce UNSUPPORTED_CLASS, score insuficiente LOW_CONFIDENCE y catálogo ausente CATALOG_UNAVAILABLE, conservando la precedencia vigente del consumidor. La desactivación concurrente y finalización se serializan en DB para no publicar con una política retirada.

Alternativa descartada: habilitar soporte global mediante semillas o confiar en el catálogo como prueba de validación. La política es la autoridad; no se escriben tablas ajenas ni se permite que AI publique recomendaciones.

### D7. Pruebas técnicas y aceptación real

Agregar etapa obligatoria `ml-contracts-and-runtime` al plan CI, sin GPU, descarga de dataset ni pesos reales. Usar paquete tensorial mínimo generado para comprobar carga e inferencia real del runtime, separado del simulador de cola y rotulado fixture sin valor agronómico. Mantener todas las etapas previas y ejecución desde checkout sin .env, aprendiendo del correctivo c1466f7.

La aceptación experimental es comando separado con dataset y release autorizados, no credenciales privadas en PR. Produce informe por clase, aprobación, checksum y E2E HTTP → cola → worker real → Diagnosis → historial para ambos tizones, negativos, aislamiento y catálogo revisado. No forzar predicciones por ID/imagen fixture para aparentar métricas. Repetir redelivery, lease vencido, timeout y restart del artefacto cargado; preservar un resultado lógico. CI verde acredita herramientas; G0–G3 y evidencias reales acreditan cierre del incremento.

## Risks / Trade-offs

- Datos homogéneos de laboratorio → evaluar contexto de captura y negativos; no declarar generalización a Ayacucho si no existe conjunto externo autorizado.
- Agrupamiento conservador impide suficientes particiones → obtener otras fuentes/grupos o mantener G1 pendiente; no dividir copias relacionadas.
- Revisión humana y cómputo no disponibles → completar herramientas con fixtures y dejar entrenamiento/promoción abiertos, sin evidencias ficticias.
- Modelo lento supera lease → medir CPU, limitar ejecución y mantener heartbeat independiente; documentar presupuesto antes de activar.
- Cambio de versión con trabajos en vuelo → pausa/drain de workers, política exacta y rechazo conservador de resultados de versión retirada; nunca revertir terminales.
- Catálogo sin contenido revisado → no inventar recomendaciones; COMPLETADO real requiere paquete revisado por clase admitida.

## Migration Plan

1. Registrar ADR de estas decisiones y aprobar G0; contratos de bundle/política/detalle antes de consumidores.
2. Migraciones aditivas y lectura de históricos; pruebas upgrade/rollback aisladas sin modificar volúmenes de desarrollo.
3. Instalar runtime, montar release y probarlo sin consumir; importar política en dry-run y validar catálogo.
4. Aplicar política aprobada y activar `ml-real` de forma controlada tras G2. No mezclar consumidores sintéticos con colas reales.
5. Rollback: detener nuevos reclamos reales, retirar política auditadamente y restaurar release/política previa aprobada si existe. Sin previa, mantener procesamiento deshabilitado; jamás volver al simulador. Conservar filas de resultados, políticas e historia. No ejecutar downgrade destructivo sobre resultados nuevos.
6. Cerrar solo con G3, CI local/remoto identificados, specs sincronizadas y evidencia real; actualizar docs al estado observado.

## Estado de corrección — 2026-10-15

La revisión encontró CLI sin entrenamiento/evaluación efectiva, adaptadores lineales
JSON presentados como arquitecturas de PyTorch, preprocesados divergentes y aprobaciones
sin respaldo. Se bloquean temporalmente los comandos de release y el arranque real para
impedir resultados falsamente válidos. Esto NO reduce los requisitos D1–D7 ni sustituye
su implementación: las tareas afectadas vuelven a pendientes. Los fixtures conservan
solo valor técnico; las especificaciones propuestas permanecen en este cambio hasta
su implementación y aceptación. G0 dispone de aprobación de diseño del responsable; G1/G2/G3 requieren evidencia nueva verificable.

## Recorrido técnico CPU — 2026-11-19

Se añadió un paquete PyTorch CPU instalable desde lock y un smoke explícitamente `FIXTURE_ONLY`: MobileNetV3-Small conjunta y ResNet18 jerárquica con pesos aleatorios iniciales, preprocesado tensorial común y checkpoints safetensors con hash. Ninguno es un bundle G2; producción sigue cerrada. La alternativa usa `resnet18_hierarchical` como identificador **interno** para no presentarla como el `resnet18` conjunto permitido hoy por `model-bundle.v1`. Antes de promoverla se deberá definir en el contrato de bundle la topología y salida de cultivo/condición, sin alterar Analyzed v1 por inferencia ni aceptar un artefacto solo porque sea legible. Los resultados de VAL_FIXTURE no sustituyen VAL autorizada ni criterios G0.

## Admisión G1 del lote piloto — 2026-11-19

El [expediente G1](../../../docs/evidence/INCREMENTO-4-G1-PILOTO-V1.2.md) cerró la admisión de los dos tizones y negativos de tomate de la distribución fijada de PlantVillage, con `leaf_id` verificable, revisión de derechos por SHA-256, control interno de calidad y TEST sellado. La procedencia experta de etiquetas es de PlantVillage; el proyecto no atribuye una nueva revisión agronómica independiente. Este cierre habilitó los experimentos en TRAIN/VAL descritos en la decisión siguiente; TEST y G2 siguen pendientes.

## Entrenamiento y selección en VAL — 2026-11-19

La [comparación real](../../../docs/evidence/INCREMENTO-4-ENTRENAMIENTO-VAL-PILOTO.md) reemplaza la alternativa jerárquica de los fixtures para el piloto v1.2.0. El cultivo ya fue identificado como `POTATO` por el usuario. MobileNetV3-Small y ResNet18 clasifican los dos tizones directamente y usan `OTHER_CROP` solo como objetivo técnico de rechazo. Ambos se entrenaron desde pesos aleatorios con el mismo TRAIN/VAL, preprocesado y presupuesto CPU. MobileNetV3 cumplió los criterios de selección en VAL; ResNet18 falló el límite de negativos. Se ajustó calibración por clase en VAL, se eligió umbral 0,50 y se congelaron pesos, configuración, umbral, protocolo y hashes antes de TEST. La medición en VAL no aprueba G2, no acredita rechazo de papa sana ni generalización a campo; TEST no se abrió y el worker real sigue bloqueado.

## Evaluación única del TEST sellado — 2026-11-19

Después del congelamiento se abrió TEST una sola vez con los mismos pesos, preprocesado, calibración, umbral y mapa. El [reporte por clase](../../../docs/evidence/INCREMENTO-4-TEST-PILOTO-V1.2.md) cumple los límites numéricos G0 v1.2.0 y deja EXTERNAL como no disponible. Los resultados de TEST no cambiaron el candidato. El paquete privado de revisión es `READY_FOR_G2_REVIEW_UNAPPROVED`; un bundle de release aprobado, integración del worker real y evidencia G3 siguen pendientes.

## Aprobación G2 del bundle restringido — 2026-11-19

El [acta G2](../../../docs/evidence/INCREMENTO-4-APROBACION-G2-PILOTO.md) vincula el bundle privado `model-bundle.v1` al congelamiento, protocolo v1.2.0, manifiestos y reporte TEST. La carga independiente en otro proceso verificó `safetensors`, configuración GroupNorm, preprocesado, calibración, umbral 0,50, mapa publicable de dos tizones, hashes y salida sintética. El responsable aprobó G2 tras esa verificación; la decisión no atribuye evaluación EXTERNAL, rechazo demostrado de papa sana ni latencia del flujo completo. El contrato piloto exige `identified_crop=POTATO` y rechazo técnico `OTHER_CROP` en lugar de inventar un umbral de detección automática de cultivo. El worker real, política y catálogo permanecen inactivos hasta 6.1–6.4 y las tareas posteriores de G3.

## Preparación técnica 6.1–6.4 — 2026-11-20

Se implementó un adaptador PyTorch CPU que carga el bundle G2 con hash de manifiesto y acta fijados, aplica exactamente el preprocesado y calibración congelados y emite solo los dos tizones o abstención. La ejecución por solicitud ocurre en proceso `spawn` acotado a 20 segundos, mientras el worker conserva heartbeat, fencing y transacción resultado/inbox/outbox antes del ACK. El perfil `ml-real` usa imagen dedicada, montaje privado de solo lectura y validación de arranque previa al consumo. [Pruebas y límites](../../../docs/evidence/INCREMENTO-4-WORKER-CPU-PREPARADO.md). El perfil no se activó: la política, el catálogo y G3 siguen pendientes.
