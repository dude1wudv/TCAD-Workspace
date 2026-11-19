"""Only new r2 behavior and the r1 dispatch boundary; never runs a solver."""
import ast
from datetime import datetime, timezone
import json
import re
import unittest
import uuid

import case_contract as C
import geometry_bridge as B
import mesh_policy as R1
import mesh_policy_v2 as R2
import mesh_policy_registry as M
import prepare_case as P

RUNTIME=P.ROOT/'local_runtime/dram-see-v4/continuous/device'
ORIGINAL=RUNTIME/'projects/20261017T084908Z-v4-continuous-b1-d3-r4'
FIXTURE=RUNTIME/('UNIT_FIXTURE_NOT_NATIVE-mesh-policy-r2-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])


def request(variant='main',policy=R2.POLICY_ID):
    return dict(schema=C.SCHEMA_MESH,kind='dc',gate_top_depth_nm=80,sn_junction_depth_nm=87,
                dimension=3,variant=variant,mesh_policy=policy)


class GradientMeshR2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files,cls.model=P.producer_payload(request())
        cls.fine,_=P.producer_payload(request('mesh'))
        cls.policy=json.loads(cls.files['mesh-policy.json'])
        cls.old=json.loads((ORIGINAL/'mesh-policy.json').read_bytes())
        FIXTURE.mkdir(exist_ok=False)
        (FIXTURE/'SYNTHETIC_NOT_NATIVE').write_text('Pure mesh r2 declaration and dispatch checks; no native D3/A0 success.\n',encoding='utf-8')
        for variant,files in (('main',cls.files),('mesh',cls.fine)):
            folder=FIXTURE/variant;folder.mkdir()
            for name,raw in files.items():(folder/name).write_bytes(raw)

    def test_only_junction_and_continuous_all_y_blend_are_added(self):
        old={w['name']:w for w in self.old['volume_refinements']}
        current={w['name']:w for w in self.policy['volume_refinements']}
        self.assertEqual(set(current)-set(old),{'BlendFullWidth'})
        self.assertEqual(set(old)-set(current),set())
        for name in old:
            if name!='Junction':self.assertEqual(old[name],current[name],name)
        junction=current['Junction']
        self.assertEqual(junction['max_size_um'],[.02,.02,.005])
        self.assertEqual(junction['min_size_um'],[.01,.01,.0025])
        for key in ('physical_min_um','physical_max_um','materials'):
            self.assertEqual(junction[key],old['Junction'][key])
        band=current['BlendFullWidth']
        self.assertEqual(band['physical_min_um'],[-.02,-.25,0.])
        self.assertEqual(band['physical_max_um'],[.02,.25,.25])
        self.assertEqual(band['max_size_um'],[.001,.02,.001])
        self.assertEqual(band['materials'],['Silicon'])
        self.assertEqual(self.old['interface_refinements'],self.policy['interface_refinements'])

    def test_h2_refines_every_spacing_without_moving_boundaries(self):
        fine=json.loads(self.fine['mesh-policy.json'])
        for key in ('volume_refinements','interface_refinements'):
            self.assertEqual(len(self.policy[key]),len(fine[key]))
            for main,half in zip(self.policy[key],fine[key]):
                for field in ('name','physical_min_um','physical_max_um','materials'):
                    self.assertEqual(main[field],half[field])
                for field in ('max_size_um','min_size_um'):
                    self.assertEqual(half[field],[v*.5 for v in main[field]])
                if key=='interface_refinements':self.assertEqual(half['first_step_um'],main['first_step_um']*.5)
        self.assertFalse(fine['native_accuracy_qualified'])

    def test_r1_original_files_payload_and_admission_still_match(self):
        self.assertEqual((P.HERE/'mesh_policy.py').read_bytes(),(ORIGINAL/'generator-mesh_policy.py').read_bytes())
        self.assertEqual(R1.DEFINITION.read_bytes(),(ORIGINAL/'mesh-policy-definition.json').read_bytes())
        self.assertEqual(R1.ASSUMPTIONS.read_bytes(),(ORIGINAL/'mesh-policy-assumptions.md').read_bytes())
        recreated,_=P.producer_payload(request(policy=R1.POLICY_ID))
        for name,raw in recreated.items():self.assertEqual(raw,(ORIGINAL/name).read_bytes(),name)
        before=(ORIGINAL/'input-manifest.json').read_bytes()
        B.geometry_admit(ORIGINAL,json.loads((ORIGINAL/'project.json').read_bytes()),P.first.sha(P.ROOT/'scripts/tcad.py'))
        self.assertEqual(before,(ORIGINAL/'input-manifest.json').read_bytes())

    def test_physical_solver_and_all_measurement_values_are_identical(self):
        for name in P.PHYSICS_FILES+('model.proposed.json','device.cmd','numerical-method.json'):
            self.assertEqual(self.files[name],(ORIGINAL/name).read_bytes(),name)
        g0=json.loads((ORIGINAL/'geometry-contract.json').read_bytes());g1=json.loads(self.files['geometry-contract.json'])
        self.assertEqual({k:v for k,v in g0.items() if k!='mesh'},{k:v for k,v in g1.items() if k!='mesh'})
        old=json.loads((ORIGINAL/'measurement-plan.json').read_bytes());new=json.loads(self.files['measurement-plan.json'])
        for key in ('measurements','contact_probes','material_probes','comparison_policy'):
            self.assertEqual(old[key],new[key],key)
        used=set(re.findall(r'\((sdedr:[A-Za-z-]+)',R2.render_block(self.policy)))
        established=set(re.findall(r'\((sdedr:[A-Za-z-]+)',(ORIGINAL/'geometry-with-measurements.scm').read_text(encoding='utf-8')))
        self.assertTrue(used<=established)

    def test_new_policy_runtime_binding_and_a0_inherit(self):
        cfg=dict(mesh_policy_id=R2.POLICY_ID,mesh_policy_sha256=P.digest(self.files['mesh-policy.json']))
        B.geometry_validate_mesh_policy_payload(self.files,cfg,require_sde=True)
        for bit in (0,1):
            req=dict(schema=C.SCHEMA,kind='transient',gate_top_depth_nm=80,sn_junction_depth_nm=87,dimension=3,
                variant='main',stored_bit=bit,source_case='A0',d3_source_run='UNIT_FIXTURE_NOT_NATIVE')
            result=P.transient_payload(self.model,req,{'input_only':True},self.files)
            self.assertNotIn(b'HeavyIon(',result['device.cmd'])
            for name in M.FILES:self.assertEqual(result[name],self.files[name])
            self.assertFalse(json.loads(result['source-contract.json'])['native_qualified'])
        with self.assertRaises(ValueError):M.select('automatic')
        bad=dict(request(),mesh_policy='dram-see-v4-gradient-mesh-r99')
        with self.assertRaises(ValueError):C.validate(bad)
        for name in ('mesh_policy_v2.py','mesh_policy_registry.py','case_contract.py','geometry_bridge.py'):
            ast.parse((P.HERE/name).read_text(encoding='utf-8'),feature_version=(3,6))


if __name__=='__main__':
    print('Preserved r2 declaration evidence:',FIXTURE)
    unittest.main(verbosity=2)
