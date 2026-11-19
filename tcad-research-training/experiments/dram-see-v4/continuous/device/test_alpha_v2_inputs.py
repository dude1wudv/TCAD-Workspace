"""New alpha-v2 device binding only; no source-math suite or native dispatch."""
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import unittest
import uuid

import alpha_v2_inputs as V
import case_contract as C
import decks
import geometry_bridge as B
import prepare_case as D
import prospective as P

RUNTIME=D.ROOT/'local_runtime/dram-see-v4/continuous/device'
FIXTURE=RUNTIME/('UNIT_FIXTURE_NOT_NATIVE-alpha-v2-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
PACKET=D.ROOT/'local_runtime/dram-see-v4/continuous/proton/alpha-v2-examples-r2/g70-sn82-e3-a30/source-features.json'
D3_INPUT=RUNTIME/'projects/20261017T080307Z-v4-continuous-b1-d3-r3'


def request(case='Aalpha',bit=0,variant='main'):
    value=dict(schema=C.SCHEMA_V2,kind='transient',particle='alpha',source_version=V.VERSION,
        source_packet_file=str(PACKET),source_case=case,stored_bit=bit,variant=variant,
        gate_top_depth_nm=70,sn_junction_depth_nm=82,dimension=3,d3_source_run='UNIT_FIXTURE_NOT_NATIVE')
    if case!='A0':value['matched_a0_project']='UNIT_FIXTURE_NOT_NATIVE'
    return value


class AlphaV2Inputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FIXTURE.mkdir(exist_ok=False)
        (FIXTURE/'SYNTHETIC_NOT_NATIVE').write_bytes(b'Pure input adapter tests. No successful D3, production project or native response is fabricated.\n')
        cls.producer={name:(D3_INPUT/name).read_bytes() for name in D.PHYSICS_FILES}
        cls.producer.update({name:(PACKET.parent/name).read_bytes() for name in ('model.proposed.json','geometry-contract.json')})
        cls.model=json.loads(cls.producer['model.proposed.json'])
        cls.files,cls.source,cls.record=V.load_original(PACKET,cls.producer)

    def test_explicit_version_and_positive_only(self):
        actual=C.validate(request())
        self.assertEqual(actual['source_features_file'],str(PACKET))
        self.assertEqual(C.role_id(actual),'B2-A2-main-b0')
        self.assertEqual(C.role_id(request('A0',1)),'B1-A0-alpha-v2-main-b1')
        for bad in (dict(request(),schema=C.SCHEMA),dict(request(),source_case='H'),dict(request(),source_case='Z'),
                    dict(request(),source_case='split'),dict(request(),energy_MeV=5),dict(request(),source_version='v999')):
            with self.assertRaises(ValueError):C.validate(bad)

    def test_original_bytes_and_authoritative_energy_direction(self):
        for name in V.INPUTS:self.assertEqual(self.files[name],(PACKET.parent/name).read_bytes())
        self.assertEqual(self.record['source_feature_version']['version_id'],V.VERSION)
        self.assertEqual(self.record['source_conditions']['energy_MeV'],3)
        self.assertEqual(self.record['source_conditions']['angle_deg'],30)
        self.assertEqual(self.model['alpha']['first_energy_MeV'],5)
        self.assertEqual(self.model['alpha']['angle_deg_from_positive_z'],0)
        self.assertGreater(self.source['path']['length_um'],1.)
        self.assertEqual(self.source['path']['end_planes'],'Perpendicular to direction at s=0 and s=L')
        self.assertFalse(self.source['native_source_qualified'])
        self.assertNotIn('energy_MeV',C.validate(request()))

    def test_both_bits_and_time_refinement_match_exact_inactive_a0(self):
        for bit in (0,1):
            for variant in ('main','time'):
                signal=V.render_payload(self.model,request('Aalpha',bit,variant),self.producer,self.files,self.source,self.record)
                a0=V.render_payload(self.model,request('A0',bit,variant),self.producer,self.files,self.source,self.record)
                self.assertEqual(V.source_free_deck(signal),a0['device.cmd'].decode())
                self.assertEqual(signal['source-contract.json'],self.files['source-contract.json'])
                self.assertEqual(a0['source-contract.json'],self.files['source-contract.json'])
                self.assertEqual(signal['run-parameters.par'],self.producer['physics.par']+b'\n'+self.files['source.par'])
                self.assertNotIn('run-parameters.par',a0);self.assertNotIn(b'HeavyIon(',a0['device.cmd'])
                self.assertFalse(json.loads(a0['device-source-binding.json'])['source_active'])
                self.assertEqual(signal['source-packet.json'],a0['source-packet.json'])
                window=json.loads(signal['source-time-contract.json'])
                self.assertEqual(window['observation_window_s'],self.source['required_source_window_s'])
                self.assertFalse(window['native_endpoint_semantics_verified'])
                segments=decks.transient_segments(self.model,.5 if variant=='time' else 1,window['observation_window_s'],window['main_max_step_s'])
                pulse=next(s for s in segments if s['source_window'])
                self.assertEqual([pulse['start_s'],pulse['end_s']],self.source['required_source_window_s'])
                self.assertEqual(pulse['max_step_s'],2e-14 if variant=='time' else 4e-14)
                folder=FIXTURE/('signal-'+variant+'-b'+str(bit));folder.mkdir()
                chosen={**signal,'case_contract.py':(D.HERE/'case_contract.py').read_bytes(),'controlled-request.json':P.encoded(C.validate(request('Aalpha',bit,variant)))}
                for name,raw in chosen.items():(folder/name).write_bytes(raw)
                cfg=dict(role_id=C.role_id(request('Aalpha',bit,variant)),size_id=C.size_id(70),numerical_variant=variant,sn_junction_depth_nm=82)
                B.geometry_validate_current_case(folder,cfg,{n:P.sha(v) for n,v in chosen.items()},self.model,signal['device.cmd'].decode())

    def test_actual_d3_and_h2_packet_mismatch_rejected(self):
        changed=dict(self.producer);changed['geometry-contract.json']=P.encoded({'not_the_original_D3':True})
        with self.assertRaisesRegex(ValueError,'source/actual D3 input differs'):
            V.render_payload(self.model,request(),changed,self.files,self.source,self.record)
        with self.assertRaisesRegex(ValueError,'matching actual D3 mesh'):
            V.render_payload(self.model,request(variant='mesh'),self.producer,self.files,self.source,self.record)

    def test_frozen_v2_byte_guard_preserves_source_and_holdout_notice(self):
        req=C.validate(request())
        identity={name:'UNIT_FIXTURE_NOT_NATIVE_NO_ORIGINAL_ARCHIVE' for name in
                  ('producer_run_id','source_manifest_sha256','source_archive_sha256','mesh_sha256','geometry_validation_sha256')}
        identity.update(model_sha256=P.sha(self.producer['model.proposed.json']),geometry_contract_sha256=P.sha(self.producer['geometry-contract.json']),
                        physics_sha256={name:P.sha(self.producer[name]) for name in D.PHYSICS_FILES})
        record=dict(self.record,actual_D3_binding=identity)
        files=V.render_payload(self.model,req,self.producer,self.files,self.source,record)
        files['role-contract.json']=P.encoded(dict(stored_bit=0,numerical_variant='main',source_configured=True,
            source_packet_sha256=P.sha(files['source-packet.json']),source_time_contract_sha256=P.sha(files['source-time-contract.json'])))
        folder=FIXTURE/'byte-guard-only';folder.mkdir()
        for name,raw in files.items():(folder/name).write_bytes(raw)
        B.geometry_validate_alpha_v2_binding(folder,identity,req,self.model,files['device.cmd'].decode())
        changed=json.loads(files['device-source-binding.json']);changed['original_data_design_notice']['original_final_axes_or_condition']=True
        (folder/'device-source-binding.json').write_bytes(P.encoded(changed))
        with self.assertRaisesRegex(ValueError,'original holdout notice differs'):
            B.geometry_validate_alpha_v2_binding(folder,identity,req,self.model,files['device.cmd'].decode())

    def test_v1_solver_bytes_match_frozen_generator_before_v2(self):
        old=P.module(D3_INPUT/'generator-prepare_case.py','_pre_v2_frozen_prepare_case')
        producer={name:(D3_INPUT/name).read_bytes() for name in D.PHYSICS_FILES+('model.proposed.json','geometry-contract.json')}
        model=json.loads(producer['model.proposed.json'])
        for case,bit,variant in (('A0',0,'main'),('A0',1,'time'),('Aalpha',0,'main')):
            req=dict(schema=C.SCHEMA,kind='transient',gate_top_depth_nm=80,sn_junction_depth_nm=87,dimension=3,variant=variant,
                source_case=case,stored_bit=bit,d3_source_run='UNIT_FIXTURE_NOT_NATIVE')
            if case!='A0':req['matched_a0_project']='UNIT_FIXTURE_NOT_NATIVE'
            before=old.transient_payload(model,req,None,producer);after=D.transient_payload(model,req,None,producer)
            for name in ('device.cmd','parameter-binding.json','numerical-method.json')+D.PHYSICS_FILES:
                self.assertEqual(before[name],after[name],name)
            if case=='Aalpha':
                for name in ('heavyion.physics.inc','source.par','run-parameters.par','alpha-profile.csv'):self.assertEqual(before[name],after[name])

    def test_real_registered_v2_two_bit_prospective_binding(self):
        packet=PACKET.parent.parent/'g80-sn87-e5-a0/source-features.json'
        producer={name:(D3_INPUT/name).read_bytes() for name in D.PHYSICS_FILES}
        producer.update({name:(packet.parent/name).read_bytes() for name in ('model.proposed.json','geometry-contract.json')})
        model=json.loads(producer['model.proposed.json'])
        original,source,record=V.load_original(packet,producer)
        bound=[]
        for bit in (0,1):
            data=D.ROOT/'local_runtime/dram-see-v4/continuous/data/source-compatible-qualification-r1'/('data-input-b'+str(bit)+'.json')
            req=C.validate(dict(request('Aalpha',bit),gate_top_depth_nm=80,sn_junction_depth_nm=87,
                                source_packet_file=str(packet),registered_data_input=str(data)))
            files=V.render_payload(model,req,producer,original,source,record)
            extra,binding=P.bind(files,req,model)
            self.assertEqual(extra['data-input.json'],data.read_bytes())
            self.assertEqual(extra['source-features.json'],packet.read_bytes())
            self.assertIn('source_features_v2.py',binding['verification_code_sha256'])
            self.assertNotIn('source_features.py',binding['verification_code_sha256'])
            self.assertEqual(binding['source_feature_version']['version_id'],V.VERSION)
            self.assertNotIn('plan_sha256',binding['registered_identity'])
            files.update(extra)
            source_binding=json.loads(files['device-source-binding.json'])
            source_binding.update(prospective_source_binding_sha256=P.sha(files['source-feature-binding.json']),
                                  prospective_source_features_sha256=P.sha(files['source-features.json']))
            files['device-source-binding.json']=P.encoded(source_binding)
            spec=json.loads(files['source-spec.json']);spec.update(data_input_sha256=P.sha(files['data-input.json']),
                source_features_sha256=P.sha(files['source-features.json']));files['source-spec.json']=P.encoded(spec)
            files['controlled-request.json']=P.encoded(req)
            target=FIXTURE/('real-prospective-input-only-b'+str(bit));target.mkdir()
            for name,raw in files.items():(target/name).write_bytes(raw)
            B.geometry_validate_prospective_binding(target,model)
            (target/'INPUT_ONLY_NOT_NATIVE.json').write_bytes(P.encoded(dict(
                pure_source_recomputed=True,original_registered_input_rebuilt=True,
                source_packet_sha256=P.sha(packet.read_bytes()),data_input_sha256=P.sha(data.read_bytes()),
                verifier_sha256=binding['source_feature_version']['verifier']['sha256'],
                dispatcher_sha256=binding['source_feature_version']['dispatcher']['sha256'],
                actual_D3_archive_bound=False,native_source_qualified=False,native_submission=False)))
            bound.append(files)
        self.assertEqual(bound[0]['source-features.json'],bound[1]['source-features.json'])
        self.assertNotEqual(bound[0]['data-input.json'],bound[1]['data-input.json'])


if __name__=='__main__':
    print('Preserved v2 adapter-only evidence:',FIXTURE)
    unittest.main(verbosity=2)
