"""SOFTWARE_FIXTURE_NOT_NATIVE: apply the data-root patch in memory only."""
import ast
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import posixpath
import re
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[4]
LEGACY_OUTPUT=ROOT/'local_runtime/dram-see-v4/continuous/runner-migration/data-root-r1'
OUTPUT=ROOT/'local_runtime/dram-see-v4/continuous/runner-migration/data-root-control-binding-r2'
BASE_SHA='66839ca8189610f5a300c640379d05b82121e2d2bc5b1755d503e648a5dc9d01'
APPLIED_SHA='252a52e202bbb03cc85f8ec9e71e2795f292afad984dc94f6ea84d31b3872f51'
BOUND_SHA='d462e4ddbbcd18999ebf7beccf66d2f1c046b2b9dbac41e1df6d111f40193c24'
SOURCE=ROOT/'scripts/tcad.py'


def digest(raw):return hashlib.sha256(raw).hexdigest()


def apply_patch_in_memory(base,diff,reverse=False):
    original=base.splitlines(keepends=True);lines=diff.splitlines(keepends=True)
    if lines[:2]!=['--- a/scripts/tcad.py\n','+++ b/scripts/tcad.py\n']:
        raise ValueError('Unexpected patch target')
    output=[];cursor=0;position=2
    while position<len(lines):
        header=re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@\n',lines[position])
        if not header:raise ValueError('Invalid unified hunk')
        start=int(header[3] if reverse else header[1])-1
        old_count=int((header[4] if reverse else header[2]) or 1)
        new_count=int((header[2] if reverse else header[4]) or 1)
        if start<cursor:raise ValueError('Overlapping unified hunks')
        output.extend(original[cursor:start]);cursor=start;position+=1;old_used=new_used=0
        while position<len(lines) and not lines[position].startswith('@@ '):
            line=lines[position];prefix=line[0];value=line[1:]
            if reverse:prefix={'+':'-','-':'+'}.get(prefix,prefix)
            if prefix in (' ','-'):
                if cursor>=len(original) or original[cursor]!=value:raise ValueError('Patch baseline differs')
                cursor+=1;old_used+=1
            if prefix in (' ','+'):output.append(value);new_used+=1
            if prefix not in (' ','+','-'):raise ValueError('Invalid unified diff line')
            position+=1
        if (old_used,new_used)!=(old_count,new_count):raise ValueError('Unified hunk length differs')
    output.extend(original[cursor:])
    return ''.join(output)


def load_sources_in_memory(current,patch_bytes,meta):
    if meta.get('base_sha256')!=BASE_SHA or meta.get('expected_applied_runner_sha256')!=APPLIED_SHA:
        raise RuntimeError('Sealed source fingerprints differ')
    if digest(patch_bytes)!=meta.get('patch_sha256'):
        raise RuntimeError('Patch fingerprint differs')
    current_sha=digest(current)
    if current_sha==BASE_SHA:
        base=current
        applied=apply_patch_in_memory(base.decode(),patch_bytes.decode())
    elif current_sha==APPLIED_SHA:
        applied=current.decode()
        base=apply_patch_in_memory(applied,patch_bytes.decode(),reverse=True).encode()
    else:
        raise RuntimeError('Current runner is neither the sealed baseline nor the sealed applied source')
    if digest(base)!=BASE_SHA or digest(applied.encode())!=APPLIED_SHA:
        raise RuntimeError('Reconstructed source fingerprint differs')
    return base,applied


def load_bound_sources_in_memory(current,patch_bytes,meta,binding_patch,binding_meta):
    if binding_meta.get('base_sha256')!=APPLIED_SHA or binding_meta.get('expected_applied_runner_sha256')!=BOUND_SHA:
        raise RuntimeError('Sealed control-binding source fingerprints differ')
    if digest(binding_patch)!=binding_meta.get('patch_sha256'):
        raise RuntimeError('Control-binding patch fingerprint differs')
    if digest(current)==BOUND_SHA:
        previous=apply_patch_in_memory(current.decode(),binding_patch.decode(),reverse=True).encode()
        if digest(previous)!=APPLIED_SHA:
            raise RuntimeError('Reconstructed data-root source fingerprint differs')
    else:
        previous=current
    base,applied=load_sources_in_memory(previous,patch_bytes,meta)
    bound=apply_patch_in_memory(applied,binding_patch.decode())
    if digest(bound.encode())!=BOUND_SHA:
        raise RuntimeError('Reconstructed control-binding source fingerprint differs')
    return base,applied,bound


SOURCE_BYTES=SOURCE.read_bytes()
SOURCE_SHA=digest(SOURCE_BYTES)
META=json.loads((LEGACY_OUTPUT/'candidate-meta.json').read_text())
PATCH=(LEGACY_OUTPUT/'tcad-data-root.patch').read_bytes()
BINDING_META=json.loads((OUTPUT/'candidate-meta.json').read_text())
BINDING_PATCH=(OUTPUT/'tcad-data-root-control-binding.patch').read_bytes()
BASE,DATA_ROOT_SOURCE,CANDIDATE=load_bound_sources_in_memory(SOURCE_BYTES,PATCH,META,BINDING_PATCH,BINDING_META)


def module_from_memory(name,source):
    module=types.ModuleType(name);module.__file__=str(SOURCE)
    exec(compile(source,str(SOURCE),'exec'),module.__dict__)
    return module


candidate=module_from_memory('data_root_candidate',CANDIDATE)
baseline=module_from_memory('data_root_baseline',BASE.decode())


class SourceLoadingTests(unittest.TestCase):
    def test_baseline_and_applied_sources_reconstruct_exact_pair(self):
        for raw in (BASE,DATA_ROOT_SOURCE.encode()):
            with self.subTest(source_sha=digest(raw)):
                base,applied=load_sources_in_memory(raw,PATCH,META)
                self.assertEqual(base,BASE)
                self.assertEqual(applied,DATA_ROOT_SOURCE)
                self.assertEqual(digest(base),BASE_SHA)
                self.assertEqual(digest(applied.encode()),APPLIED_SHA)

    def test_unknown_source_and_modified_patch_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'neither the sealed baseline'):
            load_sources_in_memory(BASE+b'\n# UNKNOWN_SOURCE\n',PATCH,META)
        with self.assertRaisesRegex(RuntimeError,'Patch fingerprint differs'):
            load_sources_in_memory(DATA_ROOT_SOURCE.encode(),PATCH+b'\n',META)
        changed=PATCH.replace(b'Optional canonical remote data directory',b'Changed canonical remote data directory',1)
        self.assertNotEqual(changed,PATCH)
        changed_meta=dict(META,patch_sha256=digest(changed))
        with self.assertRaisesRegex(RuntimeError,'Reconstructed source fingerprint differs'):
            load_sources_in_memory(BASE,changed,changed_meta)

    def test_applied_entry_loads_and_preserves_fixture_source_guards(self):
        test_path=Path(__file__).resolve()
        test_source=test_path.read_text(encoding='utf-8')
        original_read=Path.read_bytes
        for source_sha,source in ((APPLIED_SHA,DATA_ROOT_SOURCE),(BOUND_SHA,CANDIDATE)):
            with self.subTest(source_sha=source_sha):
                def read_bytes(path):
                    return source.encode() if path.resolve()==SOURCE.resolve() else original_read(path)
                loaded=types.ModuleType('data_root_applied_source_fixture')
                loaded.__file__=str(test_path)
                with patch.object(Path,'read_bytes',read_bytes):
                    exec(compile(test_source,str(test_path),'exec'),loaded.__dict__)
                    self.assertEqual(loaded.SOURCE_SHA,source_sha)
                    self.assertEqual(loaded.BASE,BASE)
                    self.assertEqual(loaded.DATA_ROOT_SOURCE,DATA_ROOT_SOURCE)
                    self.assertEqual(loaded.CANDIDATE,CANDIDATE)
                    result=unittest.TestResult()
                    loaded.DataRootTests('test_default_wrapper_and_manifest_layout_are_unchanged').run(result)
                    self.assertEqual(result.testsRun,1)
                    self.assertTrue(result.wasSuccessful(),result.errors+result.failures)
        self.assertEqual(digest(SOURCE.read_bytes()),SOURCE_SHA)

    def test_all_three_source_versions_reconstruct_exact_chain(self):
        for raw in (BASE,DATA_ROOT_SOURCE.encode(),CANDIDATE.encode()):
            with self.subTest(source_sha=digest(raw)):
                actual=load_bound_sources_in_memory(raw,PATCH,META,BINDING_PATCH,BINDING_META)
                self.assertEqual(actual,(BASE,DATA_ROOT_SOURCE,CANDIDATE))
                self.assertEqual(tuple(digest(item.encode() if isinstance(item,str) else item) for item in actual),
                                 (BASE_SHA,APPLIED_SHA,BOUND_SHA))
        with self.assertRaisesRegex(RuntimeError,'neither the sealed baseline'):
            load_bound_sources_in_memory(CANDIDATE.encode()+b'\n# UNKNOWN_SOURCE\n',PATCH,META,BINDING_PATCH,BINDING_META)

    def test_binding_patch_hash_and_reconstruction_are_checked(self):
        with self.assertRaisesRegex(RuntimeError,'Control-binding patch fingerprint differs'):
            load_bound_sources_in_memory(CANDIDATE.encode(),PATCH,META,BINDING_PATCH+b'\n',BINDING_META)
        changed=BINDING_PATCH.replace(b'Run/original control root',b'Changed/original control root',1)
        self.assertNotEqual(changed,BINDING_PATCH)
        changed_meta=dict(BINDING_META,patch_sha256=digest(changed))
        with self.assertRaisesRegex(RuntimeError,'Reconstructed control-binding source fingerprint differs'):
            load_bound_sources_in_memory(DATA_ROOT_SOURCE.encode(),PATCH,META,changed,changed_meta)


class SyntheticLinuxFS:
    """Minimal in-memory Linux openat model; never calls host filesystem/native APIs."""
    O_RDONLY=0;O_DIRECTORY=0x10000;O_NOFOLLOW=0x20000
    def __init__(self):
        self.nodes={};self.fds={};self.next_fd=10;self.open_calls=[];self.mkdir_calls=[];self.mask=0
        self.path=types.SimpleNamespace(lexists=lambda path:path in self.nodes)
        for path,uid,mode in [('/',0,0o755),('/srv',0,0o755),('/var',0,0o755),('/var/tmp',0,0o1777)]:
            self.add(path,uid,mode)
    def add(self,path,uid=1000,mode=0o700,kind='directory'):
        self.nodes[path]=dict(uid=uid,mode=mode,kind=kind,inode=len(self.nodes)+100)
    def geteuid(self):return 1000
    def umask(self,value):old=self.mask;self.mask=value;return old
    def open(self,path,flags,dir_fd=None):
        path=posixpath.join(self.fds[dir_fd],path) if dir_fd is not None else path
        self.open_calls.append((path,flags,dir_fd))
        if path not in self.nodes:raise FileNotFoundError(path)
        node=self.nodes[path]
        if node['kind']=='symlink' and flags&self.O_NOFOLLOW:raise OSError('SOFTWARE_FIXTURE_SYMLINK_REJECTED')
        if node['kind']!='directory':raise NotADirectoryError(path)
        fd=self.next_fd;self.next_fd+=1;self.fds[fd]=path;return fd
    def fstat(self,fd):
        node=self.nodes[self.fds[fd]]
        return types.SimpleNamespace(st_mode=stat.S_IFDIR|node['mode'],st_uid=node['uid'],st_dev=77,st_ino=node['inode'])
    def readlink(self,path):return self.fds[int(path.rsplit('/',1)[1])]
    def mkdir(self,name,mode,dir_fd=None):
        parent=self.fds[dir_fd];path=posixpath.join(parent,name)
        self.mkdir_calls.append((path,mode,dir_fd))
        if path in self.nodes:raise FileExistsError(path)
        owner=self.nodes[parent]
        if not (owner['mode']&(0o200 if owner['uid']==self.geteuid() else 0o002)):
            raise PermissionError('SOFTWARE_FIXTURE_PARENT_NOT_WRITABLE')
        self.add(path,self.geteuid(),mode&~self.mask)
    def close(self,fd):del self.fds[fd]


class DataRootTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(digest(SOURCE.read_bytes()),SOURCE_SHA)
        self.temp=tempfile.TemporaryDirectory(prefix='SOFTWARE_FIXTURE_NOT_NATIVE-',dir=OUTPUT)
        self.root=Path(self.temp.name);self.cfg={'remote_root':'/control/root','tool_bin':'/synthetic/bin'}
        self.patch_root=patch.object(candidate,'ROOT',self.root);self.patch_root.start()
        self.run_id='fixture-run'
    def tearDown(self):
        self.patch_root.stop()
        self.assertTrue(self.root.resolve().is_relative_to(OUTPUT.resolve()))
        self.temp.cleanup()
        self.assertEqual(digest(SOURCE.read_bytes()),SOURCE_SHA)
    def write_record(self,root=None,layout=None,remote=None):
        folder=candidate.run_folder(self.run_id);folder.mkdir(parents=True,exist_ok=True)
        record=dict(schema='tcad-native-run-r2',run_id=self.run_id,state='RUNNING',script_sha256='a'*64,
            remote_directory=remote or (root or self.cfg['remote_root'])+'/runs/'+self.run_id,
            ssh_exit_code=0,remote_exit_code=None)
        if root is not None:record['data_root']=root
        if layout is not None:
            record.update(remote_layout=layout,control_root=self.cfg['remote_root'],
                          shared_lock_path=self.cfg['remote_root'].rstrip('/')+'/.solver.lock')
        (folder/'manifest.json').write_text(json.dumps(record))
        return folder,record
    def run_directory_guard(self,fs,data_root='/srv/tcad-dram-see-v4',run_id='fixture-run'):
        with patch.dict(sys.modules,{'os':fs}),patch.object(sys,'argv',['-',data_root,run_id,self.cfg['remote_root']]),redirect_stdout(io.StringIO()) as output:
            exec(candidate.DATA_ROOT_CREATE_CODE,{})
        return json.loads(output.getvalue())
    def stage_fixture(self,module,local_root,data_root=None):
        project=self.root/'project';project.mkdir(exist_ok=True)
        (project/'project.json').write_text(json.dumps({'name':'fixture-project','steps':[{'tool':'sdevice','args':['device.cmd'],'outputs':['result.plt']}]}))
        (project/'device.cmd').write_bytes(b'SOFTWARE_FIXTURE_NOT_NATIVE\n')
        commands=[];observations=[]
        def remote(ssh,command,**kwargs):commands.append(command);return subprocess.CompletedProcess(['MOCK_ONLY'],0)
        def remote_python(ssh,code,args,**kwargs):
            observations.append((code,args))
            return {'schema':'tcad-data-root-directory-observation-r1','data_root':args[0],
                'remote_directory':args[0]+'/runs/'+args[1],'ssh_uid':1000,'directories':[]}
        with patch.object(module,'ROOT',local_root),patch.object(module,'assert_no_active_run'), \
                patch.object(module,'execute',return_value=subprocess.CompletedProcess(['MOCK_GIT'],0,stdout='fixture-commit\n')), \
                patch.object(module,'remote',side_effect=remote),patch.object(module,'remote_python',side_effect=remote_python), \
                patch.object(module.subprocess,'run',return_value=subprocess.CompletedProcess(['MOCK_SSH'],0,stdout=b'',stderr=b'')), \
                patch.object(module,'status_run',return_value={'status':'RUNNING'}):
            kwargs={'data_root':data_root} if module is candidate else {}
            module._run_project(self.cfg,['MOCK_ONLY'],project,self.run_id,True,**kwargs)
            folder=module.run_folder(self.run_id)
            return (folder/'run.sh').read_bytes(),json.loads((folder/'manifest.json').read_text()),commands,observations

    def test_old_and_explicit_new_layout_bindings(self):
        self.write_record()
        _,old=candidate.read_manifest(self.cfg,self.run_id)
        self.assertEqual(old['remote_directory'],'/control/root/runs/fixture-run')
        self.write_record('/srv/tcad-dram-see-v4',candidate.DATA_ROOT_LAYOUT)
        _,new=candidate.read_manifest(self.cfg,self.run_id)
        self.assertEqual(new['remote_directory'],'/srv/tcad-dram-see-v4/runs/fixture-run')
        self.assertEqual(candidate.read_manifest(self.cfg,self.run_id,data_root='/srv/tcad-dram-see-v4')[1],new)

    def test_new_manifest_freezes_original_control_root_and_shared_lock(self):
        local_root=self.root/'candidate'
        _,record,_,_=self.stage_fixture(candidate,local_root,'/srv/tcad-dram-see-v4')
        self.assertEqual(record['control_root'],self.cfg['remote_root'])
        self.assertEqual(record['shared_lock_path'],'/control/root/.solver.lock')
        with patch.object(candidate,'ROOT',local_root):
            self.assertEqual(candidate.read_manifest(self.cfg,self.run_id)[1],record)

    def test_control_root_drift_rejected_before_status_collect_or_relaunch(self):
        self.write_record('/srv/data',candidate.DATA_ROOT_LAYOUT)
        for root in ('/different/control','/control/root/'):
            with self.subTest(control_root=root),patch.object(candidate,'remote_python') as query, \
                    patch.object(candidate,'remote') as remote,patch.object(candidate,'_run_project') as launch, \
                    patch.object(candidate,'original_ownership'):
                changed_cfg=dict(self.cfg,remote_root=root)
                for action in (lambda:candidate.read_manifest(changed_cfg,self.run_id),
                               lambda:candidate.status_run(changed_cfg,[],self.run_id),
                               lambda:candidate.collect_run(changed_cfg,[],self.run_id),
                               lambda:candidate.run_project(changed_cfg,[],Path('unused'),self.run_id,True)):
                    with self.assertRaisesRegex(ValueError,'control root or shared lock identity differs'):
                        action()
                query.assert_not_called();remote.assert_not_called();launch.assert_not_called()

    def test_new_layout_missing_or_mismatched_control_binding_is_rejected(self):
        for missing,changed in [(('control_root',),{}),(('shared_lock_path',),{}),
                                (('control_root','shared_lock_path'),{}),
                                ((),{'control_root':'/different/control'}),
                                ((),{'shared_lock_path':'/srv/data/.solver.lock'})]:
            with self.subTest(missing=missing,changed=changed):
                folder,record=self.write_record('/srv/data',candidate.DATA_ROOT_LAYOUT)
                for key in missing:record.pop(key)
                record.update(changed)
                (folder/'manifest.json').write_text(json.dumps(record))
                with self.assertRaisesRegex(ValueError,'control root or shared lock identity differs'):
                    candidate.read_manifest(self.cfg,self.run_id)
                self.assertEqual(json.loads((folder/'manifest.json').read_text()),record)

    def test_old_layout_keeps_implicit_control_root_binding(self):
        _,record=self.write_record()
        self.assertNotIn('control_root',record);self.assertNotIn('shared_lock_path',record)
        self.assertEqual(candidate.read_manifest(self.cfg,self.run_id)[1],record)
        with self.assertRaisesRegex(ValueError,'original remote directory identity differs'):
            candidate.read_manifest(dict(self.cfg,remote_root='/different/control'),self.run_id)

    def test_unmarked_unknown_and_mismatched_layouts_are_rejected(self):
        for root,layout,remote in [('/srv/data',None,None),('/srv/data','wrong',None),
                                  ('/srv/data',candidate.DATA_ROOT_LAYOUT,'/other/runs/fixture-run'),
                                  (None,None,'/srv/data/runs/fixture-run')]:
            with self.subTest(root=root,layout=layout,remote=remote):
                self.write_record(root,layout,remote)
                with self.assertRaises(ValueError):candidate.read_manifest(self.cfg,self.run_id)

    def test_repeated_id_with_changed_root_never_launches(self):
        for existing in (None,'/srv/data'):
            self.write_record(existing,candidate.DATA_ROOT_LAYOUT if existing else None)
            with patch.object(candidate,'original_ownership'),patch.object(candidate,'status_run',return_value={'status':'RUNNING'}) as status,patch.object(candidate,'_run_project') as launch:
                with self.assertRaisesRegex(ValueError,'different data root'):
                    candidate.run_project(self.cfg,[],Path('unused'),self.run_id,True,data_root='/other/data')
                status.assert_not_called();launch.assert_not_called()
                candidate.run_project(self.cfg,[],Path('unused'),self.run_id,True)
                candidate.run_project(self.cfg,[],Path('unused'),self.run_id,True,data_root=existing or '/control/root')
                self.assertEqual(status.call_count,2);launch.assert_not_called()

    def test_bad_paths_are_rejected_locally_and_remotely_without_creation(self):
        for value in ('relative','/','//srv/data','/srv/data/','/srv//data','/srv/./data','/srv/../data',r'C:\data','/srv/data name','/srv/data\n'):
            with self.subTest(path=value):
                with self.assertRaises(ValueError):candidate.normalize_data_root(value)
                fs=SyntheticLinuxFS()
                with self.assertRaises(ValueError):self.run_directory_guard(fs,value)
                self.assertEqual(fs.mkdir_calls,[])

    def test_default_wrapper_and_manifest_layout_are_unchanged(self):
        before,before_record,before_commands,before_observations=self.stage_fixture(baseline,self.root/'baseline')
        after,after_record,after_commands,after_observations=self.stage_fixture(candidate,self.root/'candidate')
        self.assertEqual(before,after)
        self.assertEqual(before_record.keys(),after_record.keys())
        self.assertEqual(before_record['remote_directory'],after_record['remote_directory'])
        self.assertNotIn('data_root',after_record);self.assertNotIn('remote_layout',after_record)
        self.assertEqual(before_commands,after_commands)
        self.assertEqual(before_observations,[]);self.assertEqual(after_observations,[])

    def test_future_root_binds_manifest_and_keeps_original_lock(self):
        script,record,commands,observations=self.stage_fixture(candidate,self.root/'candidate','/srv/tcad-dram-see-v4')
        text=script.decode()
        self.assertEqual(record['remote_layout'],candidate.DATA_ROOT_LAYOUT)
        self.assertEqual(record['data_root'],'/srv/tcad-dram-see-v4')
        self.assertEqual(record['remote_directory'],'/srv/tcad-dram-see-v4/runs/fixture-run')
        self.assertIn('cd /srv/tcad-dram-see-v4/runs/fixture-run',text)
        self.assertIn('exec 9>/control/root/.solver.lock',text)
        self.assertNotIn('/srv/tcad-dram-see-v4/.solver.lock',text)
        self.assertIn('OMP_NUM_THREADS=1',text);self.assertIn('--threads 1 --exit-on-failure',text)
        self.assertEqual(observations[0][1],['/srv/tcad-dram-see-v4',self.run_id,'/control/root'])
        self.assertFalse(any('mkdir -p' in command for command in commands))
        self.assertEqual(record['data_root_observation']['ssh_uid'],1000)

    def test_status_and_collect_follow_new_manifest_directory(self):
        folder,record=self.write_record('/srv/data',candidate.DATA_ROOT_LAYOUT)
        observed={'directory':record['remote_directory'],'status':'RUNNING','alive':True,'remote_exit_code':None}
        with patch.object(candidate,'remote_python',return_value=observed) as query:
            candidate.status_run(self.cfg,[],self.run_id)
        self.assertEqual(query.call_args.args[2],[record['remote_directory'],record['script_sha256']])
        def capture(ssh,command,**kwargs):
            self.assertTrue(command.startswith('set -e; cd /srv/data/runs/fixture-run;'))
            self.assertIn('exec 9>/control/root/.solver.lock;',command)
            raise RuntimeError('SOFTWARE_FIXTURE_STOP_BEFORE_REMOTE')
        with patch.object(candidate,'status_run',return_value={'status':'FINISHED','alive':False}),patch.object(candidate,'remote',side_effect=capture):
            with self.assertRaisesRegex(RuntimeError,'STOP_BEFORE_REMOTE'):
                candidate.collect_run(self.cfg,[],self.run_id)
        self.assertFalse((folder/'results.tar').exists())

    def test_existing_private_srv_root_and_sticky_tmp_parent_supported(self):
        fs=SyntheticLinuxFS();fs.add('/srv/tcad-dram-see-v4',1000,0o700)
        result=self.run_directory_guard(fs)
        self.assertEqual(result['remote_directory'],'/srv/tcad-dram-see-v4/runs/fixture-run')
        self.assertEqual(result['ssh_uid'],1000)
        self.assertEqual(fs.nodes['/srv/tcad-dram-see-v4/runs/fixture-run']['mode'],0o700)
        self.assertEqual(fs.fds,{})
        self.assertTrue(all(flags&fs.O_DIRECTORY and flags&fs.O_NOFOLLOW for _,flags,_ in fs.open_calls))
        fs=SyntheticLinuxFS()
        result=self.run_directory_guard(fs,'/var/tmp/generic-data')
        self.assertEqual(result['data_root'],'/var/tmp/generic-data')
        self.assertEqual(fs.nodes['/var/tmp/generic-data']['mode'],0o700)
        self.assertTrue(all(mode==0o700 for _,mode,_ in fs.mkdir_calls))

    def test_srv_parent_is_not_chmodded_or_elevated(self):
        fs=SyntheticLinuxFS()
        with self.assertRaises(PermissionError):self.run_directory_guard(fs)
        self.assertEqual(fs.nodes['/srv']['mode'],0o755)
        self.assertNotIn('/srv/tcad-dram-see-v4',fs.nodes)
        self.assertEqual(fs.fds,{})

    def test_symlink_owner_and_write_permissions_are_rejected(self):
        cases=[('/srv','symlink',0,0o755),('/srv/tcad-dram-see-v4','symlink',1000,0o700),
               ('/srv/tcad-dram-see-v4','directory',0,0o700),('/srv/tcad-dram-see-v4','directory',1000,0o770),
               ('/srv/tcad-dram-see-v4','directory',1000,0o707),('/srv','directory',2000,0o755),
               ('/srv','directory',0,0o777),('/srv/tcad-dram-see-v4/runs','directory',1000,0o777)]
        for path,kind,uid,mode in cases:
            with self.subTest(path=path,kind=kind,uid=uid,mode=mode):
                fs=SyntheticLinuxFS();fs.add('/srv/tcad-dram-see-v4',1000,0o700);fs.add(path,uid,mode,kind)
                before=dict(fs.nodes[path])
                with self.assertRaises((ValueError,OSError)):self.run_directory_guard(fs)
                self.assertEqual(fs.nodes[path],before);self.assertEqual(fs.fds,{})

    def test_real_path_change_or_existing_remote_id_is_rejected(self):
        fs=SyntheticLinuxFS();fs.add('/srv/tcad-dram-see-v4',1000,0o700)
        with patch.object(fs,'readlink',return_value='/wrong-physical-path'),self.assertRaisesRegex(ValueError,'real path differs'):
            self.run_directory_guard(fs)
        self.assertEqual(fs.fds,{})
        for legacy in (True,False):
            fs=SyntheticLinuxFS();fs.add('/srv/tcad-dram-see-v4',1000,0o700);fs.add('/srv/tcad-dram-see-v4/runs',1000,0o700)
            existing=('/control/root' if legacy else '/srv/tcad-dram-see-v4')+'/runs/fixture-run'
            fs.add(existing,1000,0o700);before=dict(fs.nodes[existing])
            with self.assertRaisesRegex(ValueError,'already exists'):self.run_directory_guard(fs)
            self.assertEqual(fs.nodes[existing],before);self.assertEqual(fs.fds,{})

    def test_field_source_directory_contract_accepts_the_new_root(self):
        source=ROOT/'experiments/dram-see-v4/source-field-audit-3d-r1/audit_fields.py'
        tree=ast.parse(source.read_text(encoding='utf-8'))
        node=next(item for item in tree.body if isinstance(item,ast.FunctionDef) and item.name=='remote_directory')
        namespace={'re':re,'require':lambda condition,message:None if condition else (_ for _ in ()).throw(ValueError(message))}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        new='/srv/tcad-dram-see-v4/runs/'+self.run_id
        self.assertEqual(namespace['remote_directory'](new,self.run_id),new)
        self.assertIn("'source-directory.txt': sr['remote_directory']+'\\n'",(ROOT/'experiments/dram-see-v4/continuous/data/field_adapter.py').read_text())

    def test_cli_forwards_explicit_root_and_rejects_bad_root_before_connection(self):
        project=self.root/'cli-project';project.mkdir()
        (project/'project.json').write_text(json.dumps({'name':'fixture-project','steps':[]}))
        argv=['tcad.py','run',str(project),'--run-id',self.run_id,'--detach','--data-root','/srv/data']
        with patch.object(sys,'argv',argv),patch.object(candidate,'connection',return_value=(self.cfg,[],'fixture')), \
                patch.object(candidate,'run_project',return_value={'status':'SOFTWARE_FIXTURE_NOT_NATIVE'}) as run,redirect_stdout(io.StringIO()):
            candidate.main()
        run.assert_called_once_with(self.cfg,[],project,self.run_id,True,data_root='/srv/data')
        with patch.object(sys,'argv',['tcad.py','run','unused','--data-root','../escape']),patch.object(candidate,'connection') as connection:
            with self.assertRaises(ValueError):candidate.main()
        connection.assert_not_called()


if __name__=='__main__':unittest.main()
