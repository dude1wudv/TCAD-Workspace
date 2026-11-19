"""Focused fail-closed checks for transport audit and request preparation."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VALIDATION_LOGS = ROOT / 'local_runtime/dram-see-v4/transport-probe/validation/logs'


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class TransportAuditNegativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = load_module(HERE / 'audit_transport.py', '_transport_audit_negative_tests')

    def test_receipt_rejects_unknown_real_exit_code(self):
        VALIDATION_LOGS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='transport-exit-', dir=VALIDATION_LOGS) as temp:
            folder = Path(temp)
            (folder / 'record.json').write_text(json.dumps({
                'schema': 'dram-see-v4-transport-run-v1', 'run_id': folder.name,
                'runner_exit_code': None, 'remote_exit_code': 0, 'collection_exit_code': 0,
            }), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Unknown/nonzero actual exit code: runner_exit_code'):
                self.audit._receipt(folder, {})

    def test_event_audit_rejects_missing_requested_zero_deposition_event(self):
        empty_tables = [[], [], []]
        with patch.object(self.audit, 'numeric_rows', side_effect=empty_tables):
            with self.assertRaisesRegex(ValueError, 'Event IDs must be consecutive 0..N-1'):
                self.audit._events(Path('.'), {'events_requested': 1, 'miss': False},
                                   {'tracks_completed': 0, 'steps_recorded': 0}, {})

    def test_event_audit_rejects_secondary_with_missing_parent(self):
        event = {key: 0 for key in self.audit.EVENT_INT}
        event.update(event_id=0, primary_count=1, track_count=1, event_complete=1,
                     zero_si_ionizing=1, primary_first_hadronic_process='none')
        for key in self.audit.EVENT_FLOAT:
            event[key] = 0.
        event['primary_first_hadronic_t_ns'] = -1.

        track = {key: 0 for key in self.audit.TRACK_INT}
        track.update(event_id=0, track_id=2, parent_id=99, pdg=22, Z=0, A=0,
                     creator_type=4, creator_subtype=1, step_count=0)
        track['ended_by_neutron_tracking_cut'] = 0
        for key in self.audit.TRACK_FLOAT:
            track[key] = 0.
        track.update(birth_ke_MeV=1., birth_dx=1., end_volume='OUTSIDE',
                     end_material='NONE', birth_volume='World',
                     birth_material='G4_Galactic', particle='gamma',
                     creator_process='conversion')
        for key in ('end_dx', 'end_dy', 'end_dz'):
            track[key] = 0.
        steps = []
        with patch.object(self.audit, 'numeric_rows', side_effect=[ [event], [track], steps ]):
            with self.assertRaisesRegex(ValueError, 'Missing parent track'):
                self.audit._events(Path('.'), {'events_requested': 1, 'miss': False, 'arm': 'H'},
                                   {'tracks_completed': 1, 'steps_recorded': 0}, {})

    def test_energy_components_must_close(self):
        with self.assertRaisesRegex(ValueError, 'NIEL/ionizing decomposition differs'):
            self.audit._check_energy_triplet({'edep': 1., 'niel': .6, 'ionizing': .3},
                                             'edep', 'niel', 'ionizing')


class PrepareRunGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prepare_module = load_module(HERE / 'prepare_run.py', '_transport_prepare_gate_tests')

    def setUp(self):
        VALIDATION_LOGS.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='prepare-gates-', dir=VALIDATION_LOGS)
        self.root = Path(self.temp.name)
        self.here = self.root / 'experiments/dram-see-v4/transport-probe'
        self.runtime = self.root / 'local_runtime/dram-see-v4/transport-probe'
        self.here.mkdir(parents=True)
        (self.here / 'results').mkdir()
        for name in ('probe-contract.json', 'environment-spec.json'):
            (self.here / name).write_bytes((HERE / name).read_bytes())
        self.build = self.runtime / 'operations/compile-r1'
        collected = self.build / 'collected'
        collected.mkdir(parents=True)
        (self.build / 'operation.json').write_text(json.dumps({
            'ssh_exit_code': 0, 'remote_exit_code': 0, 'collection_exit_code': 0,
        }), encoding='utf-8')
        for name in ('transport_probe', 'transport_probe.cc', 'environment.sh', 'dataset-inventory.json'):
            (collected / name).write_text(name + '\n', encoding='utf-8')
        self.patchers = [
            patch.object(self.prepare_module, 'HERE', self.here),
            patch.object(self.prepare_module, 'RUNTIME', self.runtime),
            patch.object(self.prepare_module, 'ROOT', self.root),
        ]
        for item in self.patchers:
            item.start()

    def tearDown(self):
        for item in reversed(self.patchers):
            item.stop()
        self.temp.cleanup()

    def add_gate(self, name, *, contract_matches=True):
        audit_path = self.runtime / 'audits' / (name + '.json')
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps({'passed': True}), encoding='utf-8')
        contract_hash = self.prepare_module.sha(self.here / 'probe-contract.json')
        if not contract_matches:
            contract_hash = '0' * 64
        gate = {'passed': True, 'contract_sha256': contract_hash,
                'audit_evidence': [{'path': audit_path.relative_to(self.root).as_posix(),
                                    'sha256': self.prepare_module.sha(audit_path)}]}
        (self.here / 'results' / name).write_text(json.dumps(gate), encoding='utf-8')

    def test_thin_request_is_blocked_without_initialization_gate(self):
        with self.assertRaises(FileNotFoundError):
            self.prepare_module.prepare('proton-h-e1-a0-r1', self.build, 'blocked-init')
        self.assertFalse((self.runtime / 'inputs/blocked-init').exists())

    def test_small_event_request_is_blocked_without_format_gate(self):
        self.add_gate('initialization-gate.json')
        with self.assertRaises(FileNotFoundError):
            self.prepare_module.prepare('proton-h-e1-a0-r1', self.build, 'blocked-format')
        self.assertFalse((self.runtime / 'inputs/blocked-format').exists())

    def test_format_probe_requires_init_gate_but_can_precede_format_gate(self):
        self.add_gate('initialization-gate.json')
        folder = self.prepare_module.prepare('format-h5-a0-r1', self.build, 'format-probe')
        self.assertTrue((folder / 'request.json').is_file())
        self.assertTrue((folder / 'task.sh').is_file())
        self.assertFalse((self.here / 'results/format-gate.json').exists())

    def test_completed_request_cannot_be_prepared_again(self):
        self.add_gate('initialization-gate.json')
        self.add_gate('format-gate.json')
        previous = self.runtime / 'runs/completed/record.json'
        previous.parent.mkdir(parents=True)
        previous.write_text(json.dumps({'request': {'label': 'proton-h-e1-a0-r1'},
                                        'remote_exit_code': 0}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Completed request already exists; do not resubmit'):
            self.prepare_module.prepare('proton-h-e1-a0-r1', self.build, 'must-not-resubmit')
        self.assertFalse((self.runtime / 'inputs/must-not-resubmit').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
