"""Isolated software fixtures only. No live ledger/archive/session/solver calls."""
import copy
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('_delivery_under_test', HERE / 'delivery.py')
D = importlib.util.module_from_spec(spec)
exec(compile((HERE / 'delivery.py').read_bytes(), str(HERE / 'delivery.py'), 'exec'), D.__dict__)
B = D.module(D.MAIN / 'reporting.py', 'test_reporting')
OLD = D.module(D.MAIN / 'delivery.py', 'test_pure_interface')
DESIGN = json.loads((D.MAIN / 'design.json').read_bytes())
INTERFACE = OLD.interfaces(DESIGN)


def fixture():
    ledger = {'runs': {}, 'failures': [{'state': 'FAILED', 'exit_code': None, 'reason': 'synthetic unknown exit'}]}
    proof = {'aliases': dict(D.ALIASES), 'baseline': {}, 'response_sources': {}, 'original_failures': {}, 'files': {}}
    for event in DESIGN['events']:
        for bit in (0, 1):
            canonical = B.event_tag(event, bit)
            actual = D.ALIASES.get(canonical, canonical)
            run_id = 'SYNTHETIC-' + actual
            archive, input_hash = 'a' * 64, 'b' * 64
            freeze = 'SYNTHETIC/' + actual + '.json'
            source = {role: {'run_id': run_id + '-' + role, 'archive_sha256': archive,
                             'mesh_sha256': 'c' * 64} for role in ('signal', 'control', 'neutral')}
            source['signal']['run_id'] = run_id
            metrics = {'stored_bit': bit, 'deltaQ_fC': .2, 'deltaM_V': .001,
                       'D4_V': .02 if bit else -.02, 'M4_V': .02,
                       'control_M4_V': .021, 'control_D4_V': .021 if bit else -.021,
                       'classification': {}, 'sources': source, 'read_window': {}, 'control_read_window': {}}
            observation = {'metrics': metrics, 'readout_BL_V': {'signal': .52, 'control': .521, 'neutral': .5}}
            row = {'state': 'VERIFIED', 'runner_exit_code': 0, 'run_id': run_id,
                   'input_sha256': input_hash, 'audit_archive_sha256': archive,
                   'execution_freeze': freeze, 'charged_solver_s': 1.,
                   'continuous_numeric_valid': True, 'continuous_numerical_status': 'RAW_AUDIT_PASSED',
                   'parameters': {'schema': B.SCHEMA, 'physical_revision': B.REVISION}}
            ledger['runs'][actual] = row
            if actual != canonical:
                ledger['runs'][canonical] = {'state': 'FAILED', 'runner_exit_code': None,
                    'run_id': 'SYNTHETIC-FAILED-' + canonical, 'charged_solver_s': 2.}
                proof['original_failures'][canonical] = copy.deepcopy(ledger['runs'][canonical])
            proof['baseline'][canonical] = observation
            proof['response_sources'][canonical] = {'response_id': canonical, 'actual_ledger_tag': actual,
                'run_id': run_id, 'owner_plan': 'SYNTHETIC/owner-plan.json', 'case_freeze': freeze,
                'input_sha256': input_hash, 'archive_sha256': archive}
    return ledger, proof


def predictions():
    return {'predictions': [{'event_label': event['label'], 'stored_bit': bit,
        'predictions': {target: {'training_mean': 1., 'ridge': 1.} for target in INTERFACE.P.TARGETS}}
        for event in DESIGN['events'] if event['split'] != 'train' for bit in (0, 1)]}


def summary_fixture(comparisons=()):
    ledger, proof = fixture()
    logical = D.logical_slots(DESIGN, ledger, proof)
    gates = {name: {'state': 'VERIFIED'} for name in ('references', 'pilot', 'numerical_preregistered', 'train',
             'prediction_freeze', 'test', 'oxide', 'numerical_boundary', 'native')}
    budget = D.unlimited_budget(ledger, {'schema': 'dram-see-v3-unlimited-continuation-authorization',
        'solver_budget_s': None, 'expires_utc': None}, 'SYNTHETIC', B)
    summary = B.assemble(DESIGN, logical, {tag: obs['metrics'] for tag, obs in proof['baseline'].items()},
                         {}, {}, list(comparisons), gates, budget, {}, {}, synthetic=True)
    score = OLD.effective_scores(summary, {'predictions': predictions()}, INTERFACE)
    summary.update(ledger_snapshot=ledger, original_failures=ledger['failures'], raw_submission_index=[],
        provenance_prerequisites=proof, original_r4_prediction_scores=score,
        final_numerical_prediction_scores=score, prediction_scores=score,
        source_code_sha256={}, extension_cases=[], native_evidence={'state': 'SYNTHETIC_NOT_CAPTURED', 'targets': []})
    return summary


class DeliveryTests(unittest.TestCase):
    def test_four_aliases_fill_exact_slots_without_mutating_raw_ledger(self):
        ledger, proof = fixture()
        before = copy.deepcopy(ledger)
        logical = D.logical_slots(DESIGN, ledger, proof)
        self.assertEqual(len(logical['runs']), 128)
        self.assertEqual(len(ledger['runs']), 132)
        for canonical, actual in D.ALIASES.items():
            self.assertEqual(logical['runs'][canonical]['run_id'], ledger['runs'][actual]['run_id'])
            self.assertEqual(ledger['runs'][canonical]['state'], 'FAILED')
            self.assertIsNone(ledger['runs'][canonical]['runner_exit_code'])
        logical['runs'][next(iter(D.ALIASES))]['state'] = 'MUTATED_FIXTURE'
        self.assertEqual(ledger, before)

    def test_missing_and_unknown_alias_rejected(self):
        ledger, proof = fixture()
        proof['aliases']['unplanned'] = 'unplanned-retry'
        with self.assertRaisesRegex(ValueError, 'four aliases'):
            D.logical_slots(DESIGN, ledger, proof)
        ledger, proof = fixture()
        proof['baseline'].pop(next(iter(proof['baseline'])))
        with self.assertRaisesRegex(ValueError, '128 baseline'):
            D.logical_slots(DESIGN, ledger, proof)

    def test_unknown_or_nonzero_exit_cannot_supply_alias(self):
        for exit_code in (None, 1, 255):
            ledger, proof = fixture()
            actual = next(iter(D.ALIASES.values()))
            ledger['runs'][actual]['runner_exit_code'] = exit_code
            with self.assertRaisesRegex(ValueError, 'actually completed'):
                D.logical_slots(DESIGN, ledger, proof)

    def test_aliased_original_failure_must_remain_failed(self):
        ledger, proof = fixture()
        ledger['runs'][next(iter(D.ALIASES))]['state'] = 'VERIFIED'
        with self.assertRaisesRegex(ValueError, 'Original failed'):
            D.logical_slots(DESIGN, ledger, proof)

    def test_source_owner_and_archive_binding_rejected_on_mismatch(self):
        for field in ('case_freeze', 'archive_sha256', 'input_sha256', 'actual_ledger_tag', 'run_id'):
            ledger, proof = fixture()
            proof['response_sources'][next(iter(D.ALIASES))][field] = 'wrong'
            with self.assertRaises(ValueError):
                D.logical_slots(DESIGN, ledger, proof)

    def test_source_baseline_cannot_use_different_actual_archive(self):
        ledger, proof = fixture()
        proof['baseline'][next(iter(D.ALIASES))]['metrics']['sources']['signal']['run_id'] = 'OTHER-RUN'
        with self.assertRaisesRegex(ValueError, 'Baseline signal run'):
            D.logical_slots(DESIGN, ledger, proof)

    def test_fixed_denominator_stratum_n_and_failure_cost(self):
        summary = summary_fixture()
        self.assertEqual(summary['measured_main_responses'], 128)
        self.assertEqual(summary['planned_independent_events'], 64)
        self.assertEqual(sum(summary['main_threshold_counts'].values()), 128)
        self.assertEqual(summary['main_threshold_counts']['correct'], 128)
        self.assertEqual(summary['budget']['accounted_solver_s'], 136.)
        self.assertIsNone(summary['budget']['planned_budget_s'])
        self.assertEqual({r['planned_n'] for r in summary['statistics']['strata']}, {4})

    def test_budget_rejects_duplicate_charges_and_keeps_gaps_unknown(self):
        ledger, _ = fixture()
        auth = {'schema': 'dram-see-v3-unlimited-continuation-authorization', 'solver_budget_s': None, 'expires_utc': None}
        first = next(iter(ledger['runs']))
        ledger['runs']['duplicate'] = copy.deepcopy(ledger['runs'][first])
        with self.assertRaisesRegex(ValueError, 'Duplicate charged'):
            D.unlimited_budget(ledger, auth, 'fixture', B)
        ledger['runs'].pop('duplicate')
        ledger['runs'][first].pop('charged_solver_s')
        budget = D.unlimited_budget(ledger, auth, 'fixture', B)
        self.assertEqual(len(budget['accounting_gaps']), 1)
        self.assertFalse(budget['complete_cost_accounting'])
        with self.assertRaisesRegex(ValueError, 'unlimited'):
            D.unlimited_budget(ledger, dict(auth, solver_budget_s=86400), 'fixture', B)

    def test_continuous_failure_separate_final_score_no_refit(self):
        event = next(e for e in DESIGN['events'] if e['split'] == 'holdout')
        comparisons = [{'response_id': B.event_tag(event, 0), 'variation': {'step': .5, 'mesh': 1.},
                        'continuous_passed': False, 'numerically_uncertain_thresholds_V': [.0025, .005, .01]}]
        base = summary_fixture()
        final = summary_fixture(comparisons)
        selected = [r for r in final['prediction_scores']['scores'] if r['split'] == 'holdout' and r['stored_bit'] == 0]
        self.assertEqual({r['invalid_or_failed_n'] for r in selected}, {1})
        self.assertEqual({r['valid_n'] for r in selected}, {15})
        self.assertEqual(base['main_threshold_counts']['correct'], 128)
        self.assertEqual(final['main_threshold_counts']['numerically_uncertain'], 1)
        self.assertEqual(base['prediction_scores']['scores'][0]['valid_n'], 16)

    def test_crossing_affects_classification_without_discarding_continuous_values(self):
        event = next(e for e in DESIGN['events'] if e['split'] == 'holdout')
        comparisons = [{'response_id': B.event_tag(event, 0), 'variation': v,
                        'continuous_passed': True, 'numerically_uncertain_thresholds_V': [.005]}
                       for v in ({'step': .5, 'mesh': 1.}, {'step': 1., 'mesh': .7})]
        final = summary_fixture(comparisons)
        self.assertEqual(final['main_threshold_counts']['numerically_uncertain'], 1)
        self.assertTrue(all(r['invalid_or_failed_n'] == 0 for r in final['prediction_scores']['scores']))

    def test_boundary_table_requires_all128_and_registered_statuses(self):
        _, proof = fixture()
        # Start with all unrefined far from thresholds, then a pending near row.
        first = next(iter(proof['baseline']))
        proof['baseline'][first]['metrics']['M4_V'] = .0051
        scope = {'R': type('Science', (), {'design': staticmethod(lambda: DESIGN),
                     'event_tag': staticmethod(B.event_tag), 'A': D.module(D.MAIN / 'audit.py', 'fixture_audit')})(),
                 'HERE': D.MAIN, 'read': lambda p: {'comparisons': []}}
        table = OLD.pure(D.MAIN / 'extensions.py', ('numerical_uncertainty',), scope)['numerical_uncertainty'](
            {'baseline': proof['baseline']}, [])
        boundary = {'main_threshold_status': table, 'comparisons': []}
        D.verify_boundary_table(DESIGN, proof, boundary, [], INTERFACE)
        self.assertEqual(table[0]['thresholds']['0.005']['classification_refinement_status'], 'PENDING_NEAR_BOUNDARY')
        self.assertEqual(len(table), 128)
        self.assertEqual({len(row['thresholds']) for row in table}, {3})
        boundary['main_threshold_status'] = table[:-1]
        with self.assertRaisesRegex(ValueError, '128 x three'):
            D.verify_boundary_table(DESIGN, proof, boundary, [], INTERFACE)

    def test_native_machine_only_or_missing_target_is_not_eye_review(self):
        rows = [{'ledger_tag': tag, 'state': 'CAPTURED_VISUALLY_REVIEWED'} for tag in D.NATIVE_TAGS]
        D.require_native_review({'state': 'VERIFIED', 'targets': rows})
        with self.assertRaisesRegex(ValueError, 'actual visual'):
            D.require_native_review({'state': 'CAPTURED_PENDING_VISUAL_REVIEW', 'targets': rows})
        with self.assertRaisesRegex(ValueError, 'Both registered'):
            D.require_native_review({'state': 'VERIFIED', 'targets': rows[:1]})
        rows[0]['state'] = 'CAPTURED_PENDING_VISUAL_REVIEW'
        with self.assertRaisesRegex(ValueError, 'Machine PNG'):
            D.require_native_review({'state': 'VERIFIED', 'targets': rows})

    def test_extension_status_is_not_enough_for_full_collect(self):
        _, proof = fixture()
        with self.assertRaisesRegex(ValueError, 'Complete extension'):
            D.validate_extension_review({'state': 'ACTIVE'}, proof)
        # Exact case inventory,14/8 oxide and4 boundary gates are checked separately.
        plan = {'selection': {'population_count': 128}, 'baseline': proof['baseline'],
                'planned_cases': [{'tag': str(i)} for i in range(14)]}
        proof['selection'] = plan['selection']
        ext = {'state': 'VERIFIED', 'plan': plan, 'cases': [
            {'tag': str(i), 'raw_reviewed': True, 'state': 'VERIFIED', 'stage': 'oxide'} for i in range(14)],
            'oxide': {'state': 'VERIFIED', 'new_response_count': 8, 'baseline_5nm': [{}]*4, 'responses': [{}]*8, 'new_independent_events': 0},
            'boundary': {'state': 'VERIFIED', 'continuous_passed': True, 'comparisons': [{}]*4,
                         'selection': proof['selection'], 'new_independent_events': 0}}
        D.validate_extension_review(ext, proof)
        ext['cases'][0]['raw_reviewed'] = False
        with self.assertRaisesRegex(ValueError, 'completed raw review'):
            D.validate_extension_review(ext, proof)
        ext['cases'][0]['raw_reviewed'] = True
        ext['boundary']['continuous_passed'] = False
        with self.assertRaisesRegex(ValueError, 'continuous boundary'):
            D.validate_extension_review(ext, proof)

    def test_exclusive_fixture_snapshot_and_honest_materials(self):
        summary = summary_fixture()
        output = D.DEV / ('fixture-' + uuid.uuid4().hex)
        result = D.write_snapshot(summary, output, plots=False)
        self.assertFalse(result['course_complete'])
        manifest = json.loads((output / 'snapshot-manifest.json').read_bytes())
        self.assertTrue(manifest['synthetic_fixture'])
        for name, digest in manifest['files_sha256'].items():
            self.assertEqual(D.sha(output / name), digest)
        self.assertIsNone(json.loads((output / 'ledger-snapshot.json').read_bytes())['runs'][next(iter(D.ALIASES))]['runner_exit_code'])
        report = (output / 'report.md').read_text(encoding='utf8')
        materials = (output / 'materials/feasibility.md').read_text(encoding='utf8')
        self.assertIn('SYNTHETIC', report)
        self.assertIn('预算无上限', report)
        self.assertNotIn('/86400', report)
        self.assertNotIn('统一86400', materials)
        index = json.loads((output / 'materials/index.json').read_bytes())
        self.assertFalse(index['actual_student_demo'])
        self.assertFalse(index['actual_teacher_review'])
        self.assertFalse(index['actual_defense'])
        with self.assertRaisesRegex(ValueError, 'new exclusive'):
            D.write_snapshot(summary, output, plots=False)
        with self.assertRaisesRegex(ValueError, 'permitted r4'):
            D.write_snapshot(summary, D.ROOT / 'reports/final/DO-NOT-WRITE', plots=False)

    def test_real_writer_checks_eye_review_before_output_creation(self):
        summary = summary_fixture()
        summary.update(synthetic_fixture=False, simulation_evidence_verified=True)
        output = D.OUTPUT / ('MUST-NOT-BE-CREATED-' + uuid.uuid4().hex)
        with self.assertRaisesRegex(ValueError, 'actual visual'):
            D.write_snapshot(summary, output, plots=False)
        self.assertFalse(output.exists())

    def test_collect_requires_root_visual_input_before_loading_sessions(self):
        with patch.object(D, 'sources', return_value={}):
            with self.assertRaisesRegex(ValueError, 'Explicit root'):
                D.collect(D.EXTENSION, None)

    def test_existing_mapping_acceptance_remains_software_only(self):
        # The immutable mapping package is safe to inspect while solves run.
        evidence = B.Evidence()
        result = D.mapping_evidence(evidence)
        self.assertEqual(result['state'], 'SOFTWARE_MAPPING_VERIFIED')
        self.assertFalse(result['actual_student_demo'])
        evidence.stable()

    def test_complete_collect_contract_with_only_in_memory_evidence(self):
        """Exercise integration without opening any real ledger/run/plan/native file."""
        ledger, proof = fixture()
        proof.update(selection={'selected': [], 'population_count': 128},
                     raw_submission_index=[], first_plan_sha256='fixture', training_plan_sha256='fixture',
                     training_audit_sha256='fixture', prediction_plan_sha256='fixture', test_plan_sha256='fixture',
                     test_result_sha256='fixture', prediction_freeze_sha256='fixture')
        predicted = predictions()
        proof['observed_tests'] = [{'event_label': event['label'], 'stored_bit': bit, 'continuous_valid': True,
            'targets': {'deltaQ_fC': .2, 'deltaM_mV': 1.}}
            for event in DESIGN['events'] if event['split'] != 'train' for bit in (0, 1)]
        proof['original_prediction_scores'] = INTERFACE.P.score_predictions(predicted, proof['observed_tests'], DESIGN)
        ext_cases = [{'tag': 'FIXTURE-EXT-' + str(i), 'run_id': 'FIXTURE-EXT-RUN-' + str(i), 'stage': 'oxide',
                      'role': 'control', 'reused': False, 'raw_reviewed': True, 'state': 'VERIFIED',
                      'new_independent_event': False} for i in range(14)]
        for item in list(proof['baseline'].values()):
            for member in item['metrics']['sources'].values():
                if not any(row.get('run_id') == member['run_id'] for row in ledger['runs'].values()):
                    ledger['runs'][member['run_id']] = {'state': 'VERIFIED', 'run_id': member['run_id'],
                        'audit_archive_sha256': member['archive_sha256'], 'charged_solver_s': 1.}
        for case in ext_cases:
            ledger['runs'][case['tag']] = {'state': 'VERIFIED', 'run_id': case['run_id'], 'charged_solver_s': 1.,
                                          'audit_archive_sha256': 'a' * 64}
        ext = {'state': 'VERIFIED', 'plan': {'selection': proof['selection'], 'baseline': proof['baseline'],
                                           'planned_cases': [{'tag': r['tag']} for r in ext_cases]},
               'cases': ext_cases, 'files': {},
               'oxide': {'state': 'VERIFIED', 'new_response_count': 8, 'baseline_5nm': [{}]*4,
                         'responses': [{}]*8, 'new_independent_events': 0},
               'boundary': {'state': 'VERIFIED', 'continuous_passed': True, 'classification_stable': True,
                            'comparisons': [{'response_id': 'FIXTURE-EXT-ONLY'}]*4,
                            'selection': proof['selection'], 'new_independent_events': 0}}
        native = {'state': 'VERIFIED', 'targets': [{'ledger_tag': tag, 'state': 'CAPTURED_VISUALLY_REVIEWED'}
                                                  for tag in D.NATIVE_TAGS]}
        auth = {'schema': 'dram-see-v3-unlimited-continuation-authorization', 'solver_budget_s': None, 'expires_utc': None}
        class Evidence:
            def __init__(self):
                self.hashes = {}
            def bind(self, path):
                self.hashes[D.rel(path)] = 'FIXTURE-HASH'
                return 'FIXTURE-HASH'
            def read_json(self, path):
                self.bind(path)
                if Path(path).name == 'ledger.json':
                    return copy.deepcopy(ledger)
                if Path(path).name == 'predictions.json':
                    return copy.deepcopy(predicted)
                if Path(path) == D.AUTHORIZATION:
                    return auth
                return {'synthetic_software_fixture': True}
            def stable(self):
                pass
        class Session:
            def __init__(self, extension_plan):
                self.ledger = copy.deepcopy(ledger)
            def validate_chain(self):
                return {'synthetic_software_fixture': True}
            def prerequisites(self):
                return proof
            def check_prediction(self):
                return {'synthetic_software_fixture': True}
            def bundle(self, tag):
                row = self.ledger['runs'][tag]
                return {'summary': {'run_id': row['run_id'], 'archive_sha256': row['audit_archive_sha256']},
                        'parameters': {'reference_mode': 'offline'},
                        'circuit': [{'time': t, 'v(sn)': .5, 'v(bl)': .5, 'v(wl)': 0.} for t in (0., 4e-9)]}
            def stable(self):
                pass
        class Review:
            def __init__(self, *args):
                self.errors = {}
                self.reader = SimpleNamespace(bundles={}, errors={})
            def plan(self, *args):
                pass
            def native(self, *args):
                return native
        report = SimpleNamespace(**B.__dict__)
        report.Evidence = Evidence
        report.design_checked = lambda p: DESIGN
        report.stage_proofs = lambda *a: ({}, 'synthetic fixture')
        report.reference_checks = lambda *a: {k: {'state': 'VERIFIED'} for k in ('references', 'pilot')}
        report.numerical_checks = lambda *a: ([], {'state': 'VERIFIED'})
        old = SimpleNamespace(interfaces=lambda d: INTERFACE, Review=Review, effective_scores=OLD.effective_scores)
        def modules(path, name):
            return {'provenance.py': SimpleNamespace(Session=Session),
                    'extensions.py': SimpleNamespace(review=lambda *a: ext),
                    'delivery.py': old, 'reporting.py': report}[Path(path).name]
        before = copy.deepcopy(ledger)
        with patch.object(D, 'sources', return_value={}), patch.object(D, 'module', side_effect=modules), \
                patch.object(D, 'verify_boundary_table', return_value=[]), \
                patch.object(D, 'mapping_evidence', return_value={'state': 'SYNTHETIC'}):
            summary = D.collect(D.EXTENSION, D.DEV / 'SYNTHETIC-NOT-A-FILE.json')
        self.assertEqual(summary['measured_main_responses'], 128)
        self.assertEqual(summary['original_r4_prediction_scores'], proof['original_prediction_scores'])
        self.assertEqual(summary['ledger_snapshot'], before)
        self.assertEqual(len(summary['aliases']), 4)
        self.assertEqual(len(summary['original_failures']['failed_rows']), 4)
        self.assertEqual(len(summary['provenance_prerequisites']['response_sources']), 128)
        self.assertIn('PENDING', summary['course_state'])
        self.assertEqual(ledger, before)


if __name__ == '__main__':
    D.DEV.mkdir(parents=True, exist_ok=True)
    run = D.DEV / ('tests-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    run.mkdir()
    captured = io.StringIO()
    result = unittest.TextTestRunner(stream=captured, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DeliveryTests))
    (run / 'unittest.log').write_text(captured.getvalue(), encoding='utf8')
    (run / 'result.json').write_text(json.dumps({'synthetic_software_verification_only': True,
        'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'successful': result.wasSuccessful(), 'new_solver_calls': 0, 'real_collect_called': False,
        'argv': sys.argv, 'python': sys.executable}, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(captured.getvalue())
    print('EVIDENCE=' + str(run))
    sys.exit(0 if result.wasSuccessful() else 1)
