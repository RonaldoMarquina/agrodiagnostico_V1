# Instrucciones para agentes — AgroDiagnóstico V1

## Antes de cambiar archivos

1. Lee `README.md`, la capacidad pertinente de `openspec/specs/` y el cambio activo en `openspec/changes/`.
2. Lee los documentos de `docs/` relevantes y los contratos existentes en `contracts/`.
3. Comprueba el estado real del repositorio. Nunca describas una carpeta o un plan como funcionalidad terminada.
4. Conserva archivos existentes y trabaja solo dentro del alcance solicitado. Si faltan decisiones, deja una propuesta concreta en el cambio OpenSpec o un ADR; no inventes valores de producción.

## Producto y alcance

La V1 ayuda a usuarios autenticados a cargar una imagen de papa o maíz, consultar el estado y recibir un diagnóstico probable o **NO_CONCLUYENTE**, historial y orientación de un catálogo revisado. Las siete clases del `README.md` son candidatas hasta su validación. El resultado es apoyo, no certeza ni sustituto del profesional.

- Nunca inventes una enfermedad, tratamiento o grado de certeza.
- `NO_CONCLUYENTE` es un estado, no una clase del modelo; utiliza un `reason_code` como `LOW_CONFIDENCE`, `UNSUPPORTED_CROP` o `BAD_IMAGE` cuando corresponda.
- El modelo solo aporta resultado técnico y versión. Diagnosis decide si puede publicarse y obtiene recomendaciones versionadas del catálogo.
- No incluyas dosis ni tratamientos específicos sin validación de fuentes y aprobación del catálogo.
- No entrenes automáticamente con imágenes de usuarios.
- Gemini, voz, PWA y detector de plagas son opcionales después del cierre del núcleo; no los hagas dependencias del arranque principal.

## Límites entre componentes

| Ruta | Responsabilidad |
| --- | --- |
| `frontend/` | UI React, rutas de usuario y administración, cliente tipado |
| `services/identity/` | Usuarios, sesiones, tokens y roles |
| `services/diagnosis/` | Solicitud, estados, propiedad, catálogo, resultado visible, historial |
| `services/ai_inference/` | Reclamo, inferencia técnica, versiones del modelo, publicación del análisis |
| `services/notification/` | Aviso interno, preferencias e intentos de correo |
| `ml/` | Datos autorizados, manifiestos, experimentos, evaluación y artefactos |
| `contracts/` | Definiciones OpenAPI y esquemas de eventos |
| `infra/` | Contenedores, Nginx, Cloudflare, TLS y monitoreo |

Cada servicio es dueño de sus datos y migraciones. No leas ni escribas directamente las tablas de otro servicio. No guardes los bytes de fotografías en PostgreSQL; usa objetos privados. Solo el proxy debe publicar rutas externas en producción.

## Invariantes del flujo

`PENDIENTE → PROCESANDO → COMPLETADO | NO_CONCLUYENTE | FALLIDO`; `PENDIENTE → CANCELADO`. Una transición terminal no se revierte. La cancelación solo gana antes del reclamo. Usa actualización atómica y `lease_token` para ignorar resultados tardíos.

Los eventos versionados son `DiagnosisRequested`, `DiagnosisAnalyzed` y `DiagnosisFinished`. El diagnóstico y su outbox se confirman en la misma transacción; consumidores idempotentes y publicación confirmada toleran redelivery. No incluyas imágenes, tokens ni contraseñas en mensajes. Un fallo de Redis o correo no debe perder ni revertir diagnósticos.

## Seguridad y despliegue

- Verifica permisos en cada API, incluido acceso a imagen y administración; una solicitud de un usuario a recursos ajenos recibe 404 genérico.
- Valida bytes, decodificación, límites y formato real de imágenes antes de guardar.
- Usa contraseñas Argon2id, tokens firmados con validación de firma, issuer, audience y caducidad, sesiones revocables, secretos externos y logs sin datos sensibles.
- En producción: dominio real, Cloudflare como DNS y proxy, HTTPS extremo a extremo con modo Full (strict), certificado válido en el origen y CDN de estáticos. No caches `/api/v1/*`, rutas internas ni fotos privadas.

## OpenSpec y contratos

Para un cambio de comportamiento: registra propuesta y delta de especificación en `openspec/changes/<nombre>/`; añade diseño cuando cambie arquitectura y tareas verificables. Actualiza `contracts/openapi/` o `contracts/events/` si altera interfaces, implementa y prueba; verifica y archiva según el flujo instalado de OpenSpec. No crees specs vacías para aparentar requisitos cumplidos. Las rutas, payloads y versionado definitivos se fijan en los contratos antes de integrar consumidores.

`docs/` explica decisiones y operación; `openspec/specs/` es la fuente de verdad del comportamiento vigente una vez sincronizada. Si una especificación aún no existe, consulta la línea base V1 y el cambio en curso. Un cambio de estado, evento, propiedad de datos o alcance requiere ADR en `docs/adr/` y pruebas.

## Definición de terminado

Una tarea se declara terminada cuando se puede ejecutar, tiene pruebas pertinentes positivas y negativas, respeta autorización, actualiza contratos y migraciones afectadas, conserva evidencias reproducibles y alinea OpenSpec y documentación con el código. Señala lo pendiente y las métricas no medidas; no atribuyas al MVP capacidades solo previstas.
