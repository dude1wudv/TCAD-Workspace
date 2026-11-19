"""Focused tests for newly migrated controlled cases. No fabricated native archive."""
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
import uuid

import case_contract as c
import geometry_bridge as b
import prepare_case as p

RUNTIME = p.ROOT/'local_runtime/dram-see-v4/continuous/device'
FIXTURES = RUNTIME/('UNIT_FIXTURE_NOT_NATIVE-controlled-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])


def dc(depth=80, variant='main'):
    return dict(schema=c.SCHEMA, kind='dc', dimension=3, gate_top_depth_nm=depth, variant=variant)


def transient(case, bit=0, variant='main'):
    result=dict(schema=c.SCHEMA, kind='transient', dimension=3, gate_top_depth_nm=80,
                variant=variant, stored_bit=bit, source_case=case, d3_source_run='UNIT_FIXTURE_NOT_NATIVE')
    if case!='A0':result['matched_a0_project']='UNIT_FIXTURE_NOT_NATIVE'
    return result


class ControlledCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.producer,cls.model=p.producer_payload(dc())
        FIXTURES.mkdir(parents=True,exist_ok=False)
        (FIXTURES/'SYNTHETIC_NOT_NATIVE').write_text('Unit payloads only; no solver or native qualification.\n',encoding='utf-8')

    def test_whitelist_and_natural_language(self):
        self.assertEqual(c.parse_depth_change('将栅顶深度改为70 nm'),{'gate_top_depth_nm':70})
        self.assertEqual(c.parse_depth_change('请把栅顶深度设置为90纳米。'),{'gate_top_depth_nm':90})
        for text in ('栅顶深度改为75 nm','将栅顶深度改为70nm; run()','把有源宽度设为90nm'):
            with self.assertRaises(ValueError):c.parse_depth_change(text)
        for request in (dict(dc(),gate_top_depth_nm=True),dict(dc(),code='print(1)'),
                        dict(transient('Aalpha'),energy_MeV=7),dict(transient('A0'),gate_top_depth_nm=90)):
            with self.assertRaises(ValueError):c.validate(request)

    def test_geometry_family_refinement_and_retained_native_fixes(self):
        original=json.loads((RUNTIME/'projects/20261017T052753Z-v4-continuous-b1-d3-r2/measurement-plan.json').read_text(encoding='utf-8'))
        current=json.loads(self.producer['measurement-plan.json'])
        for name in ('measurements','contact_probes','material_probes'):
            self.assertEqual(current[name],original[name],name)
        for depth in (70,80,90):
            payload,model=p.producer_payload(dc(depth))
            desc=json.loads(payload['geometry-contract.json'])
            self.assertEqual(desc['size_id'],'gate-top-depth-{}nm'.format(depth))
            self.assertEqual(desc['gate_void']['top_um'],depth/1000)
            self.assertEqual(model['geometry']['active_width_nm'],20)
            self.assertEqual(model['geometry']['metal_bottom_z_nm'],150)
            self.assertNotIn(b'sde:build-mesh',payload['geometry-with-measurements.scm'])
            self.assertIn(b'sdedr:write-cmd-file',payload['geometry-with-measurements.scm'])
            self.assertIn(b'abs(',payload['geometry-with-measurements.scm'])
            self.assertNotIn(b'(bounds (bbox-exact entities))',payload['geometry-with-measurements.scm'])
            self.assertEqual([x['relative_tolerance'] for x in json.loads(payload['measurement-plan.json'])['measurements']],
                             [x['relative_tolerance'] for x in original['measurements']])
        fine,_=p.producer_payload(dc(80,'mesh'))
        a,z=(json.loads(x['geometry-contract.json'])['mesh'] for x in (self.producer,fine))
        for broad,tight in zip(a['windows'],z['windows']):
            self.assertEqual(tight['max_size_um'],[v*.5 for v in broad['max_size_um']])
            self.assertEqual(tight['min_size_um'],[v*.5 for v in broad['min_size_um']])
        self.assertEqual(z['active_doping_refinement']['max_element_um'],[.0005,.0025,.0005])

    def test_all_declared_bits_sources_and_active_parameter_binding(self):
        count=0
        for bit in (0,1):
            for variant in ('main','mesh','time'):
                baseline=p.transient_payload(self.model,transient('A0',bit,variant),{'unit_payload_only':True},self.producer)
                for source in ('A0','Aalpha','Z','H','split') if variant=='main' else ('A0','Aalpha'):
                    request=transient(source,bit,variant)
                    files=p.transient_payload(self.model,request,{'unit_payload_only':True},self.producer)
                    self.assertEqual(p.source_free_deck(files,source),baseline['device.cmd'].decode())
                    for name in p.PHYSICS_FILES:self.assertEqual(files[name],self.producer[name])
                    folder=FIXTURES/(source+'-'+variant+'-b'+str(bit));folder.mkdir()
                    selected={name:raw for name,raw in files.items() if name.endswith(('.par','.inc')) or name=='parameter-binding.json'}
                    selected['controlled-request.json']=p.raw_json(request)
                    selected['case_contract.py']=(p.HERE/'case_contract.py').read_bytes()
                    for name,raw in selected.items():(folder/name).write_bytes(raw)
                    cfg=dict(role_id=c.role_id(request),size_id=c.size_id(80),numerical_variant=variant)
                    b.geometry_validate_current_case(folder,cfg,{name:p.digest(raw) for name,raw in selected.items()},self.model,files['device.cmd'].decode())
                    if source=='A0':self.assertNotIn(b'HeavyIon(',files['device.cmd'])
                    else:
                        prefix='' if source=='Aalpha' else source+'.'
                        self.assertEqual(files['run-parameters.par'],files['physics.par']+b'\n'+files[prefix+'source.par'])
                    count+=1
        self.assertEqual(count,18)

    def test_reject_hidden_parameter_override_and_missing_native_d3(self):
        request=transient('Aalpha')
        files=p.transient_payload(self.model,request,{'unit_payload_only':True},self.producer)
        folder=FIXTURES/'adverse-source-override';folder.mkdir()
        selected={name:raw for name,raw in files.items() if name.endswith(('.par','.inc')) or name=='parameter-binding.json'}
        selected['controlled-request.json']=p.raw_json(request)
        selected['case_contract.py']=(p.HERE/'case_contract.py').read_bytes()
        selected['source.par']+=b'Material="Silicon" { Band2BandTunneling { Agen=0 } }\n'
        selected['run-parameters.par']=selected['physics.par']+b'\n'+selected['source.par']
        binding=json.loads(selected['parameter-binding.json'])
        binding['source_sha256']=p.digest(selected['source.par']);binding['active_sha256']=p.digest(selected['run-parameters.par'])
        selected['parameter-binding.json']=p.raw_json(binding)
        for name,raw in selected.items():(folder/name).write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'undeclared override'):
            b.geometry_validate_current_case(folder,dict(role_id=c.role_id(request),size_id=c.size_id(80),numerical_variant='main'),
                {name:p.digest(raw) for name,raw in selected.items()},self.model,files['device.cmd'].decode())
        missing=dict(transient('A0'),d3_source_run=str(FIXTURES/'missing-original-run'))
        with self.assertRaisesRegex(ValueError,'D3 original directory'):
            p.prepare(missing,'unit-missing-native-d3-'+uuid.uuid4().hex)


if __name__=='__main__':
    print('Preserved unit payload evidence:',FIXTURES)
    unittest.main(verbosity=2)
