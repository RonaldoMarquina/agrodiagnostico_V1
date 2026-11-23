# Design

## Context

Véase `proposal.md`. El nuevo EXTERNAL contiene 350 archivos admitidos y su
manifiesto tiene SHA-256
`20e0ba6729d08920cae3b93d914ddbaaed6c44c1f3ef6dc8b5c661700bd5e9d1`.
El preflight decodificó el lote completo con el contrato v1.4.3 y el sello
privado tiene SHA-256
`d0c76dc4b9d398cb779d71f82e9baaa250ea8a097a2d2b3ad1a8bf89efade7d1`.
Los pesos siguen siendo los de v1.4.2
`e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c`.

## Goals / Non-Goals

**Goals:**

- Demostrar que solo los artefactos aprobados pueden consumir la apertura.
- Producir una salida privada inmutable y una evidencia pública sanitizada.
- Recalcular independientemente las métricas antes de decidir G2.

**Non-Goals:**

- Reentrenar, recalibrar, cambiar el umbral o comparar candidatos.
- Reabrir Sikkim o usar resultados históricos para seleccionar parámetros.
- Ejecutar aceptación G3 real o promover el bundle rechazado.

## Decisions

### 1. Evaluador específico para el sello v1.4.3

El comando fijará en código los hashes del freeze, pesos, protocolo, contrato,
manifiesto, preflight y sello. Antes de inferir verificará también los 350
archivos bajo la raíz privada, sin aceptar argumentos que sustituyan parámetros
del modelo. Se descarta adaptar el evaluador Sikkim porque su catálogo ZIP y sus
denominadores pertenecen a una apertura histórica consumida.

### 2. Decodificación v1.4.3 sin cambio del modelo

Cada archivo se cotejará por tamaño y SHA-256 y pasará por el decodificador
v1.4.3: identificación por bytes, frame 0 para MPO, conversión explícita a RGB,
resize bilineal 224×224 y normalización ImageNet. El cambio es operacional; se
mantienen arquitectura, pesos, clase técnica, temperatura 0,50 y umbral 0,80.

### 3. Registro exclusivo antes de la inferencia

El evaluador creará atómicamente una raíz de salida inexistente y escribirá
`access.json` como `STARTED` antes de abrir la primera imagen para inferencia.
Cualquier salida previa bloquea el comando. Tanto `COMPLETED` como
`FAILED_TECHNICAL` consumen la apertura; no hay reintento selectivo.

### 4. Ejecución CPU aislada y entradas de solo lectura

La ejecución se realizará sin red, con el bundle y el lote montados en solo
lectura, modelo en evaluación, parámetros sin gradiente y contexto de
inferencia. Se registrarán runtime, CPU, hilos y memoria máxima. Se descarta
ejecutar desde un entorno con descargas habilitadas para impedir dependencias o
pesos implícitos.

### 5. Métricas reproducibles desde predicciones privadas

`predictions.jsonl` guardará SHA, estrato, probabilidades, argmax técnico,
decisión visible y latencias. Un proceso independiente verificará sus hashes y
recalculará matriz y métricas. La evidencia versionada solo contendrá agregados,
hashes y limitaciones; no incluirá imágenes ni rutas privadas.

### 6. Decisión G2 automática y cierre terminal

La decisión evaluará la conjunción exacta de los límites aprobados. El reporte
ya demostró cinco incumplimientos. El acta final separará el resultado técnico
del estado administrativo: `CLOSED_REJECTED_EXTERNAL` significa revisión G2
terminada sin aprobación; G3 será `CLOSED_NOT_PROMOTED_G2_REJECTED`. Worker y
política seguirán `INACTIVE_NOT_AUTHORIZED`.

### 7. Demostración por abstención, sin bundle

Un adaptador `demo` devolverá exclusivamente `ABSTENTION/UNSUPPORTED_CLASS`
con metadatos nulos. El perfil local `demo` arrancará ese consumidor sin montar
pesos; los workers sintéticos continuarán bajo el perfil `async-test`. El modo
real exigirá además `REAL_INFERENCE_AUTHORIZED=true`, cuyo valor por defecto y
en el perfil actual será falso. Se descarta reutilizar el simulador predictivo
como demo porque puede publicar una enfermedad y está diseñado solo para CI.

## Risks / Trade-offs

- [Una interrupción consume la apertura] → completar pruebas, hashes y carga del
  modelo antes de crear el marcador; después no reintentar.
- [El lote solo demuestra independencia por imagen] → publicar la limitación y
  no extrapolar independencia por planta o sesión.
- [Permisos privados impiden leer el bundle desde el host] → montar los
  artefactos en un proceso aislado de solo lectura sin cambiar su contenido.
- [La latencia depende del host] → registrar CPU, versiones, hilos y definición
  de las mediciones.
- [Un resultado favorable induce activación prematura] → mantener G2 separado
  de worker, política y G3.

## Migration Plan

1. Implementar y probar compuertas, mapeo visible y métricas con fixtures.
2. Verificar hashes y hacer un commit local previo a la apertura.
3. Ejecutar una sola vez sin red y con entradas de solo lectura.
4. Validar la salida desde otro proceso y publicar evidencia sanitizada.
5. Registrar G2 cerrado o abierto según la conjunción, sin activar el worker.
6. Tras la decisión del responsable, cerrar administrativamente G2 como
   rechazado y G3 como no promovido, activar solo el worker de demostración y
   conservar `ml-real` bloqueado.

No existe rollback de la evaluación. La falla queda como evidencia histórica;
este incremento no abre otro ciclo de mejora. Una futura investigación exigiría
otra decisión, otro cambio y otro EXTERNAL independiente.
