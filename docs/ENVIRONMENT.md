# Entorno de desarrollo verificado

Complemento de DEVELOPMENT.md; conserva intacta la documentación previa.
Evidencia: [aceptación del 28 de septiembre de 2026](evidence/ENVIRONMENT-2026-09-28.md).

## Versiones conservadas

| Herramienta | Versión verificada | Procedencia / decisión |
| --- | --- | --- |
| Git | 2.43.0 | Ubuntu; Git local inicializado, origin configurado |
| Python | 3.12.3 | Ubuntu; python3-venv y python3-dev presentes |
| Node.js | 24.21.0 LTS Krypton | Instalación existente en nvm; fijada en .nvmrc |
| npm | 11.19.0 | Instalación existente asociada a Node |
| Docker Engine | 29.1.3 | docker.io de Ubuntu, daemon activo y habilitado |
| Docker Compose | 2.40.3 | docker-compose-v2 de Ubuntu, plugin docker compose |
| containerd / runc | 2.2.1 / 1.3.4 | Paquetes existentes Ubuntu |
| OpenSpec | 1.13.2 | @fission-ai/openspec; requiere Node >=20.19.0 |
| GCC / G++ / Make | 13.3.0 / 13.3.0 / 4.3 | build-essential existente |
| PyTorch de prueba | 2.9.1+cpu | Wheel oficial, únicamente venv temporal |

Se conserva Docker de Ubuntu; no mezclar esta instalación con docker-ce/containerd.io.
No hay necesidad actual de libpq-dev: el driver PostgreSQL y su modo de distribución
se elegirán al configurar SQLAlchemy. Si se compila un driver contra libpq, instalar
entonces libpq-dev. No se necesitan ahora toolchains ROCm, CUDA, Rust ni bibliotecas
adicionales para imágenes; reevaluar cuando se fijen dependencias reales.

## Repetir la aceptación en este equipo

Desde Bash, usando nvm ya instalado:

```bash
cd /home/ronaldo/Documentos/agrodiagnostico_V1
source "$HOME/.nvm/nvm.sh"
nvm use
node --version
npm --version
python3 --version
docker version
docker compose version
OPENSPEC_TELEMETRY=0 openspec doctor --json
OPENSPEC_TELEMETRY=0 openspec schema validate spec-driven
OPENSPEC_TELEMETRY=0 openspec validate --all --strict --no-interactive --json
agro_report_dir=$(mktemp -d /tmp/agro-report.XXXXXX)
python3 scripts/verify_environment.py --with-torch --output "$agro_report_dir/acceptance.json"
```

El script termina con 1 si alguna comprobación ejecutada está BLOQUEADO y con 0
si todas las ejecutadas pasan o corresponden a componentes pendientes. La evaluación
manual GPU se documenta en la evidencia y no se habilita por un código 0 del script.
Para repetir sin descargar/verificar PyTorch, omitir `--with-torch`; en ese caso
no se demuestra CPU PyTorch en esa ejecución. Se requieren red, PyPI, npm y Docker Hub.
Las dependencias temporales principales están fijadas; el JSON con `pip freeze`
registra transitivas observadas, pero no es un lockfile del producto.

La imagen hello-world está fijada por digest en el script. No se montan directorios,
no se publican puertos y el contenedor corre sin red. Compose se prueba con un
archivo temporal, independiente del Compose todavía vacío del proyecto.

## Recuperación solo si faltan herramientas

Estos comandos de instalación son instrucciones para reproducir la selección;
no se ejecutaron en esta auditoría porque las herramientas ya funcionaban.
Antes de usarlos, comprobar versiones con los comandos anteriores. Mantener las
actualizaciones de seguridad de Ubuntu; no fijar permanentemente paquetes del sistema.

```bash
sudo apt-get update
sudo apt-get install git python3 python3-venv python3-dev build-essential ca-certificates curl
# Solo si faltan Docker/Compose y no hay otra distribución Docker instalada:
sudo apt-get install docker.io docker-compose-v2
sudo systemctl enable --now docker
# Solo si el usuario todavía no pertenece al grupo docker:
sudo usermod -aG docker "$USER"
# Cerrar sesión e iniciarla otra vez para aplicar el grupo.
```

El acceso actual usa el grupo docker, con privilegios equivalentes a root sobre el
host; no se abrió el socket con permisos universales. No se necesita Docker Desktop.
Las contraseñas sudo se introducen en el terminal del sistema, nunca en el chat.

Con el nvm existente, solo si faltan las versiones elegidas:

```bash
source "$HOME/.nvm/nvm.sh"
nvm install 24.21.0
nvm use 24.21.0
npm install --global npm@11.19.0
npm install --global @fission-ai/openspec@1.13.2
```

No ejecutar `openspec init` ni `openspec update`: ya existe configuración y las
integraciones fueron conservadas. OpenSpec es una herramienta global de desarrollo;
las bibliotecas del producto nunca se instalan globalmente.

## Aislamiento durante los incrementos

Python 3.12 es la base del equipo. Cuando se configure un componente, crear su
propio `.venv`, declarar dependencias en su `pyproject.toml` y generar el lockfile
con la herramienta que se acuerde. En frontend, declarar dependencias en
`frontend/package.json` y generar `frontend/package-lock.json`; usar `npm ci`
cuando ese lockfile exista. No ejecutar builds ni instalaciones del scaffold vacío.
PostgreSQL, RabbitMQ, Redis, objetos S3 y Nginx se configurarán en Compose en el
Incremento 0; no se instalaron como servicios del host.

## Fuentes oficiales consultadas

- [Node LTS](https://nodejs.org/en/about/previous-releases).
- [OpenSpec: instalación](https://github.com/Fission-AI/OpenSpec/blob/main/docs/installation.md).
- [Docker: instalación Ubuntu y conflictos de paquetes](https://docs.docker.com/engine/install/ubuntu/).
- [PyTorch: instalación CPU](https://pytorch.org/get-started/locally/).
- [AMD: matriz Radeon Linux](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/native_linux/native_linux_compatibility.html).
