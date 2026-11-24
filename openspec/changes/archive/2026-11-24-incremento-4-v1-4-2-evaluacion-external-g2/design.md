# Design

## Context

El candidato v1.4.2 está congelado en una raíz privada con digest
`07ef4eac80f59b7ca1fc42031092f3353e7e2dd89d6c8c8c17fda4865c85110a`.
El manifiesto Sikkim tiene 362 filas y SHA-256
`3c8d95e9e4d198dedf821133cb4d5f0c119a327b496396c25d4b71a493580992`;
su sello tiene SHA-256
`ab0e7e7c8a28a70a5bce4fd6424912454e2a31b31f463406233d811ed3f9a69a`
y el ZIP original `5288c8f9d4628049ae1f827c961dc3df97167de294cec020cbce0bc19b2574dc`.
La unidad de independencia disponible es archivo único, no planta. Véanse
proposal.md y la especificación del cambio para el alcance normativo.

## Goals / Non-Goals

**Goals:**

- Hacer verificable que EXTERNAL se abre una sola vez y después del freeze.
- Producir predicciones privadas completas y un resumen público sin imágenes.
- Decidir G2 exactamente con los límites aprobados y sin intervención manual en
  métricas o parámetros.

**Non-Goals:**

- Reentrenar, recalibrar, escoger otro umbral o comparar nuevos modelos.
- Reutilizar Sikkim como TEST futuro, TRAIN, VAL o fuente de depuración dirigida.
- Activar el worker, la política real o G3.
- Afirmar independencia por planta o generalización a Ayacucho.

## Decisions

### 1. Evaluador nuevo y específico para el freeze v1.4.2

Se implementará un módulo `v142_external` y un comando explícito. El preflight
validará el freeze con su cargador independiente, la identidad exacta de pesos
`e96201dc79bfd5aa99a55430f5a523f47ff91fe82d6d9de1ffc8249c06c6472c`,
configuración, preprocesado, calibración y umbral. También verificará protocolo,
manifiesto, sello y ZIP antes de leer la primera imagen. Se descarta reutilizar
un comando genérico porque podría admitir parámetros o particiones no fijados.

### 2. Lectura directa y determinista desde el ZIP sellado

Cada `source_path` del manifiesto se resolverá bajo el prefijo fijo
`Sikkim Solanaceae Leaf Image Dataset/` dentro del ZIP. Se rechazará path
traversal, entrada ausente, duplicada, directorio, tamaño o SHA diferente. Los
bytes se pasarán directamente al preprocesado congelado; no se creará una copia
extraída reutilizable. Esto reduce estado mutable y mantiene el archivo fuente
en solo lectura.

### 3. Registro de acceso antes de inferir y salida exclusiva

Tras completar todas las validaciones que no requieren abrir imágenes, el
comando creará atómicamente una raíz de salida que no puede existir previamente
y escribirá `access.json` con estado `STARTED`, hashes y propósito. La salida se
actualizará a `COMPLETED` o `FAILED_TECHNICAL`; cualquier estado previo bloquea
otra ejecución. Un fallo técnico consume la apertura y requiere una decisión
explícita de un ciclo nuevo, evitando reintentos selectivos.

### 4. Inferencia y decisión exactamente congeladas

El modelo se cargará en CPU desde `weights.safetensors`, en modo evaluación y
sin gradientes. Cada imagen usará RGB, resize bilineal directo 224×224 y
normalización ImageNet. Los logits se dividirán entre temperatura 0,50 antes de
softmax; solo los índices de ambos tizones pueden publicarse y deben alcanzar
0,80. Sano, otro cultivo y confianza inferior producen `NO_CONCLUYENTE`.

### 5. Reporte privado y resumen rastreable

`predictions.jsonl` conservará imagen por hash, etiqueta real, probabilidades,
argmax técnico, resultado visible y latencias. `external-report.json` incluirá
matriz, métricas, memoria, hashes y criterios. Un resumen sin rutas privadas ni
imágenes se incorporará a `ml/evaluation/` y `docs/evidence/`. La latencia se
reportará tanto para inferencia como para el recorrido por imagen
decodificación+preprocesado+inferencia+decisión.

### 6. Decisión G2 automática e inmutable

El evaluador calculará la conjunción de los seis criterios. Si todos pasan,
generará un acta G2 vinculada al freeze, sello y reporte, aprobada
condicionalmente por la instrucción del responsable del 2026-11-23. Si uno
falla, el acta indicará `OPEN_EXTERNAL_CRITERIA_FAILED`. En ambos casos el campo
del worker será `INACTIVE_NOT_AUTHORIZED`; no se importará ni activará política.

## Risks / Trade-offs

- [El ZIP puede contener rutas inesperadas] → cotejar todas las entradas contra
  las 362 rutas exactas y rechazar antes de registrar resultados parciales.
- [Una interrupción consume la apertura única] → completar primero hashes,
  estructura y carga del modelo; después del marcador no se reintenta sin nueva
  autorización explícita.
- [Imágenes únicas pueden estar correlacionadas] → publicar la limitación y no
  inferir independencia por planta.
- [Latencia depende del almacenamiento y host] → registrar CPU, versiones,
  hilos, RSS y definiciones de cada medición.
- [Un buen resultado puede inducir activación prematura] → G2 no activa worker,
  política ni G3; esas acciones siguen separadas.

## Migration Plan

1. Implementar y probar compuertas y cálculo con fixtures, sin montar Sikkim.
2. Verificar en un contenedor sin red el bundle y todos los hashes sellados.
3. Crear un commit local previo a la apertura con código y pruebas.
4. Montar bundle, manifiesto, sello y ZIP en solo lectura y ejecutar una vez.
5. Conservar la salida privada inmutable y publicar evidencia sanitizada.
6. Registrar G2 cerrado o abierto según la conjunción; mantener worker inactivo.

No hay rollback de la evaluación: el reporte y el registro de acceso son
históricos. Una corrección que altere inferencia o parámetros exige un nuevo
ciclo y un EXTERNAL independiente.
