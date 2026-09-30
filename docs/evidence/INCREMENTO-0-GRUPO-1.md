# Verificación documental — Incremento 0, grupo 1

Fecha: 2026-09-28 (America/Lima). Cambio `incremento-0-base-integrada`, schema `spec-driven`.
Resultado: **1.1, 1.2 y 1.3 terminadas documentalmente; 3/38 total, 35 pendientes**. No se ejecutaron grupos 2–7, no se congelaron contratos ni se implementó aplicación.

## Fuente y reproducción

Documento: `docs/reference/Definicion_Base_AgroDiagnostico_V1_Limpia.docx`.
SHA-256: `b547f52658664e27497c1c1c925c72a43a93e497b6c22179b76b97fab1ecf612`.

Desde raíz:

```bash
python3 docs/evidence/extract_v1_reference.py /tmp/agro-v1-repro.md
cmp docs/reference/Definicion_Base_AgroDiagnostico_V1_Limpia.extraida.md /tmp/agro-v1-repro.md
openspec validate --all --strict --no-interactive
openspec status --change incremento-0-base-integrada
openspec list --json
```

Se volvió a calcular la extracción y se comparó exactamente con el archivo conservado: 4.060 párrafos, 3.876 no vacíos, nueve tablas, 116 filas, 292 celdas y 5.896 nodos de texto, más el pie. Notas sin texto. Los 174 elementos VML se inspeccionaron: son separadores horizontales sin texto. No hay imágenes, cuadros de texto, revisiones insertadas/eliminadas ni altChunk sin extraer.

## Verificaciones ejecutadas

| Control | Resultado | Límite |
| --- | --- | --- |
| 1.1 Fuente | Extracción reproducible y hash preservado | No se atribuye existencia a otro documento |
| 1.1 Reconciliación | 20 REC resueltas y 28 RF; párrafos de origen comprobados | RF no implementados |
| 1.2 ADR base | Contexto, alternativas, decisión, consecuencias; cuatro propietarios y coherencia D0–D3 revisados | No se ejecutaron migraciones ni infraestructura |
| 1.3 ADR interfaces | Tres eventos, estados, lease, variantes, paginación/idempotencia y matriz de incrementos revisados | Sin contratos ejecutables ni pruebas de broker |
| Seguimiento | Solo casillas 1.1–1.3 marcadas, 35 pendientes | Sin archivo/sincronización |
| Enlaces | Destinos relativos en documentos modificados/nuevos comprobados | Sin verificación de enlaces externos |
| Integridad | Hashes anteriores/posteriores comparados; solo documentación autorizada cambió | Repositorio sin commit de referencia; no atribuir SHA de commit |

Se conservaron byte a byte el DOCX, AGENTS, `docs/Incrementos.md`, `docs/ENVIRONMENT.md`, informes previos de auditoría, `scripts/verify_environment.py`, workflow Copilot, Compose, contracts, frontend, services, infra y ml. El script nuevo bajo `docs/evidence/` es una utilidad documental, no código de producto.

## Archivos modificados

- `README.md`
- `docs/AI_MODEL.md`
- `docs/API_CONTRACTS.md`
- `docs/ARCHITECTURE.md`
- `docs/DEVELOPMENT.md`
- `docs/SECURITY.md`
- `docs/TESTING.md`
- `openspec/changes/incremento-0-base-integrada/design.md`
- `openspec/changes/incremento-0-base-integrada/proposal.md`
- `openspec/changes/incremento-0-base-integrada/specs/initial-interface-contracts/spec.md`
- `openspec/changes/incremento-0-base-integrada/tasks.md`

## Archivos nuevos

- `docs/adr/0001-incremento-0-base-tecnica.md`
- `docs/adr/0002-interfaces-y-eventos-v1.md`
- `docs/evidence/extract_v1_reference.py`
- `docs/reference/Definicion_Base_AgroDiagnostico_V1_Limpia.extraida.md`
- `docs/reference/RECONCILIACION-V1.md`
- `docs/evidence/INCREMENTO-0-GRUPO-1.md` (este informe).

## Resultados OpenSpec

Comando: `openspec validate --all --strict --no-interactive` — salida 0.

```text
✓ change/incremento-0-base-integrada
Totals: 1 passed, 0 failed (1 items)

```

Comando: `openspec status --change incremento-0-base-integrada` — salida 0.

```text
Change: incremento-0-base-integrada
Schema: spec-driven
Change root: /home/ronaldo/Documentos/agrodiagnostico_V1/openspec/changes/incremento-0-base-integrada
Progress: 4/4 artifacts complete

[x] proposal
[x] specs
[x] design
[x] tasks

All planning artifacts complete!
Next: openspec instructions apply --change "incremento-0-base-integrada" --json
- Loading change status...
```

Comando: `openspec list --json` — salida 0.

```text
{
  "changes": [
    {
      "name": "incremento-0-base-integrada",
      "completedTasks": 3,
      "totalTasks": 38,
      "lastModified": "2026-09-29T01:15:29.119Z",
      "status": "in-progress"
    }
  ],
  "root": {
    "path": "/home/ronaldo/Documentos/agrodiagnostico_V1",
    "source": "nearest"
  }
}

```
