# C4 — contenedores del entorno técnico local

Alcance del grupo4 del Incremento0. APIs solo de salud; ninguna ruta de negocio funciona todavía. El host/auditoría se conserva aparte.

```mermaid
flowchart LR
  Dev[Desarrollador / navegador] -->|127.0.0.1:HTTP_PORT| Proxy[Nginx + build React]
  subgraph application[Red interna application]
    Proxy
    Identity[Identity: salud]
    Diagnosis[Diagnosis: salud]
    AI[AI Inference: salud técnica]
    Notification[Notification: salud]
  end
  subgraph persistence[Red interna persistence]
    PG[(PostgreSQL: cuatro bases)]
    S3[(SeaweedFS: objetos privados)]
    Rabbit[(RabbitMQ: volumen durable)]
    Redis[(Redis: caché derivada)]
    DBInit[Bootstrap privilegiado]
    Migrations[Cuatro migraciones one-shot]
    S3Init[Inicializador de bucket]
  end
  Identity -->|base propia| PG
  Diagnosis -->|base propia| PG
  AI -->|base propia| PG
  Notification -->|base propia| PG
  Diagnosis -->|HeadBucket autorizado| S3
  DBInit --> PG
  Migrations --> PG
  S3Init --> S3
```

Una red edge exclusiva de Nginx permite publicar loopback; las redes application/persistence siguen internas. Nginx sirve estáticos; no enruta salud, `/internal`, AI ni negocio pendiente. Las APIs comparten red application para el enrutamiento futuro, pero no tienen puertos publicados. La red persistence tampoco publica puertos. No hay conexión funcional de las APIs a RabbitMQ/Redis: las pruebas técnicas los verifican por separado.

Orden de arranque: PostgreSQL saludable → bootstrap → migración propia → API; S3 saludable → inicializador privado → Diagnosis. Nginx espera APIs saludables. Cada servicio mantiene su volumen/credencial propios según corresponda; Redis es prescindible y no requiere volumen.

La producción sigue pendiente: dominio, Cloudflare Full(strict), TLS válido hasta el origen, CDN de estáticos y controles de operación. HTTP loopback y esta página técnica no prueban despliegue público ni diagnóstico.
