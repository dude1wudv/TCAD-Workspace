"""Three-case authorized R50 physical revision probe; never resumes v3 training.

The original run module is loaded in an isolated namespace. Its scientific
dependencies are explicitly routed to these R50 copies; save adds probe-only
identity, and preflight enforces the submission deadline. Its runner command,
serial lock, input hashing, accounting and failure behavior remain unchanged.
"""
import argparse
import csv
from datetime import datetime, timezone
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import sys
import tarfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
LOCAL = ROOT / 'local_runtime/dram-see-v3'
AUTH = LOCAL / 'autonomy-authorization.json'
ORIGINAL_TAG = 'v3-l018-alpha-a0-s202610303-b0'
PROPOSAL_SHA = 'b6d8f1e0b27993e072f4b764412c7ffbf999703b2f1c39b50527c8b9de1c71da'
LOADED = {}
CONTEXT = {}
BEFORE = None


def module(name, path):
    content = Path(path).read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    exec(compile(content, str(path), 'exec'), value.__dict__)
    import hashlib
    LOADED[Path(path).resolve().relative_to(ROOT).as_posix()] = hashlib.sha256(content).hexdigest()
    return value


D = module('_r50_original_diagnostic_helpers', BASE / 'diagnose_precharge.py')
C = module('_r50_isolated_runner_controller', BASE / 'run.py')
B = module('_r50_builder', HERE / 'build_case.py')
A = module('_r50_audit', HERE / 'audit.py')
M = module('_r50_metrics', HERE / 'metrics.py')
I = module('_r50_inspection', HERE / 'inspection.py')
LOADED[Path(__file__).resolve().relative_to(ROOT).as_posix()] = C.sha(Path(__file__))
BASE_SAVE, BASE_PREFLIGHT = C.save, C.preflight


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def repo(name):
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('R50 evidence path escapes repository')
    return path


def directory(label):
    if label != 'r1':
        raise ValueError('This authorization permits only R50 probe r1')
    return LOCAL / 'physical-revisions' / 'precharge-r50-r1'


def cases(label='r1'):
    directory(label)
    common = {'length': .18, 'bit': 0, 'oxide_nm': 5., 'step': 1., 'mesh': 1., 'reference': 'offline'}
    return [{'tag': f'v3-r50-probe-{label}-' + role, 'role': role, 'estimate_s': 900,
             'kwargs': {**common, 'neutral': role == 'neutral', **({'event': 'experiments/dram-see-v3/data/geant4/l018-alpha-a0-s202610303/event.json'} if role == 'event' else {})},
             'depends_on': [] if role == 'control' else [f'v3-r50-probe-{label}-control'] if role == 'neutral'
                           else [f'v3-r50-probe-{label}-control', f'v3-r50-probe-{label}-neutral'],
             'parent_tag': f'v3-r50-probe-{label}-control' if role == 'event' else None}
            for role in ('control', 'neutral', 'event')]


def authorization():
    auth = read(AUTH)
    expected_probe = {'precharge_resistance_on_ohm': 50, 'max_new_solver_calls': 3, 'budget_seconds': 2700,
        'reserve_per_call_seconds': 900, 'fixed_order': ['control_bit0', 'neutral', 'same_failed_event_bit0'],
        'event_seed': 202610303, 'gate_length_um': .18, 'oxide_nm': 5, 'step_scale': 1, 'mesh_scale': 1}
    if (auth.get('schema') != 'dram-see-v3-project-authorization-v1' or '授权' not in auth.get('user_messages', [])
            or auth.get('specific_probe') != expected_probe or auth.get('specific_proposal_sha256') != PROPOSAL_SHA
            or auth.get('specific_approved_proposal') != 'experiments/dram-see-v3/precharge-revision-proposal.md'):
        raise ValueError('R50 explicit project/probe authorization differs')
    invariants = {'global_solver_budget_seconds': 86400, 'settled_before_seconds': 17782.66,
        'max_simultaneous_solvers': 1, 'solver_threads': 1, 'preserve_original_100ohm_main_rows': True,
        'mix_100ohm_and_50ohm_into_one_model': False, 'relax_scientific_thresholds': False, 'replace_failed_events': False}
    if any(auth.get('invariants', {}).get(key) != value for key, value in invariants.items()):
        raise ValueError('R50 authorization invariants differ')
    window = auth.get('autonomy_window', {})
    if (window.get('start_utc') != '2026-10-10T16:37:00Z' or window.get('end_utc') != '2026-10-11T04:37:00Z'
            or window.get('new_submission_deadline_enforced') is not True):
        raise ValueError('R50 authorized submission window differs')
    for name, snapshot in auth['snapshots'].items():
        if C.sha(repo(snapshot['snapshot'])) != snapshot['sha256']:
            raise ValueError('R50 authorization evidence snapshot changed: ' + name)
    if C.sha(repo(auth['specific_approved_proposal'])) != PROPOSAL_SHA:
        raise ValueError('R50 authorized proposal changed')
    before = read(repo(auth['snapshots']['local_runtime/dram-see-v3/ledger.json']['snapshot']))
    if len(before['runs']) != 43 or before['runs'][ORIGINAL_TAG]['state'] != 'FAILED':
        raise ValueError('R50 authorization does not preserve the expected original ledger')
    design = C.design()
    if design['execution']['solver_budget_s'] != 86400:
        raise ValueError('R50 cannot expand the frozen global budget')
    event = next(item for item in design['events'] if item['label'] == 'l018-alpha-a0-s202610303')
    return auth, before, design, event


def deadline(auth, instant=None):
    now = datetime.now(timezone.utc) if instant is None else instant
    start, end = [datetime.fromisoformat(auth['autonomy_window'][key].replace('Z', '+00:00')) for key in ('start_utc', 'end_utc')]
    if not start <= now < end:
        raise ValueError('R50 new-submission authorization window is closed; preserve any normal inflight solve')
    return {'checked_utc': now.isoformat(), 'deadline_utc': end.isoformat()}


def probe_module(name):
    # Explicit isolated adapter; never substitutes decks or changes old modules.
    if name == 'build_case':
        return B
    if name == 'audit':
        return A
    raise ValueError('The R50 runner adapter exposes only its own builder/audit')


def save_probe(ledger):
    if BEFORE is None:
        raise ValueError('R50 ledger write without validated execution authority')
    allowed = {case['tag'] for case in cases()}
    for tag, row in ledger['runs'].items():
        if tag not in BEFORE['runs']:
            if tag not in allowed:
                raise ValueError('Unexpected non-probe ledger row')
            row.update(physical_revision_probe_only=True, physical_revision='r50-probe-v1', original_main_matrix_eligible=False)
    D.ledger_unchanged(BEFORE, ledger, allowed)
    BASE_SAVE(ledger)


def submission_preflight(label):
    auth, _, _, _ = authorization()
    deadline(auth)
    result = BASE_PREFLIGHT(label)
    deadline(auth)  # SSH/preflight time cannot silently pass the submission deadline.
    return result


C.module, C.save, C.preflight = probe_module, save_probe, submission_preflight


def derivation_checked():
    index = read(HERE / 'derivation.json')
    for row in index['sources']:
        if (C.sha(repo(row['original'])) != row['original_sha256'] or C.sha(repo(row['derived'])) != row['derived_sha256']
                or C.sha(HERE / row['diff']) != row['diff_sha256']):
            raise ValueError('R50 explicit source derivation changed')
    return index


def sources():
    result = C.source_hashes()
    for path in (BASE / 'diagnose_precharge.py', BASE / 'numerical.py', BASE.parent / 'dram-see-v2/event_audit.py', BASE.parent / 'dram-readout-offset-d1/build.py'):
        result[rel(path)] = C.sha(path)
    for path in HERE.iterdir():
        if path.is_file() and (path.suffix in ('.py', '.diff') or path.name == 'derivation.json'):
            result[rel(path)] = C.sha(path)
    for name, digest in LOADED.items():
        if C.sha(repo(name)) != digest:
            raise ValueError('Loaded R50 source changed since process start')
    derivation_checked()
    return result


def protected(before):
    D.ledger_unchanged(before, C.load(), [case['tag'] for case in cases()])


def reserve(plan):
    auth, before, _, _ = authorization()
    protected(before)
    window = deadline(auth)
    global_used = C.budget()
    rows = [C.load()['runs'][case['tag']] for case in plan['planned_cases'] if case['tag'] in C.load()['runs']]
    costs = [row.get('charged_solver_s', row.get('elapsed_s', 0)) for row in rows]
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in costs + [global_used]):
        raise ValueError('Invalid R50 budget accounting')
    if len(rows) >= 3 or sum(costs) + 900 > 2700 or global_used + 900 > 86400:
        raise ValueError('R50 probe/global budget cannot reserve another 900 s; do not terminate a normal solve')
    return {'probe_used_s': sum(costs), 'global_used_s': global_used, 'reserved_s': 900, **window}


def freeze(label='r1'):
    path = directory(label) / 'plan.json'
    with C.controller_lock():
        if path.exists():
            check_plan(path)
            return {'state': 'FROZEN_EXISTING', 'plan': rel(path), 'plan_sha256': C.sha(path), 'new_submissions': 0}
        if path.parent.exists():
            raise ValueError('Partial R50 plan exists; preserve and reconcile')
        auth, before, design, event = authorization()
        deadline(auth)
        D.ledger_unchanged(before, C.load(), [])
        C.budget(); C.check_preservation()
        frozen = {rel(AUTH): C.sha(AUTH), rel(C.DESIGN): C.sha(C.DESIGN), auth['specific_approved_proposal']: PROPOSAL_SHA}
        for item in auth['snapshots'].values():
            frozen[item['snapshot']] = item['sha256']
        frozen.update(D.N.event_files(event))
        original = D.inspect_run(before['runs'][ORIGINAL_TAG]['run_id'], before['runs'][ORIGINAL_TAG])
        if original['record']['precharge_only_scientific_failure'] is not True:
            raise ValueError('Original failed 100-ohm event evidence changed')
        D.event_matches_original(event, original['parameters'])
        old = {}
        for role, tag in (('signal', ORIGINAL_TAG), ('control', C.tag_base(.18, 0)), ('neutral', C.tag_neutral(.18))):
            row = before['runs'][tag]
            old[role] = original if role == 'signal' else D.reusable(D.inspect_run(row['run_id'], row))
            D.bind_run(row['run_id'], frozen)
        baseline = D.observation(old['signal'], old['control'], old['neutral'])
        source = sources()
        for name, digest in source.items():
            output = path.parent / 'source-snapshot' / name
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('xb') as stream:
                stream.write(repo(name).read_bytes())
            if C.sha(output) != digest:
                raise ValueError('R50 source changed while snapshotting')
        plan = {'schema': 'dram-see-v3-r50-probe-plan', 'label': label, 'utc': C.now(),
                'authorization': auth, 'authorization_sha256': C.sha(AUTH), 'design_sha256': C.sha(C.DESIGN),
                'source_sha256': source, 'inputs': {}, 'frozen_files_sha256': frozen, 'planned_cases': cases(label),
                'event': event, 'original_100ohm_observation': baseline, 'original_failed_record': before['runs'][ORIGINAL_TAG],
                'original_100ohm_diagnostics': {role: bundle['record'] for role, bundle in old.items()},
                'physical_revision_probe_only': True, 'original_main_matrix_eligible': False, 'new_independent_events': 0,
                'probe_budget_s': 2700, 'global_budget_s': 86400, 'next_estimate_s': 900, 'maximum_attempts': 3,
                'scope': 'Single authorized fixed-event physical circuit sensitivity; cannot repair the old main matrix or resume training.'}
        C.write_json(path, plan, exclusive=True)
        C.write_json(path.with_name('plan-sha256.json'), {'sha256': C.sha(path)}, exclusive=True)
        check_plan(path)
        return {'state': 'FROZEN', 'plan': rel(path), 'plan_sha256': C.sha(path), 'new_submissions': 0}


def check_plan(path):
    path = Path(path)
    if read(path.with_name('plan-sha256.json')).get('sha256') != C.sha(path):
        raise ValueError('R50 plan self-hash differs')
    plan = C.check_execution(path)
    auth, before, design, event = authorization()
    if (path != directory(plan['label']) / 'plan.json' or plan.get('schema') != 'dram-see-v3-r50-probe-plan'
            or plan.get('authorization') != auth or plan.get('authorization_sha256') != C.sha(AUTH)
            or plan.get('source_sha256') != sources() or plan.get('planned_cases') != cases(plan['label'])
            or plan.get('event') != event or plan.get('original_failed_record') != before['runs'][ORIGINAL_TAG]
            or any(plan.get(key) != value for key, value in {'probe_budget_s': 2700, 'global_budget_s': 86400,
                'next_estimate_s': 900, 'maximum_attempts': 3, 'physical_revision_probe_only': True,
                'original_main_matrix_eligible': False, 'new_independent_events': 0}.items())):
        raise ValueError('R50 plan authority/source/recipe/scope differs')
    for name, digest in plan['source_sha256'].items():
        if C.sha(path.parent / 'source-snapshot' / name) != digest:
            raise ValueError('R50 source snapshot differs')
    for name, digest in plan['frozen_files_sha256'].items():
        if C.sha(repo(name)) != digest:
            raise ValueError('R50 frozen evidence changed: ' + name)
    protected(before)
    return plan


def case_file(path, case):
    return Path(path).parent / 'case-freezes' / (case['tag'] + '.json')


def case_checked(path, case, row=None):
    frozen = case_file(path, case)
    execution = C.check_execution(frozen)
    plan = read(path)
    if (execution.get('probe_plan_sha256') != C.sha(path) or execution.get('probe_plan') != rel(path)
            or execution.get('case') != case or execution.get('source_sha256') != plan['source_sha256']
            or set(execution['inputs']) != {case['tag']}):
        raise ValueError('R50 case input is not bound to its exact probe plan')
    if row is not None and (row.get('execution_freeze') != rel(frozen) or row.get('execution_freeze_sha256') != C.sha(frozen)
                           or row.get('input_sha256') != execution['inputs'][case['tag']] or row.get('physical_revision_probe_only') is not True):
        raise ValueError('Existing R50 case provenance/probe identity differs')
    return frozen


def recipe(case, parameters, parent, plan):
    expected = {'schema': 'dram-see-v3-precharge-r50', 'physical_revision': 'r50-probe-v1', 'physical_revision_probe_only': True,
                'precharge_resistance_on_ohm': 50, 'gate_length_um': .18, 'oxide_nm': 5., 'step_scale': 1., 'mesh_scale': 1.,
                'neutral': case['role'] == 'neutral', 'stored_bit': None if case['role'] == 'neutral' else 0,
                'target_voltage_V': .5 if case['role'] == 'neutral' else .1, 'reference_mode': 'offline',
                'parent_run': parent, 'source_event': case['kwargs'].get('event')}
    if any(parameters.get(key) != value for key, value in expected.items()):
        raise ValueError('R50 prepared/archive recipe differs from its fixed slot')
    A.matching_key(parameters)
    if case['role'] == 'event':
        D.event_matches_original(plan['event'], parameters)
        if parameters.get('source_evidence_sha256') != plan['original_failed_record']['parameters']['source_evidence_sha256']:
            raise ValueError('R50 event differs from the original failed Geant4 bytes')
    elif parameters.get('charge_pc') != 0 or parameters.get('particle') or parameters.get('source_evidence_sha256'):
        raise ValueError('R50 reference/control is irradiated')


def match(*bundles):
    contracts = [A.matching_key(bundle['parameters']) for bundle in bundles]
    meshes = [bundle['summary']['mesh_sha256'] for bundle in bundles]
    if any(value != contracts[0] for value in contracts) or any(not value or value != meshes[0] for value in meshes):
        raise ValueError('R50 full matching contract or actual mesh differs')


def progress(path, state, records, reason=None):
    ledger = C.load()
    C.write_json(Path(path).parent / 'status.json', {'schema': 'dram-see-v3-r50-probe-progress', 'utc': C.now(),
        **CONTEXT, 'state': state, 'reason': reason, 'plan_sha256': C.sha(path),
        'physical_revision_probe_only': True, 'original_main_matrix_eligible': False,
        'cases': [{**case, 'ledger_state': ledger['runs'].get(case['tag'], {}).get('state', 'UNSUBMITTED'),
                   'run_id': ledger['runs'].get(case['tag'], {}).get('run_id'),
                   **records.get(case['tag'], {'state': 'UNSUBMITTED'})} for case in cases()]})


def save_audit(path, case, row):
    result = I.inspect_run(row['run_id'], row)['record']
    if row.get('state') == 'FAILED' and result.get('precharge_only_scientific_failure') is not True:
        raise ValueError('Failed R50 raw values cannot be exported unless solely the exact collected precharge failure')
    target = Path(path).parent / 'audits' / (case['tag'] + '.json')
    if target.exists():
        if read(target) != result:
            raise ValueError('Prior R50 diagnostic audit changed')
    else:
        C.write_json(target, result, exclusive=True)
    return result


def immutable_csv(path, rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
    content = stream.getvalue().encode('utf8')
    if Path(path).exists():
        if Path(path).read_bytes() != content:
            raise ValueError('Existing R50 derived CSV differs from original curve')
    else:
        with Path(path).open('xb') as output:
            output.write(content)


def failed_event_diagnostics(path, plan, failed, bundles):
    """Only exact precharge-only failure reaches here; no passing metrics forged."""
    if (failed.get('precharge_only_scientific_failure') is not True
            or not {'control', 'neutral'} <= set(bundles)):
        raise ValueError('Failed event is not eligible for the strictly limited raw diagnosis')
    control, neutral = bundles['control'], bundles['neutral']
    if (A.matching_key(failed['parameters']) != A.matching_key(control['parameters'])
            or failed['mesh_sha256'] != control['summary']['mesh_sha256']):
        raise ValueError('Failed R50 event does not match its audited control/reference')
    match(control, neutral)
    bln = A.sample(neutral['circuit'], 'v(bl)', 4e-9)
    ds = failed['BL_4ns_V'] - bln
    dc = A.sample(control['circuit'], 'v(bl)', 4e-9) - bln
    result = {'schema': 'dram-see-v3-r50-failed-event-diagnosis', 'state': 'FAILED_DIAGNOSTIC_ONLY',
        'physical_revision_probe_only': True, 'original_main_matrix_eligible': False, 'training_or_prediction_eligible': False,
        'raw_audit_state': 'FAILED', 'raw_audit_error': failed['raw_audit_error'], 'plan_sha256': C.sha(path),
        'diagnostic_metrics': {'deltaQ_fC': failed['parameters']['capacitance_F'] *
            (failed['SN_2p8ns_V'] - A.sample(control['circuit'], 'v(sn)', 2.8e-9)) * 1e15,
            'D4_V': ds, 'M4_V': -ds, 'control_D4_V': dc, 'control_M4_V': -dc, 'deltaM_V': ds - dc,
            'classification': {str(e): A.classification(-ds, e) for e in A.THRESHOLDS_V}},
        'sources': {'failed': failed, 'control': M._source(control), 'neutral': M._source(neutral)},
        'scope': 'Exact collected precharge-only failure; diagnostic values do not pass the raw audit, physical-reference gate or numerical-sensitivity gate.'}
    target = path.parent / 'failed-event-diagnostics.json'
    if target.exists():
        if read(target) != result:
            raise ValueError('Prior failed R50 diagnostic changed')
    else:
        C.write_json(target, result, exclusive=True)


def completed(path, case, row, parent, plan):
    if row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0:
        raise ValueError('R50 prior failure/unsettled attempt: never retry or advance dependency')
    case_checked(path, case, row)
    bundle = A.load_curves(row['run_id'])
    recipe(case, bundle['parameters'], parent, plan)
    if (row.get('parameters') != bundle['parameters'] or row.get('input_sha256') != bundle['summary']['input_sha256']
            or row.get('audit_archive_sha256') != bundle['summary']['archive_sha256']):
        raise ValueError('R50 completed archive/input identity changed')
    save_audit(path, case, row)
    return bundle


def finish(path, plan, records, bundles):
    signal, control, neutral = [bundles[role] for role in ('event', 'control', 'neutral')]
    metrics = M.compute_curves(signal, control, neutral)
    old = plan['original_100ohm_observation']
    fields = ('deltaQ_fC', 'D4_V', 'M4_V', 'control_D4_V', 'control_M4_V', 'deltaM_V')
    sensitivity = {'kind': 'physical_circuit_parameter_sensitivity_100_to_50_ohm',
        'differences_new_minus_old': {key: metrics[key] - old['metrics'][key] for key in fields},
        'classifications_100ohm_diagnostic': old['metrics']['classification'], 'classifications_50ohm': metrics['classification'],
        'old_signal_raw_audit_state': old['raw_audit_states']['signal'],
        'scope': 'Old values failed raw audit and remain diagnostic; not a same-model numerical test or replaceable main sample.'}
    source = {}
    precharge = {}
    for case in plan['planned_cases']:
        row = C.load()['runs'][case['tag']]
        record = read(path.parent / 'audits' / (case['tag'] + '.json'))
        precharge[case['role']] = record['precharge']
        D.bind_run(row['run_id'], source)
        csv_path = path.parent / (case['role'] + '-precharge.csv')
        with tarfile.open(A.run_folder(row['run_id']) / 'results.tar') as archive:
            _, raw = A.parse_plt(A.read(archive, 'circuit.plt').decode())
        # The original incoming-endpoint convention is retained; CSV is raw evidence, not a repaired curve.
        rows = A.segment(raw, 2.8e-9, 3e-9, True)
        immutable_csv(csv_path, rows)
        source[rel(csv_path)] = C.sha(csv_path)
    ledger = C.load()
    report = {'schema': 'dram-see-v3-r50-probe-result', 'state': 'THREE_PROBE_CASES_RAW_AUDIT_PASSED',
        'plan_sha256': C.sha(path), 'authorization_sha256': plan['authorization_sha256'],
        'physical_revision_probe_only': True, 'original_main_matrix_eligible': False, 'new_independent_events': 0,
        'original_failed_state_preserved': ledger['runs'][ORIGINAL_TAG]['state'], 'cases': records,
        'precharge': precharge, 'metrics': metrics, 'physical_sensitivity': sensitivity,
        'BL_4ns_V': {role: A.sample(bundle['circuit'], 'v(bl)', 4e-9) for role, bundle in bundles.items()},
        'REF_4ns_V': {role: A.sample(bundle['circuit'], 'v(ref)', 4e-9) for role, bundle in bundles.items()},
        'source_files_sha256': source, 'probe_solver_s': sum(ledger['runs'][case['tag']]['charged_solver_s'] for case in cases()),
        'global_solver_s': C.budget(), 'scope': 'Only this fixed 50-ohm event and matched references; original 128 responses/training unchanged.'}
    target = path.parent / 'result.json'
    if target.exists():
        if read(target) != report:
            raise ValueError('Completed R50 result is immutable')
    else:
        C.write_json(target, report, exclusive=True)
    CONTEXT['current_case'] = None
    progress(path, report['state'], records)
    return report


def execute(label='r1'):
    global BEFORE
    path = directory(label) / 'plan.json'
    if not path.is_file():
        raise ValueError('R50 execute requires an existing frozen plan')
    records, bundles = {}, {}
    with C.controller_lock():
        CONTEXT.update(controller_pid=os.getpid(), controller_parent_pid=os.getppid(), controller_started_utc=C.now(), current_case=None)
        try:
            plan = check_plan(path)
            auth, BEFORE, _, _ = authorization()
            C.check_preservation(); C.budget()
            progress(path, 'CHECKING_PREREQUISITES', records)
            BASE_PREFLIGHT('r50-probe-' + label)  # read-only reconciliation also allowed after deadline
            for case in plan['planned_cases']:
                check_plan(path)
                tag = case['tag']; CONTEXT['current_case'] = tag
                parent = C.resolve(case['parent_tag']) if case['parent_tag'] else None
                for prior in case['depends_on']:
                    if C.load()['runs'].get(prior, {}).get('state') != 'VERIFIED':
                        raise ValueError('R50 dependency failed or unresolved')
                if case['role'] == 'event':
                    match(bundles['control'], bundles['neutral'])
                row = C.load()['runs'].get(tag)
                if row is None:
                    reservation = reserve(plan)
                    execution = case_file(path, case)
                    if execution.exists():
                        case_checked(path, case)
                    else:
                        kwargs = dict(case['kwargs'])
                        if parent:
                            kwargs['parent'] = parent
                        inputs = C.prepare(tag, **kwargs)
                        recipe(case, read(LOCAL / 'inputs' / tag / 'parameters.json'), parent, plan)
                        C.write_json(execution, {'utc': C.now(), 'design_sha256': plan['design_sha256'],
                            'source_sha256': plan['source_sha256'], 'inputs': {tag: inputs}, 'case': case,
                            'probe_plan': rel(path), 'probe_plan_sha256': C.sha(path),
                            'physical_revision_probe_only': True, 'reservation': reservation}, exclusive=True)
                    recipe(case, read(LOCAL / 'inputs' / tag / 'parameters.json'), parent, plan)
                    check_plan(path); reserve(plan)
                    progress(path, 'SUBMITTING_CASE', records)
                    C.record(tag, execution, estimate_s=900)
                    row = C.load()['runs'][tag]
                bundle = completed(path, case, row, parent, plan)
                bundles[case['role']] = bundle
                if len(bundles) > 1:
                    match(*bundles.values())
                records[tag] = {'state': 'VERIFIED_PROBE_ONLY', 'raw_audit_state': 'PASSED', 'run_id': row['run_id'],
                                'archive_sha256': bundle['summary']['archive_sha256'], 'physical_revision_probe_only': True}
                check_plan(path)
                progress(path, 'PROBE_IN_PROGRESS', records)
            return finish(path, plan, records, bundles)
        except Exception as exc:
            tag = CONTEXT.get('current_case')
            row = C.load()['runs'].get(tag, {})
            # All failure kinds stop; no exception grants the R50 branch a retry.
            if row.get('state') == 'FAILED' and row.get('run_id') and row.get('runner_exit_code') == 0:
                try:
                    case = next(case for case in cases() if case['tag'] == tag)
                    diagnosed = save_audit(path, case, row)
                    if case['role'] == 'event':
                        failed_event_diagnostics(path, plan, diagnosed, bundles)
                    records[tag] = {'state': 'FAILED', 'raw_audit_state': diagnosed['raw_audit_state'],
                                    'physical_revision_probe_only': True, 'run_id': row['run_id'], 'error': repr(exc)}
                except Exception as diagnosis_error:
                    records[tag] = {'state': 'FAILED_REQUIRES_RECONCILIATION', 'error': repr(exc), 'diagnostic_error': repr(diagnosis_error)}
            blocked = False
            for case in cases():
                if blocked and case['tag'] not in C.load()['runs']:
                    records[case['tag']] = {'state': 'BLOCKED_PREREQUISITE', 'physical_revision_probe_only': True}
                if case['tag'] == tag:
                    blocked = True
            progress(path, 'STOPPED_REQUIRES_RECONCILIATION', records, repr(exc))
            raise
        finally:
            BEFORE = None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'execute'))
    parser.add_argument('--label', default='r1')
    args = parser.parse_args()
    print(json.dumps(freeze(args.label) if args.action == 'freeze' else execute(args.label), indent=2, ensure_ascii=False, allow_nan=False))
