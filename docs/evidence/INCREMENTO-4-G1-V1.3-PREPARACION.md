# G1 v1.3.0 — preparación de admisión, sin imágenes admitidas

Fecha: 2026-11-20 (America/Lima). [G0 v1.3.0 aprobado](INCREMENTO-4-G0-V1.3-APROBACION.md). **G1 abierto:** este expediente prepara el ingreso y particionado, pero no contiene fotos, manifiestos admitidos, particiones selladas ni evaluación. No se ha entrenado ni abierto TEST v1.3.0.

## Fuentes de auditoría y exclusión obligatoria

- Distribución PlantVillage `color`, revisión `9e97599868962bd0079b8db4b7f1efa9185fa1e7`. Inventario privado `.local/pv-g1/batch-v1/positives.csv`, SHA-256 `4109b54502970432ba75356e60a45b999039c392556fa1c469ba2502b6c60b4c`. La licencia de la distribución y su atribución están en el [expediente de fuentes](INCREMENTO-4-EXPEDIENTE-FUENTES.md); cada archivo seleccionado requiere vinculación de ruta y SHA-256 con esa revisión, derechos aplicables y revisión de etiqueta/calidad.
- Informe privado G3 `.local/ml-pilot-v1.2/g3-local-df6aef7a4d22/summary.json`, SHA-256 `47d28ab4582bd5f4f6045464b6f06ceaa2fa42eb398a19f88b38e560e5c9d8a0`. Sus cuatro SHA-256 de papa sana corresponden a tres `leaf_id` de VAL histórica; esos grupos contienen 12 fotos en el inventario. [Lista reproducible de exclusión](../../ml/manifests/g1-v1.3-exposure-blocklist.json), SHA-256 `b6152881118f1502fea00fa37e5365449e8c9d34401e7989f09c8b319248ca31`.
- **Regla de G1:** rechazar de TRAIN, VAL, TEST y EXTERNAL las 12 fotos de esos tres grupos, incluidas las cuatro usadas como controles G3. Comparar además SHA-256 y similitud visual con el TEST v1.2.0 ya abierto; ningún archivo o grupo de ese TEST puede integrar el nuevo TEST. La exclusión es preventiva y no convierte otras fotos en admitidas.

## Inventario y déficit mínimo después de la exclusión

`fotos/grupos` de papa sana son candidaturas del inventario, no G1. El TEST de tizones y tomate v1.2.0 ya fue evaluado y cuenta **0/0** para el TEST independiente nuevo.

| Estrato y partición | Candidatas utilizables si pasan G1 | Mínimo G0 | Faltante mínimo |
| --- | ---: | ---: | ---: |
| Papa sana TRAIN | 80/20 | 150/50 | **70/30** |
| Papa sana VAL, sin tres grupos G3 | 12/3 | 40/20 | **28/17** |
| Papa sana TEST nuevo, inventario nunca evaluado en G2 v1.2.0 | 16/4 | 30/15 | **14/11** |
| Tizón temprano TEST nuevo | 0/0 | 30/15 | **30/15** |
| Tizón tardío TEST nuevo | 0/0 | 30/15 | **30/15** |
| Otro cultivo TEST nuevo | 0/0 | 30/15 | **30/15** |
| **Total mínimo operativo** | | | **202 fotos/103 grupos** |

La cifra anterior **190/100** era condicional a incluir los grupos G3 expuestos en TRAIN; permanece documentada como cálculo histórico, **no como lote admisible** bajo esta decisión. Si las 16/4 candidatas sanas para TEST fallan la revisión, el faltante sube como mínimo a **218/107**. Más exclusiones o grupos relacionados elevan esas cifras.

## Secuencia de admisión y sello

1. Inventariar fuentes originales y nuevas fotos de ambos tizones, papa sana y otros cultivos. Registrar versión, URL, atribución, uso permitido, ruta, SHA-256 y condición de modelos entrenados por lote; no presumir permiso por ser público. Mantener fotos fuera de Git.
2. Revisar por archivo etiqueta original y calidad/ambigüedad. Distinguir **proveniencia experta de PlantVillage + control interno de calidad** de una nueva revisión agronómica independiente, que no consta. Excluir etiquetas dudosas, corrupción, duplicados y permisos no verificables; registrar decisión por SHA-256.
3. Aplicar la lista de exclusión G3 **antes** de contar candidatos. Verificar `leaf_id` publicado y excluir `fallback_*`. Comparar grupos, hashes y pares visuales con TRAIN/VAL/TEST v1.2.0 y entre las cuatro particiones nuevas. Un mismo grupo nunca cruza TRAIN, VAL, TEST o EXTERNAL.
4. Revalidar TRAIN/VAL históricos que se reutilicen; construir manifiestos positivos y negativos separados por estrato. Comprobar todos los mínimos G0 por fotos y grupos **después** de exclusiones. Usar los validadores existentes y extenderlos para el estrato sano antes de aceptar filas nuevas; sus pruebas deben rechazar fuente pendiente, etiqueta no revisada, archivo sin permiso, grupo expuesto y fuga entre particiones.
5. Sellar un **TEST nuevo** para los cuatro estratos y registrar hashes/manifiestos privados. Conservarlo inaccesible para selección de arquitectura, calibración o umbral. Abrirlo una sola vez, después de congelar un bundle v1.3.0 en VAL. Si falta un estrato o un sello, G1 continúa abierto y no se entrena para G2.

La [tarea 2.1–2.4](../../openspec/changes/incremento-4-v1-3-rechazo-papa-sana/tasks.md) sigue abierta. Este expediente solo fija la preparación y la lista de exclusión; no declara derechos por foto, etiquetas verificadas, nuevos datos ni G1 cerrado.
