"""DC-only checkpoint routing; SSH and native launch are always mocked."""
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
spec = importlib.util.spec_from_file_location('dc_only_runner_fixture', ROOT/'scripts/tcad.py')
tcad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcad)


class DCContinuationRunnerTests(unittest.TestCase):
    def build(self, root, reject=False, missing=False):
        project = root/'UNIT_FIXTURE_NOT_NATIVE'
        project.mkdir()
        cfg = dict(mode='produce_from_geometry', run_id='dc-continuation-fixture',
                   geometry_producer_run_id='original-geometry-fixture',
                   geometry_selector_file='dc-geometry-selector.json',
                   geometry_selector_sha256='a'*64,
                   geometry_report_file='dc-source-bindings/geometry-validation.json')
        steps = [dict(tool='sdevice', args=['device.cmd'], outputs=['dc_des.log'])]
        (project/'project.json').write_text(json.dumps(dict(name=cfg['run_id'], s2_geometry=cfg, steps=steps)))
        binding = b'{"UNIT_FIXTURE_NOT_NATIVE":true,"actual_steps":[6]}\n'
        if not missing:
            (project/'dc-source-binding.json').write_bytes(binding)
        stage = Mock(side_effect=ValueError('Original geometry source differs') if reject else None)
        bridge = types.SimpleNamespace(geometry_admit=lambda *_: cfg, geometry_stage_dc_reuse=stage)
        reply = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        launch_reply = subprocess.CompletedProcess([], 0, stdout=b'', stderr=b'')
        with patch.object(tcad, 'ROOT', root), patch.object(tcad, 'geometry_module', return_value=bridge), \
             patch.object(tcad, 'assert_no_active_run') as idle, patch.object(tcad, 'execute', return_value=reply), \
             patch.object(tcad, 'remote', return_value=reply) as transport, \
             patch.object(tcad.subprocess, 'run', return_value=launch_reply) as launch, \
             patch.object(tcad, 'status_run', return_value={'status': 'RUNNING'}):
            if reject or missing:
                with self.assertRaises((ValueError, FileNotFoundError)):
                    tcad._run_project({'remote_root': '/remote/root', 'tool_bin': '/opt/synopsys/bin'},
                                      ['ssh-fixture'], project, cfg['run_id'], True)
                idle.assert_not_called()
                transport.assert_not_called()
                launch.assert_not_called()
                self.assertFalse((root/'local_runtime/runs'/cfg['run_id']).exists())
                return
            tcad._run_project({'remote_root': '/remote/root', 'tool_bin': '/opt/synopsys/bin'},
                              ['ssh-fixture'], project, cfg['run_id'], True)
            stage.assert_called_once_with(project, cfg)
            idle.assert_called_once()
            launch.assert_called_once()
        folder = root/'local_runtime/runs'/cfg['run_id']
        return (folder/'run.sh').read_text(), json.loads((folder/'manifest.json').read_text()), binding

    def test_only_current006_and_original_geometry_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            script, manifest, binding = self.build(Path(tmp))
        self.assertEqual(manifest['native_step_start_index'], 6)
        self.assertEqual(manifest['inherited_step_indices'], [1, 2, 3, 5])
        self.assertEqual(manifest['tool_exit_codes'], {'step-006-sdevice': None})
        self.assertEqual(list(manifest['tool_evidence']), ['step-006-sdevice'])
        self.assertEqual(manifest['dc_source_binding_sha256'], hashlib.sha256(binding).hexdigest())
        self.assertEqual(manifest['geometry_producer_run_id'], 'original-geometry-fixture')
        self.assertEqual(manifest['geometry_selector_file'], 'dc-geometry-selector.json')
        self.assertEqual(manifest['geometry_selector_sha256'], 'a'*64)
        self.assertEqual(manifest['geometry_report_file'], 'dc-source-bindings/geometry-validation.json')
        for i in range(1, 6):
            self.assertNotIn('capture_native_step step-%03d-' % i, script)
        self.assertNotIn('geometry_bridge.py prepare', script)
        self.assertNotIn('geometry_bridge.py finalize', script)
        self.assertNotIn('geometry_bridge.py record-exit', script)
        self.assertEqual(script.count('mesh_resource_guard.py'), 1)
        self.assertLess(script.index('mesh_resource_guard.py'), script.index('STEP 6:'))
        self.assertIn('flock -n 9', script)
        self.assertIn('sdevice --threads 1 --exit-on-failure device.cmd', script)
        self.assertIn('OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1', script)

    def test_rejected_original_geometry_cannot_stage_or_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build(Path(tmp), reject=True)

    def test_missing_frozen_source_binding_cannot_create_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build(Path(tmp), missing=True)


if __name__ == '__main__':
    unittest.main()
