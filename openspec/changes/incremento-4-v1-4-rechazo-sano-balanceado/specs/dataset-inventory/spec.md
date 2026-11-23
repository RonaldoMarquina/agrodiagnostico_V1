## ADDED Requirements

### Requirement: Trazabilidad y derechos mínimos por archivo

Cada archivo considerado para v1.4.0 SHALL registrar fuente, revisión, ruta original, SHA-256, licencia aplicable, autor o responsable, enlace de origen, etiqueta, unidad de agrupación, estado de revisión y decisión. Una fotografía obtenida mediante búsqueda web SHALL NOT ser admitida si falta licencia aplicable, autor, enlace de origen o SHA-256; que una URL sea pública SHALL NOT bastar como permiso.

#### Scenario: Fotografía web sin expediente completo

- **WHEN** una imagen encontrada en Internet carece de cualquiera de los cuatro elementos mínimos
- **THEN** el inventario la deja pendiente o excluida y no permite que aparezca en TRAIN, VAL o EXTERNAL

#### Scenario: Licencia común de un lote

- **WHEN** una licencia demostrablemente aplicable cubre una revisión completa de un depósito
- **THEN** cada archivo puede referenciar el mismo comprobante siempre que conserve versión, ruta y SHA-256 propios

### Requirement: PlantVillage reservado para TRAIN y VAL

v1.4.0 SHALL usar PlantVillage `color` únicamente en TRAIN/VAL y SHALL conservar `leaf_id` como unidad de grupo. Ningún `fallback_*` ni nombre de archivo SHALL convertirse por suposición en hoja independiente. Un mismo `leaf_id`, SHA-256 o duplicado visual SHALL NOT cruzar TRAIN y VAL.

#### Scenario: Varias vistas de una hoja

- **WHEN** dos imágenes PlantVillage comparten `leaf_id`
- **THEN** permanecen en la misma partición y cuentan como un grupo aunque tengan rutas y hashes distintos

#### Scenario: Grupo no verificable

- **WHEN** una imagen PlantVillage no tiene `leaf_id` respaldado por la revisión fijada
- **THEN** no puede incorporarse a los manifiestos v1.4.0

### Requirement: Auditoría y admisión de Sikkim v1 como EXTERNAL

El inventario SHALL fijar Sikkim Solanaceae Leaf Image Dataset v1 mediante DOI `10.17632/4wz7zbk635.1`, licencia CC BY 4.0 y SHA-256 del ZIP `5288c8f9d4628049ae1f827c961dc3df97167de294cec020cbce0bc19b2574dc`. SHALL reconciliar exactamente 42 imágenes `Early Blight`, 76 `Late Blight`, 50 `Healthy` y 194 imágenes de tomate/pimiento como `OTHER_CROP`; las 362 imágenes SHALL tener ruta, SHA-256 único, etiqueta fuente y decisión.

#### Scenario: Reproducción del inventario Sikkim

- **WHEN** un revisor procesa el ZIP fijado y `Annotations.xlsx`
- **THEN** obtiene los cuatro conteos aprobados, 362 imágenes decodificables, ningún hash repetido y ninguna fila de papa sin anotación

#### Scenario: El archivo publicado cambia

- **WHEN** el ZIP descargado no coincide con el SHA-256 fijado o sus conteos dejan de coincidir
- **THEN** la admisión y el sellado EXTERNAL fallan sin sustituir silenciosamente la versión

### Requirement: Independencia Sikkim limitada a imagen única

Cada imagen Sikkim SHALL usar una identidad estable derivada de su SHA-256 como unidad EXTERNAL única. El inventario y los reportes SHALL declarar que la fuente no proporciona identificador de planta, hoja, sesión o parcela y SHALL NOT describir esas unidades como independientes.

#### Scenario: Reporte de independencia externa

- **WHEN** se publica el expediente o resultado EXTERNAL
- **THEN** informa 362 imágenes únicas y señala explícitamente que no se verificó independencia por planta

#### Scenario: Intento de crear grupos de planta

- **WHEN** un proceso intenta inferir plantas independientes a partir del nombre secuencial, ruta o similitud visual
- **THEN** la validación rechaza esa agrupación y conserva solamente la unidad por imagen

### Requirement: Deduplicación frente a evidencia histórica

Antes de admitir Sikkim, el inventario SHALL comparar SHA-256 y similitud visual contra sus propios archivos y contra todos los datos locales usados o expuestos en ciclos anteriores. Una coincidencia perceptual SHALL requerir revisión visual identificada; SHALL NOT excluirse ni admitirse como duplicado automáticamente.

#### Scenario: Coincidencia exacta histórica

- **WHEN** un archivo Sikkim comparte SHA-256 con cualquier archivo histórico
- **THEN** el inventario lo excluye y registra el ciclo y partición de la coincidencia

#### Scenario: Alerta perceptual falsa

- **WHEN** dHash señala cercanía pero la revisión visual demuestra hojas, fondos o cultivos distintos
- **THEN** el expediente conserva la alerta y su resolución sin registrar un duplicado inexistente

### Requirement: EXTERNAL Sikkim sellado y aislado

Las 362 imágenes Sikkim admitidas SHALL formar una única partición EXTERNAL sellada con hash antes del entrenamiento. Sus hashes SHALL NOT aparecer en TRAIN o VAL, y EXTERNAL SHALL permanecer inaccesible para entrenamiento, validación, calibración, selección de arquitectura, estrategia de balance o umbral. Solo el comando de evaluación posterior al congelamiento SHALL poder abrirlo una vez.

#### Scenario: Intento de lectura desde selección

- **WHEN** un comando anterior al congelamiento solicita una ruta o hash Sikkim
- **THEN** el control de acceso rechaza la operación y registra el intento

#### Scenario: Sellado satisfactorio

- **WHEN** derechos, etiquetas, hashes, conteos y revisión de duplicados de las 362 imágenes están completos
- **THEN** el proceso registra el hash del manifiesto EXTERNAL y habilita únicamente su futura evaluación post-congelamiento
