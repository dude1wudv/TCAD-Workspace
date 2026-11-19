"""Versioned R4 deterministic extensions; only root may activate freeze/execute.

The original case generator, physics, comparisons, runner and numerical selector
remain unchanged. This file changes provenance routing and authorized accounting.
"""
import argparse
import copy
import ctypes
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('_r4_downstream_provenance', HERE / 'provenance.py')
P = importlib.util.module_from_spec(spec)
exec(compile((HERE / 'provenance.py').read_bytes(), str(HERE / 'provenance.py'), 'exec'), P.__dict__)
RUNTIME = P.LOCAL / 'physical-revisions/r50-main-extensions-r4'
ACCEPTANCE = P.LOCAL / 'physical-revisions/r50-main-extensions-r4-acceptance.json'
SCHEMA = 'dram-see-v3-r50-main-extensions-r4-plan'
TERMINAL = 'SIMULATION_STAGES_FINISHED_PENDING_DELIVERY'
BEFORE = None
ACTIVE = None
SESSION = None
CONTEXT = {}
read, sha, rel, repo, require = P.read, P.sha, P.rel, P.repo, P.require
LOADED_SHA = sha(__file__)


def configure(session):
    """Private namespaces only; never changes old files or the global ledger."""
    global SESSION
    require(sha(__file__) == LOADED_SHA, 'Loaded extensions source differs from disk')
    SESSION = session
    ext = session.ext
    ext.R, ext.F, ext.C = session.R, session.F, session.C
    session.C.DESIGN = P.BASE / 'design.json'
    session.C.design = session.core.runner_design
    session.C.save = save
    session.C.preflight = submission_preflight
    session.C.check_prediction_freeze = prediction_guard
    return ext


def command_argv(command):
    """Parse Windows quoting exactly; malformed/unavailable parsing never exempts."""
    if os.name != 'nt' or not command:
        return []
    from ctypes import wintypes
    parse = ctypes.windll.shell32.CommandLineToArgvW
    parse.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
    parse.restype = ctypes.POINTER(wintypes.LPWSTR)
    count = ctypes.c_int()
    pointer = parse(command, ctypes.byref(count))
    if not pointer:
        return []
    try:
        return [pointer[i] for i in range(count.value)]
    finally:
        release = ctypes.windll.kernel32.LocalFree
        release.argtypes = (wintypes.HLOCAL,)
        release.restype = wintypes.HLOCAL
        release(ctypes.cast(pointer, wintypes.HLOCAL))


def own_python_parent(row, argv):
    """Only a direct Python redirector with our exact script and full argv."""
    if row['ProcessId'] != os.getppid() or (row.get('Name') or '').lower() not in ('python.exe', 'pythonw.exe'):
        return False
    current = getattr(sys, 'orig_argv', [])
    if not argv or not current or not sys.argv or Path(sys.argv[0]).resolve() != Path(__file__).resolve():
        return False
    # Only executable location may differ across a Windows venv redirector.
    # Flags, script spelling, argument boundaries, order and case remain exact.
    return argv[1:] == list(current[1:])


def own_launcher_parent(row, argv):
    if row['ProcessId'] != os.getppid() or (row.get('Name') or '').lower() not in ('python.exe', 'pythonw.exe'):
        return False
    tail = argv[1:]
    if tail[:1] == ['-B']:
        tail = tail[1:]
    if len(tail) != 1:
        return False
    script = Path(tail[0]).resolve()
    return script.name == 'launch.py' and script.is_relative_to(P.LOCAL / 'restart-launches')


def host_guard():
    """Record creation times in rejection evidence; never kills an owner."""
    command = "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|ssh)\\.exe$' } | Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True, text=True, check=True)
    rows = json.loads(result.stdout) if result.stdout.strip() else []
    for row in [rows] if isinstance(rows, dict) else rows:
        pid = row['ProcessId']; cmd = (row.get('CommandLine') or '').replace('\\', '/').lower()
        if (row.get('Name') or '').lower() == 'ssh.exe':
            raise RuntimeError('Existing SSH requires owner reconciliation; pid=' + str(pid) + ', created=' + str(row.get('CreationDate')))
        if pid == os.getpid():
            continue
        # A directly owning Pythonw launcher waits for this controller; it does
        # not submit cases. Never exempt an arbitrary parent controller.
        argv = command_argv(row.get('CommandLine') or '')
        if own_python_parent(row, argv) or own_launcher_parent(row, argv):
            continue
        same_script = any(Path(token).resolve() == Path(__file__).resolve() for token in argv[1:] if not token.startswith('-'))
        if same_script or ('dram-see-v3' in cmd and any(name in cmd for name in ('/continue.py', '/controller.py', '/finish.py', '/extensions.py'))):
            raise RuntimeError('Another possible controller remains; reconcile without killing: ' + json.dumps(row))


def submission_preflight(tag):
    SESSION.core.authorization(); host_guard()
    result = SESSION.R.BASE_PREFLIGHT(tag)
    SESSION.core.authorization()
    return result


def save(ledger):
    require(BEFORE is not None and ACTIVE is not None, 'No active downstream ledger write context')
    allowed = {c['tag'] for c in ACTIVE['planned_cases']}
    for tag, row in ledger['runs'].items():
        if tag not in BEFORE['runs']:
            require(tag in allowed, 'Non-plan downstream ledger write')
            row.update(physical_revision=P.REVISION, physical_revision_probe_only=False,
                       original_100ohm_matrix_eligible=False, deterministic_extension_only=True, new_independent_event=False)
    SESSION.R.ledger_unchanged(BEFORE, ledger, allowed)
    SESSION.F.BASE_SAVE(ledger)


def prediction_guard():
    # The complete global ledger remains visible. The independent session
    # explicitly admits only exact planned extension input roles.
    session = P.Session(RUNTIME / 'plan.json')
    session.validate_chain(); value = session.check_prediction(); session.stable()
    return value


def reserve(plan, case):
    SESSION.core.authorization()
    used = SESSION.C.budget()
    rows = SESSION.C.load()['runs'].values()
    for row in rows:
        if row.get('inherited'):
            continue
        cost = row.get('charged_solver_s', row.get('elapsed_s'))
        require(type(cost) in (int, float) and math.isfinite(cost) and cost >= 0,
                'Missing/nonfinite/negative original solver charge')
    require(type(used) in (int, float) and math.isfinite(used) and used >= 0, 'Invalid cumulative solver cost')
    require(plan['global_budget_s'] is None and plan['deadline_utc'] is None, 'Unexpected resource ceiling')
    return {'global_budget_s': None, 'deadline_utc': None, 'global_solver_s_before': used,
            'next_estimate_s': case['estimate_s'], 'budget_policy': 'unlimited authorization; original global ledger retained'}


def acceptance(proof, session=None):
    session = SESSION if session is None else session
    value = read(ACCEPTANCE)
    keys = ('first_plan_sha256', 'training_plan_sha256', 'training_audit_sha256', 'prediction_plan_sha256',
            'test_plan_sha256', 'test_result_sha256', 'prediction_freeze_sha256')
    require(value.get('schema') == 'dram-see-v3-r50-main-extensions-r4-acceptance' and value.get('approved') is True
            and value.get('design_sha256') == P.DESIGN_SHA and value.get('aliases') == P.ALIASES
            and value.get('source_manifest_sha256') == sha(HERE / 'source-manifest.json')
            and value.get('authorization_sha256') == session.core.AUTH_SHA
            and all(value.get(key) == proof[key] for key in keys), 'Root actual extension activation acceptance differs')
    require(value.get('evidence_sha256') and value.get('accepted_utc'), 'Actual independent root evidence absent')
    instant = datetime.fromisoformat(value['accepted_utc'].replace('Z', '+00:00'))
    require(instant.utcoffset() is not None and instant.utcoffset().total_seconds() == 0, 'Acceptance needs absolute UTC')
    for path, digest in value['evidence_sha256'].items():
        require(sha(repo(path)) == digest, 'Root acceptance evidence changed')
    return value


def freeze():
    session = P.Session(); ext = configure(session)
    with session.C.controller_lock():
        require(not RUNTIME.exists(), 'Extension runtime already exists; preserve and reconcile')
        submission_preflight('r50-main-extensions-r4-freeze')
        session.C.check_preservation(); session.C.budget()
        proof = session.prerequisites(); accepted = acceptance(proof); source = P.sources()
        cases = ext.cases(proof['selection']); reused = {}
        for case in cases:
            if case['tag'] in session.ledger['runs']:
                reused[case['tag']] = ext.reused_case(case, session.ledger['runs'][case['tag']])
        ledger_bytes = session.C.LEDGER.read_bytes()
        require(json.loads(ledger_bytes) == session.ledger, 'Ledger changed before extension freeze')
        session.stable()
        for name, digest in source.items():
            target = RUNTIME / 'source-snapshot' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(repo(name).read_bytes())
            require(sha(target) == digest, 'Source changed during extension snapshot')
        before_path = RUNTIME / 'ledger-before.json'
        with before_path.open('xb') as stream:
            stream.write(ledger_bytes)
        # The ledger will legitimately gain extension rows. Bind its immutable
        # byte snapshot, never the rolling ledger path, as frozen evidence.
        files = {n: h for n, h in proof['files'].items() if n != rel(session.C.LEDGER)}
        files.update({rel(ACCEPTANCE): sha(ACCEPTANCE), **accepted['evidence_sha256']})
        plan = {'schema': SCHEMA, 'physical_revision': P.REVISION, 'label': 'r4', 'utc': session.C.now(),
            'design_sha256': P.DESIGN_SHA, 'source_sha256': source, 'inputs': {}, 'planned_cases': cases,
            'reused_cases': reused, 'baseline': proof['baseline'], 'selection': proof['selection'],
            'response_sources': proof['response_sources'], 'aliases': proof['aliases'], 'original_failures': proof['original_failures'],
            'raw_submission_index': proof['raw_submission_index'], 'frozen_files_sha256': files,
            **{key: proof[key] for key in ('first_plan_sha256', 'training_plan_sha256', 'training_audit_sha256',
                 'prediction_plan_sha256', 'test_plan_sha256', 'test_result_sha256', 'prediction_freeze_sha256')},
            'ledger_before': rel(before_path), 'ledger_before_sha256': sha(before_path), 'acceptance': accepted,
            'stage_order': ['oxide', 'boundary'], 'new_independent_events': 0, 'fixed_main_responses': 128,
            'new_solver_calls': len(cases) - len(reused), 'global_budget_s': None, 'deadline_utc': None,
            'budget_policy': 'unlimited authorization; every original/failed/retry/extension charge retained', 'terminal_state': TERMINAL}
        path = RUNTIME / 'plan.json'
        session.C.write_json(path, plan, exclusive=True)
        session.C.write_json(path.with_name('plan-sha256.json'), {'sha256': sha(path)}, exclusive=True)
        check_plan()
        return {'state': 'FROZEN', 'plan_sha256': sha(path), 'new_submissions': 0, 'planned_new_solver_calls': plan['new_solver_calls']}


def check_plan():
    path = RUNTIME / 'plan.json'; session = P.Session(path); ext = configure(session)
    value = session.C.check_execution(path)
    require(value.get('schema') == SCHEMA and value.get('physical_revision') == P.REVISION
            and value.get('label') == 'r4' and value.get('source_sha256') == P.sources()
            and value.get('planned_cases') == ext.cases(value['selection']) and value.get('aliases') == P.ALIASES
            and value.get('global_budget_s') is None and value.get('deadline_utc') is None
            and value.get('new_independent_events') == 0 and value.get('fixed_main_responses') == 128
            and value.get('stage_order') == ['oxide', 'boundary'] and value.get('terminal_state') == TERMINAL,
            'Downstream plan scope, source or authorization policy differs')
    require(read(path.with_name('plan-sha256.json')).get('sha256') == sha(path), 'Downstream plan self hash differs')
    for name, digest in value['source_sha256'].items():
        require(sha(path.parent / 'source-snapshot' / name) == digest, 'Downstream source snapshot changed')
    for name, digest in value['frozen_files_sha256'].items():
        require(sha(repo(name)) == digest, 'Frozen main evidence changed: ' + name)
    before = read(repo(value['ledger_before']))
    require(sha(repo(value['ledger_before'])) == value['ledger_before_sha256'], 'Protected pre-extension ledger changed')
    session.R.ledger_unchanged(before, session.ledger, {c['tag'] for c in value['planned_cases']})
    reused = {c['tag'] for c in value['planned_cases'] if c['tag'] in before['runs']}
    require(set(value['reused_cases']) == reused and value['new_solver_calls'] == len(value['planned_cases']) - len(reused), 'Exact reuse/new charge inventory differs')
    ordered = [c['tag'] for c in value['planned_cases'] if c['tag'] not in reused]
    existing = [i for i, tag in enumerate(ordered) if tag in session.ledger['runs']]
    require(existing == list(range(len(existing))), 'Extension submissions are not a fixed prefix')
    require(all(session.ledger['runs'][ordered[i]].get('state') == 'VERIFIED' for i in existing), 'Failed/unknown extension blocks resume')
    session.validate_chain()
    require(value['acceptance'] == acceptance(value), 'Acceptance changed after extension freeze')
    return value


def case_checked(case, row=None):
    path = RUNTIME / 'case-freezes' / (case['tag'] + '.json')
    value = SESSION.C.check_execution(path)
    require(value.get('extension_plan_sha256') == sha(RUNTIME / 'plan.json') and value.get('case') == case
            and value.get('source_sha256') == ACTIVE['source_sha256'] and value.get('prediction_freeze_sha256') == P.PREDICTION_SHA
            and set(value.get('inputs', {})) == {case['tag']}, 'Extension case freeze differs')
    if row is not None:
        require(row.get('execution_freeze') == rel(path) and row.get('execution_freeze_sha256') == sha(path)
                and value['inputs'][case['tag']] == row.get('input_sha256') and row.get('physical_revision') == P.REVISION
                and row.get('deterministic_extension_only') is True, 'Extension actual provenance differs')
    return path


def progress(state, reason=None):
    ledger = SESSION.C.load()
    SESSION.C.write_json(RUNTIME / 'status.json', {'schema': 'dram-see-v3-r50-main-extensions-r4-progress',
        'utc': SESSION.C.now(), 'state': state, 'reason': reason, **CONTEXT, 'plan_sha256': sha(RUNTIME / 'plan.json'),
        'fixed_main_independent_events': 64, 'fixed_main_response_slots': 128, 'new_independent_events': 0,
        'cases': [{'tag': c['tag'], 'stage': c['stage'], 'reused': c['tag'] in ACTIVE['reused_cases'],
                   'state': ledger['runs'].get(c['tag'], {}).get('state', 'UNSUBMITTED'),
                   'run_id': ledger['runs'].get(c['tag'], {}).get('run_id')} for c in ACTIVE['planned_cases']]})


def compare_prerequisites(proof, plan):
    for key in ('baseline', 'selection', 'response_sources', 'aliases', 'original_failures', 'raw_submission_index',
                'first_plan_sha256', 'training_plan_sha256', 'training_audit_sha256', 'prediction_plan_sha256',
                'test_plan_sha256', 'test_result_sha256', 'prediction_freeze_sha256'):
        require(proof[key] == plan[key], 'Frozen original prerequisite differs: ' + key)


def execute():
    global BEFORE, ACTIVE
    initial = P.Session(RUNTIME / 'plan.json'); configure(initial)
    with initial.C.controller_lock():
        CONTEXT.update(controller_pid=os.getpid(), controller_parent_pid=os.getppid(), controller_started_utc=initial.C.now(), current_case=None, current_stage=None)
        try:
            ACTIVE = check_plan(); BEFORE = read(repo(ACTIVE['ledger_before']))
            submission_preflight('r50-main-extensions-r4-start'); SESSION.C.check_preservation(); SESSION.C.budget()
            compare_prerequisites(SESSION.prerequisites(), ACTIVE)
            outputs = {}
            for stage in ('oxide', 'boundary'):
                CONTEXT['current_stage'] = stage
                for case in (c for c in ACTIVE['planned_cases'] if c['stage'] == stage):
                    check_plan(); ext = SESSION.ext; tag = case['tag']; CONTEXT['current_case'] = tag
                    row = SESSION.ledger['runs'].get(tag)
                    parent = SESSION.C.resolve(case['parent_tag']) if case['parent_tag'] else None
                    SESSION.R.matching(case['matching_tags'])
                    if tag in ACTIVE['reused_cases']:
                        require(ext.reused_case(case, row) == ACTIVE['reused_cases'][tag], 'Exact reused role changed')
                        continue
                    require(row is None or row.get('state') == 'VERIFIED', 'Never automatically repeat failed/unsettled extension')
                    execution = RUNTIME / 'case-freezes' / (tag + '.json')
                    if row is None:
                        reservation = reserve(ACTIVE, case)
                        if execution.exists():
                            case_checked(case)
                        else:
                            kwargs = dict(case['kwargs'])
                            if parent:
                                kwargs['parent'] = parent
                            inputs = SESSION.C.prepare(tag, **kwargs)
                            ext.recipe(case, read(P.LOCAL / 'inputs' / tag / 'parameters.json'), parent)
                            SESSION.C.write_json(execution, {'utc': SESSION.C.now(), 'design_sha256': P.DESIGN_SHA,
                                'source_sha256': ACTIVE['source_sha256'], 'inputs': {tag: inputs}, 'case': case,
                                'extension_plan_sha256': sha(RUNTIME / 'plan.json'), 'prediction_freeze_sha256': P.PREDICTION_SHA,
                                'reservation': reservation}, exclusive=True)
                        ext.recipe(case, read(P.LOCAL / 'inputs' / tag / 'parameters.json'), parent)
                        check_plan(); reserve(ACTIVE, case); progress('SUBMITTING_EXTENSION')
                        SESSION.C.record(tag, execution, estimate_s=case['estimate_s'])
                        row = SESSION.C.load()['runs'][tag]
                    # New solve changed the immutable session snapshot.
                    check_plan(); ext = SESSION.ext; row = SESSION.ledger['runs'][tag]
                    case_checked(case, row); value = SESSION.bundle(tag); ext.recipe(case, value['parameters'], parent)
                    SESSION.R.matching([tag, *case['matching_tags']]); progress('EXTENSION_IN_PROGRESS')
                ext = SESSION.ext
                report, pointer = ext.finish_oxide(RUNTIME / 'plan.json', ACTIVE) if stage == 'oxide' else ext.finish_boundary(RUNTIME / 'plan.json', ACTIVE)
                outputs[stage] = pointer
                SESSION.R.immutable(RUNTIME / (stage + '-result.json'), {'state': report['state'], **pointer, 'plan_sha256': sha(RUNTIME / 'plan.json')})
                require(report['state'] == 'VERIFIED', 'Continuous tolerance failed; original numerical failure retained')
            result = {'schema': 'dram-see-v3-r50-main-extensions-r4-result', 'state': TERMINAL,
                'physical_revision': P.REVISION, 'plan_sha256': sha(RUNTIME / 'plan.json'), 'outputs': outputs,
                'new_independent_events': 0, 'fixed_main_independent_events': 64, 'fixed_main_response_slots': 128,
                'delivery_status': 'Native PNG, visual review, reports/PPT and agent course materials still require actual acceptance'}
            SESSION.R.immutable(RUNTIME / 'result.json', result)
            CONTEXT['current_case'] = None; progress(TERMINAL)
            return result
        except Exception as exc:
            if ACTIVE is not None and (RUNTIME / 'plan.json').exists():
                progress('STOPPED_REQUIRES_RECONCILIATION', repr(exc))
            raise
        finally:
            BEFORE = None; ACTIVE = None


def review(session, plan_path):
    """Read-only full extension re-audit for delivery. No immutable/write helpers."""
    require(repo(plan_path) == RUNTIME / 'plan.json' and session.extension_path == repo(plan_path), 'Review requires exact R4 extension session')
    require(sha(__file__) == LOADED_SHA, 'Loaded extension review source differs from disk')
    plan = session.extension; ext = session.ext
    ext.R, ext.C, ext.F = session.R, session.C, session.F
    proof = session.prerequisites(); compare_prerequisites(proof, plan)
    require(plan['acceptance'] == acceptance(proof, session), 'Root extension acceptance differs')
    require(plan.get('global_budget_s') is None and plan.get('deadline_utc') is None
            and plan.get('new_independent_events') == 0 and plan.get('fixed_main_responses') == 128
            and plan.get('stage_order') == ['oxide', 'boundary'] and plan.get('terminal_state') == TERMINAL,
            'Extension fixed denominator/policy differs')
    before = session.bind(repo(plan['ledger_before']))
    reused = {c['tag'] for c in plan['planned_cases'] if c['tag'] in before['runs']}
    require(set(plan['reused_cases']) == reused and plan['new_solver_calls'] == len(plan['planned_cases']) - len(reused),
            'Extension reused/charged case inventory differs')
    statuses = []
    for case in plan['planned_cases']:
        tag = case['tag']; row = session.ledger['runs'].get(tag, {})
        require(row.get('state') == 'VERIFIED' and row.get('runner_exit_code') == 0, 'Incomplete extension cannot be reviewed as complete')
        if tag in plan['reused_cases']:
            require(ext.reused_case(case, row) == plan['reused_cases'][tag], 'Reused original role differs')
        else:
            session.extension_case(case, row)
        value = session.bundle(tag)
        parent = session.ledger['runs'][case['parent_tag']]['run_id'] if case['parent_tag'] else None
        ext.recipe(case, value['parameters'], parent); session.R.matching([tag, *case['matching_tags']])
        statuses.append({'tag': tag, 'stage': case['stage'], 'role': case['role'], 'state': row['state'],
                         'run_id': row['run_id'], 'reused': tag in plan['reused_cases'], 'raw_reviewed': True,
                         'new_independent_event': False})
    # Exact upstream result builders normally call immutable(). Replace only
    # that private namespace write endpoint with an equality-only reader.
    original = session.R.immutable
    def verify_existing(path, value):
        require(session.bind(path) == value, 'Saved extension report differs from re-audited originals')
        return {'evidence': rel(path), 'evidence_sha256': sha(path)}
    session.R.immutable = verify_existing
    try:
        oxide, oxide_pointer = ext.finish_oxide(repo(plan_path), plan)
        boundary, boundary_pointer = ext.finish_boundary(repo(plan_path), plan)
    finally:
        session.R.immutable = original
    for stage, report, pointer in (('oxide', oxide, oxide_pointer), ('boundary', boundary, boundary_pointer)):
        require(session.bind(RUNTIME / (stage + '-result.json')) == {'state': report['state'], **pointer, 'plan_sha256': sha(plan_path)}, 'Extension stage pointer differs')
    result = session.bind(RUNTIME / 'result.json')
    require(result.get('schema') == 'dram-see-v3-r50-main-extensions-r4-result' and result.get('state') == TERMINAL
            and result.get('plan_sha256') == sha(plan_path) and result.get('outputs') == {'oxide': oxide_pointer, 'boundary': boundary_pointer}
            and oxide['state'] == 'VERIFIED' and boundary['state'] == 'VERIFIED', 'Actual extension completion differs or failed')
    session.stable()
    return {'state': 'VERIFIED', 'plan': plan, 'oxide': oxide, 'boundary': boundary, 'cases': statuses,
            'comparisons': boundary['comparisons'], 'files': dict(session.files)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'execute', 'audit'))
    args = parser.parse_args()
    if args.action == 'audit':
        value = P.Session(RUNTIME / 'plan.json' if (RUNTIME / 'plan.json').exists() else None).prerequisites()
        print(json.dumps({'state': 'PREREQUISITES_REVIEWED', 'baseline_count': len(value['baseline']),
                          'selection': value['selection']['selected'], 'files': value['files']}, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(freeze() if args.action == 'freeze' else execute(), indent=2, ensure_ascii=False, allow_nan=False))
