"""Bind independently recomputed source features before a new signal is frozen.

Source mathematics belongs to proton/source_features.py. Registered-row
verification belongs to data/source_inputs.py. This module copies verified
original bytes and checks their correspondence to the actual device inputs.
It does not inspect TCAD output or implement source mathematics.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
FEATURE_VERIFIER=HERE.parent/'proton/source_feature_versions.py'
DATA_VERIFIER=HERE.parent/'data/source_inputs.py'
SCHEMA='dram-see-v4-prospective-source-binding-r2'


def require(ok,message):
    if not ok:raise ValueError(message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')


def module(path,name):
    require(path.is_file() and not path.is_symlink(),'Missing exact verification implementation: '+str(path))
    spec=importlib.util.spec_from_file_location(name,str(path))
    value=importlib.util.module_from_spec(spec)
    # Read-only loading also avoids creating __pycache__ in another owner's tree.
    exec(compile(path.read_bytes(),str(path),'exec'),value.__dict__)
    return value


def original_file(value,label):
    path=Path(value)
    require(path.is_file() and not path.is_symlink(),'Missing or linked '+label)
    path=path.resolve()
    return path,path.read_bytes()


def version_evidence(dispatcher,packet=None,particle=None):
    """Read only the fixed dispatcher's registered refs, never caller-selected code."""
    info=dispatcher.version_info(packet) if packet is not None else dispatcher.version_info(version_id='v1-s2',particle=particle)
    raw={}
    for name in ('verifier','dispatcher','registry','dependency_manifest'):
        _,value=original_file(info[name]['path'],'registered '+name)
        require(sha(value)==info[name]['sha256'],'Registered source '+name+' changed')
        raw[name]=value
    if hasattr(dispatcher,'verify_version_snapshot'):
        dispatcher.verify_version_snapshot(info,raw,packet)
    return info,raw


def pure_input_files(files,source_case,particle='alpha',source_version='v1-s2'):
    if source_version=='v2-alpha-surface':
        from alpha_v2_inputs import feature_inputs
        require(particle=='alpha' and source_case=='Aalpha','Only amplitude1 alpha v2 is connected')
        return feature_inputs(files)
    if particle=='proton':
        from proton_inputs import feature_inputs
        require(source_case in ('SIGNAL','STRUCTURAL_ZERO'),'Unsupported current proton source role')
        return feature_inputs(files)
    require(source_case in ('Aalpha','Z','H','split'),'Only the current declared alpha source is connected')
    prefix='' if source_case=='Aalpha' else source_case+'.'
    names=('model.proposed.json','geometry-contract.json','alpha-profile.csv',
           prefix+'heavyion.physics.inc',prefix+'source.par')
    require(all(name in files and isinstance(files[name],bytes) for name in names),'Pure source inputs are incomplete')
    return {name:files[name] for name in names}


def bind(files,request,model):
    require(request.get('kind')=='transient' and request.get('source_case')!='A0','Prospective features apply to signals only')
    for name in ('source_features_file','registered_data_input'):
        require(isinstance(request.get(name),str) and request[name],
                'New signal freezing requires pre-TCAD '+name)
    packet_path,packet_raw=original_file(request['source_features_file'],'source-feature packet')
    data_path,data_raw=original_file(request['registered_data_input'],'registered data input')
    particle=request.get('particle','alpha')
    inputs=pure_input_files(files,request['source_case'],particle,request.get('source_version','v1-s2'))
    feature_code=FEATURE_VERIFIER.read_bytes()
    data_code=DATA_VERIFIER.read_bytes()
    source=module(FEATURE_VERIFIER,'_device_prospective_source_features')
    registered=module(DATA_VERIFIER,'_device_prospective_registered_input')
    # Both calls independently read original upstream inputs. No caller-provided
    # "verified" flag can replace recomputation or original registered-row checks.
    packet=source.verify(packet_path,input_files=inputs)
    require(packet.get('particle',particle)==particle,'Source summary particle differs from device request')
    contract_raw=source.contract_bytes(packet)
    row=registered.verify_registered_input(data_path)
    require(packet_path.read_bytes()==packet_raw and data_path.read_bytes()==data_raw,
            'Original prospective inputs changed during verification')
    require(FEATURE_VERIFIER.read_bytes()==feature_code and DATA_VERIFIER.read_bytes()==data_code,
            'Prospective verification implementation changed during verification')
    version,version_raw=version_evidence(source,packet)
    require(version['version_id']==request.get('source_version','v1-s2'),'Requested source version differs from registered verifier')
    verifier_name=Path(version['verifier']['path']).name
    if request.get('source_version')=='v2-alpha-surface':
        require(files.get('source-packet.json')==packet_raw,'Alpha v2 native source and prospective packet differ')
    require(version_raw['dispatcher']==feature_code,'Bound dispatcher differs from executed implementation')
    require(packet==json.loads(packet_raw.decode('utf-8')) and row==json.loads(data_raw.decode('utf-8')),
            'Verifier did not return the original verified payload')
    require(isinstance(contract_raw,bytes) and sha(contract_raw)==packet['feature_contract_sha256'],
            'Feature contract bytes differ')
    require(set(packet['inputs'])==set(inputs),'Source summary contains undeclared or missing input dependencies')
    for name,raw in inputs.items():
        require(packet['inputs'][name]['sha256']==sha(raw),'Source summary does not bind actual input: '+name)
    values=packet['source_features']
    require(isinstance(values,dict) and len(values)==13
            and all(type(v) in (int,float) and math.isfinite(v) for v in values.values()),
            'Source summary must have exactly thirteen finite source-derived values')
    require(row.get('schema')=='dram-see-v4-registered-data-input-v2','Unregistered data-input schema')
    require(row.get('source_features')==values
            and row.get('source_features_sha256')==sha(packet_raw)
            and row.get('source_feature_contract_sha256')==sha(contract_raw),
            'Registered row and actual source summary differ')
    reference=row.get('source_features_ref',{})
    require(reference.get('sha256')==sha(packet_raw) and Path(reference.get('path','')).resolve()==packet_path,
            'Registered row references a different source-feature packet')
    require(type(row.get('stored_bit')) is int and row['stored_bit']==request['stored_bit'],
            'Registered bit differs from actual device input')
    for key in ('gate_top_depth_nm','sn_junction_depth_nm'):
        expected=model['geometry']['gate_top_depth_nm'] if key=='gate_top_depth_nm' else model['doping']['sn_junction_depth_nm']
        require(row.get(key)==expected,'Registered device parameter differs: '+key)
    require(row.get('physics_manifest_sha256')==sha(files['physics-manifest.json']),
            'Registered physical model differs from actual solver physics')
    purpose=row.get('purpose','dataset')
    require(purpose in ('dataset','qualification','diagnostic'),'Unknown input registration purpose')
    if purpose=='dataset':
        require(request.get('variant','main')=='main' and row.get('numerical_variant','main')=='main',
                'Numerical refinement is qualification evidence, not a formal training row')
    require(row.get('particle',particle)==particle,'Registered particle differs from actual source')
    origin_keys=('plan_sha256','design_sha256') if purpose=='dataset' else ('registration_request_sha256',)
    for name in origin_keys+('circuit_contract_sha256',):
        require(isinstance(row.get(name),str) and re.fullmatch(r'[a-f0-9]{64}',row[name]),
                'Missing registered original identity: '+name)
    if purpose!='dataset':
        require(row.get('source_case')==request['source_case'] and row.get('numerical_variant')==request['variant'],
                'Registered qualification case or numerical variant differs')
    identity_keys=('stored_bit','gate_top_depth_nm','sn_junction_depth_nm','physics_manifest_sha256','circuit_contract_sha256')+origin_keys
    identity_keys+=tuple(name for name in ('purpose','source_case','numerical_variant','particle','seed','transport_event_id','energy_MeV','angle_deg','split') if name in row)
    aliases={name:name for name in inputs}
    if particle=='proton':
        from proton_inputs import ALIASES
        aliases={name:ALIASES.get(name,name) for name in inputs}
    binding=dict(schema=SCHEMA,
        source_features_original_ref=dict(path=str(packet_path),sha256=sha(packet_raw)),
        registered_source_features_ref=dict(reference),
        feature_contract_sha256=sha(contract_raw),
        registered_data_original_ref=dict(path=str(data_path),sha256=sha(data_raw)),
        pure_source_inputs_sha256={name:sha(raw) for name,raw in inputs.items()},
        input_file_aliases=aliases,
        source_features=values,
        registration_purpose=purpose,registered_identity={name:row[name] for name in identity_keys},
        source_feature_version=version,
        verification_verifier_name=verifier_name,
        verification_calls=['source_feature_versions.verify(original_packet, input_files=actual_pure_source_inputs)',
                            'source_inputs.verify_registered_input(original_registered_data_input)'],
        verification_code_sha256={verifier_name:sha(version_raw['verifier']),
            'source_feature_versions.py':sha(feature_code),'source_inputs.py':sha(data_code)},
        timing='Bound before this TCAD input manifest is created',
        native_source_or_response_qualification=False)
    return {'source-features.json':packet_raw,'source-feature-contract.json':contract_raw,
            'source-feature-binding.json':encoded(binding),'data-input.json':data_raw,
            'source-feature-verifier-snapshot.py':version_raw['verifier'],
            'source-feature-dispatcher-snapshot.py':feature_code,
            'source-feature-registry-snapshot.json':version_raw['registry'],
            'source-feature-dependencies-snapshot.json':version_raw['dependency_manifest'],
            'registered-input-verifier-snapshot.py':data_code},binding
