# Design

## Context

Véase [proposal.md](proposal.md). v1.4.1 fijó cuatro salidas técnicas, sampler 80×4 y selección VAL, pero su candidato aleatorio GroupNorm falló recall temprano y rechazo sano. v1.4.2 no modifica G0, datos, umbrales ni publicabilidad; introduce una segunda configuración MobileNetV3-Small inicializada con un checkpoint ImageNet oficial.

TorchVision instalado en el contenedor actual reporta PyTorch `2.15.0+cpu`, TorchVision `0.29.2+cpu` y `MobileNet_V3_Small_Weights.IMAGENET1K_V1`. El checkpoint oficial fue entrenado con BatchNorm; la línea base v1.4.1 usa GroupNorm. La comparación determina qué configuración completa satisface VAL, pero no atribuirá causalidad exclusivamente a la inicialización.

## Goals / Non-Goals

**Goals:**

- Fijar y verificar la procedencia del checkpoint antes de cualquier entrenamiento.
- Ejecutar transferencia en dos fases manteniendo exactamente el contrato de datos y publicación v1.4.1.
- Comparar contra v1.4.1 solo mediante evidencia histórica agregada y seleccionar exclusivamente con VAL.
- Mantener adquisición del peso separada física y temporalmente del entrenamiento offline.

**Non-Goals:**

- Cambiar G0/G1, mínimos VAL, preprocesado agronómico, sampler o aumentos.
- Reentrenar la línea base v1.4.1, usar sus pesos como warm start o reinterpretar su fallo.
- Descargar ImageNet, redistribuir el checkpoint, autorizar uso comercial o resolver jurídicamente derechos de imágenes de origen.
- Abrir Sikkim, TEST histórico, activar el worker o obtener G2 en este paso de diseño.

## Decisions

### 1. Checkpoint y procedencia fijados

El único peso base candidato será:

| Campo | Valor fijado |
| --- | --- |
| API | `torchvision.models.MobileNet_V3_Small_Weights.IMAGENET1K_V1` |
| TorchVision de ejecución | `0.29.2+cpu` |
| PyTorch de ejecución | `2.15.0+cpu` |
| URL oficial | `https://download.pytorch.org/models/mobilenet_v3_small-047dcff4.pth` |
| Nombre | `mobilenet_v3_small-047dcff4.pth` |
| Tamaño esperado | `10.306.551` bytes; se confirmará sobre la descarga |
| SHA-256 esperado | `047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f` |
| Parámetros declarados | `2.542.856` |
| Métrica publicada | ImageNet-1K acc@1 `67,668`, acc@5 `87,402` |
| Receta | `https://github.com/pytorch/vision/tree/main/references/classification#mobilenetv3-large--small` |
| Código fuente | `https://github.com/pytorch/vision/blob/main/torchvision/models/mobilenetv3.py` |
| Transformación de referencia | resize 256, crop central 224, RGB `[0,1]`, mean `[0.485,0.456,0.406]`, std `[0.229,0.224,0.225]` |

La descarga futura será explícita, con TLS verificado, a un archivo temporal fuera del repositorio. Se registrarán URL solicitada/final, fecha, cabeceras no sensibles, tamaño y SHA-256 completo. El prefijo `047dcff4` que TorchVision comprueba con `check_hash=True` no basta. Después se cargará offline mediante `torch.load(..., weights_only=True, map_location="cpu")`, se exigirá un `state_dict` con el mapa esperado y se moverá a almacenamiento privado de solo lectura. El entrenamiento no tendrá salida de red.

### 2. Condiciones de uso conservadoras

El código TorchVision está publicado bajo BSD-3-Clause. Su documentación advierte que los modelos preentrenados pueden tener licencias o condiciones derivadas del dataset y responsabiliza al usuario de comprobar el uso. ImageNet declara acceso para investigación/educación no comercial y no garantiza derechos sobre cada imagen.

Fuentes de términos fijadas para el expediente: `https://github.com/pytorch/vision/blob/main/LICENSE`, `https://github.com/pytorch/vision#pre-trained-model-license` y `https://www.image-net.org/download.php`. La fuente primaria de la URL, enum y receta del peso es el código oficial TorchVision indicado en la tabla. El SHA-256 completo esperado se tratará como una expectativa a comprobar sobre los bytes descargados; solo el hash calculado localmente, no una referencia secundaria, permitirá admitirlos.

Por ello el registro no afirmará que BSD-3-Clause despeja los derechos del checkpoint. La admisión v1.4.2 quedará limitada al proyecto académico/no comercial, conservará atribución a TorchVision/ImageNet, no redistribuirá el `.pth` y requerirá nueva revisión antes de cualquier uso comercial. Esta es una política conservadora del proyecto, no una opinión legal.

### 3. Preprocesado constante para la comparación

Se conserva el preprocesado v1.4.1: tensor RGB 224×224 y normalización ImageNet. La transformación oficial de referencia se registra como procedencia, pero no sustituye silenciosamente el resize ya fijado porque hacerlo mezclaría inicialización y preprocesado. Cambiar a resize 256/crop 224 exigiría otro ciclo previo al entrenamiento.

### 4. BatchNorm oficial preservado y congelado

Se cargará el modelo oficial completo antes de reemplazar su clasificador de 1.000 por una cabeza aleatoria de cuatro salidas. No se convertirá BatchNorm a GroupNorm porque descartaría estadísticas oficiales. Durante ambas fases, BatchNorm permanecerá en `eval`, sin actualizar medias/varianzas; sus parámetros afines tampoco recibirán gradientes.

Esta decisión hace que la comparación v1.4.1/v1.4.2 sea entre configuraciones completas —aleatoria+GroupNorm frente a ImageNet+BatchNorm congelado— y no una ablación pura. Se prefiere a destruir parte del checkpoint o actualizar estadísticas con lotes de 16.

### 5. Entrenamiento en dos fases pre-registradas

- **Fase HEAD:** 3 épocas; backbone totalmente congelado; cabeza AdamW `lr=1e-3`.
- **Fase FINE_TUNE:** 12 épocas adicionales; se descongelan los últimos tres bloques `features` y la cabeza; AdamW con `lr=1e-5` para backbone y `lr=1e-4` para cabeza; BatchNorm permanece congelado.
- Ambas fases usan semilla 42, batch 16, CPU 4 hilos, sampler 80×4 y 320 exposiciones por época.
- Solo `POTATO_HEALTHY` TRAIN recibe los aumentos conservadores ya fijados. VAL nunca se aumenta.

No se buscarán cantidades de épocas o tasas alternativas con VAL. VAL puede elegir el estado de una de las 15 épocas y su política, pero los hiperparámetros anteriores quedan congelados antes de entrenar.

### 6. Selección y comparación

Cada época produce logits sobre las 496 filas VAL. Para cada estado se ajusta temperatura y se elige umbral solo con VAL, aplicando exactamente las siete condiciones vigentes. El ranking primero exige cumplimiento total; si ninguno cumple, registra el menor incumplimiento solo como diagnóstico experimental, nunca como elegible.

La tabla final compara v1.4.2 con el resumen inmutable v1.4.1 (`ml/evaluation/train-val-result.v1.4.1.json`). No carga pesos ni predicciones históricos y no reoptimiza la política v1.4.1. “Selección de arquitectura” se interpreta como selección entre las configuraciones completas de MobileNetV3-Small; si v1.4.2 no cumple todo, ninguna gana autorización.

### 7. Congelamiento condicionado

Solo si una época v1.4.2 cumple todas las mínimas se congelan checkpoint base, pesos ajustados, configuración, mapa técnico/publicable, preprocesado, fases, calibración, umbral, manifiestos, dependencias y comandos. El congelamiento no abre Sikkim: requiere una solicitud posterior y separada.

## Risks / Trade-offs

- **Términos del checkpoint no equivalen a BSD del código** → limitar a investigación/educación no comercial, registrar fuentes y no redistribuir.
- **Comparación no aísla solo la inicialización por BatchNorm/GroupNorm** → describirla como comparación de configuraciones completas y no afirmar causalidad.
- **Dominio ImageNet distinto de hojas controladas** → mantener mínimos VAL y rechazo; una mejora parcial no habilita EXTERNAL.
- **Sobreajuste a VAL por evaluar 15 épocas y políticas** → prerregistrar fases/tasas, conservar la misma búsqueda de calibración/umbral y no añadir intentos después de ver resultados.
- **BatchNorm congelado puede limitar adaptación** → aceptar el límite en v1.4.2; cambiarlo exige otro ciclo previo.
- **Descarga mutable o comprometida** → URL oficial, TLS, tamaño y SHA-256 completo; entrenamiento offline desde montaje de solo lectura.

## Migration Plan

1. Crear el registro de procedencia y términos sin descargar datos agronómicos.
2. Descargar explícitamente el `.pth`, comprobar tamaño/SHA-256 completo y validar carga segura; si falla, cerrar el intento sin entrenar.
3. Implementar configuración, fases y pruebas con fixtures sintéticos; verificar que no existen rutas TEST/Sikkim.
4. Hacer commit local de código, configuración y registro del peso antes del entrenamiento.
5. Entrenar HEAD y FINE_TUNE solo con TRAIN; seleccionar estado/calibración/umbral solo con VAL.
6. Registrar comparación y, únicamente si todas las mínimas pasan, congelar candidato privado previo a EXTERNAL.

Rollback consiste en no promover v1.4.2 y conservar v1.4.1 como último ciclo medido no elegible. Los commits y artefactos históricos no se modifican.
