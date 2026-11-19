"""SOFTWARE_FIXTURE_NOT_NATIVE: isolated recovery fixtures; no SSH/native execution."""
from contextlib import ExitStack, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = ROOT/'local_runtime/dram-see-v4/continuous/runner-migration/r13-reboot-recovery-r1'
spec = importlib.util.spec_from_file_location('interrupted_runner_under_test',ROOT/'scripts/tcad.py')
tcad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcad)
OLD_BOOT = '11111111-1111-1111-1111-111111111111'
NEW_BOOT = '22222222-2222-2222-2222-222222222222'
OLD_RUNNER = 'a'*64


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def archive_bytes(payload):
    index = {name:dict(size=len(raw),sha256=digest(raw)) for name,raw in payload.items()}
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as archive:
        for name,raw in dict(payload,**{'_collection-members.json':json.dumps(index,sort_keys=True).encode()}).items():
            member=tarfile.TarInfo(name);member.size=len(raw)
            archive.addfile(member,io.BytesIO(raw))
    return stream.getvalue()


class InterruptedCollectionTests(unittest.TestCase):
    def setUp(self):
        OUTPUT.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='SOFTWARE_FIXTURE_NOT_NATIVE-',dir=OUTPUT)
        self.root=Path(self.temp.name)
        self.patch_root=patch.object(tcad,'ROOT',self.root);self.patch_root.start()
        self.run_id='synthetic-reboot-case'
        self.folder=tcad.run_folder(self.run_id);self.folder.mkdir(parents=True)
        self.cfg={'remote_root':'/synthetic/original'}
        self.remote_dir=self.cfg['remote_root']+'/runs/'+self.run_id
        script=b'# SOFTWARE_FIXTURE_NOT_NATIVE wrapper\n'
        device=b'# SOFTWARE_FIXTURE_NOT_NATIVE device input\n'
        self.identity=dict(schema='tcad-process-identity-r1',run_id=self.run_id,cwd=self.remote_dir,
            pid=101,start_ticks=12345,boot_id=OLD_BOOT,script_sha256=digest(script))
        self.native=dict(schema='native-process-observation-r1',requested_tool='sdevice',wrapper_pid=101,
            native_pid=102,native_start_ticks=12346,native_executable='/synthetic/bin/sdevice',status='OBSERVED')
        self.payload={'run.sh':script,'device.cmd':device,'process-identity.json':json.dumps(self.identity).encode(),
            'step-006-sdevice-process-observation.json':json.dumps(self.native).encode(),
            'execution.log':b'SOFTWARE_FIXTURE_NOT_NATIVE\nReading doping fixture\n',
            'metadata-sdevice-version-exit-code.txt':b'0\n','nested/retained-failure.txt':b'SOFTWARE_FIXTURE_NOT_NATIVE retained failure\n'}
        (self.folder/'run.sh').write_bytes(script)
        self.record=dict(schema='tcad-native-run-r2',run_id=self.run_id,state='LOST_WITHOUT_EXIT',origin='native_pipeline',
            synthetic=False,remote_directory=self.remote_dir,script_sha256=digest(script),runner_sha256=OLD_RUNNER,
            input_sha256={'device.cmd':digest(device)},ssh_exit_code=0,remote_exit_code=None,collection_exit_code=None,
            version_probe_exit_code=None,tool_exit_codes={'step-006-sdevice':None},
            steps=[dict(tool='sdevice',outputs=['unfinished.plt'])],
            last_observation={'status':'LOST_WITHOUT_EXIT','identity':self.identity},
            tool_evidence={'step-006-sdevice':dict(tool='sdevice',process_observation_file='step-006-sdevice-process-observation.json',
                raw_exit_file='step-006-sdevice-exit-code.txt',raw_process_admission_exit_file='step-006-sdevice-process-admission-exit-code.txt')})
        tcad.save_manifest(self.folder,self.record)
        self.commands=[];self.raw=None;self.snapshot=None

    def tearDown(self):
        self.patch_root.stop()
        self.assertTrue(self.root.resolve().is_relative_to(OUTPUT.resolve()))
        self.temp.cleanup()

    def receipt(self):
        return json.loads((self.folder/'manifest.json').read_text())

    def context(self):
        return tcad.interrupted_context(self.cfg,self.folder,self.receipt())

    def fixture_proof(self,context):
        observation=dict(observed_utc='2026-10-18T02:12:21Z',current_boot_id=NEW_BOOT,original_boot_id=OLD_BOOT,
            wrapper_identity=self.identity,actual_cwd=self.remote_dir,active_native_processes=[],active_directory_processes=[],
            original_wrapper_exit_present=False,locks=[dict(fd=9,path=context['shared_lock_path'],device=1,inode=2,held=True),
                dict(fd=8,path=self.remote_dir+'/.collection/snapshot.lock',device=1,inode=3,held=True)],
            native_evidence={'step-006-sdevice-process-observation.json':dict(available=True,
                sha256=digest(self.payload['step-006-sdevice-process-observation.json']),native_pid=102,
                native_start_ticks=12346,native_executable='/synthetic/bin/sdevice',status='OBSERVED')})
        return dict(schema='tcad-interrupted-collection-proof-r1',origin='derived_collection_evidence',synthetic=False,
            purpose='SOFTWARE_FIXTURE_NOT_NATIVE',context=context,context_sha256=tcad.canonical_sha256(context),
            before_snapshot=observation,after_snapshot=dict(observation))

    def make_snapshot(self,context,proof_change=None,payload_change=None):
        proof=self.fixture_proof(context)
        if proof_change:proof_change(proof)
        proof_raw=json.dumps(proof,sort_keys=True,separators=(',',':')).encode()
        payload=dict(self.payload,**{'_interrupted-collection-proof.json':proof_raw})
        if payload_change:payload_change(payload)
        self.raw=archive_bytes(payload)
        self.snapshot=dict(schema='tcad-original-snapshot-r1',sha256=digest(self.raw),bytes=len(self.raw),members=len(payload),
            interrupted_context_sha256=tcad.canonical_sha256(context),interruption_proof_sha256=digest(proof_raw))

    def remote(self,ssh,command,**kwargs):
        self.commands.append(command)
        if 'TCAD_SNAPSHOT' in command:
            self.assertTrue(command.startswith('set -e; cd '))
            self.assertLess(command.index('flock -n 9'),command.index('flock -n 8'))
            self.assertLess(command.index('flock -n 8'),command.index('def interrupted_observation'))
            if self.raw is None:self.make_snapshot(self.receipt()['interrupted_collection_context'])
            return subprocess.CompletedProcess(['MOCK_ONLY'],0,stdout=json.dumps(self.snapshot))
        self.assertTrue(command.startswith('cat '))
        kwargs['stdout'].write(self.raw)
        return subprocess.CompletedProcess(['MOCK_ONLY'],0)

    def collect(self,remote=None):
        with patch.object(tcad,'remote',side_effect=remote or self.remote):
            return tcad.collect_run(self.cfg,['MOCK_ONLY'],self.run_id,interrupted=True)

    def test_complete_reboot_archive_preserves_unknown_and_original_runner(self):
        original=(self.folder/'manifest.json').read_bytes()
        result=self.collect()
        saved=self.receipt()
        self.assertEqual(result['status'],'INTERRUPTED_COLLECTED')
        self.assertIsNone(saved['remote_exit_code'])
        self.assertIsNone(saved['tool_exit_codes']['step-006-sdevice'])
        self.assertEqual(saved['ssh_exit_code'],0)
        self.assertEqual(saved['collection_exit_code'],0)
        self.assertEqual(saved['runner_sha256'],OLD_RUNNER)
        self.assertEqual(saved['collection_implementation_sha256'],tcad.file_hash(Path(tcad.__file__)))
        self.assertEqual((self.folder/'manifest.before-interrupted-collection.json').read_bytes(),original)
        for name in ('exit-code.txt','step-006-sdevice-exit-code.txt','step-006-sdevice-process-admission-exit-code.txt'):
            self.assertIn(name,saved['capture_exit_errors'])
        with tarfile.open(self.folder/'results.tar') as archive:
            names=archive.getnames()
            self.assertIn('nested/retained-failure.txt',names)
            self.assertIn('_interrupted-collection-proof.json',names)
            self.assertNotIn('exit-code.txt',names)
            self.assertNotIn('finished-utc.txt',names)
        self.assertEqual(tcad.file_hash(self.folder/'results.tar'),self.snapshot['sha256'])

    def test_normal_collect_still_rejects_lost_exit_without_flag(self):
        with patch.object(tcad,'status_run',return_value={'status':'LOST_WITHOUT_EXIT','alive':False}),patch.object(tcad,'remote') as remote:
            with self.assertRaisesRegex(RuntimeError,'completed original'):
                tcad.collect_run(self.cfg,[],self.run_id)
        remote.assert_not_called()
        self.assertFalse((self.folder/'manifest.before-interrupted-collection.json').exists())

    def test_local_identity_or_wrapper_mismatch_rejected_before_remote(self):
        for key,value in [('pid',True),('cwd','/wrong'),('boot_id','invalid'),('script_sha256','b'*64)]:
            with self.subTest(key=key):
                record=self.receipt();record['last_observation']['identity'][key]=value
                with self.assertRaises(ValueError):tcad.interrupted_context(self.cfg,self.folder,record)
        (self.folder/'run.sh').write_bytes(b'CHANGED SOFTWARE_FIXTURE_NOT_NATIVE')
        with patch.object(tcad,'remote') as remote,self.assertRaisesRegex(ValueError,'wrapper fingerprint'):
            self.collect()
        remote.assert_not_called()

    def test_input_and_proof_mismatch_cannot_close_run(self):
        context=self.context()
        self.make_snapshot(context,payload_change=lambda p:p.update({'device.cmd':b'CHANGED SOFTWARE_FIXTURE_NOT_NATIVE'}))
        with self.assertRaisesRegex(ValueError,'provenance differs'):self.collect()
        self.assertNotEqual(self.receipt()['state'],'INTERRUPTED_COLLECTED')
        self.assertFalse((self.folder/'results.tar').exists())

    def test_same_boot_in_proof_is_not_accepted(self):
        context=self.context()
        def changed(proof):
            proof['before_snapshot']['current_boot_id']=OLD_BOOT
            proof['after_snapshot']['current_boot_id']=OLD_BOOT
        self.make_snapshot(context,proof_change=changed)
        with self.assertRaisesRegex(ValueError,'quiescent different boot'):self.collect()
        self.assertIsNone(self.receipt()['remote_exit_code'])
        self.assertFalse((self.folder/'results.tar').exists())

    def test_interrupted_transfer_resumes_original_snapshot_without_submission(self):
        calls=0
        def remote(ssh,command,**kwargs):
            nonlocal calls
            if 'TCAD_SNAPSHOT' in command:return self.remote(ssh,command,**kwargs)
            calls+=1
            if calls==1:
                kwargs['stdout'].write(self.raw[:123])
                raise subprocess.CalledProcessError(255,['MOCK_ONLY'])
            return self.remote(ssh,command,**kwargs)
        with self.assertRaises(subprocess.CalledProcessError):self.collect(remote)
        before=self.receipt()
        self.assertEqual(before['collection_exit_code'],255)
        self.assertEqual(before['ssh_exit_code'],0)
        self.assertIsNone(before['remote_exit_code'])
        result=self.collect(remote)
        self.assertEqual(result['status'],'INTERRUPTED_COLLECTED')
        self.assertEqual(calls,2)
        self.assertEqual(self.receipt()['collection_exit_code'],0)
        self.assertTrue(list(self.folder.glob('results.*.part.tar')))
        self.assertFalse(any('nohup' in command for command in self.commands))

    def test_snapshot_lock_failure_does_not_invent_transfer_exit(self):
        with patch.object(tcad,'remote',side_effect=subprocess.CalledProcessError(75,['MOCK_LOCK'])):
            with self.assertRaises(subprocess.CalledProcessError):
                tcad.collect_run(self.cfg,[],self.run_id,interrupted=True)
        self.assertIsNone(self.receipt()['collection_exit_code'])
        self.assertIsNone(self.receipt()['remote_exit_code'])
        self.assertFalse((self.folder/'results.tar').exists())

    def test_existing_archive_not_overwritten(self):
        (self.folder/'results.tar').write_bytes(b'SOFTWARE_FIXTURE_NOT_NATIVE prior archive')
        with self.assertRaisesRegex(ValueError,'Refusing to replace'):self.collect()
        self.assertEqual((self.folder/'results.tar').read_bytes(),b'SOFTWARE_FIXTURE_NOT_NATIVE prior archive')
        self.assertNotEqual(self.receipt()['state'],'INTERRUPTED_COLLECTED')

    def test_terminal_status_repeat_collect_and_repeat_id_do_not_reopen_run(self):
        self.collect()
        receipt_raw=(self.folder/'manifest.json').read_bytes()
        with patch.object(tcad,'remote') as remote,patch.object(tcad,'remote_python') as query:
            self.assertEqual(tcad.collect_run(self.cfg,[],self.run_id)['status'],'INTERRUPTED_COLLECTED')
            self.assertEqual(tcad.status_run(self.cfg,[],self.run_id)['status'],'INTERRUPTED_COLLECTED')
            with patch.object(tcad,'original_ownership'),patch.object(tcad,'_run_project') as launch:
                self.assertEqual(tcad.run_project(self.cfg,[],self.root,self.run_id,True)['status'],'INTERRUPTED_COLLECTED')
            launch.assert_not_called();query.assert_not_called();remote.assert_not_called()
        self.assertEqual((self.folder/'manifest.json').read_bytes(),receipt_raw)
        with patch.object(tcad,'remote_python',return_value=[]) as query,patch.object(tcad,'remote'):
            tcad.assert_no_active_run(self.cfg,[])
            query.assert_called_once()
        (self.folder/'results.tar').write_bytes(b'CHANGED SOFTWARE_FIXTURE_NOT_NATIVE')
        with self.assertRaisesRegex(ValueError,'immutable archive changed'):
            tcad.collect_run(self.cfg,[],self.run_id,interrupted=True)

    def test_one_normal_complete_collection_remains_successful(self):
        record=self.receipt();record['state']='EXECUTED';record['remote_exit_code']=0
        tcad.save_manifest(self.folder,record)
        payload=dict(self.payload,**{'exit-code.txt':b'0\n','step-006-sdevice-exit-code.txt':b'0\n','unfinished.plt':b'SOFTWARE_FIXTURE_NOT_NATIVE result'})
        raw=archive_bytes(payload)
        def normal_remote(ssh,command,**kwargs):
            if 'stdout' in kwargs:
                kwargs['stdout'].write(raw);return subprocess.CompletedProcess(['MOCK_ONLY'],0)
            self.assertTrue(command.startswith('set -e; cd '))
            self.assertNotIn('def interrupted_observation',command)
            return subprocess.CompletedProcess(['MOCK_ONLY'],0,stdout=json.dumps({'sha256':digest(raw),'bytes':len(raw)}))
        with patch.object(tcad,'status_run',return_value={'status':'FINISHED','alive':False}),patch.object(tcad,'remote',side_effect=normal_remote):
            result=tcad.collect_run(self.cfg,[],self.run_id)
        self.assertEqual(result['status'],'COLLECTED')
        self.assertEqual(self.receipt()['remote_exit_code'],0)
        self.assertEqual(self.receipt()['runner_sha256'],OLD_RUNNER)
        self.assertNotIn('interrupted_collection_context',self.receipt())

    def guard_fixture(self):
        remote=self.root/'remote'/self.run_id;remote.mkdir(parents=True)
        proc=self.root/'proc';(proc/'sys/kernel/random').mkdir(parents=True)
        (proc/'sys/kernel/random/boot_id').write_text(NEW_BOOT)
        identity=dict(self.identity,cwd=str(remote))
        (remote/'run.sh').write_bytes(self.payload['run.sh'])
        (remote/'process-identity.json').write_text(json.dumps(identity))
        (remote/'.collection').mkdir()
        shared=self.root/'shared.lock';shared.write_bytes(b'')
        snapshot=remote/'.collection/snapshot.lock';snapshot.write_bytes(b'')
        context=dict(schema='tcad-interrupted-collection-context-r1',run_id=self.run_id,remote_directory=str(remote),
            process_identity=identity,script_sha256=self.identity['script_sha256'],shared_lock_path=str(shared),native_evidence=[])
        def add_process(pid,name,ppid=0,cwd=None):
            path=proc/str(pid);path.mkdir()
            fields=['S',str(ppid)]+['0']*17+['999']
            (path/'stat').write_text(str(pid)+' ('+name+') '+' '.join(fields))
            (path/'comm').write_text(name)
            return str(path/'cwd'),str(remote if cwd is None else cwd)
        cwd_map=dict([add_process(900,'python',901),add_process(901,'bash')])
        fake_fcntl=types.SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=Mock())
        code=tcad.INTERRUPTED_CHECK_CODE.replace("Path('/proc')",'Path('+repr(str(proc))+')')
        stack=ExitStack()
        stack.enter_context(patch.dict(sys.modules,{'fcntl':fake_fcntl}))
        stack.enter_context(patch.object(Path,'cwd',return_value=remote))
        stack.enter_context(patch.object(tcad.os,'getpid',return_value=900))
        stack.enter_context(patch.object(tcad.os,'fstat',side_effect=lambda fd:(shared if fd==9 else snapshot).stat()))
        stack.enter_context(patch.object(tcad.os,'readlink',side_effect=lambda path:cwd_map[str(path)]))
        namespace={};exec(code,namespace)
        return stack,namespace,context,proc,remote,cwd_map,add_process,fake_fcntl

    def test_remote_guard_rejects_same_boot_even_when_pids_disappeared(self):
        stack,ns,ctx,proc,*_=self.guard_fixture()
        with stack:
            (proc/'sys/kernel/random/boot_id').write_text(OLD_BOOT)
            with self.assertRaisesRegex(ValueError,'Same-boot'):
                ns['interrupted_observation'](ctx)

    def test_remote_guard_protects_any_native_or_original_directory_writer(self):
        stack,ns,ctx,proc,remote,cwd_map,add_process,_=self.guard_fixture()
        with stack:
            cwd_map.update([add_process(102,'sdevice')])
            with self.assertRaisesRegex(ValueError,'Active native'):
                ns['interrupted_observation'](ctx)
            (proc/'102/comm').write_text('python')
            with self.assertRaisesRegex(ValueError,'original-directory'):
                ns['interrupted_observation'](ctx)

    def test_remote_guard_rechecks_original_identity_script_and_locks(self):
        stack,ns,ctx,proc,remote,_,_,flock=self.guard_fixture()
        with stack:
            observed=ns['interrupted_observation'](ctx)
            self.assertEqual(observed['current_boot_id'],NEW_BOOT)
            self.assertEqual([v['fd'] for v in observed['locks']],[9,8])
            self.assertEqual(flock.flock.call_count,2)
            flock.flock.side_effect=BlockingIOError('SOFTWARE_FIXTURE_LOCK_BUSY')
            with self.assertRaises(BlockingIOError):ns['interrupted_observation'](ctx)
            flock.flock.side_effect=None
            identity=json.loads((remote/'process-identity.json').read_text());identity['start_ticks']+=1
            (remote/'process-identity.json').write_text(json.dumps(identity))
            with self.assertRaisesRegex(ValueError,'identity differs'):ns['interrupted_observation'](ctx)
            (remote/'process-identity.json').write_text(json.dumps(ctx['process_identity']))
            (remote/'run.sh').write_bytes(b'CHANGED SOFTWARE_FIXTURE_NOT_NATIVE')
            with self.assertRaisesRegex(ValueError,'script changed'):ns['interrupted_observation'](ctx)

    def test_remote_snapshot_adds_only_derived_proof_and_full_index(self):
        stack,ns,ctx,proc,remote,_,_,_=self.guard_fixture()
        with stack:
            (remote/'other-original.dat').write_bytes(b'SOFTWARE_FIXTURE_NOT_NATIVE retained data')
            ns['interrupted_context']=ctx
            with redirect_stdout(io.StringIO()) as captured:exec(tcad.SNAPSHOT_CODE,ns)
            snapshot=json.loads(captured.getvalue())
            archive=remote/'.collection/results.tar'
            original_hash=tcad.file_hash(archive)
            self.assertEqual(original_hash,snapshot['sha256'])
            with tarfile.open(archive) as source:
                names=source.getnames();index=json.load(source.extractfile('_collection-members.json'))
                self.assertEqual(set(index),set(names)-{'_collection-members.json'})
                for name,facts in index.items():self.assertEqual(digest(source.extractfile(name).read()),facts['sha256'])
                proof=json.load(source.extractfile('_interrupted-collection-proof.json'))
                self.assertEqual(proof['before_snapshot']['current_boot_id'],NEW_BOOT)
                self.assertEqual(proof['after_snapshot']['current_boot_id'],NEW_BOOT)
                self.assertIn('other-original.dat',names)
                self.assertNotIn('exit-code.txt',names)
            self.assertFalse((remote/'exit-code.txt').exists())
            self.assertFalse((remote/'finished-utc.txt').exists())
            self.assertFalse((remote/'_interrupted-collection-proof.json').exists())
            with redirect_stdout(io.StringIO()):exec(tcad.SNAPSHOT_CODE,ns)
            self.assertEqual(tcad.file_hash(archive),original_hash)
            (proc/'sys/kernel/random/boot_id').write_text(OLD_BOOT)
            with self.assertRaisesRegex(ValueError,'Same-boot'),redirect_stdout(io.StringIO()):
                exec(tcad.SNAPSHOT_CODE,ns)
            self.assertEqual(tcad.file_hash(archive),original_hash)


if __name__=='__main__':
    unittest.main()
