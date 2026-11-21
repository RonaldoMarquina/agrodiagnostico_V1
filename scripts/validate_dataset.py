#!/usr/bin/env python3
"""Validación offline del inventario y manifiestos CSV; nunca descarga ni modifica datos."""
import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'ml/manifests'
PARTITIONS = ('TRAIN', 'VAL', 'TEST', 'EXTERNAL')
sys.path.insert(0, str(ROOT / 'ml/src'))


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


def validate_sources_v2(document, synthetic=False):
    require(document.get('schema_version') == 2, 'sources v2: versión inválida')
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
        if source['eligibility'] == 'ELIGIBLE':
            require(nonempty(lic['identifier']) and lic['evidence'], f'{sid}: elegible sin evidencia de permiso')
            expected = 'SYNTHETIC_ONLY' if synthetic else 'VERIFIED_FOR_PROJECT'
            require(lic.get('status') == expected, f'{sid}: permiso no verificado para proyecto')
        if not synthetic:
            require(sid != 'synthetic' and source['capture_context'] != 'SYNTHETIC', 'fixture en inventario real')
            if sid not in ('ayacucho_external',):
                require(source['reference'].startswith('https://') or source['reference'].startswith('docs/'), f'{sid}: referencia primaria ausente')
        for count in [source.get('reported_total'), source.get('local_total')]:
            validate_count(count, sid)
    return {s['source_id']: s for s in sources}


def validate_taxonomy_v2(taxonomy, schema):
    require(taxonomy.get('schema_version') == 2 and taxonomy.get('version') == '2.0.0', 'taxonomía v2: versión inválida')
    classes = taxonomy.get('classes', [])
    codes = [c['class_code'] for c in classes]
    require(len(codes) == 7 and len(set(codes)) == 7, 'taxonomía: siete códigos únicos requeridos')
    require(set(codes) == set(schema['properties']['class_code']['enum']), 'taxonomía/schema desalineados')
    require('NO_CONCLUYENTE' not in codes, 'NO_CONCLUYENTE no es clase')
    retired = taxonomy.get('retired_codes')
    require(isinstance(retired, list) and not set(codes) & set(retired), 'código retirado reciclado')
    require(taxonomy.get('active_protocol_version') == '1.2.0', 'taxonomía v2: protocolo activo inválido')
    require(taxonomy.get('pilot_candidate_codes') == ['POTATO_EARLY_BLIGHT', 'POTATO_LATE_BLIGHT'], 'taxonomía v2: clases piloto inválidas')
    for c in classes:
        require(c['crop_code'] in ('POTATO', 'MAIZE') and c['class_code'].startswith(c['crop_code']+'_'), 'taxonomía: cultivo incompatible')
        expected_status = 'CANDIDATE' if c['class_code'] in taxonomy['pilot_candidate_codes'] else 'OUT_OF_SCOPE_PILOT'
        require(c.get('status') == expected_status, 'taxonomía v2: alcance piloto inválido')
        require(c.get('definition_status') in ('PENDING_REVIEW', 'REVIEWED'), 'estado de revisión inválido')
        require(nonempty(c.get('name')) and nonempty(c.get('definition')) and nonempty(c.get('definition_note')), 'definición incompleta')
    return {c['class_code']: c for c in classes}


def validate_inventory_v2(base=BASE):
    schema = read_json(base / 'manifest-row.schema.json')
    Draft202012Validator.check_schema(schema)
    classes = validate_taxonomy_v2(read_json(base / 'taxonomy.v2.json'), schema)
    codes = set(classes)
    for contract in [ROOT/'contracts/schemas/common.schema.json', ROOT/'contracts/events/DiagnosisAnalyzed.v1.schema.json']:
        require(codes in list(contract_enums(read_json(contract))), f'taxonomía diverge de {contract.name}')
    document = read_json(base / 'sources.v2.json')
    sources = validate_sources_v2(document)
    require({'plantvillage', 'plantdoc', 'plantseg'} <= set(sources), 'faltan fuentes candidatas en v2')

    mappings = read_json(base / 'label-mappings.v2.json')
    require(mappings.get('schema_version') == 2, 'mappings v2: versión inválida')
    for m in mappings['mappings']:
        require(m['source'] in sources and m['class_code'] in classes, 'mapeo desconocido')
        require(m.get('status') in ('PROVISIONAL', 'UNMAPPED', 'APPROVED'), 'estado de mapeo inválido')
        require(nonempty(m.get('reference')) and nonempty(m.get('note')), 'mapeo sin evidencia/límite')

    registry = read_json(base / 'admission-registry.v2.json')
    require(registry.get('schema_version') == 2, 'admission-registry: versión inválida')
    for decision in registry.get('decisions', []):
        if decision.get('decision') == 'ADMITTED':
            require(nonempty(registry.get('reviewed_at')) and nonempty(registry.get('reviewer')), 'admission-registry incompleto')
            source = sources.get(decision.get('source_id'), {})
            require(source.get('eligibility') == 'ELIGIBLE', 'admisión sin fuente elegible')
    for source in sources.values():
        if source.get('eligibility') == 'ELIGIBLE':
            require(any(d.get('source_id') == source['source_id'] and d.get('decision') == 'ADMITTED'
                        for d in registry.get('decisions', [])), 'fuente elegible sin admisión')
    return schema, classes, sources


def validate_manifest_v2(path, schema, classes, sources, images_dir=None, synthetic=False,
                         allow_empty=True, evidence_path=None, mappings=None):
    require(not synthetic, 'validador v2 real no admite fixtures')
    count = validate_manifest(path, schema, classes, sources, synthetic=synthetic, allow_empty=allow_empty)
    if count:
        require(images_dir is not None and evidence_path is not None,
                'manifiesto no vacío exige --images-dir y --evidence privados')
        from agro_ml.data.g1_evidence import load_evidence, validate_image_evidence
        evidence, evidence_root = load_evidence(evidence_path)
        mapping_rows = mappings if mappings is not None else read_json(BASE / 'label-mappings.v2.json')['mappings']
        with Path(path).open(newline='', encoding='utf-8') as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            if not synthetic:
                require(classes[row['class_code']].get('definition_status') == 'REVIEWED',
                        'definición pendiente de revisión')
            record = evidence.get(row['image_id'])
            require(record is not None, f"{row['image_id']}: falta decisión privada por imagen")
            label = record.get('source_label')
            require(any(m.get('source') == row['source'] and m.get('class_code') == row['class_code']
                        and m.get('source_label') == label and m.get('status') == 'APPROVED'
                        for m in mapping_rows), f"{row['image_id']}: equivalencia de etiqueta no aprobada")
            try:
                validate_image_evidence(row, record, evidence_root, images_dir,
                                        sources[row['source']])
            except (ValueError, OSError) as exc:
                raise InventoryError(str(exc)) from exc
    return count


def validate_negative_manifest_v2(path, positive_path, sources, images_dir=None,
                                  evidence_path=None, allow_empty=True):
    from agro_ml.data.g1_evidence import load_evidence, validate_image_evidence
    from agro_ml.data.negatives import load_negatives_manifest, validate_negatives
    records = load_negatives_manifest(path)
    with Path(positive_path).open(newline='', encoding='utf-8') as handle:
        positives = list(csv.DictReader(handle))
    count = validate_negatives(records, positive_records=positives, allow_empty=allow_empty)
    if count:
        require(images_dir is not None and evidence_path is not None,
                'negativos no vacíos exigen --images-dir y --evidence privados')
        evidence, evidence_root = load_evidence(evidence_path)
        for record in records:
            row = record.to_dict()
            require(row['source'] in sources, f"{row['image_id']}: fuente negativa desconocida")
            try:
                validate_image_evidence(row, evidence.get(row['image_id']), evidence_root,
                                        images_dir, sources[row['source']], negative=True)
            except (ValueError, OSError) as exc:
                raise InventoryError(str(exc)) from exc
    return count


def build_g1_validation_report(positive_path, negative_path, evidence_path, positive_count,
                               negative_count):
    """Count only rows whose bytes and private evidence have already passed validation."""
    from collections import Counter
    with Path(positive_path).open(newline='', encoding='utf-8') as stream:
        positives = list(csv.DictReader(stream))
    with Path(negative_path).open(newline='', encoding='utf-8') as stream:
        negatives = list(csv.DictReader(stream))
    require(len(positives) == positive_count and len(negatives) == negative_count,
            'conteos de reporte no coinciden con validación')
    return {
        'schema_version': 1,
        'status': 'VALIDATED_ROWS_NOT_G1_APPROVAL',
        'positive_manifest_sha256': hashlib.sha256(Path(positive_path).read_bytes()).hexdigest(),
        'negative_manifest_sha256': hashlib.sha256(Path(negative_path).read_bytes()).hexdigest(),
        'evidence_sha256': hashlib.sha256(Path(evidence_path).read_bytes()).hexdigest() if evidence_path else None,
        'positive_count': positive_count,
        'negative_count': negative_count,
        'positive_by_class': dict(sorted(Counter(r['class_code'] for r in positives).items())),
        'positive_by_context': dict(sorted(Counter(r['capture_context'] for r in positives).items())),
        'negative_by_category': dict(sorted(Counter(r['negative_category'] for r in negatives).items())),
        'negative_by_context': dict(sorted(Counter(r['capture_context'] for r in negatives).items())),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, help='CSV real ya autorizado; un archivo vacío no pasa')
    parser.add_argument('--v2', action='store_true', help='Validar inventario y manifiestos versión 2')
    parser.add_argument('--images-dir', type=Path, help='Directorio opcional para comprobar bytes locales reales contra SHA-256')
    parser.add_argument('--evidence', type=Path, help='Registro privado G1 con permisos y revisión por imagen')
    parser.add_argument('--negative-manifest', type=Path, help='CSV separado de negativos autorizados')
    parser.add_argument('--report', type=Path, help='Escribir reporte privado de conteos y hashes validados (archivo nuevo)')
    args = parser.parse_args()
    try:
        is_v2 = args.v2 or (args.manifest and 'v2' in str(args.manifest))
        if is_v2:
            schema, classes, sources = validate_inventory_v2()
            manifest_path = args.manifest or BASE/'images.v2.csv'
            count = validate_manifest_v2(manifest_path, schema, classes, sources,
                                         images_dir=args.images_dir, evidence_path=args.evidence,
                                         allow_empty=args.manifest is None)
            negative_path = args.negative_manifest or BASE/'negatives.v2.csv'
            negative_count = validate_negative_manifest_v2(
                negative_path, manifest_path, sources, images_dir=args.images_dir,
                evidence_path=args.evidence, allow_empty=args.negative_manifest is None)
            if args.report:
                report = build_g1_validation_report(manifest_path, negative_path, args.evidence,
                                                    count, negative_count)
                with args.report.open('x', encoding='utf-8') as stream:
                    json.dump(report, stream, indent=2, sort_keys=True)
                    stream.write('\n')
            admitted = sum(s['eligibility'] == 'ELIGIBLE' for s in sources.values())
            reviewed = sum(c['definition_status'] == 'REVIEWED' for c in classes.values())
            print(f'PASS dataset inventory v2: {len(sources)} fuentes ({admitted} elegibles), {len(classes)} clases ({reviewed} revisadas); positivos={count}; negativos={negative_count}; validación de evidencia, no aprobación científica')
        else:
            schema, classes, sources = validate_inventory()
            count = validate_manifest(args.manifest or BASE/'images.v1.csv', schema, classes, sources, allow_empty=args.manifest is None)
            print(f'PASS dataset inventory: 3 fuentes, 7 códigos históricos y 2 clases candidatas del piloto, 21 mapeos; filas reales={count}; sin entrenamiento')
        return 0
    except (InventoryError, ValueError, KeyError, TypeError, OSError) as error:
        print(f'FAIL dataset: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
