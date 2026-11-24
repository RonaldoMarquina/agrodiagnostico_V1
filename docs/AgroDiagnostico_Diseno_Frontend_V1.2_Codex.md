
# AgroDiagnóstico V1 — Especificación del Frontend V1.2

*Versión Markdown para consulta e implementación con Codex. Fuente: documento V1.2 con 20 referencias visuales.*

|               |                                                                                                                                                                              |
|---------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Proyecto**  | Proyecto Final – Arquitectura de Software \[IS-488\]                                                                                                                         |
| **Documento** | Diseño del frontend V1.2 (actualización integral de la V1.1)                                                                                                                 |
| **Base**      | Definición Base del Proyecto – AgroDiagnóstico V1, Puntos 1 al 10                                                                                                            |
| **Fecha**     | 20 de noviembre de 2026                                                                                                                                                      |
| **Estado**    | Especificación funcional revisada. Apta para prototipos y base técnica; integración condicionada a contratos OpenAPI, pruebas y revisión humana del contenido fitosanitario. |

> **Resumen.** Se mantienen 20 pantallas (5 públicas, 7 del agricultor y 8 de administración), más un asistente flotante. La V1.2 conserva el mapa de navegación y corrige garantías de recomendaciones, consulta de modelo activo, persistencia de fotografías sin conexión, privacidad EXIF, idempotencia, seguridad de sesión, monitoreo y compatibilidad de contratos. Ningún endpoint propuesto se considera existente sin verificar el repositorio y su OpenAPI.

# 1. Principios de diseño

1.  **Diagnóstico en pocos pasos desde el celular.** Un agricultor sin conocimientos técnicos debe poder subir una foto y entender el resultado (RNF-USA01, USA02, USA03).

2.  **El frontend no es la barrera de seguridad.** Ocultar un botón es comodidad; el backend aplica RBAC y propiedad del recurso (9.8, 9.9).

3.  **El resultado siempre comunica incertidumbre.** Confianza no es precisión del modelo (8.19), existe NO CONCLUYENTE (8.20) y la cobertura limitada se anuncia (RF-11).

4.  Con mala conexión se ofrece recuperación controlada, sin prometer envío en segundo plano con la aplicación cerrada. La cola local requiere consentimiento, dispositivo seguro y limpieza de datos; RabbitMQ protege el procesamiento posterior a la recepción del servidor.

5.  **Lo que se prueba en el Punto 10 debe poder verse en pantalla.** Cada prueba de resiliencia, seguridad y usabilidad tiene su evidencia visible (sección 15).

# 2. Decisiones tomadas

Decisiones que la propuesta anterior dejaba abiertas o resolvía de forma inconsistente con la base. Las referencias numéricas apuntan a secciones de la Definición Base.

| **ID** | **Tema**                 | **Decisión**                                                                                                                                                                                                                                                                                                                               | **Motivo**                                                                                                                         |
|--------|--------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------|
| D-01   | Arquitectura del cliente | Una sola SPA React + TypeScript con dos áreas (agricultor y administración) cargadas por separado (code splitting).                                                                                                                                                                                                                        | Coherente con 7.2. El área admin no pesa en el celular del agricultor (RNF-CON03).                                                 |
| D-02   | Tema visual              | Tema claro de alto contraste con verdes agrícolas y neutros. Sin modo oscuro en V1. Los mockups oscuros de la propuesta anterior no se adoptan.                                                                                                                                                                                            | Uso al aire libre bajo luz solar.                                                                                                  |
| D-03   | Dispositivos             | Agricultor: mobile-first. Administración: escritorio primero, usable en tablet.                                                                                                                                                                                                                                                            | RNF-USA02.                                                                                                                         |
| D-04   | Sesión                   | Access token en memoria; refresh token en cookie httpOnly, Secure, SameSite=Strict y Path restringido a /api/v1/auth cuando la ruta real lo permita. Access 15 min y refresh 7 días con rotación (provisionales). Las operaciones con cookie deben validar Origin/CSRF, límites y revocación; configuración a comprobar en Identity/Nginx. | Seguridad por capas (7.15 y 9.7); evitar localStorage no basta para mitigar CSRF, XSS ni robo de sesión.                           |
| D-05   | Datos y formularios      | TanStack Query para consultas, caché y polling. React Hook Form + Zod para formularios.                                                                                                                                                                                                                                                    | Menos código propio y comportamiento uniforme ante errores.                                                                        |
| D-06   | Contratos                | Tipos TypeScript generados desde el OpenAPI de cada servicio (openapi-typescript), no escritos a mano.                                                                                                                                                                                                                                     | 7.2 y 10.5 (pruebas de contrato).                                                                                                  |
| D-07   | Interfaz                 | Tailwind CSS, shadcn/ui sobre Radix e iconos Lucide; cada componente se verifica con teclado, lectores de pantalla y contraste real.                                                                                                                                                                                                       | La biblioteca facilita accesibilidad, pero no la garantiza automáticamente.                                                        |
| D-08   | PWA                      | PWA completa fuera de V1. Cola local opcional con IndexedDB y reanudación cuando la aplicación está abierta o vuelve a abrirse; sin prometer sincronización automática con el navegador cerrado.                                                                                                                                           | RNF-CON02 y RNF-CON03; la API y el servidor siguen siendo fuentes de verdad.                                                       |
| D-09   | Rol ADMIN                | El ADMIN también crea diagnósticos propios (tabla 9.8): ve ambas áreas y alterna con un enlace. Tras iniciar sesión, USER va a /inicio y ADMIN a /admin.                                                                                                                                                                                   | La propuesta anterior contradecía la tabla RBAC.                                                                                   |
| D-10   | Rutas                    | En español, sin prefijo /app, alineadas con 7.2. /diagnosticos redirige a /historial.                                                                                                                                                                                                                                                      | Una sola convención.                                                                                                               |
| D-11   | Pantallas                | Perfil y Configuración se fusionan en “Mi cuenta” con tres pestañas.                                                                                                                                                                                                                                                                       | Mismo alcance (RF-03, RF-19) con una pantalla menos.                                                                               |
| D-12   | Asistente                | Botón flotante; no es ítem de menú ni pantalla. Navega solo tras confirmación del usuario. Voz fuera de V1.                                                                                                                                                                                                                                | 8.24 a 8.27 y 10.44.                                                                                                               |
| D-13   | Dueño del asistente      | Propuesta: módulo assistant aislado dentro de Diagnosis Service mediante AssistantPort y adaptador Gemini. Tiene timeout, cuota, circuit breaker/aislamiento y ninguna dependencia crítica en el procesamiento de diagnósticos. ADR-014 y revisión contra arquitectura real pendientes.                                                    | Evita crear otro microservicio en V1, pero debe probarse que una falla o saturación de Gemini no degrade el flujo central.         |
| D-14   | Estado CANCELADO         | Sexto estado visible. Se agrega a la lista de 2.5.                                                                                                                                                                                                                                                                                         | Aparece en 5.7 y 10.8 pero no en 2.5.                                                                                              |
| D-15   | Monitoreo                | Tarjetas de estado y acceso autorizado a Grafana; datos de salud obtenidos mediante adaptador/servicio operativo de solo lectura con timeouts, no mediante consultas indiscriminadas entre servicios.                                                                                                                                      | No duplicar Grafana ni conceder al frontend credenciales de infraestructura.                                                       |
| D-16   | Modelos IA               | Pantalla de solo lectura: versión activa por capacidad consultada desde el registro/configuración efectiva de inferencia y versiones históricas derivadas de diagnósticos. Sin activar, importar o retirar desde la UI V1.                                                                                                                 | RF-28 y 2.3 distinguen versión activa de versión que procesó cada diagnóstico.                                                     |
| D-17   | Recomendaciones          | CRUD administrativo de recomendaciones, pero ninguna orientación se publica como válida sin fuente verificable, revisión humana y habilitación de política controlada por backend. Si no hay política utilizable se informa CATALOG_UNAVAILABLE; la UI no inventa consejos.                                                                | RF-12 exige catálogo controlado; compatibilidad con la política operativa ya planteada, pendiente de cotejo con la implementación. |
| D-18   | Auditoría                | Dos pestañas: “Cuentas y accesos” (Identity) y “Catálogo y diagnósticos” (Diagnosis). No se mezclan en un solo endpoint.                                                                                                                                                                                                                   | Cada servicio es dueño de sus datos (6.8).                                                                                         |
| D-19   | Fotos para el admin      | El admin consulta metadatos; "Ver fotografía" exige comprobación de permisos, URL temporal y registro de auditoría realizado por el backend.                                                                                                                                                                                               | RNF-SEG04 y 9.16; un clic registrado solo en React no constituye auditoría fiable.                                                 |
| D-20   | Privacidad de la foto    | La optimización en navegador genera un archivo sin EXIF cuando es decodificable. Para HEIC original o cualquier fallback, el backend debe sanitizar metadatos antes de persistir; si no puede garantizarlo, se rechaza la carga con mensaje claro.                                                                                         | Privacidad de ubicación GPS incluso cuando falla la conversión en el cliente.                                                      |
| D-21   | Formato de error         | El frontend traduce códigos de error estables y muestra request_id. Se propone formato {code, message, request_id}, sujeto a compatibilidad con OpenAPI existente; no se presupone uniforme en todos los servicios.                                                                                                                        | Contratos versionados y adaptador de errores; el usuario nunca recibe excepciones internas.                                        |
| D-22   | Subida idempotente       | Idempotency-Key estable por intento lógico de fotografía/diagnóstico, conservada en IndexedDB durante reintentos. El servidor debe vincular clave, usuario y huella de carga, conservar un resultado recuperable y rechazar reutilización con contenido distinto.                                                                          | Evita dobles diagnósticos cuando se pierde una respuesta; una cabecera aislada no da idempotencia.                                 |
| D-23   | Umbrales de confianza    | confidence_band (ALTA, MEDIA, BAJA) y decisión NO CONCLUYENTE los define el backend con política versionada; la interfaz no deduce umbrales ni equipara confianza a exactitud.                                                                                                                                                             | 8.18 a 8.20: la calibración y los criterios pertenecen al modelo/política y se prueban experimentalmente.                          |
| D-24   | Idioma                   | Solo español, con todos los textos en un archivo único de mensajes (sin librería i18n).                                                                                                                                                                                                                                                    | Alcance de V1 y cambios de texto sin tocar componentes.                                                                            |
| D-25   | Publicación segura       | El frontend consulta availability/review_status del catálogo o de la política si existe en API. Solo muestra recomendaciones activas y aprobadas; ante CATALOG_UNAVAILABLE presenta mensaje de indisponibilidad y nunca inventa dosis ni tratamientos.                                                                                     | Separa predicción de IA y orientación controlada; se exige un contrato real antes de integrar.                                     |
| D-26   | Modelo activo real       | El dato del modelo activo se obtiene del registro o configuración en producción, no inferido del último diagnóstico. Mostrar "desconocido" si la fuente está indisponible.                                                                                                                                                                 | Evita confundir histórico, candidato y versión actualmente desplegada.                                                             |
| D-27   | Persistencia local       | Guardar foto optimizada solo con aceptación del usuario; avisar que permanece en el dispositivo, caduca a 24 h, se elimina tras confirmación o cierre de sesión y puede ser visible en dispositivos compartidos.                                                                                                                           | IndexedDB no equivale a almacenamiento cifrado ni sincronización en segundo plano.                                                 |
| D-28   | Seguridad de cookie      | Aplicar Origin/CSRF según contrato de Identity; refresh con rotación y protección frente a reuso, logout invalida sesión y limpia consultas y cola local del usuario.                                                                                                                                                                      | SameSite y httpOnly mitigan riesgos concretos, no sustituyen otras defensas.                                                       |
| D-29   | Supervisión segura       | No permitir al cliente acceso a APIs administrativas de RabbitMQ, bases o claves de Grafana. Agregación operativa autorizada y limitada, o enlace externo restringido; UNKNOWN ante timeout.                                                                                                                                               | Menor superficie de ataque y menor acoplamiento de Diagnosis Service.                                                              |
| D-30   | Puerta de integración    | No dar por construido ningún contrato marcado Ajustar/Agregar. Contrastar OpenAPI real, pruebas de integración y evidencia por RF antes de declarar la pantalla funcional.                                                                                                                                                                 | Distingue diseño propuesto de implementación verificada (Punto 10).                                                                |

# 3. Mapa de pantallas

Total: **20 pantallas**. Las acciones de crear, editar o confirmar se resuelven con modales dentro de estas pantallas.

| **\#** | **Pantalla**               | **Ruta**                       | **Acceso**  | **Requisitos**                  | **Etapa** |
|--------|----------------------------|--------------------------------|-------------|---------------------------------|-----------|
| 1      | Página de inicio           | /                              | Público     | Informativa (sin RF)            | 4         |
| 2      | Iniciar sesión             | /login                         | Público     | RF-02                           | 1         |
| 3      | Registro                   | /registro                      | Público     | RF-01                           | 1         |
| 4      | Recuperar contraseña       | /recuperar-contrasena          | Público     | RF-04                           | 2         |
| 5      | Restablecer contraseña     | /restablecer-contrasena?token= | Público     | RF-04                           | 2         |
| 6      | Inicio del agricultor      | /inicio                        | Autenticado | RF-16, RF-18                    | 1         |
| 7      | Nuevo diagnóstico          | /diagnosticos/nuevo            | Autenticado | RF-05, RF-06, RNF-CON01 a CON03 | 1         |
| 8      | Detalle y resultado        | /diagnosticos/:id              | Autenticado | RF-07 a RF-15, RF-20            | 1         |
| 9      | Historial                  | /historial                     | Autenticado | RF-16, RF-17                    | 1         |
| 10     | Notificaciones             | /notificaciones                | Autenticado | RF-18                           | 2         |
| 11     | Mi cuenta                  | /cuenta                        | Autenticado | RF-03, RF-19                    | 2         |
| 12     | Ayuda                      | /ayuda                         | Autenticado | RNF-USA03                       | 2         |
| 13     | Dashboard administrativo   | /admin                         | ADMIN       | RF-26                           | 3         |
| 14     | Usuarios                   | /admin/usuarios                | ADMIN       | RF-21                           | 3         |
| 15     | Diagnósticos (supervisión) | /admin/diagnosticos            | ADMIN       | RF-24                           | 3         |
| 16     | Catálogo fitosanitario     | /admin/catalogo                | ADMIN       | RF-22                           | 3         |
| 17     | Recomendaciones            | /admin/recomendaciones         | ADMIN       | RF-23                           | 3         |
| 18     | Auditoría                  | /admin/auditoria               | ADMIN       | RF-25                           | 3         |
| 19     | Modelos IA                 | /admin/modelos                 | ADMIN       | RF-28                           | 3         |
| 20     | Monitoreo del sistema      | /admin/monitoreo               | ADMIN       | RF-27                           | 3         |

# 4. Navegación y control de acceso

## 4.1 Agricultor

- **Celular:** barra inferior con cuatro ítems: Inicio, **Nuevo diagnóstico** (botón central destacado), Historial y Mi cuenta.

- **Escritorio:** menú lateral con Inicio, Nuevo diagnóstico, Historial, Notificaciones, Mi cuenta y Ayuda.

- **Encabezado (ambos):** logo, campana de notificaciones con contador de no leídas y menú de usuario (Mi cuenta, Ayuda, Cerrar sesión). Si el usuario es ADMIN, el menú agrega “Panel de administración”.

- **Asistente:** botón flotante, en la esquina inferior derecha (por encima de la barra inferior en celular).

## 4.2 Administración

- Menú lateral fijo con ocho ítems: Dashboard, Usuarios, Diagnósticos, Catálogo, Recomendaciones, Auditoría, Modelos IA y Monitoreo.

- Enlace “Mis diagnósticos” en el encabezado para pasar al área del agricultor (D-09).

- En pantallas pequeñas las tablas se desplazan horizontalmente. La administración desde el celular no es un objetivo de V1.

## 4.3 Guards de ruta

| **Guard**    | **Regla**                                                         | **Si no se cumple**                                                      |
|--------------|-------------------------------------------------------------------|--------------------------------------------------------------------------|
| Solo público | Login, registro y recuperación. Con sesión activa no se muestran. | Redirige a /inicio o /admin según el rol.                                |
| Autenticado  | Requiere access token válido (renovable con el refresh).          | Redirige a /login y recuerda la ruta de origen para volver.              |
| Rol ADMIN    | Requiere rol ADMIN en el token.                                   | Muestra “No tienes permiso para esta sección” y ofrece volver al inicio. |

> Los guards solo mejoran la experiencia. La autorización real la hace el backend en cada petición (9.8). Esto se comprueba directamente contra la API (10.36).

# 5. Flujo “Nuevo diagnóstico”

Es el flujo crítico FC-01 en el lado del cliente, con la estrategia de conectividad limitada de FC-03. No se pide seleccionar el cultivo (RF-07).

1.  **Elegir la foto.** Dos botones grandes: “Tomar foto” (cámara trasera) y “Elegir de la galería”.

2.  **Validación local inmediata.** Formato permitido, tamaño máximo y dimensión mínima. Si falla, mensaje claro y se vuelve a elegir (RF-06).

3.  Optimización en el navegador. Se corrige orientación y se genera copia JPEG sin EXIF, cuando la decodificación es compatible. HEIC/HEIF se convierte bajo demanda; si falla, solo se envía el original cuando el backend garantiza decodificación y eliminación de metadatos antes de persistir. En caso contrario se informa incompatibilidad y se pide otra imagen.

4.  **Vista previa y consejos.** Muestra la foto optimizada con su peso (“De 6,2 MB a 0,8 MB”), un consejo breve (enfoca la hoja, buena luz) y el botón “Analizar”.

5.  Envío. POST /api/v1/diagnoses con multipart e Idempotency-Key persistida para ese diagnóstico. Se muestra progreso de subida real si el transporte lo permite y opción "Cancelar envío"; cancelar la transferencia no equivale a cancelar un diagnóstico ya creado en el backend.

6.  Corte de conexión. Ante red inestable, primero consultar o reintentar con la MISMA Idempotency-Key para evitar duplicar diagnósticos. Si no se confirma recepción, ofrecer guardar la copia optimizada en IndexedDB, con aviso explícito sobre privacidad local. Al recuperar conexión con la aplicación abierta, o al reabrirla, se ofrece reintentar; no se promete envío autónomo con navegador cerrado. El dato local se borra tras confirmación, al vencer 24 h o al cerrar sesión.

7.  **Confirmación.** El servidor responde 201 con el identificador y el estado PENDIENTE. La app abre /diagnosticos/:id y empieza el seguimiento (sección 6).

### Parámetros del cliente

| **Parámetro**                     | **Valor**                                                                                 | **Se confirma con**                                             |
|-----------------------------------|-------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| Formatos aceptados                | JPEG/JPG, PNG, WebP, HEIC/HEIF                                                            | 9.12 (definitivo)                                               |
| Tamaño máximo de la foto original | 10 MB                                                                                     | RNF-CON01                                                       |
| Lado menor mínimo                 | 320 px (provisional)                                                                      | Pruebas de IA y 10.34                                           |
| Lado mayor tras optimizar         | 1 600 px (provisional)                                                                    | 10.34                                                           |
| Calidad JPEG                      | 0,85 (provisional)                                                                        | 10.34                                                           |
| Peso objetivo optimizado          | ≤ 1 MB                                                                                    | RNF-CON01                                                       |
| Reintentos automáticos de subida  | 3, con esperas de 2 s, 5 s y 12 s (provisional)                                           | 10.33                                                           |
| Tiempo de espera por intento      | 120 s (provisional)                                                                       | 10.33                                                           |
| Retención de la cola local        | 24 h como máximo (provisional). Al completar, cerrar sesión o vencer el plazo se elimina. | Pruebas de recuperación, privacidad y dispositivos compartidos. |

# 6. Estados del diagnóstico y seguimiento

| **Estado**     | **Texto al agricultor**                                                  | **Color e icono**    | **Acción**                        | **Seguimiento** |
|----------------|--------------------------------------------------------------------------|----------------------|-----------------------------------|-----------------|
| PENDIENTE      | “En cola. Pronto empezaremos a analizar tu foto.”                        | Gris, reloj          | Cancelar                          | Sí              |
| PROCESANDO     | “Analizando tu foto…”                                                    | Azul, animación      | Ninguna (ya no se puede cancelar) | Sí              |
| COMPLETADO     | “Diagnóstico listo”                                                      | Verde, check         | Ver recomendaciones y valorar     | Fin             |
| NO CONCLUYENTE | “No pudimos estar seguros con esta foto”                                 | Ámbar, interrogación | Subir otra foto con consejos      | Fin             |
| FALLIDO        | “No pudimos analizar tu foto. Inténtalo otra vez.” más el motivo general | Rojo, alerta         | Nuevo diagnóstico                 | Fin             |
| CANCELADO      | “Cancelaste este diagnóstico”                                            | Gris, tachado        | Nuevo diagnóstico                 | Fin             |

Todos los estados se muestran con **icono y texto**, nunca solo con color.

### Reglas de seguimiento

- El cliente consulta GET /api/v1/diagnoses/{id}/status cada 2 s durante los primeros 20 s, cada 5 s hasta los 2 min y cada 15 s después.

- El seguimiento se pausa cuando la pestaña está oculta, se reanuda al volver y se detiene en cualquier estado final.

- Si pasan más de 2 minutos (el objetivo es 30 s, RNF-REN03): “Está tardando más de lo normal. Puedes salir; te avisaremos cuando esté listo.”

- Los cambios de estado se anuncian a lectores de pantalla con aria-live="polite".

- Cancelar solo aparece en PENDIENTE. Si el servidor responde 409 porque el procesamiento ya empezó, se muestra el mensaje correspondiente (sección 13).

- Motivos generales de FALLIDO (RF-15), definidos por el backend: SERVICIO_TEMPORAL, IMAGEN_NO_PROCESABLE y ERROR_ANALISIS. Cada uno tiene un texto propio y nunca se muestra un error técnico.

# 7. Pantalla de resultado

Bloques de arriba hacia abajo en /diagnosticos/:id cuando el estado es COMPLETADO:

1.  **Encabezado:** estado, fecha e identificador corto.

2.  **Foto analizada:** miniatura que se puede ampliar.

3.  **Cultivo y problema probable:** nombre común destacado y nombre científico en segundo plano. Se indica si es enfermedad o plaga.

4.  **Confianza:** “Confianza del modelo: 91 %”, con barra y etiqueta Alta, Media o Baja tomada de confidence_band (D-23). Un icono de ayuda explica que **no equivale al porcentaje de acierto del sistema** (8.19).

5.  Cobertura limitada (RF-11): cuando limited_coverage sea verdadero, avisar “Orientación general: este cultivo todavía no tiene diagnóstico especializado validado”. No presentarlo con el mismo tratamiento visual que un diagnóstico soportado ni mostrar recomendaciones no aprobadas.

6.  Recomendaciones (RF-12): mostrar únicamente orientación vigente y controlada obtenida del backend, con su fuente y datos de revisión que el contrato haga públicos. Si el backend indica CATALOG_UNAVAILABLE o no existe contenido aprobado, mostrar “Todavía no contamos con recomendaciones revisadas para este resultado”. No inventar ni improvisar tratamientos.

7.  **Aviso permanente:** “Esta herramienta apoya tu decisión; no reemplaza a un ingeniero agrónomo.” (1.5)

8.  **Utilidad (RF-20):** “¿Te sirvió este resultado?” con Sí o No. Se puede cambiar; sin texto libre.

9.  **Detalles técnicos (plegado):** modelo y versión utilizados.

10. **Acciones:** “Nuevo diagnóstico” y “Quitar del historial”.

### Variantes

- **NO CONCLUYENTE:** no se muestra ningún nombre de enfermedad o plaga. Se explica con palabras simples, se dan consejos para una mejor foto (enfocar, luz natural, acercarse a la hoja afectada) y el botón principal es “Subir otra foto” (RF-10).

- **FALLIDO:** mensaje con el motivo general y el botón “Intentar con otra foto”. En 5xx se agrega “Código de soporte” plegado con el request_id (RNF-OBS03).

- **CANCELADO:** mensaje breve y acceso a un nuevo diagnóstico.

# 8. Historial

- Lista paginada de 10 elementos con miniatura, fecha, cultivo, problema y estado.

- Filtros: estado, cultivo y rango de fechas. Búsqueda por nombre del problema. Los filtros se aplican en el servidor (sección 11).

- “Quitar del historial” abre una confirmación: “Se quitará de tu historial. Esta acción no se puede deshacer.” Usa DELETE /api/v1/diagnoses/{id} (eliminación lógica, RF-17).

- Estado vacío: “Todavía no tienes diagnósticos” con el botón “Hacer mi primer diagnóstico”.

- Los diagnósticos PENDIENTE y PROCESANDO se actualizan solos mientras la pantalla está visible.

# 9. Resto de pantallas del agricultor y públicas

| **Pantalla**           | **Contenido y decisiones**                                                                                                                                                                                                                                                                                                                                   |
|------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Página de inicio       | Presentación en una sola página: qué hace, cómo funciona en tres pasos, cultivos soportados (papa y maíz), limitaciones explicadas con honestidad y botones de registro e inicio de sesión. Es lo último que se construye.                                                                                                                                   |
| Iniciar sesión         | Correo y contraseña con mostrar u ocultar. Error de credenciales sin revelar cuál campo falló. Cuenta bloqueada con mensaje propio. Enlace a recuperar contraseña.                                                                                                                                                                                           |
| Registro               | Nombre, correo, contraseña con indicador de fortaleza y confirmación. Información clara sobre finalidad y retención de fotografías, enlace a política de privacidad real y aceptación explícita si corresponde. No prometer usos ni plazos que el backend no cumpla. Correo duplicado: mensaje controlado (RF-01).                                           |
| Recuperar contraseña   | Un solo campo de correo. La respuesta es siempre: “Si existe una cuenta asociada, te enviaremos las instrucciones.” (9.10).                                                                                                                                                                                                                                  |
| Restablecer contraseña | Toma el token de la URL. Dos campos de contraseña. Si el token venció o ya se usó, muestra el estado “Enlace no válido” con opción de pedir otro.                                                                                                                                                                                                            |
| Inicio del agricultor  | Botón principal grande “Nuevo diagnóstico”. Bloque “En proceso” con estado en vivo. Últimos 5 diagnósticos. Hasta 3 notificaciones no leídas. Enlace “Ver todo el historial”.                                                                                                                                                                                |
| Notificaciones         | Lista paginada de más nuevas a más antiguas, con distintivo de no leída. Al tocar una, se marca como leída y abre el diagnóstico. Botón “Marcar todas como leídas”. El contador de la campana se actualiza cada 60 s mientras la pestaña está visible.                                                                                                       |
| Mi cuenta              | Tres pestañas. **Datos:** nombre editable; el correo se muestra pero no se edita en V1 porque cambiarlo exige verificación que RF-03 no define. **Seguridad:** cambiar contraseña y cerrar sesión. **Notificaciones:** interruptor “Avisarme por correo cuando termine un diagnóstico”; la notificación dentro de la plataforma siempre está activa (RF-19). |
| Ayuda                  | Contenido estático y accesible: captura de fotografías, alcance real de cultivos/clases, estados, interpretación de confianza, privacidad de fotos, carga pendiente en este dispositivo y preguntas frecuentes.                                                                                                                                              |

# 10. Panel de administración

| **Pantalla**    | **Contenido y acciones**                                                                                                                                                                                                                                                                   | **Decisión o dato necesario**                                                                                                       |
|-----------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| Dashboard       | Tarjetas: diagnósticos por estado, usuarios totales y confianza media; dos gráficos como máximo. Mostrar la procedencia de los indicadores y distinguir métricas de Identity y Diagnosis. Avisos de fallos o DLQ cuando estén disponibles.                                                 | No suponer un único endpoint cross-service; consumir resultados separados o agregador autorizado y comprobado.                      |
| Usuarios        | Tabla con nombre, correo, rol, estado y fecha de registro. Búsqueda, filtro por estado y paginación. Acciones Bloquear y Reactivar con confirmación. **El motivo es obligatorio al bloquear** (mínimo 5 caracteres) y queda en la auditoría.                                               | Un admin no puede bloquearse a sí mismo (frontend y backend).                                                                       |
| Diagnósticos    | Tabla con identificador, usuario, fecha, estado, cultivo, problema, confianza, modelo y versión, y error general. Filtros por estado, cultivo y fechas. Panel de detalle con tiempos y motivo del fallo. La foto no se muestra por defecto: “Ver fotografía” la abre y registra el acceso. | D-19. Supervisión, no edición: no hay acciones sobre el diagnóstico.                                                                |
| Catálogo        | Pestañas Cultivos, Enfermedades y Plagas. Gestión y activación con confirmación. Las clases o plagas no evaluadas no podrán mostrarse como soporte oficial; el backend valida la restricción.                                                                                              | La activación del catálogo no implica activar una capacidad del modelo; confirmar contratos y reglas de negocio.                    |
| Recomendaciones | Tabla por problema y formulario (título, contenido, orden, fuente, estado). Indicador de disponibilidad y revisión cuando el backend lo ofrezca. Avisar si no hay orientación aprobada; las políticas reales siguen su propio procedimiento auditado.                                      | D-17/D-25: la pantalla CRUD no constituye aprobación humana. Sin versión/política validada, no prometer recomendaciones al usuario. |
| Auditoría       | Dos pestañas (D-18). Filtros por fecha, acción y usuario. Columnas: fecha y hora, quién, acción, recurso y resultado. Solo lectura. Nunca muestra contraseñas, tokens ni secretos (9.45).                                                                                                  | Dos endpoints, uno por servicio.                                                                                                    |
| Modelos IA      | Panel de solo lectura: versión efectivamente activa por capacidad, estado del registro y tabla de versiones usadas históricamente en diagnósticos. Si no hay fuente de verdad, mostrar "No verificado".                                                                                    | D-16/D-26: no deducir activo = último diagnóstico; sin importación ni activación desde esta UI.                                     |
| Monitoreo       | Tarjetas de salud de servicios/dependencias, solicitudes pendientes y DLQ con estado OK, Degradado, Caído o Desconocido. Actualización moderada y enlace a Grafana con control de acceso.                                                                                                  | D-29: API operativa de solo lectura y timeouts; no exponer credenciales ni Management API de RabbitMQ al navegador.                 |

# 11. Contratos que el frontend necesita del backend

Matriz de compatibilidad propuesta: “Ajustar” significa que la definición de arquitectura contempla una operación conceptual, no que exista en el repositorio. “Agregar” significa operación requerida por el frontend que no aparece en el conjunto conceptual revisado. Ambos estados exigen verificar OpenAPI real, código, autorización, errores y pruebas antes de integrar. La ruta y el método definitivos pueden variar justificadamente.

| **Endpoint**                                     | **Estado**          | **Detalle**                                                                                                                                                                                                                                                                         |
|--------------------------------------------------|---------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| /api/v1/auth/login, refresh, logout              | Ajustar             | Refresh en cookie httpOnly según D-04 y rotación controlada. Validar Origin/CSRF, revocación de sesión, expiración y respuesta ACCOUNT_BLOCKED contra contratos reales.                                                                                                             |
| POST /api/v1/diagnoses                           | Ajustar             | Multipart con clave idempotente estable por diagnóstico. Retorno consistente del id y estado; reintentos idénticos devuelven el mismo diagnóstico. Contrato de conflicto para diferente archivo/mismo key.                                                                          |
| GET /api/v1/diagnoses                            | Ajustar             | Parámetros status, crop, q, from, to, page, page_size. Respuesta {items, total, page, page_size} con thumbnail_url temporal por elemento.                                                                                                                                           |
| GET /api/v1/diagnoses/{id}                       | Ajustar             | Datos del resultado y trazabilidad: status, crop, problem, confidence, confidence_band, limited_coverage, failure_reason, model, recommendations, image_url temporal, feedback y fechas. Añadir disponibilidad/revisión del catálogo si existe en el backend; no inventar el campo. |
| GET /api/v1/diagnoses/{id}/status                | Ajustar             | Respuesta liviana {status, failure_reason?} para el polling.                                                                                                                                                                                                                        |
| POST .../cancel y DELETE ...                     | Ajustar             | Cancelar responde 409 CONFLICT si el procesamiento ya empezó. Eliminar responde 204.                                                                                                                                                                                                |
| POST /api/v1/diagnoses/{id}/feedback             | Agregar             | Cuerpo {useful: boolean}. Se puede repetir para cambiar la respuesta. RF-20 no tenía endpoint.                                                                                                                                                                                      |
| GET /api/v1/notifications                        | Ajustar             | Paginado, con unread_count en la respuesta.                                                                                                                                                                                                                                         |
| PATCH /api/v1/notifications/read-all             | Agregar             | Marca todas como leídas.                                                                                                                                                                                                                                                            |
| /api/v1/notifications/preferences                | Ajustar             | Cuerpo {email_on_completed: boolean}.                                                                                                                                                                                                                                               |
| POST /api/v1/assistant/messages                  | Agregar             | Ver sección 12.                                                                                                                                                                                                                                                                     |
| GET /api/v1/admin/metrics/summary                | Agregar             | Parámetros from y to. Conteo por estado, confianza promedio y serie diaria. Lo sirve Diagnosis.                                                                                                                                                                                     |
| GET /api/v1/admin/users/stats                    | Agregar             | Total, activos y bloqueados. Lo sirve Identity.                                                                                                                                                                                                                                     |
| GET /api/v1/admin/users y PATCH .../block        | Ajustar             | Búsqueda q, filtro status y paginación. Bloquear exige {reason}.                                                                                                                                                                                                                    |
| GET /api/v1/admin/diagnoses                      | Ajustar             | Filtros y referencia del usuario. GET .../{id}/image devuelve una URL temporal y registra la auditoría.                                                                                                                                                                             |
| GET /api/v1/admin/models                         | Agregar             | Lista histórica de versiones usadas; añadir consulta independiente de modelo activo por capacidad desde el registro/configuración efectiva. Sin fuente activa, mostrar estado desconocido.                                                                                          |
| GET /api/v1/admin/system/status                  | Agregar             | Propuesta de agregación de solo lectura y timeouts a través de capa operativa autorizada; NO exigir que Diagnosis consulte todas las dependencias ni conectar la Management API de Rabbit al navegador.                                                                             |
| GET /api/v1/admin/audit/identity y /diagnosis    | Agregar             | Rutas segregadas por servicio propietario (Identity y Diagnosis). Revisar el enrutamiento Nginx y permisos; no implementar endpoint que cruce tablas privadas.                                                                                                                      |
| Recomendaciones del admin                        | Ajustar             | Verificar si el backend ya posee políticas versionadas y revisión humana. Evitar reemplazarlas por una sola columna source; fuente y estado de publicación deben derivar del proceso validado.                                                                                      |
| Todas las APIs                                   | Ajustar             | Errores preferidos: {code, message, request_id} + X-Request-ID. Adaptador de compatibilidad cuando el API real difiera. Nunca mostrar errores técnicos en bruto.                                                                                                                    |
| GET /api/v1/admin/models/active (ruta candidata) | Verificar / Agregar | Consultar modelo, versión y estado activos por capacidad desde la configuración real o registro. Fuente de verdad y permiso ADMIN.                                                                                                                                                  |
| Disponibilidad de políticas / recomendaciones    | Verificar / Ajustar | Respuesta explícita para AVAILABLE / CATALOG_UNAVAILABLE (nombres sujetos a contrato), fuentes y revisión. Frontend debe distinguir ausencia de recomendaciones de fallo del diagnóstico.                                                                                           |
| Consulta de reintento idempotente                | Verificar / Ajustar | Semántica para reintentos tras timeout: misma clave, mismo usuario y cuerpo devuelven id original; conflictos deterministas si cambia el cuerpo. Retención y consulta de estado documentadas.                                                                                       |
| Sanitización EXIF en backend                     | Verificar / Ajustar | El servidor decodifica y quita GPS/metadatos antes de persistir el objeto; HEIC de fallback solo se admite si lo garantiza. Pruebas con imagen EXIF deliberada.                                                                                                                     |

# 12. Asistente inteligente

## 12.1 Interfaz

- Botón flotante en las áreas autenticadas. En escritorio abre un panel lateral; en celular, una hoja inferior.

- Saludo con ejemplos: “¿Qué significa no concluyente?”, “¿Cómo tomo una buena foto?”, “Llévame a mi historial”.

- Cuando el asistente propone navegar, muestra un **botón de confirmación** (“Ir a Historial”). Nunca navega por su cuenta.

- El historial de la conversación vive solo en memoria (máximo 20 mensajes) y se borra al cerrar sesión.

- Las respuestas se muestran como texto plano.

## 12.2 Contrato

POST /api/v1/assistant/messages con {message (máx. 500 caracteres), current_route}. Responde {reply, action?: {intent}}. El backend devuelve solo intenciones permitidas para el rol de quien pregunta. El frontend tiene su propia tabla de intenciones y **ignora cualquier intención que no conozca** (8.25).

| **Intención**         | **Ruta**            | **Rol**     |
|-----------------------|---------------------|-------------|
| OPEN_HISTORY          | /historial          | USER, ADMIN |
| OPEN_NEW_DIAGNOSIS    | /diagnosticos/nuevo | USER, ADMIN |
| OPEN_ACCOUNT          | /cuenta             | USER, ADMIN |
| OPEN_NOTIFICATIONS    | /notificaciones     | USER, ADMIN |
| OPEN_HELP             | /ayuda              | USER, ADMIN |
| OPEN_ADMIN_USERS      | /admin/usuarios     | ADMIN       |
| OPEN_ADMIN_DIAGNOSES  | /admin/diagnosticos | ADMIN       |
| OPEN_ADMIN_CATALOG    | /admin/catalogo     | ADMIN       |
| OPEN_ADMIN_AUDIT      | /admin/auditoria    | ADMIN       |
| OPEN_ADMIN_MONITORING | /admin/monitoreo    | ADMIN       |

Las explicaciones de estados y de confianza se responden como texto, sin intención de navegación.

## 12.3 Seguridad y degradación

- El frontend no adjunta tokens, contraseñas, correos ni diagnósticos a Gemini. Solo mensaje y contexto mínimo autorizado; como el propio usuario podría escribir datos sensibles, se advierte que no comparta contraseñas ni información privada y el backend aplica filtros y límites antes de llamar al proveedor.

- Si un USER pide una sección de administración, la respuesta es “No tienes acceso a esa sección.” y no hay acción. Gemini interpreta; AgroDiagnóstico autoriza (9.21, 9.23).

- Gemini tendrá timeout, límites de uso, aislamiento de recursos y degradación independiente del flujo de diagnósticos. Ante 429 se informa la espera; ante error, “El asistente no está disponible ahora. Puedes seguir usando la plataforma”. ADR-014 y pruebas de fallo son obligatorios antes de declarar esta integración lista.

# 13. Catálogo de errores

Todos los textos viven en el archivo único de mensajes (D-24). El frontend decide el mensaje por code, nunca por el texto del servidor.

| **Situación**                         | **Código**                      | **Mensaje al usuario**                                                                                                                   | **Comportamiento**                                                                                          |
|---------------------------------------|---------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| Sin conexión o tiempo agotado         | Red                             | “No se confirmó el envío. Puedes reintentar. Si eliges guardar la foto en este dispositivo, podrás terminar cuando abras la aplicación.” | Conservar la misma clave idempotente; almacenamiento local solo con aceptación; sin prometer segundo plano. |
| Imagen no válida                      | 400, 422                        | “La imagen no es válida. Usa una foto JPG, PNG, WebP o HEIC de hasta 10 MB.”                                                             | Distinguir formatos, dimensiones, archivo dañado o EXIF no sanitizable según código estable.                |
| Foto demasiado grande                 | 413                             | “La foto es demasiado grande.”                                                                                                           | Reoptimiza o pide otra.                                                                                     |
| Sesión vencida                        | 401                             | “Tu sesión venció. Inicia sesión de nuevo.”                                                                                              | Intenta renovar una vez en silencio; si falla, va a login y vuelve a la ruta.                               |
| Credenciales incorrectas              | 401 en login                    | “Correo o contraseña incorrectos.”                                                                                                       | Sin indicar cuál falló.                                                                                     |
| Cuenta bloqueada                      | 403 ACCOUNT_BLOCKED             | “Tu cuenta está suspendida. Contacta al administrador.”                                                                                  | No reintenta.                                                                                               |
| Sin permiso                           | 403                             | “No tienes permiso para esta sección.”                                                                                                   | Ofrece volver al inicio.                                                                                    |
| Recurso inexistente o ajeno           | 404                             | “No encontramos ese diagnóstico.”                                                                                                        | Igual en ambos casos, para no revelar que existe (10.37).                                                   |
| No se puede cancelar                  | 409                             | “Este diagnóstico ya empezó a procesarse y no se puede cancelar.”                                                                        | Actualiza el estado en pantalla.                                                                            |
| Demasiados intentos                   | 429                             | “Hiciste demasiados intentos. Espera unos segundos e inténtalo de nuevo.”                                                                | Usa Retry-After para mostrar la cuenta regresiva.                                                           |
| Problema del servidor                 | 500, 502, 503                   | “Tuvimos un problema. Inténtalo de nuevo en unos minutos.”                                                                               | Muestra “Código de soporte” plegado con el request_id.                                                      |
| Correo ya registrado                  | 409 en registro                 | “Ya existe una cuenta con ese correo.”                                                                                                   | Enlace a iniciar sesión.                                                                                    |
| Asistente no disponible               | 429, 5xx                        | “El asistente no está disponible ahora. Puedes seguir usando la plataforma.”                                                             | El resto de la app sigue funcionando.                                                                       |
| Catálogo no disponible                | CATALOG_UNAVAILABLE (si existe) | “Todavía no contamos con recomendaciones revisadas para este resultado.”                                                                 | No improvisar tratamientos. La predicción puede seguir visible si el contrato y su estado lo permiten.      |
| Subida duplicada con distinto archivo | 409 (por contrato)              | “Esta solicitud se envió con otra foto. Inicia un diagnóstico nuevo.”                                                                    | No reutilizar la clave para otra fotografía.                                                                |

# 14. Seguridad, accesibilidad, rendimiento y diseño visual

## 14.1 Seguridad del cliente

- Access token solo en memoria; refresh en cookie httpOnly, Secure y SameSite restrictivo según entorno. Verificar protección Origin/CSRF en endpoints que utilizan cookies, rotación, expiración y revocación. Logout limpia caché y registros locales del usuario. No usar localStorage ni sessionStorage para tokens.

- IndexedDB conserva únicamente la foto optimizada, la clave idempotente, el usuario propietario y la fecha de caducidad, sin credenciales. Es almacenamiento accesible desde el perfil local del dispositivo: solicitar aceptación, permitir eliminar y limpiar al completar, cerrar sesión o vencer 24 h.

- Todo texto que viene del catálogo o del asistente se muestra como texto, sin HTML. Prohibido dangerouslySetInnerHTML.

- Nginx aplica Content-Security-Policy y cabeceras de seguridad ajustadas al despliegue real; revisar same-origin, CORS, cookies, URLs temporales y Referrer-Policy para evitar filtrar tokens de restablecimiento. Evitar scripts de terceros no necesarios.

- El cliente no registra tokens ni contraseñas en consola. Los reportes de error incluyen el request_id.

## 14.2 Accesibilidad

- Contraste WCAG AA como mínimo, texto base de 16 px y objetivos táctiles de al menos 44 px.

- Etiquetas visibles en los formularios y errores junto al campo. Foco visible y navegación completa por teclado en administración.

- Estados con icono y texto. Cambios de estado anunciados con aria-live.

## 14.3 Rendimiento y consumo de datos

- Carga diferida del área de administración, de los gráficos y de la conversión HEIC.

- Fuente del sistema (sin fuentes web). Miniaturas en el historial y carga diferida de imágenes.

- Presupuesto de JavaScript inicial del agricultor: 250 KB comprimido o menos (provisional).

## 14.4 Diseño visual

| **Token**                | **Valor**               | **Uso**                                           |
|--------------------------|-------------------------|---------------------------------------------------|
| Primario                 | \#2E7D32                | Botones principales, enlaces y estado COMPLETADO. |
| Primario oscuro          | \#1B5E20                | Títulos y estado hover.                           |
| Fondo / Superficie       | \#F6F8F5 / \#FFFFFF     | Fondo de página y tarjetas.                       |
| Texto / Texto secundario | \#1F2A24 / \#5B6B61     | Contenido y ayudas.                               |
| Borde                    | \#D5DDD3                | Separadores y campos.                             |
| Advertencia              | \#8A5300 sobre \#FFF3D6 | NO CONCLUYENTE y cobertura limitada.              |
| Error                    | \#C62828                | FALLIDO y validaciones.                           |
| Información              | \#1565C0                | PROCESANDO.                                       |

Tipografía del sistema, base de 16 px, títulos de 20 a 28 px, esquinas redondeadas de 12 px y escala de espaciado de 4 y 8 px. Verificar el contraste de cada combinación al implementar. Componentes propios clave: botón “Nuevo diagnóstico” grande, insignia de estado, barra de confianza y tabla administrativa.

# 15. Evidencia que el frontend aporta al Punto 10

| **Prueba**                     | **Qué debe verse o ejecutarse**                                                                                                                                                          |
|--------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 10.7 Procesamiento asíncrono   | PENDIENTE, PROCESANDO y COMPLETADO visibles en el detalle mediante el seguimiento.                                                                                                       |
| 10.9 y 10.39 Archivos          | Mensaje de imagen no válida para extensión falsa, archivo dañado o demasiado grande. HEIC cargado y analizado.                                                                           |
| 10.15 NO CONCLUYENTE           | Pantalla específica con consejos y botón “Subir otra foto”.                                                                                                                              |
| 10.25 DLQ                      | Diagnóstico FALLIDO con motivo general. El administrador ve el contador de la DLQ en Monitoreo.                                                                                          |
| 10.33 y 10.34 Conectividad     | Prueba E2E con red lenta, offline y reapertura: aceptar o rechazar guardado local, mismo UUID en reintentos, limpieza por expiración/logout, sin promesa de envío con navegador cerrado. |
| 10.36 RBAC                     | USER que abre /admin ve “No tienes permiso”. La API responde 403 a la misma petición.                                                                                                    |
| 10.37 IDOR                     | El usuario B abre el identificador del usuario A y ve “No encontramos ese diagnóstico”.                                                                                                  |
| 10.38 Rate limiting            | Mensaje 429 con espera en login, recuperación, diagnóstico y asistente.                                                                                                                  |
| 10.41 a 10.43 Asistente        | Una frase en lenguaje natural produce un botón de navegación. La misma frase para una sección de administración, con un USER, es rechazada.                                              |
| 10.45 Observabilidad           | El código de soporte corresponde a un request_id presente en logs del servicio propietario y no se filtran secretos.                                                                     |
| 10.56 Demostración integrada   | Guion con las pantallas 7, 8, 9, 14, 20 y el asistente, en ese orden.                                                                                                                    |
| 10.10 / 10.14 Modelo activo    | El panel distingue versión activa de versiones históricas. Un modelo candidato no aparece como activo; al faltar registro se muestra “No verificado”.                                    |
| RF-12 / Catálogo controlado    | Orientación no aprobada =\> no se publica. CATALOG_UNAVAILABLE se comunica claramente. La UI no contiene recomendaciones generadas libremente.                                           |
| 9.13 / 9.16 Privacidad EXIF    | Foto JPEG y HEIC con GPS de prueba: el objeto persistido no conserva la geolocalización; el fallback se rechaza si no puede sanitizarse.                                                 |
| 9.7 / D-04 Seguridad de sesión | Refresh en cookie, renovación/rotación, logout, verificación Origin/CSRF, acceso por roles y limpieza de datos locales.                                                                  |

Pruebas del frontend: Vitest y Testing Library para la lógica (optimización de imagen, cola local, mapeo de errores y polling) y Playwright para el flujo principal, la caída de conexión, IDOR, RBAC y el asistente.

# 16. Trazabilidad de requisitos funcionales

| **RF** | **Pantalla o elemento**                 | **RF** | **Pantalla o elemento**                       |
|--------|-----------------------------------------|--------|-----------------------------------------------|
| RF-01  | Registro                                | RF-15  | Resultado: variantes FALLIDO y NO CONCLUYENTE |
| RF-02  | Iniciar sesión, cerrar sesión y guards  | RF-16  | Historial y detalle                           |
| RF-03  | Mi cuenta (Datos y Seguridad)           | RF-17  | Historial: “Quitar del historial”             |
| RF-04  | Recuperar y restablecer contraseña      | RF-18  | Notificaciones y campana                      |
| RF-05  | Nuevo diagnóstico                       | RF-19  | Mi cuenta (Notificaciones)                    |
| RF-06  | Nuevo diagnóstico: validación y errores | RF-20  | Resultado: “¿Te sirvió?”                      |
| RF-07  | Resultado (sin selector de cultivo)     | RF-21  | Admin: Usuarios                               |
| RF-08  | Resultado                               | RF-22  | Admin: Catálogo                               |
| RF-09  | Resultado: confianza                    | RF-23  | Admin: Recomendaciones                        |
| RF-10  | Resultado: NO CONCLUYENTE               | RF-24  | Admin: Diagnósticos                           |
| RF-11  | Resultado: aviso de cobertura limitada  | RF-25  | Admin: Auditoría                              |
| RF-12  | Resultado: recomendaciones              | RF-26  | Admin: Dashboard                              |
| RF-13  | Detalle: estados y seguimiento          | RF-27  | Admin: Monitoreo                              |
| RF-14  | Detalle: cancelar en PENDIENTE          | RF-28  | Admin: Modelos y detalle de diagnóstico       |

# 17. Estructura del proyecto y etapas

## 17.1 Estructura de carpetas

> src/
>
> app/ enrutador, proveedores y guards
>
> features/
>
> auth/ diagnosis/ history/ notifications/ account/ help/ assistant/
>
> admin/ dashboard, users, diagnoses, catalog,
>
> recommendations, audit, models, monitoring
>
> shared/
>
> api/ cliente generado, manejo de errores y renovación de sesión
>
> ui/ componentes comunes
>
> lib/ optimización de imagen, cola IndexedDB, polling
>
> messages/ textos en español

## 17.2 Etapas

| **Etapa**                 | **Incluye**                                                                                                                                          | **Listo cuando**                                                                                               |
|---------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| 0\. Base técnica          | Vite + React/TypeScript, Tailwind, router, cliente OpenAPI verificado, layouts, sesiones con cookie segura, guardas, errores y pruebas mínimas.      | Login real contra Identity, ruta protegida, refresh/logout y garantías CSRF verificadas.                       |
| 1\. Flujo principal       | Registro, Inicio, Nuevo diagnóstico, vista previa y sanitización de imágenes, idempotencia, cola local consentida, detalle, seguimiento e historial. | FC-01 real de extremo a extremo; reintentos no duplican diagnósticos y fotos locales se limpian.               |
| 2\. Cuenta del agricultor | Recuperar y restablecer contraseña, Notificaciones, Mi cuenta, Ayuda, eliminación lógica, valoración de utilidad y cancelación.                      | RF-01 a RF-20 cubiertos.                                                                                       |
| 3\. Administración        | Usuarios, Catálogo, Recomendaciones controladas, Diagnósticos, Auditoría, Dashboard, Modelos activos/históricos y Monitoreo seguro.                  | RF-21 a RF-28 evidenciados con endpoints autorizados; recomendaciones solo aprobadas y modelos activos reales. |
| 4\. Asistente y acabado   | Asistente aislado, página pública, accesibilidad, estados completos, prototipos 390/1280 px, pruebas E2E y evidencia de defensa.                     | Demostración 10.56 reproducible; fallo de Gemini no afecta el diagnóstico principal.                           |

> Si el tiempo aprieta, se recortan primero los gráficos decorativos, landing y mejoras visuales secundarias. No recortar controles de seguridad, RF obligatorios, estados del diagnóstico ni revisión del catálogo. Los paneles de Modelos IA y Monitoreo pueden ser vistas simples de solo lectura o enlaces seguros siempre que RF-27/RF-28 sigan cubiertos y demostrados.

# 18. Cambios V1.1 → V1.2 y decisiones conservadas

| **Propuesta anterior**      | **Esta versión**                                                         | **Motivo**                                                  |
|-----------------------------|--------------------------------------------------------------------------|-------------------------------------------------------------|
| Mapa de pantallas           | Se mantienen 20: 5 públicas, 7 agricultor, 8 admin                       | Sin crecimiento de navegación ni más microservicios         |
| D-04 Sesiones               | Refuerzo de Origin/CSRF, rotación de refresh y limpieza local            | httpOnly/SameSite no reemplazan validación del servidor     |
| D-08 / D-27 Cola de subida  | Guardado solo consentido, reanudación al abrir y caducidad/limpieza      | No prometer trabajo en segundo plano sin PWA/service worker |
| D-13 Asistente              | Módulo candidato aislado con timeout, cuota y ADR pendiente              | Una falla Gemini no puede afectar Diagnosis                 |
| D-16 / D-26 Modelos         | Separar modelo activo real de modelos históricos                         | Último diagnóstico no determina modelo en producción        |
| D-17 / D-25 Recomendaciones | Publicación solo de fuentes revisadas; manejar CATALOG_UNAVAILABLE       | Consistencia con catálogo controlado y revisión humana      |
| D-19 Auditoría fotos        | Registrar acceso en backend y exigir URL temporal                        | El registro frontend no demuestra auditoría                 |
| D-20 Privacidad EXIF        | Sanitización en servidor antes de persistencia; HEIC fallback controlado | El original HEIC puede conservar GPS                        |
| D-21 Contratos              | Las rutas y errores son propuestas a comprobar con OpenAPI               | No asumir que Ajustar/Agregar ya existe                     |
| D-22 Idempotencia           | Clave estable por diagnóstico y validación servidor                      | Evitar duplicados tras timeout o reconexión                 |
| D-15 / D-29 Monitoreo       | Agregación operativa segura y Grafana protegido                          | No usar credenciales de infraestructura en navegador        |
| Etapas y aceptación         | Puertas de integración antes de declarar pantallas completas             | Requisito → API → prueba → evidencia                        |
| Diseño visual               | Mantener tema claro, móvil primero y cinco prototipos prioritarios       | Las referencias son orientación, no diseños finales         |
| Riesgos abiertos            | Contratos, contenido fitosanitario y pruebas reales separados            | Estado del diseño ≠ estado del software                     |

# 19. Pendientes y riesgos

- Valores provisionales. Confirmar con pruebas tamaño mínimo, lado mayor, calidad JPEG, tasa de compresión, reintentos, timeouts, duración de tokens, comportamiento con datos móviles y presupuesto JavaScript. Los valores de la V1.1 son hipótesis, no capacidad demostrada.

- Contratos reales del backend. Revisar OpenAPI y rutas de Identity, Diagnosis, Notification y AI; identificar qué existe, qué cambió y qué requiere implementar. Sin contrato no se marca una pantalla como integrada.

- Cobertura limitada (RF-11). La UI podrá mostrarla si existe respuesta verificada del backend; no se presume adaptador general ni se confunde orientación general con diagnóstico oficial.

- HEIC y EXIF. Verificar conversión en iPhone/Android y asegurar sanitización de GPS en el backend ANTES de persistir; si no hay garantía, rechazar el formato o fallback.

- ADR-014. Decidir y documentar la ubicación del módulo assistant y sus límites de recursos, red, timeout y fallos; una implementación interna en Diagnosis es candidata, no hecho confirmado.

- Referencias visuales. Los enlaces del Anexo A pueden caducar. Preparar capturas propias/prototipos de las pantallas 7, 8, 9, 13 y 14, y verificar fuentes/licencias de referencias externas para uso académico.

Contenido fitosanitario real. La orientación de tizón temprano y tardío necesita fuentes, revisión humana y activación controlada. No se considera resuelta por dibujar la pantalla. Confirmar el procedimiento de importación/activación y la semántica de CATALOG_UNAVAILABLE.

Estado de modelos. Consultar configuración/registro efectivo para cada capacidad. No inferir actividad del último diagnóstico ni declarar plagas oficialmente soportadas solo por aparecer en el catálogo.

Privacidad y retención. Definir aviso de tratamiento de fotografías, política de eliminación, purga y comportamiento de dispositivos compartidos antes de operar con usuarios reales.

# 20. Puertas de verificación para integrar el frontend

El documento es una especificación de diseño, no un acta de funcionamiento del backend. Para integrar cada pantalla deben existir contratos y evidencias comprobables. Si un contrato falla, se implementa la estructura visual con indicador de función pendiente, sin simular datos de producción.

| **Puerta**                | **Evidencia necesaria**                                                                              | **Estado en este documento**       |
|---------------------------|------------------------------------------------------------------------------------------------------|------------------------------------|
| G-FE01 Identidad y sesión | OpenAPI de login, refresh, logout; cookie, Origin/CSRF, revocación y pruebas de roles.               | Pendiente de cotejo con código     |
| G-FE02 Diagnósticos       | POST, detalle, estados, cancelación, historial, imagen y feedback; semántica exacta de idempotencia. | Pendiente de cotejo con código     |
| G-FE03 IA activa          | Modelo activo por capacidad y versión histórica por diagnóstico; contrato del registro.              | Pendiente de cotejo con código     |
| G-FE04 Orientación        | Fuentes, revisión humana, política activada, ausencia segura CATALOG_UNAVAILABLE.                    | Contenido y API por verificar      |
| G-FE05 Privacidad         | EXIF del original y del optimizado, URLs temporales, eliminación y cola local consentida.            | Pruebas pendientes                 |
| G-FE06 Observabilidad     | API/puente de solo lectura con permisos y timeouts; Grafana autorizado.                              | Arquitectura operativa por validar |
| G-FE07 UX/QA              | Prototipos móvil/escritorio y pruebas Vitest, Playwright y carga de archivos.                        | Ejecutar en implementación         |

# 21. Criterios mínimos de aceptación para la V1.2

La V1.2 estará lista para declararse implementada solo cuando la interfaz muestre información verdadera, proteja recursos y permita completar el flujo principal con pruebas repetibles. Los siguientes criterios deben verificarse en el entorno de pruebas y registrarse con capturas, logs o resultados automáticos.

| **Área**                | **Criterio de aceptación**                                                                                                                                                   |
|-------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Agricultor              | Puede registrar/iniciar sesión, cargar foto, consultar estado, resultado, recomendaciones aprobadas o su ausencia, historial y notificaciones sin exponer detalles técnicos. |
| Conectividad            | Tras timeout no se duplica diagnóstico; la foto pendiente se guarda solo bajo aceptación, se reanuda al abrir y puede eliminarse; no se promete sincronización cerrada.      |
| Inteligencia artificial | La confianza se presenta con límites claros, NO CONCLUYENTE sin clase forzada y modelo/versionado visibles; activo e histórico diferenciados.                                |
| Administración          | USER no accede a funciones ADMIN; los accesos a fotografías se autorizan y auditan; cambios del catálogo respetan políticas del backend.                                     |
| Seguridad               | Refresh y logout protegidos, cookies configuradas, EXIF eliminado en servidor, imágenes privadas, permisos y códigos de error seguros.                                       |
| Resiliencia             | Fallo del asistente/correo/Redis no se convierte en fallo del diagnóstico cuando el flujo principal puede seguir operando.                                                   |
| Evidencia               | OpenAPI de cada servicio, tests, capturas a 390 px y 1280 px y matriz RF → pantalla → endpoint → prueba → resultado.                                                         |

# Anexo A. Referencias visuales de las 20 pantallas

Se incluyen 20 referencias originales, una por cada pantalla del mapa de la sección 3. Los títulos son hipervínculos al trabajo de su autor y las direcciones URL quedan visibles para reproducibilidad. La columna «Qué aprovechar» indica el patrón de diseño pertinente, no una función nueva de AgroDiagnóstico. Se consultaron enlaces públicos el 20 de noviembre de 2026; disponibilidad futura sujeta a cada plataforma. Las referencias son inspiración visual, no diseños propios ni autorización de copia.

### 01. Página de inicio — `/`

**Referencia:** [Agriculture Landing Page](https://dribbble.com/shots/24694330-Agriculture-Landing-Page)  
**Autor/fuente:** sichika.uix · Dribbble  
**Qué aprovechar:** Hero claro, jerarquía de beneficios y CTA; sustituir contenidos comerciales por alcance papa/maíz y límites reales.

### 02. Iniciar sesión — `/login`

**Referencia:** [Modern Authentication UI · Login, Signup & Password Reset Flow](https://dribbble.com/shots/26947134-Modern-Authentication-UI-Login-Signup-Password-Reset-Flow)  
**Autor/fuente:** Mike Taylor / Orizon · Dribbble  
**Qué aprovechar:** Formulario breve, etiquetas visibles y enlace de recuperación; sin inicio con proveedores no definidos.

### 03. Registro — `/registro`

**Referencia:** [Sign Up Page Design | SaaS Registration Screen UI](https://dribbble.com/shots/27857544-Sign-Up-Page-Design-SaaS-Registration-Screen-UI)  
**Autor/fuente:** Rangan Mohanta Dibosh · Dribbble  
**Qué aprovechar:** Distribución de campos y CTA principal; añadir condiciones de tratamiento de imágenes y validación Zod.

### 04. Recuperar contraseña — `/recuperar-contrasena`

**Referencia:** [Login & Forgot Password Experience](https://dribbble.com/shots/24192564-Login-Forgot-Password-Experience)  
**Autor/fuente:** Joe Salowitz · Dribbble  
**Qué aprovechar:** Flujo de correo y confirmación neutra; no revelar si la cuenta existe.

### 05. Restablecer contraseña — `/restablecer-contrasena`

**Referencia:** [Reset password — Untitled UI](https://dribbble.com/shots/23081928-Reset-password-Untitled-UI)  
**Autor/fuente:** Jordan Hughes · Dribbble  
**Qué aprovechar:** Nueva contraseña, confirmación, enlace caducado y regreso a inicio de sesión.

### 06. Inicio del agricultor — `/inicio`

**Referencia:** [Smart Agro Dashboard](https://dribbble.com/shots/27095007-Smart-Agro-Dashboard)  
**Autor/fuente:** Nishant Baliyan · Dribbble  
**Qué aprovechar:** Tarjetas claras y CTA «Nuevo diagnóstico»; mostrar diagnósticos recientes, no métricas IoT fuera de alcance.

### 07. Nuevo diagnóstico — `/diagnosticos/nuevo`

**Referencia:** [AI plant app - Plant Disease Recognition](https://dribbble.com/shots/24643941-AI-plant-app-Plant-Disease-Recognition)  
**Autor/fuente:** Adhitya Putra / Hatypo Studio · Dribbble  
**Qué aprovechar:** Captura móvil protagonista, vista previa y progreso; adaptar a cola local, carga idempotente y estados de red.

### 08. Detalle y resultado — `/diagnosticos/:id`

**Referencia:** [Plant Doctor - Mobile App UI](https://dribbble.com/shots/25100949-Plant-Doctor-Mobile-App-UI)  
**Autor/fuente:** Adrian · Dribbble  
**Qué aprovechar:** Fotografía, condición probable y orientación ordenada; separar confianza de exactitud y mostrar aviso de catálogo.

### 09. Historial — `/historial`

**Referencia:** [Workflow History Table](https://dribbble.com/shots/24068264-Workflow-History-Table)  
**Autor/fuente:** Mao Lop / Leap AI · Dribbble  
**Qué aprovechar:** Lista paginada y filtros por estado/fecha; añadir miniatura, icono de estado y acciones seguras.

### 10. Notificaciones — `/notificaciones`

**Referencia:** [Notifications Page](https://dribbble.com/shots/24304228-Notifications-Page)  
**Autor/fuente:** Michael Engida · Dribbble  
**Qué aprovechar:** Lista legible de avisos, no leídos y acceso al diagnóstico; evitar controles ajenos al dominio.

### 11. Mi cuenta — `/cuenta`

**Referencia:** [User Profile Page | Light mode](https://dribbble.com/shots/24734994-User-Profile-Page-Light-mode)  
**Autor/fuente:** Dmitry Sergushkin · Dribbble  
**Qué aprovechar:** Pestañas Datos, Seguridad y Notificaciones; interfaz clara y edición mínima del perfil.

### 12. Ayuda — `/ayuda`

**Referencia:** [FAQ & Support · SaaS Interface · Dashboard Design](https://dribbble.com/shots/27050607-FAQ-Support-SaaS-Interface-Dashboard-Design)  
**Autor/fuente:** Diana Larussa · Dribbble  
**Qué aprovechar:** Secciones FAQ, consejos para fotografiar hojas y aclaración de confianza/NO CONCLUYENTE.

### 13. Dashboard administrativo — `/admin`

**Referencia:** [Agritech Dashboard | Agriculture Monitoring Dashboard](https://dribbble.com/shots/27490777-Smart-Agriculture-Monitoring-Dashboard)  
**Autor/fuente:** Design Monks LLC · Dribbble  
**Qué aprovechar:** Jerarquía de KPI y gráficos; adaptar a diagnósticos/estados, no incorporar irrigación/sensores.

### 14. Usuarios — `/admin/usuarios`

**Referencia:** [User Management Dashboard](https://dribbble.com/shots/25289541-User-Management-Dashboard)  
**Autor/fuente:** Stanislav · Dribbble  
**Qué aprovechar:** Tabla con estado, rol, filtros y acciones; bloqueo/reactivación con motivo y confirmación.

### 15. Supervisión de diagnósticos — `/admin/diagnosticos`

**Referencia:** [Comprehensive Data Table UI for Admin Dashboard](https://dribbble.com/shots/25499955-Comprehensive-Data-Table-UI-for-Admin-Dashboard)  
**Autor/fuente:** Lorraine J · Dribbble  
**Qué aprovechar:** Tabla densa con insignias y panel de detalle; filtros por cultivo, estado, fecha y error general.

### 16. Catálogo fitosanitario — `/admin/catalogo`

**Referencia:** [E-Commerce Admin Panel – Catalog Management Simplified](https://dribbble.com/shots/25680195-E-Commerce-Admin-Panel-Catalog-Management-Simplified)  
**Autor/fuente:** rahim · Dribbble  
**Qué aprovechar:** Patrón CRUD, búsqueda y estados activo/inactivo; sustituir productos por cultivos, enfermedades y plagas.

### 17. Recomendaciones — `/admin/recomendaciones`

**Referencia:** [CMS UI - Empowering Client Content Management](https://dribbble.com/shots/26661762-CMS-UI-Empowering-Client-Content-Management)  
**Autor/fuente:** Alessandro Benaya · Dribbble  
**Qué aprovechar:** Editor y vista previa; publicación solo bajo política fitosanitaria revisada y activada en backend.

### 18. Auditoría — `/admin/auditoria`

**Referencia:** [Audit Log Dashboard](https://dribbble.com/shots/26565969-Audit-Log-Dashboard)  
**Autor/fuente:** Nudoubt Agency · Dribbble  
**Qué aprovechar:** Tabla cronológica con actor, acción y resultado; separar auditoría Identity y Diagnosis.

### 19. Modelos IA — `/admin/modelos`

**Referencia:** [AI Ops Dashboard - Models Monitoring](https://dribbble.com/shots/27520271-AI-Ops-Dashboard-Models-Monitoring)  
**Autor/fuente:** Taras Migulko · Dribbble  
**Qué aprovechar:** Vista de modelos/versión y estado activo real; solo lectura, sin activar/retirar desde la UI.

### 20. Monitoreo del sistema — `/admin/monitoreo`

**Referencia:** [Web Monitoring Dashboard UI — SiteScope](https://dribbble.com/shots/26790985-Web-Monitoring-Dashboard-UI-SiteScope)  
**Autor/fuente:** Nurul Amin / Zendeeps · Dribbble  
**Qué aprovechar:** Tarjetas de salud, cola/DLQ y enlaces a Grafana; no duplicar observabilidad completa.


> Aviso de autoría y alcance. Todos los enlaces conducen a páginas originales de referencia (principalmente Dribbble), no a imágenes temporales de un CDN. Los derechos de cada obra pertenecen a sus respectivos autores; no reutilizar capturas ni elementos protegidos sin revisar los permisos correspondientes. Mantener los tokens y requisitos de la sección 14, y crear prototipos propios antes de programar. Algunas referencias muestran funciones fuera de alcance; no implementarlas.

## Cómo pasarle este documento a Codex

Los diseños de referencia no sustituyen una especificación verificable. Para que Codex construya pantallas coherentes y conectadas con el sistema real:

1.  Adjunta capturas propias o bocetos de las pantallas 7, 8, 9, 13 y 14 cuando tengas permiso para utilizarlos; usa los 20 enlaces originales de este anexo como guía de composición, no como código ni assets reutilizables.

2.  **Dale los tokens exactos** de la sección 14.4 (colores, tipografía, radios, espaciado) y pídele que los defina primero como variables de Tailwind.

3.  Pídele una pantalla a la vez, empezando por la 7 (Nuevo diagnóstico) y la 8 (Resultado), usando contratos OpenAPI existentes. Si un endpoint no está implementado, exige reportarlo y no inventar respuestas.

4.  **Exige estados:** vacío, cargando, error y éxito de cada pantalla, usando el catálogo de errores de la sección 13.

5.  **Pide una captura a 390 px y otra a 1280 px** de cada pantalla terminada y corrige antes de pasar a la siguiente.
