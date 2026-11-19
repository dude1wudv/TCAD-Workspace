"""Explicit gate voltage on the unchanged original-D2 static operating paths.

Python 3.6 stdlib. No scheduler or native launcher. The old r10 module stays
byte-for-byte fixed; only its two settle gate goals become explicit inputs.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import tarfile

REQUEST_SCHEMA = 'dram-see-v4-controlled-device-request-r14'
BRANCH = 'dram-see-v4-operating-voltage-dc-2d-r1'
ROLE = 'B2D-OPERATING-VOLTAGE-DC-main'
BASE_SHA = '1c550f1bf427a2195843b530789d172d8e621ed59f2f6eef6dfac295aa95803e'
D2_SHA = 'c09b52ad56fcdf7e22dfb70ce750b04fd9fa383e1bda8a68ac9121ed768055cd'
D2_RUN = '20261017T051217Z-v4-continuous-b1-d2-r8'
ORIGINAL_DECK_SHA = 'ed383467d7585abc64f918915a575cc2af5dba9154f5ae856af11e78b57c3e38'
RUNTIME_FILES = ('operating_voltage_dc_2d.py','operating_dc_2d.py','two_dimensional.py')
PREFIXES = ('','settle_write_','write_to_108_','write_above_108_','settle_read_','read_to_088_','read_below_088_')
OUTPUTS = tuple(p+'operating_des.plt' for p in PREFIXES)+('operating_final_des.tdr','operating_des.log')
REQUEST_FIELDS = {'schema','kind','dimension','gate_top_depth_nm','sn_junction_depth_nm','variant',
    'd2_source_run','effective_width_nm','gate_V','write_BL_V','body_V','Cstore_fF','Cbl_fF','max_source_step_V','paths'}


def require(ok,message):
    if not ok: raise ValueError('2D explicit-gate DC: '+message)
def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
def obj(raw):
    result=json.loads(raw.decode('utf-8'));require(isinstance(result,dict),'JSON object required');return result
def number(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except (OverflowError,ValueError):return False
def source_name(value): return re.split(r'[\\/]',value.rstrip('/\\'))[-1]


def local_module(name,expected=None):
    path=Path(__file__).with_name(name)
    require(path.is_file() and not path.is_symlink(),'missing/linked fixed local module '+name)
    raw=path.read_bytes()
    if expected is not None: require(sha(raw)==expected,'fixed implementation changed: '+name)
    spec=importlib.util.spec_from_file_location('_voltage_dc_fixed_'+name.replace('.','_'),str(path))
    result=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),result.__dict__)
    return result


def base_api():
    result=local_module('operating_dc_2d.py',BASE_SHA)
    require(result.D2_SHA==D2_SHA and result.D2_RUN==D2_RUN and result.ORIGINAL_DECK_SHA==ORIGINAL_DECK_SHA
            and result.PREFIXES==PREFIXES and result.OUTPUTS==OUTPUTS,'fixed original DC interface changed')
    return result


def gate_value(value):
    require(number(value),'gate_V must be an explicit finite numeric voltage; no default or boolean')
    return value


def gate_literal(value): return format(gate_value(value),'.17g')


def validate_request(request):
    require(isinstance(request,dict) and set(request)==REQUEST_FIELDS,'r14 requires all explicit DC fields, including gate_V')
    require(request['schema']==REQUEST_SCHEMA and request['kind']=='operating_dc' and request['variant']=='main'
            and request['paths']=='write0p6_1p12_read1p08_0p8-r1','unknown explicit-gate static path request')
    for key,value in (('dimension',2),('gate_top_depth_nm',80),('sn_junction_depth_nm',87),('effective_width_nm',20)):
        require(type(request[key]) is int and request[key]==value,'same original D2 geometry/width required: '+key)
    for key,value in (('write_BL_V',1.2),('body_V',0.),('Cstore_fF',20.),('Cbl_fF',200.),('max_source_step_V',.01)):
        require(number(request[key]) and request[key]==value,'unchanged original physical/path value required: '+key)
    gate_value(request['gate_V'])
    require(isinstance(request['d2_source_run'],str) and request['d2_source_run'].strip()
            and source_name(request['d2_source_run'])==D2_RUN,'the same actual D2-r8 source is required')
    return obj(encoded(request))


def role_id(request): validate_request(request);return ROLE


def render(original,gate_V):
    """Only two exact fixed gate-goal tokens change; the original r10 is intact."""
    base=base_api();old=base.render(original);token=b'Goal {Name="gate" Voltage=1.8}'
    require(old.count(token)==2,'fixed original settle gate goals differ')
    return old.replace(token,('Goal {Name="gate" Voltage='+gate_literal(gate_V)+'}').encode('ascii'))


def paths_contract(gate_V):
    gate_V=gate_value(gate_V);value=base_api().paths_contract()
    value.update(schema='dram-see-v4-operating-voltage-dc-2d-paths-r1',gate_V=gate_V,
        gate_voltage_origin='explicit controlled request; not selected by this implementation',
        gate_goal_literal=gate_literal(gate_V),gate_has_default=False,
        original_path_implementation_sha256=BASE_SHA)
    for preload in value['preload']:
        require(preload['gate_V']==[0.,1.8],'fixed original gate prebias path differs')
        preload['gate_V']=[0.,gate_V]
    return value


def numerical_contract(original): return base_api().numerical_contract(original)
def source_spec(physics_sha,width_sha): return base_api().source_spec(physics_sha,width_sha)


def binding(reader,gate_V):
    return dict(schema='dram-see-v4-operating-voltage-dc-2d-binding-r1',operating_voltage_branch=BRANCH,
        producer_run_id=D2_RUN,gate_V=gate_value(gate_V),gate_goal_literal=gate_literal(gate_V),
        controlled_request_sha256=reader.digest('controlled-request.json'),
        d2_source_binding_sha256=reader.digest('d2-source-binding.json'),
        original_device_sha256=reader.digest('original-d2-device.cmd'),
        original_math_sha256=sha(base_api().block(reader.read('original-d2-device.cmd'),'Math')),
        device_sha256=reader.digest('device.cmd'),paths_sha256=reader.digest('operating-paths.json'),
        numerical_sha256=reader.digest('numerical-method.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        verifier_sha256=sha(Path(__file__).read_bytes()),original_dc_implementation_sha256=BASE_SHA,
        native_run_completed=False,is_A0=False)


def verify_operating_inputs(reader,cfg,original):
    """New bytes/identity layer; full D2 verification is performed by its caller."""
    require(cfg.get('operating_voltage_branch')==BRANCH and 'operating_branch' not in cfg
            and cfg.get('producer_run_id')==D2_RUN and cfg.get('role_id')==ROLE,
            'explicit new DC branch/source/role required; old r10 is not relabelled')
    request=validate_request(obj(reader.read('controlled-request.json')))
    require(number(cfg.get('gate_V')) and cfg['gate_V']==request['gate_V'],'gate voltage differs between original request and project')
    for name,digest in (('operating_voltage_dc_2d.py',sha(Path(__file__).read_bytes())),
                        ('operating_dc_2d.py',BASE_SHA),('two_dimensional.py',D2_SHA)):
        require(reader.digest(name)==digest,'archived fixed runtime changed: '+name)
    require(reader.read('original-d2-device.cmd')==original and sha(original)==ORIGINAL_DECK_SHA,
            'same original independent-device deck required')
    gate=request['gate_V'];paths=paths_contract(gate)
    require(reader.read('device.cmd')==render(original,gate),'actual deck differs from the explicit gate and original paths')
    require(obj(reader.read('operating-paths.json'))==paths
            and obj(reader.read('numerical-method.json'))==numerical_contract(original),
            'original path/numerical algorithm differs')
    require(obj(reader.read('source-spec.json'))==source_spec(reader.digest('physics-manifest.json'),reader.digest('dimensional-contract.json')),
            'diagnostic source absence differs')
    expected=binding(reader,gate)
    require(obj(reader.read('operating-voltage-dc-binding.json'))==expected
            and cfg.get('operating_voltage_binding_sha256')==reader.digest('operating-voltage-dc-binding.json'),
            'frozen explicit-gate binding differs')
    return dict(operating_voltage_binding=expected,operating_paths=paths,controlled_request=request,gate_V=gate)


def verify_frozen(reader,cfg):
    D=local_module('two_dimensional.py',D2_SHA)
    result=D.verify_frozen(reader,cfg)
    original=base_api().original_deck(reader,D)
    result.update(verify_operating_inputs(reader,cfg,original))
    return result


def role_contract(cfg):
    return dict(schema='dram-see-v4-operating-voltage-dc-2d-role-r1',role=ROLE,dimension=2,
        case='OPERATING_DC_DIAGNOSTIC',execution_enabled=True,stored_bit=None,source_configured=False,
        source_dimension=2,effective_width_nm=20,area_factor=.02,gate_V=gate_value(cfg['gate_V']),
        gate_goal_literal=gate_literal(cfg['gate_V']),producer_run_id=D2_RUN,mesh_sha256=cfg['mesh_sha256'],
        dimensional_contract_sha256=cfg['dimensional_contract_sha256'],
        operating_voltage_binding_sha256=cfg['operating_voltage_binding_sha256'],
        outputs=list(OUTPUTS),is_actual_write_read=False,is_A0=False,native_syntax_verified=False,
        native_A0_functionality_qualified=False,
        outcome='Actual imposed-bias DC only; static timing estimates still require real A0 verification')


def admit(project,spec,runner_sha,bridge):
    project=Path(project);cfg=spec['s2_geometry'];D=local_module('two_dimensional.py',D2_SHA)
    require(cfg.get('schema')==bridge.GEOMETRY_SCHEMA and cfg.get('mode')=='reuse'
            and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
            and spec.get('execution_enabled') is True,'native diagnostic reuse context differs')
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve()) and not (project/'SYNTHETIC_NOT_NATIVE').exists(),
            'fixture cannot become a native diagnostic')
    request=validate_request(obj((project/'controlled-request.json').read_bytes()))
    require(cfg.get('role_id')==spec.get('role')==ROLE and cfg.get('gate_V')==request['gate_V']
            and source_name(request['d2_source_run'])==cfg.get('producer_run_id')==D2_RUN and cfg.get('run_id')!=D2_RUN
            and spec.get('native_threads')==spec.get('native_cores')==1
            and spec.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(OUTPUTS))],
            'diagnostic gate/role/source/serial steps differ')
    bridge.geometry_context(project,cfg,runner_sha);hashes=bridge.geometry_input_hashes(project)
    required=set(D.SHARED_INPUTS)|set(RUNTIME_FILES)|{D.PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}|{
        'project.json','case_contract.py','geometry_bridge.py','mesh_resource_guard.py','controlled-request.json',
        'resource-policy.json','task-authorization.json','role-contract.json','device.cmd','cell_msh.tdr','cell_msh.log',
        'd2-source-binding.json','dimensional-contract.json','original-d2-device.cmd','operating-paths.json',
        'numerical-method.json','operating-voltage-dc-binding.json','source-spec.json'}
    require(required<=set(hashes),'mandatory original explicit-gate evidence missing')
    manifest=obj((project/'input-manifest.json').read_bytes())
    require(manifest.get('run_id')==cfg['run_id'] and manifest.get('role_id')==ROLE,'input manifest identity differs')
    for name,digest in hashes.items():require(D.file_sha(bridge.geometry_path(project,name))==digest,'frozen input changed: '+name)
    verify_frozen(D.FolderReader(project),cfg)
    require(obj((project/'role-contract.json').read_bytes())==role_contract(cfg),'diagnostic role differs')
    require(obj((project/'resource-policy.json').read_bytes())==dict(schema='dram-see-v4-actual-resource-policy-r1',role=ROLE,
        observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None),'only actual resource observations are allowed')
    return cfg


class BytesReader:
    """Pure construction reader; never native evidence or source admission."""
    def __init__(self,files):self.files=files
    def read(self,name):return self.files[name]
    def digest(self,name):return sha(self.read(name))


def prepare(request,run_id,runner=None,output=None):
    """Future owner-called preparation only; never dispatches a native command."""
    request=validate_request(request);D=local_module('two_dimensional.py',D2_SHA)
    C=local_module('case_contract.py');bridge=local_module('geometry_bridge.py')
    require(getattr(C,'SCHEMA_2D_OPERATING_VOLTAGE',None)==REQUEST_SCHEMA
            and hasattr(bridge,'geometry_operating_voltage_module'),'r14 dispatch is not integrated; no input directory created')
    require(C.validate(request)==request and C.role_id(request)==ROLE,'integrated r14 request interface differs')
    require(isinstance(run_id,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',run_id)
            and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id,'new nonfixture run ID required')
    here=Path(__file__).resolve().parent;root=here.parents[3]
    runner=Path(runner or root/'scripts/tcad.py').resolve()
    require(runner==(root/'scripts/tcad.py').resolve() and runner.is_file(),'use original scripts/tcad.py')
    allowed=(root/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/operating-voltage-dc-implementation-r1').resolve()
    target=Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target),
            'new explicit-gate input directory required')
    request=dict(request);request['d2_source_run']=str(Path(request['d2_source_run']).resolve())
    runner_sha=D.file_sha(runner)
    cfg=dict(schema=bridge.GEOMETRY_SCHEMA,mode='reuse',dimension_branch=D.BRANCH,operating_voltage_branch=BRANCH,
        role_id=ROLE,run_id=run_id,producer_run_id=D2_RUN,execution_enabled=True,synthetic=False,gate_V=request['gate_V'],
        source_run_directory=request['d2_source_run'],source_dimension=2,effective_width_nm=20,area_factor=.02,
        size_id=C.size_id(80),sn_junction_depth_nm=87,numerical_variant='main',parameter_id=C.parameter_id(request))
    bundle=bridge.geometry_source_bundle(target,cfg)
    cfg.update(source_manifest_sha256=bundle['manifest_sha256'],source_archive_sha256=bundle['archive_sha256'],
        mesh_sha256=bundle['mesh_sha256'],geometry_validation_sha256=bundle['geometry_validation_sha256'],
        d2_source_binding_sha256=bundle['d2_source_binding_sha256'])
    with tarfile.open(str(bundle['archive']),'r:*') as archive:original=D.ArchiveReader(archive).read('device.cmd')
    files=dict(bundle['producer_inputs']);files.update(bundle['generated_files'])
    files.update({'controlled-request.json':encoded(request),'original-d2-device.cmd':original,
        'device.cmd':render(original,request['gate_V']),
        'dimensional-contract.json':encoded(D.dimensional_contract(bundle['d2_binding'])),
        'operating-paths.json':encoded(paths_contract(request['gate_V'])),'numerical-method.json':encoded(numerical_contract(original))})
    cfg['dimensional_contract_sha256']=sha(files['dimensional-contract.json'])
    files['source-spec.json']=encoded(source_spec(sha(files['physics-manifest.json']),cfg['dimensional_contract_sha256']))
    bound=binding(BytesReader(files),request['gate_V']);files['operating-voltage-dc-binding.json']=encoded(bound)
    cfg['operating_voltage_binding_sha256']=sha(files['operating-voltage-dc-binding.json'])
    files['role-contract.json']=encoded(role_contract(cfg))
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-operating-voltage-dc-main',role=ROLE,
        execution_enabled=True,runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(OUTPUTS))])
    files.update({'project.json':encoded(spec),
        'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',role=ROLE,
            observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',
            source='current_user_instruction',synthetic=False,role_ids=[ROLE],
            instruction='在原D2/20nm/原物理与数值算法上，以明确输入的gate_V做同一SN/BL静态电流路径诊断；原runner、owner、共享锁、串行单核单线程。保留全原结果，不设额度，不计真实写读或A0资格。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',
            plan_sha256=D.file_sha(root/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md')))})
    for name in ('geometry_bridge.py','mesh_resource_guard.py','case_contract.py')+RUNTIME_FILES:files[name]=(here/name).read_bytes()
    files['generator-prepare_case.py']=(here/'prepare_case.py').read_bytes()
    files['provenance.json']=encoded(dict(schema='dram-see-v4-operating-voltage-dc-2d-provenance-r1',role=ROLE,run_id=run_id,
        source_dimension=2,source_role='B1-D2',producer_run_id=D2_RUN,gate_V=request['gate_V'],gate_goal_literal=gate_literal(request['gate_V']),
        complete_original_D2_archive_retained=True,mesh_unchanged=True,physics_four_files_unchanged=True,
        exact_original_electrode_physics_plot_math_blocks_retained=True,independent_device_numerics=True,
        original_device_sha256=sha(original),original_dc_implementation_sha256=BASE_SHA,
        operating_voltage_binding_sha256=cfg['operating_voltage_binding_sha256'],
        no_native_scheduler_or_launcher=True,native_run_completed=False,is_actual_write_read=False,
        native_A0_functionality_qualified=False,acceptance_thresholds_changed=False,
        capacitor_assumptions_only=True,source_configured=False,final_holdout_used=False))
    hashes={name:sha(raw) for name,raw in files.items()}
    for name,digest in bundle['exports'].items():
        require(name not in hashes or hashes[name]==digest,'original proof import collision: '+name);hashes[name]=digest
    files['input-manifest.json']=encoded(dict(schema='dram-see-v4-continuous-inputs-r1',role_id=ROLE,run_id=run_id,files_sha256=hashes))
    files['execution-context.json']=encoded(dict(schema='dram-see-v4-continuous-run-context-r1',run_id=run_id,
        role_id=ROLE,producer_run_id=D2_RUN,synthetic=False,expected_runner_sha256=runner_sha,
        input_manifest_sha256=sha(files['input-manifest.json']),authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True,exist_ok=False)
    for name,raw in files.items():bridge.geometry_write(target/name,raw)
    bridge.geometry_stage_reuse(target,cfg);bridge.geometry_admit(target,spec,runner_sha)
    return dict(project=str(target),role_id=ROLE,run_id=run_id,source_run_id=D2_RUN,gate_V=request['gate_V'],
        mesh_sha256=cfg['mesh_sha256'],input_manifest_sha256=sha(files['input-manifest.json']),
        operating_voltage_binding_sha256=cfg['operating_voltage_binding_sha256'],expected_runner_sha256=runner_sha,
        native_run_completed=False,native_A0_functionality_qualified=False,native_submissions=0,diagnostic_only=True)
