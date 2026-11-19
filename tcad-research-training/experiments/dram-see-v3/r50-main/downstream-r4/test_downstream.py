"""Focused isolated software checks. SYNTHETIC fixtures are not science evidence."""
from contextlib import nullcontext
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('downstream_under_test', HERE / 'extensions.py')
X = importlib.util.module_from_spec(spec)
exec(compile((HERE / 'extensions.py').read_bytes(), str(HERE / 'extensions.py'), 'exec'), X.__dict__)
P = X.P
DEV = P.LOCAL / 'downstream-r4-development'


def aliases_ledger():
    rows = {}
    for i, (old, new) in enumerate(P.ALIASES.items()):
        rows[old] = {'state': 'FAILED', 'run_id': 'SYNTHETIC-original-' + str(i), 'runner_exit_code': None}
        rows[new] = {'state': 'VERIFIED', 'run_id': 'SYNTHETIC-retry-' + str(i), 'runner_exit_code': 0, 'retry_of': old}
    return {'runs': rows}


class DownstreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        DEV.mkdir(parents=True, exist_ok=True)
        cls.old = P.module('_synthetic_test_original_extensions', P.BASE / 'extensions.py')
        cls.design = cls.old.R.design()
        cls.frozen_sources = {name: P.sha(P.repo(name)) for name in P.read(P.PLAN)['source_sha256']}

    @classmethod
    def tearDownClass(cls):
        assert cls.frozen_sources == {name: P.sha(P.repo(name)) for name in cls.frozen_sources}, 'Frozen sources changed'

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='SYNTHETIC-', dir=DEV)
        self.root = Path(self.temp.name)
        self.original_globals = (X.SESSION, X.BEFORE, X.ACTIVE, dict(X.CONTEXT))

    def tearDown(self):
        X.SESSION, X.BEFORE, X.ACTIVE, context = self.original_globals
        X.CONTEXT.clear(); X.CONTEXT.update(context)
        self.temp.cleanup()

    def population(self):
        return [{'response_id': self.old.R.event_tag(e, b), 'event': e, 'stored_bit': b,
                 'state': 'VERIFIED', 'M4_V': .003, 'metric_sources': {'fixture': 'SYNTHETIC'}}
                for e in self.design['events'] for b in (0, 1)]

    def test_exact_aliases_keep_all_failed_unknown_exits(self):
        ledger = aliases_ledger(); before = copy.deepcopy(ledger)
        self.assertEqual(P.validate_aliases(ledger), P.ALIASES)
        self.assertEqual(ledger, before)
        ledger['runs'][P.TRAIN_ALIAS]['runner_exit_code'] = 0
        with self.assertRaisesRegex(ValueError, 'unknown runner exit'):
            P.validate_aliases(ledger)

    def test_unknown_duplicate_and_failed_alias_rejected(self):
        for mutation in ('duplicate', 'failed', 'run_id'):
            ledger = aliases_ledger(); old, actual = next(iter(P.ALIASES.items()))
            if mutation == 'duplicate':
                ledger['runs']['SYNTHETIC-extra'] = {**ledger['runs'][actual], 'run_id': 'SYNTHETIC-extra'}
            elif mutation == 'failed':
                ledger['runs'][actual]['state'] = 'FAILED'
            else:
                ledger['runs'][actual]['run_id'] = ledger['runs'][old]['run_id']
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                P.validate_aliases(ledger)

    def test_boundary_full128_ties_and_missing_blocks(self):
        population = self.population()
        selection = self.old.boundary_ranking(population)
        self.assertEqual(selection['population_count'], 128)
        self.assertEqual([r['response_id'] for r in selection['selected']], [r['response_id'] for r in population[:2]])
        population[-1]['state'] = 'FAILED'
        self.assertEqual(self.old.boundary_ranking(population)['selected'], [])
        with self.assertRaisesRegex(ValueError, 'complete'):
            self.old.cases(self.old.boundary_ranking(population), self.design)

    def test_oxide14_matching_shared_cases_and_no_new_events(self):
        cases = self.old.cases(self.old.boundary_ranking(self.population()), self.design)
        oxide = [c for c in cases if c['stage'] == 'oxide']
        self.assertEqual(len(oxide), 14)
        self.assertEqual(sum(c['role'] == 'event' for c in oxide), 8)
        self.assertEqual({c['kwargs']['oxide_nm'] for c in oxide}, {4., 6.})
        self.assertEqual({c['event']['seed'] for c in oxide if c['event']}, {202610341, 202610361})
        boundary = [c for c in cases if c['stage'] == 'boundary']
        self.assertEqual(len(boundary), 10)  # two bits share neutral only, each variation
        self.assertEqual(len({c['tag'] for c in cases}), len(cases))

    def test_numerical_unknown_near_and_crossing_remain_uncertain(self):
        population = self.population(); baseline = {r['response_id']: {'metrics': {'M4_V': .0025}} for r in population}
        tag = population[0]['response_id']
        comparisons = [{'response_id': tag, 'variation': {'step': .5, 'mesh': 1.}, 'continuous_passed': True, 'numerically_uncertain_thresholds_V': [.0025]},
                       {'response_id': tag, 'variation': {'step': 1., 'mesh': .7}, 'continuous_passed': True, 'numerically_uncertain_thresholds_V': []}]
        with patch.object(self.old, 'read', return_value={'comparisons': []}):
            rows = self.old.numerical_uncertainty({'baseline': baseline}, comparisons)
        self.assertEqual(len(rows), 128)
        self.assertEqual(rows[0]['thresholds']['0.0025']['classification_refinement_status'], 'CROSSING')
        self.assertEqual(rows[1]['thresholds']['0.0025']['classification_refinement_status'], 'PENDING_NEAR_BOUNDARY')

    def test_unlimited_reserve_keeps_costs_and_rejects_gaps(self):
        ledger = {'runs': {'old': {'charged_solver_s': 100000.}, 'retry': {'charged_solver_s': 1900.}}}
        X.SESSION = NS(core=NS(authorization=lambda: None), C=NS(budget=lambda: 101900., load=lambda: ledger))
        result = X.reserve({'global_budget_s': None, 'deadline_utc': None}, {'estimate_s': 600})
        self.assertEqual(result['global_solver_s_before'], 101900.)
        self.assertIsNone(result['global_budget_s'])
        ledger['runs']['old']['charged_solver_s'] = None
        with self.assertRaisesRegex(ValueError, 'Missing/nonfinite'):
            X.reserve({'global_budget_s': None, 'deadline_utc': None}, {'estimate_s': 600})

    def test_incomplete_test_stops_before_raw_or_chain(self):
        session = P.Session.__new__(P.Session)
        session.bind = lambda p: {'state': 'TEST_IN_PROGRESS'}
        session.validate_chain = lambda: self.fail('Must not inspect chain/raw after missing terminal gate')
        with self.assertRaisesRegex(ValueError, 'not complete'):
            session.prerequisites()

    def test_freeze_missing_gate_has_no_runtime_mutation(self):
        session = NS(C=NS(controller_lock=lambda: nullcontext(), check_preservation=lambda: None, budget=lambda: 1),
                     prerequisites=lambda: (_ for _ in ()).throw(ValueError('SYNTHETIC missing test64')))
        path = self.root / 'extension'
        with patch.object(X.P, 'Session', return_value=session), patch.object(X, 'configure'), patch.object(X, 'submission_preflight'), patch.object(X, 'RUNTIME', path):
            with self.assertRaisesRegex(ValueError, 'missing test64'):
                X.freeze()
        self.assertFalse(path.exists())

    def test_host_guard_rejects_other_controller_with_creation_time(self):
        row = {'ProcessId': 999999999, 'CreationDate': 'SYNTHETIC-time', 'CommandLine': 'python experiments/dram-see-v3/r50-main/restart-r4/continue.py execute'}
        with patch.object(X.subprocess, 'run', return_value=NS(stdout=json.dumps([row]))):
            with self.assertRaisesRegex(RuntimeError, 'SYNTHETIC-time'):
                X.host_guard()

    def guard_fixture(self, pid=555, name='python.exe', action='execute', extra=()):
        script = str(HERE / 'extensions.py')
        parent_argv = [r'C:\SYNTHETIC Python\python.exe', '-B', script, action, *extra]
        row = {'ProcessId': pid, 'ParentProcessId': 1, 'Name': name, 'CreationDate': 'SYNTHETIC-time',
               'CommandLine': X.subprocess.list2cmdline(parent_argv)}
        current = [r'E:\SYNTHETIC venv\Scripts\python.exe', '-B', script, 'execute']
        with patch.object(X.os, 'getpid', return_value=556), patch.object(X.os, 'getppid', return_value=555), patch.object(X.sys, 'argv', [script, 'execute']), patch.object(X.sys, 'orig_argv', current), patch.object(X.subprocess, 'run', return_value=NS(stdout=json.dumps([row]))):
            X.host_guard()

    def test_host_guard_exact_argv_direct_python_parent_allowed(self):
        self.guard_fixture()

    def test_host_guard_exact_argv_nonparent_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Another possible controller'):
            self.guard_fixture(pid=554)

    def test_host_guard_different_argv_parent_rejected(self):
        for action, extra in (('freeze', ()), ('execute', ('--extra',)), ('Execute', ())):
            with self.subTest(action=action, extra=extra), self.assertRaisesRegex(RuntimeError, 'Another possible controller'):
                self.guard_fixture(action=action, extra=extra)

    def test_host_guard_ssh_parent_never_exempted(self):
        with self.assertRaisesRegex(RuntimeError, 'Existing SSH'):
            self.guard_fixture(name='ssh.exe')

    def test_parent_exemption_requires_exact_script_and_python_name(self):
        row = {'ProcessId': 555, 'Name': 'cmd.exe'}
        script = str(HERE / 'extensions.py')
        argv = ['python', '-B', script, 'execute']
        with patch.object(X.os, 'getppid', return_value=555), patch.object(X.sys, 'argv', [script, 'execute']), patch.object(X.sys, 'orig_argv', argv):
            self.assertFalse(X.own_python_parent(row, argv))
            row['Name'] = 'python.exe'
            self.assertFalse(X.own_python_parent(row, ['python', '-B', script, 'execute', '--extra']))
        with patch.object(X.os, 'getppid', return_value=555), patch.object(X.sys, 'argv', [str(HERE / 'test_downstream.py')]), patch.object(X.sys, 'orig_argv', argv):
            self.assertFalse(X.own_python_parent(row, argv))

    def test_launcher_exemption_stays_direct_python_owned_path(self):
        script = str(P.LOCAL / 'restart-launches/SYNTHETIC/launch.py')
        row = {'ProcessId': 555, 'Name': 'pythonw.exe'}
        with patch.object(X.os, 'getppid', return_value=555):
            self.assertTrue(X.own_launcher_parent(row, ['pythonw', script]))
            self.assertTrue(X.own_launcher_parent(row, ['pythonw', '-B', script]))
            self.assertFalse(X.own_launcher_parent({**row, 'ProcessId': 554}, ['pythonw', script]))
            self.assertFalse(X.own_launcher_parent({**row, 'Name': 'ssh.exe'}, ['pythonw', script]))
            self.assertFalse(X.own_launcher_parent(row, ['pythonw', str(self.root / 'launch.py')]))
            self.assertFalse(X.own_launcher_parent(row, ['pythonw', script, '--unplanned']))

    def test_stable_refuses_changed_evidence(self):
        path = self.root / 'stable.json'; path.write_text('{}')
        session = P.Session.__new__(P.Session); session.files = {P.rel(path): P.sha(path)}
        self.assertTrue(session.stable()); path.write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, 'changed since read'):
            session.stable()

    def test_prediction_uses_fixed_predictor_not_fit(self):
        """Exercise the actual old check_prediction with explicit SYNTHETIC I/O stubs."""
        F = self.old.F
        folder = self.root / 'data/predictions'; folder.mkdir(parents=True)
        path = self.root / 'plan.json'; path.write_text('{}')
        freeze = {'schema': 'dram-see-v3-r50-main-prediction-freeze', 'physical_revision': P.REVISION,
                  'design_sha256': P.DESIGN_SHA, 'followup_plan_sha256': 'SYNTHETIC-hash', 'frozen_utc': '2026-10-11T00:00:00+00:00',
                  'training_independent_events': 32, 'training_responses': 64, 'test_independent_events': 32,
                  'test_paired_predictions': 64, 'models_per_bit_target': 4, 'test_responses_seen': 0,
                  'files_sha256': {P.rel(folder / n): 'SYNTHETIC-hash' for n in ('models.json','training-data.json','test-inputs.json','predictions.json','ledger-snapshot.json','provenance.json')}}
        (folder / 'freeze.sha256').write_text('SYNTHETIC-hash')
        mapping = {'freeze.json': freeze, 'prediction-binding.json': {'freeze_sha256': 'SYNTHETIC-hash', 'followup_plan_sha256': 'SYNTHETIC-hash', 'frozen_utc': freeze['frozen_utc']},
                   'training-data.json': [], 'test-inputs.json': [], 'models.json': {'schema': 'dram-see-v3-r50-main-prediction-models', 'models': {f'bit{b}:{t}': {} for b in (0,1) for t in F.P.TARGETS}},
                   'predictions.json': {'SYNTHETIC': True}, 'ledger-snapshot.json': {'runs': {}}, 'plan.json': {'source_sha256': {}},
                   'provenance.json': {'source_sha256': {}, 'test_responses_seen': 0, 'ledger_snapshot_sha256': 'SYNTHETIC-hash', 'gates': {k: {'state': 'VERIFIED'} for k in F.R.STAGES}}}
        with patch.object(F, 'HERE', self.root), patch.object(F, 'read', side_effect=lambda p: mapping[Path(p).name]), patch.object(F.C, 'sha', return_value='SYNTHETIC-hash'), patch.object(F.P, '_validated_rows'), patch.object(F.P, 'fit_models', side_effect=AssertionError('Never refit')), patch.object(F.P, 'predict_inputs', return_value={'SYNTHETIC': True}) as predict, patch.object(F, 'existing_test_attempts') as actual:
            self.assertEqual(F.check_prediction(path), freeze)
            predict.assert_called_once(); actual.assert_called_once_with(freeze)

    def test_unknown_actual_r50_input_is_not_hidden(self):
        session = P.Session.__new__(P.Session)
        session.plan = {}; session.cases = {t: {'tag': t} for t in P.ALIASES}; session.extension = None
        session.R = NS(SCHEMA='dram-see-v3-r50-main')
        params = {'physical_revision': P.REVISION, 'schema': session.R.SCHEMA}
        session.F = NS(actual_manifests=lambda: [{'run_id': 'SYNTHETIC-unknown', 'parameters': params}], is_test=lambda p: False)
        session.ledger = {'runs': {'SYNTHETIC-unplanned': {'run_id': 'SYNTHETIC-unknown', 'parameters': params}}}
        with self.assertRaisesRegex(ValueError, 'Unplanned'):
            session.validate_actual_inputs({})

    def test_compare_prerequisite_changes_rejected(self):
        keys = ('baseline','selection','response_sources','aliases','original_failures','raw_submission_index',
                'first_plan_sha256','training_plan_sha256','training_audit_sha256','prediction_plan_sha256',
                'test_plan_sha256','test_result_sha256','prediction_freeze_sha256')
        proof = {k: 'SYNTHETIC-'+k for k in keys}; plan = copy.deepcopy(proof)
        X.compare_prerequisites(proof, plan)
        for key in keys:
            wrong = {**plan, key: 'SYNTHETIC-changed'}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                X.compare_prerequisites(proof, wrong)

    def test_serial_execute_stops_on_second_failure_without_third_submission(self):
        runtime = self.root / 'runtime'; runtime.mkdir()
        (runtime / 'plan.json').write_text('{}')
        before = self.root / 'before.json'; before.write_text('{"runs":{}}')
        cases = [{'tag': 'SYNTHETIC-'+str(i), 'stage': 'oxide', 'role': 'control', 'parent_tag': None,
                  'matching_tags': [], 'kwargs': {}, 'estimate_s': 600} for i in range(3)]
        keys = ('baseline','selection','response_sources','aliases','original_failures','raw_submission_index',
                'first_plan_sha256','training_plan_sha256','training_audit_sha256','prediction_plan_sha256',
                'test_plan_sha256','test_result_sha256','prediction_freeze_sha256')
        plan = {k: 'SYNTHETIC-'+k for k in keys}
        plan.update(planned_cases=cases, reused_cases={}, ledger_before=P.rel(before), source_sha256={},
                    global_budget_s=None, deadline_utc=None)
        ledger = {'runs': {}}; submitted = []; states = []
        def write_json(path, value, exclusive=False):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x' if exclusive else 'w') as stream:
                json.dump(value, stream)
        def prepare(tag, **kwargs):
            folder = self.root / 'inputs' / tag; folder.mkdir(parents=True)
            (folder / 'parameters.json').write_text('{}')
            return {'parameters.json': P.sha(folder / 'parameters.json')}
        def record(tag, execution, estimate_s):
            submitted.append(tag)
            if len(submitted) == 2:
                ledger['runs'][tag] = {'state': 'FAILED'}
                raise ValueError('SYNTHETIC actual science failure')
            ledger['runs'][tag] = {'state': 'VERIFIED', 'run_id': 'SYNTHETIC-run', 'charged_solver_s': 1}
        ext = NS(recipe=lambda *args: None, finish_oxide=lambda *args: self.fail('Must stop before completion'))
        C = NS(controller_lock=lambda: nullcontext(), check_preservation=lambda: None, budget=lambda: 1.,
               load=lambda: ledger, prepare=prepare, record=record, write_json=write_json, now=lambda: 'SYNTHETIC-utc')
        session = NS(C=C, R=NS(matching=lambda *args: None), core=NS(authorization=lambda: None),
                     ext=ext, ledger=ledger, prerequisites=lambda: plan, bundle=lambda tag: {'parameters': {}})
        def configure(s):
            X.SESSION = s
            return ext
        with patch.object(X.P, 'Session', return_value=session), patch.object(X, 'configure', side_effect=configure), patch.object(X, 'check_plan', return_value=plan), patch.object(X, 'submission_preflight'), patch.object(X, 'case_checked'), patch.object(X, 'progress', side_effect=lambda state, reason=None: states.append(state)), patch.object(X, 'RUNTIME', runtime), patch.object(X.P, 'LOCAL', self.root):
            with self.assertRaisesRegex(ValueError, 'actual science failure'):
                X.execute()
        self.assertEqual(submitted, ['SYNTHETIC-0', 'SYNTHETIC-1'])
        self.assertEqual(ledger['runs']['SYNTHETIC-1']['state'], 'FAILED')
        self.assertNotIn('SYNTHETIC-2', ledger['runs'])
        self.assertEqual(states[-1], 'STOPPED_REQUIRES_RECONCILIATION')
        self.assertIsNone(X.BEFORE)

    def test_exact_reuse_refuses_wrong_role_or_bit(self):
        case = next(c for c in self.old.R.cases() if c['stage'] == 'numerical_preregistered' and c['role'] == 'control')
        for change in ({'role': 'neutral'}, {'kwargs': {**case['kwargs'], 'bit': 1-case['kwargs']['bit']}}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'exact'):
                self.old.reused_case({**case, **change}, {})

    def test_sources_are_fixed_and_exclude_future_delivery(self):
        inventory = P.source_inventory()
        self.assertTrue(all(not name.endswith('/downstream-r4/delivery.py') for name in inventory))
        self.assertEqual(set(P.OWN_FILES), {'provenance.py','extensions.py','implementation.md','test_downstream.py'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
