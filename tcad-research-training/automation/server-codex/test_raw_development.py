"""Raw acquisition remains separate from admission for formal science."""
import tempfile
import unittest
from pathlib import Path

import runtime


class RawDevelopmentTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.r = object.__new__(runtime.Runtime)
        self.r.workspace = Path(tmp.name).resolve()
        self.r.intents = {}
        self.r.policy = {'scientific_gate': {}}
        self.r.profiles = {'tcad': {'cfg': {}}}
        self.r._input_cache = {}
        self.task = dict(id='raw-dev-a', project='local_runtime/raw-development/raw-dev-a', backend='tcad')
        self.project = self.r.workspace / self.task['project']
        self.project.mkdir(parents=True)
        (self.project / 'project.json').write_text('{"name":"test"}')
        (self.project / 'deck.cmd').write_text('sample deck')

    def test_no_admission_or_case_claim(self):
        a = self.r._scientific_admission(self.task)
        self.assertEqual(a['scope'], 'raw_development')
        self.assertFalse(a['training_eligible'] or a['statistics_eligible'])
        self.assertNotIn('case_id', a)
        self.assertFalse(self.r.intents)

    def test_formal_and_repair_paths_do_not_fall_back(self):
        for fields in ({'project': 'plans/formal-case'}, {'adopt_run_id': 'old'},
                       {'repair_of': 'old'}, {'wave_admission_sha256': '0'*64}, {'backend': 'geant4'},
                       {'id': 'r06-formal-case'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.r._scientific_admission(dict(self.task, **fields))

    def test_duplicate_or_changed_input_refused(self):
        original, comparison = self.r._inputs(self.task)
        for old in ({'input_digest': comparison}, {'input_sha256': original}, {'project': self.task['project']}):
            self.r.intents = {'old': old}
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, 'already has'):
                self.r._scientific_admission(self.task, original)
        self.r.intents = {}
        (self.project / 'deck.cmd').write_text('changed deck')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.r._scientific_admission(self.task, original)
