> Actualización G1 del piloto v1.2.0, 2026-11-19: PlantVillage `color` quedó admitida para los dos tizones de papa y negativos de otro cultivo; [evidencia y límites](INCREMENTO-4-G1-PILOTO-V1.2.md). Los estados pendientes del texto inferior corresponden a la evaluación anterior de las siete clases.

> Alcance actual: G0 v1.2.0 aprueba únicamente los dos tizones de papa para el piloto. Las referencias a siete clases y maíz en esta evidencia describen el inventario o trabajo histórico. G1 está cerrado solo para el lote piloto documentado arriba. [Decisión](../adr/0009-modelo-validado-inferencia-y-politicas-de-publicacion.md).

# Incremento 4 — equivalencias y revisión de etiquetas

Tabla preparada el 2026-11-19 a partir de [`label-mappings.v2.json`](../../ml/manifests/label-mappings.v2.json) y [`taxonomy.v2.json`](../../ml/manifests/taxonomy.v2.json). El responsable aprobó en G0 la **denominación candidata** y la exclusión de etiquetas genéricas como diseño. Las siete clases siguen **candidatas**, sus definiciones están `PENDING_REVIEW` y ninguna equivalencia de imágenes cuenta con revisión especializada. Las cadenas de fuente son etiquetas publicadas, no diagnósticos verificados en imágenes.

| Código candidato y nombre | PlantVillage | PlantDoc | PlantSeg | Revisión agronómica pendiente |
| --- | --- | --- | --- | --- |
| `POTATO_HEALTHY` · papa sana | `Potato___healthy` | Sin etiqueta localizada | Sin etiqueta localizada | Definir qué evidencia visual permite «sana»; no implica ausencia de otras enfermedades o plagas |
| `POTATO_EARLY_BLIGHT` · tizón temprano de papa | `Potato___Early_blight` | `Potato leaf early blight` | `potato early blight` | Confirmar signos y equivalencia por fuente; revisar fotos dudosas |
| `POTATO_LATE_BLIGHT` · tizón tardío o rancha de papa | `Potato___Late_blight` | `Potato leaf late blight` | `potato late blight` | Confirmar denominación local «rancha», signos y exclusiones |
| `MAIZE_HEALTHY` · maíz sano | `Corn_(maize)___healthy` | Sin etiqueta localizada | Sin etiqueta localizada | Definir alcance de «sano» y cobertura de imágenes de campo |
| `MAIZE_COMMON_RUST` · roya común del maíz | `Corn_(maize)___Common_rust_` | `Corn rust leaf` **UNMAPPED** | `corn rust` **UNMAPPED** | Las etiquetas genéricas de roya se excluyen del mapeo automático; revisar enfermedad e imagen individual antes de cualquier decisión |
| `MAIZE_LEAF_BLIGHT` · **tizón foliar del norte** | `Corn_(maize)___Northern_Leaf_Blight` | `Corn leaf blight` **UNMAPPED** | `corn northern leaf blight` | La etiqueta genérica de PlantDoc se excluye del mapeo automático; las etiquetas «northern» siguen provisionales hasta revisión externa |
| `MAIZE_GRAY_LEAF_SPOT` · mancha gris foliar del maíz | `Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot` | `Corn Gray leaf spot` | `corn gray leaf spot` | Confirmar correspondencia taxonómica y calidad de cada etiqueta |

`UNMAPPED` también señala las tres etiquetas genéricas presentes pero excluidas del mapeo automático; cuando la etiqueta no se localizó, tampoco demuestra ausencia universal de la clase. Las demás cadenas presentes permanecen `PROVISIONAL`. No se admitirá una foto por similitud de nombre: el revisor debe confirmar cultivo, condición, definición y permiso del archivo, o excluirla/cuarentenarla. Los negativos y plagas no se convierten en una octava clase; `NO_CONCLUYENTE` es un estado.

## Registro de revisión especializada pendiente en G1

| Dato por clase y fuente | Estado actual | Evidencia requerida |
| --- | --- | --- |
| Definición diagnóstica y alcance de cada código | Pendiente | Definición revisada, versión y motivo de cambios |
| Equivalencia de cada etiqueta de origen | Pendiente | Decisión `APROBAR`, `EXCLUIR` o `REVISAR` y criterio aplicado |
| Revisión de fotos mal etiquetadas o ambiguas | Pendiente; no hay imágenes admitidas | Identificadores privados, decisión y responsable, sin publicar bytes |
| Acta de revisión | No existe | Nombre/rol del revisor, fecha, versión de taxonomía/mappings y decisión explícita |

La revisión de etiquetas no concede derechos de uso. [1.3 sigue abierta](../../openspec/changes/incremento-4-datos-y-modelo-validado/tasks.md) para G1; G0 de diseño ya está aprobado por el responsable.

La migración `diagnosis_0005` corrige solo el nombre de la semilla del catálogo si conserva el valor anterior. El código `MAIZE_LEAF_BLIGHT` y `model_supported=false` permanecen; una edición administrativa posterior se respeta. Esto alinea la denominación candidata en la API sin declarar una enfermedad validada.
