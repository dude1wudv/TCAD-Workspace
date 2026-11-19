"""Fixed alpha-v2 source input adapter; no source mathematics or native launcher."""
import json
from pathlib import Path

import case_contract as C
import decks
import numerics_patch
import physics_patch
import prospective as P

VERSION='v2-alpha-surface'
INPUTS=('model.proposed.json','geometry-contract.json','source-request.json','alpha-astar-silicon.csv',
        'source-origins.json','alpha-profile.csv','heavyion.physics.inc','source.par','source-contract.json')
PHYSICS=('physics.par','physics-manifest.json','Silicon.par','Oxide.par')


def feature_inputs(files):
    P.require(all(name in files and isinstance(files[name],bytes) for name in INPUTS),'Alpha v2 original input set is incomplete')
    return {name:files[name] for name in INPUTS}


def load_original(packet_file,producer_inputs):
    """Production caller first obtains producer_inputs from a real collected D3."""
    path,packet_raw=P.original_file(packet_file,'alpha v2 original source packet')
    dispatcher=P.module(P.FEATURE_VERIFIER,'_device_alpha_v2_registered_dispatcher')
    packet=dispatcher.verify(path)
    version,version_raw=P.version_evidence(dispatcher,packet)
    P.require(version['version_id']==VERSION and packet.get('version_id')==VERSION
              and packet.get('schema')=='continuous-particle-source-features-v2' and packet.get('particle')=='alpha',
              'Explicit alpha v2 request resolved a different registered source version')
    P.require(set(packet['inputs'])==set(INPUTS),'Unregistered alpha v2 input dependency set')
    files={}
    source_dir=Path(packet['source_package']['path']).resolve()
    for name in INPUTS:
        item,raw=P.original_file(packet['inputs'][name]['path'],'original v2 input '+name)
        P.require(item==source_dir/name and P.sha(raw)==packet['inputs'][name]['sha256'],
                  'Alpha v2 original input path or bytes changed: '+name)
        files[name]=raw
    for name in ('model.proposed.json','geometry-contract.json'):
        P.require(files[name]==producer_inputs[name],'Alpha v2 does not use the exact actual D3 '+name)
    source=json.loads(files['source-contract.json'])
    request=json.loads(files['source-request.json'])
    P.require(source==packet['source_definition'] and source.get('source_amplitude')==1.
              and packet['source_features'].get('source_present')==1,'Alpha v2 adapter supports only the original amplitude1 positive source')
    P.require(request['energy_MeV'] in (3,5,7) and request['theta_deg'] in (0,30)
              and packet['source_conditions']['energy_MeV']==request['energy_MeV']
              and packet['source_conditions']['angle_deg']==request['theta_deg'],'Alpha v2 conditions differ from authoritative source request')
    for name in ('alpha-profile.csv','heavyion.physics.inc','source.par'):
        P.require(source['source_files_sha256'][name]==P.sha(files[name]),'Alpha v2 declared native source bytes differ: '+name)
    P.require(path.read_bytes()==packet_raw and all(Path(packet['inputs'][name]['path']).read_bytes()==raw for name,raw in files.items()),
              'Alpha v2 original packet or inputs changed during binding')
    P.require(P.version_evidence(dispatcher,packet)==(version,version_raw),'Fixed alpha v2 verifier dependencies changed during binding')
    files['source-packet.json']=packet_raw
    files['alpha-v2-feature-contract.json']=dispatcher.contract_bytes(packet)
    for key,suffix in (('verifier','verifier.py'),('dispatcher','dispatcher.py'),('registry','registry.json'),('dependency_manifest','dependencies.json')):
        files['alpha-v2-'+suffix]=version_raw[key]
    record=dict(schema='dram-see-v4-alpha-v2-device-source-binding-r1',source_version=VERSION,
        original_packet_ref=dict(path=str(path),sha256=P.sha(packet_raw)),source_feature_version=version,
        original_source_inputs_sha256={name:P.sha(files[name]) for name in INPUTS},
        source_conditions=packet['source_conditions'],original_data_design_notice=packet['data_design'],
        actual_D3_binding=None,source_mathematics_recomputed_by_fixed_dispatcher=True,
        native_source_qualified=False,pmi_r12_fixed=False)
    return files,source,record


def observation_contract(source):
    P.require(source.get('schema')=='continuous-alpha-source-contract-v2'
              and source.get('actual_clock') is None and source.get('source_amplitude')==1.,'Unexpected original alpha v2 source contract')
    window=source['required_source_window_s']
    P.require(window==[source['epoch_s']-8*source['temporal']['sigma_s'],source['epoch_s']+8*source['temporal']['sigma_s']]
              and source['temporal']['sigma_s']==2e-13 and source['required_native_checks']['source_max_step_s']==4e-14
              and source['required_native_checks']['refined_source_max_step_s']==2e-14,'Alpha v2 original temporal definition differs')
    return dict(schema='dram-see-v4-alpha-v2-native-observation-contract-r1',source_contract_sha256=None,
        source_version=VERSION,observation_window_s=window,main_max_step_s=4e-14,refined_max_step_s=2e-14,
        path=source['path'],endpoint_semantics=source['required_native_checks']['endpoint_semantics'],
        required_field_checks=source['required_native_checks'],
        available_raw_outputs=['Full accepted BE source_window TDR frames','HeavyIonGeneration/HeavyIonChargeDensity',
            'PLT semiconductor HeavyIonGeneration integral','both carrier densities and circuit/node currents'],
        current_observer_limit='Existing observer measures G and first moments; no v2 finite-perpendicular-endplane qualification is inferred',
        native_endpoint_semantics_verified=False,native_clock_verified=False,native_source_qualified=False,
        data_admission_requires='Separate current v2 source-field/clock/reference audit, exact matching A0, carrier/KCL and numerical checks',
        mathematical_packet_is_native_evidence=False)


def render_payload(model,request,producer_inputs,source_files,source,record):
    request=C.validate(request)
    P.require(request.get('source_version')==VERSION,'Alpha v2 rendering requires explicit controlled version')
    P.require(json.loads(producer_inputs['model.proposed.json'])==model,'Actual alpha v2 D3 model bytes differ from renderer model')
    P.require(model['geometry']['gate_top_depth_nm']==request['gate_top_depth_nm']
              and model['doping']['sn_junction_depth_nm']==request['sn_junction_depth_nm'],'Alpha v2 request/D3 parameters differ')
    for name in ('model.proposed.json','geometry-contract.json'):
        P.require(source_files[name]==producer_inputs[name],'Alpha v2 source/actual D3 input differs: '+name)
    geometry=json.loads(producer_inputs['geometry-contract.json'])
    P.require(geometry['mesh']['scale']==(.5 if request['variant']=='mesh' else 1),
              'Alpha v2 numerical variant needs its matching actual D3 mesh and independently bound source packet')
    window=observation_contract(source)
    window['source_contract_sha256']=P.sha(source_files['source-contract.json'])
    active=request['source_case']=='Aalpha'
    files={name:producer_inputs[name] for name in PHYSICS}
    P.require(not set(files)&set(source_files),'Alpha v2 source would overwrite actual D3 physics')
    files.update(source_files)
    files['heavyion.plot.inc']=b'HeavyIonGeneration HeavyIonChargeDensity\n'
    files['heavyion.currentplot.inc']=b'CurrentPlot {\n HeavyIonGeneration( Integrate(Semiconductor) )\n}\n'
    physical=files['heavyion.physics.inc'].decode() if active else ''
    text=decks.render_transient(model,request['stored_bit'],source_block=physical,
        source_plot=files['heavyion.plot.inc'].decode().strip() if active else '',
        time_scale=.5 if request['variant']=='time' else 1,
        observation_window_s=window['observation_window_s'],observation_max_step_s=window['main_max_step_s'])
    P.require(text.count(physics_patch.SELECTOR_OLD)==1,'Unexpected base physical selector')
    text=numerics_patch.apply(text.replace(physics_patch.SELECTOR_OLD,physics_patch.SELECTOR_NEW),3,mixed=True)
    binding=dict(schema='dram-see-v4-active-parameters-r1',base_file='physics.par',base_sha256=P.sha(files['physics.par']),
        source_file=None,source_sha256=None,source_physics_file=None,source_physics_sha256=None,
        active_file='physics.par',active_sha256=P.sha(files['physics.par']),aggregation='base_only')
    if active:
        files['run-parameters.par']=files['physics.par']+b'\n'+files['source.par']
        text=text.replace('Parameter="physics.par"','Parameter="run-parameters.par"')
        text=text.replace('Math {',files['heavyion.currentplot.inc'].decode()+'Math {',1)
        binding.update(source_file='source.par',source_sha256=P.sha(files['source.par']),source_physics_file='heavyion.physics.inc',
            source_physics_sha256=P.sha(files['heavyion.physics.inc']),active_file='run-parameters.par',
            active_sha256=P.sha(files['run-parameters.par']),aggregation='base_bytes + LF + source_bytes')
    record=dict(record,source_active=active,parameter_id=C.parameter_id(request),
        actual_physics_sha256={name:P.sha(files[name]) for name in PHYSICS})
    spec=dict(schema='continuous-particle-source-spec-v1',particle='alpha',role='SIGNAL' if active else 'CONTROL',
        source_version=VERSION,stored_bit=request['stored_bit'],numerical_variant=request['variant'],
        physics_manifest_sha256=P.sha(files['physics-manifest.json']),source_contract_sha256=P.sha(files['source-contract.json']),
        source_packet_sha256=P.sha(files['source-packet.json']))
    files.update({'device.cmd':text.encode(),'parameter-binding.json':P.encoded(binding),'source-spec.json':P.encoded(spec),
        'numerical-method.json':P.encoded(numerics_patch.contract(3,mixed=True)),
        'source-time-contract.json':P.encoded(window),'device-source-binding.json':P.encoded(record)})
    return files


def source_free_deck(files):
    text=files['device.cmd'].decode();binding=json.loads(files['parameter-binding.json'])
    if binding['source_file'] is not None:
        text=text.replace(files['heavyion.physics.inc'].decode(),'').replace(files['heavyion.currentplot.inc'].decode(),'')
        text=text.replace(' '+files['heavyion.plot.inc'].decode().strip(),' ')
        text=text.replace('Parameter="run-parameters.par"','Parameter="physics.par"')
    return text
