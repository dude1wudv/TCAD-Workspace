"""Read-only post-mesh admission check, Python 3.6 compatible; never starts tools.

Only the two JSON receipts are written into the current new run directory.
Estimates are conditional resource screens, not scientific or peak-memory proof.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def mesh_vertices(text):
    matches = re.findall(r'^\s*Optimizing elements\.\.\.done\.\s*\(([0-9]+) vertices\)\s*$', text, re.M)
    if len(matches) != 1 or int(matches[0]) <= 0:
        raise ValueError('Unknown/missing/ambiguous final mesh vertex record; do not start SDevice')
    return int(matches[0])


def available_memory(text):
    matches = re.findall(r'^MemAvailable:\s+([0-9]+) kB\s*$', text, re.M)
    if len(matches) != 1:
        raise ValueError('Missing/ambiguous native MemAvailable')
    return int(matches[0])*1024


def estimate(vertices, policy, free_bytes, available_bytes):
    if type(vertices) is not int or vertices <= 0:
        raise ValueError('Positive native mesh vertex count required')
    scaled_frame = policy['reference_mean_frame_bytes'] * vertices / policy['reference_mesh_vertices']
    raw = math.ceil(scaled_frame*policy['frame_allowance']*policy['format_margin'])
    peak = raw*policy['copy_allowance']+policy['extra_bytes']
    checks = {
        'disk_conditional_estimate_with_floor': free_bytes >= peak+policy['free_disk_floor_bytes'],
        'available_memory_start_floor': available_bytes >= policy['available_memory_floor_bytes']
    }
    return {'native_mesh_vertices':vertices, 'sdevice_grid_points':None,
            'vertex_semantics':'mesh vertices are a resource proxy, not measured SDevice grid points',
            'estimated_frame_bytes_before_margin':scaled_frame,
            'conditional_raw_frame_bytes':raw, 'conditional_peak_additional_bytes':peak,
            'free_disk_bytes':free_bytes, 'available_memory_bytes':available_bytes,
            'checks':checks, 'passed':all(checks.values()),
            'reliable_node_upper_bound':None, 'peak_memory_estimate_bytes':None,
            'limitations':['410 frames and linear bytes/mesh-vertex scaling are conditional assumptions, not strict upper bounds.',
                           'The 4 GiB initial memory floor does not prove that 3D ParDiSo peak memory fits.',
                           'No mesh, source, timestep, or output decimation is performed by this guard.']}


def inspect(folder):
    folder = Path(folder)
    policy_file = folder/'source-contract.json'
    contract_raw = policy_file.read_bytes()
    c = json.loads(contract_raw.decode('utf-8'))
    if c.get('schema') != 'dram-see-v4-source-interface-3d-r1-contract':
        raise ValueError('Wrong source contract for mesh guard')
    m = json.loads((folder/'input-manifest.json').read_text(encoding='utf-8'))
    if m.get('schema') != 'dram-see-v4-source-interface-3d-r1-inputs':
        raise ValueError('Wrong input manifest for mesh guard')
    for name in ('source-contract.json','geometry-contract.json','mesh_resource_guard.py','geometry.scm','device.cmd','parameters.json'):
        if sha((folder/name).read_bytes()) != m['files_sha256'].get(name):
            raise ValueError('Input hash mismatch in mesh guard: '+name)
    p = json.loads((folder/'parameters.json').read_text(encoding='utf-8'))
    if p.get('case_id') not in ('A0','A1') or p.get('stored_bit') != 1 or p.get('dimension') != 3:
        raise ValueError('Guard called on an unsupported role')
    mesh_path = folder/'cell_msh.tdr'
    mesh_bytes = mesh_path.stat().st_size
    if not mesh_bytes:
        raise ValueError('Empty native mesh')
    log_raw = (folder/'cell_msh.log').read_bytes()
    count = mesh_vertices(log_raw.decode('utf-8',errors='replace'))
    memory_raw = Path('/proc/meminfo').read_text()
    report = estimate(count,c['resource_guard'],shutil.disk_usage(str(folder)).free,available_memory(memory_raw))
    report.update(schema='dram-see-v4-source-3d-mesh-resource-guard',case_id=p['case_id'],stored_bit=1,
                  source_contract_sha256=sha(contract_raw),input_manifest_sha256=sha((folder/'input-manifest.json').read_bytes()),
                  mesh_sha256=file_sha(mesh_path),mesh_bytes=mesh_bytes,mesh_log_sha256=sha(log_raw),
                  guard_sha256=sha((folder/'mesh_resource_guard.py').read_bytes()),policy=c['resource_guard'],
                  scientific_acceptance=False,sdevice_started_by_guard=False)
    return report


def main():
    # A prior receipt is never reused or overwritten, even on a repeated invocation.
    for name in ('mesh-resource-report.json','mesh-resource-passed.json'):
        if Path(name).exists():
            print('MESH_RESOURCE_GUARD_REFUSED_EXISTING_RECEIPT',file=sys.stderr)
            return 2
    try:
        report = inspect(Path.cwd())
    except Exception as exc:
        report = {'schema':'dram-see-v4-source-3d-mesh-resource-guard','passed':False,
                  'scientific_acceptance':False,'sdevice_started_by_guard':False,
                  'error':type(exc).__name__+': '+str(exc)}
    raw = (json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    with Path('mesh-resource-report.json').open('xb') as stream:
        stream.write(raw)
    if report['passed']:
        with Path('mesh-resource-passed.json').open('xb') as stream:
            stream.write(raw)
        print('MESH_RESOURCE_GUARD_PASSED')
        return 0
    print('MESH_RESOURCE_GUARD_BLOCKED_SDEVICE',file=sys.stderr)
    return 2


if __name__=='__main__':
    sys.exit(main())
