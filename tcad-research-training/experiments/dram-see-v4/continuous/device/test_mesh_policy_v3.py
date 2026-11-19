"""New r3 partitions/finite algorithm parameter and directly affected dispatch only."""
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
import uuid

import case_contract as C
import geometry_bridge as B
import mesh_policy_registry as M
import mesh_policy_v3 as R3
import prepare_case as P

RUNTIME=P.ROOT/'local_runtime/dram-see-v4/continuous/device'
DELIVERY=RUNTIME/'gradient-mesh-r3-r1'
R1_PROJECT=RUNTIME/'projects/20261017T084908Z-v4-continuous-b1-d3-r4'
R2_PROJECT=RUNTIME/'projects/20261017T092203Z-v4-continuous-b1-d3-r5'
ANALYSIS=RUNTIME/'mesh-r5-density-analysis-r1/analysis.json'
FIXTURE=DELIVERY/('UNIT_FIXTURE_NOT_NATIVE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])


def request(depth=80,sn=87,variant='main',policy=R3.POLICY_ID):
    return dict(schema=C.SCHEMA_MESH,kind='dc',gate_top_depth_nm=depth,sn_junction_depth_nm=sn,
                dimension=3,variant=variant,mesh_policy=policy)


class GradientMeshR3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files,cls.model=P.producer_payload(request())
        cls.fine,_=P.producer_payload(request(variant='mesh'))
        cls.policy=json.loads(cls.files['mesh-policy.json'])
        cls.old=json.loads((R2_PROJECT/'mesh-policy.json').read_bytes())
        FIXTURE.mkdir(parents=True,exist_ok=False)
        (FIXTURE/'SYNTHETIC_NOT_NATIVE').write_text('Only input declarations and new mesh-policy checks; no native D3/A0 success.\n',encoding='utf-8')
        for variant,files in (('main',cls.files),('mesh',cls.fine)):
            target=FIXTURE/variant;target.mkdir()
            for name,raw in files.items():(target/name).write_bytes(raw)

    def test_exact_approved_eleven_families_and_unchanged_other_rules(self):
        expected=json.loads(ANALYSIS.read_bytes())['proposed_local_directional_candidate']['proposed_families'][:11]
        current=self.policy['volume_refinements']
        self.assertEqual({w['directional_family'] for w in current if 'directional_family' in w},{w['name'] for w in expected})
        for family in expected:
            windows=[w for w in current if w.get('directional_family')==family['name']]
            self.assertEqual(len(windows),len(family['bounds_nm']),family['name'])
            for window,bounds in zip(windows,family['bounds_nm']):
                for field,values in zip(('physical_min_um','physical_max_um'),bounds):
                    for got,expected_nm in zip(window[field],values):self.assertAlmostEqual(got,expected_nm/1000.,places=14)
                self.assertEqual(window['max_size_um'],[v/1000. for v in family['max_xyz_nm']])
                if family['name'].startswith('STI'):
                    self.assertEqual(window['regions'],['R.Silicon','R.STI.minus','R.STI.plus'])
                    self.assertEqual(window['materials'],[])
        old={w['name']:w for w in self.old['volume_refinements']}
        new={w['name']:w for w in current}
        self.assertNotIn('GateOxide',new)
        for name,value in old.items():
            if name!='GateOxide':self.assertEqual(new[name],value,name)
        self.assertEqual(self.policy['interface_refinements'],self.old['interface_refinements'][:1])
        self.assertEqual(len([w for w in current if w['name'].startswith('Contact')]),2)

    def test_nine_parameter_combinations_preserve_physics_and_all_measurements(self):
        records=[]
        for depth in (70,80,90):
            for sn in (82,87,92):
                with self.subTest(gate=depth,sn=sn):
                    files,model=P.producer_payload(request(depth,sn))
                    previous,_=P.producer_payload(request(depth,sn,policy='dram-see-v4-gradient-mesh-r2'))
                    g=json.loads(files['geometry-contract.json']);g0=json.loads(previous['geometry-contract.json'])
                    for name in P.PHYSICS_FILES+('model.proposed.json','device.cmd','numerical-method.json'):
                        self.assertEqual(files[name],previous[name],name)
                    self.assertEqual({k:v for k,v in g.items() if k!='mesh'},{k:v for k,v in g0.items() if k!='mesh'})
                    plan=json.loads(files['measurement-plan.json']);old_plan=json.loads(previous['measurement-plan.json'])
                    for key in ('measurements','contact_probes','material_probes','comparison_policy'):
                        self.assertEqual(plan[key],old_plan[key],key)
                    self.assertEqual(len(plan['measurements']),148)
                    policy=json.loads(files['mesh-policy.json'])
                    top=next(w for w in policy['volume_refinements'] if w['name']=='GateTopNormalZ')
                    self.assertAlmostEqual(top['physical_min_um'][2],depth/1000.-.008,places=14)
                    self.assertAlmostEqual(top['physical_max_um'][2],depth/1000.+.002,places=14)
                    self.assertEqual(model['doping']['sn_junction_depth_nm'],sn)
                    for window in policy['volume_refinements']:
                        for axis,low,high in zip('xyz',window['physical_min_um'],window['physical_max_um']):
                            self.assertTrue(g['domain_um'][axis][0]<=low<high<=g['domain_um'][axis][1])
                    records.append(dict(gate_top_depth_nm=depth,sn_junction_depth_nm=sn,
                                        geometry_sha256=P.digest(files['geometry-contract.json']),measurements=len(plan['measurements'])))
        (FIXTURE/'nine-declared-geometries.json').write_bytes(P.raw_json(records))

    def test_h2_all_steps_and_fixed_physical_partitions(self):
        fine=json.loads(self.fine['mesh-policy.json'])
        for key in ('volume_refinements','interface_refinements'):
            self.assertEqual(len(self.policy[key]),len(fine[key]))
            for main,half in zip(self.policy[key],fine[key]):
                for field in ('name','physical_min_um','physical_max_um','materials','regions','directional_family'):
                    self.assertEqual(main.get(field),half.get(field))
                for field in ('max_size_um','min_size_um'):
                    self.assertEqual(half[field],[v*.5 for v in main[field]])
                if key=='interface_refinements':self.assertEqual(half['first_step_um'],main['first_step_um']*.5)
        self.assertEqual(fine['delaunizer'],self.policy['delaunizer'])

    def test_new_api_only_in_r3_block_and_unchanged_sde_elsewhere(self):
        text=self.files['geometry-with-measurements.scm'].decode()
        block=R3.render_block(self.policy)
        self.assertEqual(text.count('(sdesnmesh:delaunizer'),1)
        self.assertIn('(sdesnmesh:delaunizer "maxPoints" 2147483647)',block)
        self.assertLess(text.index('(sdesnmesh:delaunizer'),text.index('(sdedr:write-cmd-file'))
        self.assertNotIn('"type" "constrained"',block)
        self.assertNotIn('"InterfacesActive"',block)
        for region in ('R.Silicon','R.STI.minus','R.STI.plus'):
            self.assertIn('"region" "'+region+'"',block)
        self.assertNotIn('"region" "R.Trench"',block)
        old=(R2_PROJECT/'geometry-with-measurements.scm').read_text(encoding='utf-8')
        old_start='; BEGIN EXPLICIT MESH POLICY dram-see-v4-gradient-mesh-r2'
        old_end='; END EXPLICIT MESH POLICY dram-see-v4-gradient-mesh-r2\n'
        old_outside=old.split(old_start)[0]+old.split(old_end)[1]
        new_outside=text.split(R3.BEGIN)[0]+text.split(R3.END+'\n')[1]
        old_identity='; geometry_contract_sha256='+P.digest((R2_PROJECT/'geometry-contract.json').read_bytes())
        new_identity='; geometry_contract_sha256='+P.digest(self.files['geometry-contract.json'])
        self.assertEqual(old_outside.count(old_identity),1)
        self.assertEqual(new_outside.count(new_identity),1)
        self.assertEqual(new_outside,old_outside.replace(old_identity,new_identity,1))

    def test_r1_r2_and_2d_directly_affected_dispatch_preserves_old_payloads(self):
        for policy,folder in (('dram-see-v4-gradient-mesh-r1',R1_PROJECT),('dram-see-v4-gradient-mesh-r2',R2_PROJECT)):
            rebuilt,_=P.producer_payload(request(policy=policy))
            for name,raw in rebuilt.items():self.assertEqual(raw,(folder/name).read_bytes(),name)
            self.assertNotIn(b'sdesnmesh:delaunizer',rebuilt['geometry-with-measurements.scm'])
            B.geometry_admit(folder,json.loads((folder/'project.json').read_bytes()),P.first.sha(P.ROOT/'scripts/tcad.py'))
        spec=importlib.util.spec_from_file_location('r3_original_preparer',DELIVERY/'prechange/prepare_case.py')
        old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        two=dict(schema=C.SCHEMA,kind='dc',dimension=2,variant='main',gate_top_depth_nm=80,sn_junction_depth_nm=87)
        self.assertEqual(P.producer_payload(two)[0],old.producer_payload(two)[0])
        self.assertNotIn(b'sdesnmesh:delaunizer',P.producer_payload(two)[0]['geometry-with-measurements.scm'])

    def test_original_archives_and_v1_dependency_bytes_are_preserved(self):
        before=json.loads((DELIVERY/'prechange.json').read_bytes())
        self.assertTrue(before['assumptions_precede_implementation'])
        for path,entry in before['files'].items():
            if entry['expected_unchanged']:
                self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(),entry['sha256'],path)
        for name in ('mesh_policy_v3.py','mesh_policy_registry.py','case_contract.py','geometry_bridge.py'):
            ast.parse((P.HERE/name).read_text(encoding='utf-8'),feature_version=(3,6))

    def test_r3_binding_both_bit_a0_inherit_and_false_native_rejection(self):
        cfg=dict(mesh_policy_id=R3.POLICY_ID,mesh_policy_sha256=P.digest(self.files['mesh-policy.json']))
        B.geometry_validate_mesh_policy_payload(self.files,cfg,require_sde=True)
        for bit in (0,1):
            req=dict(schema=C.SCHEMA,kind='transient',gate_top_depth_nm=80,sn_junction_depth_nm=87,dimension=3,
                     variant='main',stored_bit=bit,source_case='A0',d3_source_run='UNIT_FIXTURE_NOT_NATIVE')
            files=P.transient_payload(self.model,req,{'input_only':True},self.files)
            for name in M.FILES:self.assertEqual(files[name],self.files[name])
            self.assertEqual(files['geometry-contract.json'],self.files['geometry-contract.json'])
            self.assertNotIn(b'HeavyIon(',files['device.cmd'])
            self.assertFalse(json.loads(files['source-contract.json'])['native_qualified'])
        with self.assertRaises(ValueError):B.geometry_source_bundle(FIXTURE,{},synthetic_fixture=True)
        bad=dict(self.files);g=json.loads(bad['geometry-contract.json']);g['mesh']['delaunizer']['explicit_parameters']['maxPoints']=0
        bad['geometry-contract.json']=P.raw_json(g)
        with self.assertRaises(ValueError):B.geometry_validate_mesh_policy_payload(bad,cfg,require_sde=True)
        with self.assertRaises(ValueError):C.validate(dict(request(),mesh_policy='dram-see-v4-gradient-mesh-r99'))


if __name__=='__main__':
    print('Preserved new r3 declaration evidence:',FIXTURE,flush=True)
    unittest.main(verbosity=2)
