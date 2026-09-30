# Design — Incremento 0

## Context

Motivación y alcance: [proposal.md](proposal.md). Inspección del 2026-09-28:

| Área | Evidencia observada | Consecuencia |
| --- | --- | --- |
| Git | Archivos del proyecto sin seguimiento; auditoría informa repositorio recién inicializado | No asumir baseline commiteada ni sobrescribir trabajo existente |
| Compose | `name: agrodiagnostico-v1`, `services: {}` | Hay que integrar servicios; no está probado el entorno de aplicación |
| Backend | Cuatro `main.py` vacíos, Dockerfiles con comentario y `pyproject.toml` sin dependencias (`>=3.11`) | Adoptar Python 3.12 auditado y lockfiles por componente |
| Frontend | Metadatos de package.json, sin dependencias, scripts ni aplicación | Página técnica mínima; no UI de diagnóstico |
| Contratos/migraciones/pruebas/ML | Directorios con `.gitkeep` | Crear contenido comprobable, conservando organización |
| CI | Solo `copilot-setup-steps.yml` | Mantenerlo y añadir CI específica de aplicación |
| OpenSpec | Sin specs vigentes ni cambios activos previos; schema `spec-driven` | Cinco capacidades nuevas, sin sincronizar ni archivar ahora |
| Equipo | `docs/ENVIRONMENT.md` y evidencia fechada: Python 3.12.3, Node 24.21.0, npm 11.19.0, Docker 29.1.3, Compose 2.40.3; CPU probada, GPU no verificada | Reutilizar herramientas; no reinstalar Docker ni habilitar ROCm |

Se leyeron los ocho Markdown de primer nivel de `docs/`, su informe Markdown de evidencia, AGENTS, README y CONTRIBUTING. Los contratos están vacíos. Esta observación describe la inspección inicial. Posteriormente se leyó íntegramente `docs/reference/Definicion_Base_AgroDiagnostico_V1_Limpia.docx`, entregada por el responsable como fuente V1 del grupo 1. La reconciliación y trazabilidad completa están en `docs/reference/RECONCILIACION-V1.md`; los RF todavía no están implementados.

## Goals / Non-Goals

**Goals:** comprobar conexiones reales, arranque desde cero, migraciones repetibles, aislamiento, contratos y controles automáticos. Conservar la auditoría como evidencia del host y producir después evidencia separada de aplicación.

**Non-Goals:** un flujo de diagnóstico, simulaciones clínicas, autenticación real o integración de consumidores. Los controles de autorización en contratos se probarán aquí como estructura/ejemplos; su cumplimiento en ejecución pertenece a los incrementos 1–3. La página técnica no acepta imágenes ni sesiones.

## Decisions

### D0. Unidad de entrega y puertas de revisión

Un cambio con cinco capacidades es suficiente porque sus productos son fundacionales y comparten smoke/CI. Se implementará en bloques revisables: decisiones y contratos, persistencia, integración, inventario y CI/cierre. El inventario puede desarrollarse independientemente; no se delega trabajo automáticamente. Separar hoy cinco cambios duplicaría decisiones y coordinación de aceptación sin reducir el alcance funcional.

La fuente entregada se identifica por ruta, revisión y SHA-256 en `docs/reference/RECONCILIACION-V1.md`. Las diferencias REC-01…REC-20 quedan resueltas documentalmente y los 28 RF tienen referencias literales. Los resúmenes no sustituyen esa lectura. Una nueva fuente o cambio de estado, evento, propiedad o alcance exige revisar la matriz antes de congelar interfaces. El grupo 1 no crea OpenAPI ni JSON Schema.

El grupo 1 registra `docs/adr/0001-incremento-0-base-tecnica.md` y `docs/adr/0002-interfaces-y-eventos-v1.md`, con alternativas, consecuencias y trazabilidad a la fuente reconciliada. Actualizar C4 de contexto/contenedores sin presentar elementos pendientes como desplegados.

### D1. Compose local con entrada única

Reutilizar rutas existentes. Perfil principal: PostgreSQL, RabbitMQ, Redis, S3 compatible, cuatro APIs mínimas y Nginx sirviendo build React/TypeScript. Un build de frontend puede ser etapa multistage de la imagen de Nginx, sin servidor Node persistente adicional. Solo Nginx publica un puerto configurable ligado a `127.0.0.1`; HTTP local no prueba HTTPS público. No habilitar perfiles opcionales por defecto.

Red interna para persistencia y APIs; Nginx conecta a la red de aplicación. Ningún socket Docker se monta en contenedores. Se omiten puertos de administración y ruta pública hacia AI. Los healthchecks de APIs se ejecutan en red interna. Nginx devuelve 404 para `/internal/*` y rutas de negocio no implementadas, con errores API coherentes cuando corresponda; no devolver HTML como supuesto éxito API. Usar `private, no-store` en respuestas `/api/v1/*`.

PostgreSQL, RabbitMQ y S3 tienen volúmenes nombrados asociados al proyecto. Redis es derivado y no requiere persistencia para aceptación. Inicialización idempotente crea bases/roles y bucket privado con credenciales locales externas a Git. Diagnosis recibe permiso acotado de objetos y AI lectura limitada, nunca credenciales raíz; la política de acceso por objeto vía lease llegará con el worker. La prueba anónima S3 se realiza desde la red de pruebas, no publicando el puerto.

Selección propuesta de almacenamiento local: MinIO compatible con S3, únicamente desarrollo; antes de fijar la imagen, verificar disponibilidad, procedencia, licencia y digest. Si no es viable, registrar alternativa compatible y repetir las mismas pruebas sin cambiar el contrato de objetos. No se elige proveedor de producción. Las versiones concretas de imágenes se fijarán por digest comprobado en implementación; no se inventan digests ni se deja `latest` como resultado final.

Alternativa descartada: instalar bases/broker en el host, porque impide repetir el mismo entorno en CI y altera la auditoría ya aceptada.

### D2. Readiness proporcional al incremento

| Servicio | Dependencias indispensables en Incremento 0 | Comprobaciones aparte |
| --- | --- | --- |
| Identity | Configuración y base propia en head | RabbitMQ no es dependencia de Identity |
| Diagnosis | Configuración, base en head y bucket accesible con sus permisos | Redis opcional; broker comprobado en smoke, no en readiness del API |
| AI Inference | Configuración y base propia en head | RabbitMQ y S3 en smoke; no hay worker activo ni carga de modelo |
| Notification | Configuración y base propia en head | Broker en smoke; correo no configurado ni exigido |

Respuesta técnica mínima `{status, service}`; 503 no filtra DSN, excepciones o credenciales. Sondeos acotados, con timeout configurable; propuesta inicial de desarrollo: timeout global 180 s después del build y sondeo cada 5 s, ajustable solo con evidencia. No son SLO de producción. La caída de PostgreSQL provoca readiness 503; recuperación restablece 200. La caída de Redis no invalida Diagnosis. Una futura revisión de worker deberá ampliar su propia señal de readiness sin bloquear la aceptación HTTP de diagnósticos por caída temporal del broker/outbox.

RabbitMQ se verifica mediante publish confirmado y consumo de mensaje sintético en cola durable exclusiva de la prueba. Se comprueba persistencia tras recrear el broker; no se publican eventos de diagnóstico aparentando un flujo funcional.

### D3. Migraciones base deliberadamente mínimas

La sección 6.8 de la fuente no exige una base de negocio a AI, pero permite persistencia técnica. Se conserva una base técnica de AI para futuros trabajos/inferencias/outbox, sin duplicar el diagnóstico publicable. Una instancia PostgreSQL local, cuatro bases (`identity`, `diagnosis`, `ai_inference`, `notification`) y cuatro roles propietarios sin superuser/CREATEDB/CREATEROLE. Revocar CONNECT público en esas bases y concederlo solo al rol correspondiente; restringir permisos de schemas públicos. El bootstrap privilegiado usa una credencial separada, nunca la URL de ejecución de las APIs.

Cada `services/<servicio>/migrations/` tendrá configuración Alembic e historial propio; la primera revisión no crea tablas de dominio, pero deja `alembic_version` en su head verificable. Es una base de migración, no un modelo de datos terminado. Se descarta anticipar usuarios, diagnósticos, outbox o catálogo porque requiere decisiones de los incrementos correspondientes y genera migraciones especulativas.

Migraciones ejecutadas por procesos one-shot antes de readiness, sin `create_all` ni DDL al importar la aplicación. Segunda ejecución sin cambios. Pruebas de downgrade/upgrade solo en bases efímeras. La matriz 4×4 confirma acceso propio y rechazo de doce combinaciones cruzadas. No FK, joins ni lecturas entre bases; referencias futuras entre dominios serán UUID por contrato.

### D4. Contratos antes de consumidores, sin afirmar implementación

Proponer OpenAPI 3.1 para documentos por servicio, con componentes comunes bajo `contracts/schemas/` y JSON Schema 2020-12 para eventos; fijar validadores compatibles en lockfiles y probar referencias locales. El contrato versionado es fuente de interfaz; el OpenAPI generado por FastAPI cubre solo salud implementada y se compara con ese subconjunto. No exigir a un backend vacío que implemente todas las rutas proyectadas.

El paquete inicial cubrirá las rutas enumeradas en las tareas 2.2–2.6. Las operaciones adicionales de la fuente reconciliada permanecen inventariadas con responsable e incremento y se contratarán antes de sus consumidores, según REC-03…05. Un índice tendrá operación, propietario, incremento objetivo y estado `contract-only` o `implemented`. Las rutas administrativas genéricas se registran como pendientes del incremento 1/2/5 pertinente sin fabricar handlers o comodines. La fuente reconciliada obliga a completar cambio de contraseña, confirmación de recuperación, feedback de utilidad y lectura de aviso antes de sus consumidores, además de administración. El inventario de `docs/API_CONTRACTS.md` registra equivalencias de las rutas conceptuales del DOCX y responsables; las formas finales se definen al contratar cada operación, sin implementar esas funciones en Incremento 0.

Propuestas concretas para cerrar las operaciones auxiliares no fijadas aún:

| Operación | Ruta propuesta | Protección contractual |
| --- | --- | --- |
| Reclamo | `POST /internal/diagnoses/{id}/claim` | Identidad de AI; devuelve owner/token/vencimiento del lease; 409 si no reclamable |
| Renovación | `POST /internal/diagnoses/{id}/lease/renew` | Identidad de AI más lease vigente; 409 obsoleto |
| Imagen interna | `GET /internal/diagnoses/{id}/image` | Identidad de AI y lease vigente; entrega privada, nunca URL permanente |
| Imagen propia | `GET /api/v1/diagnoses/{id}/image` | Propietario; 404 ajeno/inexistente; no-store |

El token de lease es UUID de fencing/concurrencia, distinto de una credencial bearer: el evento Analyzed lo necesita según la línea base. La prohibición de tokens en eventos se aplica a credenciales de acceso/refresh/servicio, no a ese identificador sin autoridad propia. Registrar esta distinción en ADR y fixtures.

Definir errores `{code,message,correlation_id,details?}`, cabecera `X-Correlation-ID`, UUID/UTC y paginación por cursor opaco. Propuesta local inicial: límite predeterminado 20 y máximo 100, con rechazo de valores fuera de rango; documentar como parámetros de contrato, no rendimiento medido. La carga no exige selección manual de cultivo (RF-07). Los límites iniciales propuestos son 10 MiB y 24 MP, sin validación productiva aún. JPEG/PNG/WebP y HEIC/HEIF son el objetivo de V1 según §9.12/10.9; HEIC/HEIF exige conversor y prueba E2E antes de anunciar soporte, sin eliminar ese objetivo de cierre. No implementar decodificación en este incremento.

Idempotency-Key: namespace `(owner_id, operación, clave)`, fingerprint de bytes y campos semánticos; misma solicitud devuelve mismo ID, contenido distinto responde 409. Proponer retención local de 24 h parametrizada, con comportamiento posterior al vencimiento explícito (nueva solicitud); aprobar y fijar el valor contractual antes de integrar clientes. No extrapolarlo a retención de fotografías o políticas de producción.

Seguridad del contrato: access bearer firmado; refresh en cookie HttpOnly, Secure y SameSite=Lax; mutaciones con cookie sujetas a validación de origen y token CSRF. El perfil local de Incremento 0 no prueba sesiones por HTTP. Algoritmo, issuer/audience, expiraciones, revocación y flujo definitivo se cierran mediante ADR antes del incremento 1; no incluir credenciales de prueba como ejemplos reales.

Eventos: envelope estricto y payloads discriminados por tipo/versión; usar los campos mínimos existentes. Definir variantes del análisis técnico (predicción, abstención, fallo) y razones compatibles sin delegar publicación a AI. Class codes referencian la taxonomía candidata y no acreditan soporte. `raw_score` acotado a [0,1] cuando esté presente no equivale a probabilidad clínica. Para fallo sin inferencia real, explicitar nulabilidad de metadatos de modelo requeridos y no fabricar versiones.

Propuesta de routing para documentar: exchange durable `agrodiagnostico.events`, claves `diagnosis.requested.v1`, `diagnosis.analyzed.v1`, `diagnosis.finished.v1`; consumidores y colas propios con DLQ. Solo se especifica el routing de negocio: su ejecución, confirms/outbox/inbox y reintentos se implementan en incremento 3. Fixtures negativos cubren campos faltantes, secretos adicionales, versiones, estados y combinaciones incoherentes. Cambios incompatibles requieren versión nueva.

### D5. Inventario de datos sin entrenamiento

Crear después registro de fuentes y taxonomía en `ml/manifests/`, esquema y fixtures sintéticos separados de datos reales. Propuesta de códigos inmutables: `POTATO_HEALTHY`, `POTATO_EARLY_BLIGHT`, `POTATO_LATE_BLIGHT`, `MAIZE_HEALTHY`, `MAIZE_COMMON_RUST`, `MAIZE_LEAF_BLIGHT`, `MAIZE_GRAY_LEAF_SPOT`. Todos candidatos; en particular no atribuir una definición específica a «tizón foliar» sin revisar etiquetas y línea base.

PlantVillage, PlantDoc y PlantSeg empiezan como pendientes, con enlace de origen y evidencia de licencia que se deberán investigar al implementar; no se han consultado ni aprobado en esta propuesta. Si no hay consulta posible, registrarlo como desconocido con causa. Ayacucho externo se marca no disponible salvo evidencia autorizada. Distinguir cantidades reportadas por la fuente de cantidades locales observadas. `null` representa desconocido; cero solo si se midió ausencia.

El validador inicial verifica estructura, elegibilidad declarada, taxonomía, hashes y separación de grupos entre particiones sobre fixtures. No requiere descargar imágenes; deduplicación visual, particionado definitivo, curación y test sellado pertenecen al incremento 4. No entrenar automáticamente ni derivar licencias de la popularidad de la fuente.

### D6. CI y reproducibilidad sin alterar el equipo

Conservar Python 3.12 y Node/npm auditados. Propuesta de lock Python: uv con versión fijada y lock independiente por servicio, instalado en entorno aislado o build, sin cambiar Python global; frontend usa package-lock y npm ci. Dependencias y herramientas de CI se fijan al implementar tras comprobar compatibilidad; no ejecutar instalaciones del scaffold vacío. Imágenes y actions con referencias inmutables revisables. Mantener `copilot-setup-steps.yml` intacto; su instalación global de OpenSpec no sustituye el entorno fijado de CI.

Jobs propuestos: validación/lint/tipos; pruebas técnicas y contratos/dataset/OpenSpec; build y migraciones/smoke. Compartir scripts o comandos de entrada con desarrollo para no duplicar lógica. Ejecución en pull_request y push a main, permisos contents:read, timeout y limpieza always. Nombre de proyecto Compose único por ejecución para aislar volúmenes; nunca `docker system prune`.

Guardar reportes de pruebas, versiones/digests, revisión Git (o «sin commit» con hashes en ejecución local inicial), duración, exit codes y logs sanitizados. No volcar `.env` ni Compose expandido con secretos a los artefactos. Las pruebas negativas de infraestructura son obligatorias; una suite vacía no pasa como cobertura.

## Risks / Trade-offs

- [Evolución de la fuente V1] → conservar hash, extracción y matriz reconciliada; repetir revisión ante cambios, sin certificar cobertura funcional RF por documentación.
- [Contratos futuros se confunden con endpoints disponibles] → índice por operación y comparación del subconjunto implementado, sin respuestas de negocio simuladas.
- [Múltiples servicios elevan costo local] → CPU, sin PyTorch/modelo en servicios mínimos; documentar consumo observado, no prometer capacidad.
- [Baseline Alembic sin tablas parece producto terminado] → evidencia de head y aislamiento solamente; dominio posterior explícito.
- [Cambios en disponibilidad/licencia de dependencias o fuentes] → verificación al fijar imágenes y al evaluar fuentes, con evidencia y restricciones.
- [Inventario sin dataset disponible] → aceptación por trazabilidad y validación sintética; no reportar cantidades, curación ni métricas inexistentes.
- [Parámetros locales se copian a producción] → configuración distinguida y decisiones de seguridad/despliegue pendientes antes de publicación.

## Migration Plan

1. Reconciliar fuente V1 y registrar ADR; fijar contratos antes de consumidores.
2. Añadir dependencias bloqueadas, bootstrap aislado y cuatro revisiones base; probar en proyecto Compose desechable.
3. Construir frontend técnico/APIs e integrar salud, objetos privados y persistencia; no tocar recursos ajenos.
4. Añadir inventario/validadores y CI; ejecutar positivos, negativos y reproducción desde cero.
5. Documentar comandos efectivamente probados y matriz de requisitos/evidencias; sincronizar y archivar únicamente tras implementación verificada y el flujo correspondiente.

Reversión: detener el proyecto sin `-v` conserva datos; reejecutar imágenes anteriores solo si el head es compatible. Downgrade base se ensaya únicamente en bases efímeras; no automatizar borrado de volúmenes existentes. No hay despliegue ni datos de producción que migrar en este incremento.

## Open Questions

Diferibles sin bloquear la base local: dominio/hosting, proveedor de correo/objetos de producción, retención de fotografías, hardware GPU y umbrales del modelo. Se resolverán en los incrementos correspondientes. La fuente entregada ya se ha reconciliado en D0; las decisiones contractuales deberán respetar esa matriz y los ADR del grupo 1.


## Aplicación de D4 — grupo 2

El paquete inicial ahora está en `contracts/`, con 27 operaciones contract-only, componentes comunes, eventos v1, fixtures y herramienta aislada. Las propuestas de D4 se concretan en la adenda de ADR-0002 y `docs/API_CONTRACTS.md`: límites/paginación/idempotencia adoptados para el contrato inicial, no producción medida. Salud aún no se implementa; su comparación con FastAPI corresponde al grupo4. Inspección inicial de la tabla de contexto se conserva como histórica. Evidencia y comandos en `docs/evidence/INCREMENTO-0-GRUPO-2.md`; no se avanza a otros grupos ni se sincroniza/archiva.


## Aplicación de D3 — grupo 3

Compose integra exclusivamente PostgreSQL, bootstrap separado, cuatro migraciones one-shot y comprobaciones de head dependientes de éxito. `app.persistence.schema_ready()` es el prerrequisito de persistencia para las APIs del grupo4; no se publica HTTP ni se afirma readiness completa sin las otras dependencias D2. Los secretos locales se generan fuera de Git, cada job de servicio recibe solo el propio y ningún puerto se publica. Revisiones base sin dominio, locks independientes y aceptación PostgreSQL real en proyecto efímero; operación/evidencia en `docs/PERSISTENCE.md` y `docs/evidence/INCREMENTO-0-GRUPO-3.md`.


## Aplicación de D1–D2 — grupo 4

El entorno local integra las cuatro APIs de salud, frontend técnico/Nginx, PostgreSQL, RabbitMQ, Redis y S3 privado. SeaweedFS4.17 reemplaza la propuesta de MinIO tras verificar mantenimiento/procedencia, según alternativa autorizada D1 y ADR-0003. API/datos en redes internas; edge exclusiva de Nginx publica loopback. Se ejecutan pruebas de salud, permisos, degradación y persistencia en proyecto efímero; el frontend pasa lint/tipos/render/build. La fuente de interfaz marca únicamente ocho operaciones de salud implementadas, con comparación del OpenAPI generado. Procedimiento y evidencia en DEVELOPMENT e INCREMENTO-0-GRUPO-4; no se avanza a dataset, CI o cierre global.

## Aplicación de D5 — grupo 5

`ml/manifests/` conserva fuentes por revisión, licencias declaradas y pendientes de admisión, cantidades remotas separadas de locales no medidas, siete códigos candidatos y veintiún mapeos. PlantSeg v5/v7 declara licencias diferentes; se registra la diferencia sin transferir permisos ni atribuir identidad de archivos. Las definiciones y equivalencias agronómicas continúan pendientes conforme a D5.

Manifiesto CSV de diez campos, JSON Schema y validador offline con controles globales de hash/grupo; pruebas sintéticas separadas. El inventario real no contiene filas, no se descargaron imágenes ni se entrenó. Política de cuarentena, revisión visual y admisión posterior en `ml/manifests/README.md`; evidencia en `docs/evidence/INCREMENTO-0-GRUPO-5.md`. No cambia estados de diagnóstico, eventos, propiedad ni alcance; grupos 6–7 pendientes.

## Aplicación de D6 — grupo 6

Workflow separado para PR/push main con actions fijadas por SHA, runtimes y herramientas bloqueadas, permiso contents:read, timeout y pasos always de limpieza/reportes. Copilot y auditoría conservados. `scripts/run_ci.py` ejecuta las catorce etapas obligatorias compartidas localmente; valida versiones, registra resultados/hashes y no permite declarar éxito con etapas omitidas.

Los verificadores Compose conservan diagnóstico sanitizado y verifican eliminación de recursos propios; el runner y workflow añaden limpieza de respaldo por proyecto registrado. Cuatro regresiones independientes y un timeout real se ensayan en copias restauradas/destruidas, con fallo global y artefactos preservados. La ejecución positiva y los cinco negativos están en `docs/evidence/INCREMENTO-0-GRUPO-6.md`. npm aislado actualizado sin cambiar el global; avisos residuales de dependencias incluidas por npm documentados, sin afirmar auditoría de seguridad completa. No se ejecutó el workflow remoto ni se avanzó al grupo 7.

## Aceptación integrada — grupo 7

Catorce etapas aprobadas desde checkout temporal limpio, con matriz de los 17 requisitos y hashes en `docs/evidence/INCREMENTO-0-GRUPO-7.md`. Código de aplicación sin cambios durante esta aceptación. 7.3 pendiente: workflow remoto no ejecutado, sin revisión publicada. No se sincroniza ni archiva; el cierre depende de resolver esa verificación. Los apartados por grupo conservan su estado histórico.
