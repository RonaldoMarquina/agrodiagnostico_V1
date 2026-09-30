# Tasks — Incremento 0

Los grupos 1–6 están autorizados y verificados en sus alcances documental, contractual, de persistencia, entorno técnico, inventario inicial y CI reproducida localmente. Solo se marcan tareas terminadas; 7.1, 7.2 y 7.4 verificadas; 7.3 pendiente por fallo de CI remota (ejecución 36743640034). Los IDs se refieren a los cinco deltas de `specs/`; no sustituyen RF-01…RF-28.

## 1. Línea base y decisiones previas

- [x] 1.1 Obtener la especificación detallada V1 completa en el repositorio o mediante un archivo accesible y reconciliarla con los documentos examinados. Verificar una matriz de coincidencias/discrepancias con ruta y versión de la fuente, referencias a sus requisitos y resolución documentada de cada discrepancia antes de congelar contratos. Mantener esta tarea pendiente mientras falte la fuente o queden discrepancias sin resolver; los Markdown resumidos y `docs/Incrementos.md` no sustituyen esa especificación. No inventar RF ni continuar una parte contradictoria (CTR-01, CI-03).
- [x] 1.2 Registrar ADR de alcance del Incremento 0, topología local y propiedad de persistencia según D0–D3. Verificar que contiene alternativas, consecuencias y separación entre base técnica y funcionalidades posteriores; conservar estructura, auditoría y workflow Copilot (ENV-01, MIG-02).
- [x] 1.3 Registrar ADR de contratos/eventos según D4, incluyendo lease_token como identificador sin autoridad propia, variantes de análisis y decisiones propuestas de paginación/idempotencia. Verificar coherencia con estados, emisor/consumidor y la fuente reconciliada; añadir matriz de incrementos responsables de implementar las garantías (CTR-02–04).

## 2. Contratos iniciales y pruebas de contrato

Depende del grupo 1. No requiere endpoints de negocio ni integración de consumidores.

- [x] 2.1 Añadir herramientas de validación con versiones bloqueadas y comando local repetible. Verificar ejecución en entorno aislado sin instalar dependencias globales y rechazo de una referencia rota en fixture (CTR-01, CI-01).
- [x] 2.2 Crear componentes comunes HTTP y contrato de salud de los cuatro servicios. Verificar ejemplos 200/503, UUID/UTC, error común y referencias resueltas; documentar convenciones y compatibilidad en `docs/API_CONTRACTS.md` (CTR-01).
- [x] 2.3 Crear contrato Identity para register/login/refresh/logout, perfil GET/PATCH e inicio de recuperación; fijar payloads, cookies, CSRF, errores y estado contract-only. Verificar ejemplos válidos/inválidos y matriz de seguridad; registrar confirmación de recuperación y administración aún pendientes antes de su consumidor (CTR-01–02).
- [x] 2.4 Crear contrato Diagnosis para carga, lista paginada, detalle, cancelación y borrado lógico. Verificar 202, estados terminales, 400/401/404/409/413/415, límites y casos de Idempotency-Key con mismo/diferente contenido, usuario y vencimiento; documentar semántica sin implementar handlers (CTR-01–02).
- [x] 2.5 Contratar reclamo, renovación, imagen interna e imagen propia con rutas de D4. Verificar ejemplos de lease vigente/obsoleto, errores, seguridad de servicio frente a usuario y ausencia de URL pública permanente (CTR-01–02).
- [x] 2.6 Crear contrato Notification para avisos y preferencias GET/PATCH. Verificar paginación, errores y autenticación por operación; completar índice de todas las rutas concretas del inventario y rutas administrativas pendientes con incremento propietario (CTR-01–02).
- [x] 2.7 Crear envelope y JSON Schema v1 de DiagnosisRequested, DiagnosisAnalyzed y DiagnosisFinished con campos mínimos existentes. Verificar fixtures positivos y negativos de campos requeridos, versiones, combinaciones de outcome, clase/estado NO_CONCLUYENTE y CANCELADO no notificable; rechazar campos de credenciales y binarios (CTR-03).
- [x] 2.8 Documentar routing, productores/consumidores, confirms, transacciones outbox, ACK tras commit, inbox, deduplicación, lease obsoleto y compatibilidad. Verificar matriz completa de los tres eventos y escenarios futuros, dejando ejecución de esas garantías en incremento 3 (CTR-04).

## 3. Persistencia aislada y migraciones base

Depende de decisiones del grupo 1; puede prepararse después de fijar contratos de salud.

- [x] 3.1 Fijar Python 3.12, herramienta de lock, dependencias mínimas FastAPI/SQLAlchemy/Alembic y driver PostgreSQL por servicio. Verificar instalación desde lock en entorno limpio e imports; documentar comandos en los README de servicios sin alterar herramientas globales (MIG-01, CI-01).
- [x] 3.2 Configurar PostgreSQL local con volumen, bootstrap idempotente y cuatro bases/roles según D3, manteniendo privilegios de inicialización fuera de las APIs. Verificar arranque limpio, segunda inicialización y roles sin superuser/CREATEDB/CREATEROLE (MIG-02, ENV-04).
- [x] 3.3 Crear configuración Alembic y revisión base independiente para Identity, Diagnosis, AI Inference y Notification en sus carpetas existentes. Verificar por servicio `upgrade head`, `current`, segundo upgrade sin cambios y downgrade/upgrade en bases efímeras; no crear tablas ni seeds de dominio (MIG-01).
- [x] 3.4 Añadir pruebas de acceso 4×4 y fallos de migración. Verificar cuatro conexiones propias exitosas, doce cruzadas rechazadas y salida no cero con contraseña inválida; revisar que logs no contienen la credencial de prueba (MIG-02–03).
- [x] 3.5 Integrar migraciones one-shot y detección de revisión esperada, y documentar arranque, repetición y reversión segura. Verificar que una migración fallida o head ausente impide readiness, sin `create_all` de respaldo y sin eliminar volúmenes existentes (MIG-03).

## 4. Entorno integrado mínimo

Depende de contratos de salud y grupo 3. Las pruebas de este grupo se incorporan con cada componente.

- [x] 4.1 Convertir `.env.example` en configuración comentada utilizable con placeholders seguros, diferenciando variables locales obligatorias de opcionales/de producción. Verificar preparación documentada y fallo legible cuando falta una variable obligatoria, sin imprimir secretos (ENV-01).
- [x] 4.2 Implementar APIs técnicas y Dockerfiles con dependencias fijadas; health/live y health/ready siguen la matriz D2. Verificar respuestas frente a configuración inválida, base ausente, head incorrecto, S3 inaccesible para Diagnosis y recuperación; comparar OpenAPI generado únicamente con salud contratada (ENV-02, MIG-03, CTR-01).
- [x] 4.3 Implementar frontend React/TypeScript mínimo con lock npm, lint, tipos y build servido por Nginx. Verificar renderizado «entorno técnico», sin subida ni resultado clínico, mediante una prueba de página y build; documentar comando reproducible en frontend (ENV-01, CI-01).
- [x] 4.4 Integrar RabbitMQ, Redis y S3 local con versiones/digests comprobados; comprobar licencia/procedencia de imagen S3 y registrar la selección. Añadir inicializador idempotente de bucket privado y permisos separados; verificar upload/read sintético autorizado, rechazo anónimo y denegación de escritura con credencial de AI (ENV-03–04).
- [x] 4.5 Completar Compose con redes, volúmenes, healthchecks y orden condicionado por inicialización/migración. Verificar `docker compose config --quiet` y arranque desde cero dentro del timeout documentado; revisar que no requiere GPU, modelo, servicios opcionales, correo ni Cloudflare (ENV-01–02).
- [x] 4.6 Configurar Nginx como única entrada loopback, sin rutas internas ni AI; añadir no-store para API. Verificar puertos efectivos, 404 para `/internal/*`, ausencia de éxitos simulados en negocio y página estática accesible. Documentar topología local y actualizar C4 diferenciando producción pendiente (ENV-03, CTR-01).
- [x] 4.7 Probar persistencia tras parada/recreación sin borrar volúmenes: head de migración/fila técnica, mensaje RabbitMQ durable persistente confirmado antes del reinicio y objeto privado con checksum. Verificar recuperación exacta y limpieza limitada a recursos de prueba (ENV-04).
- [x] 4.8 Añadir pruebas de degradación: PostgreSQL caído produce ready 503/live 200, restauración recupera ready; Redis caído no apaga Diagnosis; comprobar conectividad broker/S3 aparte. Verificar tiempos acotados y ausencia de falsa evidencia de inferencia, outbox o fallback de catálogo (ENV-02).
- [x] 4.9 Actualizar `docs/DEVELOPMENT.md` y README con preparación, build, arranque, migración, salud y parada efectivamente ejecutados. Verificar reproducción literal en proyecto aislado y conservar sin reescribir `docs/ENVIRONMENT.md`, evidencia del host y su script (ENV-01, CI-03).

## 5. Inventario inicial del dataset

Depende de taxonomía/alcance reconciliados; independiente del arranque de aplicación.

- [x] 5.1 Registrar en `ml/manifests/` PlantVillage, PlantDoc y PlantSeg con referencia primaria, autor/versión cuando estén disponibles, fecha de consulta, evidencia de permiso/licencia, restricciones y elegibilidad. Verificar que falta de evidencia obliga a estado pendiente/excluido; no descargar datos por defecto (DATA-01).
- [x] 5.2 Registrar cantidades reportadas y locales por clase, contexto de captura, revisión, duplicados, exclusiones y disponibilidad de Ayacucho externo. Verificar que desconocido se distingue de cero, que toda cifra tiene fuente/metodología y que la falta de datos externos queda explícita (DATA-01).
- [x] 5.3 Crear mapa versionado de las siete clases candidatas y mapeos de etiquetas de origen según D5. Verificar cultivo/clase, códigos únicos no reciclables y ausencia de NO_CONCLUYENTE como clase; documentar definiciones aún pendientes sin atribuir cobertura soportada (DATA-02).
- [x] 5.4 Definir esquema de manifiesto con los diez campos mínimos, fixtures sintéticos y validador. Verificar aceptación positiva y rechazo de hash inválido, campo ausente, clase desconocida, cultivo incompatible y fuente declarada elegible sin evidencia (DATA-01–02).
- [x] 5.5 Añadir controles de hashes/grupos cruzados y política de cuarentena, agrupamiento y revisión visual posterior. Verificar rechazo de fugas entre cada par de particiones sin mutación silenciosa; documentar en `ml/README.md` y `docs/AI_MODEL.md` límites de la validación y ausencia de entrenamiento/consentimiento automático (DATA-03).

## 6. CI de aplicación

Depende de los comandos y pruebas de grupos 2–5, que ya deben ejecutarse localmente.

- [x] 6.1 Añadir workflow separado de Copilot para pull_request/push a main con runtime/herramientas/dependencias fijados, actions por referencia inmutable, permisos mínimos, timeout y configuración efímera. Verificar validación del workflow y que no usa credenciales de producción ni GPU (CI-01).
- [x] 6.2 Conectar lint/tipos, pruebas técnicas frontend/backend, validadores de HTTP/eventos/dataset y `openspec validate --all --strict --no-interactive`, usando los mismos comandos locales. Verificar que suites vacías o pasos obligatorios omitidos no producen éxito (CI-01).
- [x] 6.3 Integrar builds, migraciones e integración Compose con nombre por ejecución; adjuntar reportes/versiones/logs sanitizados y limpieza always. Verificar ejecución exitosa y fallo por timeout, con conservación de artefactos y sin recursos residuales ni secretos (CI-01–02).
- [x] 6.4 Ensayar en copia desechable cuatro regresiones independientes: fixture de evento inválido, referencia HTTP rota, migración fallida y readiness fallido. Verificar fallo global en cada caso y restaurar la copia; documentar reproducción de controles en `docs/TESTING.md` (CI-01–02).

## 7. Aceptación integrada y preparación del cierre

- [x] 7.1 Repetir secuencia completa desde checkout limpio con volúmenes nuevos y configuración local; verificar página, cuatro APIs saludables, migraciones, contratos, inventario y pruebas de aislamiento/persistencia, sin ejecutar negocio ni entrenamiento (ENV-01–04, CTR-01–04, MIG-01–03, DATA-01–03).
- [x] 7.2 Guardar nueva evidencia fechada en `docs/evidence/` con revisión o hashes de trabajo sin commit, entorno, comandos, códigos de salida, versiones, duración y matriz requisito → prueba → resultado → artefacto. Verificar todos los requisitos de los deltas y dejar explícitos RF no verificados, métricas no medidas y pendientes de los incrementos 1–5; preservar la auditoría existente (CI-03).
- [ ] 7.3 Verificar CI de aplicación en ejecución real cuando haya revisión publicada, conservando enlace o ID de ejecución; mientras solo se reproduzca localmente, registrar «workflow remoto no ejecutado» sin dar CI remota por aprobada. No publicar ni hacer push como efecto implícito de esta tarea (CI-01–03).
- [x] 7.4 Revisar coherencia final entre contratos, ADR/C4, docs, deltas y evidencia; ejecutar validación estricta OpenSpec. Verificar que ninguna función prevista se describe como terminada y que solo se prepara sincronización/archivo después de completar pruebas y resolver pendientes de aceptación; esta propuesta no se archiva durante la planificación (CI-03).

Evidencia del grupo 7: `docs/evidence/INCREMENTO-0-GRUPO-7.md`. 7.3 pendiente: Application CI falló en ejecución 36743640034 sobre b48d9cd, publicado por el usuario tras autorización explícita. Evidencia: `docs/evidence/INCREMENTO-0-GRUPO-7-REMOTO.md`. No se sincroniza ni archiva.
