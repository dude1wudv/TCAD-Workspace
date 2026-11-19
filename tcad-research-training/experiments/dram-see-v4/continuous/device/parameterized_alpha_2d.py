"""Parameterized development alpha inputs on a real matching r13 2D A0.

No default physical time/gate, scheduler, relabelled A0 or native-positive
fixture. Host replays projection mathematics and the complete A0 reducer;
Python 3.6 guest replays actual collection/clock/metrics and frozen math bytes.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import tarfile

BRANCH = 'dram-see-v4-parameterized-alpha-2d-r1'
REQUEST_SCHEMA = 'dram-see-v4-controlled-device-request-r15'
BINDING_SCHEMA = 'dram-see-v4-parameterized-alpha-2d-binding-r1'
SPEC_SCHEMA = 'dram-see-v4-2d-parameterized-alpha-source-spec-r1'
ROLE_SCHEMA = 'dram-see-v4-2d-parameterized-alpha-role-r1'
TIME_SCHEMA = 'dram-see-v4-parameterized-alpha-2d-native-time-r1'
PARAMETERIZED_SHA = 'ed3363e8891dd261c29508f7fab3d78e9ef3ab10f8687db60ac83494723bfe65'
OPERATION_SHA = '97a5ea8cf6fb64bdfe345adaf09f4aa8f222b8b443d84819fd64c0f447e937a5'
ALPHA_NATIVE_SHA = '9ed322fdc16eb28bf99f82ca32f8b62c3a15219188aaadfd96c1882c1e7b77f7'
D2_SHA = 'c09b52ad56fcdf7e22dfb70ce750b04fd9fa383e1bda8a68ac9121ed768055cd'
CLOCK_SHA = 'bf5d9a8c5520eda054ecadd14fa4fc06f2f3b7296f16483e5ded02ff20ab4387'
METRICS_SHA = '0083e300fd1242d77616597f7a47e075386fff36d991070dd662b414e6f97bc2'
LEGACY_SHA = '14681b6fae30bce49a8b1063b3f8abd7e790e51c6afe58f74da094cd574b2d6e'
PROJECTION_SHA = 'f8e18b4c319dc10e170c5945b5b5b9ef7fa999f35ced4e21bf3f7267e97f1db4'
CORE_PROJECTION_SHA = '16d2fe5e7a182d2ed11e17c197493dac822482ee1c6c6c0da0336a9c86a81f56'
BASELINE_SHA = '8f9a759b26617fff6a416e8336fa57a56d36199d175959a6ed1ba1b49ccb89a2'
REFERENCE_SHA = '82a5b47c685c9156f212787999c07d21d1aee249b22b3f783f89cf499da4e4ec'
ASTAR_SHA = '208f8e36d2f7d231fd6a1134ae3c3a68174b46c6b328dd0f647456a4aabc177b'
DEPENDENCIES = {
    'alpha': ('../proton/alpha_source_v2.py','a75aade10dd65acbab0b3e6af03f86166112125d482e815abc590789a43eed43'),
    'moments': ('../proton/alpha_moments_v2.py','cf0c2b0d43baf8c4021989ed5de8bd162d7767a6fcfa5c68b5d35ade5c7c70c2'),
    'common': ('../projection2d/kernel.py','c9b44b5f808212a018dfa37542bc218410048ba05d9ee211b2bf933bc4d78069')}
PROJECTION_PREFIX = 'alpha-projection/'
A0_PREFIX = 'matched-a0-bindings/'
PROJECTION_FILES = ('alpha-astar-silicon.csv','alpha-profile-2d-native.csv','alpha-profile-3d-reference.csv',
    'dimensional-contract.json','geometry-contract.json','heavyion.physics.inc','input-origins.json','model.proposed.json',
    'projection-ledger.json','projection-request.json','source-contract.json','source.par','energy-source-provenance.json','input-output-manifest.json')
SHARED = ('physics.par','physics-manifest.json','Silicon.par','Oxide.par','model.proposed.json','geometry-contract.json',
    'dimensional-contract.json','numerical-method.json','initialization-contract.json','functional-criteria.json',
    'operation-timing.json','base-operation-timing.json','rendered-operation-timing.json','numerical-relation.json')
RUNTIME_FILES = ('parameterized_alpha_2d.py','parameterized_operating_2d.py','parameterized_baseline_2d.py',
    'alpha_native_2d.py','operating_transient_2d.py','two_dimensional.py','native_transient_clock.py',
    'operating_metrics_2d.py','legacy-circuit-metrics.py')
REQUEST_FIELDS = {'schema','kind','dimension','gate_top_depth_nm','sn_junction_depth_nm','variant','stored_bit',
    'source_case','particle','d2_source_run','base_d2_source_run','effective_width_nm','matched_a0_run','alpha_projection_package',
    'operation_timing_sha256','base_operation_timing_sha256','numerical_relation_sha256','gate_high_V','source_epoch_s',
    'mathematical_source_window_s','native_observation_window_s','simulation_window_s','energy_MeV','theta_deg','phi_deg','amplitude'}
FROZEN_RESULT_KEYS = {'binding','report','source_cfg','dimensional_contract','operation_timing','operating_binding',
    'source_spec','role_contract','numerical_relation','projection','alpha_binding','matched_a0','source_time_contract'}


def require(ok,message):
    if not ok: raise ValueError('Parameterized 2D alpha: '+message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')
def obj(raw):
    value=json.loads(raw.decode('utf-8'));require(isinstance(value,dict),'expected JSON object');return value
def number(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except (ValueError,OverflowError):return False
def module(name,expected=None,data=False):
    path=Path(__file__).with_name(name)
    if not path.is_file() and data:path=Path(__file__).resolve().parent.parent/'data'/name
    require(path.is_file() and not path.is_symlink(),'missing closed local module '+name)
    if expected is not None:require(sha(path.read_bytes())==expected,'fixed implementation changed: '+name)
    spec=importlib.util.spec_from_file_location('_parameterized_alpha_'+name.replace('.','_'),str(path))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
def parameterized():return module('parameterized_operating_2d.py',PARAMETERIZED_SHA)
def operation():return module('operating_transient_2d.py',OPERATION_SHA)
def alpha():return module('alpha_native_2d.py',ALPHA_NATIVE_SHA)
def dimensional():return module('two_dimensional.py',D2_SHA)
def baseline_api():return module('parameterized_baseline_2d.py',BASELINE_SHA,data=True)


def validate_request(request):
    O=operation()
    require(isinstance(request,dict) and set(request)==REQUEST_FIELDS,'exact r15 fields required')
    require(request['schema']==REQUEST_SCHEMA and request['kind']=='transient' and request['source_case']=='Aalpha'
        and request['particle']=='alpha' and request['variant'] in ('main','h2','dt2'),'explicit development alpha variant required')
    for key,value in (('dimension',2),('sn_junction_depth_nm',87),('effective_width_nm',20)):
        require(type(request[key]) is int and request[key]==value,'fixed physical contract differs: '+key)
    require(type(request['gate_top_depth_nm']) is int and request['gate_top_depth_nm'] in (70,80),'only gate70/80 development')
    require(type(request['stored_bit']) is int and request['stored_bit'] in (0,1),'integer bit required')
    for key in ('d2_source_run','base_d2_source_run','matched_a0_run','alpha_projection_package'):
        require(isinstance(request[key],str) and request[key].strip(),'explicit input path missing: '+key)
    for key in ('operation_timing_sha256','base_operation_timing_sha256','numerical_relation_sha256'):
        require(O.digest_ok(request[key]),'explicit frozen identity missing: '+key)
    require(number(request['gate_high_V']) and request['gate_high_V']>-.5 and number(request['source_epoch_s'])
        and request['source_epoch_s']>0,'explicit finite gate/source epoch required')
    require(type(request['energy_MeV']) is int and request['energy_MeV'] in (3,5)
        and type(request['theta_deg']) is int and request['theta_deg'] in (0,30)
        and type(request['phi_deg']) is int and request['phi_deg']==180
        and number(request['amplitude']) and request['amplitude']==1,'only actual E3/E5, 0/30deg, phi180, amplitude1')
    for key in ('mathematical_source_window_s','native_observation_window_s','simulation_window_s'):
        w=request[key]
        require(isinstance(w,list) and len(w)==2 and all(number(v) for v in w)
            and 0<=w[0]<request['source_epoch_s']<w[1],'explicit physical window required: '+key)
    full=request['simulation_window_s']
    require(full[0]==0 and all(full[0]<request[n][0]<request[n][1]<full[1]
        for n in ('mathematical_source_window_s','native_observation_window_s')),'source windows must lie inside full physical time')
    return obj(encoded(request))


def role_id(request):
    r=validate_request(request)
    return 'B2D-Aalpha-parameterized-r1-'+r['variant']+'-b'+str(r['stored_bit'])


def source_request(value,timing,request):
    expected=dict(schema='dram-see-v4-parameterized-alpha-projection-request-r1',gate_top_depth_nm=request['gate_top_depth_nm'],
        energy_MeV=request['energy_MeV'],theta_deg=request['theta_deg'],phi_deg=180,amplitude=1.,
        epoch_s=timing['source_epoch_s'],simulation_window_s=timing['simulation_window_s'])
    require(value==expected,'projection energy/geometry/direction or physical time differs from request/actual A0')
    return value


def source_time_contract(a0_device,contract,timing,request):
    O=operation();A=alpha();timing=O.validate_timing(timing);source_request(contract['request'],timing,request)
    require(contract['source_window_s']==timing['mathematical_source_window_s']
        and contract['full_simulation_window_s']==timing['simulation_window_s'],'projection mathematical/full physical windows differ')
    clock=module('native_transient_clock.py',CLOCK_SHA);segments,_=clock._deck(a0_device)
    require([(float(s['initial_literal']),float(s['final_literal'])) for s in segments]
        ==[(s['start_s'],s['end_s']) for s in timing['segments']],'actual A0 physical Solve segments differ')
    n=A.NUMBER.encode('ascii')
    matches=re.findall(rb'Plot\(FilePrefix="source_window" Time=\(Range=\(('+n+rb') ('+n+rb')\)\) NoOverwrite\)',a0_device)
    windows=[[v.decode('ascii') for v in pair] for pair in matches];actual=[[float(v) for v in pair] for pair in windows]
    native=timing['native_observation_window_s']
    expected=[[s['start_s'],s['end_s']] for s in timing['segments'] if native[0]<=s['start_s'] and s['end_s']<=native[1]]
    require(actual and actual==expected and actual[0][0]==native[0] and actual[-1][1]==native[1]
        and all(a[1]==b[0] for a,b in zip(actual,actual[1:])),'all actual NoOverwrite segments must cover exact native observation window')
    return dict(schema=TIME_SCHEMA,source_epoch_s=timing['source_epoch_s'],full_simulation_window_s=timing['simulation_window_s'],
        mathematical_source_window_s=timing['mathematical_source_window_s'],native_observation_window_s=native,
        native_observation_segment_literals=windows,native_segments=segments,
        native_minus_mathematical_window_s=[x-y for x,y in zip(native,timing['mathematical_source_window_s'])],
        time_remapped=False,additional_normalization=False,observation_window_is_not_physical_source_truncation=True,
        native_source_clock_qualified=False)


def render_signal(a0_device,include):return alpha().render_signal(a0_device,include)
def source_free_deck(device,include):return alpha().source_free_deck(device,include)


def verify_matched_a0(reader,manifest,inputs,request):
    """Replay original r13 only; no JSON-pass-only or old-A0 relabelling."""
    P=parameterized();O=operation();D=dimensional();A=alpha()
    r=validate_request(request);project=obj(reader.read('project.json'));cfg=project.get('s2_geometry',{})
    context=obj(reader.read('execution-context.json'))
    wanted='B2D-A0-parameterized-r1-'+r['variant']+'-b'+str(r['stored_bit'])
    require(project.get('role')==cfg.get('role_id')==context.get('role_id')==wanted
        and cfg.get('parameterized_operating_branch')==P.BRANCH,'real same-bit/variant r13 A0 required; old roles cannot be relabelled')
    A._collection(reader,manifest,inputs,D)
    require(cfg.get('run_id')==manifest['run_id'] and cfg.get('synthetic') is False and cfg.get('mode')=='reuse'
        and cfg.get('execution_enabled') is True and project.get('execution_enabled') is True
        and context.get('producer_run_id')==cfg.get('producer_run_id')
        and obj(reader.read('input-manifest.json')).get('role_id')==wanted
        and project.get('native_threads')==project.get('native_cores')==1
        and project.get('steps')==manifest.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))],
        'matched native/source/serial-step identity differs')
    audited=baseline_api().audit_reader(reader,cfg)
    require(set(audited)=={'frozen','clock','metrics','identity'},'fixed baseline public interface differs')
    verified=audited['frozen'];clock=audited['clock'];metrics=audited['metrics'];t=verified['operation_timing']
    require(t['origin']=='prescribed_input' and metrics.get('candidate_functional_pass') is True
        and len(metrics.get('checks',{}))==5 and all(v is True for v in metrics['checks'].values()),
        'real matching A0 original five criteria/KCL failed: '+json.dumps(metrics.get('checks'),sort_keys=True))
    require(metrics['accepted_trace']==clock['trace'] and metrics['time_coordinate_transformed'] is False
        and metrics['training_admitted'] is False and audited['identity']['complete_clock_evidence_verified'] is True,
        'all original real-time rows and original clock evidence required')
    shared={n:reader.read(n) for n in SHARED}
    shared.update({'operation-selection/'+n:reader.read('operation-selection/'+n) for n in t['selection_provenance']['references']})
    return dict(verified=verified,project=project,cfg=cfg,role=verified['role_contract'],device=reader.read('device.cmd'),
        metrics=metrics,clock=clock,reader_identity=audited['identity'],shared=shared,
        input_manifest_sha256=reader.digest('input-manifest.json'),circuit_plt_sha256=reader.digest('circuit.plt'),
        collection_index_sha256=reader.digest('_collection-members.json'),
        operating_binding_sha256=reader.digest('parameterized-operating-binding.json'))


def matched_identity(match,manifest,manifest_sha,archive_sha):
    b=match['verified']['binding'];selected=b['sources']['selected']['record'];base=b['sources'][b['base_source_key']]['record'];cfg=match['cfg']
    return dict(run_id=manifest['run_id'],manifest_sha256=manifest_sha,archive_sha256=archive_sha,
        input_manifest_sha256=match['input_manifest_sha256'],device_sha256=sha(match['device']),
        producer_run_id=selected['run_id'],base_producer_run_id=base['run_id'],mesh_sha256=selected['mesh_sha256'],base_mesh_sha256=base['mesh_sha256'],
        stored_bit=cfg['stored_bit'],numerical_variant=cfg['numerical_variant'],gate_top_depth_nm=cfg['gate_top_depth_nm'],
        sn_junction_depth_nm=87,effective_width_nm=20,operation_timing_sha256=sha(match['shared']['operation-timing.json']),
        base_operation_timing_sha256=sha(match['shared']['base-operation-timing.json']),numerical_relation_sha256=sha(match['shared']['numerical-relation.json']),
        gate_high_V=cfg['gate_high_V'],operating_binding_sha256=match['operating_binding_sha256'],
        circuit_plt_sha256=match['circuit_plt_sha256'],collection_index_sha256=match['collection_index_sha256'],
        baseline_implementation_sha256=BASELINE_SHA,metrics_implementation_sha256=METRICS_SHA,
        metrics_sha256=sha(encoded(match['metrics'])),functional_checks=match['metrics']['checks'],candidate_functional_pass=True,
        clock_sha256=sha(encoded(match['clock'])),clock_implementation_sha256=CLOCK_SHA,
        reader_only_identity=match['reader_identity'],original_collection_chain_replayed=True,
        all_original_rows_and_attempts_retained=True,native_engineering_completed=True,refinement_qualified=False,source_qualified=False)


def request_matches(request,timing,matched,cfg):
    O=operation()
    for name in ('stored_bit','gate_top_depth_nm','sn_junction_depth_nm','effective_width_nm','gate_high_V',
                 'operation_timing_sha256','base_operation_timing_sha256','numerical_relation_sha256'):
        require(request[name]==cfg[name]==matched[name],'request differs from real A0: '+name)
    require(request['variant']==cfg['numerical_variant']==matched['numerical_variant']
        and O.source_name(request['matched_a0_run'])==matched['run_id']
        and O.source_name(request['d2_source_run'])==matched['producer_run_id']==cfg['producer_run_id']
        and O.source_name(request['base_d2_source_run'])==matched['base_producer_run_id']
        and request['gate_high_V']==timing['voltage_levels_V']['gate_high_V'],'real matching source/variant/gate differs')
    for name in ('source_epoch_s','mathematical_source_window_s','native_observation_window_s','simulation_window_s'):
        require(request[name]==timing[name],'request must retain actual physical times: '+name)


def projection(reader,timing,request):
    manifest=obj(reader.read(PROJECTION_PREFIX+'input-output-manifest.json'))
    require(manifest.get('schema')=='dram-see-v4-parameterized-alpha-2d-input-output-manifest-r1'
        and manifest.get('implementation_sha256')==PROJECTION_SHA and manifest.get('core_projection_sha256')==CORE_PROJECTION_SHA
        and manifest.get('is_native_result') is False and manifest.get('native_source_qualified') is False
        and set(manifest.get('files',{}))==set(PROJECTION_FILES)-{'input-output-manifest.json'},'new frozen projection identity differs')
    for name,row in manifest['files'].items():
        require(row==dict(sha256=reader.digest(PROJECTION_PREFIX+name),size_bytes=reader.size(PROJECTION_PREFIX+name)),'projection bytes differ: '+name)
    for name,digest in (('alpha-projection-implementation.py',PROJECTION_SHA),('alpha-projection-core.py',CORE_PROJECTION_SHA),
                        ('alpha-projection-reference.py',REFERENCE_SHA)):
        require(reader.digest(name)==digest,'fixed mathematical snapshot differs: '+name)
    for key,(_,digest) in DEPENDENCIES.items():require(reader.digest('alpha-projection-dependency-'+key+'.py')==digest,'fixed dependency snapshot differs: '+key)
    contract=obj(reader.read(PROJECTION_PREFIX+'source-contract.json'))
    require(contract.get('schema')=='dram-see-v4-parameterized-alpha-projection-2d-r1' and contract.get('particle')=='alpha'
        and contract.get('dimension')==2 and contract.get('native_source_qualified') is False
        and contract.get('is_tcad_result') is False and contract.get('pmi_r12_fixed') is False
        and contract.get('core_projection_sha256')==CORE_PROJECTION_SHA
        and contract.get('dependency_sha256')=={k:dict(path=p,sha256=h) for k,(p,h) in DEPENDENCIES.items()}
        and contract.get('independent_reference_sha256')==REFERENCE_SHA and contract.get('astar_sha256')==ASTAR_SHA,
        'projection semantic/physical source identity differs')
    source_request(contract['request'],timing,request)
    require(obj(reader.read(PROJECTION_PREFIX+'projection-request.json'))==contract['request']
        and contract['source_window_s']==timing['mathematical_source_window_s']
        and contract['full_simulation_window_s']==timing['simulation_window_s'],'projection physical windows differ')
    for name in ('model.proposed.json','geometry-contract.json','dimensional-contract.json'):
        require(reader.digest(name)==reader.digest(PROJECTION_PREFIX+name)==contract['input_sha256'][name],'actual Si/model/width differs: '+name)
    require(reader.digest(PROJECTION_PREFIX+'alpha-astar-silicon.csv')==ASTAR_SHA==contract['input_sha256']['alpha-astar-silicon.csv'],'ASTAR original table differs')
    for name,digest in contract['derived_files_sha256'].items():require(reader.digest(PROJECTION_PREFIX+name)==digest,'derived byte identity differs: '+name)
    energy=obj(reader.read(PROJECTION_PREFIX+'energy-source-provenance.json'))
    ledger=obj(reader.read(PROJECTION_PREFIX+'projection-ledger.json'))
    require(reader.digest(PROJECTION_PREFIX+'energy-source-provenance.json')==contract['energy_source_provenance_sha256']
        and energy['stopping_table_sha256']==ASTAR_SHA and energy['stopping_source_sha256']==DEPENDENCIES['alpha'][1]
        and energy['incident_energy_MeV']==request['energy_MeV']==ledger['energy']['entry_energy_MeV']
        and energy['trajectory_energy_ledger']==ledger['energy'] and energy['mass_stopping_to_MeV_per_um']==2.33e-4
        and energy['eV_per_pair']==3.6 and energy['native_source_qualified'] is False,'actual-energy provenance differs')
    for name in ('source-contract.json','heavyion.physics.inc','source.par'):
        require(reader.read(name)==reader.read(PROJECTION_PREFIX+name),'active source bytes differ: '+name)
    require(contract['mesh_sha256']==reader.digest('cell_msh.tdr') and contract['physics_manifest_sha256']==reader.digest('physics-manifest.json'),
        'projection actual selected mesh/physics differs')
    return dict(contract=contract,ledger=ledger,manifest=manifest,energy_source_provenance=energy,guest_mathematical_replay=False,
        guest_scope='Closed frozen mathematical identities only; full new projection verify runs on host prepare')


def source_spec(reader,request,binding_sha):
    return dict(schema=SPEC_SCHEMA,particle='alpha',role='SIGNAL',source_case='Aalpha',dimension=2,stored_bit=request['stored_bit'],
        numerical_variant=request['variant'],gate_top_depth_nm=request['gate_top_depth_nm'],energy_MeV=request['energy_MeV'],
        theta_deg=request['theta_deg'],phi_deg=180,amplitude=1,source_configured=True,
        energy_definition='kinetic at Si surface; charge only electronic ASTAR loss / 3.6eV; nuclear loss retained separately',
        physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),base_operation_timing_sha256=reader.digest('base-operation-timing.json'),
        numerical_relation_sha256=reader.digest('numerical-relation.json'),source_contract_sha256=reader.digest('source-contract.json'),
        source_time_contract_sha256=reader.digest('source-time-contract.json'),parameterized_alpha_binding_sha256=binding_sha,
        currentplot_integration_unit='um',currentplot_domain='Semiconductor',currentplot_is_diagnostic_not_field_qualification=True,
        native_source_qualified=False)


def role_contract(match,role,binding_sha,source_sha,request):
    value=dict(match['role']);value.pop('parameterized_operating_binding_sha256')
    value.update(schema=ROLE_SCHEMA,role=role,case='Aalpha',source_configured=True,
        matched_a0_operating_binding_sha256=match['operating_binding_sha256'],parameterized_alpha_binding_sha256=binding_sha,
        energy_MeV=request['energy_MeV'],theta_deg=request['theta_deg'],phi_deg=180,amplitude=1,
        source_contract_sha256=source_sha,native_syntax_verified=False,native_source_qualified=False)
    return value


def binding(reader,cfg,match,matched,originals):
    return dict(schema=BINDING_SCHEMA,source_branch=BRANCH,stored_bit=cfg['stored_bit'],producer_run_id=cfg['producer_run_id'],
        gate_top_depth_nm=cfg['gate_top_depth_nm'],numerical_variant=cfg['numerical_variant'],
        verifier_sha256=sha(Path(__file__).read_bytes()),old_alpha_adapter_sha256=ALPHA_NATIVE_SHA,
        parameterized_operation_verifier_sha256=PARAMETERIZED_SHA,baseline_verifier_sha256=BASELINE_SHA,
        projection_verifier_sha256=PROJECTION_SHA,projection_core_sha256=CORE_PROJECTION_SHA,
        projection_manifest_sha256=reader.digest(PROJECTION_PREFIX+'input-output-manifest.json'),
        source_contract_sha256=reader.digest('source-contract.json'),source_time_contract_sha256=reader.digest('source-time-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),base_operation_timing_sha256=reader.digest('base-operation-timing.json'),
        numerical_relation_sha256=reader.digest('numerical-relation.json'),gate_high_V=match['cfg']['gate_high_V'],
        physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        mesh_sha256=cfg['mesh_sha256'],matched_a0=matched,matched_a0_original_files=originals,
        mathematical_policy='New parameterized projection host verify; fixed16d2 integration/render core; guest frozen bytes only',
        additional_normalization=False,native_source_qualified=False,is_native_result=False,pmi_r12_fixed=False,training_admitted=False)


def _runtime_bytes():
    result=parameterized()._runtime_bytes();here=Path(__file__).resolve().parent
    result['parameterized_alpha_2d.py']=Path(__file__).read_bytes()
    result['alpha_native_2d.py']=(here/'alpha_native_2d.py').read_bytes()
    B=baseline_api();result['parameterized_baseline_2d.py']=Path(B.__file__).read_bytes()
    require(set(result)==set(RUNTIME_FILES) and sha(result['alpha_native_2d.py'])==ALPHA_NATIVE_SHA,'closed runtime set differs')
    return result


def verify_frozen(reader,cfg):
    P=parameterized();D=dimensional();A=alpha()
    require(cfg.get('source_branch')==BRANCH and cfg.get('dimension_branch')==P.DIMENSION_BRANCH and cfg.get('mode')=='reuse'
        and 'parameterized_operating_branch' not in cfg,'explicit alpha root, never pretend A0 verification at root')
    for name,raw in _runtime_bytes().items():require(reader.digest(name)==sha(raw),'closed runtime differs: '+name)
    result,_,_=P._verify_sources(reader,cfg);request=validate_request(obj(reader.read('controlled-request.json')))
    bound=obj(reader.read('parameterized-alpha-binding.json'))
    require(bound.get('schema')==BINDING_SCHEMA and reader.digest('parameterized-alpha-binding.json')==cfg.get('parameterized_alpha_binding_sha256'),'alpha binding identity differs')
    originals=bound.get('matched_a0_original_files',{})
    require(set(originals)=={A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')},'complete original matched A0 proof required')
    for name,row in originals.items():require(row==dict(sha256=reader.digest(name),size_bytes=reader.size(name)),'original matched A0 bytes differ: '+name)
    manifest=obj(reader.read(A0_PREFIX+'manifest.json'))
    require(manifest.get('results_sha256')==reader.digest(A0_PREFIX+'results.tar')
        and manifest.get('inputs_archive_sha256')==reader.digest(A0_PREFIX+'inputs.tar'),'matched A0 original outer receipt differs')
    with reader.stream(A0_PREFIX+'results.tar') as a,reader.stream(A0_PREFIX+'inputs.tar') as i:
        with tarfile.open(fileobj=a,mode='r:*') as archive,tarfile.open(fileobj=i,mode='r:*') as inputs:
            prior=D.ArchiveReader(archive);match=verify_matched_a0(prior,manifest,D.ArchiveReader(inputs),request)
            matched=matched_identity(match,manifest,reader.digest(A0_PREFIX+'manifest.json'),reader.digest(A0_PREFIX+'results.tar'))
            for name,value in match['shared'].items():require(reader.read(name)==value,'signal/A0 unchanged physical/numerical input differs: '+name)
            require(reader.digest('cell_msh.tdr')==prior.digest('cell_msh.tdr')==cfg['mesh_sha256']
                and reader.read('d2-source-binding.json')==prior.read('d2-source-binding.json'),'signal/A0 actual source/mesh identity differs')
            timing=match['verified']['operation_timing'];request_matches(request,timing,matched,cfg)
            projected=projection(reader,timing,request);time=source_time_contract(match['device'],projected['contract'],timing,request)
            include=reader.read('heavyion.physics.inc');device=reader.read('device.cmd')
            require(device==A.render_signal(match['device'],include) and A.source_free_deck(device,include)==match['device'],
                'strip-alpha deck must equal actual matching A0 bytes')
            require(obj(reader.read('source-time-contract.json'))==time,'physical/native time declarations differ')
    require(reader.read('run-parameters.par')==reader.read('physics.par')+b'\n'+reader.read('source.par')
        and obj(reader.read('parameter-binding.json'))==A.parameter_binding(reader),'base/source parameter binding differs')
    require(bound==binding(reader,cfg,match,matched,originals),'complete source/A0/variant binding differs')
    spec=source_spec(reader,request,reader.digest('parameterized-alpha-binding.json'))
    role=role_contract(match,role_id(request),reader.digest('parameterized-alpha-binding.json'),reader.digest('source-contract.json'),request)
    require(obj(reader.read('source-spec.json'))==spec and obj(reader.read('role-contract.json'))==role
        and cfg['role_id']==role['role'],'alpha role/source declaration differs')
    require(reader.read('heavyion.plot.inc')==A.PLOT.rstrip()+b'\n' and reader.read('heavyion.currentplot.inc')==A.CURRENT,'source diagnostics differ')
    result.update(operation_timing=timing,operating_binding=match['verified']['operating_binding'],
        numerical_relation=match['verified']['numerical_relation'],source_spec=spec,role_contract=role,
        projection=projected,alpha_binding=bound,matched_a0=matched,source_time_contract=time)
    require(set(result)==FROZEN_RESULT_KEYS,'public result shape differs')
    return result


def admit(project,spec,runner_sha,bridge):
    project=Path(project);O=operation();D=dimensional();cfg=spec['s2_geometry']
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve()) and not (project/'SYNTHETIC_NOT_NATIVE').exists(),'UNIT fixture cannot be submitted')
    r=validate_request(obj((project/'controlled-request.json').read_bytes()))
    require(cfg.get('schema')==bridge.GEOMETRY_SCHEMA and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
        and spec.get('execution_enabled') is True and spec.get('role')==cfg.get('role_id')==role_id(r)
        and O.plain_name(cfg.get('run_id')) and cfg.get('run_id') not in (cfg['producer_run_id'],O.source_name(r['matched_a0_run']))
        and spec.get('native_threads')==spec.get('native_cores')==1
        and spec.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))],'native role/serial-step contract differs')
    bridge.geometry_context(project,cfg,runner_sha);hashes=bridge.geometry_input_hashes(project)
    d2_binding=obj((project/'d2-source-binding.json').read_bytes())
    required=set(D.SHARED_INPUTS)|set(RUNTIME_FILES)|set(SHARED)|set(d2_binding['original_files'])|{
        'project.json','controlled-request.json','case_contract.py','geometry_bridge.py','mesh_resource_guard.py','task-authorization.json','resource-policy.json',
        'device.cmd','cell_msh.tdr','cell_msh.log','d2-source-binding.json','dimensional-contract.json','source-contract.json','source.par',
        'heavyion.physics.inc','heavyion.plot.inc','heavyion.currentplot.inc','run-parameters.par','parameter-binding.json',
        'source-time-contract.json','parameterized-alpha-binding.json','source-spec.json','role-contract.json',
        'alpha-projection-implementation.py','alpha-projection-core.py','alpha-projection-reference.py'}|{
        PROJECTION_PREFIX+n for n in PROJECTION_FILES}|{A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}|{
        'alpha-projection-dependency-'+key+'.py' for key in DEPENDENCIES}
    require(required<=set(hashes),'mandatory original alpha/matched-A0 proof missing')
    for name,digest in hashes.items():require(D.file_sha(bridge.geometry_path(project,name))==digest,'frozen input changed: '+name)
    manifest=obj((project/'input-manifest.json').read_bytes())
    require(manifest.get('run_id')==cfg['run_id'] and manifest.get('role_id')==cfg['role_id'],'input manifest identity differs')
    result=verify_frozen(D.FolderReader(project),cfg)
    require(result['operation_timing']['origin']=='prescribed_input','UNIT timing cannot be submitted')
    require(obj((project/'resource-policy.json').read_bytes())==dict(schema='dram-see-v4-actual-resource-policy-r1',role=cfg['role_id'],
        observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None),'actual resource observations only; no quota or approval')
    return cfg


def prepare(request,run_id,runner=None,output=None):
    """Future real input: full original A0 and new projection replay before writes."""
    r=validate_request(request);P=parameterized();O=operation();D=dimensional();A=alpha()
    C=module('case_contract.py');bridge=module('geometry_bridge.py')
    require(getattr(C,'SCHEMA_2D_PARAMETERIZED_ALPHA',None)==REQUEST_SCHEMA and hasattr(bridge,'geometry_parameterized_alpha_module'),
        'r15 dispatch is not integrated; no project directory created')
    require(O.plain_name(run_id) and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id
        and run_id not in (O.source_name(r['d2_source_run']),O.source_name(r['matched_a0_run'])),'new nonfixture run ID required')
    here=Path(__file__).resolve().parent;root=here.parents[3];runner=Path(runner or root/'scripts/tcad.py').resolve()
    require(runner==(root/'scripts/tcad.py').resolve() and runner.is_file(),'original runner required')
    allowed=(root/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/parameterized-alpha-implementation-r1').resolve()
    target=Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target),'new allowed project directory required')
    r=dict(r)
    for name in ('d2_source_run','base_d2_source_run','matched_a0_run','alpha_projection_package'):r[name]=str(Path(r[name]).resolve())
    source=Path(r['matched_a0_run'])
    require(source.is_dir() and not source.is_symlink() and 'fixture' not in str(source).lower()
        and not (source/'SYNTHETIC_NOT_NATIVE').exists(),'real original matched A0 required')
    host=baseline_api().reduce_archive(source)
    require(host.get('native_engineering_chain_verified') is True and host.get('complete_clock_evidence_verified') is True
        and host.get('candidate_functional_pass') is True,'complete host A0 native/clock/five-criterion replay required')
    # Refinement comparison is intentionally separate; pending main does not
    # qualify convergence and does not erase this actual variant's five checks.
    manifest_raw=(source/'manifest.json').read_bytes();manifest=obj(manifest_raw)
    require(manifest.get('run_id')==source.name and manifest.get('state')=='COLLECTED','actual matched A0 must be completely collected')
    originals={A0_PREFIX+n:dict(path=str(source/n),sha256=D.file_sha(source/n),size_bytes=(source/n).stat().st_size)
        for n in ('manifest.json','results.tar','inputs.tar')}
    require(manifest.get('results_sha256')==originals[A0_PREFIX+'results.tar']['sha256']
        and manifest.get('inputs_archive_sha256')==originals[A0_PREFIX+'inputs.tar']['sha256'],'matched original archive/receipt differs')
    with tarfile.open(str(source/'results.tar'),'r:*') as a,tarfile.open(str(source/'inputs.tar'),'r:*') as i:
        match=verify_matched_a0(D.ArchiveReader(a),manifest,D.ArchiveReader(i),r)
    require(host['candidate_metrics']==match['metrics'],'host and frozen-reader metrics must match exact original trace')
    math_api=module('parameterized_alpha_projection_2d.py',PROJECTION_SHA)
    projected=math_api.verify(Path(r['alpha_projection_package']))
    source_request(projected['contract']['request'],match['verified']['operation_timing'],r)
    packet={n:(Path(r['alpha_projection_package'])/n).read_bytes() for n in PROJECTION_FILES}
    require(obj(packet['input-output-manifest.json'])==projected['manifest']
        and all(sha(packet[n])==row['sha256'] and len(packet[n])==row['size_bytes'] for n,row in projected['manifest']['files'].items()),
        'projection changed after full host mathematical replay')
    matched=matched_identity(match,manifest,sha(manifest_raw),originals[A0_PREFIX+'results.tar']['sha256'])
    role=role_id(r);cfg=dict(match['cfg']);cfg.pop('parameterized_operating_branch');cfg.pop('parameterized_operating_binding_sha256')
    cfg.update(role_id=role,run_id=run_id,source_branch=BRANCH,source_run_directory=r['d2_source_run'],
        base_source_run_directory=r['base_d2_source_run'],execution_enabled=True,synthetic=False)
    request_matches(r,match['verified']['operation_timing'],matched,cfg)
    bundle=P.source_bundle(target,cfg)
    require(bundle['mesh_sha256']==match['cfg']['mesh_sha256'] and bundle['d2_source_binding_sha256']==match['cfg']['d2_source_binding_sha256'],
        'signal/A0 actual selected/base D2 identity differs')
    files=dict(match['shared']);files.update(bundle['generated_files']);files.update({PROJECTION_PREFIX+n:v for n,v in packet.items()})
    for name in ('source-contract.json','heavyion.physics.inc','source.par'):files[name]=packet[name]
    time=source_time_contract(match['device'],projected['contract'],match['verified']['operation_timing'],r)
    files.update({'device.cmd':A.render_signal(match['device'],packet['heavyion.physics.inc']),
        'run-parameters.par':files['physics.par']+b'\n'+packet['source.par'],'source-time-contract.json':encoded(time),
        'heavyion.plot.inc':A.PLOT.rstrip()+b'\n','heavyion.currentplot.inc':A.CURRENT,
        'alpha-projection-implementation.py':(here/'parameterized_alpha_projection_2d.py').read_bytes(),
        'alpha-projection-core.py':(here/'alpha_projection_2d.py').read_bytes(),
        'alpha-projection-reference.py':(here/'../proton/source_reference.py').read_bytes()})
    for key,(relative,digest) in DEPENDENCIES.items():
        raw=(here/relative).read_bytes();require(sha(raw)==digest,'fixed mathematical dependency changed');files['alpha-projection-dependency-'+key+'.py']=raw
    class BytesReader:
        def read(self,name):return files[name]
        def digest(self,name):return sha(files[name])
        def size(self,name):return len(files[name])
    check=BytesReader()
    for name in ('model.proposed.json','geometry-contract.json','dimensional-contract.json'):
        require(files[name]==packet[name],'actual source/A0 model/Si/width differs: '+name)
    files['parameter-binding.json']=encoded(A.parameter_binding(check))
    bound=binding(check,cfg,match,matched,{n:{k:v for k,v in row.items() if k!='path'} for n,row in originals.items()})
    files['parameterized-alpha-binding.json']=encoded(bound);cfg['parameterized_alpha_binding_sha256']=sha(files['parameterized-alpha-binding.json'])
    files['source-spec.json']=encoded(source_spec(check,r,cfg['parameterized_alpha_binding_sha256']))
    files['role-contract.json']=encoded(role_contract(match,role,cfg['parameterized_alpha_binding_sha256'],sha(files['source-contract.json']),r))
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-'+role.lower(),role=role,execution_enabled=True,
        runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))])
    files.update({'project.json':encoded(spec),'controlled-request.json':encoded(r),
        'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',role=role,observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',source='current_user_instruction',synthetic=False,role_ids=[role],
            instruction='真实对应r13 A0五项通过后，70/80nm开发二维alpha；实际同bit/网格/物理/时序、20nm、3/5MeV及0/30度，原runner/owner/共享锁，串行单核单线程，不设置项目额度。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',plan_sha256=D.file_sha(root/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md'))),
        'provenance.json':encoded(dict(schema='dram-see-v4-parameterized-alpha-input-provenance-r1',run_id=run_id,role=role,matched_a0=matched,
            host_A0_engineering_chain_replayed=True,host_A0_clock_and_metrics_replayed=True,
            host_refinement_comparison=host['refinement_comparison'],refinement_qualified=False,
            host_projection_mathematics_replayed=True,projection_manifest_sha256=sha(packet['input-output-manifest.json']),
            energy_source_provenance_sha256=sha(packet['energy-source-provenance.json']),source_free_deck_byte_identical=True,
            actual_operation_timing_sha256=cfg['operation_timing_sha256'],gate_high_V=cfg['gate_high_V'],
            new_time_or_gate_selected_by_generator=False,additional_normalization=False,native_run_completed=False,
            native_source_qualified=False,pmi_r12_fixed=False,training_admitted=False))})
    for name in ('geometry_bridge.py','mesh_resource_guard.py','case_contract.py'):files[name]=(here/name).read_bytes()
    files.update(_runtime_bytes());files['generator-prepare_case.py']=(here/'prepare_case.py').read_bytes()
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
        require(D.file_sha(row['path'])==row['sha256'],'matched original A0 changed during preparation')
        path=target/name;path.parent.mkdir(parents=True,exist_ok=True)
        with Path(row['path']).open('rb') as inp,path.open('xb') as out:
            for block in iter(lambda:inp.read(1048576),b''):out.write(block)
        require(D.file_sha(path)==row['sha256'],'original matched A0 archive copy differs')
    bridge.geometry_stage_reuse(target,cfg);bridge.geometry_admit(target,spec,runner_sha)
    return dict(project=str(target),run_id=run_id,role_id=role,matched_a0=matched,operation_timing_sha256=cfg['operation_timing_sha256'],
        numerical_relation_sha256=cfg['numerical_relation_sha256'],gate_high_V=cfg['gate_high_V'],
        parameterized_alpha_binding_sha256=cfg['parameterized_alpha_binding_sha256'],input_manifest_sha256=sha(files['input-manifest.json']),
        native_submissions=0,native_source_qualified=False,refinement_qualified=False,training_admitted=False)
