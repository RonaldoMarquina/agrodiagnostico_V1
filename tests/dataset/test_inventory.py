import copy
import csv
import hashlib
import importlib.util
import itertools
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('validate_dataset', ROOT/'scripts/validate_dataset.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
FIXTURES = Path(__file__).parent/'fixtures'


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.schema, self.classes, self.real_sources = v.validate_inventory()
        self.source_document = v.read_json(FIXTURES/'sources.json')
        self.sources = v.validate_sources(self.source_document, synthetic=True)
        with (FIXTURES/'valid.csv').open() as f:
            self.rows = list(csv.DictReader(f))

    def check_rows(self, rows, error=None, synthetic=True, sources=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'manifest.csv'
            with path.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.schema['required'])
                writer.writeheader()
                writer.writerows(rows)
            before = path.read_bytes()
            if error:
                with self.assertRaisesRegex(v.InventoryError, error):
                    v.validate_manifest(path, self.schema, self.classes, sources or self.sources, synthetic=synthetic)
            else:
                self.assertEqual(len(rows), v.validate_manifest(path, self.schema, self.classes, sources or self.sources, synthetic=synthetic))
            self.assertEqual(before, path.read_bytes(), 'El validador no debe modificar particiones ni filas')

    def test_positive_seven_classes_four_partitions(self):
        self.assertEqual(set(v.PARTITIONS), {r['split'] for r in self.rows})
        self.check_rows(self.rows)
        for row in self.rows:
            self.assertEqual(row['sha256'], hashlib.sha256(row['image_id'].encode()).hexdigest())

    def test_invalid_fields(self):
        mutations = [('sha256', 'xyz'), ('class_code', 'UNKNOWN'), ('class_code', 'NO_CONCLUYENTE'),
                     ('crop_code', 'MAIZE'), ('split', 'QUARANTINE'), ('split_group', ''),
                     ('image_id', ''), ('source', 'unregistered'), ('license', 'unknown')]
        for key, value in mutations:
            with self.subTest(field=key, value=value):
                rows = copy.deepcopy(self.rows)
                rows[0][key] = value
                self.check_rows(rows, error='fila')

    def test_each_required_field_missing(self):
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(self.schema)
        for key in self.schema['required']:
            row = dict(self.rows[0]); del row[key]
            with self.subTest(field=key):
                self.assertFalse(validator.is_valid(row))

    def test_extra_private_fields_rejected(self):
        from jsonschema import Draft202012Validator
        for field in ('image_bytes', 'user_id', 'latitude', 'longitude', 'signed_url'):
            row = dict(self.rows[0]); row[field] = 'not-allowed'
            self.assertFalse(Draft202012Validator(self.schema).is_valid(row))

    def test_every_partition_pair_for_hash_and_group(self):
        for a, b in itertools.combinations(v.PARTITIONS, 2):
            for key in ('sha256', 'split_group'):
                with self.subTest(partitions=(a, b), key=key):
                    rows = copy.deepcopy(self.rows[:2]); rows[0]['split'] = a; rows[1]['split'] = b
                    rows[1][key] = rows[0][key]
                    self.check_rows(rows, error='fuga '+key)

    def test_group_within_partition_is_allowed(self):
        rows = copy.deepcopy(self.rows[:2]); rows[1]['split'] = rows[0]['split']
        rows[1]['split_group'] = rows[0]['split_group']
        self.check_rows(rows)

    def test_duplicate_image_id_rejected(self):
        rows = copy.deepcopy(self.rows[:2]); rows[1]['image_id'] = rows[0]['image_id']
        self.check_rows(rows, error='image_id duplicado')

    def test_ineligible_source_and_synthetic_in_real_manifest(self):
        rows = copy.deepcopy(self.rows)
        rows[0]['source'] = 'plantvillage'; rows[0]['license'] = 'CC-BY-SA-3.0'
        self.check_rows(rows, error='fuente no elegible', synthetic=False, sources=self.real_sources)
        self.check_rows(self.rows, error='fixture/cuarentena', synthetic=False)
        with self.assertRaisesRegex(v.InventoryError, 'permiso no verificado'):
            v.validate_sources(self.source_document)

    def test_eligibility_requires_evidence_and_project_review(self):
        for field, value in [('evidence', []), ('evidence', ['']), ('identifier', None), ('status', 'DECLARED_BY_PUBLISHER')]:
            document = v.read_json(v.BASE/'sources.v1.json')
            document['sources'][0]['eligibility'] = 'ELIGIBLE'
            document['sources'][0]['license']['status'] = 'VERIFIED_FOR_PROJECT'
            document['sources'][0]['license'][field] = value
            with self.subTest(field=field), self.assertRaises(v.InventoryError):
                v.validate_sources(document)

    def test_unknown_is_not_zero_and_counts_require_method(self):
        for value in (None, 0, 12):
            v.validate_count(dict(value=value, reference='source', method='measured or unknown reason'), 'fixture')
        for count in [dict(value=-1, reference='source', method='x'), dict(value=True, reference='source', method='x'),
                      dict(value=12, reference='', method=''), dict(value='unknown', reference='x', method='x')]:
            with self.assertRaises(v.InventoryError):
                v.validate_count(count, 'fixture')
        for source in self.real_sources.values():
            self.assertIsNone(source['local_total']['value'])
            self.assertTrue(all(r['local']['value'] is None for r in source['counts']))

    def test_taxonomy_duplicate_retired_supported_crop(self):
        for mutation in ('duplicate', 'retired', 'supported', 'crop'):
            taxonomy = v.read_json(v.BASE/'taxonomy.v1.json')
            if mutation == 'duplicate': taxonomy['classes'][1]['class_code'] = taxonomy['classes'][0]['class_code']
            if mutation == 'retired': taxonomy['retired_codes'] = [taxonomy['classes'][0]['class_code']]
            if mutation == 'supported': taxonomy['classes'][0]['status'] = 'SUPPORTED'
            if mutation == 'crop': taxonomy['classes'][0]['crop_code'] = 'MAIZE'
            with self.subTest(mutation=mutation), self.assertRaises(v.InventoryError):
                v.validate_taxonomy(taxonomy, self.schema)

    def test_empty_and_bad_header_rejected(self):
        self.check_rows([], error='vacío')
        for header in ('image_id,sha256\n', ','.join(self.schema['required']+['sha256'])+'\n'):
            with tempfile.TemporaryDirectory() as d:
                p = Path(d)/'bad.csv'; p.write_text(header)
                with self.assertRaisesRegex(v.InventoryError, 'cabeceras'):
                    v.validate_manifest(p, self.schema, self.classes, self.sources)

    def test_cli_real_manifest_rejects_fixture_nonzero_without_mutation(self):
        before = (FIXTURES/'valid.csv').read_bytes()
        result = subprocess.run([sys.executable, str(ROOT/'scripts/validate_dataset.py'), '--manifest', str(FIXTURES/'valid.csv')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('fuente no elegible', result.stderr)
        self.assertEqual(before, (FIXTURES/'valid.csv').read_bytes())

    def test_recorded_counts_match_research_evidence(self):
        evidence = v.read_json(v.BASE/'research-evidence.v1.json')
        counts = {r['label']:r for r in evidence['plantvillage_class_trees']}
        for row in self.real_sources['plantvillage']['counts']:
            self.assertFalse(counts[row['source_label']]['truncated'])
            self.assertEqual(counts[row['source_label']]['count'], row['reported']['value'])
        for row in self.real_sources['plantdoc']['counts']:
            if row['source_label']:
                self.assertEqual(evidence['plantdoc']['target_counts'][row['source_label']], row['reported']['value'])


if __name__ == '__main__':
    unittest.main()
