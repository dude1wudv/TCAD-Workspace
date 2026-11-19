"""Fail-closed verification of an original operation's unlaunched receipt.

This module performs local reads only. A receipt closes a failed submission
intent; it never represents collection, a released lease, or scientific success.
Runtime callers must separately retain their original connection-file pin.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile

SCHEMA = 'tcad-launch-reconciliation-r1'
PROOF_SCHEMA = 'tcad-prove-unlaunched-r1'
RECEIPT = 'launch-reconciliation.json'
OPERATION_SCHEMA = 'dram-see-v4-transport-operation-v2'
HEX = re.compile(r'[0-9a-f]{64}')
BOOT = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
IDENTITY_KEYS = ('backend', 'ssh_target', 'runtime_entry', 'remote_root')


def need(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical_sha256(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode('utf-8'))


def _hash(value):
    return isinstance(value, str) and HEX.fullmatch(value) is not None


def _unlinked(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        try:
            item = part.lstat()
        except FileNotFoundError:
            continue
        need(not stat.S_ISLNK(item.st_mode)
             and not getattr(item, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0),
             'Linked reconciliation evidence: ' + str(part))
    return path


def _bytes(path):
    path = _unlinked(path)
    before = path.stat()
    need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
         'Unsafe reconciliation evidence inode: ' + str(path))
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        need((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
             == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns),
             'Reconciliation evidence changed while opening')
        raw = stream.read()
        after = os.fstat(stream.fileno())
    # Windows stat(path).st_ctime is creation time, while fstat(fd).st_ctime
    # can be metadata-change time. Compare like-for-like descriptor snapshots.
    need((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
         == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
         'Reconciliation evidence changed while reading')
    current = path.stat()
    need((current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
         == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
         'Reconciliation evidence path changed while reading')
    return raw


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'Duplicate reconciliation JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda value: need(False, 'Nonfinite JSON evidence'))


def _time(value):
    need(isinstance(value, str), 'Missing reconciliation check time')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0,
         'Reconciliation check time must be UTC')
    need(parsed <= datetime.now(timezone.utc), 'Reconciliation check time is in the future')
    return parsed


def _input_name(name):
    need(isinstance(name, str) and bool(name) and '\\' not in name,
         'Invalid original input member')
    path = PurePosixPath(name)
    need(bool(path.parts) and not path.is_absolute() and path.as_posix() == name
         and all(part not in ('.', '..') for part in path.parts),
         'Unsafe original input member')
    return path


def frozen_subject(cfg, record, folder, profile):
    """Read and bind the unchanged manifest, original profile and frozen inputs."""
    folder = _unlinked(folder)
    raw = _bytes(folder / 'operation.json')
    need(_json(raw) == record, 'Original manifest differs from the supplied record')
    need(isinstance(cfg, dict) and cfg.get('backend') == 'ssh-runtime',
         'Reconciliation requires the original SSH runtime profile')
    identity = {key: cfg[key] for key in IDENTITY_KEYS}
    need(record.get('schema') == OPERATION_SCHEMA
         and record.get('state') == 'FAILED_BEFORE_LAUNCH'
         and record.get('submission_phase') == 'REMOTE_STAGING',
         'Only a REMOTE_STAGING FAILED_BEFORE_LAUNCH intent can be reconciled')
    need(record.get('remote_exit_code') is None
         and record.get('collection_verified') is False
         and record.get('parallel_slot_released', False) is False
         and record.get('collection_exit_code') is None
         and record.get('operation_task_exit_code') is None,
         'Executed/collected/released evidence cannot be reconciled')
    for key in ('process_identity', 'last_observation', 'collection_snapshot',
                'archive_sha256', 'results_sha256', 'collection_attempts',
                'raw_exit_codes', 'finished_utc', 'collected_utc'):
        need(record.get(key) in (None, {}, []), 'Launch/collection evidence already exists: ' + key)
    need(all(value is None for value in record.get('tool_exit_codes', {}).values()),
         'Native execution exits already exist')
    # These are created only at/after LAUNCH in the original adapter.
    for name in ('stdout.txt', 'stderr.txt', 'process-identity.json', '.launch-claim',
                 'launch-pid.txt', 'exit-code.txt', 'results.tar', 'results.partial.tar',
                 'collected', '.collection'):
        need(not os.path.lexists(folder / name), 'Original launch/output artifact exists: ' + name)
    label = record.get('label')
    need(isinstance(label, str) and re.fullmatch(r'[a-z0-9][a-z0-9-]*', label) is not None
         and folder.name == label, 'Original operation label differs')
    root = cfg['remote_root']
    need(isinstance(root, str) and re.fullmatch(r'(?:/[A-Za-z0-9_.-]+)+', root) is not None
         and all(part not in ('.', '..') for part in root.split('/')),
         'Invalid original remote pool root')
    directory = root + '/dram-see-v4/transport-probe/operations/' + label
    need(record.get('connection_identity') == identity and record.get('remote_directory') == directory,
         'Original connection/directory identity differs')
    policy = record.get('parallel_policy')
    need(isinstance(policy, dict) and cfg.get('parallel_capacity') == 9
         and not any(key in cfg for key in ('requested_threads', 'cpu_sets')),
         'Reconciliation requires the original nine-slot single-core profile')
    slot = policy.get('slot')
    need(type(slot) is int and 0 <= slot < 9, 'Invalid original operation slot')
    expected = dict(schema='tcad-shared-gate-slots-r3', capacity=9, slot=slot, cpu=slot,
                    pool_root=root, connection_identity=identity, work_id=label,
                    remote_directory=directory, kind='operation')
    need(policy == expected, 'Original parallel profile/policy differs')
    profile = Path(profile)
    need(profile.is_absolute(), 'Original profile path must be absolute')
    profile_raw = _bytes(profile)
    need(_json(profile_raw) == cfg, 'Original connection profile contents differ')
    hashes = record.get('input_sha256')
    need(isinstance(hashes, dict) and 'task.sh' in hashes and all(_hash(v) for v in hashes.values()),
         'Missing original input SHA map')
    inputs = _unlinked(record['input_directory'])
    need(inputs.is_dir(), 'Original frozen input directory is missing')
    actual = {}
    for path in inputs.rglob('*'):
        _unlinked(path)
        if path.is_file():
            actual[path.relative_to(inputs).as_posix()] = digest(_bytes(path))
        else:
            need(path.is_dir(), 'Unknown original input inode')
    need(actual == hashes, 'Original inputs changed since freeze')
    for name in hashes:
        _input_name(name)
    archive_raw = _bytes(folder / 'inputs.tar')
    need(digest(archive_raw) == record.get('inputs_archive_sha256'), 'Original input archive SHA differs')
    members = {}
    with tarfile.open(folder / 'inputs.tar', 'r:') as archive:
        for member in archive:
            _input_name(member.name)
            need(member.isfile() and member.name not in members,
                 'Linked/duplicate/non-file original archive member')
            with archive.extractfile(member) as stream:
                members[member.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    need(members == hashes, 'Original archive member SHA map differs')
    need(digest(_bytes(folder / 'inputs.tar')) == digest(archive_raw), 'Input archive changed while reading')
    script_sha = digest(_bytes(folder / 'run.sh'))
    need(script_sha == record.get('script_sha256') == record.get('wrapper_sha256'),
         'Original wrapper/script SHA differs')
    for key in ('runner_sha256', 'adapter_sha256'):
        need(_hash(record.get(key)), 'Missing original program SHA: ' + key)
    return dict(manifest_sha256=digest(raw), label=label, remote_directory=directory,
                connection_identity=identity, parallel_policy=policy,
                profile=dict(path=str(profile), sha256=digest(profile_raw),
                             config_sha256=canonical_sha256(cfg)),
                input_sha256=hashes, inputs_archive_sha256=digest(archive_raw),
                script_sha256=script_sha, wrapper_sha256=script_sha,
                runner_sha256=record['runner_sha256'], adapter_sha256=record['adapter_sha256'])


def _snapshot_file(value):
    need(isinstance(value, dict) and _hash(value.get('sha256'))
         and isinstance(value.get('raw_hex'), str), 'Missing whole-file pool snapshot')
    raw = bytes.fromhex(value['raw_hex'])
    need(digest(raw) == value['sha256'] and _json(raw) == value.get('record'),
         'Pool snapshot whole-file SHA/content differs')
    return value['record']


def _resource_layouts():
    return {
        'tcad-shared-gate-slots-r4': ('tcad-slot-pool-r2', [[0, 1], [2, 3], [4, 5], [6, 7]]),
        'tcad-shared-gate-slots-r5': ('tcad-slot-pool-r3', [[0, 1, 2, 3], [4, 5, 6, 7]]),
        'tcad-shared-gate-slots-r6': ('tcad-slot-pool-r4', [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]),
        'tcad-shared-gate-slots-r7': ('tcad-slot-pool-r5', [[0], [1], [2], [3], [4], [5], [6, 7], [8, 9]]),
        'tcad-shared-gate-slots-r8': ('tcad-slot-pool-r6', [[cpu] for cpu in range(10)]),
        'tcad-shared-gate-slots-r9': ('tcad-slot-pool-r7', [list(range(10))]),
    }


def _validate_v2_cpu_sets(sets, requested_threads=None):
    need(isinstance(sets, list) and 1 <= len(sets) <= 64, 'Invalid v2 cpu_sets layout')
    seen = set()
    widths = []
    for group in sets:
        need(isinstance(group, list) and bool(group)
             and all(type(cpu) is int and 0 <= cpu <= 4095 for cpu in group)
             and group == sorted(set(group)), 'Invalid v2 cpu_set entry')
        for cpu in group:
            need(cpu not in seen, 'Overlapping CPU across v2 slots')
            seen.add(cpu)
        widths.append(len(group))
    if requested_threads is not None:
        if type(requested_threads) is int:
            need(len(set(widths)) == 1 and requested_threads == widths[0],
                 'Scalar v2 requested_threads differs')
        elif isinstance(requested_threads, list):
            need(len(requested_threads) == len(widths)
                 and all(type(t) is int and t == w for t, w in zip(requested_threads, widths)),
                 'Per-slot v2 requested_threads differs')
        else:
            need(False, 'Invalid v2 requested_threads')
    return widths


def _lease_policy(policy, index, subject):
    need(isinstance(policy, dict), 'Malformed lease policy')
    schema = policy.get('schema')
    if schema == 'tcad-shared-gate-slots-v2':
        sets = policy.get('cpu_sets')
        widths = _validate_v2_cpu_sets(sets)
        capacity = len(sets)
        need(type(policy.get('capacity')) is int and policy['capacity'] == capacity
             and type(policy.get('slot')) is int and policy['slot'] == index < capacity
             and policy.get('pool_root') == subject['parallel_policy']['pool_root']
             and policy.get('connection_identity') == subject['connection_identity']
             and type(policy.get('requested_threads')) is int
             and policy['requested_threads'] == widths[index]
             and policy.get('cpu_set') == sets[index]
             and policy.get('kind') == 'run', 'Historical dynamic v2 lease differs')
    else:
        layout = _resource_layouts().get(schema)
        legacy = {'tcad-shared-gate-slots-r1': 3, 'tcad-shared-gate-slots-r2': 7,
                  'tcad-shared-gate-slots-r3': 9}
        capacity = len(layout[1]) if layout else legacy.get(schema)
        need(capacity is not None and (capacity == 3 and 'capacity' not in policy
             or type(policy.get('capacity')) is int and policy['capacity'] == capacity),
             'Unknown historical lease resource protocol')
        need(type(policy.get('slot')) is int and policy['slot'] == index < capacity
             and policy.get('pool_root') == subject['parallel_policy']['pool_root']
             and policy.get('connection_identity') == subject['connection_identity'],
             'Historical lease pool/profile/slot identity differs')
        if layout:
            cpus = layout[1][index]
            need(type(policy.get('requested_threads')) is int and policy['requested_threads'] == len(cpus)
                 and policy.get('cpu_set') == cpus
                 and all(type(cpu) is int for cpu in policy['cpu_set'])
                 and policy.get('kind') == 'run', 'Historical multicore lease differs')
        else:
            need(type(policy.get('cpu')) is int and policy['cpu'] == index, 'Historical CPU lease differs')
    work, kind = policy.get('work_id'), policy.get('kind')
    need(isinstance(work, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', work) is not None
         and work != subject['label'] and kind in ('run', 'operation'), 'Target/unknown historical lease')
    expected = policy['pool_root'] + ('/runs/' if kind == 'run'
               else '/dram-see-v4/transport-probe/operations/') + work
    need(policy.get('remote_directory') == expected
         and expected != subject['remote_directory'], 'Target/unknown historical lease directory')


def validate_proof(proof, subject):
    """Validate all proof fields, including the full slot snapshot and boot."""
    need(isinstance(proof, dict) and proof.get('schema') == PROOF_SCHEMA
         and proof.get('action') == 'prove-unlaunched' and proof.get('status') == 'NOT_LAUNCHED',
         'Unknown original unlaunched proof')
    need(_hash(subject.get('script_sha256'))
         and proof.get('subject_sha256') == canonical_sha256(subject)
         and proof.get('policy') == subject['parallel_policy']
         and proof.get('script_sha256') == subject['script_sha256'],
         'Remote proof subject/profile/hash differs')
    return validate_idle_evidence(proof, subject)


def validate_idle_evidence(proof, subject):
    """Shared idle-pool facts; callers separately verify their own schema/subject."""
    for key in ('reservation_acquired', 'solver_launched', 'success',
                'directory_exists', 'launch_claim_exists'):
        need(proof.get(key) is False, 'Uncertain or positive remote proof field: ' + key)
    need(isinstance(proof.get('boot_id'), str) and BOOT.fullmatch(proof['boot_id']) is not None,
         'Missing original boot ID')
    _time(proof.get('observed_utc'))
    slots = proof.get('locked_slots')
    need(proof.get('gate_mode') == proof.get('allocator_mode') == 'EXCLUSIVE'
         and isinstance(slots, list) and 9 <= len(slots) <= 64
         and all(type(i) is int for i in slots) and slots == list(range(len(slots))),
         'Incomplete original lock proof')
    snapshot = proof.get('pool_snapshot')
    need(isinstance(snapshot, dict) and canonical_sha256(snapshot) == proof.get('pool_snapshot_sha256'),
         'Entire lease snapshot SHA differs')
    leases = snapshot.get('leases')
    need(isinstance(leases, dict) and set(leases) == {'slot-%s.json' % i for i in slots},
         'Incomplete slot lease inventory')
    for index in slots:
        item = leases['slot-%s.json' % index]
        if item is None:
            continue
        lease = _snapshot_file(item)
        need(isinstance(lease, dict) and lease.get('state') == 'COLLECTED'
             and _hash(lease.get('script_sha256')), 'Outstanding/unknown slot lease')
        _lease_policy(lease.get('policy'), index, subject)
    capacity = _snapshot_file(snapshot.get('capacity'))
    old = (isinstance(capacity, dict) and capacity.get('schema') == 'tcad-slot-pool-r1'
           and type(capacity.get('capacity')) is int and capacity['capacity'] in (3, 7, 9))
    new = False
    if isinstance(capacity, dict) and capacity.get('schema') == 'tcad-slot-pool-v2':
        try:
            widths = _validate_v2_cpu_sets(capacity.get('cpu_sets'), capacity.get('requested_threads'))
            expected_threads = widths[0] if len(set(widths)) == 1 else widths
            expected = dict(schema='tcad-slot-pool-v2', capacity=len(widths),
                            requested_threads=expected_threads, cpu_sets=capacity['cpu_sets'])
            new = len(widths) <= len(slots) and canonical_sha256(capacity) == canonical_sha256(expected)
        except ValueError:
            new = False
    if not new:
        for schema, groups in _resource_layouts().values():
            threads = [len(group) for group in groups]
            expected_threads = threads[0] if len(set(threads)) == 1 else threads
            expected = dict(schema=schema, capacity=len(groups), requested_threads=expected_threads, cpu_sets=groups)
            if len(groups) <= len(slots) and canonical_sha256(capacity) == canonical_sha256(expected):
                new = True
                break
    need(old or new, 'Unknown pool capacity snapshot')
    scan = proof.get('process_scan')
    need(isinstance(scan, dict) and scan.get('scope') == 'all-uid-native-cmdline-cwd'
         and type(scan.get('owner_uid')) is int and scan['owner_uid'] >= 0
         and type(scan.get('checked_processes')) is int and scan['checked_processes'] > 0
         and isinstance(scan.get('probe_ancestor_pids'), list) and bool(scan['probe_ancestor_pids'])
         and all(type(pid) is int and pid > 0 for pid in scan['probe_ancestor_pids']),
         'Unknown/incomplete native process inventory')
    transport = proof.get('proof_transport')
    if transport is not None:
        need(isinstance(transport, dict)
             and transport.get('schema') == 'tcad-privileged-proof-transport-r1'
             and transport.get('mode') == 'server-admin-root-ssh'
             and transport.get('ssh_config') == '/etc/tcad-centos79/ssh_config'
             and transport.get('sim_alias') == 'tcad-guest-sim'
             and transport.get('root_alias') == 'tcad-guest-root'
             and transport.get('sim_boot_id') == proof.get('boot_id')
             and isinstance(transport.get('hostname'), str)
             and transport['hostname'] and type(transport.get('port')) is int
             and 1 <= transport['port'] <= 65535
             and isinstance(transport.get('hostkeyalias'), str)
             and transport['hostkeyalias']
             and scan['owner_uid'] == 0,
             'Invalid privileged proof transport binding')
    return True


def verify_receipt(cfg, record, folder, receipt):
    need(isinstance(receipt, dict) and receipt.get('schema') == SCHEMA
         and receipt.get('status') == 'not_launched' and receipt.get('outcome') == 'failed',
         'Unknown launch reconciliation receipt')
    for key in ('reservation_acquired', 'solver_launched', 'success'):
        need(receipt.get(key) is False, 'Invalid reconciliation outcome: ' + key)
    need(receipt.get('receipt_sha256') == canonical_sha256(
        {key: value for key, value in receipt.items() if key != 'receipt_sha256'}),
        'Immutable reconciliation receipt SHA differs')
    stored = receipt.get('subject')
    need(isinstance(stored, dict) and isinstance(stored.get('profile'), dict),
         'Missing frozen reconciliation subject')
    subject = frozen_subject(cfg, record, folder, stored['profile']['path'])
    need(subject == stored and canonical_sha256(subject) == receipt.get('subject_sha256'),
         'Original reconciliation subject changed')
    proof = receipt.get('proof')
    need(canonical_sha256(proof) == receipt.get('proof_sha256'), 'Remote proof SHA differs')
    validate_proof(proof, subject)
    need(_time(receipt.get('created_utc')) >= _time(proof['observed_utc']),
         'Receipt predates the original remote check')
    return True


def verified_unlaunched_receipt(cfg, record, folder) -> bool:
    """Return False only for absence; malformed/stale evidence raises ValueError."""
    path = Path(folder) / RECEIPT
    try:
        _unlinked(path)
        if not os.path.lexists(path):
            return False
        return verify_receipt(cfg, record, folder, _json(_bytes(path)))
    except (OSError, KeyError, TypeError, AttributeError, OverflowError,
            UnicodeError, RecursionError, tarfile.TarError) as exc:
        raise ValueError('Invalid original launch reconciliation evidence: ' + str(exc)) from exc
