"""Focused real-source input checks; no fabricated native success or solver call."""
import ast
import copy
import io
import json
from pathlib import Path
import tarfile
import unittest
import uuid
from unittest.mock import patch

import case_contract
import dc_continuation as dc
import geometry_bridge as bridge

ROOT=Path(__file__).resolve().parents[4]
OUT=ROOT/'local_runtime/dram-see-v4/continuous/device/d3-dc-geometry-checkpoint-r1'
R12=ROOT/'local_runtime/runs/20261017T154137Z-v4-continuous-b1-d3-r12'


class Overlay:
    def __init__(self,reader,changes):self.reader,self.changes=reader,changes
    def read(self,n):return self.changes[n] if n in self.changes else self.reader.read(n)
    def digest(self,n):return dc.sha(self.changes[n]) if n in self.changes else self.reader.digest(n)
    def size(self,n):return len(self.changes[n]) if n in self.changes else self.reader.size(n)
    def exists(self,n):return n in self.changes or self.reader.exists(n)
    def stream(self,n):return io.BytesIO(self.changes[n]) if n in self.changes else self.reader.stream(n)


class DCCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request=case_contract.validate(json.loads((OUT/'request-r7.json').read_text(encoding='utf-8')))
        cls.package=dc.source_package(R12,cls.request)
        cls.binding=cls.package['binding'];cls.selector=cls.package['selector']
        cls.folder=OUT/('UNIT_FIXTURE_NOT_NATIVE-input-only-'+uuid.uuid4().hex[:12]);cls.folder.mkdir()
        for name,raw in cls.package['files'].items():
            p=cls.folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        (cls.folder/'controlled-request.json').write_bytes(dc.encoded(cls.request))
        (cls.folder/'SYNTHETIC_NOT_NATIVE').write_text('Original bytes in a unit input fixture; no new native run.\n',encoding='utf-8')
        cls.cfg=dict(cls.package['source_cfg'],mode=dc.MODE,run_id=cls.folder.name,producer_run_id=cls.folder.name,
            dc_source_binding_sha256=dc.sha(cls.package['files']['dc-source-binding.json']),
            geometry_selector_file=dc.SELECTOR_FILE,geometry_selector_sha256=dc.sha(cls.package['files'][dc.SELECTOR_FILE]),
            geometry_report_file=dc.REPORT_FILE,geometry_producer_run_id=R12.name,
            geometry_validation_sha256=cls.selector['report_sha256'])
        dc.stage(cls.folder,cls.cfg)
        cls.reader=dc.metadata_module().FolderReader(cls.folder)
        (OUT/'staged-input-only.json').write_bytes(dc.encoded(dict(path=str(cls.folder),
            source_manifest_sha256=cls.binding['source_manifest_sha256'],dc_source_binding_sha256=cls.cfg['dc_source_binding_sha256'],
            geometry_selector_sha256=cls.cfg['geometry_selector_sha256'],geometry_report_sha256=cls.selector['report_sha256'],
            original_state='FAILED_COLLECTED',original_step006=137,actual_new_native_results=False)))

    def test_real_r12_source_preserved_and_no_current_geometry_fabricated(self):
        self.assertEqual(self.binding['source_manifest_sha256'],'88668acc1c62ec816db4077cc56ab3c009b3fe5b0ad0a84f88b9e9b1f318c2ea')
        self.assertEqual(self.binding['source_archive_sha256'],'800e8a375aca4b99a97c7a0a95f6388c8462cfff219d67deb752c369eb3bd67e')
        self.assertEqual(self.selector['report_sha256'],'414294e20c278c8e7ad0fa4353ee9610c9ef45d4f2b091f9caff9805494238fe')
        report=dc.obj(self.reader.read(dc.REPORT_FILE))
        self.assertEqual(report['producer_run_id'],R12.name)
        self.assertEqual(set(self.selector),{'schema','report_file','report_sha256','producer_run_id','evidence_members'})
        self.assertEqual(set(self.selector['evidence_members']),set(report['evidence_sha256']))
        self.assertEqual(len(set(self.selector['evidence_members'].values())),len(report['evidence_sha256']))
        empty=[]
        for original,stored in self.selector['evidence_members'].items():
            self.assertEqual(self.reader.digest(stored),report['evidence_sha256'][original])
            if self.reader.size(stored)==0:empty.append(original)
        self.assertEqual(len(empty),39)
        self.assertEqual(self.reader.read(dc.PREFIX+'step-005-svisual-exit-code.txt').strip(),b'0')
        self.assertEqual(self.reader.read(dc.PREFIX+'step-006-sdevice-exit-code.txt').strip(),b'137')
        self.assertFalse(any(self.reader.exists(n) for n in dc.FORBIDDEN_CURRENT))
        self.assertFalse(self.reader.exists('dc-completed-binding.json'))
        self.assertEqual(self.cfg['active_solver_mesh_sha256'],self.reader.digest('cell_msh.tdr'))
        for n,h in self.binding['identical_inputs_sha256'].items():self.assertEqual(self.reader.digest(n),h)

    def test_closed_recipe_and_changed_original_evidence_rejected(self):
        for update in ({'schema':case_contract.SCHEMA_ACTIVE_MESH},{'continuation_recipe':'arbitrary'},
                       {'geometry_report_file':'anything.json'},{'mesh_representation':'ogawa'}):
            with self.assertRaises(ValueError):case_contract.validate(dict(self.request,**update))
        for name in ('dc-source-bindings/material-measurements.csv','cell_msh.tdr',
                     'dc-source-bindings/step-005-svisual-exit-code.txt'):
            with self.assertRaisesRegex(ValueError,'source import/member/index differs'):
                dc.verify(Overlay(self.reader,{name:b'TAMPERED_INPUT_ONLY'}),self.cfg,self.request)
        changed=copy.deepcopy(self.binding);changed['source_remote_exit_code']=0
        with self.assertRaisesRegex(ValueError,'original005 success/006 failure'):
            dc.verify(Overlay(self.reader,{'dc-source-binding.json':dc.encoded(changed)}),self.cfg,self.request)
        changed=copy.deepcopy(self.binding);changed['imports'][dc.REPORT_FILE]['member']='material-measurements.csv'
        with self.assertRaisesRegex(ValueError,'source import/member/index differs'):
            dc.verify(Overlay(self.reader,{'dc-source-binding.json':dc.encoded(changed)}),self.cfg,self.request)

    def test_failed_r12_cannot_supply_a0_or_completed_dc_proof(self):
        with self.assertRaisesRegex(ValueError,'origin/completion differs'):
            bridge.geometry_source_bundle(OUT/'NOT_A_RUN',dict(producer_run_id=R12.name,source_run_directory=str(R12)))
        manifest=dc.obj((R12/'manifest.json').read_bytes())
        with self.assertRaisesRegex(ValueError,'not an actual completed collection'):
            dc.validate_completed(self.reader,manifest,self.cfg,io.BytesIO(b'not inspected because source failed'))
        for n in dc.FORBIDDEN_CURRENT:bridge.geometry_relative(n)
        for n in dc.evidence_hashes(self.reader):bridge.geometry_relative(n)
        with self.assertRaisesRegex(ValueError,'Unsafe evidence'):
            bridge.geometry_relative('dc-source-bindings/../device.cmd')

    def test_real_root_to_native_capture_and_false_chain_rejected(self):
        source=dc.SourceReader(self.reader)
        manifest=dc.obj(self.reader.read(dc.PREFIX+'manifest.json'))
        dc.validate_capture(source,manifest,5,'svisual')
        name='step-005-svisual-process-observation.json';original=dc.obj(source.read(name))
        for change in ('reverse','wrong_parent','wrapper_executable'):
            bad=copy.deepcopy(original)
            if change=='reverse':bad['parent_chain'].reverse()
            elif change=='wrong_parent':bad['parent_chain'][-1]['ppid']+=1
            else:bad['native_executable']='/usr/bin/bash'
            with self.assertRaises(ValueError):
                dc.validate_capture(Overlay(source,{name:dc.encoded(bad)}),manifest,5,'svisual')
        with self.assertRaisesRegex(ValueError,'native/admission nonzero'):
            dc.validate_capture(Overlay(source,{'step-005-svisual-exit-code.txt':b'137\n'}),manifest,5,'svisual')

    def test_old_r5_r6_selector_semantics_and_python36_surface(self):
        # Pure mode/request boundaries only; passed r5/r6 topology is not rerun.
        old=json.loads((ROOT/'local_runtime/dram-see-v4/continuous/device/d3-v16-solver-recovery-r1/request-r6.json').read_text())
        self.assertEqual(case_contract.validate(old),old)
        with self.assertRaises(ValueError):case_contract.validate(dict(old,dc_source_run=str(R12)))
        self.assertEqual(list(bridge.GEOMETRY_STEPS[5:]),[('sdevice',['device.cmd'])])
        self.assertEqual(dc.RUNTIME_FILES,('dc_continuation.py','metadata_continuation.py','mesh_continuation.py'))
        for name in ('dc_continuation.py','geometry_bridge.py','prepare_case.py','case_contract.py'):
            text=(Path(__file__).parent/name).read_text(encoding='utf-8')
            ast.parse(text,filename=name,feature_version=(3,6))
            for forbidden in ('.is_relative_to(','.removeprefix(','.removesuffix(','hashlib.file_digest(','math.prod(',
                              'datetime.fromisoformat(','capture_output=', 'text=True'):
                self.assertNotIn(forbidden,text)


class DCExportMechanicsTests(unittest.TestCase):
    def test_owning_archive_external_receipt_and_generated_proof_are_distinct(self):
        # Mechanical-only fixture: source qualification is deliberately mocked,
        # with no native manifest, success status or scientific result fabricated.
        folder=OUT/('UNIT_FIXTURE_NOT_NATIVE-export-map-'+uuid.uuid4().hex[:12]);folder.mkdir()
        archive=folder/'fixture.tar';receipt=folder/'fixture-receipt.json'
        old=b'UNIT_FIXTURE original mesh log\n';owned=b'UNIT_FIXTURE original DC project\n'
        receipt.write_bytes(b'UNIT_FIXTURE frozen external receipt\n')
        with tarfile.open(archive,'w') as t:
            for name,raw in (('cell_msh.log',old),('project.json',owned)):
                row=tarfile.TarInfo(name);row.size=len(raw);t.addfile(row,io.BytesIO(raw))
        generated=b'UNIT_FIXTURE generated binding structure only\n'
        exports={'cell_msh.log':dc.sha(old),'dc-completed-bindings/project.json':dc.sha(owned),
            'dc-completed-bindings/manifest.json':dc.file_sha(receipt),'dc-completed-binding.json':dc.sha(generated)}
        bundle=dict(archive=archive,archive_sha256=dc.file_sha(archive),exports=exports,
            export_members={'dc-completed-bindings/project.json':'project.json'},
            external_files={'dc-completed-bindings/manifest.json':dict(path=str(receipt),sha256=dc.file_sha(receipt))},
            generated_files={'dc-completed-binding.json':generated})
        target=folder/'payload';target.mkdir()
        with patch.object(bridge,'geometry_source_bundle',return_value=bundle),patch.object(bridge,'geometry_input_hashes',return_value=exports):
            bridge.geometry_stage_reuse(target,dict(mode='reuse'))
        for name,expected in exports.items():self.assertEqual(dc.file_sha(target/name),expected)
        self.assertFalse((target/'project.json').exists())
        bad=folder/'bad';bad.mkdir();receipt.write_bytes(b'CHANGED UNIT_FIXTURE receipt')
        with patch.object(bridge,'geometry_source_bundle',return_value=bundle),patch.object(bridge,'geometry_input_hashes',return_value=exports):
            with self.assertRaisesRegex(ValueError,'Original DC proof changed'):
                bridge.geometry_stage_reuse(bad,dict(mode='reuse'))


if __name__=='__main__':unittest.main()
