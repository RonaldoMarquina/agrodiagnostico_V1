# Proposal

## Why

El flujo asíncrono del incremento 3 está implementado, pero solo se ha probado con inferencia sintética. Para ofrecer apoyo diagnóstico real necesitamos datos autorizados, cultivo automático, evaluación independiente y una política de publicación respaldada por evidencia.

## What Changes

- Incluir selección y aprobación de fuentes, etiquetas y criterios con el docente como primeras tareas, según decisión del usuario. No hay dataset admitido ni métricas aprobadas actualmente.
- Curar imágenes privadas, verificar bytes, duplicados y grupos relacionados, versionar particiones y sellar evaluación antes de experimentar.
- Implementar entrenamiento reproducible en CPU, comparar una línea base y una alternativa, identificar cultivo sin entrada manual y evaluar abstención ante imágenes fuera de cobertura.
- Calibrar en validación, evaluar en test independiente y admitir únicamente clases que cumplan criterios preacordados. Ausencia de evidencia bloquea promoción y cierre, no se reemplaza con fixtures.
- Integrar un artefacto real verificado al worker conservando leases, heartbeat, idempotencia y outbox; mantener simulación exclusiva de pruebas.
- Gestionar políticas de publicación versionadas en Diagnosis, soporte efectivo del catálogo y trazabilidad del resultado; conservar recomendaciones revisadas e historia inmutable.
- Separar CI técnico sin dataset privado de aceptación experimental con modelo y datos reales. Registrar límites y aprobación humana verificable.

Fuera de alcance: interfaz final, notificaciones, despliegue público y observabilidad integral del incremento 5; Gemini, voz, PWA, detector de plagas y entrenamiento automático con fotos/feedback de usuarios.

## Capabilities

### New Capabilities

- `reproducible-model-training-and-evaluation`: protocolo experimental, selección, calibración, evaluación independiente y aprobación de artefactos.
- `validated-model-inference`: carga segura de artefactos reales, cultivo automático, abstención e integración durable.
- `model-publication-policy`: activación auditada, decisión de Diagnosis, soporte por versión y trazabilidad de resultados.

### Modified Capabilities

- `dataset-inventory`: admisión real, curación de bytes, duplicados visuales y particiones selladas, preservando inventario histórico.
- `continuous-integration-foundation`: verificación técnica de ML y aceptación real separada para cerrar el incremento.

## Impact

Afecta `ml/`, validadores y pruebas de dataset, `services/ai_inference/`, `services/diagnosis/`, contratos, Compose y CI. Se agregarán dependencias ML bloqueadas y migraciones propias de Diagnosis para políticas y trazabilidad. Los eventos existentes se conservan si mantienen su semántica; contratos de artefacto/política y evolución compatible del detalle se fijarán antes de consumidores. Se requiere ADR de integración y publicación, documentación operativa y evidencia reproducible. No se descarga, entrena ni implementa durante esta propuesta.
