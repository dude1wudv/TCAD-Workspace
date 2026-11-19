"""Explicit-operation 2D alpha inputs, with replay of a real matching A0.

Guest verification is Python 3.6 stdlib. Host prepare replays the fixed 16d2
projection; guest verifies frozen mathematical bytes and never executes archive
code. No scheduler, new timing choice, source qualification or training label.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import tarfile

BRANCH = 'dram-see-v4-operating-alpha-2d-r1'
REQUEST_SCHEMA = 'dram-see-v4-controlled-device-request-r12'
BINDING_SCHEMA = 'dram-see-v4-operating-alpha-2d-binding-r1'
SPEC_SCHEMA = 'dram-see-v4-2d-operating-alpha-source-spec-r1'
ROLE_SCHEMA = 'dram-see-v4-2d-operating-alpha-role-r1'
TIME_SCHEMA = 'dram-see-v4-operating-alpha-2d-native-time-r1'
OPERATION_SHA = '97a5ea8cf6fb64bdfe345adaf09f4aa8f222b8b443d84819fd64c0f447e937a5'
ALPHA_NATIVE_SHA = '9ed322fdc16eb28bf99f82ca32f8b62c3a15219188aaadfd96c1882c1e7b77f7'
D2_SHA = 'c09b52ad56fcdf7e22dfb70ce750b04fd9fa383e1bda8a68ac9121ed768055cd'
CLOCK_SHA = 'bf5d9a8c5520eda054ecadd14fa4fc06f2f3b7296f16483e5ded02ff20ab4387'
METRICS_SHA = '0083e300fd1242d77616597f7a47e075386fff36d991070dd662b414e6f97bc2'
LEGACY_SHA = '14681b6fae30bce49a8b1063b3f8abd7e790e51c6afe58f74da094cd574b2d6e'
PROJECTION_SHA = '16d2fe5e7a182d2ed11e17c197493dac822482ee1c6c6c0da0336a9c86a81f56'
REFERENCE_SHA = '82a5b47c685c9156f212787999c07d21d1aee249b22b3f783f89cf499da4e4ec'
DEPENDENCIES = {
    'alpha': ('../proton/alpha_source_v2.py','a75aade10dd65acbab0b3e6af03f86166112125d482e815abc590789a43eed43'),
    'moments': ('../proton/alpha_moments_v2.py','cf0c2b0d43baf8c4021989ed5de8bd162d7767a6fcfa5c68b5d35ade5c7c70c2'),
    'common': ('../projection2d/kernel.py','c9b44b5f808212a018dfa37542bc218410048ba05d9ee211b2bf933bc4d78069')}
PROJECTION_PREFIX = 'alpha-projection/'
A0_PREFIX = 'matched-a0-bindings/'
PROJECTION_FILES = ('alpha-astar-silicon.csv','alpha-profile-2d-native.csv','alpha-profile-3d-reference.csv',
    'dimensional-contract.json','geometry-contract.json','heavyion.physics.inc','input-origins.json','model.proposed.json',
    'projection-ledger.json','projection-request.json','source-contract.json','source.par','input-output-manifest.json')
SHARED = ('physics.par','physics-manifest.json','Silicon.par','Oxide.par','model.proposed.json','geometry-contract.json',
    'dimensional-contract.json','numerical-method.json','initialization-contract.json','functional-criteria.json',
    'operation-timing.json','rendered-operation-timing.json')
RUNTIME_FILES = ('operating_alpha_2d.py','alpha_native_2d.py','operating_transient_2d.py','two_dimensional.py',
    'native_transient_clock.py','operating_metrics_2d.py','legacy-circuit-metrics.py')
REQUEST_FIELDS = {'schema','kind','dimension','gate_top_depth_nm','sn_junction_depth_nm','variant','stored_bit',
    'source_case','particle','d2_source_run','effective_width_nm','matched_a0_run','alpha_projection_package',
    'operation_timing_sha256','gate_high_V','source_epoch_s','mathematical_source_window_s','native_observation_window_s'}


def require(ok,message):
    if not ok: raise ValueError('2D operating alpha: '+message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')
def obj(raw):
    value=json.loads(raw.decode('utf-8'));require(isinstance(value,dict),'expected JSON object');return value
def number(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except (ValueError,OverflowError):return False
def module(name,expected=None):
    path=Path(__file__).with_name(name)
    require(path.is_file() and not path.is_symlink(),'missing fixed local module '+name)
    if expected is not None:require(sha(path.read_bytes())==expected,'fixed implementation changed: '+name)
    spec=importlib.util.spec_from_file_location('_operating_alpha_'+name.replace('.','_'),str(path))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
def operation():return module('operating_transient_2d.py',OPERATION_SHA)
def alpha():return module('alpha_native_2d.py',ALPHA_NATIVE_SHA)
def dimensional():return module('two_dimensional.py',D2_SHA)


def validate_request(request):
    O=operation()
    require(isinstance(request,dict) and set(request)==REQUEST_FIELDS,'exact r12 fields required')
    require(request['schema']==REQUEST_SCHEMA and request['kind']=='transient' and request['source_case']=='Aalpha'
            and request['particle']=='alpha' and request['variant']=='main','only explicit-operation positive alpha main is supported')
    for key,value in (('dimension',2),('gate_top_depth_nm',80),('sn_junction_depth_nm',87),('effective_width_nm',20)):
        require(type(request[key]) is int and request[key]==value,'fixed original D2 geometry/width differs: '+key)
    require(type(request['stored_bit']) is int and request['stored_bit'] in (0,1),'integer bit 0 or 1 required')
    for key in ('d2_source_run','matched_a0_run','alpha_projection_package'):
        require(isinstance(request[key],str) and request[key].strip(),'explicit input path missing: '+key)
    require(O.source_name(request['d2_source_run'])==O.D2_RUN and O.digest_ok(request['operation_timing_sha256']),
            'original D2 identity or explicit operation timing SHA differs')
    require(number(request['gate_high_V']) and request['gate_high_V']>-.5
            and number(request['source_epoch_s']) and request['source_epoch_s']>0,'explicit finite gate/source epoch required')
    for key in ('mathematical_source_window_s','native_observation_window_s'):
        window=request[key]
        require(isinstance(window,list) and len(window)==2 and all(number(v) for v in window)
                and 0<=window[0]<request['source_epoch_s']<window[1],'explicit physical source window required: '+key)
    return obj(encoded(request))


def role_id(request):return 'B2D-Aalpha-operating-r1-main-b'+str(validate_request(request)['stored_bit'])


def source_request(value,timing):
    require(isinstance(value,dict) and set(value)=={'schema','energy_MeV','theta_deg','phi_deg','amplitude','epoch_s','simulation_window_s'},
            'fixed projection request shape differs')
    expected=dict(schema='dram-see-v4-alpha-projection-request-r1',energy_MeV=5,theta_deg=0,phi_deg=180,amplitude=1.,
        epoch_s=timing['source_epoch_s'],simulation_window_s=timing['simulation_window_s'])
    require(value==expected and all(number(value[n]) for n in ('energy_MeV','theta_deg','phi_deg','amplitude','epoch_s')),
            'only original 5MeV normal amplitude1 source at explicit actual operation times is supported')
    return value


def source_time_contract(a0_device,contract,timing):
    O=operation();A=alpha();timing=O.validate_timing(timing);source_request(contract['request'],timing)
    require(contract['source_window_s']==timing['mathematical_source_window_s']
            and contract['full_simulation_window_s']==timing['simulation_window_s'], 'projection physical mathematical/full windows differ')
    clock=module('native_transient_clock.py',CLOCK_SHA);segments,_=clock._deck(a0_device)
    require([(float(s['initial_literal']),float(s['final_literal'])) for s in segments]
            ==[(s['start_s'],s['end_s']) for s in timing['segments']], 'actual A0 Solve physical segments differ')
    n=A.NUMBER.encode('ascii')
    matches=re.findall(rb'Plot\(FilePrefix="source_window" Time=\(Range=\(('+n+rb') ('+n+rb')\)\) NoOverwrite\)',a0_device)
    windows=[[v.decode('ascii') for v in pair] for pair in matches]
    actual=[[float(v) for v in pair] for pair in windows]
    native=timing['native_observation_window_s']
    expected=[[s['start_s'],s['end_s']] for s in timing['segments'] if native[0]<=s['start_s'] and s['end_s']<=native[1]]
    require(actual and actual==expected and actual[0][0]==native[0] and actual[-1][1]==native[1]
            and all(a[1]==b[0] for a,b in zip(actual,actual[1:])), 'all actual NoOverwrite observation segments must cover the exact native window')
    return dict(schema=TIME_SCHEMA,source_epoch_s=timing['source_epoch_s'],full_simulation_window_s=timing['simulation_window_s'],
        mathematical_source_window_s=timing['mathematical_source_window_s'],native_observation_window_s=native,
        native_observation_segment_literals=windows,native_segments=segments,
        native_minus_mathematical_window_s=[x-y for x,y in zip(native,timing['mathematical_source_window_s'])],
        time_remapped=False,additional_normalization=False,observation_window_is_not_physical_source_truncation=True,
        native_source_clock_qualified=False)


def render_signal(a0_device,include):return alpha().render_signal(a0_device,include)
def source_free_deck(device,include):return alpha().source_free_deck(device,include)


def verify_matched_a0(reader,manifest,inputs,bit):
    """Only original new-operation A0; no flag-only or old-r8 acceptance."""
    O=operation();D=dimensional();A=alpha()
    project=obj(reader.read('project.json'));cfg=project.get('s2_geometry',{});context=obj(reader.read('execution-context.json'))
    wanted='B2D-A0-operating-r1-main-b'+str(bit)
    require(type(bit) is int and bit in (0,1) and project.get('role')==cfg.get('role_id')==context.get('role_id')==wanted
            and cfg.get('operating_transient_branch')==O.BRANCH,'matched A0 must be the actual same-bit r11 operation; old r8 cannot be relabelled')
    A._collection(reader,manifest,inputs,D)
    require(cfg.get('run_id')==manifest['run_id'] and cfg.get('synthetic') is False and cfg.get('mode')=='reuse'
            and cfg.get('execution_enabled') is True and project.get('execution_enabled') is True
            and context.get('producer_run_id')==cfg.get('producer_run_id')==O.D2_RUN
            and obj(reader.read('input-manifest.json')).get('role_id')==wanted
            and project.get('native_threads')==project.get('native_cores')==1
            and project.get('steps')==manifest.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))],
            'matched A0 source/run/serial step identity differs')
    verified=O.verify_frozen(reader,cfg);t=verified['operation_timing']
    require(t['origin']=='prescribed_input' and verified['role_contract']['stored_bit']==bit
            and verified['source_spec']['source_configured'] is False,'fixture or non-control cannot supply actual matched A0')
    device=reader.read('device.cmd');clock=module('native_transient_clock.py',CLOCK_SHA).audit(
        reader.read('circuit.plt'),reader.read('access_device.plt'),reader.read('transient_des.log'),device)
    metrics=O.metrics_api().baseline(clock['trace'],bit,t)
    require(metrics['candidate_functional_pass'] is True and all(v is True for v in metrics['checks'].values()),
            'matched A0 original five criteria/KCL failed: '+json.dumps(metrics['checks'],sort_keys=True))
    require(metrics['accepted_trace']==clock['trace'] and metrics['time_coordinate_transformed'] is False
            and metrics['training_admitted'] is False,'pure metrics must preserve real time/trace and scope')
    shared={n:reader.read(n) for n in SHARED}
    shared.update({'operation-selection/'+n:reader.read('operation-selection/'+n) for n in t['selection_provenance']['references']})
    return dict(verified=verified,project=project,cfg=cfg,role=verified['role_contract'],device=device,metrics=metrics,
        clock=clock,shared=shared,input_manifest_sha256=reader.digest('input-manifest.json'),
        circuit_plt_sha256=reader.digest('circuit.plt'),collection_index_sha256=reader.digest('_collection-members.json'),
        operating_binding_sha256=reader.digest('operating-transient-binding.json'))


def matched_identity(match,manifest,manifest_sha,archive_sha):
    return dict(run_id=manifest['run_id'],manifest_sha256=manifest_sha,archive_sha256=archive_sha,
        input_manifest_sha256=match['input_manifest_sha256'],device_sha256=sha(match['device']),producer_run_id=match['cfg']['producer_run_id'],
        stored_bit=match['cfg']['stored_bit'],numerical_variant='main',operation_timing_sha256=sha(match['shared']['operation-timing.json']),
        gate_high_V=match['cfg']['gate_high_V'],operating_binding_sha256=match['operating_binding_sha256'],
        circuit_plt_sha256=match['circuit_plt_sha256'],collection_index_sha256=match['collection_index_sha256'],
        metrics_implementation_sha256=METRICS_SHA,metrics_sha256=sha(encoded(match['metrics'])),functional_checks=match['metrics']['checks'],
        candidate_functional_pass=True,clock_sha256=sha(encoded(match['clock'])),clock_implementation_sha256=CLOCK_SHA,
        all_original_rows_and_attempts_retained=True,native_engineering_completed=True,refinement_qualified=False,source_qualified=False)


def projection(reader,timing):
    manifest=obj(reader.read(PROJECTION_PREFIX+'input-output-manifest.json'))
    require(manifest.get('schema')=='dram-see-v4-alpha-2d-input-output-manifest-r1'
            and manifest.get('implementation_sha256')==PROJECTION_SHA and manifest.get('is_native_result') is False
            and manifest.get('native_source_qualified') is False and set(manifest.get('files',{}))==set(PROJECTION_FILES)-{'input-output-manifest.json'},
            'fixed unqualified projection package differs')
    for name,row in manifest['files'].items():
        require(row==dict(sha256=reader.digest(PROJECTION_PREFIX+name),size_bytes=reader.size(PROJECTION_PREFIX+name)), 'projection bytes differ: '+name)
    require(reader.digest('alpha-projection-implementation.py')==PROJECTION_SHA,'projection implementation snapshot differs')
    for key,(_,digest) in DEPENDENCIES.items():
        require(reader.digest('alpha-projection-dependency-'+key+'.py')==digest,'projection dependency snapshot differs: '+key)
    require(reader.digest('alpha-projection-reference.py')==REFERENCE_SHA,'independent mathematical reference differs')
    contract=obj(reader.read(PROJECTION_PREFIX+'source-contract.json'))
    require(contract.get('schema')=='dram-see-v4-alpha-projection-2d-r1' and contract.get('particle')=='alpha'
            and contract.get('dimension')==2 and contract.get('native_source_qualified') is False
            and contract.get('is_tcad_result') is False and contract.get('pmi_r12_fixed') is False
            and contract.get('dependency_sha256')=={k:dict(path=p,sha256=h) for k,(p,h) in DEPENDENCIES.items()}
            and contract.get('independent_reference_sha256')==REFERENCE_SHA,'projection semantic/implementation identity differs')
    source_request(contract['request'],timing)
    require(obj(reader.read(PROJECTION_PREFIX+'projection-request.json'))==contract['request']
            and contract['source_window_s']==timing['mathematical_source_window_s']
            and contract['full_simulation_window_s']==timing['simulation_window_s'],'projection time contract differs')
    for name in ('model.proposed.json','geometry-contract.json','dimensional-contract.json'):
        require(reader.digest(name)==reader.digest(PROJECTION_PREFIX+name)==contract['input_sha256'][name], 'actual Si/width/model differs: '+name)
    for name in ('source-contract.json','heavyion.physics.inc','source.par'):
        require(reader.read(name)==reader.read(PROJECTION_PREFIX+name),'active source bytes differ: '+name)
    require(contract['mesh_sha256']==reader.digest('cell_msh.tdr') and contract['physics_manifest_sha256']==reader.digest('physics-manifest.json'),
            'projection actual mesh/physics differs')
    return dict(contract=contract,ledger=obj(reader.read(PROJECTION_PREFIX+'projection-ledger.json')),manifest=manifest,
        guest_mathematical_replay=False,guest_scope='Frozen bytes and closed implementation identity; full P.verify mathematical replay is host prepare only')


def source_spec(reader,bit,binding_sha):
    return dict(schema=SPEC_SCHEMA,particle='alpha',role='SIGNAL',source_case='Aalpha',dimension=2,stored_bit=bit,numerical_variant='main',
        source_configured=True,physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),source_contract_sha256=reader.digest('source-contract.json'),
        source_time_contract_sha256=reader.digest('source-time-contract.json'),operating_alpha_binding_sha256=binding_sha,
        currentplot_integration_unit='um',currentplot_domain='Semiconductor',currentplot_is_diagnostic_not_field_qualification=True,
        native_source_qualified=False)


def role_contract(match,role,binding_sha,source_sha):
    value=dict(match['role']);value.pop('operating_transient_binding_sha256')
    value.update(schema=ROLE_SCHEMA,role=role,case='Aalpha',source_configured=True,
        matched_a0_operating_binding_sha256=match['operating_binding_sha256'],operating_alpha_binding_sha256=binding_sha,
        source_contract_sha256=source_sha,native_syntax_verified=False,native_source_qualified=False)
    return value


def binding(reader,cfg,match,matched,originals):
    return dict(schema=BINDING_SCHEMA,source_branch=BRANCH,stored_bit=cfg['stored_bit'],producer_run_id=cfg['producer_run_id'],
        verifier_sha256=sha(Path(__file__).read_bytes()),old_alpha_adapter_sha256=ALPHA_NATIVE_SHA,operation_verifier_sha256=OPERATION_SHA,
        projection_verifier_sha256=PROJECTION_SHA,projection_manifest_sha256=reader.digest(PROJECTION_PREFIX+'input-output-manifest.json'),
        source_contract_sha256=reader.digest('source-contract.json'),source_time_contract_sha256=reader.digest('source-time-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),gate_high_V=match['cfg']['gate_high_V'],
        physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        mesh_sha256=cfg['mesh_sha256'],matched_a0=matched,matched_a0_original_files=originals,
        mathematical_policy='Fixed16d2 host P.verify; guest frozen identity only',additional_normalization=False,
        native_source_qualified=False,is_native_result=False,pmi_r12_fixed=False,training_admitted=False)


def request_matches(request,timing,matched,cfg):
    O=operation()
    require(request['stored_bit']==cfg['stored_bit']==matched['stored_bit']
            and O.source_name(request['matched_a0_run'])==matched['run_id']
            and request['operation_timing_sha256']==matched['operation_timing_sha256']==cfg['operation_timing_sha256']
            and request['gate_high_V']==timing['voltage_levels_V']['gate_high_V']==cfg['gate_high_V']
            and request['source_epoch_s']==timing['source_epoch_s']
            and request['mathematical_source_window_s']==timing['mathematical_source_window_s']
            and request['native_observation_window_s']==timing['native_observation_window_s'], 'request differs from actual matched operation/source times or gate')


def verify_frozen(reader,cfg):
    O=operation();D=dimensional();A=alpha()
    require(cfg.get('source_branch')==BRANCH and cfg.get('dimension_branch')==D.BRANCH and cfg.get('mode')=='reuse'
            and 'operating_transient_branch' not in cfg,'alpha root must not masquerade as the strict A0 branch')
    runtime={'operating_alpha_2d.py':sha(Path(__file__).read_bytes()),'alpha_native_2d.py':ALPHA_NATIVE_SHA,'operating_transient_2d.py':OPERATION_SHA,
        'two_dimensional.py':D2_SHA,'native_transient_clock.py':CLOCK_SHA,'operating_metrics_2d.py':METRICS_SHA,'legacy-circuit-metrics.py':LEGACY_SHA}
    require(all(reader.digest(n)==h for n,h in runtime.items()),'frozen runtime bytes differ')
    result=D.verify_frozen(reader,cfg);request=validate_request(obj(reader.read('controlled-request.json')))
    bound=obj(reader.read('operating-alpha-binding.json'))
    require(bound.get('schema')==BINDING_SCHEMA and reader.digest('operating-alpha-binding.json')==cfg.get('operating_alpha_binding_sha256'), 'alpha binding identity differs')
    originals=bound.get('matched_a0_original_files',{})
    require(set(originals)=={A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')},'complete original matched A0 proof required')
    for name,row in originals.items():require(row==dict(sha256=reader.digest(name),size_bytes=reader.size(name)),'original matched A0 bytes differ: '+name)
    manifest=obj(reader.read(A0_PREFIX+'manifest.json'))
    require(manifest.get('results_sha256')==reader.digest(A0_PREFIX+'results.tar')
            and manifest.get('inputs_archive_sha256')==reader.digest(A0_PREFIX+'inputs.tar'),'matched A0 outer receipt differs')
    with reader.stream(A0_PREFIX+'results.tar') as a,reader.stream(A0_PREFIX+'inputs.tar') as i:
        with tarfile.open(fileobj=a,mode='r:*') as archive,tarfile.open(fileobj=i,mode='r:*') as inputs:
            prior=D.ArchiveReader(archive);match=verify_matched_a0(prior,manifest,D.ArchiveReader(inputs),request['stored_bit'])
            matched=matched_identity(match,manifest,reader.digest(A0_PREFIX+'manifest.json'),reader.digest(A0_PREFIX+'results.tar'))
            for name,value in match['shared'].items():require(reader.read(name)==value,'signal/A0 operation/physics/width changed: '+name)
            require(reader.digest('cell_msh.tdr')==prior.digest('cell_msh.tdr')==cfg['mesh_sha256']
                    and cfg['producer_run_id']==match['cfg']['producer_run_id'],'signal/A0 actual D2 mesh differs')
            timing=match['verified']['operation_timing'];request_matches(request,timing,matched,cfg)
            p=projection(reader,timing);time=source_time_contract(match['device'],p['contract'],timing)
            include=reader.read('heavyion.physics.inc');device=reader.read('device.cmd')
            require(device==A.render_signal(match['device'],include) and A.source_free_deck(device,include)==match['device'],
                    'stripped alpha deck must equal the actual matched A0 bytes')
            require(obj(reader.read('source-time-contract.json'))==time,'native/mathematical time declarations differ')
    require(reader.read('run-parameters.par')==reader.read('physics.par')+b'\n'+reader.read('source.par')
            and obj(reader.read('parameter-binding.json'))==A.parameter_binding(reader),'exact base/source parameter binding differs')
    expected=binding(reader,cfg,match,matched,originals)
    require(bound==expected,'complete alpha source/operation/matched-A0 binding differs')
    spec=source_spec(reader,request['stored_bit'],reader.digest('operating-alpha-binding.json'))
    role=role_contract(match,role_id(request),reader.digest('operating-alpha-binding.json'),reader.digest('source-contract.json'))
    require(obj(reader.read('source-spec.json'))==spec and obj(reader.read('role-contract.json'))==role
            and cfg['role_id']==role['role'],'alpha role/source declaration differs')
    require(reader.read('heavyion.plot.inc')==A.PLOT.rstrip()+b'\n' and reader.read('heavyion.currentplot.inc')==A.CURRENT,
            'source field/current diagnostic requests differ')
    result.update(operation_timing=timing,source_spec=spec,projection=p,alpha_binding=bound,matched_a0=matched,source_time_contract=time,role_contract=role)
    return result


def admit(project,spec,runner_sha,bridge):
    project=Path(project);O=operation();D=dimensional()
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve()) and not (project/'SYNTHETIC_NOT_NATIVE').exists(),'fixture cannot be submitted')
    cfg=spec['s2_geometry'];request=validate_request(obj((project/'controlled-request.json').read_bytes()))
    require(cfg.get('schema')==bridge.GEOMETRY_SCHEMA and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
            and spec.get('execution_enabled') is True and spec.get('role')==cfg.get('role_id')==role_id(request)
            and O.plain_name(cfg.get('run_id')) and cfg.get('run_id') not in (O.D2_RUN,O.source_name(request['matched_a0_run']))
            and spec.get('native_threads')==spec.get('native_cores')==1
            and spec.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))], 'native role/serial-step context differs')
    bridge.geometry_context(project,cfg,runner_sha);hashes=bridge.geometry_input_hashes(project)
    required=set(D.SHARED_INPUTS)|set(RUNTIME_FILES)|set(SHARED)|{D.PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}|{
        'project.json','controlled-request.json','case_contract.py','geometry_bridge.py','mesh_resource_guard.py','task-authorization.json','resource-policy.json',
        'device.cmd','cell_msh.tdr','cell_msh.log','d2-source-binding.json','dimensional-contract.json','source-contract.json','source.par',
        'heavyion.physics.inc','heavyion.plot.inc','heavyion.currentplot.inc','run-parameters.par','parameter-binding.json',
        'source-time-contract.json','operating-alpha-binding.json','source-spec.json','role-contract.json','alpha-projection-implementation.py',
        'alpha-projection-reference.py'}|{PROJECTION_PREFIX+n for n in PROJECTION_FILES}|{A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}|{
        'alpha-projection-dependency-'+key+'.py' for key in DEPENDENCIES}
    require(required<=set(hashes),'mandatory original alpha/matched-A0 evidence absent')
    for name,digest in hashes.items():require(D.file_sha(bridge.geometry_path(project,name))==digest,'frozen input changed: '+name)
    manifest=obj((project/'input-manifest.json').read_bytes())
    require(manifest.get('run_id')==cfg['run_id'] and manifest.get('role_id')==cfg['role_id'],'input manifest identity differs')
    verify_frozen(D.FolderReader(project),cfg)
    require(obj((project/'resource-policy.json').read_bytes())==dict(schema='dram-see-v4-actual-resource-policy-r1',role=cfg['role_id'],
        observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None),'only actual resource observations are allowed')
    return cfg


def prepare(request,run_id,runner=None,output=None):
    """Future actual input only; real matched A0 and full P.verify before writing."""
    request=validate_request(request);O=operation();D=dimensional();A=alpha()
    C=module('case_contract.py');bridge=module('geometry_bridge.py')
    require(getattr(C,'SCHEMA_2D_OPERATING_ALPHA',None)==REQUEST_SCHEMA and hasattr(bridge,'geometry_operating_alpha_module'),
            'r12 dispatch is not integrated; no project directory created')
    require(O.plain_name(run_id) and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id
            and run_id not in (O.D2_RUN,O.source_name(request['matched_a0_run'])),'new nonfixture run ID required')
    here=Path(__file__).resolve().parent;root=here.parents[3];runner=Path(runner or root/'scripts/tcad.py').resolve()
    require(runner==(root/'scripts/tcad.py').resolve() and runner.is_file(),'original runner required')
    allowed=(root/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/operating-alpha-implementation-r1').resolve()
    target=Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target),'new allowed output directory required')
    request=dict(request)
    for name in ('d2_source_run','matched_a0_run','alpha_projection_package'):request[name]=str(Path(request[name]).resolve())
    source=Path(request['matched_a0_run'])
    require(source.is_dir() and not source.is_symlink() and 'fixture' not in str(source).lower()
            and not (source/'SYNTHETIC_NOT_NATIVE').exists(),'real original matched A0 required')
    manifest_raw=(source/'manifest.json').read_bytes();manifest=obj(manifest_raw)
    require(manifest.get('run_id')==source.name and manifest.get('state')=='COLLECTED','matched A0 is not completely collected')
    originals={A0_PREFIX+n:dict(path=str(source/n),sha256=D.file_sha(source/n),size_bytes=(source/n).stat().st_size) for n in ('manifest.json','results.tar','inputs.tar')}
    require(manifest.get('results_sha256')==originals[A0_PREFIX+'results.tar']['sha256']
            and manifest.get('inputs_archive_sha256')==originals[A0_PREFIX+'inputs.tar']['sha256'],'matched original archive/receipt mismatch')
    with tarfile.open(str(source/'results.tar'),'r:*') as a,tarfile.open(str(source/'inputs.tar'),'r:*') as i:
        match=verify_matched_a0(D.ArchiveReader(a),manifest,D.ArchiveReader(i),request['stored_bit'])
    P=module('alpha_projection_2d.py',PROJECTION_SHA);projected=P.verify(Path(request['alpha_projection_package']))
    source_request(projected['contract']['request'],match['verified']['operation_timing'])
    packet={n:(Path(request['alpha_projection_package'])/n).read_bytes() for n in PROJECTION_FILES}
    require(obj(packet['input-output-manifest.json'])==projected['manifest']
            and all(sha(packet[n])==row['sha256'] and len(packet[n])==row['size_bytes'] for n,row in projected['manifest']['files'].items()),
            'projection changed after full host mathematical replay')
    matched=matched_identity(match,manifest,sha(manifest_raw),originals[A0_PREFIX+'results.tar']['sha256'])
    role=role_id(request);cfg=dict(match['cfg']);cfg.pop('operating_transient_branch');cfg.pop('operating_transient_binding_sha256')
    cfg.update(role_id=role,run_id=run_id,source_branch=BRANCH,source_run_directory=request['d2_source_run'],execution_enabled=True,synthetic=False)
    request_matches(request,match['verified']['operation_timing'],matched,cfg)
    bundle=bridge.geometry_source_bundle(target,cfg)
    require(bundle['mesh_sha256']==match['cfg']['mesh_sha256'] and bundle['d2_source_binding_sha256']==match['cfg']['d2_source_binding_sha256'],
            'signal/A0 original D2 binding differs')
    files=dict(match['shared']);files.update(bundle['generated_files']);files.update({PROJECTION_PREFIX+n:v for n,v in packet.items()})
    for name in ('source-contract.json','heavyion.physics.inc','source.par'):files[name]=packet[name]
    time=source_time_contract(match['device'],projected['contract'],match['verified']['operation_timing'])
    files.update({'device.cmd':A.render_signal(match['device'],packet['heavyion.physics.inc']),
        'run-parameters.par':files['physics.par']+b'\n'+packet['source.par'],'source-time-contract.json':encoded(time),
        'heavyion.plot.inc':A.PLOT.rstrip()+b'\n','heavyion.currentplot.inc':A.CURRENT,
        'alpha-projection-implementation.py':(here/'alpha_projection_2d.py').read_bytes(),
        'alpha-projection-reference.py':(here/'../proton/source_reference.py').read_bytes()})
    for key,(relative,digest) in DEPENDENCIES.items():
        data=(here/relative).read_bytes();require(sha(data)==digest,'fixed projection dependency changed');files['alpha-projection-dependency-'+key+'.py']=data
    class BytesReader:
        def read(self,name):return files[name]
        def digest(self,name):return sha(files[name])
        def size(self,name):return len(files[name])
    check=BytesReader()
    for name in ('model.proposed.json','geometry-contract.json','dimensional-contract.json'):
        require(files[name]==packet[name],'actual source/A0 model/Si/width differs: '+name)
    files['parameter-binding.json']=encoded(A.parameter_binding(check))
    bound=binding(check,cfg,match,matched,{n:{k:v for k,v in row.items() if k!='path'} for n,row in originals.items()})
    files['operating-alpha-binding.json']=encoded(bound);cfg['operating_alpha_binding_sha256']=sha(files['operating-alpha-binding.json'])
    files['source-spec.json']=encoded(source_spec(check,request['stored_bit'],cfg['operating_alpha_binding_sha256']))
    files['role-contract.json']=encoded(role_contract(match,role,cfg['operating_alpha_binding_sha256'],sha(files['source-contract.json'])))
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-'+role.lower(),role=role,execution_enabled=True,
        runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))])
    files.update({'project.json':encoded(spec),'controlled-request.json':encoded(request),
        'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',role=role,observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',source='current_user_instruction',synthetic=False,role_ids=[role],
            instruction='真实新时序A0通过后，原D2同bit/网格/物理/宽度/电路时序的5MeV法向alpha；原runner/owner/锁及单核单线程，不设置项目额度。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',plan_sha256=D.file_sha(root/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md'))),
        'provenance.json':encoded(dict(schema='dram-see-v4-operating-alpha-2d-provenance-r1',run_id=run_id,role=role,matched_a0=matched,
            host_projection_mathematics_replayed=True,projection_manifest_sha256=sha(packet['input-output-manifest.json']),
            source_free_deck_byte_identical=True,actual_operation_timing_sha256=cfg['operation_timing_sha256'],gate_high_V=cfg['gate_high_V'],
            new_time_or_gate_selected_by_generator=False,additional_normalization=False,native_run_completed=False,native_source_qualified=False,pmi_r12_fixed=False,training_admitted=False))})
    for name in ('geometry_bridge.py','mesh_resource_guard.py','case_contract.py','operating_alpha_2d.py','alpha_native_2d.py','operating_transient_2d.py','two_dimensional.py','native_transient_clock.py'):
        files[name]=(here/name).read_bytes()
    files['operating_metrics_2d.py']=(here.parent/'data/operating_metrics_2d.py').read_bytes()
    files['legacy-circuit-metrics.py']=(here.parents[1]/'s2-inputs-r1/metrics.py').read_bytes()
    files['generator-prepare_case.py']=(here/'prepare_case.py').read_bytes()
    hashes={n:sha(v) for n,v in files.items()}
    for name,digest in bundle['exports'].items():
        require(name not in hashes or hashes[name]==digest,'original D2 import collision');hashes[name]=digest
    for name,row in originals.items():require(name not in hashes,'matched proof collision');hashes[name]=row['sha256']
    files['input-manifest.json']=encoded(dict(schema='dram-see-v4-continuous-inputs-r1',role_id=role,run_id=run_id,files_sha256=hashes))
    runner_sha=D.file_sha(runner)
    files['execution-context.json']=encoded(dict(schema='dram-see-v4-continuous-run-context-r1',run_id=run_id,role_id=role,producer_run_id=cfg['producer_run_id'],
        synthetic=False,expected_runner_sha256=runner_sha,input_manifest_sha256=sha(files['input-manifest.json']),authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True,exist_ok=False)
    for name,value in files.items():bridge.geometry_write(target/name,value)
    for name,row in originals.items():
        require(D.file_sha(row['path'])==row['sha256'],'original A0 changed during preparation')
        path=target/name;path.parent.mkdir(parents=True,exist_ok=True)
        with Path(row['path']).open('rb') as inp,path.open('xb') as out:
            for block in iter(lambda:inp.read(1048576),b''):out.write(block)
        require(D.file_sha(path)==row['sha256'],'matched archive copy differs')
    bridge.geometry_stage_reuse(target,cfg);bridge.geometry_admit(target,spec,runner_sha)
    return dict(project=str(target),run_id=run_id,role_id=role,matched_a0=matched,operation_timing_sha256=cfg['operation_timing_sha256'],
        gate_high_V=cfg['gate_high_V'],operating_alpha_binding_sha256=cfg['operating_alpha_binding_sha256'],
        input_manifest_sha256=sha(files['input-manifest.json']),native_submissions=0,native_source_qualified=False,training_admitted=False)
