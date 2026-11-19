# Design

## Context

El inventario `ml/manifests/` tiene fuentes PENDING, siete códigos CANDIDATE y un CSV sin imágenes admitidas. El validador comprueba estructura y separación por hash/grupo declarado, no bytes ni casi duplicados. `ml/datasets/` y `ml/models/` contienen estructura, no entrenamiento. El worker llama directamente al simulador y su arranque exige test; Diagnosis admite únicamente la versión sintética con umbral de fixture 0.9. `Problem.model_supported` inicia false y no es editable por API. Analyzed v1 transporta clase, cultivo, raw_score y versiones, no logits ni recomendaciones. Ver motivación en proposal.md.

## Goals / Non-Goals

**Goals:** poder reproducir una evaluación y asociar cada resultado publicado a pesos, datos, preprocesado, calibración, política y catálogo revisados. Preservar el flujo durable y contratos de autorización.

**Non-Goals:** prometer precisión antes de medir, automatizar aprobación experta, convertir feedback en etiquetas o completar interfaz/despliegue del incremento 5.

## Decisions

### D1. Puertas de evidencia y responsabilidades

El usuario confirmó incluir selección y aprobación como primeras tareas. Antigravity implementa herramientas y aporta reportes; el responsable del proyecto obtiene permisos y revisión de etiquetas, y acuerda criterios con el docente. No se inventan firmas ni se aprueba una fuente cambiando un booleano.

G0: protocolo fechado y aprobado antes de experimentar: definición de clases (incluida equivalencia de tizón foliar), mínimos de muestras/grupos por partición y clase, métricas por clase y cultivo, límites de error/abstención, negativos, calibración y presupuesto CPU/latencia/memoria. Los valores numéricos quedan pendientes de esa tarea, no son defaults productivos. G1: fuentes admitidas y dataset curado con particiones selladas. G2: evaluación independiente satisfactoria y paquete revisado. G3: aceptación real e integración con catálogo revisado. Si una puerta no se cumple, tareas dependientes permanecen abiertas; puede avanzar infraestructura con fixtures, nunca declarar modelo validado. El cierre exige soporte aprobado para ambos cultivos; cobertura menor a siete clases necesita aceptación explícita del alcance y registro de clases excluidas. Si ningún candidato cumple, no cerrar.

### D2. Datos y particiones

Conservar inventario v1 histórico y producir una nueva versión coherente de fuentes, taxonomía, mappings y manifiesto; no modificar significados de códigos. Admisión por revisión exacta, uso previsto, atribución y evidencia aplicable a imágenes. No elegir ahora PlantVillage/PlantDoc/PlantSeg por popularidad: se revisan en G0/G1. Guardar bytes y localización privada fuera de Git; resolver image_id/hash mediante índice privado sin URL pública ni coordenadas en reportes.

Ingestión explícita de fuentes autorizadas, límite de archivos/bytes, rutas seguras, decodificación y hash real. Cuarentena privada y registro de decisiones. Agrupar componentes relacionados globalmente entre fuentes mediante metadatos, hash y búsqueda de similares revisada; un algoritmo perceptual no acredita independencia por sí solo. Si solo se conoce la fuente, agrupar conservadoramente por fuente; no relajar agrupamiento para conseguir cantidades. Augmentations solo TRAIN y después de dividir. TEST/EXTERNAL inmutables con checksum y registro de acceso. Negativos de otros cultivos/objetos/calidad/ambigüedad en manifiesto separado autorizado y relacionado con los mismos grupos; no introducir NO_CONCLUYENTE ni nuevas enfermedades en taxonomía v1.

### D3. Experimentos reproducibles y cultivo automático

Crear paquete ML aislado con lock CPU y comandos de curación, partición, entrenamiento, calibración, evaluación y empaquetado. Mantener CI sin GPU. Pesos preentrenados, si se usan, requieren procedencia/licencia y checksum; descargas explícitas fuera de ejecución del servicio.

Comparar clasificación conjunta cultivo/clase y alternativa con identificación de cultivo seguida de clasificación, usando mismos datos, presupuesto y protocolo. La elección se hace en VAL por criterios G0, no usando TEST. Registrar configuración, semilla, commit, dependencias, hardware, tiempos y tolerancias de reproducibilidad; no exigir bit a bit entre hardware distinto. El artefacto final encapsula todos los componentes elegidos y su preprocesado. Fuera de dominio/imagen ambigua requiere mecanismo evaluado de rechazo: argmax entre siete clases no demuestra reconocimiento de cultivo desconocido.

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

La aceptación experimental es comando separado con dataset y release autorizados, no credenciales privadas en PR. Produce informe por clase, aprobación, checksum y E2E HTTP → cola → worker real → Diagnosis → historial para ambos cultivos, negativos, aislamiento y catálogo revisado. No forzar predicciones por ID/imagen fixture para aparentar métricas. Repetir redelivery, lease vencido, timeout y restart del artefacto cargado; preservar un resultado lógico. CI verde acredita herramientas; G0–G3 y evidencias reales acreditan cierre del incremento.

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
su implementación y aceptación. G0/G1/G2/G3 requieren evidencia nueva verificable.
