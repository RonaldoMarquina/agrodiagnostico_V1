## MODIFIED Requirements

### Requirement: Navegación controlada y registro cerrado de intenciones
El sistema SHALL mantener un registro cerrado `intent -> target -> roles -> availability` y emitir acciones `{"type": "NAVIGATE", "target": "<TARGET>"}` únicamente cuando la salida del proveedor valide contra el esquema interno cerrado, corresponda a un intent de navegación habilitado y el usuario tenga autorización efectiva. Navegar SHALL NOT ejecutar mutaciones ni operaciones de negocio (como crear diagnósticos, modificar perfil o alterar catálogo). Con las capacidades backend de auditoría y monitoreo publicadas, los destinos administrativos `OPEN_AUDIT -> AUDIT` y `OPEN_MONITORING -> MONITORING` SHALL permanecer habilitados exclusivamente para el rol `ADMIN`, mientras cualquier destino marcado como no disponible o diferido en el registro SHALL continuar sin emitir acciones ejecutables (`action = null`).

#### Scenario: Navegación autorizada para usuario estándar
- **WHEN** un usuario autenticado con rol `USER` envía «Llévame a mi historial», «Quiero hacer un nuevo diagnóstico» o «Quiero modificar mi perfil»
- **THEN** el sistema responde `200` con `status = "SUCCESS"`, el intent normalizado correspondiente (`OPEN_HISTORY`, `OPEN_NEW_DIAGNOSIS` o `OPEN_PROFILE`) y `action = {"type": "NAVIGATE", "target": "<TARGET>"}`, sin crear diagnósticos ni modificar datos

#### Scenario: Navegación administrativa autorizada para ADMIN sobre recurso disponible
- **WHEN** un usuario autenticado con rol `ADMIN` solicita gestión de usuarios, catálogo fitosanitario, recomendaciones o supervisión de diagnósticos
- **THEN** el sistema responde `200` con `status = "SUCCESS"`, el intent administrativo normalizado y el target autorizado correspondiente

#### Scenario: Navegación administrativa de auditoría y monitoreo habilitada para ADMIN
- **WHEN** un usuario autenticado con rol `ADMIN` solicita abrir auditoría («Abre auditoría») o monitoreo operativo («Muéstrame el estado del sistema»)
- **THEN** el sistema responde `200` con `status = "SUCCESS"`, el intent `OPEN_AUDIT` o `OPEN_MONITORING` y `action = {"type": "NAVIGATE", "target": "AUDIT"}` o `{"type": "NAVIGATE", "target": "MONITORING"}`, manteniendo `403` si un usuario con rol `USER` solicita cualquiera de esos intents

#### Scenario: Destino administrativo diferido o no disponible
- **WHEN** el registro marca algún destino como no disponible en tiempo de ejecución o configuración
- **THEN** el sistema no emite ninguna acción ejecutable (`action = null`) y devuelve una respuesta segura indicando indisponibilidad o ausencia del destino

#### Scenario: Solicitud ambigua o salida inválida del proveedor
- **WHEN** el mensaje del usuario es ambiguo o el proveedor devuelve un intent desconocido, una URL externa, SQL, múltiples acciones incompatibles o un JSON malformado
- **THEN** ante ambigüedad responde `200` con `status = "CLARIFICATION_REQUIRED"` y `action = null`, y ante salida inválida del proveedor rechaza la salida con `503` seguro y sin acción ejecutable
