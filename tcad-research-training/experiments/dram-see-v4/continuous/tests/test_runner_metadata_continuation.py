"""New checkpoint routing; all SSH and native launch boundaries are mocked."""
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
spec = importlib.util.spec_from_file_location('metadata_continuation_runner', ROOT / 'scripts/tcad.py')
tcad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcad)
STEPS = [
    dict(tool='svisual', args=['--threads', '1', '--max_threads', '1', '-b', '-tcl', '-script', 'measure-geometry.tcl'], outputs=['geometry-status.json']),
    dict(tool='sdevice', args=['device.cmd'], outputs=['dc_des.log']),
]


class MetadataContinuationRunnerTests(unittest.TestCase):
    def build(self, root, reject=False, missing=False):
        project = root / 'UNIT_FIXTURE_NOT_NATIVE'
        project.mkdir()
        cfg = dict(mode='produce_from_metadata', run_id='metadata-continuation-fixture')
        (project / 'project.json').write_text(json.dumps(dict(name=cfg['run_id'], s2_geometry=cfg, steps=STEPS)))
        binding = b'{"synthetic_fixture":true,"source":"two-original-runs-and-typed-operations"}\n'
        if not missing:
            (project / 'metadata-source-binding.json').write_bytes(binding)
        stage = Mock(side_effect=ValueError('Original metadata/source differs') if reject else None)
        bridge = types.SimpleNamespace(geometry_admit=lambda *_: cfg, geometry_stage_metadata_reuse=stage,
            GEOMETRY_EXITS={'step-005-svisual-exit-code.txt': 'svisual-exit-code.txt'})
        reply = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        launch_reply = subprocess.CompletedProcess([], 0, stdout=b'', stderr=b'')
        with patch.object(tcad, 'ROOT', root), patch.object(tcad, 'geometry_module', return_value=bridge), \
             patch.object(tcad, 'assert_no_active_run') as check, patch.object(tcad, 'execute', return_value=reply), \
             patch.object(tcad, 'remote', return_value=reply) as transport, \
             patch.object(tcad.subprocess, 'run', return_value=launch_reply) as launch, \
             patch.object(tcad, 'status_run', return_value={'status': 'RUNNING'}):
            if reject or missing:
                with self.assertRaises((ValueError, FileNotFoundError)):
                    tcad._run_project({'remote_root': '/remote/root', 'tool_bin': '/opt/synopsys/bin'},
                                      ['ssh-fixture'], project, cfg['run_id'], True)
                check.assert_not_called()
                transport.assert_not_called()
                launch.assert_not_called()
                self.assertFalse((root / 'local_runtime/runs' / cfg['run_id']).exists())
                return
            tcad._run_project({'remote_root': '/remote/root', 'tool_bin': '/opt/synopsys/bin'},
                              ['ssh-fixture'], project, cfg['run_id'], True)
            stage.assert_called_once_with(project, cfg)
            check.assert_called_once()
            launch.assert_called_once()
        folder = root / 'local_runtime/runs' / cfg['run_id']
        return (folder / 'run.sh').read_text(), json.loads((folder / 'manifest.json').read_text()), binding

    def test_only_visual_and_device_execute_no_invented_converter_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            script, manifest, binding = self.build(Path(tmp))
        self.assertEqual(list(manifest['tool_exit_codes']), ['step-005-svisual', 'step-006-sdevice'])
        self.assertEqual(list(manifest['tool_evidence']), ['step-005-svisual', 'step-006-sdevice'])
        self.assertTrue(all(v is None for v in manifest['tool_exit_codes'].values()))
        self.assertEqual(manifest['native_step_start_index'], 5)
        self.assertEqual(manifest['inherited_step_indices'], [1, 2, 3])
        self.assertEqual(manifest['metadata_source_binding_sha256'], hashlib.sha256(binding).hexdigest())
        self.assertEqual(manifest['geometry_observation_backend'], 'native_hdf5_v16_export')
        for index in range(1, 5):
            self.assertNotIn('capture_native_step step-%03d-' % index, script)
        self.assertNotIn('--canonical tdx-converter-exit-code.txt', script)
        self.assertEqual(script.count('geometry_bridge.py prepare'), 1)
        self.assertEqual(script.count('geometry_bridge.py finalize'), 1)
        self.assertLess(script.index('mesh_resource_guard.py'), script.index('geometry_bridge.py prepare'))
        self.assertLess(script.index('geometry_bridge.py prepare'), script.index('STEP 5:'))
        self.assertLess(script.index('STEP 5:'), script.index('geometry_bridge.py finalize'))
        self.assertLess(script.index('geometry_bridge.py finalize'), script.index('STEP 6:'))
        self.assertIn('flock -n 9', script)
        self.assertIn('sdevice --threads 1 --exit-on-failure device.cmd', script)
        self.assertIn('OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1', script)

    def test_rejected_source_cannot_stage_or_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build(Path(tmp), reject=True)

    def test_missing_frozen_binding_cannot_create_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build(Path(tmp), missing=True)


if __name__ == '__main__':
    unittest.main()
