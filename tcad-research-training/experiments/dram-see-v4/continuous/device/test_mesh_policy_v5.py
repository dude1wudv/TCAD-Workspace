"""Only r5 partitions, fixed physics, and directly affected r4 reuse/dispatch."""
import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import re
import unittest
import uuid

import case_contract as C
import geometry_bridge as B
import mesh_policy_registry as M
import mesh_policy_v5 as R5
import prepare_case as P

OUT=P.ROOT/'local_runtime/dram-see-v4/continuous/device/gradient-mesh-r5-r1'
OLD=P.ROOT/'local_runtime/dram-see-v4/continuous/device/gradient-mesh-r4-r1/projects/20261017T103531Z-v4-continuous-b1-d3-r7'
FIXTURE=OUT/('UNIT_FIXTURE_NOT_NATIVE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])


def request(variant='main',gate=80,sn=87,policy=R5.POLICY_ID):
    return dict(schema=C.SCHEMA_MESH,kind='dc',gate_top_depth_nm=gate,sn_junction_depth_nm=sn,
                dimension=3,variant=variant,mesh_policy=policy)


def strip_mesh(raw,geometry_raw):
    text=raw.decode('utf-8')
    text,count=re.subn(r'; BEGIN EXPLICIT MESH POLICY [^\n]+\n.*?; END EXPLICIT MESH POLICY [^\n]+\n',
                      '',text,flags=re.S)
    if count!=1:raise AssertionError('Exactly one declared mesh block required')
    recorded=re.findall(r'^; geometry_contract_sha256=([0-9a-f]{64})$',text,flags=re.M)
    if recorded!=[P.digest(geometry_raw)]:raise AssertionError('SDE metadata must bind its exact geometry bytes')
    text=re.sub(r'^; geometry_contract_sha256=[0-9a-f]{64}$','; geometry_contract_sha256=BOUND_ORIGINAL_INPUT',text,flags=re.M)
    return text


class GradientMeshR5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files,cls.model=P.producer_payload(request())
        cls.fine,_=P.producer_payload(request('mesh'))
        cls.policy=json.loads(cls.files['mesh-policy.json'])
        cls.previous=json.loads((OLD/'mesh-policy.json').read_bytes())
        cls.definition=json.loads(cls.files['mesh-policy-definition.json'])
        cls.table=json.loads(cls.definition['doping_partition_source']['raw_utf8'])
        FIXTURE.mkdir(parents=True,exist_ok=False)
        (FIXTURE/'SYNTHETIC_NOT_NATIVE').write_text('Declaration/partition tests only; no project.json, native mesh, successful D3 or A0.\n',encoding='utf-8')
        for variant,files in (('main',cls.files),('mesh',cls.fine)):
            folder=FIXTURE/variant;folder.mkdir()
            for name,raw in files.items():(folder/name).write_bytes(raw)

    def test_thirteen_original_rectangles_replace_four_old_windows_without_gaps(self):
        windows={w['name']:w for w in self.policy['volume_refinements']}
        before={w['name']:w for w in self.previous['volume_refinements']}
        self.assertEqual(hashlib.sha256(self.definition['doping_partition_source']['raw_utf8'].encode()).hexdigest(),R5.DOPING_TABLE_SHA256)
        self.assertEqual(len(self.table['placements']),13)
        self.assertFalse(set(self.table['replace_exact_windows'])&set(windows))
        for row in self.table['placements']:
            w=windows[R5.doping_window_name(row)]
            self.assertEqual(w['physical_min_um'],[v/1000 for v in row['lo_nm']])
            self.assertEqual(w['physical_max_um'],[v/1000 for v in row['hi_nm']])
            self.assertEqual(w['max_size_um'],[v/1000 for v in row['max_step_nm']])
            self.assertEqual(w['min_size_um'],[v/2000 for v in row['max_step_nm']])
            self.assertEqual(w['materials'],['Silicon'])
        # Exact rectangle arrangements, not sample probes: each open partition cell
        # inside each original rectangular placement has exactly one replacement.
        for replaced in self.table['replace_exact_windows']:
            old=before[replaced]
            parts=[windows[R5.doping_window_name(row)] for row in self.table['placements'] if row['replaces']==replaced]
            for part in parts:
                for axis in range(3):
                    self.assertGreaterEqual(part['physical_min_um'][axis],old['physical_min_um'][axis])
                    self.assertLessEqual(part['physical_max_um'][axis],old['physical_max_um'][axis])
            grids=[sorted({old['physical_min_um'][a],old['physical_max_um'][a]}|
                          {part[key][a] for part in parts for key in ('physical_min_um','physical_max_um')}) for a in range(3)]
            centers=[[(a+b)/2 for a,b in zip(grid,grid[1:])] for grid in grids]
            for point in itertools.product(*centers):
                count=sum(all(part['physical_min_um'][a]<point[a]<part['physical_max_um'][a] for a in range(3)) for part in parts)
                self.assertEqual(count,1,(replaced,point))

    def test_actual_gate_geometry_has_five_bands_and_retains_all_endpoints(self):
        segments=('Surface','StraightUpper','GateTop','StraightLower','CurveTransition')
        for gate in (70,80,90):
            files,_=P.producer_payload(request(gate=gate))
            policy=json.loads(files['mesh-policy.json']);g=json.loads(files['geometry-contract.json'])
            windows={w['name']:w for w in policy['volume_refinements']}
            oxide=g['nominal_oxide_um']['side'];zc=g['outer_trench']['round_center_z_um'];gt=g['gate_void']['top_um']
            bounds=(0,oxide*.5,gt-oxide*2,gt+oxide*.5,zc-oxide,zc+oxide*.25)
            for family,count,oldmax,coarse in (('GateSideNormalX',2,[.001,.005,.001],[.001,.005,.005]),
                                              ('TrenchSTISideCorners',4,[.001,.001,.001],[.001,.001,.005])):
                for index in range(1,count+1):
                    old=next(w for w in self.previous['volume_refinements'] if w['name']==family+str(index))
                    self.assertNotIn(family+str(index),windows)
                    for j,segment in enumerate(segments):
                        w=windows[family+str(index)+segment]
                        self.assertEqual(w['physical_min_um'][:2],old['physical_min_um'][:2])
                        self.assertEqual(w['physical_max_um'][:2],old['physical_max_um'][:2])
                        self.assertEqual(w['physical_min_um'][2],bounds[j]);self.assertEqual(w['physical_max_um'][2],bounds[j+1])
                        self.assertEqual(w['max_size_um'],coarse if j in (1,3) else oldmax)
            B.geometry_validate_mesh_policy_payload(files,dict(mesh_policy_id=R5.POLICY_ID,mesh_policy_sha256=P.digest(files['mesh-policy.json'])),require_sde=True)

    def test_only_approved_windows_change_and_all_h2_lengths_halve(self):
        old={w['name']:w for w in self.previous['volume_refinements']}
        new={w['name']:w for w in self.policy['volume_refinements']}
        replaced=set(self.table['replace_exact_windows'])|{n for n in old if n.startswith(('GateSideNormalX','TrenchSTISideCorners'))}
        self.assertEqual(set(old)-set(new),replaced)
        for name in set(old)-replaced:self.assertEqual(new[name],old[name],name)
        for key in ('interface_refinements','delaunizer','source_transverse_partition','previous_native_delaunizer_serialization'):
            self.assertEqual(self.policy[key],self.previous[key],key)
        fine=json.loads(self.fine['mesh-policy.json'])
        for key in ('volume_refinements','interface_refinements'):
            self.assertEqual(len(self.policy[key]),len(fine[key]))
            for main,half in zip(self.policy[key],fine[key]):
                for field in set(main)-{'max_size_um','min_size_um','first_step_um'}:self.assertEqual(main[field],half[field],field)
                for field in ('max_size_um','min_size_um'):self.assertEqual(half[field],[v*.5 for v in main[field]])
                if key=='interface_refinements':self.assertEqual(half['first_step_um'],main['first_step_um']*.5)
        self.assertEqual(self.policy['delaunizer'],fine['delaunizer'])

    def test_actual_physics_148_measurements_and_nonmesh_commands_stay_byte_equal(self):
        for name in P.PHYSICS_FILES+('model.proposed.json','device.cmd','numerical-method.json'):
            self.assertEqual(self.files[name],(OLD/name).read_bytes(),name)
        previous=json.loads((OLD/'geometry-contract.json').read_bytes());current=json.loads(self.files['geometry-contract.json'])
        self.assertEqual({k:v for k,v in previous.items() if k!='mesh'},{k:v for k,v in current.items() if k!='mesh'})
        oldplan=json.loads((OLD/'measurement-plan.json').read_bytes());plan=json.loads(self.files['measurement-plan.json'])
        self.assertEqual(len(plan['measurements']),148)
        for key in ('measurements','contact_probes','material_probes','comparison_policy'):self.assertEqual(plan[key],oldplan[key])
        self.assertEqual(strip_mesh(self.files['geometry-with-measurements.scm'],self.files['geometry-contract.json']),
                         strip_mesh((OLD/'geometry-with-measurements.scm').read_bytes(),(OLD/'geometry-contract.json').read_bytes()))
        def tcl_body(raw,geometry_raw):
            self.assertEqual(re.findall(r'^# geometry_contract_sha256=([0-9a-f]{64})$',raw.decode(),flags=re.M),[P.digest(geometry_raw)])
            text,n=re.subn(r'^# geometry_contract_sha256=[0-9a-f]{64}$','# geometry_contract_sha256=BOUND_ORIGINAL_INPUT',raw.decode(),flags=re.M)
            self.assertEqual(n,1);return text
        self.assertEqual(tcl_body(self.files['measure-geometry.tcl'],self.files['geometry-contract.json']),
                         tcl_body((OLD/'measure-geometry.tcl').read_bytes(),(OLD/'geometry-contract.json').read_bytes()))
        before=ast.parse((OUT/'before/geometry_bridge.py').read_text(encoding='utf-8'))
        original_steps=next(ast.literal_eval(node.value) for node in before.body if isinstance(node,ast.Assign)
                            and any(isinstance(target,ast.Name) and target.id=='GEOMETRY_STEPS' for target in node.targets))
        self.assertEqual(B.GEOMETRY_STEPS,original_steps)
        self.assertEqual(len(B.GEOMETRY_STEPS),6)

    def test_unanalyzed_sn_and_changed_original_table_are_rejected(self):
        for sn in (82,92):
            with self.assertRaisesRegex(ValueError,'SN87'):C.validate(request(sn=sn))
            model=P.baseline_model(80,sn)
            desc=P.geometry.describe_geometry(model,3,1)
            with self.assertRaisesRegex(ValueError,'SN87'):R5.build(P.raw_json(model),desc,1)
        desc=P.geometry.describe_geometry(self.model,3,1)
        bad=deepcopy(self.definition)
        table=json.loads(bad['doping_partition_source']['raw_utf8']);table['placements'][0]['max_step_nm'][2]=5
        raw=P.raw_json(table);bad['doping_partition_source'].update(raw_utf8=raw.decode(),sha256=P.digest(raw))
        with self.assertRaisesRegex(ValueError,'evidence differs'):R5.doping_partitions(P.raw_json(self.model),desc,bad)

    def test_r5_binding_a0_inherits_exact_policy_and_false_spans_are_not_qualified(self):
        for variant,files in (('main',self.files),('mesh',self.fine)):
            cfg=dict(mesh_policy_id=R5.POLICY_ID,mesh_policy_sha256=P.digest(files['mesh-policy.json']))
            B.geometry_validate_mesh_policy_payload(files,cfg,require_sde=True)
            for bit in (0,1):
                req=dict(schema=C.SCHEMA,kind='transient',gate_top_depth_nm=80,sn_junction_depth_nm=87,
                         dimension=3,variant=variant,stored_bit=bit,source_case='A0',d3_source_run='UNIT_FIXTURE_NOT_NATIVE')
                control=P.transient_payload(self.model,req,{'input_only':True},files)
                for name in M.FILES+('geometry-contract.json',):self.assertEqual(control[name],files[name])
                self.assertNotIn(b'HeavyIon(',control['device.cmd'])
                self.assertFalse(json.loads(control['source-contract.json'])['native_qualified'])
            bad_policy=deepcopy(json.loads(files['mesh-policy.json']))
            bad_policy['doping_partition_evidence']['actual_cell_spans_verified']=True
            with self.assertRaisesRegex(ValueError,'qualification'):
                B.geometry_validate_r5_partitions(files,json.loads(files['geometry-contract.json']),bad_policy,json.loads(files['mesh-policy-definition.json']))
            bad_policy=deepcopy(json.loads(files['mesh-policy.json']))
            window=next(w for w in bad_policy['volume_refinements'] if w['name']=='GateSideNormalX1StraightLower')
            window['physical_min_um'][0]-=.001;window['sde_min_um'][0]-=.001
            with self.assertRaisesRegex(ValueError,'band differs'):
                B.geometry_validate_r5_partitions(files,json.loads(files['geometry-contract.json']),bad_policy,json.loads(files['mesh-policy-definition.json']))

    def test_old_r4_recomputes_and_original_sources_and_frozen_input_are_unchanged(self):
        recreated,_=P.producer_payload(request(policy='dram-see-v4-gradient-mesh-r4'))
        for name,raw in recreated.items():self.assertEqual(raw,(OLD/name).read_bytes(),name)
        B.geometry_admit(OLD,json.loads((OLD/'project.json').read_bytes()),P.first.sha(P.ROOT/'scripts/tcad.py'))
        before=json.loads((OUT/'prechange.json').read_bytes())
        self.assertTrue(before['assumptions_precede_implementation'])
        self.assertEqual(before['assumptions_sha256'],P.first.sha(P.HERE/'MESH-GRADIENT-R5-ASSUMPTIONS.md'))
        for path,entry in before['files'].items():
            if entry['expected_unchanged']:self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(),entry['sha256'],path)
        for name in ('mesh_policy_v5.py','mesh_policy_registry.py','case_contract.py','geometry_bridge.py'):
            ast.parse((P.HERE/name).read_text(encoding='utf-8'),feature_version=(3,6))


if __name__=='__main__':
    print('Preserved r5 unit inputs, never a native run:',FIXTURE,flush=True)
    unittest.main(verbosity=2)
