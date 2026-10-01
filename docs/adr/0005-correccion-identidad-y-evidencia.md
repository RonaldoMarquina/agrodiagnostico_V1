# ADR-0005 — Corrección del cierre de identidad

Fecha: 2026-09-30. Estado: adoptado para `corregir-cierre-incremento-1`.

## Contexto

Una revisión posterior al archivo detectó claves JWT no montadas en Compose, Origin comparado solo por hostname como fallback, CSRF sin vínculo con la sesión, auditoría incompleta, respuestas contrarias al contrato y una simulación en memoria presentada como evidencia de procesos independientes. No se cambia el algoritmo ni el alcance de Identity/Diagnosis definidos en ADR-0004.

## Decisión

- `prepare_local.py` prepara una pareja Ed25519 persistente con OpenSSL. Valida la pareja existente y nunca la reemplaza automáticamente. Identity monta ambos PEM mediante secretos de archivo; el arranque falla si faltan o son incompatibles. Otros servicios no reciben la clave privada.
- Origin se compara exactamente con la allowlist (esquema, host y puerto incluidos). El CSRF es HMAC-SHA256, con el refresh aleatorio de 256 bits como clave y etiqueta fija `agrodiagnostico:csrf:v1`; cookie y cabecera se comparan en tiempo constante con el resultado esperado. No se almacena ni registra el refresh en texto claro. Este vínculo funciona entre procesos sin estado compartido en memoria ni columna CSRF adicional.
- Login bloqueado devuelve el mismo 401 que credenciales incorrectas. Logout desconocido/expirado/revocado devuelve 401; logout válido revoca la familia conforme al contrato y limpia cookies. El middleware es la única autoridad de correlación y el manejador de errores limpia cookies en la respuesta real.
- La migración `identity_0003` añade actor, destino, acción, correlación y marcador legacy. Las filas existentes permanecen intactas y marcadas como heredadas; los campos faltantes quedan null. Las nuevas filas de aplicación llevan contexto normativo. Se conservan columnas históricas y trigger de UPDATE/DELETE prohibidos. Auditoría y mutación se confirman juntas.
- La aceptación usa contenedores y red propios, PostgreSQL con rol de aplicación restringido, tres procesos Identity independientes y Nginx. Las pruebas en memoria nunca toman DB_HOST ni eliminan datos de una base configurada.

## Alternativas y consecuencias

Guardar un hash CSRF por sesión sería válido, pero exige migrar sesiones para un dato derivable del refresh. Se descarta double-submit sin vínculo y aceptar Origin por hostname. También se descarta rellenar correlaciones históricas inventadas.

Los clientes con CSRF emitido por la implementación anterior deben volver a iniciar sesión después del despliegue. Access tokens conservan la ventana stateless del ADR-0004. El archivo OpenSpec original se conserva; la evidencia nueva rectifica sus afirmaciones de cierre. Las pruebas no acreditan producción, entrega real de correo ni rendimiento medido.

La migración es aditiva y se prueba con filas históricas. No se migra ni reinicia automáticamente el entorno de desarrollo del usuario durante la corrección; aplicar el nuevo código requiere preparar secretos, reconstruir y ejecutar migraciones con el procedimiento documentado.
