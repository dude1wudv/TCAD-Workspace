"""Original-D2 static operating paths, never an A0 or a native launcher.

The new role reuses the complete verified D2 archive and independent-device
numerics. Python 3.6 standard library; preparation only writes immutable inputs.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tarfile

BRANCH = 'dram-see-v4-operating-dc-2d-r1'
ROLE = 'B2D-OPERATING-DC-main'
D2_RUN = '20261017T051217Z-v4-continuous-b1-d2-r8'
D2_SHA = 'c09b52ad56fcdf7e22dfb70ce750b04fd9fa383e1bda8a68ac9121ed768055cd'
ORIGINAL_DECK_SHA = 'ed383467d7585abc64f918915a575cc2af5dba9154f5ae856af11e78b57c3e38'
RUNTIME_FILES = ('operating_dc_2d.py', 'two_dimensional.py')
PREFIXES = ('', 'settle_write_', 'write_to_108_', 'write_above_108_', 'settle_read_', 'read_to_088_', 'read_below_088_')
OUTPUTS = tuple(p+'operating_des.plt' for p in PREFIXES)+('operating_final_des.tdr', 'operating_des.log')


def require(ok, message):
    if not ok:
        raise ValueError('2D operating DC: '+message)


def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')
def obj(raw):
    value=json.loads(raw.decode('utf-8'))
    require(isinstance(value,dict), 'expected JSON object')
    return value


def local_module(name, expected=None):
    path=Path(__file__).with_name(name)
    if expected is not None:
        require(sha(path.read_bytes())==expected, 'fixed original verifier differs: '+name)
    spec=importlib.util.spec_from_file_location('_operating2d_'+name.replace('.','_'),str(path))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def source_name(value): return re.split(r'[\\/]',value.rstrip('/\\'))[-1]


def block(raw, name):
    hits=list(re.finditer(rb'(?m)^'+name.encode('ascii')+rb'\s*\{',raw))
    require(len(hits)==1, 'original independent-device block is ambiguous: '+name)
    start=hits[0].start();depth=1;cursor=hits[0].end()
    while depth and cursor<len(raw):
        if raw[cursor:cursor+1]==b'{': depth+=1
        elif raw[cursor:cursor+1]==b'}': depth-=1
        cursor+=1
    require(depth==0, 'unterminated original block: '+name)
    return raw[start:cursor]


def sweep(prefix, goals, maximum, load_equilibrium=False):
    # No Time/Intervals filter: UG W-2024.09 pp176-179 specifies every point.
    return (' NewCurrentPrefix="'+prefix+'"\n'
        +(' Load(FilePrefix="operating_equilibrium")\n' if load_equilibrium else '')+' CurrentPlot\n'
        ' Quasistationary(InitialStep=0.001 MinStep=1e-8 MaxStep='+maximum+' Increment=1.3\n'
        +' '.join('  Goal {Name="'+name+'" Voltage='+value+'}' for name,value in goals)+') {\n'
        '  Coupled {Poisson Electron Hole}\n  CurrentPlot\n }\n')


def render(original):
    require(sha(original)==ORIGINAL_DECK_SHA, 'only the observed successful D2-r8 device deck is supported')
    sections=[block(original,n) for n in ('Electrode','Physics','Plot','Math')]
    solve=('Solve {\n Coupled(Iterations=100) {Poisson}\n'
           ' Coupled(Iterations=100) {Poisson Electron Hole}\n'
           ' Save(FilePrefix="operating_equilibrium")\n')
    solve+=sweep('settle_write_',(('gate','1.8'),('drain','1.2'),('source','0.6')),'0.0166666666666666')
    solve+=sweep('write_to_108_',(('source','1.08'),),'0.0208333333333333')
    solve+=sweep('write_above_108_',(('source','1.12'),),'0.25')
    # Reset only this diagnostic branch to its own actual equilibrium solution.
    # This is not loading a written state or simulating an A0 initial condition.
    solve+=sweep('settle_read_',(('gate','1.8'),('drain','0.6'),('source','1.08')),'0.00925925925925925',True)
    solve+=sweep('read_to_088_',(('source','0.88'),('drain','0.62')),'0.05')
    solve+=sweep('read_below_088_',(('source','0.8'),('drain','0.628')),'0.125')
    solve+=' Plot(FilePrefix="operating_final")\n}\n'
    return (b'* Static imposed-bias diagnostic only; no physical write/read or A0 qualification.\n'
        b'File { Grid="cell_msh.tdr" Current="operating" Plot="operating" Output="operating" Parameter="physics.par" }\n'
        +b'\n'.join(sections)+b'\n'+solve.encode('ascii'))


def paths_contract():
    return dict(schema='dram-see-v4-operating-dc-2d-paths-r1',dimension=2,
        interpretation='Imposed quasi-static bias paths, not physical transient time or A0 functionality',
        gate_V=1.8,body_V=0.,VDD_V=1.2,effective_width_nm=20,area_factor=.02,
        capacitor_assumptions=dict(Cstore_fF=20,Cbl_fF=200,implemented_in_static_solver=False,
            explicit_capacitance_rescale=False,source='Unchanged original A0 model values'),
        preload=[dict(prefix='settle_write_',source_V=[0.,.6],gate_V=[0.,1.8],drain_V=[0.,1.2],
                      max_normalized_step='0.0166666666666666',used_for_time_estimate=False),
                 dict(prefix='settle_read_',source_V=[0.,1.08],gate_V=[0.,1.8],drain_V=[0.,.6],
                      max_normalized_step='0.00925925925925925',used_for_time_estimate=False)],
        write=dict(source_start_V=.6,source_end_V=1.12,drain_fixed_V=1.2,
            source_TotalCurrent_expected_sign='negative: into-device convention, current delivered out of device to SN',
            required_native_source_endpoint_V=1.08,
            segments=[dict(prefix='write_to_108_',source_V=[.6,1.08],max_normalized_step='0.0208333333333333'),
                      dict(prefix='write_above_108_',source_V=[1.08,1.12],max_normalized_step='0.25')]),
        read=dict(source_V=[1.08,.8],drain_V=[.6,.628],
            source_TotalCurrent_expected_sign='positive: current leaves SN and enters device',
            simultaneous_linear_goals=True,drain_path='0.6+0.1*(1.08-VSN)',
            required_native_source_endpoint_V=.88,required_native_drain_endpoint_V=.62,
            segments=[dict(prefix='read_to_088_',source_V=[1.08,.88],drain_V=[.6,.62],max_normalized_step='0.05'),
                      dict(prefix='read_below_088_',source_V=[.88,.8],drain_V=[.62,.628],max_normalized_step='0.125')],
            predicted_20mV_BL_crossing_source_V=.88),
        max_source_voltage_step_V=.01,step_is_voltage_resolution=True,
        current_output=dict(all_actual_solve_points=True,CurrentPlot='bare statement',prefixes=list(PREFIXES),
            resampling=False,discard_unfavorable_points=False,physical_time_axis=False,
            retain_all_terminal_currents=True,retain_original_log_rejected_attempts=True,
            vendor_reference='SDevice W-2024.09 UG pp176-179; no Time/Intervals point filter'),
        future_time_estimate=dict(write='Cstore*integral(dVSN/(-I_source_into_device))',
            read='Cstore*integral_from_lower_to_1.08(dVSN/I_source_into_device)',
            width_postprocessing_multiplier=1,zero_or_reversed_current='Retain and report; no clipping or claimed finite passage time',
            caveats=['Check actual current direction, bias path, all terminal leakage and charge balance',
                     'Static path ignores transient/displacement/history effects and does not establish write/read timing',
                     'BL path assumes capacitance-ratio charge sharing; significant other terminal currents invalidate that estimate',
                     'Any timing choice must be tested by new actual A0 with unchanged functional criteria']),
        native_run_completed=False,native_A0_functionality_qualified=False,native_source_qualified=False)


def numerical_contract(original):
    return dict(schema='dram-see-v4-operating-dc-2d-numerics-r1',source_run_id=D2_RUN,
        source_device_sha256=sha(original),source_math_sha256=sha(block(original,'Math')),
        source_numerical_json_present=False,method='ParDiSo',mixed_mode=False,
        exact_original_math_retained=True,exact_initial_coupled_statements_retained=True,
        equations=['Poisson','Electron','Hole'],RelErrControl=True,Digits=5,
        ErrRef_electron=1e7,ErrRef_hole=1e7,Iterations=30,Notdamped=100,ExitOnFailure=True,
        thread_management='Original runner --threads 1, taskset one CPU and existing shared lock',
        no_added_physics=True,criteria_changed=False,native_diagnostic_syntax_verified=False)


def source_spec(physics_sha, width_sha):
    return dict(schema='dram-see-v4-operating-dc-2d-source-absence-r1',role='DIAGNOSTIC',
        source_case='NONE',source_configured=False,dimension=2,is_A0=False,
        physics_manifest_sha256=physics_sha,dimensional_contract_sha256=width_sha)


def original_deck(reader, D):
    with reader.stream(D.PREFIX+'results.tar') as stream:
        with tarfile.open(fileobj=stream,mode='r:*') as archive:
            return D.ArchiveReader(archive).read('device.cmd')


def verify_frozen(reader,cfg):
    D=local_module('two_dimensional.py',D2_SHA)
    result=D.verify_frozen(reader,cfg)
    require(cfg.get('operating_branch')==BRANCH and cfg.get('producer_run_id')==D2_RUN,
            'explicit original-D2 diagnostic identity required')
    original=original_deck(reader,D)
    require(reader.read('original-d2-device.cmd')==original and sha(original)==ORIGINAL_DECK_SHA,
            'original independent-device numerical/physical deck differs')
    require(reader.read('device.cmd')==render(original), 'static operating deck differs from explicit paths')
    require(obj(reader.read('operating-paths.json'))==paths_contract()
            and obj(reader.read('numerical-method.json'))==numerical_contract(original),
            'diagnostic path/numerical declaration differs')
    require(obj(reader.read('source-spec.json'))==source_spec(reader.digest('physics-manifest.json'),reader.digest('dimensional-contract.json')),
            'diagnostic is not an A0 or particle-source role')
    binding=obj(reader.read('operating-dc-binding.json'))
    expected=dict(schema='dram-see-v4-operating-dc-2d-binding-r1',operating_branch=BRANCH,
        producer_run_id=D2_RUN,d2_source_binding_sha256=reader.digest('d2-source-binding.json'),
        original_device_sha256=sha(original),original_math_sha256=sha(block(original,'Math')),
        device_sha256=reader.digest('device.cmd'),paths_sha256=reader.digest('operating-paths.json'),
        numerical_sha256=reader.digest('numerical-method.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        verifier_sha256=sha(Path(__file__).read_bytes()),native_run_completed=False,is_A0=False)
    require(binding==expected and reader.digest('operating_dc_2d.py')==expected['verifier_sha256']
            and cfg.get('operating_binding_sha256')==reader.digest('operating-dc-binding.json'),
            'frozen operating diagnostic/version binding differs')
    result.update(operating_binding=binding,operating_paths=paths_contract())
    return result


def admit(project,spec,runner_sha,bridge):
    project=Path(project);cfg=spec['s2_geometry'];C=local_module('case_contract.py')
    require(cfg.get('schema')==bridge.GEOMETRY_SCHEMA and cfg.get('mode')=='reuse'
            and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
            and spec.get('execution_enabled') is True,'native diagnostic reuse context differs')
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve()) and not (project/'SYNTHETIC_NOT_NATIVE').exists(),
            'synthetic input cannot become a native diagnostic')
    request=C.validate(obj((project/'controlled-request.json').read_bytes()))
    require(request['schema']==C.SCHEMA_2D_OPERATING and C.role_id(request)==cfg.get('role_id')==spec.get('role')==ROLE
            and source_name(request['d2_source_run'])==cfg.get('producer_run_id')==D2_RUN
            and cfg.get('run_id')!=D2_RUN and spec.get('native_threads')==spec.get('native_cores')==1
            and spec.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(OUTPUTS))],
            'diagnostic role/source/serial steps differ')
    bridge.geometry_context(project,cfg,runner_sha)
    hashes=bridge.geometry_input_hashes(project)
    D=local_module('two_dimensional.py',D2_SHA)
    required=set(D.SHARED_INPUTS)|set(RUNTIME_FILES)|{D.PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}|{
        'project.json','case_contract.py','geometry_bridge.py','mesh_resource_guard.py','controlled-request.json',
        'resource-policy.json','task-authorization.json','role-contract.json','device.cmd','cell_msh.tdr','cell_msh.log',
        'd2-source-binding.json','dimensional-contract.json','original-d2-device.cmd','operating-paths.json',
        'numerical-method.json','operating-dc-binding.json','source-spec.json'}
    require(required<=set(hashes),'mandatory original diagnostic evidence missing')
    manifest=obj((project/'input-manifest.json').read_bytes())
    require(manifest.get('run_id')==cfg['run_id'] and manifest.get('role_id')==ROLE,'diagnostic input manifest identity differs')
    for name,digest in hashes.items():
        require(D.file_sha(bridge.geometry_path(project,name))==digest,'frozen diagnostic input changed: '+name)
    verify_frozen(D.FolderReader(project),cfg)
    require(obj((project/'role-contract.json').read_bytes())==role_contract(cfg), 'diagnostic is not a functional acceptance role')
    policy=obj((project/'resource-policy.json').read_bytes())
    require(policy==dict(schema='dram-see-v4-actual-resource-policy-r1',role=ROLE,observation_only=True,
        imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None),'only actual resource observations are allowed')
    return cfg


def role_contract(cfg):
    return dict(schema='dram-see-v4-operating-dc-2d-role-r1',role=ROLE,dimension=2,
        case='OPERATING_DC_DIAGNOSTIC',execution_enabled=True,stored_bit=None,source_configured=False,
        source_dimension=2,effective_width_nm=20,area_factor=.02,
        producer_run_id=D2_RUN,mesh_sha256=cfg['mesh_sha256'],
        dimensional_contract_sha256=cfg['dimensional_contract_sha256'],
        operating_binding_sha256=cfg['operating_binding_sha256'],
        outputs=list(OUTPUTS),is_actual_write_read=False,is_A0=False,
        native_syntax_verified=False,native_A0_functionality_qualified=False,
        outcome='Actual DC curves only; timing is a later quasi-static estimate requiring real A0 verification')


def prepare(request,run_id,runner=None,output=None):
    C=local_module('case_contract.py');D=local_module('two_dimensional.py',D2_SHA)
    bridge=local_module('geometry_bridge.py');request=C.validate(request)
    require(request['schema']==C.SCHEMA_2D_OPERATING,'explicit r10 diagnostic required')
    require(isinstance(run_id,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',run_id),'unsafe run ID')
    here=Path(__file__).resolve().parent;root=here.parents[3]
    runner=Path(runner or root/'scripts/tcad.py').resolve()
    require(runner==(root/'scripts/tcad.py').resolve() and runner.is_file(),'use original scripts/tcad.py')
    allowed=(root/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/operating-dc-implementation-r1').resolve()
    target=Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target),
            'new diagnostic input directory required')
    request=dict(request);request['d2_source_run']=str(Path(request['d2_source_run']).resolve())
    require(source_name(request['d2_source_run'])==D2_RUN,'only actual successful D2-r8 supported')
    runner_sha=D.file_sha(runner)
    cfg=dict(schema=bridge.GEOMETRY_SCHEMA,mode='reuse',dimension_branch=D.BRANCH,operating_branch=BRANCH,
        role_id=ROLE,run_id=run_id,producer_run_id=D2_RUN,execution_enabled=True,synthetic=False,
        source_run_directory=request['d2_source_run'],source_dimension=2,effective_width_nm=20,area_factor=.02,
        size_id=C.size_id(80),sn_junction_depth_nm=87,numerical_variant='main',parameter_id=C.parameter_id(request))
    bundle=bridge.geometry_source_bundle(target,cfg)
    cfg.update(source_manifest_sha256=bundle['manifest_sha256'],source_archive_sha256=bundle['archive_sha256'],
        mesh_sha256=bundle['mesh_sha256'],geometry_validation_sha256=bundle['geometry_validation_sha256'],
        d2_source_binding_sha256=bundle['d2_source_binding_sha256'])
    with tarfile.open(str(bundle['archive']),'r:*') as archive:
        original=D.ArchiveReader(archive).read('device.cmd')
    files=dict(bundle['producer_inputs']);files.update(bundle['generated_files'])
    files['original-d2-device.cmd']=original;files['device.cmd']=render(original)
    files['dimensional-contract.json']=encoded(D.dimensional_contract(bundle['d2_binding']))
    cfg['dimensional_contract_sha256']=sha(files['dimensional-contract.json'])
    files['operating-paths.json']=encoded(paths_contract());files['numerical-method.json']=encoded(numerical_contract(original))
    files['source-spec.json']=encoded(source_spec(sha(files['physics-manifest.json']),cfg['dimensional_contract_sha256']))
    binding=dict(schema='dram-see-v4-operating-dc-2d-binding-r1',operating_branch=BRANCH,producer_run_id=D2_RUN,
        d2_source_binding_sha256=cfg['d2_source_binding_sha256'],original_device_sha256=sha(original),
        original_math_sha256=sha(block(original,'Math')),device_sha256=sha(files['device.cmd']),
        paths_sha256=sha(files['operating-paths.json']),numerical_sha256=sha(files['numerical-method.json']),
        dimensional_contract_sha256=cfg['dimensional_contract_sha256'],verifier_sha256=D.file_sha(__file__),
        native_run_completed=False,is_A0=False)
    files['operating-dc-binding.json']=encoded(binding);cfg['operating_binding_sha256']=sha(files['operating-dc-binding.json'])
    files['role-contract.json']=encoded(role_contract(cfg))
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-operating-dc-main',role=ROLE,
        execution_enabled=True,runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(OUTPUTS))])
    files.update({'project.json':encoded(spec),'controlled-request.json':encoded(request),
        'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',role=ROLE,
            observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',
            source='current_user_instruction',synthetic=False,role_ids=[ROLE],
            instruction='在原D2网格/物理/宽度上做静态充放电电流诊断，不计A0资格；原runner、owner、共享锁与单核单线程，全部原生结果保留，不设资源额度。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',
            plan_sha256=D.file_sha(root/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md')))})
    for name in ('geometry_bridge.py','mesh_resource_guard.py','case_contract.py')+RUNTIME_FILES:
        files[name]=(here/name).read_bytes()
    files['generator-prepare_case.py']=(here/'prepare_case.py').read_bytes()
    files['provenance.json']=encoded(dict(schema='dram-see-v4-operating-dc-2d-provenance-r1',role=ROLE,run_id=run_id,
        source_dimension=2,source_role='B1-D2',producer_run_id=D2_RUN,
        complete_original_D2_archive_retained=True,mesh_unchanged=True,physics_four_files_unchanged=True,
        exact_original_electrode_physics_plot_math_blocks_retained=True,independent_device_numerics=True,
        original_device_sha256=sha(original),operating_binding_sha256=cfg['operating_binding_sha256'],
        no_native_scheduler_or_launcher=True,native_run_completed=False,is_actual_write_read=False,
        native_A0_functionality_qualified=False,acceptance_thresholds_changed=False,
        capacitor_assumptions_only=True,source_configured=False,final_holdout_used=False))
    hashes={name:sha(raw) for name,raw in files.items()}
    for name,digest in bundle['exports'].items():
        require(name not in hashes or hashes[name]==digest,'original proof import collision: '+name)
        hashes[name]=digest
    files['input-manifest.json']=encoded(dict(schema='dram-see-v4-continuous-inputs-r1',role_id=ROLE,run_id=run_id,files_sha256=hashes))
    files['execution-context.json']=encoded(dict(schema='dram-see-v4-continuous-run-context-r1',run_id=run_id,
        role_id=ROLE,producer_run_id=D2_RUN,synthetic=False,expected_runner_sha256=runner_sha,
        input_manifest_sha256=sha(files['input-manifest.json']),authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True,exist_ok=False)
    for name,raw in files.items():bridge.geometry_write(target/name,raw)
    bridge.geometry_stage_reuse(target,cfg)
    bridge.geometry_admit(target,spec,runner_sha)
    return dict(project=str(target),role_id=ROLE,run_id=run_id,source_run_id=D2_RUN,
        mesh_sha256=cfg['mesh_sha256'],input_manifest_sha256=sha(files['input-manifest.json']),
        operating_binding_sha256=cfg['operating_binding_sha256'],expected_runner_sha256=runner_sha,
        native_run_completed=False,native_A0_functionality_qualified=False,native_submissions=0,
        diagnostic_only=True)
