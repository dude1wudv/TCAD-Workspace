"""Focused regression checks for the r9 2D alpha dispatch and input payload."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
DEVICE = ROOT / 'experiments/dram-see-v4/continuous/device'
DATA = ROOT / 'experiments/dram-see-v4/continuous/data'
VALIDATION = ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/alpha-validation'
ALPHA_ROOT = ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/alpha-native-integration'
OFFLINE = ALPHA_ROOT / 'offline-payload-b0'
REQUEST = ALPHA_ROOT / 'request-bit0-main.json'
A0_CANDIDATE = ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/device-implementation/candidates/20261019T104330Z-v4-2d-a0-main-b0-input-r2'
R8_CANDIDATES = {
    0: ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/device-implementation/candidates/20261019T104330Z-v4-2d-a0-main-b0-input-r2',
    1: ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/device-implementation/candidates/20261019T104330Z-v4-2d-a0-main-b1-input-r2',
}

spec = importlib.util.spec_from_file_location('tcad_alpha_dispatch_validation', ROOT / 'scripts/tcad.py')
tcad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcad)
bridge = tcad.geometry_module()
alpha_spec = importlib.util.spec_from_file_location('alpha_native_2d_validation', DEVICE / 'alpha_native_2d.py')
alpha = importlib.util.module_from_spec(alpha_spec)
alpha_spec.loader.exec_module(alpha)
RUNNER_SHA256 = tcad.file_hash(ROOT / 'scripts/tcad.py')


class TwoDimensionalAlphaInputTests(unittest.TestCase):
    def test_r8_b0_b1_still_enter_through_original_runner_and_stage_reuse(self):
        """New alpha dispatch must leave frozen source-free A0 on its old path."""
        for bit, candidate in R8_CANDIDATES.items():
            with self.subTest(stored_bit=bit):
                with tempfile.TemporaryDirectory(prefix='r8-alpha-dispatch-b{}-'.format(bit), dir=str(VALIDATION)) as temp:
                    temp_root = Path(temp)
                    project = temp_root / 'candidate'
                    shutil.copytree(candidate, project)
                    project_spec = json.loads((project / 'project.json').read_text(encoding='utf-8'))
                    admitted, staged = [], []
                    real_admit, real_stage = bridge.geometry_admit, bridge.geometry_stage_reuse

                    def admit_spy(*args):
                        result = real_admit(*args)
                        admitted.append(result)
                        return result

                    def stage_spy(*args):
                        result = real_stage(*args)
                        staged.append((args, result))
                        return result

                    exec_result = subprocess.CompletedProcess([], 0, stdout='mock-commit', stderr='')
                    remote_result = subprocess.CompletedProcess([], 0, stdout='', stderr='')
                    ssh_result = subprocess.CompletedProcess([], 0, stdout=b'', stderr=b'')
                    with patch.object(tcad, 'ROOT', temp_root), \
                         patch.object(tcad, 'geometry_module', return_value=bridge), \
                         patch.object(bridge, 'geometry_admit', side_effect=admit_spy), \
                         patch.object(bridge, 'geometry_stage_reuse', side_effect=stage_spy), \
                         patch.object(tcad, 'assert_no_active_run'), \
                         patch.object(tcad, 'execute', return_value=exec_result), \
                         patch.object(tcad, 'remote', return_value=remote_result), \
                         patch.object(tcad.subprocess, 'run', return_value=ssh_result), \
                         patch.object(tcad, 'status_run', return_value={'status': 'RUNNING'}):
                        result = tcad._run_project(
                            {'remote_root': '/remote/root', 'tool_bin': '/opt/synopsys/bin'},
                            ['ssh-fixture'], project, run_id=project_spec['s2_geometry']['run_id'], detach=True,
                        )

                    self.assertEqual(result['status'], 'RUNNING')
                    self.assertEqual(len(admitted), 1)
                    self.assertEqual(len(staged), 1)
                    self.assertIs(staged[0][1], admitted[0])
                    self.assertEqual(admitted[0]['role_id'], 'B2D-A0-main-b{}'.format(bit))
                    self.assertEqual(admitted[0]['source_dimension'], 2)
                    self.assertEqual(admitted[0]['producer_run_id'], '20261017T051217Z-v4-continuous-b1-d2-r8')
                    generated = temp_root / 'local_runtime/runs' / admitted[0]['run_id']
                    manifest = json.loads((generated / 'manifest.json').read_text(encoding='utf-8'))
                    run_script = (generated / 'run.sh').read_text(encoding='utf-8')
                    self.assertEqual(manifest['runner_sha256'], RUNNER_SHA256)
                    self.assertIn('flock -n 9', run_script)
                    self.assertIn('sdevice --threads 1 --exit-on-failure device.cmd', run_script)
                    self.assertIn('taskset -c "$cpu"', run_script)

    def test_r9_source_payload_removes_to_exact_a0_deck_and_keeps_units(self):
        a0 = (A0_CANDIDATE / 'device.cmd').read_bytes()
        include = (OFFLINE / 'heavyion.physics.inc').read_bytes()
        signal = alpha.render_signal(a0, include)
        self.assertEqual(alpha.source_free_deck(signal, include), a0)
        self.assertNotEqual(signal, a0)
        self.assertEqual(signal.count(alpha.BEGIN), 1)
        self.assertEqual(signal.count(alpha.END), 1)
        self.assertEqual(signal.count(alpha.PLOT), 1)
        self.assertEqual(signal.count(alpha.CURRENT), 1)
        self.assertIn(b'HeavyIon("AlphaStrip20nm2D")', include)
        self.assertEqual((OFFLINE / 'run-parameters.par').read_bytes(),
                         (OFFLINE / 'physics.par').read_bytes() + b'\n' + (OFFLINE / 'source.par').read_bytes())

        for name in ('physics.par', 'physics-manifest.json', 'Silicon.par', 'Oxide.par',
                     'model.proposed.json', 'geometry-contract.json', 'dimensional-contract.json'):
            with self.subTest(shared_input=name):
                self.assertEqual((OFFLINE / name).read_bytes(), (A0_CANDIDATE / name).read_bytes())

        contract = json.loads((OFFLINE / 'source-contract.json').read_text(encoding='utf-8'))
        dimension = json.loads((OFFLINE / 'dimensional-contract.json').read_text(encoding='utf-8'))
        self.assertEqual(contract['schema'], alpha.PROJECTION_SCHEMA)
        self.assertEqual(contract['dimension'], 2)
        self.assertEqual(contract['G2_unit'], 'cm^-3 s^-1')
        self.assertEqual(contract['mapping']['effective_width_um'], 0.02)
        self.assertAlmostEqual(contract['mapping']['effective_width_cm'], 2e-6, places=20)
        self.assertEqual(contract['mapping']['area_factor'], 0.02)
        self.assertEqual(contract['mesh_sha256'], hashlib.sha256((A0_CANDIDATE / 'cell_msh.tdr').read_bytes()).hexdigest())
        self.assertEqual(contract['physics_manifest_sha256'], hashlib.sha256((A0_CANDIDATE / 'physics-manifest.json').read_bytes()).hexdigest())
        self.assertEqual(contract['mapping']['explicit_capacitance_rescale'], False)
        self.assertEqual(contract['mapping']['port_current_additional_width_factor'], 1)
        self.assertEqual(contract['native_coordinates'], {'X': 'physical_x', 'Y': 'physical_z'})
        self.assertEqual(contract['raw_native_area_integral_to_pairs_per_s'], 2e-14)
        self.assertTrue(contract['source_window_is_observation_only'])
        self.assertFalse(contract['native_source_qualified'])
        self.assertFalse(contract['is_tcad_result'])
        self.assertFalse(contract['pmi_r12_fixed'])
        self.assertEqual(dimension['source_dimension'], 2)
        self.assertEqual(dimension['effective_width_nm'], 20)

        timed = alpha.timing(a0, contract)
        self.assertEqual(timed['source_epoch_s'], 15e-9)
        self.assertEqual(timed['native_observation_window_literals'],
                         ['1.4998400000000001e-08', '1.5001599999999999e-08'])
        self.assertEqual(timed['native_minus_mathematical_window_s'][0], 3.308722450212111e-24)
        self.assertTrue(timed['observation_window_is_not_physical_source_truncation'])

    def test_formal_prepare_refuses_running_same_bit_a0_without_creating_project(self):
        request = json.loads(REQUEST.read_text(encoding='utf-8'))
        matched = Path(request['matched_a0_run'])
        manifest = json.loads((matched / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(request['stored_bit'], 0)
        self.assertEqual(manifest['run_id'], matched.name)
        self.assertEqual(manifest['state'], 'RUNNING')
        self.assertIsNone(manifest.get('remote_exit_code'))
        self.assertIsNone(manifest.get('collection_exit_code'))

        run_id = 'validation-no-collected-a0-r1'
        target = ALPHA_ROOT / 'projects' / run_id
        self.assertFalse(target.exists())
        completed = subprocess.run(
            [str(ROOT / 'local_runtime/vdmos-analysis-venv/Scripts/python.exe'), '-X', 'utf8', '-B',
             str(DEVICE / 'prepare_case.py'), '--request', str(REQUEST), '--run-id', run_id, '--output', str(target)],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn('matched A0 is not yet completely collected', completed.stderr)
        self.assertFalse(target.exists())

    def test_sourceful_alpha_is_rejected_by_a0_only_baseline_entry(self):
        """baseline-2d must not treat an active alpha trace as a source-free A0."""
        sys.path.insert(0, str(DATA))
        pipeline_spec = importlib.util.spec_from_file_location('alpha_pipeline_boundary_test', DATA / 'pipeline.py')
        pipeline = importlib.util.module_from_spec(pipeline_spec)
        pipeline_spec.loader.exec_module(pipeline)
        dimensional_contract = json.loads((A0_CANDIDATE / 'dimensional-contract.json').read_text(encoding='utf-8'))
        times = [i * 1e-10 for i in range(251)]
        trace = {'time_s': times, 'v_sn_V': [0.0] * len(times),
                 'v_bl_V': [0.6] * len(times), 'i_sn_A': [0.0] * len(times)}
        alpha_evidence = {
            'archived_role': {'case': 'Aalpha', 'stored_bit': 0, 'source_configured': True},
            'dimensional_2d': {
                'contract': dimensional_contract,
                'source_spec': {'schema': 'dram-see-v4-2d-alpha-source-spec-r1', 'source_configured': True},
            },
        }
        with patch.object(pipeline, 'original_run', return_value=(trace, alpha_evidence)):
            with self.assertRaises(ValueError):
                pipeline.baseline_2d('UNIT_FIXTURE_NOT_NATIVE')


if __name__ == '__main__':
    unittest.main()
