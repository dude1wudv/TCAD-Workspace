"""Focused UNIT_FIXTURE_NOT_NATIVE checks for new 2D alpha data routes."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / 'experiments/dram-see-v4/continuous/data'
HANDOFF = ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/alpha-field-integration'
sys.path.insert(0, str(DATA))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arithmetic_clock(reference, reducer):
    """Build the sealed reference's explicitly synthetic arithmetic fixture."""
    projection = reducer.projection_module()
    start, end = reference['source_window_s']
    epoch, sigma = reference['epoch_s'], reference['sigma_s']
    times = [0.0, *[start + (end-start)*i/160 for i in range(161)], 25e-9]
    intervals = [dict(accepted_index=i, start_s=a, end_s=b, dt_s=b-a)
                 for i, (a, b) in enumerate(zip(times, times[1:]), 1)]
    frames = [dict(v, source_file='UNIT_FIXTURE_NOT_NATIVE_'+str(v['accepted_index']))
              for v in intervals if v['end_s'] > start and v['start_s'] < end]
    column = 'IntegrSemiconductor HeavyIonGeneration'
    scalars = [dict(time=times[0], **{column: 0.0})]
    for interval in intervals:
        mass = projection.R.temporal_interval(interval['start_s']-epoch,
            interval['end_s']-epoch, 0.0, sigma)[0]
        rate = reference['rois']['Total']['all_time_charge_fC']*mass/interval['dt_s']/reducer.RAW_TO_FC_PER_S
        scalars.append(dict(time=interval['end_s'], **{column: rate}))
    index = dict(frames=frames, accepted_intervals=intervals,
        source_window_s=[start, end], source_present=True, generation_columns=[column],
        source_scalars=scalars, solver_time_bounds_s=[0.0, 25e-9])
    raw = {}
    for frame in frames:
        data = {}
        mass = projection.R.temporal_interval(frame['start_s']-epoch,
            frame['end_s']-epoch, 0.0, sigma)[0]
        factor = mass/frame['dt_s']/reducer.RAW_TO_FC_PER_S
        for scope in list(reducer.ROIS)+['SILICON_NO_WINDOW']:
            expected = reference['rois']['Total' if scope == 'SILICON_NO_WINDOW' else scope]
            data['G', scope] = expected['all_time_charge_fC']*factor
            data['XG', scope] = expected['absolute_moments_fC_um'][0]*factor
            data['ZG', scope] = expected['absolute_moments_fC_um'][1]*factor
            data['ONE', scope] = expected['silicon_area_um2']
        raw[frame['source_file']] = data
    return index, raw


def pure_identity_fixture(response, fields):
    """Return dictionaries labelled as unit fixtures, never archives or receipts."""
    cdim = dict(contract={'fixture': 'UNIT_FIXTURE_NOT_NATIVE width=20nm'},
        contract_sha256='unit-width', source_binding_sha256='unit-d2',
        source_spec=dict(schema='dram-see-v4-2d-control-source-spec-r1',
            source_configured=False, source_case='A0', stored_bit=0, numerical_variant='main'))
    control = dict(run_id='UNIT_FIXTURE_NOT_NATIVE_A0', archive_sha256='unit-archive',
        manifest_sha256='unit-manifest', device_cmd_sha256='unit-device',
        input_sha256={'input-manifest.json': 'unit-inputs'},
        execution_context={'producer_run_id': 'unit-producer'}, circuit_plt_sha256='unit-plt',
        dimensional_2d=copy.deepcopy(cdim), archived_role={'stored_bit': 0},
        archived_model={k: {} for k in ('geometry', 'doping', 'circuit')},
        mesh_sha256='unit-mesh', physics_manifest_sha256='unit-physics',
        physics_base_parameters_sha256='unit-base', circuit_signature='unit-circuit')
    signal = copy.deepcopy(control)
    signal['run_id'] = 'UNIT_FIXTURE_NOT_NATIVE_ALPHA'
    signal['dimensional_2d']['source_spec'] = dict(schema=fields.SOURCE_SCHEMA, stored_bit=0)
    signal['dimensional_2d']['alpha'] = dict(matched_a0=dict(
        run_id=control['run_id'], archive_sha256=control['archive_sha256'],
        manifest_sha256=control['manifest_sha256'], device_sha256=control['device_cmd_sha256'],
        input_manifest_sha256='unit-inputs', producer_run_id='unit-producer', stored_bit=0,
        numerical_variant='main', circuit_plt_sha256='unit-plt'))
    return signal, control


class Alpha2DFieldEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = load(DATA/'alpha2d_reference.py', 'alpha2d_reference_edge_test')
        cls.fields = load(DATA/'alpha2d_fields.py', 'alpha2d_fields_edge_test')
        cls.response = load(DATA/'alpha2d_response.py', 'alpha2d_response_edge_test')
        cls.fixture_reference = json.loads((HANDOFF/'new-reference-r2.json').read_text(encoding='utf-8'))

    def test_explicit_alpha_source_routes_only_to_alpha_adapter(self):
        audit = load(DATA/'current_audit.py', 'current_audit_alpha_dispatch_test')
        project = {'s2_geometry': {'source_dimension': 2}}
        archive = SimpleNamespace(members={'dimensional-contract.json': object()},
            read=lambda name: json.dumps(project).encode() if name == 'project.json' else
                json.dumps({'schema': 'dram-see-v4-2d-alpha-source-spec-r1'}).encode())
        alpha_adapter = SimpleNamespace(geometry=Mock(return_value={'report': {'branch': 'alpha'}}))
        a0_adapter = SimpleNamespace(geometry=Mock(return_value={'report': {'branch': 'a0'}}))
        with patch.dict(sys.modules, {'alpha2d_fields': alpha_adapter, 'field_adapter_2d': a0_adapter}):
            result = audit.geometry(archive, {'role_id': 'B2D-Aalpha-main-b0'})
        self.assertEqual(result, {'branch': 'alpha'})
        alpha_adapter.geometry.assert_called_once()
        a0_adapter.geometry.assert_not_called()

    def test_alpha_cli_routes_to_new_module_without_aliasing_a0_commands(self):
        adapter = load(DATA/'field_adapter.py', 'field_adapter_alpha_dispatch_test')
        alpha = SimpleNamespace(prepare=Mock(return_value={'schema': 'UNIT_FIXTURE_NOT_NATIVE', 'marker': 'prepare'}),
            convert=Mock(return_value={'schema': 'UNIT_FIXTURE_NOT_NATIVE', 'marker': 'convert',
                'native_source_field_verified': False}))
        a0 = SimpleNamespace(prepare=Mock(return_value={'marker': 'A0'}),
            convert=Mock(return_value={'marker': 'A0'}))
        with patch.dict(sys.modules, {'alpha2d_fields': alpha, 'field_adapter_2d': a0}), \
             patch.object(adapter.A, 'write_new') as write_new:
            with patch.object(sys, 'argv', ['field_adapter.py', 'prepare-alpha2d', '--solver', 'solver',
                    '--label', 'fixture', '--adapter', 'operation', '--output', 'out']), patch('builtins.print'):
                adapter.main()
            with patch.object(sys, 'argv', ['field_adapter.py', 'convert-alpha2d', '--solver', 'solver',
                    '--extraction', 'extract', '--output', 'out']), patch('builtins.print'):
                adapter.main()
        alpha.prepare.assert_called_once()
        alpha.convert.assert_called_once()
        write_new.assert_called_once_with(Path('out'), {'schema': 'UNIT_FIXTURE_NOT_NATIVE',
            'marker': 'convert', 'native_source_field_verified': False})
        a0.prepare.assert_not_called()
        a0.convert.assert_not_called()

    def test_matched_identity_rejects_alpha_bit_physics_width_and_frozen_a0_mismatch(self):
        signal, control = pure_identity_fixture(self.response, self.fields)
        mutations = []
        bad = copy.deepcopy(control); bad['archived_role']['stored_bit'] = 1
        mutations.append(('stored bit', bad))
        bad = copy.deepcopy(control); bad['physics_manifest_sha256'] = 'different-physics'
        mutations.append(('physics', bad))
        bad = copy.deepcopy(control); bad['dimensional_2d']['contract']['fixture'] = 'different-width'
        mutations.append(('width contract', bad))
        bad = copy.deepcopy(control); bad['archive_sha256'] = 'different-frozen-A0'
        mutations.append(('frozen A0 archive', bad))
        for label, candidate in mutations:
            with self.subTest(mismatch=label):
                with self.assertRaisesRegex(ValueError, 'differs|exact frozen matched A0'):
                    self.response.matched_identity(signal, candidate)

    def test_arithmetic_fixture_rejects_missing_reference_active_frame(self):
        ref = self.fixture_reference
        index, raw = arithmetic_clock(ref, self.reference)
        missing = copy.deepcopy(raw)
        peak = max(index['frames'], key=lambda frame: raw[frame['source_file']]['G', 'SILICON_NO_WINDOW'])
        for scope in list(self.reference.ROIS)+['SILICON_NO_WINDOW']:
            for key in ('G', 'XG', 'ZG'):
                missing[peak['source_file']][key, scope] = 0.0
        result = self.reference.compare(ref, index, missing)
        self.assertFalse(result['passed'])
        self.assertTrue(any('Reference-active source frame is missing' in item for item in result['failures']))

    def test_arithmetic_fixture_rejects_time_centroid_shift(self):
        ref = self.fixture_reference
        index, raw = arithmetic_clock(ref, self.reference)
        ordered = index['frames']
        step = ordered[1]['start_s']-ordered[0]['start_s']
        offset = max(1, int(round(0.08e-12/step)))
        shifted = {frame['source_file']: copy.deepcopy(raw[frame['source_file']]) for frame in ordered}
        scopes = list(self.reference.ROIS)+['SILICON_NO_WINDOW']
        for frame in ordered:
            shifted[frame['source_file']] = {
                key: (value if key[0] == 'ONE' else 0.0)
                for key, value in raw[frame['source_file']].items()
            }
        for i, frame in enumerate(ordered):
            destination = min(i+offset, len(ordered)-1)
            target = ordered[destination]['source_file']
            for scope in scopes:
                for prefix in ('G', 'XG', 'ZG'):
                    shifted[target][prefix, scope] += raw[frame['source_file']][prefix, scope]
        result = self.reference.compare(ref, index, shifted)
        self.assertFalse(result['passed'])
        self.assertTrue(any('Native time centroid exceeds 0.04ps' in item for item in result['failures']))

    def test_arithmetic_fixture_retains_actual_dt_and_rejects_above_004ps(self):
        ref = self.fixture_reference
        index, raw = arithmetic_clock(ref, self.reference)
        target = next(frame for frame in index['frames'] if frame['end_s'] > ref['source_window_s'][0])
        start = target['start_s']
        old_end = target['end_s']
        target['end_s'] = start + 0.05e-12
        target['dt_s'] = 0.05e-12
        interval = next(item for item in index['accepted_intervals'] if item['accepted_index'] == target['accepted_index'])
        interval['end_s'] = target['end_s']; interval['dt_s'] = target['dt_s']
        scalar = next(item for item in index['source_scalars'] if item['time'] == old_end)
        scalar['time'] = target['end_s']
        result = self.reference.compare(ref, index, raw)
        self.assertFalse(result['passed'])
        self.assertTrue(result['actual_step_violations'])
        self.assertTrue(any('Actual accepted source-window step exceeds 0.04ps' in item for item in result['failures']))

    def test_arithmetic_fixture_preserves_outside_window_plt_charge_failure(self):
        ref = self.fixture_reference
        index, raw = arithmetic_clock(ref, self.reference)
        column = index['generation_columns'][0]
        index['source_scalars'].insert(-1, {'time': ref['source_window_s'][1]+1e-12, column: 1e32})
        result = self.reference.compare(ref, index, raw)
        self.assertFalse(result['passed'])
        self.assertGreater(result['charge']['PLT_outside_window_fC'], 0.0)
        self.assertTrue(any('full-simulation PLT source total exceeds 5%' in item for item in result['failures']))


if __name__ == '__main__':
    unittest.main()
