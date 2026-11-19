"""Only the new operation receipt branch; fixtures are not research results."""
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location('proton_prepare',ROOT/'experiments/dram-see-v4/continuous/proton/prepare.py')
prepare=importlib.util.module_from_spec(spec);spec.loader.exec_module(prepare)


class ReceiptTests(unittest.TestCase):
    def fixture(self,root):
        operation=root/'synthetic-receipt-unit';folder=operation/'collected';folder.mkdir(parents=True)
        for name,raw in {'task.sh':b'exit 0\n','exit-code.txt':b'0\n','operation-task-exit-code.txt':b'0\n','output.dat':b'fixture only\n'}.items():
            (folder/name).write_bytes(raw)
        with tarfile.open(operation/'results.tar','w') as archive:
            for p in folder.iterdir():archive.add(p,arcname=p.name,recursive=False)
        receipt=dict(schema='dram-see-v4-transport-operation-v2',label=operation.name,state='COLLECTED_PENDING_AUDIT',collection_verified=True,origin='native_pipeline',synthetic=False,ssh_exit_code=255,remote_exit_code=0,operation_task_exit_code=0,collection_exit_code=0,input_sha256={'task.sh':prepare.sha(folder/'task.sh')},archive_sha256=prepare.sha(operation/'results.tar'))
        (operation/'operation.json').write_text(json.dumps(receipt))
        return operation,receipt

    def test_recovered_v2_retains_raw_ssh_255(self):
        with tempfile.TemporaryDirectory() as d:
            operation,receipt=self.fixture(Path(d))
            _,result=prepare.complete_operation(operation,('output.dat',))
            self.assertEqual(result['ssh_exit_code'],255)

    def test_v2_requires_complete_collection(self):
        with tempfile.TemporaryDirectory() as d:
            operation,receipt=self.fixture(Path(d));receipt['collection_verified']=False
            (operation/'operation.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'verified original'):prepare.complete_operation(operation)

    def test_legacy_ssh_255_still_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            operation,receipt=self.fixture(Path(d));receipt['schema']='dram-see-v4-transport-operation-v1'
            (operation/'operation.json').write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError,'actual successful'):prepare.complete_operation(operation)


if __name__=='__main__':unittest.main()
