"""Standard-library CLI for a private, pinned-host Sentaurus workstation."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
import time
import uuid

PREFLIGHT_EXIT_CODE = 75
RESERVATION_BUSY_EXIT_CODE = 74
ALLOCATION_WAIT_SECONDS = 8


class PreflightRejected(RuntimeError):
    """Remote slot reservation was rejected before creating any remote run dir or process."""


class ReservationBusy(RuntimeError):
    def __init__(self, lock):
        super().__init__('lock_busy: ' + lock)
        self.lock = lock
        self.diagnostic = None

    def payload(self):
        result = dict(status='ORIGINAL_ALLOCATOR_BUSY', error_code='lock_busy', retryable=True,
                      lock=self.lock, reservation_acquired=False, solver_launched=False)
        if self.diagnostic is not None:
            result['diagnostic'] = str(self.diagnostic)
        return result

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'local_runtime/connection.json'
STATE_ROOT = None


class RuntimeSSH(list):
    """SSH argv carrying one explicit private-runtime entry point."""
    def __init__(self, argv, entry):
        super().__init__(argv)
        self.runtime_entry = entry


def state_root():
    return STATE_ROOT if STATE_ROOT is not None else ROOT / 'local_runtime'


def connection_identity(cfg):
    if cfg.get('backend', 'vmware') == 'ssh-runtime':
        return {key: cfg[key] for key in ('backend', 'ssh_target', 'runtime_entry', 'remote_root')}
    return None


def select_connection(path):
    """Keep cloud state separate without reinterpreting historical VM manifests."""
    global CONFIG, STATE_ROOT
    candidate = Path(path).resolve()
    cfg = json.loads(candidate.read_text(encoding='utf-8'))
    backend = cfg.get('backend', 'vmware')
    if backend not in ('vmware', 'ssh-runtime'):
        raise ValueError('Unsupported connection backend')
    target_root = None
    if backend == 'ssh-runtime':
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', cfg.get('ssh_target', '')):
            raise ValueError('Runtime SSH target must be an explicit SSH alias')
        normalize_data_root(cfg.get('runtime_entry'))
        normalize_data_root(cfg.get('remote_root'))
        normalize_data_root(cfg.get('tool_bin'))
        target_root = Path(cfg.get('local_state_root', '')).resolve()
        allowed = (ROOT / 'local_runtime/cloud-benchmark').resolve()
        if allowed not in target_root.parents:
            raise ValueError('Cloud state must use a profile below local_runtime/cloud-benchmark')
    CONFIG, STATE_ROOT = candidate, target_root
    return cfg


def remote_argv(ssh, script):
    entry = getattr(ssh, 'runtime_entry', None)
    if entry:
        # Both stdin uploads and stdout downloads run as tcad inside this same chroot.
        script = 'exec ' + shlex.quote(entry) + ' /bin/bash -lc ' + shlex.quote(script)
    return list(ssh) + ['bash -lc ' + shlex.quote(script)]


def execute(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def connection():
    cfg = select_connection(CONFIG)
    if cfg.get('backend', 'vmware') == 'ssh-runtime':
        ssh = RuntimeSSH(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                          '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15',
                          '-o', 'ServerAliveCountMax=3', cfg['ssh_target']], cfg['runtime_entry'])
        return cfg, ssh, cfg['ssh_target']
    result = execute([cfg['vmrun'], 'getGuestIPAddress', cfg['vmx']],
                     capture_output=True, text=True, timeout=30)
    import ipaddress
    ip = ipaddress.IPv4Address(result.stdout.strip())
    if not ip.is_private or ip.is_loopback:
        raise ValueError('Expected a private VMware guest IPv4 address')
    ssh = ['ssh', '-i', cfg['identity'], '-o', 'IdentitiesOnly=yes',
           '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'HostKeyAlias=tcad-training-vm',
           '-o', 'UserKnownHostsFile=' + cfg['known_hosts'],
           '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15',
           '-o', 'ServerAliveCountMax=3', cfg['user'] + '@' + str(ip)]
    return cfg, ssh, str(ip)


def remote(ssh, script, **kwargs):
    return execute(remote_argv(ssh, script), **kwargs)


def doctor(cfg, ssh, ip):
    script = ('set -eu; export PATH=' + shlex.quote(cfg['tool_bin']) + ':"$PATH"; '
              'printf "SSH_OK\\n"; hostname; id -un; '
              'for tool in sde snmesh sdevice swb svisual; do command -v "$tool"; done; '
              'command -v flock; command -v taskset; command -v tar; '
              'getconf _NPROCESSORS_ONLN; df -h "$HOME"; sdevice -v')
    result = remote(ssh, script, capture_output=True, text=True, timeout=60)
    print(result.stdout)
    folder = state_root() / 'diagnostics'
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    (folder / (stamp + '.json')).write_text(json.dumps({
        'utc': stamp, 'ip': ip, 'stdout': result.stdout, 'stderr': result.stderr,
        'scope': 'SSH, executable discovery and version/license probe; not physics validation'
    }, indent=2), encoding='utf-8')


def native_capture_shell_lines(policy=None):
    """Existing-wrapper only: bounded exact-child /proc capture; never retry tools."""
    lines = [
        'capture_observe() {',
        '  taskset -c "$cpu" /usr/bin/python3 - "$1" "$2" "$3" "$4" "$5" <<\'S2_CAPTURE_PROC_PY\'',
        'import hashlib',
        'import json',
        'import os',
        'from pathlib import Path',
        'import re',
        'import sys',
        'import time',
        '',
        'tool, root_text, parent_text, prefix, installation = sys.argv[1:]',
        'root_pid, wrapper_pid = int(root_text), int(parent_text)',
        "if not re.fullmatch(r'(?:(?:step-[0-9]+-)?(?:sde|snmesh|sdevice|svisual|tdx)|metadata-sdevice-version)', prefix):",
        "    raise ValueError('Invalid capture evidence prefix')",
        "if tool not in ('sde', 'snmesh', 'sdevice', 'svisual', 'tdx'):",
        "    raise ValueError('Unknown native capture target')",
        "status_file = Path(prefix + '-process-status.txt')",
        "record_file = Path(prefix + '-process-observation.json')",
        'if status_file.exists() or record_file.exists():',
        "    print('CAPTURE_EVIDENCE_ALREADY_EXISTS ' + prefix, file=sys.stderr)",
        '    raise SystemExit(3)',
        "if not os.path.isabs(installation) or os.path.realpath(installation) == '/':",
        "    raise ValueError('A specific absolute native installation root is required')",
        "installation = os.path.realpath(installation).rstrip('/')",
        "record = dict(schema='native-process-observation-r1', origin='native_pipeline',",
        '              synthetic=False, requested_tool=tool, root_child_pid=root_pid,',
        '              wrapper_pid=wrapper_pid, installation_root=installation,',
        "              status='UNAVAILABLE', reason='NO_EXACT_NATIVE_IDENTITY_WITHIN_WINDOW',",
        '              maximum_observation_s=2.0, no_kill_or_retry=True)',
        '',
        'def read_process(pid):',
        "    base = Path('/proc') / str(pid)",
        "    stat_text = (base / 'stat').read_text()",
        "    rest = stat_text.rsplit(')', 1)[1].split()",
        '    start_ticks = int(rest[19])',
        "    raw = (base / 'status').read_text()",
        "    fields = dict(line.split(':', 1) for line in raw.splitlines() if ':' in line)",
        "    identity = dict(pid=pid, ppid=int(fields['PPid'].strip()), start_ticks=start_ticks,",
        "                    name=fields['Name'].strip())",
        "    children_text = (base / 'task' / str(pid) / 'children').read_text()",
        '    children = [int(item) for item in children_text.split()]',
        '    return identity, raw, children',
        '',
        'def exact_native(pid, identity):',
        "    native_name = 'svisual_exec' if tool == 'svisual' else tool",
        "    if identity['name'] != native_name:",
        '        return None',
        "    executable = os.readlink('/proc/{}/exe'.format(pid))",
        "    if executable.endswith(' (deleted)') or Path(executable).name != native_name:",
        '        return None',
        "    if not executable.startswith(installation + '/'):",
        '        return None',
        "    with open('/proc/{}/exe'.format(pid), 'rb') as stream:",
        "        if stream.read(4) != b'\\x7fELF':",
        '            return None',
        '    return executable',
        '',
        'def same_identity(expected):',
        "    observed, _, _ = read_process(expected['pid'])",
        "    return all(observed[key] == expected[key] for key in ('pid', 'ppid', 'start_ticks'))",
        '',
        'def select_native(matches, wait_channels):',
        '    if len(matches) == 1:',
        "        return matches[0], 'single_exact_native'",
        "    if tool != 'sde' or len(matches) < 2:",
        "        raise ValueError('MULTIPLE_EXACT_NATIVE_DESCENDANTS')",
        '    leaves = [item for item in matches if all(',
        "        other[3] == item[3][:len(other[3])] for other in matches)]",
        '    if len(leaves) != 1:',
        "        raise ValueError('BRANCHED_SDE_NATIVE_DESCENDANTS')",
        '    leaf = leaves[0]',
        '    if any(item[2] != leaf[2] for item in matches):',
        "        raise ValueError('SDE_NATIVE_EXECUTABLES_DIFFER')",
        '    for identity, raw, executable, chain in matches:',
        "        if identity['pid'] == leaf[0]['pid']:",
        '            continue',
        "        fields = dict(line.split(':', 1) for line in raw.splitlines() if ':' in line)",
        "        if fields.get('State', '').strip().split()[:1] != ['S'] or wait_channels.get(identity['pid']) != 'do_wait':",
        "            raise ValueError('SDE_NATIVE_ANCESTOR_NOT_WAITING_FOR_CHILD')",
        "    return leaf, 'unique_native_leaf_in_waiting_sde_chain'",
        '',
        'deadline = time.monotonic() + 2.0',
        'initial_root = None',
        'while time.monotonic() < deadline:',
        '    try:',
        '        root_identity, root_status, root_children = read_process(root_pid)',
        "        if root_identity['ppid'] != wrapper_pid:",
        "            record['reason'] = 'ROOT_NO_LONGER_CHILD_OF_WRAPPER'",
        '            break',
        '        if initial_root is None:',
        '            initial_root = root_identity',
        "        elif any(root_identity[key] != initial_root[key] for key in ('pid', 'ppid', 'start_ticks')):",
        "            record['reason'] = 'ROOT_PROCESS_IDENTITY_CHANGED'",
        '            break',
        '        queue = [(root_identity, root_status, root_children, [root_identity])]',
        '        seen, matches, child_map = set(), [], {}',
        '        while queue:',
        '            identity, raw, children, chain = queue.pop(0)',
        "            pid = identity['pid']",
        '            if pid in seen:',
        '                continue',
        '            seen.add(pid)',
        '            child_map[pid] = children',
        '            if len(seen) > 128:',
        "                raise ValueError('DESCENDANT_TREE_TOO_LARGE')",
        '            try:',
        '                executable = exact_native(pid, identity)',
        '                if executable:',
        '                    matches.append((identity, raw, executable, chain))',
        '            except (OSError, ValueError, KeyError):',
        '                pass',
        '            for child_pid in children:',
        '                try:',
        '                    child, child_raw, descendants = read_process(child_pid)',
        "                    if child['ppid'] == pid:",
        '                        queue.append((child, child_raw, descendants, chain + [child]))',
        '                except (OSError, ValueError, KeyError, IndexError):',
        '                    pass',
        '        if len(matches) > 1:',
        "            record.update(status='AMBIGUOUS', reason='MULTIPLE_EXACT_NATIVE_DESCENDANTS',",
        "                          candidates=[dict(pid=item[0]['pid'], executable=item[2],",
        '                                           parent_chain=item[3]) for item in matches])',
        "            if tool != 'sde':",
        '                break',
        '        if matches:',
        '            wait_channels = {}',
        '            if len(matches) > 1:',
        "                wait_channels = {item[0]['pid']: (Path('/proc') / str(item[0]['pid']) / 'wchan').read_text().strip() for item in matches}",
        "                record['candidate_snapshots'] = [dict(identity=item[0], executable=item[2], parent_chain=item[3],",
        "                    raw_status=item[1], wait_channel=wait_channels[item[0]['pid']],",
        "                    scope='unadmitted actual candidate snapshot') for item in matches]",
        '            try:',
        '                selected, selection_method = select_native(matches, wait_channels)',
        '            except ValueError as exc:',
        "                record['reason'] = str(exc)",
        '                time.sleep(0.05)',
        '                continue',
        '            identity, raw, executable, chain = selected',
        '            if not all(same_identity(node) for node in chain):',
        "                record['reason'] = 'ANCESTRY_CHANGED_DURING_OBSERVATION'",
        '                break',
        "            observed, raw_after, _ = read_process(identity['pid'])",
        "            if observed != identity or exact_native(identity['pid'], observed) != executable:",
        "                record['reason'] = 'NATIVE_IDENTITY_CHANGED_DURING_OBSERVATION'",
        '                break',
        '            family_snapshots = []',
        '            if len(matches) > 1:',
        '                for expected, prior_raw, member_exe, member_chain in sorted(matches, key=lambda item: len(item[3])):',
        "                    current, member_raw, current_children = read_process(expected['pid'])",
        "                    if current != expected or exact_native(expected['pid'], current) != member_exe or current_children != child_map[expected['pid']]:",
        "                        raise ValueError('SDE_FAMILY_IDENTITY_OR_CHILDREN_CHANGED')",
        "                    wait_raw = (Path('/proc') / str(expected['pid']) / 'wchan').read_text()",
        "                    member_fields = dict(line.split(':', 1) for line in member_raw.splitlines() if ':' in line)",
        "                    if expected['pid'] != identity['pid'] and (member_fields.get('State', '').strip().split()[:1] != ['S'] or wait_raw.strip() != 'do_wait'):",
        "                        raise ValueError('SDE_ANCESTOR_WAIT_STATE_CHANGED')",
        '                    family_snapshots.append((current, member_raw, member_exe, member_chain, wait_raw))',
        '                if not all(same_identity(node) for node in chain):',
        "                    raise ValueError('SDE_FAMILY_ANCESTRY_CHANGED')",
        "                raw_after = next(item[1] for item in family_snapshots if item[0]['pid'] == identity['pid'])",
        "            # Preserve the target process's actual kernel status, including a",
        '            # violating thread/CPU value. The evidence consumer decides gates.',
        "            with status_file.open('x', encoding='utf-8', newline='') as stream:",
        '                stream.write(raw_after)',
        '            family = []',
        '            for member, member_raw, member_exe, member_chain, wait_raw in family_snapshots:',
        "                member_status = Path(prefix + '-process-family-' + str(member['pid']) + '-status.txt')",
        "                member_wait = Path(prefix + '-process-family-' + str(member['pid']) + '-wchan.txt')",
        "                with member_status.open('x', encoding='utf-8', newline='') as stream:",
        '                    stream.write(member_raw)',
        "                with member_wait.open('x', encoding='utf-8', newline='') as stream:",
        '                    stream.write(wait_raw)',
        '                family.append(dict(identity=member, executable=member_exe, parent_chain=member_chain,',
        '                    status_file=member_status.name, status_sha256=hashlib.sha256(member_raw.encode()).hexdigest(),',
        '                    wait_channel_file=member_wait.name, wait_channel_sha256=hashlib.sha256(wait_raw.encode()).hexdigest(),',
        "                    status_source='/proc/{}/status'.format(member['pid']), wait_channel_source='/proc/{}/wchan'.format(member['pid'])))",
        "            fields = dict(line.split(':', 1) for line in raw_after.splitlines() if ':' in line)",
        "            record.update(status='OBSERVED', reason=None, native_pid=identity['pid'],",
        "                          native_executable=executable, native_start_ticks=identity['start_ticks'],",
        "                          parent_chain=chain, status_source='/proc/{}/status'.format(identity['pid']),",
        '                          status_file=status_file.name,',
        '                          status_sha256=hashlib.sha256(raw_after.encode()).hexdigest(),',
        "                          observed_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),",
        "                          observed_threads=fields['Threads'].strip(),",
        "                          observed_cpus_allowed_list=fields['Cpus_allowed_list'].strip(),",
        '                          selection_method=selection_method, native_candidate_count=len(matches), native_process_family=family,',
        "                          observation_scope=('actual native family snapshot, including waiting SDE ancestors; not whole-run proof' if family else 'single actual native process snapshot; not whole-run proof'))",
        '            break',
        '    except (OSError, ValueError, KeyError, IndexError) as exc:',
        "        record['last_observation_error'] = type(exc).__name__ + ': ' + str(exc)",
        '    time.sleep(0.05)',
        'if initial_root is not None:',
        "    record['root_identity'] = initial_root",
        "with record_file.open('x', encoding='utf-8') as stream:",
        '    json.dump(record, stream, indent=2)',
        "    stream.write('\\n')",
        "print('CAPTURE_PROCESS_' + record['status'] + ' ' + prefix)",
        'S2_CAPTURE_PROC_PY',
        '}',
        'capture_admit() {',
        '  taskset -c "$cpu" /usr/bin/python3 - "$1" "$2" "$cpu" <<\'S2_CAPTURE_ADMIT_PY\'',
        'import hashlib',
        'import json',
        'from pathlib import Path',
        'import re',
        'import sys',
        '',
        'prefix, tool, requested_cpu = sys.argv[1:]',
        "report_path = Path(prefix + '-process-admission.json')",
        'if report_path.exists():',
        "    raise ValueError('Never overwrite process admission evidence')",
        'errors = []',
        'try:',
        "    observation = json.loads(Path(prefix + '-process-observation.json').read_text())",
        "    status_raw = Path(prefix + '-process-status.txt').read_bytes()",
        "    status = status_raw.decode('utf-8')",
        "    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)",
        "    if observation.get('status') != 'OBSERVED':",
        "        errors.append('Native identity was missing or ambiguous')",
        "    native_name = 'svisual_exec' if tool == 'svisual' else tool",
        "    if observation.get('requested_tool') != tool or fields.get('Name', '').strip() != native_name:",
        "        errors.append('Native tool identity differs')",
        "    if str(observation.get('native_pid')) != fields.get('Pid', '').strip():",
        "        errors.append('Observed native PID differs from raw status')",
        "    if hashlib.sha256(status_raw).hexdigest() != observation.get('status_sha256'):",
        "        errors.append('Raw process status hash differs')",
        "    if fields.get('Threads', '').strip() != '1':",
        "        errors.append('Actual native process Threads is not 1')",
        "    cpu_value = fields.get('Cpus_allowed_list', '').strip()",
        "    if re.fullmatch(r'[0-9]+', cpu_value) is None or cpu_value != requested_cpu:",
        "        errors.append('Actual native CPU is not the single taskset CPU')",
        "    family = observation.get('native_process_family', [])",
        "    if observation.get('selection_method') == 'unique_native_leaf_in_waiting_sde_chain':",
        "        if tool != 'sde' or len(family) < 2 or observation.get('native_candidate_count') != len(family):",
        "            errors.append('Incomplete SDE native family evidence')",
        "        leaf_chain = observation['parent_chain']",
        '        family_ids = []',
        '        for member in family:',
        "            member_identity = member['identity']; member_pid = member_identity['pid']",
        '            family_ids.append(member_pid)',
        "            expected_status = prefix + '-process-family-' + str(member_pid) + '-status.txt'",
        "            expected_wait = prefix + '-process-family-' + str(member_pid) + '-wchan.txt'",
        "            if member['status_file'] != expected_status or member['wait_channel_file'] != expected_wait:",
        "                raise ValueError('SDE family evidence filename differs')",
        "            member_raw = Path(expected_status).read_bytes(); wait_raw = Path(expected_wait).read_bytes()",
        "            member_fields = dict(line.split(':', 1) for line in member_raw.decode('utf-8').splitlines() if ':' in line)",
        "            if hashlib.sha256(member_raw).hexdigest() != member['status_sha256'] or hashlib.sha256(wait_raw).hexdigest() != member['wait_channel_sha256']:",
        "                errors.append('SDE family raw evidence hash differs')",
        "            if member_fields.get('Name', '').strip() != 'sde' or member_fields.get('Pid', '').strip() != str(member_pid) or member_fields.get('PPid', '').strip() != str(member_identity['ppid']):",
        "                errors.append('SDE family raw identity differs')",
        "            if member_fields.get('Threads', '').strip() != '1' or member_fields.get('Cpus_allowed_list', '').strip() != requested_cpu:",
        "                errors.append('Actual SDE family member is not single-thread/single-CPU')",
        "            chain = member['parent_chain']",
        "            if not chain or chain[-1] != member_identity or chain != leaf_chain[:len(chain)] or member['executable'] != observation['native_executable']:",
        "                errors.append('SDE family is not one same-ELF ancestor chain')",
        "            if member_pid != observation['native_pid'] and (member_fields.get('State', '').strip().split()[:1] != ['S'] or wait_raw.decode().strip() != 'do_wait'):",
        "                errors.append('Actual SDE ancestor is not waiting for a child')",
        "            if member_pid == observation['native_pid'] and member_raw != status_raw:",
        "                errors.append('Selected native leaf differs from family evidence')",
        "        if len(set(family_ids)) != len(family_ids) or observation['native_pid'] not in family_ids:",
        "            errors.append('SDE family identities are incomplete or duplicated')",
        "    elif family or observation.get('selection_method') not in (None, 'single_exact_native'):",
        "        errors.append('Unregistered native process selection method')",
        'except (OSError, ValueError, KeyError, TypeError) as exc:',
        "    errors.append(type(exc).__name__ + ': ' + str(exc))",
        "report = dict(schema='native-process-admission-r1', origin='native_pipeline', synthetic=False,",
        '              requested_tool=tool, requested_cpu=requested_cpu,',
        "              status='FAILED' if errors else 'PASSED', errors=errors,",
        "              scope='capture admission only; not scientific acceptance',",
        '              actual_native_exit_is_separate=True)',
        "with report_path.open('x', encoding='utf-8') as stream:",
        '    json.dump(report, stream, indent=2)',
        "    stream.write('\\n')",
        "print('CAPTURE_ADMISSION_' + report['status'] + ' ' + prefix)",
        'raise SystemExit(86 if errors else 0)',
        'S2_CAPTURE_ADMIT_PY',
        '}',
        'capture_native_step() {',
        '  local capture_prefix="$1" capture_tool="$2" capture_installation="$3"',
        '  shift 3',
        '  taskset -c "$cpu" "$@" &',
        '  local capture_child_pid=$!',
        '  if [ "$capture_prefix" != metadata-sdevice-version ]; then',
        '    capture_observe "$capture_tool" "$capture_child_pid" "$$" "$capture_prefix" "$capture_installation" || true',
        '  fi',
        '  set +e',
        '  wait "$capture_child_pid"',
        '  local capture_child_rc=$?',
        '  set -e',
        '  printf \'%s\\n\' "$capture_child_rc" > "$capture_prefix-exit-code.txt"',
        '  if [ "$capture_child_rc" -ne 0 ] || [ "$capture_prefix" = metadata-sdevice-version ]; then',
        '    return "$capture_child_rc"',
        '  fi',
        '  set +e',
        '  capture_admit "$capture_prefix" "$capture_tool"',
        '  local capture_admission_rc=$?',
        '  set -e',
        '  printf \'%s\\n\' "$capture_admission_rc" > "$capture_prefix-process-admission-exit-code.txt"',
        '  return "$capture_admission_rc"',
        '}',
    ]
    return multicore_capture_lines(lines, policy) if is_multicore(policy) else lines


# Shared by the existing remote protocol, its capture code and offline archive
# verification. Keep this source compatible with the guest's Python 3.6.
MULTICORE_SCHEMA = 'tcad-shared-gate-slots-r4'
MULTICORE_CPU_SETS = [[0, 1], [2, 3], [4, 5], [6, 7]]
QUADCORE_SCHEMA = 'tcad-shared-gate-slots-r5'
QUADCORE_CPU_SETS = [[0, 1, 2, 3], [4, 5, 6, 7]]
FIVEX2_SCHEMA = 'tcad-shared-gate-slots-r6'
FIVEX2_CPU_SETS = [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]
MIXED_SCHEMA = 'tcad-shared-gate-slots-r7'
MIXED_CPU_SETS = [[0], [1], [2], [3], [4], [5], [6, 7], [8, 9]]
TENX1_SCHEMA = 'tcad-shared-gate-slots-r8'
ONETEN_SCHEMA = 'tcad-shared-gate-slots-r9'
DYNAMIC_SLOTS_SCHEMA = 'tcad-shared-gate-slots-v2'
DYNAMIC_POOL_SCHEMA = 'tcad-slot-pool-v2'
MULTICORE_AUDIT_CODE = r'''
import os,re,time
from pathlib import Path
def mc_need(ok, message):
    if not ok:raise ValueError(message)
class MCTransientSnapshotError(ValueError):
    pass
class MCTaskSnapshotUnavailable(FileNotFoundError):
    pass
def mc_cpus(text):
    mc_need(isinstance(text,str) and re.fullmatch(r'[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*',text) is not None,
            'Malformed observed CPU set')
    result=[]
    for part in text.split(','):
        ends=[int(x) for x in part.split('-')]
        mc_need(len(ends)==1 or ends[0]<=ends[1],'Reversed observed CPU range')
        mc_need(max(ends)<=4095,'Observed CPU exceeds bounded audit range')
        result.extend(range(ends[0],ends[-1]+1))
    mc_need(len(result)==len(set(result)),'Duplicated observed CPU')
    return sorted(result)
def mc_validate_cpu_sets(sets, requested_threads=None):
    mc_need(isinstance(sets,list) and 1<=len(sets)<=64,'Invalid cpu_sets layout')
    seen=set()
    widths=[]
    for group in sets:
        mc_need(isinstance(group,list) and bool(group)
            and all(type(c) is int and 0<=c<=4095 for c in group)
            and group==sorted(set(group)),'Invalid cpu_set entry')
        for c in group:
            mc_need(c not in seen,'Overlapping CPU across slots')
            seen.add(c)
        widths.append(len(group))
    if requested_threads is not None:
        if type(requested_threads) is int:
            mc_need(len(set(widths))==1 and requested_threads==widths[0],
                'Scalar requested_threads must match uniform cpu_sets width')
        elif isinstance(requested_threads,list):
            mc_need(len(requested_threads)==len(widths)
                and all(type(t) is int and t==w for t,w in zip(requested_threads,widths)),
                'Per-slot requested_threads must match cpu_sets widths')
        else:
            mc_need(False,'Invalid requested_threads')
    return widths
def mc_layout(schema):
    return {'tcad-shared-gate-slots-r4':(4,2,[[0,1],[2,3],[4,5],[6,7]]),
            'tcad-shared-gate-slots-r5':(2,4,[[0,1,2,3],[4,5,6,7]]),
            'tcad-shared-gate-slots-r6':(5,2,[[0,1],[2,3],[4,5],[6,7],[8,9]]),
            'tcad-shared-gate-slots-r7':(8,None,[[0],[1],[2],[3],[4],[5],[6,7],[8,9]]),
            'tcad-shared-gate-slots-r8':(10,1,[[cpu] for cpu in range(10)]),
            'tcad-shared-gate-slots-r9':(1,10,[list(range(10))])}.get(schema)
def mc_is_multicore(value):
    return isinstance(value,dict) and (mc_layout(value.get('schema')) is not None or value.get('schema')=='tcad-shared-gate-slots-v2')
def mc_pool_configuration(schema, cpu_sets=None):
    if schema=='tcad-shared-gate-slots-v2':
        widths=mc_validate_cpu_sets(cpu_sets)
        requested_threads=widths[0] if len(set(widths))==1 else widths
        return dict(schema='tcad-slot-pool-v2',capacity=len(cpu_sets),cpu_sets=[list(g) for g in cpu_sets],requested_threads=requested_threads)
    capacity,threads,sets=mc_layout(schema)
    if type(threads) is int:
        thread_values=[threads]*capacity
    else:
        thread_values=threads or [len(group) for group in sets]
    pool_schema={'tcad-shared-gate-slots-r4':'tcad-slot-pool-r2',
                 'tcad-shared-gate-slots-r5':'tcad-slot-pool-r3',
                 'tcad-shared-gate-slots-r6':'tcad-slot-pool-r4',
                 'tcad-shared-gate-slots-r7':'tcad-slot-pool-r5',
                 'tcad-shared-gate-slots-r8':'tcad-slot-pool-r6',
                 'tcad-shared-gate-slots-r9':'tcad-slot-pool-r7'}[schema]
    requested_threads=thread_values[0] if len(set(thread_values))==1 else thread_values
    return dict(schema=pool_schema,capacity=capacity,cpu_sets=sets,requested_threads=requested_threads)
def mc_policy(value):
    if value.get('schema')=='tcad-shared-gate-slots-v2':
        sets=value.get('cpu_sets')
        widths=mc_validate_cpu_sets(sets)
        capacity=len(sets)
        slot=value.get('slot')
        mc_need(type(value.get('capacity')) is int and value['capacity']==capacity
            and type(slot) is int and 0<=slot<capacity
            and type(value.get('requested_threads')) is int
            and value['requested_threads']==widths[slot]
            and type(value.get('cpu_set')) is list
            and all(type(x) is int for x in value['cpu_set'])
            and value['cpu_set']==sets[slot]
            and 'cpu' not in value and value.get('kind')=='run','Invalid dynamic multicore resource policy')
        return value['cpu_set']
    layout=mc_layout(value.get('schema'))
    mc_need(layout is not None,'Invalid multicore resource schema')
    capacity,threads,sets=layout
    slot=value.get('slot')
    mc_need(type(value.get('capacity')) is int and value['capacity']==capacity
        and type(slot) is int and 0<=slot<capacity
        and type(value.get('requested_threads')) is int
        and value['requested_threads']==len(sets[slot])
        and type(value.get('cpu_set')) is list
        and all(type(x) is int for x in value['cpu_set'])
        and value['cpu_set']==sets[slot]
        and 'cpu' not in value and value.get('kind')=='run','Invalid multicore resource policy')
    return value['cpu_set']
def mc_fields(raw):
    return dict((k,v.strip()) for k,v in (line.split(':',1) for line in raw.splitlines() if ':' in line))
def mc_validate(snapshot, cpus, threads, pid=None, ticks=None, cwd=None, exact=False):
    mc_need(snapshot.get('schema')=='tcad-task-resource-snapshot-r1'
        and type(snapshot.get('cpu_set')) is list
        and all(type(cpu) is int for cpu in snapshot['cpu_set'])
        and snapshot['cpu_set']==cpus and type(snapshot.get('threads')) is int
        and snapshot['threads']>0 and (threads is None or snapshot['threads']==threads),
        'Resource snapshot CPU/thread contract differs')
    main=mc_fields(snapshot['status'])
    actual_pid=snapshot['pid']
    os_threads=snapshot['threads']
    allowed=mc_cpus(main.get('Cpus_allowed_list'))
    mc_need(type(actual_pid) is int and actual_pid>0
        and type(snapshot.get('start_ticks')) is int and snapshot['start_ticks']>0
        and main.get('Pid')==str(actual_pid) and main.get('Tgid')==str(actual_pid)
        and main.get('Threads')==str(os_threads) and set(allowed)<=set(cpus)
        and (not exact or allowed==cpus),
        'Actual process CPU set or thread count differs')
    mc_need((pid is None or actual_pid==pid) and (ticks is None or snapshot['start_ticks']==ticks)
        and (cwd is None or snapshot.get('cwd')==cwd),'Resource snapshot original identity differs')
    tasks=snapshot['tasks']
    mc_need(len(tasks)==os_threads and len(set(t['tid'] for t in tasks))==os_threads
        and actual_pid in [t['tid'] for t in tasks],'Actual task count differs')
    for task in tasks:
        fields=mc_fields(task['status'])
        mc_need(type(task.get('tid')) is int and task['tid']>0
            and type(task.get('start_ticks')) is int and task['start_ticks']>0
            and fields.get('Pid')==str(task['tid']) and fields.get('Tgid')==str(actual_pid)
            and fields.get('Threads')==str(os_threads)
            and set(mc_cpus(fields.get('Cpus_allowed_list')))<=set(cpus),
            'Actual task CPU set or thread count differs')
        if task['tid']==actual_pid:
            mc_need(task['start_ticks']==snapshot['start_ticks'],'Original main task identity differs')
    return snapshot
def _mc_snapshot_once(proc_root, pid, cpus, threads, cwd, ticks=None, exact=False):
    base=proc_root/str(pid)
    before=(base/'stat').read_text().rsplit(')',1)[1].split()
    mc_need(before[0]!='Z','Resource process is a zombie')
    mc_need(ticks is None or int(before[19])==ticks,'Resource snapshot original identity differs')
    status=(base/'status').read_text()
    main=mc_fields(status)
    allowed=mc_cpus(main.get('Cpus_allowed_list'))
    mc_need(main.get('Pid')==str(pid) and main.get('Tgid')==str(pid)
        and set(allowed)<=set(cpus) and (not exact or allowed==cpus),
        'Actual process CPU set or thread count differs')
    os_threads=main.get('Threads','')
    mc_need(os_threads.isdigit() and int(os_threads)>0,'Invalid actual OS thread count')
    task_root=base/'task'
    tids=sorted(int(p.name) for p in task_root.glob('[0-9]*'))
    tasks=[]
    for tid in tids:
        task=task_root/str(tid)
        try:
            first=(task/'stat').read_text().rsplit(')',1)[1].split()
            raw=(task/'status').read_text()
            fields=mc_fields(raw)
            mc_need(fields.get('Pid')==str(tid) and fields.get('Tgid')==str(pid)
                and set(mc_cpus(fields.get('Cpus_allowed_list')))<=set(cpus),
                'Actual task CPU set or thread count differs')
            last=(task/'stat').read_text().rsplit(')',1)[1].split()
        except FileNotFoundError as exc:
            missing=MCTaskSnapshotUnavailable(*exc.args)
            missing.filename=exc.filename
            raise missing from exc
        except ProcessLookupError as exc:
            raise MCTransientSnapshotError('Task exited while reading resource evidence') from exc
        if first[19]!=last[19] or last[0]=='Z':
            raise MCTransientSnapshotError('Task identity changed during resource audit')
        tasks.append(dict(tid=tid,start_ticks=int(first[19]),status=raw))
    after=(base/'stat').read_text().rsplit(')',1)[1].split()
    mc_need(before[19]==after[19] and after[0]!='Z',
        'Original process identity changed during resource audit')
    if (tids!=sorted(int(p.name) for p in task_root.glob('[0-9]*'))
        or len(tids)!=int(os_threads)
        or mc_fields((base/'status').read_text()).get('Threads')!=os_threads
        or any(mc_fields(task['status']).get('Threads')!=os_threads for task in tasks)):
        raise MCTransientSnapshotError('Process/task membership changed during resource audit')
    value=dict(schema='tcad-task-resource-snapshot-r1',pid=pid,start_ticks=int(before[19]),
        cwd=os.readlink(str(base/'cwd')),cpu_set=cpus,threads=int(os_threads),status=status,tasks=tasks)
    return mc_validate(value,cpus,threads,pid,ticks,cwd,exact)
def mc_snapshot(proc_root, pid, cpus, threads, cwd, ticks=None, exact=False):
    # /proc is not atomic: a native worker may exit between enumeration and read.
    # Retry the complete observation; never accept a partially observed task set.
    original=(proc_root/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
    mc_need(original[0]!='Z','Resource process is a zombie')
    original_ticks=int(original[19])
    mc_need(ticks is None or original_ticks==ticks,'Resource snapshot original identity differs')
    for attempt in range(8):
        try:
            return _mc_snapshot_once(proc_root,pid,cpus,threads,cwd,original_ticks,exact)
        except (MCTaskSnapshotUnavailable,MCTransientSnapshotError):
            if attempt==7:raise
            time.sleep(0.01)
'''
_MULTICORE_HELPERS = {}
exec(compile(MULTICORE_AUDIT_CODE, '<shared multicore audit>', 'exec'), _MULTICORE_HELPERS)


def is_multicore(policy):
    return _MULTICORE_HELPERS['mc_is_multicore'](policy)


def multicore_capture_lines(lines, policy):
    """Extend r4/r5 captures; historical single-core shell bytes stay intact."""
    _MULTICORE_HELPERS['mc_policy'](policy)
    lines = list(lines)
    config = 'mc_config = ' + repr(policy)
    # Each embedded interpreter receives exactly the same checked contract.
    for marker in ('prefix, tool, requested_cpu = sys.argv[1:]',
                   'tool, root_text, parent_text, prefix, installation = sys.argv[1:]'):
        at = lines.index(marker)
        lines[at:at] = MULTICORE_AUDIT_CODE.splitlines() + [config]
    at = lines.index('            # Preserve the target process\'s actual kernel status, including a')
    lines[at:at] = [
        "            mc_threads = None if tool == 'sdevice' else 1",
        "            mc_native = mc_snapshot(Path('/proc'), identity['pid'], mc_config['cpu_set'], mc_threads, os.getcwd(), identity['start_ticks'])",
        "            mc_wrapper = mc_snapshot(Path('/proc'), wrapper_pid, mc_config['cpu_set'], 1, os.getcwd(), exact=True)",
        "            mc_family = [mc_snapshot(Path('/proc'), item[0]['pid'], mc_config['cpu_set'], 1, os.getcwd(), item[0]['start_ticks']) for item in family_snapshots]",
        "            raw_after = mc_native['status']",
        "            family_snapshots = [(member, next(s['status'] for s in mc_family if s['pid']==member['pid']), exe, chain_part, wait) for member, raw, exe, chain_part, wait in family_snapshots]",
        "            record.update(schema='native-process-observation-r2', resource_policy=mc_config,",
        "                          native_resources=mc_native, wrapper_resources=mc_wrapper, family_resources=mc_family)",
    ]
    replacements = {
        "    if fields.get('Threads', '').strip() != '1':":
            "    if not fields.get('Threads', '').strip().isdigit() or int(fields['Threads'])<1 or (tool!='sdevice' and fields['Threads'].strip()!='1'):",
        "        errors.append('Actual native process Threads is not 1')":
            "        errors.append('Actual native process Threads differs from resource policy')",
        "    if re.fullmatch(r'[0-9]+', cpu_value) is None or cpu_value != requested_cpu:":
            "    if not set(mc_cpus(cpu_value))<=set(mc_config['cpu_set']) or mc_cpus(requested_cpu)!=mc_config['cpu_set']:",
        "        errors.append('Actual native CPU is not the single taskset CPU')":
            "        errors.append('Actual native CPU set differs from resource policy')",
        "            if member_fields.get('Threads', '').strip() != '1' or member_fields.get('Cpus_allowed_list', '').strip() != requested_cpu:":
            "            if member_fields.get('Threads', '').strip() != '1' or mc_cpus(member_fields.get('Cpus_allowed_list', '').strip()) != mc_config['cpu_set']:",
        "report = dict(schema='native-process-admission-r1', origin='native_pipeline', synthetic=False,":
            "report = dict(schema='native-process-admission-r2', origin='native_pipeline', synthetic=False, resource_policy=mc_config, requested_threads=mc_config['requested_threads'] if tool=='sdevice' else 1,",
    }
    for old, new in replacements.items():
        lines[lines.index(old)] = new
    at = lines.index("    family = observation.get('native_process_family', [])")
    lines[at:at] = [
        "    mc_need(observation.get('schema')=='native-process-observation-r2' and observation.get('resource_policy')==mc_config, 'Native observation resource policy differs')",
        "    mc_validate(observation['native_resources'], mc_config['cpu_set'], None if tool=='sdevice' else 1, observation['native_pid'], observation['native_start_ticks'], os.getcwd())",
        "    mc_validate(observation['wrapper_resources'], mc_config['cpu_set'], 1, observation['wrapper_pid'], cwd=os.getcwd(), exact=True)",
        "    mc_need(observation['native_resources']['status']==status, 'Native resource/raw status differs')",
        "    mc_need(len(observation['family_resources'])==len(observation.get('native_process_family', [])), 'Missing SDE family resource evidence')",
        "    for member in observation.get('native_process_family', []):",
        "        snapshot = next(s for s in observation['family_resources'] if s['pid']==member['identity']['pid'])",
        "        mc_validate(snapshot, mc_config['cpu_set'], 1, member['identity']['pid'], member['identity']['start_ticks'], os.getcwd())",
        "        mc_need(snapshot['status']==Path(member['status_file']).read_text(), 'SDE family resource/raw status differs')",
    ]
    return lines


def capture_archive_exit_codes(archive_path, names):
    """Read only explicit raw exit members; absent/invalid/duplicate stays None."""
    values = {name: None for name in names}
    errors = {}
    with tarfile.open(archive_path) as archive:
        members = {name: [] for name in names}
        for member in archive:
            name = member.name[2:] if member.name.startswith('./') else member.name
            if name in members:
                members[name].append(member)
        for name, found in members.items():
            if len(found) != 1 or not found[0].isfile() or found[0].size > 64:
                errors[name] = 'missing, ambiguous, nonregular, or oversized raw exit'
                continue
            raw = archive.extractfile(found[0]).read()
            if re.fullmatch(rb'[0-9]+\s*', raw) is None or not 0 <= int(raw) <= 255:
                errors[name] = 'invalid raw POSIX exit code'
                continue
            values[name] = int(raw)
    return values, errors


import importlib.util
from contextlib import ExitStack, contextmanager
from pathlib import PurePosixPath


def utc():
    return datetime.now(timezone.utc).isoformat()


def load_module(path, name):
    definition = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


def geometry_module():
    return load_module(ROOT/'experiments/dram-see-v4/continuous/device/geometry_bridge.py', '_continuous_geometry')


@contextmanager
def original_ownership(*, shared=False):
    """Use the existing byte lock; never call the historical queue/budget paths."""
    directory = ROOT/'experiments/dram-see-v4/nuclear-closure-r1'
    previous = sys.modules.get('common')
    sys.modules['common'] = load_module(directory/'common.py', '_original_owner_common')
    try:
        supervisor = load_module(directory/'supervisor.py', '_original_owner_supervisor')
    finally:
        if previous is None:
            sys.modules.pop('common', None)
        else:
            sys.modules['common'] = previous
    if not shared:
        with supervisor.ownership():
            yield
        return
    import fcntl
    path = supervisor.OWNER_LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another scheduler owns the shared local lock') from exc
        if not os.path.samestat(os.fstat(stream.fileno()), path.stat()):
            raise RuntimeError('Original local scheduling lock inode changed')
        yield


def enter_launch_owner(owner, staged_launch):
    deadline = time.monotonic() + ALLOCATION_WAIT_SECONDS
    while True:
        try:
            ownership = original_ownership(shared=True) if staged_launch and sys.platform.startswith('linux') else original_ownership()
            owner.enter_context(ownership)
            return
        except RuntimeError as exc:
            if not staged_launch or str(exc) != 'Another scheduler owns the shared local lock':
                raise
            if time.monotonic() >= deadline:
                raise ReservationBusy('local-owner') from exc
            time.sleep(0.1)


def retain_busy_attempt(folder, work_id, failure):
    diagnostics = folder.parent / '.allocator-busy'
    diagnostics.mkdir(exist_ok=True)
    failure.diagnostic = diagnostics / (work_id + '-' + uuid.uuid4().hex)
    save_json_record(folder/'allocator-busy.json', failure.payload(), durable=True)
    folder.rename(failure.diagnostic)
    sync_directory(diagnostics)
    sync_directory(folder.parent)


def validate_run_id(run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,150}', run_id):
        raise ValueError('Invalid immutable run ID')
    return run_id


def run_folder(run_id):
    return state_root()/'runs'/validate_run_id(run_id)


@contextmanager
def record_writer(folder):
    lock_dir = folder.parent / '.writers'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / (folder.name + '.lock')).open('a+b') as stream:
        windows = sys.platform == 'win32'
        if windows:
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
        else:
            import fcntl
        try:
            if windows:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Another runner is writing original work ' + folder.name) from exc
        yield


@contextmanager
def staged_project_writer(project):
    canonical = os.path.normcase(str(project.resolve()))
    lock_name = hashlib.sha256(os.fsencode(canonical)).hexdigest()
    with ExitStack() as writers:
        try:
            writers.enter_context(record_writer(ROOT/'local_runtime'/'staged-projects'/lock_name))
        except RuntimeError as exc:
            raise ReservationBusy('local-project') from exc
        yield


@contextmanager
def collection_owner(folder, filename):
    with record_writer(folder), ExitStack() as owner:
        path = folder / filename
        if not path.is_file() or 'sealed_snapshot' not in json.loads(path.read_text(encoding='utf-8')):
            owner.enter_context(original_ownership())
        yield


def sync_directory(path):
    if sys.platform != 'win32':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def save_json_record(path, record, *, durable=False):
    pending = path.with_name(path.stem + '.' + uuid.uuid4().hex + '.tmp')
    with pending.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(record, indent=2) + '\n')
        if durable:
            stream.flush()
            os.fsync(stream.fileno())
    os.replace(pending, path)
    if durable:
        sync_directory(path.parent)


def save_manifest(folder, evidence, *, durable=False):
    evidence['updated_utc'] = utc()
    save_json_record(folder/'manifest.json', evidence, durable=durable)


DATA_ROOT_LAYOUT = 'tcad-data-root-layout-r1'


def normalize_data_root(value):
    if (not isinstance(value,str) or re.fullmatch(r'(?:/[A-Za-z0-9_.-]+)+',value) is None
            or any(part in ('.','..') for part in value.split('/'))
            or PurePosixPath(value).as_posix()!=value):
        raise ValueError('Data root must be a canonical absolute POSIX path with safe components')
    return value


DATA_ROOT_CREATE_CODE = r'''
import json,os,re,stat,sys,time
from pathlib import PurePosixPath
data_root,run_id,control_root=sys.argv[1:]
def canonical(value):
    if (re.fullmatch(r'(?:/[A-Za-z0-9_.-]+)+',value) is None
            or any(part in ('.','..') for part in value.split('/'))
            or PurePosixPath(value).as_posix()!=value):
        raise ValueError('Unsafe canonical data/control root')
    return value
canonical(data_root);canonical(control_root)
if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,150}',run_id) is None:
    raise ValueError('Invalid immutable run ID')
remote_directory=data_root+'/runs/'+run_id
legacy_directory=control_root+'/runs/'+run_id
if legacy_directory!=remote_directory and os.path.lexists(legacy_directory):
    raise ValueError('Original control-root run ID already exists; never relocate or resubmit')
uid=os.geteuid();os.umask(0o077);opened=[];created=[];facts=[]
flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
def verify(fd,path,private):
    value=os.fstat(fd);mode=stat.S_IMODE(value.st_mode)
    if not stat.S_ISDIR(value.st_mode):raise ValueError('Not a directory: '+path)
    if private:
        if value.st_uid!=uid or mode&0o022:
            raise ValueError('Data directory must belong to original SSH uid with no group/world writes: '+path)
    elif value.st_uid not in (0,uid) or (mode&0o022 and not (value.st_uid==0 and mode&stat.S_ISVTX)):
        raise ValueError('Unsafe data-root parent ownership or permissions: '+path)
    if os.readlink('/proc/self/fd/'+str(fd))!=path:
        raise ValueError('Data directory real path differs; symlinks/renames are not accepted: '+path)
    return dict(path=path,uid=value.st_uid,mode=mode,device=value.st_dev,inode=value.st_ino,private=private)
def child(parent,name,path,private,create=False,exclusive=False):
    if create:
        try:
            os.mkdir(name,0o700,dir_fd=parent);created.append(path)
        except FileExistsError:
            if exclusive:raise ValueError('Original run directory already exists; never overwrite')
    fd=os.open(name,flags,dir_fd=parent);opened.append(fd)
    facts.append(verify(fd,path,private))
    return fd
try:
    fd=os.open('/',flags);opened.append(fd);facts.append(verify(fd,'/',False))
    parts=PurePosixPath(data_root).parts[1:];path=''
    for name in parts[:-1]:
        path+='/'+name
        fd=child(fd,name,path,False)
    path+='/'+parts[-1]
    fd=child(fd,parts[-1],path,True,create=True)
    runs=child(fd,'runs',data_root+'/runs',True,create=True)
    child(runs,run_id,remote_directory,True,create=True,exclusive=True)
    checked=[verify(fd,item['path'],item['private']) for fd,item in zip(opened,facts)]
    print(json.dumps(dict(schema='tcad-data-root-directory-observation-r1',data_root=data_root,
        remote_directory=remote_directory,ssh_uid=uid,directories=checked,created_paths=created,
        observed_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))))
finally:
    for fd in reversed(opened):os.close(fd)
'''


def create_data_root_run(cfg, ssh, data_root, run_id):
    root=normalize_data_root(data_root)
    result=remote_python(ssh,DATA_ROOT_CREATE_CODE,[root,validate_run_id(run_id),cfg['remote_root'].rstrip('/')])
    if (result.get('schema')!='tcad-data-root-directory-observation-r1' or result.get('data_root')!=root
            or result.get('remote_directory')!=root+'/runs/'+run_id
            or type(result.get('ssh_uid')) is not int or result['ssh_uid']<0):
        raise ValueError('Original data-root creation observation differs')
    return result


def read_manifest(cfg, run_id, data_root=None):
    folder = run_folder(run_id)
    evidence = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if evidence.get('connection_identity') != connection_identity(cfg):
        raise ValueError('Run belongs to a different connection backend or runtime identity')
    parallel_record_policy(cfg, evidence)
    if 'remote_layout' not in evidence:
        if 'data_root' in evidence:
            raise ValueError('Data root requires an explicit supported remote layout')
        root = cfg['remote_root'].rstrip('/')
    else:
        if evidence.get('remote_layout') != DATA_ROOT_LAYOUT:
            raise ValueError('Unsupported explicit remote data layout')
        control_root = cfg['remote_root']
        if (evidence.get('control_root') != control_root
                or evidence.get('shared_lock_path') != control_root.rstrip('/') + '/.solver.lock'):
            raise ValueError('Run/original control root or shared lock identity differs')
        root = normalize_data_root(evidence.get('data_root'))
    expected = root + '/runs/' + run_id
    if evidence.get('run_id') != run_id or evidence.get('remote_directory') != expected:
        raise ValueError('Run/original remote directory identity differs')
    if data_root is not None and normalize_data_root(data_root) != root:
        raise ValueError('Existing run ID is bound to a different data root; never resubmit')
    return folder, evidence


def termination_module():
    return load_module(Path(__file__).with_name('runner_termination.py'), '_tcad_runner_termination')


def cancel_run(cfg, ssh, run_id, reason, grace_seconds=15, requested_by='operator'):
    folder, record = read_manifest(cfg, run_id)
    if 'sealed_snapshot' in record:
        raise ValueError('Original run is already sealed')
    return termination_module().cancel(sys.modules[__name__] if __name__ in sys.modules else _termination_adapter(),
        cfg, ssh, folder, record, reason, grace_seconds, requested_by)


def _termination_adapter():
    # importlib-based adapters do not necessarily register the loaded module.
    import types
    return types.SimpleNamespace(parallel_query=parallel_query, remote_python=remote_python)


def process_identity_lines(run_id):
    return ["/usr/bin/python3 - \"$$\" " + shlex.quote(run_id) + " <<'TCAD_IDENTITY'",
            'import hashlib,json,os,sys',
            'from pathlib import Path',
            'pid=int(sys.argv[1]); base=Path("/proc")/str(pid)',
            'ticks=int((base/"stat").read_text().rsplit(")",1)[1].split()[19])',
            'value=dict(schema="tcad-process-identity-r1",run_id=sys.argv[2],pid=pid,start_ticks=ticks,boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),cwd=os.getcwd(),script_sha256=hashlib.sha256(Path("run.sh").read_bytes()).hexdigest(),process_group=os.getpgrp(),session_id=os.getsid(0))',
            'Path("process-identity.json").write_text(json.dumps(value,sort_keys=True))',
            'TCAD_IDENTITY']


STATUS_CODE = termination_module().TERMINATION_CHECK_CODE + r'''
import hashlib,json,os,sys
from pathlib import Path
folder=Path(sys.argv[1]); expected_script=sys.argv[2]
value=dict(directory=str(folder),exists=folder.is_dir(),status='NOT_FOUND',alive=False,remote_exit_code=None)
if folder.is_dir():
    value['status']='START_UNCONFIRMED'
    identity_file=folder/'process-identity.json'
    if identity_file.is_file():
        identity=json.loads(identity_file.read_text());value['identity']=identity
        if identity['cwd']!=str(folder) or identity['run_id']!=folder.name or identity['script_sha256']!=expected_script:
            raise ValueError('Original run identity mismatch')
        if hashlib.sha256((folder/'run.sh').read_bytes()).hexdigest()!=expected_script:
            raise ValueError('Original run script changed')
        proc=Path('/proc')/str(identity['pid'])
        try:
            stat=(proc/'stat').read_text().rsplit(')',1)[1].split()
            value['alive']=(int(stat[19])==identity['start_ticks'] and stat[0]!='Z'
                and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==identity['boot_id']
                and os.readlink(str(proc/'cwd'))==str(folder)
                and b'run.sh' in (proc/'cmdline').read_bytes())
        except (OSError,ValueError):pass
    exit_file=folder/'exit-code.txt'
    if exit_file.is_file():
        raw=exit_file.read_text().strip()
        if not raw.isdigit() or not 0<=int(raw)<=255:raise ValueError('Invalid original exit code')
        value['remote_exit_code']=int(raw)
    if value['alive']:value['status']='RUNNING'
    elif value['remote_exit_code'] is not None:value['status']='FINISHED'
    elif identity_file.is_file():value['status']='LOST_WITHOUT_EXIT'
    if identity_file.is_file() and not value['alive']:
        termination=checked_termination(folder,identity)
        if termination:
            value['termination_record']=termination
            value['derived_exit_code']=termination.get('derived_exit_code')
            value['status']='FINISHED'
    log=folder/'execution.log'
    if log.is_file():
        value['log_bytes']=log.stat().st_size
        with log.open('rb') as stream:
            stream.seek(max(0,value['log_bytes']-2400))
            value['log_tail']=stream.read().decode('utf-8','replace')
print(json.dumps(value))
'''


def remote_python(ssh, code, args, timeout=45):
    script = '/usr/bin/python3 - ' + shlex.join([str(a) for a in args]) + " <<'TCAD_QUERY'\n" + code + '\nTCAD_QUERY\n'
    result = remote(ssh, script, capture_output=True, text=True, timeout=timeout)
    return json.loads(result.stdout)


PARALLEL_SCHEMA = 'tcad-shared-gate-slots-r1'
PARALLEL_EXTENDED_SCHEMA = 'tcad-shared-gate-slots-r2'
PARALLEL_NINE_SCHEMA = 'tcad-shared-gate-slots-r3'
PARALLEL_MAX_CAPACITY = 64
MULTICORE_PROFILE_SCHEMAS = {
    2: QUADCORE_SCHEMA,
    4: MULTICORE_SCHEMA,
    5: FIVEX2_SCHEMA,
    8: MIXED_SCHEMA,
    10: TENX1_SCHEMA,
    1: ONETEN_SCHEMA,
}


def _profile_multicore_schema(cfg):
    if 'cpu_sets' not in cfg:
        return None
    capacity = cfg.get('parallel_capacity', len(cfg['cpu_sets']))
    legacy = MULTICORE_PROFILE_SCHEMAS.get(capacity)
    if legacy is not None:
        _, expected_threads, expected_sets = _MULTICORE_HELPERS['mc_layout'](legacy)
        if cfg['cpu_sets'] == expected_sets:
            return legacy
    return DYNAMIC_SLOTS_SCHEMA


def parallel_capacity(cfg):
    capacity = cfg.get('parallel_capacity', 3)
    if 'cpu_sets' in cfg:
        if type(capacity) is not int or not 1 <= capacity <= PARALLEL_MAX_CAPACITY:
            raise ValueError('Parallel capacity must be integer between 1 and {}'.format(PARALLEL_MAX_CAPACITY))
        sets = cfg.get('cpu_sets')
        widths = _MULTICORE_HELPERS['mc_validate_cpu_sets'](sets, cfg.get('requested_threads'))
        if len(sets) != capacity:
            raise ValueError('parallel_capacity ({}) must equal len(cpu_sets) ({})'.format(capacity, len(sets)))
        return capacity
    if 'requested_threads' in cfg:
        raise ValueError('Legacy single-core profiles cannot reinterpret resource fields')
    if type(capacity) is not int or capacity not in (3, 7, 9):
        raise ValueError('Legacy single-core capacity must be 3, 7 or 9; declare cpu_sets for custom layouts')
    return capacity


def parallel_policy(cfg, slot, work_id, directory, kind='run'):
    capacity = parallel_capacity(cfg)
    if connection_identity(cfg) is None or type(slot) is not int or not 0 <= slot < capacity:
        raise ValueError('Parallel slots require ssh-runtime and an integer slot below profile capacity')
    root = normalize_data_root(cfg['remote_root'])
    validate_run_id(work_id)
    expected = (root + '/runs/' + work_id if kind == 'run' else
                root + '/dram-see-v4/transport-probe/operations/' + work_id)
    if kind not in ('run', 'operation') or directory != expected:
        raise ValueError('Parallel work must retain the canonical control-root layout')
    if 'cpu_sets' in cfg:
        if kind != 'run':
            raise ValueError('Multicore shared pool does not admit Geant4 operations; use the original single-core profile in an idle pool')
        schema = _profile_multicore_schema(cfg)
        cpu_set = list(cfg['cpu_sets'][slot])
        policy = dict(schema=schema, slot=slot, cpu_set=cpu_set,
                      requested_threads=len(cpu_set), capacity=capacity, pool_root=root,
                      connection_identity=connection_identity(cfg), work_id=work_id,
                      remote_directory=directory, kind=kind)
        if schema == DYNAMIC_SLOTS_SCHEMA:
            policy['cpu_sets'] = [list(group) for group in cfg['cpu_sets']]
        return policy
    policy = dict(schema=PARALLEL_SCHEMA, slot=slot, cpu=slot, pool_root=root,
                  connection_identity=connection_identity(cfg), work_id=work_id,
                  remote_directory=directory, kind=kind)
    if capacity != 3:
        policy.update(schema=PARALLEL_EXTENDED_SCHEMA if capacity == 7 else PARALLEL_NINE_SCHEMA,
                      capacity=capacity)
    return policy


def parallel_record_policy(cfg, record):
    policy = record.get('parallel_policy')
    if policy is None:
        return None
    kind = 'operation' if 'label' in record else 'run'
    work_id = record.get('label') if kind == 'operation' else record.get('run_id')
    expected = parallel_policy(cfg, policy.get('slot'), work_id, record.get('remote_directory'), kind)
    if policy != expected:
        raise ValueError('Original parallel slot/CPU/connection/pool identity differs')
    return policy


PROCESS_IDENTITY_KEYS = ('schema', 'run_id', 'pid', 'start_ticks', 'boot_id', 'cwd', 'script_sha256')


def checked_parallel_identity(record, identity, require_pinned=False):
    work_id = record.get('label', record.get('run_id'))
    if (not isinstance(identity, dict) or identity.get('schema') != 'tcad-process-identity-r1'
            or identity.get('run_id') != work_id or identity.get('cwd') != record['remote_directory']
            or identity.get('script_sha256') != record['script_sha256']
            or any(type(identity.get(key)) is not int or identity[key] <= 0 for key in ('pid', 'start_ticks'))
            or re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', identity.get('boot_id', '')) is None):
        raise ValueError('Invalid original parallel process identity')
    anchors = [record.get('process_identity'), record.get('last_observation', {}).get('identity')]
    if require_pinned and not any(anchors):
        raise ValueError('Missing pinned original parallel process identity')
    for pinned in anchors:
        if pinned is not None and any(identity.get(key) != pinned.get(key) for key in PROCESS_IDENTITY_KEYS):
            raise ValueError('Original parallel process identity changed')
    return {key: identity[key] for key in PROCESS_IDENTITY_KEYS}


# This is the shared remote protocol for BOTH existing public runners. No daemon,
# TTL reaper, alternate launcher or manual lock override is introduced.
REMOTE_DURABILITY_CODE = r'''
import os
def sync_path(path):
    with path.open('rb') as stream:os.fsync(stream.fileno())
def sync_dir(path):
    fd=os.open(str(path),os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
'''


PARALLEL_CODE = termination_module().TERMINATION_CHECK_CODE + REMOTE_DURABILITY_CODE + MULTICORE_AUDIT_CODE + '\npool_slots=range({})\nallocation_wait={}\n'.format(PARALLEL_MAX_CAPACITY, ALLOCATION_WAIT_SECONDS) + r'''
import fcntl,hashlib,json,os,re,stat,sys,time
from pathlib import Path
request=json.loads(sys.argv[1]);policy=request['policy'];action=request['action']
root=Path(policy['pool_root']);store=root/'.solver-slots';proc=Path('/proc')
def need(ok,message):
    if not ok:raise ValueError(message)
def acquire(fd,mode,label):
    bounded=request.get('staged_launch') is True or action in ('seal','release-sealed')
    deadline=time.monotonic()+allocation_wait if bounded else None
    while True:
        try:
            fcntl.flock(fd,mode|fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if deadline is None:raise
            if time.monotonic()>=deadline:
                print('TCAD_ALLOCATION_LOCK_BUSY: '+json.dumps(dict(lock=label,request=request),sort_keys=True),file=sys.stderr)
                raise SystemExit(74)
            time.sleep(0.1)
def policy_capacity(value):
    if mc_is_multicore(value):
        mc_policy(value)
        return value['capacity']
    if value.get('schema')=='tcad-shared-gate-slots-r1':
        need('capacity' not in value,'Legacy slot capacity cannot be reinterpreted')
        return 3
    expected={'tcad-shared-gate-slots-r2':7,'tcad-shared-gate-slots-r3':9}.get(value.get('schema'))
    need(expected is not None and type(value.get('capacity')) is int
        and value['capacity']==expected,'Invalid extended slot capacity')
    return expected
def safe_path(path):
    for part in [path]+list(path.parents):
        if part.exists():need(not part.is_symlink(),'Linked slot path')
def opened(path):
    safe_path(path)
    fd=os.open(str(path),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    item=os.fstat(fd)
    need(stat.S_ISREG(item.st_mode) and item.st_nlink==1,'Unsafe slot lock inode')
    return fd
def read(path):
    safe_path(path)
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        item=os.fstat(stream.fileno());need(stat.S_ISREG(item.st_mode) and item.st_nlink==1,'Unsafe lease inode')
        return json.load(stream)
def save(path,value,durable=False):
    safe_path(path);temporary=path.with_name(path.name+'.'+__import__('uuid').uuid4().hex+'.tmp')
    fd=os.open(str(temporary),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,sort_keys=True)
        if durable:stream.flush();os.fsync(stream.fileno())
    os.replace(str(temporary),str(path))
    if durable:sync_dir(path.parent)
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()
def identity_alive(identity):
    try:
        path=proc/str(identity['pid']);fields=(path/'stat').read_text().rsplit(')',1)[1].split()
        return (fields[0]!='Z' and int(fields[19])==identity['start_ticks']
            and (proc/'sys/kernel/random/boot_id').read_text().strip()==identity['boot_id']
            and os.readlink(str(path/'cwd'))==identity['cwd'])
    except (OSError,ValueError,KeyError):return False

def original_identity(lease):
    identity=read(Path(policy['remote_directory'])/'process-identity.json')
    need(identity.get('schema')=='tcad-process-identity-r1' and identity.get('run_id')==policy['work_id']
        and identity.get('cwd')==policy['remote_directory'] and identity.get('script_sha256')==lease['script_sha256']
        and all(type(identity.get(k)) is int and identity[k]>0 for k in ('pid','start_ticks'))
        and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',identity.get('boot_id','')) is not None,
        'Invalid original slot process identity')
    if lease['state']=='ACTIVE' or lease.get('identity') is not None:
        need(identity==lease.get('identity'),'Current process identity differs from original ACTIVE lease')
    if request.get('process_identity') is not None:
        pinned={key:identity.get(key) for key in ('schema','run_id','pid','start_ticks','boot_id','cwd','script_sha256')}
        need(pinned==request['process_identity'],'Current process identity differs from pinned original')
    return identity
def held(fd,path,mode):
    safe_path(path);a=os.fstat(fd);b=os.stat(str(path))
    need(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino),'Wrong inherited lock FD')
    fcntl.flock(fd,mode|fcntl.LOCK_NB)
def discovered_slot_indices():
    indices=set()
    for path in store.glob('slot-*.json'):
        m=re.fullmatch(r'slot-([0-9]+)\.json',path.name)
        need(m is not None,'Unknown slot lease outside supported pool')
        idx=int(m.group(1))
        need(0<=idx<64,'Unknown slot lease outside supported pool')
        indices.add(idx)
    return sorted(indices)
def checked_lease(index):
    path=store/('slot-%s.json'%index)
    if not path.exists():return None
    value=read(path);other=value['policy'];kind=other.get('kind');work=other.get('work_id','')
    expected=str(root)+('/runs/' if kind=='run' else '/dram-see-v4/transport-probe/operations/')+work
    state=value.get('state')
    need(state in ('RESERVED','ACTIVE','COLLECTED')
        and re.fullmatch(r'[a-f0-9]{64}',value.get('script_sha256','')) is not None,'Malformed lease state/SHA')
    need(other.get('pool_root')==str(root)
        and type(other.get('slot')) is int and other['slot']==index
        and kind in ('run','operation') and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',work) is not None
        and other.get('remote_directory')==expected,'Malformed slot reservation identity')
    if state!='COLLECTED':
        capacity=policy_capacity(other)
        need((mc_is_multicore(other) or (type(other.get('cpu')) is int and other['cpu']==index))
            and 0<=index<capacity,'Malformed slot reservation identity')
    else:
        try:
            capacity=policy_capacity(other)
            need((mc_is_multicore(other) or (type(other.get('cpu')) is int and other['cpu']==index))
                and 0<=index<capacity,'Malformed slot reservation identity')
        except ValueError:
            # Closed COLLECTED leases from another schema revision hold no lock or CPU;
            # never let a retired slot record block a new layout in an idle pool.
            if action in ('prove-unlaunched','prove-unlaunched-intent'):
                raise
    return value
def pool_leases():
    # Both public runners share this entire namespace, including slots outside
    # the requesting profile's capacity. Never overlook an extended peer.
    return [value for value in (checked_lease(i) for i in discovered_slot_indices()) if value is not None]
def available_cpu():
    cpus=mc_policy(policy) if mc_is_multicore(policy) else [policy['cpu']]
    need(set(cpus)<=os.sched_getaffinity(0),'Requested CPU is not available')
def pool_configuration():
    if mc_is_multicore(policy):
        mc_policy(policy)
        return mc_pool_configuration(policy['schema'], policy.get('cpu_sets'))
    return dict(schema='tcad-slot-pool-r1',capacity=policy_capacity(policy))
def valid_multicore_pool(value):
    if not isinstance(value,dict):return False
    if value.get('schema')=='tcad-slot-pool-v2':
        try:
            sets=value.get('cpu_sets')
            widths=mc_validate_cpu_sets(sets,value.get('requested_threads'))
            expected=mc_pool_configuration('tcad-shared-gate-slots-v2',sets)
            return type(value.get('capacity')) is int and value['capacity']==len(widths) and value==expected
        except ValueError:
            return False
    for schema in ('tcad-shared-gate-slots-r4','tcad-shared-gate-slots-r5',
                   'tcad-shared-gate-slots-r6','tcad-shared-gate-slots-r7',
                   'tcad-shared-gate-slots-r8','tcad-shared-gate-slots-r9'):
        expected=mc_pool_configuration(schema)
        if (type(value.get('capacity')) is not int
                or value.get('capacity') != expected['capacity']
                or value.get('cpu_sets') != expected['cpu_sets']):
            continue
        requested=value.get('requested_threads');expected_requested=expected['requested_threads']
        if type(expected_requested) is int:
            requested_ok=type(requested) is int and requested==expected_requested
        else:
            requested_ok=(type(requested) is list and len(requested)==len(expected_requested)
                          and all(type(item) is int for item in requested)
                          and requested==expected_requested)
        if requested_ok and value==expected:
            return True
    return False
def check_pool_capacity(leases):
    capacity=policy_capacity(policy)
    active=[value for value in leases if value['state']!='COLLECTED']
    need(all(policy_capacity(value['policy'])==capacity for value in active),
         'Execution pool capacity differs from outstanding reservation')
    path=store/'capacity.json'
    if path.exists():
        value=read(path)
        valid_old=(value.get('schema')=='tcad-slot-pool-r1'
            and type(value.get('capacity')) is int and value['capacity'] in (3,7,9))
        valid_new=valid_multicore_pool(value)
        if value==pool_configuration():return
        if active or action!='reserve':
            need(valid_old or valid_new,'Malformed pool capacity')
    elif capacity==3:
        return  # Pre-extension r1 pools did not have a capacity manifest.
    # Historical collected records can still be verified through their original
    # profile. Any new capacity is installed only by a reservation in an idle pool.
    own=next((value for value in leases if value['policy']==policy),None)
    if action in ('verify','release') and own is not None and own['state']=='COLLECTED':return
    need(action=='reserve' and not active,'Execution pool capacity differs or is missing; reconcile outstanding work first')
    locks=[]
    try:
        lock_indices=set(range(capacity))
        for lp in store.glob('slot-*.lock'):
            m=re.fullmatch(r'slot-([0-9]+)\.lock',lp.name)
            if m is not None and 0<=int(m.group(1))<64:
                lock_indices.add(int(m.group(1)))
        for index in sorted(lock_indices):
            fd=opened(store/('slot-%s.lock'%index));locks.append(fd)
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        admission([])
    finally:
        for fd in locks:os.close(fd)
def admission(leases):
    owners={}
    resources=[]
    for lease in leases:
        other=lease['policy']
        need(other['schema']==policy['schema'] and other['pool_root']==policy['pool_root']
            and other['connection_identity']==policy['connection_identity'],'Foreign execution pool reservation')
        need(policy_capacity(other)==policy_capacity(policy) and type(other['slot']) is int
            and 0<=other['slot']<policy_capacity(policy)
            and (mc_is_multicore(other)
                 or other['cpu']==other['slot']),'Invalid peer CPU/slot')
        if lease['state']=='RESERVED':continue
        need(lease['state']=='ACTIVE','Unknown reserved slot state')
        identity=lease['identity'];directory=Path(other['remote_directory'])
        need(identity['run_id']==other['work_id'] and identity['cwd']==str(directory)
            and identity['script_sha256']==lease['script_sha256'] and digest(directory/'run.sh')==lease['script_sha256'],
            'Peer wrapper identity differs')
        if identity_alive(identity):
            if mc_is_multicore(other):
                cpus=mc_policy(other)
                wrapper=mc_snapshot(proc,identity['pid'],cpus,1,identity['cwd'],identity['start_ticks'],exact=True)
                resources.append(dict(role='wrapper',policy=other,snapshot=wrapper))
                owners[identity['pid']]=(identity,other)
            else:owners[identity['pid']]=(identity,other['cpu'])
        else:
            recovered_after_boot_change = (
                action in ('collect', 'release')
                and isinstance(identity.get('boot_id'), str)
                and identity['boot_id'] != (proc/'sys/kernel/random/boot_id').read_text().strip())
            if recovered_after_boot_change:
                # A reboot removed the original wrapper and native process.
                # The collection audit below still scans every native process
                # before creating the immutable interruption archive.
                continue
            need(((directory/'exit-code.txt').is_file() and (directory/'finished-utc.txt').is_file())
                 or checked_termination(directory,identity) is not None,
                 'Unknown outstanding parallel work; reconcile original first')
            if mc_is_multicore(other):
                proof=read(directory/'parallel-slot-evidence.json')
                need(proof.get('policy')==other and proof.get('identity')==identity,
                     'Original terminal multicore wrapper proof differs')
                snapshot=mc_validate(proof['wrapper_resources'],mc_policy(other),1,
                    identity['pid'],identity['start_ticks'],identity['cwd'],exact=True)
                resources.append(dict(role='terminal_wrapper',policy=other,snapshot=snapshot))
    for path in proc.glob('[0-9]*'):
        try:
            comm=(path/'comm').read_text().strip();fields=(path/'stat').read_text().rsplit(')',1)[1].split()
        except OSError:continue
        native=comm.startswith(('sdevice','snmesh','sde','transport','cc1','cmi')) or comm in ('tdx','svisual','svisual_exec')
        if not native or fields[0]=='Z':continue
        pid=int(path.name);ancestor=pid;seen=set();owner=None
        while ancestor>0 and ancestor not in seen:
            seen.add(ancestor)
            if ancestor in owners:owner=owners[ancestor];break
            try:ancestor=int((proc/str(ancestor)/'stat').read_text().rsplit(')',1)[1].split()[1])
            except (OSError,ValueError):break
        need(owner is not None,'Unregistered active native process '+str(pid))
        identity,cpu=owner
        need(os.readlink(str(path/'cwd'))==identity['cwd'],'Native cwd does not belong to its slot')
        if isinstance(cpu,dict):
            snapshot=mc_snapshot(proc,pid,mc_policy(cpu),None if comm.startswith('sdevice') else 1,
                                 identity['cwd'],int(fields[19]))
            resources.append(dict(role='native',policy=cpu,snapshot=snapshot))
            continue
        cpu_lines=[x.split(':',1)[1].strip() for x in (path/'status').read_text().splitlines() if x.startswith('Cpus_allowed_list:')]
        need(cpu_lines==[str(cpu)],'Native affinity differs from registered slot')
        tasks=list((path/'task').glob('[0-9]*'))
        need(bool(tasks),'Missing native task affinity evidence')
        for thread in tasks:
            values=[x.split(':',1)[1].strip() for x in (thread/'status').read_text().splitlines() if x.startswith('Cpus_allowed_list:')]
            need(values==[str(cpu)],'Native auxiliary task escaped its single CPU slot')
    return resources
def prove_unlaunched():
    # This narrow, read-only protocol cannot reserve, cancel, collect or switch
    # capacity. It is called only inside the original controller ownership lock.
    intent_proof=action=='prove-unlaunched-intent'
    if intent_proof:
        need(policy.get('schema')=='tcad-shared-gate-slots-r4'
             and policy.get('kind')=='run' and policy.get('capacity')==4,
             'Intent proof requires the original four-slot TCAD profile')
        mc_policy(policy)
        need('script_sha256' in request and request['script_sha256'] is None,
             'Pre-manifest intent must not invent a wrapper SHA')
    else:
        need(policy.get('schema')=='tcad-shared-gate-slots-r3'
             and policy.get('kind')=='operation' and policy.get('capacity')==9,
             'Unlaunched proof requires the original nine-slot operation profile')
    work=policy['work_id'];directory=Path(policy['remote_directory'])
    suffix='/runs/' if intent_proof else '/dram-see-v4/transport-probe/operations/'
    need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*' if intent_proof else r'[a-z0-9][a-z0-9-]*',work) is not None
         and str(directory)==str(root)+suffix+work
         and policy.get('connection_identity',{}).get('remote_root')==str(root),
         'Unlaunched proof has a different canonical subject')
    for key in (('subject_sha256',) if intent_proof else ('script_sha256','subject_sha256')):
        need(isinstance(request.get(key),str)
             and re.fullmatch(r'[a-f0-9]{64}',request[key]) is not None,
             'Missing unlaunched proof hash binding')
    need(request.get('process_identity') is None,'Launched identity cannot be reconciled as unlaunched')
    def unlinked(path):
        for part in reversed([path]+list(path.parents)):
            try:item=part.lstat()
            except FileNotFoundError:continue
            need(not stat.S_ISLNK(item.st_mode),'Linked unlaunched proof path')
            if part!=path:
                need(stat.S_ISDIR(item.st_mode),'Nondirectory unlaunched proof parent')
    def existing_lock(path):
        unlinked(path)
        fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW)
        try:
            item=os.fstat(fd)
            need(stat.S_ISREG(item.st_mode) and item.st_nlink==1,
                 'Unsafe existing unlaunched lock')
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            current=os.stat(str(path))
            need((item.st_dev,item.st_ino)==(current.st_dev,current.st_ino),
                 'Original unlaunched lock inode changed')
            return fd
        except BaseException:
            os.close(fd)
            raise
    def absent():
        unlinked(directory)
        try:directory.lstat()
        except FileNotFoundError:return
        need(False,'Original operation directory/claim exists')
    def snapshot():
        leases=pool_leases()
        need(all(v['policy']['work_id']!=work
                 and v['policy']['remote_directory']!=str(directory) for v in leases),
             'Original ID already has a lease')
        need(all(v['state']=='COLLECTED' for v in leases),
             'Outstanding lease prevents an idle unlaunched proof')
        result={}
        def frozen(path,value):
            raw=path.read_bytes()
            need(json.loads(raw)==value,'Pool evidence changed while reading')
            return dict(sha256=hashlib.sha256(raw).hexdigest(),raw_hex=raw.hex(),record=value)
        for index in proof_slots:
            path=store/('slot-%s.json'%index);unlinked(path)
            value=checked_lease(index)
            if value is not None:
                need(value['policy'].get('connection_identity')==policy['connection_identity'],
                     'Foreign historical pool connection identity')
            result[path.name]=None if value is None else frozen(path,value)
        path=store/'capacity.json';unlinked(path)
        value=read(path)  # Missing/unknown descriptors are not proof of an idle pool.
        old=(value.get('schema')=='tcad-slot-pool-r1'
             and type(value.get('capacity')) is int and value['capacity'] in (3,7,9))
        new=valid_multicore_pool(value)
        need(old or new,'Unknown pool descriptor during unlaunched proof')
        return dict(leases=result,capacity=frozen(path,value))
    def boot():
        value=(proc/'sys/kernel/random/boot_id').read_text().strip()
        need(re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',value) is not None,
             'Unknown boot identity during unlaunched proof')
        return value
    def process_scan():
        # Do not interpret unreadable /proc evidence as process absence. The
        # original connection must expose comm/stat/cmdline/cwd for all UIDs.
        own=os.geteuid();ancestors=set();pid=os.getpid()
        while pid:
            need(pid not in ancestors and len(ancestors)<128,'Unknown proof ancestry')
            ancestors.add(pid)
            fields=(proc/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
            pid=int(fields[1])
        count=0
        with os.scandir(str(proc)) as entries:
            pids=[entry.name for entry in entries if entry.name.isdigit()]
        need(bool(pids),'Unknown/empty process inventory')
        for name in pids:
            path=proc/name
            try:
                before=(path/'stat').read_text().rsplit(')',1)[1].split()
                comm=(path/'comm').read_text().strip()
                if before[0]=='Z':continue
                native=comm.startswith(('sdevice','snmesh','sde','transport','cc1','cmi')) or comm in ('tdx','svisual','svisual_exec')
                need(not native,'Unregistered active native process '+name)
                command=(path/'cmdline').read_bytes()
                # Kernel threads have no userspace cwd/cmdline. PF_KTHREAD is
                # kernel stat flags bit 0x00200000, never inferred from emptiness.
                kernel=bool(int(before[6]) & 0x00200000)
                if not kernel:
                    cwd=os.readlink(str(path/'cwd'))
                    need(cwd!=str(directory) and not cwd.startswith(str(directory)+'/'),
                         'Original target cwd is still in use')
                need(int(name) in ancestors or work.encode() not in command,
                     'Original target process is still present')
                after=(path/'stat').read_text().rsplit(')',1)[1].split()
                need(before[19]==after[19] and after[0]!='Z','Process identity changed during unlaunched proof')
                count+=1
            except (FileNotFoundError,ProcessLookupError):
                # A proven vanished PID is harmless; unreadable/live partial
                # evidence and PID reuse remain a closed failure.
                need(not path.exists(),'Unknown partial process evidence')
        need(count>0,'No complete process evidence')
        return dict(scope='all-uid-native-cmdline-cwd',
                    owner_uid=own,checked_processes=count,probe_ancestor_pids=sorted(ancestors))
    fds=[]
    try:
        unlinked(root);unlinked(store)
        need(store.is_dir(),'Missing original slot store')
        paths=[root/'.solver.lock',store/'allocation.lock']
        for path in paths:
            fds.append(existing_lock(path))
        lock_indices=[]
        for lp in store.glob('slot-*.lock'):
            unlinked(lp)
            m=re.fullmatch(r'slot-([0-9]+)\.lock',lp.name)
            need(m is not None,'Unknown slot lock outside supported pool')
            idx=int(m.group(1))
            need(0<=idx<64,'Slot lock index outside supported pool')
            lock_indices.append(idx)
        max_lock=max([8]+lock_indices)
        proof_slots=range(max_lock+1)
        need(all(idx<=max_lock for idx in discovered_slot_indices()),
             'Extended lease has no original slot lock')
        slot_paths=[store/('slot-%s.lock'%i) for i in proof_slots]
        for path in slot_paths:
            fds.append(existing_lock(path))
        first_boot=boot();absent();before=snapshot()
        processes=process_scan()
        absent();need(snapshot()==before,'Pool changed during unlaunched proof')
        need(boot()==first_boot,'Boot changed during unlaunched proof')
        for fd,path in zip(fds,paths+slot_paths):
            unlinked(path);opened_stat=os.fstat(fd);current=path.stat()
            need((opened_stat.st_dev,opened_stat.st_ino)==(current.st_dev,current.st_ino),
                 'Original lock inode changed during unlaunched proof')
        snapshot_sha=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        return dict(schema='tcad-prove-unlaunched-intent-r1' if intent_proof else 'tcad-prove-unlaunched-r1',
                    action=action,
                    status='NOT_LAUNCHED',policy=policy,script_sha256=request['script_sha256'],
                    subject_sha256=request['subject_sha256'],boot_id=first_boot,
                    observed_utc=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),
                    reservation_acquired=False,solver_launched=False,success=False,
                    directory_exists=False,launch_claim_exists=False,
                    gate_mode='EXCLUSIVE',allocator_mode='EXCLUSIVE',locked_slots=list(proof_slots),
                    pool_snapshot=before,pool_snapshot_sha256=snapshot_sha,process_scan=processes)
    finally:
        for fd in reversed(fds):os.close(fd)
safe_path(root);need(root.is_dir(),'Missing canonical control root')
capacity=policy_capacity(policy)
need(type(policy['slot']) is int and 0<=policy['slot']<capacity
     and (mc_is_multicore(policy)
          or (type(policy['cpu']) is int and policy['cpu']==policy['slot'])),'Invalid requested slot')
if action in ('prove-unlaunched','prove-unlaunched-intent'):
    print(json.dumps(prove_unlaunched(),sort_keys=True))
    raise SystemExit(0)
lease_path=store/('slot-%s.json'%policy['slot']);slot_path=store/('slot-%s.lock'%policy['slot'])
def release_sealed(lease):
    directory=Path(policy['remote_directory']);collection=directory/'.collection'
    receipt=read(collection/'receipt.json')
    snapshot=request['sealed_snapshot']
    archive=(collection/'results.tar').lstat()
    need(receipt.get('schema')=='tcad-original-snapshot-r1'
         and receipt['sha256']==snapshot['sha256'] and receipt['bytes']==snapshot['bytes']
         and stat.S_ISREG(archive.st_mode) and archive.st_nlink==1 and archive.st_size==snapshot['bytes'],
         'Collection receipt differs from sealed snapshot')
    identity=request['process_identity']
    proof=dict(schema='tcad-sealed-slot-release-r1',policy=policy,
               script_sha256=request['script_sha256'],identity=identity,
               archive_sha256=snapshot['sha256'],archive_bytes=snapshot['bytes'])
    path=collection/'slot-release.json'
    proved=path.is_file()
    if proved:need(read(path)==proof,'Original sealed slot release proof differs')
    if lease is None or lease['policy']!=policy:
        need(proved and lease is not None and lease['policy']['remote_directory']!=str(directory),
             'Original slot lease identity differs without sealed release proof')
    else:
        need(lease['script_sha256']==request['script_sha256'],'Slot script SHA differs')
        original_identity(lease)
        if lease['state']=='COLLECTED':
            need(proved and lease.get('archive_sha256')==snapshot['sha256'],
                 'Original closed lease differs from sealed release proof')
        else:
            slot=opened(slot_path);fcntl.flock(slot,fcntl.LOCK_EX|fcntl.LOCK_NB)
            need(not identity_alive(identity),'Original wrapper is still alive during sealed release')
            exit_path=directory/'exit-code.txt'
            if exit_path.is_file():
                raw=exit_path.read_text().strip()
                need(not receipt.get('interrupted_context_sha256'),'Interrupted receipt conflicts with original exit')
                need(raw.isdigit() and 0<=int(raw)<=255,'Invalid original exit code')
            elif receipt.get('interrupted_context_sha256'):
                context_sha=receipt['interrupted_context_sha256'];proof_sha=receipt['interruption_proof_sha256']
                need((context_sha,proof_sha)==tuple(request.get('interruption',())),
                     'Interrupted seal proof differs from receipt')
                need(re.fullmatch(r'[a-f0-9]{64}',proof_sha) is not None,'Invalid interrupted seal proof hash')
                proof_path=collection/('interrupted-proof-'+proof_sha+'.json');proof=read(proof_path)
                need(digest(proof_path)==proof_sha and proof.get('context_sha256')==context_sha
                     and proof.get('context',{}).get('process_identity')==identity,
                     'Original interrupted seal proof differs')
            else:
                need(checked_termination(directory,original_identity(lease)) is not None,'No original exit')
            if lease['state']=='RESERVED':
                need(exit_path.is_file() and int(raw)!=0 and not (directory/'parallel-slot-evidence.json').exists(),
                     'Unactivated reservation cannot be sealed as successful execution')
            if not proved:save(path,proof,durable=True)
            else:sync_path(path);sync_dir(collection)
            lease.update(state='COLLECTED',archive_sha256=snapshot['sha256'])
            save(lease_path,lease,durable=True)
        sync_dir(store)
    return dict(proof,state='COLLECTED')

gate_held=False;allocator_held=False
try:
    store.mkdir(mode=0o700,exist_ok=True);safe_path(store)
    gate=opened(root/'.solver.lock');acquire(gate,fcntl.LOCK_SH,'solver-gate');gate_held=True
    allocator=opened(store/'allocation.lock');acquire(allocator,fcntl.LOCK_EX,'allocator');allocator_held=True
    lease=checked_lease(policy['slot'])
    if action not in ('seal','release-sealed'):
        all_leases=pool_leases();check_pool_capacity(all_leases)
    if action=='reserve':
        available_cpu()
        admission([peer for peer in all_leases if peer['state']!='COLLECTED'])
        slot=opened(slot_path);fcntl.flock(slot,fcntl.LOCK_EX|fcntl.LOCK_NB)
        need(lease is None or lease['state']=='COLLECTED','Slot reserved until verified collection')
except (OSError, ValueError) as exc:
    if action!='reserve':
        raise
    print('TCAD_RESERVE_REJECTED: '+str(exc),file=sys.stderr)
    try:
        if gate_held and allocator_held and 'all_leases' in locals():
            directory=Path(policy['remote_directory']);safe_path(directory)
            absent=not any(peer['policy'].get('work_id')==policy['work_id'] or peer['policy'].get('remote_directory')==str(directory) for peer in all_leases)
            if absent and not directory.exists():
                proof=dict(schema='tcad-original-preflight-rejection-r1',request=request,
                    reservation_acquired=False,solver_launched=False,target_lease_absent=True,
                    target_directory_absent=True,gate_held=True,allocator_held=True,
                    boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
                print('TCAD_PREFLIGHT_NOT_LAUNCHED: '+json.dumps(proof,sort_keys=True),file=sys.stderr)
    except (OSError,ValueError,KeyError) as proof_error:
        print('Preflight non-launch proof unavailable: '+str(proof_error),file=sys.stderr)
    raise SystemExit(75)
resource_audit=None
if action=='release-sealed':
    print(json.dumps(release_sealed(lease),sort_keys=True))
    raise SystemExit(0)
if mc_is_multicore(policy) and action in ('verify','collect','release'):
    resource_audit=dict(schema='tcad-live-resource-audit-r1',policy=policy,
        snapshots=admission([peer for peer in all_leases if peer['state']!='COLLECTED']))
if action=='reserve':
    need(not any(peer['policy']['remote_directory']==policy['remote_directory'] for peer in all_leases),
         'Original work already has a slot record')
    directory=Path(policy['remote_directory'])
    safe_path(directory);need(not directory.exists(),'Original work directory already exists')
    save(store/'capacity.json',pool_configuration())
    lease=dict(policy=policy,state='RESERVED',script_sha256=request['script_sha256'])
    save(lease_path,lease,durable=request.get('staged_launch') is True)
else:
    need(lease is not None and lease['policy']==policy,'Original slot lease identity differs')
    if request.get('script_sha256') is not None:
        need(lease['script_sha256']==request['script_sha256'],'Slot script SHA differs')
    identity=None
    if action!='activate' and (lease['state']=='ACTIVE' or lease.get('identity') is not None
            or request.get('process_identity') is not None or action in ('collect','seal','release')):
        identity=original_identity(lease)
    if action in ('activate','collect','seal'):
        held(9,root/'.solver.lock',fcntl.LOCK_SH);held(7,slot_path,fcntl.LOCK_EX)
        need(lease['state'] in ('RESERVED','ACTIVE'),'Collected slot cannot execute/collect again')
        need(digest(Path(policy['remote_directory'])/'run.sh')==lease['script_sha256'],'Original parallel wrapper changed')
        if action=='activate':
            need(lease['state']=='RESERVED','Parallel work was already activated')
            identity=original_identity(lease)
            need(identity['pid']==os.getppid() and identity_alive(identity)
                and identity['cwd']==policy['remote_directory'] and identity['run_id']==policy['work_id']
                and identity['script_sha256']==lease['script_sha256'],'Actual parallel wrapper differs')
            peers=[peer for peer in all_leases if peer['state']!='COLLECTED']
            admission(peers)
            wrapper_resources=None
            if mc_is_multicore(policy):
                wrapper_resources=mc_snapshot(proc,identity['pid'],mc_policy(policy),1,
                    identity['cwd'],identity['start_ticks'],exact=True)
            lease.update(state='ACTIVE',identity=identity);save(lease_path,lease)
            evidence=dict(policy=policy,script_sha256=lease['script_sha256'],identity=identity,
                          gate_mode='SHARED',slot_mode='EXCLUSIVE',gate_fd=9,slot_fd=7)
            if mc_is_multicore(policy):
                evidence['wrapper_resources']=wrapper_resources
            path=Path(policy['remote_directory'])/'parallel-slot-evidence.json'
            need(not path.exists(),'Never overwrite original slot proof');save(path,evidence)
            lock=Path(policy['remote_directory'])/'shared-lock-evidence.txt'
            need(not lock.exists(),'Never overwrite original gate proof')
            lock.write_text('status=ACQUIRED\nfd=9\nlock_path=%s\npid=%s\nmode=SHARED\nslot=%s\nslot_fd=7\nacquired_utc=%s\n' % (
                str(root/'.solver.lock'),identity['pid'],policy['slot'],__import__('time').strftime('%Y-%m-%dT%H:%M:%SZ',__import__('time').gmtime())))
        else:
            evidence=dict(policy=policy,script_sha256=lease['script_sha256'],lease_state=lease['state'],identity=identity,
                          gate_mode='SHARED',slot_mode='EXCLUSIVE',status='COLLECTION_LOCKS_ACQUIRED')
            if action=='seal':
                need(not identity_alive(identity),'Original wrapper is still alive during sealing')
                if lease['state']=='RESERVED':
                    directory=Path(policy['remote_directory']);raw=(directory/'exit-code.txt').read_text().strip()
                    need(raw.isdigit() and 1<=int(raw)<=255 and not (directory/'parallel-slot-evidence.json').exists(),
                         'Unactivated reservation cannot be sealed as successful execution')
            if mc_is_multicore(policy):
                need(not identity_alive(identity),'Original wrapper is still alive during collection')
                proof=Path(policy['remote_directory'])/'parallel-slot-evidence.json'
                if lease['state']=='ACTIVE':
                    original=read(proof)
                    need(original.get('policy')==policy and original.get('identity')==identity,
                         'Original multicore activation proof differs')
                    evidence['wrapper_resources']=mc_validate(original['wrapper_resources'],mc_policy(policy),
                        1,identity['pid'],identity['start_ticks'],identity['cwd'],exact=True)
            path=Path(policy['remote_directory'])/'parallel-slot-collection-evidence.json'
            if path.exists():need(read(path)==evidence,'Original slot collection proof changed')
            elif action=='seal':save(path,evidence,durable=True)
            else:save(path,evidence)
    elif action=='release':
        slot=opened(slot_path);fcntl.flock(slot,fcntl.LOCK_EX|fcntl.LOCK_NB)
        receipt=read(Path(policy['remote_directory'])/'.collection/receipt.json')
        need(receipt['sha256']==request['archive_sha256'],'Collection receipt differs from verified archive')
        exit_path = Path(policy['remote_directory'])/'exit-code.txt'
        if not exit_path.is_file():
            current_boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            need(identity['boot_id'] != current_boot or checked_termination(Path(policy['remote_directory']),identity) is not None,
                 'No original terminal exit and no proven boot change')
        if lease['state']=='RESERVED':
            raw=(Path(policy['remote_directory'])/'exit-code.txt').read_text().strip()
            need(raw.isdigit() and 1<=int(raw)<=255
                and not (Path(policy['remote_directory'])/'parallel-slot-evidence.json').exists(),
                'Unactivated reservation cannot be collected as successful execution')
        lease['state']='COLLECTED';lease['archive_sha256']=request['archive_sha256'];save(lease_path,lease)
    else:need(action=='verify','Unknown slot protocol operation')
print(json.dumps(dict(lease,resource_audit=resource_audit) if resource_audit is not None else lease,sort_keys=True))
'''


def parallel_query(cfg, ssh, record, action, *, proof_subject_sha256=None, proof_ssh=None):
    proof_action = action in ('prove-unlaunched', 'prove-unlaunched-intent')
    if not proof_action and proof_ssh is not None:
        raise ValueError('proof_ssh is only valid for prove-unlaunched')
    if proof_ssh is not None and (not hasattr(os, 'geteuid') or os.geteuid() != 0):
        raise PermissionError('Privileged unlaunched proof requires server administrator euid 0')
    policy = parallel_record_policy(cfg, record)
    if policy is None:
        return None
    request = dict(policy=policy, action=action, script_sha256=record.get('script_sha256'))
    if action == 'reserve' and record.get('staged_launch') is True:
        request['staged_launch'] = True
    if proof_action:
        if not isinstance(proof_subject_sha256, str) or re.fullmatch(r'[a-f0-9]{64}', proof_subject_sha256) is None:
            raise ValueError('Unlaunched proof requires the frozen local subject SHA')
        request['subject_sha256'] = proof_subject_sha256
    elif proof_subject_sha256 is not None:
        raise ValueError('Proof subject is only valid for prove-unlaunched')
    identity = record.get('process_identity') or record.get('last_observation', {}).get('identity')
    if identity is not None:
        request['process_identity'] = checked_parallel_identity(record, identity)
    if action == 'release':
        request['archive_sha256'] = record.get('results_sha256', record.get('archive_sha256'))
    if action == 'release-sealed':
        request['sealed_snapshot'] = sealed_snapshot(record)
        request['process_identity'] = checked_parallel_identity(record, identity, require_pinned=True)
        if record.get('interrupted_collection_snapshot'):
            interruption = record['interrupted_collection_snapshot']
            request['interruption'] = [interruption['interrupted_context_sha256'], interruption['interruption_proof_sha256']]
    query_ssh = proof_ssh if proof_action and proof_ssh is not None else ssh
    try:
        value = remote_python(query_ssh, PARALLEL_CODE, [json.dumps(request, sort_keys=True)])
    except subprocess.CalledProcessError as exc:
        if request.get('staged_launch') and exc.returncode == RESERVATION_BUSY_EXIT_CODE:
            prefix = 'TCAD_ALLOCATION_LOCK_BUSY: '
            messages = [line[len(prefix):] for line in (exc.stderr or '').splitlines() if line.startswith(prefix)]
            if len(messages) == 1:
                busy = json.loads(messages[0])
                if busy.get('request') == request and busy.get('lock') in ('solver-gate', 'allocator'):
                    raise ReservationBusy(busy['lock']) from exc
        raise
    if not isinstance(value, dict) or value.get('policy') != policy:
        raise ValueError('Remote slot returned a different original identity')
    if action == 'reserve' and (value.get('state') != 'RESERVED'
                                or value.get('script_sha256') != request['script_sha256']):
        raise ValueError('Missing original reservation receipt')
    if action == 'release-sealed' and (
        value.get('schema') != 'tcad-sealed-slot-release-r1' or value.get('state') != 'COLLECTED'
        or value.get('script_sha256') != request['script_sha256']
        or value.get('identity') != request['process_identity']
        or value.get('archive_sha256') != request['sealed_snapshot']['sha256']
        or value.get('archive_bytes') != request['sealed_snapshot']['bytes']
    ):
        raise ValueError('Missing original sealed slot release receipt')
    if value.get('identity') is not None:
        checked_parallel_identity(record, value['identity'])
    return value


def parallel_shell_lines(policy, action, record=None, *, staged_launch=False):
    root = policy['pool_root']
    request = dict(policy=policy, action=action)
    if staged_launch:
        request['staged_launch'] = True
    if record is not None:
        request.update(script_sha256=record['script_sha256'], process_identity=checked_parallel_identity(
            record, record.get('process_identity'), require_pinned=True))
    request = json.dumps(request, sort_keys=True)
    # Append-open avoids truncating an existing lock before the Python FD/inode
    # check. The reservation protocol created and checked these regular files.
    gate = 'flock -s -w %d 9 || exit 75' % ALLOCATION_WAIT_SECONDS if staged_launch else 'flock -s -n 9 || exit 75'
    return ['exec 9>>' + shlex.quote(root + '/.solver.lock'), gate,
            'exec 7>>' + shlex.quote(root + '/.solver-slots/slot-%s.lock' % policy['slot']),
            'flock -n 7 || exit 75',
            # Query mode keeps its one JSON stdout. In a composed shell the
            # protocol receipt belongs to stderr; stdout is the snapshot API.
            # Original activation/collection proof files remain unchanged.
            '/usr/bin/python3 - ' + shlex.quote(request) + " 1>&2 <<'TCAD_PARALLEL'",
            PARALLEL_CODE, 'TCAD_PARALLEL']


def parallel_release(cfg, ssh, record):
    if record.get('parallel_policy') and not record.get('parallel_slot_released'):
        parallel_query(cfg, ssh, record, 'release')
        record['parallel_slot_released'] = True


def _verified_unlaunched_operation(path, record):
    """Ignore only a separately verified old operation that never launched.

    A new TCAD multicore submission must still inspect all historical runner
    records.  Older Geant4 submissions use the shared nine-slot operation
    profile, however, and their terminal FAILED_BEFORE_LAUNCH records cannot
    be interpreted with the current TCAD pool profile.  The reconciliation
    receipt is the only allowed escape from that reinterpretation.
    """
    if (record.get('state') != 'FAILED_BEFORE_LAUNCH'
            or not (path.parent / 'launch-reconciliation.json').is_file()):
        return False
    source = ROOT / 'experiments/dram-see-v4/transport-probe/launch_reconciliation.py'
    if source.is_symlink() or not source.is_file():
        raise RuntimeError('Missing original unlaunched-receipt verifier')
    spec = importlib.util.spec_from_file_location(
        '_tcad_launch_reconciliation', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target_identity = record.get('connection_identity')
    if not isinstance(target_identity, dict):
        raise RuntimeError('Unlaunched operation is missing its connection identity')

    # The selected profile is the current TCAD profile.  Historical operation
    # profiles are kept beside it; only a non-symlink nine-slot profile with
    # the exact recorded SSH identity may validate this receipt.
    profile_dir = CONFIG.parent if CONFIG is not None else ROOT / 'local_runtime/cloud-benchmark'
    candidates = []
    for candidate in sorted(profile_dir.glob('connection-*.json')):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            historical = json.loads(candidate.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            continue
        if (isinstance(historical, dict) and historical.get('parallel_capacity') == 9
                and connection_identity(historical) == target_identity):
            candidates.append((candidate, historical))
    for candidate, historical in candidates:
        try:
            if module.verified_unlaunched_receipt(
                    historical, record, path.parent):
                return True
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    raise RuntimeError(
        'Invalid or unverifiable original unlaunched operation receipt: '
        + str(path))


def parallel_assert_local(cfg):
    paths = list((state_root() / 'runs').glob('*/manifest.json'))
    paths += list((state_root() / 'dram-see-v4/transport-probe/operations').glob('*/operation.json'))
    for path in paths:
        if path.parent.name.startswith('.'):
            continue
        record = json.loads(path.read_text(encoding='utf-8'))
        if path.parent.parent.name == 'operations' and _verified_unlaunched_operation(path, record):
            continue
        complete = record.get('state') in ('COLLECTED', 'FAILED_COLLECTED', 'COLLECTED_PENDING_AUDIT', 'INTERRUPTED_COLLECTED')
        if complete and (not record.get('parallel_policy') or record.get('parallel_slot_released')):
            continue
        if parallel_record_policy(cfg, record) is None:
            raise RuntimeError('Reconcile legacy outstanding work before parallel launch: ' + str(path))


def status_run(cfg, ssh, run_id, *, for_seal=False):
    folder, evidence = read_manifest(cfg, run_id)
    if evidence.get('schema') != 'tcad-native-run-r2':
        raise ValueError('Historical run retains its original semantics; use its original recovery path')
    if 'sealed_snapshot' in evidence:
        return dict(evidence['last_observation'], local_state=evidence['state'])
    parallel_record_policy(cfg, evidence)
    resource_audit = None
    if not for_seal and evidence.get('parallel_policy') and not evidence.get('parallel_slot_released'):
        lease = parallel_query(cfg, ssh, evidence, 'verify')
        if is_multicore(evidence['parallel_policy']):
            resource_audit = lease.get('resource_audit')
            if (not isinstance(resource_audit, dict)
                    or resource_audit.get('schema') != 'tcad-live-resource-audit-r1'
                    or resource_audit.get('policy') != evidence['parallel_policy']):
                raise ValueError('Missing live multicore resource audit')
        if lease.get('identity') is not None:
            evidence['process_identity'] = checked_parallel_identity(evidence, lease['identity'])
    if evidence.get('state') == 'INTERRUPTED_COLLECTED':
        verify_interrupted_terminal(folder, evidence)
        return dict(run_id=run_id, status='INTERRUPTED_COLLECTED', local_state='INTERRUPTED_COLLECTED',
                    alive=False, remote_exit_code=evidence['remote_exit_code'],
                    observation_source='verified_immutable_local_archive')
    observation = remote_python(ssh, STATUS_CODE, [evidence['remote_directory'], evidence['script_sha256']])
    if evidence.get('parallel_policy'):
        if observation.get('directory') != evidence['remote_directory']:
            raise ValueError('Observed original parallel directory differs')
        if observation.get('identity') is not None:
            evidence['process_identity'] = checked_parallel_identity(evidence, observation['identity'])
        elif observation.get('status') in ('RUNNING', 'FINISHED', 'LOST_WITHOUT_EXIT') or evidence.get('process_identity'):
            raise ValueError('Missing observed original parallel process identity')
    observation.update(run_id=run_id, observed_utc=utc())
    if resource_audit is not None:
        observation['resource_audit'] = resource_audit
    evidence['last_observation'] = observation
    if observation['remote_exit_code'] is not None:
        evidence['remote_exit_code'] = observation['remote_exit_code']
    if evidence['state'] not in ('COLLECTED', 'FAILED_COLLECTED'):
        evidence['state'] = {'RUNNING':'RUNNING','FINISHED':'EXECUTED','LOST_WITHOUT_EXIT':'LOST_WITHOUT_EXIT'}.get(observation['status'], evidence['state'])
    save_manifest(folder, evidence)
    observation['local_state'] = evidence['state']
    return observation


def assert_no_active_run(cfg, ssh):
    for path in (state_root()/'dram-see-v4/transport-probe/operations').glob('*/operation.json'):
        operation = json.loads(path.read_text(encoding='utf-8'))
        if (operation.get('staged_launch') is True and operation.get('parallel_slot_released') is not True
                and operation.get('connection_identity') == connection_identity(cfg)):
            raise RuntimeError('Reconcile the original outstanding staged operation before a serial launch: '+path.parent.name)
    for path in (state_root()/'runs').glob('*/manifest.json'):
        if path.parent.name.startswith('.'):
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('schema') != 'tcad-native-run-r2' or data.get('state') in ('COLLECTED','FAILED_COLLECTED'):
            continue
        if data.get('state') == 'INTERRUPTED_COLLECTED':
            verify_interrupted_terminal(path.parent, data)
            continue
        if sealed_and_released(data):
            continue
        with record_writer(path.parent):
            observed = status_run(cfg, ssh, data['run_id'])
            raise RuntimeError('Reconcile the original outstanding run before a new launch: ' + data['run_id'] + ' ' + observed['status'])
    code = r'''
import json,os
from pathlib import Path
active=[]
for base in Path('/proc').glob('[0-9]*'):
    try:
        name=(base/'comm').read_text().strip()
        argv=(base/'cmdline').read_bytes().split(b'\0')
        native_batch=name.startswith(('sdevice','snmesh','sde','transport_mat','cc1plus','cmi')) or name=='tdx' or (name=='svisual' and any(a in (b'-b',b'-batch') for a in argv))
        if native_batch:
            stat=(base/'stat').read_text().rsplit(')',1)[1].split()
            if stat[0]!='Z':active.append(dict(pid=int(base.name),name=name,cwd=os.readlink(str(base/'cwd'))))
    except OSError:pass
print(json.dumps(active))
'''
    active = remote_python(ssh, code, [])
    if active:
        raise RuntimeError('An existing native process must be protected: ' + json.dumps(active))
    remote(ssh, 'flock -n ' + shlex.quote(cfg['remote_root'].rstrip('/')+'/.solver.lock') + ' -c true', timeout=30)


INTERRUPTED_CHECK_CODE = r'''
import fcntl,hashlib,json,os,re,time
from pathlib import Path

def interrupted_observation(context):
    root=Path.cwd();proc_root=Path('/proc')
    identity=json.loads((root/'process-identity.json').read_text())
    if str(root)!=context['remote_directory'] or root.name!=context['run_id']:
        raise ValueError('Interrupted collection cwd/run ID differs')
    if identity!=context['process_identity']:
        raise ValueError('Interrupted collection original process identity differs')
    if hashlib.sha256((root/'run.sh').read_bytes()).hexdigest()!=context['script_sha256']:
        raise ValueError('Interrupted collection original script changed')
    current_boot=(proc_root/'sys/kernel/random/boot_id').read_text().strip()
    if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',current_boot) is None:
        raise ValueError('Current boot identity is invalid')
    if current_boot==identity['boot_id']:
        raise ValueError('Same-boot missing process is not a proven reboot interruption')
    if (root/'exit-code.txt').exists():
        raise ValueError('Original wrapper exit exists; use the normal collection path')
    lock_facts=[]
    for fd,path in ((9,context['shared_lock_path']),(8,str(root/'.collection/snapshot.lock'))):
        actual=os.fstat(fd);expected=Path(path).stat()
        if (actual.st_dev,actual.st_ino)!=(expected.st_dev,expected.st_ino):
            raise ValueError('Collection lock FD is not the original lock path')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        lock_facts.append(dict(fd=fd,path=path,device=actual.st_dev,inode=actual.st_ino,held=True))
    ancestors=set();pid=os.getpid()
    while pid>0 and pid not in ancestors:
        ancestors.add(pid)
        try:pid=int((proc_root/str(pid)/'stat').read_text().rsplit(')',1)[1].split()[1])
        except FileNotFoundError:break
    active=[];directory_processes=[]
    for base in proc_root.glob('[0-9]*'):
        try:
            stat=(base/'stat').read_text().rsplit(')',1)[1].split()
            name=(base/'comm').read_text().strip()
            if stat[0]=='Z':continue
            native=name.startswith(('sdevice','snmesh','sde','transport','cc1','cmi')) or name in ('tdx','svisual','svisual_exec')
            if native:active.append(dict(pid=int(base.name),name=name,start_ticks=int(stat[19])))
            if int(base.name) not in ancestors:
                try:cwd=os.readlink(str(base/'cwd'))
                except PermissionError:cwd=None
                if cwd==str(root):directory_processes.append(dict(pid=int(base.name),name=name,start_ticks=int(stat[19])))
        except (FileNotFoundError,ProcessLookupError):pass
    if active or directory_processes:
        raise ValueError('Active native/original-directory process must be protected: '+json.dumps(dict(native=active,directory=directory_processes)))
    native_evidence={}
    for item in context['native_evidence']:
        path=root/item['file']
        if not path.is_file():
            native_evidence[item['file']]=dict(available=False)
            continue
        raw=path.read_bytes();data=json.loads(raw.decode('utf-8'))
        if data.get('requested_tool')!=item['tool'] or data.get('wrapper_pid')!=identity['pid']:
            raise ValueError('Original native observation is not from this wrapper')
        native_evidence[item['file']]=dict(available=True,sha256=hashlib.sha256(raw).hexdigest(),
            native_pid=data.get('native_pid'),native_start_ticks=data.get('native_start_ticks'),
            native_executable=data.get('native_executable'),status=data.get('status'))
    return dict(observed_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),current_boot_id=current_boot,
        original_boot_id=identity['boot_id'],wrapper_identity=identity,actual_cwd=str(root),
        active_native_processes=active,active_directory_processes=directory_processes,
        original_wrapper_exit_present=False,locks=lock_facts,native_evidence=native_evidence)
'''


SNAPSHOT_CODE = termination_module().TERMINATION_CHECK_CODE + REMOTE_DURABILITY_CODE + r'''
import hashlib,io,json,os,tarfile
from pathlib import Path
root=Path.cwd();store=root/'.collection';store.mkdir(exist_ok=True)
target=store/'results.tar';receipt=store/'receipt.json'
part=store/'results.tar.tmp';pending=store/'receipt.pending.json'
interrupted=globals().get('interrupted_context')
context_sha=hashlib.sha256(json.dumps(interrupted,sort_keys=True,separators=(',',':')).encode()).hexdigest() if interrupted else None
before=interrupted_observation(interrupted) if interrupted else None
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
context=globals().get('snapshot_context');termination=None
sealing=globals().get('sealed_exit') is not None
if context:
    for name,expected in dict(context['input_sha256'],**{'run.sh':context['script_sha256']}).items():
        path=root/name
        if path.is_symlink() or not path.is_file() or digest(path)!=expected:raise ValueError('Original input/output provenance differs: '+name)
    if context.get('identity'):termination=checked_termination(root,context['identity'])
    if (root/'exit-code.txt').is_file() and (root/'exit-code.txt').read_text().strip()=='0':
        for name in context.get('required_outputs',[]):
            if not (root/name).is_file() or (root/name).stat().st_size<=0:raise ValueError('Successful run missing required output: '+name)
        for name in context.get('raw_exit_files',[]):
            if not (root/name).is_file() or (root/name).read_text().strip()!='0':raise ValueError('Success marker conflicts with raw native exits: '+name)
if sealing:
    exit_path=root/'exit-code.txt'
    raw=exit_path.read_text().strip() if exit_path.is_file() else None
    if (raw is not None and (not raw.isdigit() or not 0<=int(raw)<=255)
        or (int(raw) if raw is not None else None)!=sealed_exit['code']
        or (raw is None and not (termination or interrupted))):
        raise ValueError('Observed original terminal exit changed before sealing')
termination_sha=digest(root/'termination-record.json') if termination else None
def publish_pending():
    if not target.exists():os.replace(str(part),str(target))
    sync_dir(store)
    os.replace(str(pending),str(receipt))
    sync_dir(store)
    sync_dir(root)
recovered=False
if pending.exists():
    old=json.loads(pending.read_text())
    frozen=target if target.exists() else part
    if (receipt.exists() or old.get('schema')!='tcad-original-snapshot-r1'
        or old.get('termination_record_sha256')!=termination_sha
        or old.get('interrupted_context_sha256')!=context_sha
        or frozen.stat().st_size!=old['bytes'] or digest(frozen)!=old['sha256']):
        raise ValueError('Pending immutable original snapshot differs')
    if interrupted:
        proof=store/('interrupted-proof-'+old['interruption_proof_sha256']+'.json')
        if digest(proof)!=old['interruption_proof_sha256']:raise ValueError('Original interruption proof changed')
        sync_path(proof)
    sync_path(frozen);sync_path(pending);sync_dir(store)
    publish_pending();recovered=True
if target.is_file() and receipt.is_file():
    old=json.loads(receipt.read_text())
    if old.get('termination_record_sha256')!=termination_sha:raise ValueError('Existing original snapshot has a different termination context')
    if not recovered and (digest(target)!=old['sha256'] or (sealing and target.stat().st_size!=old['bytes'])):
        raise ValueError('Immutable remote snapshot changed')
    if bool(old.get('interrupted_context_sha256'))!=bool(interrupted):
        raise ValueError('Existing original snapshot has a different collection mode')
    if interrupted:
        if old['interrupted_context_sha256']!=context_sha:raise ValueError('Original interruption context changed')
        proof=store/('interrupted-proof-'+old['interruption_proof_sha256']+'.json')
        if digest(proof)!=old['interruption_proof_sha256']:raise ValueError('Original interruption proof changed')
    if sealing and not recovered:
        sync_path(target);sync_path(receipt);sync_dir(store);sync_dir(root)
    print(json.dumps(old))
else:
    if (interrupted or sealing) and (target.exists() or receipt.exists()):raise ValueError('Incomplete existing snapshot metadata; preserve original archive')
    if not interrupted and not termination and not (root/'exit-code.txt').is_file():raise ValueError('No original exit')
    if interrupted and (root/'_interrupted-collection-proof.json').exists():raise ValueError('Original file collides with derived interruption proof')
    files=[]
    for p in root.rglob('*'):
        if p.relative_to(root).parts[0]=='.collection':continue
        if p.is_symlink():raise ValueError('Unexpected link in original output')
        if p.is_file():files.append(p)
    index={p.relative_to(root).as_posix():dict(size=p.stat().st_size,sha256=digest(p)) for p in sorted(files)}
    with tarfile.open(str(part),'w') as archive:
        for p in sorted(files):archive.add(str(p),arcname=p.relative_to(root).as_posix(),recursive=False)
        if interrupted:
            after=interrupted_observation(interrupted)
            if after['current_boot_id']!=before['current_boot_id'] or after['native_evidence']!=before['native_evidence']:
                raise ValueError('Interruption observation changed during snapshot')
            proof=dict(schema='tcad-interrupted-collection-proof-r1',origin='derived_collection_evidence',synthetic=False,
                purpose='complete_existing_original_directory_after_proven_boot_change',context=interrupted,
                context_sha256=context_sha,before_snapshot=before,after_snapshot=after)
            proof_raw=json.dumps(proof,sort_keys=True,separators=(',',':')).encode()
            proof_sha=hashlib.sha256(proof_raw).hexdigest();proof_path=store/('interrupted-proof-'+proof_sha+'.json')
            if proof_path.exists():
                if proof_path.read_bytes()!=proof_raw:raise ValueError('Immutable interruption proof differs')
            else:
                if sealing:
                    proof_part=store/'interrupted-proof.tmp'
                    proof_part.write_bytes(proof_raw);sync_path(proof_part)
                    os.replace(str(proof_part),str(proof_path));sync_dir(store)
                else:
                    with proof_path.open('xb') as output:output.write(proof_raw)
            name='_interrupted-collection-proof.json';index[name]=dict(size=len(proof_raw),sha256=proof_sha)
            member=tarfile.TarInfo(name);member.size=len(proof_raw);archive.addfile(member,io.BytesIO(proof_raw))
        raw=json.dumps(index,sort_keys=True).encode();member=tarfile.TarInfo('_collection-members.json');member.size=len(raw);archive.addfile(member,io.BytesIO(raw))
    value=dict(schema='tcad-original-snapshot-r1',sha256=digest(part),bytes=part.stat().st_size,members=len(index))
    if termination_sha:value['termination_record_sha256']=termination_sha
    if interrupted:value.update(interrupted_context_sha256=context_sha,interruption_proof_sha256=proof_sha)
    if sealing:
        sync_path(part)
        temporary=store/'receipt.pending.tmp'
        temporary.write_text(json.dumps(value,sort_keys=True));sync_path(temporary)
        os.replace(str(temporary),str(pending));sync_dir(store)
        publish_pending()
    else:
        os.replace(str(part),str(target))
        receipt.write_text(json.dumps(value,sort_keys=True))
    print(json.dumps(value))
'''


def verify_archive(path, evidence):
    with tarfile.open(path) as archive:
        entries = archive.getmembers()
        names = [m.name for m in entries]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate original archive member')
        members = {m.name:m for m in entries}
        for member in entries:
            name = PurePosixPath(member.name)
            if not member.isfile() or name.is_absolute() or '..' in name.parts or '\\' in member.name:
                raise ValueError('Unsafe original archive member: ' + member.name)
        index = json.load(archive.extractfile(members['_collection-members.json']))
        if set(index) != set(members)-{'_collection-members.json'}:
            raise ValueError('Incomplete original archive index')
        for name, facts in index.items():
            h=hashlib.sha256()
            with archive.extractfile(members[name]) as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
            if members[name].size != facts['size'] or h.hexdigest() != facts['sha256']:
                raise ValueError('Original output differs from frozen snapshot: '+name)
        for name, digest in dict(evidence['input_sha256'], **{'run.sh':evidence['script_sha256']}).items():
            if index.get(name,{}).get('sha256') != digest:
                raise ValueError('Original input/output provenance differs: ' + name)
        if evidence.get('parallel_policy'):
            identity = json.load(archive.extractfile(members['process-identity.json']))
            checked_parallel_identity(evidence, identity, require_pinned=True)
            policy = evidence['parallel_policy']
            collected = json.load(archive.extractfile(members['parallel-slot-collection-evidence.json']))
            if (collected.get('policy') != policy or collected.get('script_sha256') != evidence['script_sha256']
                    or collected.get('gate_mode') != 'SHARED' or collected.get('slot_mode') != 'EXCLUSIVE'
                    or collected.get('status') != 'COLLECTION_LOCKS_ACQUIRED'
                    or collected.get('identity') != identity
                    or identity.get('run_id') != policy['work_id'] or identity.get('cwd') != policy['remote_directory']
                    or identity.get('script_sha256') != evidence['script_sha256']):
                raise ValueError('Original parallel collection/identity proof differs')
            if 'parallel-slot-evidence.json' in members:
                proof = json.load(archive.extractfile(members['parallel-slot-evidence.json']))
                valid = (proof.get('policy') == policy and proof.get('identity') == identity
                         and collected.get('lease_state') == 'ACTIVE'
                         and proof.get('script_sha256') == evidence['script_sha256']
                         and proof.get('gate_mode') == 'SHARED' and proof.get('slot_mode') == 'EXCLUSIVE'
                         and proof.get('gate_fd') == 9 and proof.get('slot_fd') == 7)
            else:
                # A real failed wrapper before slot activation is still evidence;
                # never promote its collector lock proof to successful execution.
                valid = evidence['remote_exit_code'] not in (None, 0) and collected.get('lease_state') == 'RESERVED'
            if not valid:
                raise ValueError('Original parallel slot proof differs')
        if evidence['remote_exit_code'] == 0:
            for step in evidence['steps']:
                for name in step['outputs']:
                    if index.get(name,{}).get('size',0) <= 0:
                        raise ValueError('Successful run missing required output: ' + name)
        if is_multicore(evidence.get('parallel_policy')):
            verify_multicore_archive(archive, members, evidence)
    return index


def verify_multicore_archive(archive, members, evidence):
    """Audit archived r4/r5 resources; failed native work stays a failed archive."""
    policy = evidence['parallel_policy']
    cpus = _MULTICORE_HELPERS['mc_policy'](policy)
    identity = evidence['process_identity']
    validate = _MULTICORE_HELPERS['mc_validate']

    def obj(name):
        if name not in members:
            raise ValueError('Missing multicore archive evidence: ' + name)
        return json.load(archive.extractfile(members[name]))

    proof = obj('parallel-slot-collection-evidence.json')
    if 'parallel-slot-evidence.json' in members:
        activated = obj('parallel-slot-evidence.json')
        validate(activated['wrapper_resources'], cpus, 1, identity['pid'],
                 identity['start_ticks'], identity['cwd'], exact=True)
        if proof.get('wrapper_resources') != activated['wrapper_resources']:
            raise ValueError('Multicore original wrapper collection resources differ')
    if evidence['remote_exit_code'] != 0:
        return  # Preserve missing/violating native evidence without declaring a pass.
    for key, tool in evidence['tool_evidence'].items():
        prefix = key
        observed = obj(tool['process_observation_file'])
        admitted = obj(tool['process_admission_file'])
        native_threads = policy['requested_threads'] if tool['tool'] == 'sdevice' else 1
        if (observed.get('schema') != 'native-process-observation-r2'
                or observed.get('status') != 'OBSERVED'
                or observed.get('resource_policy') != policy
                or observed.get('wrapper_pid') != identity['pid']
                or observed.get('requested_tool') != tool['tool']
                or admitted.get('schema') != 'native-process-admission-r2'
                or admitted.get('resource_policy') != policy
                or type(admitted.get('requested_threads')) is not int
                or admitted.get('requested_threads') != native_threads
                or _MULTICORE_HELPERS['mc_cpus'](admitted.get('requested_cpu')) != cpus
                or admitted.get('requested_tool') != tool['tool']
                or admitted.get('status') != 'PASSED' or admitted.get('errors') != []):
            raise ValueError('Multicore native admission/resource contract differs: ' + prefix)
        validate(observed['wrapper_resources'], cpus, 1, identity['pid'],
                 identity['start_ticks'], identity['cwd'], exact=True)
        validate(observed['native_resources'], cpus, None if tool['tool']=='sdevice' else 1,
                 observed['native_pid'], observed['native_start_ticks'], identity['cwd'])
        raw = archive.extractfile(members[tool['process_status_file']]).read()
        if (raw.decode('utf-8') != observed['native_resources']['status']
                or hashlib.sha256(raw).hexdigest() != observed.get('status_sha256')):
            raise ValueError('Multicore native raw status differs: ' + prefix)
        family = observed.get('native_process_family', [])
        snapshots = observed['family_resources']
        if len(snapshots) != len(family) or len({s['pid'] for s in snapshots}) != len(snapshots):
            raise ValueError('Multicore native family evidence differs')
        for member in family:
            original = member['identity']
            snapshot = next((s for s in snapshots if s['pid'] == original['pid']), None)
            if snapshot is None:
                raise ValueError('Missing multicore family resource snapshot')
            validate(snapshot, cpus, 1, original['pid'], original['start_ticks'], identity['cwd'])
            raw = archive.extractfile(members[member['status_file']]).read()
            if (raw.decode('utf-8') != snapshot['status']
                    or hashlib.sha256(raw).hexdigest() != member['status_sha256']):
                raise ValueError('Multicore family raw status differs')
        exit_file = tool['raw_process_admission_exit_file']
        if archive.extractfile(members[exit_file]).read().strip() != b'0':
            raise ValueError('Multicore process admission exit is not zero')


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def interrupted_context(cfg, folder, evidence, *, record_name='manifest.json', save=save_manifest, sealing=False):
    schema = 'tcad-native-run-r2' if record_name == 'manifest.json' else 'dram-see-v4-transport-operation-v2'
    run_id = evidence.get('run_id', evidence.get('label'))
    if (evidence.get('schema')!=schema or evidence.get('origin')!='native_pipeline'
            or evidence.get('synthetic') is not False or evidence.get('remote_exit_code') is not None):
        raise ValueError('Interrupted collection requires the original native run with unknown wrapper exit')
    identity=evidence.get('process_identity') or evidence.get('last_observation',{}).get('identity')
    if (not isinstance(identity,dict) or identity.get('schema')!='tcad-process-identity-r1'
            or identity.get('run_id')!=run_id or identity.get('cwd')!=evidence['remote_directory']
            or identity.get('script_sha256')!=evidence['script_sha256']
            or any(type(identity.get(k)) is not int or identity[k]<=0 for k in ('pid','start_ticks'))
            or re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',identity.get('boot_id','')) is None):
        raise ValueError('A complete previously recorded original process identity is required')
    if file_hash(folder/'run.sh')!=evidence['script_sha256']:
        raise ValueError('Local original wrapper fingerprint differs')
    native=[]
    for key,item in sorted(evidence.get('tool_evidence',{}).items()):
        name=item.get('process_observation_file')
        if not isinstance(name,str) or re.fullmatch(r'[A-Za-z0-9_.-]+',name) is None:
            raise ValueError('Expected original native observation filename')
        native.append(dict(step=key,tool=item['tool'],file=name))
    if evidence.get('capture_svisual_requested'):
        native.append(dict(step='svisual',tool='svisual',file='svisual-process-observation.json'))
    backup=folder/(Path(record_name).stem+'.before-interrupted-collection.json')
    current=(folder/record_name).read_bytes()
    if not backup.exists():
        with backup.open('xb') as stream:
            stream.write(current)
            if sealing:
                stream.flush()
                os.fsync(stream.fileno())
    saved=json.loads(backup.read_text(encoding='utf-8'))
    for key in ('run_id','label','remote_directory','script_sha256','runner_sha256','input_sha256','ssh_exit_code','remote_exit_code'):
        if saved.get(key)!=evidence.get(key):raise ValueError('Original pre-collection manifest differs: '+key)
    context=dict(schema='tcad-interrupted-collection-context-r1',run_id=run_id,
        remote_directory=evidence['remote_directory'],process_identity=identity,script_sha256=evidence['script_sha256'],
        source_runner_sha256=evidence['runner_sha256'],source_manifest_sha256=file_hash(backup),
        input_sha256_map_sha256=canonical_sha256(evidence['input_sha256']),native_evidence=native,
        shared_lock_path=cfg['remote_root'].rstrip('/')+'/.solver.lock',
        collection_implementation_sha256=file_hash(Path(__file__)))
    previous=evidence.get('interrupted_collection_context')
    if previous is not None and previous!=context:
        raise ValueError('Original interrupted collection context or implementation changed')
    evidence['interrupted_collection_context']=context
    evidence['collection_implementation_sha256']=context['collection_implementation_sha256']
    if sealing:
        evidence['interrupted_seal_requested'] = True
        save(folder,evidence,durable=True)
    else:
        save(folder,evidence)
    return context


def verify_interrupted_archive(path, evidence, index, snapshot, context):
    name='_interrupted-collection-proof.json'
    if 'exit-code.txt' in index:
        raise ValueError('Interrupted original archive unexpectedly contains a wrapper exit')
    context_sha=canonical_sha256(context)
    if (snapshot.get('interrupted_context_sha256')!=context_sha
            or snapshot.get('interruption_proof_sha256')!=index.get(name,{}).get('sha256')):
        raise ValueError('Original interrupted snapshot/proof binding differs')
    with tarfile.open(path) as archive:
        proof=json.load(archive.extractfile(name))
        original=json.load(archive.extractfile('process-identity.json'))
    if (proof.get('schema')!='tcad-interrupted-collection-proof-r1' or proof.get('origin')!='derived_collection_evidence'
            or proof.get('synthetic') is not False or proof.get('context')!=context
            or proof.get('context_sha256')!=context_sha or original!=context['process_identity']):
        raise ValueError('Original interrupted proof identity/context differs')
    observations=[proof.get(key,{}) for key in ('before_snapshot','after_snapshot')]
    for item in observations:
        boot=item.get('current_boot_id','')
        if (re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',boot) is None
                or boot==original['boot_id'] or item.get('original_boot_id')!=original['boot_id']
                or item.get('wrapper_identity')!=original or item.get('actual_cwd')!=evidence['remote_directory']
                or item.get('active_native_processes')!=[] or item.get('active_directory_processes')!=[]
                or item.get('original_wrapper_exit_present') is not False or not item.get('observed_utc')):
            raise ValueError('Interrupted proof does not establish a quiescent different boot')
        locks=item.get('locks',[])
        if len(locks)!=2:
            raise ValueError('Original interrupted proof lacks both collection locks')
        for value,fd,lock_path in zip(locks,(9,8),(context['shared_lock_path'],evidence['remote_directory']+'/.collection/snapshot.lock')):
            if (value.get('fd')!=fd or value.get('path')!=lock_path or value.get('held') is not True
                    or any(type(value.get(k)) is not int or value[k]<0 for k in ('device','inode'))):
                raise ValueError('Original interrupted proof lock identity differs')
        if set(item.get('native_evidence',{}))!={v['file'] for v in context['native_evidence']}:
            raise ValueError('Original interrupted native observation inventory differs')
        for filename,value in item['native_evidence'].items():
            if value.get('available') is True:
                if value.get('sha256')!=index.get(filename,{}).get('sha256'):
                    raise ValueError('Original native observation differs from interruption proof')
            elif value.get('available') is not False or filename in index:
                raise ValueError('Original native observation availability differs')
    if (observations[0]['current_boot_id']!=observations[1]['current_boot_id']
            or observations[0]['native_evidence']!=observations[1]['native_evidence']
            or observations[0]['locks']!=observations[1]['locks']):
        raise ValueError('Interrupted snapshot observations changed')
    return proof


def verify_interrupted_terminal(folder, evidence):
    if (evidence.get('collection_verified') is not True or evidence.get('remote_exit_code') is not None
            or type(evidence.get('collection_exit_code')) is not int or evidence['collection_exit_code']!=0
            or evidence.get('execution_outcome')!='INTERRUPTED_UNKNOWN_EXIT'
            or not evidence.get('interruption_proof_sha256') or not evidence.get('interrupted_collection_context')):
        raise ValueError('Interrupted terminal receipt is not a verified original collection')
    if file_hash(folder/'results.tar')!=evidence['results_sha256']:
        raise ValueError('Previously collected immutable archive changed')


def sealed_snapshot(record):
    if 'sealed_snapshot' not in record:
        return None
    snapshot = record['sealed_snapshot']
    if (not isinstance(snapshot, dict) or not isinstance(snapshot.get('sha256'), str)
            or re.fullmatch(r'[0-9a-f]{64}', snapshot['sha256']) is None
            or type(snapshot.get('bytes')) is not int or snapshot['bytes'] <= 0
            or not isinstance(snapshot.get('sealed_utc'), str)):
        raise ValueError('Invalid original sealed snapshot')
    stamp = datetime.fromisoformat(snapshot['sealed_utc'])
    if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
        raise ValueError('Original seal timestamp must be UTC')
    return snapshot


def sealed_and_released(record):
    return record.get('parallel_slot_released') is True and sealed_snapshot(record) is not None


def snapshot_command(cfg, record, snapshot_context, *, interrupted=None, sealing=False):
    directory = shlex.quote(record['remote_directory'])
    lock = shlex.quote(cfg['remote_root'].rstrip('/')+'/.solver.lock')
    snapshot_code = 'snapshot_context='+repr(snapshot_context)+'\n'+SNAPSHOT_CODE
    if sealing:
        snapshot_code = 'sealed_exit='+repr({'code': record['remote_exit_code']})+'\n'+snapshot_code
    if interrupted is not None:
        snapshot_code = INTERRUPTED_CHECK_CODE+'\ninterrupted_context='+repr(interrupted)+'\n'+snapshot_code
    if record.get('parallel_policy'):
        lines = (parallel_shell_lines(record['parallel_policy'], 'seal', record) if sealing
                 else parallel_shell_lines(record['parallel_policy'], 'collect'))
        return '\n'.join(['set -e', 'cd ' + directory] + lines + [
            'mkdir -p .collection; exec 8>.collection/snapshot.lock; flock -n 8 || exit 75',
            "/usr/bin/python3 - <<'TCAD_SNAPSHOT'", snapshot_code, 'TCAD_SNAPSHOT', ''])
    return ('set -e; cd '+directory+'; exec 9>'+lock+'; flock -n 9 || exit 75; mkdir -p .collection; '
            "exec 8>.collection/snapshot.lock; flock -n 8 || exit 75; /usr/bin/python3 - <<'TCAD_SNAPSHOT'\n"
            + snapshot_code+'\nTCAD_SNAPSHOT\n')


def prepare_seal(cfg, ssh, record, observed, snapshot_context, *, interrupted=None):
    expected_status = 'LOST_WITHOUT_EXIT' if interrupted is not None else 'FINISHED'
    if observed['status'] != expected_status or observed['alive'] is not False:
        raise RuntimeError('Only the completed original work can be sealed: ' + observed['status'])
    identity = checked_parallel_identity(record, observed.get('identity'))
    record.update(process_identity=identity, remote_exit_code=observed['remote_exit_code'])
    snapshot_context['identity'] = identity
    command = snapshot_command(cfg, record, snapshot_context, sealing=True, interrupted=interrupted)
    response = remote(ssh, command, capture_output=True, text=True, timeout=300)
    receipt = json.loads(response.stdout)
    context_sha = canonical_sha256(interrupted) if interrupted is not None else None
    if receipt.get('schema') != 'tcad-original-snapshot-r1' or receipt.get('interrupted_context_sha256') != context_sha:
        raise ValueError('Invalid original snapshot receipt for seal')
    record['sealed_snapshot'] = dict(sha256=receipt['sha256'], bytes=receipt['bytes'], sealed_utc=utc())
    sealed_snapshot(record)
    record['collection_verified'] = False
    if interrupted is not None:
        proof_sha = receipt.get('interruption_proof_sha256')
        if not isinstance(proof_sha, str) or re.fullmatch(r'[0-9a-f]{64}', proof_sha) is None:
            raise ValueError('Invalid original interrupted seal proof')
        record['interrupted_collection_snapshot'] = receipt
    return receipt


def seal_observed(cfg, ssh, folder, record, observed, snapshot_context, save, record_name):
    if observed['status'] != 'LOST_WITHOUT_EXIT':
        if record.get('interrupted_seal_requested'):
            raise ValueError('Original terminal exit changed during interrupted seal recovery')
        return prepare_seal(cfg, ssh, record, observed, snapshot_context)
    try:
        context = interrupted_context(cfg, folder, record, record_name=record_name, save=save, sealing=True)
        receipt = prepare_seal(cfg, ssh, record, observed, snapshot_context, interrupted=context)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        record.pop('sealed_snapshot', None)
        record['seal_reconciliation_error'] = getattr(exc, 'stderr', None) or str(exc)
        save(folder, record, durable=True)
        raise RuntimeError('LOST_WITHOUT_EXIT: original reboot seal proof unavailable; retain original slot: '
                           + record['seal_reconciliation_error']) from exc
    record.pop('seal_reconciliation_error', None)
    return receipt


def finish_seal(cfg, ssh, folder, record, save):
    snapshot = sealed_snapshot(record)
    if record.get('parallel_slot_released') is not True:
        save(folder, record, durable=True)
        if record.get('parallel_policy'):
            parallel_query(cfg, ssh, record, 'release-sealed')
        record['parallel_slot_released'] = True
        save(folder, record, durable=True)
    return dict(status='SEALED', sealed_snapshot=snapshot, parallel_slot_released=True,
                collection_verified=record.get('collection_verified') is True,
                remote_exit_code=record['remote_exit_code'])


def run_snapshot_context(evidence):
    return dict(input_sha256=evidence['input_sha256'],script_sha256=evidence['script_sha256'],
        identity=evidence.get('process_identity'),required_outputs=[name for step in evidence['steps'] for name in step['outputs']],
        raw_exit_files=['metadata-sdevice-version-exit-code.txt']+[value['raw_exit_file'] for value in evidence['tool_evidence'].values()])


def seal_run(cfg, ssh, run_id):
    with record_writer(run_folder(run_id)):
        folder, evidence = read_manifest(cfg, run_id)
        if sealed_snapshot(evidence) is None:
            if (evidence.get('collection_verified')
                    or (evidence.get('interrupted_collection_context') and not evidence.get('interrupted_seal_requested'))
                    or evidence.get('state') in ('COLLECTED', 'FAILED_COLLECTED', 'INTERRUPTED_COLLECTED')):
                raise ValueError('Use collect to finish the existing original collection')
            observed = status_run(cfg, ssh, run_id, for_seal=True)
            folder, evidence = read_manifest(cfg, run_id)
            seal_observed(cfg, ssh, folder, evidence, observed, run_snapshot_context(evidence), save_manifest, 'manifest.json')
        return dict(finish_seal(cfg, ssh, folder, evidence, save_manifest), run_id=run_id)


def collect_run(cfg, ssh, run_id, interrupted=False):
    folder,evidence = read_manifest(cfg,run_id)
    policy = parallel_record_policy(cfg, evidence)
    sealed = sealed_snapshot(evidence)
    if sealed is not None and interrupted:
        raise ValueError('Use normal collect for this original sealed snapshot')
    # Parallel recovery uses the original pool gate and slot lease through the
    # verified collect protocol below. It never clears a lease without proving
    # a different boot, quiescent native processes, immutable input identity,
    # and a verified archive before release.
    if evidence.get('state')=='INTERRUPTED_COLLECTED':
        verify_interrupted_terminal(folder,evidence)
        if policy and sealed is None:
            parallel_release(cfg, ssh, evidence)
            save_manifest(folder, evidence)
        return dict(run_id=run_id,status=evidence['state'],remote_exit_code=evidence['remote_exit_code'],archive=str(folder/'results.tar'))
    if evidence.get('state') in ('COLLECTED','FAILED_COLLECTED'):
        if file_hash(folder/'results.tar') != evidence['results_sha256']:
            raise ValueError('Previously collected immutable archive changed')
        if sealed is None:
            parallel_release(cfg, ssh, evidence)
            if policy:
                save_manifest(folder, evidence)
        return dict(run_id=run_id,status=evidence['state'],remote_exit_code=evidence['remote_exit_code'],archive=str(folder/'results.tar'))
    context=None
    interrupted_snapshot = evidence.get('interrupted_collection_snapshot') if sealed is not None else None
    if interrupted:
        context=interrupted_context(cfg,folder,evidence)
    elif interrupted_snapshot is not None:
        context=evidence['interrupted_collection_context']
    elif sealed is None:
        observed = status_run(cfg,ssh,run_id)
        if observed['status']!='FINISHED' or observed['alive']:
            raise RuntimeError('Only the completed original job can be collected: '+observed['status'])
        folder,evidence=read_manifest(cfg,run_id)
    qdir=shlex.quote(evidence['remote_directory'])
    partial=folder/('results.'+uuid.uuid4().hex+'.part.tar')
    transfer_started=False
    try:
        snapshot=sealed
        if snapshot is None:
            script=snapshot_command(cfg,evidence,run_snapshot_context(evidence),interrupted=context)
            result=remote(ssh,script,capture_output=True,text=True,timeout=300)
            snapshot=json.loads(result.stdout)
        with partial.open('xb') as stream:
            transfer_started=True
            transfer=remote(ssh,'cat '+qdir+'/.collection/results.tar',stdout=stream,timeout=300)
        evidence['collection_exit_code']=transfer.returncode
        if partial.stat().st_size!=snapshot['bytes'] or file_hash(partial)!=snapshot['sha256']:
            raise ValueError('Incomplete original archive transfer; retain partial and resume collect')
        if transfer.returncode!=0:
            raise ValueError('Original archive transfer did not exit zero')
        index=verify_archive(partial,evidence)
        if context is not None:
            verify_interrupted_archive(partial,evidence,index,interrupted_snapshot or snapshot,context)
        raw_names=['exit-code.txt','metadata-sdevice-version-exit-code.txt']+[v['raw_exit_file'] for v in evidence['tool_evidence'].values()]
        if context is not None:
            raw_names += [v['raw_process_admission_exit_file'] for v in evidence['tool_evidence'].values() if v.get('raw_process_admission_exit_file')]
        exits,errors=capture_archive_exit_codes(partial,raw_names)
        if sealed is not None and exits['exit-code.txt'] != evidence['remote_exit_code']:
            raise ValueError('Sealed and archived original exits differ')
        evidence['remote_exit_code']=exits['exit-code.txt']
        evidence['version_probe_exit_code']=exits['metadata-sdevice-version-exit-code.txt']
        for key,value in evidence['tool_evidence'].items():evidence['tool_exit_codes'][key]=exits[value['raw_exit_file']]
        evidence['capture_exit_errors']=errors
        with tarfile.open(partial) as stream:termination=termination_module().verify_archive(stream,evidence)
        if termination:
            evidence['termination_record']=termination
            if termination['execution_outcome']=='TERMINATED_BY_OPERATOR':
                evidence.update(execution_outcome='TERMINATED_BY_OPERATOR',derived_exit_code=termination.get('derived_exit_code'))
        evidence['results_sha256']=snapshot['sha256']
        evidence['collected_bytes']=snapshot['bytes']
        evidence['collected_utc']=utc()
        if evidence['remote_exit_code']==0 and (errors or evidence['version_probe_exit_code']!=0 or any(v!=0 for v in evidence['tool_exit_codes'].values())):
            raise ValueError('Success marker conflicts with raw native exits')
        target=folder/'results.tar'
        if target.exists():
            if file_hash(target)!=snapshot['sha256']:raise ValueError('Refusing to replace a different existing archive')
        else:os.replace(partial,target)
        if context is not None:
            receipt = interrupted_snapshot or snapshot
            evidence.update(state='INTERRUPTED_COLLECTED',execution_outcome='INTERRUPTED_UNKNOWN_EXIT',
                interruption_reason='ORIGINAL_BOOT_REPLACED',interruption_proof_sha256=receipt['interruption_proof_sha256'],
                interrupted_collection_snapshot=receipt,interrupted_raw_exit_codes=exits,
                process_identity=context['process_identity'])
        else:
            evidence['state']='COLLECTED' if evidence['remote_exit_code']==0 else 'FAILED_COLLECTED'
        evidence['collection_verified']=True
        evidence.pop('collection_error',None)
        save_manifest(folder,evidence)
        if policy and sealed is None:
            parallel_release(cfg, ssh, evidence)
            save_manifest(folder, evidence)
    except BaseException as exc:
        evidence['collection_error']=repr(exc)
        if transfer_started and getattr(exc,'returncode',None) is not None:evidence['collection_exit_code']=exc.returncode
        save_manifest(folder,evidence)
        raise
    return dict(run_id=run_id,status=evidence['state'],remote_exit_code=evidence['remote_exit_code'],ssh_exit_code=evidence['ssh_exit_code'],archive=str(folder/'results.tar'),bytes=snapshot['bytes'])


def run_project(cfg, ssh, project, run_id=None, detach=False, data_root=None, parallel_slot=None, *, staged_launch=False):
    if data_root is not None:data_root=normalize_data_root(data_root)
    if staged_launch and (not detach or parallel_slot is None):
        raise ValueError('--staged-launch requires --detach and --parallel-slot')
    with ExitStack() as launch_owner, ExitStack() as writers:
        project = Path(project)
        enter_launch_owner(launch_owner, staged_launch)
        if run_id and run_folder(run_id).exists():
            writers.enter_context(record_writer(run_folder(run_id)))
            bound = read_manifest(cfg,run_id,data_root=data_root)
            if parallel_slot is not None and (bound[1].get('parallel_policy') or {}).get('slot') != parallel_slot:
                raise ValueError('Repeated run ID cannot change original execution slot')
            return status_run(cfg,ssh,run_id)
        if staged_launch:
            writers.enter_context(staged_project_writer(project))
        return _run_project(cfg,ssh,project,run_id=run_id,detach=detach,data_root=data_root,
                            writers=writers, release_launch_owner=launch_owner.close if staged_launch else None,
                            **({'parallel_slot': parallel_slot} if parallel_slot is not None else {}))


def _run_project(cfg, ssh, project, run_id=None, detach=False, data_root=None, parallel_slot=None,
                 *, writers=None, release_launch_owner=None):
    if writers is None:
        with ExitStack() as local_writers:
            return _run_project(cfg, ssh, project, run_id, detach, data_root, parallel_slot, writers=local_writers,
                                release_launch_owner=release_launch_owner)
    if data_root is not None:data_root=normalize_data_root(data_root)
    project = project.resolve()
    if not project.is_dir():
        raise ValueError('Project directory does not exist')
    spec = json.loads((project / 'project.json').read_text(encoding='utf-8'))
    bridge = geometry_module() if 's2_geometry' in spec else None
    geometry_cfg = bridge.geometry_admit(project, spec, file_hash(Path(__file__))) if bridge else None
    if geometry_cfg and geometry_cfg['mode'] == 'reuse':
        bridge.geometry_stage_reuse(project, geometry_cfg)
    elif geometry_cfg and geometry_cfg['mode'] == 'produce_from_mesh':
        bridge.geometry_stage_mesh_reuse(project, geometry_cfg)
    elif geometry_cfg and geometry_cfg['mode'] == 'produce_from_metadata':
        bridge.geometry_stage_metadata_reuse(project, geometry_cfg)
    elif geometry_cfg and geometry_cfg['mode'] == 'produce_from_geometry':
        bridge.geometry_stage_dc_reuse(project, geometry_cfg)
    mesh_source_binding_sha256 = (file_hash(project / 'mesh-source-binding.json')
                                 if geometry_cfg and geometry_cfg['mode'] == 'produce_from_mesh' else None)
    metadata_source_binding_sha256 = (file_hash(project / 'metadata-source-binding.json')
                                     if geometry_cfg and geometry_cfg['mode'] == 'produce_from_metadata' else None)
    dc_source_binding_sha256 = (file_hash(project / 'dc-source-binding.json')
                               if geometry_cfg and geometry_cfg['mode'] == 'produce_from_geometry' else None)
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', spec['name']):
        raise ValueError('Use a lowercase engineering project name')
    steps = spec['steps']
    if not steps:
        raise ValueError('A project needs at least one real tool step')
    allowed = {'sde', 'snmesh', 'sdevice'} | ({'svisual', 'tdx'} if geometry_cfg else set())
    for step in steps:
        if step['tool'] not in allowed or not all(isinstance(a, str) for a in step['args']):
            raise ValueError('Only explicit supported native tool argument arrays are allowed')
        if step['tool'] == 'sdevice' and any('thread' in a.lower() for a in step['args']):
            raise ValueError('Thread count is managed by the runner')
        if not step.get('outputs'):
            raise ValueError('Every step must declare its expected output files')
        for output in step['outputs']:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', output):
                raise ValueError('Expected outputs must be simple filenames')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run_id = run_id or (geometry_cfg['run_id'] if geometry_cfg else stamp + '-' + spec['name'] + '-' + uuid.uuid4().hex[:8])
    validate_run_id(run_id)
    if geometry_cfg and run_id != geometry_cfg['run_id']:
        raise ValueError('Requested run ID differs from exact geometry context')
    if connection_identity(cfg) is not None and (ROOT/'local_runtime/runs'/run_id).exists():
        raise ValueError('Historical VM run ID cannot be resubmitted through a cloud profile')
    local = run_folder(run_id)
    writers.enter_context(record_writer(local))
    remote_dir = (data_root if data_root is not None else cfg['remote_root'].rstrip('/')) + '/runs/' + run_id
    policy = parallel_policy(cfg, parallel_slot, run_id, remote_dir) if parallel_slot is not None else None
    if is_multicore(policy):
        for key in ('native_threads', 'native_cores'):
            if key in spec and (type(spec[key]) is not int or spec[key] != policy['requested_threads']):
                raise ValueError('Multicore project metadata must agree with requested threads/cores')
    elif parallel_slot is None and 'cpu_sets' in cfg:
        raise ValueError('Multicore profiles require an explicit parallel slot')
    if local.exists():
        bound = read_manifest(cfg,run_id,data_root=data_root)
        if parallel_slot is not None and bound[1].get('parallel_policy') != policy:
            raise ValueError('Repeated run ID cannot change original execution slot/policy')
        return status_run(cfg, ssh, run_id)
    if policy:
        parallel_assert_local(cfg)
    else:
        assert_no_active_run(cfg, ssh)
    staging = local.with_name('.staging-' + run_id)
    staging.mkdir(parents=True, exist_ok=False)
    active_dir = staging
    evidence = None
    reserve_attempted = False
    def save():
        save_manifest(active_dir, evidence)
    try:
        remote_dir = (data_root if data_root is not None else cfg['remote_root'].rstrip('/')) + '/runs/' + run_id
        commit = execute(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                         capture_output=True, text=True).stdout.strip()
        files = sorted(p for p in project.rglob('*') if p.is_file())
        if any(p.is_symlink() for p in project.rglob('*')):
            raise ValueError('Symlinks are not allowed in simulation inputs')
        inputs = {p.relative_to(project).as_posix(): file_hash(p) for p in files}
        evidence = {'schema': 'tcad-native-run-r2', 'run_id': run_id,
                    'started_utc': utc(), 'project_directory': str(project), 'detached': detach, 'commit': commit, 'input_sha256': inputs,
                    'origin': 'native_pipeline', 'synthetic': False,
                    'ssh_exit_code': None, 'remote_exit_code': None, 'collection_exit_code': None,
                    'version_probe_exit_code': None,
                    'tool_exit_codes': {}, 'tool_evidence': {},
                    'runner_sha256': file_hash(Path(__file__)),
                    'steps': steps, 'remote_directory': remote_dir, 'state': 'PREPARED',
                    'interpretation': 'Engineering execution only; scientific validity requires review'}
        if connection_identity(cfg) is not None:
            evidence['connection_identity'] = connection_identity(cfg)
        if data_root is not None:
            evidence.update(remote_layout=DATA_ROOT_LAYOUT,data_root=data_root,
                            control_root=cfg['remote_root'],
                            shared_lock_path=cfg['remote_root'].rstrip('/')+'/.solver.lock')
        if geometry_cfg and geometry_cfg['mode'] == 'produce_from_mesh':
            evidence.update(native_step_start_index=3, inherited_step_indices=[1, 2],
                            mesh_source_binding_sha256=mesh_source_binding_sha256)
        elif geometry_cfg and geometry_cfg['mode'] == 'produce_from_metadata':
            evidence.update(native_step_start_index=5, inherited_step_indices=[1, 2, 3],
                            metadata_source_binding_sha256=metadata_source_binding_sha256,
                            geometry_observation_backend='native_hdf5_v16_export')
        elif geometry_cfg and geometry_cfg['mode'] == 'produce_from_geometry':
            evidence.update(native_step_start_index=6, inherited_step_indices=[1, 2, 3, 5],
                            dc_source_binding_sha256=dc_source_binding_sha256,
                            geometry_producer_run_id=geometry_cfg['geometry_producer_run_id'],
                            geometry_selector_file=geometry_cfg['geometry_selector_file'],
                            geometry_selector_sha256=geometry_cfg['geometry_selector_sha256'],
                            geometry_report_file=geometry_cfg['geometry_report_file'],
                            geometry_observation_backend='native_hdf5_v16_export')
        if release_launch_owner is not None:
            evidence['staged_launch'] = True
        if policy:
            evidence['parallel_policy'] = policy
            if is_multicore(policy):
                evidence['requested_resources'] = dict(cpu_set=policy['cpu_set'], requested_threads=policy['requested_threads'],
                    sdevice_environment=dict(OMP_NUM_THREADS=policy['requested_threads'],
                                            MKL_NUM_THREADS=policy['requested_threads'], OPENBLAS_NUM_THREADS=1))
        archive = staging / 'inputs.tar'
        with tarfile.open(archive, 'w') as tf:
            for p in files:
                tf.add(p, arcname=p.relative_to(project).as_posix(), recursive=False)
        qdir = shlex.quote(remote_dir)
        qroot = shlex.quote(cfg['remote_root'])
        runner = ['#!/bin/bash', 'set -euo pipefail', 'umask 077',
                  'cd ' + qdir,
                  'trap \'rc=$?; printf "%s\\n" "$rc" > exit-code.txt; date -u +%Y-%m-%dT%H:%M:%SZ > finished-utc.txt\' EXIT',
                  'trap \'trap "" TERM INT; wait || :; exit 143\' TERM',
                  'trap \'trap "" TERM INT; wait || :; exit 130\' INT',
                  'exec > execution.log 2>&1',
                  'export PATH=' + shlex.quote(cfg['tool_bin']) + ':"$PATH"',
                  'export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1',
                  'mkdir -p ' + qroot,
                  'exec 9>' + qroot + '/.solver.lock',
                  'flock -n 9 || { echo "Another project run holds the solver lock" >&2; exit 75; }',
                  "printf 'status=ACQUIRED\nfd=9\nlock_path=%s\npid=%s\nacquired_utc=%s\n' "
                  + shlex.quote(cfg['remote_root'].rstrip('/') + '/.solver.lock')
                  + ' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > shared-lock-evidence.txt',
                  'cpu=$(awk \'/^Cpus_allowed_list:/{split($2,a,/[-,]/);print a[1]}\' /proc/self/status)',
                  'date -u; hostname']
        if policy:
            # Remove only the explicit legacy lock/first-CPU block for NEW jobs.
            start = runner.index('exec 9>' + qroot + '/.solver.lock')
            runner = runner[:start] + process_identity_lines(run_id)
            if is_multicore(policy):
                runner += ['cpu=' + ','.join(str(cpu) for cpu in policy['cpu_set']), 'taskset -pc "$cpu" $$']
                runner += parallel_shell_lines(policy, 'activate', staged_launch=release_launch_owner is not None)
                runner += ['date -u; hostname']
            else:
                runner += parallel_shell_lines(policy, 'activate', staged_launch=release_launch_owner is not None)
                runner += ['cpu=' + str(policy['cpu']), 'taskset -pc "$cpu" $$', 'date -u; hostname']
        else:
            runner += process_identity_lines(run_id)
        runner += native_capture_shell_lines(policy) if is_multicore(policy) else native_capture_shell_lines()
        capture_installation = cfg['tool_bin'].rstrip('/').rsplit('/', 1)[0]
        runner += ['capture_native_step metadata-sdevice-version sdevice '
                   + shlex.quote(capture_installation) + ' sdevice -v', 'taskset -pc $$']
        if geometry_cfg and geometry_cfg['mode'] in ('reuse', 'produce_from_mesh', 'produce_from_metadata', 'produce_from_geometry'):
            runner += ['taskset -c "$cpu" /usr/bin/python3 mesh_resource_guard.py']
        if geometry_cfg and geometry_cfg['mode'] in ('produce_from_mesh', 'produce_from_metadata'):
            runner += ['taskset -c "$cpu" /usr/bin/python3 geometry_bridge.py prepare --folder . --run-id ' + shlex.quote(run_id)]
        first_step = ({'produce_from_mesh': 3, 'produce_from_metadata': 5, 'produce_from_geometry': 6}.get(geometry_cfg['mode'], 1)
                      if geometry_cfg else 1)
        for index, step in enumerate(steps, first_step):
            args = [step['tool']]
            if step['tool'] == 'sdevice':
                if is_multicore(policy):
                    args += ['--threads', str(policy['requested_threads']), '--exit-on-failure']
                else:
                    args += ['--threads', '1', '--exit-on-failure']
            args += step['args']
            capture_key = 'step-{:03d}-{}'.format(index, step['tool'])
            evidence['tool_exit_codes'][capture_key] = None
            evidence['tool_evidence'][capture_key] = {
                'step_index': index, 'tool': step['tool'],
                'raw_exit_file': capture_key + '-exit-code.txt',
                'process_status_file': capture_key + '-process-status.txt',
                'process_observation_file': capture_key + '-process-observation.json',
                'process_admission_file': capture_key + '-process-admission.json',
                'raw_process_admission_exit_file': capture_key + '-process-admission-exit-code.txt'}
            if is_multicore(policy):
                evidence['tool_evidence'][capture_key].update(
                    requested_cpu_set=policy['cpu_set'], requested_threads=policy['requested_threads'] if step['tool']=='sdevice' else 1)
            capture_command = 'capture_native_step ' + shlex.join([capture_key, step['tool'], capture_installation]) + ' ' + shlex.join(args)
            if is_multicore(policy):
                step_threads = policy['requested_threads'] if step['tool'] == 'sdevice' else 1
                runner += ['export OMP_NUM_THREADS={0} MKL_NUM_THREADS={0}'.format(step_threads)]
            runner += ['echo ' + shlex.quote('STEP ' + str(index) + ': ' + shlex.join(args))]
            if geometry_cfg and geometry_cfg['mode'] in ('produce', 'produce_from_mesh', 'produce_from_metadata') and step['tool'] in ('sde', 'snmesh', 'tdx', 'svisual'):
                canonical = bridge.GEOMETRY_EXITS[capture_key + '-exit-code.txt']
                runner += ['if ' + capture_command + '; then geometry_step_rc=0; else geometry_step_rc=$?; fi',
                           'if taskset -c "$cpu" /usr/bin/python3 geometry_bridge.py record-exit ' + shlex.join(['--folder', '.', '--source', capture_key + '-exit-code.txt', '--canonical', canonical]) + '; then geometry_alias_rc=0; else geometry_alias_rc=$?; fi',
                           'if [ "$geometry_step_rc" -ne 0 ]; then exit "$geometry_step_rc"; fi',
                           'if [ "$geometry_alias_rc" -ne 0 ]; then exit "$geometry_alias_rc"; fi']
            else:
                runner += [capture_command]
            runner += ['test -s ' + shlex.quote(out) for out in step['outputs']]
            if geometry_cfg and geometry_cfg['mode'] in ('produce', 'produce_from_mesh', 'produce_from_metadata'):
                if step['tool'] == 'snmesh':
                    runner += ['taskset -c "$cpu" /usr/bin/python3 mesh_resource_guard.py',
                               'taskset -c "$cpu" /usr/bin/python3 geometry_bridge.py prepare --folder . --run-id ' + shlex.quote(run_id)]
                elif step['tool'] == 'svisual':
                    runner += ['taskset -c "$cpu" /usr/bin/python3 geometry_bridge.py finalize --folder . --run-id ' + shlex.quote(run_id)]
        runner += ['echo ENGINEERING_RUN_COMPLETED']
        script = '\n'.join(runner) + '\n'
        (staging / 'run.sh').write_text(script, encoding='utf-8', newline='\n')
        evidence['script_sha256'] = file_hash(staging / 'run.sh')
        evidence['inputs_archive_sha256'] = file_hash(archive)
        save()
        if release_launch_owner is not None:
            staging.rename(local)
            active_dir = local
            archive = local / 'inputs.tar'
            save_manifest(local, evidence, durable=True)
            sync_directory(local.parent)
        if policy:
            reserve_attempted = True
            try:
                parallel_query(cfg, ssh, evidence, 'reserve')
            except subprocess.CalledProcessError as exc:
                # Exit 75 alone could come from the SSH wrapper or a login hook.
                if exc.returncode == PREFLIGHT_EXIT_CODE and any(
                        line.startswith('TCAD_RESERVE_REJECTED: ')
                        for line in (exc.stderr or '').splitlines()):
                    diag_dir = state_root() / 'preflight-failures'
                    diag_dir.mkdir(parents=True, exist_ok=True)
                    diag_stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                    diag_path = diag_dir / ('{}-{}-{}.json'.format(diag_stamp, run_id, uuid.uuid4().hex[:6]))
                    diag_path.write_text(json.dumps({
                        'utc': utc(), 'run_id': run_id, 'slot': policy['slot'],
                        'preflight_rejected': True, 'error': repr(exc),
                        'returncode': getattr(exc, 'returncode', None),
                        'stderr': getattr(exc, 'stderr', None),
                    }, indent=2) + '\n', encoding='utf-8')
                    failure=PreflightRejected(exc.stderr.strip())
                    proofs=[line.split(': ',1)[1] for line in (exc.stderr or '').splitlines() if line.startswith('TCAD_PREFLIGHT_NOT_LAUNCHED: ')]
                    if len(proofs)==1:
                        proof=json.loads(proofs[0])
                        value=json.loads(diag_path.read_text())
                        value.update(schema='tcad-original-preflight-receipt-r1',remote_proof=proof,
                            connection_identity=connection_identity(cfg),input_sha256=inputs,runner_sha256=evidence['runner_sha256'])
                        diag_path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
                        failure.receipt=dict(path=str(diag_path),sha256=file_hash(diag_path))
                    if active_dir == staging:
                        shutil.rmtree(staging)
                    elif hasattr(failure, 'receipt'):
                        evidence.update(state='FAILED_BEFORE_LAUNCH', preflight_receipt=failure.receipt)
                        save()
                    raise failure from exc
                raise
        if active_dir == staging:
            staging.rename(local)
            active_dir = local
            archive = local / 'inputs.tar'
        if release_launch_owner is not None:
            release_launch_owner()
    except ReservationBusy as exc:
        retain_busy_attempt(active_dir, run_id, exc)
        raise
    except PreflightRejected:
        raise
    except BaseException as exc:
        if active_dir == local:
            evidence['state'] = 'TRANSFER_OR_CONNECTION_FAILED'
            evidence['transport_error'] = repr(exc)
            if getattr(exc, 'returncode', None) is not None:
                evidence['ssh_exit_code'] = exc.returncode
            save()
        if staging.exists() and not local.exists():
            if reserve_attempted and evidence is not None:
                # A missing or invalid receipt can follow a successful reserve.
                staging.rename(local)
                active_dir = local
                evidence['state'] = 'TRANSFER_OR_CONNECTION_FAILED'
                evidence['transport_error'] = repr(exc)
                if getattr(exc, 'returncode', None) is not None:
                    evidence['ssh_exit_code'] = exc.returncode
                save()
            else:
                shutil.rmtree(staging, ignore_errors=True)
        raise
    try:
        if data_root is None:
            remote(ssh, 'umask 077; mkdir -p ' + shlex.quote(cfg['remote_root'] + '/runs') + '; mkdir ' + qdir, timeout=30)
        else:
            evidence['data_root_observation']=create_data_root_run(cfg,ssh,data_root,run_id)
            save()
        with archive.open('rb') as stream:
            remote(ssh, 'tar -xf - -C ' + qdir, stdin=stream, timeout=120)
        remote(ssh, 'cat > ' + qdir + '/run.sh', input=script.encode(), timeout=30)
        evidence['state'] = 'STAGED'
        save()
        claim = 'cd ' + qdir + '; mkdir .launch-claim || exit 76; '
        evidence['state'] = 'LAUNCH_REQUESTED'
        save()
        if detach:
            command = claim + 'nohup setsid bash ./run.sh </dev/null >launch.log 2>&1 &'
            # A subshell prevents the shell grammar from backgrounding mkdir itself.
            command = 'cd ' + qdir + '; mkdir .launch-claim || exit 76; (nohup setsid bash ./run.sh </dev/null >launch.log 2>&1 & echo $! > launch-pid.txt)'
            result = subprocess.run(remote_argv(ssh, command), capture_output=True, timeout=30)
            (local/'launch.stdout').write_bytes(result.stdout)
            (local/'launch.stderr').write_bytes(result.stderr)
            evidence['ssh_exit_code'] = result.returncode
            evidence['state'] = 'RUNNING' if result.returncode == 0 else 'LAUNCH_UNCERTAIN'
        else:
            with (local/'console.log').open('wb') as console:
                result = subprocess.run(remote_argv(ssh, claim + 'exec setsid bash ./run.sh'), stdout=console, stderr=subprocess.STDOUT)
            evidence['ssh_exit_code'] = result.returncode
            evidence['state'] = 'EXECUTED' if result.returncode == 0 else 'FAILED_OR_DISCONNECTED'
        save()
    except BaseException as exc:
        evidence['state'] = 'TRANSFER_OR_CONNECTION_FAILED'
        evidence['transport_error'] = repr(exc)
        if getattr(exc, 'returncode', None) is not None:
            evidence['ssh_exit_code'] = exc.returncode
        save()
        raise
    if detach:
        return status_run(cfg, ssh, run_id)
    observed = status_run(cfg, ssh, run_id)
    if observed['status'] == 'FINISHED':
        return collect_run(cfg, ssh, run_id)
    return observed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection', type=Path, help='Explicit connection profile; default VMware profile is unchanged')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor')
    sub.add_parser('shell')
    run=sub.add_parser('run')
    run.add_argument('project',type=Path)
    run.add_argument('--run-id')
    run.add_argument('--detach',action='store_true')
    run.add_argument('--staged-launch',action='store_true',
                     help='Release local scheduling ownership after a detached parallel reservation')
    run.add_argument('--data-root',help='Optional canonical remote data directory for new runs; control root and shared lock stay unchanged')
    run.add_argument('--parallel-slot', type=int, choices=range(PARALLEL_MAX_CAPACITY),
                     help='Explicit NEW cloud execution slot; default remains original serial runner')
    cancel=sub.add_parser('cancel')
    cancel.add_argument('run_id')
    cancel.add_argument('--reason',required=True)
    cancel.add_argument('--grace-seconds',type=int,default=15)
    cancel.add_argument('--requested-by',default='operator')
    cancel.add_argument('--json',action='store_true')
    for name in ('status','collect','seal'):
        item=sub.add_parser(name)
        item.add_argument('run_id')
        item.add_argument('--json',action='store_true')
        if name=='collect':
            item.add_argument('--interrupted',action='store_true',
                help='Collect original evidence only after a proven boot change; never infer a successful exit')
    args=parser.parse_args()
    if args.connection is not None:
        select_connection(args.connection)
    if args.command=='run':
        if args.data_root is not None:args.data_root=normalize_data_root(args.data_root)
        project=args.project.resolve()
        spec=json.loads((project/'project.json').read_text(encoding='utf-8'))
        requested=args.run_id or spec.get('s2_geometry',{}).get('run_id')
        if requested:validate_run_id(requested)
        if not (requested and run_folder(requested).exists()) and 's2_geometry' in spec:
            geometry_module().geometry_admit(project,spec,file_hash(Path(__file__)))
    cfg,ssh,ip=connection()
    if args.command=='doctor':doctor(cfg,ssh,ip)
    elif args.command=='shell':
        if getattr(ssh, 'runtime_entry', None):
            execute(list(ssh[:-1])+['-t',ssh[-1], 'bash -lc ' + shlex.quote('exec ' + shlex.quote(ssh.runtime_entry) + ' /bin/bash -l')])
        else:
            execute(ssh[:-1]+['-t',ssh[-1]])
    elif args.command=='run':
        try:
            result=run_project(cfg,ssh,args.project,args.run_id,args.detach,data_root=args.data_root,
                               staged_launch=args.staged_launch,
                               **({'parallel_slot': args.parallel_slot} if args.parallel_slot is not None else {}))
        except ReservationBusy as exc:
            print(json.dumps(exc.payload()), flush=True)
            return RESERVATION_BUSY_EXIT_CODE
        print(json.dumps(result,indent=2))
    elif args.command=='seal':
        print(json.dumps(seal_run(cfg,ssh,args.run_id),indent=2))
    elif args.command=='collect':
        with collection_owner(run_folder(args.run_id), 'manifest.json'):
            result=collect_run(cfg,ssh,args.run_id,interrupted=args.interrupted)
        print(json.dumps(result,indent=2))
    else:
        with original_ownership(), record_writer(run_folder(args.run_id)):
            if args.command=='cancel':
                result=cancel_run(cfg,ssh,args.run_id,args.reason,args.grace_seconds,args.requested_by)
            else:
                result=status_run(cfg,ssh,args.run_id)
        print(json.dumps(result,indent=2))


if __name__=='__main__':
    try:sys.exit(main())
    except PreflightRejected as exc:
        print('PREFLIGHT_REJECTED:',exc,file=sys.stderr)
        if getattr(exc,'receipt',None):print(json.dumps(dict(status='ORIGINAL_PREFLIGHT_REJECTED',receipt=exc.receipt)),flush=True)
        if getattr(exc,'stderr',None):print(exc.stderr,file=sys.stderr)
        sys.exit(PREFLIGHT_EXIT_CODE)
    except (OSError,ValueError,RuntimeError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
        print('ERROR:',exc,file=sys.stderr)
        if getattr(exc,'stderr',None):print(exc.stderr,file=sys.stderr)
        sys.exit(1)
