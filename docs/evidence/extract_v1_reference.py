"""Extracción documental reproducible; no forma parte de la aplicación."""
from pathlib import Path
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'docs/reference/Definicion_Base_AgroDiagnostico_V1_Limpia.docx'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def extract():
    with zipfile.ZipFile(SOURCE) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        paragraphs = list(root.iter(W + 'p'))
        ids = {id(p): i for i, p in enumerate(paragraphs, 1)}
        tables = list(root.iter(W + 'tbl'))
        table_ids = {id(t): i for i, t in enumerate(tables, 1)}
        consumed = []
        lines = ['# Extracción íntegra de la definición base V1', '',
                 'Fuente: `Definicion_Base_AgroDiagnostico_V1_Limpia.docx`.',
                 'SHA-256: `' + hashlib.sha256(SOURCE.read_bytes()).hexdigest() + '`.',
                 'Orden XML conservado. P = párrafo, T = tabla; se incluyen párrafos vacíos y todas las celdas.',
                 'Texto literal, sin interpretar números ilustrativos como resultados medidos.', '']
        def walk(node):
            if node.tag == W + 'p':
                consumed.append(node)
                text = ''.join(n.text or '' for n in node.iter(W + 't'))
                lines.append(f'P{ids[id(node)]}: {text}')
            elif node.tag == W + 'tbl':
                lines.extend(['', f'## T{table_ids[id(node)]}', ''])
                for ri, row in enumerate(node.findall(W + 'tr'), 1):
                    lines.append(f'Fila {ri}')
                    for ci, cell in enumerate(row.findall(W + 'tc'), 1):
                        lines.append(f'Celda {ci}')
                        for child in cell:
                            walk(child)
                lines.extend(['Fin de tabla', ''])
            else:
                for child in node:
                    walk(child)
        walk(root.find(W + 'body'))
        assert [id(p) for p in consumed] == [id(p) for p in paragraphs]
        extras = {}
        for name in sorted(archive.namelist()):
            if name.startswith(('word/header', 'word/footer', 'word/footnotes', 'word/endnotes')) and name.endswith('.xml'):
                part = ET.fromstring(archive.read(name))
                texts = [''.join(n.text or '' for n in p.iter(W+'t')) for p in part.iter(W+'p')]
                extras[name] = texts
                lines.extend(['', '## Parte adicional: ' + name, *texts])
        unsupported = {tag: len(list(root.iter(W+tag))) for tag in ('drawing', 'txbxContent', 'altChunk', 'del', 'ins')}
        assert not any(unsupported.values()), unsupported
        pictures = list(root.iter(W + 'pict'))
        for picture in pictures:
            assert len(picture) == 1 and picture[0].tag == '{urn:schemas-microsoft-com:vml}rect'
            assert picture[0].get('{urn:schemas-microsoft-com:office:office}hr') == 't'
            assert not list(picture[0])
        lines.extend(['', f'Separadores horizontales VML sin texto: {len(pictures)}.'])
        counts = {'sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  'paragraphs': len(paragraphs), 'tables': len(tables), 'horizontal_rules': len(pictures),
                  'rows': sum(len(t.findall(W+'tr')) for t in tables),
                  'cells': sum(len(list(t.iter(W+'tc'))) for t in tables),
                  'text_nodes': len(list(root.iter(W+'t'))),
                  'nonempty_paragraphs': sum(bool(''.join(n.text or '' for n in p.iter(W+'t'))) for p in paragraphs),
                  'unsupported_content': unsupported, 'additional_parts': extras}
        return '\n'.join(lines) + '\n', counts

if __name__ == '__main__':
    content, counts = extract()
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'docs/reference/Definicion_Base_AgroDiagnostico_V1_Limpia.extraida.md'
    target.write_text(content, encoding='utf-8')
    print(json.dumps(counts, ensure_ascii=False, indent=2))
