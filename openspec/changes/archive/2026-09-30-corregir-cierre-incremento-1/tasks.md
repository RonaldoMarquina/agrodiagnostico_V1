# Tasks

## 1. Correcciones de seguridad e integración

- [x] 1.1 Implementar claves persistentes y montaje Identity; comprobar preparación repetida, pareja correcta y configuración Compose; documentar operación.
- [x] 1.2 Corregir Origin, CSRF de sesión, respuestas login/logout, cookies de error y correlación; agregar regresiones positivas/negativas y actualizar contratos pertinentes.
- [x] 1.3 Añadir migración/auditoría normativa sin alterar filas históricas; probar eventos, correlación, atomicidad e inmutabilidad; registrar ADR correctivo.

## 2. Verificación y cierre

- [x] 2.1 Hacer seguras las pruebas existentes y añadir aceptación de procesos separados PostgreSQL/Nginx desechables; verificar concurrencia, revocaciones y migración con datos heredados.
- [x] 2.2 Integrar chequeos en CI y ejecutar pruebas pertinentes, contratos, lint y OpenSpec; registrar evidencia reproducible y corregir estado documental.
- [x] 2.3 Sincronizar deltas y archivar el correctivo con las skills instaladas una vez verificadas todas las tareas, conservando el archivo histórico y plan del incremento 2.
