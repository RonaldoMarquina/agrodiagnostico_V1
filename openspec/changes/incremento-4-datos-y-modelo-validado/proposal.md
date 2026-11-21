# Proposal

## Why

El flujo asíncrono del incremento 3 está implementado, pero solo se ha probado con inferencia sintética. Para ofrecer apoyo diagnóstico real necesitamos datos autorizados, entrada de hoja de papa identificada, evaluación independiente y una política de publicación respaldada por evidencia.

## What Changes

- Definir y aprobar por el responsable del proyecto el protocolo G0 antes de entrenar con datos reales; documentar fuentes candidatas y política de admisión. La revisión de imágenes y etiquetas concretas corresponde a G1 y la medición a G2.
- Curar imágenes privadas, verificar bytes, duplicados y grupos relacionados, versionar particiones y sellar evaluación antes de experimentar.
- Implementar entrenamiento reproducible en CPU y comparar MobileNetV3 y ResNet18 para los dos tizones de papa previamente identificada, con rechazo técnico de entradas fuera de cobertura.
- Calibrar en validación, evaluar en test independiente y admitir únicamente clases que cumplan criterios preacordados. Ausencia de evidencia bloquea promoción y cierre, no se reemplaza con fixtures.
- Integrar un artefacto real verificado al worker conservando leases, heartbeat, idempotencia y outbox; mantener simulación exclusiva de pruebas.
- Gestionar políticas de publicación versionadas en Diagnosis, soporte efectivo del catálogo y trazabilidad del resultado; conservar recomendaciones revisadas e historia inmutable.
- Separar CI técnico sin dataset privado de aceptación experimental con modelo y datos reales. Registrar límites y aprobación humana verificable.

Decisión de alcance de G0 del responsable (2026-11-19, protocolo v1.2.0): la aprobación formal docente deja de ser condición del protocolo. El responsable aprueba los dos tizones candidatos del piloto, mínimos, presupuestos y umbrales de diseño, incluidos cobertura ≥ 0,70 y error selectivo ≤ 0,10. Esta decisión no admite imágenes ni acredita resultados agronómicos.

Fuera de alcance: interfaz final, notificaciones, despliegue público y observabilidad integral del incremento 5; Gemini, voz, PWA, detector de plagas y entrenamiento automático con fotos/feedback de usuarios.

## Capabilities

### New Capabilities

- `reproducible-model-training-and-evaluation`: protocolo experimental, selección, calibración, evaluación independiente y aprobación de artefactos.
- `validated-model-inference`: carga segura de artefactos reales, clasificación de dos tizones de papa y abstención e integración durable.
- `model-publication-policy`: activación auditada, decisión de Diagnosis, soporte por versión y trazabilidad de resultados.

### Modified Capabilities

- `dataset-inventory`: admisión real, curación de bytes, duplicados visuales y particiones selladas, preservando inventario histórico.
- `continuous-integration-foundation`: verificación técnica de ML y aceptación real separada para cerrar el incremento.

## Impact

Afecta `ml/`, validadores y pruebas de dataset, `services/ai_inference/`, `services/diagnosis/`, contratos, Compose y CI. Se agregarán dependencias ML bloqueadas y migraciones propias de Diagnosis para políticas y trazabilidad. Los eventos existentes se conservan si mantienen su semántica; contratos de artefacto/política y evolución compatible del detalle se fijarán antes de consumidores. Se requiere ADR de integración y publicación, documentación operativa y evidencia reproducible. No se descarga, entrena ni implementa durante esta propuesta.
