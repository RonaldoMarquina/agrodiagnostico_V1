# G0/G1 v1.4.0 — materialización y sello EXTERNAL

Fecha: **2026-11-22** (America/Lima). Responsable: **PROJECT_OWNER**. Estado: **G0 aprobado y G1 cerrado; G2/G3 abiertos**. No se entrenó un modelo, no se calibró un umbral, no se abrió EXTERNAL para modelado y no existen métricas v1.4.0.

## Decisión y topología

El protocolo ejecutable [`protocol-g0.v1.4.0.json`](../../ml/evaluation/protocol-g0.v1.4.0.json), SHA-256 `e3dad24755550c574f33c5fa5b736eec639c9a36b054fcb3fee9e2c3e96550af`, fija:

- PlantVillage `color` revisión `9e97599868962bd0079b8db4b7f1efa9185fa1e7` únicamente para TRAIN/VAL.
- Sikkim v1, DOI `10.17632/4wz7zbk635.1`, únicamente para EXTERNAL sellado.
- El TEST y los resultados v1.3.2 quedan históricos e inmutables; no participan en selección v1.4.0.
- Solo tizón temprano y tardío son diagnósticos publicables. Papa sana y otro cultivo son objetivos de rechazo.

## PlantVillage TRAIN/VAL final

El manifiesto privado `.local/ml-v1.4.0/plantvillage-train-val.jsonl`, SHA-256 `b7bcdc87b1ae252c55370b1354c579c4b0fa80da962ce47b83c7a28ca66824e1`, deriva del G1 v1.3.1 sin alterar los bytes ni sus decisiones por archivo. Conserva fuente, licencia CC BY-SA 3.0, ruta original, SHA-256 y `leaf_id`; cada fila enlaza el comprobante copiado `plantvillage-rights.md`, SHA-256 `9fbe34695a3f05583f47345e5174383226ecee9e7af9e21d979307771b2362fb`. Se excluyeron todas las filas TEST y `OTHER_CROP` TRAIN; los 68 grupos TEST históricos quedan bloqueados. No hay `fallback_*`, SHA repetidos ni grupos que crucen TRAIN/VAL.

| Estrato | TRAIN fotos/grupos | VAL fotos/grupos | Uso v1.4.0 |
| --- | ---: | ---: | --- |
| `POTATO_EARLY_BLIGHT` | 541/136 | 165/42 | clase técnica y diagnóstico publicable |
| `POTATO_LATE_BLIGHT` | 499/129 | 153/39 | clase técnica y diagnóstico publicable |
| `POTATO_HEALTHY` | 80/20 | 28/7 | clase técnica de rechazo |
| `OTHER_CROP` | — | 150/38 | rechazo solo en VAL |

Totales utilizados por topología: **TRAIN 1.120 fotos/285 grupos** y **VAL 496 fotos/126 grupos**. Los grupos son `leaf_id`; no se cuentan vistas aumentadas como originales o grupos.

## Registro privado y derechos Sikkim

La fuente fijada es `Sikkim Solanaceae Leaf Image Dataset.zip`, 170.561.971 bytes, SHA-256 `5288c8f9d4628049ae1f827c961dc3df97167de294cec020cbce0bc19b2574dc`, archivo publicado UUID `23a902c9-9fea-4113-97db-8fee07632abd`. El depósito registra CC BY 4.0 y atribución a Kishor Chettri / Sikkim University.

El registro privado `.local/ml-v1.4.0/sikkim-external.jsonl`, SHA-256 `3c8d95e9e4d198dedf821133cb4d5f0c119a327b496396c25d4b71a493580992`, contiene **362 filas**, una por archivo: ruta, SHA-256, etiqueta fuente, estrato, dimensiones, decisión, motivo, autor, licencia, URL primaria, URL de licencia y referencia a `.local/ml-v1.4.0/source-proof.json`. Los archivos se decodificaron y reconciliaron contra `Annotations.xlsx` o su carpeta de fuente.

| Estrato EXTERNAL | Archivos únicos |
| --- | ---: |
| `POTATO_EARLY_BLIGHT` | 42 |
| `POTATO_LATE_BLIGHT` | 76 |
| `POTATO_HEALTHY` | 50 |
| `OTHER_CROP` | 194 |
| **Total** | **362** |

La identidad `sikkim-image:<sha256>` significa **archivo único**, no planta, hoja, sesión o parcela independiente. La etiqueta se describe como anotación de la fuente más control interno de decodificación/ambigüedad; no hubo nueva revisión agronómica independiente.

## Duplicados y limitación de correlación

Los 362 SHA son únicos y hay cero coincidencias exactas contra 6.059 imágenes PlantVillage locales. La revisión [`sikkim-v1-visual-decisions.json`](../../ml/manifests/sikkim-v1-visual-decisions.json), SHA-256 `c98ae03cbcb5ea09bbe8421ed66396ce5a8683466560e6d942395ac2ec1ba5df`, identifica las 20 alertas dHash cruzadas y las resuelve como archivos/escenas distintos.

El mismo método encontró 37 pares internos Sikkim; varios son visualmente relacionados o posiblemente derivados. Permanecen como archivos SHA distintos porque G0 define denominadores por archivo de la revisión fijada. Esto limita la independencia y debe figurar en cualquier reporte EXTERNAL; no se permite concluir rendimiento por planta.

## Sello y compuertas

El sello privado `.local/ml-v1.4.0/external-seal.json` tiene SHA-256 `ab0e7e7c8a28a70a5bce4fd6424912454e2a31b31f463406233d811ed3f9a69a`. Su copia sanitizada versionada es [`external-seal.v1.4.0.json`](../../ml/evaluation/external-seal.v1.4.0.json). Fija:

- 362 filas y conteos por estrato;
- SHA-256 de bytes del manifiesto `3c8d95e9e4d198dedf821133cb4d5f0c119a327b496396c25d4b71a493580992`;
- hash canónico de filas `1481922bfdded000c02243fbc8088ae5a38746523129aeefcff56cd117f4963f`;
- hash del protocolo aprobado;
- independencia solo por imagen única.

`agro_ml.v14_gates` rechaza procedencia incompleta, licencia/autor/URL/hash ausentes, Sikkim en TRAIN/VAL, grupos `fallback_*`, grupos TEST históricos, mezcla de hashes, cambio del manifiesto y todo acceso EXTERNAL para entrenamiento, VAL, calibración o selección. La única autorización de modelado posible será `FINAL_EXTERNAL_EVALUATION`, después de comprobar hashes de bundle, configuración, preprocesado, mapa, calibración y un umbral elegido en VAL.

Comando de materialización ejecutado, sin descargas implícitas:

```bash
python3 scripts/materialize_g0_v1_4.py \
  --sikkim-root '.local/sikkim-v1-audit/extracted/Sikkim Solanaceae Leaf Image Dataset' \
  --sikkim-zip .local/sikkim-v1-audit/sikkim-v1.zip \
  --plantvillage-package .local/pv-g1/g1-v1.3.1-admitted \
  --plantvillage-reference-images .local/pv-g1/batch-v1/images \
  --protocol ml/evaluation/protocol-g0.v1.4.0.json \
  --visual-decisions ml/manifests/sikkim-v1-visual-decisions.json \
  --output .local/ml-v1.4.0
```

Resultado: `G1_V1_4_0_CLOSED_EXTERNAL_SEALED_NOT_OPENED_FOR_MODELING`; reporte privado SHA-256 `88e14ef0d668bdea6deb291533d45797e9ce77592256d893e0673ce2bef1d101`. La compuerta conserva imágenes/manifiestos privados fuera de Git.

## Plan de entrenamiento, aún no ejecutado

[`potato-v14-balanced-cpu.plan.json`](../../ml/configs/potato-v14-balanced-cpu.plan.json) fija dos estrategias comparables en la misma VAL:

1. MobileNetV3-Small con inicialización aleatoria, pérdida ponderada y los 1.120 originales por época. Pesos `N/(K*n_clase)`: temprano `0,6900800986`, tardío `0,7481629927`, sana `4,6666666667`.
2. El mismo modelo y preprocesado con sampler consciente de `leaf_id`: clase uniforme, grupo uniforme y una imagen del grupo; 80 muestras por clase/época, 240 totales, semilla registrada.

Solo `POTATO_HEALTHY` en TRAIN puede recibir flip horizontal p=0,5, rotación ±15° y jitter conservador definido en la configuración. Cada vista conserva SHA original y `leaf_id`; VAL/EXTERNAL rechazan aumentos. Arquitectura, balance, calibración y umbral se eligen solo con VAL. **Este documento no registra ejecución ni rendimiento.**
