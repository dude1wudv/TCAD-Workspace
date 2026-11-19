"""New connector behavior only. Every generated fixture is explicitly nonnative.

Original source rendering is reused; this does not fake a transport archive,
test source quadrature again, dispatch TCAD or qualify a source/response.
"""
import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import unittest
import uuid

import case_contract as C
import decks
import geometry_bridge as B
import prepare_case as D
import prospective as P
import proton_inputs as N

RUNTIME=P.ROOT/'local_runtime/dram-see-v4/continuous/device'
FIXTURE=RUNTIME/('UNIT_FIXTURE_NOT_NATIVE-proton-inputs-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])


def request(case,bit=0,variant='main'):
    value=dict(schema=C.SCHEMA,kind='transient',dimension=3,gate_top_depth_nm=80,particle='proton',
        source_case=case,stored_bit=bit,variant=variant,d3_source_run='UNIT_FIXTURE_NOT_NATIVE',
        proton_source_bundle='UNIT_FIXTURE_NOT_NATIVE')
    if case!='A0':value['matched_a0_project']='UNIT_FIXTURE_NOT_NATIVE'
    return C.validate(value)


class ProtonConnector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FIXTURE.mkdir(parents=True,exist_ok=False)
        (FIXTURE/'SYNTHETIC_NOT_NATIVE').write_bytes(b'Pure declared input fixtures; no native event, archive or qualification.\n')
        producer=RUNTIME/'projects/20261017T052753Z-v4-continuous-b1-d3-r2'
        cls.producer={name:(producer/name).read_bytes() for name in D.PHYSICS_FILES+('model.proposed.json','geometry-contract.json')}
        cls.model=json.loads(cls.producer['model.proposed.json'])
        cls.geometry=json.loads(cls.producer['geometry-contract.json'])
        dispatcher=P.module(P.FEATURE_VERIFIER,'_unit_device_fixed_dispatcher')
        cls.version,cls.version_raw=P.version_evidence(dispatcher,particle='proton')
        helper=dispatcher.load_version('v1-s2',particle='proton')
        with helper.proton_modules() as (transport,couple,event):
            # A declared mathematical segment only; never a fabricated native ledger.
            cls.rows=[[-.052,0.,.08,-.052,0.,.09,15e-9,15.0001e-9,1.,.03,2e-12]]
            cls.fragments=couple.represent(cls.rows)
            cls.hi,cls.par=couple.render(cls.fragments)
        cls.wrapper=dict(schema='continuous-bcat-proton-geometry-v1',
            coordinate_transform='identity: TCAD x,y,z_depth in um = Geant4 x,y,z in um',
            gate_transport_material='G4_Galactic',geometry=copy.deepcopy(cls.geometry))

    def fixture_source(self,zero=False):
        bounds=None if zero else [self.rows[0][6],self.rows[0][7]]
        source=dict(schema='continuous-proton-heavyion-candidate-v1',epoch_s=15e-9,event_id=0,eV_per_pair=3.6,
            kernel=dict(width_um=.03,temporal_sigma_s=2e-12,source='original isotropic Gaussian line-convolution'),
            fragment_count=0 if zero else len(self.fragments),source_time_bounds_s=bounds,
            required_source_window_s=None if zero else [bounds[0]-16e-12,bounds[1]+16e-12])
        files={'fragments.json':P.encoded([] if zero else self.fragments),'heavyion.physics.inc':b'' if zero else self.hi.encode(),
            'source.par':b'' if zero else self.par.encode(),'heavyion.plot.inc':b'HeavyIonGeneration HeavyIonChargeDensity\n',
            'heavyion.currentplot.inc':b'CurrentPlot { HeavyIonGeneration(Integrate(Semiconductor)) }\n',
            'sources.dat':b'NUCLEAR_CLOSURE_SOURCE_V1 0\n' if zero else b'UNIT_FIXTURE_NOT_NATIVE mathematical source rows\n',
            'source-contract.json':P.encoded(source),'source-bundle.json':P.encoded({'UNIT_FIXTURE_NOT_NATIVE':True}),
            'transport-geometry-contract.json':P.encoded(self.wrapper),'transport-model-input.json':self.producer['model.proposed.json'],
            'transport-request.json':P.encoded({'UNIT_FIXTURE_NOT_NATIVE':True})}
        return files,source

    def check_parameters(self,files,req,label):
        folder=FIXTURE/label;folder.mkdir()
        selected={name:raw for name,raw in files.items() if name.endswith(('.par','.inc')) or name in ('parameter-binding.json','fragments.json')}
        selected['case_contract.py']=(P.HERE/'case_contract.py').read_bytes()
        selected['controlled-request.json']=P.encoded(req)
        for name,raw in selected.items():(folder/name).write_bytes(raw)
        cfg=dict(role_id=C.role_id(req),size_id=C.size_id(80),numerical_variant=req['variant'])
        B.geometry_validate_current_case(folder,cfg,{k:P.sha(v) for k,v in selected.items()},self.model,files['device.cmd'].decode())
        return folder,cfg,selected

    def test_existing_alpha_timing_bytes_unchanged(self):
        old=P.module(P.ROOT/'experiments/dram-see-v4/s2-inputs-r1/decks.py','_original_decks_readonly')
        original=json.loads((D.CANDIDATE/'roles/B1-A0-main-b0/model.proposed.json').read_bytes())
        for bit in (0,1):
            for scale in (1,.5):
                self.assertEqual(decks.render_transient(original,bit,time_scale=scale),old.render_transient(original,bit,time_scale=scale))

    def test_positive_both_bits_variants_match_control_and_original_parameters(self):
        src,contract=self.fixture_source()
        for bit in (0,1):
            for variant in ('main','mesh','time'):
                req=request('SIGNAL',bit,variant)
                signal=N.render_payload(self.model,req,self.producer,src,contract,{'unit_payload_only':True})
                a0=N.render_payload(self.model,request('A0',bit,variant),self.producer,src,contract,{'unit_payload_only':True})
                self.assertEqual(N.source_free_deck(signal),a0['device.cmd'].decode())
                self.assertEqual(signal['run-parameters.par'],self.producer['physics.par']+b'\n'+src['source.par'])
                for name in D.PHYSICS_FILES:self.assertEqual(signal[name],self.producer[name])
                self.assertEqual(json.loads(signal['source-spec.json'])['numerical_variant'],variant)
                self.check_parameters(signal,req,'signal-'+variant+'-b'+str(bit))
                self.check_parameters(a0,request('A0',bit,variant),'control-'+variant+'-b'+str(bit))
        window=N.timing(contract)
        main=decks.transient_segments(self.model,1,window['observation_window_s'],window['main_max_step_s'])
        fine=decks.transient_segments(self.model,.5,window['observation_window_s'],window['main_max_step_s'])
        self.assertEqual([[s['start_s'],s['end_s']] for s in main if s['source_window']],[contract['required_source_window_s']])
        self.assertTrue(all(a['max_step_s']/2==b['max_step_s'] for a,b in zip(main,fine)))
        self.assertTrue(all(a['end_s']==b['start_s'] for a,b in zip(main,main[1:])))

    def test_structural_zero_keeps_source_absent_and_exact_control(self):
        src,contract=self.fixture_source(zero=True)
        for bit in (0,1):
            zero=N.render_payload(self.model,request('STRUCTURAL_ZERO',bit),self.producer,src,contract,{'unit_payload_only':True})
            a0=N.render_payload(self.model,request('A0',bit),self.producer,src,contract,{'unit_payload_only':True})
            self.assertEqual(zero['device.cmd'],a0['device.cmd'])
            self.assertNotIn(b'HeavyIon',zero['device.cmd']);self.assertNotIn('run-parameters.par',zero)
            self.assertIsNone(json.loads(zero['source-time-contract.json'])['original_required_source_window_s'])
            self.check_parameters(zero,request('STRUCTURAL_ZERO',bit),'zero-b'+str(bit))
        with self.assertRaisesRegex(ValueError,'signal/zero role differs'):
            N.render_payload(self.model,request('SIGNAL'),self.producer,src,contract,{'unit_payload_only':True})

    def test_late_source_rejected_without_changing_original_envelope(self):
        _,contract=self.fixture_source();late=copy.deepcopy(contract)
        late['source_time_bounds_s'][1]=21e-9
        late['required_source_window_s']=[late['source_time_bounds_s'][0]-16e-12,21e-9+16e-12]
        original=copy.deepcopy(late)
        with self.assertRaisesRegex(ValueError,'event retained, no clipping'):N.timing(late)
        self.assertEqual(late,original)

    def test_aliases_use_transport_geometry_and_physical_mismatch_rejected(self):
        src,_=self.fixture_source();files=dict(self.producer,**src)
        actual=P.pure_input_files(files,'SIGNAL','proton')
        self.assertEqual(actual['geometry-contract.json'],src['transport-geometry-contract.json'])
        self.assertNotEqual(actual['geometry-contract.json'],files['geometry-contract.json'])
        self.assertNotIn('device.cmd',actual)
        changed=copy.deepcopy(self.wrapper);changed['geometry']['mesh']={'different_numerical_variant':'mesh'}
        N.geometry_equal(changed,self.geometry,self.model,self.model)
        changed['geometry']['coordinate_system']='WRONG'
        with self.assertRaisesRegex(ValueError,'physical geometry'):N.geometry_equal(changed,self.geometry,self.model,self.model)
        wrong=copy.deepcopy(self.model);wrong['doping']['sn_junction_depth_nm']+=1
        with self.assertRaisesRegex(ValueError,'geometry or doping'):N.geometry_equal(self.wrapper,self.geometry,wrong,self.model)

    def test_missing_or_fixture_event_cannot_supply_original_source(self):
        with self.assertRaisesRegex(ValueError,'absent or linked'):N.load_original(str(FIXTURE/'not-a-source'),self.geometry,self.model)
        with self.assertRaisesRegex(ValueError,'fixture cannot'):N.load_original(str(FIXTURE),self.geometry,self.model)

    def test_parameter_override_and_wrong_version_snapshot_rejected(self):
        src,contract=self.fixture_source()
        files=N.render_payload(self.model,request('SIGNAL'),self.producer,src,contract,{'unit_payload_only':True})
        folder,cfg,selected=self.check_parameters(files,request('SIGNAL'),'adverse-parameter')
        (folder/'source.par').write_bytes(src['source.par']+b'Band2BandTunneling { Agen=1 }\n')
        with self.assertRaisesRegex(ValueError,'parameter relationship differs'):
            B.geometry_validate_current_case(folder,cfg,{k:P.sha(v) for k,v in selected.items()},self.model,files['device.cmd'].decode())
        names=dict(verifier='v1.py',dispatcher='dispatch.py',registry='registry.json',dependency_manifest='deps.json')
        for name,target in names.items():(folder/target).write_bytes(self.version_raw[name])
        B.geometry_validate_source_version(folder,self.version,names)
        (folder/'v1.py').write_bytes(self.version_raw['dispatcher'])
        with self.assertRaisesRegex(ValueError,'verifier snapshot differs'):B.geometry_validate_source_version(folder,self.version,names)

    def test_fixed_dispatcher_actual_input_binding_only(self):
        source=P.ROOT/'local_runtime/dram-see-v4/continuous/device/source-feature-inputs-alpha-main-20261017T062254Z'
        files={name:(source/name).read_bytes() for name in ('model.proposed.json','geometry-contract.json','alpha-profile.csv',
                                                          'heavyion.physics.inc','source.par')}
        files['physics-manifest.json']=self.producer['physics-manifest.json']
        packet=P.ROOT/'local_runtime/dram-see-v4/continuous/proton/source-features-s2-alpha-main-r1/source-features.json'
        registered=P.ROOT/'local_runtime/dram-see-v4/continuous/data/source-conditioned-qualification-r1/data-input-b0.json'
        req=dict(kind='transient',source_case='Aalpha',variant='main',stored_bit=0,
                 source_features_file=str(packet),registered_data_input=str(registered))
        extra,binding=P.bind(files,req,self.model)
        self.assertEqual(extra['source-features.json'],packet.read_bytes())
        self.assertEqual(extra['data-input.json'],registered.read_bytes())
        self.assertEqual(binding['schema'],'dram-see-v4-prospective-source-binding-r2')
        self.assertEqual(binding['verification_code_sha256']['source_features.py'],self.version['verifier']['sha256'])
        self.assertEqual(binding['verification_code_sha256']['source_feature_versions.py'],self.version['dispatcher']['sha256'])
        target=FIXTURE/'actual-pure-input-recomputation-only';target.mkdir()
        for name,raw in dict(files,**extra).items():(target/name).write_bytes(raw)
        (target/'controlled-request.json').write_bytes(P.encoded(req))
        (target/'source-contract.json').write_bytes(P.encoded({
            'prospective_source_binding_sha256':P.sha(extra['source-feature-binding.json']),
            'prospective_source_features_sha256':P.sha(extra['source-features.json'])}))
        B.geometry_validate_prospective_binding(target,self.model)
        (target/'RESULT_INPUT_ONLY.json').write_bytes(P.encoded(dict(
            actual_original_source_packet_recomputed=True,actual_registered_input_recomputed=True,
            source_packet_sha256=P.sha(packet.read_bytes()),registered_data_sha256=P.sha(registered.read_bytes()),
            dispatcher_sha256=self.version['dispatcher']['sha256'],verifier_sha256=self.version['verifier']['sha256'],
            physics_manifest_sha256=P.sha(files['physics-manifest.json']),
            native_run=False,native_source_qualified=False,proton_event_tested=False)))

    def test_frozen_relationship_guard_unit_graph(self):
        """Byte relationships only: no production project or native archive exists."""
        for zero in (False,True):
            src,source=self.fixture_source(zero)
            event=dict(schema='continuous-proton-native-event-binding-v1',UNIT_FIXTURE_NOT_NATIVE=True,
                particle='proton',transport_event_id=0,source_time_s=source['epoch_s'],original_ssh_exit_code=255,
                original_task_exit_code=0,original_remote_exit_code=0,original_collection_exit_code=0)
            for key,name in [('geometry_contract','transport-geometry-contract.json'),('model_input','transport-model-input.json'),
                             ('request','transport-request.json')]:event[key]={'sha256':P.sha(src[name])}
            src['event-binding.json']=P.encoded(event)
            src['source-reference-pre-clock.json']=P.encoded({'UNIT_FIXTURE_NOT_NATIVE':True})
            src['source-bundle.json']=P.encoded(dict(schema='continuous-proton-source-bundle-v1',binding=event,
                source_contract_sha256=P.sha(src['source-contract.json']),
                source_payload_sha256={name:P.sha(src[name]) for name in N.PAYLOAD+('source-reference-pre-clock.json',)}))
            originals={name:P.sha(src[name]) for name in N.PAYLOAD+('source-reference-pre-clock.json','source-bundle.json','event-binding.json')}
            originals['geometry-contract.json']=P.sha(src['transport-geometry-contract.json'])
            src['proton-source-input-manifest.json']=P.encoded(dict(schema='continuous-proton-inputs-v1',
                kind='complete_native_proton_event_source_bundle',UNIT_FIXTURE_NOT_NATIVE=True,files=originals))
            for name,suffix in [('verifier','verifier.py'),('dispatcher','dispatcher.py'),('registry','registry.json'),('dependency_manifest','dependencies.json')]:
                src['proton-source-'+suffix]=self.version_raw[name]
            cfg=dict(producer_run_id='UNIT_FIXTURE_NOT_NATIVE-D3',source_manifest_sha256='a'*64,source_archive_sha256='b'*64,
                     mesh_sha256='c'*64,geometry_validation_sha256='d'*64)
            producer=dict(cfg,geometry_contract_sha256=P.sha(self.producer['geometry-contract.json']),
                model_sha256=P.sha(self.producer['model.proposed.json']),physics_sha256={name:P.sha(self.producer[name]) for name in D.PHYSICS_FILES})
            record=dict(schema='dram-see-v4-original-proton-source-binding-r1',UNIT_FIXTURE_NOT_NATIVE=True,
                complete_event_reaudited=False,source_manifest_sha256=P.sha(src['proton-source-input-manifest.json']),
                original_source_sha256={name:P.sha(raw) for name,raw in src.items()},original_event_binding=event,
                source_feature_version=self.version,actual_D3_binding=producer)
            case='STRUCTURAL_ZERO' if zero else 'SIGNAL';req=request(case)
            files=N.render_payload(self.model,req,self.producer,src,source,record)
            files['controlled-request.json']=P.encoded(req)
            files['role-contract.json']=P.encoded(dict(stored_bit=0,numerical_variant='main',case=case,source_configured=not zero,
                source_time_contract_sha256=P.sha(files['source-time-contract.json']),source_bundle_sha256=P.sha(files['source-bundle.json'])))
            if zero:files['data-input.json']=P.encoded(dict(zero_source_comparison_window_s=N.timing(source)['observation_window_s']))
            folder=FIXTURE/('zero' if zero else 'positive');folder.mkdir()
            (folder/'SYNTHETIC_NOT_NATIVE').write_bytes(b'Only the frozen-byte guard is called; no native event audit or production project.\n')
            for name,raw in files.items():(folder/name).write_bytes(raw)
            B.geometry_validate_proton_binding(folder,cfg,self.model,files['device.cmd'].decode())
            (folder/'transport-geometry-contract.json').write_bytes(self.producer['geometry-contract.json'])
            with self.assertRaisesRegex(ValueError,'Original proton source bytes changed'):
                B.geometry_validate_proton_binding(folder,cfg,self.model,files['device.cmd'].decode())


if __name__=='__main__':
    print('Preserved pure connector fixtures:',FIXTURE)
    unittest.main(verbosity=2)
