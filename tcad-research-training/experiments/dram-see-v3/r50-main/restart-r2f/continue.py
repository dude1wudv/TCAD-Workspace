"""R50-main continuation after the r2e training reconciliation bug.

The r2e solver outputs are immutable evidence. This controller audits the
completed 64 canonical training responses (one deterministic retry alias),
freezes a new prediction plan, and then delegates the already reviewed
prediction/test implementation to the existing finish module.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = ROOT / 'experiments/dram-see-v3/r50-main'
LOCAL = ROOT / 'local_runtime/dram-see-v3'
R2E_PLAN = LOCAL / 'physical-revisions/r50-main-restart-r2e/plan.json'
R2C_RETRY_FREEZE = LOCAL / 'physical-revisions/r50-main-restart-r2c/case-freezes/v3-r50-main-retry-r2-l035-alpha-a30-s202610394-b1.json'
RUNTIME = LOCAL / 'physical-revisions/r50-main-restart-r2f'
ACCEPTANCE = LOCAL / 'physical-revisions/r50-main-restart-r2f-acceptance.json'
TRAINING_AUDIT = LOCAL / 'physical-revisions/r50-main-restart-r2f-training-audit.json'
OLD_FAILED = 'v3-r50-main-l035-alpha-a30-s202610394-b1'
RETRY = 'v3-r50-main-retry-r2-l035-alpha-a30-s202610394-b1'
REVISION = 'r50-main-r1'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), module.__dict__)
    return module


F = load_module('r50_followup_r2f', BASE / 'finish.py')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def write_json(path, value, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 'x' if exclusive else 'w'
    with path.open(mode, encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def first_stage_files():
    old = LOCAL / 'physical-revisions/r50-main-r1'
    files = {rel(R2E_PLAN): sha(R2E_PLAN), rel(R2C_RETRY_FREEZE): sha(R2C_RETRY_FREEZE)}
    for name in ('plan.json', 'stage-index.json'):
        path = old / name
        if path.is_file():
            files[rel(path)] = sha(path)
    for name in ('references.json', 'pilot.json', 'numerical_preregistered.json'):
        path = old / 'stages' / name
        if not path.is_file():
            raise ValueError('Missing verified prerequisite evidence: ' + rel(path))
        files[rel(path)] = sha(path)
    return files


def alias_bundle(tag):
    return ORIGINAL_BUNDLE(RETRY if tag == OLD_FAILED else tag)


ORIGINAL_BUNDLE = F.R.bundle
F.R.bundle = alias_bundle


def audit_training():
    design = F.R.design()
    ledger = F.C.load()
    cases = {case['tag']: case for case in F.R.cases(design)}
    wanted = [F.R.event_tag(event, bit) for event in design['events']
              if event['split'] == 'train' for bit in (0, 1)]
    if len(wanted) != 64 or len(set(wanted)) != 64:
        raise ValueError('Frozen design does not contain exactly 64 training responses')
    if OLD_FAILED not in wanted:
        raise ValueError('Retry alias is not a canonical training response')
    if ledger['runs'].get(OLD_FAILED, {}).get('state') != 'FAILED':
        raise ValueError('Original FAILED training row was changed')
    retry_row = ledger['runs'].get(RETRY)
    if not retry_row or retry_row.get('state') != 'VERIFIED' or retry_row.get('retry_of') != OLD_FAILED:
        raise ValueError('Verified deterministic retry alias is missing or inconsistent')
    actual = {}
    records = {}
    for canonical in wanted:
        actual_tag = RETRY if canonical == OLD_FAILED else canonical
        row = ledger['runs'].get(actual_tag)
        if not row or row.get('state') != 'VERIFIED' or row.get('runner_exit_code') != 0:
            raise ValueError('Training response is not independently VERIFIED: ' + canonical)
        params = row.get('parameters') or {}
        if ((row.get('physical_revision') not in (None, REVISION))
                or params.get('physical_revision') != REVISION
                or params.get('physical_revision_probe_only') is not False):
            raise ValueError('Training response physical identity mismatch: ' + actual_tag)
        if not isinstance(row.get('charged_solver_s'), (int, float)) or row['charged_solver_s'] <= 0:
            raise ValueError('Training response has no positive solver charge: ' + actual_tag)
        case = cases[canonical]
        bundle = alias_bundle(canonical)
        parent = F.C.resolve(case['parent_tag'])
        F.R.recipe(case, bundle['parameters'], parent)
        F.R.matching(case['matching_tags'])
        freeze = Path(row['execution_freeze'])
        if not freeze.is_absolute():
            freeze = ROOT / freeze
        if not freeze.is_file():
            if actual_tag == RETRY and R2C_RETRY_FREEZE.is_file():
                freeze = R2C_RETRY_FREEZE
            else:
                raise ValueError('Missing execution freeze: ' + actual_tag)
        freeze_value = read(freeze)
        freeze_case = freeze_value.get('case', {})
        if actual_tag != RETRY and freeze_case.get('tag') != canonical:
            raise ValueError('Execution freeze case identity mismatch: ' + canonical)
        if actual_tag == RETRY and freeze_case.get('retry_of') != OLD_FAILED:
            raise ValueError('Retry execution freeze is not bound to the original failure')
        actual[canonical] = actual_tag
        records[canonical] = {
            'state': 'VERIFIED', 'actual_tag': actual_tag, 'run_id': row['run_id'],
            'charged_solver_s': row['charged_solver_s'], 'execution_freeze': rel(freeze),
            'execution_freeze_sha256': sha(freeze), 'archive_sha256': row.get('audit_archive_sha256'),
        }
    files = first_stage_files()
    files[rel(TRAINING_AUDIT)] = sha(TRAINING_AUDIT) if TRAINING_AUDIT.is_file() else ''
    stage_files = {}
    old = LOCAL / 'physical-revisions/r50-main-r1'
    for stage in ('references', 'pilot', 'numerical_preregistered'):
        stage_files[stage] = read(old / 'stages' / (stage + '.json'))
        if stage_files[stage].get('state') != 'VERIFIED':
            raise ValueError('Prerequisite stage is not VERIFIED: ' + stage)
    train = {
        'schema': 'dram-see-v3-r50-main-restart-training-r2f',
        'physical_revision': REVISION, 'state': 'VERIFIED',
        'first_plan_sha256': sha(R2E_PLAN), 'training_response_ids': wanted,
        'actual_ledger_tags': actual, 'training_independent_events': 32,
        'training_responses': 64, 'records': records,
    }
    evidence = {'schema': 'dram-see-v3-r50-main-restart-r2f-training-audit',
                'utc': datetime.now(timezone.utc).isoformat(), 'design_sha256': F.R.DESIGN_SHA,
                'first_plan_sha256': sha(R2E_PLAN), 'training': train,
                'prerequisite_stages': stage_files, 'files_sha256': files}
    if TRAINING_AUDIT.exists():
        frozen = read(TRAINING_AUDIT)
        if (frozen.get('schema') != evidence['schema']
                or frozen.get('design_sha256') != evidence['design_sha256']
                or frozen.get('first_plan_sha256') != evidence['first_plan_sha256']
                or frozen.get('training') != evidence['training']
                or frozen.get('prerequisite_stages') != evidence['prerequisite_stages']):
            raise ValueError('Existing r2f training audit differs; preserve and reconcile')
        evidence = frozen
        files.update(frozen.get('files_sha256', {}))
    else:
        write_json(TRAINING_AUDIT, evidence, exclusive=True)
    files[rel(TRAINING_AUDIT)] = sha(TRAINING_AUDIT)
    comparisons = stage_files['numerical_preregistered'].get('comparisons', [])
    return {'design': design, 'files': files, 'stages': {**stage_files, 'train': train},
            'comparisons': comparisons, 'training': train, 'first_plan_sha256': sha(R2E_PLAN)}


def acceptance():
    value = read(ACCEPTANCE)
    if (value.get('schema') != 'dram-see-v3-r50-main-restart-r2f-acceptance'
            or value.get('approved') is not True or value.get('design_sha256') != F.R.DESIGN_SHA
            or value.get('first_plan_sha256') != sha(R2E_PLAN)
            or value.get('source_manifest_sha256') != sha(BASE / 'followup-source-manifest.json')
            or value.get('evidence') != rel(TRAINING_AUDIT)):
        raise ValueError('r2f acceptance is missing or bound to different evidence')
    return value


def unlimited_deadline(*_args, **_kwargs):
    return {'new_submission_allowed': True, 'policy': 'unlimited_authorization'}


def check_plan(path):
    path = Path(path)
    plan = read(path)
    if (plan.get('schema') != 'dram-see-v3-r50-main-restart-r2f-plan'
            or plan.get('physical_revision') != REVISION or plan.get('label') != 'r2f'
            or plan.get('source_sha256') != F.sources() or plan.get('planned_cases') != F.cases()
            or plan.get('first_plan_sha256') != sha(R2E_PLAN) or plan.get('global_budget_s') is not None
            or plan.get('terminal_state') != 'TEST_FINISHED_PENDING_EXTENSIONS'):
        raise ValueError('r2f plan identity/recipe/policy mismatch')
    if read(path.with_name('plan-sha256.json')).get('sha256') != sha(path):
        raise ValueError('r2f plan self-hash mismatch')
    for name, digest in plan['source_sha256'].items():
        if sha(path.parent / 'source-snapshot' / name) != digest:
            raise ValueError('r2f source snapshot differs: ' + name)
    for name, digest in plan['frozen_files_sha256'].items():
        if sha(ROOT / name) != digest:
            raise ValueError('r2f frozen evidence differs: ' + name)
    ledger_before = ROOT / plan['ledger_before']
    if sha(ledger_before) != plan['ledger_before_sha256']:
        raise ValueError('r2f protected ledger snapshot changed')
    F.R.ledger_unchanged(read(ledger_before), F.C.load(), {case['tag'] for case in F.cases()})
    return plan


def reserve(_plan):
    return {'new_submission_allowed': True, 'global_solver_s_before': F.C.budget(),
            'next_estimate_s': 600, 'budget_policy': 'unlimited_authorization'}


def freeze():
    if RUNTIME.exists():
        raise ValueError('r2f runtime already exists; preserve and reconcile')
    if ACCEPTANCE.exists():
        raise ValueError('r2f acceptance already exists; preserve and reconcile')
    with F.C.controller_lock():
        F.host_guard()
        F.C.check_preservation(); F.C.budget()
        proof = audit_training()
        F.no_test_submissions(F.C.load(), F.actual_manifests())
        source = F.sources()
        acceptance_value = {
            'schema': 'dram-see-v3-r50-main-restart-r2f-acceptance', 'approved': True,
            'design_sha256': F.R.DESIGN_SHA, 'first_plan_sha256': proof['first_plan_sha256'],
            'source_manifest_sha256': sha(BASE / 'followup-source-manifest.json'),
            'accepted_utc': datetime.now(timezone.utc).isoformat(), 'evidence': rel(TRAINING_AUDIT),
            'basis': 'automated root audit of immutable r2e/r2c records; no solver dispatch',
        }
        write_json(ACCEPTANCE, acceptance_value, exclusive=True)
        proof['files'][rel(ACCEPTANCE)] = sha(ACCEPTANCE)
        RUNTIME.mkdir(parents=True, exist_ok=False)
        for name, digest in source.items():
            target = RUNTIME / 'source-snapshot' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
            if sha(target) != digest:
                raise ValueError('Source changed during r2f snapshot: ' + name)
        before_bytes = F.C.LEDGER.read_bytes()
        before_path = RUNTIME / 'ledger-before.json'
        before_path.write_bytes(before_bytes)
        frozen = dict(proof['files'])
        frozen[rel(ACCEPTANCE)] = sha(ACCEPTANCE)
        plan = {
            'schema': 'dram-see-v3-r50-main-restart-r2f-plan', 'physical_revision': REVISION,
            'label': 'r2f', 'utc': datetime.now(timezone.utc).isoformat(),
            'design_sha256': F.R.DESIGN_SHA, 'source_sha256': source,
            'planned_cases': F.cases(), 'first_plan_sha256': proof['first_plan_sha256'],
            'frozen_files_sha256': frozen, 'ledger_before': rel(before_path),
            'ledger_before_sha256': sha(before_path), 'stage_order': ['test_transport', 'prediction_freeze', 'test'],
            'maximum_new_solver_calls': 64, 'global_budget_s': None,
            'budget_policy': 'unlimited_authorization; unique global ledger remains accounting truth',
            'terminal_state': 'TEST_FINISHED_PENDING_EXTENSIONS',
            'extensions_and_delivery_implemented': False,
        }
        write_json(RUNTIME / 'plan.json', plan, exclusive=True)
        write_json(RUNTIME / 'plan-sha256.json', {'sha256': sha(RUNTIME / 'plan.json')}, exclusive=True)
        check_plan(RUNTIME / 'plan.json')
        return {'state': 'FROZEN', 'plan_sha256': sha(RUNTIME / 'plan.json'),
                'training_responses': 64, 'training_independent_events': 32}


def configure():
    F.RUNTIME = RUNTIME
    F.ACCEPTANCE = ACCEPTANCE
    F.directory = lambda label='r2f': RUNTIME
    F.acceptance = acceptance
    F.checked_training = lambda: audit_training()
    F.check_plan = check_plan
    F.reserve = reserve
    F.R.deadline = unlimited_deadline
    F.submission_preflight = lambda tag: (F.R.BASE_PREFLIGHT(tag), unlimited_deadline())[-1]


def execute():
    configure()
    result = F.execute('r2f')
    return result


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'freeze'
    configure()
    if action == 'freeze':
        result = freeze()
    elif action == 'execute':
        result = execute()
    else:
        raise SystemExit('usage: continue.py freeze|execute')
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
