# internal-diagnosis-work-leases Specification

## Purpose

Controlar acceso interno y trabajo exclusivo mediante identidad de servicio y leases temporales, preservando estados terminales y recuperación tras caída del worker.

## Requirements

### Requirement: Identidad verificada y frontera interna
Claim, renovación e imagen interna SHALL exigir principal ai_inference e instancia autenticados mediante credencial de servicio independiente de Identity. Lease y UUID no SHALL autorizar solos. La identidad verificada SHALL determinar lease_owner. Nginx SHALL ocultar todas las rutas internas.

#### Scenario: Credencial ausente o falsa
- **WHEN** falta JWT interno o tiene firma, kid, instancia, issuer, audience o fechas inválidas
- **THEN** devuelve 401 sin mutar estado ni entregar bytes

#### Scenario: Usuario en ruta interna
- **WHEN** un USER o ADMIN presenta JWT de usuario válido
- **THEN** devuelve 403; no se usa como identidad de worker

#### Scenario: Frontera proxy
- **WHEN** se solicita /internal por Nginx
- **THEN** responde 404 aun con credencial interna

#### Scenario: Separación inversa
- **WHEN** JWT interno accede a una ruta privada de usuario
- **THEN** no obtiene autoridad de usuario

### Requirement: Reclamo exclusivo y cancelación
Claim SHALL cambiar atómicamente PENDIENTE a PROCESANDO con nuevo lease_token y owner. Solo SHALL recuperar PROCESANDO vencido, fuera de la espera mínima y dentro del presupuesto. Lease vigente o terminal SHALL responder 409 DIAGNOSIS_NOT_CLAIMABLE; inexistente 404 NOT_FOUND.

#### Scenario: Claim contra cancelación
- **WHEN** claim y cancelación compiten simultáneamente
- **THEN** solo una transición gana; CANCELADO no genera Finished ni se reclama

#### Scenario: Dos workers
- **WHEN** dos instancias reclaman simultáneamente
- **THEN** solo una obtiene lease y consume intento

#### Scenario: Reclamo terminal
- **WHEN** se intenta reclamar cualquier terminal
- **THEN** se conserva el terminal y responde 409 con details field=status y code=TERMINAL; un conflicto transitorio no incluye esa señal

### Requirement: Renovación e imagen con fencing
Renovación e imagen SHALL comprobar PROCESANDO, owner/token actuales y tiempo de DB estrictamente menor que expires_at. Renovación no SHALL superar deadline de procesamiento ni cambiar token. La imagen SHALL entregarse como bytes privados no-store; el tombstone no cancela trabajo interno válido.

#### Scenario: Frontera
- **WHEN** now es igual a expires_at
- **THEN** renovación e imagen devuelven 409 STALE_LEASE

#### Scenario: Otro worker
- **WHEN** una instancia usa el token de otra
- **THEN** recibe 409 sin bytes ni renovación

#### Scenario: Generación antigua
- **WHEN** un worker presenta un token sustituido
- **THEN** se rechaza sin prolongar ni modificar la generación nueva

#### Scenario: Tombstone
- **WHEN** el propietario borra lógicamente durante trabajo con lease válido
- **THEN** las rutas de usuario responden 404 y el trabajo interno puede terminar sin hacer visible el recurso

### Requirement: Recuperación acotada y reloj de autoridad
Diagnosis SHALL contar como máximo tres generaciones de ejecución, con esperas y deadline documentados/configurables. Reintentos de entrega no SHALL incrementar ese contador. Un recuperador SHALL señalizar una vez por generación vencida o finalizar FALLIDO/PROCESSING_TIMEOUT al agotar presupuesto/deadline, atómicamente con Finished.

#### Scenario: Worker muerto
- **WHEN** un worker muere y vence su primer lease
- **THEN** se permite una nueva generación tras la espera, sin revertir a PENDIENTE

#### Scenario: Presupuesto agotado
- **WHEN** vence el tercer lease sin resultado o se alcanza deadline
- **THEN** se confirma FALLIDO y exactamente un Finished lógico

#### Scenario: Sin primer claim
- **WHEN** el broker permanece caído y la solicitud nunca fue reclamada
- **THEN** no se aplica el deadline de procesamiento a ese PENDIENTE

#### Scenario: Resultado tardío
- **WHEN** llega Analyzed con token vencido o tras terminal
- **THEN** se ignora y audita sin cambiar resultado ni emitir Finished adicional

#### Scenario: Señal de recuperación sin consumir
- **WHEN** ya se emitió una señal para un lease vencido y se alcanza el deadline sin nuevo reclamo
- **THEN** el recuperador confirma FALLIDO/PROCESSING_TIMEOUT y un solo Finished, sin omitir el deadline por la señal previa
