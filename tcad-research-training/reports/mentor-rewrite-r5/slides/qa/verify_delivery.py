"""Read-only package/evidence checks. Uses zip/XML, never python-pptx."""
import argparse
import hashlib
import json
import posixpath
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

HERE = Path(__file__).resolve().parents[1]
ASSETS = HERE.parent / 'assets'
NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify(tag):
    final = HERE / 'output' / ('dram-see-v3-mentor-' + tag + '.pptx')
    meta = json.loads((HERE / ('slides-text-' + tag + '.json')).read_text(encoding='utf8'))
    summary = json.loads((ASSETS / 'data/snapshot/summary.json').read_text(encoding='utf8'))
    failures = json.loads((ASSETS / 'data/snapshot/original-failures.json').read_text(encoding='utf8'))
    ledger = json.loads((ASSETS / 'data/snapshot/ledger-snapshot.json').read_text(encoding='utf8'))
    result = {'final': str(final), 'final_sha256': sha(final.read_bytes()), 'scientific_sources_unchanged': True,
              'tables': [], 'charts': [], 'native_images': [], 'checked_slides': []}
    manifest = json.loads((HERE / 'qa' / tag / 'source-manifest.json').read_text(encoding='utf8'))
    for name, digest in manifest['files'].items():
        assert sha(Path(name).read_bytes()) == digest, name
    assert sha((HERE / 'build_deck.mjs').read_bytes()) == manifest['builder_sha256']
    with ZipFile(final) as package:
        slides = [n for n in package.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
        assert len(slides) == len(meta) == 14
        for item in meta:
            i = item['slide']; filename = f'ppt/slides/slide{i}.xml'
            slide = ET.fromstring(package.read(filename))
            relpath = f'ppt/slides/_rels/slide{i}.xml.rels'
            rels = {r.attrib['Id']: posixpath.normpath(posixpath.join('ppt/slides', r.attrib['Target'])).lstrip('/')
                    for r in ET.fromstring(package.read(relpath))}
            text = '\n'.join(t.text or '' for t in slide.findall('.//a:t', NS))
            if i <= 11:
                assert not any(term in text for term in ('owner', 'case-freeze', 'SHA256', 'alias', 'FAILED', 'null')), i
            tables = slide.findall('.//a:tbl', NS)
            assert len(tables) == len(item.get('tables', [])), i
            for table, expected in zip(tables, item.get('tables', [])):
                rows = [[''.join(t.text or '' for t in cell.findall('.//a:t', NS))
                         for cell in row.findall('a:tc', NS)] for row in table.findall('a:tr', NS)]
                assert rows == [[s.replace('\n', '') for s in row] for row in expected], (i, rows, expected)
                result['tables'].append({'slide': i, 'rows': len(rows), 'native_and_values_match': True})
            charts = slide.findall('.//c:chart', NS)
            assert len(charts) == len(item.get('charts', [])), i
            for chartref, authored in zip(charts, item.get('charts', [])):
                chart = ET.fromstring(package.read(rels[chartref.attrib['{' + NS['r'] + '}id']]))
                series = chart.findall('.//c:ser', NS)
                assert len(series) == len(authored['config']['series'])
                for ser, expected in zip(series, authored['config']['series']):
                    vals = [float(v.text) for v in ser.findall('.//c:val//c:pt/c:v', NS)]
                    assert vals == expected['values'], (i, vals, expected['values'])
                assert chart.find('.//c:externalData', NS) is not None
                result['charts'].append({'slide': i, 'series': len(series), 'native_values_match': True, 'workbook_link_present': True})
            pics = slide.findall('.//p:pic', NS)
            assert len(pics) == len(item.get('images', [])), i
            for pic, expected in zip(pics, item.get('images', [])):
                blip = pic.find('.//a:blip', NS)
                imagebytes = package.read(rels[blip.attrib['{' + NS['r'] + '}embed']])
                assert sha(imagebytes) == expected['sha256']
                assert imagebytes == (ASSETS / 'figures' / expected['name']).read_bytes()
                result['native_images'].append({'slide': i, 'file': expected['name'], 'embedded_bytes_unchanged': True})
            notes = ET.fromstring(package.read(f'ppt/notesSlides/notesSlide{i}.xml'))
            notetext = ''.join(t.text or '' for t in notes.findall('.//a:t', NS))
            assert item['notes'] in notetext
            assert '来源：' in notetext
            result['checked_slides'].append(i)
    assert summary['planned_independent_events'] == 64 and summary['measured_main_responses'] == 128
    assert len(failures['failure_log']) == 7
    main_failures = [f for f in failures['failure_log'] if f['tag'].startswith('v3-r50-main-l')]
    assert len(main_failures) == 4
    assert all(ledger['runs'][f['tag']]['state'] == 'FAILED' and ledger['runs'][f['tag']]['runner_exit_code'] is None for f in main_failures)
    for split in ('holdout', 'extrapolation'):
        for bit in (0, 1):
            for target in ('deltaQ_fC', 'deltaM_mV'):
                scores = summary['final_numerical_prediction_scores']['scores']
                pairs = {r['model']: r for r in scores if r['split'] == split and r['stored_bit'] == bit and r['target'] == target}
                assert pairs['ridge']['valid_n'] == 16
                assert pairs['ridge']['RMSE'] < pairs['training_mean']['RMSE']
    result.update(state='PASS', slides=14, main_slides=11, backup_slides=3,
                  failure_rows_preserved=7, main_original_failed_null_preserved=4,
                  native_table_count=len(result['tables']), native_chart_count=len(result['charts']),
                  new_solver_calls=0, native_powerpoint_execution_tested=False)
    output = HERE / 'qa' / tag / 'content-verification.json'
    with output.open('x', encoding='utf8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('tag')
    verify(parser.parse_args().tag)
