"""Observe actual resources and verify the native mesh; never launches tools.

No project budget, future resource forecast or approval signature is required.
Capacity numbers are recorded as observations. Nonempty available resources,
immutable inputs and exact D3 mesh reuse remain mandatory. Python 3.6.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys


def digest(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('Missing or linked input: ' + str(path))
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def mesh_vertices(text):
    hits = re.findall(r'^\s*The final mesh has:\s*\r?\n\s*([0-9]+) points\.\s*$', text, re.M)
    if len(hits) != 1 or int(hits[0]) <= 0:
        raise ValueError('Missing or ambiguous positive final mesh vertex count')
    return int(hits[0])


def available_memory(text):
    hits = re.findall(r'^MemAvailable:\s+([0-9]+) kB\s*$', text, re.M)
    if len(hits) != 1:
        raise ValueError('Missing or ambiguous MemAvailable')
    return int(hits[0]) * 1024


def evaluate(policy, free_bytes, available_bytes):
    if policy.get('schema') != 'dram-see-v4-actual-resource-policy-r1':
        raise ValueError('Wrong current resource observation policy')
    for name, value in (('free_bytes', free_bytes), ('available_bytes', available_bytes)):
        if type(value) is not int or value < 0:
            raise ValueError('Invalid resource observation: ' + name)
    checks = {'disk_has_available_bytes': free_bytes > 0,
              'memory_has_available_bytes': available_bytes > 0}
    return dict(checks=checks, passed=all(checks.values()),
                free_bytes=free_bytes, available_bytes=available_bytes,
                capacity_prediction=False, scientific_acceptance=False, starts_sdevice=False,
                not_verified_here=['Shared lock, owner and CPU affinity are enforced by the original runner.',
                                   'These observations do not predict future peak resource demand.'])


def inspect(folder):
    folder = Path(folder)
    policy = json.loads((folder / 'resource-policy.json').read_text(encoding='utf-8'))
    report = evaluate(policy, shutil.disk_usage(str(folder)).free,
                      available_memory(Path('/proc/meminfo').read_text()))
    manifest = json.loads((folder / 'input-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != 'dram-see-v4-continuous-inputs-r1':
        raise ValueError('Wrong input manifest')
    for name, expected in manifest['files_sha256'].items():
        parts = name.split('/')
        if any(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', part) is None for part in parts):
            raise ValueError('Unsafe input filename')
        if digest(folder.joinpath(*parts)) != expected:
            raise ValueError('Frozen input changed: ' + name)
    context = json.loads((folder / 'execution-context.json').read_text(encoding='utf-8'))
    if context.get('input_manifest_sha256') != digest(folder / 'input-manifest.json'):
        raise ValueError('Execution context/input manifest differs')
    mesh = folder / 'cell_msh.tdr'
    if mesh.stat().st_size <= 0:
        raise ValueError('Empty native mesh')
    actual = digest(mesh)
    expected = policy.get('imported_mesh_sha256')
    reuse = json.loads((folder / 'project.json').read_text(encoding='utf-8')).get('s2_geometry', {}).get('mode') == 'reuse'
    if reuse and (not expected or actual != expected):
        raise ValueError('Every transient requires the exact original D3 mesh')
    count = mesh_vertices((folder / 'cell_msh.log').read_text(encoding='utf-8', errors='replace'))
    report.update(schema='dram-see-v4-mesh-resource-report-r1', mesh_sha256=actual, mesh_vertices=count,
                  resource_policy_sha256=digest(folder / 'resource-policy.json'),
                  input_manifest_sha256=digest(folder / 'input-manifest.json'),
                  run_id=context.get('run_id'), role_id=context.get('role_id'))
    return report


def main():
    if any(Path(n).exists() for n in ('mesh-resource-report.json', 'mesh-resource-passed.json')):
        print('Refusing to overwrite an existing resource receipt', file=sys.stderr)
        return 2
    try:
        result = inspect(Path.cwd())
    except Exception as exc:
        result = dict(schema='dram-see-v4-mesh-resource-report-r1', passed=False,
                      scientific_acceptance=False, starts_sdevice=False,
                      error=type(exc).__name__ + ': ' + str(exc))
    raw = json.dumps(result, indent=2, allow_nan=False) + '\n'
    with Path('mesh-resource-report.json').open('x', encoding='utf-8') as stream:
        stream.write(raw)
    if result['passed']:
        with Path('mesh-resource-passed.json').open('x', encoding='utf-8') as stream:
            stream.write(raw)
    return 0 if result['passed'] else 2


if __name__ == '__main__':
    sys.exit(main())
