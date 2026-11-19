"""Focused original-runner tests; all transport and native boundaries are mocked."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('mesh_continuation_runner', ROOT / 'scripts/tcad.py')
tcad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcad)

STEPS = [
    dict(tool='tdx', args=['-tcl', 'observe_tdr_topology.tcl', 'cell_msh.tdr'], outputs=['tdr-region-status.json']),
    dict(tool='tdx', args=['-dd', '-M', '0', '-S', '0', 'cell_msh.tdr', 'mesh-observed'], outputs=['mesh-observed.grd', 'mesh-observed.dat']),
    dict(tool='svisual', args=['--threads', '1', '--max_threads', '1', '-b', '-tcl', '-script', 'measure-geometry.tcl'], outputs=['geometry-status.json']),
    dict(tool='sdevice', args=['device.cmd'], outputs=['dc_des.log']),
]
EXITS = {'step-003-tdx-exit-code.txt': 'tdx-metadata-exit-code.txt',
         'step-004-tdx-exit-code.txt': 'tdx-converter-exit-code.txt',
         'step-005-svisual-exit-code.txt': 'svisual-exit-code.txt'}


class MeshContinuationRunnerTests(unittest.TestCase):
    def build(self, root, fail_source=False, missing_binding=False):
        project = root / 'project'
        project.mkdir()
        cfg = dict(mode='produce_from_mesh', run_id='mesh-continuation-fixture')
        (project / 'project.json').write_text(json.dumps(dict(name='mesh-continuation-fixture',
            s2_geometry=cfg, steps=STEPS)), encoding='utf-8')
        binding = b'{"synthetic_fixture":true,"source_run_id":"original-fixture-only"}\n'
        if not missing_binding:
            (project / 'mesh-source-binding.json').write_bytes(binding)
        stage = Mock(side_effect=ValueError('Original mesh identity differs') if fail_source else None)
        bridge = types.SimpleNamespace(GEOMETRY_EXITS=EXITS, geometry_admit=lambda *_: cfg,
            geometry_stage_mesh_reuse=stage)
        result = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        launched = subprocess.CompletedProcess([], 0, stdout=b'', stderr=b'')
        with patch.object(tcad, 'ROOT', root), \
             patch.object(tcad, 'geometry_module', return_value=bridge), \
             patch.object(tcad, 'assert_no_active_run') as live_check, \
             patch.object(tcad, 'execute', return_value=result), \
             patch.object(tcad, 'remote', return_value=result) as transport, \
             patch.object(tcad.subprocess, 'run', return_value=launched) as native, \
             patch.object(tcad, 'status_run', return_value={'status': 'RUNNING'}):
            if fail_source or missing_binding:
                with self.assertRaises((ValueError, FileNotFoundError)):
                    tcad._run_project({'remote_root': '/remote/root', 'tool_bin': '/opt/synopsys/bin'},
                        ['ssh-fixture'], project, run_id=cfg['run_id'], detach=True)
                live_check.assert_not_called()
                transport.assert_not_called()
                native.assert_not_called()
                self.assertFalse((root / 'local_runtime/runs' / cfg['run_id']).exists())
                return
            tcad._run_project({'remote_root': '/remote/root', 'tool_bin': '/opt/synopsys/bin'},
                ['ssh-fixture'], project, run_id=cfg['run_id'], detach=True)
            stage.assert_called_once_with(project, cfg)
            live_check.assert_called_once()
            native.assert_called_once()
        folder = root / 'local_runtime/runs' / cfg['run_id']
        return ((folder / 'run.sh').read_text(encoding='utf-8'),
                json.loads((folder / 'manifest.json').read_text(encoding='utf-8')), binding)

    def test_four_actual_steps_keep_original_indices_and_inherited_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            script, manifest, binding = self.build(Path(tmp))
        keys = ['step-003-tdx', 'step-004-tdx', 'step-005-svisual', 'step-006-sdevice']
        self.assertEqual(list(manifest['tool_exit_codes']), keys)
        self.assertEqual(list(manifest['tool_evidence']), keys)
        self.assertTrue(all(v is None for v in manifest['tool_exit_codes'].values()))
        self.assertEqual(manifest['steps'], STEPS)
        self.assertEqual(manifest['native_step_start_index'], 3)
        self.assertEqual(manifest['inherited_step_indices'], [1, 2])
        self.assertEqual(manifest['mesh_source_binding_sha256'], hashlib.sha256(binding).hexdigest())
        self.assertNotIn('capture_native_step step-001-', script)
        self.assertNotIn('capture_native_step step-002-', script)
        self.assertEqual(script.count('geometry_bridge.py prepare'), 1)
        self.assertEqual(script.count('geometry_bridge.py finalize'), 1)
        self.assertLess(script.index('mesh_resource_guard.py'), script.index('geometry_bridge.py prepare'))
        self.assertLess(script.index('geometry_bridge.py prepare'), script.index('STEP 3:'))
        self.assertLess(script.index('STEP 5:'), script.index('geometry_bridge.py finalize'))
        self.assertLess(script.index('geometry_bridge.py finalize'), script.index('STEP 6:'))
        for key in keys:
            self.assertIn('capture_native_step ' + key, script)
        for canonical in EXITS.values():
            self.assertIn('--canonical ' + canonical, script)
        self.assertIn('flock -n 9', script)
        self.assertIn('sdevice --threads 1 --exit-on-failure device.cmd', script)
        self.assertIn('OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1', script)

    def test_source_rejection_cannot_stage_remote_or_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build(Path(tmp), fail_source=True)

    def test_missing_frozen_binding_cannot_create_a_run_or_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build(Path(tmp), missing_binding=True)


if __name__ == '__main__':
    unittest.main()
