# Design

## Context

La revisión reprodujo Origin tolerante por hostname, CSRF double-submit sin vínculo, ausencia de USER_REGISTERED, 403 para bloqueados, logout inválido 204 y correlaciones distintas. Compose no monta claves. Tests multi-instancia reutilizan el mismo app y pueden borrar usuarios de una base configurada.

## Goals / Non-Goals

Corregir esos hallazgos y demostrar comportamiento en procesos separados. No implementar incremento 2 ni modificar estados de diagnóstico, algoritmos JWT o retención de sesiones.

## Decisions

- Preparar claves Ed25519 persistentes con OpenSSL, validar pareja existente y fallar ante configuración inconsistente; Compose monta ambos PEM solo en Identity. Preparador no imprime secretos.
- CSRF determinista HMAC-SHA256 con refresh como clave y etiqueta fija de dominio; ligado al secreto aleatorio de sesión, verificable entre instancias sin columna nueva. Comparación constante de cookie/cabecera/valor esperado. Requiere nuevo login a clientes con CSRF antiguo; refresh expirado/revocado sigue 401 y Origin incorrecto 403.
- Middleware único genera correlación; dependencias reutilizan request.state. Login bloqueado comparte 401 con credenciales incorrectas. Logout desconocido/expirado/revocado devuelve 401; cookies de error se limpian en la respuesta real.
- Migración 0003 aditiva para auditoría: actor_id, target_id, action, correlation_id y legacy. Filas anteriores quedan legacy=true sin UPDATE ni valores inventados; nuevos eventos legacy=false requieren acción/correlación. Mantener columnas históricas por compatibilidad, trigger append-only y helper único para eventos nuevos. No eliminar filas para probar.
- Procesos Docker independientes con PostgreSQL/Nginx desechables y nombres únicos. Claves/config compartidas, ningún estado Python compartido. Escenarios login A/refresh B/logout C, refresh concurrente, reuso, revocación por cambio/reset/bloqueo y auditoría/migraciones. El viejo test en memoria se etiqueta como tal y nunca accede a DB_HOST.
- Integrar unit tests en chequeo backend y aceptación en integración existente mediante invocación separada; contratos se validan además de pruebas runtime. Documentar evidencia nueva y rectificar resumen histórico sin modificar archivo OpenSpec original.

## Risks / Trade-offs

CSRF antiguo invalida clientes activos: renovar login tras despliegue. Auditoría histórica incompleta permanece identificada, no se puede reconstruir. Migración aditiva probada con datos heredados; rollback de esquema solo en entorno desechable. No se despliega ni migra automáticamente la base de desarrollo del usuario.
