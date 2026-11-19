"""Explicit, single-run recovered-engineering contract; never manufactures original exits."""
from pathlib import Path
import importlib.util
import json
import hashlib
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V4 = HERE.parent
RUN_ID = '20261014T040702Z-v4-source-interface-r5-a1-b1-time-b8fc5db7'
LABEL = 'r5-a1-b1-time-r1'
RUN_FOLDER = ROOT / 'local_runtime/runs' / RUN_ID
EXECUTION_PATH = ROOT / 'local_runtime/dram-see-v4/source-interface-r5/launches' / LABEL / 'execution.json'
STATE = ROOT / 'local_runtime/dram-see-v4/interface-completion-r1/recovery-20261014'
CONTRACT = HERE / 'contract.json'
ARCHIVE_SHA = 'ca9b51554f10d4a4ffb846ee4bc1b49aa606d99ab7774287b6844ff5452d01df'
MANIFEST_SHA = '8b66b4947aa25164aef91ee3c55e9f17adeecafd26f75e44a02b441265943426'
EXECUTION_SHA = '933789b5f01e0ca9e3d0504d92fcac558e4c5febb6a185f3dff3a15dcef12770'

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def require(ok, message):
    if not ok: raise ValueError(message)
def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
    return digest.hexdigest()
def reference(path): return {'path': Path(path).resolve().relative_to(ROOT).as_posix(), 'sha256': sha(path)}
def is_original_execution(path): return Path(path).resolve() == EXECUTION_PATH.resolve()

def verify_execution(path, record):
    require(is_original_execution(path), 'Recovery is not authorized for this execution path')
    require(sha(path) == EXECUTION_SHA and record == read(EXECUTION_PATH), 'Original invocation bytes or supplied record changed')
    return verify()

def verify(run=None):
    run = RUN_FOLDER if run is None else Path(run).resolve()
    require(run == RUN_FOLDER.resolve(), 'Recovery run is outside the exact allowlist')
    c = read(CONTRACT)
    require(c['status'] == 'AUTHORIZED_SINGLE_RUN_ENGINEERING_EXCEPTION' and
            c['authorization']['user_answer'] == '授权该单次工程恢复例外', 'Missing explicit recovery exception authorization')
    require(c['run_id'] == RUN_ID and c['label'] == LABEL and c['archive_sha256'] == ARCHIVE_SHA and
            c['original_manifest_sha256'] == MANIFEST_SHA and c['original_execution_sha256'] == EXECUTION_SHA,
            'Recovery contract identity differs')
    require(sha(run / 'manifest.json') == MANIFEST_SHA and sha(EXECUTION_PATH) == EXECUTION_SHA,
            'Original execution or manifest changed; never synthesize success exits')
    execution = read(EXECUTION_PATH); manifest = read(run / 'manifest.json')
    require(execution['state'] == 'RUNNING' and execution['runner_exit_code'] is None and
            execution.get('ssh_exit_code') is None and manifest['state'] == 'RUNNING' and
            manifest.get('ssh_exit_code') is None, 'Original unknown exit facts changed')
    require(execution['new_round_position'] == 14 and execution['invocation_budget_position'] == 19 and
            execution['budget_category'] == 'primary' and execution['role_id'] == 'a1-b1-time', 'Original budget identity differs')
    require(manifest['run_id'] == RUN_ID and manifest['remote_directory'] == c['remote_directory'], 'Original run location differs')
    require(sha(run / 'results.tar') == ARCHIVE_SHA, 'Original result archive changed')
    require(sha(run / 'inputs.tar') == c['inputs_tar_sha256'], 'Original input archive changed')
    require(sha(run / 'run.sh') == c['run_script_sha256'], 'Original run script changed')
    receipt_path = ROOT / c['collection_receipt']['path']
    require(sha(receipt_path) == c['collection_receipt']['sha256'], 'Collection receipt changed')
    receipt = read(receipt_path)
    require(receipt['state'] == 'ORIGINAL_ARCHIVE_VERIFIED' and receipt['archive_sha256'] == ARCHIVE_SHA and
            receipt['collection_ssh_exit_code'] == 0 and receipt['original_remote_exit_code'] == 0 and
            receipt['all_remote_files_stable'] is True and receipt['archived_file_count'] == 849 and
            receipt['original_runner_exit_code'] is None and receipt['original_ssh_exit_code'] is None and
            receipt['engineering_marker_present'] is False and receipt['new_solver_calls'] == 0,
            'Collection receipt is incomplete or changes original facts')
    old = module(V4 / 'source-probe/audit_probe.py', '_recovery_frozen_primitives')
    report = {}
    project = (ROOT / execution['project']).resolve()
    require(manifest['input_sha256'] == execution['source_input_sha256'], 'Original input identity differs')
    with old.Archive(run / 'inputs.tar') as inputs:
        require(set(inputs.members) == set(manifest['input_sha256']), 'Original input file set differs')
        for name, digest in manifest['input_sha256'].items():
            require(inputs.digest(name) == digest == sha(project / name), 'Original/current input changed: ' + name)
    with old.Archive(run / 'results.tar') as archive:
        require(len(archive.members) == 849, 'Original file inventory differs')
        for name, digest in manifest['input_sha256'].items():
            require(archive.digest(name) == digest, 'Archived input changed: ' + name)
        require(archive.read('exit-code.txt').strip() == b'0', 'Original remote exit is nonzero/unknown')
        wrapper = archive.read('execution.log').decode('utf-8')
        require('ENGINEERING_RUN_COMPLETED' not in wrapper.splitlines(), 'Allowlisted marker observation changed')
        require(archive.read('run.sh') == (run / 'run.sh').read_bytes(), 'Original remote run script differs')
        script = archive.read('run.sh').decode('utf-8')
        for token in ('set -euo pipefail', '--threads 1 --exit-on-failure', 'OMP_NUM_THREADS=1', 'flock -n 9'):
            require(token in script, 'Missing original serial constraint: ' + token)
        require(old.json_load(archive.read('project.json'))['steps'] == manifest['steps'], 'Declared tool steps differ')
        for step in manifest['steps']:
            for name in step['outputs']:
                require(name in archive.members and archive.members[name].size > 0, 'Missing original output: ' + name)
        log = archive.read('transient_des.log').decode('utf-8')
        require('Sentaurus Device simulation finished' in log and 'Curve trace finished.' in log and
                "Writing plot 'final_access_des.tdr' (TDR format) ... done." in log, 'Native completion evidence incomplete')
        curves = old._curves(archive, report)
        require(len(curves['circuit']) == 1028 and len(curves['device']) == 1028, 'Allowlisted complete curves differ')
        frames = [name for name in archive.members if re.fullmatch(r'gstep_\d+_access_des.tdr', name)]
        require(len(frames) == 405, 'Original frame family incomplete')
        fields = module(V4 / 'source-field-audit-r2/audit_fields.py', '_recovery_frozen_frame_index')
        intervals, boundary = fields.index_frames(log, curves['device'], frames, True)
        require(len(intervals) == 404 and len(boundary) == 1, 'Original accepted frame coverage differs')
        mesh_sha = archive.digest('cell_msh.tdr')
        require(mesh_sha == c['mesh_sha256'], 'Original mesh identity differs')
        wall = re.search(r'wallclock:\s*([\d.]+) s', log)
        require(wall is not None, 'Missing native timing evidence')
    gate = ROOT / c['matched_a0_gate']['path']
    require(sha(gate) == c['matched_a0_gate']['sha256'], 'Matched A0 gate changed')
    result = dict(run_id=RUN_ID, manifest_sha256=MANIFEST_SHA, archive_sha256=ARCHIVE_SHA,
                  mesh_sha256=mesh_sha, solver_wallclock_s=float(wall[1]), original_manifest=manifest,
                  recovery_reference=reference(CONTRACT), original_execution_contract_passed=False,
                  recovered_engineering_evidence_passed=True, accepted_frame_count=len(intervals),
                  boundary_frame_count=len(boundary), original_runner_exit_code=None, original_ssh_exit_code=None,
                  original_remote_exit_code=0, collection_ssh_exit_code=0, engineering_marker_present=False)
    return result

def bind_report(out, run=None):
    proof = verify(run)
    for key in ('run_id', 'manifest_sha256', 'archive_sha256', 'mesh_sha256', 'solver_wallclock_s',
                'recovery_reference', 'original_execution_contract_passed', 'recovered_engineering_evidence_passed'):
        out[key] = proof[key]
    out['engineering_evidence'] = {key: proof[key] for key in ('original_runner_exit_code', 'original_ssh_exit_code',
        'original_remote_exit_code', 'collection_ssh_exit_code', 'engineering_marker_present')}
    out['engineering_evidence']['scope'] = 'Explicit user-authorized recovered engineering evidence; original execution contract did not pass'
    out['input_sha256'] = proof['original_manifest']['input_sha256']
    out['inputs_tar_sha256'] = sha(RUN_FOLDER / 'inputs.tar')
    out['run_script_sha256'] = sha(RUN_FOLDER / 'run.sh')
    out['solver_finished'] = True
    return proof['original_manifest']

def check_release():
    module(V4 / 'three-dimensional-pilot-r1/control.py', '_recovery_original_release').check_release()
    release = read(HERE / 'release.json')
    require(release['passed'] is True, 'Recovery implementation has not passed independent verification')
    for name, digest in release['files_sha256'].items():
        require(sha(ROOT / name) == digest, 'Recovery implementation changed: ' + name)
    for item in release['validation_evidence']:
        path = ROOT / item['path']
        require(sha(path) == item['sha256'] and read(path)['passed'] is True, 'Recovery validation evidence changed/failed')
    return reference(HERE / 'release.json')

if __name__ == '__main__':
    print(json.dumps(verify(), indent=2, ensure_ascii=False))
