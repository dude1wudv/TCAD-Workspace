"""R50-main restart-r2 controller.

This revision is a bounded engineering retry for the one R50-main response
whose solver finished but whose Windows collection marker was missing.  It
keeps the original failed row and archive immutable, adopts only independently
verified rows from r50-main-r1, and appends one uniquely tagged retry row to the
global ledger.  It has no prediction/test/extension entry point.
"""
from datetime import datetime, timezone
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[2]
LOCAL = ROOT / 'local_runtime/dram-see-v3'
RUNTIME = LOCAL / 'physical-revisions/r50-main-restart-r2b'
AUTH = LOCAL / 'unlimited-authorization-20261011T0346Z.json'
ACTIVATION = LOCAL / 'physical-revisions/r50-main-restart-r2b-activation.json'
OLD_RUNTIME = LOCAL / 'physical-revisions/r50-main-r1'
OLD_PLAN = OLD_RUNTIME / 'plan.json'
RETRY_TAG = 'v3-r50-main-retry-r2-l035-alpha-a30-s202610394-b1'
OLD_FAILED_TAG = 'v3-r50-main-l035-alpha-a30-s202610394-b1'
REVISION = 'r50-main-r1'
SCHEMA = 'dram-see-v3-r50-main-restart-r2b'
DESIGN_SHA = '6d52749bb8b9716b13b5ff1aa562a3ee331e3d7a062f32287c23710a5d1cf740'
OLD_PLAN_SHA = '3a10fc7df24d0dfd94353aed79e429059f93ccdf0cee45905bcf0af9ec9c45fb'
LOADED = {}


def load_module(name, path):
    path = Path(path)
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), obj.__dict__)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    LOADED[path.resolve().relative_to(ROOT).as_posix()] = digest
    return obj


T = load_module('tcad_restart_r2', ROOT / 'scripts/tcad.py')
C = load_module('common_restart_r2', BASE.parent / 'common.py')
sys.modules['common'] = C
RUN = load_module('run_restart_r2', BASE.parent / 'run.py')
B = load_module('build_case_restart_r2', HERE / 'build_case.py')
A = load_module('audit_restart_r2', HERE / 'audit.py')
ORIG = load_module('original_r50_main', BASE / 'controller.py')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def write(path, value, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open('x', encoding='utf8', newline='\n') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
    else:
        C.write_json(path, value)


def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def safe_tag(value):
    return value.replace('.', 'p')


def ledger():
    return RUN.load()


def source_files():
    names = ('controller.py', 'build_case.py', 'audit.py', 'event_audit.py',
             'design.json', 'plan.md', 'design.sha256')
    paths = {rel(HERE / name): sha(HERE / name) for name in names}
    for path in (BASE.parent / 'common.py', BASE.parent / 'run.py', ROOT / 'scripts/tcad.py',
                 ROOT / 'experiments/dram-see-v1/analyze.py', ROOT / 'experiments/dram-see-v1/build_case.py',
                 ROOT / 'experiments/dram-see-v2/build_case.py', ROOT / 'experiments/dram-readout-offset-d1/build.py'):
        paths[rel(path)] = sha(path)
    return paths


def source_manifest():
    manifest = read(HERE / 'source-manifest.json')
    expected = source_files()
    if manifest.get('schema') != 'dram-see-v3-r50-main-restart-source-manifest':
        raise ValueError('Restart source manifest schema mismatch')
    if manifest.get('physical_revision') != REVISION or manifest.get('files_sha256') != expected:
        raise ValueError('Restart source manifest differs from current fixed sources')
    return expected | {rel(HERE / 'source-manifest.json'): sha(HERE / 'source-manifest.json')}


def auth():
    if not AUTH.is_file():
        raise ValueError('Unlimited authorization file is required before restart activation')
    value = read(AUTH)
    if value.get('schema') != 'dram-see-v3-unlimited-continuation-authorization' or value.get('solver_budget_s') is not None:
        raise ValueError('Unlimited continuation authorization is absent or budget-limited')
    if value.get('engineering_recovery', {}).get('retry_tag') != RETRY_TAG:
        raise ValueError('Unlimited authorization is not bound to this retry')
    return value


def design():
    path = HERE / 'design.json'
    if sha(path) != DESIGN_SHA:
        raise ValueError('Frozen R50-main design changed')
    value = read(path)
    if value.get('schema') != 'dram-see-v3-r50-main' or value.get('physical_revision') != REVISION:
        raise ValueError('Unexpected R50-main design identity')
    if len(value.get('events', [])) != 64:
        raise ValueError('Restart must retain 64 independent events')
    return value


def old_plan():
    if not OLD_PLAN.is_file() or sha(OLD_PLAN) != OLD_PLAN_SHA:
        raise ValueError('Original r50-main-r1 execution plan changed or is missing')
    value = read(OLD_PLAN)
    if value.get('schema') != 'dram-see-v3-r50-main-execution-plan':
        raise ValueError('Original plan schema mismatch')
    return value


def fixed_retry_case(plan):
    rows = [row for row in plan['planned_cases'] if row['tag'] == OLD_FAILED_TAG]
    if len(rows) != 1:
        raise ValueError('Original failed case is not uniquely present in the frozen plan')
    case = json.loads(json.dumps(rows[0]))
    case['tag'] = RETRY_TAG
    case['original_tag'] = OLD_FAILED_TAG
    case['retry_of'] = OLD_FAILED_TAG
    case['retry_reason'] = 'Engineering collection marker absent; solver output retained as FAILED_COLLECTED'
    return case


def adoption_snapshot(plan, current):
    planned = {row['tag'] for row in plan['planned_cases']}
    adopted = []
    for tag in sorted(planned):
        row = current['runs'].get(tag)
        if tag == OLD_FAILED_TAG:
            if not row or row.get('state') != 'FAILED' or row.get('failure_category') != 'ENGINEERING_EVIDENCE_INCOMPLETE':
                raise ValueError('Original engineering failure row is not preserved exactly')
            continue
        if row is None:
            continue
        if row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0:
            raise ValueError('Existing nonfailed r50-main-r1 case is not independently VERIFIED: ' + tag)
        adopted.append(tag)
    if RETRY_TAG in current['runs']:
        raise ValueError('Retry tag already exists; never retry a retry')
    return adopted


def activation():
    value = read(ACTIVATION) if ACTIVATION.is_file() else None
    if not value or value.get('schema') != 'dram-see-v3-r50-main-restart-activation' or value.get('approved') is not True:
        raise ValueError('Independent restart activation acceptance is required')
    if value.get('original_plan_sha256') != sha(OLD_PLAN) or value.get('design_sha256') != DESIGN_SHA:
        raise ValueError('Restart activation is bound to a different original plan/design')
    if value.get('retry_tag') != RETRY_TAG or value.get('original_failed_tag') != OLD_FAILED_TAG:
        raise ValueError('Restart activation tag binding mismatch')
    if not value.get('evidence'):
        raise ValueError('Restart activation evidence is missing')
    auth()
    return value


def preserve_ledger(before, current, allow_retry=False):
    if set(before) != set(current):
        raise ValueError('Global ledger top-level fields changed')
    for key in before:
        if key not in ('runs', 'failures') and before[key] != current[key]:
            raise ValueError('Protected global ledger section changed: ' + key)
    for tag, row in before['runs'].items():
        if current['runs'].get(tag) != row:
            raise ValueError('Protected ledger row changed: ' + tag)
    extra = set(current['runs']) - set(before['runs'])
    allowed = {RETRY_TAG} if allow_retry else set()
    if not extra <= allowed:
        raise ValueError('Unexpected ledger additions: ' + repr(sorted(extra)))
    if current['failures'][:len(before['failures'])] != before['failures']:
        raise ValueError('Protected failure history changed')
    if allow_retry:
        additions = current['failures'][len(before['failures']):]
        if any(row.get('tag') != RETRY_TAG or row.get('state') != 'FAILED' for row in additions):
            raise ValueError('Retry failure append is malformed')
    elif len(current['failures']) != len(before['failures']):
        raise ValueError('Failure history changed before retry submission')


def restart_plan(path):
    value = read(path)
    marker = path.with_name('plan-sha256.json')
    if read(marker).get('sha256') != sha(path):
        raise ValueError('Restart execution plan self-hash changed')
    if value.get('schema') != SCHEMA or value.get('retry_case', {}).get('tag') != RETRY_TAG:
        raise ValueError('Restart plan schema/tag mismatch')
    if value.get('original_plan_sha256') != sha(OLD_PLAN):
        raise ValueError('Restart plan is not bound to original plan')
    before = ROOT / value['ledger_before']
    if sha(before) != value.get('ledger_before_sha256'):
        raise ValueError('Restart protected ledger snapshot changed')
    preserve_ledger(read(before), ledger())
    for name, digest in value['source_sha256'].items():
        snap = path.parent / 'source-snapshot' / name
        if sha(snap) != digest:
            raise ValueError('Restart source snapshot changed: ' + name)
    return value


def freeze(label='r2'):
    if label != 'r2':
        raise ValueError('Only restart-r2 is implemented')
    path = RUNTIME / 'plan.json'
    with C.controller_lock():
        if path.exists():
            restart_plan(path)
            return {'state': 'FROZEN_EXISTING', 'plan_sha256': sha(path)}
        if path.parent.exists() and any(path.parent.iterdir()):
            raise ValueError('Partial restart freeze exists; preserve and reconcile')
        activation()
        d = design(); previous = old_plan(); current = ledger()
        if not current['runs'].get(OLD_FAILED_TAG):
            raise ValueError('Original failed row is absent')
        adopted = adoption_snapshot(previous, current)
        source = source_manifest()
        before_path = path.parent / 'ledger-before.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        write(before_path, current, exclusive=True)
        frozen = {'original_plan': rel(OLD_PLAN), 'original_plan_sha256': sha(OLD_PLAN),
                  'old_failed_row_sha256': hashlib.sha256(json.dumps(current['runs'][OLD_FAILED_TAG], sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                  'adopted_tags_sha256': hashlib.sha256(json.dumps(adopted, separators=(',', ':')).encode()).hexdigest()}
        for name, digest in source.items():
            target = path.parent / 'source-snapshot' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                source_path = ROOT / name
                stream.write(source_path.read_bytes())
            if sha(target) != digest:
                raise ValueError('Source changed during restart freeze: ' + name)
        case = fixed_retry_case(previous)
        plan = {'schema': SCHEMA, 'physical_revision': REVISION, 'label': label,
                'utc': C.now(), 'design_sha256': DESIGN_SHA, 'original_plan_sha256': sha(OLD_PLAN),
                'source_sha256': source, 'frozen_files_sha256': frozen,
                'ledger_before': rel(before_path), 'ledger_before_sha256': sha(before_path),
                'retry_case': case, 'adopted_verified_tags': adopted,
                'protected_failed_tags': [OLD_FAILED_TAG], 'fixed_main_independent_events': 64,
                'fixed_main_response_slots': 128, 'global_budget_s': None,
                'budget_policy': 'unlimited new restart submissions; global ledger remains sole cost truth',
                'new_submission_deadline_utc': None,
                'implemented_terminal_state': 'TRAINING_FINISHED_PENDING_PREDICTION',
                'later_stages_implemented': False, 'activation': activation(),
                'retry_attempt_limit': 1}
        write(path, plan, exclusive=True)
        write(path.with_name('plan-sha256.json'), {'sha256': sha(path)}, exclusive=True)
        restart_plan(path)
        return {'state': 'FROZEN', 'plan': rel(path), 'plan_sha256': sha(path), 'adopted': len(adopted)}


def retry_parameters(case):
    return {'length': case['kwargs']['length'], 'bit': case['kwargs']['bit'],
            'event': case['kwargs']['event'], 'parent': case['parent_tag'],
            'step': case['kwargs'].get('step', 1.), 'mesh': case['kwargs'].get('mesh', 1.),
            'oxide_nm': 5., 'reference': 'offline', 'neutral': False}


def save_retry(value, before):
    preserve_ledger(before, value, allow_retry=True)
    RUN.save(value)


def save_continuation(value, before):
    """Protect every pre-restart row while allowing fixed planned R50 cases."""
    if set(before) != set(value):
        raise ValueError('Global ledger top-level fields changed')
    for key in before:
        if key not in ('runs', 'failures') and before[key] != value[key]:
            raise ValueError('Protected global ledger section changed: ' + key)
    allowed = {RETRY_TAG} | {row['tag'] for row in old_plan()['planned_cases']}
    for tag, row in before['runs'].items():
        if value['runs'].get(tag) != row:
            raise ValueError('Protected ledger row changed: ' + tag)
    if not set(value['runs']) - set(before['runs']) <= allowed:
        raise ValueError('Unexpected continuation ledger row')
    if value['failures'][:len(before['failures'])] != before['failures']:
        raise ValueError('Protected failure history changed')
    extras = value['failures'][len(before['failures']):]
    if any(row.get('tag') not in allowed or row.get('state') != 'FAILED' for row in extras):
        raise ValueError('Malformed continuation failure append')
    RUN.save(value)


def configure_original_runner(before):
    """Reuse the accepted R50 case/metric flow with the restart ledger guard."""
    ORIG.C.DESIGN = BASE / 'design.json'
    def design_unlimited():
        value = copy.deepcopy(design())
        value['execution']['solver_budget_s'] = float('inf')
        return value
    ORIG.C.design = design_unlimited
    ORIG.C.module = lambda name: B if name == 'build_case' else A if name == 'audit' else (_ for _ in ()).throw(ValueError(name))
    ORIG.C.save = lambda value: save_continuation(value, before)
    ORIG.C.preflight = C.preflight
    ORIG.C.budget = RUN.budget
    ORIG.C.check_prediction_freeze = lambda: None


def run_remaining_training(path, plan, before):
    configure_original_runner(before)
    actual_tags = {OLD_FAILED_TAG: RETRY_TAG}
    completed = []
    for case in old_plan()['planned_cases']:
        if case.get('stage') != 'train':
            continue
        canonical = case['tag']
        if canonical == OLD_FAILED_TAG:
            row = ledger()['runs'].get(RETRY_TAG)
            if not row or row.get('state') != 'VERIFIED':
                raise ValueError('Verified retry is required before canonical training reconciliation')
            completed.append(canonical)
            continue
        row = ledger()['runs'].get(canonical)
        if row is None:
            parent = ORIG.C.resolve(case['parent_tag']) if case.get('parent_tag') else None
            ORIG.matching(case.get('matching_tags', ()))
            kwargs = dict(case['kwargs'])
            if parent:
                kwargs['parent'] = parent
            inputs = ORIG.C.prepare(canonical, **kwargs)
            execution = RUNTIME / 'case-freezes' / (canonical + '.json')
            body = {'utc': C.now(), 'design_sha256': sha(BASE / 'design.json'),
                    'source_sha256': ORIG.source_hashes(), 'inputs': {canonical: inputs},
                    'main_plan': rel(path), 'main_plan_sha256': sha(path), 'case': case,
                    'physical_revision': REVISION, 'restart_lineage': 'r50-main-restart-r2'}
            write(execution, body, exclusive=True)
            params = read(LOCAL / 'inputs' / canonical / 'parameters.json')
            ORIG.recipe(case, params, parent)
            ORIG.C.record(canonical, execution, estimate_s=case.get('estimate_s', 600))
            value = ledger(); value['runs'][canonical]['restart_lineage'] = 'r50-main-restart-r2'
            save_continuation(value, before)
            row = value['runs'][canonical]
        if row.get('state') != 'VERIFIED':
            raise ValueError('Training case did not verify: ' + canonical)
        completed.append(canonical)
    if len(completed) != 64:
        raise ValueError('Training reconciliation did not cover 64 canonical responses')
    evidence = {'schema': 'dram-see-v3-r50-main-restart-training', 'physical_revision': REVISION,
                'restart_plan_sha256': sha(path), 'training_response_ids': completed,
                'actual_ledger_tags': actual_tags,
                'training_independent_events': 32, 'training_responses': 64,
                'state': 'VERIFIED'}
    write(RUNTIME / 'stages' / 'train.json', evidence, exclusive=True)
    write(RUNTIME / 'stage-index.json', {'schema': 'dram-see-v3-r50-main-restart-stage-index',
        'physical_revision': REVISION, 'plan_sha256': sha(path), 'stages': {'train': evidence},
        'accounting': 'Unique global ledger is the sole solver-cost truth'}, exclusive=True)
    return {'state': 'TRAINING_FINISHED_PENDING_PREDICTION', 'training_responses': 64,
            'training_independent_events': 32, 'actual_ledger_tags': actual_tags,
            'global_solver_s': RUN.budget()}


def run_retry(path, plan):
    current = ledger(); before = read(ROOT / plan['ledger_before']); case = plan['retry_case']
    if RETRY_TAG in current['runs']:
        row = current['runs'][RETRY_TAG]
        if row.get('state') == 'VERIFIED':
            return row
        raise ValueError('Retry already failed or is unsettled; no blind second retry')
    parent_tag = case['parent_tag']
    parent_row = current['runs'].get(parent_tag)
    if not parent_row or parent_row.get('state') != 'VERIFIED':
        raise ValueError('Retry parent control is not verified: ' + parent_tag)
    parent_run = parent_row['run_id']
    input_tag = safe_tag(RETRY_TAG)
    input_dir = LOCAL / 'inputs' / input_tag
    if input_dir.exists():
        raise ValueError('Retry input already exists; preserve and reconcile')
    params = retry_parameters(case)
    params['parent'] = parent_run
    B.build(input_dir, **params)
    execution = RUNTIME / 'case-freezes' / (RETRY_TAG + '.json')
    execution.parent.mkdir(parents=True, exist_ok=True)
    body = {'utc': C.now(), 'schema': SCHEMA, 'retry_tag': RETRY_TAG,
            'original_tag': OLD_FAILED_TAG, 'original_plan': rel(OLD_PLAN),
            'restart_plan': rel(path), 'restart_plan_sha256': sha(path),
            'inputs': {RETRY_TAG: {p.name: sha(p) for p in input_dir.iterdir() if p.is_file()}},
            'case': case, 'source_sha256': plan['source_sha256'],
            'parent_run': parent_run}
    write(execution, body, exclusive=True)
    current = ledger()
    item = {'state': 'RUNNING', 'tag': RETRY_TAG, 'started_utc': C.now(),
            'input_directory': rel(input_dir), 'execution_freeze': rel(execution),
            'execution_freeze_sha256': sha(execution), 'input_sha256': body['inputs'][RETRY_TAG],
            'parameters': read(input_dir / 'parameters.json'), 'inherited': False,
            'physical_revision': REVISION, 'physical_revision_probe_only': False,
            'original_100ohm_matrix_eligible': False, 'retry_of': OLD_FAILED_TAG}
    current['runs'][RETRY_TAG] = item; save_retry(current, before)
    logs = LOCAL / 'batch-logs'; logs.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-B', str(ROOT / 'scripts/tcad.py'), 'run', str(input_dir)]
    item['command'] = command; current = ledger(); current['runs'][RETRY_TAG] = item; save_retry(current, before)
    started = time.monotonic()
    stdout_path = logs / (RETRY_TAG + '.stdout.log'); stderr_path = logs / (RETRY_TAG + '.stderr.log')
    with stdout_path.open('xb') as out, stderr_path.open('xb') as err:
        result = subprocess.run(command, cwd=ROOT, stdout=out, stderr=err)
    item.update(runner_exit_code=result.returncode, elapsed_s=time.monotonic() - started, finished_utc=C.now())
    matches = list((ROOT / 'local_runtime/runs').glob('*-' + RETRY_TAG + '-*'))
    if len(matches) == 1:
        item['run_id'] = matches[0].name
    current = ledger(); current['runs'][RETRY_TAG] = item; save_retry(current, before)
    try:
        if len(matches) != 1 or result.returncode:
            raise RuntimeError('Retry runner failed or produced ambiguous archive')
        summary = A.audit(item['run_id'], export=True)
        item['charged_solver_s'] = summary.get('solver_s', summary.get('wallclock_s', item['elapsed_s']))
        item['state'] = 'VERIFIED'; item['raw_audit_state'] = 'PASSED'; item['audit_archive_sha256'] = summary.get('archive_sha256')
        item['retry_acceptance'] = 'engineering marker and numerical archive audit passed'
        current = ledger(); current['runs'][RETRY_TAG] = item; save_retry(current, before)
        return item
    except Exception as exc:
        item['state'] = 'FAILED'; item['failure_category'] = 'ENGINEERING_OR_NUMERICAL_RETRY_FAILED'; item['failure_reason'] = repr(exc)
        item['charged_solver_s'] = item.get('elapsed_s', 0.)
        current = ledger(); current['runs'][RETRY_TAG] = item; current['failures'].append(dict(item)); save_retry(current, before)
        raise


def progress(path, state, reason=None, row=None):
    value = {'schema': 'dram-see-v3-r50-main-restart-r2-progress', 'physical_revision': REVISION,
             'utc': C.now(), 'state': state, 'reason': reason, 'plan_sha256': sha(path),
             'retry_tag': RETRY_TAG, 'original_failed_tag': OLD_FAILED_TAG,
             'adopted_verified_count': len(read(path)['adopted_verified_tags']),
             'retry_row': row, 'fixed_main_independent_events': 64,
             'fixed_main_response_slots': 128,
             'implemented_terminal_state': 'TRAINING_FINISHED_PENDING_PREDICTION'}
    write(path.parent / 'status.json', value)


def execute(label='r2'):
    if label != 'r2':
        raise ValueError('Only restart-r2 is implemented')
    path = RUNTIME / 'plan.json'
    with C.controller_lock():
        plan = restart_plan(path); activation(); C.check_preservation()
        progress(path, 'CHECKING_PREREQUISITES')
        C.preflight('r50-main-restart-r2')
        progress(path, 'RETRY_SUBMITTING', row={'state': 'RUNNING', 'tag': RETRY_TAG})
        row = run_retry(path, plan)
        result = run_remaining_training(path, plan, read(ROOT / plan['ledger_before']))
        progress(path, result['state'], row=result)
        return {**result, 'retry_tag': RETRY_TAG, 'retry_state': row.get('state'),
                'adopted_verified_count': len(plan['adopted_verified_tags'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('freeze', 'execute'))
    parser.add_argument('--label', default='r2')
    args = parser.parse_args()
    result = freeze(args.label) if args.action == 'freeze' else execute(args.label)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
