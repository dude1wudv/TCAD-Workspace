"""Negative dispatch tests; no SSH or solver is called."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('control',Path(__file__).with_name('witness_control.py'))
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.request=dict(label='witness-test-r1',stage='initialization',mode='init',arm='H',seed=1,event_count=0)
        self.patch=patch.multiple(m,HERE=self.base/'contract',RUNTIME=self.base/'runtime')
        self.patch.start()
        m.write(m.HERE/'witness-contract.json',{'requests':[self.request]})
    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()
    def test_unknown_request_rejected_before_remote(self):
        with self.assertRaisesRegex(ValueError,'outside frozen'):
            m.prepare('witness-other-r1',self.base)
    def test_unknown_previous_state_blocks(self):
        op=m.RUNTIME/'operations/witness-test-r1'
        m.write(op/'operation.json',{'state':'REQUIRES_READ_ONLY_RECONCILIATION','remote_exit_code':None})
        m.write(m.RUNTIME/'inputs/witness-test-r1/request.json',self.request)
        with self.assertRaisesRegex(ValueError,'state unknown'):
            m.prepare(self.request['label'],self.base,attempt='witness-test-r2')
    def test_completed_request_blocks_repeat(self):
        op=m.RUNTIME/'operations/witness-test-r1'
        m.write(op/'operation.json',{'state':'COLLECTED_PENDING_AUDIT','remote_exit_code':0})
        m.write(op/'collected/request.json',self.request)
        with self.assertRaisesRegex(ValueError,'Completed request'):
            m.prepare(self.request['label'],self.base,attempt='witness-test-r2')
    def test_missing_pilot_gate_blocks_fixed(self):
        with self.assertRaises(FileNotFoundError): m.require_gate('pilot')
    def test_nonzero_or_unknown_exit_not_complete(self):
        op=self.base/'bad-build'
        m.write(op/'operation.json',{'state':'COLLECTED_PENDING_AUDIT','ssh_exit_code':0,'remote_exit_code':None,'collection_exit_code':0})
        with self.assertRaisesRegex(ValueError,'not known successful'): m.assert_operation_complete(op)
    def test_collect_unknown_state_rejected(self):
        op=m.RUNTIME/'operations/witness-test-r1'
        m.write(op/'operation.json',{'state':'RUNNING'})
        with self.assertRaisesRegex(ValueError,'not terminal'): m.collect('witness-test-r1')
    def test_immutable_file(self):
        p=self.base/'immutable.json'; m.write(p,{'x':1})
        with self.assertRaises(FileExistsError): m.write(p,{'x':2})
        self.assertEqual(json.loads(p.read_text()),{'x':1})

if __name__=='__main__': unittest.main()
