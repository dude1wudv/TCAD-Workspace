"""Build unapplied capture review patches for the two existing execution entries.

Only source text, ASTs, and hashes are handled here. No candidate code, shell,
runner, SSH, native tool, or patch-application command is executed.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CAPTURE_ROOT = ROOT / "local_runtime/dram-see-v4/s2-evidence-r1/20261016T123650Z/capture"
SOURCES = {
    "scripts/tcad.py": "8a08d895d788f053da8d07cc29dd7c745ede9b5f3b29b757ad012ca79f7779d5",
    "experiments/dram-see-v4/transport-probe/operation.py":
        "55d4b650b047be490a1aeb6b5c6d97c833e9bcab3c7ccbfc17ce7ee53c930d1b",
}


# This text is embedded in the existing runner's generated run.sh by the review
# candidate. It is not written as a separately executable helper or runner.
CAPTURE_SHELL = r'''capture_observe() {
  taskset -c "$cpu" /usr/bin/python3 - "$1" "$2" "$3" "$4" "$5" <<'S2_CAPTURE_PROC_PY'
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

tool, root_text, parent_text, prefix, installation = sys.argv[1:]
root_pid, wrapper_pid = int(root_text), int(parent_text)
if not re.fullmatch(r'(?:(?:step-[0-9]+-)?(?:sde|snmesh|sdevice|svisual)|metadata-sdevice-version)', prefix):
    raise ValueError('Invalid capture evidence prefix')
if tool not in ('sde', 'snmesh', 'sdevice', 'svisual'):
    raise ValueError('Unknown native capture target')
status_file = Path(prefix + '-process-status.txt')
record_file = Path(prefix + '-process-observation.json')
if status_file.exists() or record_file.exists():
    print('CAPTURE_EVIDENCE_ALREADY_EXISTS ' + prefix, file=sys.stderr)
    raise SystemExit(3)
if not os.path.isabs(installation) or os.path.realpath(installation) == '/':
    raise ValueError('A specific absolute native installation root is required')
installation = os.path.realpath(installation).rstrip('/')
record = dict(schema='native-process-observation-r1', origin='native_pipeline',
              synthetic=False, requested_tool=tool, root_child_pid=root_pid,
              wrapper_pid=wrapper_pid, installation_root=installation,
              status='UNAVAILABLE', reason='NO_EXACT_NATIVE_IDENTITY_WITHIN_WINDOW',
              maximum_observation_s=2.0, no_kill_or_retry=True)

def read_process(pid):
    base = Path('/proc') / str(pid)
    stat_text = (base / 'stat').read_text()
    rest = stat_text.rsplit(')', 1)[1].split()
    start_ticks = int(rest[19])
    raw = (base / 'status').read_text()
    fields = dict(line.split(':', 1) for line in raw.splitlines() if ':' in line)
    identity = dict(pid=pid, ppid=int(fields['PPid'].strip()), start_ticks=start_ticks,
                    name=fields['Name'].strip())
    children_text = (base / 'task' / str(pid) / 'children').read_text()
    children = [int(item) for item in children_text.split()]
    return identity, raw, children

def exact_native(pid, identity):
    if identity['name'] != tool:
        return None
    executable = os.readlink('/proc/{}/exe'.format(pid))
    if executable.endswith(' (deleted)') or Path(executable).name != tool:
        return None
    if not executable.startswith(installation + '/'):
        return None
    with open('/proc/{}/exe'.format(pid), 'rb') as stream:
        if stream.read(4) != b'\x7fELF':
            return None
    return executable

def same_identity(expected):
    observed, _, _ = read_process(expected['pid'])
    return all(observed[key] == expected[key] for key in ('pid', 'ppid', 'start_ticks'))

deadline = time.monotonic() + 2.0
initial_root = None
while time.monotonic() < deadline:
    try:
        root_identity, root_status, root_children = read_process(root_pid)
        if root_identity['ppid'] != wrapper_pid:
            record['reason'] = 'ROOT_NO_LONGER_CHILD_OF_WRAPPER'
            break
        if initial_root is None:
            initial_root = root_identity
        elif any(root_identity[key] != initial_root[key] for key in ('pid', 'ppid', 'start_ticks')):
            record['reason'] = 'ROOT_PROCESS_IDENTITY_CHANGED'
            break
        queue = [(root_identity, root_status, root_children, [root_identity])]
        seen, matches = set(), []
        while queue:
            identity, raw, children, chain = queue.pop(0)
            pid = identity['pid']
            if pid in seen:
                continue
            seen.add(pid)
            if len(seen) > 128:
                raise ValueError('DESCENDANT_TREE_TOO_LARGE')
            try:
                executable = exact_native(pid, identity)
                if executable:
                    matches.append((identity, raw, executable, chain))
            except (OSError, ValueError, KeyError):
                pass
            for child_pid in children:
                try:
                    child, child_raw, descendants = read_process(child_pid)
                    if child['ppid'] == pid:
                        queue.append((child, child_raw, descendants, chain + [child]))
                except (OSError, ValueError, KeyError, IndexError):
                    pass
        if len(matches) > 1:
            record.update(status='AMBIGUOUS', reason='MULTIPLE_EXACT_NATIVE_DESCENDANTS',
                          candidates=[dict(pid=item[0]['pid'], executable=item[2],
                                           parent_chain=item[3]) for item in matches])
            break
        if len(matches) == 1:
            identity, raw, executable, chain = matches[0]
            if not all(same_identity(node) for node in chain):
                record['reason'] = 'ANCESTRY_CHANGED_DURING_OBSERVATION'
                break
            observed, raw_after, _ = read_process(identity['pid'])
            if observed != identity or exact_native(identity['pid'], observed) != executable:
                record['reason'] = 'NATIVE_IDENTITY_CHANGED_DURING_OBSERVATION'
                break
            # Preserve the target process's actual kernel status, including a
            # violating thread/CPU value. The evidence consumer decides gates.
            with status_file.open('x', encoding='utf-8', newline='') as stream:
                stream.write(raw_after)
            fields = dict(line.split(':', 1) for line in raw_after.splitlines() if ':' in line)
            record.update(status='OBSERVED', reason=None, native_pid=identity['pid'],
                          native_executable=executable, native_start_ticks=identity['start_ticks'],
                          parent_chain=chain, status_source='/proc/{}/status'.format(identity['pid']),
                          status_file=status_file.name,
                          status_sha256=hashlib.sha256(raw_after.encode()).hexdigest(),
                          observed_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                          observed_threads=fields['Threads'].strip(),
                          observed_cpus_allowed_list=fields['Cpus_allowed_list'].strip(),
                          observation_scope='single actual native process snapshot; not whole-run proof')
            break
    except (OSError, ValueError, KeyError, IndexError) as exc:
        record['last_observation_error'] = type(exc).__name__ + ': ' + str(exc)
    time.sleep(0.05)
if initial_root is not None:
    record['root_identity'] = initial_root
with record_file.open('x', encoding='utf-8') as stream:
    json.dump(record, stream, indent=2)
    stream.write('\n')
print('CAPTURE_PROCESS_' + record['status'] + ' ' + prefix)
S2_CAPTURE_PROC_PY
}
capture_admit() {
  taskset -c "$cpu" /usr/bin/python3 - "$1" "$2" "$cpu" <<'S2_CAPTURE_ADMIT_PY'
import hashlib
import json
from pathlib import Path
import re
import sys

prefix, tool, requested_cpu = sys.argv[1:]
report_path = Path(prefix + '-process-admission.json')
if report_path.exists():
    raise ValueError('Never overwrite process admission evidence')
errors = []
try:
    observation = json.loads(Path(prefix + '-process-observation.json').read_text())
    status_raw = Path(prefix + '-process-status.txt').read_bytes()
    status = status_raw.decode('utf-8')
    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
    if observation.get('status') != 'OBSERVED':
        errors.append('Native identity was missing or ambiguous')
    if observation.get('requested_tool') != tool or fields.get('Name', '').strip() != tool:
        errors.append('Native tool identity differs')
    if str(observation.get('native_pid')) != fields.get('Pid', '').strip():
        errors.append('Observed native PID differs from raw status')
    if hashlib.sha256(status_raw).hexdigest() != observation.get('status_sha256'):
        errors.append('Raw process status hash differs')
    if fields.get('Threads', '').strip() != '1':
        errors.append('Actual native process Threads is not 1')
    cpu_value = fields.get('Cpus_allowed_list', '').strip()
    if re.fullmatch(r'[0-9]+', cpu_value) is None or cpu_value != requested_cpu:
        errors.append('Actual native CPU is not the single taskset CPU')
except (OSError, ValueError, KeyError, TypeError) as exc:
    errors.append(type(exc).__name__ + ': ' + str(exc))
report = dict(schema='native-process-admission-r1', origin='native_pipeline', synthetic=False,
              requested_tool=tool, requested_cpu=requested_cpu,
              status='FAILED' if errors else 'PASSED', errors=errors,
              scope='capture admission only; not scientific acceptance',
              actual_native_exit_is_separate=True)
with report_path.open('x', encoding='utf-8') as stream:
    json.dump(report, stream, indent=2)
    stream.write('\n')
print('CAPTURE_ADMISSION_' + report['status'] + ' ' + prefix)
raise SystemExit(86 if errors else 0)
S2_CAPTURE_ADMIT_PY
}
capture_native_step() {
  local capture_prefix="$1" capture_tool="$2" capture_installation="$3"
  shift 3
  taskset -c "$cpu" "$@" &
  local capture_child_pid=$!
  if [ "$capture_prefix" != metadata-sdevice-version ]; then
    capture_observe "$capture_tool" "$capture_child_pid" "$$" "$capture_prefix" "$capture_installation" || true
  fi
  set +e
  wait "$capture_child_pid"
  local capture_child_rc=$?
  set -e
  printf '%s\n' "$capture_child_rc" > "$capture_prefix-exit-code.txt"
  if [ "$capture_child_rc" -ne 0 ] || [ "$capture_prefix" = metadata-sdevice-version ]; then
    return "$capture_child_rc"
  fi
  set +e
  capture_admit "$capture_prefix" "$capture_tool"
  local capture_admission_rc=$?
  set -e
  printf '%s\n' "$capture_admission_rc" > "$capture_prefix-process-admission-exit-code.txt"
  return "$capture_admission_rc"
}'''


ARCHIVE_EXIT_HELPER = '''def capture_archive_exit_codes(archive_path, names):
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
            if re.fullmatch(rb'[0-9]+\\s*', raw) is None or not 0 <= int(raw) <= 255:
                errors[name] = 'invalid raw POSIX exit code'
                continue
            values[name] = int(raw)
    return values, errors


'''


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Frozen source anchor is missing or ambiguous: " + old[:100])
    return source.replace(old, new, 1)


def _helper_source():
    lines = "\n".join("        " + repr(line) + "," for line in CAPTURE_SHELL.splitlines())
    return ("def native_capture_shell_lines():\n"
            '    """Existing-wrapper only: bounded exact-child /proc capture; never retry tools."""\n'
            "    return [\n" + lines + "\n    ]\n\n\n" + ARCHIVE_EXIT_HELPER)


def _tcad_candidate(source):
    candidate = _replace_once(source, "def run_project(cfg, ssh, project):\n",
                              _helper_source() + "def run_project(cfg, ssh, project):\n")
    candidate = _replace_once(candidate,
        "    evidence = {'run_id': run_id, 'commit': commit, 'input_sha256': inputs,\n",
        "    evidence = {'run_id': run_id, 'commit': commit, 'input_sha256': inputs,\n"
        "                'origin': 'native_pipeline', 'synthetic': False,\n"
        "                'ssh_exit_code': None, 'remote_exit_code': None, 'collection_exit_code': None,\n"
        "                'version_probe_exit_code': None,\n"
        "                'tool_exit_codes': {}, 'tool_evidence': {},\n")
    old = "              'flock -n 9 || { echo \"Another project run holds the solver lock\" >&2; exit 75; }',\n"
    new = old + "              \"printf 'status=ACQUIRED\\nfd=9\\nlock_path=%s\\npid=%s\\nacquired_utc=%s\\n' \"\n" \
        + "              + shlex.quote(cfg['remote_root'].rstrip('/') + '/.solver.lock')\n" \
        + "              + ' \"$$\" \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > shared-lock-evidence.txt',\n"
    candidate = _replace_once(candidate, old, new)
    old = "              'date -u; hostname; sdevice -v; taskset -pc $$']\n"
    new = "              'date -u; hostname']\n" \
        + "    runner += native_capture_shell_lines()\n" \
        + "    capture_installation = cfg['tool_bin'].rstrip('/').rsplit('/', 1)[0]\n" \
        + "    runner += ['capture_native_step metadata-sdevice-version sdevice '\n" \
        + "               + shlex.quote(capture_installation) + ' sdevice -v', 'taskset -pc $$']\n"
    candidate = _replace_once(candidate, old, new)
    old = "        runner += ['echo ' + shlex.quote('STEP ' + str(index) + ': ' + shlex.join(args)),\n" \
        + "                   'taskset -c \"$cpu\" ' + shlex.join(args)]\n"
    new = "        capture_key = 'step-{:03d}-{}'.format(index, step['tool'])\n" \
        + "        evidence['tool_exit_codes'][capture_key] = None\n" \
        + "        evidence['tool_evidence'][capture_key] = {\n" \
        + "            'step_index': index, 'tool': step['tool'],\n" \
        + "            'raw_exit_file': capture_key + '-exit-code.txt',\n" \
        + "            'process_status_file': capture_key + '-process-status.txt',\n" \
        + "            'process_observation_file': capture_key + '-process-observation.json',\n" \
        + "            'process_admission_file': capture_key + '-process-admission.json',\n" \
        + "            'raw_process_admission_exit_file': capture_key + '-process-admission-exit-code.txt'}\n" \
        + "        runner += ['echo ' + shlex.quote('STEP ' + str(index) + ': ' + shlex.join(args)),\n" \
        + "                   'capture_native_step ' + shlex.join([capture_key, step['tool'], capture_installation])\n" \
        + "                   + ' ' + shlex.join(args)]\n"
    candidate = _replace_once(candidate, old, new)
    old = "    with (local / 'results.tar').open('wb') as stream:\n" \
        + "        remote(ssh, 'tar -cf - -C ' + qdir + ' .', stdout=stream, timeout=300)\n" \
        + "    evidence['results_sha256'] = file_hash(local / 'results.tar')\n" \
        + "    evidence['state'] = 'COLLECTED' if result.returncode == 0 else 'FAILED_COLLECTED'\n" \
        + "    save()\n"
    new = "    try:\n" \
        + "        with (local / 'results.tar').open('wb') as stream:\n" \
        + "            collection = remote(ssh, 'tar -cf - -C ' + qdir + ' .', stdout=stream, timeout=300)\n" \
        + "        evidence['collection_exit_code'] = collection.returncode\n" \
        + "        evidence['results_sha256'] = file_hash(local / 'results.tar')\n" \
        + "        names = ['exit-code.txt', 'metadata-sdevice-version-exit-code.txt'] + [item['raw_exit_file'] for item in evidence['tool_evidence'].values()]\n" \
        + "        raw_exits, exit_errors = capture_archive_exit_codes(local / 'results.tar', names)\n" \
        + "        evidence['remote_exit_code'] = raw_exits['exit-code.txt']\n" \
        + "        evidence['version_probe_exit_code'] = raw_exits['metadata-sdevice-version-exit-code.txt']\n" \
        + "        for key, item in evidence['tool_evidence'].items():\n" \
        + "            evidence['tool_exit_codes'][key] = raw_exits[item['raw_exit_file']]\n" \
        + "        evidence['capture_exit_errors'] = exit_errors\n" \
        + "        evidence['state'] = 'COLLECTED' if result.returncode == 0 else 'FAILED_COLLECTED'\n" \
        + "    except Exception as exc:\n" \
        + "        actual_rc = getattr(exc, 'returncode', None)\n" \
        + "        if type(actual_rc) is int:\n" \
        + "            evidence['collection_exit_code'] = actual_rc\n" \
        + "        evidence['collection_error'] = repr(exc)\n" \
        + "        raise\n" \
        + "    finally:\n" \
        + "        save()\n"
    return _replace_once(candidate, old, new)


def _operation_candidate(source):
    candidate = _replace_once(source,
        "    record = {'schema': 'dram-see-v4-transport-operation-v1', 'label': label,\n",
        "    record = {'schema': 'dram-see-v4-transport-operation-v1', 'label': label,\n"
        "              'origin': 'native_pipeline', 'synthetic': False,\n"
        "              'operation_task_exit_code': None, 'tool_exit_codes': {'svisual': None},\n")
    old = "        wrapper = '\\n'.join([\n"
    new = "        capture_installation = cfg['tool_bin'].rstrip('/').rsplit('/', 1)[0]\n" \
        + "        capture_svisual_command = cfg['tool_bin'].rstrip('/') + '/svisual'\n" \
        + "        task_text = (inputs / 'task.sh').read_text(encoding='utf-8')\n" \
        + "        capture_svisual = any(line.lstrip().startswith(prefix + ' ')\n" \
        + "                              for line in task_text.splitlines()\n" \
        + "                              for prefix in (capture_svisual_command, shlex.quote(capture_svisual_command)))\n" \
        + "        record['capture_svisual_requested'] = capture_svisual\n" \
        + "        wrapper = '\\n'.join([\n"
    candidate = _replace_once(candidate, old, new)
    old = "            'flock -n 9 || { echo SHARED_SOLVER_LOCK_BUSY; exit 75; }',\n"
    new = old + "            \"printf 'status=ACQUIRED\\nfd=9\\nlock_path=%s\\npid=%s\\nacquired_utc=%s\\n' \"\n" \
        + "            + shlex.quote(base + '/.solver.lock')\n" \
        + "            + ' \"$$\" \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > shared-lock-evidence.txt',\n"
    candidate = _replace_once(candidate, old, new)
    old = "            'bash task.sh', 'echo V4_OPERATION_COMPLETED',\n" \
        + "        ]) + '\\n'\n"
    new = "        ] + tcad.native_capture_shell_lines() + [\n" \
        + "            'bash task.sh &', 'operation_task_pid=$!',\n" \
        + "            ('capture_observe svisual \"$operation_task_pid\" \"$$\" svisual ' + shlex.quote(capture_installation) + ' || true')\n" \
        + "                if capture_svisual else ': # No exact SVisual command recognized; no native PID inferred.',\n" \
        + "            'set +e', 'wait \"$operation_task_pid\"', 'operation_task_rc=$?', 'set -e',\n" \
        + "            \"printf '%s\\\\n' \\\"$operation_task_rc\\\" > operation-task-exit-code.txt\",\n" \
        + "            'if [ \"$operation_task_rc\" -ne 0 ]; then exit \"$operation_task_rc\"; fi', 'echo V4_OPERATION_COMPLETED',\n" \
        + "        ]) + '\\n'\n"
    candidate = _replace_once(candidate, old, new)
    old = "                    if record['ssh_exit_code'] == 0 and record['remote_exit_code'] == 0:\n"
    new = "                    raw_exits, exit_errors = tcad.capture_archive_exit_codes(\n" \
        + "                        folder / 'results.tar', ['operation-task-exit-code.txt', 'svisual-exit-code.txt'])\n" \
        + "                    record['operation_task_exit_code'] = raw_exits['operation-task-exit-code.txt']\n" \
        + "                    record['tool_exit_codes']['svisual'] = raw_exits['svisual-exit-code.txt']\n" \
        + "                    record['capture_exit_errors'] = exit_errors\n" + old
    candidate = _replace_once(candidate, old, new)
    old = "            except Exception as exc:\n" \
        + "                record['collection_error'] = repr(exc)\n"
    new = "            except Exception as exc:\n" \
        + "                actual_rc = getattr(exc, 'returncode', None)\n" \
        + "                if type(actual_rc) is int:\n" \
        + "                    record['collection_exit_code'] = actual_rc\n" \
        + "                record['collection_error'] = repr(exc)\n"
    return _replace_once(candidate, old, new)


def _function_ast(tree, name):
    matches = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    if len(matches) != 1:
        raise ValueError("Expected exactly one function: " + name)
    return ast.dump(matches[0], include_attributes=False)


def _parse_report(path, source, candidate):
    source_tree = ast.parse(source, filename=path)
    candidate_tree = ast.parse(candidate, filename=path + ".review")
    compile(candidate_tree, path + ".review", "exec")  # Compilation only; never exec.
    facts = {"python_ast_parse": True, "python_ast_compile_only": True,
             "candidate_executed": False, "native_calls": 0, "patch_applied": False}
    if path == "scripts/tcad.py":
        unchanged = ("connection", "remote", "execute", "doctor", "main")
        facts["unchanged_function_asts"] = {name: _function_ast(source_tree, name) == _function_ast(candidate_tree, name) for name in unchanged}
        facts["sdevice_thread_flags_retained"] = "args += ['--threads', '1', '--exit-on-failure']" in candidate
        facts["step_output_validation_retained"] = "runner += ['test -s ' + shlex.quote(out) for out in step['outputs']]" in candidate
        facts["collection_rc_from_return"] = "evidence['collection_exit_code'] = collection.returncode" in candidate
        facts["collection_rc_preserved_on_exception"] = "evidence['collection_exit_code'] = actual_rc" in candidate
        facts["step_exit_values_initialized_unknown"] = "evidence['tool_exit_codes'][capture_key] = None" in candidate
        facts["existing_version_probe_recorded_without_new_call"] = " + ' sdevice -v', 'taskset -pc $$']" in candidate and "evidence['version_probe_exit_code'] = raw_exits['metadata-sdevice-version-exit-code.txt']" in candidate
    else:
        facts["task_script_not_rewritten"] = "(inputs / 'task.sh').read_text" in candidate and "(inputs / 'task.sh').write_text" not in candidate
        facts["existing_task_child_waited"] = "'bash task.sh &'" in candidate and "'wait \"$operation_task_pid\"'" in candidate
        facts["task_nonzero_wait_rc_propagated_unchanged"] = 'then exit "$operation_task_rc"; fi' in candidate
        facts["svisual_raw_exit_only"] = "record['tool_exit_codes']['svisual'] = raw_exits['svisual-exit-code.txt']" in candidate
        facts["collection_rc_from_return_retained"] = "record['collection_exit_code'] = result.returncode" in candidate
        facts["shared_helper_in_existing_tcad_entry"] = "tcad.native_capture_shell_lines()" in candidate
    facts["origin_is_only_future_runtime_record"] = "'origin': 'native_pipeline', 'synthetic': False" in candidate
    facts["shared_lock_preserved"] = "flock -n 9" in candidate and "shared-lock-evidence.txt" in candidate
    facts["no_apply_or_retry_added"] = "automatic_retry': False" in candidate if path.endswith("operation.py") else True
    false_keys = [key for key, value in facts.items() if value is False and key not in {"candidate_executed", "patch_applied"}]
    if false_keys or not all(facts.get("unchanged_function_asts", {}).values()):
        raise ValueError("Candidate preservation checks failed: " + repr(false_keys))
    return facts


def _observer_report():
    code = CAPTURE_SHELL.split("<<'S2_CAPTURE_PROC_PY'\n", 1)[1].split("\nS2_CAPTURE_PROC_PY", 1)[0]
    tree = ast.parse(code, filename="embedded-readonly-proc-observer.review")
    compile(tree, "embedded-readonly-proc-observer.review", "exec")
    admission_code = CAPTURE_SHELL.split("<<'S2_CAPTURE_ADMIT_PY'\n", 1)[1].split("\nS2_CAPTURE_ADMIT_PY", 1)[0]
    admission_tree = ast.parse(admission_code, filename="embedded-process-admission.review")
    compile(admission_tree, "embedded-process-admission.review", "exec")
    facts = {"embedded_python_ast_parse_compile_only": True,
             "elf_magic_is_four_actual_bytes": any(isinstance(node, ast.Constant) and node.value == b'\x7fELF' for node in ast.walk(tree)),
             "exact_child_descendants_only": "'children'" in code and "child['ppid'] == pid" in code,
             "root_parent_and_start_identity_checked": "root_identity['ppid'] != wrapper_pid" in code and "root_identity[key] != initial_root[key]" in code,
             "exact_tool_name_elf_and_install_root": "identity['name'] != tool" in code and "Path(executable).name != tool" in code and "b'\\x7fELF'" in code,
             "multiple_matches_are_ambiguous": "if len(matches) > 1:" in code and "status='AMBIGUOUS'" in code,
             "raw_native_proc_status_preserved": "stream.write(raw_after)" in code,
             "native_pid_exe_and_chain_recorded": all(x in code for x in ("native_pid=", "native_executable=", "parent_chain=chain")),
             "no_kill_pgrep_or_native_launch_in_observer": not any(x in code for x in ("pgrep", "os.kill", "subprocess", "Popen", "os.system")),
             "native_step_wait_actual_rc": 'wait "$capture_child_pid"\n  local capture_child_rc=$?' in CAPTURE_SHELL,
             "observer_failure_does_not_skip_wait": '|| true\n  fi\n  set +e\n  wait "$capture_child_pid"' in CAPTURE_SHELL,
             "admission_after_wait_and_actual_native_exit_write": CAPTURE_SHELL.index('wait "$capture_child_pid"') < CAPTURE_SHELL.index('> "$capture_prefix-exit-code.txt"') < CAPTURE_SHELL.index('capture_admit "$capture_prefix" "$capture_tool"'),
             "admission_exit_separate_from_native_exit": 'return "$capture_admission_rc"' in CAPTURE_SHELL and "raise SystemExit(86 if errors else 0)" in admission_code,
             "original_version_probe_no_pid_admission": '[ "$capture_prefix" = metadata-sdevice-version ]' in CAPTURE_SHELL,
             "admission_requires_actual_one_thread_and_requested_single_cpu": "fields.get('Threads', '').strip() != '1'" in admission_code and "cpu_value != requested_cpu" in admission_code,
             "shell_syntax_or_runtime_not_executed": True}
    if not all(facts.values()):
        raise ValueError("Observer static checks failed: " + repr(facts))
    return facts


def build_patches(output: Path) -> dict:
    """Write only new .review.patch files and their offline provenance report."""
    output = Path(output).resolve()
    allowed = CAPTURE_ROOT.resolve()
    if output != allowed and not output.is_relative_to(allowed):
        raise ValueError("Capture output must remain within this task's runtime/capture")
    if output.exists():
        raise FileExistsError("Never overwrite a capture review package")
    originals = {}
    for name, expected in SOURCES.items():
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing or linked frozen source: " + name)
        raw = path.read_bytes()
        if _sha(raw) != expected:
            raise ValueError("Source SHA-256 differs; no patch generated: " + name)
        originals[name] = raw.decode("utf-8")
    builders = {"scripts/tcad.py": _tcad_candidate,
                "experiments/dram-see-v4/transport-probe/operation.py": _operation_candidate}
    payloads, entries = {}, []
    for name, source in originals.items():
        candidate = builders[name](source)
        report = _parse_report(name, source, candidate)
        patch = "".join(difflib.unified_diff(source.splitlines(keepends=True), candidate.splitlines(keepends=True),
                                             fromfile="a/"+name, tofile="b/"+name, n=3))
        if not patch:
            raise ValueError("Empty review patch")
        filename = Path(name).stem + ".review.patch"
        payloads[filename] = patch.encode("utf-8")
        entries.append({"source_path": name, "source_sha256": SOURCES[name],
                        "source_bytes": len(source.encode()), "candidate_sha256": _sha(candidate.encode()),
                        "candidate_bytes": len(candidate.encode()), "patch_file": filename,
                        "patch_sha256": _sha(payloads[filename]), "parse_and_preservation": report})
    report = {"schema": "s2-native-capture-patch-candidate-r1", "origin": "patch_candidate",
              "status": "UNAPPLIED_REVIEW_ONLY", "execution_enabled": False,
              "patches_applied": False, "native_calls": 0, "candidate_code_executed": False,
              "generator_sha256": _sha(Path(__file__).read_bytes()), "entries": entries,
              "observer_static_review": _observer_report(),
              "deployment_dependency": "Both review patches require one separately authorized reviewed release; operation uses tcad helper.",
              "unverified": ["bash syntax and runtime", "vendor launcher/native identity and descendant behavior",
                             "actual native /proc observation timing", "actual native exit capture and archive exception paths",
                             "short or delayed tools may remain unobserved", "actual post-wait admission blocking of downstream steps",
                             "no whole-run CPU/thread sampling proof"],
              "no_second_runner_written": True, "native_receipts_created": 0}
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        (output/name).write_bytes(raw)
    (output/"capture-patch-report.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    # A concurrent source edit invalidates the complete package instead of
    # silently accepting a diff against a moving baseline.
    if any(_sha((ROOT/name).read_bytes()) != expected for name, expected in SOURCES.items()):
        raise RuntimeError("Frozen source changed during patch generation; candidate is not releasable")
    return report
