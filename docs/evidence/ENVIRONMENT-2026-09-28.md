# Aceptación del entorno — 2026-09-28

Ruta: `/home/ronaldo/Documentos/agrodiagnostico_V1`.
Ubuntu 24.04.5 LTS, x86_64, kernel 7.0.0-31-generic, Ryzen 7 5800XT,
16 hilos, 31 GiB RAM visibles (equipo de 32 GB), 23 GiB disponibles y 410 GiB libres.

## Resultado

Herramientas de desarrollo y ejecución CPU: LISTO para iniciar el Incremento 0.
AgroDiagnóstico: PENDIENTE DE IMPLEMENTACIÓN. GPU AMD: BLOQUEADO para
aceleración verificada, sin bloquear desarrollo ni pruebas CPU.

No fue necesario instalar herramientas del sistema ni usar sudo. Se conservaron
Git, Python, Node/npm, Docker y OpenSpec existentes. Se creó Git local en `main`
porque no existía `.git`; el remoto consultado estaba vacío (`git ls-remote
--exit-code` terminó con 2 sin salida ni errores). Se añadió `origin`, sin commit
ni push. La ejecución inicial registra el fallo Git y la final demuestra su corrección.

## Verificaciones ejecutadas

El JSON final contiene cada comando, directorio, salida completa y código de retorno.
Las categorías pendientes no son verificaciones funcionales superadas.

| Verificación | Estado | Salida |
| --- | --- | --- |
| OS | LISTO | 0 |
| Kernel | LISTO | 0 |
| Disk | LISTO | 0 |
| RAM | LISTO | 0 |
| CPU | LISTO | 0 |
| Git | LISTO | 0 |
| Compiler | LISTO | 0 |
| C++ compiler | LISTO | 0 |
| Make | LISTO | 0 |
| Git repository | LISTO | 0 |
| Python | LISTO | 0 |
| Node | LISTO | 0 |
| npm | LISTO | 0 |
| Docker daemon | LISTO | 0 |
| Docker startup | LISTO | 0 |
| Docker active | LISTO | 0 |
| Compose | LISTO | 0 |
| Docker smoke | LISTO | 0 |
| Docker image digest | LISTO | 0 |
| OpenSpec version | LISTO | 0 |
| OpenSpec changes | LISTO | 0 |
| OpenSpec specs | LISTO | 0 |
| OpenSpec doctor | LISTO | 0 |
| OpenSpec schema | LISTO | 0 |
| OpenSpec templates | LISTO | 0 |
| OpenSpec artifacts | PENDIENTE DE IMPLEMENTACIÓN | 0 |
| GPU PCI | LISTO | 0 |
| Project Compose | PENDIENTE DE IMPLEMENTACIÓN | 0 |
| Python venv | LISTO | 0 |
| Python package install | LISTO | 0 |
| Python import | LISTO | 0 |
| OpenSpec config YAML | LISTO | 0 |
| PyTorch CPU install | LISTO | 0 |
| PyTorch CPU tensor and autograd | LISTO | 0 |
| Temporary Python dependencies | LISTO | 0 |
| npm execution | LISTO | 0 |
| npm registry | LISTO | 0 |
| Compose smoke | LISTO | 0 |
| Frontend, microservices, contracts, migrations, tests and application CI | PENDIENTE DE IMPLEMENTACIÓN | — |
| PostgreSQL, RabbitMQ, Redis, S3 and Nginx | PENDIENTE DE IMPLEMENTACIÓN | — |
| Public domain, Cloudflare, TLS and CDN | PENDIENTE DE IMPLEMENTACIÓN | — |

OpenSpec doctor informa `healthy: true`; el esquema instalado `spec-driven` es válido;
la configuración del proyecto es YAML válido con contexto y esquema esperados.
`validate --all --strict --no-interactive --json` informa cero elementos, cero
aprobados y cero fallidos. No se crearon specs para producir un resultado artificial.
La validación del esquema instalado y el parseo YAML no equivalen a validar requisitos inexistentes.

Compose del proyecto conserva `services: {}`. Su comando de validación se registra,
pero un archivo sin servicios no demuestra PostgreSQL, Redis, RabbitMQ, S3 ni Nginx.
Los dos contenedores hello-world terminaron con código 0 usando Docker y Compose.
Una consulta final no encontró contenedores hello-world residuales. No se borraron
imágenes, contenedores ni volúmenes ajenos. La imagen descargada queda en caché.

## GPU y CPU

PCI `1002:73df`, subsistema `1043:05c9`, familia Navi 22, controlador `amdgpu`.
VRAM reportada: 12868124672 bytes, aproximadamente 12 GiB. Es consistente con la
RX 6700 XT indicada por el usuario; el nombre PCI agrupa varios modelos y no
identifica de forma exclusiva esa variante.

No existen paquetes ROCm/HIP detectados, ni herramientas rocminfo/rocm-smi en PATH.
`/dev/kfd` existe pero el usuario no puede leerlo ni escribirlo; renderD128 sí es
accesible. No se cambiaron grupos, controladores ni permisos de dispositivos.

La [matriz Radeon de AMD para ROCm 7.2.1](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/native_linux/native_linux_compatibility.html)
no lista RX 6700 XT y documenta Ubuntu 24.04.4/kernel 6.17, distintos del host.
Esa página advierte que desde Core SDK 7.13.0 la documentación está unificada.
La consulta a la matriz unificada devolvió HTTP 429: no se afirma haber descartado
todas las versiones posteriores. Compatibilidad GPU actual no demostrada.
Falta confirmar una combinación GPU/OS/kernel/ROCm/PyTorch oficialmente soportada,
resolver el acceso KFD y ejecutar una prueba real en GPU antes de habilitarla.

PyTorch 2.9.1+cpu, instalado únicamente en un venv temporal, importó y calculó
el gradiente de x² en x=2: resultado 4.0 en CPU. No se entrenó ningún modelo.
La base de cómputo permite comenzar trabajo ML en CPU; el pipeline, sus dependencias
y el rendimiento del entrenamiento todavía están pendientes. Apareció un aviso
por ausencia de NumPy en ese entorno mínimo; no se probó interoperabilidad NumPy.
No se instaló PyTorch globalmente ni en los servicios. El venv se eliminó al finalizar.

## Pendientes

- Primer cambio OpenSpec del Incremento 0, contratos, CI, servicios Compose,
  migraciones, pruebas y builds reales.
- Definir y fijar dependencias/lockfiles aislados al configurar cada componente.
- Primer commit y publicación en GitHub; no son parte de la prueba del host.
- GPU condicionada a compatibilidad y prueba; no es requisito para empezar.
- Dominio, Cloudflare, TLS y CDN: PENDIENTE DE IMPLEMENTACIÓN hasta despliegue público.
- El sandbox del agente falló con bubblewrap antes de ejecutar comandos; se usó
  ejecución autorizada fuera del sandbox. Esto no es un fallo de las herramientas del host.
