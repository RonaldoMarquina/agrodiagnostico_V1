# Design

## Context

Véase `proposal.md` para la motivación. La revisión técnica, limitada a
metadatos de decodificación y SHA-256, examinó las 362 entradas selladas de
Sikkim sin cargar el modelo: 360 se identificaron como `JPEG/RGB` y dos como
`MPO/RGB`. La primera entrada que el contrato v1.4.2 habría rechazado fue el
índice 127, ruta privada `Potato_Field_Dataset/potato (36).JPG`, SHA-256
`8e0993659311bde40bca316cb6f6721055eb76a1e012a3d970c511551cb2297f`,
6000×4000, `MPO/RGB`. Los 362 objetos podían convertirse a RGB. No se cargaron
pesos, no se generaron logits o predicciones y no se calcularon métricas.

La extensión `.JPG` no era evidencia suficiente del contenedor. La causa fue
la comprobación `format in {JPEG, PNG, WEBP}` anterior a la conversión RGB, no
un modo `CMYK`, `RGBA`, `P` ni un TIFF. Sikkim ya consumió su apertura y queda
fuera del ciclo nuevo.

## Goals / Non-Goals

**Goals:**

- Separar verificación del contenedor, política de frames, conversión de color
  y transformación tensorial en un contrato auditable.
- Descubrir cualquier incompatibilidad de un EXTERNAL completo antes de su
  sello y antes de la primera inferencia.
- Seleccionar una fuente nueva por evidencia legal, diagnóstica y de
  independencia, no por cantidad publicada.
- Demostrar que el cambio operativo no altera el modelo ni las entradas RGB ya
  compatibles.

**Non-Goals:**

- Reabrir Sikkim, reconstruir sus predicciones parciales o completar sus
  métricas.
- Reentrenar, recalibrar, buscar otro umbral o cambiar pesos y arquitectura.
- Aprobar una fuente por su página pública sin auditar sus archivos exactos.
- Ejecutar la evaluación independiente o cerrar G2 dentro de la materialización
  inicial de este cambio.
- Activar el worker real, importar una política o avanzar G3.

## Decisions

### 1. Contrato finito de formatos, modos y frames

Se admitirán contenedores detectados por bytes `JPEG`, `MPO`, `PNG`, `WEBP` y
`TIFF`; modos `1`, `L`, `LA`, `P`, `RGB`, `RGBA`, `CMYK` e `I;16`. La
transparencia se compondrá sobre blanco antes de RGB. Se rechazará cualquier
modo fuera de la lista, en vez de confiar en que una conversión genérica sea
semánticamente segura.

`MPO` usará solo el frame primario que Pillow presenta como frame 0 y quedará
registrado como `MPO`; no se fingirá que es JPEG. PNG/WEBP animados y TIFF
multipágina se rechazarán porque elegir un frame ocultamente cambiaría el
contenido evaluado. Se consideró aceptar cualquier formato que Pillow pudiera
abrir, pero se descarta por superficie de ataque, semántica de frames y falta
de fixtures contractuales.

### 2. Orden determinista de transformación

El recorrido será: límite de bytes → identificación/verificación completa →
política de frames → carga del frame → límites de dimensiones → orientación
EXIF → composición de alpha → conversión RGB → resize bilineal directo
224×224 → tensor float32 → normalización ImageNet → comprobación de forma y
finitud. La aumentación seguirá permitida solo en TRAIN y no forma parte del
preflight EXTERNAL.

Cada formato/modo admitido tendrá un fixture generado localmente con contenido
identificado; se añadirán fixtures corruptos, con extensión engañosa,
animados/multipágina y excesivos. Una batería de regresión comparará tensores
v1.4.2/v1.4.3 para entradas RGB compatibles. Esta decisión conserva el
preprocesado aprendido y limita el cambio a la compatibilidad de decodificación.

### 3. Freeze derivado con parámetros de modelo idénticos

El bundle v1.4.3 referenciará los mismos hashes de pesos y arquitectura del
freeze v1.4.2, el mapa técnico de cuatro clases, temperatura 0,50 y umbral
0,80. Solo cambiarán la versión y hash del contrato de decodificación. El
validador comparará cada parámetro y bloqueará cualquier diferencia. No se
llamará “mismo bundle” porque el contrato operacional sí cambia; será un freeze
derivado y trazable.

### 4. Preflight EXTERNAL sin modelo

El preflight resolverá todas las rutas bajo una raíz privada, verificará el
SHA-256 contra el registro por archivo y ejecutará la transformación completa
hasta tensor. Producirá un registro JSONL por SHA con formato, modo, tamaño,
dimensiones, frames, shape, finitud y estado, más un resumen con hash del
manifiesto y del propio reporte. No importará pesos ni expondrá una opción de
inferencia.

El sello solo podrá referenciar un reporte completo cuya cardinalidad y conjunto
de hashes coincidan exactamente con el manifiesto admitido. Una exclusión exige
crear una revisión nueva del manifiesto y repetir todo el preflight antes del
sello; nunca se parchea un lote ya sellado.

### 5. Auditoría de la nueva fuente antes de elegir denominadores

La primera candidata es **PLDD-UP v1**, DOI
`10.17632/3j4nfkvp2n.1`, publicada con CC BY 4.0. Su ficha declara 4.803
imágenes EB, 6.116 LB y 4.600 sanas capturadas en campos de Uttar Pradesh con
cámaras y teléfonos. Es prometedora para los tres estratos de papa, pero la
ficha no demuestra grupos por planta/sesión ni resuelve por sí sola la revisión
de etiquetas, originales/derivados o duplicados.

Para el estrato `OTHER_CROP` se auditará primero el subconjunto **Raw_Dataset**
de tomate de **Pota-Toma-To v1**, DOI `10.17632/354fsxwccb.1`, también publicado
con CC BY 4.0. La ficha declara 435 imágenes totales y separa originales RGB de
una copia procesada; solo los originales podrían ser candidatos. Si los
conteos, derechos o independencia no alcanzan, se excluirá la fuente y se
buscará otra revisión primaria, sin reducir criterios silenciosamente.

La auditoría del archivo exacto de Pota-Toma-To confirmó 435 filas crudas, pero
las carpetas se denominan como resultados de Google Search y la descripción
interna solo declara agregación desde repositorios públicos, sin autor, URL ni
licencia por fotografía. La licencia de portada advierte que contenido de
terceros puede requerir permiso adicional. Por ello sus 435 archivos y todos
los derivados quedan excluidos; no aportan el estrato `OTHER_CROP`.

Como sustituto se incorpora **CornLeafDiseaseCollection v1**, DOI
`10.17632/w56xxnykcc.1`, CC BY 4.0. Sus autores declaran haber tomado las 1.079
fotografías en tres plantaciones experimentales de Manabí y publican por
archivo SHA-256, etiqueta, bloque, variedad y ubicación. La auditoría inicial
decodificó 1.079/1.079 JPEG/RGB y excluyó 38 archivos correspondientes a 19
hashes duplicados; quedan 1.041 candidatos antes de la revisión visual. Aunque
existen bloque y coordenadas, no hay identificador de planta o sesión: su
unidad admisible es imagen única y esa limitación no se convertirá en
independencia por planta.

Estas páginas son evidencia de candidatura, no de admisión. La implementación
descargará versiones exactas a almacenamiento privado, conservará hashes de
archivo fuente y por imagen, verificará licencia/atribución, inspeccionará el
árbol y metadatos, distinguirá originales de derivados, revisará etiquetas y
hará deduplicación exacta y visual contra TRAIN/VAL y evidencia histórica. Si
no hay identificador de planta o sesión, la unidad se declarará “imagen única”
con la limitación correspondiente; no se inventarán grupos.

### 6. Criterios del nuevo EXTERNAL se fijan después de la auditoría

Se preservarán como tasas de diseño F1 macro ≥0,75 y recall ≥0,75 por tizón,
rechazo sano ≥0,90 y publicación errónea sana ≤0,10, y publicación errónea de
otro cultivo no mayor que la política vigente aproximada de 5 %. Sin embargo,
los límites enteros y denominadores Sikkim 42/76/50/194 no se reutilizarán. El
responsable aprobará la tabla exacta v1.4.3 a partir de originales admitidos
antes de sellar; cualquier cambio posterior exige otro ciclo.

## Risks / Trade-offs

- [MPO puede contener más de una vista] → usar y registrar únicamente el frame
  primario; no admitirlo si el frame primario no es verificable.
- [Componer alpha o convertir CMYK cambia valores de píxel] → fijar el orden,
  versión de Pillow y fixtures hashados; reportar el modo original.
- [TIFF puede ser enorme o multipágina] → mantener límites de bytes/dimensiones,
  tratar advertencias de descompresión como error y admitir solo una página.
- [La fuente candidata puede ser derivada o no tener grupos] → auditar archivos
  exactos, excluir derivados y declarar independencia solo al nivel demostrado.
- [Dos fuentes crean dominios distintos] → reportar resultados por estrato y
  fuente; no presentar el agregado como independencia por planta.
- [Las tasas producen límites enteros ambiguos] → aprobar numerador y
  denominador exactos antes del sello, sin redondeo posterior a resultados.

## Migration Plan

1. Registrar la causa `MPO/RGB` y el veto de reuso Sikkim en evidencia v1.4.3.
2. Implementar el decodificador versionado, fixtures y regresión RGB sin montar
   ningún EXTERNAL real.
3. Implementar el preflight total y probarlo con lotes sintéticos.
4. Auditar las revisiones candidatas en almacenamiento privado y excluir todo
   archivo que no cumpla derechos, etiqueta, procedencia o independencia.
5. Aprobar los conteos, denominadores y límites enteros v1.4.3.
6. Ejecutar el preflight sobre la revisión admitida; corregir únicamente creando
   una revisión nueva y repitiendo antes del sello.
7. Crear el freeze derivado y el sello EXTERNAL, hacer commit y árbol limpio.
8. Proponer por separado la apertura única y evaluación G2. El rollback antes
   del sello consiste en retirar la revisión candidata; después del sello no se
   modifica y un fallo requiere otro ciclo.

## Open Questions

- Los conteos finales de PLDD-UP y de la selección CornLeaf de Manabí solo se
  fijan tras deduplicación, revisión interna identificada y preflight completo.
  Son una compuerta de admisión, no una suposición derivada de las portadas.
