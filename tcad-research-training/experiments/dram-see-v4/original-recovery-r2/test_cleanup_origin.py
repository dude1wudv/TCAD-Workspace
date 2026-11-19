"""Offline gate-origin checks; never prepare a cleanup plan or execute a shell."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
REVIEW=ROOT/'local_runtime/dram-see-v4/interface-completion-r1/cleanup-recovery-review-20261014'
spec=importlib.util.spec_from_file_location('_cleanup_origin_test',HERE/'cleanup_plan.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
ORIGINAL_SHA='bc0a76ff03dc0cc6eee9229dc615b23509c4ef6117ec204abfd79eace9a96a1a'
RECOVERY_SHA='29314dd3de9c8ef56d027a9325719ba2ad85a89094e0272433d46ef914cd058e'
ROLE='a6-b1-time'


class GateOrigin(unittest.TestCase):
    def setUp(self):
        REVIEW.mkdir(parents=True,exist_ok=True)
        self.temporary=tempfile.TemporaryDirectory(prefix='gate-fixture-',dir=REVIEW)
        self.addCleanup(self.temporary.cleanup)
        self.state=Path(self.temporary.name)
        self.gate=copy.deepcopy(c.read(c.STATE/'gates'/(ROLE+'.json')))
        self.path=self.state/'gates'/(ROLE+'.json')
        self.path.parent.mkdir(parents=True)
        self.write()
        self.original_read=c.read
        self.original_sha=c.sha

    def write(self):
        self.path.write_text(json.dumps(self.gate,indent=2)+'\n',encoding='utf-8')

    def check(self):
        with patch.object(c,'STATE',self.state):return c.gate_record(ROLE)

    def test_real_original_gate_origin_still_passes(self):
        _,gate=c.gate_record('a4-b1-main')
        self.assertEqual(gate['acceptance_code_sha256'],ORIGINAL_SHA)

    def test_real_recovery_gate_passes_without_rewriting_any_evidence(self):
        path=c.STATE/'gates'/(ROLE+'.json');before=path.read_bytes()
        _,gate=c.gate_record(ROLE)
        self.assertEqual(gate['acceptance_code_sha256'],RECOVERY_SHA)
        self.assertEqual(path.read_bytes(),before)

    def test_unknown_origin_rejected(self):
        self.gate['acceptance_code_sha256']='0'*64;self.write()
        with self.assertRaisesRegex(ValueError,'explicit frozen allowlist'):self.check()

    def test_missing_origin_rejected(self):
        self.gate.pop('acceptance_code_sha256');self.write()
        with self.assertRaisesRegex(ValueError,'explicit frozen allowlist'):self.check()

    def test_original_source_bytes_changed_rejected(self):
        self.gate['acceptance_code_sha256']=ORIGINAL_SHA;self.write()
        target=c.HERE/'acceptance.py'
        with patch.object(c,'sha',side_effect=lambda p:'0'*64 if Path(p)==target else self.original_sha(p)):
            with self.assertRaisesRegex(ValueError,'Original final acceptance code changed'):self.check()

    def test_recovery_source_bytes_changed_rejected(self):
        target=c.HERE.parent/'original-recovery-r1/acceptance.py'
        with patch.object(c,'sha',side_effect=lambda p:'0'*64 if Path(p)==target else self.original_sha(p)):
            with self.assertRaisesRegex(ValueError,'Recovered final acceptance code changed'):self.check()

    def test_failed_recovery_release_blocks_gate(self):
        fake=SimpleNamespace(check_release=Mock(side_effect=ValueError('Recovery implementation changed')))
        fake_spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda obj:None))
        with patch.object(c.importlib.util,'spec_from_file_location',return_value=fake_spec), \
             patch.object(c.importlib.util,'module_from_spec',return_value=fake):
            with self.assertRaisesRegex(ValueError,'Recovery implementation changed'):self.check()
        fake.check_release.assert_called_once_with()

    def test_recovery_release_must_bind_exact_acceptance_file(self):
        release=c.HERE.parent/'original-recovery-r1/release.json'
        def changed(path):
            value=self.original_read(path)
            if Path(path)==release:
                value['files_sha256'][c.ref(release.parent/'acceptance.py')]='0'*64
            return value
        with patch.object(c,'read',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'not bound by its frozen release'):self.check()

    def test_recovery_release_must_still_be_passed(self):
        release=c.HERE.parent/'original-recovery-r1/release.json'
        def changed(path):
            value=self.original_read(path)
            if Path(path)==release:value['passed']=False
            return value
        with patch.object(c,'read',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'not bound by its frozen release'):self.check()

    def test_foreign_campaign_rejected_before_release(self):
        self.gate['campaign_sha256']='0'*64;self.write()
        with patch.object(c.importlib.util,'spec_from_file_location') as load:
            with self.assertRaisesRegex(ValueError,'Role gate campaign changed'):self.check()
        load.assert_not_called()

    def test_failed_gate_rejected(self):
        self.gate['passed']=False;self.write()
        with self.assertRaisesRegex(ValueError,'Final role gate did not pass'):self.check()

    def test_changed_bound_evidence_still_rejected(self):
        self.gate['evidence'][0]['sha256']='0'*64;self.write()
        with self.assertRaisesRegex(ValueError,'Gate evidence hash differs'):self.check()

    def test_empty_evidence_still_rejected(self):
        self.gate['evidence']=[];self.write()
        with self.assertRaisesRegex(ValueError,'has no evidence'):self.check()


class FrozenCleanupBoundaries(unittest.TestCase):
    def test_original_cleanup_hash_unchanged(self):
        self.assertEqual(hashlib.sha256((c.HERE/'cleanup_plan.py').read_bytes()).hexdigest(),
                         '56354a08900f6361fd7bcc408f534eb17041876d66f68f26a659c88faa49575d')

    def test_every_original_function_except_origin_gate_has_identical_ast(self):
        def funcs(path):
            tree=ast.parse(path.read_text(encoding='utf-8'))
            return {n.name:ast.dump(n,include_attributes=False) for n in tree.body
                    if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name!='gate_record'}
        self.assertEqual(funcs(HERE/'cleanup_plan.py'),funcs(c.HERE/'cleanup_plan.py'))
        # This covers Archive, local_path, operation_success, remote_paths,
        # render_script, prepare and every other original function unchanged.

    def test_contract_and_state_remain_original(self):
        self.assertEqual(c.HERE,ROOT/'experiments/dram-see-v4/interface-completion-r1')
        self.assertEqual(c.CAMPAIGN,c.HERE/'campaign.json')
        self.assertEqual(c.STATE,ROOT/'local_runtime/dram-see-v4/interface-completion-r1')


if __name__=='__main__':unittest.main()
