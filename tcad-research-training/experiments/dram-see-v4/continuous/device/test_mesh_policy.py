"""Focused new-policy checks. No synthetic successful D3 archive is constructed."""
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unittest
import uuid

import case_contract as C
import geometry_bridge as B
import mesh_policy as M
import prepare_case as P
import prospective

RUNTIME=P.ROOT/'local_runtime/dram-see-v4/continuous/device'
ORIGINAL=RUNTIME/'projects/20261017T080307Z-v4-continuous-b1-d3-r3'
FAILED=P.ROOT/'local_runtime/runs/20261017T080307Z-v4-continuous-b1-d3-r3'
FIXTURE=RUNTIME/('UNIT_FIXTURE_NOT_NATIVE-mesh-policy-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])


def request(variant='main'):
    return dict(schema=C.SCHEMA_MESH,kind='dc',gate_top_depth_nm=80,sn_junction_depth_nm=87,
                dimension=3,variant=variant,mesh_policy=M.POLICY_ID)


class GradientMeshPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_manifest=(ORIGINAL/'input-manifest.json').read_bytes()
        cls.files,cls.model=P.producer_payload(request())
        cls.fine,_=P.producer_payload(request('mesh'))
        cls.policy=json.loads(cls.files['mesh-policy.json'])
        FIXTURE.mkdir(exist_ok=False)
        (FIXTURE/'SYNTHETIC_NOT_NATIVE').write_text('Declared payload tests only. No native source, completed D3 or A0 qualification.\n',encoding='utf-8')
        for variant,files in (('main',cls.files),('mesh',cls.fine)):
            folder=FIXTURE/variant;folder.mkdir()
            for name,raw in files.items():(folder/name).write_bytes(raw)

    def test_explicit_selection_and_legacy_2d_bytes(self):
        self.assertEqual(C.validate(request())['mesh_policy'],M.POLICY_ID)
        for bad in (dict(request(),schema=C.SCHEMA),dict(request(),dimension=2),
                    dict(request(),mesh_policy='automatic'),dict(request(),kind='transient')):
            with self.assertRaises(ValueError):C.validate(bad)
        old=prospective.module(ORIGINAL/'generator-prepare_case.py','_before_gradient_frozen_prepare_case')
        req=dict(schema=C.SCHEMA,kind='dc',gate_top_depth_nm=80,sn_junction_depth_nm=87,dimension=2,variant='main')
        before,_=old.producer_payload(req);after,_=P.producer_payload(req)
        self.assertEqual(before,after)
        self.assertNotIn('mesh-policy.json',after)

    def test_physics_deck_and_original_measurements_are_unchanged(self):
        for name in P.PHYSICS_FILES+('model.proposed.json','device.cmd','numerical-method.json'):
            self.assertEqual(self.files[name],(ORIGINAL/name).read_bytes(),name)
        before=json.loads((ORIGINAL/'geometry-contract.json').read_bytes())
        after=json.loads(self.files['geometry-contract.json'])
        self.assertEqual({k:v for k,v in before.items() if k!='mesh'},
                         {k:v for k,v in after.items() if k!='mesh'})
        old=json.loads((ORIGINAL/'measurement-plan.json').read_bytes())
        new=json.loads(self.files['measurement-plan.json'])
        for name in ('measurements','contact_probes','material_probes','comparison_policy'):
            self.assertEqual(old[name],new[name],name)
        self.assertEqual(old['expected_geometry']['mesh'],self.policy['legacy_mesh_contract'])
        self.assertFalse(self.policy['native_accuracy_qualified'])

    def test_partitions_boundaries_and_all_length_refinement(self):
        windows={v['name']:v for v in self.policy['volume_refinements']}
        self.assertEqual(len(windows),11)
        self.assertEqual(windows['ActiveDopingCore']['physical_min_um'],[-.02,-.07,0.])
        self.assertEqual(windows['ActiveDopingCore']['max_size_um'],[.001,.005,.001])
        for name in ('ActiveDopingLeft','ActiveDopingRight'):
            self.assertEqual(windows[name]['max_size_um'],[.005,.005,.001])
            self.assertEqual(windows[name]['physical_max_um'][2],.25)
        self.assertEqual(windows['ContactSource']['physical_min_um'],[-.074,-.015,0.])
        self.assertEqual(windows['ContactSource']['physical_max_um'],[-.03,.015,.04])
        track=[windows['AlphaTrack'+s] for s in ('Near','Bulk','End')]
        self.assertEqual([[w['physical_min_um'][2],w['physical_max_um'][2]] for w in track],[[0.,.25],[.25,.98],[.98,1.]])
        original_track=next(v for v in self.policy['legacy_mesh_contract']['windows'] if v['name']=='AlphaTrack')
        for window in track:
            self.assertEqual(window['physical_min_um'][:2],original_track['physical_min_um'][:2])
            self.assertEqual(window['physical_max_um'][:2],original_track['physical_max_um'][:2])
        self.assertEqual(track[1]['max_size_um'],[.005,.005,.02])
        self.assertTrue(all(w['materials']==['Silicon'] for w in track))
        interfaces=self.policy['interface_refinements']
        self.assertEqual([v['first_step_um'] for v in interfaces],[.005,.001])
        self.assertTrue(all(v['DoubleSide'] and v['factor']==1.5 for v in interfaces))
        fine=json.loads(self.fine['mesh-policy.json'])
        for key in ('volume_refinements','interface_refinements'):
            for main,half in zip(self.policy[key],fine[key]):
                self.assertEqual(main['name'],half['name'])
                for field in ('physical_min_um','physical_max_um'):
                    self.assertEqual(main[field],half[field])
                for field in ('max_size_um','min_size_um'):
                    self.assertEqual(half[field],[x*.5 for x in main[field]])
                if key=='interface_refinements':self.assertEqual(half['first_step_um'],main['first_step_um']*.5)

    def test_only_established_sde_forms_and_frozen_mesh_binding(self):
        original=(ORIGINAL/'geometry-with-measurements.scm').read_text(encoding='utf-8')
        actual=self.files['geometry-with-measurements.scm'].decode()
        before=original.split('(sdedr:define-refeval-window "Window.All"',1)[0]
        self.assertEqual(before,actual.split(M.BEGIN,1)[0])
        used=set(re.findall(r'\((sdedr:[A-Za-z-]+)',M.render_block(self.policy)))
        established=set(re.findall(r'\((sdedr:[A-Za-z-]+)',original))
        self.assertTrue(used<=established)
        self.assertNotIn('"Window.ActiveDoping"',actual)
        self.assertNotIn('"Window.AlphaTrack"',actual)
        self.assertNotIn('"Mesh.Interfaces"',actual)
        cfg=dict(mesh_policy_id=M.POLICY_ID,mesh_policy_sha256=P.digest(self.files['mesh-policy.json']))
        B.geometry_validate_mesh_policy_payload(self.files,cfg,require_sde=True)
        bad=dict(self.files);bad['geometry-with-measurements.scm']=bad['geometry-with-measurements.scm'].replace(b'"Cuboid"',b'"Rectangle"',1)
        with self.assertRaisesRegex(ValueError,'mesh block differs'):
            B.geometry_validate_mesh_policy_payload(bad,cfg,require_sde=True)
        missing={name:raw for name,raw in self.files.items() if name not in M.FILES}
        with self.assertRaisesRegex(ValueError,'missing its original files'):
            B.geometry_validate_mesh_policy_payload(missing,{})
        for name in ('geometry_bridge.py','case_contract.py','mesh_policy.py'):
            ast.parse((P.HERE/name).read_text(encoding='utf-8'),feature_version=(3,6))

    def test_v1_two_bit_a0_keeps_deck_and_inherits_exact_policy(self):
        old={name:(ORIGINAL/name).read_bytes() for name in P.PHYSICS_FILES+('model.proposed.json','geometry-contract.json')}
        for bit in (0,1):
            for variant,producer in (('main',self.files),('time',self.files),('mesh',self.fine)):
                req=dict(schema=C.SCHEMA,kind='transient',gate_top_depth_nm=80,sn_junction_depth_nm=87,
                    dimension=3,variant=variant,stored_bit=bit,source_case='A0',d3_source_run='UNIT_FIXTURE_NOT_NATIVE')
                a=P.transient_payload(self.model,req,{'declared_only':True},producer)
                b=P.transient_payload(self.model,req,{'declared_only':True},old)
                for name in P.PHYSICS_FILES+('model.proposed.json','device.cmd','numerical-method.json','parameter-binding.json'):
                    self.assertEqual(a[name],b[name],name)
                for name in M.FILES:self.assertEqual(a[name],producer[name])
                self.assertNotIn(b'HeavyIon(',a['device.cmd'])
                self.assertFalse(json.loads(a['source-contract.json'])['native_qualified'])
                self.assertEqual(json.loads(a['controlled-parameters.json'])['bound_files_sha256']['mesh-policy.json'],P.digest(producer['mesh-policy.json']))
                (FIXTURE/('a0-b'+str(bit)+'-'+variant+'.cmd')).write_bytes(a['device.cmd'])

    def test_original_d3_input_admits_but_real_oom_archive_cannot_supply_a0(self):
        runner_sha=P.first.sha(P.ROOT/'scripts/tcad.py')
        B.geometry_admit(ORIGINAL,json.loads((ORIGINAL/'project.json').read_bytes()),runner_sha)
        self.assertEqual((ORIGINAL/'input-manifest.json').read_bytes(),self.original_manifest)
        manifest=json.loads((FAILED/'manifest.json').read_bytes())
        self.assertEqual(manifest['remote_exit_code'],137)
        self.assertEqual(manifest['state'],'FAILED_COLLECTED')
        cfg=dict(source_run_directory=str(FAILED.resolve()),producer_run_id=FAILED.name)
        with self.assertRaisesRegex(ValueError,'origin/completion differs'):
            B.geometry_source_bundle(RUNTIME/'not-created-old-oom-a0',cfg)


if __name__=='__main__':
    print('Preserved mesh-policy input-only evidence:',FIXTURE)
    unittest.main(verbosity=2)
