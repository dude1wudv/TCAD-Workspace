"""Targeted software checks for current authorization migration; no native work."""
import ast
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import geometry_bridge as bridge
import mesh_resource_guard as guard
import prepare

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CHECKS = ROOT / 'local_runtime/dram-see-v4/continuous/device/checks'
REFERENCE = ROOT / 'local_runtime/dram-see-v4/continuous/device/projects/20261017T041900Z-v4-continuous-b1-d2-r1'


class CurrentContext(unittest.TestCase):
    def setUp(self):
        CHECKS.mkdir(parents=True, exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(prefix='admission-inputs-', dir=str(CHECKS)))

    def copied(self):
        target = self.folder / 'project'
        shutil.copytree(str(REFERENCE), str(target))
        return target

    def admit(self, target):
        context = json.loads((target / 'execution-context.json').read_text(encoding='utf-8'))
        return bridge.geometry_admit(target, json.loads((target / 'project.json').read_text(encoding='utf-8')),
                                     context['expected_runner_sha256'])

    def test_d2_without_budget_forecast_or_release(self):
        self.assertFalse((REFERENCE / 'cell_msh.tdr').exists())
        self.assertFalse(any(REFERENCE.glob('*release*')))
        self.assertFalse(any(REFERENCE.glob('*budget*')))
        self.assertEqual(self.admit(REFERENCE)['role_id'], 'B1-D2')

    def test_changed_payload_rejected(self):
        target = self.copied()
        with (target / 'device.cmd').open('a', encoding='utf-8') as f:
            f.write('\n* deliberate software test mutation\n')
        with self.assertRaisesRegex(ValueError, 'Frozen input changed: device.cmd'):
            self.admit(target)

    def test_synthetic_marker_rejected(self):
        target = self.copied()
        (target / 'SYNTHETIC_NOT_NATIVE').write_text('SOFTWARE CHECK ONLY', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Synthetic cannot be submitted'):
            self.admit(target)

    def test_wrong_runner_rejected(self):
        target = self.copied()
        with self.assertRaisesRegex(ValueError, 'Original runner version differs'):
            bridge.geometry_admit(target, json.loads((target / 'project.json').read_text(encoding='utf-8')), '0'*64)

    def test_resource_observations_have_no_old_quota(self):
        policy = dict(schema='dram-see-v4-actual-resource-policy-r1')
        self.assertTrue(guard.evaluate(policy, 1024, 1024)['passed'])
        self.assertFalse(guard.evaluate(policy, 0, 1024)['passed'])
        self.assertFalse(guard.evaluate(policy, 1024, 0)['passed'])
        self.assertFalse(guard.evaluate(policy, 1024, 1024)['capacity_prediction'])

    def test_original_failed_exit_bytes_preserved(self):
        raw = b'37\n'
        (self.folder / 'step-001-sde-exit-code.txt').write_bytes(raw)
        self.assertEqual(bridge.geometry_record_exit(self.folder, 'step-001-sde-exit-code.txt', 'sde-exit-code.txt'), 37)
        self.assertEqual((self.folder / 'sde-exit-code.txt').read_bytes(), raw)
        with self.assertRaisesRegex(ValueError, 'Original native exit is nonzero'):
            bridge.geometry_exit_sources(self.folder, complete=False)

    def test_a0_requires_real_d3_before_output_creation(self):
        target = self.folder / 'a0-no-d3'
        with self.assertRaisesRegex(ValueError, 'A0 requires --d3-source'):
            prepare.prepare('B1-A0-main-b0', 'software-test-no-d3', ROOT / 'scripts/tcad.py', output=target)
        self.assertFalse(target.exists())

    def test_numerical_comparisons_and_observation_checks_unchanged(self):
        def functions(path):
            return {n.name: ast.dump(n, include_attributes=False) for n in
                    ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.FunctionDef)}
        original = functions(prepare.CANDIDATE / 'roles/B1-D2/evaluate.py')
        current = functions(HERE / 'evaluate.py')
        # Contact bounds moved to the mandatory mesh measurements after native
        # r3. Their source/coverage and unchanged tolerance have focused checks.
        for name in ('verify_context', 'raw_number', 'csv_rows', 'close', 'bounds'):
            self.assertEqual(current[name], original[name], name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
