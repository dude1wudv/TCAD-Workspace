"""SOFTWARE_FIXTURE_NOT_NATIVE: exercise real runner dispatch with mocked transport."""
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]


def runner():
    spec = importlib.util.spec_from_file_location('cloud_test_tcad', ROOT / 'scripts/tcad.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CloudBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tcad = runner()
        self.tcad.ROOT = self.root
        self.profile = self.root / 'connection.json'
        self.cfg = dict(backend='ssh-runtime', ssh_target='tcad-cloud',
                        runtime_entry='/srv/tcad-migration/minimal/scripts/enter-runtime.sh',
                        remote_root='/home/tcad/research-training',
                        tool_bin='/usr/synopsys/sentaurus/W-2024.09/bin',
                        local_state_root=str(self.root / 'local_runtime/cloud-benchmark/cloud'))
        self.profile.write_text(json.dumps(self.cfg))
        self.tcad.select_connection(self.profile)
        self.cfg, self.ssh, _ = self.tcad.connection()

    def test_cloud_connection_never_probes_vm_and_keeps_strict_host_checking(self):
        with patch.object(self.tcad, 'execute', side_effect=AssertionError('unexpected network or VM')):
            cfg, ssh, alias = self.tcad.connection()
        self.assertEqual(alias, 'tcad-cloud')
        self.assertIn('StrictHostKeyChecking=yes', ssh)
        self.assertIn('BatchMode=yes', ssh)
        self.assertNotIn('HostKeyAlias=tcad-training-vm', ssh)

    def test_all_remote_command_bytes_are_nested_in_runtime_entry(self):
        script = "cat > '/home/tcad/run/input' <<'END'\n$x `cmd`; text\nEND"
        argv = self.tcad.remote_argv(self.ssh, script)
        outer = shlex.split(argv[-1])
        self.assertEqual(outer[:2], ['bash', '-lc'])
        inner = shlex.split(outer[2])
        self.assertEqual(inner[:4], ['exec', self.cfg['runtime_entry'], '/bin/bash', '-lc'])
        self.assertEqual(inner[4], script)
        with patch.object(self.tcad, 'execute') as call:
            self.tcad.remote(self.ssh, script, input=b'EXACT_BYTES', timeout=12)
        self.assertEqual(call.call_args.args[0], argv)
        self.assertEqual(call.call_args.kwargs['input'], b'EXACT_BYTES')

    def test_vm_default_command_and_ledger_remain_unchanged(self):
        self.assertEqual(self.tcad.remote_argv(['ssh', 'vm'], 'echo hi'),
                         ['ssh', 'vm', "bash -lc 'echo hi'"])
        self.profile.write_text(json.dumps(dict(vmrun='VMRUN', vmx='VMX', identity='KEY',
                  known_hosts='KNOWN', user='tcad', remote_root='/home/tcad/research-training')))
        with patch.object(self.tcad, 'execute', return_value=subprocess.CompletedProcess([], 0, '192.168.1.3')) as call:
            cfg, ssh, ip = self.tcad.connection()
        self.assertEqual(call.call_args.args[0], ['VMRUN', 'getGuestIPAddress', 'VMX'])
        self.assertEqual(self.tcad.run_folder('new'), self.root / 'local_runtime/runs/new')
        self.assertIn('HostKeyAlias=tcad-training-vm', ssh)

    def test_profile_rejects_legacy_state_or_injected_alias(self):
        for update in [dict(local_state_root=str(self.root/'local_runtime')),
                       dict(ssh_target='-oProxyCommand=bad'), dict(runtime_entry='/safe/../escape')]:
            with self.subTest(update=update):
                self.profile.write_text(json.dumps(dict(self.cfg, **update)))
                with self.assertRaises(ValueError):
                    self.tcad.select_connection(self.profile)

    def test_manifest_cannot_be_rebound_to_other_host_or_vm(self):
        folder = self.tcad.run_folder('new')
        folder.mkdir(parents=True)
        evidence = dict(run_id='new', remote_directory=self.cfg['remote_root']+'/runs/new',
                        connection_identity=self.tcad.connection_identity(self.cfg))
        (folder/'manifest.json').write_text(json.dumps(evidence))
        self.tcad.read_manifest(self.cfg, 'new')
        for cfg in [dict(self.cfg, ssh_target='another-cloud'), dict(remote_root=self.cfg['remote_root'])]:
            with self.assertRaisesRegex(ValueError, 'different connection'):
                self.tcad.read_manifest(cfg, 'new')

    def test_cloud_ignores_old_ledger_but_blocks_its_own_unresolved_run(self):
        old = self.root/'local_runtime/runs/old'
        old.mkdir(parents=True)
        (old/'manifest.json').write_text(json.dumps(dict(schema='tcad-native-run-r2',state='RUNNING',run_id='old')))
        with patch.object(self.tcad, 'remote_python', return_value=[]), patch.object(self.tcad, 'remote'), patch.object(self.tcad, 'status_run') as status:
            self.tcad.assert_no_active_run(self.cfg, self.ssh)
            status.assert_not_called()
        own = self.tcad.run_folder('new')
        own.mkdir(parents=True)
        (own/'manifest.json').write_text(json.dumps(dict(schema='tcad-native-run-r2',state='LAUNCH_UNCERTAIN',run_id='new')))
        with patch.object(self.tcad, 'status_run', return_value={'status':'LOST_WITHOUT_EXIT'}) as status:
            with self.assertRaisesRegex(RuntimeError, 'Reconcile'):
                self.tcad.assert_no_active_run(self.cfg, self.ssh)
            status.assert_called_once_with(self.cfg, self.ssh, 'new')

    def project(self):
        folder = self.root/'inputs'
        folder.mkdir()
        (folder/'device.cmd').write_text('SOFTWARE_FIXTURE_NOT_NATIVE')
        (folder/'project.json').write_text(json.dumps(dict(name='cloud-test',steps=[
            dict(tool='sdevice',args=['device.cmd'],outputs=['out.plt'])])))
        return folder

    def test_historical_run_id_is_rejected_before_any_transfer(self):
        project = self.project()
        (self.root/'local_runtime/runs/old').mkdir(parents=True)
        with patch.object(self.tcad, 'remote', side_effect=AssertionError('unexpected transfer')):
            with self.assertRaisesRegex(ValueError, 'Historical VM run ID'):
                self.tcad._run_project(self.cfg, self.ssh, project, run_id='old')

    def test_same_run_id_returns_status_under_existing_owner_without_submit(self):
        self.tcad.run_folder('new').mkdir(parents=True)
        with patch.object(self.tcad,'original_ownership',return_value=nullcontext()) as owner, patch.object(self.tcad,'read_manifest'), patch.object(self.tcad,'status_run',return_value={'status':'RUNNING'}) as status, patch.object(self.tcad,'_run_project') as submit:
            self.assertEqual(self.tcad.run_project(self.cfg,self.ssh,'unused',run_id='new'),{'status':'RUNNING'})
        owner.assert_called_once()
        submit.assert_not_called()

    def test_real_collect_download_uses_chroot_and_verifies_exact_archive(self):
        import hashlib
        import io
        import tarfile
        digest=lambda raw:hashlib.sha256(raw).hexdigest()
        payload={'device.cmd':b'input','run.sh':b'script','out.plt':b'result',
                 'exit-code.txt':b'0\n','metadata-sdevice-version-exit-code.txt':b'0\n',
                 'step-001-sdevice-exit-code.txt':b'0\n'}
        index={name:dict(size=len(raw),sha256=digest(raw)) for name,raw in payload.items()}
        payload['_collection-members.json']=json.dumps(index).encode()
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w') as archive:
            for name,raw in payload.items():
                member=tarfile.TarInfo(name);member.size=len(raw)
                archive.addfile(member,io.BytesIO(raw))
        raw=stream.getvalue()
        folder=self.tcad.run_folder('new');folder.mkdir(parents=True)
        evidence=dict(schema='tcad-native-run-r2',state='EXECUTED',run_id='new',
            remote_directory=self.cfg['remote_root']+'/runs/new',remote_exit_code=0,ssh_exit_code=255,
            input_sha256={'device.cmd':digest(b'input')},script_sha256=digest(b'script'),
            steps=[dict(outputs=['out.plt'])],tool_exit_codes={},
            tool_evidence={'step-001-sdevice':dict(raw_exit_file='step-001-sdevice-exit-code.txt')},
            connection_identity=self.tcad.connection_identity(self.cfg))
        (folder/'manifest.json').write_text(json.dumps(evidence))
        calls=[]
        def execute(argv,**kwargs):
            calls.append(argv)
            self.assertIn(self.cfg['runtime_entry'],argv[-1])
            if 'stdout' in kwargs:
                kwargs['stdout'].write(raw)
                return subprocess.CompletedProcess(argv,0)
            return subprocess.CompletedProcess(argv,0,json.dumps(dict(sha256=digest(raw),bytes=len(raw))))
        with patch.object(self.tcad,'status_run',return_value={'status':'FINISHED','alive':False}), patch.object(self.tcad,'execute',side_effect=execute):
            result=self.tcad.collect_run(self.cfg,self.ssh,'new')
        self.assertEqual(len(calls),2)
        self.assertEqual(result['status'],'COLLECTED')
        self.assertEqual(result['ssh_exit_code'],255)
        self.assertEqual((folder/'results.tar').read_bytes(),raw)
        saved=json.loads((folder/'manifest.json').read_text())
        self.assertTrue(saved['collection_verified'])
        self.assertEqual(saved['connection_identity'],self.tcad.connection_identity(self.cfg))

    def test_sync_and_detach_launch_and_input_transfer_share_runtime_backend(self):
        project = self.project()
        for detach in (False, True):
            run_id = 'new-detach' if detach else 'new-sync'
            transfers = []
            def fake_remote(ssh, script, **kwargs):
                # Inspect real transfer bytes while the runner-owned stream is open.
                if 'stdin' in kwargs:
                    transfers.append(kwargs['stdin'].read())
                return subprocess.CompletedProcess([],0,b'',b'')
            with patch.object(self.tcad, 'original_ownership',return_value=nullcontext()), patch.object(self.tcad,'assert_no_active_run'), patch.object(self.tcad,'execute',return_value=subprocess.CompletedProcess([],0,'COMMIT')), patch.object(self.tcad,'remote',side_effect=fake_remote), patch.object(self.tcad.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'',b'')) as launch, patch.object(self.tcad,'status_run',return_value={'status':'FINISHED'}), patch.object(self.tcad,'collect_run',return_value={'status':'COLLECTED'}) as collect:
                result = self.tcad.run_project(self.cfg,self.ssh,project,run_id=run_id,detach=detach)
            self.assertEqual(len(transfers),1)
            self.assertTrue(transfers[0])
            command = launch.call_args.args[0]
            self.assertIn(self.cfg['runtime_entry'], command[-1])
            self.assertIn('.launch-claim', command[-1])
            evidence=json.loads((self.tcad.run_folder(run_id)/'manifest.json').read_text())
            self.assertEqual(evidence['connection_identity'],self.tcad.connection_identity(self.cfg))
            script=(self.tcad.run_folder(run_id)/'run.sh').read_text()
            self.assertIn('flock -n 9',script)
            self.assertIn('--threads 1 --exit-on-failure',script)
            self.assertIn('taskset -c',script)
            if detach:
                collect.assert_not_called()
            else:
                collect.assert_called_once_with(self.cfg,self.ssh,run_id)
                self.assertEqual(result,{'status':'COLLECTED'})


if __name__ == '__main__':
    unittest.main()
