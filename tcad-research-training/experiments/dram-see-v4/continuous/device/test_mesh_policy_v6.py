"""New r6 behavior only; no solver, old suite, mesh or scientific qualification."""
import ast
from collections import Counter
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
import mesh_policy_v6 as R6
import prepare_case as P

OUT=P.ROOT/'local_runtime/dram-see-v4/continuous/device/gradient-mesh-r6-r1'
OLD=P.ROOT/'local_runtime/dram-see-v4/continuous/device/gradient-mesh-r5-r1/projects/20261017T114154Z-v4-continuous-b1-d3-r8'
FIXTURE=OUT/('UNIT_FIXTURE_NOT_NATIVE-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])


def request(variant='main',gate=80,sn=87,policy=R6.POLICY_ID):
    return dict(schema=C.SCHEMA_MESH,kind='dc',gate_top_depth_nm=gate,sn_junction_depth_nm=sn,
                dimension=3,variant=variant,mesh_policy=policy)


def strip_mesh(raw,geometry_raw):
    text=raw.decode('utf-8')
    text,count=re.subn(r'; BEGIN EXPLICIT MESH POLICY [^\n]+\n.*?; END EXPLICIT MESH POLICY [^\n]+\n',
                      '',text,flags=re.S)
    if count!=1:raise AssertionError('Exactly one explicit mesh block required')
    recorded=re.findall(r'^; geometry_contract_sha256=([0-9a-f]{64})$',text,flags=re.M)
    if recorded!=[P.digest(geometry_raw)]:raise AssertionError('First validate the exact original geometry SHA')
    return re.sub(r'^; geometry_contract_sha256=[0-9a-f]{64}$',
                  '; geometry_contract_sha256=BOUND_ORIGINAL_INPUT',text,flags=re.M)


def contains(window,point):
    return all(window['physical_min_um'][a]<=point[a]<=window['physical_max_um'][a] for a in range(3))


def effective(windows,point,key):
    rows=[w[key] for w in windows if contains(w,point)]
    return [min(row[a] for row in rows) for a in range(3)] if rows else None


class GradientMeshR6(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files,cls.model=P.producer_payload(request())
        cls.fine,_=P.producer_payload(request('mesh'))
        cls.policy=json.loads(cls.files['mesh-policy.json'])
        cls.previous=json.loads((OLD/'mesh-policy.json').read_bytes())
        cls.definition=json.loads(cls.files['mesh-policy-definition.json'])
        cls.table=json.loads(cls.definition['doping_partition_source']['raw_utf8'])
        cls.source=json.loads(cls.definition['source_spacing_source']['raw_utf8'])
        FIXTURE.mkdir(parents=True,exist_ok=False)
        (FIXTURE/'SYNTHETIC_NOT_NATIVE').write_text('Input unit fixture only; no project.json, native mesh or successful D3/A0.\n',encoding='utf-8')
        for variant,files in (('main',cls.files),('mesh',cls.fine)):
            folder=FIXTURE/variant;folder.mkdir()
            for name,raw in files.items():(folder/name).write_bytes(raw)

    def test_99_original_rows_units_evidence_and_old13_exit(self):
        source=self.definition['doping_partition_source'];raw=source['raw_utf8'].encode()
        self.assertEqual(raw,(P.ROOT/source['path']).read_bytes())
        self.assertEqual(P.digest(raw),R6.DOPING_TABLE_SHA256)
        self.assertEqual(len(self.table['placements']),99)
        self.assertEqual(Counter(r['evidence_class'] for r in self.table['placements']),R6.EVIDENCE_COUNTS)
        windows={w['name']:w for w in self.policy['volume_refinements']}
        self.assertFalse(set(self.table['replace_only_r5_doping_window_names'])&set(windows))
        for row in self.table['placements']:
            w=windows[row['id']]
            for actual,expected in (('physical_min_um','lo_um_decimal'),('physical_max_um','hi_um_decimal'),
                                    ('max_size_um','max_step_um_decimal'),('min_size_um','minimum_step_um_decimal')):
                self.assertEqual(w[actual],[float(v) for v in row[expected]],row['id'])
            self.assertEqual(w['materials'],['Silicon'])
            self.assertEqual(w['doping_evidence_class'],row['evidence_class'])
            self.assertEqual(w['doping_new_mathematical_certification'],row['evidence_class']=='NEW_HESSIAN_BOUNDED_COARSENING')
        self.assertFalse(self.policy['doping_partition_evidence']['full_domain_certified'])
        self.assertEqual(self.policy['doping_partition_evidence']['baseline_policy_ref'],self.table['baseline_policy_ref'])

    def test_complete_piecewise_field_coverage_no_finer_and_exact_inherited_regions(self):
        removed=set(self.table['replace_only_r5_doping_window_names'])
        old=[w for w in self.previous['volume_refinements'] if w['name'] in removed]
        new=[w for w in self.policy['volume_refinements'] if 'doping_candidate_id' in w]
        # Each arrangement cell has a constant rectangular placement field.
        # Evaluate its interior and every boundary combination, not physics probes.
        grids=[sorted({w[k][a] for w in old+new for k in ('physical_min_um','physical_max_um')}) for a in range(3)]
        axes=[sorted(set(grid)|{(a+b)/2 for a,b in zip(grid,grid[1:])}) for grid in grids]
        checked=0;inherited_checked=0
        inherited=[w for w in new if w['doping_evidence_class']=='INHERITED_ACTUAL_R5_NO_NEW_CERTIFICATION']
        for point in itertools.product(*axes):
            o=effective(old,point,'max_size_um');n=effective(new,point,'max_size_um')
            self.assertEqual(o is None,n is None,('coverage',point))
            if o is None:continue
            for key in ('max_size_um','min_size_um'):
                before=effective(old,point,key);after=effective(new,point,key)
                self.assertTrue(all(a>=b for a,b in zip(after,before)),(point,key,before,after))
            # At open inherited rectangles the full doping field remains exactly r5.
            if any(all(w['physical_min_um'][a]<point[a]<w['physical_max_um'][a] for a in range(3)) for w in inherited):
                self.assertEqual(n,o,('inherited',point));inherited_checked+=1
            checked+=1
        self.assertGreater(checked,0);self.assertGreater(inherited_checked,0)
        (FIXTURE/'nominal-piecewise-field-check.json').write_bytes(P.raw_json(dict(
            arrangement_points=checked,inherited_points=inherited_checked,actual_tetrahedra_verified=False,
            full_domain_science_qualified=False,material_mask='unchanged Silicon for every compared rectangle')))

    def test_only_three_source_xy_changes_other_rules_and_all_h2_sizes(self):
        old={w['name']:w for w in self.previous['volume_refinements']}
        new={w['name']:w for w in self.policy['volume_refinements']}
        removed=set(self.table['replace_only_r5_doping_window_names'])
        added={r['id'] for r in self.table['placements']}
        cores={r['name'] for r in self.source['changes_only']}
        self.assertEqual(set(old)-set(new),removed)
        self.assertEqual(set(new)-set(old),added)
        for name in set(old)-removed-cores:self.assertEqual(new[name],old[name],name)
        for row in self.source['changes_only']:
            before,after=old[row['name']],new[row['name']]
            self.assertEqual({k:v for k,v in before.items() if k not in ('max_size_um','min_size_um')},
                             {k:v for k,v in after.items() if k not in ('max_size_um','min_size_um')})
            self.assertEqual(before['max_size_um'],row['old_max_size_um'])
            self.assertEqual(after['max_size_um'],row['candidate_max_size_um'])
            self.assertEqual(before['min_size_um'],row['old_min_size_um'])
            self.assertEqual(after['min_size_um'],row['candidate_min_size_um'])
            self.assertEqual(after['max_size_um'][2],before['max_size_um'][2])
            self.assertEqual(after['min_size_um'][2],before['min_size_um'][2])
        for key in ('interface_refinements','delaunizer','source_transverse_partition',
                    'straight_geometry_partition','previous_native_delaunizer_serialization'):
            self.assertEqual(self.policy[key],self.previous[key],key)
        fine=json.loads(self.fine['mesh-policy.json'])
        for key in ('volume_refinements','interface_refinements'):
            self.assertEqual(len(self.policy[key]),len(fine[key]))
            for main,half in zip(self.policy[key],fine[key]):
                for field in set(main)-{'max_size_um','min_size_um','first_step_um'}:self.assertEqual(main[field],half[field],field)
                for field in ('max_size_um','min_size_um'):self.assertEqual(half[field],[v*.5 for v in main[field]])
                if key=='interface_refinements':self.assertEqual(half['first_step_um'],main['first_step_um']*.5)
        self.assertEqual(self.policy['delaunizer'],fine['delaunizer'])

    def test_physics_148_nonmesh_commands_and_six_steps_unchanged(self):
        for name in P.PHYSICS_FILES+('model.proposed.json','device.cmd','numerical-method.json'):
            self.assertEqual(self.files[name],(OLD/name).read_bytes(),name)
        oldgeometry=json.loads((OLD/'geometry-contract.json').read_bytes())
        geometry=json.loads(self.files['geometry-contract.json'])
        self.assertEqual({k:v for k,v in geometry.items() if k!='mesh'},{k:v for k,v in oldgeometry.items() if k!='mesh'})
        plan=json.loads(self.files['measurement-plan.json']);before=json.loads((OLD/'measurement-plan.json').read_bytes())
        self.assertEqual(len(plan['measurements']),148)
        for key in ('measurements','contact_probes','material_probes','comparison_policy'):self.assertEqual(plan[key],before[key])
        self.assertEqual(strip_mesh(self.files['geometry-with-measurements.scm'],self.files['geometry-contract.json']),
                         strip_mesh((OLD/'geometry-with-measurements.scm').read_bytes(),(OLD/'geometry-contract.json').read_bytes()))
        def tcl(raw,geometry_raw):
            text=raw.decode();recorded=re.findall(r'^# geometry_contract_sha256=([0-9a-f]{64})$',text,flags=re.M)
            self.assertEqual(recorded,[P.digest(geometry_raw)])
            return re.sub(r'^# geometry_contract_sha256=[0-9a-f]{64}$','# geometry_contract_sha256=BOUND_ORIGINAL_INPUT',text,flags=re.M)
        self.assertEqual(tcl(self.files['measure-geometry.tcl'],self.files['geometry-contract.json']),
                         tcl((OLD/'measure-geometry.tcl').read_bytes(),(OLD/'geometry-contract.json').read_bytes()))
        before_ast=ast.parse((OUT/'before/geometry_bridge.py').read_text(encoding='utf-8'))
        original_steps=next(ast.literal_eval(node.value) for node in before_ast.body if isinstance(node,ast.Assign)
            and any(isinstance(target,ast.Name) and target.id=='GEOMETRY_STEPS' for target in node.targets))
        self.assertEqual(B.GEOMETRY_STEPS,original_steps);self.assertEqual(len(B.GEOMETRY_STEPS),6)

    def test_gate_geometry_scope_sn_rejection_and_source_certificate_limits(self):
        certificate=self.policy['source_spacing_evidence']['conditional_certificate']
        self.assertEqual(float(certificate['candidate10']['absolute_fC']),.2544455426878)
        self.assertEqual(float(certificate['outside4w_preserved40nm_tail_bound_fC']),.0001569205112)
        self.assertEqual(float(certificate['axial_global20nm_bound_fC']),.0020134647576)
        for gate in (70,80,90):
            files=self.files if gate==80 else P.producer_payload(request(gate=gate))[0]
            policy=json.loads(files['mesh-policy.json'])
            B.geometry_validate_mesh_policy_payload(files,dict(mesh_policy_id=R6.POLICY_ID,
                mesh_policy_sha256=P.digest(files['mesh-policy.json'])),require_sde=True)
            evidence=policy['source_spacing_evidence']
            self.assertEqual(evidence['conditional_certificate_scope_matches_input'],gate==80)
            self.assertFalse(evidence['actual_cell_spans_verified']);self.assertFalse(evidence['ROI_centroid_moments_qualified'])
        for sn in (82,92):
            with self.assertRaisesRegex(ValueError,'SN87'):C.validate(request(sn=sn))
            model=P.baseline_model(80,sn)
            with self.assertRaisesRegex(ValueError,'SN87'):R6.build(P.raw_json(model),P.geometry.describe_geometry(model,3,1),1)

    def test_identity_mutations_fail_and_a0_preserves_original_producer_policy(self):
        for variant,files in (('main',self.files),('mesh',self.fine)):
            B.geometry_validate_mesh_policy_payload(files,dict(mesh_policy_id=R6.POLICY_ID,
                mesh_policy_sha256=P.digest(files['mesh-policy.json'])),require_sde=True)
            for bit in (0,1):
                req=dict(schema=C.SCHEMA,kind='transient',gate_top_depth_nm=80,sn_junction_depth_nm=87,
                         dimension=3,variant=variant,stored_bit=bit,source_case='A0',d3_source_run='UNIT_FIXTURE_NOT_NATIVE')
                control=P.transient_payload(self.model,req,{'input_only':True},files)
                for name in M.FILES+('geometry-contract.json',):self.assertEqual(control[name],files[name])
                self.assertNotIn(b'HeavyIon(',control['device.cmd'])
                self.assertFalse(json.loads(control['source-contract.json'])['native_qualified'])
        for mutation in ('span','inherited','source_z','side'):
            policy=deepcopy(self.policy)
            if mutation=='span':policy['doping_partition_evidence']['actual_cell_spans_verified']=True
            if mutation=='inherited':
                next(w for w in policy['volume_refinements'] if w.get('doping_evidence_class')=='INHERITED_ACTUAL_R5_NO_NEW_CERTIFICATION')['doping_new_mathematical_certification']=True
            if mutation=='source_z':
                next(w for w in policy['volume_refinements'] if w['name']=='AlphaTrackBulkCore')['max_size_um'][2]=.01
            if mutation=='side':
                w=next(w for w in policy['volume_refinements'] if w['name']=='GateSideNormalX1StraightLower')
                w['physical_min_um'][0]-=.001;w['sde_min_um'][0]-=.001
            with self.assertRaises(ValueError):B.geometry_validate_r6_partitions(self.files,json.loads(self.files['geometry-contract.json']),policy,self.definition)
        changed=deepcopy(self.definition);changed['doping_partition_source']['raw_utf8']+=' '
        with self.assertRaisesRegex(ValueError,'evidence differs'):
            R6.doping_partitions(P.raw_json(self.model),P.geometry.describe_geometry(self.model,3,1),changed)

    def test_old_r5_recomputes_input_admits_and_protected_bytes_unchanged(self):
        recreated,_=P.producer_payload(request(policy='dram-see-v4-gradient-mesh-r5'))
        for name,raw in recreated.items():self.assertEqual(raw,(OLD/name).read_bytes(),name)
        B.geometry_admit(OLD,json.loads((OLD/'project.json').read_bytes()),P.first.sha(P.ROOT/'scripts/tcad.py'))
        before=json.loads((OUT/'prechange.json').read_bytes())
        self.assertTrue(before['assumptions_precede_implementation'])
        self.assertEqual(before['assumptions_sha256'],P.first.sha(P.HERE/'MESH-GRADIENT-R6-ASSUMPTIONS.md'))
        for path,entry in before['files'].items():
            if entry['expected_unchanged']:self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(),entry['sha256'],path)
        def function_source(text,name):
            return text.split('def '+name+'(',1)[1].split('\n\ndef ',1)[0]
        self.assertEqual(function_source((OUT/'before/geometry_bridge.py').read_text(encoding='utf-8'),'geometry_validate_r5_partitions'),
                         function_source((P.HERE/'geometry_bridge.py').read_text(encoding='utf-8'),'geometry_validate_r5_partitions'))
        for name in ('mesh_policy_v6.py','mesh_policy_registry.py','case_contract.py','geometry_bridge.py'):
            ast.parse((P.HERE/name).read_text(encoding='utf-8'),feature_version=(3,6))


if __name__=='__main__':
    print('Preserved r6 unit inputs, never a native run:',FIXTURE,flush=True)
    unittest.main(verbosity=2)
