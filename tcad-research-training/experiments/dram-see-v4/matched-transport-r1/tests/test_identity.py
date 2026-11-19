"""Synthetic receipt/gate identity counterexamples; no native-run claims."""
from contextlib import ExitStack
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
def module(name, filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result
a=module('matched_identity_audit','audit_matched.py')
c=module('matched_identity_control','control.py')
def raw(value):
    return (json.dumps(value,indent=2)+'\n').encode()
def digest(value):
    return hashlib.sha256(value).hexdigest()


class ReceiptIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='offline-',dir=Path(__file__).parent)
        self.root=Path(self.tmp.name).resolve()
        self.contract=json.loads((HERE/'matched-contract.json').read_text())
        self.request=copy.deepcopy(self.contract['requests'][0]);self.label=self.request['label']
        self.folder=self.root/'local_runtime/dram-see-v4/matched-transport-r1/runs'/self.label
        self.folder.mkdir(parents=True)
        self.operation_folder=self.root/'local_runtime/dram-see-v4/transport-probe/operations'/self.label
        self.operation_folder.mkdir(parents=True)
        target=self.root/self.contract['geometry_path'];target.parent.mkdir(parents=True)
        geometry=(HERE.parent/'source-interface-3d-r1/geometry-contract.json').read_bytes()
        target.write_bytes(geometry)
        required={'task.sh','run.sh','exit-code.txt','execution.log','affinity.txt','metadata.json','status.json',
            'constructors.csv','processes.csv','hadronic-models.csv','materials.csv','elements.csv','cuts.csv',
            'events.csv','tracks.csv','steps.csv','birth-links.csv','status-history.jsonl','particles.csv',
            'material-energy.csv','geometry-built.csv','timings.csv','geometry.hh','geometry-contract.json','matched-contract.json'}
        contents={name:b'synthetic fixture, not native output\n' for name in required}
        contents.update({'request.json':raw(self.request),'matched-contract.json':(HERE/'matched-contract.json').read_bytes(),
                         'geometry-contract.json':geometry,'exit-code.txt':b'0\n'})
        for name,data in contents.items():(self.folder/name).write_bytes(data)
        inputs={name:digest(contents[name]) for name in ['task.sh','request.json','matched-contract.json','geometry-contract.json','geometry.hh']}
        outputs={name:digest(data) for name,data in contents.items()}
        self.archive=self.operation_folder/'results.tar'
        with tarfile.open(self.archive,'w') as archive:
            for name,data in contents.items():
                entry=tarfile.TarInfo(name);entry.size=len(data);archive.addfile(entry,io.BytesIO(data))
        self.operation=dict(schema='dram-see-v4-transport-operation-v1',label=self.label,
            ssh_exit_code=0,remote_exit_code=0,collection_exit_code=0,archive_sha256=a.sha(self.archive),input_sha256=inputs)
        self.record=dict(schema='dram-see-v4-matched-run-r1',run_id=self.label,mode='init',arm='H',
            runner_exit_code=0,remote_exit_code=0,collection_exit_code=0,request=self.request,input_sha256=inputs,output_sha256=outputs,
            raw_archive={'path':self.archive.relative_to(self.root).as_posix(),'sha256':a.sha(self.archive)},
            operation_evidence={'path':(self.operation_folder/'operation.json').relative_to(self.root).as_posix()})

    def tearDown(self):self.tmp.cleanup()

    def check(self,folder=None):
        operation=self.operation_folder/'operation.json';operation.write_bytes(raw(self.operation))
        self.record['operation_evidence']['sha256']=a.sha(operation)
        (self.folder/'record.json').write_bytes(raw(self.record))
        report={}
        with patch.object(a,'ROOT',self.root):
            result=a._receipt(folder or self.folder,report)
        return result,report

    def test_valid_receipt_binds_report_and_frozen_request(self):
        record,report=self.check()
        self.assertEqual(record['run_id'],self.request['label'])
        self.assertEqual(report['run_id'],self.request['label'])
        self.assertEqual(report['request'],self.request)

    def test_altered_run_id_rejected(self):
        self.record['run_id']='wrong-run-id'
        with self.assertRaisesRegex(ValueError,'Run identity differs'):self.check()

    def test_missing_run_id_rejected(self):
        self.record.pop('run_id')
        with self.assertRaisesRegex(ValueError,'Run identity differs'):self.check()

    def test_missing_request_label_rejected(self):
        self.record['request'].pop('label')
        with self.assertRaisesRegex(ValueError,'request label'):self.check()

    def test_wrong_folder_rejected_even_with_correct_record_id(self):
        other=self.folder.with_name('wrong-folder');self.folder.rename(other);self.folder=other
        with self.assertRaisesRegex(ValueError,'Run path differs'):self.check()

    def test_wrong_operation_label_rejected(self):
        self.operation['label']='wrong-operation'
        with self.assertRaisesRegex(ValueError,'operation label differs'):self.check()

    def test_missing_operation_label_rejected(self):
        self.operation.pop('label')
        with self.assertRaisesRegex(ValueError,'operation label differs'):self.check()

    def test_wrong_operation_path_rejected(self):
        self.record['operation_evidence']['path']='operation.json'
        with self.assertRaisesRegex(ValueError,'Operation path differs'):self.check()

    def test_wrong_archive_path_rejected(self):
        self.record['raw_archive']['path']='results.tar'
        with self.assertRaisesRegex(ValueError,'Archive path differs'):self.check()


class GateIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='offline-',dir=Path(__file__).parent)
        self.root=Path(self.tmp.name).resolve();self.runtime=self.root/'local_runtime/dram-see-v4/matched-transport-r1'
        self.contract=json.loads((HERE/'matched-contract.json').read_text())
        self.stack=ExitStack()
        self.stack.enter_context(patch.object(c,'ROOT',self.root))
        self.stack.enter_context(patch.object(c,'RUNTIME',self.runtime))
        self.stack.enter_context(patch.object(c,'contract',return_value=self.contract))
        for request in self.contract['requests'][:2]:
            label=request['label'];rp=self.runtime/'runs'/label/'record.json';ap=self.runtime/'audits'/label/'audit.json'
            rp.parent.mkdir(parents=True);ap.parent.mkdir(parents=True)
            rp.write_bytes(raw(dict(run_id=label,request=request,mode='init')))
            ap.write_bytes(raw(dict(run_id=label,request=request,run_dir=str(rp.parent),mode='init',passed=True,
                                    record_sha256=c.sha(rp),audit_code_sha256=c.sha(HERE/'audit_matched.py'))))

    def tearDown(self):self.stack.close();self.tmp.cleanup()

    def mutate(self,kind,key,value,remove=False):
        label=self.contract['requests'][0]['label']
        path=self.runtime/('runs' if kind=='record' else 'audits')/label/(kind+'.json')
        data=c.read(path)
        if remove:data.pop(key)
        else:data[key]=value
        path.write_bytes(raw(data))
        if kind=='record':
            ap=self.runtime/'audits'/label/'audit.json';audit=c.read(ap);audit['record_sha256']=c.sha(path);ap.write_bytes(raw(audit))

    def test_valid_create_and_use_initialization_gate(self):
        c.gate_initialization();c.require_initialization_gate()

    def test_gate_creation_rejects_wrong_record_id(self):
        self.mutate('record','run_id','wrong')
        with self.assertRaisesRegex(ValueError,'identity differs'):c.gate_initialization()

    def test_gate_creation_rejects_wrong_audit_id(self):
        self.mutate('audit','run_id','wrong')
        with self.assertRaisesRegex(ValueError,'identity differs'):c.gate_initialization()

    def test_gate_creation_rejects_missing_audit_id(self):
        self.mutate('audit','run_id',None,True)
        with self.assertRaisesRegex(ValueError,'identity differs'):c.gate_initialization()

    def test_gate_creation_rejects_wrong_audit_run_dir(self):
        self.mutate('audit','run_dir',str(self.runtime/'runs'/'other'))
        with self.assertRaisesRegex(ValueError,'identity differs'):c.gate_initialization()

    def test_gate_use_rechecks_id_even_if_hashes_updated(self):
        gate_path=c.gate_initialization();self.mutate('audit','run_id','wrong')
        gate=c.read(gate_path);item=gate['evidence'][0];item['audit_sha256']=c.sha(self.root/item['audit_path'])
        gate_path.write_bytes(raw(gate))
        with self.assertRaisesRegex(ValueError,'identity differs'):c.require_initialization_gate()

    def test_gate_use_rejects_missing_label(self):
        path=c.gate_initialization();gate=c.read(path);gate['evidence'][0].pop('request_label');path.write_bytes(raw(gate))
        with self.assertRaisesRegex(ValueError,'identity differs'):c.require_initialization_gate()

    def test_gate_use_rejects_relocated_audit_path(self):
        path=c.gate_initialization();gate=c.read(path);gate['evidence'][0]['audit_path']='elsewhere/audit.json';path.write_bytes(raw(gate))
        with self.assertRaisesRegex(ValueError,'path differs'):c.require_initialization_gate()

    def test_gate_use_rejects_missing_one_init(self):
        path=c.gate_initialization();gate=c.read(path);gate['evidence'].pop();path.write_bytes(raw(gate))
        with self.assertRaisesRegex(ValueError,'both frozen'):c.require_initialization_gate()


if __name__=='__main__':unittest.main()
