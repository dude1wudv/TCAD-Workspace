"""New adapter checks only. Mocked mathematics is explicitly not native evidence."""
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import geometry_bridge as bridge
import prospective as P

ROOT=P.ROOT/'local_runtime/dram-see-v4/continuous/device'
FIXTURE=ROOT/('UNIT_FIXTURE_NOT_NATIVE-prospective-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])


class ProspectiveBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FIXTURE.mkdir(parents=True,exist_ok=False)
        (FIXTURE/'SYNTHETIC_NOT_NATIVE').write_text('Adapter mocks only. No source mathematics or native qualification.\n',encoding='utf-8')
        cls.feature_code=FIXTURE/'feature-verifier-fixture.py';cls.feature_code.write_text('# UNIT_FIXTURE_NOT_NATIVE\n')
        cls.data_code=FIXTURE/'data-verifier-fixture.py';cls.data_code.write_text('# UNIT_FIXTURE_NOT_NATIVE\n')
        verifier=FIXTURE/'source_features.py';verifier.write_bytes(b'# Different original v1 fixture\n')
        dependency=FIXTURE/'registered-dependencies.json';dependency.write_bytes(P.encoded({'UNIT_FIXTURE_NOT_NATIVE':True}))
        registry=FIXTURE/'registry-fixture.json';registry.write_bytes(P.encoded({'versions':[{'version_id':'v1-s2',
            'verifier_sha256':P.sha(verifier.read_bytes()),'dependency_snapshot':{'sha256':P.sha(dependency.read_bytes())}}]}))
        cls.version=dict(version_id='v1-s2',**{name:{'path':str(path),'sha256':P.sha(path.read_bytes())}
            for name,path in [('verifier',verifier),('dispatcher',cls.feature_code),('registry',registry),('dependency_manifest',dependency)]})
        cls.model={'geometry':{'gate_top_depth_nm':80},'doping':{'sn_junction_depth_nm':87}}
        cls.files={'model.proposed.json':P.encoded(cls.model),'geometry-contract.json':b'{"UNIT_FIXTURE_NOT_NATIVE":true}\n',
                   'alpha-profile.csv':b'UNIT_FIXTURE_NOT_NATIVE\n','heavyion.physics.inc':b'UNIT_SOURCE\n',
                   'source.par':b'UNIT_PARAMETERS\n','physics-manifest.json':b'{"UNIT_FIXTURE_NOT_NATIVE":true}\n',
                   'field-measurements.csv':b'MUST_NEVER_REACH_SOURCE_VERIFIER\n'}
        cls.contract=P.encoded({'schema':'UNIT_FIXTURE_NOT_NATIVE-source-feature-contract'})

    def inputs(self,label,bit=0,mutation=None):
        folder=FIXTURE/label;folder.mkdir()
        values={'unit_source_quantity_'+str(i):float(i) for i in range(13)}
        packet={'source_features':values,'inputs':{name:{'path':str(folder/name),'sha256':P.sha(raw)}
                for name,raw in P.pure_input_files(self.files,'Aalpha').items()},
                'feature_contract':json.loads(self.contract),'feature_contract_sha256':P.sha(self.contract)}
        packet['implementations']={'source_features.py':self.version['verifier']}
        if mutation:mutation(packet)
        packet_path=folder/'source-features.json';packet_path.write_bytes(P.encoded(packet))
        row={'schema':'dram-see-v4-registered-data-input-v2','source_features':copy.deepcopy(values),
             'source_features_sha256':P.sha(packet_path.read_bytes()),'source_feature_contract_sha256':P.sha(self.contract),
             'source_features_ref':{'path':str(packet_path),'sha256':P.sha(packet_path.read_bytes())},
             'stored_bit':bit,'gate_top_depth_nm':80,'sn_junction_depth_nm':87,
             'physics_manifest_sha256':P.sha(self.files['physics-manifest.json']),
             'plan_sha256':'a'*64,'design_sha256':'b'*64,'circuit_contract_sha256':'c'*64}
        data=folder/'data-input-original.json';data.write_bytes(P.encoded(row))
        request={'kind':'transient','source_case':'Aalpha','stored_bit':bit,
                 'source_features_file':str(packet_path),'registered_data_input':str(data)}
        return folder,packet,row,request

    def call(self,packet,row,request):
        calls=[]
        def verify(path,input_files):
            calls.append(('source',path,set(input_files)))
            self.assertEqual(input_files,P.pure_input_files(self.files,'Aalpha'))
            self.assertNotIn('field-measurements.csv',input_files)
            return packet
        def registered(path):calls.append(('registered',path));return row
        feature=SimpleNamespace(verify=verify,contract_bytes=lambda packet:self.contract,version_info=lambda packet:self.version)
        data=SimpleNamespace(verify_registered_input=registered)
        with patch.object(P,'FEATURE_VERIFIER',self.feature_code),patch.object(P,'DATA_VERIFIER',self.data_code),\
             patch.object(P,'module',side_effect=[feature,data]):
            result=P.bind(self.files,request,self.model)
        self.assertEqual([x[0] for x in calls],['source','registered'])
        return result

    def test_same_packet_two_bits_and_frozen_relationships(self):
        folder,packet,row,request=self.inputs('two-bits')
        first,binding=self.call(packet,row,request)
        self.assertNotEqual(binding['verification_code_sha256']['source_features.py'],
                            binding['verification_code_sha256']['source_feature_versions.py'])
        self.assertEqual(binding['source_feature_version'],self.version)
        row1=dict(row,stored_bit=1);path1=folder/'data-bit1.json';path1.write_bytes(P.encoded(row1))
        second,_=self.call(packet,row1,dict(request,stored_bit=1,registered_data_input=str(path1)))
        self.assertEqual(first['source-features.json'],second['source-features.json'])
        self.assertNotEqual(first['data-input.json'],second['data-input.json'])
        frozen=folder/'frozen-byte-relationship-fixture';frozen.mkdir()
        for name,raw in {**self.files,**first}.items():(frozen/name).write_bytes(raw)
        (frozen/'controlled-request.json').write_bytes(P.encoded(request))
        (frozen/'source-contract.json').write_bytes(P.encoded({
            'prospective_source_binding_sha256':P.sha(first['source-feature-binding.json']),
            'prospective_source_features_sha256':P.sha(first['source-features.json'])}))
        bridge.geometry_validate_prospective_binding(frozen,self.model)
        (frozen/'geometry-contract.json').write_bytes(b'{"tampered":true}\n')
        with self.assertRaisesRegex(ValueError,'pure source/geometry'):
            bridge.geometry_validate_prospective_binding(frozen,self.model)

    def test_false_flag_does_not_replace_real_input_hash(self):
        _,packet,row,request=self.inputs('adverse-input-hash',mutation=lambda p:p['inputs']['geometry-contract.json'].update(sha256='d'*64))
        packet['verified']=True
        Path(request['source_features_file']).write_bytes(P.encoded(packet))
        row['source_features_sha256']=row['source_features_ref']['sha256']=P.sha(Path(request['source_features_file']).read_bytes())
        Path(request['registered_data_input']).write_bytes(P.encoded(row))
        with self.assertRaisesRegex(ValueError,'actual input: geometry-contract.json'):
            self.call(packet,row,request)

    def test_registered_bit_and_physics_mismatch_rejected(self):
        for field,value in [('stored_bit',1),('physics_manifest_sha256','e'*64)]:
            _,packet,row,request=self.inputs('adverse-'+field)
            row[field]=value;Path(request['registered_data_input']).write_bytes(P.encoded(row))
            with self.assertRaisesRegex(ValueError,'Registered (bit|physical model) differs'):
                self.call(packet,row,request)

    def test_upstream_recomputation_rejection_propagates(self):
        _,packet,row,request=self.inputs('adverse-upstream')
        feature=SimpleNamespace(verify=lambda *args,**kwargs:(_ for _ in ()).throw(ValueError('Pure-input recomputation rejected contaminated source')))
        with patch.object(P,'FEATURE_VERIFIER',self.feature_code),patch.object(P,'DATA_VERIFIER',self.data_code),\
             patch.object(P,'module',side_effect=[feature,object()]):
            with self.assertRaisesRegex(ValueError,'recomputation rejected'):
                P.bind(self.files,request,self.model)

    def test_verifier_implementation_change_during_call_rejected(self):
        folder,packet,row,request=self.inputs('adverse-verifier-race')
        code=folder/'changing-verifier.py';code.write_bytes(b'# before\n')
        def verify(*args,**kwargs):code.write_bytes(b'# changed during verification\n');return packet
        feature=SimpleNamespace(verify=verify,contract_bytes=lambda packet:self.contract)
        data=SimpleNamespace(verify_registered_input=lambda path:row)
        with patch.object(P,'FEATURE_VERIFIER',code),patch.object(P,'DATA_VERIFIER',self.data_code),\
             patch.object(P,'module',side_effect=[feature,data]):
            with self.assertRaisesRegex(ValueError,'implementation changed'):
                P.bind(self.files,request,self.model)

    def test_qualification_requires_input_identity_not_training_plan(self):
        folder,packet,row,request=self.inputs('qualification-without-training-plan')
        row.update(purpose='qualification',source_case='Aalpha',numerical_variant='main',registration_request_sha256='f'*64)
        row.pop('plan_sha256');row.pop('design_sha256')
        Path(request['registered_data_input']).write_bytes(P.encoded(row));request['variant']='main'
        frozen,binding=self.call(packet,row,request)
        self.assertNotIn('plan_sha256',binding['registered_identity'])
        self.assertNotIn('design_sha256',binding['registered_identity'])
        target=folder/'byte-relationship-only';target.mkdir()
        for name,raw in {**self.files,**frozen}.items():(target/name).write_bytes(raw)
        (target/'controlled-request.json').write_bytes(P.encoded(request))
        (target/'source-contract.json').write_bytes(P.encoded({
            'prospective_source_binding_sha256':P.sha(frozen['source-feature-binding.json']),
            'prospective_source_features_sha256':P.sha(frozen['source-features.json'])}))
        bridge.geometry_validate_prospective_binding(target,self.model)


if __name__=='__main__':
    print('Preserved adapter-only fixture:',FIXTURE)
    unittest.main(verbosity=2)
