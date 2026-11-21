# Orientación revisada del catálogo — piloto de papa

Fecha: 2026-11-20. Versión de contenido: `1.0.0`. Alcance: `POTATO_EARLY_BLIGHT` y `POTATO_LATE_BLIGHT` del protocolo G0 v1.2.0. Archivo exacto: [`pilot-potato-guidance.v1.json`](../catalog/pilot-potato-guidance.v1.json), SHA-256 `dd614a5116515d6a8cd04ae5d4902234d7a15e8b729ca46003b8c33dc6295bc0`.

El responsable del proyecto aprobó el 2026-11-20 los puntos obligatorios y las exclusiones del texto mediante su instrucción de cierre de 7.5. La redacción fue cotejada con las fuentes publicadas por Codex. Se registra como **revisión de orientación general por el responsable**, sin atribuir una evaluación agronómica independiente ni certificación de un especialista. Referencia `PROJECT-OWNER-CATALOG-GUIDANCE-2026-11-20-V1`.

Fuentes consultadas:

- [SENASA, Guía para la implementación de buenas prácticas agrícolas para el cultivo de papa](https://www.senasa.gob.pe/senasa/descargasarchivos/2020/07/Guia-BPA-PAPA.pdf): rotación y malezas (p. 8); enfermedades, semilla y herramientas (p. 11); residuos y riego (p. 12). Reconoce rancha/tizón tardío y alternaria/tizón temprano.
- [CIP, Manejo integrado del tizón tardío, hoja divulgativa 2](https://cipotato.org/wp-content/uploads/2014/09/003858.pdf): combina medidas, selección de variedades, semilla sana, saneamiento, riego y consulta especializada antes de productos.

La orientación publicada describe una **señal visual que requiere confirmación en campo**, inspección de plantas cercanas, registro de síntomas y prácticas preventivas generales. Para tizón tardío añade manejo integrado, variedades adecuadas y consulta técnica temprana. Deriva a SENASA o un profesional agrícola antes de aplicar productos. No contiene marcas, dosis, frecuencias ni instrucciones de aplicación de fungicidas.

La publicación se hace solo mediante `POST /api/v1/admin/recommendations` con credencial de administrador, que asigna versión y auditoría. [`publish_pilot_guidance.py`](../../scripts/publish_pilot_guidance.py) valida el paquete y usa `dry-run` por defecto; acepta `--apply` únicamente contra proxy local en loopback. No modifica semillas ni asigna `model_supported`: ese campo depende de la política. Los resultados de importación y aceptación aislada se registran en el expediente G3.
