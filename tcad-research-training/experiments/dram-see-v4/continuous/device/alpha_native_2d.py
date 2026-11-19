"""Frozen 2D alpha inputs and real same-bit A0 pairing; never launches TCAD.

Runtime verification uses Python 3.6 stdlib. Host preparation alone replays the
fixed alpha projection implementation. No archived arbitrary Python is run.
The unchanged, known-hash circuit metrics are the only executable payload.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import tarfile
import types

BRANCH = 'dram-see-v4-alpha-native-2d-r1'
BINDING_SCHEMA = 'dram-see-v4-alpha-native-2d-binding-r1'
SPEC_SCHEMA = 'dram-see-v4-2d-alpha-source-spec-r1'
PROJECTION_SCHEMA = 'dram-see-v4-alpha-projection-2d-r1'
MANIFEST_SCHEMA = 'dram-see-v4-alpha-2d-input-output-manifest-r1'
D2_SHA = 'c09b52ad56fcdf7e22dfb70ce750b04fd9fa383e1bda8a68ac9121ed768055cd'
PROJECTION_SHA = '16d2fe5e7a182d2ed11e17c197493dac822482ee1c6c6c0da0336a9c86a81f56'
METRICS_SHA = '14681b6fae30bce49a8b1063b3f8abd7e790e51c6afe58f74da094cd574b2d6e'
CLOCK_SHA = 'bf5d9a8c5520eda054ecadd14fa4fc06f2f3b7296f16483e5ded02ff20ab4387'
RUNTIME_FILES = ('alpha_native_2d.py', 'two_dimensional.py', 'alpha-a0-metrics.py', 'native_transient_clock.py')
PROJECTION_PREFIX = 'alpha-projection/'
A0_PREFIX = 'matched-a0-bindings/'
PROJECTION_FILES = ('alpha-astar-silicon.csv', 'alpha-profile-2d-native.csv',
    'alpha-profile-3d-reference.csv', 'dimensional-contract.json', 'geometry-contract.json',
    'heavyion.physics.inc', 'input-origins.json', 'model.proposed.json', 'projection-ledger.json',
    'projection-request.json', 'source-contract.json', 'source.par', 'input-output-manifest.json')
SHARED = ('physics.par', 'physics-manifest.json', 'Silicon.par', 'Oxide.par',
    'model.proposed.json', 'geometry-contract.json', 'dimensional-contract.json',
    'numerical-method.json', 'initialization-contract.json', 'functional-criteria.json')
PLOT = b'HeavyIonGeneration HeavyIonChargeDensity '
CURRENT = b'CurrentPlot {\n HeavyIonGeneration( Integrate(Semiconductor) )\n}\n'
BEGIN = b'* ALPHA2D_PHYSICS_BEGIN\n'
END = b'* ALPHA2D_PHYSICS_END\n'
NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'


def require(ok, message):
    if not ok:
        raise ValueError('2D alpha: '+message)


def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')
def obj(raw):
    value = json.loads(raw.decode('utf-8'))
    require(isinstance(value, dict), 'expected a JSON object')
    return value


def _fixed_module(filename, expected):
    path = Path(__file__).with_name(filename)
    require(sha(path.read_bytes()) == expected, 'fixed implementation changed: '+filename)
    spec = importlib.util.spec_from_file_location('_alpha2d_fixed_'+filename.replace('.', '_'), str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dimensional(): return _fixed_module('two_dimensional.py', D2_SHA)


def native_source_request(request):
    expected=dict(schema='dram-see-v4-alpha-projection-request-r1',energy_MeV=5,
        theta_deg=0,phi_deg=180,amplitude=1.,epoch_s=1.5e-8,simulation_window_s=[0.,25e-9])
    require(request==expected and all(type(request[n]) in (int,float) for n in
            ('energy_MeV','theta_deg','phi_deg','amplitude','epoch_s')),
            'first native alpha branch supports only 5MeV/normal/amplitude1 with original timing')
    return request


def _metrics(raw):
    require(sha(raw) == METRICS_SHA, 'original functional/KCL metric implementation differs')
    module = types.ModuleType('_alpha2d_unchanged_circuit_metrics')
    # Hash is an in-source allowlist, not a value supplied by the archive.
    exec(compile(raw, '<fixed-original-s2-circuit-metrics>', 'exec'), module.__dict__)
    return module


def circuit_trace(raw, device_plt, native_log, device_deck):
    """Same versioned host/guest interval association; no favorable-row choice."""
    clock = _fixed_module('native_transient_clock.py', CLOCK_SHA).audit(raw, device_plt, native_log, device_deck)
    return clock['trace'], clock


def _collection(reader, manifest, inputs, D):
    require(manifest.get('schema') == 'tcad-native-run-r2' and manifest.get('state') == 'COLLECTED'
            and manifest.get('collection_verified') is True and manifest.get('origin') == 'native_pipeline'
            and manifest.get('synthetic') is False, 'matched A0 is not a complete original native run')
    require(type(manifest.get('ssh_exit_code')) is int, 'raw A0 SSH exit is missing')
    require(all(type(manifest.get(n)) is int and manifest[n] == 0 for n in
                ('remote_exit_code','collection_exit_code','version_probe_exit_code')), 'matched A0 has a nonzero/unknown actual exit')
    require(D._exit(reader.read('metadata-sdevice-version-exit-code.txt')) == 0,
            'matched A0 original version probe failed')
    inventory = obj(reader.read('_collection-members.json'))
    require(set(inventory) == {n for n,m in reader.members.items() if m.isfile()}-{'_collection-members.json'},
            'matched A0 collection inventory is incomplete')
    for name, row in inventory.items():
        require(row == dict(size=reader.size(name),sha256=reader.digest(name)), 'matched A0 archived bytes differ: '+name)
    expected = manifest.get('input_sha256', {})
    require(expected and set(expected) == {n for n,m in inputs.members.items() if m.isfile()}, 'matched A0 input inventory differs')
    for name, digest in expected.items():
        require(inputs.digest(name) == digest == reader.digest(name), 'matched A0 input differs: '+name)
    context = obj(reader.read('execution-context.json'))
    frozen = obj(reader.read('input-manifest.json'))
    require(context.get('schema') == 'dram-see-v4-continuous-run-context-r1' and context.get('synthetic') is False
            and context.get('input_manifest_sha256') == reader.digest('input-manifest.json')
            and context.get('run_id') == manifest.get('run_id')
            and context.get('expected_runner_sha256') == manifest.get('runner_sha256')
            and re.fullmatch(r'[a-f0-9]{64}',manifest.get('runner_sha256','')) is not None
            and context.get('authorization_sha256') == reader.digest('task-authorization.json'),
            'matched A0 frozen execution identity differs')
    require(frozen.get('schema') == 'dram-see-v4-continuous-inputs-r1'
            and frozen.get('run_id') == manifest['run_id'] and frozen.get('files_sha256')
            and set(frozen['files_sha256']) == set(expected)-{'execution-context.json','input-manifest.json'},
            'matched A0 input-manifest coverage differs')
    for name, digest in frozen['files_sha256'].items():
        require(digest == expected[name], 'matched A0 inner input digest differs')
    identity = obj(reader.read('process-identity.json'))
    require(identity.get('schema') == 'tcad-process-identity-r1' and identity.get('run_id') == manifest['run_id']
            and identity.get('cwd') == manifest.get('remote_directory')
            and identity.get('script_sha256') == manifest.get('script_sha256') == reader.digest('run.sh')
            and identity == manifest.get('last_observation',{}).get('identity')
            and type(identity.get('pid')) is int and identity['pid'] > 1
            and type(identity.get('start_ticks')) is int and identity['start_ticks'] > 0
            and re.fullmatch(r'[a-f0-9-]{36}',identity.get('boot_id','')) is not None, 'matched A0 original wrapper identity differs')
    lock = dict(line.split('=',1) for line in reader.read('shared-lock-evidence.txt').decode().splitlines() if '=' in line)
    require(lock.get('status') == 'ACQUIRED' and lock.get('pid') == str(identity['pid']) and lock.get('fd') == '9'
            and lock.get('lock_path') == '/home/tcad/research-training/.solver.lock', 'matched A0 shared lock evidence differs')
    require(manifest.get('tool_exit_codes') == {'step-001-sdevice':0}
            and type(manifest['tool_exit_codes']['step-001-sdevice']) is int
            and set(manifest.get('tool_evidence',{})) == {'step-001-sdevice'}
            and 'native_step_start_index' not in manifest, 'matched A0 must contain only its actual SDevice step')
    D._capture(reader, manifest, identity, 1, 'sdevice')
    require(D._exit(reader.read('exit-code.txt')) == 0
            and b'ENGINEERING_RUN_COMPLETED' in reader.read('execution.log').splitlines()
            and b'Sentaurus Device simulation finished' in reader.read('transient_des.log')
            and all(reader.size(n)>0 for n in D.A0_OUTPUTS), 'matched A0 actual transient completion is missing')
    return context


def _a0(reader, manifest, inputs, bit, D):
    context = _collection(reader, manifest, inputs, D)
    project = obj(reader.read('project.json')); cfg = project.get('s2_geometry',{})
    role = obj(reader.read('role-contract.json')); source = obj(reader.read('source-spec.json'))
    expected_role = 'B2D-A0-main-b'+str(bit)
    require(project.get('role') == cfg.get('role_id') == context.get('role_id') == expected_role
            and cfg.get('run_id') == manifest['run_id'] and cfg.get('mode') == 'reuse'
            and context.get('producer_run_id') == cfg.get('producer_run_id')
            and obj(reader.read('input-manifest.json')).get('role_id') == expected_role
            and project.get('native_threads') == project.get('native_cores') == 1
            and project.get('steps') == manifest.get('steps') ==
                [dict(tool='sdevice',args=['device.cmd'],outputs=list(D.A0_OUTPUTS))], 'matched A0 bit/role/steps differ')
    require(role.get('schema') == 'dram-see-v4-2d-control-role-r1' and role.get('role') == expected_role
            and role.get('stored_bit') == bit and type(role.get('stored_bit')) is int
            and role.get('case') == 'A0' and role.get('source_configured') is False
            and role.get('numerical_variant') == 'main', 'matched A0 role contract differs')
    require(source.get('schema') == 'dram-see-v4-2d-control-source-spec-r1'
            and source.get('role') == 'CONTROL' and source.get('source_case') == 'A0'
            and source.get('source_configured') is False and source.get('dimension') == 2
            and source.get('stored_bit') == bit and source.get('numerical_variant') == 'main'
            and source.get('physics_manifest_sha256') == reader.digest('physics-manifest.json')
            and source.get('dimensional_contract_sha256') == reader.digest('dimensional-contract.json'), 'matched A0 source absence differs')
    verified = D.verify_frozen(reader, cfg)
    device = reader.read('device.cmd')
    require(re.search(rb'\b(?:HeavyIon|Load)\s*\(',device) is None
            and re.findall(rb'\bParameter\s*=\s*"([^"]+)"',device) == [b'physics.par']
            and re.findall(rb'AreaFactor\s*=\s*([^\s}]+)',device) == [b'0.02']
            and device.count(b'Set(sn=0.6)') == device.count(b'Unset(sn)') == 1
            and device.index(b'Set(sn=0.6)') < device.index(b'Unset(sn)') < device.index(b' Transient(')
            and re.findall(rb'(?<![A-Za-z])Set\(sn=([^)]*)\)',device) == [b'0.6'], 'matched A0 source/neutral initialization differs')
    trace, clock = circuit_trace(reader.read('circuit.plt'),reader.read('access_device.plt'),
                                 reader.read('transient_des.log'),device)
    metrics = _metrics(reader.read('metrics.py')).baseline(trace,bit)
    require(metrics['candidate_functional_pass'] is True and all(v is True for v in metrics['checks'].values()),
            'matched A0 original write/hold/precharge/read/KCL criteria have not passed')
    return dict(verified=verified, project=project, cfg=cfg, role=role, device=device, metrics=metrics,
        duplicate_identical_rows_removed=0, native_transient_clock=clock,
        shared={n:reader.read(n) for n in SHARED}, input_manifest_sha256=reader.digest('input-manifest.json'),
        circuit_plt_sha256=reader.digest('circuit.plt'), collection_index_sha256=reader.digest('_collection-members.json'))


def timing(a0_device, contract):
    windows = re.findall(rb'Plot\(FilePrefix="source_window" Time=\(Range=\(('+NUMBER.encode()+rb') ('+NUMBER.encode()+rb')\)\) NoOverwrite\)',a0_device)
    require(len(windows)==1, 'matched A0 needs its unique original source-observation window')
    literal = [v.decode('ascii') for v in windows[0]]; native = [float(v) for v in literal]
    mathematical = contract['source_window_s']
    require(native == [14.9984*1e-9,15.0016*1e-9]
            and mathematical == [1.4998399999999998e-8,1.50016e-8]
            and contract['request']['epoch_s'] == 1.5e-8
            and contract['full_simulation_window_s'] == [0.,25e-9], 'source/A0 time version differs; no silent remapping')
    segments = re.findall(rb' Transient\(InitialTime=('+NUMBER.encode()+rb') FinalTime=('+NUMBER.encode()+rb')[^\n]* MaxStep=('+NUMBER.encode()+rb') Increment=1.3\)',a0_device)
    require(segments and float(segments[0][0])==0 and float(segments[-1][1])==25*1e-9
            and all(a[1]==b[0] for a,b in zip(segments,segments[1:])), 'A0 full transient timing differs')
    return dict(schema='dram-see-v4-alpha-2d-native-time-r1',source_epoch_s=1.5e-8,
        mathematical_source_window_s=mathematical,native_observation_window_s=native,
        native_observation_window_literals=literal,
        native_minus_mathematical_window_s=[a-b for a,b in zip(native,mathematical)],
        native_segments=[dict(initial_literal=a.decode(),final_literal=b.decode(),max_step_literal=c.decode()) for a,b,c in segments],
        observation_window_is_not_physical_source_truncation=True,
        comparison='Native window is the exact original A0 window; mathematical window and floating-point differences remain separate',
        native_source_clock_qualified=False)


def render_signal(a0_device, include):
    require(include.startswith(b'HeavyIon("AlphaStrip20nm2D") (\n') and include.endswith(b')\n'), 'wrong mapped alpha include')
    require(BEGIN not in a0_device and END not in a0_device and PLOT not in a0_device
            and re.search(rb'\bHeavyIon\s*\(',a0_device) is None, 'control already has an active source')
    marker=b' }\n}\nFile { Output="transient" }\n'
    require(a0_device.count(marker)==1 and a0_device.count(b'Plot { ')==1
            and a0_device.count(b'Math {')==1 and a0_device.count(b'Parameter="physics.par"')==1,
            'unexpected original A0 deck structure')
    value=a0_device.replace(marker,BEGIN+include+END+marker,1)
    value=value.replace(b'Plot { ',b'Plot { '+PLOT,1).replace(b'Math {',CURRENT+b'Math {',1)
    return value.replace(b'Parameter="physics.par"',b'Parameter="run-parameters.par"',1)


def source_free_deck(device, include):
    fragment=BEGIN+include+END
    require(device.count(fragment)==device.count(CURRENT)==device.count(b'Plot { '+PLOT)==1
            and device.count(b'Parameter="run-parameters.par"')==1, 'source removal is not exact/unique')
    return (device.replace(fragment,b'',1).replace(CURRENT,b'',1).replace(b'Plot { '+PLOT,b'Plot { ',1)
            .replace(b'Parameter="run-parameters.par"',b'Parameter="physics.par"',1))


def projection(reader):
    manifest=obj(reader.read(PROJECTION_PREFIX+'input-output-manifest.json'))
    require(manifest.get('schema')==MANIFEST_SCHEMA and manifest.get('implementation_sha256')==PROJECTION_SHA
            and manifest.get('is_native_result') is False and manifest.get('native_source_qualified') is False
            and set(manifest.get('files',{}))==set(PROJECTION_FILES)-{'input-output-manifest.json'}, 'projection package identity differs')
    for n,row in manifest['files'].items():
        require(row==dict(sha256=reader.digest(PROJECTION_PREFIX+n),size_bytes=reader.size(PROJECTION_PREFIX+n)),
                'projection original bytes differ: '+n)
    require(reader.digest('alpha-projection-implementation.py')==PROJECTION_SHA, 'frozen mathematical verifier differs')
    contract=obj(reader.read(PROJECTION_PREFIX+'source-contract.json'))
    require(contract.get('schema')==PROJECTION_SCHEMA and contract.get('particle')=='alpha'
            and contract.get('dimension')==2 and contract.get('native_source_qualified') is False
            and contract.get('is_tcad_result') is False and contract.get('pmi_r12_fixed') is False,
            'projection is not the explicit unqualified 2D alpha source')
    request=obj(reader.read(PROJECTION_PREFIX+'projection-request.json'))
    require(request==contract['request'],'projection request differs from its original contract')
    native_source_request(request)
    for n in ('model.proposed.json','geometry-contract.json','dimensional-contract.json'):
        require(reader.digest(n)==reader.digest(PROJECTION_PREFIX+n)==contract['input_sha256'][n],
                'projection differs from actual 2D input: '+n)
    for n in ('source-contract.json','heavyion.physics.inc','source.par'):
        require(reader.read(n)==reader.read(PROJECTION_PREFIX+n), 'active source differs from original projection: '+n)
    require(contract['mesh_sha256']==reader.digest('cell_msh.tdr')
            and contract['physics_manifest_sha256']==reader.digest('physics-manifest.json'), 'projection mesh/physics differs')
    return dict(contract=contract,ledger=obj(reader.read(PROJECTION_PREFIX+'projection-ledger.json')),manifest=manifest)


def verify_frozen(reader, cfg):
    D=dimensional()
    require(cfg.get('source_branch')==BRANCH and cfg.get('dimension_branch')==D.BRANCH
            and cfg.get('mode')=='reuse' and cfg.get('source_dimension')==2, 'explicit alpha/2D branch required')
    require(reader.digest('alpha_native_2d.py')==D.file_sha(__file__)
            and reader.digest('two_dimensional.py')==D2_SHA
            and reader.digest('alpha-a0-metrics.py')==METRICS_SHA
            and reader.digest('native_transient_clock.py')==CLOCK_SHA, 'frozen alpha runtime identity differs')
    result=D.verify_frozen(reader,cfg)
    bound=obj(reader.read('alpha-native-binding.json'))
    require(bound.get('schema')==BINDING_SCHEMA and bound.get('source_branch')==BRANCH
            and reader.digest('alpha-native-binding.json')==cfg.get('alpha_native_binding_sha256'), 'alpha binding differs')
    require(bound.get('verifier_sha256')==reader.digest('alpha_native_2d.py')
            and bound.get('projection_verifier_sha256')==PROJECTION_SHA
            and bound.get('projection_manifest_sha256')==reader.digest(PROJECTION_PREFIX+'input-output-manifest.json'),
            'alpha mathematical/runtime identity differs')
    p=projection(reader);source=obj(reader.read('source-spec.json'))
    bit=bound.get('stored_bit')
    require(type(bit) is int and bit in (0,1), 'actual alpha bit missing')
    expected_spec=dict(schema=SPEC_SCHEMA,particle='alpha',role='SIGNAL',source_case='Aalpha',dimension=2,
        stored_bit=bit,numerical_variant='main',source_configured=True,
        physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        source_contract_sha256=reader.digest('source-contract.json'),alpha_native_binding_sha256=reader.digest('alpha-native-binding.json'),
        currentplot_integration_unit='um',currentplot_domain='Semiconductor',native_source_qualified=False)
    require(source==expected_spec,'explicit active 2D source identity differs')
    require(set(bound.get('matched_a0_original_files',{}))=={A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')},
            'matched A0 original proof inventory differs')
    for n,row in bound['matched_a0_original_files'].items():
        require(row==dict(sha256=reader.digest(n),size_bytes=reader.size(n)), 'matched A0 original changed: '+n)
    manifest=obj(reader.read(A0_PREFIX+'manifest.json'))
    require(manifest.get('results_sha256')==reader.digest(A0_PREFIX+'results.tar')
            and manifest.get('inputs_archive_sha256')==reader.digest(A0_PREFIX+'inputs.tar'), 'matched A0 receipt/archive differs')
    with reader.stream(A0_PREFIX+'results.tar') as a,reader.stream(A0_PREFIX+'inputs.tar') as i:
        with tarfile.open(fileobj=a,mode='r:*') as archive,tarfile.open(fileobj=i,mode='r:*') as inputs:
            prior=D.ArchiveReader(archive);match=_a0(prior,manifest,D.ArchiveReader(inputs),bit,D)
            summary=matched_identity(match,manifest,reader.digest(A0_PREFIX+'manifest.json'),reader.digest(A0_PREFIX+'results.tar'))
            require(bound.get('matched_a0')==summary, 'matched A0 identity/functional recomputation differs')
            for n in SHARED:
                require(reader.read(n)==prior.read(n), 'signal/A0 physical or numerical input differs: '+n)
            require(reader.digest('cell_msh.tdr')==prior.digest('cell_msh.tdr')==cfg['mesh_sha256']
                    and cfg['producer_run_id']==match['cfg']['producer_run_id'], 'signal/A0 actual D2 mesh differs')
            device=reader.read('device.cmd');include=reader.read('heavyion.physics.inc')
            require(device==render_signal(match['device'],include)
                    and source_free_deck(device,include)==match['device'], 'source-free signal must exactly reproduce the original A0 deck')
            time=timing(match['device'],p['contract'])
            require(obj(reader.read('source-time-contract.json'))==time,'actual/source timing identity differs')
    require(reader.read('run-parameters.par')==reader.read('physics.par')+b'\n'+reader.read('source.par'),
            'actual source parameters are not exact base bytes + LF + mapped source bytes')
    expected_parameters=parameter_binding(reader)
    require(obj(reader.read('parameter-binding.json'))==expected_parameters, 'active parameter binding differs')
    role=obj(reader.read('role-contract.json'));expected_role=dict(match['role'])
    expected_role.update(schema='dram-see-v4-2d-alpha-role-r1',role='B2D-Aalpha-main-b'+str(bit),case='Aalpha',source_configured=True,
        source_contract_sha256=reader.digest('source-contract.json'),alpha_native_binding_sha256=reader.digest('alpha-native-binding.json'),
        native_syntax_verified=False,native_source_qualified=False)
    require(role==expected_role and cfg.get('role_id')==expected_role['role'],'2D alpha role differs')
    require(bound.get('source_contract_sha256')==reader.digest('source-contract.json')
            and bound.get('source_time_contract_sha256')==reader.digest('source-time-contract.json')
            and bound.get('physics_manifest_sha256')==reader.digest('physics-manifest.json')
            and bound.get('dimensional_contract_sha256')==reader.digest('dimensional-contract.json')
            and bound.get('mesh_sha256')==cfg['mesh_sha256']
            and bound.get('native_source_qualified') is False and bound.get('is_native_result') is False,
            'alpha bound source/timing/width/mesh identity differs')
    result.update(source_spec=source,projection=p,alpha_binding=bound,matched_a0=summary,source_time_contract=time)
    return result


def parameter_binding(reader):
    return dict(schema='dram-see-v4-active-parameters-r1',base_file='physics.par',base_sha256=reader.digest('physics.par'),
        source_file='source.par',source_sha256=reader.digest('source.par'),source_physics_file='heavyion.physics.inc',
        source_physics_sha256=reader.digest('heavyion.physics.inc'),active_file='run-parameters.par',
        active_sha256=reader.digest('run-parameters.par'),aggregation='base_bytes + LF + source_bytes')


def matched_identity(match, manifest, manifest_sha, archive_sha):
    return dict(run_id=manifest['run_id'],manifest_sha256=manifest_sha,archive_sha256=archive_sha,
        input_manifest_sha256=match['input_manifest_sha256'],device_sha256=sha(match['device']),
        producer_run_id=match['cfg']['producer_run_id'],stored_bit=match['role']['stored_bit'],numerical_variant='main',
        circuit_plt_sha256=match['circuit_plt_sha256'],collection_index_sha256=match['collection_index_sha256'],
        original_metric_implementation_sha256=METRICS_SHA,metrics_sha256=sha(encoded(match['metrics'])),
        functional_checks=match['metrics']['checks'],candidate_functional_pass=True,
        duplicate_identical_rows_removed=match['duplicate_identical_rows_removed'],
        native_transient_clock_sha256=sha(encoded(match['native_transient_clock'])),
        native_transient_clock_implementation_sha256=CLOCK_SHA,
        native_engineering_completed=True,refinement_qualified=False,source_qualified=False)


def admit(project, spec, runner_sha, bridge):
    D=dimensional();project=Path(project);cfg=spec['s2_geometry']
    require(cfg.get('schema')==bridge.GEOMETRY_SCHEMA and cfg.get('execution_enabled') is True
            and cfg.get('synthetic') is False and spec.get('execution_enabled') is True,
            'native alpha execution context is missing')
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve()) and not (project/'SYNTHETIC_NOT_NATIVE').exists(),
            'synthetic inputs cannot be submitted')
    contract_path=Path(__file__).with_name('case_contract.py')
    spec0=importlib.util.spec_from_file_location('_alpha2d_current_case_contract',str(contract_path))
    C=importlib.util.module_from_spec(spec0);spec0.loader.exec_module(C)
    request=C.validate(obj((project/'controlled-request.json').read_bytes()))
    require(request['schema']==C.SCHEMA_2D_ALPHA and C.role_id(request)==spec.get('role')==cfg.get('role_id')
            and spec.get('native_threads')==spec.get('native_cores')==1
            and spec.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(D.A0_OUTPUTS))], '2D alpha role or single-step native execution differs')
    bridge.geometry_context(project,cfg,runner_sha)
    hashes=bridge.geometry_input_hashes(project)
    required=set(RUNTIME_FILES)|set(SHARED)|{PROJECTION_PREFIX+n for n in PROJECTION_FILES}|{
        'project.json','controlled-request.json','source-spec.json','source-contract.json','source.par','heavyion.physics.inc',
        'heavyion.plot.inc','heavyion.currentplot.inc','run-parameters.par','parameter-binding.json','device.cmd',
        'alpha-native-binding.json','source-time-contract.json','alpha-projection-implementation.py','role-contract.json',
        'geometry_bridge.py','mesh_resource_guard.py','case_contract.py','task-authorization.json','resource-policy.json'}
    require(required<=set(hashes),'mandatory alpha input absent')
    for n,h in hashes.items():require(D.file_sha(bridge.geometry_path(project,n))==h,'frozen alpha input changed: '+n)
    result=verify_frozen(D.FolderReader(project),cfg)
    require(request['stored_bit']==result['source_spec']['stored_bit']
            and Path(request['d2_source_run']).name==cfg['producer_run_id']
            and Path(request['matched_a0_run']).name==result['matched_a0']['run_id']
            and request['source_epoch_s']==result['projection']['contract']['request']['epoch_s']
            and request['source_observation_window_s']==result['projection']['contract']['source_window_s'], 'request differs from frozen actual inputs')
    require((project/'heavyion.plot.inc').read_bytes()==PLOT.rstrip()+b'\n'
            and (project/'heavyion.currentplot.inc').read_bytes()==CURRENT,'native source field/integral output request differs')
    return cfg


def prepare(request, run_id, runner=None, output=None):
    """Host-only construction; an unfinished/failed A0 cannot produce a run."""
    import case_contract as C
    import geometry_bridge as bridge
    D=dimensional();request=C.validate(request)
    require(request['schema']==C.SCHEMA_2D_ALPHA,'explicit r9 alpha request required')
    require(isinstance(run_id,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',run_id),'unsafe run ID')
    here=Path(__file__).resolve().parent;root=here.parents[3]
    runner=Path(runner or root/'scripts/tcad.py').resolve()
    require(runner==(root/'scripts/tcad.py').resolve() and runner.is_file(),'use the original runner')
    allowed=root/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/alpha-native-integration'
    target=Path(output or allowed/'projects'/run_id).resolve()
    require(allowed.resolve() in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target),
            'new alpha-native-integration directory required')
    request=dict(request)
    for n in ('d2_source_run','matched_a0_run','alpha_projection_package'):request[n]=str(Path(request[n]).resolve())
    source=Path(request['matched_a0_run'])
    require(source.is_dir() and not source.is_symlink() and 'fixture' not in str(source).lower()
            and not (source/'SYNTHETIC_NOT_NATIVE').exists(), 'real original matched A0 run directory required')
    manifest_raw=(source/'manifest.json').read_bytes();manifest=obj(manifest_raw)
    # Check state before attempting any large archive or constructing output.
    require(manifest.get('run_id')==source.name and manifest.get('state')=='COLLECTED', 'matched A0 is not yet completely collected')
    originals={A0_PREFIX+n:dict(path=str(source/n),sha256=D.file_sha(source/n),size_bytes=(source/n).stat().st_size)
               for n in ('manifest.json','results.tar','inputs.tar')}
    require(manifest.get('results_sha256')==originals[A0_PREFIX+'results.tar']['sha256']
            and manifest.get('inputs_archive_sha256')==originals[A0_PREFIX+'inputs.tar']['sha256'], 'A0 receipt/archive hash differs')
    with tarfile.open(str(source/'results.tar'),'r:*') as a,tarfile.open(str(source/'inputs.tar'),'r:*') as i:
        prior=D.ArchiveReader(a);match=_a0(prior,manifest,D.ArchiveReader(i),request['stored_bit'],D)
        require(match['cfg']['producer_run_id']==Path(request['d2_source_run']).name, 'A0 and requested D2 producer differ')
        inherited={n:prior.read(n) for n in SHARED+('metrics.py','controlled-parameters.json')}
    P=_fixed_module('alpha_projection_2d.py',PROJECTION_SHA)
    projected=P.verify(Path(request['alpha_projection_package']))
    native_source_request(projected['contract']['request'])
    source_files={n:(Path(request['alpha_projection_package'])/n).read_bytes() for n in PROJECTION_FILES}
    require(obj(source_files['input-output-manifest.json'])==projected['manifest']
            and obj(source_files['source-contract.json'])==projected['contract']
            and all(sha(source_files[n])==row['sha256'] and len(source_files[n])==row['size_bytes']
                    for n,row in projected['manifest']['files'].items()), 'projection changed after complete mathematical replay')
    for n in ('model.proposed.json','geometry-contract.json','dimensional-contract.json'):
        require(inherited[n]==source_files[n],'projection/A0 input differs: '+n)
    role=C.role_id(request);runner_sha=D.file_sha(runner)
    cfg=dict(match['cfg']);cfg.update(role_id=role,run_id=run_id,source_branch=BRANCH,
        source_run_directory=request['d2_source_run'],execution_enabled=True,synthetic=False)
    bundle=bridge.geometry_source_bundle(target,cfg)
    require(bundle['mesh_sha256']==match['cfg']['mesh_sha256'] and bundle['d2_source_binding_sha256']==match['cfg']['d2_source_binding_sha256'],
            'actual alpha/A0 D2 binding differs')
    files=dict(inherited);files.update(bundle['generated_files'])
    files.update({PROJECTION_PREFIX+n:raw for n,raw in source_files.items()})
    for n in ('source-contract.json','heavyion.physics.inc','source.par'):files[n]=source_files[n]
    files.update({'device.cmd':render_signal(match['device'],files['heavyion.physics.inc']),
        'run-parameters.par':files['physics.par']+b'\n'+files['source.par'],
        'heavyion.plot.inc':PLOT.rstrip()+b'\n','heavyion.currentplot.inc':CURRENT,
        'source-time-contract.json':encoded(timing(match['device'],projected['contract'])),
        'alpha-projection-implementation.py':(here/'alpha_projection_2d.py').read_bytes(),
        'alpha-a0-metrics.py':files['metrics.py']})
    matched=matched_identity(match,manifest,sha(manifest_raw),originals[A0_PREFIX+'results.tar']['sha256'])
    bound=dict(schema=BINDING_SCHEMA,source_branch=BRANCH,stored_bit=request['stored_bit'],verifier_sha256=D.file_sha(__file__),
        projection_verifier_sha256=PROJECTION_SHA,projection_manifest_sha256=sha(source_files['input-output-manifest.json']),
        source_contract_sha256=sha(files['source-contract.json']),source_time_contract_sha256=sha(files['source-time-contract.json']),
        physics_manifest_sha256=sha(files['physics-manifest.json']),dimensional_contract_sha256=sha(files['dimensional-contract.json']),
        mesh_sha256=cfg['mesh_sha256'],matched_a0=matched,
        matched_a0_original_files={n:{k:v for k,v in row.items() if k!='path'} for n,row in originals.items()},
        native_source_qualified=False,is_native_result=False)
    files['alpha-native-binding.json']=encoded(bound);cfg['alpha_native_binding_sha256']=sha(files['alpha-native-binding.json'])
    files['source-spec.json']=encoded(dict(schema=SPEC_SCHEMA,particle='alpha',role='SIGNAL',source_case='Aalpha',dimension=2,
        stored_bit=request['stored_bit'],numerical_variant='main',source_configured=True,
        physics_manifest_sha256=sha(files['physics-manifest.json']),dimensional_contract_sha256=sha(files['dimensional-contract.json']),
        source_contract_sha256=sha(files['source-contract.json']),alpha_native_binding_sha256=cfg['alpha_native_binding_sha256'],
        currentplot_integration_unit='um',currentplot_domain='Semiconductor',native_source_qualified=False))
    class BytesReader:
        def digest(self,name):return sha(files[name])
    files['parameter-binding.json']=encoded(parameter_binding(BytesReader()))
    role_contract=dict(match['role']);role_contract.update(schema='dram-see-v4-2d-alpha-role-r1',role=role,case='Aalpha',source_configured=True,
        source_contract_sha256=sha(files['source-contract.json']),alpha_native_binding_sha256=cfg['alpha_native_binding_sha256'],
        native_syntax_verified=False,native_source_qualified=False)
    files['role-contract.json']=encoded(role_contract)
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-'+role.lower(),role=role,execution_enabled=True,
        runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(D.A0_OUTPUTS))])
    files.update({'project.json':encoded(spec),'controlled-request.json':encoded(request),
        'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',role=role,
            observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',source='current_user_instruction',
            synthetic=False,role_ids=[role],instruction='用户授权二维DRAM主线：真实A0通过后，同网格/物理/电路时序的5MeV alpha信号；原runner/owner/锁及单核单线程；不设项目额度。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',plan_sha256=D.file_sha(root/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md'))),
        'provenance.json':encoded(dict(schema='dram-see-v4-alpha-native-2d-provenance-r1',run_id=run_id,role=role,
            source_dimension=2,matched_a0=matched,projection_manifest_sha256=bound['projection_manifest_sha256'],
            source_free_deck_byte_identical=True,mesh_physics_width_capacitances_timing_unchanged=True,
            first_condition_selection='Fixed A0 ID order: bit0 first, never selected from alpha response',
            native_run_completed=False,native_source_qualified=False,pmi_r12_fixed=False))})
    for n in ('geometry_bridge.py','mesh_resource_guard.py','case_contract.py','two_dimensional.py','alpha_native_2d.py','native_transient_clock.py'):
        files[n]=(here/n).read_bytes()
    files['generator-prepare_case.py']=(here/'prepare_case.py').read_bytes()
    hashes={n:sha(raw) for n,raw in files.items()}
    for n,h in bundle['exports'].items():
        require(n not in hashes or hashes[n]==h,'D2 export collision: '+n);hashes[n]=h
    for n,row in originals.items():require(n not in hashes,'A0 proof collision');hashes[n]=row['sha256']
    files['input-manifest.json']=encoded(dict(schema='dram-see-v4-continuous-inputs-r1',role_id=role,run_id=run_id,files_sha256=hashes))
    files['execution-context.json']=encoded(dict(schema='dram-see-v4-continuous-run-context-r1',run_id=run_id,role_id=role,
        producer_run_id=cfg['producer_run_id'],synthetic=False,expected_runner_sha256=runner_sha,
        input_manifest_sha256=sha(files['input-manifest.json']),authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True,exist_ok=False)
    for n,raw in files.items():bridge.geometry_write(target/n,raw)
    for n,row in originals.items():
        destination=target/n;destination.parent.mkdir(parents=True,exist_ok=True)
        require(D.file_sha(row['path'])==row['sha256'],'original A0 changed during preparation')
        with Path(row['path']).open('rb') as inp,destination.open('xb') as out:
            for block in iter(lambda:inp.read(1048576),b''):out.write(block)
        require(D.file_sha(destination)==row['sha256'],'A0 archive copy differs')
    bridge.geometry_stage_reuse(target,cfg)
    bridge.geometry_admit(target,spec,runner_sha)
    return dict(project=str(target),role_id=role,run_id=run_id,input_manifest_sha256=sha(files['input-manifest.json']),
        expected_runner_sha256=runner_sha,source_dimension=2,matched_a0=matched,mesh_sha256=cfg['mesh_sha256'],
        alpha_native_binding_sha256=cfg['alpha_native_binding_sha256'],native_run_completed=False,native_source_qualified=False)
