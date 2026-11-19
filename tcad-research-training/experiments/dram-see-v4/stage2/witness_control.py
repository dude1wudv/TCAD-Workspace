"""Prepare/collect the frozen witness campaign using the existing serial adapter."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil

ROOT = Path(__file__).resolve().parents[3]
V4 = ROOT / 'experiments/dram-see-v4'
HERE = V4 / 'mechanism-witness'
RUNTIME = ROOT / 'local_runtime/dram-see-v4/transport-probe'
SOURCE = HERE / 'transport_witness.cc'

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def write(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write('\n')

def label_ok(label):
    if not re.fullmatch('witness-[a-z0-9-]+', label):
        raise ValueError('New immutable witness label required')

def hashlist(folder):
    frozen = {p.name: sha(p) for p in sorted(folder.iterdir()) if p.is_file()}
    (folder / 'input-hashes.sha256').write_bytes(''.join(h+'  '+n+'\n' for n,h in frozen.items()).encode())

def assert_operation_complete(folder):
    op = read(folder / 'operation.json')
    if op['state'] != 'COLLECTED_PENDING_AUDIT' or any(op[k] != 0 for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')):
        raise ValueError('Operation not known successful; do not resubmit automatically')
    return op

def compile_inputs(label):
    label_ok(label)
    if not SOURCE.is_file():
        raise ValueError('New witness source not ready')
    folder = RUNTIME / 'inputs' / label
    folder.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(SOURCE, folder / SOURCE.name)
    env = RUNTIME / 'operations/install-data-r2/collected'
    for name in ('environment.sh','dataset-inventory.json'):
        shutil.copyfile(env/name, folder/name)
    for source in (HERE/'witness-contract.json', V4/'transport-probe/environment-spec.json'):
        shutil.copyfile(source, folder/source.name)
    hashlist(folder)
    script = '''set -euo pipefail
sha256sum -c input-hashes.sha256
source environment.sh
G4ROOT=/home/tcad/research-training/dram-see-v1/software/Geant4-10.7.3-Linux
g++ --version > compiler-version.txt
"$G4ROOT/bin/geant4-config" --version > geant4-version.txt
g++ -O2 $("$G4ROOT/bin/geant4-config" --cflags) transport_witness.cc -o transport_witness $("$G4ROOT/bin/geant4-config" --libs)
ldd transport_witness > linked-libraries.txt
if grep -q 'not found' linked-libraries.txt; then exit 78; fi
sha256sum transport_witness transport_witness.cc environment.sh dataset-inventory.json > build-sha256.txt
'''
    (folder/'task.sh').write_text(script, encoding='utf-8', newline='\n')
    return folder

def gate(stage):
    contract = read(HERE/'witness-contract.json')
    items = [x for x in contract['requests'] if x['stage'] == stage]
    evidence = []
    for req in items:
        candidates = []
        for p in (RUNTIME/'runs').glob('witness-*/record.json'):
            rec = read(p)
            if rec['request'] == req:
                for audit_path in (RUNTIME/'audits').glob(p.parent.name+'*/audit.json'):
                    audit = read(audit_path)
                    if (audit.get('passed') is True and audit.get('record_sha256') == sha(p)
                        and audit.get('audit_code_sha256') == sha(HERE/'audit_witness.py')
                        and Path(audit.get('run_dir','')).resolve() == p.parent.resolve()):
                        candidates.append((p,audit_path))
        if len(candidates) != 1:
            raise ValueError('Require one passed request: '+req['label'])
        p,audit = candidates[0]
        evidence.append({'request':req['label'], 'record_path':p.relative_to(ROOT).as_posix(),
                         'record_sha256':sha(p),'audit_path':audit.relative_to(ROOT).as_posix(),'audit_sha256':sha(audit)})
    obj = {'schema':'dram-see-v4-witness-gate-v1','stage':stage,'passed':True,
           'contract_sha256':sha(HERE/'witness-contract.json'),'evidence':evidence,
           'checked_utc':datetime.now(timezone.utc).isoformat()}
    path = HERE/'results'/(stage+'-gate.json')
    write(path,obj)
    return path

def require_gate(stage):
    p = HERE/'results'/(stage+'-gate.json')
    g = read(p)
    if g.get('passed') is not True or g['contract_sha256'] != sha(HERE/'witness-contract.json'):
        raise ValueError('Missing/stale gate')
    for item in g['evidence']:
        for key in ('record','audit'):
            if sha(ROOT/item[key+'_path']) != item[key+'_sha256']:
                raise ValueError('Gate evidence changed')
        if read(ROOT/item['audit_path']).get('passed') is not True:
            raise ValueError('Failed gate audit')

def prepare(label, build, attempt=None):
    contract = read(HERE/'witness-contract.json')
    reqs = [q for q in contract['requests'] if q['label'] == label]
    if len(reqs) != 1:
        raise ValueError('Request outside frozen campaign')
    req = reqs[0]
    if req['stage'] in ('pilot','fixed'):
        require_gate('initialization')
    if req['stage'] == 'fixed':
        require_gate('pilot')
    attempt = attempt or label
    label_ok(attempt)
    for p in (RUNTIME/'operations').glob('witness-*/operation.json'):
        source_req = p.parent/'collected/request.json'
        input_req = RUNTIME/'inputs'/p.parent.name/'request.json'
        rp = source_req if source_req.is_file() else input_req
        if rp.is_file() and read(rp).get('label') == label:
            op = read(p)
            if op.get('remote_exit_code') == 0:
                raise ValueError('Completed request exists; refuse repeat')
            if op.get('state') not in ('FAILED_COLLECTED',):
                raise ValueError('Prior state unknown; read-only reconcile first')
    build = Path(build).resolve()
    if not build.is_relative_to((RUNTIME/'operations').resolve()):
        raise ValueError('Build outside existing adapter evidence')
    assert_operation_complete(build)
    if sha(build/'collected/transport_witness.cc') != sha(SOURCE):
        raise ValueError('Build and current source differ; freeze revision first')
    folder = RUNTIME/'inputs'/attempt
    folder.mkdir(parents=True, exist_ok=False)
    for name in ('transport_witness','transport_witness.cc','environment.sh','dataset-inventory.json'):
        shutil.copyfile(build/'collected'/name,folder/name)
    for source in (HERE/'witness-contract.json',V4/'transport-probe/environment-spec.json'):
        shutil.copyfile(source,folder/source.name)
    write(folder/'request.json',req)
    hashlist(folder)
    argv = ['./transport_witness',req['mode'],req['arm'],str(req['seed']),str(req['event_count'])]
    script = '\n'.join(['set -euo pipefail','sha256sum -c input-hashes.sha256','source environment.sh',
        'chmod u+x transport_witness',
        "printf '%s  binary\\n' \"$(sha256sum transport_witness | cut -d ' ' -f1)\" > provenance.sha256",
        "printf '%s  environment\\n' \"$(sha256sum environment.sh | cut -d ' ' -f1)\" >> provenance.sha256",
        "printf '%s  dataset_inventory\\n' \"$(sha256sum dataset-inventory.json | cut -d ' ' -f1)\" >> provenance.sha256",
        ' '.join(map(shlex.quote,argv)), ''])
    (folder/'task.sh').write_text(script,encoding='utf-8',newline='\n')
    return folder

def collect(label):
    label_ok(label)
    opfolder = RUNTIME/'operations'/label
    receipt = read(opfolder/'operation.json')
    if receipt['state'] not in ('COLLECTED_PENDING_AUDIT','FAILED_COLLECTED'):
        raise ValueError('Attempt not terminal/collected; reconcile without resubmitting')
    source = opfolder/'collected'
    req = read(source/'request.json')
    dest = RUNTIME/'runs'/label
    shutil.copytree(source,dest)
    rec = dict(schema='dram-see-v4-witness-run-v1',run_id=label,
        mode='init' if req['mode']=='init' else 'events',arm=req['arm'],
        runner_exit_code=receipt['ssh_exit_code'],remote_exit_code=receipt['remote_exit_code'],
        collection_exit_code=receipt['collection_exit_code'],
        runner_exit_definition='Actual synchronous SSH wrapper process code',
        request=req,input_sha256=receipt['input_sha256'],binary_sha256=sha(dest/'transport_witness'),
        environment_sha256=sha(dest/'environment.sh'),dataset_inventory_sha256=sha(dest/'dataset-inventory.json'),
        raw_archive={'path':(opfolder/'results.tar').relative_to(ROOT).as_posix(),'sha256':sha(opfolder/'results.tar')},
        operation_evidence={'path':(opfolder/'operation.json').relative_to(ROOT).as_posix(),'sha256':sha(opfolder/'operation.json')},
        single_thread_evidence={'run_manager':'G4RunManager','threads':1,'affinity_cpu_count':1,'affinity_evidence_file':'affinity.txt'},
        provenance_files={'binary':'transport_witness','binary_witness':'provenance.sha256','environment':'environment.sh','dataset_inventory':'dataset-inventory.json'},
        output_sha256={p.relative_to(dest).as_posix():sha(p) for p in sorted(dest.rglob('*')) if p.is_file()})
    write(dest/'record.json',rec)
    return dest

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command',required=True)
    c = sub.add_parser('compile-inputs'); c.add_argument('label')
    c = sub.add_parser('prepare'); c.add_argument('label'); c.add_argument('build',type=Path); c.add_argument('--attempt')
    c = sub.add_parser('collect'); c.add_argument('label')
    c = sub.add_parser('gate'); c.add_argument('stage',choices=['initialization','pilot','fixed'])
    a = p.parse_args()
    if a.command == 'compile-inputs': result = compile_inputs(a.label)
    elif a.command == 'prepare': result = prepare(a.label,a.build,a.attempt)
    elif a.command == 'collect': result = collect(a.label)
    else: result = gate(a.stage)
    print(result.relative_to(ROOT).as_posix())
