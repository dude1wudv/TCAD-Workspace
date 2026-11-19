"""Independent stable-index audit equivalence and adapter identity tests."""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RT = ROOT / 'local_runtime/dram-see-v4/nuclear-closure-r1'
VALIDATION = RT / 'audit-index-r5/validation'
sys.path.insert(0, str(HERE))
R3_PATH = HERE / 'transport_audit_r3.py'
R5_PATH = HERE / 'transport_audit_indexed_r5.py'


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


R3 = load(R3_PATH, '_audit_r3_index_validation')
R5 = load(R5_PATH, '_audit_r5_index_validation')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_report(report):
    result = copy.deepcopy(report)
    result.pop('audit_code_sha256', None)
    result.pop('audit_revision', None)
    return result


def synthetic_ledger_fixture():
    materials = ('G4_Galactic', 'G4_Si', 'G4_SILICON_DIOXIDE')
    events, tracks, steps = [], [], []
    for event_id in range(2):
        for track_id in (1, 2):
            tracks.append({'event_id': event_id, 'track_id': track_id, 'particle': 'proton',
                           'pdg': 2212, 'Z': 1, 'A': 1})
        for step_id in range(120):
            track_id = 1 + step_id % 2
            material = materials[step_id % len(materials)]
            ionizing = (1e-13, 1e-7, 0.125, 1e5, 1e-10)[step_id % 5]
            niel = ionizing * (0.0, 0.125, 0.5)[step_id % 3]
            steps.append({'event_id': event_id, 'track_id': track_id,
                          'pre_material': material, 'niel_MeV': niel,
                          'ionizing_MeV': ionizing, 'edep_MeV': niel + ionizing})
    ledger = []
    for event_id in range(2):
        selected = [row for row in steps if row['event_id'] == event_id]
        events.append({'event_id': event_id,
                       **{field + '_all_MeV': math.fsum(step[field + '_MeV'] for step in selected)
                          for field in ('edep', 'niel', 'ionizing')}})
        scopes = [('event', 0, selected)] + [
            ('track', track_id, [step for step in selected if step['track_id'] == track_id])
            for track_id in (1, 2)]
        for scope, track_id, scoped_steps in scopes:
            for material in materials:
                chosen = [step for step in scoped_steps if step['pre_material'] == material]
                ledger.append({'scope': scope, 'event_id': event_id, 'track_id': track_id,
                               'material': material, 'step_count': len(chosen),
                               **{field + '_MeV': math.fsum(step[field + '_MeV'] for step in chosen)
                                  for field in ('edep', 'niel', 'ionizing')}})
    return {'mode': 'normal'}, (events, tracks, steps), ledger


def ast_with_identity_normalized(path: Path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    mapping = (
        ('transport_audit_indexed_r5.py', 'transport_audit_r3.py'),
        ('transport_index_r5', 'transport_r3'),
        ('event_source_index_r5.py', 'event_source_audit_r3.py'),
        ('campaign_index_r5.py', 'campaign_audit_r3.py'),
        ('audits-index-r5', 'audits-r3'),
        ('stages-index-r5', 'stages-r3'),
        ('release-audit-index-r5.json', 'release-audit-r3.json'),
        ('audit-index-r5', 'audit-r3'),
        ('Indexed audit r5 not released', 'Audit r3 not released'),
        ('release-storage-r4.json', 'release-audit-r3.json'),
        ('Storage r4 not released', 'Audit r3 not released'),
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id == 'transport_index_r5': node.id = 'transport_r3'
            if node.id == 'campaign_index_r5': node.id = 'campaign_audit_r3'
            if node.id == 'event_source_index_r5': node.id = 'event_source_audit_r3'
        if isinstance(node, ast.alias):
            if node.name == 'transport_index_r5': node.name = 'transport_r3'
            if node.name == 'campaign_index_r5': node.name = 'campaign_audit_r3'
            if node.name == 'event_source_index_r5': node.name = 'event_source_audit_r3'
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for old, new in mapping:
                node.value = node.value.replace(old, new)
    return ast.dump(tree, include_attributes=False)


class IndexedAuditTests(unittest.TestCase):
    def test_only_material_ledger_function_ast_changed(self):
        old_tree = ast.parse(R3_PATH.read_text(encoding='utf-8'))
        new_tree = ast.parse(R5_PATH.read_text(encoding='utf-8'))
        excluded = {'_material_ledger'}
        def declarations(tree):
            return {node.name: ast.dump(node, include_attributes=False)
                    for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and node.name not in excluded}
        old, new = declarations(old_tree), declarations(new_tree)
        self.assertEqual(old.keys(), new.keys())
        self.assertEqual(old, new)
        self.assertEqual(R3.TOLERANCES, R5.TOLERANCES)
        self.assertEqual(R3.LIMITS, R5.LIMITS)
        self.assertEqual(R3.AUDIT_REVISION, 'r3-device-miss-with-preserved-world-ledger')
        self.assertEqual(R5.AUDIT_REVISION, 'indexed-r5-stable-material-ledger')

    def test_real_n1_audits_are_semantically_identical(self):
        record_path = RT / 'transport/runs/nc-r1-h-000/record.json'
        receipt = json.loads(record_path.read_text(encoding='utf-8'))
        self.assertEqual(receipt['request']['closure_stage'], 'N1')
        run = record_path.parent
        with tempfile.TemporaryDirectory(prefix='audit-index-r5-n1-', dir=VALIDATION) as temp:
            out = Path(temp)
            r3 = R3.audit_events(run, out / 'r3')
            r5 = R5.audit_events(run, out / 'r5')
        self.assertTrue(r3['passed'], r3['errors'])
        self.assertTrue(r5['passed'], r5['errors'])
        self.assertEqual(len(r3['checks']), 10)
        self.assertEqual(len(r5['checks']), 10)
        self.assertTrue(all(check['passed'] is True for check in r3['checks'].values()))
        self.assertTrue(all(check['passed'] is True for check in r5['checks'].values()))
        self.assertEqual(normalize_report(r3), normalize_report(r5))
        self.assertEqual(r3['record_sha256'], sha(record_path))
        self.assertEqual(r5['record_sha256'], sha(record_path))
        self.assertEqual(r3['audit_code_sha256'], sha(R3_PATH))
        self.assertEqual(r5['audit_code_sha256'], sha(R5_PATH))
        self.assertEqual(r3['audit_revision'], R3.AUDIT_REVISION)
        self.assertEqual(r5['audit_revision'], R5.AUDIT_REVISION)

    def test_material_ledger_reorder_duplicate_and_missing_match_r3_outcomes(self):
        metadata, records, ledger = synthetic_ledger_fixture()
        originals = {module: module.numeric_rows for module in (R3, R5)}
        volume_map = {'World': 'G4_Galactic', 'Si': 'G4_Si', 'Ox': 'G4_SILICON_DIOXIDE', 'OUTSIDE': 'NONE'}
        inventory = [
            {'phase': phase, 'particle': 'proton', 'pdg': '2212', 'Z': '1', 'A': '1',
             'particle_type': 'baryon', 'particle_subtype': 'nucleus', 'has_process_manager': '1', 'process_count': '0'}
            for phase in ('post_zero_event_init', 'post_events')]
        def run_ledger(module, case):
            values = copy.deepcopy(ledger)
            local_records = copy.deepcopy(records)
            if case == 'reorder':
                values.reverse()
                local_records[2].reverse()
            elif case == 'duplicate':
                values.append(copy.deepcopy(values[0]))
            elif case == 'missing':
                values.pop()
            def indexed_rows(_folder, filename, *args, **kwargs):
                self.assertEqual(filename, 'material-energy.csv')
                return copy.deepcopy(values)
            report = {}
            with patch.object(module, 'numeric_rows', side_effect=indexed_rows), \
                 patch.object(module, '_volume_materials', return_value=volume_map), \
                 patch.object(module, '_miss_device', return_value=None), \
                 patch.object(module, 'csv_rows', side_effect=lambda _folder, name, *args, **kwargs:
                              inventory if name == 'particles.csv' else []):
                try:
                    module._material_ledger(VALIDATION, metadata, local_records, report)
                    return ('pass', report)
                except ValueError as exc:
                    return ('reject', str(exc))
        base_r3, base_r5 = run_ledger(R3, 'valid'), run_ledger(R5, 'valid')
        self.assertEqual(base_r3, base_r5)
        for case, expected in (('reorder', 'pass'), ('duplicate', 'reject'), ('missing', 'reject')):
            with self.subTest(case=case):
                r3, r5 = run_ledger(R3, case), run_ledger(R5, case)
                self.assertEqual(r3[0], expected)
                self.assertEqual(r5[0], expected)
                self.assertEqual(r3, r5)
                if case == 'reorder':
                    self.assertEqual(r3, base_r3)


class AdapterIdentityTests(unittest.TestCase):
    def test_four_r5_adapters_only_change_revision_identity_and_paths(self):
        pairs = (
            ('transport_r3.py', 'transport_index_r5.py'),
            ('event_source_audit_r3.py', 'event_source_index_r5.py'),
            ('campaign_audit_r3.py', 'campaign_index_r5.py'),
            ('continue_storage_r4.py', 'continue_index_r5.py'),
        )
        for old_name, new_name in pairs:
            with self.subTest(adapter=new_name):
                self.assertEqual(ast_with_identity_normalized(HERE / old_name),
                                 ast_with_identity_normalized(HERE / new_name))

    def test_r5_stage_and_selection_are_revision_bound_and_resume_isolated(self):
        transport = (HERE / 'transport_index_r5.py').read_text(encoding='utf-8')
        continuation = (HERE / 'continue_index_r5.py').read_text(encoding='utf-8')
        source = (HERE / 'event_source_index_r5.py').read_text(encoding='utf-8')
        campaign = (HERE / 'campaign_index_r5.py').read_text(encoding='utf-8')
        self.assertIn("audits-index-r5", transport)
        self.assertIn("release-audit-index-r5.json", transport)
        self.assertIn("transport_revision='audit-index-r5'", transport)
        self.assertIn("transport/stages-index-r5", continuation)
        self.assertIn("release-audit-index-r5.json", continuation)
        self.assertIn("chosen.get('transport_revision')=='audit-index-r5'", continuation)
        self.assertIn("transport_audit_indexed_r5.py", continuation)
        self.assertIn("transport_audit_indexed_r5.py", source)
        self.assertIn("event_source_index_r5.py", campaign)
        self.assertIn("audit-index-r5", campaign)
        self.assertIn('supervisor_storage_r4 as s', continuation)
        self.assertIn('prepared_inputs_r4 as prepared', continuation)


if __name__ == '__main__':
    unittest.main(verbosity=2)
