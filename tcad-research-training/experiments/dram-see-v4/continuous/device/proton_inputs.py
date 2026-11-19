"""Original complete Geant4 event -> current device payload, without dispatch.

Only source_bundle/couple own ancestry and source mathematics. This connector
replays their read-only checks, keeps original source bytes and uses the real D3
mesh. Pure rendering helpers below do not qualify a native event by themselves.
"""
import json
import math
from pathlib import Path
import re

import decks
import numerics_patch
import physics_patch
import prospective as P

PAYLOAD=('sources.dat','heavyion.physics.inc','source.par','source-contract.json','fragments.json',
         'heavyion.plot.inc','heavyion.currentplot.inc')
ALIASES={'geometry-contract.json':'transport-geometry-contract.json',
         'model-input.json':'transport-model-input.json','request.json':'transport-request.json'}
FEATURE_NAMES=('source-bundle.json','geometry-contract.json')+PAYLOAD+('request.json','model-input.json')
NONPHYSICAL={'schema','status','native_qualified','size_id','legacy_size_label','mesh'}
require=P.require


def geometry_equal(transport,tcad,transport_model,tcad_model):
    require(transport.get('schema')=='continuous-bcat-proton-geometry-v1'
            and transport.get('coordinate_transform')=='identity: TCAD x,y,z_depth in um = Geant4 x,y,z in um',
            'Only the original identity-coordinate transport geometry is supported')
    require(transport.get('gate_transport_material')=='G4_Galactic','Undeclared transport gate material')
    left={k:v for k,v in transport['geometry'].items() if k not in NONPHYSICAL}
    right={k:v for k,v in tcad.items() if k not in NONPHYSICAL}
    require(left==right,'Actual D3 and transport physical geometry/contact/doping/unit definitions differ')
    require(transport_model['geometry']==tcad_model['geometry'] and transport_model['doping']==tcad_model['doping'],
            'Original Geant4/TCAD model geometry or doping differs')


def feature_inputs(files):
    return {name:files[ALIASES.get(name,name)] for name in FEATURE_NAMES}


def load_original(source_directory,tcad_geometry,tcad_model):
    path=Path(source_directory)
    require(path.is_absolute() and path.is_dir() and not path.is_symlink(), 'Original proton source bundle directory is absent or linked')
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(path) and not (path/'SYNTHETIC_NOT_NATIVE').exists(),
            'A fixture cannot supply an original proton event')
    manifest_raw=(path/'input-manifest.json').read_bytes();manifest=json.loads(manifest_raw)
    require(manifest.get('schema')=='continuous-proton-inputs-v1'
            and manifest.get('kind')=='complete_native_proton_event_source_bundle','Not a complete original event source bundle')
    raw={}
    for name,expected in manifest['files'].items():
        require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*',name) is not None,'Unsafe source filename')
        item=path/name;require(item.is_file() and not item.is_symlink(),'Missing/linked source member: '+name)
        raw[name]=item.read_bytes();require(P.sha(raw[name])==expected,'Original source package changed: '+name)
    source=json.loads(raw['source-contract.json']);bundle=json.loads(raw['source-bundle.json']);binding=bundle['binding']
    require(bundle.get('schema')=='continuous-proton-source-bundle-v1'
            and source.get('schema')=='continuous-proton-heavyion-candidate-v1','Unknown proton source representation')
    operation=Path(binding['operation']['path']).parent;build=Path(binding['build_operation']['path']).parent
    dispatcher=P.module(P.FEATURE_VERIFIER,'_device_fixed_proton_source_dispatcher')
    version,version_raw=P.version_evidence(dispatcher,particle='proton')
    helper=dispatcher.load_version('v1-s2',particle='proton')
    # v1's dependency context restores the caller's device.prepare afterwards.
    with helper.proton_modules() as (transport,couple,event):
        actual=event.audit_transport_event(operation,binding['transport_event_id'],build=build)
        require(actual==binding,'Complete original event/binary/ancestry evidence differs')
        expected=couple.package_payload(operation,binding['transport_event_id'],source['epoch_s'],
            source['approximation']['let_node_width_fraction'],source['approximation']['max_segment_time_sigma_fraction'])
        require(set(expected)==set(PAYLOAD),'Unsupported original source payload version')
        require(all(raw[name]==value and bundle['source_payload_sha256'][name]==P.sha(value)
                    for name,value in expected.items()),'Source differs from complete original Geant4 event')
    require(json.loads(raw['event-binding.json'])==binding,'Original event-binding file differs')
    for name,expected in bundle['source_payload_sha256'].items():
        require(name in raw and P.sha(raw[name])==expected,'Original bound source artifact changed: '+name)
    require(bundle['source_contract_sha256']==P.sha(raw['source-contract.json'])
            and source['epoch_s']==binding['source_time_s'],'Event epoch or coupling contract differs')
    transport_model=Path(binding['model_input']['path']).read_bytes()
    original_request=Path(binding['request']['path']).read_bytes()
    require(P.sha(transport_model)==binding['model_input']['sha256']
            and P.sha(original_request)==binding['request']['sha256']
            and P.sha(raw['geometry-contract.json'])==binding['geometry_contract']['sha256'],
            'Original transport geometry/model/request binding differs')
    geometry_equal(json.loads(raw['geometry-contract.json']),tcad_geometry,json.loads(transport_model),tcad_model)
    require((path/'input-manifest.json').read_bytes()==manifest_raw
            and all((path/name).read_bytes()==value for name,value in raw.items()),
            'Original proton source bundle changed during read-only audit')
    require(P.version_evidence(dispatcher,particle='proton')==(version,version_raw),
            'Fixed proton source verification dependencies changed during audit')
    files={ALIASES.get(name,name):value for name,value in raw.items()}
    files['transport-model-input.json']=transport_model;files['transport-request.json']=original_request
    files['proton-source-input-manifest.json']=manifest_raw
    for name,suffix in (('verifier','verifier.py'),('dispatcher','dispatcher.py'),
                        ('registry','registry.json'),('dependency_manifest','dependencies.json')):
        files['proton-source-'+suffix]=version_raw[name]
    record=dict(schema='dram-see-v4-original-proton-source-binding-r1',source_directory=str(path),
        source_manifest_sha256=P.sha(manifest_raw),original_event_binding=binding,
        source_feature_version=version,
        feature_input_aliases={name:ALIASES.get(name,name) for name in FEATURE_NAMES},
        original_source_sha256={name:P.sha(value) for name,value in files.items()},
        complete_event_reaudited=True,native_TCAD_source_qualified=False,pmi_r12_fixed=False,
        geometry_comparison='All physical fields and complete model geometry/doping exact; only declared descriptive/mesh fields excluded')
    return files,source,bundle,record


def timing(source):
    require(source.get('kernel')==dict(width_um=.03,temporal_sigma_s=2e-12,source='original isotropic Gaussian line-convolution')
            and source.get('eV_per_pair')==3.6,'Unsupported proton source kernel or pair energy')
    count=source.get('fragment_count')
    require(type(count) is int and count>=0,'Invalid original fragment count')
    if count:
        bounds=source.get('source_time_bounds_s');window=source.get('required_source_window_s')
        require(isinstance(bounds,list) and len(bounds)==2 and all(type(v) in (int,float) and math.isfinite(v) for v in bounds)
                and bounds[0]<=bounds[1],'Missing complete original source time bounds')
        require(window==[bounds[0]-16e-12,bounds[1]+16e-12],'Original full eight-sigma source window differs')
        require(8.1e-9<window[0]<window[1]<19.9e-9,
                'Unsupported late/early proton event: full eight-sigma window '+str(window)+' is outside existing hold-to-19.9ns collection; event retained, no clipping')
        return dict(schema='dram-see-v4-proton-observation-window-r1',mode='positive_source_envelope',
            observation_window_s=window,main_max_step_s=4e-13,source_present=True,
            original_required_source_window_s=window,late_deposits_clipped=False)
    epoch=source.get('epoch_s')
    require(source.get('source_time_bounds_s') is None and source.get('required_source_window_s') is None
            and type(epoch) in (int,float) and math.isfinite(epoch) and 8.1e-9<epoch<19.9e-9,
            'Structural-zero event needs an explicit original epoch inside the existing hold interval')
    return dict(schema='dram-see-v4-proton-observation-window-r1',mode='structural_zero_comparison',
        observation_window_s=[epoch,19.9e-9],main_max_step_s=1e-10,source_present=False,
        original_required_source_window_s=None,late_deposits_clipped=False,
        missing_generation_semantics='structural absence; native G remains null, never a measured zero')


def render_payload(model,request,producer_inputs,source_files,source,source_record):
    """Pure renderer. Production caller must obtain source_record via load_original."""
    window=timing(source);case=request['source_case'];active=case=='SIGNAL'
    if case!='A0':require(active is window['source_present'],'Requested proton signal/zero role differs from the complete event')
    fragments=json.loads(source_files['fragments.json'])
    require(len(fragments)==source['fragment_count'],'Original fragments/count differ')
    if not window['source_present']:
        require(not fragments and not source_files['heavyion.physics.inc'].strip() and not source_files['source.par'].strip(),
                'Structural-zero original event must have empty source representation')
    physics=source_files['heavyion.physics.inc'].decode('utf-8') if active else ''
    text=decks.render_transient(model,request['stored_bit'],source_block=physics,
        source_plot=source_files['heavyion.plot.inc'].decode().strip() if active else '',
        time_scale=.5 if request['variant']=='time' else 1,
        observation_window_s=window['observation_window_s'],observation_max_step_s=window['main_max_step_s'])
    require(text.count(physics_patch.SELECTOR_OLD)==1,'Unexpected original physical selector')
    text=numerics_patch.apply(text.replace(physics_patch.SELECTOR_OLD,physics_patch.SELECTOR_NEW),3,mixed=True)
    files={name:producer_inputs[name] for name in ('physics.par','physics-manifest.json','Silicon.par','Oxide.par',
                                                  'model.proposed.json','geometry-contract.json')}
    require(not set(files)&set(source_files),'Transport wrapper would overwrite actual D3 input')
    files.update(source_files)
    parameters=dict(schema='dram-see-v4-active-parameters-r1',base_file='physics.par',base_sha256=P.sha(files['physics.par']),
        source_file=None,source_sha256=None,source_physics_file=None,source_physics_sha256=None,
        active_file='physics.par',active_sha256=P.sha(files['physics.par']),aggregation='base_only')
    if active:
        files['run-parameters.par']=files['physics.par']+b'\n'+files['source.par']
        text=text.replace('Parameter="physics.par"','Parameter="run-parameters.par"')
        text=text.replace('Math {',files['heavyion.currentplot.inc'].decode()+'Math {',1)
        parameters.update(source_file='source.par',source_sha256=P.sha(files['source.par']),source_physics_file='heavyion.physics.inc',
            source_physics_sha256=P.sha(files['heavyion.physics.inc']),active_file='run-parameters.par',
            active_sha256=P.sha(files['run-parameters.par']),aggregation='base_bytes + LF + source_bytes')
    spec=dict(schema='continuous-particle-source-spec-v1',particle='proton',role='CONTROL' if case=='A0' else case,
        stored_bit=request['stored_bit'],numerical_variant=request['variant'],physics_manifest_sha256=P.sha(files['physics-manifest.json']),
        source_contract_sha256=P.sha(files['source-contract.json']))
    files.update({'device.cmd':text.encode(),'parameter-binding.json':P.encoded(parameters),'source-spec.json':P.encoded(spec),
        'numerical-method.json':P.encoded(numerics_patch.contract(3,mixed=True)),
        'source-time-contract.json':P.encoded(window),'device-source-binding.json':P.encoded(source_record)})
    return files


def source_free_deck(files):
    text=files['device.cmd'].decode();binding=json.loads(files['parameter-binding.json'])
    if binding['active_file']=='run-parameters.par':
        text=text.replace(files['heavyion.physics.inc'].decode(),'')
        text=text.replace(files['heavyion.currentplot.inc'].decode(),'')
        text=text.replace(' '+files['heavyion.plot.inc'].decode().strip(),' ')
        text=text.replace('Parameter="run-parameters.par"','Parameter="physics.par"')
    return text
