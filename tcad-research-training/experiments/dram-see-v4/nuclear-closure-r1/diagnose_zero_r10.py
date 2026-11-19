"""One explicitly authorized zero-source diagnostic, using the original runners.

This entry has no point-source or device-matrix dispatch. Unknown/failed attempts
are never relaunched. Native fields retain the r8 scientific checks unchanged.
"""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

import common as c
import supervisor_storage_r4 as s

ROLE = 'qualification-zero'
LABEL = 'nc-r1-qualification-zero-trace-r10'
FIELD_LABEL = 'nc-r1-fields-qualification-zero-trace-r10'
ROOT_OUT = c.RT / 'pmi-root-cause-r10'
PROJECT = c.RT / 'inputs/qualification-zero-trace-r10'
ORIGINAL_PROJECT = c.RT / 'inputs/qualification-zero'
PATTERN = '*-v4-nuclear-closure-r1-qualification-zero-*'


def check_release():
    path = c.HERE / 'release-trace-r10.json'
    release = c.read(path)
    c.require(release['schema'] == 'nuclear-closure-trace-release-r10' and
              release['scope'] == 'single_authorized_qualification_zero_diagnostic' and
              release['execution_enabled'] is True, 'Diagnostic not released')
    c.require(release['contract_sha256'] == c.sha(c.HERE / 'contract.json'), 'Contract changed')
    for item in release['files']:
        c.check_ref(item)
    c.require(release['authorization'] == c.ref(ROOT_OUT / 'authorization.json'),
              'Release and charged diagnostic authorization differ')
    auth = c.read(c.check_ref(release['authorization']))
    c.require(auth['authorized'] is True and auth['maximum_diagnostic_solver_attempts'] == 1 and
              auth['charge_to_tcad_total'] is True and auth['charge_to_tcad_corrective'] is True,
              'One-time diagnostic authorization missing')
    c.require(auth['total_limit'] == 18 and auth['corrective_limit'] == 4, 'Budget authorization changed')
    active = c.read(c.RT / 'active-entry.json')
    c.require(active['execution_enabled'] is True and
              active['execution_mode'] == 'SINGLE_ZERO_DIAGNOSTIC' and
              active['entry'] == c.ref(Path(__file__)) and active['release'] == c.ref(path),
              'Entry is not the unique registered diagnostic')
    return c.ref(path)


def assert_no_unknown_attempts():
    """An idle lock does not establish the result of a disconnected prior job."""
    for path in (c.RT / 'attempts').glob('*.json'):
        row = c.read(path)
        c.require(type(row.get('exit_code')) is int and row.get('state') not in ('RESERVED', 'RUNNING'),
                  'Unresolved original attempt: ' + row['label'])
        if row['kind'] == 'tcad':
            c.require(row.get('run_directory'), 'TCAD attempt has no original run identity')
            run = c.ROOT / row['run_directory']
            manifest = c.read(run / 'manifest.json')
            c.require(manifest.get('state') in ('COLLECTED', 'FAILED_COLLECTED') and
                      type(manifest.get('ssh_exit_code')) is int and
                      manifest.get('results_sha256') == c.sha(run / 'results.tar'),
                      'Unresolved original TCAD directory: ' + row['label'])
        else:
            c.require(row['kind'] in ('compile', 'transport', 'postprocess'), 'Unknown cost category')
            operation = c.read(c.OLD_OPS / 'operations' / row['label'] / 'operation.json')
            c.require(operation.get('state') in ('COLLECTED_PENDING_AUDIT', 'FAILED_COLLECTED') and
                      all(type(operation.get(k)) is int for k in
                          ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code')),
                      'Unresolved original operation: ' + row['label'])


def check_same_conditions(project, original=ORIGINAL_PROJECT):
    import build_cases as b
    proof = b.check_project(project)
    b.check_project(original)
    old_files = {p.name: p.read_bytes() for p in Path(original).iterdir()}
    new_files = {p.name: p.read_bytes() for p in Path(project).iterdir()}
    c.require(set(old_files) == set(new_files), 'Diagnostic input inventory changed')
    allowed = {'pmi_nuclear_source.so.linux64', 'parameters.json', 'input-manifest.json'}
    changes = {name for name in old_files if old_files[name] != new_files[name]}
    c.require(changes <= allowed, 'Physical/deck/mesh/source inputs differ: ' + str(changes - allowed))
    parameters = []
    for raw in (old_files['parameters.json'], new_files['parameters.json']):
        value = json.loads(raw)
        c.require(value['role'] == ROLE and value['source_count'] == 0, 'Not the original zero-source role')
        c.require(value['matching_contract_sha256'] == b.digest(value['matching_contract']), 'Matching digest differs')
        c.require(value['pmi_binary_sha256'] == value['matching_contract']['pmi_binary_sha256'], 'PMI identities differ')
        value = copy.deepcopy(value)
        del value['pmi_binary_sha256'], value['matching_contract_sha256']
        del value['matching_contract']['pmi_binary_sha256']
        parameters.append(value)
    c.require(parameters[0] == parameters[1], 'Diagnostic parameters changed beyond binary provenance')
    return dict(passed=True, role=ROLE, original=c.ref(Path(original) / 'input-manifest.json'),
                diagnostic=proof, changed_files=sorted(changes), physical_inputs_identical=True)


def known_runs():
    known = set()
    for path in (c.RT / 'attempts').glob('*.json'):
        value = c.read(path)
        if value.get('kind') == 'tcad' and value.get('run_directory'):
            known.add((c.ROOT / value['run_directory']).resolve())
    current = {p.resolve() for p in (c.ROOT / 'local_runtime/runs').glob(PATTERN)}
    c.require(current <= known, 'Untracked original zero run exists; inspect without submission')
    return current


def run_once(project):
    path = c.RT / 'attempts' / (LABEL + '.json')
    inputs = {p.relative_to(project).as_posix(): c.sha(p) for p in sorted(project.rglob('*')) if p.is_file()}
    proof = check_same_conditions(project)
    if path.exists():
        row = c.read(path)
        c.require(row['label'] == LABEL and row['kind'] == 'tcad' and row['role'] == ROLE and
                  row['corrective'] is True and row['input_hashes'] == inputs,
                  'Prior diagnostic attempt identity differs')
        c.require(row.get('state') == 'EXECUTED' and row.get('exit_code') == 0 and row.get('run_directory'),
                  'Prior diagnostic failed/unknown; no resubmission')
        run = c.ROOT / row['run_directory']
        manifest = c.read(run / 'manifest.json')
        c.require(manifest.get('state') == 'COLLECTED' and manifest.get('ssh_exit_code') == 0 and
                  manifest['input_sha256'] == inputs and c.sha(run / 'results.tar') == manifest['results_sha256'],
                  'Prior diagnostic original result incomplete')
        return run, path
    check_release()
    old = known_runs()
    budget = s.budget()
    c.require(budget['tcad_calls'] < c.contract()['budgets']['tcad_total'] and
              budget['tcad_corrective_calls'] < c.contract()['budgets']['tcad_corrective'], 'TCAD budget exhausted')
    c.require(not any(c.read(p).get('diagnostic_authorization') == c.ref(ROOT_OUT / 'authorization.json')
                      for p in (c.RT / 'attempts').glob('*.json')), 'One-time authorization already consumed')
    before = s.preflight(LABEL)
    row = dict(schema='nuclear-closure-attempt-r1', label=LABEL, kind='tcad', role=ROLE,
               corrective=True, corrective_of='nc-r1-qualification-zero', diagnostic_only=True,
               diagnostic_authorization=c.ref(ROOT_OUT / 'authorization.json'), release=check_release(),
               created_utc=c.utc(), owner_pid=os.getpid(), preflight=before, exit_code=None, state='RESERVED',
               input_directory=project.relative_to(c.ROOT).as_posix(), input_hashes=inputs, offline_proof=proof,
               runner=c.ref(c.ROOT / 'scripts/tcad.py'), prior_runs=sorted(p.relative_to(c.ROOT).as_posix() for p in old))
    c.write(path, row)
    c.write(c.RT / 'budget.json', s.budget(), exclusive=False)
    command = [sys.executable, '-B', str(c.ROOT / 'scripts/tcad.py'), 'run', str(project)]
    log = c.RT / 'logs' / LABEL
    log.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with (log / 'stdout.log').open('xb') as stdout, (log / 'stderr.log').open('xb') as stderr:
        child = subprocess.Popen(command, cwd=c.ROOT, stdout=stdout, stderr=stderr)
        row.update(state='RUNNING', pid=child.pid, argv=command)
        c.write(path, row, exclusive=False)
        s.update_status(state='RUNNING_AUTHORIZED_ZERO_DIAGNOSTIC', owner_pid=os.getpid(),
                        active_child=child.pid, active_label=LABEL, scientific_passed=False)
        row['exit_code'] = child.wait()
    candidates = {p.resolve() for p in (c.ROOT / 'local_runtime/runs').glob(PATTERN)} - old
    row.update(state='EXECUTED' if row['exit_code'] == 0 else 'FAILED_OR_UNKNOWN', finished_utc=c.utc(),
               wall_seconds=time.monotonic() - started,
               candidate_runs=sorted(p.relative_to(c.ROOT).as_posix() for p in candidates))
    if len(candidates) == 1:
        row['run_directory'] = next(iter(candidates)).relative_to(c.ROOT).as_posix()
    c.write(path, row, exclusive=False)
    c.write(c.RT / 'budget.json', s.budget(), exclusive=False)
    s.update_status(active_child=None, active_label=None)
    c.require(len(candidates) == 1, 'Cannot identify one original diagnostic result; do not resubmit')
    run = next(iter(candidates))
    manifest = c.read(run / 'manifest.json')
    c.require(row['exit_code'] == 0 and manifest.get('ssh_exit_code') == 0 and
              manifest.get('state') == 'COLLECTED' and manifest['input_sha256'] == inputs and
              manifest['results_sha256'] == c.sha(run / 'results.tar'), 'Diagnostic failed/unknown; preserve original')
    return run, path


def save_trace(run):
    import acceptance_values_r8 as acceptance
    with acceptance.original().Archive(run / 'results.tar') as archive:
        c.require(archive.read('exit-code.txt').decode().strip() == '0', 'Native exit is not zero')
        text = archive.read('execution.log').decode('utf-8', errors='replace')
        c.require('ENGINEERING_RUN_COMPLETED' in text, 'Native completion marker missing')
    lines = [line for line in text.splitlines() if line.startswith('NC_TRACE_R10_')]
    c.require(lines, 'No native diagnostic telemetry captured')
    records = []
    for line in lines:
        parts = line.split()
        row = dict(kind=parts[0])
        for item in parts[1:]:
            key, value = item.split('=', 1)
            c.require(key not in row, 'Duplicate telemetry key')
            row[key] = value
        records.append(row)
    result = dict(schema='nuclear-closure-real-telemetry-r10', run_id=run.name,
                  archive=c.ref(run / 'results.tar'), records=records, raw_lines=lines,
                  note='Actual log samples and counters only; never substitutes for native full-frame TDR qualification.')
    path = ROOT_OUT / 'native-trace.json'
    if path.exists():
        c.require(c.read(path) == result, 'Prior native telemetry changed')
    else:
        c.write(path, result)
    return c.ref(path)


def fields(run, project):
    import field_audit_values_r8 as f
    inputs = c.OLD_OPS / 'inputs' / FIELD_LABEL
    op = c.OLD_OPS / 'operations' / FIELD_LABEL
    manifest, proof = f.source_provenance(run, project)
    expected = f.operation_inputs(manifest, proof)
    if inputs.exists():
        c.require(not any(p.is_symlink() for p in inputs.rglob('*')) and
                  {p.name: p.read_bytes() for p in inputs.iterdir()} == expected, 'Prior diagnostic field package changed')
    else:
        c.require(not (c.RT / 'attempts' / (FIELD_LABEL + '.json')).exists() and not op.exists(),
                  'Field attempt exists without inputs; inspect only')
        f.prepare(run, FIELD_LABEL, project)
    s.operation(FIELD_LABEL, inputs, 'postprocess', timeout=172800)
    f.collect_receipt(op)
    output = ROOT_OUT / 'diagnostic-fields'
    if output.exists():
        old = c.read(output / 'audit.json')
        result = f.audit(run, op, project)
        ignored = {'frames_csv_path', 'frames_csv_sha256'}
        c.require({k: v for k, v in old.items() if k not in ignored} == result, 'Saved diagnostic field audit differs')
        if 'frames_csv_path' in old:
            c.require(c.sha(Path(old['frames_csv_path'])) == old['frames_csv_sha256'], 'Saved native frame CSV changed')
        return old
    return f.audit(run, op, project, output=output)


def main():
    with s.ownership():
        s.assert_no_competing_scheduler(s.local_processes())
        release = check_release()
        assert_no_unknown_attempts()
        execution = ROOT_OUT / 'execution.json'
        if execution.exists():
            previous = c.read(execution)
            c.require(previous.get('state') not in ('RUNNING', 'COMPLETE'),
                      'Existing diagnostic owner/result; inspect without starting another entry')
            c.require(False, 'Failed/unknown entry requires original-directory recovery, never blind restart')
        record = dict(utc=c.utc(), pid=os.getpid(), state='RUNNING', release=release,
                      owner_lock=str(s.OWNER_LOCK), authorization=c.ref(ROOT_OUT / 'authorization.json'))
        c.write(execution, record)
        s.update_status(owner_pid=os.getpid(), active_child=None, state='BUILDING_AUTHORIZED_ZERO_TRACE', scientific_passed=False)
        try:
            import native_trace_compile_r10 as native
            binary = native.ensure_compiled()
            import build_cases as b
            if not PROJECT.exists():
                b.build(ROLE, PROJECT, None, binary)
            c.require(c.sha(PROJECT / binary.name) == c.sha(binary), 'Diagnostic project uses wrong PMI binary')
            physical = check_same_conditions(PROJECT)
            c.write(ROOT_OUT / 'same-condition-proof.json', physical)
            run, attempt = run_once(PROJECT)
            telemetry = save_trace(run)
            audit = fields(run, PROJECT)
            result = dict(schema='nuclear-closure-zero-diagnostic-result-r10', utc=c.utc(), engineering_completed=True,
                          diagnostic_role=ROLE, run=c.ref(run / 'manifest.json'), attempt=c.ref(attempt),
                          telemetry=telemetry, field_audit=c.ref(ROOT_OUT / 'diagnostic-fields/audit.json'),
                          zero_native_field_gate_passed=audit['passed'], full_pmi_qualification_passed=False,
                          no_production_gate_published=True, no_other_solver_dispatched=True, budget=s.budget())
            c.write(ROOT_OUT / 'diagnostic-result.json', result)
            record.update(state='COMPLETE', finished_utc=c.utc(), result=c.ref(ROOT_OUT / 'diagnostic-result.json'))
            s.update_status(state='ZERO_DIAGNOSTIC_COMPLETE_REQUIRES_ROOT_ANALYSIS', scientific_passed=False,
                            diagnostic_result=c.ref(ROOT_OUT / 'diagnostic-result.json'))
            return 0
        except Exception as exc:
            record.update(state='FAILED_OR_UNKNOWN', finished_utc=c.utc(), error=repr(exc), traceback=traceback.format_exc())
            s.update_status(state='PAUSED_DIAGNOSTIC_FAILURE_OR_UNKNOWN', error=repr(exc), scientific_passed=False)
            traceback.print_exc()
            return 2
        finally:
            c.write(execution, record, exclusive=False)
            s.update_status(owner_pid=None, active_child=None, active_label=None)
            c.write(c.RT / 'budget.json', s.budget(), exclusive=False)
            active = c.read(c.RT / 'active-entry.json')
            if active.get('entry') == c.ref(Path(__file__)):
                c.write(ROOT_OUT / 'active-entry-before-exit.json', active)
                active.update(execution_enabled=False, execution_mode='READ_ONLY_HOLD',
                              reason='One-time diagnostic entry ended; inspect original result before any separate release.', utc=c.utc())
                c.write(c.RT / 'active-entry.json', active, exclusive=False)


if __name__ == '__main__':
    if len(sys.argv) != 1:
        raise SystemExit('No force/adopt/retry flags; original unknown jobs must be inspected')
    raise SystemExit(main())
