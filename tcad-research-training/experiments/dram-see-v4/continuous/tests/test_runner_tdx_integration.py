"""Focused tests for the six-step TDX geometry wrapper integration."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('tdx_runner_under_test', ROOT / 'scripts/tcad.py')
tcad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcad)
bridge = tcad.geometry_module()


class TdxRunnerIntegrationTests(unittest.TestCase):
    def build_six_step_runner(self, root):
        project = root / 'project'
        project.mkdir()
        steps = [
            {'tool': tool, 'args': args, 'outputs': [f'output-{index}.dat']}
            for index, (tool, args) in enumerate(bridge.GEOMETRY_STEPS, 1)
        ]
        spec_data = {
            'name': 'tdx-integration',
            's2_geometry': {'run_id': 'tdx-integration', 'mode': 'produce'},
            'steps': steps,
        }
        (project / 'project.json').write_text(json.dumps(spec_data), encoding='utf-8')
        (project / 'fixture.in').write_text('local fixture only', encoding='utf-8')
        fake_bridge = types.SimpleNamespace(
            GEOMETRY_EXITS=bridge.GEOMETRY_EXITS,
            geometry_admit=lambda *_args: {'mode': 'produce', 'run_id': 'tdx-integration'},
        )
        completed_exec = subprocess.CompletedProcess([], 0, stdout='', stderr='')
        completed_ssh = subprocess.CompletedProcess([], 0, stdout=b'', stderr=b'')
        with patch.object(tcad, 'ROOT', root), \
             patch.object(tcad, 'geometry_module', return_value=fake_bridge), \
             patch.object(tcad, 'assert_no_active_run'), \
             patch.object(tcad, 'execute', return_value=completed_exec), \
             patch.object(tcad, 'remote', return_value=completed_exec), \
             patch.object(tcad.subprocess, 'run', return_value=completed_ssh), \
             patch.object(tcad, 'status_run', return_value={'status': 'RUNNING'}):
            tcad._run_project(
                {'remote_root': '/remote/root', 'tool_bin': '/opt/synopsys/bin'},
                ['ssh-fixture'], project, run_id='tdx-integration', detach=True,
            )
        return (root / 'local_runtime/runs/tdx-integration/run.sh').read_text(encoding='utf-8')

    def test_six_step_wrapper_preserves_tdx_exits_and_bridge_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.build_six_step_runner(Path(tmp))

        lines = runner.splitlines()
        step3 = next(i for i, line in enumerate(lines) if 'STEP 3:' in line)
        step4 = next(i for i, line in enumerate(lines) if 'STEP 4:' in line)
        step5 = next(i for i, line in enumerate(lines) if 'STEP 5:' in line)
        step6 = next(i for i, line in enumerate(lines) if 'STEP 6:' in line)
        prepare = next(i for i, line in enumerate(lines) if 'geometry_bridge.py prepare' in line)
        finalize = next(i for i, line in enumerate(lines) if 'geometry_bridge.py finalize' in line)
        map_meta = next(i for i, line in enumerate(lines) if '--canonical tdx-metadata-exit-code.txt' in line)
        map_convert = next(i for i, line in enumerate(lines) if '--canonical tdx-converter-exit-code.txt' in line)

        self.assertLess(step3, map_meta)
        self.assertLess(map_meta, step4)
        self.assertLess(step4, map_convert)
        self.assertLess(map_convert, step5)
        self.assertLess(step2_index(lines), prepare)
        self.assertLess(prepare, step3)
        self.assertLess(step5, finalize)
        self.assertLess(finalize, step6)
        self.assertIn('capture_native_step step-003-tdx tdx', '\n'.join(lines))
        self.assertIn('capture_native_step step-004-tdx tdx', '\n'.join(lines))
        self.assertIn('step-003-tdx-exit-code.txt', runner)
        self.assertIn('step-004-tdx-exit-code.txt', runner)
        self.assertIn('capture_native_step step-006-sdevice', runner)
        self.assertIn('sdevice --threads 1 --exit-on-failure device.cmd', runner)

    def test_tdx_identity_requires_exact_installation_and_elf(self):
        capture_lines = tcad.native_capture_shell_lines()
        start = next(i for i, line in enumerate(capture_lines) if line == 'def exact_native(pid, identity):')
        end = next(i for i in range(start, len(capture_lines)) if capture_lines[i] == '    return executable')
        namespace = {'os': os, 'Path': Path, 'tool': 'tdx', 'installation': '/opt/synopsys'}
        exec('\n'.join(capture_lines[start:end + 1]), namespace)
        exact_native = namespace['exact_native']
        identity = {'name': 'tdx'}
        executable = '/opt/synopsys/bin/tdx'

        def check(readlink_value, elf_header, installation='/opt/synopsys', name='tdx'):
            namespace['installation'] = installation
            with patch.object(os, 'readlink', return_value=readlink_value), \
                 patch('builtins.open', return_value=io.BytesIO(elf_header)):
                return exact_native(123, {'name': name})

        self.assertEqual(check(executable, b'\x7fELFpayload'), executable)
        self.assertIsNone(check('/other/bin/tdx', b'\x7fELFpayload'))
        self.assertIsNone(check(executable, b'not-elf'))
        self.assertIsNone(check(executable, b'\x7fELFpayload', installation='/wrong/root'))
        self.assertIsNone(check(executable, b'\x7fELFpayload', name='tdx-wrapper'))


def step2_index(lines):
    return next(i for i, line in enumerate(lines) if 'STEP 2:' in line)


if __name__ == '__main__':
    unittest.main()
