#!/usr/bin/env python3
"""Validación offline del inventario y manifiestos CSV; nunca descarga ni modifica datos."""
import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'ml/manifests'
PARTITIONS = ('TRAIN', 'VAL', 'TEST', 'EXTERNAL')


class InventoryError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InventoryError(message)


def read_json(path):
    return json.loads(Path(path).read_text())


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate_sources(document, synthetic=False):
    require(document.get('schema_version') == 1, 'sources: versión inválida')
    sources = document.get('sources')
    require(isinstance(sources, list) and sources, 'sources: lista vacía o ausente')
    seen = set()
    for source in sources:
        for field in ('source_id', 'name', 'version', 'reference', 'consulted_at',
                      'eligibility_reason', 'restrictions', 'capture_context',
                      'label_review', 'duplicates', 'exclusions'):
            require(nonempty(source.get(field)), f'source: falta {field}')
        sid = source['source_id']
        require(sid not in seen, f'source duplicada: {sid}')
        seen.add(sid)
        require(isinstance(source.get('authors'), list) and source['authors']
                and all(nonempty(x) for x in source['authors']), f'{sid}: autores ausentes')
        date.fromisoformat(source['consulted_at'])
        require(source.get('eligibility') in ('PENDING', 'EXCLUDED', 'ELIGIBLE'), f'{sid}: elegibilidad inválida')
        lic = source.get('license', {})
        require(isinstance(lic, dict) and 'identifier' in lic and isinstance(lic.get('evidence'), list), f'{sid}: licencia incompleta')
        require(all(nonempty(x) for x in lic['evidence']), f'{sid}: evidencia vacía')
        if source['eligibility'] == 'ELIGIBLE':
            require(nonempty(lic['identifier']) and lic['evidence'], f'{sid}: elegible sin evidencia de permiso')
            expected = 'SYNTHETIC_ONLY' if synthetic else 'VERIFIED_FOR_PROJECT'
            require(lic.get('status') == expected, f'{sid}: permiso no verificado para proyecto')
        if not synthetic:
            require(sid != 'synthetic' and source['capture_context'] != 'SYNTHETIC', 'fixture en inventario real')
            require(source['reference'].startswith('https://'), f'{sid}: referencia primaria ausente')
            require(all(x.startswith('https://') for x in lic['evidence']), f'{sid}: evidencia debe ser referencia primaria')
        for count in [source.get('reported_total'), source.get('local_total')]:
            validate_count(count, sid)
        require(isinstance(source.get('counts'), list), f'{sid}: counts ausente')
        for row in source['counts']:
            validate_count(row.get('reported'), sid)
            validate_count(row.get('local'), sid)
    return {s['source_id']: s for s in sources}


def validate_count(count, source):
    require(isinstance(count, dict) and 'value' in count, f'{source}: conteo ausente')
    value = count['value']
    require(value is None or type(value) is int and value >= 0, f'{source}: conteo inválido (null = desconocido)')
    require(nonempty(count.get('reference')) and nonempty(count.get('method')), f'{source}: cifra sin fuente/metodología')


def validate_taxonomy(taxonomy, schema):
    require(taxonomy.get('schema_version') == 1 and taxonomy.get('version') == '1.0.0', 'taxonomía: versión inválida')
    classes = taxonomy.get('classes', [])
    codes = [c['class_code'] for c in classes]
    require(len(codes) == 7 and len(set(codes)) == 7, 'taxonomía: siete códigos únicos requeridos')
    require(set(codes) == set(schema['properties']['class_code']['enum']), 'taxonomía/schema desalineados')
    require('NO_CONCLUYENTE' not in codes, 'NO_CONCLUYENTE no es clase')
    retired = taxonomy.get('retired_codes')
    require(isinstance(retired, list) and not set(codes) & set(retired), 'código retirado reciclado')
    for c in classes:
        require(c['crop_code'] in ('POTATO', 'MAIZE') and c['class_code'].startswith(c['crop_code']+'_'), 'taxonomía: cultivo incompatible')
        require(c.get('status') == 'CANDIDATE', 'inventario inicial no acredita soporte')
        require(c.get('definition_status') in ('PENDING_REVIEW', 'REFERENCED'), 'definición sin estado')
        require(nonempty(c.get('name')) and nonempty(c.get('definition')) and nonempty(c.get('definition_note')), 'definición incompleta')
    return {c['class_code']: c for c in classes}


def contract_enums(node):
    if isinstance(node, dict):
        if 'enum' in node and any(isinstance(x, str) and x.startswith('POTATO_') for x in node['enum']):
            yield set(node['enum'])
        for value in node.values():
            yield from contract_enums(value)
    elif isinstance(node, list):
        for value in node:
            yield from contract_enums(value)


def validate_inventory(base=BASE):
    schema = read_json(base / 'manifest-row.schema.json')
    Draft202012Validator.check_schema(schema)
    classes = validate_taxonomy(read_json(base / 'taxonomy.v1.json'), schema)
    codes = set(classes)
    for contract in [ROOT/'contracts/schemas/common.schema.json', ROOT/'contracts/events/DiagnosisAnalyzed.v1.schema.json']:
        require(codes in list(contract_enums(read_json(contract))), f'taxonomía diverge de {contract.name}')
    document = read_json(base / 'sources.v1.json')
    sources = validate_sources(document)
    require(set(sources) == {'plantvillage', 'plantdoc', 'plantseg'}, 'faltan fuentes candidatas')
    mappings = read_json(base / 'label-mappings.v1.json')
    require(mappings.get('schema_version') == 1, 'mappings: versión inválida')
    pairs = set()
    for m in mappings['mappings']:
        pair = (m['source'], m['class_code'])
        require(pair not in pairs and pair[0] in sources and pair[1] in classes, 'mapeo duplicado o desconocido')
        pairs.add(pair)
        require(m.get('status') == ('PROVISIONAL' if m.get('source_label') else 'UNMAPPED'), 'mapeo no revisado anunciado como aprobado')
        require(nonempty(m.get('reference')) and nonempty(m.get('note')), 'mapeo sin evidencia/límite')
        matching = [x for x in sources[pair[0]]['counts'] if x['class_code'] == pair[1]]
        require(len(matching) == 1 and matching[0]['source_label'] == m['source_label'], 'conteo/mapeo desalineados')
    require(pairs == {(s, c) for s in sources for c in classes}, 'faltan mapeos explícitos (incluidos desconocidos)')
    for source in sources.values():
        require(len(source['counts']) == 7, 'conteos por clase incompletos')
    external = document.get('external_ayacucho', {})
    require(external.get('availability') == 'UNAVAILABLE' and external.get('local_count') is None
            and external.get('permission_evidence') == [] and nonempty(external.get('reason')), 'Ayacucho no disponible debe ser explícito')
    return schema, classes, sources


def validate_manifest(path, schema, classes, sources, synthetic=False, allow_empty=False):
    validator = Draft202012Validator(schema)
    ids, hashes, groups = set(), {}, {}
    count = 0
    with Path(path).open(newline='') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        require(len(fields) == len(set(fields)) and set(fields) == set(schema['required']), 'CSV: se requieren exactamente diez cabeceras únicas')
        for line, row in enumerate(reader, 2):
            errors = sorted(validator.iter_errors(row), key=lambda e: str(e.path))
            require(not errors, f'fila {line}: esquema inválido' + (f' ({errors[0].message})' if errors else ''))
            require(row['class_code'] in classes and classes[row['class_code']]['crop_code'] == row['crop_code'], f'fila {line}: clase/cultivo incompatible')
            require(row['image_id'] not in ids, f'fila {line}: image_id duplicado')
            ids.add(row['image_id'])
            source = sources.get(row['source'])
            require(source is not None and source['eligibility'] == 'ELIGIBLE', f'fila {line}: fuente no elegible')
            require(row['license'] == source['license']['identifier'], f'fila {line}: licencia no coincide')
            if synthetic:
                require(row['source'] == 'synthetic' and row['capture_context'] == 'SYNTHETIC'
                        and row['label_quality'] == 'SYNTHETIC', f'fila {line}: fixture no sintético')
            else:
                require(row['capture_context'] != 'SYNTHETIC' and row['label_quality'] == 'REVIEWED', f'fila {line}: requiere revisión real; fixture/cuarentena no admitido')
            for key, seen in [('sha256', hashes), ('split_group', groups)]:
                value = row[key]
                require(value not in seen or seen[value] == row['split'], f'fila {line}: fuga {key} entre {seen.get(value)} y {row["split"]}')
                seen[value] = row['split']
            count += 1
    require(count > 0 or allow_empty, 'manifiesto vacío: solo inventario inicial permite cero filas')
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, help='CSV real ya autorizado; un archivo vacío no pasa')
    args = parser.parse_args()
    try:
        schema, classes, sources = validate_inventory()
        count = validate_manifest(args.manifest or BASE/'images.v1.csv', schema, classes, sources, allow_empty=args.manifest is None)
        print(f'PASS dataset inventory: 3 fuentes, 7 clases candidatas, 21 mapeos; filas reales={count}; sin entrenamiento')
        return 0
    except (InventoryError, ValueError, KeyError, TypeError, OSError) as error:
        print(f'FAIL dataset: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
