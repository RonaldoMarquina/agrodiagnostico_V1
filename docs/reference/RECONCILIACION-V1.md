# Reconciliación de la fuente V1 — grupo 1 del Incremento 0

Fecha: 2026-09-28 (America/Lima). Cambio: `incremento-0-base-integrada`.
Estado: revisión documental; ningún RF se declara implementado ni probado en ejecución.

## Fuente y alcance de lectura

Fuente entregada explícitamente por el responsable para esta reconciliación: [Definicion_Base_AgroDiagnostico_V1_Limpia.docx](Definicion_Base_AgroDiagnostico_V1_Limpia.docx). Título interno: «Definición Base del Proyecto – AgroDiagnóstico V1»; sección 3: requisitos funcionales consolidados V1.0. Metadatos DOCX: revisión 3, modificación `2026-09-28T01:43:00Z`. Identidad exacta SHA-256: `b547f52658664e27497c1c1c925c72a43a93e497b6c22179b76b97fab1ecf612`.

Se leyó el contenido completo de las secciones 1–10, incluidas sus nueve tablas: actores, RF, flujos, tecnologías, problemas/soluciones, registro ilustrativo de modelos, RBAC, comparación ilustrativa de modelos y trazabilidad. La [extracción íntegra](Definicion_Base_AgroDiagnostico_V1_Limpia.extraida.md) conserva orden, párrafos P1–P4060, filas y celdas. Hay 3.876 párrafos no vacíos, 116 filas y 292 celdas; el pie también se extrae. Las notas no contienen texto; 174 elementos VML son separadores horizontales, sin imágenes o texto oculto. El [extractor documental](../evidence/extract_v1_reference.py) comprueba esa estructura.

El documento se denomina **definición base** y en P3/P4060 menciona además una «especificación detallada». No se afirma disponer de un segundo documento. La instrucción explícita del responsable identifica este archivo como fuente V1 completa para el grupo 1: se reconcilia su contenido real, sin reconstruir ni inventar otra fuente. El nombre anterior mencionado en el editor no se utiliza. Una futura fuente distinta exigirá otra revisión.

## Documentos y artefactos contrastados

`AGENTS.md`, README, CONTRIBUTING; `docs/ARCHITECTURE.md`, `API_CONTRACTS.md`, `AI_MODEL.md`, `SECURITY.md`, `DEVELOPMENT.md`, `DEPLOYMENT.md`, `TESTING.md`, `ENVIRONMENT.md`, `Incrementos.md` e informe de auditoría del 28/09; propuesta, diseño, tareas y los cinco deltas del cambio. `openspec/specs/` y `contracts/` siguen sin contenido funcional; no hay consumidores existentes a los que migrar.

La evidencia del host se conserva como registro histórico, incluida su observación de que antes faltaba la fuente. La tabla/notas del editor en `Incrementos.md` no sustituyen el DOCX. Las decisiones siguientes resuelven diferencias documentales; sus pruebas de comportamiento se mantienen en incrementos posteriores.

## Matriz de discrepancias y resolución

| ID | Fuente exacta | Diferencia observada | Resolución y destino | Estado |
| --- | --- | --- | --- | --- |
| REC-01 | P1–3, P4060 | El plan dice fuente ausente y usa otro título | Fuente identificada por entrega explícita, revisión y hash arriba; actualizar README, propuesta y diseño. No atribuir existencia a otro DOCX | Resuelta |
| REC-02 | RF-07, §1.2 P11, §8.21 | Markdown/delta no explicitan cultivo automático | La carga no exige cultivo; AI lo intenta identificar; desconocido no se inventa. Añadido a API, AI_MODEL, diseño y CTR-01; prueba funcional incremento 4 | Resuelta |
| REC-03 | RF-03/04, §6.2.2 P502–515 | `/users/me` y `/password/forgot|reset` frente a `/profile` y `/password-recovery`; faltan cambio y confirmación | §6.2.2 declara rutas conceptuales ajustables. Conservar nombres del inventario local y registrar equivalencias, cambio de contraseña y confirmación como operaciones obligatorias antes del consumidor del incremento 1. Sin OpenAPI en grupo 1 | Resuelta |
| REC-04 | RF-20, §8.34 | Feedback omitido en resúmenes | Diagnosis posee feedback útil/no útil vinculado al propietario; no es etiqueta ML. Inventariar obligación para incremento 2 y UI 5, ruta/payload en su contrato previo; sin agregar implementación al Incremento 0 | Resuelta |
| REC-05 | §6.3.2, §6.5.2 | Estado separado, lectura de aviso y preferencias con rutas diferentes | Detalle puede incluir estado; conservar preferencias del inventario, registrar equivalencia y lectura de aviso como obligación futura; administración conceptual se inventaría, no se publica un wildcard | Resuelta |
| REC-06 | §6.8 P749; §7.11 | AI no necesita base **de negocio** inicialmente; diseño usa cuatro bases | Mantener cuarta base exclusivamente técnica para revisión Alembic, luego trabajos/inferencia/outbox. No duplicar diagnóstico publicable ni acceder a tablas de Diagnosis. Refinamiento permitido por la excepción técnica del P749 y outbox; ADR de base | Resuelta |
| REC-07 | RF-18 frente a §6.7 P739 | RF enumera COMPLETADO/NO CONCLUYENTE, flujo también FALLIDO | Lista RF es mínimo, no exclusión. Adoptar los tres terminales notificables del flujo detallado; CANCELADO no emite Finished. Ya coincide con ARCHITECTURE y CTR-03; ADR de eventos | Resuelta |
| REC-08 | §2.5, §10.7/10.8 | «NO CONCLUYENTE» y `NO_CONCLUYENTE` coexisten | Identificador de API/evento es `NO_CONCLUYENTE`; etiqueta humana puede llevar espacio. No es clase; reason_code obligatorio para abstención visible | Resuelta |
| REC-09 | §5.1.7 P316, §8.22 | Orientación general podría interpretarse como diagnóstico externo | Aplicar límite explícito §1.2/RF-11/§8.22 y AGENTS: recaptura y explicación de cobertura; ningún diagnóstico ni tratamiento fuera de clases validadas | Resuelta |
| REC-10 | §8.1/8.28 frente a §8.3/8.5/8.36/8.37 y §10.63 | Pasajes generales parecen incluir plagas/Gemini en V1 | Secciones explícitas de alcance prevalecen: plagas, Gemini, voz, PWA opcionales posteriores. Catálogo puede representar plagas experimentales, sin activar inferencia o soporte | Resuelta |
| REC-11 | §9.12, §9.47 P2913, §10.9 | DOCX prevé HEIC/HEIF; SECURITY condiciona al conversor y diseño solo menciona JPEG/PNG/WebP | Mantener HEIC/HEIF como objetivo de V1, implementación en incremento 2 y E2E antes de anunciar soporte/cerrar V1. Rechazo controlado mientras no se soporte; no eliminar el objetivo ni fingir aceptación. Actualizar SECURITY, TESTING, diseño y CTR-01 | Resuelta |
| REC-12 | RNF-CON01, §9.13/9.46 | ~10 MB frente a 10 MiB y 24 MP del resumen | 10 MiB/24 MP son parámetros iniciales propuestos, no valores validados de producción. Contrato deberá declarar bytes/dimensiones exactos. Optimización ~1 MB es objetivo experimental, no condición fija | Resuelta |
| REC-13 | RNF-RES02, §7.8, §10.24 frente al diagrama §10.25 | Tres flechas Retry pueden sugerir cuatro intentos | Texto normativo explícito: tres intentos totales, inicial + dos reintentos. Diagrama ilustrativo no redefine política; fallos permanentes no se reintentan | Resuelta |
| REC-14 | §6.4.5, §9.27, §10.46 | `/health` conceptual y modelo listo frente a salud sin modelo del incremento 0 | `/health/live` y `/health/ready` son separación adoptada. Readiness del scaffold no acredita worker de inferencia; al incorporar modelo debe exigir carga del artefacto. Tabla D2 permanece limitada al incremento 0 | Resuelta |
| REC-15 | §8.29 frente a API_CONTRACTS | `crop/predicted_class/confidence/model_name/inference_time/status` frente a nombres técnicos | Mapeo explícito en ADR; outcome técnico separado de estado publicable; clase/cultivo desconocidos admiten ausencia semántica sin inventar valores. `capability` implícita en v1 de enfermedades; extender requiere contrato versionado | Resuelta |
| REC-16 | AGENTS y API_CONTRACTS frente a `lease_token` requerido | Prohibición de tokens podría eliminar fencing | Prohibidos tokens de autenticación; lease_token es identificador opaco de concurrencia, nunca credencial autónoma. Reclamo/renovación/imagen requieren identidad de servicio; ADR y API aclaran | Resuelta |
| REC-17 | §8.7 frente a §1.4 y DATA-01 | «Será utilizado» no demuestra permisos/datos disponibles | Todas las fuentes siguen candidatas hasta verificar licencia, correspondencia y conteos; no descargar ni entrenar en grupo 1; tablas de modelos/métricas son ejemplos | Resuelta |
| REC-18 | §4.9 frente a §7.22 y §9.36–38 | Observabilidad primero candidata, luego seleccionada | Stack seleccionado Prometheus/Grafana/OTel, completo en incremento 5; salud/CI en 0. No añadir dashboards al arranque obligatorio actual | Resuelta |
| REC-19 | §9.48, §10.57 | Compose HTTP local podría confundirse con cierre público | Dominio real, Cloudflare Full (strict), TLS origen y CDN siguen obligatorios en incremento 5; ENV local no demuestra CF-01…06 | Resuelta |
| REC-20 | §10.59 y carpetas vacías | Lista ilustrativa ADR-001…013 no corresponde a archivos existentes | Crear solo dos ADR reales del grupo 1 con numeración local y enlaces, sin generar trece documentos vacíos | Resuelta |

## Trazabilidad funcional completa

Fuente de todos los IDs: tabla T2, §3 V1.0. P indica el párrafo literal del requisito. «Prueba prevista» no significa ejecución; todos los RF permanecen **pendientes de implementación/validación**. CTR documenta interfaces, no cumple el RF.

| RF | P | Contenido | Responsable / incremento | Prueba prevista y relación con incremento 0 |
| --- | --- | --- | --- | --- |
| RF-01 | P68 | Registro sin duplicar correo | Identity / 1 | Registro válido y duplicado; CTR-01/02 |
| RF-02 | P70 | Login/logout y roles | Identity y APIs / 1 | Sesión válida/revocada, USER vs ADMIN; CTR-02 |
| RF-03 | P72 | Perfil y cambio de contraseña | Identity / 1 | Cambio autorizado, credencial inválida y acceso ajeno; REC-03 |
| RF-04 | P74 | Recuperación con correo | Identity + adaptador correo / 1 | Token válido/usado/expirado, fallo correo sin enumeración; REC-03 |
| RF-05 | P76 | Carga de fotografía | Diagnosis / 2 | 202 autenticado, 401 anónimo; CTR-01/02 |
| RF-06 | P78 | Validación y recaptura | Diagnosis / 2 | Formatos válidos, corruptos, exceso y HEIC/HEIF con conversor; REC-11 |
| RF-07 | P80 | Cultivo automático | AI / 4; carga / 2 | Sin selección obligatoria, cultivo ajeno no inventado; REC-02 |
| RF-08 | P82 | Siete clases candidatas | ML + AI / 4 | Evaluación por clase y fuera de cobertura; DATA-01…03 |
| RF-09 | P84 | Resultado y confianza | AI + Diagnosis / 4; UI / 5 | Score no presentado como certeza; CTR-03 |
| RF-10 | P86 | Baja confianza | Diagnosis + ML / 4 | Abstención calibrada y recaptura; CTR-03 |
| RF-11 | P88 | Fuera de cobertura | Diagnosis + ML / 4 | Sin enfermedad ni tratamiento; REC-09 |
| RF-12 | P90 | Catálogo controlado | Diagnosis / 2–4 | Recomendación versionada solo concluyente; CTR-03/04 |
| RF-13 | P92 | Asincronía y estado | Diagnosis + AI / 2–3 | 202 antes de inferir, recuperación broker; CTR-04 |
| RF-14 | P94 | Cancelación pendiente | Diagnosis / 2–3 | Carrera claim/cancel, 200/409; CTR-02 |
| RF-15 | P96 | Reintentos y causa general | AI + Diagnosis / 3 | Tres intentos, DLQ, sin excepciones sensibles; CTR-04 |
| RF-16 | P98 | Historial/detalle | Diagnosis / 2 | Paginación propia, A/B 404; CTR-02 |
| RF-17 | P100 | Borrado lógico | Diagnosis / 2 | Idempotencia, exclusión historial, acceso ajeno; CTR-02 |
| RF-18 | P102 | Aviso y correo | Notification / 5 | Finished repetido, proveedor caído, terminales; REC-07 |
| RF-19 | P104 | Preferencias/entregas | Notification / 5 | Preferencia propia/ajena, estado de intento; CTR-01 |
| RF-20 | P106 | Utilidad del resultado | Diagnosis / 2; UI / 5 | Propietario permite/no permite, sin reentrenar; REC-04 |
| RF-21 | P108 | Bloqueo/reactivación | Identity / 1 | ADMIN autorizado/USER denegado y revocación; REC-03 |
| RF-22 | P110 | Catálogo administrable | Diagnosis / 2 | Activar/desactivar con RBAC; plaga experimental no soportada; REC-10 |
| RF-23 | P112 | Recomendaciones administrables | Diagnosis / 2 | Mutación auditada, snapshot histórico; CTR-04 |
| RF-24 | P114 | Supervisión diagnósticos | Diagnosis / 2; UI / 5 | ADMIN autorizado, USER denegado, error general; CTR-02 |
| RF-25 | P116 | Auditoría | Servicio dueño / 1–3; consulta / 5 | Actor/fecha/cambio sin secretos; CI-02 |
| RF-26 | P118 | Métricas de uso | Diagnosis + observabilidad / 5 | Contadores reales y protección de paneles; no medida en 0 |
| RF-27 | P120 | Salud y pendientes | APIs / 0; administración / 5 | live/ready 200/503 y supervisión autorizada posterior; ENV-02 |
| RF-28 | P122 | Versión de modelo | AI + Diagnosis / 3–4; UI / 5 | Versión persistida y consultable; modelo simulado identificado; CTR-03 |

## Cobertura de las diez secciones y RNF

| Fuente | Contraste y conclusión | Verificación futura |
| --- | --- | --- |
| §1–3, tablas T1/T2 | Alcance, actores y 28 RF trazados arriba; omisiones resueltas | Matriz RF con positivos/negativos y autorización |
| §4.1 REN01–04, §4.2 ESC01–04 | Coincide con TESTING: p95 500 ms/2 s/30 s, carga progresiva; metas no mediciones | Carga y 1/N workers en 5, modelo en 4 |
| §4.3 DIS01–02, §4.4 RES01–07 | Recuperación/degradación, tres intentos; ENV y CTR refinan | Salud en 0; fallos distribuidos en 3/5 |
| §4.5 SEG01–10 | Coincide con SECURITY y AGENTS: permisos, secretos, archivos, proxy | Aislamiento en 0; auth/IDOR/archivos en 1–2/5 |
| §4.6 USA01–03, §4.7 CON01–03 | Cultivo automático y conectividad explicitados; PWA opcional | Recaptura y red limitada en 2/5 |
| §4.8 MAN01–05 | Cuatro servicios, adapters, versiones y CI concordantes | CTR/MIG/CI en 0; sustitución modelo en 4 |
| §4.9 OBS01–06 | Salud inicial no sustituye observabilidad completa | ENV-02 en 0; trazas/métricas/alertas en 5 |
| §4.10 COS01–03, §4.11 POR01–03 | CPU, contenedores, configuración externa, sin promesas de costo cero | Builds y consumo observado, ENV/CI |
| §4.12–13 y §5, tabla T3 | Flujos y fallos coinciden; REC-09/13 resuelven ambigüedad | T-01…T-12 de TESTING en incrementos correspondientes |
| §6 y §7, tablas T4/T5 | Propiedad, APIs conceptuales, stack; REC-03…08/14–16 | ADR de base e interfaces; contratos después |
| §8, tabla T6 | Clases candidatas, datos autorizados y versionado; ejemplos no artefactos reales | DATA en 0, experimentos/test en 4 |
| §9, tabla T7 | RBAC, privacidad, HEIC/HEIF, producción CF; REC-11/19 | Seguridad, formatos y CF-01…06 antes del cierre público |
| §10, tablas T8/T9 | Pruebas, evidencias, ADR y gobierno concordantes; no hay mediciones aún | CI en 0; validación funcional/ML/operacional en 1–5 |

## Cierre documental

No quedan discrepancias de interpretación abiertas para el grupo 1. Las decisiones futuras explícitas (payloads definitivos, algoritmo/expiraciones JWT, parámetros de producción, proveedor, licencia de datos y modelo) no se dan por resueltas: ya están asignadas a contratos o incrementos previos a sus consumidores. Ningún endpoint, esquema JSON ni tabla de negocio se crea en esta revisión.

Decisiones que formalizan el resultado: [ADR de base](../adr/0001-incremento-0-base-tecnica.md) y [ADR de interfaces/eventos](../adr/0002-interfaces-y-eventos-v1.md). Su existencia y verificación son las tareas 1.2 y 1.3, distintas de esta reconciliación.
