# Autenticación Interna y Ciclo de Vida de Leases

Este documento define la arquitectura, preparación operativa, procedimientos de rotación y políticas de ciclo de vida de leases para la comunicación entre servicios (`ai_inference` y `diagnosis`), conforme al ADR-0008 (D2).

---

## 1. Autenticación Interna de Servicios (Ed25519)

### 1.1 Modelo Criptográfico y Formato de Tokens
Para evitar tráfico no autenticado o falsificación entre workers e inferencia técnica, la comunicación interna entre `ai_inference` y `diagnosis` utiliza **JSON Web Tokens (JWT)** firmados con algoritmos asimétricos de curva elíptica **Ed25519 (`EdDSA`)**.

- **Emisor (`iss`)**: `agrodiagnostico-internal`
- **Audiencia (`aud`)**: `agrodiagnostico-diagnosis`
- **Sujeto (`sub`)**: Identificador de la instancia del worker (`instance_id`)
- **Cabecera JWT**:
  - `alg`: `EdDSA`
  - `kid`: Clave pública correspondiente registrada en Diagnosis (p. ej. `worker-inference-v1`)
  - `typ`: `JWT`
- **Tiempo de vida (`exp`)**: Máximo 60 segundos desde emisión (`iat`).
- **Tolerancia temporal**: **0 segundos** (cero margen de gracia). No se toleran desvíos ni expiraciones pasadas.
- **Identificador único (`jti`)**: UUID v4 aleatorio por token.

### 1.2 Aislamiento Estricto de Roles y Tokens
Existe separación absoluta entre identidades de usuario final y tokens de servicio:
1. **Rutas internas (`/internal/*`)**:
   - Requieren token Ed25519 de servicio interno en cabecera `Authorization: Bearer <internal_token>`.
   - Si se presenta un token de usuario (`USER` o `ADMIN`), el endpoint responde estrictamente **403 FORBIDDEN** (`INTERNAL_ACCESS_REQUIRED`).
   - Si el token está ausente, expirado o malformado, responde **401 UNAUTHORIZED**.
2. **Rutas de usuario (`/api/v1/*`)**:
   - Si se presenta un token interno de servicio (`iss == agrodiagnostico-internal`), la autenticación responde estrictamente **403 FORBIDDEN** (`SERVICE_TOKEN_NOT_ALLOWED`).
   - Los servicios internos no pueden suplantar a usuarios ni consultar sus recursos de usuario directamente.

---

## 2. Preparación y Rotación de Secretos

### 2.1 Generación de Claves Ed25519
Cada worker posee su propio par de claves asimétricas:
```bash
# Generar clave privada Ed25519 en formato PEM
openssl genpkey -algorithm ED25519 -out /run/secrets/worker_ed25519_key.pem

# Extraer clave pública correspondiente
openssl pkey -in /run/secrets/worker_ed25519_key.pem -pubout -out /run/secrets/worker_ed25519_pub.pem
```

### 2.2 Almacenamiento y Permisos
- Las claves privadas se montan en `/run/secrets/` en modo solo lectura (`:ro`).
- Permisos de archivo en disco: estrictamente `0600` (lectura/escritura únicamente por el usuario de proceso del servicio, típicamente `appuser`).
- El servicio Diagnosis almacena un registro de claves públicas de confianza (`TrustedKeyRegistry`), mapeando cada `kid` a su clave pública correspondiente.

### 2.3 Procedimiento de Rotación sin Interrupción (Zero-Downtime)
1. **Generación**: Se genera un nuevo par de claves Ed25519 con nuevo `kid` (p. ej. `worker-inference-v2`).
2. **Registro en Diagnosis**: Se añade la nueva clave pública al `TrustedKeyRegistry` de Diagnosis manteniendo la anterior:
   ```json
   {
     "worker-inference-v1": "-----BEGIN PUBLIC KEY-----\n...",
     "worker-inference-v2": "-----BEGIN PUBLIC KEY-----\n..."
   }
   ```
3. **Despliegue de Diagnosis**: Se reinicia o actualiza la configuración de Diagnosis. Ambas claves son válidas simultáneamente.
4. **Transición de Workers**: Se actualizan los workers de AI Inference para firmar con la clave privada de `worker-inference-v2`.
5. **Ventana de drenado**: Se espera el tiempo de expiración máximo de tokens en tránsito (60 segundos).
6. **Retiro de Clave Antigua**: Se elimina `worker-inference-v1` del registro de Diagnosis y se destruye la clave privada antigua del almacenamiento de secretos.

---

## 3. Semántica de Leases y Endpoints Internos

### 3.1 Derivación de `lease_owner`
El propietario del lease (`lease_owner`) se deriva **estrictamente de los claims del JWT verificado** (`token.instance_id`). Ningún cliente puede declarar ni sobreescribir el `lease_owner` a través de encabezados HTTP ni cuerpos JSON.

### 3.2 Reclamo Atómico (`POST /internal/diagnoses/{id}/claim`)
- **Semántica**: El worker reclama una solicitud para procesamiento exclusivo.
- **Transición**: De `PENDIENTE` a `PROCESANDO`.
- **Concurrencia**: Ejecutado con bloqueo exclusivo a nivel de fila (`SELECT ... FOR UPDATE`).
- **Carreras concurrentes**:
  - Si dos workers intentan reclamar simultáneamente, el primero gana. El segundo recibe **409 Conflict** (`DIAGNOSIS_NOT_CLAIMABLE`).
  - Si un usuario cancela la solicitud (`PENDIENTE -> CANCELADO`) antes del reclamo, la cancelación gana y el reclamo posterior recibe **409 Conflict** (`DIAGNOSIS_NOT_CLAIMABLE`).
  - El diagnóstico `CANCELADO` permanece cancelado y jamás emite evento `Finished`.
- **Generación y contadores**: Un reclamo exitoso incrementa `attempt_count` exactamente en 1, genera un nuevo UUID `lease_token`, calcula `lease_expires_at = now + lease_duration` y fija `processing_deadline_at = now + max_processing_time`.

### 3.3 Renovación de Lease (`POST /internal/diagnoses/{id}/lease/renew`)
- **Cuerpo JSON**: `{"lease_token": "<UUID>"}`.
- **Validación**:
  - El diagnóstico debe estar en estado `PROCESANDO`.
  - El `lease_owner` de la base de datos debe coincidir con la `instance_id` del token JWT.
  - El `lease_token` debe coincidir con el token vigente.
  - El reloj autoritativo de la base de datos (`db_now`) debe ser estrictamente menor que `lease_expires_at` (`db_now < lease_expires_at`).
  - `db_now` debe ser estrictamente menor que `processing_deadline_at`.
- **Casos de rechazo**:
  - En la frontera exacta `db_now == lease_expires_at` o posterior, la renovación es rechazada con **409 Conflict** (`STALE_LEASE`).
  - Si se presenta un token expirado o de otra generación, responde **409 Conflict** (`STALE_LEASE`).
  - Si `db_now >= processing_deadline_at`, responde **409 Conflict** (`STALE_LEASE`).
- **Límite de Deadline**: La nueva expiración se calcula como `min(db_now + lease_duration, processing_deadline_at)`. La renovación nunca extiende la vigencia más allá del deadline absoluto.

### 3.4 Entrega de Imagen Privada (`GET /internal/diagnoses/{id}/image`)
- **Encabezado de autorización**: `X-Lease-Token: <UUID>`.
- **Validación**: Requiere lease activo y válido para el worker peticionario.
- **Tombstones**: Si el diagnóstico tiene borrado lógico (`deleted_at IS NOT NULL`), la entrega interna **no falla** si el lease sigue activo, permitiendo al worker completar el análisis en vuelo.
- **Almacenamiento**: Si el backend de almacenamiento (S3/MinIO) está caído, responde **503 Service Unavailable** (`STORAGE_UNAVAILABLE`).
- **Seguridad y CDN**:
  - La respuesta incluye encabezado `Cache-Control: no-store, no-cache, must-revalidate, private`.
  - Se entregan los bytes binarios exactos (`image/jpeg`, etc.).
  - **Bajo ninguna circunstancia se devuelven URLs públicas ni URLs firmadas (presigned URLs)**.

---

## 4. Política de Leases y Recuperación (Task 3.4)

### 4.1 Parámetros Locales Validados
| Parámetro | Valor Local | Descripción |
|---|---|---|
| `lease_duration_seconds` | 60 s | Duración de vigencia de cada concesión de lease. |
| `heartbeat_interval_seconds` | 20 s | Intervalo esperado de renovación periódica por el worker. |
| `recovery_wait_initial_seconds` | 5 s | Tiempo de espera tras expiración de Generación 1 antes de permitir Generación 2. |
| `recovery_wait_secondary_seconds` | 15 s | Tiempo de espera tras expiración de Generación 2 antes de permitir Generación 3. |
| `max_processing_time_seconds` | 300 s | Deadline máximo acumulado de procesamiento por diagnóstico. |
| `max_attempt_count` | 3 | Presupuesto máximo de generaciones de ejecución. |

### 4.2 Reglas de Validación de Configuración
La política rechaza configuraciones inválidas en el arranque (`LeaseConfigurationError`):
- `heartbeat_interval_seconds >= lease_duration_seconds`: Inválido (el worker no tendría margen para renovar antes de expirar).
- Cualquier valor no positivo (`<= 0`): Inválido.
- `max_processing_time_seconds < lease_duration_seconds`: Inválido.
- `max_attempt_count < 1`: Inválido.

### 4.3 Invariante de Solicitudes Pendientes
Las solicitudes en estado `PENDIENTE` sin primer reclamo **nunca expiran** bajo esta política. Solo las solicitudes en estado `PROCESANDO` que han consumido un reclamo poseen `lease_expires_at` y `processing_deadline_at`.

---

## 5. Perímetro de Red y Protección Nginx

Los endpoints bajo el prefijo `/internal/*` están reservados exclusivamente para tráfico de servicio a servicio dentro de la red privada:
- En el reverse proxy perimetral (`infra/nginx/default.conf`):
  ```nginx
  location ^~ /internal {
      return 404;
  }
  ```
- Nginx descarta inmediatamente cualquier intento de acceso público a `/internal/*` devolviendo un **404 Not Found** indistinguible de rutas inexistentes.

