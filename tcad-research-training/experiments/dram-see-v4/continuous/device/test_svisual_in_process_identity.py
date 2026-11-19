"""Focused Tcl identity integration; no SVisual/native processes are launched."""
import csv
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import tkinter
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
spec = importlib.util.spec_from_file_location('visual_identity_patch', HERE / 'visual_patch.py')
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)
FROZEN = ROOT / 'local_runtime/dram-see-v4/continuous/device/mesh-continuation-r1/projects/20261017T134520Z-v4-continuous-b1-d3-r10/measure-geometry.tcl'
LIBRARY = ROOT / 'local_runtime/dram-see-v4/continuous/actual-usage/d3-r9-installed-tcl-sha256/sha256.tcl'


class SVisualIdentityTests(unittest.TestCase):
    def run_identity(self, folder, change=False, missing_provider=False):
        mesh = folder / 'mesh.tdr'
        mesh.write_bytes(b'UNIT_FIXTURE_NOT_NATIVE\0\xff\n')
        expected = hashlib.sha256(mesh.read_bytes()).hexdigest()
        helper = (HERE / 'tdx_hash_sha256.tcl').read_text(encoding='utf-8')
        old_path = '/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/lib/tcllib1.16/sha1/sha256.tcl'
        self.assertEqual(helper.count(old_path), 1)
        provider = folder / 'tdx_hash_sha256.tcl'
        provider.write_text(helper.replace(old_path, LIBRARY.as_posix()), encoding='utf-8')
        text = patcher.apply_in_process_identity(FROZEN.read_text(encoding='utf-8'))
        tcl = tkinter.Tcl()
        tcl.eval('rename exec original_exec; set forbidden_exec_calls 0; proc exec {args} {incr ::forbidden_exec_calls; error "External command forbidden in fixture"}')
        tcl.eval(text[:text.index('proc s2_inventory')])
        for name, value in [('s2_hash_provider_script', str(provider if not missing_provider else folder / 'missing.tcl')),
                            ('s2_mesh', mesh.as_posix()), ('s2_expected_sha', expected), ('s2_run_id', 'UNIT_FIXTURE_NOT_NATIVE')]:
            tcl.setvar(name, value)
        tcl.setvar('identity_path', (folder / 'identity.csv').as_posix())
        tcl.eval('set channel [open $identity_path {WRONLY CREAT EXCL}]; dict set s2_channels identity $channel; s2_csv $channel {phase path sha256 run_id command_status}')
        first = int(tcl.call('s2_identity', 'BEFORE'))
        if change:
            mesh.write_bytes(mesh.read_bytes() + b'changed')
        second = None if missing_provider else int(tcl.call('s2_identity', 'AFTER'))
        tcl.eval('close $channel')
        with (folder / 'identity.csv').open(newline='', encoding='utf-8') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(int(tcl.getvar('forbidden_exec_calls')), 0)
        return first, second, rows, int(tcl.getvar('s2_errors'))

    def in_folder(self, **kwargs):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory(prefix='UNIT_FIXTURE_NOT_NATIVE-') as tmp:
            try:
                folder = Path(tmp)
                os.chdir(folder)
                return self.run_identity(folder, **kwargs)
            finally:
                os.chdir(previous)

    def test_both_hashes_work_with_exec_disabled(self):
        before, after, rows, errors = self.in_folder()
        self.assertEqual((before, after, errors), (1, 1, 0))
        self.assertEqual([r['phase'] for r in rows], ['BEFORE', 'AFTER'])
        self.assertEqual([r['command_status'] for r in rows], ['OK', 'OK'])
        self.assertEqual(rows[0]['sha256'], rows[1]['sha256'])

    def test_changed_mesh_keeps_after_digest_and_rejects(self):
        before, after, rows, errors = self.in_folder(change=True)
        self.assertEqual((before, after, errors), (1, 0, 1))
        self.assertEqual(rows[-1]['command_status'], 'ERROR')
        self.assertNotEqual(rows[0]['sha256'], rows[1]['sha256'])

    def test_provider_load_failure_is_not_a_successful_identity(self):
        before, after, rows, errors = self.in_folder(missing_provider=True)
        self.assertEqual((before, after, errors), (0, None, 1))
        self.assertEqual(rows[0]['command_status'], 'ERROR')
        self.assertEqual(rows[0]['sha256'], '')


if __name__ == '__main__':
    unittest.main()
