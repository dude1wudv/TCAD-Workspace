"""Focused recovery tests. All generated archives are software fixtures."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import subprocess
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[4]
spec=importlib.util.spec_from_file_location('current_tcad',ROOT/'scripts/tcad.py')
tcad=importlib.util.module_from_spec(spec);spec.loader.exec_module(tcad)


class RecoveryTests(unittest.TestCase):
    def test_live_descendant_lock_prevents_snapshot(self):
        evidence={'state':'EXECUTED','remote_directory':'/original/existing',
                  'input_sha256':{},'script_sha256':'fixture','steps':[],'tool_evidence':{}}
        def locked(ssh,script,**kwargs):
            self.assertIn('exec 9>/original/.solver.lock; flock -n 9 || exit 75;',script)
            raise subprocess.CalledProcessError(75,['ssh'])
        with tempfile.TemporaryDirectory() as d,patch.object(tcad,'read_manifest',return_value=(Path(d),evidence)),patch.object(tcad,'status_run',return_value={'status':'FINISHED','alive':False}),patch.object(tcad,'remote',side_effect=locked):
            with self.assertRaises(subprocess.CalledProcessError):
                tcad.collect_run({'remote_root':'/original'},[],'existing')
            self.assertFalse((Path(d)/'results.tar').exists())

    def test_repeated_id_only_queries_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'local_runtime/runs/same-id';folder.mkdir(parents=True)
            (folder/'manifest.json').write_text(json.dumps({
                'schema':'tcad-native-run-r2','state':'RUNNING','run_id':'same-id',
                'remote_directory':'/original/runs/same-id',
            }))
            with patch.object(tcad,'ROOT',root),patch.object(tcad,'original_ownership') as owner,patch.object(tcad,'status_run',return_value={'status':'RUNNING'}) as status,patch.object(tcad,'_run_project') as submit:
                value=tcad.run_project({'remote_root':'/original'},[],root,'same-id',True)
            self.assertEqual(value['status'],'RUNNING');status.assert_called_once();submit.assert_not_called()

    def test_unknown_original_blocks_new_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'local_runtime/runs/old-id';folder.mkdir(parents=True)
            (folder/'manifest.json').write_text(json.dumps({'schema':'tcad-native-run-r2','state':'LAUNCH_UNCERTAIN','run_id':'old-id'}))
            with patch.object(tcad,'ROOT',root),patch.object(tcad,'status_run',return_value={'status':'START_UNCONFIRMED'}),patch.object(tcad,'remote') as remote:
                with self.assertRaisesRegex(RuntimeError,'original outstanding run'):tcad.assert_no_active_run({},[])
                remote.assert_not_called()

    def test_running_original_cannot_be_collected(self):
        with patch.object(tcad,'read_manifest',return_value=(Path('.'),{'state':'RUNNING'})),patch.object(tcad,'status_run',return_value={'status':'RUNNING','alive':True}),patch.object(tcad,'remote') as remote:
            with self.assertRaisesRegex(RuntimeError,'completed original'):tcad.collect_run({},[],'existing')
            remote.assert_not_called()

    def test_collection_keeps_disconnect_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            data={'schema':'tcad-native-run-r2','state':'EXECUTED','run_id':'existing','remote_directory':'/original/existing','remote_exit_code':0,'ssh_exit_code':255,'input_sha256':{'device.cmd':hashlib.sha256(b'input').hexdigest()},'script_sha256':hashlib.sha256(b'script').hexdigest(),'steps':[{'outputs':['result.plt']}],'tool_evidence':{'step-001-sdevice':{'raw_exit_file':'step-001-sdevice-exit-code.txt'}},'tool_exit_codes':{}}
            payload={'device.cmd':b'input','run.sh':b'script','result.plt':b'result','exit-code.txt':b'0\n','metadata-sdevice-version-exit-code.txt':b'0\n','step-001-sdevice-exit-code.txt':b'0\n'}
            archive=self.archive(payload)
            def remote(*args,**kwargs):
                if 'stdout' in kwargs:
                    kwargs['stdout'].write(archive)
                    return type('Result',(),{'returncode':0})()
                return type('Result',(),{'stdout':json.dumps({'sha256':hashlib.sha256(archive).hexdigest(),'bytes':len(archive)})})()
            with patch.object(tcad,'read_manifest',side_effect=lambda *a:(folder,data)),patch.object(tcad,'status_run',return_value={'status':'FINISHED','alive':False}),patch.object(tcad,'remote',side_effect=remote):
                result=tcad.collect_run({'remote_root':'/original'},[],'existing')
            self.assertEqual(result['status'],'COLLECTED');self.assertEqual(result['ssh_exit_code'],255)
            self.assertTrue(data['collection_verified']);self.assertTrue((folder/'results.tar').is_file())

    @staticmethod
    def archive(payload):
        index={k:{'size':len(v),'sha256':hashlib.sha256(v).hexdigest()} for k,v in payload.items()}
        payload=dict(payload,**{'_collection-members.json':json.dumps(index).encode()})
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w') as archive:
            for name,raw in payload.items():
                member=tarfile.TarInfo(name);member.size=len(raw);archive.addfile(member,io.BytesIO(raw))
        return stream.getvalue()

    def test_input_mismatch_still_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.tar';path.write_bytes(self.archive({'device.cmd':b'wrong','run.sh':b'script'}))
            evidence={'input_sha256':{'device.cmd':hashlib.sha256(b'right').hexdigest()},'script_sha256':hashlib.sha256(b'script').hexdigest(),'remote_exit_code':1}
            with self.assertRaisesRegex(ValueError,'provenance differs'):tcad.verify_archive(path,evidence)


if __name__=='__main__':unittest.main()
