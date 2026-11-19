"""Create an auditable receipt from a completed immutable v4 operation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / 'local_runtime/dram-see-v4/transport-probe'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(label):
    operation = RUNTIME / 'operations' / label
    receipt = json.loads((operation / 'operation.json').read_text(encoding='utf-8'))
    if receipt['state'] not in ('COLLECTED_PENDING_AUDIT', 'FAILED_COLLECTED'):
        raise ValueError('Operation is not a completed collected attempt')
    source = operation / 'collected'
    request = json.loads((source / 'request.json').read_text(encoding='utf-8'))
    destination = RUNTIME / 'runs' / label
    shutil.copytree(source, destination)
    raw = operation / 'results.tar'
    record = {'schema': 'dram-see-v4-transport-run-v1', 'run_id': label,
              'mode': 'init' if request['mode'] == 'init' else 'events', 'arm': request['arm'],
              'runner_exit_code': receipt['ssh_exit_code'], 'remote_exit_code': receipt['remote_exit_code'],
              'collection_exit_code': receipt['collection_exit_code'],
              'runner_exit_definition': 'Actual SSH process return code for the synchronous wrapper; not an invented second process code',
              'request': request, 'input_sha256': receipt['input_sha256'],
              'binary_sha256': sha(destination / 'transport_probe'),
              'environment_sha256': sha(destination / 'environment.sh'),
              'dataset_inventory_sha256': sha(destination / 'dataset-inventory.json'),
              'raw_archive': {'path': raw.relative_to(ROOT).as_posix(), 'sha256': sha(raw)},
              'operation_evidence': {'path': (operation / 'operation.json').relative_to(ROOT).as_posix(), 'sha256': sha(operation / 'operation.json')},
              'single_thread_evidence': {'run_manager': 'G4RunManager', 'threads': 1, 'affinity_cpu_count': 1,
                                         'affinity_evidence_file': 'affinity.txt'},
              'provenance_files': {'binary': 'transport_probe', 'binary_witness': 'provenance.sha256',
                                   'environment': 'environment.sh', 'dataset_inventory': 'dataset-inventory.json'}}
    record['output_sha256'] = {p.relative_to(destination).as_posix(): sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    (destination / 'record.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(destination.relative_to(ROOT).as_posix())
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    args = parser.parse_args()
    collect(args.label)
