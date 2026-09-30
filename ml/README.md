# Datos y modelos — AgroDiagnóstico V1

El grupo 5 del Incremento 0 entrega el [inventario inicial](manifests/README.md): tres fuentes investigadas, siete clases candidatas y veintiún mapeos explícitos. Las fuentes siguen pendientes de admisión, los conteos locales no están medidos y Ayacucho externo no está disponible. No se descargaron imágenes ni se entrenó un modelo.

Verificación desde la raíz:

```bash
bash scripts/check_dataset.sh
```

El comando valida fuentes, taxonomía, manifiesto inicial y pruebas sintéticas; rechaza campos inválidos, fuentes sin permiso demostrado y hashes/grupos compartidos entre particiones. Los fixtures están separados en `tests/dataset/fixtures/`, no son fotografías disponibles. Los detalles del CSV, cuarentena, agrupamiento y límites se documentan en [manifiestos](manifests/README.md).

Curación real, comprobación de bytes, revisión visual de casi duplicados, permisos por imagen, particiones definitivas, test sellado, entrenamiento y evaluación pertenecen al incremento 4. NO_CONCLUYENTE es estado de abstención, no clase; no hay métricas, cobertura soportada ni umbrales medidos. Los códigos de clases son estables y no reciclables.

No incorporar automáticamente imágenes ni feedback de usuarios al entrenamiento. Mantener imágenes privadas y ubicación precisa fuera de Git; el validador no acredita consentimiento. CPU es la base de reproducibilidad futura; GPU requiere validación. Plagas/Gemini/voz/PWA no forman parte del núcleo obligatorio.

Referencias: [estrategia IA](../docs/AI_MODEL.md), [fuente reconciliada](../docs/reference/RECONCILIACION-V1.md), [tareas](../openspec/changes/archive/2026-09-30-incremento-0-base-integrada/tasks.md) y [evidencia del inventario](../docs/evidence/INCREMENTO-0-GRUPO-5.md).
