"""Only the newly controlled SN-depth behavior; never native qualification."""
import copy
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import unittest
import uuid

import case_contract as C
import doping_patch
import geometry_bridge as B
import prepare_case as D

RUNTIME=D.ROOT/'local_runtime/dram-see-v4/continuous/device'
FIXTURE=RUNTIME/('UNIT_FIXTURE_NOT_NATIVE-sn-parameters-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])


def dc(sn=87,gate=80,dimension=3):
    return dict(schema=C.SCHEMA,kind='dc',gate_top_depth_nm=gate,sn_junction_depth_nm=sn,dimension=dimension,variant='main')


def a0(sn=87,gate=80,bit=0):
    return dict(schema=C.SCHEMA,kind='transient',gate_top_depth_nm=gate,sn_junction_depth_nm=sn,dimension=3,
                variant='main',source_case='A0',stored_bit=bit,d3_source_run='UNIT_FIXTURE_NOT_NATIVE')


class SNParameters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FIXTURE.mkdir(parents=True,exist_ok=False)
        (FIXTURE/'SYNTHETIC_NOT_NATIVE').write_bytes(b'Controlled input/parameter checks only. No collected D3 or original result archive is fabricated.\n')
        cls.default,cls.model=D.producer_payload(dc())

    def test_default_whitelist_and_independent_parameter_identity(self):
        omitted=dc();omitted.pop('sn_junction_depth_nm')
        self.assertEqual(C.validate(omitted)['sn_junction_depth_nm'],87)
        self.assertEqual(D.producer_payload(omitted),D.producer_payload(dc()))
        for gate in (70,80,90):
            for sn in (82,87,92):
                self.assertEqual(C.validate(a0(sn,gate))['sn_junction_depth_nm'],sn)
                self.assertIn('sn-junction-depth-'+str(sn)+'nm',C.parameter_id(dc(sn,gate)))
        for sn in (81,88,93,True,82.0,'82'):
            with self.assertRaisesRegex(ValueError,'SN junction depth'):C.validate(dc(sn))
        self.assertEqual(C.parse_depth_change('请将SN结深改为82 nm'),{'sn_junction_depth_nm':82})
        with self.assertRaises(ValueError):C.parse_depth_change('将SN结深改为82 nm; run()')

    def test_real_sde_initializer_and_original_probe_policy(self):
        for dimension in (2,3):
            default,_=D.producer_payload(dc(dimension=dimension))
            reference=json.loads(default['measurement-plan.json'])
            signatures=lambda plan:[{k:v for k,v in row.items() if k!='expected'} for row in plan['measurements']]
            concentrations=[]
            for sn in (82,87,92):
                files,model=D.producer_payload(dc(sn,dimension=dimension))
                geometry=json.loads(files['geometry-contract.json']);plan=json.loads(files['measurement-plan.json'])
                self.assertEqual(model['doping']['sn_junction_depth_nm'],sn)
                self.assertEqual(model['geometry']['units'],'nm');self.assertEqual(model['doping']['units'],'cm^-3')
                self.assertEqual(geometry['doping']['a_sn_um'],(sn/1000.)/math.sqrt(math.log(1450.)))
                self.assertIn(('s2_asn='+format(sn/1000.,'.15g')+'/sqrt(log(1450))').encode(),files['geometry-with-measurements.scm'])
                self.assertIn(b's2_asn',files['geometry-with-measurements.scm'])
                self.assertIn(b'abs(',files['geometry-with-measurements.scm'])
                self.assertEqual(signatures(plan),signatures(reference))
                self.assertEqual(plan['comparison_policy'],reference['comparison_policy'])
                self.assertEqual(plan['contact_probes'],reference['contact_probes'])
                self.assertEqual(plan['material_probes'],reference['material_probes'])
                point=[-.052,.087] if dimension==2 else [-.052,0.,.087]
                row=next(row for row in plan['measurements'] if row.get('native_position')==point and row['field']=='ArsenicActiveConcentration')
                expected=doping_patch.original_value(-.052,.087,sn)
                self.assertEqual(row['expected'],expected)
                self.assertAlmostEqual(doping_patch.stable_value(-.052,.087,sn)/expected,1.,places=13)
                concentrations.append(row['expected'])
                for name in D.PHYSICS_FILES:self.assertEqual(files[name],self.default[name])
            self.assertLess(concentrations[0],concentrations[1]);self.assertLess(concentrations[1],concentrations[2])

    def test_a0_inherits_actual_selected_model_bytes_and_rejects_wrong_sn(self):
        for gate,sn in ((70,82),(80,82),(80,87),(80,92),(90,92)):
            producer,model=D.producer_payload(dc(sn,gate))
            for bit in (0,1):
                req=a0(sn,gate,bit)
                files=D.transient_payload(model,req,{'unit_input_identity_only':True},producer)
                for name in D.PHYSICS_FILES+('model.proposed.json','geometry-contract.json'):
                    self.assertEqual(files[name],producer[name])
                self.assertNotIn(b'HeavyIon(',files['device.cmd'])
                self.assertNotIn('run-parameters.par',files)
                self.assertEqual(json.loads(files['controlled-parameters.json'])['sn_junction_depth_nm'],sn)
                if (gate,sn)!=(80,87):
                    self.assertNotIn('alpha-reference.json',files)
                    self.assertEqual(json.loads(files['source-spec.json'])['role'],'CONTROL')
                    self.assertIsNone(json.loads(files['source-contract.json'])['source_oracle'])
                wrong=a0(87 if sn!=87 else 82,gate,bit)
                with self.assertRaisesRegex(ValueError,'D3 SN junction depth differs'):
                    D.transient_payload(model,wrong,{'unit_input_identity_only':True},producer)

    def test_v1_particle_boundaries_and_original_fixed_source_bytes(self):
        for sn,gate in ((82,80),(92,80),(87,70),(87,90)):
            req=dict(a0(sn,gate),source_case='Aalpha',matched_a0_project='UNIT_FIXTURE_NOT_NATIVE')
            with self.assertRaisesRegex(ValueError,'alpha v1 source requires'):C.validate(req)
            req=dict(a0(sn,gate),particle='proton',proton_source_bundle='UNIT_FIXTURE_NOT_NATIVE')
            with self.assertRaisesRegex(ValueError,'proton v1 source/control requires'):C.validate(req)
        registry=json.loads((D.HERE.parent/'proton/source-feature-versions.json').read_bytes())
        version=next(value for value in registry['versions'] if value['version_id']=='v1-s2')
        manifest=json.loads((D.ROOT/version['dependency_snapshot']['repository_relative_path']).read_bytes())
        original=manifest['dependencies']['alpha_reference']
        self.assertEqual(hashlib.sha256((D.ROOT/original['repository_relative_path']).read_bytes()).hexdigest(),original['sha256'])

    def test_new_parameter_manifest_guard_rejects_relabeling(self):
        req=C.validate(dc(82));files,model=D.producer_payload(req)
        folder=FIXTURE/'dc-sn82';folder.mkdir()
        selected=dict(files,**{'controlled-request.json':D.raw_json(req),'case_contract.py':(D.HERE/'case_contract.py').read_bytes()})
        for name,raw in selected.items():(folder/name).write_bytes(raw)
        cfg=dict(mode='produce',role_id='B1-D3',size_id=C.size_id(80),numerical_variant='main',sn_junction_depth_nm=82,
            parameter_id=C.parameter_id(req),controlled_parameters_sha256=D.digest(files['controlled-parameters.json']))
        hashes={name:D.digest(raw) for name,raw in selected.items()}
        B.geometry_validate_current_case(folder,cfg,hashes,model,files['device.cmd'].decode())
        altered=copy.deepcopy(model);altered['doping']['sn_junction_depth_nm']=87
        with self.assertRaisesRegex(ValueError,'gate/SN depth'):
            B.geometry_validate_current_case(folder,cfg,hashes,altered,files['device.cmd'].decode())
        description=json.loads(files['controlled-parameters.json']);description['sn_junction_depth_nm']=87
        (folder/'controlled-parameters.json').write_bytes(D.raw_json(description))
        cfg['controlled_parameters_sha256']=D.digest(D.raw_json(description))
        with self.assertRaisesRegex(ValueError,'actual Gaussian/units definition'):
            B.geometry_validate_current_case(folder,cfg,hashes,model,files['device.cmd'].decode())

    def test_control_guard_requires_the_same_d3_identity(self):
        req=C.validate(a0(82,70));producer,model=D.producer_payload(dc(82,70))
        identity={name:'UNIT_FIXTURE_NOT_NATIVE_NO_ORIGINAL_ARCHIVE' for name in
                  ('producer_run_id','source_manifest_sha256','source_archive_sha256','mesh_sha256','geometry_validation_sha256')}
        identity.update(model_sha256=D.digest(producer['model.proposed.json']),
                        geometry_contract_sha256=D.digest(producer['geometry-contract.json']))
        files=D.transient_payload(model,req,identity,producer)
        folder=FIXTURE/'a0-gate70-sn82';folder.mkdir()
        selected=dict(files,**{'controlled-request.json':D.raw_json(req),'case_contract.py':(D.HERE/'case_contract.py').read_bytes()})
        for name,raw in selected.items():(folder/name).write_bytes(raw)
        cfg=dict(identity,mode='reuse',role_id='B1-A0-main-b0',size_id=C.size_id(70),numerical_variant='main',
            sn_junction_depth_nm=82,parameter_id=C.parameter_id(req),
            controlled_parameters_sha256=D.digest(files['controlled-parameters.json']))
        hashes={name:D.digest(raw) for name,raw in selected.items()}
        B.geometry_validate_current_case(folder,cfg,hashes,model,files['device.cmd'].decode())
        B.geometry_validate_controlled_a0(folder,cfg,req)
        with self.assertRaisesRegex(ValueError,'A0/D3 identity differs: mesh_sha256'):
            B.geometry_validate_current_case(folder,dict(cfg,mesh_sha256='ANOTHER_DECLARED_MESH'),hashes,model,files['device.cmd'].decode())
        source=json.loads(files['source-contract.json']);source['source_oracle']='BORROWED_S2_REFERENCE'
        (folder/'source-contract.json').write_bytes(D.raw_json(source))
        with self.assertRaisesRegex(ValueError,'source absence or selected model differs'):
            B.geometry_validate_controlled_a0(folder,cfg,req)


if __name__=='__main__':
    print('Preserved parameter-only fixtures:',FIXTURE)
    unittest.main(verbosity=2)
