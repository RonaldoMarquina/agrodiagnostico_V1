# Despliegue, dominio, HTTPS y CDN

## Requisitos obligatorios

En la entrega pública: dominio real bajo DNS de Cloudflare, proxy activado para la aplicación, HTTPS para usuarios, TLS desde Cloudflare hasta el origen con modo **Full (strict)**, CDN verificable para assets estáticos y controles de caché para recursos privados. El servidor de origen necesita un certificado vigente aceptado por Full (strict), emitido por una CA pública o Cloudflare Origin CA. Elige proveedor de hosting, correo y almacenamiento definitivo mediante ADR de costo y operación; no hay un dominio ni servidor contratados todavía.

## Topología

```text
Navegador ─HTTPS→ Cloudflare (DNS, proxy, CDN) ─HTTPS→ Nginx
                                                   ├─ frontend estático
                                                   └─ /api/v1/* → servicios internos

Red interna: PostgreSQL · RabbitMQ · Redis · objetos privados · workers
```

Solo el punto de entrada previsto debe ser público. Restringe puertos de bases, broker, dashboards y APIs internas mediante red y firewall. Protege acceso de operador a métricas y paneles. Mantén separados los secretos de producción y desarrollo.

## TLS y redirecciones

1. Configura DNS y proxy de Cloudflare para el nombre del servicio.
2. Instala en Nginx del origen un certificado vigente cuyo nombre cubra el hostname; verifica cadena según el tipo de certificado.
3. Configura Full (strict) y prueba la conexión efectiva al origen; activa redirección HTTP → HTTPS para visitantes sin crear bucles.
4. Verifica validez, renovación y alertas del certificado antes de la presentación; documenta responsable y procedimiento de renovación.

Full (strict) requiere TLS válido también en el tramo Cloudflare → origen. Un certificado Origin CA sirve a ese tramo con proxy activo, pero el acceso directo de un navegador al origen puede no confiar en esa CA; elige y prueba la opción de despliegue real.

## CDN y privacidad

| Rutas o contenido | Política pretendida |
| --- | --- |
| `/assets/*` con nombres versionados/hash | Elegible para CDN; cabecera `Cache-Control: public, max-age=31536000, immutable` si el asset es inmutable |
| HTML de entrada (`/`) | Actualización controlada; no aplicar caché inmutable de assets |
| `/api/v1/*`, login, sesiones, perfil, historial y resultados | Regla explícita **Bypass cache** y `Cache-Control: private, no-store` donde corresponda |
| `/internal/*`, imágenes privadas, URL firmadas y dashboards | Sin caché compartida; acceso interno o autorización por propietario |

Revisa el orden de Cache Rules para que una regla amplia de estáticos no anule el bypass de privados. Las cabeceras del origen y las reglas de Cloudflare deben ser coherentes. Comprueba `CF-Cache-Status` en un asset versionado tras solicitudes repetidas y verifica bypass/ausencia de almacenamiento para recursos privados mediante configuración, cabeceras y prueba de dos sesiones. Un estado `DYNAMIC` puede ser correcto para API; no exijas literalmente `BYPASS` en todas las respuestas.

## Publicación y recuperación

- CI fija dependencias, ejecuta lint/pruebas, valida contratos y migraciones, construye imágenes y registra commit y versión de modelo.
- Aplica migraciones por servicio antes de habilitar la nueva versión; prepara reversión o recuperación cuando no sean reversibles.
- Health checks `/health/live` y `/health/ready` comprueban dependencias indispensables; la caída tolerable de Redis o correo no apaga el diagnóstico.
- Configura backup de PostgreSQL y objetos, cifra cuando corresponda y ensaya restauración con datos conocidos.
- Publica métricas de error, p95, profundidad/edad de cola, outbox, DLQ, inferencia y abstenciones; enlaza trazas con `correlation_id`.
- Guarda evidencia de CF-01 a CF-06 descrita en [TESTING.md](TESTING.md). No presentes un certificado o un cache hit hipotético como prueba realizada.

## Decisiones pendientes antes de producción

| Decisión | Criterio de cierre |
| --- | --- |
| Dominio y hosting | Compra, costo, acceso administrativo, disponibilidad y DNS verificables |
| Certificado del origen | Compatibilidad Full (strict), renovación y prueba de fallo |
| Proveedor de objetos y correo | Precio, permisos, privacidad, límites y pruebas de degradación |
| Política de retención y backup | Plazos aprobados, restauración medida y acceso restringido |
| Carga soportada | Ensayo reproducible con modelo real y presupuesto de recursos |

Esas decisiones se documentan en ADR y configuración de infraestructura cuando se tomen.
