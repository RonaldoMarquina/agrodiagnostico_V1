# Incremento 0 — grupo 2: contratos y pruebas

Cierre: 2026-09-29, America/Lima. Cambio `incremento-0-base-integrada`, tareas 2.1–2.8. Trabajo sin commit; hashes de artefactos en [manifiesto](incremento-0-grupo-2-sha256.json). Se conserva la evidencia histórica del host y del grupo 1.

## Resultado y reproducción

Ejecutar `bash scripts/check_contracts.sh` desde la raíz con Python 3.12. El comando crea y elimina su propio venv, instala dependencias transitivas bloqueadas con hashes y valida sin servicios ni credenciales. La instalación requiere índice de paquetes o caché; la resolución de referencias es local. [Salida, códigos y duración](incremento-0-grupo-2-checks.txt).

Paquete: cuatro OpenAPI 3.1.1, 27 operaciones contract-only, cinco archivos de esquemas (componentes, envelope y tres eventos), 330 ejemplos incluidos y 360 casos sintéticos positivos/negativos. Once pruebas unittest comprueban el paquete y las matrices. Ningún endpoint, incluida salud, se declara implementado.

## Matriz de aceptación

| Tarea / requisito | Comprobación | Artefacto |
| --- | --- | --- |
| 2.1 / CTR-01, CI-01 parcial | Instalación aislada con lock y hashes; fixture roto y referencia rota en copia de OpenAPI producen rechazo/salida1 | requirements.lock; check_contracts.sh; test_broken_reference_fixture_rejected y test_cli_fails_for_broken_reference_in_actual_operation |
| 2.2 / CTR-01 | Referencias resueltas, UUID/UTC, errores; live200 y ready200/503 de cuatro servicios, ejemplos correctos/incorrectos | common.schema.json; test_health_status_per_service; test_positive_and_negative_fixtures |
| 2.3 / CTR-01–02 | Registro/login/refresh/logout/perfil/recuperación; cookies, Origin y CSRF declarados; payloads y negativos; operaciones futuras conservadas | identity.openapi.json; security-matrix.json; deferred-operations.json |
| 2.4 / CTR-01–02 | Multipart sin cultivo,202/4xx, detalle por estado, cancelación y DELETE; ejemplos de mismo/diferente contenido, propietario y frontera de vencimiento | diagnosis.openapi.json; http-scenarios.json; test_upload_contract_and_idempotency_examples |
| 2.5 / CTR-01–02 | Claim/renew/imagen interna/propia; identidad separada de lease; ejemplos vigentes/obsoletos y errores, sin redirección pública | diagnosis.openapi.json; test_security_matrix; http-scenarios.json |
| 2.6 / CTR-01–02 | Preferencias/avisos, paginación y negativos; igualdad del índice con las 27 operaciones, obligaciones futuras con dueño/incremento | notification.openapi.json; operations.json; deferred-operations.json |
| 2.7 / CTR-03 | Tres eventos y variantes, campos requeridos, versiones, secretos/binarios, coherencia clase/cultivo y rechazo de CANCELADO | events/*.schema.json; fixtures/schema-cases.json |
| 2.8 / CTR-04 | Matriz de routing/emisor/consumidor, commit/outbox/inbox/ACK/confirms y casos futuros | events/README.md; routing.json; test_event_routing_and_future_guarantees |

## Límites explícitos

Son comprobaciones de contrato, no pruebas de autorización, idempotencia, atomicidad, entrega RabbitMQ, decodificación de fotografías o inferencia en ejecución. Fixtures de archivos y modelos son sintéticos. Los casos HTTP declaran runtime_verified=false; escenarios de entrega pending-runtime. No se ejecutan RF ni se miden métricas ML/productivas.

Persisten obligaciones antes de consumidores: cambio/confirmación de contraseña y administración Identity en incremento1; feedback/catálogo/administración Diagnosis en2; entrega/concurrencia en3; modelo validado en4; lectura de avisos, consumidor Notification/correo y supervisión en5. HEIC/HEIF permanece pendiente de conversor y E2E, sin eliminarlo de V1.

Grupos 3–7 del Incremento0 pendientes. Compose y servicios continúan como scaffold; CI remota no ejecutada. No se hace push, despliegue, sincronización ni archivo OpenSpec. Los documentos históricos de inspección inicial describen su fecha, no el nuevo paquete de contratos.
