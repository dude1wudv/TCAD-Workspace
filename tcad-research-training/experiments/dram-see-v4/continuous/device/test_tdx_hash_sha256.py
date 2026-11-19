"""Focused local Tcl checks only; every metadata fixture is explicitly non-native."""
from pathlib import Path
from datetime import datetime,timezone
import csv
import hashlib
import json
import os
import tkinter
import unittest
import uuid

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OUT=ROOT/'local_runtime/dram-see-v4/continuous/device/tdx-metadata-fork-recovery-r1'
VENDOR=ROOT/'local_runtime/dram-see-v4/continuous/actual-usage/d3-r9-installed-tcl-sha256/sha256.tcl'
INSTALLED='/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/lib/tcllib1.16/sha1/sha256.tcl'
FIXTURE=OUT/('UNIT_FIXTURE_NOT_NATIVE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
FIXTURE.mkdir()
(FIXTURE/'SYNTHETIC_NOT_NATIVE').write_text('Local Tcl behavior tests; no native mesh, project, archive or scientific evidence.\n',encoding='utf-8')


class InProcessSHA(unittest.TestCase):
    def setUp(self):
        self.cwd=Path.cwd()
        self.folder=FIXTURE/self._testMethodName;self.folder.mkdir()
        self.assertEqual(hashlib.sha256(VENDOR.read_bytes()).hexdigest(),
                         '107ef278e9752467718d0cfaf7dac868f31b7c91ff80fbc4700a07eac939dee1')

    def tearDown(self):os.chdir(str(self.cwd))

    def interpreter(self,folder=None,library=None,initialize=True):
        folder=folder or self.folder
        vendor=folder/'installed-original-sha256.tcl'
        vendor.write_bytes(VENDOR.read_bytes() if library is None else library)
        helper=(HERE/'tdx_hash_sha256.tcl').read_text(encoding='utf-8')
        self.assertEqual(helper.count(INSTALLED),1)
        # Test-only path substitution in a labeled fixture; production helper
        # remains fixed to the original installed provider and expected raw SHA.
        helper=helper.replace(INSTALLED,vendor.as_posix())
        (folder/'tdx_hash_sha256.tcl').write_text(helper,encoding='utf-8')
        t=tkinter.Tcl()
        # A test cannot accidentally launch a process or load an extension.
        t.eval('rename exec {}; rename load {}')
        if initialize:
            t.call('source',str(folder/'tdx_hash_sha256.tcl'))
            t.call('::dram_tdx_sha256::initialize')
        return t

    def test_empty_abc_binary_and_multiple_chunks_match_hashlib(self):
        t=self.interpreter()
        vectors={'empty':b'','abc':b'abc','all-bytes':bytes(range(256)),
                 'multiple-chunks':bytes(range(256))*777+b'\x00\r\n\x80\xffEND'}
        results=[]
        for name,raw in vectors.items():
            path=self.folder/(name+'.bin');path.write_bytes(raw)
            actual=t.call('::dram_tdx_sha256::digest_file',str(path))
            expected=hashlib.sha256(raw).hexdigest()
            self.assertEqual(actual,expected,name)
            results.append(dict(name=name,bytes=len(raw),sha256=actual))
        (self.folder/'local-vector-results.json').write_text(json.dumps(dict(
            tcl_patchlevel=t.eval('info patchlevel'),vectors=results,native_called=False),indent=2)+'\n',encoding='utf-8')

    def test_safe_child_disables_fork_extension_and_package_resolution(self):
        t=self.interpreter();child=t.getvar('::dram_tdx_sha256::child')
        self.assertEqual(int(t.call('interp','issafe',child)),1)
        for command in ('exec','load','source','open','socket','interp'):
            self.assertEqual(t.call('interp','eval',child,'info commands '+command),'')
            with self.assertRaises(tkinter.TclError):t.call('interp','eval',child,command+' forbidden')
        self.assertEqual(t.call('interp','eval',child,'package unknown'),'')
        for package in ('tcllibc','sha256c','critcl'):
            self.assertEqual(t.call('interp','eval',child,'package provide '+package),'')
            self.assertEqual(t.call('interp','eval',child,'package versions '+package),'')
            with self.assertRaises(tkinter.TclError):t.call('interp','eval',child,'package require '+package)
        self.assertEqual(t.call('interp','eval',child,'set ::sha2::loaded'),'tcl')
        self.assertEqual(t.call('interp','eval',child,'package provide sha256'),'1.0.3')

    def test_same_length_source_change_is_rejected_and_child_removed(self):
        raw=VENDOR.read_bytes();changed=raw.replace(b'Copyright',b'copyright',1)
        self.assertEqual(len(raw),len(changed));self.assertNotEqual(raw,changed)
        t=self.interpreter(library=changed,initialize=False)
        t.call('source',str(self.folder/'tdx_hash_sha256.tcl'))
        with self.assertRaisesRegex(tkinter.TclError,'source digest differs'):
            t.call('::dram_tdx_sha256::initialize')
        self.assertEqual(int(t.getvar('::dram_tdx_sha256::initialized')),0)
        self.assertEqual(t.eval('set ::dram_tdx_sha256::child'),'')
        self.assertEqual(t.eval('interp children'),'')

    def test_unrepresentable_length_rejected_without_truncation(self):
        t=self.interpreter();path=self.folder/'small.bin';path.write_bytes(b'unchanged')
        t.setvar('test_oversize_path',str(path))
        t.eval('''rename file ::original_test_file
proc file {operation args} {
    if {$operation eq "size" && [lindex $args 0] eq $::test_oversize_path} {return 536870912}
    return [uplevel 1 [linsert $args 0 ::original_test_file $operation]]
}''')
        with self.assertRaisesRegex(tkinter.TclError,'full bit length'):
            t.call('::dram_tdx_sha256::digest_file',str(path))
        self.assertEqual(path.read_bytes(),b'unchanged')

    def observer(self,folder,mode):
        t=self.interpreter(folder=folder,initialize=False)
        mesh=folder/'fixture-not-native.tdr';mesh.write_bytes(b'UNIT_FIXTURE_NOT_NATIVE\x00\xff\r\n')
        (folder/'observe_tdr_topology.tcl').write_bytes((HERE/'observe_tdr_topology.tcl').read_bytes())
        t.call('cd',str(folder))
        t.setvar('cmd_args(rest)',t.call('list',str(mesh)))
        t.setvar('mock_mode',mode)
        t.eval('''
proc TdrFileOpen {args} {set ::mock_open 1}
proc TdrFileClose {path} {
    if {$::mock_mode eq "close-error"} {error "MOCK_CLOSE_ERROR_NOT_NATIVE"}
    if {$::mock_mode eq "change"} {
        set f [open $path a];fconfigure $f -encoding binary -translation binary;puts -nonewline $f X;close $f
    }
    if {$::mock_mode eq "remove"} {file delete $path}
    set ::mock_close 1
}
proc TdrFileGetNumGeometry {args} {return 1}
proc TdrGeometryGetDimension {args} {return 3}
proc TdrGeometryGetNumRegion {args} {return 1}
proc TdrGeometryGetNumState {args} {return 1}
proc TdrGeometryGetName {args} {return UNIT_FIXTURE_NOT_NATIVE}
proc TdrGeometryGetType {args} {return mixed_element}
proc TdrGeometryGetTransform {args} {return {1 0 0 0 1 0 0 0 1}}
proc TdrGeometryGetShift {args} {return {0 0 0}}
proc TdrRegionGetName {args} {return R.Silicon}
proc TdrRegionGetMaterial {args} {return Silicon}
proc TdrRegionGetType {args} {return bulk}
proc TdrRegionGetDimension {args} {return 3}
proc TdrRegionGetNumDataset {args} {return 0}
''')
        return t,mesh,folder/'observe_tdr_topology.tcl'

    def test_observer_before_after_provider_and_no_overwrite(self):
        t,mesh,script=self.observer(self.folder,'unchanged')
        t.call('source',str(script))
        with (self.folder/'tdr-topology-identity.csv').open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
        self.assertEqual([r['phase'] for r in rows],['BEFORE','AFTER'])
        self.assertEqual({r['sha256'] for r in rows},{hashlib.sha256(mesh.read_bytes()).hexdigest()})
        with (self.folder/'tdr-hash-provider.csv').open(encoding='utf-8',newline='') as f:p=list(csv.DictReader(f))
        self.assertEqual(len(p),1);self.assertEqual(p[0]['backend'],'tcl');self.assertEqual(p[0]['package_version'],'1.0.3')
        self.assertEqual(p[0]['safe_interpreter'],'1');self.assertEqual(p[0]['unsafe_commands_visible'],'')
        self.assertEqual(p[0]['source_sha256'],hashlib.sha256(VENDOR.read_bytes()).hexdigest())
        status=json.loads((self.folder/'tdr-region-status.json').read_bytes())
        self.assertTrue(status['completed']);self.assertFalse(status['scientific_acceptance'])
        originals={p.name:p.read_bytes() for p in self.folder.glob('tdr-*')}
        with self.assertRaisesRegex(tkinter.TclError,'Refusing to overwrite'):t.call('source',str(script))
        self.assertEqual(originals,{p.name:p.read_bytes() for p in self.folder.glob('tdr-*')})
        self.assertFalse((self.folder/'tdr-metadata-failure.csv').exists())

    def test_observer_failure_phase_and_original_stack_never_marks_completed(self):
        for mode,phase,origin in (('close-error','TDR_CLOSE','TdrFileClose'),('change','HASH_COMPARE','Original TDR changed')):
            folder=self.folder/mode;folder.mkdir()
            t,mesh,script=self.observer(folder,mode)
            with self.assertRaises(tkinter.TclError):t.call('source',str(script))
            self.assertFalse((folder/'tdr-region-status.json').exists())
            with (folder/'tdr-metadata-failure.csv').open(encoding='utf-8',newline='') as f:failure=list(csv.DictReader(f))
            self.assertEqual(len(failure),1);self.assertEqual(failure[0]['phase'],phase)
            self.assertIn(origin,failure[0]['error_info'])
            with (folder/'tdr-topology-identity.csv').open(encoding='utf-8',newline='') as f:identities=list(csv.DictReader(f))
            self.assertEqual([r['phase'] for r in identities],['BEFORE'] if mode=='close-error' else ['BEFORE','AFTER'])
            if mode=='change':self.assertNotEqual(identities[0]['sha256'],identities[1]['sha256'])

    def test_after_digest_failure_keeps_before_without_after_or_completed(self):
        t,mesh,script=self.observer(self.folder,'remove')
        with self.assertRaisesRegex(tkinter.TclError,'SHA input is missing'):
            t.call('source',str(script))
        self.assertFalse((self.folder/'tdr-region-status.json').exists())
        with (self.folder/'tdr-metadata-failure.csv').open(encoding='utf-8',newline='') as f:failure=list(csv.DictReader(f))
        self.assertEqual(failure[0]['phase'],'HASH_AFTER')
        self.assertIn('::dram_tdx_sha256::digest_file',failure[0]['error_info'])
        with (self.folder/'tdr-topology-identity.csv').open(encoding='utf-8',newline='') as f:identities=list(csv.DictReader(f))
        self.assertEqual([row['phase'] for row in identities],['BEFORE'])


if __name__=='__main__':
    print('Local Tcl fixtures only, not native:',FIXTURE,flush=True)
    unittest.main(verbosity=2)
