# Pruebas y evidencias

## Regla de aceptación

Cada requisito RF-01 a RF-28 debe vincularse a caso positivo, negativo y prueba de autorización cuando exponga datos. Guarda matriz `RF → contrato/evento → prueba → resultado → evidencia`. La meta de desempeño no equivale a una medición. Registra commit, hardware, red, modelo, versión de datos, tamaño de imagen, concurrencia y duración en cada prueba de carga.

## Casos de extremo a extremo y resiliencia

| ID | Acción | Resultado exigido |
| --- | --- | --- |
| T-01 | A carga JPEG válido; B consulta ID/imagen de A | `202` y transiciones hasta terminal; B obtiene 404 |
| T-02 | Reenvío tras timeout con misma `Idempotency-Key` | Mismo `diagnosis_id`; una fila y resultado |
| T-03 | Carga falsa `.jpg`, corrupta o excesiva | 4xx legible y ningún `DiagnosisRequested` |
| T-04 | Cancelación en carrera con reclamo | Gana una transición; `CANCELADO` no infiere |
| T-05 | Matar worker tras reclamar | Lease vencido permite recuperación; un resultado o `FALLIDO` trazable |
| T-06 | Caer RabbitMQ tras commit de solicitud | Outbox conserva y entrega al volver; no se pierde diagnóstico |
| T-07 | Duplicar `DiagnosisAnalyzed` y caer publicador tras envío | Resultado/evento final únicos y aviso idempotente |
| T-08 | Caer Redis y proveedor de correo | Catálogo responde de PostgreSQL; diagnóstico termina; correo se reintenta aparte |
| T-09 | Imagen de cultivo ajeno o score bajo | `NO_CONCLUYENTE` con motivo y recaptura; sin recomendación específica |
| T-10 | ADMIN cambia recomendación | Nuevo resultado usa versión nueva; historial conserva anterior y auditoría |
| T-11 | Ejecutar modelo real sobre test sellado y externo si existe | Reporte por clase, confusión, calibración, abstención y latencia |
| T-12 | Restaurar backup y migrar entorno limpio | Usuario, diagnóstico, imagen referenciada y catálogo coherentes |

Antes del incremento 4, T-01 puede comprobar la integración con worker provisional siempre que la evidencia indique claramente que el resultado es simulado. El cierre exige repetir el flujo con modelo real validado.

## Métricas de rendimiento propuestas

| Métrica objetivo | Método |
| --- | --- |
| API síncrona p95 ≤ 500 ms | Historial, estado, catálogo y perfil; k6, 15 min de carga estable tras calentamiento |
| Registro de diagnóstico p95 ≤ 2 s | Desde recepción completa de imagen por API hasta `202` y ID; no incluye subida de red |
| Diagnóstico completo p95 ≤ 30 s | Desde commit `PENDIENTE` hasta estado terminal, separando cola/inferencia/persistencia |
| Escalamiento | Misma muestra con uno y dos workers; medir cola, throughput, CPU/RAM y errores |

Son metas iniciales, no cifras ya logradas. Define primero una carga reproducible acorde al entorno; 100, 500, 1000 y 5000 usuarios virtuales son escalones exploratorios, no capacidad garantizada. Si falla una meta, informa valor observado, condiciones, causa probable, ajuste y nueva medición.

## Evidencia de despliegue

| ID | Comprobación |
| --- | --- |
| CF-01 | Dominio real resuelve por Cloudflare y abre la aplicación |
| CF-02 | HTTP redirige a HTTPS y certificado del visitante es válido |
| CF-03 | Cloudflare usa Full (strict) y valida certificado vigente del origen |
| CF-04 | Asset versionado estático muestra cacheo comprobable, por ejemplo `CF-Cache-Status: HIT` tras solicitudes apropiadas |
| CF-05 | API, login, historial y fotografía privada evitan caché compartida; verificar regla y cabeceras, no depender solo de un valor de `CF-Cache-Status` |
| CF-06 | Servicios internos y paneles no son accesibles públicamente; ruta por Nginx y TLS comprobados |

Conserva capturas/cabeceras sin cookies ni tokens en `docs/evidence/`, junto con fecha, entorno y URL enmascarada si contiene datos personales. Consulta [DEPLOYMENT.md](DEPLOYMENT.md) para reglas de caché.

## Automatización y cierre

CI ejecuta lint, pruebas relevantes, validación de contratos, migraciones y build con versiones fijadas. El cierre requiere flujo funcional, cobertura real declarada por clase, permisos, recuperación ante fallos, backup/restore, métricas honestas, C4/ADR y evidencia de dominio/HTTPS/CDN. Gemini, voz, PWA y plagas no son puertas de cierre.

## Trazabilidad de la fuente recibida

La [matriz de reconciliación](reference/RECONCILIACION-V1.md) identifica los 28 RF con párrafo fuente, responsable, incremento y prueba prevista. No es evidencia de ejecución. Además de T-01…T-12, el cierre deberá cubrir cambio/recuperación de contraseña, cultivo automático sin selección previa, feedback autorizado sin entrenamiento automático y lectura de avisos. Para JPEG/PNG/WebP y HEIC/HEIF se exige carga, decodificación, normalización y procesamiento, además de negativos corruptos/falsos; HEIC/HEIF requiere conversor y E2E en contenedor antes de declarar soporte. Véase §9.12/10.9 del DOCX.


## Contratos iniciales disponibles — Incremento 0, grupo 2

Ejecutar desde la raíz `bash scripts/check_contracts.sh` con Python3.12. Crea entorno efímero, instala lock con hashes, valida cuatro documentos OpenAPI/referencias y ejemplos, y ejecuta pruebas positivas/negativas. No instala globalmente ni necesita servicios. Véanse [instrucciones](../contracts/README.md) y [evidencia](evidence/INCREMENTO-0-GRUPO-2.md).

La prueba de referencia rota modifica una copia temporal de contracts y exige salida1 del CLI, preservando originales. Los fixtures cubren UUID/UTC, payloads, salud200/503, errores, paginación, roles no asignables por registro, propiedades rechazadas, variantes de eventos, versiones desconocidas, secretos/binarios extra, CANCELADO no notificable, clase/cultivo y nulabilidad. Las matrices de cookies/CSRF/lease/idempotencia se revisan estáticamente y validan ejemplos; **no son pruebas de autorización, concurrencia, decodificación ni entrega ejecutadas**. Todos los casos HTTP declaran runtime_verified=false y los de entrega pending-runtime.

Al cerrar el grupo 2, migraciones, servicios y frontend seguían pendientes; sus pruebas posteriores se documentan debajo. El grupo 6 aporta CI reproducida localmente; el workflow remoto sigue sin ejecutarse.


## Persistencia — Incremento 0, grupo 3

`python3 scripts/check_persistence.py` comprueba PostgreSQL real sin publicar puertos, con secretos y volumen efímeros propios. Cubre cuatro accesos propios/doce rechazos cruzados, permisos de roles, ausencia de tablas de dominio, bootstrap repetido, upgrade/current/repetición/downgrade/upgrade, head ausente/desconocido, contraseña inválida, fallo SQL de migración con rollback, bloqueo de jobs dependientes y recuperación. Verifica heads persistidos tras recrear PostgreSQL antes de reaplicar migraciones y ausencia de secretos en salidas/logs. [Operación](PERSISTENCE.md) y [evidencia](evidence/INCREMENTO-0-GRUPO-3.md). No acredita todavía endpoints de salud HTTP ni dependencia S3.

Verificación independiente de los cuatro locks/imports desde entornos nuevos: `bash scripts/check_service_locks.sh`. Instala uv bloqueado en venv efímero y limpia solo sus entornos.


## Entorno integrado — Incremento0, grupo4

`python3 scripts/check_environment.py` usa secretos y proyecto Docker efímeros. Comprueba configuración ausente, build con lint/tipos/prueba de render, arranque acotado, salud200/503 y OpenAPI generado de las ocho operaciones técnicas; revisiones ausentes/incorrectas; caída/restauración PostgreSQL y S3, Redis no indispensable; puertos loopback, rutas rechazadas y no-store; S3 privado con AI solo lectura. Conserva head PostgreSQL, mensaje RabbitMQ durable confirmado y checksum de objeto al recrear contenedores, comprobándolos antes de repetir inicializadores/migraciones. Limpia solo su proyecto. [Evidencia](evidence/INCREMENTO-0-GRUPO-4.md).

Esta aceptación no implementa ni verifica diagnóstico, outbox/inbox, catálogo, entrenamiento o despliegue público. El esquema común y las19 operaciones de negocio siguen contract-only. Auditoría histórica del host y sus herramientas se conservan.

## Inventario — Incremento 0, grupo 5

`bash scripts/check_dataset.sh` valida fuentes, conteos trazables, taxonomía candidata alineada con contratos y CSV inicial. La suite comprueba siete clases/cuatro particiones sintéticas; campos ausentes o inválidos, licencia sin evidencia, cultivo incompatible, fuente pendiente, códigos duplicados/retirados, campos privados adicionales y rechazo de fixtures por el CLI real. Los seis pares de particiones se prueban por hash y por grupo (doce casos); el validador informa el conflicto y conserva los archivos intactos. Un grupo dentro de su partición puede repetirse.

No requiere datos reales, servicios ni GPU. Reutiliza el lock de validación de contratos en un venv temporal, sin instalaciones globales. Una suite vacía o manifiesto explícito vacío falla. El inventario inicial sin filas se identifica como tal, no como dataset listo. [Política y límites](../ml/manifests/README.md), [evidencia](evidence/INCREMENTO-0-GRUPO-5.md). La conexión a CI pertenece al grupo 6.

## CI de aplicación — Incremento 0, grupo 6

El workflow de aplicación y el ejecutor local comparten las etapas de `tooling/ci/plan.json`. Preparación: `bash scripts/prepare_ci.sh`; ejecución: `python3 scripts/run_ci.py`. Requiere runtimes fijados y Docker local; herramientas aisladas, sin dependencias globales nuevas. Se registra resultado global, versiones, hashes, códigos, duración y logs sanitizados; ninguna etapa omitida ni suite vacía produce éxito.

`python3 scripts/check_ci_regressions.py` crea copias desechables y ejecuta el pipeline completo tras introducir por separado un fixture de evento inválido, una referencia HTTP inexistente, una migración que falla o un host de DB inválido para readiness de Identity. Un quinto caso acorta el presupuesto del smoke para comprobar timeout 124. Cada ensayo exige fallo en su etapa prevista, código global no cero, conservación de reportes y limpieza del proyecto registrado; restaura los archivos de la copia antes de eliminarla. El árbol de trabajo original no se modifica.

[Procedimiento detallado y versiones](CI.md). Los tests de salud por servicio prueban fallo cerrado, recuperación y contrato técnico; la integración Compose comprueba las respuestas HTTP reales y migraciones. Las métricas ML, funciones de negocio y ejecución remota GitHub quedan fuera de esta prueba local.

Resultado del grupo 6: catorce etapas positivas y cinco regresiones verificadas, con limpieza y reportes conservados. [Evidencia](evidence/INCREMENTO-0-GRUPO-6.md). No se marca el cierre global del grupo 7.

## Aceptación integrada — grupo 7

Las 14 etapas se repitieron desde checkout temporal limpio con instalación nueva y volúmenes propios. [Procedencia, matriz y límites](evidence/INCREMENTO-0-GRUPO-7.md). CI remota aprobada en ejecución 36749372314; 7.3 verificada.

Historial de corrección: [primera ejecución fallida 36743640034](https://github.com/RonaldoMarquina/agrodiagnostico_V1/actions/runs/36743640034). [Evidencia](evidence/INCREMENTO-0-GRUPO-7-REMOTO.md).

La [tercera ejecución de Application CI](https://github.com/RonaldoMarquina/agrodiagnostico_V1/actions/runs/36749372314) aprobó la revisión `97472b1`; pasos y artefacto constan en [evidencia remota](evidence/INCREMENTO-0-GRUPO-7-REMOTO.md).
