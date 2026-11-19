"""Isolated R50-main references/pilot/numerical/training controller.

Uses the original runner, global ledger, controller lock and preflight. This
version stops after training; no transport-test, prediction, test or extension
entry point exists. The accepted fixed source manifest excludes future modules.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
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
RUNTIME = LOCAL / 'physical-revisions/r50-main-r1'
ACCEPTANCE = LOCAL / 'physical-revisions/r50-main-r1-acceptance.json'
AUTH = LOCAL / 'autonomy-authorization.json'
DESIGN_SHA = '6d52749bb8b9716b13b5ff1aa562a3ee331e3d7a062f32287c23710a5d1cf740'
PLAN_SHA = 'c2f08d68394b669b0ab7edb6727523743cd00a93647e132756421d40a8d9db67'
AUTH_SHA = 'd584724713301b3fd9c7dc240d058c5ebaa995b909b9f7442425f3b78303d703'
SCHEMA = 'dram-see-v3-r50-main'
REVISION = 'r50-main-r1'
STAGES = ('references', 'pilot', 'numerical_preregistered', 'train')
LOADED = {}
BEFORE = None
CONTEXT = {}
BUNDLES = {}


def load_module(name, path, register=False):
    content = Path(path).read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = obj
    exec(compile(content, str(path), 'exec'), obj.__dict__)
    LOADED[Path(path).resolve().relative_to(ROOT).as_posix()] = hashlib.sha256(content).hexdigest()
    return obj


# Load project code from its bytes, including the original runner dependencies.
T = load_module('tcad', ROOT / 'scripts/tcad.py', True)
COMMON = load_module('common', BASE / 'common.py', True)
C = load_module('_r50_main_original_runner', BASE / 'run.py')
B = load_module('_r50_main_builder', HERE / 'build_case.py')
A = load_module('_r50_main_audit', HERE / 'audit.py')
M = load_module('_r50_main_metrics', HERE / 'metrics.py')
N = load_module('_r50_main_pure_numerical', HERE / 'numerical.py')
E = load_module('_r50_main_transport_validation', BASE / 'event_audit.py')
PA = load_module('_r50_probe_activation_audit', BASE / 'precharge-r50/audit.py')
LOADED[Path(__file__).resolve().relative_to(ROOT).as_posix()] = C.sha(__file__)
BASE_SAVE, BASE_PREFLIGHT = C.save, C.preflight

# Exact dependency list: additions for a later controller revision do not change
# this active version. Source-manifest.json itself is separately byte-hashed.
SOURCE_FILES = tuple('experiments/dram-see-v3/r50-main/' + name for name in (
    'controller.py', 'build_case.py', 'audit.py', 'metrics.py', 'numerical.py',
    'build_case.py.diff', 'audit.py.diff', 'metrics.py.diff', 'numerical.py.diff',
    'derivation.json', 'plan.md', 'design.json', 'design.sha256')) + (
    'experiments/dram-see-v3/common.py', 'experiments/dram-see-v3/run.py',
    'experiments/dram-see-v3/build_case.py', 'experiments/dram-see-v3/audit.py',
    'experiments/dram-see-v3/metrics.py', 'experiments/dram-see-v3/numerical.py',
    'experiments/dram-see-v3/event_audit.py', 'experiments/dram-see-v3/stats-design.json',
    'experiments/dram-see-v3/precharge-r50/audit.py', 'experiments/dram-see-v3/precharge-r50/build_case.py',
    'experiments/dram-see-v1/build_case.py', 'experiments/dram-see-v1/analyze.py',
    'experiments/dram-see-v2/build_case.py', 'experiments/dram-see-v2/event_audit.py',
    'experiments/dram-readout-offset-d1/build.py', 'scripts/tcad.py')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def repo(name):
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Evidence path escapes project')
    return path


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def design():
    if C.sha(HERE / 'design.json') != DESIGN_SHA or C.sha(HERE / 'plan.md') != PLAN_SHA:
        raise ValueError('Frozen R50-main science design changed')
    d = read(HERE / 'design.json')
    if (d.get('schema') != SCHEMA or d.get('physical_revision') != REVISION
            or d['execution']['solver_budget_s'] != 86400 or d['physical_change']['probe_reference_reuse'] is not False
            or len(d['events']) != 64 or sum(e['split'] == 'train' for e in d['events']) != 32):
        raise ValueError('Unexpected R50-main scope')
    return d


def directory(label='r1'):
    if label != 'r1':
        raise ValueError('Only the frozen R50-main r1 is implemented')
    return RUNTIME


def sources():
    expected = {name: C.sha(repo(name)) for name in SOURCE_FILES}
    manifest = read(HERE / 'source-manifest.json')
    if (manifest.get('schema') != 'dram-see-v3-r50-main-source-manifest' or manifest.get('physical_revision') != REVISION
            or manifest.get('files_sha256') != expected):
        raise ValueError('Accepted fixed source manifest differs')
    for name, digest in LOADED.items():
        if expected.get(name) != digest:
            raise ValueError('Loaded source bytes differ from the accepted source manifest: ' + name)
    for row in read(HERE / 'derivation.json')['sources']:
        if (C.sha(repo(row['original'])) != row['original_sha256'] or C.sha(repo(row['derived'])) != row['derived_sha256']
                or C.sha(HERE / row['diff']) != row['diff_sha256']):
            raise ValueError('Explicit model derivation changed')
    return {**expected, rel(HERE / 'source-manifest.json'): C.sha(HERE / 'source-manifest.json')}


def control_tag(length, bit, step=1., mesh=1.):
    return C.safe_tag(f'v3-r50-main-control-l{round(length * 100):03d}-b{bit}-ox5-s{step:g}-m{mesh:g}')


def neutral_tag(length, step=1., mesh=1.):
    return C.safe_tag(f'v3-r50-main-neutral-l{round(length * 100):03d}-ox5-s{step:g}-m{mesh:g}')


def event_tag(event, bit):
    return 'v3-r50-main-' + event['label'] + '-b' + str(bit)


def refined_tag(event, bit, step, mesh):
    return C.safe_tag(f'v3-r50-main-num-{event["label"]}-b{bit}-s{step:g}-m{mesh:g}')


def event_path(event):
    return BASE / 'data/geant4' / event['label'] / 'event.json'


def target_event(d):
    fixed = d['numerical']['preregistered']
    return next(e for e in d['events'] if all(e[key] == fixed[other] for key, other in (
        ('gate_length_um', 'length_um'), ('particle', 'particle'), ('angle_deg', 'angle_deg'), ('replicate', 'replicate'))))


def cases(d=None):
    d = design() if d is None else d
    result = []
    def add(stage, tag, role, kwargs, parent=None, matching=(), event=None, offline=None):
        result.append({'stage': stage, 'tag': tag, 'role': role, 'kwargs': kwargs, 'parent_tag': parent,
            'matching_tags': list(matching), 'event': event, 'offline_tag': offline,
            'estimate_s': 1000 if role == 'physical' else 900 if stage == 'numerical_preregistered' else 600})
    for length in (.18, .25, .35, .45):
        for bit in (0, 1):
            add('references', control_tag(length, bit), 'control', {'length': length, 'bit': bit})
        add('references', neutral_tag(length), 'neutral', {'length': length, 'neutral': True})
    for length in (.18, .25, .35, .45):
        for bit in (0, 1):
            add('references', f'v3-r50-main-physical-l{round(length * 100):03d}-b{bit}', 'physical',
                {'length': length, 'bit': bit, 'reference': 'physical'}, matching=(control_tag(length, bit), neutral_tag(length)), offline=control_tag(length, bit))
    for event in (e for e in d['events'] if e['pilot']):
        for bit in (0, 1):
            length = event['gate_length_um']
            add('pilot', event_tag(event, bit), 'event', {'length': length, 'bit': bit, 'event': rel(event_path(event))},
                control_tag(length, bit), (control_tag(length, bit), neutral_tag(length)), event)
    for particle, angle, bit in (('alpha', 30, 1), ('proton', 0, 0)):
        event = next(e for e in d['events'] if e['pilot'] and e['particle'] == particle and e['angle_deg'] == angle)
        add('pilot', f'v3-r50-main-isolation-{particle}-a{angle}-b{bit}', 'physical',
            {'length': .18, 'bit': bit, 'reference': 'physical', 'event': rel(event_path(event))},
            matching=(event_tag(event, bit), neutral_tag(.18)), event=event, offline=event_tag(event, bit))
    event, bit = target_event(d), d['numerical']['preregistered']['stored_bit']
    for variation in d['numerical']['variations']:
        step, mesh = variation['step'], variation['mesh']
        common = {'length': event['gate_length_um'], 'step': step, 'mesh': mesh}
        control, neutral = control_tag(common['length'], bit, step, mesh), neutral_tag(common['length'], step, mesh)
        add('numerical_preregistered', control, 'control', {**common, 'bit': bit})
        add('numerical_preregistered', neutral, 'neutral', {**common, 'neutral': True})
        add('numerical_preregistered', refined_tag(event, bit, step, mesh), 'event',
            {**common, 'bit': bit, 'event': rel(event_path(event))}, control, (control, neutral), event)
    for event in (e for e in d['events'] if e['split'] == 'train' and not e['pilot']):
        for bit in (0, 1):
            length = event['gate_length_um']
            add('train', event_tag(event, bit), 'event', {'length': length, 'bit': bit, 'event': rel(event_path(event))},
                control_tag(length, bit), (control_tag(length, bit), neutral_tag(length)), event)
    if len(result) != 92 or len({case['tag'] for case in result}) != 92:
        raise ValueError('Unexpected first-segment case count or duplicate')
    return result


def ledger_unchanged(before, current, allowed):
    if set(before) != set(current):
        raise ValueError('Original ledger top-level fields changed')
    for key in before:
        if key not in ('runs', 'failures') and before[key] != current[key]:
            raise ValueError('Original ledger section changed: ' + key)
    if any(current['runs'].get(tag) != row for tag, row in before['runs'].items()):
        raise ValueError('Original/probe ledger row changed')
    if not set(current['runs']) - set(before['runs']) <= set(allowed):
        raise ValueError('Unexpected run added outside the frozen R50-main cases')
    prior, failures = before['failures'], current['failures']
    if failures[:len(prior)] != prior or len(failures) < len(prior):
        raise ValueError('Original failure history changed')
    extra = failures[len(prior):]
    if len({row.get('tag') for row in extra}) != len(extra) or any(row.get('tag') not in allowed or row.get('state') != 'FAILED' or current['runs'].get(row.get('tag')) != row for row in extra):
        raise ValueError('Invalid R50-main failure append')


def save_main(ledger):
    if BEFORE is None:
        raise ValueError('No activated R50-main execution context for a ledger write')
    allowed = {case['tag'] for case in cases()}
    for tag, row in ledger['runs'].items():
        if tag not in BEFORE['runs']:
            if tag not in allowed:
                raise ValueError('Non-plan ledger write')
            row.update(physical_revision=REVISION, physical_revision_probe_only=False, original_100ohm_matrix_eligible=False)
    ledger_unchanged(BEFORE, ledger, allowed)
    BASE_SAVE(ledger)


def deadline(auth=None, instant=None):
    auth = read(AUTH) if auth is None else auth
    current = datetime.now(timezone.utc) if instant is None else instant
    start, end = [datetime.fromisoformat(auth['autonomy_window'][key].replace('Z', '+00:00')) for key in ('start_utc', 'end_utc')]
    if end.isoformat() != '2026-10-11T04:37:00+00:00' or not start <= current < end:
        raise RuntimeError('Submission window closed; no normal running solve is terminated')
    return {'checked_utc': current.isoformat(), 'deadline_utc': end.isoformat()}


def submission_preflight(tag):
    deadline()
    result = BASE_PREFLIGHT(tag)
    deadline()
    return result


def runner_module(name):
    if name == 'build_case':
        return B
    if name == 'audit':
        return A
    raise ValueError('Original runner adapter only permits R50-main builder and audit')


def reject_test():
    raise ValueError('This accepted controller ends after training; predictions and test dispatch are not implemented here')


C.DESIGN, C.design = HERE / 'design.json', design
C.module, C.save, C.preflight = runner_module, save_main, submission_preflight
C.check_prediction_freeze = reject_test


def activation():
    d = design(); source = sources()
    if C.sha(AUTH) != AUTH_SHA:
        raise ValueError('Explicit autonomy authorization changed')
    auth = read(AUTH)
    accepted = read(ACCEPTANCE)
    result_path = repo(d['activation']['requires_probe_result'])
    result = read(result_path)
    if (accepted.get('schema') != 'dram-see-v3-r50-main-activation-acceptance' or accepted.get('approved') is not True
            or accepted.get('design_sha256') != DESIGN_SHA or accepted.get('probe_result_sha256') != C.sha(result_path)
            or accepted.get('source_manifest_sha256') != C.sha(HERE / 'source-manifest.json')
            or not accepted.get('accepted_utc') or not accepted.get('evidence')
            or result.get('state') != 'THREE_PROBE_CASES_RAW_AUDIT_PASSED'):
        raise ValueError('Independent actual probe/source acceptance is absent or differs')
    datetime.fromisoformat(accepted['accepted_utc'].replace('Z', '+00:00'))
    probe_plan = result_path.with_name('plan.json')
    if result.get('plan_sha256') != C.sha(probe_plan) or read(probe_plan.with_name('plan-sha256.json')).get('sha256') != C.sha(probe_plan):
        raise ValueError('Probe result/plan binding changed')
    pp = read(probe_plan)
    for name, digest in {**pp['source_sha256'], **pp['frozen_files_sha256'], **result['source_files_sha256']}.items():
        if C.sha(repo(name)) != digest:
            raise ValueError('Actual probe source/evidence changed: ' + name)
    probes = accepted.get('probe_run_archives', {})
    if set(probes) != {'control', 'neutral', 'event'}:
        raise ValueError('All three individually accepted probe archives are required')
    ledger = C.load()
    original_path = repo(auth['snapshots']['local_runtime/dram-see-v3/ledger.json']['snapshot'])
    if C.sha(original_path) != auth['snapshots']['local_runtime/dram-see-v3/ledger.json']['sha256']:
        raise ValueError('Original 43-row authorization snapshot changed')
    original = read(original_path)
    if len(original['runs']) != 43:
        raise ValueError('Unexpected original protected population')
    allowed = {'v3-r50-probe-r1-' + role for role in ('control', 'neutral', 'event')} | {case['tag'] for case in cases(d)}
    ledger_unchanged(original, ledger, allowed)
    bound = {rel(AUTH): C.sha(AUTH), rel(ACCEPTANCE): C.sha(ACCEPTANCE), rel(result_path): C.sha(result_path), rel(probe_plan): C.sha(probe_plan)}
    for role, expected in probes.items():
        tag = 'v3-r50-probe-r1-' + role
        row = ledger['runs'].get(tag, {})
        case_result = result.get('cases', {}).get(tag, {})
        if (row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0 or row.get('run_id') != expected.get('run_id')
                or case_result.get('run_id') != row.get('run_id') or case_result.get('raw_audit_state') != 'PASSED'):
            raise ValueError('Probe row/result is not a passed matching archive')
        summary = PA.audit(row['run_id'], export=False)
        if (summary['archive_sha256'] != expected.get('archive_sha256') or summary['archive_sha256'] != row.get('audit_archive_sha256')
                or summary['archive_sha256'] != case_result.get('archive_sha256') or summary['parameters'] != row.get('parameters')
                or summary['input_sha256'] != row.get('input_sha256')):
            raise ValueError('Independently accepted probe archive hash differs')
        p = summary['parameters']
        if p.get('neutral') != (role == 'neutral') or bool(p.get('source_event')) != (role == 'event'):
            raise ValueError('Accepted probe archive role differs')
        for name in ('manifest.json', 'inputs.tar', 'results.tar'):
            file = PA.run_folder(row['run_id']) / name
            bound[rel(file)] = C.sha(file)
    return auth, accepted, bound, source


def train_event_files(d):
    files = {}
    for event in d['events']:
        if event['split'] != 'train':
            continue
        path = event_path(event)
        E.validate_event(path, {key: event[key] for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'energy_MeV')})
        for name in ('event.json', 'steps.csv', 'events.csv'):
            file = path.parent / name
            files[rel(file)] = C.sha(file)
    if len(files) != 96:
        raise ValueError('Training transport must cover exactly 32 immutable events')
    return files


def reject_unplanned_archives(d):
    """Check actual input metadata, never infer model identity from old tag text."""
    planned = {case['tag'] for case in cases(d)}
    for manifest_path in (ROOT / 'local_runtime/runs').glob('*/manifest.json'):
        archive = manifest_path.parent / 'inputs.tar'
        if not archive.exists():
            continue
        with tarfile.open(archive) as tf:
            members = [m for m in tf.getmembers() if Path(m.name).name == 'parameters.json' and m.isfile()]
            if not members:
                continue
            if len(members) != 1:
                raise ValueError('Ambiguous actual run input metadata')
            p = json.loads(tf.extractfile(members[0]).read())
        if p.get('schema') == SCHEMA or p.get('physical_revision') == REVISION:
            if p.get('schema') != SCHEMA or p.get('physical_revision') != REVISION or p.get('physical_revision_probe_only') is not False:
                raise ValueError('Inconsistent actual R50-main archive identity')
            matches = [tag for tag, row in C.load()['runs'].items() if row.get('run_id') == manifest_path.parent.name]
            if len(matches) != 1 or matches[0] not in planned:
                raise ValueError('Unreconciled/unplanned actual R50-main attempt')
            if p.get('source_event') and p.get('gate_length_um') in (.25, .45):
                raise ValueError('Actual R50-main test submission exists before prediction implementation/freeze')


def freeze(label='r1'):
    path = directory(label) / 'plan.json'
    with C.controller_lock():
        if path.exists():
            check_plan(path)
            return {'state': 'FROZEN_EXISTING', 'plan_sha256': C.sha(path), 'new_submissions': 0}
        if path.parent.exists():
            raise ValueError('Partial R50-main freeze exists; preserve and reconcile')
        auth, accepted, frozen, source = activation()
        deadline(auth); C.budget(); C.check_preservation()
        d = design(); reject_unplanned_archives(d)
        before = C.load()
        if len(before['runs']) != 46 or any(tag.startswith('v3-r50-main-') for tag in before['runs']):
            raise ValueError('Expected exact 43 original plus three accepted probe records before first freeze')
        frozen.update(train_event_files(d))
        for name, digest in source.items():
            output = path.parent / 'source-snapshot' / name
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open('xb') as stream:
                stream.write(repo(name).read_bytes())
            if C.sha(output) != digest:
                raise ValueError('Source changed while freezing')
        before_path = path.parent / 'ledger-before.json'
        C.write_json(before_path, before, exclusive=True)
        plan = {'schema': 'dram-see-v3-r50-main-execution-plan', 'physical_revision': REVISION, 'label': label, 'utc': C.now(),
            'design_sha256': DESIGN_SHA, 'source_sha256': source, 'inputs': {}, 'frozen_files_sha256': frozen,
            'ledger_before': rel(before_path), 'ledger_before_sha256': C.sha(before_path), 'planned_cases': cases(d),
            'stage_order': list(STAGES), 'global_budget_s': 86400, 'new_submission_deadline_utc': '2026-10-11T04:37:00Z',
            'fixed_main_independent_events': 64, 'fixed_main_response_slots': 128,
            'implemented_terminal_state': 'TRAINING_FINISHED_PENDING_PREDICTION', 'later_stages_implemented': False,
            'acceptance': accepted, 'maximum_new_solver_calls_this_segment': 92}
        C.write_json(path, plan, exclusive=True)
        C.write_json(path.with_name('plan-sha256.json'), {'sha256': C.sha(path)}, exclusive=True)
        check_plan(path)
        return {'state': 'FROZEN', 'plan': rel(path), 'plan_sha256': C.sha(path), 'new_submissions': 0}


def check_plan(path):
    path = Path(path)
    if read(path.with_name('plan-sha256.json')).get('sha256') != C.sha(path):
        raise ValueError('Execution plan self-hash changed')
    plan = C.check_execution(path)
    if (path != directory(plan['label']) / 'plan.json' or plan.get('schema') != 'dram-see-v3-r50-main-execution-plan'
            or plan.get('physical_revision') != REVISION or plan.get('source_sha256') != sources()
            or plan.get('planned_cases') != cases() or plan.get('stage_order') != list(STAGES)
            or plan.get('global_budget_s') != 86400 or plan.get('maximum_new_solver_calls_this_segment') != 92
            or plan.get('implemented_terminal_state') != 'TRAINING_FINISHED_PENDING_PREDICTION' or plan.get('later_stages_implemented') is not False):
        raise ValueError('Execution version/recipe/scope differs')
    for name, digest in plan['source_sha256'].items():
        if C.sha(path.parent / 'source-snapshot' / name) != digest:
            raise ValueError('Frozen source snapshot changed')
    for name, digest in plan['frozen_files_sha256'].items():
        if C.sha(repo(name)) != digest:
            raise ValueError('Frozen acceptance/event/archive evidence changed: ' + name)
    before_file = repo(plan['ledger_before'])
    if C.sha(before_file) != plan['ledger_before_sha256']:
        raise ValueError('Protected original ledger snapshot changed')
    ledger_unchanged(read(before_file), C.load(), {case['tag'] for case in plan['planned_cases']})
    return plan


def reserve(plan, case):
    window = deadline()
    used = C.budget()
    costs = [row.get('charged_solver_s', row.get('elapsed_s', 0)) for row in C.load()['runs'].values() if not row.get('inherited')]
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in costs + [used]):
        raise ValueError('Invalid global cost accounting')
    if used + case['estimate_s'] > 86400:
        raise RuntimeError('Global budget insufficient for the next fixed item; retain all unsubmitted slots')
    by_tag = {item['tag']: item for item in plan['planned_cases']}
    for tag, row in C.load()['runs'].items():
        if tag in by_tag and row.get('charged_solver_s', row.get('elapsed_s', 0)) > by_tag[tag]['estimate_s']:
            raise RuntimeError('Actual run exceeded its frozen reserve; safe-boundary versioned estimate review required')
    return {**window, 'global_solver_s_before': used, 'next_estimate_s': case['estimate_s']}


def recipe(case, p, parent):
    kw = {'length': .25, 'bit': 1, 'neutral': False, 'step': 1., 'mesh': 1., 'reference': 'offline', **case['kwargs']}
    expected = {'schema': SCHEMA, 'physical_revision': REVISION, 'physical_revision_probe_only': False,
        'gate_length_um': kw['length'], 'stored_bit': None if kw['neutral'] else kw['bit'], 'neutral': kw['neutral'],
        'step_scale': kw['step'], 'mesh_scale': kw['mesh'], 'oxide_nm': 5., 'reference_mode': kw['reference'],
        'source_event': kw.get('event'), 'parent_run': parent, 'precharge_resistance_on_ohm': 50,
        'target_voltage_V': .5 if kw['neutral'] else .1 if kw['bit'] == 0 else .9}
    if any(p.get(key) != value for key, value in expected.items()):
        raise ValueError('Prepared/archive parameters differ from exact frozen case')
    A.matching_key(p)
    if case['event']:
        event = case['event']
        if any(p.get(key) != event[key] for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'energy_MeV')):
            raise ValueError('Particle identity differs from fixed event')
        source = {'source-event.json': C.sha(event_path(event)), 'source-steps.csv': C.sha(event_path(event).parent / 'steps.csv'), 'source-events.csv': C.sha(event_path(event).parent / 'events.csv')}
        if p.get('source_evidence_sha256') != source:
            raise ValueError('Particle source bytes differ')
    elif p.get('charge_pc') != 0 or p.get('particle') or p.get('source_evidence_sha256'):
        raise ValueError('Unirradiated case has a particle source')


def case_file(path, case):
    return Path(path).parent / 'case-freezes' / (case['tag'] + '.json')


def case_checked(path, case, row=None):
    frozen = case_file(path, case)
    execution = C.check_execution(frozen)
    plan = read(path)
    if (execution.get('main_plan_sha256') != C.sha(path) or execution.get('main_plan') != rel(path)
            or execution.get('case') != case or execution.get('source_sha256') != plan['source_sha256']
            or set(execution['inputs']) != {case['tag']}):
        raise ValueError('Case is not bound to exact accepted plan/source/inputs')
    if row is not None and (row.get('execution_freeze') != rel(frozen) or row.get('execution_freeze_sha256') != C.sha(frozen)
            or row.get('input_sha256') != execution['inputs'][case['tag']] or row.get('physical_revision') != REVISION
            or row.get('physical_revision_probe_only') is not False):
        raise ValueError('Existing case provenance or model identity differs')
    return frozen


def bundle(tag):
    row = C.load()['runs'].get(tag, {})
    if row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0:
        raise ValueError('Required R50-main raw archive is not verified: ' + tag)
    if (row.get('continuous_numeric_valid') is False or row.get('continuous_numerical_status') not in
            (None, 'RAW_AUDIT_PASSED', 'MATCHED_REFINEMENT_PASSED', 'PASSED')):
        raise ValueError('Explicit continuous numerical failure/unknown status blocks dependent training: ' + tag)
    rid = row['run_id']; folder = A.run_folder(rid)
    hashes = tuple(C.sha(folder / name) for name in ('manifest.json', 'inputs.tar', 'results.tar'))
    key = (rid, *hashes)
    if key not in BUNDLES:
        BUNDLES[key] = A.load_curves(rid)
    value = BUNDLES[key]
    if (value['parameters'] != row.get('parameters') or value['summary']['archive_sha256'] != row.get('audit_archive_sha256')
            or value['summary']['input_sha256'] != row.get('input_sha256')):
        raise ValueError('Global record and actual archive provenance differ')
    return value


def matching(tags):
    values = [bundle(tag) for tag in tags]
    if not values:
        return
    keys = [A.matching_key(value['parameters']) for value in values]
    meshes = [value['summary']['mesh_sha256'] for value in values]
    if any(key != keys[0] for key in keys) or len(set(meshes)) != 1:
        raise ValueError('Actual matching geometry/mesh/complete R50-main contract differs')


def immutable(path, value):
    path = Path(path)
    if path.exists():
        if read(path) != value:
            raise ValueError('Immutable stage evidence differs: ' + rel(path))
    else:
        C.write_json(path, value, exclusive=True)
    return {'evidence': rel(path), 'evidence_sha256': C.sha(path)}


def observation(signal, control, neutral):
    values = {role: bundle(tag) for role, tag in zip(('signal', 'control', 'neutral'), (signal, control, neutral))}
    return {'metrics': M.compute_curves(*(values[role] for role in ('signal', 'control', 'neutral'))),
        'readout_BL_V': {role: A.sample(value['circuit'], 'v(bl)', 4e-9) for role, value in values.items()}}


def finish_case(path, case):
    row = C.load()['runs'][case['tag']]
    parent = C.resolve(case['parent_tag']) if case['parent_tag'] else None
    case_checked(path, case, row)
    value = bundle(case['tag']); recipe(case, value['parameters'], parent)
    matching([case['tag'], *case['matching_tags']])
    result = {'state': 'VERIFIED', 'raw_audit_state': 'PASSED', 'run_id': row['run_id'], 'archive_sha256': value['summary']['archive_sha256']}
    if case['role'] == 'physical':
        comparison = M.compare_physical_curves(value, bundle(case['offline_tag']), bundle(neutral_tag(case['kwargs']['length'])))
        result.update(immutable(HERE / 'data/reference-validation' / (case['tag'] + '.json'), comparison))
        if not comparison['passed']:
            raise ValueError('R50-main physical/offline reference comparison failed; stop all dependent cases')
    elif case['role'] == 'event':
        comparison = M.compute_curves(value, *(bundle(tag) for tag in case['matching_tags']))
        result.update(immutable(HERE / 'data/metrics' / (case['tag'] + '.json'), comparison))
    return result


def finish_stage(path, plan, stage, records):
    stage_cases = [case for case in plan['planned_cases'] if case['stage'] == stage]
    evidence = {'schema': 'dram-see-v3-r50-main-stage', 'physical_revision': REVISION, 'stage': stage,
        'state': 'VERIFIED', 'plan_sha256': C.sha(path), 'design_sha256': DESIGN_SHA,
        'cases': {case['tag']: records[case['tag']] for case in stage_cases}}
    if stage == 'numerical_preregistered':
        d = design(); event = target_event(d); bit = d['numerical']['preregistered']['stored_bit']; length = event['gate_length_um']
        baseline = observation(event_tag(event, bit), control_tag(length, bit), neutral_tag(length))
        comparisons = []
        for variation in d['numerical']['variations']:
            step, mesh = variation['step'], variation['mesh']
            refined = observation(refined_tag(event, bit, step, mesh), control_tag(length, bit, step, mesh), neutral_tag(length, step, mesh))
            comparisons.append({'response_id': event_tag(event, bit), 'event': event, 'stored_bit': bit, 'variation': variation,
                **N.compare_observations(baseline, refined, tuple(x / 1000 for x in d['thresholds_mV']),
                    d['gates']['numerical_readout_change_mV'] / 1000, d['gates']['numerical_deltaQ_change_fC'])})
        passed = all(row['continuous_passed'] for row in comparisons)
        report = {'schema': 'dram-see-v3-r50-main-numerical-validation', 'physical_revision': REVISION,
            'state': 'VERIFIED' if passed else 'NUMERICAL_FAILED', 'continuous_passed': passed,
            'classification_stable': all(row['classification_stable'] for row in comparisons), 'comparisons': comparisons,
            'plan_sha256': C.sha(path), 'design_sha256': DESIGN_SHA, 'new_independent_events': 0}
        evidence.update(immutable(HERE / 'data/numerical/preregistered.json', report))
        evidence.update(state=report['state'], continuous_passed=passed, classification_stable=report['classification_stable'])
    if stage == 'train':
        training = [event_tag(e, bit) for e in design()['events'] if e['split'] == 'train' for bit in (0, 1)]
        if len(training) != 64 or any(records.get(tag, {}).get('state') != 'VERIFIED' for tag in training):
            raise ValueError('All exact 64 fresh R50-main training responses required')
        evidence['training_response_ids'] = training
        evidence['training_independent_events'] = 32
        evidence['training_responses'] = 64
    pointer = immutable(path.parent / 'stages' / (stage + '.json'), evidence)
    index_path = path.parent / 'stage-index.json'
    index = read(index_path) if index_path.exists() else {'schema': 'dram-see-v3-r50-main-stage-index', 'physical_revision': REVISION,
        'plan_sha256': C.sha(path), 'stages': {}, 'accounting': 'References only; unique global ledger is the sole solver-cost truth'}
    if index.get('plan_sha256') != C.sha(path) or index.get('physical_revision') != REVISION:
        raise ValueError('Independent stage index has wrong execution identity')
    entry = {'state': evidence['state'], **pointer, 'run_ids': [records[case['tag']]['run_id'] for case in stage_cases]}
    if stage == 'numerical_preregistered':
        entry.update(continuous_passed=evidence['continuous_passed'], classification_stable=evidence['classification_stable'])
    if stage in index['stages'] and index['stages'][stage] != entry:
        raise ValueError('Completed stage index changed')
    index['stages'][stage] = entry
    C.write_json(index_path, index)
    if evidence['state'] != 'VERIFIED':
        raise ValueError('Preregistered continuous tolerance failed; training expansion remains blocked')


def progress(path, state, records, reason=None):
    ledger = C.load(); d = design()
    C.write_json(path.parent / 'status.json', {'schema': 'dram-see-v3-r50-main-progress', 'physical_revision': REVISION,
        'utc': C.now(), **CONTEXT, 'state': state, 'reason': reason, 'plan_sha256': C.sha(path),
        'fixed_independent_events': 64, 'fixed_paired_responses': 128, 'later_stages_implemented': False,
        'cases': [{**case, 'ledger_state': ledger['runs'].get(case['tag'], {}).get('state', 'UNSUBMITTED'),
            'run_id': ledger['runs'].get(case['tag'], {}).get('run_id'), **records.get(case['tag'], {})} for case in cases(d)],
        'main_response_slots': [{'response_id': event_tag(e, bit), 'event_label': e['label'], 'stored_bit': bit, 'split': e['split'],
            'state': ledger['runs'].get(event_tag(e, bit), {}).get('state', 'UNSUBMITTED')} for e in d['events'] for bit in (0, 1)]})


def execute(label='r1'):
    global BEFORE
    path = directory(label) / 'plan.json'
    if not path.is_file():
        raise ValueError('Execution requires the independently accepted immutable plan')
    records = {}
    with C.controller_lock():
        CONTEXT.update(controller_pid=os.getpid(), controller_parent_pid=os.getppid(), controller_started_utc=C.now(), current_case=None, current_stage=None)
        try:
            plan = check_plan(path); BEFORE = read(repo(plan['ledger_before']))
            activation(); reject_unplanned_archives(design())
            C.check_preservation(); C.budget()
            progress(path, 'CHECKING_PREREQUISITES', records)
            BASE_PREFLIGHT('r50-main-' + label)  # read-only reconciliation even after deadline
            for stage in STAGES:
                CONTEXT['current_stage'] = stage
                for case in (case for case in plan['planned_cases'] if case['stage'] == stage):
                    check_plan(path); tag = case['tag']; CONTEXT['current_case'] = tag
                    parent = C.resolve(case['parent_tag']) if case['parent_tag'] else None
                    matching(case['matching_tags'])
                    row = C.load()['runs'].get(tag)
                    if row is not None and row.get('state') != 'VERIFIED':
                        raise ValueError('Prior FAILED/unsettled attempt is never retried: ' + tag)
                    if row is None:
                        reservation = reserve(plan, case)
                        execution = case_file(path, case)
                        if execution.exists():
                            case_checked(path, case)
                        else:
                            kwargs = dict(case['kwargs'])
                            if parent:
                                kwargs['parent'] = parent
                            inputs = C.prepare(tag, **kwargs)
                            recipe(case, read(LOCAL / 'inputs' / tag / 'parameters.json'), parent)
                            C.write_json(execution, {'utc': C.now(), 'design_sha256': DESIGN_SHA, 'source_sha256': plan['source_sha256'],
                                'inputs': {tag: inputs}, 'main_plan': rel(path), 'main_plan_sha256': C.sha(path), 'case': case,
                                'physical_revision': REVISION, 'reservation': reservation}, exclusive=True)
                        recipe(case, read(LOCAL / 'inputs' / tag / 'parameters.json'), parent)
                        check_plan(path); reserve(plan, case)
                        progress(path, 'SUBMITTING_CASE', records)
                        C.record(tag, execution, estimate_s=case['estimate_s'])
                    records[tag] = finish_case(path, case)
                    progress(path, 'STAGE_IN_PROGRESS', records)
                finish_stage(path, plan, stage, records)
                check_plan(path)
                progress(path, 'STAGE_VERIFIED', records)
            CONTEXT['current_case'] = None
            progress(path, 'TRAINING_FINISHED_PENDING_PREDICTION', records)
            return {'state': 'TRAINING_FINISHED_PENDING_PREDICTION', 'training_responses': 64,
                'training_independent_events': 32, 'test_responses_submitted': 0, 'new_prediction_freeze': False,
                'remaining_main_slots': 64, 'global_solver_s': C.budget()}
        except Exception as exc:
            tag = CONTEXT.get('current_case'); row = C.load()['runs'].get(tag, {})
            if tag:
                records[tag] = {'state': 'GATE_OR_PROVENANCE_FAILED' if row.get('state') == 'VERIFIED' else row.get('state', 'UNSUBMITTED'),
                    'ledger_state': row.get('state', 'UNSUBMITTED'), 'run_id': row.get('run_id'), 'error': repr(exc)}
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
