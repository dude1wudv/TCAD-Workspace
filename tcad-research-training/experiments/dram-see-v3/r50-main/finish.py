"""Accepted R50-main training -> test transport -> predictions -> test64.

This continuation stops at TEST_FINISHED_PENDING_EXTENSIONS. No oxide,
boundary, GUI or final-delivery implementation is implied by that state.
"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
LOCAL = ROOT / 'local_runtime/dram-see-v3'
RUNTIME = LOCAL / 'physical-revisions/r50-main-followup-r1'
ACCEPTANCE = LOCAL / 'physical-revisions/r50-main-followup-r1-acceptance.json'
BEFORE = None
CONTEXT = {}
LOADED = {}


def module(name, path):
    content = Path(path).read_bytes()
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    exec(compile(content, str(path), 'exec'), obj.__dict__)
    LOADED[Path(path).resolve().relative_to(ROOT).as_posix()] = hashlib.sha256(content).hexdigest()
    return obj


R = module('_r50_followup_first_segment', HERE / 'controller.py')
C = module('_r50_followup_original_runner', BASE / 'run.py')
P = module('_r50_followup_pure_prediction', HERE / 'prediction.py')
T = module('_r50_followup_transport_adapter', HERE / 'transport_adapter.py')
LOADED[Path(__file__).resolve().relative_to(ROOT).as_posix()] = C.sha(__file__)
BASE_SAVE = C.save
read, rel, repo = R.read, R.rel, R.repo
FOLLOWUP_FILES = tuple('experiments/dram-see-v3/r50-main/' + name for name in (
    'finish.py', 'prediction.py', 'prediction.py.diff', 'transport_adapter.py', 'transport_adapter.py.diff',
    'followup-derivation.json')) + ('experiments/dram-see-v3/prediction.py', 'experiments/dram-see-v3/transport.py',
    'experiments/dram-see-v1/geant4_transport.cc')


def directory(label='r1'):
    if label != 'r1':
        raise ValueError('Only the accepted R50-main followup r1 is implemented')
    return RUNTIME


def sources():
    files = {**R.sources(), **{name: C.sha(repo(name)) for name in FOLLOWUP_FILES}}
    m = read(HERE / 'followup-source-manifest.json')
    if m.get('schema') != 'dram-see-v3-r50-main-followup-source-manifest' or m.get('files_sha256') != files:
        raise ValueError('Accepted followup fixed source manifest differs')
    for name, digest in LOADED.items():
        if files.get(name) != digest:
            raise ValueError('Loaded followup source differs: ' + name)
    for row in read(HERE / 'followup-derivation.json')['sources']:
        if any(C.sha(path) != digest for path, digest in ((repo(row['original']), row['original_sha256']),
                (repo(row['derived']), row['derived_sha256']), (HERE / row['diff'], row['diff_sha256']))):
            raise ValueError('Followup derivation source/diff changed')
    return {**files, rel(HERE / 'followup-source-manifest.json'): C.sha(HERE / 'followup-source-manifest.json')}


def cases():
    return [{'tag': R.event_tag(e, bit), 'stage': 'test', 'role': 'event', 'event': e,
        'kwargs': {'length': e['gate_length_um'], 'bit': bit, 'event': rel(R.event_path(e))},
        'parent_tag': R.control_tag(e['gate_length_um'], bit),
        'matching_tags': [R.control_tag(e['gate_length_um'], bit), R.neutral_tag(e['gate_length_um'])],
        'estimate_s': 600} for e in R.design()['events'] if e['split'] != 'train' for bit in (0, 1)]


def host_guard():
    """Read-only process check: first controller must actually have exited."""
    command = "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw)\\.exe$' } | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True, text=True, check=True)
    rows = json.loads(result.stdout) if result.stdout.strip() else []
    rows = [rows] if isinstance(rows, dict) else rows
    for row in rows:
        pid, cmd = row['ProcessId'], (row.get('CommandLine') or '').replace('\\', '/').lower()
        if pid == os.getpid():
            continue
        if pid == os.getppid() and all(str(arg).replace('\\', '/').lower() in cmd for arg in sys.argv):
            continue
        if any(name in cmd for name in ('r50-main/controller.py', 'r50-main/finish.py', 'precharge-r50/controller.py')):
            raise RuntimeError('Another R50 controller process still exists; do not dispatch')


def submission_preflight(tag):
    R.deadline(); host_guard()
    result = R.BASE_PREFLIGHT(tag)
    R.deadline()
    return result


def save_followup(ledger):
    if BEFORE is None:
        raise ValueError('No accepted followup write context')
    allowed = {case['tag'] for case in cases()}
    for tag, row in ledger['runs'].items():
        if tag not in BEFORE['runs']:
            if tag not in allowed:
                raise ValueError('Non-test run in this continuation')
            row.update(physical_revision=R.REVISION, physical_revision_probe_only=False, original_100ohm_matrix_eligible=False)
    R.ledger_unchanged(BEFORE, ledger, allowed)
    BASE_SAVE(ledger)


C.DESIGN, C.design, C.module = HERE / 'design.json', R.design, R.runner_module
C.save, C.preflight = save_followup, submission_preflight


def bind(path, files):
    files[rel(path)] = C.sha(path)
    return read(path)


def bind_bundle(bundle, files):
    folder = R.A.run_folder(bundle['summary']['run_id'])
    for name in ('manifest.json', 'inputs.tar', 'results.tar'):
        files[rel(folder / name)] = C.sha(folder / name)


def actual_manifests():
    """Input metadata only; never opens an unseen particle response archive."""
    result = []
    for path in sorted((ROOT / 'local_runtime/runs').glob('*/manifest.json')):
        m = read(path); inputs = path.parent / 'inputs.tar'
        if not inputs.exists():
            raise ValueError('Uninspectable actual submission input archive: ' + path.parent.name)
        with tarfile.open(inputs) as tf:
            members = [item for item in tf.getmembers() if item.isfile() and Path(item.name).name == 'parameters.json']
            if not members and '-v3-' not in path.parent.name:
                continue
            if len(members) != 1:
                raise ValueError('Ambiguous actual submitted parameters')
            p = json.loads(tf.extractfile(members[0]).read())
            expected = m.get('input_sha256', {}).get('parameters.json')
            if expected != hashlib.sha256(tf.extractfile(members[0]).read()).hexdigest():
                raise ValueError('Actual input parameter hash differs from manifest')
        result.append({'run_id': path.parent.name, 'parameters': p, 'manifest_sha256': C.sha(path), 'inputs_sha256': C.sha(inputs)})
    return result


def is_test(p):
    related = p.get('schema') == R.SCHEMA or p.get('physical_revision') == R.REVISION
    if not related:
        return False
    if p.get('schema') != R.SCHEMA or p.get('physical_revision') != R.REVISION or p.get('physical_revision_probe_only') is not False:
        raise ValueError('Inconsistent actual main model identity')
    return bool(p.get('source_event')) and p.get('gate_length_um') in (.25, .45)


def no_test_submissions(ledger, manifests):
    for tag, row in ledger['runs'].items():
        if is_test(row.get('parameters', {})) or tag in {case['tag'] for case in cases()}:
            raise ValueError('R50-main test submission already recorded before prediction freeze')
    if any(is_test(row['parameters']) for row in manifests):
        raise ValueError('Actual R50-main test input archive predates prediction freeze')


def checked_training():
    """Rebuild all first-segment scientific gates read-only, including raw archives."""
    d = R.design(); files = {}
    path = R.directory() / 'plan.json'; plan = bind(path, files)
    if bind(path.with_name('plan-sha256.json'), files).get('sha256') != C.sha(path):
        raise ValueError('First plan self-hash changed')
    C.check_execution(path)
    if plan.get('source_sha256') != R.sources() or plan.get('planned_cases') != R.cases(d):
        raise ValueError('First segment source/recipe differs')
    for name, digest in plan['source_sha256'].items():
        snapshot = path.parent / 'source-snapshot' / name
        if C.sha(snapshot) != digest:
            raise ValueError('First source snapshot changed')
        files[rel(snapshot)] = digest
    for name, digest in plan['frozen_files_sha256'].items():
        if C.sha(repo(name)) != digest:
            raise ValueError('First activation/source event evidence changed')
        files[name] = digest
    first_before = bind(repo(plan['ledger_before']), files)
    if files[plan['ledger_before']] != plan['ledger_before_sha256']:
        raise ValueError('First original ledger snapshot changed')
    R.ledger_unchanged(first_before, C.load(), {c['tag'] for c in R.cases(d) + cases()})
    status = read(path.parent / 'status.json')
    if status.get('state') != 'TRAINING_FINISHED_PENDING_PREDICTION':
        raise ValueError('First segment has not reached its true training terminal state')
    index = bind(path.parent / 'stage-index.json', files)
    if index.get('physical_revision') != R.REVISION or index.get('plan_sha256') != C.sha(path) or set(index.get('stages', {})) != set(R.STAGES):
        raise ValueError('First stage index identity/inventory differs')
    stages = {}
    for stage in R.STAGES:
        pointer = index['stages'][stage]
        value = bind(repo(pointer['evidence']), files)
        if (pointer.get('state') != 'VERIFIED' or pointer.get('evidence_sha256') != files[pointer['evidence']]
                or value.get('state') != 'VERIFIED' or value.get('physical_revision') != R.REVISION
                or value.get('plan_sha256') != C.sha(path)):
            raise ValueError('First stage was not actually verified: ' + stage)
        stages[stage] = value
    bundles = {}
    for case in R.cases(d):
        tag = case['tag']; row = C.load()['runs'].get(tag, {})
        R.case_checked(path, case, row)
        execution = repo(row['execution_freeze']); bind(execution, files)
        value = R.bundle(tag); bind_bundle(value, files); bundles[tag] = value
        parent = C.resolve(case['parent_tag']) if case['parent_tag'] else None
        R.recipe(case, value['parameters'], parent); R.matching([tag, *case['matching_tags']])
        record = stages[case['stage']]['cases'].get(tag, {})
        if record.get('state') != 'VERIFIED' or record.get('run_id') != row.get('run_id') or record.get('archive_sha256') != value['summary']['archive_sha256']:
            raise ValueError('First stage run source differs')
        computed = None
        if case['role'] == 'physical':
            computed = R.M.compare_physical_curves(value, R.bundle(case['offline_tag']), R.bundle(R.neutral_tag(case['kwargs']['length'])))
            if not computed['passed']:
                raise ValueError('Physical reference/source-isolation no longer passes')
        elif case['role'] == 'event':
            computed = R.M.compute_curves(value, *(R.bundle(t) for t in case['matching_tags']))
        if computed is not None:
            original = bind(repo(record['evidence']), files)
            if original != computed or files[record['evidence']] != record['evidence_sha256']:
                raise ValueError('Original first-stage raw comparison/metric evidence differs')
    target = R.target_event(d); bit = d['numerical']['preregistered']['stored_bit']; length = target['gate_length_um']
    baseline = R.observation(R.event_tag(target, bit), R.control_tag(length, bit), R.neutral_tag(length))
    comparisons = []
    for variation in d['numerical']['variations']:
        step, mesh = variation['step'], variation['mesh']
        refined = R.observation(R.refined_tag(target, bit, step, mesh), R.control_tag(length, bit, step, mesh), R.neutral_tag(length, step, mesh))
        comparisons.append({'response_id': R.event_tag(target, bit), 'event': target, 'stored_bit': bit, 'variation': variation,
            **R.N.compare_observations(baseline, refined, tuple(x / 1000 for x in d['thresholds_mV']),
                d['gates']['numerical_readout_change_mV'] / 1000, d['gates']['numerical_deltaQ_change_fC'])})
    numeric_path = HERE / 'data/numerical/preregistered.json'; numeric = bind(numeric_path, files)
    if (numeric.get('physical_revision') != R.REVISION or numeric.get('continuous_passed') is not True
            or numeric.get('comparisons') != comparisons or any(not row['continuous_passed'] for row in comparisons)
            or stages['numerical_preregistered'].get('evidence_sha256') != C.sha(numeric_path)):
        raise ValueError('Actual preregistered continuous comparisons failed or differ')
    wanted = [R.event_tag(e, b) for e in d['events'] if e['split'] == 'train' for b in (0, 1)]
    if stages['train'].get('training_response_ids') != wanted or len(wanted) != 64:
        raise ValueError('First training gate lacks all exact 64 R50-main responses')
    return {'design': d, 'files': files, 'bundles': bundles, 'comparisons': comparisons, 'stages': stages, 'first_plan_sha256': C.sha(path)}


def acceptance():
    value = read(ACCEPTANCE)
    first = R.directory() / 'plan.json'
    if (value.get('schema') != 'dram-see-v3-r50-main-followup-acceptance' or value.get('approved') is not True
            or value.get('design_sha256') != R.DESIGN_SHA or value.get('first_plan_sha256') != C.sha(first)
            or value.get('source_manifest_sha256') != C.sha(HERE / 'followup-source-manifest.json')
            or not value.get('accepted_utc') or not value.get('evidence')):
        raise ValueError('Independent followup source acceptance absent or changed')
    datetime.fromisoformat(value['accepted_utc'].replace('Z', '+00:00'))
    return value


def freeze(label='r1'):
    path = directory(label) / 'plan.json'
    with C.controller_lock():
        if path.exists():
            check_plan(path)
            return {'state': 'FROZEN_EXISTING', 'new_submissions': 0, 'plan_sha256': C.sha(path)}
        if path.parent.exists():
            raise ValueError('Partial followup plan exists; preserve and reconcile')
        source = sources(); approved = acceptance(); R.deadline(); host_guard()
        C.budget(); C.check_preservation()
        proof = checked_training(); no_test_submissions(C.load(), actual_manifests())
        before = C.load()
        for name, digest in source.items():
            target = path.parent / 'source-snapshot' / name; target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(repo(name).read_bytes())
            if C.sha(target) != digest:
                raise ValueError('Followup source changed during snapshot')
        before_path = path.parent / 'ledger-before.json'; C.write_json(before_path, before, exclusive=True)
        plan = {'schema': 'dram-see-v3-r50-main-followup-plan', 'physical_revision': R.REVISION, 'label': label, 'utc': C.now(),
            'design_sha256': R.DESIGN_SHA, 'source_sha256': source, 'inputs': {}, 'planned_cases': cases(),
            'first_plan_sha256': proof['first_plan_sha256'], 'frozen_files_sha256': {**proof['files'], rel(ACCEPTANCE): C.sha(ACCEPTANCE)},
            'ledger_before': rel(before_path), 'ledger_before_sha256': C.sha(before_path), 'acceptance': approved,
            'stage_order': ['test_transport', 'prediction_freeze', 'test'], 'maximum_new_solver_calls': 64,
            'global_budget_s': 86400, 'deadline_utc': '2026-10-11T04:37:00Z',
            'terminal_state': 'TEST_FINISHED_PENDING_EXTENSIONS', 'extensions_and_delivery_implemented': False}
        C.write_json(path, plan, exclusive=True)
        C.write_json(path.with_name('plan-sha256.json'), {'sha256': C.sha(path)}, exclusive=True)
        check_plan(path)
        return {'state': 'FROZEN', 'new_submissions': 0, 'plan_sha256': C.sha(path)}


def check_plan(path):
    path = Path(path); plan = C.check_execution(path)
    if (read(path.with_name('plan-sha256.json')).get('sha256') != C.sha(path) or path != directory(plan['label']) / 'plan.json'
            or plan.get('schema') != 'dram-see-v3-r50-main-followup-plan' or plan.get('physical_revision') != R.REVISION
            or plan.get('source_sha256') != sources() or plan.get('planned_cases') != cases()
            or plan.get('global_budget_s') != 86400 or plan.get('maximum_new_solver_calls') != 64
            or plan.get('terminal_state') != 'TEST_FINISHED_PENDING_EXTENSIONS' or plan.get('extensions_and_delivery_implemented') is not False):
        raise ValueError('Followup frozen plan identity/source/recipe differs')
    for name, digest in plan['source_sha256'].items():
        if C.sha(path.parent / 'source-snapshot' / name) != digest:
            raise ValueError('Followup source snapshot differs')
    for name, digest in plan['frozen_files_sha256'].items():
        if C.sha(repo(name)) != digest:
            raise ValueError('Frozen training/activation evidence changed')
    if C.sha(repo(plan['ledger_before'])) != plan['ledger_before_sha256']:
        raise ValueError('Followup protected ledger snapshot changed')
    R.ledger_unchanged(read(repo(plan['ledger_before'])), C.load(), {case['tag'] for case in cases()})
    return plan


def reserve(plan):
    window = R.deadline(); used = C.budget()
    costs = [row.get('charged_solver_s', row.get('elapsed_s', 0)) for row in C.load()['runs'].values() if not row.get('inherited')]
    if any(type(value) not in (float, int) or not math.isfinite(value) or value < 0 for value in costs + [used]):
        raise ValueError('Invalid global cost')
    if used + 600 > 86400:
        raise RuntimeError('Global budget insufficient for next fixed test item')
    if any(C.load()['runs'].get(c['tag'], {}).get('charged_solver_s', 0) > 600 for c in cases()):
        raise RuntimeError('Actual test exceeded frozen reserve; versioned review needed')
    return {**window, 'global_solver_s_before': used, 'next_estimate_s': 600}


def event_record(e, files):
    path = R.event_path(e)
    value = R.E.validate_event(path, {key: e[key] for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'energy_MeV')})
    for name in ('event.json', 'events.csv', 'steps.csv'):
        file = path.parent / name; files[rel(file)] = C.sha(file)
    operation = LOCAL / 'operations' / ('g4-' + e['label'])
    record = bind(operation / 'operation.json', files)
    request = bind(operation / 'request.json', files)
    archive_path = operation / 'events.tar'
    if (record.get('state') != 'VALIDATED' or record.get('exit_code') != 0 or record.get('collection_exit_code') != 0
            or record.get('event_metadata_sha256') != C.sha(path) or record.get('archive_sha256') != C.sha(archive_path)
            or value.get('operation_archive_sha256') != C.sha(archive_path) or record.get('request_sha256') != C.sha(operation / 'request.json')
            or any(request.get(key) != e[key] for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'energy_MeV'))):
        raise ValueError('Transport attempt is not explicitly collected/validated with matching original evidence')
    with tarfile.open(archive_path) as tf:
        members = {member.name: member for member in tf.getmembers()}
        if set(members) != {'events.csv', 'steps.csv', 'transport-exit-code.txt'} or any(not m.isfile() for m in members.values()):
            raise ValueError('Transport collection members differ')
        if tf.extractfile(members['transport-exit-code.txt']).read().strip() != b'0':
            raise ValueError('Actual transport did not exit successfully')
        for name in ('events.csv', 'steps.csv'):
            if tf.extractfile(members[name]).read() != (path.parent / name).read_bytes():
                raise ValueError('Transport exported CSV differs from original collected bytes')
    for name in ('events.tar', 'command.sh', 'stdout.txt', 'stderr.txt', 'collection-command.txt', 'collection-stderr.txt'):
        file = operation / name; files[rel(file)] = C.sha(file)
    return value


def predictor_rows(proof):
    d = proof['design']; files = dict(proof['files']); train, test = [], []
    for e in d['events']:
        transport = event_record(e, files); length = e['gate_length_um']
        for bit in (0, 1):
            row = {key: e[key] for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'condition_id', 'replicate', 'split')}
            row.update(event_label=e['label'], stored_bit=bit, physical_revision=R.REVISION,
                Qdep_fC=transport['converted'][0]['charge_pc'] * 1000, source_event_sha256=files[rel(R.event_path(e))])
            control, neutral = R.bundle(R.control_tag(length, bit)), R.bundle(R.neutral_tag(length))
            if e['split'] == 'train':
                signal = R.bundle(R.event_tag(e, bit)); result = R.M.compute_curves(signal, control, neutral)
                if signal['parameters']['charge_pc'] != transport['converted'][0]['charge_pc']:
                    raise ValueError('Training G4 deposition differs from original raw source')
                near = [epsilon for epsilon in d['thresholds_mV'] if abs(abs(result['M4_V'] * 1000) - epsilon) <= d['numerical']['near_boundary_mV']]
                prereg = e == R.target_event(d) and bit == d['numerical']['preregistered']['stored_bit']
                uncertain = sorted({eps * 1000 for c in proof['comparisons'] for eps in c['numerically_uncertain_thresholds_V']}) if prereg else near
                row.update(targets={'deltaQ_fC': result['deltaQ_fC'], 'deltaM_mV': result['deltaM_V'] * 1000},
                    continuous_valid=True, continuous_numerical_status='MATCHED_REFINEMENT_PASSED' if prereg else 'RAW_AUDIT_PASSED',
                    classification=result['classification'], classification_numerically_uncertain_thresholds_mV=uncertain,
                    classification_numerical_status='preregistered checked' if prereg else 'near boundary unresolved' if near else 'outside near-boundary band',
                    sources=result['sources'], metric_validity=result['validity'])
                train.append(row)
            else:
                baseline = R.M.compute_curves(control, control, neutral)
                row.update(known_control={'M4_mV': baseline['control_M4_V'] * 1000, 'hold_SN_V': R.A.sample(control['circuit'], 'v(sn)', 2.8e-9)},
                    sources={'control': baseline['sources']['control'], 'neutral': baseline['sources']['neutral']})
                test.append(row)
    P._validated_rows(train, d, True); P._validated_rows(test, d, False)
    return train, test, files


def freeze_predictions(path, plan, proof):
    out = HERE / 'data/predictions'
    if out.exists():
        return check_prediction(path)
    R.deadline(); no_test_submissions(C.load(), actual_manifests())
    ledger_bytes = C.LEDGER.read_bytes(); ledger = json.loads(ledger_bytes)
    train, test, files = predictor_rows(proof)
    models = P.fit_models(train, proof['design']); predictions = P.predict_inputs(models, test, proof['design'])
    if C.LEDGER.read_bytes() != ledger_bytes:
        raise ValueError('Global ledger changed while preparing model freeze')
    no_test_submissions(ledger, actual_manifests())
    files.update(plan['source_sha256']); files[rel(path)] = C.sha(path)
    provenance = {'schema': 'dram-see-v3-r50-main-prediction-provenance', 'physical_revision': R.REVISION,
        'design_sha256': R.DESIGN_SHA, 'followup_plan_sha256': C.sha(path), 'first_plan_sha256': plan['first_plan_sha256'],
        'source_sha256': plan['source_sha256'], 'gates': proof['stages'], 'ledger_snapshot_sha256': hashlib.sha256(ledger_bytes).hexdigest(),
        'test_responses_seen': 0, 'test_submission_check': 'actual inputs.tar metadata and complete global ledger; no response archive read',
        'classification_policy': 'critical continuous targets retained; near/crossing flags preserved; known continuous failure blocks'}
    artifacts = {'models.json': models, 'training-data.json': train, 'test-inputs.json': test, 'predictions.json': predictions,
        'ledger-snapshot.json': ledger, 'provenance.json': provenance}
    out.mkdir(parents=True, exist_ok=False)
    for name, value in artifacts.items():
        if name == 'ledger-snapshot.json':
            # Preserve the exact source bytes named in provenance, including
            # original whitespace/newlines; parsing is for checks only.
            with (out / name).open('xb') as stream:
                stream.write(ledger_bytes)
        else:
            C.write_json(out / name, value, exclusive=True)
        files[rel(out / name)] = C.sha(out / name)
    frozen = {'schema': 'dram-see-v3-r50-main-prediction-freeze', 'physical_revision': R.REVISION,
        'frozen_utc': datetime.now(timezone.utc).isoformat(), 'design_sha256': R.DESIGN_SHA, 'followup_plan_sha256': C.sha(path),
        'training_independent_events': 32, 'training_responses': 64, 'test_independent_events': 32,
        'test_paired_predictions': 64, 'models_per_bit_target': 4, 'test_responses_seen': 0, 'files_sha256': files}
    C.write_json(out / 'freeze.json', frozen, exclusive=True)
    with (out / 'freeze.sha256').open('x', encoding='ascii') as stream:
        stream.write(C.sha(out / 'freeze.json') + '\n')
    C.write_json(path.parent / 'prediction-binding.json', {'freeze': rel(out / 'freeze.json'), 'freeze_sha256': C.sha(out / 'freeze.json'),
        'followup_plan_sha256': C.sha(path), 'frozen_utc': frozen['frozen_utc']}, exclusive=True)
    return check_prediction(path)


def check_prediction(path=None):
    path = directory() / 'plan.json' if path is None else Path(path)
    out = HERE / 'data/predictions'; f = read(out / 'freeze.json'); binding = read(path.parent / 'prediction-binding.json')
    if (binding.get('freeze_sha256') != C.sha(out / 'freeze.json') or binding.get('followup_plan_sha256') != C.sha(path)
            or (out / 'freeze.sha256').read_text().strip() != C.sha(out / 'freeze.json') or binding.get('frozen_utc') != f.get('frozen_utc')
            or f.get('schema') != 'dram-see-v3-r50-main-prediction-freeze' or f.get('physical_revision') != R.REVISION
            or f.get('design_sha256') != R.DESIGN_SHA or f.get('followup_plan_sha256') != C.sha(path)
            or any(f.get(k) != v for k, v in {'training_independent_events': 32, 'training_responses': 64, 'test_independent_events': 32,
                'test_paired_predictions': 64, 'models_per_bit_target': 4, 'test_responses_seen': 0}.items())):
        raise ValueError('Prediction freeze identity/self-hash/completeness differs')
    instant = datetime.fromisoformat(f['frozen_utc'])
    if instant.utcoffset() != timedelta(0):
        raise ValueError('Prediction freeze needs an absolute UTC timestamp')
    names = ('models.json', 'training-data.json', 'test-inputs.json', 'predictions.json', 'ledger-snapshot.json', 'provenance.json')
    if not {rel(out / n) for n in names} <= set(f['files_sha256']):
        raise ValueError('Incomplete frozen prediction artifacts')
    for name, digest in f['files_sha256'].items():
        if C.sha(repo(name)) != digest:
            raise ValueError('Immutable prediction source/artifact differs: ' + name)
    d = R.design(); train = read(out / 'training-data.json'); test = read(out / 'test-inputs.json'); models = read(out / 'models.json')
    P._validated_rows(train, d, True); P._validated_rows(test, d, False)
    if any(row.get('physical_revision') != R.REVISION for row in train + test):
        raise ValueError('Frozen predictor rows have wrong physical revision')
    if models.get('schema') != 'dram-see-v3-r50-main-prediction-models' or set(models.get('models', {})) != {f'bit{b}:{t}' for b in (0, 1) for t in P.TARGETS}:
        raise ValueError('Four actual models are required')
    if P.predict_inputs(models, test, d) != read(out / 'predictions.json'):
        raise ValueError('Frozen predictions differ from actual coefficients and inputs')
    snapshot = read(out / 'ledger-snapshot.json'); no_test_submissions(snapshot, [])
    provenance = read(out / 'provenance.json')
    if (provenance.get('source_sha256') != read(path)['source_sha256'] or provenance.get('test_responses_seen') != 0
            or provenance.get('ledger_snapshot_sha256') != C.sha(out / 'ledger-snapshot.json')):
        raise ValueError('Prediction source provenance differs')
    for stage in R.STAGES:
        if provenance.get('gates', {}).get(stage, {}).get('state') != 'VERIFIED':
            raise ValueError('Frozen prerequisite gate incomplete')
    existing_test_attempts(f)
    return f


C.check_prediction_freeze = check_prediction


def existing_test_attempts(frozen):
    """Every actual test must be a coherent, verified prefix after the freeze."""
    ledger = C.load(); ordered = cases(); by_tag = {case['tag']: case for case in ordered}
    existing = [i for i, case in enumerate(ordered) if case['tag'] in ledger['runs']]
    if existing != list(range(len(existing))):
        raise ValueError('Existing test submissions are not a prefix of fixed order')
    for i in existing:
        case = ordered[i]; row = ledger['runs'][case['tag']]
        if row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0:
            raise ValueError('An existing failed/unknown test blocks all new dispatch')
        submitted_after_freeze(row, frozen)
        R.recipe(case, row.get('parameters', {}), C.resolve(case['parent_tag']))
    inspected = set()
    for item in actual_manifests():
        if not is_test(item['parameters']):
            continue
        matches = [tag for tag, row in ledger['runs'].items() if row.get('run_id') == item['run_id']]
        if len(matches) != 1 or matches[0] not in by_tag or ledger['runs'][matches[0]].get('parameters') != item['parameters']:
            raise ValueError('Actual test archive lacks exact global ledger identity')
        inspected.add(matches[0])
    if inspected != {ordered[i]['tag'] for i in existing}:
        raise ValueError('A recorded test has no matching actual input archive')


def case_checked(path, case, row=None):
    frozen = path.parent / 'case-freezes' / (case['tag'] + '.json'); value = C.check_execution(frozen)
    if (value.get('followup_plan_sha256') != C.sha(path) or value.get('source_sha256') != read(path)['source_sha256']
            or value.get('case') != case or set(value['inputs']) != {case['tag']}
            or value.get('prediction_freeze_sha256') != C.sha(HERE / 'data/predictions/freeze.json')):
        raise ValueError('Test case is not bound to accepted plan and pre-test predictions')
    if row is not None and (row.get('execution_freeze') != rel(frozen) or row.get('execution_freeze_sha256') != C.sha(frozen)
            or row.get('input_sha256') != value['inputs'][case['tag']] or row.get('physical_revision') != R.REVISION):
        raise ValueError('Existing test attempt provenance differs')
    return frozen


def submitted_after_freeze(row, frozen):
    freeze_time = datetime.fromisoformat(frozen['frozen_utc'])
    started = datetime.fromisoformat(row['started_utc'])
    if started.tzinfo is None or started <= freeze_time:
        raise ValueError('Actual ledger test submission did not follow prediction freeze')
    # Runner IDs encode UTC to whole seconds. This interval check supplements
    # the exact ledger timestamp without pretending to know subsecond runner time.
    runner_start = datetime.strptime(row['run_id'][:16], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
    if runner_start + timedelta(seconds=1) <= freeze_time or runner_start + timedelta(seconds=1) <= started:
        raise ValueError('Actual runner identity predates its frozen test dispatch')


def progress(path, state, reason=None):
    ledger = C.load()
    C.write_json(path.parent / 'status.json', {'schema': 'dram-see-v3-r50-main-followup-progress', 'utc': C.now(), **CONTEXT,
        'state': state, 'reason': reason, 'plan_sha256': C.sha(path), 'independent_events': 64, 'paired_responses': 128,
        'extensions_and_delivery_implemented': False,
        'main_response_slots': [{'response_id': R.event_tag(e, bit), 'event_label': e['label'], 'stored_bit': bit, 'split': e['split'],
            'state': ledger['runs'].get(R.event_tag(e, bit), {}).get('state', 'UNSUBMITTED')} for e in R.design()['events'] for bit in (0, 1)]})


def execute(label='r1'):
    global BEFORE
    path = directory(label) / 'plan.json'
    with C.controller_lock():
        CONTEXT.update(controller_pid=os.getpid(), controller_parent_pid=os.getppid(), controller_started_utc=C.now(), current_case=None)
        try:
            plan = check_plan(path); BEFORE = read(repo(plan['ledger_before']))
            host_guard(); R.BASE_PREFLIGHT('r50-main-followup-start'); C.check_preservation(); C.budget()
            proof = checked_training()
            if not (HERE / 'data/predictions').exists():
                no_test_submissions(C.load(), actual_manifests())
                for event in (e for e in R.design()['events'] if e['split'] != 'train'):
                    CONTEXT['current_case'] = 'transport-' + event['label']; check_plan(path)
                    file = R.event_path(event)
                    if not file.exists():
                        reserve(plan); submission_preflight('r50-main-transport-' + event['label'])
                        progress(path, 'GENERATING_FIXED_TEST_INPUT')
                        T.run(event['label'], event['gate_length_um'], event['particle'], event['seed'], event['angle_deg'])
                    event_record(event, {})
                freeze_predictions(path, plan, proof)
            frozen = check_prediction(path)
            observed = []
            for case in cases():
                check_plan(path); check_prediction(path); tag = case['tag']; CONTEXT['current_case'] = tag
                row = C.load()['runs'].get(tag); parent = C.resolve(case['parent_tag'])
                R.matching(case['matching_tags'])
                if row is not None and row.get('state') != 'VERIFIED':
                    raise ValueError('Prior failed/unsettled test is never resubmitted')
                execution = path.parent / 'case-freezes' / (tag + '.json')
                if row is None:
                    reservation = reserve(plan)
                    if execution.exists():
                        case_checked(path, case)
                    else:
                        inputs = C.prepare(tag, parent=parent, **case['kwargs'])
                        R.recipe(case, read(LOCAL / 'inputs' / tag / 'parameters.json'), parent)
                        C.write_json(execution, {'utc': C.now(), 'design_sha256': R.DESIGN_SHA, 'source_sha256': plan['source_sha256'],
                            'inputs': {tag: inputs}, 'followup_plan_sha256': C.sha(path), 'case': case,
                            'prediction_freeze_sha256': C.sha(HERE / 'data/predictions/freeze.json'), 'reservation': reservation}, exclusive=True)
                    R.recipe(case, read(LOCAL / 'inputs' / tag / 'parameters.json'), parent)
                    check_plan(path); reserve(plan); progress(path, 'SUBMITTING_TEST')
                    C.record(tag, execution, estimate_s=600); row = C.load()['runs'][tag]
                case_checked(path, case, row); submitted_after_freeze(row, frozen)
                value = R.bundle(tag); R.recipe(case, value['parameters'], parent)
                metrics = R.M.compute_curves(value, *(R.bundle(t) for t in case['matching_tags']))
                R.immutable(HERE / 'data/metrics' / (tag + '.json'), metrics)
                observed.append({'event_label': case['event']['label'], 'stored_bit': case['kwargs']['bit'], 'continuous_valid': True,
                    'continuous_numerical_status': 'RAW_AUDIT_PASSED', 'targets': {'deltaQ_fC': metrics['deltaQ_fC'], 'deltaM_mV': metrics['deltaM_V'] * 1000},
                    'classification': metrics['classification'], 'sources': metrics['sources']})
                progress(path, 'TEST_IN_PROGRESS')
            scores = P.score_predictions(read(HERE / 'data/predictions/predictions.json'), observed, R.design())
            pointer = R.immutable(HERE / 'data/prediction-scores.json', scores)
            R.immutable(path.parent / 'test-result.json', {'schema': 'dram-see-v3-r50-main-test-result', 'state': 'TEST_FINISHED_PENDING_EXTENSIONS',
                'test_responses': 64, 'test_independent_events': 32, 'plan_sha256': C.sha(path),
                'prediction_freeze_sha256': C.sha(HERE / 'data/predictions/freeze.json'), 'observations': observed, **pointer,
                'extensions_and_delivery_implemented': False})
            CONTEXT['current_case'] = None; progress(path, 'TEST_FINISHED_PENDING_EXTENSIONS')
            return {'state': 'TEST_FINISHED_PENDING_EXTENSIONS', 'test_responses': 64, 'global_solver_s': C.budget()}
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
