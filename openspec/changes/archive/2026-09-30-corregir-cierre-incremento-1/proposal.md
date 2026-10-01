# Proposal

## Why

La revisión del incremento 1 archivado detectó configuración JWT ausente, Origin/CSRF insuficientes, auditoría incompleta y evidencia multi-instancia que no probaba procesos independientes. Es necesario corregir la implementación antes del incremento 2 sin reescribir su archivo histórico.

## What Changes

- Secretos Ed25519 persistentes preparados e inyectados en Identity.
- Origin exacto y CSRF ligado criptográficamente a la sesión; respuestas login/logout y correlación conformes a specs.
- Auditoría con actor, destino, acción y correlación, eventos normativos y migración conservadora.
- Pruebas de regresión y aceptación con procesos separados, PostgreSQL y proxy aislados, sin eliminar datos de desarrollo.
- Rectificación documental de la evidencia histórica y contratos afectados.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `user-authentication-and-sessions`: precisar comparación de Origin y vínculo CSRF con sesión.
- `role-authorization-and-user-administration`: precisar conservación de auditoría histórica incompleta durante migración correctiva.

## Impact

Identity, migración 0003, preparación local/Compose, contratos/escenarios, pruebas/CI y documentación. Sin implementación de Diagnosis ni cambios al plan del incremento 2.
