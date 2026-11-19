"""Prepare immutable matched transport packages; never connects or runs solvers.

The caller copies the returned package into the original operation.py input
namespace, verifies package hashes, and invokes that existing adapter once.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import shutil

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / 'local_runtime/dram-see-v4/matched-transport-r1'
OLD_RUNTIME = ROOT / 'local_runtime/dram-see-v4/transport-probe'
GEOMETRY = HERE.parent / 'source-interface-3d-r1/geometry-contract.json'
TOLERANCES = {'energy_abs_MeV': 1e-12, 'energy_relative': 1e-9,
              'time_abs_ns': 1e-9, 'position_abs_um': 1e-9, 'direction_norm_abs': 1e-10}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def validate_geometry(geometry):
    if (geometry.get('schema') != 'dram-see-v4-shared-geometry-3d-r1'
            or geometry.get('dimension') != 3 or geometry.get('units', {}).get('length') != 'um'
            or geometry.get('coordinate_system') != 'AsIs'):
        raise ValueError('Only the shared untransformed 3D geometry contract is supported')
    solids = geometry.get('solids', [])
    if not solids or len({s['id'] for s in solids}) != len(solids):
        raise ValueError('Missing or duplicate solid IDs')
    for solid in solids:
        if solid.get('shape') != 'cuboid' or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*', solid['id']):
            raise ValueError('Unsupported solid')
        if solid['id'] in ('World', 'OUTSIDE') or not solid.get('geant4_material', '').startswith('G4_'):
            raise ValueError('Invalid material or reserved solid name')
        if any(len(solid[k]) != 3 for k in ('min_um', 'max_um')):
            raise ValueError('Cuboid must be three-dimensional')
        if not all(math.isfinite(float(lo)) and math.isfinite(float(hi)) and lo < hi
                   for lo, hi in zip(solid['min_um'], solid['max_um'])):
            raise ValueError('Invalid cuboid extents')
        if not math.isfinite(solid['density_g_cm3']) or solid['density_g_cm3'] <= 0:
            raise ValueError('Invalid material density')
    for i, left in enumerate(solids):
        for right in solids[i+1:]:
            if all(min(a, b) > max(c, d) for a, b, c, d in
                   zip(left['max_um'], right['max_um'], left['min_um'], right['min_um'])):
                raise ValueError('Overlapping solid interiors require an explicit shared Boolean geometry')
    return solids


def make_contract(geometry_path=GEOMETRY):
    geometry = read(geometry_path)
    solids = validate_geometry(geometry)
    lower = [min(s['min_um'][i] for s in solids) for i in range(3)]
    upper = [max(s['max_um'][i] for s in solids) for i in range(3)]
    world_half = [max(abs(lower[i]), abs(upper[i])) + 10. for i in range(3)]
    hit = [s for s in solids if s['min_um'][0] < .7 < s['max_um'][0]
           and s['min_um'][2] < 0 < s['max_um'][2]]
    if not hit:
        raise ValueError('Frozen normal beam does not cross a solid interior')
    normal = [.7, lower[1]-1., 0.]
    miss = [upper[0]+1., lower[1]-1., 0.]
    if not all(abs(v) < h for point in (normal, miss) for v, h in zip(point, world_half)):
        raise ValueError('Beam source outside world')
    requests = []
    for mode, arm, seed, count in [('init','H',40142001,0), ('init','E',40142002,0),
                                   ('normal','H',40142101,2), ('normal','E',40142102,2),
                                   ('miss','H',40142103,2), ('miss','E',40142104,2)]:
        requests.append(dict(label=f'matched-{mode}-{arm.lower()}-r1', mode=mode, arm=arm, seed=seed,
                             event_count=count, stage='initialization' if mode=='init' else 'pilot',
                             geometry_id=geometry['geometry_id'], geometry_sha256=sha(geometry_path),
                             energy_MeV=100., angle_deg=0., beam_position_um=miss if mode=='miss' else normal,
                             beam_direction=[0.,1.,0.],
                             surface_position_um=None if mode=='miss' else [.7,min(s['min_um'][1] for s in hit),0.]))
    return dict(schema='dram-see-v4-matched-transport-contract-r1',
                geometry_path=GEOMETRY.relative_to(ROOT).as_posix(), geometry_sha256=sha(geometry_path),
                geometry=geometry, world_half_um=world_half, world_material='G4_Galactic',
                world_rule='Origin-centred vacuum cuboid: max absolute entity coordinate + 10 um per axis',
                production_cut_um=.01, charged_max_step_um=.02, step_limit_scope='all declared device solids; charged particles only',
                requests=requests, total_primary_events=8, binary_call_limit=6, retry_limit=0,
                physics={'H':'QGSP_BIC + ReplacePhysics(G4EmStandardPhysics_option4) + StepLimiterPhysics',
                         'E':'G4EmStandardPhysics_option4 + StepLimiterPhysics'},
                csv_arithmetic_tolerances=TOLERANCES, automatic_retry=False, events_for_probability=False,
                tcad_mapping=False, requires_native_dynamic_ion_inventory=True,
                scope='Geometry-matched transport format/cost pilot; not converged transport or TCAD response')


def freeze_contract():
    contract = make_contract()
    destination = HERE / 'matched-contract.json'
    if destination.exists():
        if read(destination) != contract:
            raise ValueError('Existing contract differs; do not overwrite a frozen revision')
    else:
        write(destination, contract)
    return destination


def contract():
    value = read(HERE / 'matched-contract.json')
    if value != make_contract():
        raise ValueError('Shared geometry or frozen matched contract changed')
    return value


def header(value):
    """Generate C++ constants without JSON parsing or a second geometry definition."""
    fmt = lambda v: format(float(v), '.17g')
    vec = lambda values: '{' + ','.join(fmt(x) for x in values) + '}'
    lines = ['#pragma once', '// Generated from the exact shared geometry snapshot; do not hand-edit.',
             'namespace frozen {',
             'struct Solid { const char* id; const char* material; double lo[3], hi[3]; double density; };',
             'struct Request { const char* label; const char* mode; const char* arm; int seed; int events; double position[3]; bool hits; double surface[3]; };',
             'static const Solid solids[] = {']
    for s in value['geometry']['solids']:
        lines.append('{' + json.dumps(s['id']) + ',' + json.dumps(s['geant4_material']) + ','
                     + vec(s['min_um']) + ',' + vec(s['max_um']) + ',' + fmt(s['density_g_cm3']) + '},')
    lines += ['};', 'static const Request requests[] = {']
    for r in value['requests']:
        lines.append('{' + ','.join(json.dumps(r[k]) for k in ('label','mode','arm')) + ','
                     + str(r['seed']) + ',' + str(r['event_count']) + ',' + vec(r['beam_position_um']) + ','
                     + ('true' if r['surface_position_um'] is not None else 'false') + ','
                     + vec(r['surface_position_um'] or [0,0,0]) + '},')
    lines += ['};', 'static const double world_half_um[3] = ' + vec(value['world_half_um']) + ';']
    for key, data in [('geometry_id', value['geometry']['geometry_id']), ('geometry_sha256', value['geometry_sha256']),
                      ('geometry_json', json.dumps(value['geometry'], separators=(',',':'), ensure_ascii=True)),
                      ('contract_sha256', sha(HERE / 'matched-contract.json'))]:
        lines.append('static const char* ' + key + ' = ' + json.dumps(data, ensure_ascii=True) + ';')
    lines += ['}', '']
    return '\n'.join(lines)


def label_ok(label):
    if not re.fullmatch(r'matched-[a-z0-9-]+', label):
        raise ValueError('Matched immutable operation label required')


def hashlist(folder):
    frozen = {p.name: sha(p) for p in sorted(folder.iterdir()) if p.is_file()}
    (folder/'input-hashes.sha256').write_bytes(''.join(h+'  '+n+'\n' for n,h in frozen.items()).encode())


def assert_operation_complete(folder):
    operation = read(folder/'operation.json')
    if operation.get('state') != 'COLLECTED_PENDING_AUDIT' or any(operation.get(k) != 0 for k in
            ('ssh_exit_code','remote_exit_code','collection_exit_code')):
        raise ValueError('Operation not known successful; reconcile, never blindly retry')
    for name, digest in operation['input_sha256'].items():
        if sha(folder/'collected'/name) != digest:
            raise ValueError('Collected operation input differs: '+name)
    if sha(folder/'results.tar') != operation['archive_sha256']:
        raise ValueError('Operation archive differs')
    return operation


def compile_inputs(label='matched-build-r1'):
    label_ok(label)
    value = contract()
    folder = RUNTIME/'inputs'/label
    folder.mkdir(parents=True, exist_ok=False)
    for path in (HERE/'transport_matched.cc', HERE/'matched-contract.json', GEOMETRY):
        shutil.copyfile(path, folder/path.name)
    (folder/'geometry.hh').write_text(header(value), encoding='utf-8', newline='\n')
    environment = OLD_RUNTIME/'operations/install-data-r2/collected'
    for name in ('environment.sh','dataset-inventory.json'):
        shutil.copyfile(environment/name, folder/name)
    shutil.copyfile(HERE.parent/'transport-probe/environment-spec.json', folder/'environment-spec.json')
    hashlist(folder)
    script = '''set -euo pipefail
sha256sum -c input-hashes.sha256
source environment.sh
G4ROOT=/home/tcad/research-training/dram-see-v1/software/Geant4-10.7.3-Linux
g++ --version > compiler-version.txt
"$G4ROOT/bin/geant4-config" --version > geant4-version.txt
g++ -O2 $("$G4ROOT/bin/geant4-config" --cflags) transport_matched.cc -o transport_matched $("$G4ROOT/bin/geant4-config" --libs)
ldd transport_matched > linked-libraries.txt
if grep -q 'not found' linked-libraries.txt; then exit 78; fi
sha256sum transport_matched transport_matched.cc geometry.hh matched-contract.json geometry-contract.json environment.sh dataset-inventory.json > build-sha256.txt
'''
    (folder/'task.sh').write_text(script, encoding='utf-8', newline='\n')
    return folder


def require_initialization_gate():
    gate = read(RUNTIME/'gates/initialization.json')
    if gate.get('passed') is not True or gate['contract_sha256'] != sha(HERE/'matched-contract.json'):
        raise ValueError('Missing/stale initialization gate')
    for item in gate['evidence']:
        for key in ('record','audit'):
            if sha(ROOT/item[key+'_path']) != item[key+'_sha256']:
                raise ValueError('Initialization gate evidence changed')
        evidence = read(ROOT/item['audit_path'])
        if evidence.get('passed') is not True or evidence.get('audit_code_sha256') != sha(HERE/'audit_matched.py'):
            raise ValueError('Initialization gate audit is failed or stale')


def prepare(label, build):
    value = contract()
    requests = [r for r in value['requests'] if r['label'] == label]
    if len(requests) != 1:
        raise ValueError('Request outside frozen six-call contract')
    current_budget = budget_status()
    if current_budget['invocation_reservations'] >= value['binary_call_limit']:
        raise ValueError('Six invocation reservations exhausted; no retry allowance')
    request = requests[0]
    if request['mode'] != 'init':
        require_initialization_gate()
    # A package is an immutable reservation. No failure or unknown run is silently retried.
    for op in (OLD_RUNTIME/'operations').glob('matched-*/operation.json'):
        for candidate in (op.parent/'collected/request.json', OLD_RUNTIME/'inputs'/op.parent.name/'request.json'):
            if candidate.exists() and read(candidate).get('label') == label:
                raise ValueError('Request already has an operation; inspect its original state')
    build = Path(build).resolve()
    assert_operation_complete(build)
    for name, expected in [('transport_matched.cc',HERE/'transport_matched.cc'),
                           ('matched-contract.json',HERE/'matched-contract.json'), ('geometry-contract.json',GEOMETRY)]:
        if sha(build/'collected'/name) != sha(expected):
            raise ValueError('Build differs from current frozen source/contract: '+name)
    if (build/'collected/geometry.hh').read_text(encoding='utf-8') != header(value):
        raise ValueError('Build geometry header differs from shared contract')
    folder = RUNTIME/'inputs'/label
    folder.mkdir(parents=True, exist_ok=False)
    for name in ('transport_matched','transport_matched.cc','geometry.hh','matched-contract.json',
                 'geometry-contract.json','environment.sh','dataset-inventory.json','environment-spec.json'):
        shutil.copyfile(build/'collected'/name, folder/name)
    write(folder/'request.json', request)
    write(folder/'package-origin.json', {'build_operation_path':build.relative_to(ROOT).as_posix(),
          'build_operation_sha256':sha(build/'operation.json'), 'control_sha256':sha(Path(__file__))})
    hashlist(folder)
    script = '\n'.join(['set -euo pipefail','sha256sum -c input-hashes.sha256','source environment.sh',
        'chmod u+x transport_matched',
        "printf '%s  binary\\n' \"$(sha256sum transport_matched | cut -d ' ' -f1)\" > provenance.sha256",
        "printf '%s  environment\\n' \"$(sha256sum environment.sh | cut -d ' ' -f1)\" >> provenance.sha256",
        "printf '%s  dataset_inventory\\n' \"$(sha256sum dataset-inventory.json | cut -d ' ' -f1)\" >> provenance.sha256",
        './transport_matched '+shlex.quote(label), ''])
    (folder/'task.sh').write_text(script, encoding='utf-8', newline='\n')
    return folder


def budget_status():
    """Read original operation receipts; unknown/failed starts conservatively count."""
    value = contract()
    allowed = {r['label']:r for r in value['requests']}
    calls = []
    for operation_path in sorted((OLD_RUNTIME/'operations').glob('matched-*/operation.json')):
        operation = read(operation_path)
        request_path = operation_path.parent/'collected/request.json'
        if not request_path.exists():
            request_path = OLD_RUNTIME/'inputs'/operation_path.parent.name/'request.json'
        if not request_path.exists():
            if operation_path.parent.name.startswith('matched-build-'):
                continue
            raise ValueError('Matched operation has unknown purpose; inspect before continuing')
        request = read(request_path)
        if request.get('label') not in allowed or request != allowed[request['label']]:
            raise ValueError('Operation request differs from fixed matched contract')
        calls.append({'operation_label':operation['label'],'request_label':request['label'],
                      'event_count':request['event_count'],'state':operation.get('state'),
                      'remote_exit_code':operation.get('remote_exit_code'),
                      'operation_path':operation_path.relative_to(ROOT).as_posix(),
                      'operation_sha256':sha(operation_path)})
    labels = [c['request_label'] for c in calls]
    if len(labels) != len(set(labels)):
        raise ValueError('Duplicate matched request operations found; pause for reconciliation')
    return {'schema':'dram-see-v4-matched-budget-r1','binary_call_limit':6,'primary_event_limit':8,
            'invocation_reservations':len(calls),'requested_primary_events':sum(c['event_count'] for c in calls),
            'remaining_invocations':6-len(calls),'automatic_retry':False,'calls':calls,
            'semantics':'Operation reservation counts conservatively even when binary start is unproven; compilation excluded.'}


def collect(operation_folder):
    opfolder = Path(operation_folder).resolve()
    receipt = read(opfolder/'operation.json')
    label = receipt['label']; label_ok(label)
    if receipt.get('state') not in ('COLLECTED_PENDING_AUDIT','FAILED_COLLECTED'):
        raise ValueError('Attempt not terminal/collected; reconcile without resubmitting')
    source = opfolder/'collected'
    request = read(source/'request.json')
    destination = RUNTIME/'runs'/label
    shutil.copytree(source, destination)
    record = dict(schema='dram-see-v4-matched-run-r1',run_id=label,
        mode='init' if request['mode']=='init' else 'events',arm=request['arm'],
        runner_exit_code=receipt['ssh_exit_code'],remote_exit_code=receipt['remote_exit_code'],
        collection_exit_code=receipt['collection_exit_code'], request=request,
        runner_exit_definition='Actual synchronous original operation.py SSH wrapper code',
        input_sha256=receipt['input_sha256'], binary_sha256=sha(destination/'transport_matched'),
        environment_sha256=sha(destination/'environment.sh'),dataset_inventory_sha256=sha(destination/'dataset-inventory.json'),
        raw_archive={'path':(opfolder/'results.tar').relative_to(ROOT).as_posix(),'sha256':sha(opfolder/'results.tar')},
        operation_evidence={'path':(opfolder/'operation.json').relative_to(ROOT).as_posix(),'sha256':sha(opfolder/'operation.json')},
        provenance_files={'binary':'transport_matched','binary_witness':'provenance.sha256',
                          'environment':'environment.sh','dataset_inventory':'dataset-inventory.json'},
        output_sha256={p.relative_to(destination).as_posix():sha(p) for p in sorted(destination.rglob('*')) if p.is_file()})
    write(destination/'record.json',record)
    return destination


def gate_initialization():
    value = contract(); evidence = []
    for request in value['requests'][:2]:
        record_path = RUNTIME/'runs'/request['label']/'record.json'
        audit_path = RUNTIME/'audits'/request['label']/'audit.json'
        r, a = read(record_path), read(audit_path)
        if (r['request'] != request or a.get('passed') is not True or a.get('record_sha256') != sha(record_path)
                or a.get('audit_code_sha256') != sha(HERE/'audit_matched.py')):
            raise ValueError('Require current passed H/E initialization evidence')
        evidence.append({'record_path':record_path.relative_to(ROOT).as_posix(),'record_sha256':sha(record_path),
                         'audit_path':audit_path.relative_to(ROOT).as_posix(),'audit_sha256':sha(audit_path)})
    path = RUNTIME/'gates/initialization.json'
    write(path,dict(passed=True,contract_sha256=sha(HERE/'matched-contract.json'),evidence=evidence,
                    checked_utc=datetime.now(timezone.utc).isoformat()))
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('freeze-contract')
    c = sub.add_parser('compile-inputs'); c.add_argument('--label', default='matched-build-r1')
    c = sub.add_parser('prepare'); c.add_argument('label'); c.add_argument('build', type=Path)
    c = sub.add_parser('collect'); c.add_argument('operation_folder', type=Path)
    sub.add_parser('gate-initialization')
    sub.add_parser('budget')
    args = parser.parse_args()
    if args.command == 'freeze-contract': result = freeze_contract()
    elif args.command == 'compile-inputs': result = compile_inputs(args.label)
    elif args.command == 'prepare': result = prepare(args.label,args.build)
    elif args.command == 'collect': result = collect(args.operation_folder)
    elif args.command == 'gate-initialization': result = gate_initialization()
    else: result = budget_status()
    print(json.dumps(result,indent=2) if isinstance(result,dict) else result.relative_to(ROOT).as_posix())
