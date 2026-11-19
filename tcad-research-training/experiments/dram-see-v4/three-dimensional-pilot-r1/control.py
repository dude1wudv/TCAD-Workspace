"""Budgeted pilot dispatch through the existing runners, never an auto retry loop."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import msvcrt
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
V4 = HERE.parent
RT = ROOT / 'local_runtime/dram-see-v4'
STATE = RT / 'three-dimensional-pilot-r1'
OLD = RT / 'interface-completion-r1'
GiB = 2 ** 30


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(part)
    return digest.hexdigest()


def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def utc():
    return datetime.now(timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    sys.modules[name] = obj
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), obj.__dict__)
    return obj


def save(path, value, new=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if new:
        with path.open('x', encoding='utf-8') as stream:
            stream.write(text)
    else:
        temp = path.with_suffix('.tmp')
        temp.write_text(text, encoding='utf-8')
        temp.replace(path)


def reference(path):
    return dict(path=rel(path), sha256=sha(path))


@contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def check_release():
    path = HERE / 'release.json'
    require(path.is_file(), 'Pilot implementation has not been independently verified and frozen')
    value = read(path)
    require(value.get('passed') is True, 'Pilot implementation release is not passed')
    for name, digest in value['files_sha256'].items():
        require(sha(ROOT / name) == digest, 'Frozen pilot file changed: ' + name)
    for item in value['validation_evidence']:
        require(sha(ROOT / item['path']) == item['sha256'], 'Validation evidence changed')
        require(read(ROOT / item['path']).get('passed') is True, 'Validation did not pass')
    module(V4 / 'interface-completion-r1/campaign_runner.py', '_pilot_old_release').check_release()
    return reference(path)


def old_queue_gate():
    """Must be called while holding the old scheduler lock; no state mutation."""
    runner = module(V4 / 'interface-completion-r1/campaign_runner.py', '_pilot_old_state')
    status = read(OLD / 'coordination.json')
    require(not runner.pid_alive(status['scheduler_pid']), 'Old scheduler still alive; pilot remains waiting')
    require(status['state'] == 'ALL_PRIMARY_ROLES_PASSED',
            'Old 2D queue has not fully passed; diagnose before explicitly releasing dependent 3D work')
    gates = module(V4 / 'interface-completion-r1/control.py', '_pilot_old_gates')
    refs = [gates.check_gate(row['role_id']) for row in read(V4 / 'interface-completion-r1/campaign.json')['roles']]
    gates.unresolved_postprocessing()
    for path in (RT / 'source-interface-r5/launches').glob('*/execution.json'):
        record = read(path)
        require(record.get('state') == 'RUNNER_EXITED' and record.get('runner_exit_code') is not None,
                'Previous 2D invocation unresolved: ' + rel(path))
        if record['runner_exit_code']:
            gates.known_solver_failure(record)
        else:
            require(record.get('runner_manifest_state') == 'COLLECTED' and record.get('ssh_exit_code') == 0,
                    'Previous 2D remote outcome unresolved: ' + rel(path))
    return dict(coordination=reference(OLD / 'coordination.json'), gates=refs)


def prior_calls():
    return [read(p) for p in sorted((STATE / 'calls').glob('*/execution.json'))]


def verify_history(records):
    """Reconcile saved status against original evidence before any new call."""
    for record in records:
        require(record.get('campaign_sha256') == sha(HERE / 'campaign.json'), 'Prior pilot belongs to another contract')
        require(record.get('state') in ('COMPLETED', 'KNOWN_FAILURE'), 'Original pilot call unresolved')
        if record['kind'] == 'tcad':
            run = ROOT / 'local_runtime/runs' / record['run_id']
            manifest = read(run / 'manifest.json')
            require(manifest.get('input_sha256') == record['input_sha256'], 'Prior original input differs')
            if record['state'] == 'COMPLETED':
                require(record.get('runner_exit_code') == manifest.get('ssh_exit_code') == 0 and
                        manifest.get('state') == 'COLLECTED', 'Prior TCAD outcome unknown')
                require(sha(run / 'results.tar') == manifest['results_sha256'] == record['result_archive_sha256'],
                        'Prior TCAD archive changed')
            else:
                module(V4 / 'interface-completion-r1/control.py', '_pilot_verify_failure').known_solver_failure(record)
        else:
            ref = record.get('operation')
            require(ref and sha(ROOT / ref['path']) == ref['sha256'], 'Original operation record changed')
            op = read(ROOT / ref['path'])
            require(op.get('input_sha256') == record['input_sha256'] and op.get('collection_exit_code') == 0,
                    'Original operation input/collection differs')
            require(sha((ROOT / ref['path']).parent / 'results.tar') == op['archive_sha256'], 'Original operation archive changed')
            if record['state'] == 'COMPLETED':
                require(record.get('runner_exit_code') == op.get('remote_exit_code') == op.get('ssh_exit_code') == 0 and
                        op.get('state') == 'COLLECTED_PENDING_AUDIT', 'Original operation outcome unknown')
            else:
                module(V4 / 'interface-completion-r1/campaign_runner.py', '_pilot_verify_operation_failure').known_operation_failure((ROOT / ref['path']).parent)


def validate_budget(records, kind, role, category='primary', repair=None):
    c = read(HERE / 'campaign.json')
    require(kind in ('tcad', 'geant'), 'Unbudgeted kind')
    require(category in ('primary', 'reserve'), 'Unbudgeted category')
    for record in records:
        require(record.get('state') in ('COMPLETED', 'KNOWN_FAILURE'), 'Original pilot call unresolved; do not resubmit')
    subset = [r for r in records if r['kind'] == kind]
    require(len(subset) < c['maximum_tcad_calls' if kind == 'tcad' else 'maximum_geant_calls'], 'Call cap reached')
    allowed = c['primary_tcad_roles'] if kind == 'tcad' else c['geant_request_order']
    require(role in allowed, 'Role is outside the frozen pilot')
    if category == 'primary':
        require(not any(r['role'] == role for r in subset), 'Role already attempted; never silently repeat')
        require(repair is None, 'Primary request cannot use a repair ticket')
    else:
        require(kind == 'tcad', 'Geant reruns require a new contract')
        require(sum(r['category'] == 'reserve' for r in subset) < c['corrective_tcad_calls'], 'Corrective cap reached')
        require(repair and repair.get('role') == role and repair.get('root_cause') and repair.get('repair_description'),
                'Diagnosed repair ticket required')
        require(repair.get('same_root_cause_consecutive_failures') == 1, 'Repeated same-cause failure pauses branch')
        require(repair.get('automatic_retry') is False and repair.get('maximum_additional_calls') == 1,
                'Repair ticket must authorize exactly one deliberate call')
        for field in ('failure_evidence', 'offline_evidence'):
            require(bool(repair.get(field)), 'Repair evidence missing')
            for item in repair[field]:
                require(sha(ROOT / item['path']) == item['sha256'], 'Repair evidence changed')
                if field == 'offline_evidence':
                    require(read(ROOT / item['path']).get('passed') is True, 'Offline repair verification failed')
        require(not any(r.get('repair') == repair for r in subset), 'Repair ticket already consumed')
        require(any(read(ROOT / item['path']).get('passed') is False or
                    read(ROOT / item['path']).get('state') == 'KNOWN_FAILURE' for item in repair['failure_evidence']),
                'No failed evidence justifies correction')
        for prior in subset:
            if (prior.get('repair') or {}).get('root_cause') == repair['root_cause']:
                require(prior['state'] == 'COMPLETED', 'Same root cause failed after repair; pause branch')
                pilot_gate(prior['role'])
    if kind == 'geant':
        n = 0 if role.startswith('init-') else 2
        require(sum(r.get('primary_events', 0) for r in subset) + n <= c['maximum_geant_primary_events'], 'Primary event cap reached')


def pilot_gate(role):
    p = STATE / 'gates' / (role + '.json')
    require(p.is_file(), 'Pilot dependency gate missing: ' + role)
    d = read(p)
    require(d.get('schema') == 'dram-see-v4-3d-pilot-gate-r1' and d.get('passed') is True and d.get('role') == role,
            'Pilot dependency schema/role/status failed')
    require(d.get('campaign_sha256') == sha(HERE / 'campaign.json'), 'Pilot dependency has wrong contract')
    require(isinstance(d.get('evidence'), list) and bool(d['evidence']), 'Pilot dependency has no evidence')
    require(re.fullmatch(r'pilot3d-[a-z0-9-]+', d.get('label', '')) and re.fullmatch(r'[A-Za-z0-9_-]+', d.get('run_id', '')),
            'Pilot dependency label/run identity missing')
    paths = []
    for item in d['evidence']:
        path = (ROOT / item['path']).resolve()
        require(path.is_relative_to(ROOT) and path.is_file() and not path.is_symlink(), 'Invalid pilot evidence path')
        require(sha(path) == item['sha256'], 'Pilot dependency evidence changed')
        paths.append(rel(path))
    require(len(paths) == len(set(paths)), 'Duplicate pilot evidence reference')
    launch = STATE / 'calls' / d['label'] / 'execution.json'
    acceptance = STATE / 'audits' / d['label'] / 'audit.json'
    field = (ROOT / d['field_audit_path']).resolve()
    manifest = ROOT / 'local_runtime/runs' / d['run_id'] / 'manifest.json'
    require(field.is_relative_to(RT / 'source-field-audit-3d-r1'), 'Unexpected pilot field evidence')
    require({rel(x) for x in (launch, acceptance, field, manifest)} <= set(paths), 'Required pilot evidence is not bound')
    call = read(launch); audit = read(acceptance)
    require(call.get('role') == role and call.get('run_id') == d['run_id'] and call.get('label') == d['label'],
            'Pilot gate call identity differs')
    verify_history([call])
    require(audit.get('schema') == 'dram-see-v4-native-3d-pilot-acceptance-r1' and audit.get('passed') is True
            and audit.get('errors') == [] and audit.get('role') == role and audit.get('run_id') == d['run_id'],
            'Pilot acceptance does not match gate')
    require(audit.get('acceptance_code_sha256') == sha(HERE / 'acceptance.py') and audit.get('field_evidence') == reference(field),
            'Pilot acceptance implementation/field binding differs')
    if role == 'a1-b1-3d':
        require(rel(STATE / 'gates/a0-b1-3d.json') in paths, 'A1 gate has no matched A0 binding')
    return reference(p)


def resource_check(label, raw_bytes):
    """Explicit forecast is recorded; no 2D-to-3D timing extrapolation."""
    require(re.fullmatch(r'[a-z0-9-]+', label) and raw_bytes > 0, 'Invalid resource request')
    c = read(HERE / 'campaign.json')
    original = module(V4 / 'interface-completion-r1/resources.py', '_pilot_old_space')
    old_bytes = original.local_new_bytes()
    new_bytes = sum(p.stat().st_size for p in STATE.rglob('*') if p.is_file() and not p.is_symlink())
    for base in [RT / 'source-interface-3d-r1', RT / 'source-field-audit-3d-r1', RT / 'matched-transport-r1']:
        new_bytes += sum(p.stat().st_size for p in base.rglob('*') if p.is_file() and not p.is_symlink())
    for base in (ROOT / 'local_runtime/runs').glob('*-v4-source-interface-3d-*'):
        new_bytes += sum(p.stat().st_size for p in base.rglob('*') if p.is_file())
    for parent in ('inputs', 'operations'):
        for base in (RT / 'transport-probe' / parent).glob('*'):
            if base.name.startswith(('matched-', 'pilot3d-')):
                new_bytes += sum(p.stat().st_size for p in base.rglob('*') if p.is_file() and not p.is_symlink())
    runner = module(ROOT / 'scripts/tcad.py', '_pilot_resource_runner')
    cfg, ssh, _ = runner.connection()
    script = '''set -eu
rootdir=__ROOT__
printf 'AVAILABLE_KIB '
df -Pk "$rootdir" | awk 'NR==2 {print $4}'
awk '/MemTotal|MemAvailable|SwapFree/ {print}' /proc/meminfo
for procpath in /proc/[0-9]*; do
  app=$(cat "$procpath/comm" 2>/dev/null || true)
  location=$(readlink "$procpath/cwd" 2>/dev/null || true)
  case "$app" in
    sdevice*|snmesh*|sde|transport*) printf 'ACTIVE %s %s %s\\n' "${procpath##*/}" "$app" "$location" ;;
    svisual*) case "$location" in "$rootdir/dram-see-v4/"*) printf 'ACTIVE %s %s %s\\n' "${procpath##*/}" "$app" "$location" ;; esac ;;
  esac
done
if flock -n "$rootdir/.solver.lock" true; then printf 'LOCK_FREE\\n'; else printf 'LOCK_BUSY\\n'; fi
printf 'RESOURCE_SCAN_COMPLETE\\n'
'''.replace('__ROOT__', shlex.quote(cfg['remote_root'].rstrip('/')))
    folder = STATE / 'resources' / label
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'read-only.sh').write_text(script, encoding='utf-8', newline='\n')
    result = subprocess.run(ssh + ['bash -lc ' + shlex.quote(script)], capture_output=True, timeout=45)
    (folder / 'stdout.txt').write_bytes(result.stdout)
    (folder / 'stderr.txt').write_bytes(result.stderr)
    text = result.stdout.decode(errors='replace')
    match = re.search(r'^AVAILABLE_KIB (\d+)$', text, re.M)
    remaining_old = max(0, c['old_local_reservation_GiB'] * GiB - old_bytes)
    local_peak = raw_bytes * c['local_peak_multiplier']
    remote_peak = raw_bytes * c['remote_peak_multiplier']
    checks = dict(ssh=result.returncode == 0, complete='RESOURCE_SCAN_COMPLETE' in text,
                  lock_free='LOCK_FREE' in text, no_active=not any(x.startswith('ACTIVE ') for x in text.splitlines()),
                  remote_space=bool(match) and int(match[1]) * 1024 - remote_peak >= c['minimum_remote_free_after_peak_GiB'] * GiB,
                  local_space=shutil.disk_usage(ROOT).free >= remaining_old + max(local_peak, c['new_local_ceiling_GiB'] * GiB - new_bytes),
                  new_local_cap=new_bytes + local_peak <= c['new_local_ceiling_GiB'] * GiB)
    d = dict(schema='dram-see-v4-3d-resource-r1', created_utc=utc(), passed=all(checks.values()), checks=checks,
             raw_forecast_bytes=raw_bytes, local_peak_bytes=local_peak, remote_peak_bytes=remote_peak,
             old_actual_bytes=old_bytes, old_reserved_remaining_bytes=remaining_old, new_actual_bytes=new_bytes,
             forecast_is_measurement=False, campaign_sha256=sha(HERE / 'campaign.json'))
    save(folder / 'record.json', d, new=True)
    return d | reference(folder / 'record.json')


def invoke_operation(package, label, kind, role=None, timeout=900):
    """Only transport binary requests consume the six-call Geant budget."""
    package = Path(package).resolve()
    require(kind in ('build', 'geant', 'field'), 'Unknown operation kind')
    require(re.fullmatch(r'(matched|pilot3d)-[a-z0-9-]+', label), 'Invalid pilot operation label')
    require(package.is_relative_to(RT) and (package / 'task.sh').is_file(), 'Unknown operation package')
    require(not any(p.is_symlink() for p in package.rglob('*')), 'Linked inputs forbidden')
    require(0 < timeout <= 86400, 'Explicit bounded operation timeout required')
    with lock(OLD / 'scheduler.lock'), lock(RT / 'source-probe/execution.lock'):
        release = check_release(); old = old_queue_gate()
        verify_history(prior_calls() + [read(p) for p in (STATE / 'operations').glob('*/execution.json')])
        # The original operation adapter independently locks the remote solver.
        original = module(V4 / 'interface-completion-r1/control.py', '_pilot_operation_state')
        original.unresolved_postprocessing()
        if kind == 'geant':
            validate_budget(prior_calls(), 'geant', role)
            transport = module(V4 / 'matched-transport-r1/control.py', '_pilot_transport_control')
            contract = transport.contract()
            req = read(package / 'request.json')
            require(req in contract['requests'], 'Geant request is outside frozen contract')
            expected_role = ('init' if req['mode'] == 'init' else ('miss' if req['mode'] == 'miss' else 'normal')) + '-' + req['arm'].lower()
            require(expected_role == role and req['label'] == label, 'Geant role/label differs')
            if not role.startswith('init-'):
                transport.require_initialization_gate()
        elif kind == 'build':
            require(re.fullmatch(r'matched-build-r[1-9][0-9]*', label) and not (package / 'request.json').exists(), 'Build cannot contain a binary request')
        else:
            require((package / 'source-evidence.json').is_file(), 'Field package lacks source evidence')
        resource = resource_check(label, 64 * 1024 * 1024)
        require(resource['passed'], 'Operation resource readiness failed')
        original_input = RT / 'transport-probe/inputs' / label
        original_operation = RT / 'transport-probe/operations' / label
        require(not original_operation.exists(), 'Original operation exists; reconcile without resubmission')
        digests = {p.relative_to(package).as_posix(): sha(p) for p in package.rglob('*') if p.is_file()}
        if original_input.resolve() != package:
            require(not original_input.exists(), 'Staged original-adapter input exists; explicit recovery required')
            shutil.copytree(package, original_input)
        require(digests == {p.relative_to(original_input).as_posix(): sha(p) for p in original_input.rglob('*') if p.is_file()}, 'Staged package differs')
        base = 'calls' if kind == 'geant' else 'operations'
        folder = STATE / base / label
        folder.mkdir(parents=True, exist_ok=False)
        record = dict(schema='dram-see-v4-pilot-operation-r1', kind=kind, role=role, label=label,
                      category='primary', state='PREPARING', started_utc=utc(), automatic_retry=False,
                      campaign_sha256=sha(HERE / 'campaign.json'), release=release, old_queue=old,
                      resources=resource, package=rel(package), adapter_input=rel(original_input),
                      input_sha256=digests, primary_events=(0 if role and role.startswith('init-') else 2) if kind == 'geant' else 0)
        save(folder / 'execution.json', record, new=True)
        try:
            argv = [sys.executable, '-B', str(V4 / 'transport-probe/operation.py'), label, str(original_input), '--timeout', str(timeout)]
            with (folder / 'stdout.log').open('xb') as out, (folder / 'stderr.log').open('xb') as err:
                child = subprocess.Popen(argv, cwd=ROOT, stdout=out, stderr=err)
                record.update(state='RUNNING', launcher_pid=os.getpid(), runner_pid=child.pid, argv=argv)
                save(folder / 'execution.json', record)
                record['runner_exit_code'] = child.wait()
            op = read(original_operation / 'operation.json')
            record['operation'] = reference(original_operation / 'operation.json')
            require(op['input_sha256'] == digests, 'Original adapter inputs differ')
            require(op['collection_exit_code'] == 0 and op.get('ssh_exit_code') is not None and op.get('remote_exit_code') is not None,
                    'Original operation outcome unknown')
            require(sha(original_operation / 'results.tar') == op['archive_sha256'], 'Operation archive changed')
            if record['runner_exit_code'] == 0 and op['state'] == 'COLLECTED_PENDING_AUDIT' and op['ssh_exit_code'] == op['remote_exit_code'] == 0:
                record['state'] = 'COMPLETED'
            else:
                record['failure_proof'] = module(V4 / 'interface-completion-r1/campaign_runner.py', '_pilot_operation_failure').known_operation_failure(original_operation)
                record['state'] = 'KNOWN_FAILURE'
        except Exception as exc:
            record.update(state='REQUIRES_ORIGINAL_STATE_RECONCILIATION', error=repr(exc))
        finally:
            record['finished_utc'] = utc(); save(folder / 'execution.json', record)
        return record


def invoke_tcad(project, label, raw_bytes, category='primary', repair_path=None):
    project = Path(project).resolve()
    require(project.is_relative_to((RT / 'source-interface-3d-r1/inputs').resolve()), 'Unregistered 3D input location')
    require(re.fullmatch(r'pilot3d-[a-z0-9-]+', label), 'Unique pilot3d label required')
    builder = module(V4 / 'source-interface-3d-r1/build_interface.py', '_pilot_builder')
    proof = builder.check_project(project)
    params = read(project / 'parameters.json')
    role = params['case_id'].lower() + '-b1-3d'
    require(params['stored_bit'] == 1, 'Only bit1 pilot is released')
    repair = read(repair_path) if repair_path else None
    with lock(OLD / 'scheduler.lock'), lock(RT / 'source-probe/execution.lock'):
        release = check_release()
        old = old_queue_gate()
        verify_history(prior_calls() + [read(p) for p in (STATE / 'operations').glob('*/execution.json')])
        validate_budget(prior_calls(), 'tcad', role, category, repair)
        dependencies = [pilot_gate('a0-b1-3d')] if role == 'a1-b1-3d' else []
        resources = resource_check(label, raw_bytes)
        require(resources['passed'], 'Pilot resource forecast does not fit; no call submitted')
        folder = STATE / 'calls' / label
        folder.mkdir(parents=True, exist_ok=False)
        record = dict(schema='dram-see-v4-pilot-call-r1', kind='tcad', role=role, label=label,
                      category=category, repair=repair, state='PREPARING', started_utc=utc(),
                      campaign_sha256=sha(HERE / 'campaign.json'), release=release, old_queue=old,
                      dependencies=dependencies, resources=resources, project=rel(project),
                      resource_forecast_scope='Pre-mesh prefix; native same-SDE resource guard conditions full field output on actual mesh before SDevice',
                      input_check=proof, input_sha256={p.relative_to(project).as_posix(): sha(p) for p in project.rglob('*') if p.is_file()},
                      launcher_pid=os.getpid(), runner_exit_code=None, automatic_retry=False)
        save(folder / 'execution.json', record, new=True)
        try:
            argv = [sys.executable, '-B', str(ROOT / 'scripts/tcad.py'), 'run', str(project)]
            record['argv'] = argv
            with (folder / 'stdout.log').open('xb') as out, (folder / 'stderr.log').open('xb') as err:
                child = subprocess.Popen(argv, cwd=ROOT, stdout=out, stderr=err)
                record.update(state='RUNNING', runner_pid=child.pid)
                save(folder / 'execution.json', record)
                record['runner_exit_code'] = child.wait()
            match = re.search(r'^Run evidence:\s*(.+)$', (folder / 'stdout.log').read_text(encoding='utf-8', errors='replace'), re.M)
            require(match is not None, 'Runner outcome has no run identifier; reconcile original call')
            run = Path(match[1].strip()).resolve()
            require(run.is_relative_to((ROOT / 'local_runtime/runs').resolve()), 'Unexpected run path')
            manifest = read(run / 'manifest.json')
            record.update(run_id=run.name, runner_manifest_state=manifest['state'], ssh_exit_code=manifest.get('ssh_exit_code'),
                          result_archive_sha256=manifest.get('results_sha256'),
                          manifest_input_matches_project=manifest['input_sha256'] == record['input_sha256'])
            require(record['manifest_input_matches_project'], 'Runner inputs differ')
            if record['runner_exit_code'] == 0:
                require(manifest['state'] == 'COLLECTED' and manifest.get('ssh_exit_code') == 0, 'Incomplete original run')
                require(sha(run / 'results.tar') == manifest['results_sha256'], 'Original archive checksum differs')
                record['state'] = 'COMPLETED'
            else:
                old_api = module(V4 / 'interface-completion-r1/control.py', '_pilot_known_failure')
                record['failure_proof'] = old_api.known_solver_failure(record)
                record['state'] = 'KNOWN_FAILURE'
            record['scientific_status'] = 'PENDING_AUDIT' if record['state'] == 'COMPLETED' else 'FAILED'
        except Exception as exc:
            record.update(state='REQUIRES_ORIGINAL_STATE_RECONCILIATION', error=repr(exc))
        finally:
            record['finished_utc'] = utc()
            save(folder / 'execution.json', record)
        return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    run = sub.add_parser('invoke-tcad')
    run.add_argument('project', type=Path); run.add_argument('label'); run.add_argument('--raw-forecast-bytes', type=int, required=True)
    run.add_argument('--category', choices=('primary', 'reserve'), default='primary'); run.add_argument('--repair-ticket', type=Path)
    op = sub.add_parser('invoke-operation')
    op.add_argument('package', type=Path); op.add_argument('label'); op.add_argument('--kind', choices=('build', 'geant', 'field'), required=True)
    op.add_argument('--role'); op.add_argument('--timeout', type=int, default=900)
    sub.add_parser('check-release')
    args = parser.parse_args()
    if args.command == 'check-release':
        print(json.dumps(check_release(), indent=2))
    elif args.command == 'invoke-tcad':
        result = invoke_tcad(args.project, args.label, args.raw_forecast_bytes, args.category, args.repair_ticket)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result['state'] == 'COMPLETED' else 2)
    else:
        result = invoke_operation(args.package, args.label, args.kind, args.role, args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result['state'] == 'COMPLETED' else 2)
