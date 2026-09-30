#!/usr/bin/env python3
"""Offline contract validation. Does not run HTTP handlers or broker consumers."""
import argparse
import json
from pathlib import Path
from urllib.parse import unquote, urldefrag

from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import OpenAPIV31SpecValidator

ROOT = Path(__file__).resolve().parents[1]
METHODS = {'get', 'post', 'patch', 'put', 'delete', 'options', 'head'}


def read(path):
    return json.loads(Path(path).read_text())


def resolve(node, document, boundary, trail=()):
    """Resolve local JSON pointers only; reject missing, remote and escaping refs.

    This package has no recursive schemas. Fail explicitly if one is introduced,
    rather than silently skipping its validation.
    """
    if isinstance(node, list):
        return [resolve(v, document, boundary, trail) for v in node]
    if not isinstance(node, dict):
        return node
    if '$ref' in node:
        uri, pointer = urldefrag(node['$ref'])
        if '://' in uri or uri.startswith('/'):
            raise ValueError(f'Nonlocal reference in {document.name}: {uri}')
        target = (document.parent / uri).resolve() if uri else document.resolve()
        if not target.is_relative_to(boundary.resolve()):
            raise ValueError('Reference escapes contract root')
        key = (str(target), pointer)
        if key in trail:
            raise ValueError(f'Recursive reference unsupported: {key}')
        value = read(target)
        if pointer:
            if not pointer.startswith('/'):
                raise ValueError(f'Expected JSON pointer: {pointer}')
            for segment in pointer[1:].split('/'):
                segment = unquote(segment).replace('~1', '/').replace('~0', '~')
                value = value[int(segment)] if isinstance(value, list) else value[segment]
        resolved = resolve(value, target, boundary, trail + (key,))
        siblings = {k: v for k, v in node.items() if k != '$ref'}
        if siblings:
            # Schema $ref siblings constrain, never overwrite referenced keywords.
            return {'allOf': [resolved, resolve(siblings, document, boundary, trail)]}
        return resolved
    return {k: resolve(v, document, boundary, trail) for k, v in node.items()}


def validator(schema):
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def embedded_examples(node, location='root'):
    """Validate OpenAPI parameter/header/media examples against their schema."""
    count = 0
    if isinstance(node, dict):
        if 'schema' in node:
            check = validator(node['schema'])
            if 'example' in node:
                check.validate(node['example'])
                count += 1
            for example in node.get('examples', {}).values():
                check.validate(example['value'])
                count += 1
        for k, v in node.items():
            count += embedded_examples(v, location + '/' + k)
    elif isinstance(node, list):
        for v in node:
            count += embedded_examples(v, location)
    return count


def validate_package(root):
    root = Path(root).resolve()
    documents = sorted((root / 'openapi').glob('*.openapi.json'))
    if len(documents) != 4:
        raise ValueError('Expected four service OpenAPI documents')
    operation_ids = set()
    operations = []
    examples = 0
    for path in documents:
        doc = resolve(read(path), path, root)
        OpenAPIV31SpecValidator(doc).validate()
        examples += embedded_examples(doc)
        for route, methods in doc['paths'].items():
            for method, op in methods.items():
                if method not in METHODS:
                    continue
                identifier = op['operationId']
                if identifier in operation_ids:
                    raise ValueError(f'Duplicate operationId: {identifier}')
                operation_ids.add(identifier)
                expected_status = 'implemented' if route in {'/health/live', '/health/ready'} else 'contract-only'
                if op['x-status'] != expected_status:
                    raise ValueError('Only technical health is implemented in group 4')
                if 'security' not in op:
                    raise ValueError(f'Missing explicit security: {identifier}')
                for code, response in op['responses'].items():
                    for media in response.get('content', {}).values():
                        if 'example' not in media and not media.get('examples'):
                            raise ValueError(f'Missing example: {identifier}/{code}')
                operations.append((op['x-owner'], method.upper(), route, identifier,
                                   op['x-increment'], op['x-status']))
    index = read(root / 'operations.json')
    indexed = [(v['service'], v['method'], v['path'], v['operation_id'],
                v['increment'], v['status']) for v in index]
    if len(indexed) != len(set(indexed)) or set(indexed) != set(operations):
        raise ValueError('Operation inventory differs from OpenAPI')
    schemas = sorted((root / 'schemas').glob('*.schema.json')) + sorted((root / 'events').glob('*.schema.json'))
    if len(schemas) < 5:
        raise ValueError('Missing common/event schemas')
    for path in schemas:
        validator(resolve(read(path), path, root))
    return {'openapi': len(documents), 'operations': len(operations),
            'schemas': len(schemas), 'embedded_examples': examples}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT / 'contracts')
    args = parser.parse_args()
    try:
        result = validate_package(args.root)
    except Exception as exc:
        # Do not echo instance values (which might contain a future real token).
        print(f'Contract validation FAILED: {type(exc).__name__}')
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
