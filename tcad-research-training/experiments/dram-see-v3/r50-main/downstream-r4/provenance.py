"""Read-only, alias-aware R4 provenance. Never fits, dispatches or writes evidence."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[2]
LOCAL = ROOT / 'local_runtime/dram-see-v3'
REVISION = 'r50-main-r1'
DESIGN_SHA = '6d52749bb8b9716b13b5ff1aa562a3ee331e3d7a062f32287c23710a5d1cf740'
R4_SHA = '2b19a32059b95d782d9ddf100f225c9079e9d06c9fc9b4cfcf1bbff1704a10a1'
PREDICTION_SHA = 'f0384066be6d42bb71dad6fd8e4e1a2f474e6f9f45d918da759ca0274a4cff9e'
PLAN = LOCAL / 'physical-revisions/r50-main-restart-r4/plan.json'
PREDICTION_PLAN = LOCAL / 'physical-revisions/r50-main-restart-r2f/plan.json'
FIRST_PLAN = LOCAL / 'physical-revisions/r50-main-r1/plan.json'
TRAINING_PLAN = LOCAL / 'physical-revisions/r50-main-restart-r2e/plan.json'
TRAINING_AUDIT = LOCAL / 'physical-revisions/r50-main-restart-r2f-training-audit.json'
ALIASES = {
    'v3-r50-main-l035-alpha-a30-s202610394-b1': 'v3-r50-main-retry-r2-l035-alpha-a30-s202610394-b1',
    'v3-r50-main-l025-alpha-a30-s202610353-b0': 'v3-r50-main-retry-r3-l025-alpha-a30-s202610353-b0',
    'v3-r50-main-l025-proton-a0-s202610361-b0': 'v3-r50-main-retry-r3-l025-proton-a0-s202610361-b0',
    'v3-r50-main-l025-proton-a30-s202610371-b1': 'v3-r50-main-retry-r4-l025-proton-a30-s202610371-b1',
}
TRAIN_ALIAS = next(iter(ALIASES))
OWN_FILES = ('provenance.py', 'extensions.py', 'implementation.md', 'test_downstream.py')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


LOADED_SHA = sha(__file__)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def repo(path):
    result = (ROOT / path).resolve()
    if not result.is_relative_to(ROOT):
        raise ValueError('Evidence path escapes project')
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), value.__dict__)
    return value


def source_inventory():
    """Inventory only; never creates or refreshes a manifest."""
    r4 = read(BASE / 'restart-r4/source-manifest.json')
    old = read(BASE / 'extensions-source-manifest.json')
    result = dict(r4['files_sha256'])
    for name, digest in old['files_sha256'].items():
        require(name not in result or result[name] == digest, 'Upstream source manifests conflict')
        result[name] = digest
    for path in (BASE / 'restart-r4/source-manifest.json', BASE / 'extensions-source-manifest.json'):
        result[rel(path)] = sha(path)
    result.update({rel(HERE / name): sha(HERE / name) for name in OWN_FILES})
    return result


def sources():
    path = HERE / 'source-manifest.json'
    expected = source_inventory(); value = read(path)
    require(expected[rel(HERE / 'provenance.py')] == LOADED_SHA, 'Loaded provenance source differs from disk')
    require(value.get('schema') == 'dram-see-v3-downstream-r4-sources'
            and value.get('r4_plan_sha256') == R4_SHA and value.get('files_sha256') == expected,
            'Downstream fixed source manifest differs')
    for name, digest in expected.items():
        require(sha(repo(name)) == digest, 'Frozen source changed: ' + name)
    return {**expected, rel(path): sha(path)}


def validate_aliases(ledger):
    """Pure identity gate; original unknown exit codes are never repaired."""
    rows = ledger['runs']
    for original, actual in ALIASES.items():
        require(rows.get(original, {}).get('state') == 'FAILED', 'Original FAILED missing: ' + original)
        require(rows[original].get('runner_exit_code') is None, 'Original unknown runner exit changed')
        aliases = [tag for tag, row in rows.items() if row.get('retry_of') == original]
        require(aliases == [actual], 'Retry alias is missing, duplicated or unknown')
        row = rows[actual]
        require(row.get('state') == 'VERIFIED' and row.get('runner_exit_code') == 0,
                'Retry is not actually VERIFIED: ' + actual)
    ids = [r['run_id'] for r in rows.values() if r.get('run_id')]
    require(len(ids) == len(set(ids)), 'Duplicate raw run ID in global ledger')
    return dict(ALIASES)


class Session:
    """One immutable read snapshot; create a new Session after a real new solve.

    extension_plan may only be the independently frozen downstream R4 plan.
    Public methods return ordinary serializable data; ledger is never rewritten.
    """
    def __init__(self, extension_plan=None):
        self.files = {}
        self.ledger_path = LOCAL / 'ledger.json'
        self.ledger = self.bind(self.ledger_path)
        self.q = module('_downstream_r4_readonly', BASE / 'restart-r4/continue.py')
        self.core = self.q.CORE
        self.C, self.R, self.F = self.q.C, self.q.R, self.q.F
        self.raw_bundle = self.core.PREVIOUS.ORIGINAL_BUNDLE
        self.R.bundle = self.bundle
        self.F.existing_test_attempts = self.validate_actual_inputs
        self.ext = module('_downstream_original_extensions', BASE / 'extensions.py')
        self.extension_path = repo(extension_plan) if extension_plan is not None else None
        self.extension = self.bind(self.extension_path) if self.extension_path else None
        self.plan = None
        self.training = None
        self.first = {c['tag']: c for c in self.R.cases()}
        self.tests = {c['tag']: c for c in self.F.cases()}
        self.cases = {**self.first, **self.tests}
        self.traces = {}

    def bind(self, path):
        path = repo(path)
        digest = sha(path)
        require(rel(path) not in self.files or self.files[rel(path)] == digest, 'Evidence changed during review')
        self.files[rel(path)] = digest
        return read(path)

    def bind_hash(self, path, expected=None):
        path = repo(path); digest = sha(path)
        require(expected is None or digest == expected, 'Bound evidence changed: ' + rel(path))
        require(rel(path) not in self.files or self.files[rel(path)] == digest, 'Evidence changed during review')
        self.files[rel(path)] = digest
        return digest

    def stable(self):
        for path, digest in self.files.items():
            require(sha(repo(path)) == digest, 'Evidence changed since read: ' + path)
        return True

    def plan_snapshot(self, path):
        value = self.bind(path)
        require(self.bind(path.with_name('plan-sha256.json')).get('sha256') == sha(path), 'Plan marker differs')
        for name, digest in value['source_sha256'].items():
            self.bind_hash(repo(name), digest)
            self.bind_hash(path.parent / 'source-snapshot' / name, digest)
        self.bind_hash(repo(value['ledger_before']), value['ledger_before_sha256'])
        return value

    def validate_chain(self):
        sources(); self.core.authorization()
        self.bind_hash(self.core.AUTH, self.core.AUTH_SHA)
        self.bind_hash(PLAN, R4_SHA)
        self.plan = self.plan_snapshot(PLAN)
        require(self.plan.get('schema') == 'dram-see-v3-r50-main-restart-r4-plan'
                and self.plan.get('source_sha256') == self.q.sources()
                and self.plan.get('aliases') == {k: v for k, v in ALIASES.items() if k != TRAIN_ALIAS}
                and self.plan.get('planned_cases') == list(self.tests.values())
                and self.plan.get('global_budget_s') is None and self.plan.get('deadline_utc') is None,
                'R4 source, aliases, canonical inventory or unlimited policy differs')
        for name, digest in self.plan['frozen_files_sha256'].items():
            self.bind_hash(repo(name), digest)
        self.bind_hash(PREDICTION_PLAN, self.core.OLD_PLAN_SHA)
        for path in (FIRST_PLAN, TRAINING_PLAN, PREDICTION_PLAN, self.q.R3_PLAN,
                     LOCAL / 'physical-revisions/r50-main-restart-r2c/plan.json'):
            self.plan_snapshot(path)
        self.training = self.bind(TRAINING_AUDIT)
        wanted = [self.R.event_tag(e, b) for e in self.R.design()['events'] if e['split'] == 'train' for b in (0, 1)]
        t = self.training['training']
        require(self.training.get('design_sha256') == DESIGN_SHA and self.training.get('first_plan_sha256') == sha(TRAINING_PLAN)
                and t.get('state') == 'VERIFIED' and t.get('training_response_ids') == wanted
                and t.get('training_responses') == 64 and t.get('training_independent_events') == 32,
                'Preserved training64 audit differs')
        require(t.get('actual_ledger_tags') == {x: ALIASES.get(x, x) for x in wanted}, 'Training alias map differs')
        validate_aliases(self.ledger)
        allowed = set(self.plan['aliases'].values()) | set(self.tests)
        if self.extension:
            require(self.extension_path == LOCAL / 'physical-revisions/r50-main-extensions-r4/plan.json'
                    and self.extension.get('schema') == 'dram-see-v3-r50-main-extensions-r4-plan', 'Wrong downstream extension identity')
            require(self.bind(self.extension_path.with_name('plan-sha256.json')).get('sha256') == sha(self.extension_path),
                    'Extension marker differs')
            require(self.extension.get('planned_cases') == self.ext.cases(self.extension['selection']), 'Extension fixed cases differ')
            require(self.extension.get('test_plan_sha256') == R4_SHA and self.extension.get('source_sha256') == sources(),
                    'Extension upstream/source identity differs')
            for name, digest in self.extension['source_sha256'].items():
                self.bind_hash(self.extension_path.parent / 'source-snapshot' / name, digest)
            for name, digest in self.extension['frozen_files_sha256'].items():
                self.bind_hash(repo(name), digest)
            self.bind_hash(repo(self.extension['ledger_before']), self.extension['ledger_before_sha256'])
            self.R.ledger_unchanged(self.bind(repo(self.extension['ledger_before'])), self.ledger,
                                    {c['tag'] for c in self.extension['planned_cases']})
            allowed |= {c['tag'] for c in self.extension['planned_cases']}
        self.R.ledger_unchanged(self.bind(repo(self.plan['ledger_before'])), self.ledger, allowed)
        require(self.plan['prior_case_plans'] == self.q.prior_routes(self.bind(repo(self.plan['ledger_before'])), self.bind(self.q.R3_PLAN)),
                'Protected test owner map differs')
        return {'aliases': dict(ALIASES), 'r4_plan_sha256': R4_SHA, 'prediction_plan_sha256': sha(PREDICTION_PLAN),
                'training_audit_sha256': sha(TRAINING_AUDIT), 'files': dict(self.files)}

    def bundle(self, tag):
        actual = ALIASES.get(tag, tag)
        value = self.raw_bundle(actual)
        folder = self.R.A.run_folder(value['summary']['run_id'])
        for name in ('manifest.json', 'inputs.tar', 'results.tar'):
            self.bind_hash(folder / name)
        return value

    def trace_case(self, canonical):
        require(self.plan is not None and self.training is not None, 'validate_chain must precede case review')
        case = self.cases[canonical]; actual = ALIASES.get(canonical, canonical)
        row = self.ledger['runs'].get(actual, {})
        require(row.get('state') == 'VERIFIED' and row.get('runner_exit_code') == 0, 'Response not VERIFIED: ' + canonical)
        if canonical in self.tests:
            actual_case = copy.deepcopy(case)
            if actual != canonical:
                actual_case.update(tag=actual, retry_of=canonical)
            old_owner = self.plan['prior_case_plans'].get(actual)
            if old_owner:
                owner = repo(old_owner)
            else:
                require(actual_case in self.plan['dispatch_cases'], 'Test absent from frozen dispatch owners')
                owner = PLAN
            require(owner in (PREDICTION_PLAN, self.q.R3_PLAN, PLAN), 'Unknown test owner')
            freeze = self.F.case_checked(owner, actual_case, row)
            if actual != canonical:
                original = self.ledger['runs'][canonical]
                old, new = self.core.input_archive(original), self.core.input_archive(row)
                self.core.same_retry_inputs(original['input_sha256'], row['input_sha256'], read_project(old), read_project(new))
        elif canonical in self.training['training']['records']:
            record = self.training['training']['records'][canonical]
            require(record['actual_tag'] == actual and record['run_id'] == row['run_id']
                    and record['execution_freeze_sha256'] == row['execution_freeze_sha256']
                    and record['archive_sha256'] == row['audit_archive_sha256']
                    and record['charged_solver_s'] == row['charged_solver_s'], 'Training audit raw identity differs')
            freeze = repo(record['execution_freeze']); frozen = self.bind(freeze)
            self.bind_hash(freeze, record['execution_freeze_sha256'])
            if canonical == TRAIN_ALIAS:
                owner = LOCAL / 'physical-revisions/r50-main-restart-r2c/plan.json'
                require(frozen.get('restart_plan') == rel(owner) and frozen.get('restart_plan_sha256') == sha(owner)
                        and frozen.get('original_tag') == canonical and frozen.get('retry_tag') == actual,
                        'Training retry owner differs')
            else:
                owner = repo(frozen['main_plan'])
                require(owner in (FIRST_PLAN, TRAINING_PLAN) and frozen.get('main_plan_sha256') == sha(owner),
                        'Training case owner differs')
            fcase = frozen['case']
            require(fcase.get('tag') == actual and all(fcase.get(k) == case.get(k) for k in ('kwargs', 'role', 'parent_tag', 'matching_tags', 'event')),
                    'Training frozen recipe differs')
            require(frozen.get('inputs') == {actual: row['input_sha256']} and rel(freeze) == row['execution_freeze'],
                    'Training case prepared inputs differ')
            for name, digest in frozen['source_sha256'].items():
                self.bind_hash(repo(name), digest)
            folder = LOCAL / 'inputs' / actual
            require({p.name: sha(p) for p in folder.iterdir() if p.is_file()} == row['input_sha256'], 'Training prepared files changed')
        else:
            owner = FIRST_PLAN
            freeze = self.R.case_checked(owner, case, row)
        self.bind_hash(freeze, row['execution_freeze_sha256']); self.bind_hash(owner)
        value = self.bundle(canonical)
        parent = self.ledger['runs'][case['parent_tag']]['run_id'] if case['parent_tag'] else None
        self.R.recipe(case, value['parameters'], parent)
        self.R.matching([canonical, *case['matching_tags']])
        result = {'response_id': canonical, 'actual_ledger_tag': actual, 'run_id': row['run_id'],
            'owner_plan': rel(owner), 'owner_plan_sha256': sha(owner), 'case_freeze': rel(freeze),
            'case_freeze_sha256': sha(freeze), 'input_sha256': row['input_sha256'], 'archive_sha256': row['audit_archive_sha256']}
        self.traces[canonical] = result
        return result

    def observation(self, canonical_response_id):
        case = self.cases[canonical_response_id]
        require(case['role'] == 'event' and 'event' in case, 'Canonical event response required')
        trace = self.trace_case(canonical_response_id)
        value = self.R.observation(canonical_response_id, *case['matching_tags'])
        return {**trace, 'observation': value}

    def validate_actual_inputs(self, frozen):
        """Retain every actual input, including FAILED originals and exact extensions."""
        require(self.plan is not None, 'Prediction input review requires validated chain')
        allowed = dict(self.cases)
        for canonical, actual in ALIASES.items():
            allowed[actual] = {**allowed[canonical], 'tag': actual}
        extras = {c['tag']: c for c in self.extension['planned_cases']} if self.extension else {}
        allowed.update(extras)
        seen = set()
        for item in self.F.actual_manifests():
            p = item['parameters']
            if p.get('schema') != self.R.SCHEMA and p.get('physical_revision') != REVISION:
                continue
            self.F.is_test(p)  # validates the complete physical identity even for non-test inputs
            matches = [(t, r) for t, r in self.ledger['runs'].items() if r.get('run_id') == item['run_id']]
            require(len(matches) == 1, 'R50 input lacks unique original ledger row')
            tag, row = matches[0]
            require(tag in allowed and row.get('parameters') == p, 'Unplanned or mismatched R50 actual input: ' + tag)
            require(row.get('state') == 'VERIFIED' or tag in ALIASES and row.get('state') == 'FAILED',
                    'Unsettled/failed non-original input blocks further work')
            self.core.input_archive(row)  # inputs only; never original FAILED electrical output
            case = allowed[tag]; parent = self.ledger['runs'][case['parent_tag']]['run_id'] if case['parent_tag'] else None
            if tag in extras:
                self.ext.recipe(case, p, parent)
                require(tag in self.extension['reused_cases'] or row.get('deterministic_extension_only') is True,
                        'Missing deterministic extension role')
                self.extension_case(case, row)
            else:
                self.R.recipe(case, p, parent)
            if self.F.is_test(p):
                self.F.submitted_after_freeze(row, frozen)
            folder = self.R.A.run_folder(row['run_id'])
            self.bind_hash(folder / 'manifest.json', item['manifest_sha256'])
            self.bind_hash(folder / 'inputs.tar', item['inputs_sha256'])
            seen.add(tag)
        expected = {t for t, row in self.ledger['runs'].items() if row.get('parameters', {}).get('physical_revision') == REVISION}
        require(seen == expected, 'Recorded R50 input lacks real matching archive')

    def extension_case(self, case, row):
        require(self.extension is not None, 'No accepted extension plan')
        if case['tag'] in self.extension['reused_cases']:
            return self.trace_case(case['tag'])
        path = self.extension_path.parent / 'case-freezes' / (case['tag'] + '.json')
        value = self.bind(path)
        require(value.get('extension_plan_sha256') == sha(self.extension_path) and value.get('case') == case
                and value.get('source_sha256') == self.extension['source_sha256']
                and value.get('inputs') == {case['tag']: row['input_sha256']}
                and value.get('prediction_freeze_sha256') == PREDICTION_SHA
                and row.get('execution_freeze') == rel(path) and row.get('execution_freeze_sha256') == sha(path),
                'Extension case provenance differs')
        self.C.check_execution(path)
        return value

    def check_prediction(self):
        self.bind_hash(BASE / 'data/predictions/freeze.json', PREDICTION_SHA)
        frozen = self.F.check_prediction(PREDICTION_PLAN)
        for name, digest in frozen['files_sha256'].items():
            self.bind_hash(repo(name), digest)
        self.bind_hash(PREDICTION_PLAN.parent / 'prediction-binding.json')
        self.bind_hash(BASE / 'data/predictions/freeze.sha256')
        return frozen

    def scientific_first(self):
        """Recheck actual references, isolation, preregistered comparisons and training."""
        stages = {}
        for stage in ('references', 'pilot', 'numerical_preregistered'):
            stages[stage] = self.bind(FIRST_PLAN.parent / 'stages' / (stage + '.json'))
            require(stages[stage].get('state') == 'VERIFIED' and stages[stage].get('plan_sha256') == sha(FIRST_PLAN), 'Original gate differs')
            require(self.training['prerequisite_stages'][stage] == stages[stage], 'Training prerequisite differs')
        for tag, case in self.first.items():
            self.trace_case(tag)
            value = self.bundle(tag)
            if case['stage'] in stages:
                record = stages[case['stage']]['cases'][tag]
                require(record.get('state') == 'VERIFIED' and record.get('run_id') == value['summary']['run_id']
                        and record.get('archive_sha256') == value['summary']['archive_sha256'], 'Original gate raw identity differs')
                if case['role'] == 'physical':
                    computed = self.R.M.compare_physical_curves(value, self.bundle(case['offline_tag']), self.bundle(self.R.neutral_tag(case['kwargs']['length'])))
                    require(computed['passed'], 'Reference/source-isolation comparison failed')
                elif case['role'] == 'event':
                    computed = self.R.M.compute_curves(value, *(self.bundle(t) for t in case['matching_tags']))
                else:
                    computed = None
                if computed is not None:
                    require(self.bind(repo(record['evidence'])) == computed, 'Original metric/comparison differs')
                    self.bind_hash(repo(record['evidence']), record['evidence_sha256'])
        d = self.R.design(); event = self.R.target_event(d); bit = d['numerical']['preregistered']['stored_bit']; length = event['gate_length_um']
        baseline = self.R.observation(self.R.event_tag(event, bit), self.R.control_tag(length, bit), self.R.neutral_tag(length))
        comparisons = []
        for variation in d['numerical']['variations']:
            step, mesh = variation['step'], variation['mesh']
            refined = self.R.observation(self.R.refined_tag(event, bit, step, mesh), self.R.control_tag(length, bit, step, mesh), self.R.neutral_tag(length, step, mesh))
            comparisons.append({'response_id': self.R.event_tag(event, bit), 'event': event, 'stored_bit': bit, 'variation': variation,
                **self.R.N.compare_observations(baseline, refined, tuple(x / 1000 for x in d['thresholds_mV']),
                    d['gates']['numerical_readout_change_mV'] / 1000, d['gates']['numerical_deltaQ_change_fC'])})
        numeric = self.bind(BASE / 'data/numerical/preregistered.json')
        require(numeric.get('comparisons') == comparisons and numeric.get('continuous_passed') is True
                and all(c['continuous_passed'] for c in comparisons), 'Preregistered numerical gate failed/differs')
        self.bind_hash(BASE / 'data/numerical/preregistered.json', stages['numerical_preregistered']['evidence_sha256'])
        return comparisons

    def prerequisites(self):
        status = self.bind(PLAN.parent / 'status.json')
        require(status.get('state') == 'TEST_FINISHED_PENDING_EXTENSIONS', 'Actual R4 test64 is not complete')
        self.validate_chain(); self.scientific_first(); frozen = self.check_prediction()
        baseline, population, traces = {}, [], {}
        for event in self.R.design()['events']:
            for bit in (0, 1):
                canonical = self.R.event_tag(event, bit); value = self.observation(canonical)
                traces[canonical] = {k: v for k, v in value.items() if k != 'observation'}
                baseline[canonical] = value['observation']; metric = value['observation']['metrics']
                population.append({'response_id': canonical, 'event': event, 'stored_bit': bit, 'state': 'VERIFIED',
                    'M4_V': metric['M4_V'], 'metric_sources': metric['sources']})
        require(len(population) == 128, 'Exactly128 canonical main responses required')
        for row in self.bind(BASE / 'data/predictions/training-data.json'):
            event = next(e for e in self.R.design()['events'] if e['label'] == row['event_label'])
            metric = baseline[self.R.event_tag(event, row['stored_bit'])]['metrics']
            require(row['targets'] == {'deltaQ_fC': metric['deltaQ_fC'], 'deltaM_mV': metric['deltaM_V'] * 1000}
                    and row['sources'] == metric['sources'] and row['classification'] == metric['classification'],
                    'Frozen training row differs from actual matching archives')
        observed = []
        for canonical, case in self.tests.items():
            actual = ALIASES.get(canonical, canonical); metric = baseline[canonical]['metrics']
            file = PLAN.parent / 'metrics' / (canonical + '.json')
            require(self.bind(file) == metric, 'R4 saved metric differs from original raw')
            observed.append({'response_id': canonical, 'actual_ledger_tag': actual, 'retry_of': canonical if actual != canonical else None,
                'event_label': case['event']['label'], 'stored_bit': case['kwargs']['bit'], 'continuous_valid': True,
                'continuous_numerical_status': 'RAW_AUDIT_PASSED', 'targets': {'deltaQ_fC': metric['deltaQ_fC'], 'deltaM_mV': metric['deltaM_V'] * 1000},
                'classification': metric['classification'], 'sources': metric['sources'],
                'metrics_evidence': {'evidence': rel(file), 'evidence_sha256': sha(file)}})
        scores = self.F.P.score_predictions(read(BASE / 'data/predictions/predictions.json'), observed, self.R.design())
        score_path = PLAN.parent / 'prediction-scores.json'
        require(self.bind(score_path) == scores, 'Preserved original R4 score differs')
        result = self.bind(PLAN.parent / 'test-result.json')
        expected = self.q.completed_result(observed, {'evidence': rel(score_path), 'evidence_sha256': sha(score_path)})
        require(result == expected, 'Actual R4 completed result/ordered aliases/raw attempts differ')
        selection = self.ext.boundary_ranking(population, 2, tuple(v / 1000 for v in self.R.design()['thresholds_mV']))
        require(selection['selection_status'] == 'FROZEN', 'Complete boundary ranking unavailable')
        self.stable()
        return {'files': dict(self.files), 'baseline': baseline, 'selection': selection, 'response_sources': traces,
            'aliases': dict(ALIASES), 'original_failures': {t: copy.deepcopy(self.ledger['runs'][t]) for t in ALIASES},
            'raw_submission_index': result['raw_submission_index'], 'first_plan_sha256': sha(FIRST_PLAN),
            'training_plan_sha256': sha(TRAINING_PLAN), 'training_audit_sha256': sha(TRAINING_AUDIT),
            'prediction_plan_sha256': sha(PREDICTION_PLAN), 'test_plan_sha256': R4_SHA,
            'test_result_sha256': sha(PLAN.parent / 'test-result.json'), 'prediction_freeze_sha256': PREDICTION_SHA,
            'original_prediction_scores': scores, 'observed_tests': observed}


def read_project(blobs):
    return json.loads(blobs['project.json'])
