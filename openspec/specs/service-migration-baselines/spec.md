# service-migration-baselines Specification

## Purpose

Permitir inicializar y verificar la persistencia de cada servicio de forma independiente, sin anticipar tablas de dominio ni compartir permisos entre servicios.

## Requirements

### Requirement: MIG-01 Base migrable independiente
Identity, Diagnosis, AI Inference y Notification SHALL disponer de historial de migraciones independiente, revisión base identificable y comando reproducible de upgrade. El Incremento 0 SHALL limitar la base a metadatos de migración sin usuarios, diagnósticos, inferencias, avisos ni semillas clínicas. Las revisiones de negocio SHALL añadirse en sus incrementos sin reescribir la base ya aplicada.

#### Scenario: Base vacía y segunda ejecución
- **WHEN** se aplica upgrade a cada base vacía y se repite la misma operación
- **THEN** cada servicio queda en su head esperado, la segunda ejecución no introduce cambios y no existen tablas de otro dominio ni datos de negocio ficticios.

#### Scenario: Reversibilidad de la revisión inicial
- **WHEN** se baja a base y se vuelve a aplicar head en bases desechables
- **THEN** se obtiene el mismo estado estructural; la prueba no requiere ni borra bases existentes del desarrollador.

### Requirement: MIG-02 Aislamiento efectivo de credenciales
Cada servicio SHALL conectar únicamente a su base mediante credencial propia sin privilegios de superusuario, creación de bases o roles. La inicialización privilegiada SHALL ejecutarse separadamente. Las migraciones SHALL operar solo sobre la base de su propietario.

#### Scenario: Matriz de acceso
- **WHEN** cada una de las cuatro credenciales intenta migrar su base y conectar o leer en las otras tres
- **THEN** las cuatro operaciones propias funcionan y los doce accesos cruzados son denegados, sin recurrir a convenciones de nombres como único aislamiento.

### Requirement: MIG-03 Fallos de migración visibles
El entorno SHALL impedir declarar listo un servicio cuyo esquema no corresponda a la revisión esperada o cuya migración falle; SHALL mantener un error operativo sin credenciales y permitir repetir la migración corregida.

#### Scenario: Revisión ausente o credencial inválida
- **WHEN** se inicia un servicio sobre una base sin migrar o se ejecuta una migración con credencial inválida
- **THEN** el servicio no está ready o el comando termina distinto de cero respectivamente; no se crea automáticamente un esquema alternativo ni se informa éxito.
