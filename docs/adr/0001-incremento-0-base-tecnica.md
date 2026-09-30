# ADR-0001 — Alcance técnico, topología y persistencia del Incremento 0

Fecha: 2026-09-28. Estado: decisión adoptada; base técnica implementada en grupos 3–4. Los apartados fechados conservan el estado histórico de cada entrega.
Tarea: 1.2 de `incremento-0-base-integrada`.

## Contexto y fuentes

Fuente DOCX revisión 3, hash y lectura íntegra en [reconciliación V1](../reference/RECONCILIACION-V1.md). Secciones 6.1–6.18, 7.5–7.6, 7.14, 7.17–7.19, 9.1–9.5, 9.27, 9.44 y 10.63. Refinamiento del diseño D0–D3; requisitos ENV-01…04 y MIG-01…03. La estructura, auditoría del host y workflow Copilot existen; Compose, servicios funcionales, contratos y migraciones no están implementados.

## Decisión

El Incremento 0 entrega una base técnica reproducible, no diagnósticos. Conserva cuatro servicios en sus rutas existentes, frontend técnico y Nginx; integra PostgreSQL, RabbitMQ, Redis y S3 compatible. Ejecuta CPU, sin requerir pesos, GPU, correo, Cloudflare ni módulos opcionales. La página identifica el entorno como técnico; no simula resultados clínicos.

Nginx es la única entrada local publicada, ligada a loopback. Bases, broker, Redis, S3, consolas y APIs quedan internos; `/internal/*` y AI no son rutas públicas. HTTP local no satisface producción: dominio real, Cloudflare Full (strict), TLS de origen y CDN de estáticos siguen en incremento 5. Objetos privados y credenciales mínimas, con bootstrap separado de aplicación. No almacenar bytes de fotografías en PostgreSQL.

| Servicio | Datos de los que será dueño | Base local | Incremento 0 |
| --- | --- | --- | --- |
| Identity | Usuarios, roles, sesiones y recuperación | `identity` | Revisión Alembic, sin tablas de negocio |
| Diagnosis | Solicitudes, resultado visible, catálogo, referencias de imagen, feedback, auditoría, outbox/inbox | `diagnosis` | Revisión Alembic, sin tablas de negocio |
| AI Inference | Trabajos y análisis técnicos, metadatos de versiones y outbox | `ai_inference` | Revisión Alembic técnica, sin inferencia ni pesos |
| Notification | Avisos, preferencias, intentos y estado de entrega | `notification` | Revisión Alembic, sin correo ni consumidores |

Una instancia PostgreSQL puede alojar las cuatro bases. Cada rol accede solo a su base, sin superusuario, CREATEDB o CREATEROLE; CONNECT público se revoca en esas bases. No tablas compartidas, joins ni claves foráneas entre servicios. Bootstrap privilegiado separado; migraciones one-shot, no `create_all` al iniciar APIs. El grupo 3 implementará y probará cuatro accesos propios y doce rechazos cruzados.

**Resolución REC-06:** §6.8 P749 no exige base de negocio a AI y permite conservación técnica. La cuarta base no crea un segundo propietario de diagnósticos: permite persistir análisis técnico y outbox antes del ACK en incremento 3, conforme a §7.11 y AGENTS. Evita perder el análisis cuando falla la publicación sin escribir en Diagnosis. En 0 solo se comprueba el historial de migración.

Liveness indica proceso; readiness exige configuración y base propia en head. Diagnosis exige también acceso autorizado al bucket. Redis/correo no condicionan Diagnosis. El broker se comprueba por smoke independiente: no convertir su caída en impedimento futuro de registrar diagnóstico y outbox. En 0 AI no es worker funcional; en 3/4 la señal del worker exigirá sus dependencias y el modelo correspondiente cargado, conforme a §9.27/10.46.

PostgreSQL, RabbitMQ y objetos usan volúmenes propios. Parar/recrear sin borrar volúmenes debe conservar fila técnica, mensaje durable persistente y objeto. Las pruebas negativas y de reversión usan recursos efímeros identificados, sin borrar recursos del desarrollador. Se conserva Python 3.12 y Node/npm auditados; las dependencias/imágenes se fijarán al implementar, no se inventan versiones/digests.

## Alternativas consideradas

| Alternativa | Decisión y motivo |
| --- | --- |
| Rehacer scaffold/auditoría e instalar dependencias en el host | Descartada: duplica trabajo existente y deteriora reproducibilidad |
| Base/tablas compartidas por todos los servicios | Descartada: viola propiedad y permisos verificables |
| Instancia PostgreSQL física por servicio desde 0 | Diferida: aislamiento lógico probado es suficiente para base local; mayor costo operativo |
| AI sin persistencia técnica y publicación directa | Descartada para este diseño: dificulta commit local/outbox/ACK y recuperación exigidos |
| Tablas de usuarios/diagnósticos/outbox completas en 0 | Descartada: adelanta dominio de incrementos 1–3; la revisión base no acredita esas funciones |
| Kubernetes, modelo real y observabilidad completa en arranque de 0 | Diferidos: no son necesarios para aceptación técnica; observabilidad V1 permanece obligatoria en 5 |

## Consecuencias y límites

Cuatro bases implican bootstrap, credenciales y migraciones independientes, incluso para AI técnico. El host compartido sigue siendo un punto de fallo; no se promete alta disponibilidad. Readiness del scaffold solo demuestra preparación técnica. El backend no tiene autenticación de usuario ni contratos funcionales ejecutables por este ADR. HEIC/HEIF, feedback y cultivo automático quedan en los incrementos asignados en la matriz, sin eliminarse del alcance V1.

## Verificación de esta decisión

Revisión documental: cuatro propietarios sin duplicar resultado visible; alternativas y consecuencias presentes; coincidencia con D0–D3 y REC-06/14/19; en esa revisión del grupo 1, las tareas 3.2–3.5 y 4.1–4.9 permanecían pendientes. La [evidencia del grupo 1](../evidence/INCREMENTO-0-GRUPO-1.md) registra validación e integridad de los archivos preservados. No se ejecutaron pruebas de infraestructura ni migraciones como parte de 1.2.


## Concreción de persistencia — grupo 3, 2026-09-29

Se implementan los cuatro historiales y locks independientes, PostgreSQL16 privado con volumen, bootstrap idempotente separado y jobs de migración one-shot. Sin tablas de dominio: únicamente alembic_version. Roles de servicio sin privilegios globales; CONNECT público revocado. Configuración por campos y archivos de secretos evita URLs con credenciales en logs.

La comprobación `schema_ready()` verifica el head real frente al historial, falla cerrada y no ejecuta DDL. Compose bloquea el job de comprobación hasta que su migración termina con0. Es la porción de persistencia de readiness; el endpoint HTTP y la conjunción con S3 para Diagnosis siguen en grupo4. No se anticipan esos handlers para declarar terminado el grupo3.

[Operación](../PERSISTENCE.md) documenta Python3.12, uv y dependencias bloqueadas, secretos locales, límites de usuario de contenedor, repetición/reversión y aceptación efímera. [Evidencia](../evidence/INCREMENTO-0-GRUPO-3.md) prueba aislamiento4×4, migraciones y fallos reales. La sección original de este ADR se conserva como decisión histórica del grupo1.
