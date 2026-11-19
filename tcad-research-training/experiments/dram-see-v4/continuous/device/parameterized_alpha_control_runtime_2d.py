"""Closed Python-3.6 runtime for zero/half/finite-split alpha controls.

Host prepare replays fixed mathematical inputs and full matching A0 evidence.
Guest replays original A0 archives, source bytes and fixed runtime identities;
it never executes archived Python or imports the host-only projection kernels.
Only the original runner dispatch may admit/run this single SDevice step.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import tarfile

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
BRANCH='dram-see-v4-parameterized-alpha-controls-2d-r1'
REQUEST_SCHEMA='dram-see-v4-parameterized-alpha-control-request-r1'
CANDIDATE_SHA='459fe6bfcc57b514bf68f23779d81e8eaa7e453c02bc8a71cad1f0462821acf2'
PROJECTION_SHA='a2593ddcf1cf6e776d69cafb4c174d82885f81b221dcf6c9577fe5577d3e90dc'
ALPHA_SHA='395879dae534e5ab1832740e056519457d1dbb217e7a69180078ea026148ebef'
BASE_SHA='f8e18b4c319dc10e170c5945b5b5b9ef7fa999f35ced4e21bf3f7267e97f1db4'
BINDING_SCHEMA='dram-see-v4-parameterized-alpha-control-binding-r1'
SOURCE_SCHEMA='dram-see-v4-parameterized-alpha-control-source-spec-r1'
RUNTIME_SCHEMA='dram-see-v4-parameterized-alpha-control-runtime-r1'
PREFIX='alpha-control-projection/'
A0_PREFIX='matched-a0-bindings/'
CASES={'zero':('Z',0.),'half':('H',.5),'split':('split',1.)}
FROZEN_RESULT_KEYS={'binding','report','source_cfg','dimensional_contract','operation_timing','operating_binding',
    'source_spec','role_contract','numerical_relation','projection','control_binding','control_runtime_binding','matched_a0','source_time_contract'}

def require(ok,message):
    if not ok:raise ValueError('Parameterized alpha control runtime: '+message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')
def obj(raw):
    value=json.loads(raw.decode('utf-8'));require(isinstance(value,dict),'JSON object required');return value
def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for raw in iter(lambda:f.read(1048576),b''):h.update(raw)
    return h.hexdigest()
def fixed(name,expected):
    path=HERE/name;raw=path.read_bytes()
    require(not path.is_symlink() and sha(raw)==expected,'fixed local implementation differs: '+name)
    spec=importlib.util.spec_from_file_location('_control_runtime_'+name.replace('.','_'),str(path))
    module=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),module.__dict__);return module
def candidate():return fixed('parameterized_alpha_controls_2d.py',CANDIDATE_SHA)
def parent():return fixed('parameterized_alpha_2d.py',ALPHA_SHA)
def control_math():
    """Host only. Never called from guest admission or verify_frozen."""
    return fixed('parameterized_alpha_control_projection_2d.py',PROJECTION_SHA)
def validate_request(request):return candidate().validate_request(request)
def role_id(request):return candidate().role_id(request)

class BytesReader:
    def __init__(self,files):self.files=files
    def read(self,name):return self.files[name]
    def digest(self,name):return sha(self.read(name))
    def size(self,name):return len(self.read(name))

class _BaseProjectionReader:
    """Fixed data aliases for the unchanged r15 byte verifier, never code."""
    def __init__(self,reader):self.reader=reader
    def target(self,name):
        if name.startswith('alpha-projection/'):return PREFIX+'base-projection/'+name[len('alpha-projection/'):]
        if name in ('source-contract.json','heavyion.physics.inc','source.par'):return PREFIX+'base-projection/'+name
        return name
    def read(self,name):return self.reader.read(self.target(name))
    def digest(self,name):return self.reader.digest(self.target(name))
    def size(self,name):return self.reader.size(self.target(name))

def _runtime_bytes():
    result=parent()._runtime_bytes()
    result['parameterized_alpha_controls_2d.py']=(HERE/'parameterized_alpha_controls_2d.py').read_bytes()
    require(sha(result['parameterized_alpha_controls_2d.py'])==CANDIDATE_SHA,'candidate implementation changed')
    result['parameterized_alpha_control_runtime_2d.py']=Path(__file__).read_bytes()
    return result

def _snapshot_map():
    R=parent();mapping={'alpha-projection-implementation.py':('parameterized_alpha_projection_2d.py',BASE_SHA),
        'alpha-projection-core.py':('alpha_projection_2d.py',R.CORE_PROJECTION_SHA),
        'alpha-projection-reference.py':('../proton/source_reference.py',R.REFERENCE_SHA),
        'alpha-control-projection-implementation.py':('parameterized_alpha_control_projection_2d.py',PROJECTION_SHA)}
    mapping.update({'alpha-projection-dependency-'+k+'.py':v for k,v in R.DEPENDENCIES.items()})
    return mapping

def _mathematical_snapshots():
    result={}
    mapping=_snapshot_map()
    for name,(relative,h) in mapping.items():
        raw=(HERE/relative).read_bytes();require(sha(raw)==h,'fixed host mathematical dependency changed: '+relative);result[name]=raw
    return result

def _projection_bytes(reader,timing,reference,control):
    R=parent();base=R.projection(_BaseProjectionReader(reader),timing,reference)
    manifest=obj(reader.read(PREFIX+'input-output-manifest.json'))
    require(manifest.get('schema')=='dram-see-v4-parameterized-alpha-control-projection-manifest-r1'
        and manifest.get('implementation_sha256')==PROJECTION_SHA and manifest.get('base_projection_sha256')==BASE_SHA
        and manifest.get('native_source_qualified') is False and manifest.get('is_native_result') is False
        and manifest.get('training_admitted') is False,'control projection version/qualification differs')
    wanted=set('base-projection/'+n for n in R.PROJECTION_FILES)|{'control-request.json','segments.json','projection-ledger.json',
        'energy-source-provenance.json','heavyion.physics.inc','source.par','source-contract.json','fragment-000-profile.csv'}
    if control=='split':wanted.add('fragment-001-profile.csv')
    require(set(manifest.get('files',{}))==wanted,'control full source inventory differs')
    for name,row in manifest['files'].items():
        require(row==dict(sha256=reader.digest(PREFIX+name),size_bytes=reader.size(PREFIX+name)),'control source bytes differ: '+name)
    for name,(_,h) in _snapshot_map().items():require(reader.digest(name)==h,'fixed mathematical snapshot differs: '+name)
    contract=obj(reader.read(PREFIX+'source-contract.json'));ledger=obj(reader.read(PREFIX+'projection-ledger.json'))
    energy=obj(reader.read(PREFIX+'energy-source-provenance.json'));case,amp=CASES[control]
    expected_request=dict(schema='dram-see-v4-parameterized-alpha-control-projection-request-r1',control=control,source_case=case,
        amplitude=amp,base_request=base['contract']['request'],split_at_original_s_um=.5 if control=='split' else None)
    require(contract.get('schema')=='dram-see-v4-parameterized-alpha-control-projection-2d-r1'
        and contract.get('request')==obj(reader.read(PREFIX+'control-request.json'))==expected_request
        and contract.get('base_request')==base['contract']['request'] and contract.get('configured_amplitude')==amp
        and contract.get('base_projection_implementation_sha256')==BASE_SHA
        and contract.get('base_source_contract_sha256')==reader.digest(PREFIX+'base-projection/source-contract.json')
        and contract.get('base_projection_manifest_sha256')==reader.digest(PREFIX+'base-projection/input-output-manifest.json'),
        'control source/base identity differs')
    for name in ('response','path','input_sha256','mesh_sha256','physics_manifest_sha256','source_window_s','full_simulation_window_s'):
        require(contract[name]==base['contract'][name],'control changed original physical domain/time: '+name)
    require(contract['base_mapping']==base['contract']['mapping'] and contract['time_shift_s']==0
        and contract['additional_normalization'] is False and contract['native_source_qualified'] is False
        and contract['native_qualified'] is False and contract['training_admitted'] is False
        and contract['is_tcad_result'] is False and contract['pmi_r12_fixed'] is False,'control scope differs')
    require(ledger['tail_renormalization'] is False and ledger['discarded_source_records']==0 and ledger['actual_clock'] is None
        and ledger['native_source_qualified'] is False and ledger['native_zero_split_checks_executed'] is False
        and ledger['energy']==energy and energy['original_parent_energy']==base['ledger']['energy']
        and energy['original_parent_provenance']==base['energy_source_provenance'],'energy/source ledger differs')
    segments=json.loads(reader.read(PREFIX+'segments.json').decode('utf-8'))
    require(segments==ledger['segments'] and contract['segments']==[{k:v for k,v in s.items() if k not in ('coarse','refined')} for s in segments],
        'segment identity differs')
    for name,h in contract['derived_files_sha256'].items():require(reader.digest(PREFIX+name)==h,'derived source differs: '+name)
    for name in ('source-contract.json','heavyion.physics.inc','source.par'):require(reader.read(name)==reader.read(PREFIX+name),'active control source differs: '+name)
    return dict(contract=contract,ledger=ledger,manifest=manifest,energy_source_provenance=energy,base_projection=base,
        guest_mathematical_replay=False,guest_scope='Original A0 native/clock replay and closed frozen source bytes; host performs mathematical replay')

def _candidate_declarations(files,r,match,matched,originals):
    R=parent();reference=r['reference_alpha_request']
    contract=obj(files['source-contract.json'])
    packet={'input-output-manifest.json':files[PREFIX+'input-output-manifest.json']}
    case,amplitude=CASES[r['control']];role=role_id(r)
    bound=dict(schema=BINDING_SCHEMA,source_branch=BRANCH,control=r['control'],source_case=case,amplitude=amplitude,
        source_contract_sha256=sha(files['source-contract.json']),control_projection_manifest_sha256=sha(packet['input-output-manifest.json']),
        base_alpha_source_contract_sha256=contract['base_source_contract_sha256'],
        matched_a0=matched,matched_a0_original_files={n:{k:v for k,v in row.items() if k!='path'} for n,row in originals.items()},
        operation_timing_sha256=sha(files['operation-timing.json']),source_time_contract_sha256=sha(files['source-time-contract.json']),
        mesh_sha256=sha(files['cell_msh.tdr']),physics_manifest_sha256=sha(files['physics-manifest.json']),
        dimensional_contract_sha256=sha(files['dimensional-contract.json']),
        implementation_sha256=CANDIDATE_SHA,projection_implementation_sha256=PROJECTION_SHA,
        parent_alpha_verifier_sha256=ALPHA_SHA,baseline_verifier_sha256=R.BASELINE_SHA,
        host_matched_A0_original_chain_replayed=True,source_free_deck_byte_identical=True,
        host_control_mathematics_replayed=True,native_control_run_completed=False,
        native_source_qualified=False,training_admitted=False,additional_normalization=False)
    files['parameterized-alpha-control-binding.json']=encoded(bound)
    binding_sha=sha(files['parameterized-alpha-control-binding.json'])
    spec=dict(schema=SOURCE_SCHEMA,particle='alpha',role='SIGNAL',source_case=case,control=r['control'],
        stored_bit=reference['stored_bit'],numerical_variant='main',dimension=2,gate_top_depth_nm=80,
        sn_junction_depth_nm=87,effective_width_nm=20,energy_MeV=5,theta_deg=0,phi_deg=180,amplitude=amplitude,
        source_configured=True,input_structural_zero=amplitude==0,structural_zero_is_not_measured_G_zero=True,
        energy_definition='Reference Si-entry E5 trajectory retained; amplitude changes configured G, not incident energy',
        source_contract_sha256=sha(files['source-contract.json']),source_time_contract_sha256=sha(files['source-time-contract.json']),
        operation_timing_sha256=sha(files['operation-timing.json']),physics_manifest_sha256=sha(files['physics-manifest.json']),
        dimensional_contract_sha256=sha(files['dimensional-contract.json']),control_binding_sha256=binding_sha,
        expected_comparison='same-bit r13 A0' if case=='Z' else 'same-bit unsplit full alpha from identical parent source',
        half_response_linearity_assumed=False,source_field_comparison_required=True,
        source_native_relative_tolerance=.05,zero_split_response_charge_limit_fC=1e-4,zero_split_response_voltage_limit_V=1e-5,
        zero_split_limits_are_not_checks_executed=True,native_source_qualified=False,training_admitted=False)
    files['source-spec.json']=encoded(spec)
    files['role-contract.json']=encoded(dict(schema='dram-see-v4-parameterized-alpha-control-role-r1',role=role,
        source_case=case,stored_bit=reference['stored_bit'],source_branch=BRANCH,
        matched_A0_role=match['role'],source_spec_sha256=sha(files['source-spec.json']),control_binding_sha256=binding_sha,
        source_configured=True,native_syntax_verified=False,native_source_qualified=False))
    return bound,spec,obj(files['role-contract.json'])

def _derive_control_bytes(P,CP,verified,ctx,base,control):
    pieces=CP.fragments(P,ctx,control);amp=CP.CASES[control]['amplitude']
    coarse=[];fine=[];segment_records=[];payload={'base-projection/'+n:raw for n,raw in base.items()}
    for piece,metadata in pieces:
        offset=[a-b for a,b in zip(piece['path']['origin_um'],ctx['path']['origin_um'])]
        c=CP.translate_moments(P.projected_integral(piece),offset)
        f=CP.translate_moments(P.projected_integral(piece,True),offset)
        coarse.append(c);fine.append(f);segment_records.append(dict(metadata,coarse=c,refined=f))
        payload[metadata['profile_file']]=P.A.profile_bytes([dict(r,original_s_um=s) for r,s in zip(piece['rows'],metadata['original_s_um'])])
    total_c,total_f=CP.aggregate(coarse),CP.aggregate(fine)
    differences={k:abs(total_c[k]-v) for k,v in total_f.items() if type(v) in (float,int)}
    require(all(differences[k]<=total_c['offline_charge_gate_fC'] for k in differences if k.endswith('_fC')),
        'existing offline charge refinement gate failed')
    expected={k:amp*v for k,v in verified['ledger']['refined'].items() if type(v) in (float,int)
        and (k.endswith('_fC') or k.endswith('_fC_um') or k.endswith('_fC_um2') or k.endswith('_fC_ps') or k.endswith('_fC_ps2'))}
    comparison={k:total_f[k]-v for k,v in expected.items() if k in total_f and k!='offline_charge_gate_fC'}
    require(all(abs(comparison[k])<=max(1e-6,.001*abs(expected[k])) for k in CP.CHARGES),
        'control source differs from declared parent amplitude/partition')
    energy=dict(original_parent_energy=verified['ledger']['energy'],original_parent_provenance=obj(base['energy-source-provenance.json']),
        segments=[r['original_energy_account'] for r in segment_records],
        incident_energy_counted_once=True,restarted_at_incident_energy_per_segment=False,
        configured_source_amplitude=amp,amplitude_is_not_incident_energy_scaling=True,
        reference_energy_unscaled=True,nuclear_energy_converted_to_charge=False)
    for key in ('electronic_deposition_MeV','nuclear_deposition_MeV','tabulated_line_charge_fC'):
        energy[key+'_partition_residual']=math.fsum(r['original_energy_account'][key] for r in segment_records)-verified['ledger']['energy'][key]
    request=dict(schema=CP.REQUEST_SCHEMA,control=control,source_case=CP.CASES[control]['source_case'],
        amplitude=amp,base_request=verified['contract']['request'],split_at_original_s_um=.5 if control=='split' else None)
    ledger=dict(schema='dram-see-v4-parameterized-alpha-control-charge-ledger-r1',coarse=total_c,refined=total_f,
        segments=segment_records,refinement_absolute_differences=differences,parent_scaled_reference=expected,
        difference_from_parent_scaled_reference=comparison,energy=energy,
        charge_partition_order=list(CP.CHARGES),tail_renormalization=False,discarded_source_records=0,
        original_all_time_line_source_retained=True,actual_clock=None,is_native_measurement=False,
        native_zero_split_charge_limit_fC=1e-4,native_zero_split_voltage_limit_V=1e-5,
        native_zero_split_checks_executed=False,native_source_qualified=False)
    include,parameters=CP.render(P,pieces)
    contract=dict(schema=CP.SCHEMA,particle='alpha',dimension=2,request=request,
        base_source_contract_sha256=sha(base['source-contract.json']),base_projection_manifest_sha256=sha(base['input-output-manifest.json']),
        base_projection_implementation_sha256=BASE_SHA,base_request=ctx['request'],response=ctx['response'],
        path=ctx['path'],mapping=P.mapping(amp,ctx['request']['epoch_s']),base_mapping=ctx['factors'],configured_amplitude=amp,
        segments=[{k:v for k,v in m.items() if k not in ('coarse','refined')} for m in segment_records],
        input_sha256=verified['contract']['input_sha256'],mesh_sha256=verified['contract']['mesh_sha256'],
        physics_manifest_sha256=verified['contract']['physics_manifest_sha256'],
        source_window_s=ctx['source_window_s'],full_simulation_window_s=ctx['request']['simulation_window_s'],
        G2_unit='cm^-3 s^-1',native_to_physical_axes=dict(X='x',Y='z'),effective_width_cm=2e-6,
        original_reference_point_um=ctx['path']['origin_um'],moment_reference='All segment moments translated back to original input r0',
        domain='Finite perpendicular axial end planes plus original extruded Si mask; no tail renormalization',
        end_plane_oracle='0<=local_s<L; seam belongs only to second piece; G=0 at overall end',
        old_parent_endpoint_point_convention_unchanged=True,
        native_endpoint_and_seam_field_verification='PENDING; finite point values are not proved by zero-measure integral equivalence',
        vendor_basis=dict(version='W-2024.09',pages=[812,813,814,815,816,1728,1729],
            pdf_sha256='98f37002013ccc2e73c0316e3ea66fd7d06fd773abac7caaa3d362ea85d5c5b0'),
        base_energy_is_not_regenerated_per_piece=True,time_shift_s=0,additional_normalization=False,
        native_source_qualified=False,native_qualified=False,is_tcad_result=False,training_admitted=False,pmi_r12_fixed=False)
    payload.update({'control-request.json':encoded(request),'segments.json':encoded(segment_records),
        'projection-ledger.json':encoded(ledger),'energy-source-provenance.json':encoded(energy),
        'heavyion.physics.inc':include,'source.par':parameters})
    contract['derived_files_sha256']={n:sha(v) for n,v in payload.items() if not n.startswith('base-projection/')}
    payload['source-contract.json']=encoded(contract)
    return payload,contract,ledger,pieces

def replay_control(read,prefix=PREFIX):
    """Host pure-input replay from byte reader; never executes archived code.

    The declarations/composition above mirror sealed a259. All physical
    kernels, fragment transforms and integration are still called from a259/f8.
    The original parent profile, energy accounts and both manifests are exact.
    """
    CP=control_math();P=CP.base_api()
    base={n:read(prefix+'base-projection/'+n) for n in CP.BASE_FILES}
    request=obj(base['projection-request.json'])
    require(request.get('gate_top_depth_nm')==80 and request.get('energy_MeV')==5 and request.get('theta_deg')==0
        and request.get('phi_deg')==180 and request.get('amplitude')==1,'only development g80 E5 normal parent')
    inputs={n:base[n] for n in P.INPUT_NAMES}
    payload,contract,ledger=P.derive(inputs,request)
    origins=obj(base['input-origins.json'])
    require(origins.get('schema')=='dram-see-v4-parameterized-alpha-2d-input-origins-r1'
        and set(origins.get('inputs',{}))==set(inputs)
        and all(origins['inputs'][n]['sha256']==sha(v) for n,v in inputs.items()),'original parent input identity differs')
    payload['input-origins.json']=base['input-origins.json']
    manifest=dict(schema=P.MANIFEST_SCHEMA,files={n:dict(sha256=sha(v),size_bytes=len(v)) for n,v in payload.items()},
        implementation_sha256=BASE_SHA,core_projection_sha256=P.CORE_SHA,is_native_result=False,native_source_qualified=False)
    require(manifest==obj(base['input-output-manifest.json']) and all(base[n]==v for n,v in payload.items()),
        'full parent mathematical replay differs')
    verified=dict(contract=contract,ledger=ledger,manifest=manifest)
    ctx=P._context(inputs,request)
    require(ctx['path']['length_um']==1. and ctx['path']['direction']==[-0.,0.,1.]
        and ctx['path']['origin_um']==[-.052,0.,0.] and len(ctx['rows'])==101
        and ctx['rows'][50]['path_um']==.5,'original finite parent trajectory differs')
    control=obj(read(prefix+'control-request.json'))['control']
    payload,contract,ledger,pieces=_derive_control_bytes(P,CP,verified,ctx,base,control)
    manifest=CP.manifest(payload)
    require(manifest==obj(read(prefix+'input-output-manifest.json')) and all(read(prefix+n)==v for n,v in payload.items()),
        'complete control mathematical replay differs')
    projected=dict(contract=contract,ledger=ledger,manifest=manifest,
        energy_source_provenance=obj(payload['energy-source-provenance.json']),
        guest_mathematical_replay=False,host_mathematical_replay=True)
    return projected,ctx,pieces

def runtime_binding(reader,cfg):
    return dict(schema=RUNTIME_SCHEMA,source_branch=BRANCH,run_id=cfg['run_id'],role_id=cfg['role_id'],
        implementation_sha256=file_sha(__file__),candidate_implementation_sha256=CANDIDATE_SHA,
        control_projection_implementation_sha256=PROJECTION_SHA,parent_alpha_verifier_sha256=ALPHA_SHA,
        candidate_binding_sha256=reader.digest('parameterized-alpha-control-binding.json'),
        controlled_request_sha256=reader.digest('controlled-request.json'),source_spec_sha256=reader.digest('source-spec.json'),
        role_contract_sha256=reader.digest('role-contract.json'),device_sha256=reader.digest('device.cmd'),
        source_contract_sha256=reader.digest('source-contract.json'),source_time_contract_sha256=reader.digest('source-time-contract.json'),
        runtime_sha256={n:sha(v) for n,v in _runtime_bytes().items()},
        guest_math_replayed=False,guest_uses_only_closed_local_runtime=True,native_source_qualified=False,training_admitted=False)

def verify_frozen(reader,cfg):
    """Python 3.6 guest entry: full real A0 evidence, no host math imports."""
    R=parent();P=R.parameterized();D=R.dimensional();A=R.alpha()
    require(cfg.get('source_branch')==BRANCH and cfg.get('dimension_branch')==P.DIMENSION_BRANCH
        and cfg.get('mode')=='reuse' and 'parameterized_operating_branch' not in cfg,'explicit control root required')
    for name,raw in _runtime_bytes().items():require(reader.digest(name)==sha(raw),'closed runtime differs: '+name)
    result,_,_=P._verify_sources(reader,cfg)
    request=validate_request(obj(reader.read('controlled-request.json')));reference=request['reference_alpha_request']
    require(reader.read('source-control-request.json')==encoded(request),'candidate/frozen request differs')
    bound=obj(reader.read('parameterized-alpha-control-binding.json'))
    require(bound.get('schema')==BINDING_SCHEMA and reader.digest('parameterized-alpha-control-binding.json')==cfg.get('parameterized_alpha_control_binding_sha256'),
        'candidate binding identity differs')
    originals=bound.get('matched_a0_original_files',{})
    require(set(originals)=={A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')},'complete original matched A0 required')
    for n,row in originals.items():require(row==dict(sha256=reader.digest(n),size_bytes=reader.size(n)),'original matched A0 differs: '+n)
    manifest=obj(reader.read(A0_PREFIX+'manifest.json'))
    require(manifest.get('results_sha256')==reader.digest(A0_PREFIX+'results.tar')
        and manifest.get('inputs_archive_sha256')==reader.digest(A0_PREFIX+'inputs.tar'),'matched original outer receipt differs')
    with reader.stream(A0_PREFIX+'results.tar') as a,reader.stream(A0_PREFIX+'inputs.tar') as i:
        with tarfile.open(fileobj=a,mode='r:*') as ar,tarfile.open(fileobj=i,mode='r:*') as ir:
            prior=D.ArchiveReader(ar);match=R.verify_matched_a0(prior,manifest,D.ArchiveReader(ir),reference)
            matched=R.matched_identity(match,manifest,reader.digest(A0_PREFIX+'manifest.json'),reader.digest(A0_PREFIX+'results.tar'))
            for n,v in match['shared'].items():require(reader.read(n)==v,'control/A0 unchanged input differs: '+n)
            require(reader.digest('cell_msh.tdr')==prior.digest('cell_msh.tdr')==cfg['mesh_sha256']
                and reader.read('d2-source-binding.json')==prior.read('d2-source-binding.json'),'control/A0 selected source differs')
            timing=match['verified']['operation_timing'];R.request_matches(reference,timing,matched,cfg)
            projected=_projection_bytes(reader,timing,reference,request['control'])
            time=R.source_time_contract(match['device'],projected['base_projection']['contract'],timing,reference)
            include=reader.read('heavyion.physics.inc');deck=reader.read('device.cmd')
            require(deck==A.render_signal(match['device'],include) and A.source_free_deck(deck,include)==match['device'],
                'control electrical deck differs from original matched A0')
            require(obj(reader.read('source-time-contract.json'))==time,'physical source/native time differs')
    require(reader.read('run-parameters.par')==reader.read('physics.par')+b'\n'+reader.read('source.par')
        and obj(reader.read('parameter-binding.json'))==A.parameter_binding(reader),'actual parameter binding differs')
    names=['source-contract.json',PREFIX+'input-output-manifest.json','operation-timing.json','source-time-contract.json',
        'cell_msh.tdr','physics-manifest.json','dimensional-contract.json']
    declarations={n:reader.read(n) for n in names}
    expected,spec,role=_candidate_declarations(declarations,request,match,matched,originals)
    require(bound==expected and obj(reader.read('source-spec.json'))==spec and obj(reader.read('role-contract.json'))==role
        and cfg['role_id']==role_id(request)==role['role'],'exact candidate source/binding/role differs')
    runtime=runtime_binding(reader,cfg)
    require(obj(reader.read('parameterized-alpha-control-runtime-binding.json'))==runtime
        and reader.digest('parameterized-alpha-control-runtime-binding.json')==cfg.get('parameterized_alpha_control_runtime_sha256'),
        'control runtime binding differs')
    require(reader.read('heavyion.plot.inc')==A.PLOT.rstrip()+b'\n' and reader.read('heavyion.currentplot.inc')==A.CURRENT,
        'control source diagnostics differ')
    result.update(operation_timing=timing,operating_binding=match['verified']['operating_binding'],
        numerical_relation=match['verified']['numerical_relation'],source_spec=spec,role_contract=role,projection=projected,
        control_binding=bound,control_runtime_binding=runtime,matched_a0=matched,source_time_contract=time)
    require(set(result)==FROZEN_RESULT_KEYS,'public control result shape differs')
    return result

def admit(project,spec,runner_sha,bridge):
    R=parent();D=R.dimensional();O=R.operation();project=Path(project);cfg=spec['s2_geometry']
    require('fixture' not in str(project.resolve()).lower() and not (project/'SYNTHETIC_NOT_NATIVE').exists(),'fixture cannot be admitted')
    request=validate_request(obj((project/'controlled-request.json').read_bytes()));reference=request['reference_alpha_request']
    require(cfg.get('schema')==bridge.GEOMETRY_SCHEMA and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
        and spec.get('execution_enabled') is True and spec.get('role')==cfg.get('role_id')==role_id(request)
        and O.plain_name(cfg.get('run_id')) and cfg['run_id'] not in (cfg['producer_run_id'],O.source_name(reference['matched_a0_run']))
        and spec.get('native_threads')==spec.get('native_cores')==1
        and spec.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))],'original single SDevice role/step differs')
    bridge.geometry_context(project,cfg,runner_sha);hashes=bridge.geometry_input_hashes(project)
    d2=obj((project/'d2-source-binding.json').read_bytes())
    projection=obj((project/PREFIX/'input-output-manifest.json').read_bytes())
    required=set(D.SHARED_INPUTS)|set(_runtime_bytes())|set(R.SHARED)|set(d2['original_files'])|set(_snapshot_map())|{
        'project.json','controlled-request.json','case_contract.py','geometry_bridge.py','mesh_resource_guard.py',
        'task-authorization.json','resource-policy.json','device.cmd','cell_msh.tdr','cell_msh.log','d2-source-binding.json',
        'source-contract.json','source.par','heavyion.physics.inc','heavyion.plot.inc','heavyion.currentplot.inc','run-parameters.par',
        'parameter-binding.json','source-time-contract.json','source-control-request.json','parameterized-alpha-control-binding.json',
        'parameterized-alpha-control-runtime-binding.json','source-spec.json','role-contract.json','matched-a0-host-audit.json',PREFIX+'input-output-manifest.json'}|{
        PREFIX+n for n in projection['files']}|{A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}
    require(required<=set(hashes),'mandatory complete control/original proof missing')
    for name,h in hashes.items():require(D.file_sha(bridge.geometry_path(project,name))==h,'frozen input changed: '+name)
    manifest=obj((project/'input-manifest.json').read_bytes())
    require(manifest.get('run_id')==cfg['run_id'] and manifest.get('role_id')==cfg['role_id'],'input manifest identity differs')
    result=verify_frozen(D.FolderReader(project),cfg)
    require(result['operation_timing']['origin']=='prescribed_input','UNIT timing cannot be submitted')
    require(obj((project/'resource-policy.json').read_bytes())==dict(schema='dram-see-v4-actual-resource-policy-r1',role=cfg['role_id'],
        observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None),'observation-only resource policy required')
    return cfg

def prepare(request,run_id,runner=None,output=None):
    """Future original-runner input; no write before real A0 and source replay."""
    C=candidate();R=parent();P=R.parameterized();O=R.operation();D=R.dimensional()
    request=validate_request(request);reference=request['reference_alpha_request']
    dispatch=R.module('case_contract.py');bridge=R.module('geometry_bridge.py')
    require(getattr(dispatch,'SCHEMA_2D_PARAMETERIZED_ALPHA_CONTROL',None)==REQUEST_SCHEMA
        and hasattr(bridge,'geometry_parameterized_alpha_control_module'),'control dispatch not integrated; no project created')
    require(O.plain_name(run_id) and 'fixture' not in run_id.lower()
        and run_id not in (O.source_name(reference['d2_source_run']),O.source_name(reference['matched_a0_run'])),'new nonfixture run ID required')
    runner=Path(runner or ROOT/'scripts/tcad.py').resolve()
    require(runner==(ROOT/'scripts/tcad.py').resolve() and runner.is_file(),'original runner only')
    allowed=(ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/parameterized-alpha-controls-native-integration-r1').resolve()
    target=Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'fixture' not in str(target).lower(),'new control project path required')
    request=obj(encoded(request));reference=request['reference_alpha_request']
    request['control_projection_package']=str(Path(request['control_projection_package']).resolve())
    for n in ('d2_source_run','base_d2_source_run','matched_a0_run','alpha_projection_package'):reference[n]=str(Path(reference[n]).resolve())
    payload=C.candidate_payload(request)
    files=dict(payload['files']);originals=payload['imports'];matched=payload['binding']['matched_a0'];source=Path(reference['matched_a0_run'])
    with tarfile.open(str(source/'results.tar'),'r:*') as archive:
        cfg=dict(obj(D.ArchiveReader(archive).read('project.json'))['s2_geometry'])
    cfg.pop('parameterized_operating_branch');cfg.pop('parameterized_operating_binding_sha256')
    role=role_id(request);cfg.update(run_id=run_id,role_id=role,source_branch=BRANCH,source_run_directory=reference['d2_source_run'],
        base_source_run_directory=reference['base_d2_source_run'],synthetic=False,execution_enabled=True)
    R.request_matches(reference,obj(files['operation-timing.json']),matched,cfg)
    bundle=P.source_bundle(target,cfg)
    require(bundle['mesh_sha256']==cfg['mesh_sha256'] and bundle['d2_source_binding_sha256']==cfg['d2_source_binding_sha256'],
        'control selected/base D2 identity differs')
    for n,raw in bundle['generated_files'].items():require(n not in files or files[n]==raw,'D2 import collision: '+n);files[n]=raw
    files.update(_runtime_bytes());files.update(_mathematical_snapshots())
    files['controlled-request.json']=encoded(request)
    cfg['parameterized_alpha_control_binding_sha256']=sha(files['parameterized-alpha-control-binding.json'])
    files['parameterized-alpha-control-runtime-binding.json']=encoded(runtime_binding(BytesReader(files),cfg))
    cfg['parameterized_alpha_control_runtime_sha256']=sha(files['parameterized-alpha-control-runtime-binding.json'])
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-'+role.lower(),role=role,execution_enabled=True,
        runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))])
    files.update({'project.json':encoded(spec),'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',
        role=role,observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',source='current_user_instruction',
            synthetic=False,role_ids=[role],instruction='Explicitly authorized g80 E5 normal zero/half/split controls on original runner; real matched r13 A0, serial single core/thread, actual usage only.',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',plan_sha256=D.file_sha(ROOT/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md'))),
        'provenance.json':encoded(dict(schema='dram-see-v4-parameterized-alpha-control-input-provenance-r1',
            candidate_manifest=payload['manifest'],matched_a0=matched,host_source_mathematics_replayed=True,
            new_scientific_time_or_gate_selected=False,native_run_completed=False,native_source_qualified=False,training_admitted=False))})
    for n in ('geometry_bridge.py','mesh_resource_guard.py','case_contract.py'):files[n]=(HERE/n).read_bytes()
    files['generator-prepare_case.py']=(HERE/'prepare_case.py').read_bytes()
    hashes={n:sha(v) for n,v in files.items()}
    for n,h in bundle['exports'].items():require(n not in hashes or hashes[n]==h,'D2 export collision: '+n);hashes[n]=h
    for n,row in originals.items():require(n not in hashes,'matched A0 import collision: '+n);hashes[n]=row['sha256']
    files['input-manifest.json']=encoded(dict(schema='dram-see-v4-continuous-inputs-r1',run_id=run_id,role_id=role,files_sha256=hashes))
    runner_sha=D.file_sha(runner)
    files['execution-context.json']=encoded(dict(schema='dram-see-v4-continuous-run-context-r1',run_id=run_id,role_id=role,
        producer_run_id=cfg['producer_run_id'],synthetic=False,expected_runner_sha256=runner_sha,
        input_manifest_sha256=sha(files['input-manifest.json']),authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True,exist_ok=False)
    for n,raw in files.items():bridge.geometry_write(target/n,raw)
    for n,row in originals.items():
        require(file_sha(row['path'])==row['sha256'],'matched A0 changed while preparing')
        destination=target/n;destination.parent.mkdir(parents=True,exist_ok=True)
        with Path(row['path']).open('rb') as inp,destination.open('xb') as out:
            for block in iter(lambda:inp.read(1048576),b''):out.write(block)
        require(file_sha(destination)==row['sha256'],'matched original copy differs')
    bridge.geometry_stage_reuse(target,cfg);bridge.geometry_admit(target,spec,runner_sha)
    return dict(project=str(target),run_id=run_id,role_id=role,matched_a0=matched,
        parameterized_alpha_control_binding_sha256=cfg['parameterized_alpha_control_binding_sha256'],
        parameterized_alpha_control_runtime_sha256=cfg['parameterized_alpha_control_runtime_sha256'],
        input_manifest_sha256=sha(files['input-manifest.json']),native_submissions=0,native_source_qualified=False,training_admitted=False)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',type=Path,required=True)
    p.add_argument('--run-id',required=True);p.add_argument('--output',type=Path);args=p.parse_args()
    print(encoded(prepare(obj(args.request.read_bytes()),args.run_id,output=args.output)).decode('utf-8'))
    return 0

if __name__=='__main__':raise SystemExit(main())
