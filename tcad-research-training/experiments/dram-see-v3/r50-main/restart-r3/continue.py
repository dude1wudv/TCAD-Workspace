"""Versioned deterministic engineering retries; frozen R50 predictions unchanged.

Only this new controller owns the r3 write adapter. The original runner/audit,
scientific design, previous source snapshots and failed rows remain immutable.
"""
import argparse
import copy
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
ROOT = HERE.parents[3]
BASE = HERE.parent
LOCAL = ROOT / 'local_runtime/dram-see-v3'
RUNTIME = LOCAL / 'physical-revisions/r50-main-restart-r3'
OLD_PLAN = LOCAL / 'physical-revisions/r50-main-restart-r2f/plan.json'
OLD_PLAN_SHA = '31a1429197043eb23ef80876fe940e59c97094b1372731cf1bb05e49a6e77177'
AUTH = LOCAL / 'unlimited-authorization-20261011T0346Z.json'
AUTH_SHA = '98cc9d302e82e3f70f1f51c62ec3a953e59c3c70e112399b85d4e382474b3adc'
PREDICTION = BASE / 'data/predictions/freeze.json'
PREDICTION_SHA = 'f0384066be6d42bb71dad6fd8e4e1a2f474e6f9f45d918da759ca0274a4cff9e'
ALIASES = {
    'v3-r50-main-l025-alpha-a30-s202610353-b0': 'v3-r50-main-retry-r3-l025-alpha-a30-s202610353-b0',
    'v3-r50-main-l025-proton-a0-s202610361-b0': 'v3-r50-main-retry-r3-l025-proton-a0-s202610361-b0',
}
BEFORE = None
CONTEXT = {}
ACTIVE_PLAN = None


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), obj.__dict__)
    return obj


PREVIOUS = module('_r50_restart_r2f_readonly', BASE / 'restart-r2f/continue.py')
F = PREVIOUS.F
C, R = F.C, F.R
read, rel, repo, sha = R.read, R.rel, R.repo, C.sha
SELF_LOADED_SHA = sha(__file__)


def sources():
    result = F.sources()
    for path in (BASE / 'restart-r2f/continue.py', HERE / 'continue.py', HERE / 'implementation.md', HERE / 'test_continue.py'):
        result[rel(path)] = sha(path)
    if result[rel(HERE / 'continue.py')] != SELF_LOADED_SHA:
        raise ValueError('Loaded r3 controller changed')
    if result[rel(BASE / 'restart-r2f/continue.py')] != '08769c5b119b404a0aa959170c8c0269845f2bb9b8b9b370a90eecf0f137946b':
        raise ValueError('Previous training reconciliation implementation changed')
    return result


def authorization():
    value = read(AUTH)
    if (sha(AUTH) != AUTH_SHA or value.get('schema') != 'dram-see-v3-unlimited-continuation-authorization'
            or value.get('solver_budget_s') is not None or value.get('expires_utc') is not None):
        raise ValueError('Unlimited project continuation authorization differs')
    return value


def runner_design():
    # The old runner only consumes this copy to compare its accounting total.
    # R.design(), the disk design, model fitting and numerical gates stay exact.
    authorization()
    value = copy.deepcopy(R.design())
    value['execution']['solver_budget_s'] = math.inf
    return value


def original_cases():
    ordered = F.cases()
    if len(ordered) != 64 or len({c['tag'] for c in ordered}) != 64:
        raise ValueError('Exactly 64 canonical test slots are required')
    if not set(ALIASES) <= {c['tag'] for c in ordered}:
        raise ValueError('Retry is outside the frozen test population')
    return ordered


def actual_case(case):
    value = copy.deepcopy(case)
    if case['tag'] in ALIASES:
        value.update(tag=ALIASES[case['tag']], retry_of=case['tag'])
    return value


def allowed_tags():
    return {actual_case(c)['tag'] for c in original_cases()}


def validate_ledger(ledger, before=None):
    """Pure structural gate; FAILED is permitted only for the two fixed originals."""
    rows = ledger['runs']; ordered = original_cases(); originals = {c['tag'] for c in ordered}
    aliases = set(ALIASES.values())
    present = [i for i, c in enumerate(ordered) if c['tag'] in rows]
    if present != list(range(len(present))):
        raise ValueError('Original test submissions are not a fixed-order prefix')
    for canonical, alias in ALIASES.items():
        if rows.get(canonical, {}).get('state') != 'FAILED':
            raise ValueError('Original engineering FAILED row must remain FAILED: ' + canonical)
        candidates = [tag for tag, row in rows.items() if row.get('retry_of') == canonical]
        if candidates not in ([], [alias]):
            raise ValueError('Duplicate or unknown retry alias for ' + canonical)
    for tag, row in rows.items():
        related = tag in originals | aliases or F.is_test(row.get('parameters', {}))
        if not related:
            continue
        if tag not in originals | aliases:
            raise ValueError('Unplanned actual test attempt: ' + tag)
        if tag in ALIASES:
            continue
        if row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0:
            raise ValueError('Unknown/failed test attempt blocks dispatch: ' + tag)
        if tag in aliases and row.get('retry_of') != next(k for k, v in ALIASES.items() if v == tag):
            raise ValueError('Retry ledger identity differs')
    if before is not None:
        R.ledger_unchanged(before, ledger, allowed_tags())
        pending = [actual_case(c)['tag'] for c in ordered if actual_case(c)['tag'] not in before['runs']]
        found = [i for i, tag in enumerate(pending) if tag in rows]
        if found != list(range(len(found))):
            raise ValueError('New submissions skipped the fixed retry/remaining order')
    return rows


def same_retry_inputs(original, retry, original_project, retry_project):
    if set(original) != set(retry) or 'project.json' not in original:
        raise ValueError('Retry input inventory differs')
    if any(original[name] != retry[name] for name in original if name != 'project.json'):
        raise ValueError('Retry changes device/parameters/source/mesh/parent bytes')
    left, right = copy.deepcopy(original_project), copy.deepcopy(retry_project)
    if left.pop('name', None) not in ALIASES or right.pop('name', None) != ALIASES[original_project['name']] or left != right:
        raise ValueError('Only the fixed retry project name may differ')


def input_archive(row):
    folder = R.A.run_folder(row['run_id'])
    m = read(folder / 'manifest.json')
    if m.get('input_sha256') != row.get('input_sha256'):
        raise ValueError('Original manifest input hashes differ from ledger')
    with tarfile.open(folder / 'inputs.tar') as archive:
        entries = archive.getmembers()
        if any(not x.isfile() or Path(x.name).name != x.name for x in entries):
            raise ValueError('Unexpected input archive member')
        blobs = {x.name: archive.extractfile(x).read() for x in entries}
    if len(blobs) != len(entries) or {n: hashlib.sha256(b).hexdigest() for n, b in blobs.items()} != row['input_sha256']:
        raise ValueError('Input archive bytes differ from frozen ledger hashes')
    if json.loads(blobs['parameters.json']) != row.get('parameters'):
        raise ValueError('Actual archived parameters differ from ledger')
    return blobs


def case_checked(case, row=None, new=False):
    path = RUNTIME / 'plan.json' if new else OLD_PLAN
    execution = F.case_checked(path, case, row)
    if case.get('retry_of'):
        original = C.load()['runs'][case['retry_of']]
        old_blobs = input_archive(original)
        folder = LOCAL / 'inputs' / case['tag']
        hashes = {p.name: sha(p) for p in folder.iterdir() if p.is_file()}
        same_retry_inputs(original['input_sha256'], hashes, json.loads(old_blobs['project.json']), read(folder / 'project.json'))
        if row is not None:
            new_blobs = input_archive(row)
            same_retry_inputs(original['input_sha256'], row['input_sha256'], json.loads(old_blobs['project.json']), json.loads(new_blobs['project.json']))
    return execution


def validate_attempts(frozen):
    """Replacement only for finish's prefix gate; all physical audits stay strict."""
    ledger = C.load(); before = read(repo(ACTIVE_PLAN['ledger_before'])) if ACTIVE_PLAN else None
    rows = validate_ledger(ledger, before)
    by_tag = {c['tag']: c for c in original_cases()}
    by_tag.update({actual_case(c)['tag']: actual_case(c) for c in original_cases() if c['tag'] in ALIASES})
    inspected = set()
    for item in F.actual_manifests():
        if not F.is_test(item['parameters']):
            continue
        matches = [tag for tag, row in rows.items() if row.get('run_id') == item['run_id']]
        if len(matches) != 1 or matches[0] not in by_tag or rows[matches[0]].get('parameters') != item['parameters']:
            raise ValueError('Actual test archive lacks unique ledger identity')
        tag = matches[0]; row = rows[tag]; case = by_tag[tag]
        input_archive(row)
        F.submitted_after_freeze(row, frozen)
        R.recipe(case, row['parameters'], C.resolve(case['parent_tag']))
        case_checked(case, row, new=before is not None and tag not in before['runs'])
        if tag not in ALIASES:
            R.bundle(tag)  # true local runner/SSH zero, remote markers, raw numeric audit
        inspected.add(tag)
    if inspected != {tag for tag in by_tag if tag in rows}:
        raise ValueError('Recorded test lacks its unique actual input archive')


F.existing_test_attempts = validate_attempts


def prediction():
    if sha(PREDICTION) != PREDICTION_SHA:
        raise ValueError('Original prediction freeze bytes changed')
    # Original plan binding remains the original r2f plan; no model regeneration.
    return F.check_prediction(OLD_PLAN)


def old_plan_check():
    value = read(OLD_PLAN)
    if sha(OLD_PLAN) != OLD_PLAN_SHA or value.get('source_sha256') != F.sources() or value.get('planned_cases') != original_cases():
        raise ValueError('Original r2f plan differs')
    if read(OLD_PLAN.with_name('plan-sha256.json')).get('sha256') != OLD_PLAN_SHA:
        raise ValueError('Original r2f plan self-hash differs')
    for name, digest in value['source_sha256'].items():
        if sha(OLD_PLAN.parent / 'source-snapshot' / name) != digest:
            raise ValueError('Original r2f source snapshot differs')
    for name, digest in value['frozen_files_sha256'].items():
        if sha(repo(name)) != digest:
            raise ValueError('Original r2f training/activation evidence differs')
    if sha(repo(value['ledger_before'])) != value['ledger_before_sha256']:
        raise ValueError('Original r2f ledger snapshot differs')
    return value


def reconciliation(path):
    value = read(path)
    if (value.get('schema') != 'dram-see-v3-r50-main-restart-r3-reconciliation' or value.get('approved') is not True
            or value.get('failed_tags') != list(ALIASES) or value.get('aliases') != ALIASES or not value.get('files_sha256')):
        raise ValueError('Root failure reconciliation is absent or not exact')
    for name, digest in value['files_sha256'].items():
        if sha(repo(name)) != digest:
            raise ValueError('Root reconciliation evidence differs: ' + name)
    validate_ledger(C.load())
    return value


def acceptance(path, reconciliation_path):
    value = read(path)
    if (value.get('schema') != 'dram-see-v3-r50-main-restart-r3-acceptance' or value.get('approved') is not True
            or value.get('design_sha256') != R.DESIGN_SHA or value.get('source_sha256') != sources()
            or value.get('reconciliation_sha256') != sha(reconciliation_path)
            or value.get('prediction_freeze_sha256') != PREDICTION_SHA or not value.get('evidence')):
        raise ValueError('Independent root r3 source acceptance absent or differs')
    instant = datetime.fromisoformat(value['accepted_utc'].replace('Z', '+00:00'))
    if instant.utcoffset().total_seconds() != 0:
        raise ValueError('Acceptance must use UTC')
    return value


def bind_run(row, files):
    folder = R.A.run_folder(row['run_id'])
    for name in ('manifest.json', 'inputs.tar', 'results.tar'):
        file = folder / name
        if not file.is_file():
            raise ValueError('All old test raw archives must be collected before r3 freeze')
        files[rel(file)] = sha(file)
    file = repo(row['execution_freeze']); files[rel(file)] = sha(file)


def freeze(reconciliation_path, acceptance_path):
    global ACTIVE_PLAN
    if RUNTIME.exists():
        raise ValueError('r3 runtime exists; use execute only after reviewing its exact plan')
    with C.controller_lock():
        R.BASE_PREFLIGHT('r50-main-restart-r3-freeze')
        C.check_preservation(); C.budget(); authorization(); old = old_plan_check()
        proof = PREVIOUS.audit_training()
        rec = reconciliation(reconciliation_path); acceptance(acceptance_path, reconciliation_path)
        frozen = prediction(); source = sources()
        ledger_bytes = C.LEDGER.read_bytes(); before = json.loads(ledger_bytes)
        validate_ledger(before)
        if any(tag in before['runs'] for tag in ALIASES.values()):
            raise ValueError('A retry alias already exists before r3 freeze')
        files = {**old['frozen_files_sha256'], **proof['files'], **frozen['files_sha256'], **rec['files_sha256']}
        for file in (OLD_PLAN, OLD_PLAN.with_name('plan-sha256.json'), OLD_PLAN.parent / 'prediction-binding.json',
                     AUTH, PREDICTION, PREDICTION.with_name('freeze.sha256'), Path(reconciliation_path), Path(acceptance_path)):
            files[rel(file)] = sha(file)
        for case in original_cases():
            if case['tag'] in before['runs']:
                bind_run(before['runs'][case['tag']], files)
        for name, digest in source.items():
            target = RUNTIME / 'source-snapshot' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(repo(name).read_bytes())
            if sha(target) != digest:
                raise ValueError('Source changed while snapshotting')
        snapshot = RUNTIME / 'ledger-before.json'; snapshot.write_bytes(ledger_bytes)
        pending = [actual_case(c) for c in original_cases() if actual_case(c)['tag'] not in before['runs']]
        plan = {'schema': 'dram-see-v3-r50-main-restart-r3-plan', 'physical_revision': R.REVISION,
            'label': 'r3', 'utc': C.now(), 'design_sha256': R.DESIGN_SHA, 'source_sha256': source,
            'inputs': {}, 'original_plan': rel(OLD_PLAN), 'original_plan_sha256': OLD_PLAN_SHA,
            'prediction_freeze_sha256': PREDICTION_SHA, 'aliases': ALIASES, 'planned_cases': original_cases(),
            'dispatch_cases': pending, 'frozen_files_sha256': files, 'ledger_before': rel(snapshot),
            'ledger_before_sha256': sha(snapshot), 'reconciliation': rel(reconciliation_path), 'acceptance': rel(acceptance_path),
            'global_budget_s': None, 'deadline_utc': None, 'maximum_new_solver_calls': len(pending),
            'budget_policy': 'unlimited authorization; unique global ledger charges original and retry separately',
            'terminal_state': 'TEST_FINISHED_PENDING_EXTENSIONS', 'extensions_and_delivery_implemented': False}
        C.write_json(RUNTIME / 'plan.json', plan, exclusive=True)
        C.write_json(RUNTIME / 'plan-sha256.json', {'sha256': sha(RUNTIME / 'plan.json')}, exclusive=True)
        ACTIVE_PLAN = check_plan()
        prediction()
        return {'state': 'FROZEN', 'plan_sha256': sha(RUNTIME / 'plan.json'), 'new_submissions': 0,
                'maximum_new_solver_calls': len(pending), 'canonical_test_responses': 64}


def check_plan():
    path = RUNTIME / 'plan.json'; plan = read(path)
    authorization(); old_plan_check()
    if (plan.get('schema') != 'dram-see-v3-r50-main-restart-r3-plan' or plan.get('physical_revision') != R.REVISION
            or plan.get('design_sha256') != R.DESIGN_SHA or plan.get('source_sha256') != sources()
            or plan.get('aliases') != ALIASES or plan.get('planned_cases') != original_cases()
            or plan.get('original_plan') != rel(OLD_PLAN) or plan.get('original_plan_sha256') != OLD_PLAN_SHA
            or plan.get('prediction_freeze_sha256') != PREDICTION_SHA or plan.get('global_budget_s') is not None
            or plan.get('deadline_utc') is not None or plan.get('terminal_state') != 'TEST_FINISHED_PENDING_EXTENSIONS'
            or read(path.with_name('plan-sha256.json')).get('sha256') != sha(path)):
        raise ValueError('r3 plan identity/source/alias/budget/recipe differs')
    for name, digest in plan['source_sha256'].items():
        if sha(path.parent / 'source-snapshot' / name) != digest:
            raise ValueError('r3 source snapshot differs')
    for name, digest in plan['frozen_files_sha256'].items():
        if sha(repo(name)) != digest:
            raise ValueError('Frozen pre-r3 evidence changed: ' + name)
    snapshot = repo(plan['ledger_before'])
    if sha(snapshot) != plan['ledger_before_sha256']:
        raise ValueError('Protected r3 ledger snapshot changed')
    before = read(snapshot)
    expected = [actual_case(c) for c in original_cases() if actual_case(c)['tag'] not in before['runs']]
    if plan.get('dispatch_cases') != expected or plan.get('maximum_new_solver_calls') != len(expected):
        raise ValueError('Frozen pending order/call count differs')
    validate_ledger(C.load(), before)
    return plan


def save(ledger):
    if BEFORE is None:
        raise ValueError('No active r3 write context')
    for tag, row in ledger['runs'].items():
        if tag not in BEFORE['runs']:
            if tag not in allowed_tags():
                raise ValueError('Attempted write outside r3 fixed sequence')
            row.update(physical_revision=R.REVISION, physical_revision_probe_only=False, original_100ohm_matrix_eligible=False)
            for original, alias in ALIASES.items():
                if tag == alias:
                    row['retry_of'] = original
    R.ledger_unchanged(BEFORE, ledger, allowed_tags())
    F.BASE_SAVE(ledger)


def submission_preflight(tag):
    authorization()
    result = R.BASE_PREFLIGHT(tag)
    authorization()
    return result


def prepare_retry(case):
    original = C.load()['runs'][case['retry_of']]
    if original.get('state') != 'FAILED':
        raise ValueError('Retry target is no longer the preserved FAILED attempt')
    blobs = input_archive(original); folder = LOCAL / 'inputs' / case['tag']
    folder.mkdir(parents=True, exist_ok=False)
    for name, content in blobs.items():
        if name == 'project.json':
            value = json.loads(content); value['name'] = case['tag']
            content = (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf8')
        with (folder / name).open('xb') as stream:
            stream.write(content)
    hashes = {p.name: sha(p) for p in folder.iterdir() if p.is_file()}
    same_retry_inputs(original['input_sha256'], hashes, json.loads(blobs['project.json']), read(folder / 'project.json'))
    return hashes


def progress(state, reason=None):
    ledger = C.load(); slots = []
    aliases = {**{PREVIOUS.OLD_FAILED: PREVIOUS.RETRY}, **ALIASES}
    for event in R.design()['events']:
        for bit in (0, 1):
            canonical = R.event_tag(event, bit); actual = aliases.get(canonical, canonical)
            slots.append({'response_id': canonical, 'actual_ledger_tag': actual, 'event_label': event['label'], 'stored_bit': bit,
                'split': event['split'], 'state': ledger['runs'].get(actual, {}).get('state', 'UNSUBMITTED'),
                'preserved_original_state': ledger['runs'].get(canonical, {}).get('state') if actual != canonical else None})
    C.write_json(RUNTIME / 'status.json', {'schema': 'dram-see-v3-r50-main-restart-r3-progress', 'utc': C.now(), **CONTEXT,
        'state': state, 'reason': reason, 'plan_sha256': sha(RUNTIME / 'plan.json'), 'independent_events': 64,
        'paired_responses': 128, 'main_response_slots': slots, 'extensions_and_delivery_implemented': False})


def observe(case, frozen, before):
    canonical = case['tag']; current = actual_case(case); tag = current['tag']; row = C.load()['runs'].get(tag)
    parent = C.resolve(current['parent_tag']); R.matching(current['matching_tags'])
    if row is None:
        execution = RUNTIME / 'case-freezes' / (tag + '.json')
        if execution.exists():
            case_checked(current, new=True)
        else:
            inputs = prepare_retry(current) if current.get('retry_of') else C.prepare(tag, parent=parent, **current['kwargs'])
            R.recipe(current, read(LOCAL / 'inputs' / tag / 'parameters.json'), parent)
            C.write_json(execution, {'utc': C.now(), 'design_sha256': R.DESIGN_SHA,
                'source_sha256': ACTIVE_PLAN['source_sha256'], 'inputs': {tag: inputs},
                'followup_plan_sha256': sha(RUNTIME / 'plan.json'), 'case': current,
                'prediction_freeze_sha256': PREDICTION_SHA, 'reservation': {'global_budget_s': None, 'global_solver_s_before': C.budget()}}, exclusive=True)
        check_plan(); prediction(); progress('SUBMITTING_TEST')
        C.record(tag, execution, estimate_s=600)
        row = C.load()['runs'][tag]
    if row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0:
        raise ValueError('Failed/unknown new attempt cannot be resubmitted')
    case_checked(current, row, new=tag not in before['runs'])
    F.submitted_after_freeze(row, frozen)
    value = R.bundle(tag); R.recipe(current, value['parameters'], parent)
    metrics = R.M.compute_curves(value, *(R.bundle(t) for t in current['matching_tags']))
    pointer = R.immutable(RUNTIME / 'metrics' / (canonical + '.json'), metrics)
    return {'response_id': canonical, 'actual_ledger_tag': tag, 'retry_of': current.get('retry_of'),
        'event_label': case['event']['label'], 'stored_bit': case['kwargs']['bit'], 'continuous_valid': True,
        'continuous_numerical_status': 'RAW_AUDIT_PASSED', 'targets': {'deltaQ_fC': metrics['deltaQ_fC'], 'deltaM_mV': metrics['deltaM_V'] * 1000},
        'classification': metrics['classification'], 'sources': metrics['sources'], 'metrics_evidence': pointer}


def raw_submission_index():
    rows = C.load()['runs']; tags = {c['tag'] for c in original_cases()} | set(ALIASES.values())
    ordered = sorted(((tag, row) for tag, row in rows.items() if tag in tags), key=lambda x: (x[1]['started_utc'], x[0]))
    reverse = {value: key for key, value in ALIASES.items()}
    return [{'raw_submission_index': i, 'canonical_response_id': reverse.get(tag, tag), 'actual_ledger_tag': tag,
        'state': row['state'], 'run_id': row['run_id'], 'runner_exit_code': row.get('runner_exit_code'),
        'started_utc': row['started_utc'], 'charged_solver_s': row.get('charged_solver_s'), 'retry_of': row.get('retry_of')}
        for i, (tag, row) in enumerate(ordered)]


def execute():
    global BEFORE, ACTIVE_PLAN
    with C.controller_lock():
        CONTEXT.update(controller_pid=os.getpid(), controller_parent_pid=os.getppid(), controller_started_utc=C.now(), current_case=None)
        try:
            ACTIVE_PLAN = check_plan(); BEFORE = read(repo(ACTIVE_PLAN['ledger_before']))
            R.BASE_PREFLIGHT('r50-main-restart-r3-start'); C.check_preservation(); C.budget()
            PREVIOUS.audit_training(); frozen = prediction(); observed = []
            for case in original_cases():
                check_plan(); prediction(); CONTEXT['current_case'] = actual_case(case)['tag']
                observed.append(observe(case, frozen, BEFORE)); progress('TEST_IN_PROGRESS')
            check_plan(); prediction()
            scores = F.P.score_predictions(read(BASE / 'data/predictions/predictions.json'), observed, R.design())
            pointer = R.immutable(RUNTIME / 'prediction-scores.json', scores)
            result = {'schema': 'dram-see-v3-r50-main-restart-r3-test-result', 'state': 'TEST_FINISHED_PENDING_EXTENSIONS',
                'physical_revision': R.REVISION, 'test_responses': 64, 'test_independent_events': 32,
                'plan_sha256': sha(RUNTIME / 'plan.json'), 'prediction_freeze_sha256': PREDICTION_SHA,
                'observations': observed, 'raw_submission_index': raw_submission_index(), 'aliases': ALIASES,
                'preserved_original_failures': list(ALIASES), **pointer, 'extensions_and_delivery_implemented': False}
            R.immutable(RUNTIME / 'test-result.json', result)
            CONTEXT['current_case'] = None; progress('TEST_FINISHED_PENDING_EXTENSIONS')
            return {'state': result['state'], 'test_responses': 64, 'global_solver_s': C.budget()}
        except Exception as exc:
            if (RUNTIME / 'plan.json').exists():
                progress('STOPPED_REQUIRES_RECONCILIATION', repr(exc))
            raise
        finally:
            BEFORE = None


C.design, C.save, C.preflight = runner_design, save, submission_preflight
C.check_prediction_freeze = prediction


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'execute'))
    parser.add_argument('--reconciliation', type=Path)
    parser.add_argument('--acceptance', type=Path)
    args = parser.parse_args()
    if args.action == 'freeze' and (args.reconciliation is None or args.acceptance is None):
        parser.error('freeze requires --reconciliation and --acceptance from root review')
    result = freeze(args.reconciliation, args.acceptance) if args.action == 'freeze' else execute()
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), flush=True)
