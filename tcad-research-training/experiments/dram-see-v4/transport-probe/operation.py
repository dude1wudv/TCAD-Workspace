"""Original v4 operation adapter, with identity-bound status and resumable collection.

The old LABEL INPUTS command and run() return code remain available. New jobs
have no execution deadline; --timeout limits only the local synchronous wait.
All native work keeps the original ownership, pinned SSH and shared solver lock.
"""
import argparse
from contextlib import ExitStack, nullcontext
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import tarfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = ROOT / 'local_runtime/dram-see-v4/transport-probe'
DEFAULT_RUNTIME = RUNTIME
CLOUD_INPUTS_ROOT = None
SCHEMA = 'dram-see-v4-transport-operation-v2'
COMPLETE_STATES = ('COLLECTED_PENDING_AUDIT', 'FAILED_COLLECTED')
IDENTITY_KEYS = ('schema', 'run_id', 'cwd', 'pid', 'start_ticks', 'boot_id', 'script_sha256')
PRIVILEGED_SSH_CONFIG = '/etc/tcad-centos79/ssh_config'
PRIVILEGED_SIM_ALIAS = 'tcad-guest-sim'
PRIVILEGED_ROOT_ALIAS = 'tcad-guest-root'
RESERVED_INPUTS = {
    'run.sh', 'exit-code.txt', 'operation-task-exit-code.txt', 'process-identity.json',
    'execution.log', 'launch.log', 'launch-pid.txt', 'started-utc.txt',
    'finished-utc.txt', 'shared-lock-evidence.txt', 'affinity.txt',
    '_collection-members.json', '.collection', '.launch-claim',
}


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def load_tcad(connection=None):
    global RUNTIME, CLOUD_INPUTS_ROOT
    spec = importlib.util.spec_from_file_location('_v4_pinned_tcad', ROOT / 'scripts/tcad.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if connection is not None:
        cfg = module.select_connection(connection)
        if module.connection_identity(cfg) is not None:
            RUNTIME = module.state_root() / 'dram-see-v4/transport-probe'
            CLOUD_INPUTS_ROOT = (ROOT / 'local_runtime/cloud-benchmark/geant4-preparation/inputs').resolve()
        else:
            RUNTIME, CLOUD_INPUTS_ROOT = DEFAULT_RUNTIME, None
    elif CLOUD_INPUTS_ROOT is not None:
        RUNTIME, CLOUD_INPUTS_ROOT = DEFAULT_RUNTIME, None
    return module


def operation_folder(label):
    if not isinstance(label, str) or not re.fullmatch('[a-z0-9][a-z0-9-]*', label):
        raise ValueError('Invalid immutable operation label')
    return RUNTIME / 'operations' / label


def save_record(folder, record, *, durable=False):
    record['updated_utc'] = utc()
    pending = folder / ('operation.' + uuid.uuid4().hex + '.tmp')
    with pending.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(record, indent=2) + '\n')
        if durable:
            stream.flush()
            os.fsync(stream.fileno())
    os.replace(pending, folder / 'operation.json')
    if durable and sys.platform != 'win32':
        descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def connection_identity(cfg):
    if cfg.get('backend', 'vmware') == 'ssh-runtime':
        return {key: cfg[key] for key in ('backend', 'ssh_target', 'runtime_entry', 'remote_root')}
    return None


def read_record(cfg, label):
    folder = operation_folder(label)
    record = json.loads((folder / 'operation.json').read_text(encoding='utf-8'))
    if record.get('connection_identity') != connection_identity(cfg):
        raise ValueError('Operation belongs to a different connection backend or runtime identity')
    expected = cfg['remote_root'].rstrip('/') + '/dram-see-v4/transport-probe/operations/' + label
    if record.get('label') != label or record.get('remote_directory') != expected:
        raise ValueError('Operation/original remote directory identity differs')
    return folder, record


def check_identity(record, identity):
    if not isinstance(identity, dict) or identity.get('schema') != 'tcad-process-identity-r1':
        raise ValueError('Original operation process identity is absent')
    if (identity.get('run_id') != record['label'] or identity.get('cwd') != record['remote_directory']
            or identity.get('script_sha256') != record['script_sha256']):
        raise ValueError('Original operation process identity differs')
    if any(type(identity.get(key)) is not int or identity[key] <= 0 for key in ('pid', 'start_ticks')):
        raise ValueError('Invalid original PID/start ticks')
    if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', identity.get('boot_id', '')) is None:
        raise ValueError('Invalid original boot identity')
    pinned = record.get('process_identity')
    if pinned and any(identity.get(key) != pinned.get(key) for key in IDENTITY_KEYS):
        raise ValueError('Original operation process identity changed')
    return {key: identity[key] for key in IDENTITY_KEYS}


def _reconciliation_module():
    source = Path(__file__).with_name('launch_reconciliation.py')
    spec = importlib.util.spec_from_file_location('_v4_launch_reconciliation', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verified_unlaunched_receipt(cfg, record, folder) -> bool:
    """Pure local verifier for Runtime: absent=False, invalid=ValueError."""
    return _reconciliation_module().verified_unlaunched_receipt(cfg, record, folder)


def _ssh_config_identity(alias):
    """Return only public routing identity; never expose key-file options."""
    result = subprocess.run(
        ['ssh', '-G', '-F', PRIVILEGED_SSH_CONFIG, alias],
        capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise ValueError('Fixed guest SSH config cannot resolve required alias')
    fields = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition(' ')
        if separator and key in ('hostname', 'port', 'hostkeyalias'):
            if key in fields:
                raise ValueError('Ambiguous VM identity in fixed guest SSH config')
            fields[key] = value.strip()
    if (set(fields) != {'hostname', 'port', 'hostkeyalias'}
            or fields['hostname'].lower() in ('', 'none')
            or fields['hostkeyalias'].lower() in ('', 'none')
            or not fields['port'].isdigit() or not 1 <= int(fields['port']) <= 65535):
        raise ValueError('Fixed guest SSH config has incomplete VM identity')
    return fields


def _privileged_proof_ssh():
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        raise PermissionError('privileged-proof requires server administrator euid 0')
    sim = _ssh_config_identity(PRIVILEGED_SIM_ALIAS)
    root = _ssh_config_identity(PRIVILEGED_ROOT_ALIAS)
    if sim != root:
        raise ValueError('Guest sim/root SSH aliases do not resolve to the same VM')
    # This object is constructed only for the prove action. It deliberately
    # has no runtime_entry, so the root alias executes the original protocol
    # directly inside the guest through the fixed private SSH config.
    proof_ssh = ['ssh', '-F', PRIVILEGED_SSH_CONFIG, '-o', 'BatchMode=yes',
                 '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
                 '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                 PRIVILEGED_ROOT_ALIAS]
    sim_ssh = ['ssh', '-F', PRIVILEGED_SSH_CONFIG, '-o', 'BatchMode=yes',
               '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
               '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
               PRIVILEGED_SIM_ALIAS]
    return proof_ssh, sim_ssh, dict(schema='tcad-privileged-proof-transport-r1',
                           mode='server-admin-root-ssh',
                           ssh_config=PRIVILEGED_SSH_CONFIG,
                           sim_alias=PRIVILEGED_SIM_ALIAS,
                           root_alias=PRIVILEGED_ROOT_ALIAS,
                           hostname=sim['hostname'], port=int(sim['port']),
                           hostkeyalias=sim['hostkeyalias'])


def _sim_boot_id(tcad, ssh):
    result = tcad.remote_python(
        ssh,
        "import json\nfrom pathlib import Path\n"
        "value=Path('/proc/sys/kernel/random/boot_id').read_text().strip()\n"
        "print(json.dumps({'boot_id': value}))",
        [])
    boot_id = result.get('boot_id') if isinstance(result, dict) else None
    if not isinstance(boot_id, str) or re.fullmatch(
            r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot_id) is None:
        raise ValueError('Original sim chain returned an invalid boot ID')
    return boot_id


def reconcile_unlaunched_operation(tcad, cfg, ssh, label, *,
                                   proof_ssh=None, proof_transport=None,
                                   sim_ssh=None):
    """Close only an original, proven never-reserved/never-launched intent."""
    with tcad.record_writer(operation_folder(label)):
        return _reconcile_unlaunched_operation(tcad, cfg, ssh, label, proof_ssh=proof_ssh,
                                               proof_transport=proof_transport, sim_ssh=sim_ssh)


def _reconcile_unlaunched_operation(tcad, cfg, ssh, label, *, proof_ssh, proof_transport, sim_ssh):
    folder, record = read_record(cfg, label)
    verifier = _reconciliation_module()
    if verifier.verified_unlaunched_receipt(cfg, record, folder):
        receipt = json.loads((folder / verifier.RECEIPT).read_bytes())
        if receipt['subject'] != verifier.frozen_subject(cfg, record, folder, tcad.CONFIG):
            raise ValueError('Repeated reconciliation changed the original frozen subject/profile')
        return _reconciliation_summary(record, folder)
    tcad.parallel_record_policy(cfg, record)
    subject = verifier.frozen_subject(cfg, record, folder, tcad.CONFIG)
    if (proof_ssh is None) != (proof_transport is None):
        raise ValueError('Privileged proof transport must be complete')
    query = dict(proof_subject_sha256=verifier.canonical_sha256(subject))
    if proof_ssh is not None:
        if not hasattr(os, 'geteuid') or os.geteuid() != 0:
            raise PermissionError('privileged-proof requires server administrator euid 0')
        sim_boot_id = _sim_boot_id(tcad, sim_ssh or ssh)
        query['proof_ssh'] = proof_ssh
    proof = tcad.parallel_query(cfg, ssh, record, 'prove-unlaunched', **query)
    if proof_transport is not None:
        if proof.get('boot_id') != sim_boot_id:
            raise ValueError('Privileged proof boot ID differs from original sim chain')
        proof['proof_transport'] = dict(proof_transport, sim_boot_id=sim_boot_id)
    verifier.validate_proof(proof, subject)
    # A remote read may take time. Freeze again before the sole local write.
    if verifier.frozen_subject(cfg, record, folder, tcad.CONFIG) != subject:
        raise ValueError('Original unlaunched evidence changed during the remote check')
    receipt = dict(schema=verifier.SCHEMA, status='not_launched', outcome='failed',
                   reservation_acquired=False, solver_launched=False, success=False,
                   created_utc=utc(), subject=subject,
                   subject_sha256=verifier.canonical_sha256(subject),
                   proof=proof, proof_sha256=verifier.canonical_sha256(proof))
    receipt['receipt_sha256'] = verifier.canonical_sha256(receipt)
    verifier.verify_receipt(cfg, record, folder, receipt)
    try:
        # O_EXCL prevents replacement of a receipt, including a dangling link.
        with (folder / verifier.RECEIPT).open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        # Concurrent identical original inputs can reuse only a valid receipt.
        if not verifier.verified_unlaunched_receipt(cfg, record, folder):
            raise ValueError('Conflicting original launch reconciliation receipt')
        existing = json.loads((folder / verifier.RECEIPT).read_bytes())
        if existing['subject'] != subject:
            raise ValueError('Conflicting original launch reconciliation subject')
    verifier.verified_unlaunched_receipt(cfg, record, folder)
    return _reconciliation_summary(record, folder)


def _reconciliation_summary(record, folder):
    return dict(label=record['label'], status='not_launched', outcome='failed',
                local_state=record['state'], launch_reconciled=True,
                reservation_acquired=False, solver_launched=False, success=False,
                receipt=str(folder / 'launch-reconciliation.json'))


def status_operation(tcad, cfg, ssh, label, *, for_seal=False):
    folder, record = read_record(cfg, label)
    if verified_unlaunched_receipt(cfg, record, folder):
        return dict(_reconciliation_summary(record, folder), status='NOT_LAUNCHED',
                    alive=False, remote_exit_code=None, ssh_exit_code=record.get('ssh_exit_code'))
    policy = tcad.parallel_record_policy(cfg, record)
    if not for_seal and policy and 'sealed_snapshot' not in record and not record.get('parallel_slot_released'):
        lease = tcad.parallel_query(cfg, ssh, record, 'verify')
        if lease.get('identity') is not None:
            record['process_identity'] = check_identity(record, lease['identity'])
    if record.get('schema') != SCHEMA:
        # Never upgrade old receipts or reinterpret their SSH failures.
        return dict(label=label, status='HISTORICAL_OPERATION', local_state=record['state'],
                    remote_exit_code=record.get('remote_exit_code'),
                    ssh_exit_code=record.get('ssh_exit_code'), historical_semantics=True)
    if record['state'] in COMPLETE_STATES:
        # Downstream packages bind operation.json itself; completed receipts stay immutable.
        return dict(summary(record, folder), status='FINISHED', alive=False, local_state=record['state'],
                    observation_source='completed_local_receipt')
    if 'sealed_snapshot' in record:
        return dict(record['last_observation'], local_state=record['state'], ssh_exit_code=record['ssh_exit_code'])
    if record.get('submission_phase') in ('INPUT_FREEZE', 'REMOTE_STAGING') or record['state'] == 'FAILED_BEFORE_LAUNCH':
        return dict(label=label, status='NOT_LAUNCHED', local_state=record['state'],
                    remote_exit_code=None, ssh_exit_code=record['ssh_exit_code'])
    observed = tcad.remote_python(ssh, tcad.STATUS_CODE,
                                 [record['remote_directory'], record['script_sha256']])
    if observed.get('directory') != record['remote_directory']:
        raise ValueError('Observed original operation directory differs')
    identity = observed.get('identity')
    if identity is not None:
        record['process_identity'] = check_identity(record, identity)
    elif observed.get('status') in ('RUNNING', 'FINISHED', 'LOST_WITHOUT_EXIT'):
        raise ValueError('Cannot establish the original operation process identity')
    if observed.get('status') == 'FINISHED':
        termination=observed.get('termination_record')
        proven=termination and termination.get('execution_outcome')=='TERMINATED_BY_OPERATOR'
        valid_raw=type(observed.get('remote_exit_code')) is int and 0<=observed['remote_exit_code']<=255
        if observed.get('alive') is not False or not (valid_raw or (proven and observed.get('remote_exit_code') is None)):
            raise ValueError('Original operation exit is not confirmed')
        if record['state'] in COMPLETE_STATES and record['remote_exit_code'] != observed['remote_exit_code']:
            raise ValueError('Previously collected original exit changed')
        record['remote_exit_code'] = observed['remote_exit_code']
    observed.update(label=label, observed_utc=utc())
    record['last_observation'] = observed
    if record['state'] not in COMPLETE_STATES:
        record['state'] = {'RUNNING': 'RUNNING', 'FINISHED': 'EXECUTED',
                           'LOST_WITHOUT_EXIT': 'LOST_WITHOUT_EXIT'}.get(observed['status'], record['state'])
    save_record(folder, record)
    return dict(observed, local_state=record['state'], ssh_exit_code=record['ssh_exit_code'])


def assert_no_outstanding_operation(tcad, cfg, ssh):
    for path in (RUNTIME / 'operations').glob('*/operation.json'):
        record = json.loads(path.read_text(encoding='utf-8'))
        if (record.get('schema') == SCHEMA and record.get('state') not in (*COMPLETE_STATES, 'FAILED_BEFORE_LAUNCH')
                and (record.get('staged_launch') or record.get('submission_phase') not in ('INPUT_FREEZE', 'REMOTE_STAGING'))
                and not tcad.sealed_and_released(record)):
            with tcad.record_writer(path.parent):
                observed = status_operation(tcad, cfg, ssh, record['label'])
                raise RuntimeError('Reconcile the original outstanding operation before a new launch: '
                                   + record['label'] + ' ' + observed['status'])
    tcad.assert_no_active_run(cfg, ssh)


def render_wrapper(tcad, cfg, directory, label, capture_svisual, policy=None, *, staged_launch=False):
    base = cfg['remote_root'].rstrip('/')
    capture_installation = cfg['tool_bin'].rstrip('/').rsplit('/', 1)[0]
    lines = [
        '#!/bin/bash', 'set -euo pipefail', 'umask 077', 'cd ' + shlex.quote(directory),
        'trap \'rc=$?; printf "%s\\n" "$rc" > exit-code.txt; date -u +%Y-%m-%dT%H:%M:%SZ > finished-utc.txt\' EXIT',
        "trap 'trap \"\" TERM INT; wait || :; exit 143' TERM",
        "trap 'trap \"\" TERM INT; wait || :; exit 130' INT",
        'exec > execution.log 2>&1',
    ] + tcad.process_identity_lines(label) + [
        'exec 9>' + shlex.quote(base + '/.solver.lock'),
        'flock -n 9 || { echo SHARED_SOLVER_LOCK_BUSY; exit 75; }',
        "printf 'status=ACQUIRED\\nfd=9\\nlock_path=%s\\npid=%s\\nacquired_utc=%s\\n' "
        + shlex.quote(base + '/.solver.lock')
        + ' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > shared-lock-evidence.txt',
        'for proc in /proc/[0-9]*; do',
        '  comm=$(cat "$proc/comm" 2>/dev/null || true)',
        '  case "$comm" in sdevice*|snmesh*|sde|transport*|cc1*|cmi*) echo ACTIVE_SOLVER_DETECTED "$comm"; exit 76;; esac',
        '  if [ "$comm" = svisual ] && tr "\\0" "\\n" < "$proc/cmdline" 2>/dev/null | grep -Eq "^(-b|-batch)$"; then',
        '    echo ACTIVE_SOLVER_DETECTED "$comm"; exit 76', '  fi', 'done',
        'export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1',
        "cpu=$(awk '/^Cpus_allowed_list:/{split($2,a,/[-,]/);print a[1]}' /proc/self/status)",
        'taskset -pc "$cpu" $$',
        "awk '/^(Threads|Cpus_allowed_list):/' /proc/self/status > affinity.txt",
        'date -u +%Y-%m-%dT%H:%M:%SZ > started-utc.txt',
    ] + tcad.native_capture_shell_lines() + [
        'bash task.sh &', 'operation_task_pid=$!',
        ('capture_observe svisual "$operation_task_pid" "$$" svisual ' + shlex.quote(capture_installation) + ' || true')
        if capture_svisual else ': # No exact SVisual command recognized; no native PID inferred.',
        'set +e', 'wait "$operation_task_pid"', 'operation_task_rc=$?', 'set -e',
        'printf \'%s\\n\' "$operation_task_rc" > operation-task-exit-code.txt',
        'if [ "$operation_task_rc" -ne 0 ]; then exit "$operation_task_rc"; fi',
    ]
    if policy:
        start = lines.index('exec 9>' + shlex.quote(base + '/.solver.lock'))
        stop = lines.index('date -u +%Y-%m-%dT%H:%M:%SZ > started-utc.txt') + 1
        lines = lines[:start] + tcad.parallel_shell_lines(policy, 'activate', staged_launch=staged_launch) + [
            'export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1',
            'cpu=' + str(policy['cpu']), 'taskset -pc "$cpu" $$',
            "awk '/^(Threads|Cpus_allowed_list):/' /proc/self/status > affinity.txt",
            'date -u +%Y-%m-%dT%H:%M:%SZ > started-utc.txt'] + lines[stop:]
    if capture_svisual:
        lines += ['set +e', 'capture_admit svisual svisual', 'operation_admission_rc=$?', 'set -e',
                  'printf \'%s\\n\' "$operation_admission_rc" > svisual-process-admission-exit-code.txt',
                  'if [ "$operation_admission_rc" -ne 0 ]; then exit "$operation_admission_rc"; fi']
    return '\n'.join(lines + ['echo V4_OPERATION_COMPLETED']) + '\n'


def safe_member_name(name):
    path = PurePosixPath(name)
    if (path.is_absolute() or not path.parts or path.as_posix() != name
            or any(part in ('.', '..') for part in path.parts) or '\\' in name or ':' in name):
        raise ValueError('Unsafe original archive member: ' + name)
    return path


def verify_operation_archive(tcad, path, record):
    # Reuse the original runner's complete SHA index and exact input checks.
    index = tcad.verify_archive(path, dict(record, steps=[]))
    with tarfile.open(path) as archive:
        for member in archive:
            safe_member_name(member.name)
        identity = json.load(archive.extractfile('process-identity.json'))
        check_identity(record, identity)
    return index


def verify_extracted(destination, index, archive):
    expected = dict(index)
    with tarfile.open(archive) as source:
        raw = source.extractfile('_collection-members.json').read()
    expected['_collection-members.json'] = dict(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    found = set()
    for path in destination.rglob('*'):
        if path.is_symlink():
            raise ValueError('Unexpected link in collected original output')
        if path.is_file():
            name = path.relative_to(destination).as_posix()
            facts = expected.get(name)
            if facts is None or path.stat().st_size != facts['size'] or sha(path) != facts['sha256']:
                raise ValueError('Collected original output differs: ' + name)
            found.add(name)
    if found != set(expected):
        raise ValueError('Collected original output is incomplete')


def extract_original(folder, archive, index):
    destination = folder / 'collected'
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError('Unsafe existing collected directory')
        verify_extracted(destination, index, archive)
        return
    staging = folder / 'collected.partial'
    if staging.is_symlink():
        raise ValueError('Unsafe partial collection directory')
    staging.mkdir(exist_ok=True)
    with tarfile.open(archive) as source:
        for member in source:
            target = staging.joinpath(*safe_member_name(member.name).parts)
            if any(path.is_symlink() for path in (target, *target.parents) if path != folder.parent):
                raise ValueError('Unexpected link in partial original collection')
            if target.exists():
                with source.extractfile(member) as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if not target.is_file() or target.stat().st_size != member.size or sha(target) != digest:
                    raise ValueError('Partial original extraction differs: ' + member.name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = folder / ('extraction-fragment-' + uuid.uuid4().hex + '.part')
            with source.extractfile(member) as stream, pending.open('xb') as out:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    out.write(block)
            os.replace(pending, target)
    verify_extracted(staging, index, archive)
    staging.rename(destination)


def operation_snapshot_context(record):
    return dict(input_sha256=record['input_sha256'], script_sha256=record['script_sha256'],
                identity=record.get('process_identity'), required_outputs=[],
                raw_exit_files=['operation-task-exit-code.txt'] + (
                    ['svisual-exit-code.txt', 'svisual-process-admission-exit-code.txt']
                    if record['capture_svisual_requested'] else []))


def seal_operation(tcad, cfg, ssh, label):
    with tcad.record_writer(operation_folder(label)):
        folder, record = read_record(cfg, label)
        tcad.parallel_record_policy(cfg, record)
        if record.get('schema') != SCHEMA:
            raise ValueError('Historical operation retains its original collection and exit semantics')
        if tcad.sealed_snapshot(record) is None:
            if record['state'] in COMPLETE_STATES:
                raise ValueError('Use collect to finish the existing original collection')
            observed = status_operation(tcad, cfg, ssh, label, for_seal=True)
            folder, record = read_record(cfg, label)
            receipt = tcad.seal_observed(cfg, ssh, folder, record, observed, operation_snapshot_context(record),
                                         save_record, 'operation.json')
            previous = record.get('collection_snapshot')
            if previous is not None and previous != receipt:
                raise ValueError('Immutable original collection snapshot changed')
            record['collection_snapshot'] = receipt
        return dict(tcad.finish_seal(cfg, ssh, folder, record, save_record), label=label)


def collect_operation(tcad, cfg, ssh, label):
    folder, record = read_record(cfg, label)
    policy = tcad.parallel_record_policy(cfg, record)
    if record.get('schema') != SCHEMA:
        raise ValueError('Historical operation retains its original collection and exit semantics')
    sealed = tcad.sealed_snapshot(record)
    interrupted_snapshot = record.get('interrupted_collection_snapshot') if sealed is not None else None
    target = folder / 'results.tar'
    if record['state'] in COMPLETE_STATES:
        if sha(target) != record['archive_sha256']:
            raise ValueError('Previously collected immutable archive changed')
        index = verify_operation_archive(tcad, target, record)
        if interrupted_snapshot is not None:
            tcad.verify_interrupted_archive(target, record, index, interrupted_snapshot,
                                            record['interrupted_collection_context'])
        verify_extracted(folder / 'collected', index, target)
        if sealed is None and policy and not record.get('parallel_slot_released'):
            tcad.parallel_release(cfg, ssh, record)
            save_record(folder, record)
        return summary(record, folder)
    if sealed is None:
        observed = status_operation(tcad, cfg, ssh, label)
        if observed['status'] != 'FINISHED' or observed['alive']:
            raise RuntimeError('Only the completed original operation can be collected: ' + observed['status'])
        folder, record = read_record(cfg, label)
    qdir = shlex.quote(record['remote_directory'])
    try:
        snapshot = sealed
        if snapshot is None:
            command = tcad.snapshot_command(cfg, record, operation_snapshot_context(record))
            response = tcad.remote(ssh, command, capture_output=True, text=True, timeout=300)
            snapshot = json.loads(response.stdout)
            previous = record.get('collection_snapshot')
            if previous and previous != snapshot:
                raise ValueError('Immutable original collection snapshot changed')
            record['collection_snapshot'] = snapshot
            save_record(folder, record)
        if target.exists():
            if sha(target) != snapshot['sha256'] or (sealed is not None and target.stat().st_size != snapshot['bytes']):
                raise ValueError('Refusing to replace a different existing archive')
        else:
            partial = folder / 'results.partial.tar'
            if partial.is_symlink():
                raise ValueError('Unsafe partial archive')
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > snapshot['bytes']:
                raise ValueError('Partial archive exceeds immutable snapshot')
            attempt = dict(started_utc=utc(), resumed_at_bytes=offset, ssh_exit_code=None)
            record.setdefault('collection_attempts', []).append(attempt)
            save_record(folder, record)
            transfer_command = 'tail -c +' + str(offset + 1) + ' ' + qdir + '/.collection/results.tar'
            (folder / 'collection-command.txt').write_text(transfer_command + '\n', encoding='utf-8')
            try:
                with partial.open('ab') as stream, (folder / ('collection-stderr-' + str(len(record['collection_attempts'])) + '.txt')).open('xb') as err:
                    transfer = tcad.remote(ssh, transfer_command, stdout=stream, stderr=err, timeout=300)
                attempt['ssh_exit_code'] = transfer.returncode
                record['collection_exit_code'] = transfer.returncode
            except BaseException as exc:
                actual = getattr(exc, 'returncode', None)
                if type(actual) is int:
                    attempt['ssh_exit_code'] = record['collection_exit_code'] = actual
                attempt['error'] = repr(exc)
                raise
            finally:
                attempt['finished_utc'] = utc()
                attempt['received_bytes'] = partial.stat().st_size - offset
                save_record(folder, record)
            if partial.stat().st_size != snapshot['bytes'] or sha(partial) != snapshot['sha256']:
                if partial.stat().st_size >= snapshot['bytes']:
                    retained = folder / ('results.rejected-' + uuid.uuid4().hex + '.tar')
                    partial.rename(retained)
                    record['rejected_archive'] = retained.name
                raise ValueError('Incomplete or changed original archive transfer; retain evidence and resume collect')
            verify_operation_archive(tcad, partial, record)
            partial.rename(target)
        if record['collection_exit_code'] != 0:
            raise ValueError('No actual successful original archive transfer')
        index = verify_operation_archive(tcad, target, record)
        if interrupted_snapshot is not None:
            tcad.verify_interrupted_archive(target, record, index, interrupted_snapshot,
                                            record['interrupted_collection_context'])
        raw_names = ['exit-code.txt', 'operation-task-exit-code.txt']
        if record['capture_svisual_requested']:
            raw_names += ['svisual-exit-code.txt', 'svisual-process-admission-exit-code.txt']
        exits, errors = tcad.capture_archive_exit_codes(target, raw_names)
        if exits['exit-code.txt'] != record['remote_exit_code']:
            raise ValueError('Observed and archived original exits differ')
        record['operation_task_exit_code'] = exits['operation-task-exit-code.txt']
        record['raw_exit_codes'] = exits
        record['capture_exit_errors'] = errors
        if record['capture_svisual_requested']:
            record['tool_exit_codes']['svisual'] = exits['svisual-exit-code.txt']
            record['process_admission_exit_code'] = exits['svisual-process-admission-exit-code.txt']
        if record['remote_exit_code'] == 0 and (errors or any(value != 0 for value in exits.values())):
            raise ValueError('Success marker conflicts with original task/native exits')
        extract_original(folder, target, index)
        with tarfile.open(target) as stream:termination=tcad.termination_module().verify_archive(stream,record)
        if termination:
            record['termination_record']=termination
            if termination['execution_outcome']=='TERMINATED_BY_OPERATOR':
                record.update(execution_outcome='TERMINATED_BY_OPERATOR',derived_exit_code=termination.get('derived_exit_code'))
        finished_file=folder/'collected/finished-utc.txt'
        finished_utc = (finished_file.read_text().strip()
                        if finished_file.is_file() or not (termination or interrupted_snapshot) else None)
        if interrupted_snapshot is not None:
            record.update(execution_outcome='INTERRUPTED_UNKNOWN_EXIT', interruption_reason='ORIGINAL_BOOT_REPLACED',
                          interruption_proof_sha256=interrupted_snapshot['interruption_proof_sha256'])
        record.update(archive_sha256=snapshot['sha256'], collected_bytes=snapshot['bytes'],
                      collection_verified=True, collected_utc=utc(),
                      finished_utc=finished_utc,
                      state='COLLECTED_PENDING_AUDIT' if record['remote_exit_code'] == 0 else 'FAILED_COLLECTED')
        record.pop('collection_error', None)
        save_record(folder, record)
        if policy and sealed is None:
            tcad.parallel_release(cfg, ssh, record)
            save_record(folder, record)
    except BaseException as exc:
        record['collection_error'] = repr(exc)
        save_record(folder, record)
        raise
    return summary(record, folder)


def summary(record, folder):
    return {**{key: record.get(key) for key in ('label', 'state', 'ssh_exit_code', 'remote_exit_code',
                                               'operation_task_exit_code', 'collection_exit_code', 'collection_verified')},
            'archive': str(folder / 'results.tar')}


def _run_operation(tcad, cfg, ssh, label, inputs, timeout, detach, parallel_slot=None, release_launch_owner=None):
    folder = operation_folder(label)
    directory = cfg['remote_root'].rstrip('/') + '/dram-see-v4/transport-probe/operations/' + label
    policy = tcad.parallel_policy(cfg, parallel_slot, label, directory, 'operation') if parallel_slot is not None else None
    if connection_identity(cfg) is not None and (DEFAULT_RUNTIME/'operations'/label).exists():
        raise ValueError('Historical VM operation label cannot be resubmitted through a cloud profile')
    if folder.exists():
        if policy:
            _, previous = read_record(cfg, label)
            if previous.get('parallel_policy') != policy:
                raise ValueError('Repeated operation label cannot change original slot/policy')
        return status_operation(tcad, cfg, ssh, label)
    inputs = Path(inputs).resolve()
    allowed_inputs = CLOUD_INPUTS_ROOT if connection_identity(cfg) is not None else RUNTIME.resolve()
    if allowed_inputs is None or not inputs.is_relative_to(allowed_inputs) or not (inputs / 'task.sh').is_file():
        raise ValueError('Inputs must be below the explicit backend input root with task.sh')
    paths = list(inputs.rglob('*'))
    if any(p.is_symlink() for p in paths):
        raise ValueError('No input links allowed')
    files = sorted(p for p in paths if p.is_file())
    for path in files:
        name = path.relative_to(inputs).as_posix()
        if safe_member_name(name).parts[0] in RESERVED_INPUTS:
            raise ValueError('Input collides with original operation evidence: ' + name)
    if policy:
        tcad.parallel_assert_local(cfg)
    else:
        assert_no_outstanding_operation(tcad, cfg, ssh)
    base = cfg['remote_root'].rstrip('/')
    directory = base + '/dram-see-v4/transport-probe/operations/' + label
    task_bytes = (inputs / 'task.sh').read_bytes()
    task_text = task_bytes.decode('utf-8')
    svisual_command = cfg['tool_bin'].rstrip('/') + '/svisual'
    capture_svisual = any(line.lstrip().startswith(prefix + separator)
                          for line in task_text.splitlines()
                          for prefix in (svisual_command, "'" + svisual_command + "'", '"' + svisual_command + '"')
                          for separator in (' ', '\t'))
    record = dict(schema=SCHEMA, label=label, started_utc=utc(), state='PREPARED', submission_phase='INPUT_FREEZE',
                  origin='native_pipeline', synthetic=False, automatic_retry=False,
                  detached=detach, ssh_exit_code=None, remote_exit_code=None, collection_exit_code=None,
                  operation_task_exit_code=None, tool_exit_codes={'svisual': None} if capture_svisual else {},
                  capture_svisual_requested=capture_svisual, collection_verified=False,
                  input_sha256={p.relative_to(inputs).as_posix(): sha(p) for p in files},
                  adapter_sha256=sha(Path(__file__)), runner_sha256=sha(ROOT / 'scripts/tcad.py'),
                  remote_directory=directory, input_directory=str(inputs),
                  interpretation='Engineering execution/collection only; scientific validity requires review')
    if connection_identity(cfg) is not None:
        record['connection_identity'] = tcad.connection_identity(cfg)
    if policy:
        record['parallel_policy'] = policy
    if release_launch_owner is not None:
        record['staged_launch'] = True
    if timeout is not None:
        record['local_wait_timeout_s'] = timeout
    folder.mkdir(parents=True, exist_ok=False)
    save_record(folder, record)
    try:
        with tarfile.open(folder / 'inputs.tar', 'x') as archive:
            for path in files:
                archive.add(path, arcname=path.relative_to(inputs).as_posix(), recursive=False)
        with tarfile.open(folder / 'inputs.tar') as archive:
            actual = {member.name: hashlib.file_digest(archive.extractfile(member), 'sha256').hexdigest()
                      for member in archive if member.isfile()}
        if actual != record['input_sha256'] or hashlib.sha256(task_bytes).hexdigest() != record['input_sha256']['task.sh']:
            raise ValueError('Input changed while freezing the original operation')
        wrapper = render_wrapper(tcad, cfg, directory, label, capture_svisual,
                                 **({'staged_launch': True} if release_launch_owner is not None else {}),
                                 **({'policy': policy} if policy else {}))
        (folder / 'run.sh').write_text(wrapper, encoding='utf-8', newline='\n')
        record.update(wrapper_sha256=sha(folder / 'run.sh'), script_sha256=sha(folder / 'run.sh'),
                      inputs_archive_sha256=sha(folder / 'inputs.tar'), submission_phase='REMOTE_STAGING')
        save_record(folder, record)
        if policy:
            tcad.parallel_query(cfg, ssh, record, 'reserve')
        if release_launch_owner is not None:
            save_record(folder, record, durable=True)
            tcad.sync_directory(folder.parent)
            release_launch_owner()
        tcad.remote(ssh, 'set -e; umask 077; mkdir -p ' + shlex.quote(base + '/dram-see-v4/transport-probe/operations')
                    + '; mkdir ' + shlex.quote(directory), timeout=30)
        with (folder / 'inputs.tar').open('rb') as stream:
            tcad.remote(ssh, 'tar -xf - -C ' + shlex.quote(directory), stdin=stream, timeout=120)
        tcad.remote(ssh, 'cat > ' + shlex.quote(directory + '/run.sh'), input=wrapper.encode(), timeout=30)
        record.update(state='LAUNCH_REQUESTED', submission_phase='LAUNCH')
        save_record(folder, record)
        command = ('set -e; cd ' + shlex.quote(directory) + '; mkdir .launch-claim || exit 76; '
                   '(nohup setsid bash ./run.sh </dev/null >launch.log 2>&1 & echo $! > launch-pid.txt)')
        with (folder / 'stdout.txt').open('xb') as out, (folder / 'stderr.txt').open('xb') as err:
            result = subprocess.run(tcad.remote_argv(ssh, command), stdout=out, stderr=err, timeout=30)
        record.update(ssh_exit_code=result.returncode,
                      state='LAUNCH_REQUESTED' if result.returncode == 0 else 'LAUNCH_UNCERTAIN')
        save_record(folder, record)
    except tcad.ReservationBusy as exc:
        tcad.retain_busy_attempt(folder, label, exc)
        raise
    except BaseException as exc:
        record.update(state='REQUIRES_READ_ONLY_RECONCILIATION' if record['submission_phase'] == 'LAUNCH'
                      else 'FAILED_BEFORE_LAUNCH', error=repr(exc))
        actual = getattr(exc, 'returncode', None)
        if type(actual) is int:
            record['ssh_exit_code'] = actual
        save_record(folder, record)
        raise
    started = time.monotonic()
    while True:
        observed = status_operation(tcad, cfg, ssh, label)
        if detach:
            return observed
        if observed['status'] == 'FINISHED':
            return collect_operation(tcad, cfg, ssh, label)
        if observed['status'] != 'RUNNING':
            return observed
        if timeout is not None and time.monotonic() - started >= timeout:
            return dict(observed, local_wait_expired=True, original_operation_untouched=True)
        time.sleep(min(60, max(0.1, timeout - (time.monotonic() - started))) if timeout is not None else 60)


def run(label, inputs, timeout=None, *, detach=False, owner_held=False, connection=None, parallel_slot=None,
        staged_launch=False):
    """Run once, or locate a repeated label. owner_held is for an already-held caller lock."""
    operation_folder(label)
    if timeout is not None and (isinstance(timeout, bool) or timeout <= 0):
        raise ValueError('Optional local wait timeout must be positive')
    if staged_launch and (not detach or parallel_slot is None or owner_held):
        raise ValueError('--staged-launch requires --detach, --parallel-slot and runner-owned scheduling')
    tcad = load_tcad(connection)
    try:
        with ExitStack() as launch_owner, ExitStack() as writers:
            if not owner_held:
                tcad.enter_launch_owner(launch_owner, staged_launch)
            folder = operation_folder(label)
            writers.enter_context(tcad.record_writer(folder))
            if staged_launch and not folder.exists():
                writers.enter_context(tcad.staged_project_writer(Path(inputs)))
            cfg, ssh, _ = tcad.connection()
            result = _run_operation(tcad, cfg, ssh, label, inputs, timeout, detach,
                                    **({'release_launch_owner': launch_owner.close} if staged_launch else {}),
                                    **({'parallel_slot': parallel_slot} if parallel_slot is not None else {}))
    except tcad.ReservationBusy as exc:
        print(json.dumps(exc.payload()), flush=True)
        return tcad.RESERVATION_BUSY_EXIT_CODE
    print(json.dumps(result, indent=2), flush=True)
    state = result.get('state', result.get('local_state'))
    accepted = (result.get('status') == 'RUNNING'
                or (result.get('status') == 'FINISHED' and result.get('remote_exit_code') == 0)
                or (result.get('status') == 'START_UNCONFIRMED' and result.get('ssh_exit_code') == 0))
    return 0 if state == 'COLLECTED_PENDING_AUDIT' or (detach and accepted) else 1


def status(label, *, owner_held=False, connection=None):
    tcad = load_tcad(connection)
    with (nullcontext() if owner_held else tcad.original_ownership()), tcad.record_writer(operation_folder(label)):
        cfg, ssh, _ = tcad.connection()
        return status_operation(tcad, cfg, ssh, label)


def collect(label, *, owner_held=False, connection=None):
    tcad = load_tcad(connection)
    folder = operation_folder(label)
    with (tcad.record_writer(folder) if owner_held else tcad.collection_owner(folder, 'operation.json')):
        cfg, ssh, _ = tcad.connection()
        return collect_operation(tcad, cfg, ssh, label)


def seal(label, *, connection=None):
    tcad = load_tcad(connection)
    cfg, ssh, _ = tcad.connection()
    return seal_operation(tcad, cfg, ssh, label)


def cancel(label, *, connection=None, reason, grace_seconds=15, requested_by='operator'):
    tcad=load_tcad(connection)
    with tcad.original_ownership(), tcad.record_writer(operation_folder(label)):
        cfg,ssh,_=tcad.connection()
        folder,record=read_record(cfg,label)
        if 'sealed_snapshot' in record:
            raise ValueError('Original operation is already sealed')
        return tcad.termination_module().cancel(tcad,cfg,ssh,folder,record,reason,grace_seconds,requested_by)


def reconcile_unlaunched(label, *, connection=None, privileged_proof=False):
    tcad = load_tcad(connection)
    with tcad.original_ownership():
        cfg, ssh, _ = tcad.connection()
        if privileged_proof:
            proof_ssh, sim_ssh, proof_transport = _privileged_proof_ssh()
            return reconcile_unlaunched_operation(
                tcad, cfg, ssh, label, proof_ssh=proof_ssh,
                proof_transport=proof_transport, sim_ssh=sim_ssh)
        return reconcile_unlaunched_operation(tcad, cfg, ssh, label)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    connection_parser = argparse.ArgumentParser(add_help=False)
    connection_parser.add_argument('--connection', type=Path)
    connection_args, argv = connection_parser.parse_known_args(argv)
    parser = argparse.ArgumentParser(description=__doc__, parents=[connection_parser])
    commands = ('status', 'collect', 'seal', 'reconcile-unlaunched', 'cancel')
    if argv and argv[0] in commands and not (len(argv) > 1 and Path(argv[1]).is_dir()):
        parser.add_argument('command', choices=commands)
        parser.add_argument('label')
        parser.add_argument('--json', action='store_true')
        parser.add_argument('--privileged-proof', action='store_true')
        parser.add_argument('--reason')
        parser.add_argument('--grace-seconds', type=int, default=15)
        parser.add_argument('--requested-by', default='operator')
        args = parser.parse_args(argv)
        if args.command=='cancel':
            if not args.reason:parser.error('cancel requires --reason')
            result=cancel(args.label,connection=connection_args.connection,reason=args.reason,
                          grace_seconds=args.grace_seconds,requested_by=args.requested_by)
            print(json.dumps(result,indent=2),flush=True)
            return 0
        if args.privileged_proof and args.command != 'reconcile-unlaunched':
            parser.error('--privileged-proof is only valid for reconcile-unlaunched')
        handler = {'status': status, 'collect': collect, 'seal': seal, 'reconcile-unlaunched': reconcile_unlaunched}[args.command]
        result = handler(args.label, connection=connection_args.connection,
                         **({'privileged_proof': True} if args.privileged_proof else {}))
        print(json.dumps(result, indent=2), flush=True)
        return 0
    parser.add_argument('label')
    parser.add_argument('inputs', type=Path)
    parser.add_argument('--detach', action='store_true')
    parser.add_argument('--staged-launch', action='store_true',
                        help='Release local scheduling ownership after a detached parallel reservation')
    parser.add_argument('--parallel-slot', type=int, choices=range(9))
    parser.add_argument('--timeout', type=float, default=None,
                        help='Optional local wait in seconds; does not stop or resubmit the original job')
    args = parser.parse_args(argv)
    return run(args.label, args.inputs, args.timeout, detach=args.detach, connection=connection_args.connection,
               **({'staged_launch': True} if args.staged_launch else {}),
               **({'parallel_slot': args.parallel_slot} if args.parallel_slot is not None else {}))


if __name__ == '__main__':
    raise SystemExit(main())
