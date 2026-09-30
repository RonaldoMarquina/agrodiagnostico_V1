# Contribuir a AgroDiagnóstico V1

## Orden de trabajo

1. Revisa `AGENTS.md`, `README.md` y el incremento actual descrito en `docs/DEVELOPMENT.md`.
2. Consulta `openspec/specs/` y crea o continúa un cambio en `openspec/changes/` para comportamiento nuevo. Documenta el motivo, deltas, diseño cuando aplique y tareas con forma de verificación.
3. Fija primero el contrato en `contracts/openapi/` o `contracts/events/` cuando afecte a otros componentes.
4. Implementa el mínimo coherente del incremento, incluida la migración de cada servicio dueño de datos.
5. Ejecuta las pruebas relevantes, comprueba permisos y fallos, y guarda evidencia con entorno, commit y resultado.
6. Revisa el cambio, actualiza documentos/diagramas y archiva en OpenSpec después de comprobar que la implementación coincide.

No se da por completada una tarea solo por crear su carpeta. No mezcles funciones opcionales con los servicios obligatorios.

## Convenciones

- Mantén nombres estables de servicios, estados y eventos. Versiona cambios incompatibles y registra ADR.
- No hagas joins entre bases o esquemas de distintos servicios. Cada servicio gestiona sus migraciones Alembic.
- Incluye `correlation_id` en llamadas y eventos; usa UTC y evita secretos o fotos en logs y repositorio.
- Da mensajes legibles al usuario y códigos de error estables para el cliente.
- Para datos y modelos, registra fuente, licencia, partición, versión y métricas; no subas imágenes privadas ni pesos grandes al repositorio sin una decisión explícita de almacenamiento.
- Mantén el archivo `.env.example` sin credenciales reales. Nunca subas `.env`, claves, tokens o certificados privados.

## Revisión propuesta

Cada solicitud de cambio debe indicar: alcance e IDs de requisitos, contrato alterado, migraciones, pruebas y resultado, riesgos de seguridad y efecto en despliegue o documentación. Si modifica datos del modelo, adjunta manifiesto y reporte de evaluación; si toca la red pública, adjunta comprobaciones de TLS y caché.

Prioriza correcciones que preserven el flujo principal y el aislamiento entre usuarios. Las extensiones opcionales se estudian después de las evidencias de cierre de V1.
