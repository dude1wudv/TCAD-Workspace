"""Focused identity-boundary checks for qualification_2d; UNIT files only."""
import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / 'experiments/dram-see-v4/continuous/data/qualification_2d.py'
EVIDENCE = ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/qualification-implementation-r1'
UNIT_PLAN = EVIDENCE / 'check-r1/UNIT-alpha-plan.json'
spec = importlib.util.spec_from_file_location('qualification_2d_identity_boundary_subject', MODULE)
Q = importlib.util.module_from_spec(spec)
exec(compile(MODULE.read_bytes(), str(MODULE), 'exec'), Q.__dict__)


class QualificationIdentityBoundary(unittest.TestCase):
    def test_mixed_directory_triple_is_rejected(self):
        """A valid set of hashes from another folder cannot stand in for the named run."""
        with tempfile.TemporaryDirectory(prefix='UNIT-identity-', dir=str(EVIDENCE)) as temp:
            base = Path(temp)
            directories = [base / 'run-a', base / 'run-b']
            for directory in directories:
                directory.mkdir()
                for name in Q.RUN_FILES:
                    (directory / name).write_bytes(('UNIT_NOT_NATIVE:' + name).encode('ascii'))
            ref_b = Q.run_reference(directories[1])
            mixed = dict(directory=str(directories[0]), files=ref_b['files'])
            replay = Q.Replay()
            result = replay.artifact('main.signal', mixed, base)
            self.assertIsNone(result)
            self.assertEqual(replay.artifacts['main.signal']['status'], 'invalid')
            self.assertTrue(any('same original directory and exact files' in item['message'] for item in replay.errors))

    def test_caller_plan_object_must_match_hashed_plan(self):
        """A modified in-memory plan cannot be paired with the immutable plan reference."""
        self.assertTrue(UNIT_PLAN.is_file(), 'author UNIT plan fixture is required')
        ref = Q.immutable_ref(UNIT_PLAN)
        plan = Q.read_json(UNIT_PLAN)
        changed = copy.deepcopy(plan)
        changed['design_id'] = 'UNIT_MUTATED_CALLER_PLAN'
        with self.assertRaisesRegex(ValueError, 'immutable plan content differs'):
            Q._assemble(ref, 0, None, given_plan=changed)


if __name__ == '__main__':
    unittest.main()
