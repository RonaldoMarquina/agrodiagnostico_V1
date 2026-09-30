# Proposal — Incremento 0: base integrada

## Why

La estructura y la auditoría del equipo ya existen, pero todavía no hay un entorno de aplicación ejecutable ni contratos verificables. El Incremento 0 debe convertir esa base en una integración local reproducible que permita desarrollar los incrementos siguientes sin confundir preparación del host con funcionalidad del producto.

## What Changes

- Integrar Compose con PostgreSQL, RabbitMQ, Redis, objetos S3 privados, Nginx, frontend mínimo y cuatro servicios con salud técnica; ejecución CPU sin modelo ni worker de negocio.
- Fijar contratos iniciales HTTP y los tres eventos v1, con ejemplos positivos/negativos y distinción explícita entre contrato previsto y endpoint implementado.
- Introducir Alembic y una revisión base ejecutable por servicio, con aislamiento de bases y credenciales; tablas de negocio en incrementos posteriores.
- Añadir CI de aplicación reproducible para contratos, pruebas técnicas, migraciones, builds y smoke integrado, conservando el workflow de preparación de Copilot.
- Crear inventario versionado de fuentes y etiquetas candidatas del dataset, con permisos, cantidades observadas o desconocidas, restricciones y validaciones; sin descargar ni entrenar automáticamente.
- Conservar estructura, auditoría y evidencias existentes. Documentar decisiones, comandos comprobados y evidencia nueva durante la implementación.

## Capabilities

### New Capabilities

- `integrated-development-environment`: arranque local, salud, aislamiento, configuración y persistencia.
- `initial-interface-contracts`: contratos HTTP/eventos versionados y comprobables antes de integrar consumidores.
- `service-migration-baselines`: revisiones Alembic independientes y privilegios verificables por servicio.
- `continuous-integration-foundation`: controles reproducibles y evidencia de fallos sin servicios externos de producción.
- `dataset-inventory`: procedencia y elegibilidad de datos sin atribuir cobertura validada.

### Modified Capabilities

Ninguna: `openspec/specs/` solo contiene `.gitkeep` y no había cambios activos al iniciar esta propuesta.

## Impact

La implementación futura afectará los archivos existentes en `frontend/`, `services/`, `infra/`, `contracts/`, `ml/`, `.github/workflows/`, `tests/`, configuración raíz y documentación. La propuesta inicial fue solo de planificación. Después se completaron el grupo 1 documental (reconciliación y ADR), el grupo 2 (contratos y validadores), el grupo 3 (persistencia aislada y migraciones base), el grupo 4 (entorno técnico integrado), el grupo 5 (inventario inicial de datos) y el grupo 6 (CI reproducida localmente); la aceptación local del grupo 7 está verificada y 7.3 sigue pendiente: Application CI falló en la ejecución 36743640034. Hay ocho operaciones de salud implementadas, diecinueve de negocio contract-only y esquemas de eventos comprobables. No hay despliegue público ni negocio implementado.

Se mantiene un solo cambio con cinco capacidades y entregas internas pequeñas: contratos → persistencia/entorno → CI; inventario independiente. Comparten una única aceptación técnica, por lo que no se requiere dividirlos en cambios separados. Cualquier ampliación hacia funciones de usuario se propondrá aparte.

## Non-goals

Registro/login funcional, carga de fotos, transiciones de diagnóstico, publicadores/consumidores outbox, worker provisional, catálogo clínico, correo, entrenamiento, GPU, observabilidad completa y despliegue público quedan para sus incrementos. Dominio, Cloudflare, TLS y CDN siguen siendo obligatorios para V1 pública, pero no se declaran cumplidos por Compose local.

## Fuente reconciliada

Se revisaron los documentos del proyecto y la fuente completa entregada por el responsable: `docs/reference/Definicion_Base_AgroDiagnostico_V1_Limpia.docx` (definición base, revisión DOCX 3). La extracción íntegra, las nueve tablas, las discrepancias resueltas y la trazabilidad RF-01…RF-28 constan en `docs/reference/RECONCILIACION-V1.md`. No se atribuye existencia a una segunda especificación ni se declara ningún RF implementado. El grupo 1 formaliza decisiones y el grupo 2 aporta los contratos validados. Su cumplimiento funcional sigue pendiente de los incrementos responsables.
