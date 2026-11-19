"""R50-main post-test oxide and fixed complete-population boundary validation.

All earlier modules stay byte-identical. The prediction guard has an explicit
read-only role adapter: deterministic extension archives cannot be mistaken for
the 64 original test responses. No scoring/model fitting occurs in this module.
"""
import argparse
import ast
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
LOCAL = ROOT / 'local_runtime/dram-see-v3'
RUNTIME = LOCAL / 'physical-revisions/r50-main-extensions-r1'
ACCEPTANCE = LOCAL / 'physical-revisions/r50-main-extensions-r1-acceptance.json'
BEFORE = None
CONTEXT = {}
LOADED = {}


def module(name, path):
    content = Path(path).read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    exec(compile(content, str(path), 'exec'), value.__dict__)
    LOADED[Path(path).resolve().relative_to(ROOT).as_posix()] = hashlib.sha256(content).hexdigest()
    return value


F = module('_r50_extensions_followup', HERE / 'finish.py')
R = F.R
C = module('_r50_extensions_original_runner', BASE / 'run.py')
read, rel, repo = R.read, R.rel, R.repo
BASE_SAVE = C.save
LOADED[Path(__file__).resolve().relative_to(ROOT).as_posix()] = C.sha(__file__)
# The registered selector is loaded as exactly one original pure function.
# Its arithmetic helper is the unchanged version in the first numerical module.
selector_path = BASE / 'numerical.py'
selector_node = next(n for n in ast.parse(selector_path.read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == 'boundary_ranking')
selector_scope = {'_number': R.N._number}
exec(compile(ast.Module(body=[selector_node], type_ignores=[]), str(selector_path), 'exec'), selector_scope)
boundary_ranking = selector_scope['boundary_ranking']


def directory(label='r1'):
    if label != 'r1':
        raise ValueError('Only the accepted extension r1 is implemented')
    return RUNTIME


def sources():
    files = {**F.sources(), rel(Path(__file__)): C.sha(__file__)}
    manifest = read(HERE / 'extensions-source-manifest.json')
    if manifest.get('schema') != 'dram-see-v3-r50-main-extensions-source-manifest' or manifest.get('files_sha256') != files:
        raise ValueError('Extension fixed source manifest changed')
    for name, digest in LOADED.items():
        if files.get(name) != digest:
            raise ValueError('Loaded extension source differs from frozen bytes')
    return {**files, rel(HERE / 'extensions-source-manifest.json'): C.sha(HERE / 'extensions-source-manifest.json')}


def oxide_events(d):
    ext = d['oxide_extension']
    return [next(e for e in d['events'] if e['gate_length_um'] == ext['length_um'] and e['particle'] == particle
        and e['angle_deg'] == ext['angle_deg'] and e['replicate'] == ext['replicate']) for particle in ext['particles']]


def oxide_control(bit, thickness):
    return C.safe_tag(f'v3-r50-main-oxide-control-l025-b{bit}-ox{thickness:g}-s1-m1')


def oxide_neutral(thickness):
    return C.safe_tag(f'v3-r50-main-oxide-neutral-l025-ox{thickness:g}-s1-m1')


def oxide_tag(event, bit, thickness):
    return C.safe_tag(f'v3-r50-main-oxide-{event["label"]}-b{bit}-ox{thickness:g}')


def cases(selection, d=None):
    d = R.design() if d is None else d
    if (selection.get('selection_status') != 'FROZEN' or selection.get('population_count') != 128
            or len(selection.get('selected', [])) != 2
            or len({row['response_id'] for row in selection['selected']}) != 2):
        raise ValueError('Boundary cases require two unique selections from the complete frozen main population')
    result = []
    for thickness in d['oxide_extension']['oxide_nm']:
        if thickness == d['oxide_extension']['baseline_nm']:
            continue
        for bit in (0, 1):
            result.append({'tag': oxide_control(bit, thickness), 'stage': 'oxide', 'role': 'control',
                'kwargs': {'length': .25, 'bit': bit, 'oxide_nm': thickness}, 'event': None,
                'parent_tag': None, 'matching_tags': [], 'estimate_s': 600})
        result.append({'tag': oxide_neutral(thickness), 'stage': 'oxide', 'role': 'neutral',
            'kwargs': {'length': .25, 'neutral': True, 'oxide_nm': thickness}, 'event': None,
            'parent_tag': None, 'matching_tags': [], 'estimate_s': 600})
        for event in oxide_events(d):
            for bit in (0, 1):
                result.append({'tag': oxide_tag(event, bit, thickness), 'stage': 'oxide', 'role': 'event', 'event': event,
                    'kwargs': {'length': .25, 'bit': bit, 'oxide_nm': thickness, 'event': rel(R.event_path(event))},
                    'parent_tag': oxide_control(bit, thickness), 'matching_tags': [oxide_control(bit, thickness), oxide_neutral(thickness)],
                    'estimate_s': 600})
    boundary = {}
    for selected in selection['selected']:
        event, bit = selected['event'], selected['stored_bit']; length = event['gate_length_um']
        for variation in d['numerical']['variations']:
            step, mesh = variation['step'], variation['mesh']
            control, neutral = R.control_tag(length, bit, step, mesh), R.neutral_tag(length, step, mesh)
            common = {'length': length, 'step': step, 'mesh': mesh}
            for tag, role, kwargs, parent, matching, source in (
                (control, 'control', {**common, 'bit': bit}, None, [], None),
                (neutral, 'neutral', {**common, 'neutral': True}, None, [], None),
                (R.refined_tag(event, bit, step, mesh), 'event', {**common, 'bit': bit, 'event': rel(R.event_path(event))}, control, [control, neutral], event)):
                case = {'tag': tag, 'stage': 'boundary', 'role': role, 'kwargs': kwargs, 'parent_tag': parent,
                    'matching_tags': matching, 'event': source, 'estimate_s': 900}
                if tag in boundary and boundary[tag] != case:
                    raise ValueError('Conflicting shared boundary prerequisites')
                boundary[tag] = case
    if len(result) != 14 or len(selection.get('selected', [])) != 2 or len(boundary) > 12:
        raise ValueError('Extension count differs from fixed design')
    result += list(boundary.values())
    if len({case['tag'] for case in result}) != len(result):
        raise ValueError('Duplicate extension run tag')
    return result


def recipe(case, p, parent):
    kw = {'length': .25, 'bit': 1, 'neutral': False, 'step': 1., 'mesh': 1., 'oxide_nm': 5., **case['kwargs']}
    expected = {'schema': R.SCHEMA, 'physical_revision': R.REVISION, 'physical_revision_probe_only': False,
        'gate_length_um': kw['length'], 'stored_bit': None if kw['neutral'] else kw['bit'], 'neutral': kw['neutral'],
        'step_scale': kw['step'], 'mesh_scale': kw['mesh'], 'oxide_nm': kw['oxide_nm'], 'reference_mode': 'offline',
        'source_event': kw.get('event'), 'parent_run': parent, 'precharge_resistance_on_ohm': 50,
        'target_voltage_V': .5 if kw['neutral'] else .1 if kw['bit'] == 0 else .9}
    if any(p.get(key) != value for key, value in expected.items()):
        raise ValueError('Extension actual parameters differ from frozen recipe')
    R.A.matching_key(p)
    if case['event']:
        event = case['event']
        if any(p.get(key) != event[key] for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'energy_MeV')):
            raise ValueError('Extension event identity differs')
        expected_source = {'source-event.json': C.sha(R.event_path(event)),
            'source-steps.csv': C.sha(R.event_path(event).parent / 'steps.csv'), 'source-events.csv': C.sha(R.event_path(event).parent / 'events.csv')}
        if p.get('source_evidence_sha256') != expected_source:
            raise ValueError('Extension source bytes differ from original fixed event')
    elif p.get('charge_pc') != 0 or p.get('source_event') or p.get('particle') or p.get('source_evidence_sha256'):
        raise ValueError('Extension control/neutral has a particle')


def host_guard():
    F.host_guard()
    command = "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw)\\.exe$' } | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True, text=True, check=True)
    rows = json.loads(result.stdout) if result.stdout.strip() else []
    for row in [rows] if isinstance(rows, dict) else rows:
        pid, cmd = row['ProcessId'], (row.get('CommandLine') or '').replace('\\', '/').lower()
        if pid == os.getpid() or (pid == os.getppid() and all(str(arg).replace('\\', '/').lower() in cmd for arg in sys.argv)):
            continue
        if 'r50-main/extensions.py' in cmd:
            raise RuntimeError('Another extensions controller has not exited')


def main_test_attempts(frozen):
    """Explicit role adapter for the frozen followup's prediction guard.

Require all original test64. Additional extension inputs must match this exact
extension plan; never treat their deterministic reruns as extra test samples.
"""
    ledger = C.load(); main = {case['tag']: case for case in F.cases()}
    extras = {case['tag']: case for case in CONTEXT.get('planned_cases', [])}
    for tag, case in main.items():
        row = ledger['runs'].get(tag, {})
        if row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0:
            raise ValueError('Complete verified test64 is required for any extension')
        F.submitted_after_freeze(row, frozen)
        R.recipe(case, row['parameters'], C.resolve(case['parent_tag']))
    inspected = set()
    for item in F.actual_manifests():
        if not F.is_test(item['parameters']):
            continue
        tags = [tag for tag, row in ledger['runs'].items() if row.get('run_id') == item['run_id']]
        if len(tags) != 1 or ledger['runs'][tags[0]].get('parameters') != item['parameters']:
            raise ValueError('Unknown actual test/extension input archive')
        tag = tags[0]
        if tag in main:
            inspected.add(tag)
        elif tag in extras:
            case = extras[tag]
            row = ledger['runs'][tag]
            if row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0:
                raise ValueError('Unsettled/failed extension blocks further dispatch')
            recipe(case, item['parameters'], C.resolve(case['parent_tag']) if case['parent_tag'] else None)
        else:
            raise ValueError('Non-main input is not in the accepted deterministic extension plan')
    if inspected != set(main):
        raise ValueError('Some test responses lack actual matching input archives')


# This adapter changes only this imported module namespace. Frozen source files
# and old data remain unchanged; all model/provenance checks still execute.
F.existing_test_attempts = main_test_attempts
C.DESIGN, C.design, C.module = HERE / 'design.json', R.design, R.runner_module
C.check_prediction_freeze = F.check_prediction


def submission_preflight(tag):
    R.deadline(); host_guard(); result = R.BASE_PREFLIGHT(tag); R.deadline()
    return result


def save_extensions(ledger):
    if BEFORE is None:
        raise ValueError('No accepted extension write authority')
    allowed = {case['tag'] for case in CONTEXT['planned_cases']}
    for tag, row in ledger['runs'].items():
        if tag not in BEFORE['runs']:
            if tag not in allowed:
                raise ValueError('Non-plan extension ledger write')
            row.update(physical_revision=R.REVISION, physical_revision_probe_only=False,
                original_100ohm_matrix_eligible=False, deterministic_extension_only=True, new_independent_event=False)
    R.ledger_unchanged(BEFORE, ledger, allowed)
    BASE_SAVE(ledger)


C.save, C.preflight = save_extensions, submission_preflight


def main_observation(event, bit):
    length = event['gate_length_um']
    return R.observation(R.event_tag(event, bit), R.control_tag(length, bit), R.neutral_tag(length))


def prerequisites():
    """Only called before first extension freeze, while no extension exists."""
    proof = F.checked_training(); files = proof['files']; path = F.directory() / 'plan.json'
    followup = F.check_plan(path); F.bind(path, files)
    F.bind(path.with_name('plan-sha256.json'), files)
    for name, digest in followup['frozen_files_sha256'].items():
        if C.sha(repo(name)) != digest:
            raise ValueError('Followup prerequisite evidence changed')
        files[name] = digest
    frozen = F.check_prediction(); prediction_path = HERE / 'data/predictions/freeze.json'
    files.update(frozen['files_sha256']); F.bind(prediction_path, files)
    files[rel(prediction_path.with_name('freeze.sha256'))] = C.sha(prediction_path.with_name('freeze.sha256'))
    F.bind(path.parent / 'prediction-binding.json', files)
    status = read(path.parent / 'status.json')
    if status.get('state') != 'TEST_FINISHED_PENDING_EXTENSIONS':
        raise ValueError('Followup has not actually completed test64')
    original_result = F.bind(path.parent / 'test-result.json', files)
    if (original_result.get('state') != 'TEST_FINISHED_PENDING_EXTENSIONS' or original_result.get('plan_sha256') != C.sha(path)
            or original_result.get('prediction_freeze_sha256') != C.sha(prediction_path) or original_result.get('test_responses') != 64):
        raise ValueError('Actual followup completion evidence differs')
    observed = []
    for case in F.cases():
        tag = case['tag']; row = C.load()['runs'][tag]
        F.case_checked(path, case, row); F.bind(repo(row['execution_freeze']), files)
        F.submitted_after_freeze(row, frozen)
        value = R.bundle(tag); F.bind_bundle(value, files)
        R.recipe(case, value['parameters'], C.resolve(case['parent_tag']))
        metrics = R.M.compute_curves(value, *(R.bundle(t) for t in case['matching_tags']))
        metric_path = HERE / 'data/metrics' / (tag + '.json')
        if F.bind(metric_path, files) != metrics:
            raise ValueError('Original test metric differs from audited raw archive')
        observed.append({'event_label': case['event']['label'], 'stored_bit': case['kwargs']['bit'], 'continuous_valid': True,
            'continuous_numerical_status': 'RAW_AUDIT_PASSED', 'targets': {'deltaQ_fC': metrics['deltaQ_fC'], 'deltaM_mV': metrics['deltaM_V'] * 1000},
            'classification': metrics['classification'], 'sources': metrics['sources']})
    if original_result.get('observations') != observed:
        raise ValueError('Original test result no longer matches actual archives')
    score_path = HERE / 'data/prediction-scores.json'
    score = F.P.score_predictions(read(HERE / 'data/predictions/predictions.json'), observed, R.design())
    if F.bind(score_path, files) != score or original_result.get('evidence_sha256') != C.sha(score_path):
        raise ValueError('Frozen-model test scores differ')
    population, baseline = [], {}
    for event in R.design()['events']:
        for bit in (0, 1):
            tag = R.event_tag(event, bit); obs = main_observation(event, bit); baseline[tag] = obs
            population.append({'response_id': tag, 'event': event, 'stored_bit': bit, 'state': 'VERIFIED',
                'M4_V': obs['metrics']['M4_V'], 'metric_sources': obs['metrics']['sources']})
    if len(population) != 128:
        raise ValueError('Selection requires exactly the complete 128 main responses')
    d = R.design(); selection = boundary_ranking(population, d['numerical']['additional_count'], tuple(x / 1000 for x in d['thresholds_mV']))
    if selection['selection_status'] != 'FROZEN' or selection['population_count'] != 128:
        raise ValueError('Complete original boundary selection unavailable')
    return {'files': files, 'baseline': baseline, 'selection': selection, 'first_plan_sha256': proof['first_plan_sha256'],
        'followup_plan_sha256': C.sha(path), 'test_result_sha256': C.sha(path.parent / 'test-result.json'),
        'prediction_freeze_sha256': C.sha(prediction_path)}


def acceptance():
    value = read(ACCEPTANCE)
    expected = {'schema': 'dram-see-v3-r50-main-extensions-acceptance', 'approved': True, 'design_sha256': R.DESIGN_SHA,
        'first_plan_sha256': C.sha(R.directory() / 'plan.json'), 'followup_plan_sha256': C.sha(F.directory() / 'plan.json'),
        'test_result_sha256': C.sha(F.directory() / 'test-result.json'), 'prediction_freeze_sha256': C.sha(HERE / 'data/predictions/freeze.json'),
        'source_manifest_sha256': C.sha(HERE / 'extensions-source-manifest.json')}
    if any(value.get(key) != expected_value for key, expected_value in expected.items()) or not value.get('accepted_utc') or not value.get('evidence'):
        raise ValueError('Independent actual extension activation/source acceptance is absent or differs')
    datetime.fromisoformat(value['accepted_utc'].replace('Z', '+00:00'))
    return value


def reused_case(case, row):
    """Only an exact first-segment preregistered role may be shared."""
    original = next((c for c in R.cases() if c['tag'] == case['tag'] and c['stage'] == 'numerical_preregistered'), None)
    if original is None or original['kwargs'] != case['kwargs'] or original['role'] != case['role'] or original['parent_tag'] != case['parent_tag']:
        raise ValueError('Existing case is not an exact registered reusable refinement')
    R.case_checked(R.directory() / 'plan.json', original, row)
    bundle = R.bundle(case['tag']); parent = C.resolve(case['parent_tag']) if case['parent_tag'] else None
    recipe(case, bundle['parameters'], parent); R.matching([case['tag'], *case['matching_tags']])
    return {'run_id': row['run_id'], 'archive_sha256': bundle['summary']['archive_sha256'],
        'execution_freeze': row['execution_freeze'], 'execution_freeze_sha256': row['execution_freeze_sha256'],
        'matching_contract_sha256': bundle['parameters']['matching_contract_sha256'], 'mesh_sha256': bundle['summary']['mesh_sha256'],
        'role': case['role'], 'reused': True, 'new_solver_charge_s': 0}


def freeze(label='r1'):
    path = directory(label) / 'plan.json'
    with C.controller_lock():
        if path.exists():
            check_plan(path); return {'state': 'FROZEN_EXISTING', 'new_submissions': 0, 'plan_sha256': C.sha(path)}
        if path.parent.exists():
            raise ValueError('Partial extension freeze exists; preserve and reconcile')
        sources_now = sources(); accepted = acceptance(); R.deadline(); host_guard(); C.budget(); C.check_preservation()
        proof = prerequisites(); planned = cases(proof['selection']); before_bytes = C.LEDGER.read_bytes(); before = json.loads(before_bytes)
        reused = {}
        for case in planned:
            if case['tag'] in before['runs']:
                reused[case['tag']] = reused_case(case, before['runs'][case['tag']])
        for name, digest in sources_now.items():
            target = path.parent / 'source-snapshot' / name; target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(repo(name).read_bytes())
            if C.sha(target) != digest:
                raise ValueError('Source changed while freezing extension')
        before_path = path.parent / 'ledger-before.json'
        with before_path.open('xb') as stream:
            stream.write(before_bytes)
        plan = {'schema': 'dram-see-v3-r50-main-extensions-plan', 'physical_revision': R.REVISION, 'label': label, 'utc': C.now(),
            'design_sha256': R.DESIGN_SHA, 'source_sha256': sources_now, 'inputs': {}, 'planned_cases': planned, 'reused_cases': reused,
            'frozen_files_sha256': {**proof['files'], rel(ACCEPTANCE): C.sha(ACCEPTANCE)}, 'baseline': proof['baseline'], 'selection': proof['selection'],
            'first_plan_sha256': proof['first_plan_sha256'], 'followup_plan_sha256': proof['followup_plan_sha256'],
            'test_result_sha256': proof['test_result_sha256'], 'prediction_freeze_sha256': proof['prediction_freeze_sha256'],
            'ledger_before': rel(before_path), 'ledger_before_sha256': C.sha(before_path), 'acceptance': accepted,
            'stage_order': ['oxide', 'boundary'], 'new_independent_events': 0, 'fixed_main_responses': 128,
            'new_solver_calls': len(planned) - len(reused), 'global_budget_s': 86400,
            'deadline_utc': '2026-10-11T04:37:00Z', 'terminal_state': 'SIMULATION_STAGES_FINISHED_PENDING_DELIVERY'}
        C.write_json(path, plan, exclusive=True); C.write_json(path.with_name('plan-sha256.json'), {'sha256': C.sha(path)}, exclusive=True)
        check_plan(path)
        return {'state': 'FROZEN', 'new_submissions': 0, 'plan_sha256': C.sha(path), 'planned_new_solver_calls': plan['new_solver_calls']}


def check_plan(path):
    path = Path(path); plan = C.check_execution(path)
    if (read(path.with_name('plan-sha256.json')).get('sha256') != C.sha(path) or path != directory(plan['label']) / 'plan.json'
            or plan.get('schema') != 'dram-see-v3-r50-main-extensions-plan' or plan.get('physical_revision') != R.REVISION
            or plan.get('source_sha256') != sources() or plan.get('planned_cases') != cases(plan['selection'])
            or plan.get('global_budget_s') != 86400 or plan.get('new_independent_events') != 0 or plan.get('fixed_main_responses') != 128
            or plan.get('stage_order') != ['oxide', 'boundary'] or plan.get('terminal_state') != 'SIMULATION_STAGES_FINISHED_PENDING_DELIVERY'):
        raise ValueError('Extension plan identity/source/recipe/scope changed')
    for name, digest in plan['source_sha256'].items():
        if C.sha(path.parent / 'source-snapshot' / name) != digest:
            raise ValueError('Extension source snapshot changed')
    for name, digest in plan['frozen_files_sha256'].items():
        if C.sha(repo(name)) != digest:
            raise ValueError('Frozen original main evidence changed: ' + name)
    if C.sha(repo(plan['ledger_before'])) != plan['ledger_before_sha256']:
        raise ValueError('Protected pre-extension ledger bytes changed')
    before = read(repo(plan['ledger_before']))
    R.ledger_unchanged(before, C.load(), {case['tag'] for case in plan['planned_cases']})
    wanted_reused = {case['tag'] for case in plan['planned_cases'] if case['tag'] in before['runs']}
    if set(plan['reused_cases']) != wanted_reused or plan['new_solver_calls'] != len(plan['planned_cases']) - len(wanted_reused):
        raise ValueError('Extension reuse/new-charge accounting differs')
    ordered_new = [case['tag'] for case in plan['planned_cases'] if case['tag'] not in wanted_reused]
    ledger = C.load()
    existing = [i for i, tag in enumerate(ordered_new) if tag in ledger['runs']]
    if existing != list(range(len(existing))):
        raise ValueError('Existing extension attempts are not a prefix of the fixed order')
    if any(ledger['runs'][ordered_new[i]].get('state') != 'VERIFIED' for i in existing):
        raise ValueError('Failed or unsettled extension attempt blocks further dispatch')
    return plan


def verify_frozen_prerequisites(plan):
    """After extensions exist, re-audit originals without changing old selectors."""
    d = R.design(); population = []
    for case in R.cases(d):
        value = R.bundle(case['tag'])
        R.case_checked(R.directory() / 'plan.json', case, C.load()['runs'][case['tag']])
        R.recipe(case, value['parameters'], C.resolve(case['parent_tag']) if case['parent_tag'] else None)
    frozen = F.check_prediction()
    for case in F.cases():
        row = C.load()['runs'][case['tag']]; value = R.bundle(case['tag'])
        F.case_checked(F.directory() / 'plan.json', case, row); F.submitted_after_freeze(row, frozen)
        R.recipe(case, value['parameters'], C.resolve(case['parent_tag']))
    for event in d['events']:
        for bit in (0, 1):
            identifier = R.event_tag(event, bit); observed = main_observation(event, bit)
            if observed != plan['baseline'][identifier]:
                raise ValueError('Frozen main observation changed during extension')
            population.append({'response_id': identifier, 'event': event, 'stored_bit': bit, 'state': 'VERIFIED',
                'M4_V': observed['metrics']['M4_V'], 'metric_sources': observed['metrics']['sources']})
    selection = boundary_ranking(population, d['numerical']['additional_count'], tuple(x / 1000 for x in d['thresholds_mV']))
    if selection != plan['selection']:
        raise ValueError('Frozen complete-population boundary ranking changed')


def reserve(plan, case):
    window = R.deadline(); used = C.budget()
    costs = [row.get('charged_solver_s', row.get('elapsed_s', 0)) for row in C.load()['runs'].values() if not row.get('inherited')]
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in costs + [used]):
        raise ValueError('Invalid global solver cost')
    if used + case['estimate_s'] > 86400:
        raise RuntimeError('Global budget insufficient for next fixed extension item')
    for item in plan['planned_cases']:
        if item['tag'] not in plan['reused_cases'] and C.load()['runs'].get(item['tag'], {}).get('charged_solver_s', 0) > item['estimate_s']:
            raise RuntimeError('Actual extension exceeded frozen reserve; versioned estimate review needed')
    return {**window, 'global_solver_s_before': used, 'next_estimate_s': case['estimate_s']}


def case_checked(path, case, row=None):
    frozen = path.parent / 'case-freezes' / (case['tag'] + '.json'); value = C.check_execution(frozen)
    if (value.get('extension_plan_sha256') != C.sha(path) or value.get('source_sha256') != read(path)['source_sha256']
            or value.get('case') != case or set(value['inputs']) != {case['tag']}
            or value.get('prediction_freeze_sha256') != read(path)['prediction_freeze_sha256']):
        raise ValueError('Case is not bound to exact extension plan/input/source')
    if row is not None and (row.get('execution_freeze') != rel(frozen) or row.get('execution_freeze_sha256') != C.sha(frozen)
            or row.get('input_sha256') != value['inputs'][case['tag']] or row.get('physical_revision') != R.REVISION
            or row.get('deterministic_extension_only') is not True):
        raise ValueError('Existing extension provenance/role changed')
    return frozen


def finish_oxide(path, plan):
    baseline, responses = [], []
    for event in oxide_events(R.design()):
        for bit in (0, 1):
            identifier = R.event_tag(event, bit); old = plan['baseline'][identifier]
            baseline.append({'response_id': identifier, 'event': event, 'stored_bit': bit, 'oxide_nm': 5., 'observation': old, 'reused': True})
            for thickness in (4., 6.):
                observed = R.observation(oxide_tag(event, bit, thickness), oxide_control(bit, thickness), oxide_neutral(thickness))
                if observed['metrics']['sources']['control']['mesh_sha256'] == old['metrics']['sources']['control']['mesh_sha256']:
                    raise ValueError('Oxide extension reused the actual 5 nm mesh')
                differences = {key: R.N._number(observed['metrics'][key]) - R.N._number(old['metrics'][key])
                    for key in ('deltaQ_fC', 'D4_V', 'M4_V', 'control_D4_V', 'control_M4_V', 'deltaM_V')}
                responses.append({'response_id': oxide_tag(event, bit, thickness), 'main_response_id': identifier,
                    'event': event, 'stored_bit': bit, 'oxide_nm': thickness, 'observation': observed,
                    'differences_from_5nm': differences, 'baseline_classification': old['metrics']['classification'],
                    'classification': observed['metrics']['classification'], 'new_independent_event': False})
    report = {'schema': 'dram-see-v3-r50-main-oxide-sensitivity', 'physical_revision': R.REVISION, 'state': 'VERIFIED',
        'design_sha256': R.DESIGN_SHA, 'execution_plan': rel(path), 'execution_plan_sha256': C.sha(path),
        'prediction_freeze_sha256': plan['prediction_freeze_sha256'], 'baseline_5nm': baseline, 'responses': responses,
        'new_independent_events': 0, 'new_response_count': 8, 'new_thicknesses': [4., 6.],
        'included_in_length_prediction_scores': False, 'parameter_source': R.design()['oxide_extension']['source'],
        'transport_scope': R.design()['oxide_extension']['transport_scope'],
        'scope': 'Controlled oxide sensitivity at fixed silicon-entry events; not additional independent samples or calibrated process inference'}
    return report, R.immutable(HERE / 'data/oxide/results.json', report)


def numerical_uncertainty(plan, comparisons):
    """Class evidence separate from continuous validity; unknown is never passed."""
    d = R.design(); threshold_values = [v / 1000 for v in d['thresholds_mV']]
    prereg = read(HERE / 'data/numerical/preregistered.json')['comparisons']
    all_comparisons = prereg + comparisons
    rows = []
    for event in d['events']:
        for bit in (0, 1):
            identifier = R.event_tag(event, bit); observed = plan['baseline'][identifier]['metrics']; margin = observed['M4_V']
            selected = [c for c in all_comparisons if c['response_id'] == identifier]
            by_variation = {(c['variation']['step'], c['variation']['mesh']): c for c in selected}
            complete = set(by_variation) == {(.5, 1.), (1., .7)}
            status = {}
            for threshold in threshold_values:
                near = abs(abs(margin) - threshold) <= d['numerical']['near_boundary_mV'] / 1000
                continuous_failed = any(c.get('continuous_passed') is not True for c in selected)
                crossed = any(threshold in c.get('numerically_uncertain_thresholds_V', []) for c in selected)
                uncertain = continuous_failed or crossed or (near and not complete)
                status[str(threshold)] = {'raw_classification': R.A.classification(margin, threshold),
                    'near_boundary': near, 'matched_two_variations_complete': complete, 'numerically_uncertain': uncertain,
                    'classification_refinement_status': 'FAILED_CONTINUOUS' if continuous_failed else 'CROSSING' if crossed
                        else 'CONFIRMED_STABLE' if complete else 'PENDING_NEAR_BOUNDARY' if near else 'OUTSIDE_BAND_UNREFINED'}
            rows.append({'response_id': identifier, 'event': event, 'stored_bit': bit, 'M4_V': margin, 'thresholds': status})
    return rows


def finish_boundary(path, plan):
    d = R.design(); comparisons = []
    for target in plan['selection']['selected']:
        event, bit = target['event'], target['stored_bit']; length = event['gate_length_um']; identifier = R.event_tag(event, bit)
        baseline = plan['baseline'][identifier]
        for variation in d['numerical']['variations']:
            step, mesh = variation['step'], variation['mesh']
            refined = R.observation(R.refined_tag(event, bit, step, mesh), R.control_tag(length, bit, step, mesh), R.neutral_tag(length, step, mesh))
            comparison = R.N.compare_observations(baseline, refined, tuple(x / 1000 for x in d['thresholds_mV']),
                d['gates']['numerical_readout_change_mV'] / 1000, d['gates']['numerical_deltaQ_change_fC'])
            comparisons.append({'response_id': identifier, 'event': event, 'stored_bit': bit, 'variation': variation, **comparison})
    passed = all(c['continuous_passed'] for c in comparisons)
    report = {'schema': 'dram-see-v3-r50-main-numerical-validation', 'physical_revision': R.REVISION, 'stage': 'numerical_boundary',
        'state': 'VERIFIED' if passed else 'NUMERICAL_FAILED', 'continuous_passed': passed,
        'classification_stable': all(c['classification_stable'] for c in comparisons), 'comparisons': comparisons,
        'selection': plan['selection'], 'reused_cases': plan['reused_cases'], 'main_threshold_status': numerical_uncertainty(plan, comparisons),
        'new_independent_events': 0, 'execution_plan': rel(path), 'execution_plan_sha256': C.sha(path), 'design_sha256': R.DESIGN_SHA}
    pointer = R.immutable(HERE / 'data/numerical/boundary.json', report)
    return report, pointer


def progress(path, state, reason=None):
    ledger = C.load(); plan = read(path)
    C.write_json(path.parent / 'status.json', {'schema': 'dram-see-v3-r50-main-extensions-progress', 'utc': C.now(),
        **{k: v for k, v in CONTEXT.items() if k != 'planned_cases'}, 'state': state, 'reason': reason,
        'plan_sha256': C.sha(path), 'fixed_main_independent_events': 64, 'fixed_main_response_slots': 128, 'new_independent_events': 0,
        'cases': [{**case, 'reused': case['tag'] in plan['reused_cases'],
            'ledger_state': ledger['runs'].get(case['tag'], {}).get('state', 'UNSUBMITTED'),
            'run_id': ledger['runs'].get(case['tag'], {}).get('run_id')} for case in plan['planned_cases']]})


def execute(label='r1'):
    global BEFORE
    path = directory(label) / 'plan.json'
    with C.controller_lock():
        CONTEXT.update(controller_pid=os.getpid(), controller_parent_pid=os.getppid(), controller_started_utc=C.now(), current_case=None, current_stage=None)
        try:
            plan = check_plan(path); BEFORE = read(repo(plan['ledger_before'])); CONTEXT['planned_cases'] = plan['planned_cases']
            host_guard(); R.BASE_PREFLIGHT('r50-main-extensions-start'); C.check_preservation(); C.budget()
            verify_frozen_prerequisites(plan)
            outputs = {}
            for stage in ('oxide', 'boundary'):
                CONTEXT['current_stage'] = stage
                for case in (c for c in plan['planned_cases'] if c['stage'] == stage):
                    check_plan(path); tag = case['tag']; CONTEXT['current_case'] = tag
                    row = C.load()['runs'].get(tag); parent = C.resolve(case['parent_tag']) if case['parent_tag'] else None
                    R.matching(case['matching_tags'])
                    if tag in plan['reused_cases']:
                        if reused_case(case, row) != plan['reused_cases'][tag]:
                            raise ValueError('Previously audited exact reused refinement changed')
                        continue
                    if row is not None and row.get('state') != 'VERIFIED':
                        raise ValueError('Failed/unsettled extension is never retried')
                    execution = path.parent / 'case-freezes' / (tag + '.json')
                    if row is None:
                        reservation = reserve(plan, case)
                        if execution.exists():
                            case_checked(path, case)
                        else:
                            kwargs = dict(case['kwargs'])
                            if parent:
                                kwargs['parent'] = parent
                            inputs = C.prepare(tag, **kwargs); recipe(case, read(LOCAL / 'inputs' / tag / 'parameters.json'), parent)
                            C.write_json(execution, {'utc': C.now(), 'design_sha256': R.DESIGN_SHA, 'source_sha256': plan['source_sha256'],
                                'inputs': {tag: inputs}, 'case': case, 'extension_plan_sha256': C.sha(path),
                                'prediction_freeze_sha256': plan['prediction_freeze_sha256'], 'reservation': reservation}, exclusive=True)
                        recipe(case, read(LOCAL / 'inputs' / tag / 'parameters.json'), parent)
                        check_plan(path); reserve(plan, case); progress(path, 'SUBMITTING_EXTENSION')
                        C.record(tag, execution, estimate_s=case['estimate_s']); row = C.load()['runs'][tag]
                    case_checked(path, case, row); value = R.bundle(tag); recipe(case, value['parameters'], parent)
                    R.matching([tag, *case['matching_tags']]); progress(path, 'EXTENSION_IN_PROGRESS')
                report, pointer = finish_oxide(path, plan) if stage == 'oxide' else finish_boundary(path, plan)
                outputs[stage] = pointer
                R.immutable(path.parent / (stage + '-result.json'), {'state': report['state'], **pointer, 'plan_sha256': C.sha(path)})
                if report['state'] != 'VERIFIED':
                    raise ValueError('Boundary continuous tolerance failed; preserve failed numerical evidence')
            result = {'schema': 'dram-see-v3-r50-main-extensions-result', 'state': 'SIMULATION_STAGES_FINISHED_PENDING_DELIVERY',
                'physical_revision': R.REVISION, 'plan_sha256': C.sha(path), 'outputs': outputs,
                'new_independent_events': 0, 'fixed_main_independent_events': 64, 'fixed_main_response_slots': 128,
                'delivery_status': 'GUI, report and human course activities require separate actual acceptance'}
            R.immutable(path.parent / 'result.json', result); CONTEXT['current_case'] = None
            progress(path, result['state']); return result
        except Exception as exc:
            if path.exists():
                progress(path, 'STOPPED_REQUIRES_RECONCILIATION', repr(exc))
            raise
        finally:
            BEFORE = None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'execute'))
    parser.add_argument('--label', default='r1')
    args = parser.parse_args()
    print(json.dumps(freeze(args.label) if args.action == 'freeze' else execute(args.label), indent=2, ensure_ascii=False, allow_nan=False))
