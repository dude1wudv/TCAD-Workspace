"""Trusted MC2 extraction action. No solver, readiness marker, backup or deletion.

This host-side adapter receives trusted roots from its operator. A model must
not supply workspace, run paths, commands, cache names, or reader modules.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

import result_maintenance as storage

READER = Path('experiments/dram-se-r04/electrical/multicore-response-reader-r1/extract.py')
SOURCE_SHA = '42d84e5d40f560bd3d775b4c4ee2683317f04433ac4786ceef95577df82d18d7'
CONTRACT_SHA = '77dc9ea2e4b63cb3f5c78d060afd962b68ac3b23c8904195d3df12f1aae0a8b8'


def inside(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or path.resolve()!=path or not path.is_relative_to(root):
        raise ValueError('redirected or noncanonical path')
    return path


def capture(workspace, task, run_id):
    root = Path(workspace).absolute()
    if root.resolve()!=root or not root.is_dir():
        raise ValueError('expected original workspace')
    reader = inside(root, READER)
    contract_path = inside(root, READER.with_name('contract.json'))
    if storage.sha(reader)!=SOURCE_SHA or storage.sha(contract_path)!=CONTRACT_SHA:
        raise ValueError('MC2 reader or contract changed')
    contract = storage.readj(contract_path)
    if task not in contract['tasks'] or not run_id or Path(run_id).name!=run_id or run_id in ('.','..'):
        raise ValueError('unsupported task or invalid run')
    inp = inside(root, contract['tasks'][task]['input'])
    folder = inside(root, Path(contract['run_root'])/run_id)
    cache = inside(root, Path('local_runtime/dram-se-r04')/('maintenance-'+run_id))
    with storage.transaction(storage.context(folder)[0]):
        _, m = storage.context(folder)
        archive = folder/'results.tar'
        if archive.is_symlink() or not archive.is_file():
            raise ValueError('requires separate verified restoration; no original tar')
        if m.get('project_directory')!=str(inp) or m.get('input_sha256')!=contract['tasks'][task]['hashes']:
            raise ValueError('run not bound to requested frozen inputs')
        before = storage.sha(folder/'manifest.json')
        if cache.exists():
            # A prior cache may be partial or unrelated. Nothing is overwritten.
            raise ValueError('maintenance cache exists; verify separately, do not re-extract')
        subprocess.run([sys.executable, '-I', '-B', str(reader), 'extract', str(folder), str(inp),
                        '--output-dir', str(cache)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, check=True)
        result=storage.readj(cache/'extraction.json'); receipt=storage.readj(cache/'receipt.json')
        proof=result['provenance']; reader_hashes={n:storage.sha(inside(root,READER.with_name(n)))
            for n in ('extract.py','archive.py','numeric.py','contract.json')}
        if not (result.get('schema')=='dram-se-r04-mc2-response-observation-r1'
                and result.get('status')=='observations_only_requires_scientific_interpretation'
                and result.get('synthetic') is False and receipt.get('is_scientific_acceptance') is False
                and receipt.get('schema')=='dram-se-r04-mc2-observation-cache-r1'
                and receipt.get('extraction_sha256')==storage.sha(cache/'extraction.json')
                and receipt.get('provenance')==proof and proof.get('task_id')==task and proof.get('run_id')==run_id
                and proof.get('manifest_sha256')==before==storage.sha(folder/'manifest.json')
                and proof.get('archive_sha256')==m['results_sha256'] and proof.get('input_sha256')==m['input_sha256']
                and receipt.get('mc2_reader_sha256')==result.get('mc2_reader_sha256')==reader_hashes):
            raise ValueError('new readout failed provenance checks; keep cache for diagnosis')
    return dict(stage='readout_extracted',extraction_sha256=receipt['extraction_sha256'],cleanup_authorized=False)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ('workspace','task','run-id'): ap.add_argument('--'+arg,required=True)
    a=ap.parse_args(); print(json.dumps(capture(a.workspace,a.task,a.run_id)))
