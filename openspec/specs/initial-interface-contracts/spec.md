# initial-interface-contracts Specification

## Purpose

Establecer interfaces iniciales versionadas y validables, separando lo contratado para futuros incrementos de los endpoints técnicos ejecutables en el Incremento 0.

## Requirements

### Requirement: CTR-01 Contratos HTTP iniciales explícitos
Los contratos SHALL cubrir salud de los cuatro servicios y las rutas públicas iniciales de la tabla «HTTP público previsto» de `docs/API_CONTRACTS.md` para auth, perfil, diagnoses, notifications y notification-preferences; las operaciones adicionales de la tabla de reconciliación conservarán su incremento responsable. SHALL incluir reclamo, renovación de lease y acceso autorizado a imagen como operaciones internas o propias, fijando método, ruta y autorización antes de cualquier consumidor. SHALL definir UUID, UTC, correlation_id, errores comunes, paginación, carga multipart, límites, estados, idempotencia y seguridad por operación. Las rutas administrativas aún sin definición SHALL figurar en un inventario pendiente sin una ruta ficticia `/admin/...` ejecutable. La carga SHALL NOT exigir selección manual del cultivo (RF-07). El inventario SHALL conservar cambio y confirmación de recuperación de contraseña, feedback de utilidad y lectura de avisos como obligaciones previas a sus consumidores, aunque su contrato se complete en incrementos posteriores. Los formatos objetivo V1 SHALL incluir HEIC/HEIF, cuyo soporte solo se anunciará tras conversor y prueba E2E; los límites iniciales no se declararán validados para producción.

#### Scenario: Validación y ejemplos
- **WHEN** se validan documentos, referencias y ejemplos de cada operación contratada
- **THEN** no hay referencias rotas, identificadores de operación duplicados ni schemas vacíos usados para ocultar decisiones, y cada ejemplo válido satisface su esquema.

#### Scenario: Estado de implementación
- **WHEN** se consulta el inventario de operaciones y el entorno del Incremento 0
- **THEN** solo salud y página técnica se declaran implementadas; las operaciones de negocio se identifican como previstas y no devuelven éxitos simulados.

#### Scenario: Fuente reconciliada sin pérdida de alcance
- **WHEN** se revisa el inventario frente a RF-03, RF-04, RF-07, RF-20 y las secciones 6.5.2 y 9.12 del DOCX identificado en la reconciliación
- **THEN** las operaciones omitidas tienen responsable e incremento previo al consumidor, la carga no exige cultivo y HEIC/HEIF conserva su aceptación pendiente de conversión y E2E sin afirmar soporte implementado.

### Requirement: CTR-02 Semántica de acceso y reintentos documentada
Los contratos SHALL exigir autenticación para recursos propios, 404 genérico para recursos ajenos o inexistentes, ADMIN para administración e identidad de servicio para operaciones internas. SHALL especificar 202 de carga válida, rechazo de carga inválida, cancelación pendiente con 200 y conflicto 409 después del reclamo. SHALL asociar Idempotency-Key al propietario y operación, definir retención y devolver conflicto al reutilizarla con contenido distinto. SHALL definir el ciclo de cookie de refresh, protección CSRF aplicable y revocación sin fijar secretos ni expiraciones de producción arbitrarias.

#### Scenario: Matriz negativa del contrato
- **WHEN** se revisan los casos de usuario anónimo, recurso ajeno, carga excesiva, tipo no admitido, cancelación tardía y clave reutilizada con contenido distinto
- **THEN** existen respuestas y ejemplos inequívocos para 401, 404, 413, 415 y 409 según el caso; estas pruebas de esquema no se cuentan como autorización funcional implementada.

### Requirement: CTR-03 Eventos versionados y responsabilidades estables
Los contratos SHALL definir DiagnosisRequested v1, DiagnosisAnalyzed v1 y DiagnosisFinished v1 con envelope event_id, event_type, schema_version, occurred_at, correlation_id y payload, y los campos mínimos de `docs/API_CONTRACTS.md`. SHALL distinguir análisis técnico de decisión publicable; NO_CONCLUYENTE SHALL ser estado con motivo y no clase. DiagnosisFinished SHALL admitir únicamente COMPLETADO, NO_CONCLUYENTE y FALLIDO. Los eventos SHALL excluir bytes de imagen, contraseñas, tokens de autenticación y enlaces firmados. El lease_token requerido SHALL ser un identificador opaco de concurrencia sin autoridad de autenticación por sí mismo.

#### Scenario: Ejemplos válidos e inválidos
- **WHEN** se validan fixtures positivos de los tres eventos y variantes sin campos obligatorios, con versión no soportada, estado CANCELADO en Finished, clase NO_CONCLUYENTE o campos prohibidos
- **THEN** los positivos pasan y todos los negativos son rechazados con causa trazable; el contrato no incluye tratamientos ni recomendaciones generadas por AI.

### Requirement: CTR-04 Compatibilidad y garantías de entrega especificadas
Los contratos SHALL registrar emisor, consumidor, routing, compatibilidad, deduplicación por consumidor/event_id, confirmación de publicación, ACK tras commit y aislamiento de versiones desconocidas. SHALL preservar la transacción diagnóstico/outbox, el rechazo de lease obsoleto y terminales irreversibles como obligaciones de los incrementos que implementen el flujo. Cambios incompatibles SHALL requerir nueva versión y decisión registrada.

#### Scenario: Revisión de interfaz sin consumidores de negocio
- **WHEN** se entrega el paquete inicial de contratos
- **THEN** la matriz de productores y consumidores y los casos de duplicado/lease obsoleto están definidos, pero ninguna validación estática se declara prueba de entrega, idempotencia o transición en ejecución.
