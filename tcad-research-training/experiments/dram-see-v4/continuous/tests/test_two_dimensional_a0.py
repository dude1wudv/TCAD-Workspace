"""Focused input-engineering checks for the frozen 2D A0 r8 candidates."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
DEVICE = ROOT / 'experiments/dram-see-v4/continuous/device'
VALIDATION = ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/validation'
CANDIDATES = {
    0: ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/device-implementation/candidates/20261019T104330Z-v4-2d-a0-main-b0-input-r2',
    1: ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/device-implementation/candidates/20261019T104330Z-v4-2d-a0-main-b1-input-r2',
}

spec = importlib.util.spec_from_file_location('tcad_a0_validation', ROOT / 'scripts/tcad.py')
tcad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcad)
bridge = tcad.geometry_module()
RUNNER_SHA256 = tcad.file_hash(ROOT / 'scripts/tcad.py')


class TwoDimensionalA0InputTests(unittest.TestCase):
    def test_original_runner_admits_and_stages_both_frozen_bits(self):
        """Exercise original _run_project and real bridge calls with remote effects mocked."""
        for bit, candidate in CANDIDATES.items():
            with self.subTest(stored_bit=bit):
                self.assertTrue(candidate.is_dir())
                with tempfile.TemporaryDirectory(prefix='a0-b{}-'.format(bit), dir=str(VALIDATION)) as temp:
                    temp_root = Path(temp)
                    project = temp_root / 'candidate'
                    shutil.copytree(candidate, project)
                    spec_data = json.loads((project / 'project.json').read_text(encoding='utf-8'))
                    admitted = []
                    staged = []
                    actual_admit = bridge.geometry_admit
                    actual_stage = bridge.geometry_stage_reuse

                    def record_admit(*args):
                        cfg = actual_admit(*args)
                        admitted.append(cfg)
                        return cfg

                    def record_stage(*args):
                        result = actual_stage(*args)
                        staged.append((args, result))
                        return result

                    execute_result = subprocess.CompletedProcess([], 0, stdout='fixture-commit', stderr='')
                    remote_result = subprocess.CompletedProcess([], 0, stdout='', stderr='')
                    ssh_result = subprocess.CompletedProcess([], 0, stdout=b'', stderr=b'')
                    with patch.object(tcad, 'ROOT', temp_root), \
                         patch.object(tcad, 'geometry_module', return_value=bridge), \
                         patch.object(bridge, 'geometry_admit', side_effect=record_admit), \
                         patch.object(bridge, 'geometry_stage_reuse', side_effect=record_stage), \
                         patch.object(tcad, 'assert_no_active_run'), \
                         patch.object(tcad, 'execute', return_value=execute_result), \
                         patch.object(tcad, 'remote', return_value=remote_result), \
                         patch.object(tcad.subprocess, 'run', return_value=ssh_result), \
                         patch.object(tcad, 'status_run', return_value={'status': 'RUNNING'}) as status:
                        result = tcad._run_project(
                            {'remote_root': '/remote/root', 'tool_bin': '/opt/synopsys/bin'},
                            ['ssh-fixture'], project, run_id=spec_data['s2_geometry']['run_id'], detach=True,
                        )

                    self.assertEqual(result['status'], 'RUNNING')
                    status.assert_called_once()
                    self.assertEqual(len(admitted), 1)
                    self.assertEqual(len(staged), 1)
                    cfg = admitted[0]
                    self.assertIs(staged[0][1], cfg)
                    self.assertEqual(cfg['role_id'], 'B2D-A0-main-b{}'.format(bit))
                    self.assertEqual(cfg['producer_run_id'], '20261017T051217Z-v4-continuous-b1-d2-r8')
                    self.assertEqual(cfg['source_dimension'], 2)
                    self.assertEqual(cfg['effective_width_nm'], 20)
                    self.assertEqual(cfg['area_factor'], 0.02)
                    self.assertEqual(cfg['mesh_sha256'], json.loads((project / 'd2-source-binding.json').read_text())['mesh_sha256'])

                    manifest = json.loads((temp_root / 'local_runtime/runs' / cfg['run_id'] / 'manifest.json').read_text())
                    runner = (temp_root / 'local_runtime/runs' / cfg['run_id'] / 'run.sh').read_text(encoding='utf-8')
                    self.assertEqual(manifest['runner_sha256'], RUNNER_SHA256)
                    self.assertIn('flock -n 9', runner)
                    self.assertIn('sdevice --threads 1 --exit-on-failure device.cmd', runner)
                    self.assertIn('taskset -c "$cpu"', runner)
                    self.assertEqual(hashlib.sha256((project / 'cell_msh.tdr').read_bytes()).hexdigest(), cfg['mesh_sha256'])

    def test_width_capacitance_shared_initialization_and_bit_driver(self):
        device_text = {}
        for bit, candidate in CANDIDATES.items():
            request = json.loads((candidate / 'controlled-request.json').read_text(encoding='utf-8'))
            width = json.loads((candidate / 'dimensional-contract.json').read_text(encoding='utf-8'))
            device = (candidate / 'device.cmd').read_text(encoding='utf-8')
            device_text[bit] = device

            self.assertEqual(request['schema'], 'dram-see-v4-controlled-device-request-r8')
            self.assertEqual((request['dimension'], request['effective_width_nm'], request['stored_bit']), (2, 20, bit))
            self.assertEqual((width['native_dimension'], width['physical_dimension'], width['source_dimension']), (2, 2, 2))
            self.assertEqual((width['effective_width_nm'], width['effective_width_um'], width['effective_width_cm']), (20, 0.02, 2e-6))
            self.assertEqual(width['area_factor'], 0.02)
            self.assertEqual(width['native_to_physical_axes'], {'X': 'x', 'Y': 'z', 'Z': 'omitted_y'})
            self.assertEqual(width['out_of_plane_axis'], 'y')
            self.assertTrue(width['port_current_already_width_scaled'])
            self.assertFalse(width['explicit_capacitance_rescale'])
            self.assertEqual((width['Cstore_fF'], width['Cbl_fF']), (20, 200))
            self.assertIn('Physics { AreaFactor=0.02', device)
            self.assertEqual(device.count('Capacitor_pset cstore (sn plate) {capacitance=2e-14}'), 1)
            self.assertEqual(device.count('Capacitor_pset cbl (bl 0) {capacitance=2e-13}'), 1)
            self.assertIn('pwl=(0 -0.5 2e-9 -0.5 2.1e-9 1.8', device)
            self.assertEqual(device.count('Set(sn=0.6)'), 1)
            self.assertEqual(device.count('Unset(sn)'), 1)
            self.assertEqual(device.count('Transient('), 15)
            self.assertLess(device.index('Set(sn=0.6)'), device.index('Unset(sn)'))
            self.assertLess(device.index('Unset(sn)'), device.index('Transient('))
            self.assertNotRegex(device, r'\bLoad\s*\(')
            self.assertEqual(__import__('re').findall(r'(?<![A-Za-z])Set\(sn=([^)]*)\)', device), ['0.6'])
            final_times = [float(value) for value in __import__('re').findall(r'Transient\([^\n]*FinalTime=([0-9.eE+-]+)', device)]
            self.assertTrue(final_times)
            self.assertTrue(math.isclose(max(final_times), 25e-9, rel_tol=1e-12))

        drive_lines = {}
        for bit, device in device_text.items():
            drive_lines[bit] = next(line for line in device.splitlines() if 'Vsource_pset vdrive ' in line)
        self.assertIn('pwl=(0 0 6.1e-9 0 6.2e-9 0.6 25e-9 0.6)', drive_lines[0])
        self.assertIn('pwl=(0 1.2 6.1e-9 1.2 6.2e-9 0.6 25e-9 0.6)', drive_lines[1])
        normalized = {}
        for bit, device in device_text.items():
            normalized[bit] = '\n'.join(
                'Vsource_pset vdrive (drive 0) {pwl=(BIT_SELECT)}' if 'Vsource_pset vdrive ' in line else line
                for line in device.splitlines()
            )
        self.assertEqual(normalized[0], normalized[1])

    def test_frozen_byte_changes_to_width_axes_source_dimension_mesh_or_physics_are_rejected(self):
        candidate = CANDIDATES[0]
        with tempfile.TemporaryDirectory(prefix='a0-tamper-', dir=str(VALIDATION)) as temp:
            project = Path(temp) / 'candidate'
            shutil.copytree(candidate, project)
            original = {}

            def json_mutation(path, field_path, replacement):
                value = json.loads(path.read_text(encoding='utf-8'))
                target = value
                for key in field_path[:-1]:
                    target = target[key]
                target[field_path[-1]] = replacement
                return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')

            cases = [
                ('effective width', 'dimensional-contract.json',
                 lambda p, raw: json_mutation(p, ('effective_width_nm',), 21)),
                ('axis mapping', 'dimensional-contract.json',
                 lambda p, raw: json_mutation(p, ('native_to_physical_axes', 'Y'), 'y')),
                ('source dimension', 'd2-source-binding.json',
                 lambda p, raw: json_mutation(p, ('source_dimension',), 3)),
                ('source mesh', 'cell_msh.tdr',
                 lambda p, raw: bytes([raw[0] ^ 1]) + raw[1:]),
                ('physics input', 'physics.par',
                 lambda p, raw: bytes([raw[0] ^ 1]) + raw[1:]),
            ]
            for label, relative, mutate in cases:
                with self.subTest(tamper=label):
                    path = project / relative
                    if relative not in original:
                        original[relative] = path.read_bytes()
                    before = original[relative]
                    self.assertTrue(before)
                    path.write_bytes(mutate(path, before))
                    try:
                        spec_data = json.loads((project / 'project.json').read_text(encoding='utf-8'))
                        with self.assertRaisesRegex(ValueError, 'frozen 2D input changed'):
                            bridge.geometry_admit(project, spec_data, RUNNER_SHA256)
                    finally:
                        path.write_bytes(before)

    def test_legacy_3d_a0_request_keeps_its_role_and_r8_is_separate(self):
        def load_contract(path, name):
            module_spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(module)
            return module

        current = load_contract(DEVICE / 'case_contract.py', 'current_case_contract')
        old = load_contract(ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/device-implementation/before/case_contract.py', 'old_case_contract')
        legacy = {
            'schema': current.SCHEMA, 'kind': 'transient', 'dimension': 3,
            'gate_top_depth_nm': 80, 'sn_junction_depth_nm': 87, 'variant': 'main',
            'stored_bit': 0, 'source_case': 'A0', 'd3_source_run': 'legacy-d3-run',
        }
        self.assertEqual(current.role_id(legacy), 'B1-A0-main-b0')
        self.assertEqual(current.role_id(legacy), old.role_id(legacy))
        self.assertTrue(current.is_role('B1-A0-main-b0'))

        request2d = {
            'schema': current.SCHEMA_2D, 'kind': 'transient', 'dimension': 2,
            'gate_top_depth_nm': 80, 'sn_junction_depth_nm': 87, 'variant': 'main',
            'stored_bit': 0, 'source_case': 'A0', 'd2_source_run': 'original-d2-run',
            'effective_width_nm': 20,
        }
        self.assertEqual(current.role_id(request2d), 'B2D-A0-main-b0')
        with self.assertRaises(ValueError):
            old.validate(request2d)


if __name__ == '__main__':
    unittest.main()
