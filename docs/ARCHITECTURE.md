# Arquitectura de AgroDiagnóstico V1

## Propósito y límites

Una persona autenticada sube una fotografía; el sistema la valida y guarda privadamente, crea una solicitud asíncrona, procesa la imagen con un modelo versionado y ofrece un resultado evaluado junto con recomendaciones revisadas. La V1 se limita a las clases validadas de papa y maíz. El modelo no diagnostica otras plantas ni prescribe dosis.

## Contenedores y propiedad

| Componente | Datos propios | Interfaz principal |
| --- | --- | --- |
| Frontend React/TypeScript | Estado de UI, sin secretos persistentes | REST por Nginx |
| Identity | Usuarios, refresh sessions y recuperación | `/api/v1/auth`, perfil |
| Diagnosis | Diagnósticos, objetos referenciados, resultados visibles, catálogo, outbox/inbox | `/api/v1/diagnoses`, `/api/v1/admin`, operaciones internas |
| AI Inference | Trabajos e inferencias técnicas, versiones, outbox | Cola de eventos y API interna autorizada |
| Notification | Avisos, preferencias e intentos de entrega | `DiagnosisFinished`, API de notificaciones |
| PostgreSQL | Base o esquema y usuario por servicio | Conexión interna |
| Object Storage | Imágenes privadas | Acceso mínimo de Diagnosis y lectura autorizada del worker |
| RabbitMQ | Eventos durables y DLQ | Red interna |
| Redis | Caché derivada del catálogo | Red interna; PostgreSQL como respaldo |
| Nginx | Entrada y enrutamiento | HTTPS desde Cloudflare en producción |

Los servicios no comparten tablas, migraciones ni credenciales. Las referencias entre dominios usan identificadores, eventos o APIs. En local pueden compartir una instancia de PostgreSQL con aislamiento lógico.

## Recorrido principal

1. Diagnosis comprueba sesión, formato real y límites de la imagen; la coloca en un bucket privado.
2. En la misma transacción crea `PENDIENTE` y el outbox de `DiagnosisRequested`. Un publicador usa confirmación del broker antes de marcarlo entregado.
3. El worker reclama atómicamente el trabajo y obtiene un lease; Diagnosis cambia a `PROCESANDO`. El worker lee el objeto autorizado y realiza inferencia.
4. AI persiste inferencia técnica y outbox de `DiagnosisAnalyzed` antes del ACK. Diagnosis consume idempotentemente, valida `lease_token`, versión y estado.
5. Diagnosis decide `COMPLETADO` o `NO_CONCLUYENTE`. Solo el primero vincula recomendaciones del catálogo validado. Guarda resultado, snapshot de versión y outbox de `DiagnosisFinished`.
6. Notification crea un aviso interno idempotente. Intenta correo según preferencia; un fallo de correo no modifica el diagnóstico. La UI consulta estado e historial propios.

`DiagnosisFinished` cubre los terminales notificables, incluidos `COMPLETADO`, `NO_CONCLUYENTE` y `FALLIDO`; no se emite una notificación de éxito al cancelar.

## Estados y concurrencia

| Origen | Destino | Condición |
| --- | --- | --- |
| PENDIENTE | PROCESANDO | Reclamo atómico; no cancelado |
| PENDIENTE | CANCELADO | Cancelación del propietario antes del reclamo |
| PROCESANDO | COMPLETADO | Clase soportada y evidencia suficiente |
| PROCESANDO | NO_CONCLUYENTE | Confianza insuficiente, imagen inadecuada o fuera de cobertura |
| PROCESANDO | FALLIDO | Fallo definitivo o reintentos agotados |

El lease tiene `owner`, `token` y vencimiento. Un resultado emitido por un lease obsoleto se ignora y audita. Las transiciones terminales son únicas. El barrido de leases vencidos permite recuperación; los valores iniciales de 120 s de lease, renovación cada 30 s y barrido cada 30 s se ajustarán según medidas reales. Tres intentos totales significan uno inicial y hasta dos reintentos, solo para errores transitorios.

## Patrones y fallos

- **Outbox/inbox e idempotencia:** soportan publicación recuperable y entrega al menos una vez. Una misma `Idempotency-Key` del propietario devuelve el mismo `diagnosis_id` para la misma operación definida por contrato.
- **DLQ y replay:** conservan evento y causa general sin binarios ni secretos; el replay administrativo verifica el estado y no revive terminales por accidente.
- **Cache Aside:** Redis acelera lecturas apropiadas del catálogo; una caída vuelve a PostgreSQL. La edición invalida la clave versionada después del commit.
- **Puertos/adaptadores:** aíslan almacenamiento, correo y motor de IA donde existe variabilidad real; evitar capas vacías por convención.
- **Observabilidad:** `correlation_id` recorre HTTP y eventos; los logs conservan `diagnosis_id` cuando se autorice, sin usarlo como etiqueta de métricas de alta cardinalidad.

## Frontera pública

Cloudflare recibe el dominio y reenvía por TLS al Nginx de origen. Nginx sirve frontend y APIs públicas; PostgreSQL, RabbitMQ, Redis, objetos y rutas `/internal/*` permanecen restringidos. El CDN cachea recursos estáticos versionados; fotografías, sesiones, historial y respuestas privadas no entran en caché compartida. Véase [DEPLOYMENT.md](DEPLOYMENT.md).

## Registro de decisiones

Usa `docs/adr/` para cambios de topología, contratos, estrategia de autenticación, modelo de datos, almacenamiento o alcance de IA. Cada ADR incluirá contexto, alternativas, decisión, consecuencias y fecha. Actualiza diagramas C4 de contexto/contenedores y, cuando aporten, componentes.

## Precisiones del grupo 1

La [reconciliación V1](reference/RECONCILIACION-V1.md) interpreta §6.8 como ausencia de base **de negocio** obligatoria para AI, no prohibición de persistencia técnica. Se mantiene base propia técnica para trabajos, inferencias y outbox; Diagnosis conserva el único resultado publicable. El [ADR de base](adr/0001-incremento-0-base-tecnica.md) limita las cuatro migraciones del Incremento 0 a metadatos Alembic.

Diagnosis también será dueño del feedback de utilidad (RF-20), sin uso automático como etiquetas ML. `FALLIDO` es notificable por §6.7 aunque RF-18 solo enumere resultados concluyentes/no concluyentes. `CANCELADO` no produce DiagnosisFinished. Decisiones de interfaz y concurrencia en el [ADR correspondiente](adr/0002-interfaces-y-eventos-v1.md).


## Entorno local implementado en grupo4

[Topología técnica](c4/entorno-local.md) y [ADR-0003](adr/0003-entorno-local-y-almacenamiento.md): salud de cuatro APIs, página técnica y dependencias privadas, con Nginx como única entrada loopback. Los flujos de diagnóstico descritos arriba siguen previstos, no implementados por esta integración.
