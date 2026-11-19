"""R4 versioned adapter over the immutable, reviewed R3 engineering retry core."""
import argparse
import copy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = HERE.parent
LOCAL = ROOT / 'local_runtime/dram-see-v3'
RUNTIME = LOCAL / 'physical-revisions/r50-main-restart-r4'
R3_PATH = BASE / 'restart-r3/continue.py'
R3_SOURCE_SHA = '8a1e9c6bbc9b2e4b31776f6e3efc2ff24c213d0f2fefbdfadb746b1948754257'
R3_PLAN = LOCAL / 'physical-revisions/r50-main-restart-r3/plan.json'
R3_PLAN_SHA = 'ed0bce1f2420e3a8f1df303afcfc36daa062a8bd4261ce61e50747a1e4ec645d'
NEW_FAILED = 'v3-r50-main-l025-proton-a30-s202610371-b1'
NEW_RETRY = 'v3-r50-main-retry-r4-l025-proton-a30-s202610371-b1'

spec = importlib.util.spec_from_file_location('_r50_restart_r4_upstream_r3', R3_PATH)
CORE = importlib.util.module_from_spec(spec)
exec(compile(R3_PATH.read_bytes(), str(R3_PATH), 'exec'), CORE.__dict__)
C, R, F = CORE.C, CORE.R, CORE.F
read, rel, repo, sha = CORE.read, CORE.rel, CORE.repo, CORE.sha
ORIGINAL_ALIASES = copy.deepcopy(CORE.ALIASES)
ALIASES = {**ORIGINAL_ALIASES, NEW_FAILED: NEW_RETRY}
SELF_LOADED_SHA = sha(__file__)
UPSTREAM_SOURCES = CORE.sources


def source_files():
    value = UPSTREAM_SOURCES()
    if value[rel(R3_PATH)] != R3_SOURCE_SHA:
        raise ValueError('Immutable upstream r3 source differs')
    for name in ('continue.py', 'implementation.md', 'test_continue.py'):
        value[rel(HERE / name)] = sha(HERE / name)
    if value[rel(HERE / 'continue.py')] != SELF_LOADED_SHA:
        raise ValueError('Loaded r4 controller changed')
    return value


def sources():
    files = source_files(); manifest = HERE / 'source-manifest.json'; value = read(manifest)
    if (value.get('schema') != 'dram-see-v3-r50-main-restart-r4-source-manifest'
            or value.get('upstream_controller') != rel(R3_PATH) or value.get('upstream_controller_sha256') != R3_SOURCE_SHA
            or value.get('upstream_plan') != rel(R3_PLAN) or value.get('upstream_plan_sha256') != R3_PLAN_SHA
            or value.get('files_sha256') != files):
        raise ValueError('R4 explicit source-manifest/version chain differs')
    return {**files, rel(manifest): sha(manifest)}


def upstream_plan():
    CORE.old_plan_check()
    value = read(R3_PLAN)
    if (sha(R3_PLAN) != R3_PLAN_SHA or value.get('schema') != 'dram-see-v3-r50-main-restart-r3-plan'
            or value.get('aliases') != ORIGINAL_ALIASES or value.get('source_sha256') != UPSTREAM_SOURCES()
            or value.get('planned_cases') != CORE.original_cases()
            or read(R3_PLAN.with_name('plan-sha256.json')).get('sha256') != R3_PLAN_SHA):
        raise ValueError('Original r3 plan/source/alias chain differs')
    for name, digest in value['source_sha256'].items():
        if sha(R3_PLAN.parent / 'source-snapshot' / name) != digest:
            raise ValueError('Original r3 source snapshot differs')
    for name, digest in value['frozen_files_sha256'].items():
        if sha(repo(name)) != digest:
            raise ValueError('Original r3 frozen evidence differs: ' + name)
    if sha(repo(value['ledger_before'])) != value['ledger_before_sha256']:
        raise ValueError('Original r3 protected ledger bytes differ')
    # The new failure occurred after r3 freeze. Every row present at that freeze,
    # including the previous two originals, remains exactly immutable.
    R.ledger_unchanged(read(repo(value['ledger_before'])), C.load(),
                       {c['tag'] for c in CORE.original_cases()} | set(ALIASES.values()))
    return value


def prior_routes(ledger=None, upstream=None):
    """Derive original owner from frozen membership, never from an arbitrary row path."""
    if ledger is None and CORE.ACTIVE_PLAN is not None:
        return CORE.ACTIVE_PLAN['prior_case_plans']
    ledger = C.load() if ledger is None else ledger
    upstream = read(R3_PLAN) if upstream is None else upstream
    old = read(repo(upstream['ledger_before']))['runs']
    old_tags = {c['tag'] for c in CORE.original_cases()}
    dispatched = {c['tag'] for c in upstream['dispatch_cases']}
    routes = {}
    for tag in ledger['runs']:
        if tag not in old_tags | set(ALIASES.values()):
            continue
        if tag in old:
            routes[tag] = rel(CORE.OLD_PLAN)
        elif tag in dispatched:
            routes[tag] = rel(R3_PLAN)
        else:
            raise ValueError('Unrecognized pre-r4 submitted test owner: ' + tag)
    return routes


def route_plan(tag, new, routes):
    if tag in routes:
        if new:
            raise ValueError('A prior case cannot be treated as a new r4 submission')
        path = repo(routes[tag])
        if path not in (CORE.OLD_PLAN, R3_PLAN):
            raise ValueError('Prior case owner is not an allowed frozen generation')
        return path
    if not new:
        raise ValueError('Existing case is absent from the protected owner map')
    return RUNTIME / 'plan.json'


def case_checked(case, row=None, new=False):
    path = route_plan(case['tag'], new, prior_routes())
    execution = F.case_checked(path, case, row)
    if case.get('retry_of'):
        original = C.load()['runs'][case['retry_of']]
        original_blobs = CORE.input_archive(original)
        folder = LOCAL / 'inputs' / case['tag']
        inputs = {p.name: sha(p) for p in folder.iterdir() if p.is_file()}
        CORE.same_retry_inputs(original['input_sha256'], inputs,
                               json.loads(original_blobs['project.json']), read(folder / 'project.json'))
        if row is not None:
            actual = CORE.input_archive(row)
            CORE.same_retry_inputs(original['input_sha256'], row['input_sha256'],
                                   json.loads(original_blobs['project.json']), json.loads(actual['project.json']))
    return execution


def require_existing_retries(ledger):
    for original, alias in ORIGINAL_ALIASES.items():
        row = ledger['runs'].get(alias, {})
        if row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0 or row.get('retry_of') != original:
            raise ValueError('Previous r3 retry must remain a verified reusable response')


def reconciliation(path):
    value = read(path)
    if (value.get('schema') != 'dram-see-v3-r50-main-restart-r4-reconciliation' or value.get('approved') is not True
            or value.get('failed_tags') != list(ALIASES) or value.get('aliases') != ALIASES or not value.get('files_sha256')):
        raise ValueError('Root r4 failure reconciliation is absent or differs')
    for name, digest in value['files_sha256'].items():
        if sha(repo(name)) != digest:
            raise ValueError('Root r4 reconciliation evidence differs: ' + name)
    CORE.validate_ledger(C.load()); require_existing_retries(C.load())
    return value


def acceptance(path, reconciliation_path):
    value = read(path)
    if (value.get('schema') != 'dram-see-v3-r50-main-restart-r4-acceptance' or value.get('approved') is not True
            or value.get('design_sha256') != R.DESIGN_SHA or value.get('source_sha256') != sources()
            or value.get('reconciliation_sha256') != sha(reconciliation_path)
            or value.get('prediction_freeze_sha256') != CORE.PREDICTION_SHA or not value.get('evidence')):
        raise ValueError('Independent root r4 source acceptance is absent or differs')
    instant = datetime.fromisoformat(value['accepted_utc'].replace('Z', '+00:00'))
    if instant.utcoffset() is None or instant.utcoffset().total_seconds() != 0:
        raise ValueError('Acceptance requires absolute UTC')
    return value


def freeze(reconciliation_path, acceptance_path):
    if RUNTIME.exists():
        raise ValueError('R4 runtime already exists; preserve and reconcile')
    with C.controller_lock():
        R.BASE_PREFLIGHT('r50-main-restart-r4-freeze')
        C.check_preservation(); C.budget(); CORE.authorization(); previous = upstream_plan()
        proof = CORE.PREVIOUS.audit_training()
        rec = reconciliation(reconciliation_path); acceptance(acceptance_path, reconciliation_path)
        frozen = CORE.prediction(); source = sources()
        ledger_bytes = C.LEDGER.read_bytes(); before = json.loads(ledger_bytes)
        CORE.validate_ledger(before); require_existing_retries(before)
        if NEW_RETRY in before['runs']:
            raise ValueError('New r4 retry was already submitted before its freeze')
        routes = prior_routes(before, previous)
        files = {**previous['frozen_files_sha256'], **proof['files'], **frozen['files_sha256'], **rec['files_sha256']}
        for file in (R3_PLAN, R3_PLAN.with_name('plan-sha256.json'), repo(previous['ledger_before']),
                     CORE.AUTH, CORE.PREDICTION, CORE.PREDICTION.with_name('freeze.sha256'),
                     Path(reconciliation_path), Path(acceptance_path)):
            files[rel(file)] = sha(file)
        for tag in routes:
            CORE.bind_run(before['runs'][tag], files)
        for name, digest in source.items():
            target = RUNTIME / 'source-snapshot' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(repo(name).read_bytes())
            if sha(target) != digest:
                raise ValueError('Source changed during r4 snapshot')
        snapshot = RUNTIME / 'ledger-before.json'; snapshot.write_bytes(ledger_bytes)
        pending = [CORE.actual_case(c) for c in CORE.original_cases() if CORE.actual_case(c)['tag'] not in before['runs']]
        plan = {'schema': 'dram-see-v3-r50-main-restart-r4-plan', 'physical_revision': R.REVISION,
            'label': 'r4', 'utc': C.now(), 'design_sha256': R.DESIGN_SHA, 'source_sha256': source,
            'inputs': {}, 'upstream_plan': rel(R3_PLAN), 'upstream_plan_sha256': R3_PLAN_SHA,
            'original_prediction_plan': rel(CORE.OLD_PLAN), 'original_prediction_plan_sha256': CORE.OLD_PLAN_SHA,
            'prediction_freeze_sha256': CORE.PREDICTION_SHA, 'aliases': ALIASES,
            'planned_cases': CORE.original_cases(), 'dispatch_cases': pending, 'prior_case_plans': routes,
            'frozen_files_sha256': files, 'ledger_before': rel(snapshot), 'ledger_before_sha256': sha(snapshot),
            'reconciliation': rel(reconciliation_path), 'acceptance': rel(acceptance_path),
            'global_budget_s': None, 'deadline_utc': None, 'maximum_new_solver_calls': len(pending),
            'budget_policy': 'unlimited authorization; all original/failed/retry costs in unique ledger',
            'terminal_state': 'TEST_FINISHED_PENDING_EXTENSIONS', 'extensions_and_delivery_implemented': False}
        C.write_json(RUNTIME / 'plan.json', plan, exclusive=True)
        C.write_json(RUNTIME / 'plan-sha256.json', {'sha256': sha(RUNTIME / 'plan.json')}, exclusive=True)
        CORE.ACTIVE_PLAN = check_plan(); CORE.prediction()
        return {'state': 'FROZEN', 'plan_sha256': sha(RUNTIME / 'plan.json'), 'new_submissions': 0,
                'maximum_new_solver_calls': len(pending), 'canonical_test_responses': 64}


def check_plan():
    path = RUNTIME / 'plan.json'; plan = read(path)
    CORE.authorization(); previous = upstream_plan()
    if (plan.get('schema') != 'dram-see-v3-r50-main-restart-r4-plan' or plan.get('physical_revision') != R.REVISION
            or plan.get('design_sha256') != R.DESIGN_SHA or plan.get('source_sha256') != sources()
            or plan.get('aliases') != ALIASES or plan.get('planned_cases') != CORE.original_cases()
            or plan.get('upstream_plan') != rel(R3_PLAN) or plan.get('upstream_plan_sha256') != R3_PLAN_SHA
            or plan.get('original_prediction_plan') != rel(CORE.OLD_PLAN) or plan.get('original_prediction_plan_sha256') != CORE.OLD_PLAN_SHA
            or plan.get('prediction_freeze_sha256') != CORE.PREDICTION_SHA or plan.get('global_budget_s') is not None
            or plan.get('deadline_utc') is not None or plan.get('terminal_state') != 'TEST_FINISHED_PENDING_EXTENSIONS'
            or read(path.with_name('plan-sha256.json')).get('sha256') != sha(path)):
        raise ValueError('R4 frozen plan/source/alias/recipe policy differs')
    for name, digest in plan['source_sha256'].items():
        if sha(RUNTIME / 'source-snapshot' / name) != digest:
            raise ValueError('R4 source snapshot differs')
    for name, digest in plan['frozen_files_sha256'].items():
        if sha(repo(name)) != digest:
            raise ValueError('Frozen pre-r4 evidence differs: ' + name)
    snapshot = repo(plan['ledger_before'])
    if sha(snapshot) != plan['ledger_before_sha256']:
        raise ValueError('Protected r4 ledger bytes changed')
    before = read(snapshot)
    expected = [CORE.actual_case(c) for c in CORE.original_cases() if CORE.actual_case(c)['tag'] not in before['runs']]
    if (plan.get('dispatch_cases') != expected or plan.get('maximum_new_solver_calls') != len(expected)
            or plan.get('prior_case_plans') != prior_routes(before, previous)):
        raise ValueError('R4 pending sequence/case owner map differs')
    CORE.validate_ledger(C.load(), before); require_existing_retries(C.load())
    return plan


def progress(state, reason=None):
    ledger = C.load(); slots = []
    aliases = {CORE.PREVIOUS.OLD_FAILED: CORE.PREVIOUS.RETRY, **ALIASES}
    for event in R.design()['events']:
        for bit in (0, 1):
            canonical = R.event_tag(event, bit); actual = aliases.get(canonical, canonical)
            slots.append({'response_id': canonical, 'actual_ledger_tag': actual, 'event_label': event['label'], 'stored_bit': bit,
                'split': event['split'], 'state': ledger['runs'].get(actual, {}).get('state', 'UNSUBMITTED'),
                'preserved_original_state': ledger['runs'].get(canonical, {}).get('state') if actual != canonical else None})
    C.write_json(RUNTIME / 'status.json', {'schema': 'dram-see-v3-r50-main-restart-r4-progress', 'utc': C.now(), **CORE.CONTEXT,
        'state': state, 'reason': reason, 'plan_sha256': sha(RUNTIME / 'plan.json'), 'independent_events': 64,
        'paired_responses': 128, 'main_response_slots': slots, 'extensions_and_delivery_implemented': False})


def completed_result(observed, pointer):
    expected = CORE.original_cases()
    if len(observed) != 64 or [r.get('response_id') for r in observed] != [c['tag'] for c in expected]:
        raise ValueError('Scoring requires exactly the original 64 ordered canonical slots')
    if [r.get('actual_ledger_tag') for r in observed] != [CORE.actual_case(c)['tag'] for c in expected]:
        raise ValueError('Scoring alias identities differ')
    return {'schema': 'dram-see-v3-r50-main-restart-r4-test-result', 'state': 'TEST_FINISHED_PENDING_EXTENSIONS',
        'physical_revision': R.REVISION, 'test_responses': 64, 'test_independent_events': 32,
        'plan_sha256': sha(RUNTIME / 'plan.json'), 'prediction_freeze_sha256': CORE.PREDICTION_SHA,
        'observations': observed, 'raw_submission_index': CORE.raw_submission_index(), 'aliases': ALIASES,
        'preserved_original_failures': list(ALIASES), **pointer, 'extensions_and_delivery_implemented': False}


def execute():
    with C.controller_lock():
        CORE.CONTEXT.update(controller_pid=os.getpid(), controller_parent_pid=os.getppid(), controller_started_utc=C.now(), current_case=None)
        try:
            CORE.ACTIVE_PLAN = check_plan(); CORE.BEFORE = read(repo(CORE.ACTIVE_PLAN['ledger_before']))
            R.BASE_PREFLIGHT('r50-main-restart-r4-start'); C.check_preservation(); C.budget()
            CORE.PREVIOUS.audit_training(); frozen = CORE.prediction(); observed = []
            for case in CORE.original_cases():
                check_plan(); CORE.prediction(); CORE.CONTEXT['current_case'] = CORE.actual_case(case)['tag']
                observed.append(CORE.observe(case, frozen, CORE.BEFORE)); progress('TEST_IN_PROGRESS')
            check_plan(); CORE.prediction()
            # Validate denominator/alias order before calling the unchanged scorer.
            completed_result(observed, {})
            scores = F.P.score_predictions(read(BASE / 'data/predictions/predictions.json'), observed, R.design())
            pointer = R.immutable(RUNTIME / 'prediction-scores.json', scores)
            R.immutable(RUNTIME / 'test-result.json', completed_result(observed, pointer))
            CORE.CONTEXT['current_case'] = None; progress('TEST_FINISHED_PENDING_EXTENSIONS')
            return {'state': 'TEST_FINISHED_PENDING_EXTENSIONS', 'test_responses': 64, 'global_solver_s': C.budget()}
        except Exception as exc:
            if (RUNTIME / 'plan.json').exists():
                progress('STOPPED_REQUIRES_RECONCILIATION', repr(exc))
            raise
        finally:
            CORE.BEFORE = None


# Explicit extension points of the immutable core, in this private namespace.
# Audit, input equality, preparation, runner, true exit handling, matching,
# prediction coefficients, thresholds, save protection and accounting are reused.
CORE.RUNTIME = RUNTIME
CORE.ALIASES = ALIASES
CORE.case_checked = case_checked
CORE.check_plan = check_plan
CORE.progress = progress


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'execute'))
    parser.add_argument('--reconciliation', type=Path)
    parser.add_argument('--acceptance', type=Path)
    args = parser.parse_args()
    if args.action == 'freeze' and (args.reconciliation is None or args.acceptance is None):
        parser.error('freeze requires root --reconciliation and --acceptance')
    result = freeze(args.reconciliation, args.acceptance) if args.action == 'freeze' else execute()
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), flush=True)
