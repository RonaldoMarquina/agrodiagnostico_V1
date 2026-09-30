# integrated-development-environment Specification

## Purpose

Proporcionar un entorno local integrado y repetible para comprobar conectividad, salud y aislamiento antes de implementar funciones de AgroDiagnóstico.

## Requirements

### Requirement: ENV-01 Arranque integrado conservando la base existente
El entorno SHALL iniciar frontend mínimo, Identity, Diagnosis, AI Inference, Notification, PostgreSQL, RabbitMQ, Redis, almacenamiento S3 y Nginx mediante Docker Compose y configuración local documentada. SHALL conservar estructura y auditoría existentes, funcionar en CPU y no requerir GPU, pesos, correo, Cloudflare ni servicios opcionales.

#### Scenario: Entorno limpio
- **WHEN** se prepara configuración local según documentación y se construye e inicia el proyecto con volúmenes nuevos
- **THEN** los servicios persistentes alcanzan estado saludable dentro del timeout documentado, los inicializadores terminan con código 0 y Nginx entrega una página que identifica el entorno técnico sin afirmar diagnóstico disponible.

#### Scenario: Configuración incompleta
- **WHEN** falta una variable obligatoria para conectar un servicio
- **THEN** el arranque falla con el nombre de la variable y código distinto de cero sin mostrar valores secretos ni usar credenciales implícitas de producción.

### Requirement: ENV-02 Salud comprobable y degradación explícita
Cada API SHALL ofrecer internamente `/health/live` y `/health/ready`. Liveness SHALL indicar proceso activo con 200; readiness SHALL devolver 200 solo con configuración, migración base y dependencias indispensables disponibles, y 503 en caso contrario. Las respuestas SHALL omitir secretos y detalles internos sensibles. Redis y correo SHALL NOT condicionar la disponibilidad de Diagnosis.

#### Scenario: Base propia indisponible
- **WHEN** se interrumpe la conexión a la base del servicio después de arrancar
- **THEN** su readiness devuelve 503 dentro del límite de sondeo documentado mientras liveness continúa en 200 si el proceso sigue activo; al restaurar la base recupera readiness sin borrar datos.

#### Scenario: Caché indisponible
- **WHEN** Redis deja de responder
- **THEN** Diagnosis conserva readiness si sus dependencias indispensables funcionan; la evidencia no atribuye a esta prueba un fallback de catálogo aún no implementado.

### Requirement: ENV-03 Frontera local y objetos privados
El perfil integrado SHALL publicar únicamente Nginx en loopback; bases, broker, caché, APIs, consolas S3 y objetos SHALL carecer de puertos publicados. Nginx SHALL rechazar `/internal/*` y no exponer AI Inference. Los objetos SHALL ser privados y las credenciales de inicialización SHALL estar separadas de las de aplicación. La configuración local SHALL NOT presentarse como despliegue público seguro ya completado.

#### Scenario: Inspección y acceso anónimo
- **WHEN** se inspeccionan puertos efectivos y se intenta acceder por Nginx a rutas internas o por S3 sin credenciales a un objeto de prueba existente
- **THEN** solo Nginx está publicado, la ruta interna responde 404 y el acceso anónimo al objeto es denegado sin entregar bytes.

### Requirement: ENV-04 Persistencia reproducible
PostgreSQL, RabbitMQ y objetos SHALL conservar datos en volúmenes propios al detener y volver a crear contenedores sin eliminación de volúmenes. Las pruebas SHALL usar identificadores y recursos sintéticos aislados y no borrar recursos ajenos.

#### Scenario: Recreación con datos técnicos
- **WHEN** se guarda una fila técnica, un mensaje persistente en cola durable de prueba y un objeto privado sintético, y se ejecuta parada y recreación sin borrar volúmenes
- **THEN** los tres datos se recuperan y sus contenidos coinciden; la limpieza solo elimina los recursos identificados como pertenecientes a la prueba.
