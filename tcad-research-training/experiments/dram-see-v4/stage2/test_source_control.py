"""Fail-closed dispatch and cross-revision budget checks; no remote calls."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('source_control',Path(__file__).with_name('source_control.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SourceControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.patch=patch.object(m,'RUNTIME_BASE',self.base);self.patch.start()
    def tearDown(self):
        self.patch.stop();self.temp.cleanup()
    def record(self,revision='r2',label='done',**changes):
        p=self.base/f'source-interface-{revision}/launches/{label}/execution.json'
        p.parent.mkdir(parents=True)
        record=dict(state='RUNNER_EXITED',runner_exit_code=0,ssh_exit_code=0,
                    runner_manifest_state='COLLECTED',identity=['A1',1,'base'])
        record.update(changes);p.write_text(json.dumps(record));return p
    def test_same_revision_completed_request_rejected(self):
        with self.assertRaisesRegex(ValueError,'Completed frozen'):
            m.validate_history([self.record()],['A1',1,'base'],'r2')
    def test_new_revision_preserves_previous_budget(self):
        p=self.record();m.validate_history([p],['A1',1,'base'],'r3')
    def test_budget_sums_both_revisions(self):
        previous=[self.record('r2' if i<2 else 'r3',str(i)) for i in range(19)]
        with self.assertRaisesRegex(ValueError,'19 new solver invocations'):
            m.validate_history(previous,['A4',1,'base'],'r3')
    def test_unknown_local_state_rejected(self):
        p=self.record(state='RUNNING',runner_exit_code=None)
        with self.assertRaisesRegex(ValueError,'state unknown'):
            m.validate_history([p],['A1',1,'base'],'r3')
    def test_unknown_remote_state_rejected(self):
        p=self.record(ssh_exit_code=None)
        with self.assertRaisesRegex(ValueError,'state unknown'):
            m.validate_history([p],['A1',1,'base'],'r3')
    def test_mismatched_label_revision_rejected(self):
        with self.assertRaisesRegex(ValueError,'approved revision'):
            m.resolve_request(self.base/'source-interface-r3/inputs/a1','r2-a1')
    def test_non_input_and_unknown_revision_rejected(self):
        for path,label in [('source-interface-r3/a1','r3-a1'),('source-interface-r5/inputs/a1','r5-a1')]:
            with self.assertRaisesRegex(ValueError,'approved revision'):
                m.resolve_request(self.base/path,label)
    def test_valid_r3_resolves_without_making_files(self):
        revision,runtime,project=m.resolve_request(self.base/'source-interface-r3/inputs/a1','r3-a1')
        self.assertEqual(revision,'r3');self.assertFalse(project.exists())

if __name__=='__main__':unittest.main()
