"""Freeze one predeclared Geant4 request; no connection or solver execution."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUNTIME = ROOT / 'local_runtime/dram-see-v4/transport-probe'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_gate(name):
    path = HERE / 'results' / name
    gate = json.loads(path.read_text(encoding='utf-8'))
    if gate.get('passed') is not True or gate.get('contract_sha256') != sha(HERE / 'probe-contract.json'):
        raise ValueError('Missing or stale gate: ' + name)
    if not gate.get('audit_evidence'):
        raise ValueError('Gate has no audit evidence')
    for item in gate['audit_evidence']:
        evidence = (ROOT / item['path']).resolve()
        if not evidence.is_relative_to(RUNTIME.resolve()) or sha(evidence) != item['sha256']:
            raise ValueError('Gate audit hash mismatch')
        if json.loads(evidence.read_text(encoding='utf-8')).get('passed') is not True:
            raise ValueError('Gate references failed audit')


def prepare(label, build, attempt=None):
    contract = json.loads((HERE / 'probe-contract.json').read_text(encoding='utf-8'))
    choices = [q for q in contract['requests'] if q['label'] == label]
    if len(choices) != 1:
        raise ValueError('Request is not in the frozen contract')
    request = choices[0]
    if request['mode'] == 'thin':
        require_gate('initialization-gate.json')
        if request['stage'] != 'format-probe':
            require_gate('format-gate.json')
    for previous in (RUNTIME / 'runs').glob('*/record.json'):
        evidence = json.loads(previous.read_text(encoding='utf-8'))
        if evidence.get('request', {}).get('label') == label and evidence.get('remote_exit_code') == 0:
            raise ValueError('Completed request already exists; do not resubmit')
    attempt = attempt or label
    if not re.fullmatch('[a-z0-9][a-z0-9-]*', attempt):
        raise ValueError('Invalid attempt label')
    build = Path(build).resolve()
    if not build.is_relative_to((RUNTIME / 'operations').resolve()):
        raise ValueError('Build must be an existing collected v4 operation')
    record = json.loads((build / 'operation.json').read_text(encoding='utf-8'))
    if any(record[k] != 0 for k in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code')):
        raise ValueError('Build operation did not complete successfully')
    folder = RUNTIME / 'inputs' / attempt
    folder.mkdir(parents=True, exist_ok=False)
    for name in ('transport_probe', 'transport_probe.cc', 'environment.sh', 'dataset-inventory.json'):
        shutil.copyfile(build / 'collected' / name, folder / name)
    shutil.copyfile(HERE / 'probe-contract.json', folder / 'probe-contract.json')
    shutil.copyfile(HERE / 'environment-spec.json', folder / 'environment-spec.json')
    (folder / 'request.json').write_text(json.dumps(request, indent=2) + '\n', encoding='utf-8')
    frozen = {p.name: sha(p) for p in sorted(folder.iterdir()) if p.is_file()}
    (folder / 'input-hashes.sha256').write_bytes((''.join(h + '  ' + name + '\n' for name, h in frozen.items())).encode())
    argv = ['./transport_probe', request['mode'], request['arm'], str(request['energy_MeV']),
            str(request['angle_deg']), str(request['seed']), str(request['event_count']), 'miss=' + str(request['miss'])]
    script = '\n'.join([
        'set -euo pipefail', 'sha256sum -c input-hashes.sha256', 'source environment.sh',
        'chmod u+x transport_probe',
        "printf '%s  binary\\n' \"$(sha256sum transport_probe | cut -d ' ' -f1)\" > provenance.sha256",
        "printf '%s  environment\\n' \"$(sha256sum environment.sh | cut -d ' ' -f1)\" >> provenance.sha256",
        "printf '%s  dataset_inventory\\n' \"$(sha256sum dataset-inventory.json | cut -d ' ' -f1)\" >> provenance.sha256",
        ' '.join(map(shlex.quote, argv)),
    ]) + '\n'
    (folder / 'task.sh').write_text(script, encoding='utf-8', newline='\n')
    print(folder.relative_to(ROOT).as_posix())
    return folder


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('build', type=Path)
    parser.add_argument('--attempt', help='New immutable attempt for the same frozen request; never overwrites earlier inputs')
    args = parser.parse_args()
    prepare(args.label, args.build, args.attempt)
