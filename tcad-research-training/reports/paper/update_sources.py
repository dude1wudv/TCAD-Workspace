"""Bind report artifacts to fixed, completed evidence; never invokes solvers."""
from pathlib import Path
import csv
import hashlib
import json
import re
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

paths = [
    'docs/course-project-syllabus.md',
    'experiments/dram-readout-offset-d1/report.md',
    'experiments/dram-readout-offset-d1/interpretation.md',
    'experiments/dram-readout-offset-d1/data/summary.csv',
    'experiments/dram-readout-offset-d1/validation/independent-final.json',
    'experiments/dram-see-v1/report.md',
    'experiments/dram-see-v1/geant4_transport.cc',
    'experiments/dram-see-v3/stats-design.json',
    'experiments/dram-see-v3/build_case.py',
    'experiments/dram-see-v3/demo.md',
    'experiments/dram-see-v3/data/demo/request-demonstration.json',
    'experiments/dram-see-v3/data/summary/20261010T140027916013Z/published-report.md',
    'local_runtime/dram-see-v3/inputs/v3-physical-l018-b1/geometry.scm',
    'local_runtime/dram-see-v3/inputs/v3-physical-l018-b1/device.cmd',
]
for path in paths:
    if not (ROOT / path).is_file():
        raise FileNotFoundError(path)

source_csv = ROOT / 'experiments/dram-readout-offset-d1/data/summary.csv'
with source_csv.open(encoding='utf-8-sig', newline='') as stream:
    rows = list(csv.DictReader(stream))
by_tag = {r['tag']: r for r in rows}
tags = ['scan035', 'alpha-match', 'scan045', 'center050', 'scan055', 'bridge090']
fields = ['D_mV', 'two_capacitor_D_mV', 'offline_center_BL_reference_D_mV']
tex = (HERE / 'report.tex').read_text(encoding='utf-8')
blocks = re.findall(r'\\addplot\[[^\]]+\] coordinates \{(.*?)\};', tex, re.S)
assert len(blocks) == 4, 'Expected three data series and one zero guide'
plotted = []
for block, field in zip(blocks[:3], fields):
    coordinates = [(float(a), float(b)) for a,b in re.findall(r'\(([-\d.]+),([-\d.]+)\)', block)]
    assert len(coordinates) == 6
    records = []
    for coord, tag in zip(coordinates, tags):
        row = by_tag['rodiag1-' + tag]
        assert row['state'] == 'VERIFIED'
        expected = float(row['read_SN_V']), float(row[field])
        assert coord == expected, (coord, expected)
        records.append({'tag': row['tag'], 'run_id': row['run_id'],
                        'archive_sha256': row['archive_sha256'], 'x_V': coord[0], 'y_mV': coord[1]})
    plotted.append({'field': field, 'points': records})

citations = {k for group in re.findall(r'\\cite\{([^}]+)\}',tex) for k in group.split(',')}
entries = set(re.findall(r'\\bibitem\{([^}]+)\}',tex))
assert citations == entries
labels = re.findall(r'\\label\{([^}]+)\}',tex)
assert len(labels) == len(set(labels))
references = set(re.findall(r'\\(?:eqref|ref)\{([^}]+)\}',tex))
assert references <= set(labels)
assert not any(token in tex for token in ['TODO', 'FIXME', '[VERIFY]', '题录待', '交付前替换'])

payload = {
    'schema': 'dram-report-provenance-v1',
    'created_utc': datetime.now(timezone.utc).isoformat(),
    'scope': 'Model basis, physical mechanisms, completed D1 diagnostics; not final v3 results',
    'repository_relative_sources': [{'path': p, 'sha256': digest(ROOT/p)} for p in paths],
    'outputs': [{'path': p, 'sha256': digest(HERE/p)} for p in ['report.tex','report.pdf','build.ps1','README.txt','update_sources.py']],
    'external_sources': [
        {'key': 'keeth2001', 'url': 'https://catalogimages.wiley.com/images/db/pdf/0780360141.excerpt.pdf',
         'verified_scope': '1T1C, precharge, charge sharing, sensing and restoration; printed pp.22-29; not project parameter calibration'},
        {'key': 'g4em', 'url': 'https://geant4-userdoc.web.cern.ch/UsersGuides/PhysicsListGuide/BackupVersions/V10.7/html/electromagnetic/Opt4.html',
         'verified_scope': 'Geant4 10.7 electromagnetic option4 definition; not a 10.7.3 patch-by-patch audit'},
        {'key': 'ryder2021', 'doi': '10.1109/TNS.2021.3060339',
         'url': 'https://nepp.nasa.gov/docs/papers/2021-Ryder-TNS-Paper-SET-Epitaxial-Silicon-Diode-20210010229.pdf',
         'metadata_verification': 'Crossref API: IEEE TNS 68(5), 626-633, May 2021',
         'verified_scope': '3.6 eV per electron-hole pair; effects of charge spatial/temporal distribution; epitaxial diode, not this DRAM'},
        {'key': 'label1996', 'url': 'https://nepp.nasa.gov/DocUploads/6D728AF0-2817-4530-97555B6DCB26D083/seecai.pdf',
         'verified_scope': 'SEE generation/collection mechanisms and circuit-dependent upset; pp.21-23'},
    ],
    'figure_3': {'x_field': 'read_SN_V', 'series': plotted, 'connecting_lines': 'visual guides only; no interpolation claim'},
    'checks': {'plotted_pairs_compared': 18, 'maximum_numeric_difference': 0.0,
               'citation_keys': sorted(citations), 'cross_reference_targets_exist': True,
               'raw_solver_reaudit_performed': False, 'simulation_inputs_modified': False},
}
(HERE/'sources.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'plotted_pairs_verified':18,'citations':len(citations),'source_files':len(paths)},ensure_ascii=False))
