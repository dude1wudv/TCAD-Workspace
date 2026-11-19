"""Narrow binder-only regression probe; contains no response or label fixture."""
import importlib.util
from unittest.mock import patch
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT/'experiments/dram-see-v4/continuous/data'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_response_2d(row, plan):
    """Untrusted same-file stub: deliberately never called by this probe."""
    raise AssertionError('Binder probe must not invoke a purported scientific replay')


class LearningReplayerTrustBoundaryTests(unittest.TestCase):
    def test_plan_self_bound_same_name_stub_is_not_trusted_replay(self):
        learner = load(DATA/'learning_2d.py', 'learning_2d_replayer_boundary_test')
        source = Path(__file__).resolve()
        plan = {'qualification_replay_ref': {
            'path': str(source), 'sha256': learner.S.sha(source)}}
        with self.assertRaisesRegex(ValueError, 'trusted|canonical|approved'):
            learner._bound_replayer(plan, source.parent, verify_response_2d)

    def test_fit_entry_fails_closed_before_opening_labels_when_canonical_module_missing(self):
        learner = load(DATA/'learning_2d.py', 'learning_2d_missing_canonical_test')
        self.assertFalse(learner.QUALIFICATION_PATH.exists())
        plan = {'qualification_replay_ref': {
            'path': str(learner.QUALIFICATION_PATH.resolve()), 'sha256': '0'*64}}
        plan_path = Path(__file__).with_name('PLAN_NOT_READ.json')
        output = Path(__file__).with_name('MODEL_NOT_CREATED.json')
        self.assertFalse(output.exists())
        with patch.object(learner.S, 'read_json', return_value=plan), \
             patch.object(learner.S, 'verify_plan_files', return_value=[]), \
             patch.object(learner, '_read_rows', side_effect=AssertionError('response file must stay unopened')) as read_rows:
            with self.assertRaisesRegex(ValueError, 'Canonical trusted qualification_2d.py is not implemented/not connected'):
                learner.fit_registered(plan_path, {'training-id': 'LABEL_NOT_OPENED.json'}, 'alpha', output, None)
            read_rows.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
