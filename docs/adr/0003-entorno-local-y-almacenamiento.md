# ADR-0003 — Entorno técnico local y almacenamiento S3

Fecha: 2026-09-29. Alcance: grupo4 de Incremento0; no despliegue productivo.

## Decisión

Se integra el perfil principal con cuatro APIs FastAPI de salud, React/TypeScript compilado y servido por Nginx, PostgreSQL, RabbitMQ, Redis y almacenamiento S3. Nginx es la única entrada publicada en127.0.0.1. Red application interna conecta proxy/APIs; persistence interna conecta servicios y dependencias. Una tercera red edge, exclusiva de Nginx, permite publicar su puerto loopback; ninguna API se conecta a edge. Bootstrap de bases/objetos son jobs separados con credenciales propias de inicialización. APIs usan UID/GID local y únicamente su secreto de base; Diagnosis recibe además su credencial S3.

Readiness sigue D2 del cambio: base propia en head en los cuatro servicios; Diagnosis requiere acceso autorizado al bucket. Redis y broker se verifican aparte; su caída no revierte diagnósticos ni simula fallback ya implementado. La salud de AI no acredita worker, GPU o modelo. Tiempo de arranque aceptado:180s después del build; las sondas tienen límites explícitos.

Las rutas de negocio permanecen contract-only. Nginx devuelve404 JSON y no-store en API, y404 para salud interna, /internal y AI. No se publica interfaz administrativa de dependencias. La página identifica «Entorno técnico» sin carga ni resultados clínicos.

## Selección S3 y procedencia

El diseño D1 permite una alternativa S3 compatible si MinIO no resulta viable. La [fuente oficial de MinIO](https://github.com/minio/minio) declara repositorio archivado y ausencia de mantenimiento; [licencia](https://github.com/minio/minio/blob/master/LICENSE) AGPLv3 y distribución comunitaria actual basada en fuente. Se descarta iniciar esta base con binarios históricos sin mantenimiento.

Se adopta **SeaweedFS4.17**, imagen `chrislusf/seaweedfs`, distribuida por el proyecto y fijada al digest comprobado en Compose. [Repositorio y referencia Docker](https://github.com/seaweedfs/seaweedfs), [licencia Apache-2.0](https://github.com/seaweedfs/seaweedfs/blob/master/LICENSE), [API S3 y autenticación](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API). Consulta2026-09-29. Esto registra procedencia/licencia, no certifica cumplimiento productivo ni ausencia de vulnerabilidades.

El servidor guarda volúmenes y metadatos en/data, con imagen y volumen separados del código. Solo el puerto S3 escucha en la red de Docker: filer/master/volume quedan ligados a loopback dentro del contenedor para evitar acceso sin autenticación por interfaces alternativas. Configuración sin identidad anónima. Admin inicializa; Diagnosis recibe Read/Write/List solo para el bucket; AI Read/List del mismo bucket, sin escritura. La futura autorización por objeto y lease sigue pendiente del incremento3.

El inicializador crea bucket privado si falta y conserva el existente. La aceptación debe comprobar upload/read sintético, denegación anónima, denegación de escritura AI y persistencia con checksum tras recreación. Ninguna imagen de usuario ni dataset entra en estas pruebas.

## Alternativas y consecuencias

- Mantener MinIO histórico: descartado por mantenimiento; no se adopta producto comercial como dependencia local.
- Almacenamiento falso en memoria: descartado porque no demuestra API S3 ni persistencia/privacidad reales.
- Acceso directo a filer sin autorización: descartado; interfaces alternativas solo loopback.
- APIs de negocio provisionales: descartadas; devolver éxito simulado confundiría la base técnica con producto.

SeaweedFS agrega configuración propia de credenciales; sus garantías productivas y elección de proveedor se revisarán antes del despliegue público. HTTP local no satisface dominio, Cloudflare, TLS origen ni CDN. Las pruebas de broker usan una cola sintética durable y confirms, sin eventos de diagnóstico ni consumidores outbox/inbox.
