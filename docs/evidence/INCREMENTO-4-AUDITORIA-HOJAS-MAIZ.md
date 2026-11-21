> Nota posterior: G0 v1.2.0 fue aprobado como piloto de los dos tizones de papa. Los números de esta auditoría describen el diseño histórico v1.1.0.

# Auditoría de hojas y etiquetas de PlantVillage color

19 de noviembre de 2026 · G0 vigente v1.1.0 · G1 abierto.

## Por qué falta el grupo en las cuatro clases de maíz

Se contrastaron las 4.802 rutas positivas de la lista TRAIN del editor con el inventario preparado, el mapa y el método original `_generate_examples` de la revisión `9e97599868962bd0079b8db4b7f1efa9185fa1e7`. Se ejecutó únicamente ese método para obtener sus metadatos. La comprobación local fija los SHA-256 de los cuatro insumos. Se reproduce desde la raíz con `python3 scripts/audit_plantvillage_leaf_ids.py .local/pv-g1`. [Cargador de la revisión](https://huggingface.co/datasets/mohanty/PlantVillage/blob/9e97599868962bd0079b8db4b7f1efa9185fa1e7/plant_village.py) · [Auditoría ejecutable](../../scripts/audit_plantvillage_leaf_ids.py).

El cargador toma la carpeta como etiqueta. Para la clave de hoja elimina `_final_masked`, conserva el sufijo posterior a `___`, corta desde `copy`, quita extensión y espacios y busca en minúsculas. Si encuentra una sola sugerencia la acepta. Si hay varias, toma la primera que contenga la clase. Una clave ausente o varias sugerencias sin clase compatible producen `fallback_` seguido del identificador derivado del nombre. El importador local exige una única sugerencia distinta con clase exacta e identificador numérico. **En maíz el fallo ocurre antes de aplicar ese filtro**. Ninguna de las 3.058 claves consultadas figura en el mapa y entre sus 40.328 claves no hay sugerencias con prefijo de las cuatro clases de maíz. La revisión permite localizar la omisión, pero no documenta por qué el editor dejó fuera esos identificadores.

| Clase de maíz | Fotos | Claves presentes | Salidas fallback | Cadenas fallback distintas | Hojas verificables |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sano | 912 | 0 | 912 | 535 | 0 |
| Roya común | 975 | 0 | 975 | 975 | 0 |
| Tizón foliar del norte | 765 | 0 | 765 | 691 | 0 |
| Mancha gris foliar | 406 | 0 | 406 | 360 | 0 |

Por ejemplo, en mancha gris tres rutas con UUID distintos terminan en `RS_GLSp 4663.JPG`, `RS_GLSp 4663 copy.jpg` y `RS_GLSp 4663 copy 2.jpg`. Las tres producen `fallback_RS_GLSp 4663`. En roya, `RS_Rust 1818.JPG` produce `fallback_RS_Rust 1818`. Una cadena repetida advierte de una posible relación. Una cadena única tampoco certifica que se fotografió una hoja distinta. Todas las filas de maíz tienen grupo y partición vacíos.

Como control, las 120 rutas de papa sana recuperan 30 hojas del mapa. Las 836 de tizón temprano recuperan 209 y las 788 de tizón tardío, 197, antes de exclusiones. En las 1.744 coincide exactamente el identificador publicado con el registrado localmente.

## Revisión de los cuatro casos pendientes

Codex cotejó la etiqueta exacta de carpeta y verificó el SHA-256 antes de inspeccionar cada original. Las dos fotos de maíz están en cuarentena y las dos de papa en TRAIN candidato. Los prefijos identifican los hashes completos del registro privado. La inspección previa cubrió 40 miniaturas. Esta segunda lectura se limitó a los cuatro originales señalados. No participó un especialista agronómico.

| Archivo original y prefijo SHA-256 | Etiqueta del editor | Observación a resolución original y decisión |
| --- | --- | --- |
| RS_Rust 1818.JPG · `0014e6d6c1ea` | Common_rust_ | Se distinguen numerosos puntos pardos pequeños dispersos. La miniatura ocultaba parte del detalle. Pendiente confirmar la enfermedad y resolver el grupo. |
| RS_Rust 1998.JPG · `012bf2c749bc` | Common_rust_ | Hay pocas marcas claras y pardas junto a una nervadura prominente. Pendiente confirmar la enfermedad y resolver el grupo. |
| RS_LB 3969.JPG · `00a66ec071c8` | Late_blight | Se observan zonas oscuras en el extremo superior y el borde inferior. Hoja publicada 115.0 de esta clase. Etiología pendiente. |
| RS_LB 4575.JPG · `01dd20dcb5ca` | Late_blight | El limbo está plegado, con áreas pardas centrales y sombra en el margen. Hoja publicada 173.0 de esta clase. Etiología pendiente. |

Los signos visibles justifican conservar las observaciones y la etiqueta de origen como provisional. Los cuatro casos continúan pendientes de dictamen. Un nombre de archivo, una etiqueta genérica de roya/tizón o el aspecto de una mancha no bastan para aprobar la equivalencia agronómica. [Equivalencias y revisiones pendientes](INCREMENTO-4-REVISION-TAXONOMIA-Y-MAPPINGS.md).

## Dos decisiones posibles antes del entrenamiento

**A. Mantener G0 v1.1.0 y las siete clases.** Incorporar una colección documentada, por ejemplo una campaña con productores o una estación agraria que consienta el uso previsto, registre identificadores en la captura y aporte etiquetas revisadas por un especialista. Es una vía propuesta. Aún falta obtener esa colección. Aceptar cada lote con revisión, ruta, SHA-256, licencia o permiso aplicable y agrupación global de vistas de cada hoja/planta/sesión. Detectar y retirar las copias entre fuentes antes de asignar nuevas filas. Conservar los grupos ya reservados. Estos son los déficits **mínimos** si las filas de papa sana actuales superan revisión, antes de nuevos descartes.

| Aporte necesario, fotos/grupos distintos | TRAIN | VAL | TEST reservado | Total |
| --- | ---: | ---: | ---: | ---: |
| Cada una de las cuatro clases de maíz | 150/50 | 40/20 | 30/15 | 220/85 |
| Papa sana adicional | 70/30 | 16/14 | 14/11 | 100/55 |

El piso conjunto adicional es de **980 fotos y 395 grupos sumando las cinco clases**. Conviene comprobar que la nueva fuente esté representada en condiciones comparables entre clases para que el fondo o el origen no predigan el cultivo. EXTERNAL de Ayacucho requiere su propio permiso y separación si llega a estar disponible. Alcanzar estos mínimos habilita la preparación experimental una vez resuelta la revisión. Los resultados del modelo corresponden a G2.

**B. Proponer G0 v1.2.0 como piloto de alcance reducido.** Antes de entrenar o acceder a TEST, el responsable podría aprobar por escrito un piloto de diferenciación de tizón temprano frente a tardío en muestras de papa previamente identificadas y derivadas para esa comparación. Mantener para ambas clases los mínimos de fotos/grupos, el rechazo, los límites CPU y los umbrales de calidad. Fijar en esa nueva versión que F1 macro y cobertura se calcularían sobre las dos clases del piloto y que el cierre se limitaría a ese piloto. Definir y revisar ejemplos fuera de alcance, incluidos papa sana, maíz y cuadros ambiguos, y comprobar su rechazo. La separación por hoja seguiría siendo obligatoria. Los dos tizones superan hoy los mínimos de cantidad en las particiones candidatas. Falta verificar etiquetas y negativos antes de cualquier experimento.

Esta alternativa pierde el diagnóstico de maíz, la declaración de papa sana y la validación de cultivo automático para dos cultivos. Tampoco acredita el requisito vigente de al menos una enfermedad aprobada por cultivo ni resultados comparables con el F1 de siete clases. Se documentaría en protocolo, ADR y OpenSpec como decisión prospectiva del responsable, con fecha, justificación y denominadores. **B es propuesta. La única versión aprobada sigue siendo v1.1.0.** [Criterios vigentes](../../ml/evaluation/protocol-g0.v1.json).

G1 y las tareas 1.3, 3.3, 3.5 y 3.6 permanecen abiertas. La tarea documental 1.2 sigue cerrada. Esta auditoría usó metadatos y cuatro originales de TRAIN o cuarentena. No hubo entrenamiento ni acceso a imágenes TEST.

La [evaluación posterior de cuatro fuentes originales](INCREMENTO-4-FUENTES-PARA-COMPLETAR-G1.md) cuantifica los aportes posibles para maíz y papa sana y documenta qué registros de captura faltan.
