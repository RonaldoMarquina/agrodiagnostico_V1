# Frontend técnico — AgroDiagnóstico

React/TypeScript: página «Entorno técnico», sin sesiones, carga, diagnóstico ni historial. Se compila con Vite y Nginx sirve los artefactos estáticos. El navegador no recibe secretos ni se conecta directamente a servicios internos.

Desde la raíz, con Node24.21.0 y npm11.19.0:

```bash
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
```

Versiones directas exactas y cierre transitivo en package-lock.json. La prueba de página renderiza el componente y verifica título, advertencia de indisponibilidad y ausencia de carga/botón de diagnóstico. El build Docker ejecuta las mismas comprobaciones antes de copiar dist a Nginx; un fallo interrumpe la imagen.

El entorno integrado se prepara según [DEVELOPMENT](../docs/DEVELOPMENT.md). La UI funcional pertenece a incrementos posteriores, no a esta página.
