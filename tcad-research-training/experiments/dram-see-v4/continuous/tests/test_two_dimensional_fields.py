"""Focused integration checks for the newly added 2D field and baseline routes."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / 'experiments/dram-see-v4/continuous/data'
DEVICE = ROOT / 'experiments/dram-see-v4/continuous/device'
B0 = ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/device-implementation/candidates/20261019T104330Z-v4-2d-a0-main-b0-input-r2'
sys.path.insert(0, str(DATA))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TwoDimensionalFieldRouteTests(unittest.TestCase):
    def test_current_audit_routes_2d_archive_to_fixed_adapter(self):
        audit = load(DATA / 'current_audit.py', 'current_audit_2d_route_test')
        context = {'role_id': 'B2D-A0-main-b0'}
        project = {'s2_geometry': {'source_dimension': 2}}
        archive = SimpleNamespace(
            members={'dimensional-contract.json': object()},
            read=lambda name: json.dumps(project).encode('utf-8') if name == 'project.json' else b'{}',
        )
        report = {'schema': '2d-route-fixture'}
        adapter = SimpleNamespace(geometry=Mock(return_value={'report': report}))
        with patch.dict(sys.modules, {'field_adapter_2d': adapter}):
            result = audit.geometry(archive, context)
        self.assertIs(result, report)
        adapter.geometry.assert_called_once_with(archive, context)

    def test_public_adapter_commands_dispatch_to_separate_2d_implementation(self):
        adapter_2d = load(DATA / 'field_adapter_2d.py', 'field_adapter_2d_cli_test')
        adapter = load(DATA / 'field_adapter.py', 'field_adapter_cli_test')
        with patch.dict(sys.modules, {'field_adapter_2d': adapter_2d}):
            with patch.object(adapter_2d, 'prepare', return_value={'status': 'INPUTS_ONLY_NOT_EXECUTED', 'dimension': 2}) as prepare, \
                 patch.object(sys, 'argv', ['field_adapter.py', 'prepare-2d-a0', '--solver', 'solver-r2', '--label', 'b0-fields', '--adapter', 'operation.py', '--output', 'new-output']), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                adapter.main()
            prepare.assert_called_once()
            self.assertEqual(prepare.call_args.args, (Path('solver-r2'), 'b0-fields', Path('operation.py'), Path('new-output')))
            self.assertIn('INPUTS_ONLY_NOT_EXECUTED', output.getvalue())

            converted = {'schema': 'dram-see-v4-2d-a0-native-field-measurements-r1', 'native_qualified': False}
            with patch.object(adapter_2d, 'convert', return_value=converted) as convert, \
                 patch.object(adapter.A, 'write_new') as write_new, \
                 patch.object(sys, 'argv', ['field_adapter.py', 'convert-2d-a0', '--solver', 'solver-r2', '--extraction', 'extract-r2', '--output', 'converted.json']), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                adapter.main()
            convert.assert_called_once_with(Path('solver-r2'), Path('extract-r2'))
            write_new.assert_called_once_with(Path('converted.json'), converted)
            self.assertIn('dram-see-v4-2d-a0-native-field-measurements-r1', output.getvalue())

    def test_2d_baseline_keeps_frozen_circuit_metrics_and_applies_no_extra_width(self):
        wrapper = load(DATA / 'metrics.py', 'metrics_2d_wrapper_test')
        original = load(ROOT / 'experiments/dram-see-v4/s2-inputs-r1/metrics.py', 'frozen_s2_metrics_test')
        dimension = json.loads((B0 / 'dimensional-contract.json').read_text(encoding='utf-8'))
        times = [i * 1e-10 for i in range(251)]
        trace = {
            'time_s': times,
            'v_sn_V': [0.0 for _ in times],
            'v_bl_V': [0.6 for _ in times],
            'i_sn_A': [0.0 for _ in times],
        }
        baseline = original.baseline(trace, 0)
        result = wrapper.baseline_2d(trace, 0, dimension)
        for key in ('stored_bit', 'written_vsn_V', 'hold_drift_V', 'precharge_vbl_V',
                    'mean_read_vbl_V', 'signed_read_margin_V', 'checks',
                    'candidate_functional_pass', 'kcl', 'G1_qualified',
                    'native_engineering_chain_verified'):
            value = baseline[key]
            self.assertEqual(result[key], value)
        self.assertEqual(result['schema'], 'dram-see-v4-2d-a0-baseline-metrics-r1')
        self.assertEqual(result['dimension'], 2)
        self.assertEqual(result['effective_width_nm'], 20)
        self.assertEqual(result['current_postprocessing_width_multiplier'], 1)
        self.assertEqual(result['explicit_capacitance_postprocessing_multiplier'], 1)
        self.assertTrue(result['original_criteria_unchanged'])
        self.assertFalse(result['native_qualified'])
        self.assertFalse(result['full_3d_qualification'])


if __name__ == '__main__':
    unittest.main()
