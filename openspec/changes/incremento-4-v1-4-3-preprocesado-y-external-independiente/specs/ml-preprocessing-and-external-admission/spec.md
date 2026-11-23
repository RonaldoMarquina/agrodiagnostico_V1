# Spec Delta

## Purpose

Define un contrato seguro de decodificación a RGB y la admisión verificable de
un conjunto EXTERNAL nuevo antes de consumir una evaluación independiente.

## ADDED Requirements

### Requirement: El preprocesado v1.4.3 decodifica formatos y modos explícitos
El sistema SHALL aceptar únicamente contenedores `JPEG`, `MPO`, `PNG`, `WEBP`
y `TIFF` correctamente identificados por sus bytes, con modos de origen `1`,
`L`, `LA`, `P`, `RGB`, `RGBA`, `CMYK` o `I;16`. SHALL aplicar orientación
EXIF, componer transparencia sobre fondo blanco cuando exista y convertir la
imagen explícitamente a `RGB` antes del resize bilineal 224×224 y la
normalización ImageNet. SHALL conservar los límites de tamaño, dimensiones,
tensor finito y aumentación exclusiva de TRAIN.

#### Scenario: Modo admitido se normaliza a RGB
- **WHEN** una imagen válida usa uno de los contenedores y modos admitidos
- **THEN** el tensor resultante tiene tres canales RGB, forma 3×224×224, valores finitos y normalización ImageNet

#### Scenario: Contenedor o modo fuera del contrato
- **WHEN** los bytes no corresponden a un contenedor admitido, el modo no está admitido o la imagen no puede verificarse completamente
- **THEN** el sistema rechaza la imagen antes de inferir y registra la causa sin reinterpretar su extensión

### Requirement: La política de frames evita contenido ambiguo
El sistema SHALL admitir el frame primario de un `MPO` válido y SHALL rechazar
animaciones o archivos multipágina `PNG`, `WEBP` y `TIFF`. El formato, modo y
número de frames detectados SHALL formar parte de la evidencia de
compatibilidad.

#### Scenario: MPO con frame primario válido
- **WHEN** un objeto `MPO` contiene un frame primario decodificable dentro de los límites
- **THEN** el sistema usa únicamente ese frame, lo registra como `MPO` y continúa con la conversión explícita a RGB

#### Scenario: Imagen animada o TIFF multipágina
- **WHEN** un `PNG`, `WEBP` o `TIFF` contiene más de un frame
- **THEN** el sistema lo rechaza como entrada ambigua antes de generar un tensor evaluable

### Requirement: El cambio de decodificación no altera el modelo congelado
El ciclo v1.4.3 SHALL conservar exactamente los pesos, la arquitectura, el mapa
de cuatro clases técnicas, la temperatura 0,50 y el umbral 0,80 del bundle
v1.4.2. Para una entrada `RGB` ya admitida, la orientación, resize,
normalización y tensor SHALL coincidir con el contrato congelado v1.4.2.

#### Scenario: Regresión de una entrada RGB compatible
- **WHEN** el mismo objeto JPEG, PNG o WEBP RGB se procesa con v1.4.2 y v1.4.3
- **THEN** ambos recorridos producen el mismo tensor y v1.4.3 no cambia parámetros de inferencia

#### Scenario: Artefacto del modelo modificado
- **WHEN** cambia el hash de pesos, arquitectura, mapa, calibración o umbral frente al freeze v1.4.2
- **THEN** el sistema rechaza su uso como candidato v1.4.3

### Requirement: Todo EXTERNAL pasa preflight completo antes del sello
El sistema SHALL decodificar sin inferencia todos los archivos de cualquier
candidato EXTERNAL antes de sellarlo. El preflight SHALL verificar ruta segura,
SHA-256, tamaño, formato, modo, dimensiones, frames, conversión RGB, tensor
3×224×224 finito y correspondencia uno a uno con el manifiesto. Un solo fallo
SHALL impedir el sello; no se permiten muestreo parcial ni exclusiones
silenciosas posteriores al preflight.

#### Scenario: Preflight completo satisfactorio
- **WHEN** cada fila del manifiesto corresponde a un archivo íntegro y todos se decodifican con el contrato v1.4.3
- **THEN** el sistema emite un registro de compatibilidad por SHA-256 y permite continuar hacia la revisión del sello sin cargar el modelo

#### Scenario: Falla un archivo del lote
- **WHEN** falta un archivo, cambia su SHA-256 o falla cualquier comprobación de decodificación o tensor
- **THEN** el sistema rechaza el lote completo antes del sello y no ejecuta predicciones ni métricas

### Requirement: El EXTERNAL v1.4.3 es nuevo, trazable e independiente
El sistema SHALL admitir únicamente imágenes de una revisión nueva con URL de
origen, versión, autor, licencia aplicable, SHA-256, etiqueta, decisión,
procedencia de captura y unidad de independencia demostrable. SHALL excluir
derivados, duplicados exactos o visuales y objetos con etiqueta o derechos
dudosos. Los conteos finales y los límites enteros de aceptación SHALL ser
definidos y aprobados por el responsable del proyecto antes de sellar el lote.

#### Scenario: Metadato o independencia insuficiente
- **WHEN** una imagen carece de licencia aplicable, procedencia, etiqueta revisable o unidad de independencia declarable
- **THEN** queda pendiente o excluida y no contribuye a ningún denominador EXTERNAL

#### Scenario: Criterios aprobados antes del sello
- **WHEN** concluyen la auditoría, deduplicación y preflight del lote nuevo
- **THEN** el responsable aprueba por versión sus estratos, denominadores, límites y limitaciones antes de crear el sello

### Requirement: Sikkim permanece como evidencia histórica no reutilizable
El sistema SHALL conservar Sikkim, su registro de acceso y el fallo técnico
v1.4.2 sin volver a procesar sus imágenes, generar predicciones ni calcular
métricas. Ningún archivo o denominador Sikkim SHALL formar parte del EXTERNAL,
TEST o decisión G2 de v1.4.3.

#### Scenario: Intento de reutilizar Sikkim
- **WHEN** un manifiesto, sello o comando v1.4.3 referencia el archivo, revisión, rutas o sello Sikkim históricos
- **THEN** el sistema rechaza la operación antes de abrir imágenes y conserva intacta la evidencia v1.4.2

#### Scenario: Consulta de la causa histórica
- **WHEN** se revisa el expediente del fallo v1.4.2
- **THEN** se informa `MPO` como formato detectado y `RGB` como modo, sin inferir métricas ni completar resultados ausentes
