"""Focused r4 source-column changes and the directly affected r3 dispatch."""
import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unittest
import uuid

import case_contract as C
import geometry_bridge as B
import mesh_policy_registry as M
import mesh_policy_v4 as R4
import prepare_case as P

OUT=P.ROOT/'local_runtime/dram-see-v4/continuous/device/gradient-mesh-r4-r1'
OLD=P.ROOT/'local_runtime/dram-see-v4/continuous/device/gradient-mesh-r3-r1/projects/20261017T100332Z-v4-continuous-b1-d3-r6'
FIXTURE=OUT/('UNIT_FIXTURE_NOT_NATIVE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])


def request(variant='main',policy=R4.POLICY_ID):
    return dict(schema=C.SCHEMA_MESH,kind='dc',gate_top_depth_nm=80,sn_junction_depth_nm=87,
                dimension=3,variant=variant,mesh_policy=policy)


class GradientMeshR4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files,cls.model=P.producer_payload(request())
        cls.fine,_=P.producer_payload(request('mesh'))
        cls.policy=json.loads(cls.files['mesh-policy.json'])
        cls.previous=json.loads((OLD/'mesh-policy.json').read_bytes())
        FIXTURE.mkdir(parents=True,exist_ok=False)
        (FIXTURE/'SYNTHETIC_NOT_NATIVE').write_text('New r4 declaration checks only; no native result or successful D3/A0.\n',encoding='utf-8')
        for variant,files in (('main',cls.files),('mesh',cls.fine)):
            directory=FIXTURE/variant;directory.mkdir()
            for name,raw in files.items():(directory/name).write_bytes(raw)

    def test_only_three_outer_windows_and_three_matching_cores_change(self):
        before={w['name']:w for w in self.previous['volume_refinements']}
        after={w['name']:w for w in self.policy['volume_refinements']}
        sources=('AlphaTrackNear','AlphaTrackBulk','AlphaTrackEnd')
        self.assertEqual(set(after)-set(before),{name+'Core' for name in sources})
        self.assertEqual(set(before)-set(after),set())
        center=[v/1000 for v in self.model['alpha']['position_nm'][:2]]
        width=self.model['alpha']['radial_Gaussian_w_nm']/1000
        for name,old in before.items():
            if name not in sources:self.assertEqual(after[name],old,name);continue
            outer=after[name];core=after[name+'Core']
            for field in set(old)-{'max_size_um','min_size_um'}:self.assertEqual(outer[field],old[field],field)
            self.assertEqual(outer['max_size_um'],[.01,.01,old['max_size_um'][2]])
            self.assertEqual(outer['min_size_um'],[.005,.005,old['min_size_um'][2]])
            self.assertEqual(core['max_size_um'],old['max_size_um'])
            self.assertEqual(core['min_size_um'],old['min_size_um'])
            self.assertEqual(core['physical_min_um'],[v-2*width for v in center]+[old['physical_min_um'][2]])
            self.assertEqual(core['physical_max_um'],[v+2*width for v in center]+[old['physical_max_um'][2]])
            self.assertEqual(core['materials'],['Silicon'])
        self.assertEqual(self.policy['interface_refinements'],self.previous['interface_refinements'])
        self.assertEqual(self.policy['delaunizer'],self.previous['delaunizer'])
        observation=self.policy['previous_native_delaunizer_serialization']
        self.assertEqual((observation['requested_integer'],observation['actual_literal'],observation['actual_literal_numeric_value']),
                         (2147483647,'2.14748e+09',2147480000))
        self.assertFalse(observation['exact_parameter_match'])
        self.assertFalse(observation['is_current_run_measurement'])

    def test_core_derives_from_source_and_validates_original_geometry(self):
        definition=json.loads(self.files['mesh-policy-definition.json'])
        domain=json.loads(self.files['geometry-contract.json'])['domain_um']
        # Deliberately mathematical fixtures, not a new authorized source family.
        for center,width_nm in (([100,-20,0],40),([950,0,0],50)):
            model=deepcopy(self.model);model['alpha']['position_nm']=center;model['alpha']['radial_Gaussian_w_nm']=width_nm
            c=[v/1000 for v in center[:2]];width=width_nm/1000
            track=dict(physical_min_um=[max(domain[axis][0],c[i]-4*width) for i,axis in enumerate('xy')]+[0.],
                       physical_max_um=[min(domain[axis][1],c[i]+4*width) for i,axis in enumerate('xy')]+[1.])
            part=R4.source_core_geometry(P.raw_json(model),track,domain,definition)
            self.assertEqual(part['source_center_xy_um'],c)
            self.assertEqual(part['core_min_xy_um'],[max(domain[axis][0],c[i]-2*width) for i,axis in enumerate('xy')])
            self.assertEqual(part['core_max_xy_um'],[min(domain[axis][1],c[i]+2*width) for i,axis in enumerate('xy')])
            bad=deepcopy(track);bad['physical_max_um'][0]-=.001
            with self.assertRaises(ValueError):R4.source_core_geometry(P.raw_json(model),bad,domain,definition)
        self.assertFalse(self.policy['source_transverse_partition']['source_tail_renormalized'])
        self.assertFalse(self.policy['source_transverse_partition']['native_coverage_qualified'])

    def test_all_h2_spacings_with_fixed_bounds_and_algorithm_parameter(self):
        fine=json.loads(self.fine['mesh-policy.json'])
        for key in ('volume_refinements','interface_refinements'):
            self.assertEqual(len(self.policy[key]),len(fine[key]))
            for main,half in zip(self.policy[key],fine[key]):
                for field in set(main)-{'max_size_um','min_size_um','first_step_um'}:
                    self.assertEqual(main[field],half[field],field)
                for field in ('max_size_um','min_size_um'):self.assertEqual(half[field],[v*.5 for v in main[field]])
                if key=='interface_refinements':self.assertEqual(half['first_step_um'],main['first_step_um']*.5)
        for key in ('delaunizer','source_transverse_partition','previous_native_delaunizer_serialization'):
            self.assertEqual(self.policy[key],fine[key])

    def test_physical_measurements_old_r3_payload_and_byte_preservation(self):
        for name in P.PHYSICS_FILES+('model.proposed.json','device.cmd','numerical-method.json'):
            self.assertEqual(self.files[name],(OLD/name).read_bytes(),name)
        g0=json.loads((OLD/'geometry-contract.json').read_bytes());g1=json.loads(self.files['geometry-contract.json'])
        self.assertEqual({k:v for k,v in g0.items() if k!='mesh'},{k:v for k,v in g1.items() if k!='mesh'})
        old_plan=json.loads((OLD/'measurement-plan.json').read_bytes());plan=json.loads(self.files['measurement-plan.json'])
        self.assertEqual(len(plan['measurements']),148)
        for key in ('measurements','contact_probes','material_probes','comparison_policy'):self.assertEqual(plan[key],old_plan[key])
        recreated,_=P.producer_payload(request(policy='dram-see-v4-gradient-mesh-r3'))
        for name,raw in recreated.items():self.assertEqual(raw,(OLD/name).read_bytes(),name)
        B.geometry_admit(OLD,json.loads((OLD/'project.json').read_bytes()),P.first.sha(P.ROOT/'scripts/tcad.py'))
        before=json.loads((OUT/'prechange.json').read_bytes())
        self.assertTrue(before['assumptions_precede_implementation'])
        for path,record in before['files'].items():
            if record['expected_unchanged']:self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(),record['sha256'],path)
        for name in ('mesh_policy_v4.py','mesh_policy_registry.py','case_contract.py','geometry_bridge.py'):
            ast.parse((P.HERE/name).read_text(encoding='utf-8'),feature_version=(3,6))

    def test_new_policy_admission_and_both_bit_a0_inherit_both_mesh_levels(self):
        for variant,files in (('main',self.files),('mesh',self.fine)):
            cfg=dict(mesh_policy_id=R4.POLICY_ID,mesh_policy_sha256=P.digest(files['mesh-policy.json']))
            B.geometry_validate_mesh_policy_payload(files,cfg,require_sde=True)
            for bit in (0,1):
                req=dict(schema=C.SCHEMA,kind='transient',gate_top_depth_nm=80,sn_junction_depth_nm=87,
                    dimension=3,variant=variant,stored_bit=bit,source_case='A0',d3_source_run='UNIT_FIXTURE_NOT_NATIVE')
                result=P.transient_payload(self.model,req,{'input_only':True},files)
                for name in M.FILES+('geometry-contract.json',):self.assertEqual(result[name],files[name])
                self.assertNotIn(b'HeavyIon(',result['device.cmd'])
                self.assertFalse(json.loads(result['source-contract.json'])['native_qualified'])
        with self.assertRaises(ValueError):C.validate(dict(request(),mesh_policy='dram-see-v4-gradient-mesh-r99'))


if __name__=='__main__':
    print('Preserved new r4 declaration evidence:',FIXTURE,flush=True)
    unittest.main(verbosity=2)
