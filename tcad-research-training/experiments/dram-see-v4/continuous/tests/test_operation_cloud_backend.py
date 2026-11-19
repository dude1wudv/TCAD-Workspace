"""SOFTWARE_FIXTURE_NOT_NATIVE: existing operation adapter, mocked transport only."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[4]
PREPARATION=ROOT/'local_runtime/cloud-benchmark/geant4-preparation'


def module():
    spec=importlib.util.spec_from_file_location('cloud_operation_test',ROOT/'experiments/dram-see-v4/transport-probe/operation.py')
    op=importlib.util.module_from_spec(spec);spec.loader.exec_module(op)
    return op


class CloudOperationTests(unittest.TestCase):
    def setUp(self):
        PREPARATION.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=PREPARATION,prefix='SOFTWARE_FIXTURE-')
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.op=module()
        self.cfg=dict(backend='ssh-runtime',ssh_target='tcad-cloud',
            runtime_entry='/srv/tcad-migration/minimal/scripts/enter-runtime.sh',
            remote_root='/home/tcad/research-training',
            tool_bin='/usr/synopsys/sentaurus/W-2024.09/bin',local_state_root=str(self.base/'state'))
        self.profile=self.base/'connection.json';self.profile.write_text(json.dumps(self.cfg))
        self.tcad=self.op.load_tcad(self.profile)
        self.cfg,self.ssh,_=self.tcad.connection()
        self.inputs=self.base/'inputs';self.inputs.mkdir()
        (self.inputs/'task.sh').write_text('# SOFTWARE_FIXTURE_NOT_NATIVE\n')
        self.op.CLOUD_INPUTS_ROOT=self.inputs
        self.op.DEFAULT_RUNTIME=self.base/'legacy'

    def test_cloud_config_binds_separate_ledger_and_allowed_input_root(self):
        self.assertEqual(self.op.RUNTIME,self.base/'state/dram-see-v4/transport-probe')
        self.assertEqual(self.op.connection_identity(self.cfg),self.tcad.connection_identity(self.cfg))
        self.assertIn('StrictHostKeyChecking=yes',self.ssh)
        self.op.load_tcad(self.profile)
        self.assertEqual(self.op.CLOUD_INPUTS_ROOT,(PREPARATION/'inputs').resolve())

    def test_default_module_returns_to_vm_without_reading_config_or_network(self):
        default=self.op.load_tcad()
        self.assertIsNone(self.op.CLOUD_INPUTS_ROOT)
        self.assertEqual(self.op.RUNTIME,self.op.DEFAULT_RUNTIME)
        self.assertIsNone(default.STATE_ROOT)

    def test_wrong_backend_identity_rejected_even_when_remote_path_matches(self):
        folder=self.op.operation_folder('new');folder.mkdir(parents=True)
        evidence=dict(label='new',remote_directory=self.cfg['remote_root']+'/dram-see-v4/transport-probe/operations/new',
                      connection_identity=self.op.connection_identity(self.cfg))
        (folder/'operation.json').write_text(json.dumps(evidence))
        self.op.read_record(self.cfg,'new')
        for cfg in [dict(self.cfg,ssh_target='another-cloud'),dict(remote_root=self.cfg['remote_root'])]:
            with self.assertRaisesRegex(ValueError,'different connection'):
                self.op.read_record(cfg,'new')

    def test_historical_vm_label_cannot_be_launched_as_cloud(self):
        (self.op.DEFAULT_RUNTIME/'operations/old').mkdir(parents=True)
        with patch.object(self.tcad,'remote',side_effect=AssertionError('unexpected network')):
            with self.assertRaisesRegex(ValueError,'Historical VM operation label'):
                self.op._run_operation(self.tcad,self.cfg,self.ssh,'old',self.inputs,None,True)

    def test_cloud_inputs_outside_exact_root_rejected(self):
        other=self.base/'other';other.mkdir();(other/'task.sh').write_text('fixture')
        with self.assertRaisesRegex(ValueError,'explicit backend input root'):
            self.op._run_operation(self.tcad,self.cfg,self.ssh,'new',other,None,True)

    def test_cli_connection_reaches_each_existing_entrypoint(self):
        for argv,name in [(['new',str(self.inputs),'--detach'],'run'),(['status','new','--json'],'status'),(['collect','new','--json'],'collect')]:
            with self.subTest(name=name),patch.object(self.op,name,return_value=0 if name=='run' else {'status':'FIXTURE'}) as call:
                self.op.main(['--connection',str(self.profile)]+argv)
            self.assertEqual(call.call_args.kwargs['connection'],self.profile)

    def test_public_entries_select_connection_and_keep_original_owner(self):
        for name,target in [('status','status_operation'),('collect','collect_operation')]:
            with self.subTest(name=name),patch.object(self.op,'load_tcad',return_value=self.tcad) as load,patch.object(self.tcad,'original_ownership',return_value=nullcontext()) as owner,patch.object(self.op,target,return_value={'status':'FIXTURE'}) as command:
                getattr(self.op,name)('new',connection=self.profile)
            load.assert_called_once_with(self.profile)
            owner.assert_called_once()
            command.assert_called_once_with(self.tcad,self.cfg,self.ssh,'new')

    def test_launch_uses_same_chroot_as_staging_and_keeps_locks_and_affinity(self):
        staged=[]
        def remote(ssh,script,**kwargs):
            self.assertIs(ssh,self.ssh)
            self.assertIn(self.cfg['runtime_entry'],self.tcad.remote_argv(ssh,script)[-1])
            if 'stdin' in kwargs:staged.append(kwargs['stdin'].read())
            return subprocess.CompletedProcess([],0)
        with patch.object(self.op,'assert_no_outstanding_operation') as admission,patch.object(self.tcad,'remote',side_effect=remote),patch.object(self.op.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as launch,patch.object(self.op,'status_operation',return_value={'status':'RUNNING'}):
            result=self.op._run_operation(self.tcad,self.cfg,self.ssh,'new',self.inputs,None,True)
        admission.assert_called_once_with(self.tcad,self.cfg,self.ssh)
        self.assertEqual(result,{'status':'RUNNING'})
        self.assertEqual(len(staged),1)
        self.assertIn(self.cfg['runtime_entry'],launch.call_args.args[0][-1])
        folder=self.op.operation_folder('new');record=json.loads((folder/'operation.json').read_text())
        self.assertEqual(record['connection_identity'],self.tcad.connection_identity(self.cfg))
        script=(folder/'run.sh').read_text()
        self.assertIn('flock -n 9',script)
        self.assertIn('taskset -pc "$cpu" $$',script)
        self.assertIn('OMP_NUM_THREADS=1',script)
        self.assertNotIn('sdevice -v',script)
        self.assertFalse(record['capture_svisual_requested'])

    def test_same_cloud_label_only_status_never_relaunch(self):
        self.op.operation_folder('new').mkdir(parents=True)
        with patch.object(self.op,'status_operation',return_value={'status':'RUNNING'}) as status,patch.object(self.tcad,'remote') as transfer:
            result=self.op._run_operation(self.tcad,self.cfg,self.ssh,'new',self.inputs,None,True)
        status.assert_called_once_with(self.tcad,self.cfg,self.ssh,'new')
        transfer.assert_not_called()


if __name__=='__main__':unittest.main()
