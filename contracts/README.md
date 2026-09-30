# Contratos iniciales V1

Paquete del grupo 2, Incremento 0. Desde grupo4, ocho operaciones de salud están **implemented** y las diecinueve de negocio siguen **contract-only**. Los JSON OpenAPI 3.1.1 son la fuente de interfaz y los eventos usan JSON Schema 2020-12. No se sincronizan aún a specs vigentes ni se archiva el cambio.

## Verificación reproducible

Desde la raíz, con Python 3.12 y acceso al índice de paquetes (o caché local):

```bash
bash scripts/check_contracts.sh
```

El comando crea un venv efímero, instala exclusivamente el lock con hashes, valida documentos/referencias/ejemplos y ejecuta unittest. Al terminar elimina su propio venv, incluso ante fallo. No instala paquetes globales, levanta servicios ni necesita credenciales, fotos, modelos o GPU. La instalación puede usar red; la resolución de contratos es exclusivamente local. Los fixtures sintéticos de imagen representan la forma del campo, no prueban decodificación ni límites de bytes/píxeles.

Para desarrollo reiterado se puede crear `contracts/tooling/.venv`, instalar `python -m pip install --require-hashes -r contracts/tooling/requirements.lock` desde ese entorno y ejecutar su Python sobre `scripts/validate_contracts.py` y `-m unittest discover -s tests/contracts -p 'test_*.py' -v`. No usar el Python global para instalar.

Lock generado con Python 3.12, pip-tools 7.5.2; entrada en [requirements.in](tooling/requirements.in), cierre transitivo y hashes en [requirements.lock](tooling/requirements.lock). Regenerar solo ante actualización deliberada, con pip-tools en venv aislado y `pip-compile --generate-hashes --strip-extras --output-file contracts/tooling/requirements.lock contracts/tooling/requirements.in`; revisar diff y repetir aceptación. La reproducción normal no resuelve versiones nuevas.

## Archivos e interpretación

- [Identity](openapi/identity.openapi.json), [Diagnosis](openapi/diagnosis.openapi.json), [AI Inference](openapi/ai_inference.openapi.json) y [Notification](openapi/notification.openapi.json): rutas, seguridad, errores, ejemplos y extensiones de aceptación.
- [Componentes](schemas/common.schema.json): UUID, UTC, errores y payloads comunes.
- [Inventario](operations.json) y [matriz de seguridad](security-matrix.json): se comprueban contra OpenAPI.
- [Escenarios HTTP](http-scenarios.json): precondición y respuesta esperada; `runtime_verified: false` evita confundirlos con handlers probados.
- [Obligaciones pendientes](deferred-operations.json): contratos futuros, responsables y rutas conceptuales antes de consumidores; no son endpoints publicados.
- [Entrega de eventos](events/README.md) y [routing](events/routing.json): obligaciones futuras e incremento responsable.

El OpenAPI generado por las APIs se compara solamente con las rutas de salud durante la aceptación integrada. Cada operación tiene `x-status`, `x-owner`, `x-increment`. `x-upload-policy` y `x-idempotency` fijan límites y semántica que JSON Schema no puede imponer sobre bytes reales o sobre el historial de solicitudes. No se genera un servidor ficticio para hacer pasar estas pruebas. El validador exige inventario completo, ejemplos por respuesta con cuerpo, seguridad explícita, IDs únicos y referencias resolubles dentro de `contracts/`; rechaza referencias externas y esquemas recursivos no soportados por esta herramienta.

## Compatibilidad

Las formas v1 son cerradas (`additionalProperties: false`). Añadir campos también puede romper consumidores: exige revisar/versionar, no asumir compatibilidad aditiva. La versión de API/evento no es la versión del modelo. Las siete clases son candidatas, sin métricas ni tratamientos. Cambiar semántica requiere OpenSpec y ADR si afecta estado, propiedad o arquitectura.

Referencias técnicas consultadas: [OpenAPI 3.1.1](https://spec.openapis.org/oas/v3.1.1.html), [validación jsonschema](https://python-jsonschema.readthedocs.io/en/stable/validate/) y [openapi-spec-validator](https://openapi-spec-validator.readthedocs.io/en/latest/). Los formatos se comprueban explícitamente con `FormatChecker`, además de exigir sufijo UTC `Z`.
