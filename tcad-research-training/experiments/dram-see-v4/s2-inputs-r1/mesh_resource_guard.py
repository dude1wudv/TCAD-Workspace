"""Future post-mesh resource check; never launches tools. Python 3.6 compatible.

Review packages have no approved policy and always fail closed. This check is
only the remote half of admission: local storage, locks, ledgers and ownership
must also pass in the unchanged project's sole scheduler before any dispatch.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

GIB = 1024 ** 3


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def mesh_vertices(text):
    hits = re.findall(r'^\s*Optimizing elements\.\.\.done\.\s*\(([0-9]+) vertices\)\s*$', text, re.M)
    if len(hits) != 1 or int(hits[0]) <= 0:
        raise ValueError('Missing or ambiguous positive final mesh vertex count')
    return int(hits[0])


def available_memory(text):
    hits = re.findall(r'^MemAvailable:\s+([0-9]+) kB\s*$', text, re.M)
    if len(hits) != 1:
        raise ValueError('Missing or ambiguous MemAvailable')
    return int(hits[0])*1024


def evaluate(policy, free_bytes, available_bytes):
    if policy.get('schema') != 's2-resource-policy-r1' or policy.get('approved') is not True:
        raise ValueError('Review-only/unapproved S2 resource policy')
    if policy.get('execution_enabled') is not True or not policy.get('release_id'):
        raise ValueError('Missing future execution release')
    # These are existing floors, not adjustable policy fields.
    for key in ('forecast_remote_peak_bytes', 'forecast_peak_memory_bytes'):
        value = policy.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('Unpriced resource forecast: '+key)
    if not policy.get('forecast_evidence_sha256') or not policy.get('scheduler_preflight_sha256'):
        raise ValueError('Missing measured/reviewed forecast or scheduler preflight binding')
    checks = {
        'remote_free_after_forecast_ge_8GiB': free_bytes-policy['forecast_remote_peak_bytes'] >= 8*GIB,
        'available_memory_ge_4GiB': available_bytes >= 4*GIB,
        'peak_memory_forecast_fits': available_bytes >= policy['forecast_peak_memory_bytes'],
    }
    return {'checks': checks, 'passed': all(checks.values()),
            'free_bytes': free_bytes, 'available_bytes': available_bytes,
            'not_verified_here': ['local free >=20GiB after forecast', 'combined retained <=160GiB',
                                  'shared lock, owner, single core/thread, role budget reservation'],
            'scientific_acceptance': False, 'starts_sdevice': False}


def inspect(folder):
    folder = Path(folder)
    policy = json.loads((folder/'resource-policy.json').read_text(encoding='utf-8'))
    # Refuse an unapproved review package before consulting native products.
    if policy.get('approved') is not True or policy.get('execution_enabled') is not True:
        raise ValueError('Review-only/unapproved S2 resource policy')
    report = evaluate(policy, shutil.disk_usage(str(folder)).free,
                      available_memory(Path('/proc/meminfo').read_text()))
    manifest = json.loads((folder/'input-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != 's2-role-inputs-r1':
        raise ValueError('Wrong input manifest')
    for name, expected in manifest['files_sha256'].items():
        if digest(folder/name) != expected:
            raise ValueError('Frozen input changed: '+name)
    mesh = folder/'cell_msh.tdr'
    if mesh.stat().st_size <= 0:
        raise ValueError('Empty native mesh')
    actual = digest(mesh)
    expected = policy.get('imported_mesh_sha256')
    if policy.get('role', '').startswith('B1-A0') and (not expected or actual != expected):
        raise ValueError('A0 requires the exact released D3 mesh')
    count = mesh_vertices((folder/'cell_msh.log').read_text(encoding='utf-8', errors='replace'))
    report.update(schema='s2-mesh-resource-report-r1', mesh_sha256=actual, mesh_vertices=count,
                  resource_policy_sha256=digest(folder/'resource-policy.json'),
                  release_id=policy['release_id'])
    return report


def main():
    if any(Path(n).exists() for n in ('mesh-resource-report.json', 'mesh-resource-passed.json')):
        print('Refusing to overwrite an existing resource receipt', file=sys.stderr)
        return 2
    try:
        result = inspect(Path.cwd())
    except Exception as exc:
        result = {'schema': 's2-mesh-resource-report-r1', 'passed': False,
                  'scientific_acceptance': False, 'starts_sdevice': False,
                  'error': type(exc).__name__+': '+str(exc)}
    raw = json.dumps(result, indent=2, allow_nan=False)+'\n'
    with Path('mesh-resource-report.json').open('x', encoding='utf-8') as stream:
        stream.write(raw)
    if result['passed']:
        with Path('mesh-resource-passed.json').open('x', encoding='utf-8') as stream:
            stream.write(raw)
    return 0 if result['passed'] else 2


if __name__ == '__main__':
    sys.exit(main())
