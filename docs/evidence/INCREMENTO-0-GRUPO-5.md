# Evidencia — Incremento 0, grupo 5

Fecha: 2026-09-29 (America/Lima). Cambio `incremento-0-base-integrada`, schema `spec-driven`. Alcance autorizado: 5.1–5.5, inventario inicial; grupos 6–7 no ejecutados. Repositorio sin commit; identidad del trabajo mediante [SHA-256](incremento-0-grupo-5-sha256.json). Python 3.12.3; validadores desde lock con hashes en entorno efímero. Las evidencias históricas de los grupos anteriores y auditoría del host se conservan.

## Resultado y trazabilidad

| Tarea / requisito | Comprobación realizada | Resultado / artefacto |
| --- | --- | --- |
| 5.1 / DATA-01 | Referencias primarias, autores, revisión, consulta, permisos y restricciones; rechazo de fuente elegible sin evidencia o revisión de admisión | Tres fuentes PENDING en [sources.v1.json](../../ml/manifests/sources.v1.json); pruebas de elegibilidad positivas/negativas |
| 5.2 / DATA-01 | Conteos remotos con fuente/método, diferencia null/cero, controles de metadatos no truncados; contexto, duplicados/exclusiones y ausencia externa | Siete filas por fuente; locales desconocidos, Ayacucho UNAVAILABLE; [metadatos de investigación](../../ml/manifests/research-evidence.v1.json) |
| 5.3 / DATA-02 | Siete códigos únicos y candidatos, cultivo coherente, no reciclaje de retirados ni NO_CONCLUYENTE; alineación con contratos HTTP/eventos | [Taxonomía](../../ml/manifests/taxonomy.v1.json) y [21 mapeos](../../ml/manifests/label-mappings.v1.json), equivalencias provisionales explícitas |
| 5.4 / DATA-01–02 | CSV con diez campos; siete clases/cuatro particiones sintéticas pasan; hash inválido, campos ausentes/adicionales, cultivo/clase incompatibles y fuente sin permiso fallan | [Esquema](../../ml/manifests/manifest-row.schema.json), [validador](../../scripts/validate_dataset.py), [pruebas](../../tests/dataset/test_inventory.py) |
| 5.5 / DATA-03 | Seis pares de particiones × hash/grupo = doce casos de fuga rechazados sin modificar filas; caso de grupo dentro de partición permitido | Pruebas pasan; [política de agrupamiento/cuarentena](../../ml/manifests/README.md#partición-cuarentena-y-privacidad), documentación ML/AI actualizada |

`bash scripts/check_dataset.sh`: **14 pruebas, todas correctas**, incluido CLI negativo con salida 1 y conservación del archivo. El comando global termina 0. El manifiesto real contiene cero filas, únicamente cabecera; esto no convierte conteos de imágenes desconocidos en cero ni acredita dataset entrenable. Los fixtures no se contabilizan como datos reales.

`openspec validate --all --strict --no-interactive`: salida 0. `openspec status --change incremento-0-base-integrada`: artefactos completos. `openspec instructions apply --change incremento-0-base-integrada --json`: **30/38 tareas completas, ocho pendientes**. No se confunde estado completo de planificación con cierre global del cambio.

Comandos exactos, versiones del runtime indicadas, salida y duración por comando: [registro de verificaciones](incremento-0-grupo-5-checks.txt). Reproducción local desde la raíz: `bash scripts/check_dataset.sh`; instalación aislada desde `contracts/tooling/requirements.lock`, seguida de validación offline. No exige Docker, GPU, pesos ni fotografías.

## Investigación y límites

Se consultaron exclusivamente metadatos y documentación de autores: GitHub, distribución PlantVillage enlazada por el autor y registros Zenodo. No se descargaron ZIP, imágenes ni pesos. Las revisiones Git y los árboles usados están en el registro de fuentes. Los conteos PlantVillage se obtuvieron por árboles de clase completos; respuestas recursivas truncadas se descartaron. PlantDoc usa archivos remotos por carpeta de train/test, sin afirmar que se haya conciliado el total del artículo con recortes ni eliminado duplicados.

Los permisos declarados de PlantSeg v5 y v7 difieren; la distinción se conserva y ninguna revisión queda admitida automáticamente. Licencias públicas no certifican derechos individuales de fotos de Internet. Las equivalencias agronómicas, en particular «tizón foliar», y la identidad de etiquetas entre código y archivo PlantSeg v7 necesitan revisión antes de curación.

El validador comprueba declaraciones y separación por hash/grupo; no calcula hashes de fotos, inspecciona píxeles, detecta todos los casi duplicados ni valida consentimientos. Revisión visual, grupos fiables, permisos aplicables, test sellado, entrenamiento y evaluación pertenecen al incremento 4. No hay métricas, umbrales ni cobertura soportada, ni se da por cumplido RF-08 u otro RF por estas pruebas sintéticas. No se incorporan imágenes de usuarios ni coordenadas.

No se inicia CI, sincronización/archivo OpenSpec, push o despliegue. Se detiene la ejecución al cerrar el grupo 5.
