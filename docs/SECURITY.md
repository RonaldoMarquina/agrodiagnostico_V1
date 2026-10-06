# Seguridad y privacidad

## Principios de acceso

Una cuenta autenticada es obligatoria para crear y leer diagnósticos. `USER` gestiona sus recursos; `ADMIN` dispone de rutas de supervisión auditadas y se provisiona por procedimiento controlado, nunca por registro público. Comprueba rol y propiedad en cada solicitud del backend: ocultar un botón no es autorización. Una consulta a diagnóstico o fotografía ajena devuelve 404 genérico.

## Identidad y sesión

- Hash de contraseñas con Argon2id; límites de intentos sensibles y recuperación mediante token temporal almacenado como hash.
- Access token firmado y breve; valida firma, issuer, audience, expiración, rol y estado de cuenta en los servicios autorizados.
- Refresh token rotativo y revocable, preferentemente en cookie `HttpOnly`, `Secure`, `SameSite` según flujo probado; protege contra CSRF cuando aplique.
- El bloqueo de cuenta invalida o impide el uso posterior de sesiones según la política implementada, con prueba de regresión.
- Evita mensajes de autenticación y recuperación que enumeren cuentas; mantén trazas operativas sin revelar credenciales.

La selección de algoritmo de firma (Ed25519/EdDSA), expiraciones (access 15 min, refresh 7 días), persistencia compartida de RefreshSession en PostgreSQL y rotación atómica con detección de reuso se define normativamente en [ADR-0004](adr/0004-seguridad-identidad-y-autorizacion.md).

### Ventana stateless de 15 minutos en servicios consumidores (Diagnosis)
Diagnosis valida los access tokens de forma completamente local y asimétrica con la clave pública Ed25519 de Identity (`JWT_PUBLIC_KEY_PATH`), sin realizar consultas a la base de datos de Identity ni verificar el estado de la sesión central en cada petición. Esto garantiza aislamiento total y alto rendimiento.
Como consecuencia de esta arquitectura desacoplada, existe una ventana stateless de 15 minutos (900 segundos): si un usuario es bloqueado o sus permisos son revocados en Identity, dicha revocación impide inmediatamente renovar el token vía refresh token o autenticarse en Identity, pero los access tokens emitidos previamente seguirán siendo técnicamente válidos en Diagnosis hasta que transcurra su tiempo de vida (máximo 15 minutos). No se utilizan listas negras ni sincronizaciones distribuidas síncronas entre Identity y Diagnosis para preservar el desacoplamiento de servicios.


## Fotografías y objetos

Valida tamaño, extensión, MIME real, bytes, decodificación y dimensiones antes de crear el diagnóstico. Parámetros iniciales configurables: máximo 10 MiB, 24 megapíxeles y JPEG/PNG/WebP; HEIC/HEIF forma parte del objetivo V1 de la fuente (§9.12 y §10.9): se incorporará con conversor y prueba E2E en contenedor antes de anunciar soporte y cerrar V1. La implementación deberá rechazarlos de forma controlada mientras no tenga ese soporte; esta condición de validación no elimina el requisito. El grupo 2 fija inicialmente 10485760 bytes/24000000 píxeles en el contrato; no son límites productivos medidos. Cambiar la configuración efectiva requiere alinear contrato y consumidores. Rechaza bombas de descompresión, imágenes corruptas y cargas disfrazadas. Usa clave aleatoria, bucket privado, metadatos mínimos y eliminación de metadatos sensibles según política.

Diagnosis conserva `object_key` y controla lectura por propietario/rol antes de usar proxy o emitir URL firmada corta. AI recibe solo acceso mínimo al objeto requerido. No almacenes bytes de imagen en PostgreSQL ni enlaces permanentes públicos. Define retención y borrado de objetos junto con el borrado lógico del historial y obligaciones de auditoría.

## Aislamiento de infraestructura

En producción expón únicamente el punto de entrada público por HTTPS. Bases, broker, Redis, object storage, workers y `/internal/*` están en redes privadas y usan credenciales separadas por servicio. Aplica mínimo privilegio y valida esquemas y estados al consumir eventos. El proxy de Cloudflare nunca debe servir fotografías o resultados privados desde caché compartida.

No subas `.env`, claves, secretos, pesos o datasets privados al repositorio. Usa gestor de secretos o mecanismo seguro del entorno. No escribas tokens, imágenes, contraseñas ni payloads sensibles completos en logs; propaga `correlation_id` para investigar sin exponer datos.

## Amenazas y pruebas

| Riesgo | Control verificable |
| --- | --- |
| Acceso a recursos de otra cuenta | Dos usuarios A/B; rutas y URL de objeto de B denegadas a A |
| Escalada de rol o token | Firma/issuer/audience/caducidad, cuenta bloqueada y RBAC administrativo |
| Carga maliciosa | Archivo falso `.jpg`, corrupto, excesivo y con dimensiones extremas rechazado antes de crear evento |
| Duplicación de eventos | Inbox, transición atómica y unicidad; un resultado y un aviso por evento esperado |
| Exposición de secretos | Escaneo del repositorio y logs, configuración fuera de Git |
| Pérdida de datos | Backup de bases y objetos y restauración ensayada con diagnóstico conocido |
| Prompt injection opcional | Intenciones cerradas; backend autoriza toda acción; sin SQL, URL o comandos arbitrarios |

Audita mutaciones administrativas con actor, fecha y cambio pertinente, sin registrar secretos. La política de retención, acceso a auditoría y respuesta a incidentes se terminará con el entorno real.


Corrección de identidad: [ADR-0005](adr/0005-correccion-identidad-y-evidencia.md). Origin ya no admite esquemas/puertos alternativos por coincidencia del hostname. Refresh y logout exigen CSRF ligado al refresh, no solo dos valores arbitrarios coincidentes. La auditoría nueva incluye actor, destino, acción y correlación; filas históricas incompletas quedan identificadas como legacy, sin reconstruir datos ausentes.
