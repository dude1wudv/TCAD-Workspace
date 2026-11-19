"""Explicit-time 2D A0 input construction; no scheduler or native qualification.

Python 3.6 standard library. Original D2 proof and small original A0 template
bytes are checked independently. No operation duration or gate-high default.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

BRANCH = 'dram-see-v4-operating-transient-2d-r1'
REQUEST_SCHEMA = 'dram-see-v4-controlled-device-request-r11'
TIMING_SCHEMA = 'dram-see-v4-2d-operation-timing-r1'
D2_RUN = '20261017T051217Z-v4-continuous-b1-d2-r8'
D2_SHA = 'c09b52ad56fcdf7e22dfb70ce750b04fd9fa383e1bda8a68ac9121ed768055cd'
CLOCK_SHA = 'bf5d9a8c5520eda054ecadd14fa4fc06f2f3b7296f16483e5ded02ff20ab4387'
METRICS_SHA = '0083e300fd1242d77616597f7a47e075386fff36d991070dd662b414e6f97bc2'
LEGACY_SHA = '14681b6fae30bce49a8b1063b3f8abd7e790e51c6afe58f74da094cd574b2d6e'
TEMPLATE_RUN = '20261019T104330Z-v4-2d-a0-main-b0-input-r2'
TEMPLATE_SHA = 'c87ef4950327efcd97184165b84fccfbc747e1601a0418c94a199d7f70a60531'
TEMPLATE_MANIFEST_SHA = 'cea7089c3013b5f1857ca799cd4e90f424dcf45fef730cbb8da39113a1f7df7f'
TEMPLATE_FILES = ('input-manifest.json', 'project.json', 'controlled-request.json',
                  'device.cmd', 'initialization-contract.json', 'numerical-method.json')
RUNTIME_FILES = ('operating_transient_2d.py', 'two_dimensional.py', 'native_transient_clock.py',
                 'operating_metrics_2d.py', 'legacy-circuit-metrics.py')
OUTPUTS = ('circuit.plt', 'access_device.plt', 'initial_access_des.tdr',
           'final_access_des.tdr', 'transient_des.log')
BASE_TIMING = {'schema','timing_id','time_unit','simulation_window_s','write_end_s',
    'precharge_time_s','hold_window_s','read_window_s','source_epoch_s',
    'native_observation_window_s','mathematical_source_window_s'}
EXTRA_TIMING = {'origin','selection_provenance','write_rise_window_s','write_fall_window_s',
    'precharge_transition_window_s','driver_isolate_s','read_rise_window_s',
    'read_fall_window_s','charge_window_s','voltage_levels_V','segments'}
STEP_FIELDS = {'start_s','end_s','initial_step_s','min_step_s','max_step_s','increment','decrement','time_integrator'}
FIXED_VOLTAGES = dict(gate_low_V=-.5, write0_V=0., write1_V=1.2,
    precharge_V=.6, plate_V=.6, neutral_sn_V=.6, body_V=0.)
REQUEST_FIELDS = {'schema','kind','dimension','gate_top_depth_nm','sn_junction_depth_nm',
    'variant','stored_bit','source_case','d2_source_run','effective_width_nm',
    'a0_template_project','operation_timing_file','operation_timing_sha256','operation_evidence_files'}


def require(ok, message):
    if not ok: raise ValueError('2D explicit operation: '+message)


def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
def obj(raw):
    value=json.loads(raw.decode('utf-8'))
    require(isinstance(value,dict),'expected JSON object')
    return value
def number(value):
    try: return type(value) in (int,float) and math.isfinite(value)
    except (ValueError,OverflowError): return False
def digest_ok(value): return isinstance(value,str) and re.fullmatch(r'[a-f0-9]{64}',value) is not None
def plain_name(value): return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',value) is not None
def source_name(value): return re.split(r'[\\/]',value.rstrip('/\\'))[-1]
def literal(value):
    require(number(value),'nonfinite native numeric literal')
    return format(value,'.17g')


def local_module(name, expected=None):
    path=Path(__file__).with_name(name)
    if name=='operating_metrics_2d.py' and not path.exists(): path=path.parent.parent/'data'/name
    require(path.is_file() and not path.is_symlink(),'missing fixed local module '+name)
    if expected is not None: require(sha(path.read_bytes())==expected,'fixed implementation differs: '+name)
    spec=importlib.util.spec_from_file_location('_explicit_operation_'+name.replace('.','_'),str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def metrics_api(): return local_module('operating_metrics_2d.py',METRICS_SHA)


def validate_request(request):
    require(isinstance(request,dict) and set(request)==REQUEST_FIELDS,'r11 requires its exact explicit fields')
    require(request['schema']==REQUEST_SCHEMA and request['kind']=='transient'
            and request['source_case']=='A0' and request['variant']=='main','only explicit-operation main A0 is supported')
    for key,value in (('dimension',2),('gate_top_depth_nm',80),('sn_junction_depth_nm',87),('effective_width_nm',20)):
        require(type(request[key]) is int and request[key]==value,'original D2 geometry/width differs: '+key)
    require(type(request['stored_bit']) is int and request['stored_bit'] in (0,1),'bit must be integer 0 or 1')
    for key in ('d2_source_run','a0_template_project','operation_timing_file'):
        require(isinstance(request[key],str) and request[key].strip(),'missing explicit path: '+key)
    require(source_name(request['d2_source_run'])==D2_RUN and source_name(request['a0_template_project'])==TEMPLATE_RUN,
            'original D2 and original small A0 template identities differ')
    require(digest_ok(request['operation_timing_sha256']),'explicit timing bytes SHA required')
    refs=request['operation_evidence_files']
    require(isinstance(refs,dict) and all(plain_name(k) and isinstance(v,str) and v.strip() for k,v in refs.items()),
            'selection evidence must be named explicit data files')
    return json.loads(encoded(request).decode('utf-8'))


def role_id(request): return 'B2D-A0-operating-r1-main-b'+str(validate_request(request)['stored_bit'])


def pair(timing,name):
    value=timing[name]
    require(isinstance(value,list) and len(value)==2 and all(number(x) for x in value)
            and 0<=value[0]<value[1],'finite physical second window required: '+name)
    return value


def validate_timing(timing):
    require(isinstance(timing,dict) and set(timing)==BASE_TIMING|EXTRA_TIMING,'complete closed operation timing contract required')
    timing=metrics_api().validate_timing(timing)
    require(timing['origin'] in ('prescribed_input','UNIT_FIXTURE_NOT_NATIVE'),'unknown timing origin')
    provenance=timing['selection_provenance']
    require(isinstance(provenance,dict) and set(provenance)=={'description','references'}
            and isinstance(provenance['description'],str) and provenance['description'].strip()
            and isinstance(provenance['references'],dict),'explicit selection provenance required')
    require(all(plain_name(k) and digest_ok(v) for k,v in provenance['references'].items()),'invalid selection evidence identity')
    require(timing['origin']=='UNIT_FIXTURE_NOT_NATIVE' or provenance['references'],
            'prescribed operation needs actual frozen selection evidence references, not an approval flag')
    levels=timing['voltage_levels_V']
    require(isinstance(levels,dict) and set(levels)==set(FIXED_VOLTAGES)|{'gate_high_V'}
            and all(number(v) for v in levels.values()),'explicit voltage levels including gate_high_V required')
    require(all(levels[k]==v for k,v in FIXED_VOLTAGES.items()) and levels['gate_high_V']>levels['gate_low_V'],
            'fixed original voltage changed or gate high is not above gate low')
    full=pair(timing,'simulation_window_s');wr=pair(timing,'write_rise_window_s');wf=pair(timing,'write_fall_window_s')
    pc=pair(timing,'precharge_transition_window_s');rr=pair(timing,'read_rise_window_s');rf=pair(timing,'read_fall_window_s')
    charge=pair(timing,'charge_window_s');hold=timing['hold_window_s'];read=timing['read_window_s'];obs=timing['native_observation_window_s']
    require(number(timing['driver_isolate_s']) and 0<wr[0]<wr[1]<timing['write_end_s']==wf[0]<wf[1]
            and wf[1]<=pc[0]<pc[1]<timing['precharge_time_s']==timing['driver_isolate_s']==hold[0],
            'write/precharge/isolation phase semantics differ')
    require(hold[1]<rr[0]<rr[1]<=read[0]<read[1]<=rf[0]<rf[1]<full[1],
            'read scoring window must be inside the actual read WL plateau and full recovery window')
    require(hold[0]<=charge[0]<=obs[0]<obs[1]<=charge[1]<=hold[1],
            'explicit charge window must contain native observation within pre-read hold')
    segments=timing['segments'];require(isinstance(segments,list) and segments,'explicit complete segment table required')
    ends=[]
    for i,seg in enumerate(segments):
        require(isinstance(seg,dict) and set(seg)==STEP_FIELDS,'segment needs each physical boundary and step control')
        require(all(number(v) for k,v in seg.items() if k!='time_integrator') and seg['time_integrator']=='BE',
                'finite explicit BE step policy required')
        require(0<=seg['start_s']<seg['end_s'] and 0<seg['min_step_s']<=seg['initial_step_s']<=seg['max_step_s'],
                'invalid segment time or step ordering')
        require(seg['min_step_s']==1e-18 and seg['increment']==1.3 and seg['decrement']==2,
                'original MinStep/Increment/Decrement controls must remain explicit and unchanged')
        require(seg['start_s']==(full[0] if i==0 else segments[i-1]['end_s']),'segment gap, overlap or time remapping')
        if obs[0]<=seg['start_s'] and seg['end_s']<=obs[1]:
            require(seg['max_step_s']<=4e-14,'original source observation 0.04ps maximum step cannot be enlarged')
        ends.append(seg['start_s'])
    ends.append(segments[-1]['end_s'])
    require(ends[-1]==full[1],'all physical simulation time must be covered')
    events=[timing['write_end_s'],timing['precharge_time_s'],timing['driver_isolate_s']]
    for key in ('write_rise_window_s','write_fall_window_s','precharge_transition_window_s','hold_window_s',
                'read_rise_window_s','read_fall_window_s','read_window_s','charge_window_s','native_observation_window_s'):
        events.extend(timing[key])
    require(set(events)<=set(ends),'every native phase/evaluation boundary must be an actual Solve endpoint')
    return timing


def rendered_timing(timing):
    timing=validate_timing(timing);values={}
    def walk(value,path):
        if number(value): values[path]=dict(value=value,native_literal=literal(value))
        elif isinstance(value,dict):
            for key,item in value.items():walk(item,path+'/'+key)
        elif isinstance(value,list):
            for i,item in enumerate(value):walk(item,path+'/'+str(i))
    walk(timing,'')
    return dict(schema='dram-see-v4-2d-rendered-operation-timing-r1',timing_id=timing['timing_id'],
        numeric_literals=values,seconds_untransformed=True,no_resampling=True,
        read_scoring_window_s=timing['read_window_s'],read_WL_plateau_s=[timing['read_rise_window_s'][1],timing['read_fall_window_s'][0]],
        native_observation_window_s=timing['native_observation_window_s'],mathematical_source_window_s=timing['mathematical_source_window_s'],
        source_epoch_is_not_automatically_a_native_segment_boundary=True)


def render(original_a0_deck,bit,timing):
    require(type(bit) is int and bit in (0,1),'stored bit must be integer 0 or 1')
    require(isinstance(original_a0_deck,bytes) and sha(original_a0_deck)==TEMPLATE_SHA,'only original validated r2 bit0 template bytes')
    t=validate_timing(timing);text=original_a0_deck.decode('utf-8');levels=t['voltage_levels_V'];low=levels['gate_low_V'];high=levels['gate_high_V']
    wr,wf,rr,rf=(t[n] for n in ('write_rise_window_s','write_fall_window_s','read_rise_window_s','read_fall_window_s'))
    full=t['simulation_window_s'];pc=t['precharge_transition_window_s']
    gate=[(full[0],low),(wr[0],low),(wr[1],high),(wf[0],high),(wf[1],low),(rr[0],low),(rr[1],high),(rf[0],high),(rf[1],low),(full[1],low)]
    write=levels['write1_V'] if bit else levels['write0_V']
    drive=[(full[0],write),(pc[0],write),(pc[1],levels['precharge_V']),(full[1],levels['precharge_V'])]
    prefix,solve=text.split('Solve {\n',1)
    for name,node,points in (('vwl','wl',gate),('vdrive','drive',drive)):
        line=' Vsource_pset '+name+' ('+node+' 0) {pwl=('+' '.join(literal(x)+' '+literal(v) for x,v in points)+')}\n'
        prefix,count=re.subn(r'^ Vsource_pset '+name+r' \('+node+r' 0\) \{pwl=\([^\n]*\n',lambda m:line,prefix,flags=re.M)
        require(count==1,'template PWL location differs')
    require(prefix.count(' PrintLinearSolver\n')==1,'template diagnostic insertion location differs')
    prefix=prefix.replace(' PrintLinearSolver\n',' PrintLinearSolver\n CNormPrint\n PrintRhsPerEquation\n')
    initial=solve.split(' Transient(',1)[0]
    require(initial==' Coupled(Iterations=100) {Poisson}\n Coupled(Iterations=100) {Poisson Electron Hole Contact Circuit}\n Plot(FilePrefix="initial")\n Unset(sn)\n','original common initialization differs')
    output=prefix+'Solve {\n'+initial
    for i,seg in enumerate(t['segments']):
        if seg['start_s']==t['driver_isolate_s']: output+=' Set(rdrive."resistance"=1e15)\n'
        values=(('InitialTime','start_s'),('FinalTime','end_s'),('InitialStep','initial_step_s'),('MinStep','min_step_s'),('MaxStep','max_step_s'),('Increment','increment'),('Decrement','decrement'))
        output+=' Transient('+' '.join(name+'='+literal(seg[key]) for name,key in values)+') {\n  Coupled {Poisson Electron Hole Contact Circuit}\n'
        if t['native_observation_window_s'][0]<=seg['start_s'] and seg['end_s']<=t['native_observation_window_s'][1]:
            output+='  Plot(FilePrefix="source_window" Time=(Range=('+literal(seg['start_s'])+' '+literal(seg['end_s'])+')) NoOverwrite)\n'
        if i==len(t['segments'])-1:output+='  Plot(FilePrefix="final" Time=('+literal(full[1])+'))\n'
        output+=' }\n'
    return (output+'}\n').encode('utf-8')


def verify_template(reader,prefix='operation-template/'):
    manifest_raw=reader.read(prefix+'input-manifest.json')
    require(sha(manifest_raw)==TEMPLATE_MANIFEST_SHA,'original template input manifest differs')
    manifest=obj(manifest_raw)
    require(manifest.get('run_id')==TEMPLATE_RUN and manifest.get('role_id')=='B2D-A0-main-b0','template must retain its original role/run')
    for name in TEMPLATE_FILES[1:]:
        require(reader.digest(prefix+name)==manifest['files_sha256'][name],'small template member changed: '+name)
    require(reader.digest(prefix+'device.cmd')==TEMPLATE_SHA,'original template deck changed')
    for name in local_module('two_dimensional.py',D2_SHA).SHARED_INPUTS+('dimensional-contract.json',):
        require(reader.digest(name)==manifest['files_sha256'][name],'new input does not retain template original physics/width: '+name)
    return {name:reader.read(prefix+name) for name in TEMPLATE_FILES}


def source_spec(bit,timing_sha,width_sha,physics_sha):
    return dict(schema='dram-see-v4-2d-operating-control-source-spec-r1',role='CONTROL',source_case='A0',
        source_configured=False,structural_source_absence=True,dimension=2,stored_bit=bit,numerical_variant='main',
        operation_timing_sha256=timing_sha,dimensional_contract_sha256=width_sha,physics_manifest_sha256=physics_sha,
        particle_source_qualified=False)


def payload(template,shared,cfg,request,timing_raw,selection_files):
    """Pure small payload; excludes project/context/manifests and native files."""
    request=validate_request(request);t=validate_timing(obj(timing_raw));timing_sha=sha(timing_raw)
    require(timing_sha==request['operation_timing_sha256'],'explicit timing file bytes differ')
    require(set(selection_files)==set(t['selection_provenance']['references']), 'complete selection evidence bytes required')
    for name,digest in t['selection_provenance']['references'].items(): require(sha(selection_files[name])==digest,'selection evidence bytes differ: '+name)
    bit=request['stored_bit'];files={'operation-template/'+n:template[n] for n in TEMPLATE_FILES}
    files.update({'operation-selection/'+n:raw for n,raw in selection_files.items()})
    files['operation-timing.json']=timing_raw;files['rendered-operation-timing.json']=encoded(rendered_timing(t))
    files['device.cmd']=render(template['device.cmd'],bit,t)
    files['initialization-contract.json']=template['initialization-contract.json']
    files['source-spec.json']=encoded(source_spec(bit,timing_sha,sha(shared['dimensional-contract.json']),sha(shared['physics-manifest.json'])))
    files['source-contract.json']=encoded(dict(schema='dram-see-v4-2d-operating-structural-control-r1',
        source_configured=False,source_dimension=2,structural_source_absence=True,source_field_absence='structural absence, never measured zero',
        operation_timing_sha256=timing_sha,native_observation_window_s=t['native_observation_window_s'],
        mathematical_source_window_s=t['mathematical_source_window_s'],source_epoch_s=t['source_epoch_s'],
        native_source_qualified=False,native_A0_functionality_qualified=False))
    files['functional-criteria.json']=encoded(dict(schema='dram-see-v4-2d-operating-functional-criteria-r1',
        operation_timing_sha256=timing_sha,implementation_sha256=METRICS_SHA,criteria=metrics_api().criteria(),thresholds_changed=False))
    files['numerical-method.json']=encoded(dict(schema='dram-see-v4-2d-operating-numerics-r1',
        original_numerical_method=obj(template['numerical-method.json']),original_numerical_sha256=sha(template['numerical-method.json']),
        diagnostic_output=['CNormPrint','PrintRhsPerEquation'],official_document='Sentaurus Device User Guide W-2024.09',official_pages=[228,229],
        algorithm_or_convergence_criteria_changed=False,explicit_operation_timing_sha256=timing_sha,
        actual_native_diagnostic_syntax_verified=False))
    files['parameter-binding.json']=encoded(dict(schema='dram-see-v4-active-parameters-r1',base_file='physics.par',base_sha256=sha(shared['physics.par']),
        source_file=None,source_sha256=None,source_physics_file=None,source_physics_sha256=None,
        active_file='physics.par',active_sha256=sha(shared['physics.par']),aggregation='base_only'))
    bound={n:sha(raw) for n,raw in files.items()}
    binding=dict(schema='dram-see-v4-2d-operating-transient-binding-r1',branch_id=BRANCH,stored_bit=bit,
        producer_run_id=D2_RUN,d2_source_binding_sha256=cfg['d2_source_binding_sha256'],
        template_run_id=TEMPLATE_RUN,template_manifest_sha256=TEMPLATE_MANIFEST_SHA,
        operation_timing_sha256=timing_sha,gate_high_V=t['voltage_levels_V']['gate_high_V'],
        dimensional_contract_sha256=sha(shared['dimensional-contract.json']),verifier_sha256=sha(Path(__file__).read_bytes()),
        clock_sha256=CLOCK_SHA,metrics_sha256=METRICS_SHA,legacy_helper_sha256=LEGACY_SHA,
        files_sha256=bound,physics_cards_unchanged=True,mesh_unchanged=True,
        native_run_completed=False,native_A0_functionality_qualified=False,scientific_evidence_verified=False,training_admitted=False)
    files['operating-transient-binding.json']=encoded(binding)
    return files


def role_contract(cfg,timing):
    return dict(schema='dram-see-v4-2d-operating-control-role-r1',role=cfg['role_id'],dimension=2,case='A0',
        stored_bit=cfg['stored_bit'],numerical_variant='main',source_configured=False,source_dimension=2,
        effective_width_nm=20,area_factor=.02,Cstore_fF=20,Cbl_fF=200,
        gate_high_V=timing['voltage_levels_V']['gate_high_V'],operation_timing_sha256=cfg['operation_timing_sha256'],
        operating_transient_binding_sha256=cfg['operating_transient_binding_sha256'],
        dimensional_contract_sha256=cfg['dimensional_contract_sha256'],producer_run_id=D2_RUN,mesh_sha256=cfg['mesh_sha256'],
        actual_read_WL_plateau_s=[timing['read_rise_window_s'][1],timing['read_fall_window_s'][0]],
        read_scoring_window_s=timing['read_window_s'],source_observation_window_s=timing['native_observation_window_s'],
        full_physical_window_s=timing['simulation_window_s'],native_syntax_verified=False,native_A0_functionality_qualified=False,
        response_admission='Both actual bits, complete original clocks, original five criteria/KCL and separate field/refinement evidence required')


def verify_frozen(reader,cfg):
    D=local_module('two_dimensional.py',D2_SHA);result=D.verify_frozen(reader,cfg)
    require(cfg.get('operating_transient_branch')==BRANCH and cfg.get('producer_run_id')==D2_RUN,'explicit operation/D2 branch required')
    request=validate_request(obj(reader.read('controlled-request.json')))
    require(cfg.get('role_id')==role_id(request) and cfg.get('stored_bit')==request['stored_bit']
            and cfg.get('numerical_variant')=='main','role/bit/variant differs')
    raw=reader.read('operation-timing.json');t=validate_timing(obj(raw))
    require(cfg.get('operation_timing_sha256')==sha(raw)==request['operation_timing_sha256'],'timing identity differs')
    require(cfg.get('gate_high_V')==t['voltage_levels_V']['gate_high_V']
            and set(request['operation_evidence_files'])==set(t['selection_provenance']['references']),
            'gate high or selection reference inventory differs')
    template=verify_template(reader)
    shared={n:reader.read(n) for n in D.SHARED_INPUTS+('dimensional-contract.json',)}
    selections={n:reader.read('operation-selection/'+n) for n in t['selection_provenance']['references']}
    expected=payload(template,shared,cfg,request,raw,selections)
    for name,value in expected.items(): require(reader.read(name)==value,'deterministic input differs: '+name)
    require(cfg.get('operating_transient_binding_sha256')==reader.digest('operating-transient-binding.json')
            and obj(reader.read('role-contract.json'))==role_contract(cfg,t),'operation binding or role differs')
    for name,digest in (('operating_transient_2d.py',sha(Path(__file__).read_bytes())),('two_dimensional.py',D2_SHA),
                        ('native_transient_clock.py',CLOCK_SHA),('operating_metrics_2d.py',METRICS_SHA),('legacy-circuit-metrics.py',LEGACY_SHA)):
        require(reader.digest(name)==digest,'fixed runtime implementation differs: '+name)
    local_module('native_transient_clock.py',CLOCK_SHA)._deck(reader.read('device.cmd'))
    result.update(operation_timing=t,operating_binding=obj(expected['operating-transient-binding.json']),
        source_spec=obj(expected['source-spec.json']),role_contract=role_contract(cfg,t))
    return result


def admit(project,spec,runner_sha,bridge):
    project=Path(project)
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve()) and not (project/'SYNTHETIC_NOT_NATIVE').exists(),
            'unit fixture cannot be submitted')
    cfg=spec['s2_geometry'];D=local_module('two_dimensional.py',D2_SHA)
    require(cfg.get('schema')==bridge.GEOMETRY_SCHEMA and cfg.get('mode')=='reuse'
            and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True and spec.get('execution_enabled') is True,
            'native original-runner reuse context differs')
    request=validate_request(obj((project/'controlled-request.json').read_bytes()))
    require(spec.get('role')==cfg.get('role_id')==role_id(request) and cfg.get('run_id')!=D2_RUN
            and plain_name(cfg.get('run_id')) and spec.get('native_threads')==spec.get('native_cores')==1
            and spec.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(OUTPUTS))], 'role/serial original-step contract differs')
    bridge.geometry_context(project,cfg,runner_sha);hashes=bridge.geometry_input_hashes(project)
    required=set(D.SHARED_INPUTS)|set(RUNTIME_FILES)|{D.PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}|{
        'project.json','case_contract.py','geometry_bridge.py','mesh_resource_guard.py','controlled-request.json','resource-policy.json','task-authorization.json',
        'role-contract.json','device.cmd','cell_msh.tdr','cell_msh.log','d2-source-binding.json','dimensional-contract.json',
        'operation-timing.json','rendered-operation-timing.json','operating-transient-binding.json','initialization-contract.json',
        'source-spec.json','source-contract.json','functional-criteria.json','numerical-method.json','parameter-binding.json'}|{'operation-template/'+n for n in TEMPLATE_FILES}
    require(required<=set(hashes),'mandatory operation/D2 source evidence missing')
    for name,digest in hashes.items():require(D.file_sha(bridge.geometry_path(project,name))==digest,'frozen operation input differs: '+name)
    manifest=obj((project/'input-manifest.json').read_bytes())
    require(manifest.get('run_id')==cfg['run_id'] and manifest.get('role_id')==cfg['role_id'],'input manifest identity differs')
    result=verify_frozen(D.FolderReader(project),cfg)
    require(result['operation_timing']['origin']=='prescribed_input','fixture timing cannot be submitted')
    require(set(request['operation_evidence_files'])==set(result['operation_timing']['selection_provenance']['references'])
            and {'operation-selection/'+n for n in request['operation_evidence_files']}<=set(hashes),'selection evidence inventory differs')
    require(obj((project/'resource-policy.json').read_bytes())==dict(schema='dram-see-v4-actual-resource-policy-r1',role=cfg['role_id'],
        observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None),'only actual resource observations are allowed')
    return cfg


def prepare(request,run_id,runner=None,output=None):
    """Prepare exactly one future explicitly selected A0 input; never launch it."""
    request=validate_request(request);D=local_module('two_dimensional.py',D2_SHA)
    C=local_module('case_contract.py');bridge=local_module('geometry_bridge.py')
    require(getattr(C,'SCHEMA_2D_OPERATION',None)==REQUEST_SCHEMA and hasattr(bridge,'geometry_operating_transient_module'),
            'r11 dispatch patch is not integrated; no input directory created')
    require(plain_name(run_id) and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id,'new nonfixture run ID required')
    here=Path(__file__).resolve().parent;root=here.parents[3]
    runner=Path(runner or root/'scripts/tcad.py').resolve()
    require(runner==(root/'scripts/tcad.py').resolve() and runner.is_file(),'use original scripts/tcad.py')
    allowed=(root/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/operating-transient-implementation-r1').resolve()
    target=Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target),'new allowed output directory required')
    raw=Path(request['operation_timing_file']).read_bytes();t=validate_timing(obj(raw))
    require(t['origin']=='prescribed_input' and sha(raw)==request['operation_timing_sha256'],'actual explicit operation selection required')
    require(set(request['operation_evidence_files'])==set(t['selection_provenance']['references']),'selection evidence file mapping differs')
    selected={n:Path(p).read_bytes() for n,p in request['operation_evidence_files'].items()}
    request=dict(request);request['d2_source_run']=str(Path(request['d2_source_run']).resolve())
    role=role_id(request);runner_sha=D.file_sha(runner)
    cfg=dict(schema=bridge.GEOMETRY_SCHEMA,mode='reuse',dimension_branch=D.BRANCH,operating_transient_branch=BRANCH,
        role_id=role,run_id=run_id,producer_run_id=D2_RUN,stored_bit=request['stored_bit'],execution_enabled=True,synthetic=False,
        source_run_directory=request['d2_source_run'],source_dimension=2,effective_width_nm=20,area_factor=.02,
        size_id='gate-top-depth-80nm',sn_junction_depth_nm=87,numerical_variant='main',parameter_id='gate-top-depth-80nm__sn-junction-depth-87nm')
    bundle=bridge.geometry_source_bundle(target,cfg)
    cfg.update(source_manifest_sha256=bundle['manifest_sha256'],source_archive_sha256=bundle['archive_sha256'],mesh_sha256=bundle['mesh_sha256'],
        geometry_validation_sha256=bundle['geometry_validation_sha256'],d2_source_binding_sha256=bundle['d2_source_binding_sha256'])
    files=dict(bundle['producer_inputs']);files.update(bundle['generated_files'])
    files['dimensional-contract.json']=encoded(D.dimensional_contract(bundle['d2_binding']))
    cfg['dimensional_contract_sha256']=sha(files['dimensional-contract.json']);cfg['operation_timing_sha256']=sha(raw)
    cfg['gate_high_V']=t['voltage_levels_V']['gate_high_V']
    template_dir=Path(request['a0_template_project']).resolve()
    require(template_dir.name==TEMPLATE_RUN and not template_dir.is_symlink(),'original small A0 template directory differs')
    template={n:(template_dir/n).read_bytes() for n in TEMPLATE_FILES}
    # Verify template against exact original manifest and current unchanged shared bytes before any output write.
    small={'operation-template/'+n:v for n,v in template.items()};small.update(files)
    class SmallReader:
        def read(self,name):return small[name]
        def digest(self,name):return sha(small[name])
    verify_template(SmallReader())
    files.update(payload(template,files,cfg,request,raw,selected))
    cfg['operating_transient_binding_sha256']=sha(files['operating-transient-binding.json'])
    files['role-contract.json']=encoded(role_contract(cfg,t))
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-'+role.lower(),role=role,execution_enabled=True,
        runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(OUTPUTS))])
    files.update({'project.json':encoded(spec),'controlled-request.json':encoded(request),
        'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',role=role,observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',source='current_user_instruction',synthetic=False,role_ids=[role],
            instruction='在原D2/20nm/20与200fF上按显式物理时序运行二维A0；原runner、owner、共享锁、串行单核单线程，完整保存原生结果，不设项目资源额度。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',plan_sha256=D.file_sha(root/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md')))})
    for name in ('geometry_bridge.py','mesh_resource_guard.py','case_contract.py','operating_transient_2d.py','two_dimensional.py','native_transient_clock.py'):
        files[name]=(here/name).read_bytes()
    files['operating_metrics_2d.py']=(here.parent/'data/operating_metrics_2d.py').read_bytes()
    files['legacy-circuit-metrics.py']=(here.parents[1]/'s2-inputs-r1/metrics.py').read_bytes()
    files['generator-prepare_case.py']=(here/'prepare_case.py').read_bytes()
    files['provenance.json']=encoded(dict(schema='dram-see-v4-2d-operating-input-provenance-r1',run_id=run_id,role=role,
        producer_run_id=D2_RUN,complete_original_D2_archive_retained=True,template_run_id=TEMPLATE_RUN,
        full_old_A0_result_archive_copied=False,operation_timing_sha256=sha(raw),gate_high_V=t['voltage_levels_V']['gate_high_V'],
        new_time_or_voltage_selected_by_generator=False,source_configured=False,physics_cards_unchanged=True,
        mesh_unchanged=True,neutral_common_initialization=True,target_bit_preset=False,thresholds_changed=False,
        native_run_completed=False,native_A0_functionality_qualified=False,training_admitted=False))
    hashes={name:sha(value) for name,value in files.items()}
    for name,digest in bundle['exports'].items():
        require(name not in hashes or hashes[name]==digest,'original D2 import collision: '+name);hashes[name]=digest
    files['input-manifest.json']=encoded(dict(schema='dram-see-v4-continuous-inputs-r1',role_id=role,run_id=run_id,files_sha256=hashes))
    files['execution-context.json']=encoded(dict(schema='dram-see-v4-continuous-run-context-r1',run_id=run_id,role_id=role,producer_run_id=D2_RUN,
        synthetic=False,expected_runner_sha256=runner_sha,input_manifest_sha256=sha(files['input-manifest.json']),authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True,exist_ok=False)
    for name,value in files.items():bridge.geometry_write(target/name,value)
    bridge.geometry_stage_reuse(target,cfg);bridge.geometry_admit(target,spec,runner_sha)
    return dict(project=str(target),run_id=run_id,role_id=role,source_run_id=D2_RUN,mesh_sha256=cfg['mesh_sha256'],
        operation_timing_sha256=sha(raw),operating_transient_binding_sha256=cfg['operating_transient_binding_sha256'],
        input_manifest_sha256=sha(files['input-manifest.json']),expected_runner_sha256=runner_sha,
        gate_high_V=t['voltage_levels_V']['gate_high_V'],native_submissions=0,native_run_completed=False,native_A0_functionality_qualified=False)
