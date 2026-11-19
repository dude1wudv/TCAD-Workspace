"""First real-batch 2D proton input spine, never a native-source qualification.

Host: fixed complete G4/source mathematics, actual new PMI build and actual A0
replay. Guest: Python 3.6 closed runtime, archive/input/exit identity, full A0
clock/metrics and frozen source consistency. No archived code is executed.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BRANCH = 'dram-see-v4-parameterized-proton-2d-r1'
REQUEST_SCHEMA = 'dram-see-v4-parameterized-proton-request-r1'
BINDING_SCHEMA = 'dram-see-v4-parameterized-proton-binding-r1'
SPEC_SCHEMA = 'dram-see-v4-parameterized-proton-source-spec-r1'
ROLE_SCHEMA = 'dram-see-v4-parameterized-proton-role-r1'
TIME_SCHEMA = 'dram-see-v4-parameterized-proton-native-time-r1'
ALPHA_SHA = '395879dae534e5ab1832740e056519457d1dbb217e7a69180078ea026148ebef'
ACTIVATION_SHA = 'c2ae3cd2684cf0463ddd5ff3d9ef7e259f492d9f6763d3b0ec0e793cb813a6a7'
NATIVE_SHA = '139164c45e0673e13f80cf5821320fce1313a4f3a71e4f760b4344f94179c6dd'
SOURCE_PREPARER_SHA = 'a9446fe3e8fa04f634b82e965eb1a0dbad819b5598f373121f877c02019efcfe'
PMI_MANIFEST_SHA = '31dceb972a678be8bccd016d56a9866851a3af46071bc43fd645ccddab289eba'
PMI_CPP_SHA = '1b8eb30bfcd001142235e9cf2f870cdfb38d98546305028d8ca70664805b05c6'
PMI_MATH_SHA = 'bb1ff7fa938adc36ed3cdf5c2a91d60c24d50afcb338ccc68d8840dab1943c77'
PMI_HEADER_SHA = '7fccf1497de68fb3ce993c02b00ac4ca324f4f9ee5b5065f367c0533a82c7383'
LIBRARY = 'pmi_projection_qy_r1.so.linux64'
SIGMA = 2e-12
WIDTH_UM = .03
SUPPORT_SIGMA = 8
EVENT_IDS = [0, 1, 2, 3]
A0_PREFIX = 'matched-a0-bindings/'
TRANSPORT_PREFIX = 'proton-transport-bindings/'
BUILD_PREFIX = 'proton-build-bindings/'
PMI_PREFIX = 'proton-pmi-bindings/'
BATCH_PREFIX = 'proton-batch/'
SOURCE_PREFIX = 'proton-source-inputs/'
ACTIVATION_PREFIX = 'proton-activation/'
SOURCE_FILES = ('projection-sources3d.dat', 'projection-context.dat',
                'input-only-projection-reference.json', 'full-original-event-source.json')
CURRENT_DIAGNOSTIC = b'CurrentPlot {\n OpticalGeneration( Integrate(Semiconductor) )\n}\n'
FRAGMENTS = {
 'activation-device-file.inc': 'ab1d9be3bf71f6f068f0b60c007c406413327ce20636ebfaaa9dcae7f56cdea8',
 'activation-global-file.inc': '99399d351f6a3da009fc22969d280f04b784185d9051cc22e0e5b27a7c43268d',
 'activation-initial-solve.inc': '0439ebaeb60a55bd4892cd4a9de18ed5438828bd4760fdf78966e23cc70a2e28',
 'activation-physics.inc': 'cfae39c78c50a3752da8472df07825894544291f6d0612f0bc505c003349346e',
 'activation-plot.inc': '4e424f2ee1cd076d8060e99d5eff666224521487e4a9c0bcda37ad0dfe4ca59d',
 'proton-reference-apd.plx': 'e9d54e5d397554aa5edac9d8765ede8e79186e45ac4bb10acb659c2e1a205fa3',
 'proton-reference-spectrum.txt': '1d11b26a84a6eb22aac829654e2873589d255593e2c94d058d7b596c59a27eab',
}
HOST_SOURCES = {
 'parameterized_proton_activation_2d.py': ('device', ACTIVATION_SHA),
 'bcat_native_adapter.py': ('projection2d', NATIVE_SHA),
 'prepare_pmi_candidate.py': ('projection2d', SOURCE_PREPARER_SHA),
 'adapter.py': ('projection2d', '3d078e0aa6cd38bc11dc7a4ae7c91d26585bbd5f33cb6a90931a9b645391d952'),
 'project.py': ('projection2d', 'b73bd65d93e1a0052bfa9a338885188ab0c15258397a5c2942f430d75ad8251d'),
 'kernel.py': ('projection2d', 'c9b44b5f808212a018dfa37542bc218410048ba05d9ee211b2bf933bc4d78069'),
}
REQUEST_FIELDS = {'schema','kind','dimension','gate_top_depth_nm','sn_junction_depth_nm','variant','stored_bit',
 'source_case','particle','d2_source_run','base_d2_source_run','effective_width_nm','matched_a0_run',
 'transport_batch_package','pmi_source_inputs','pmi_build_operation','event_id','transport_seed','original_event_count',
 'operation_timing_sha256','base_operation_timing_sha256','numerical_relation_sha256','gate_high_V','source_epoch_s',
 'mathematical_source_window_s','native_observation_window_s','simulation_window_s','charge_window_s',
 'energy_MeV','theta_deg','phi_deg'}
FROZEN_RESULT_KEYS = {'binding','report','source_cfg','dimensional_contract','operation_timing','operating_binding',
 'source_spec','role_contract','numerical_relation','projection','proton_binding','matched_a0','source_time_contract',
 'activation','pmi_build','native_batch'}
RUNTIME_FILES = ('parameterized_alpha_2d.py','parameterized_operating_2d.py','parameterized_baseline_2d.py',
 'alpha_native_2d.py','operating_transient_2d.py','two_dimensional.py','native_transient_clock.py',
 'operating_metrics_2d.py','legacy-circuit-metrics.py','parameterized_proton_2d.py')


def require(ok, message):
    if not ok: raise ValueError('Parameterized 2D proton: ' + message)


def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')
def obj(raw):
    value=json.loads(raw.decode('utf-8'));require(isinstance(value,dict),'expected JSON object');return value
def number(value): return type(value) in (int,float) and math.isfinite(value)
def module(name, expected=None, family='device'):
    path=HERE/name
    if family!='device':path=HERE.parent/family/name
    require(path.is_file() and not path.is_symlink(),'missing fixed local module '+name)
    require(expected is None or sha(path.read_bytes())==expected,'fixed source changed: '+name)
    spec=importlib.util.spec_from_file_location('_parameterized_proton_'+name.replace('.','_'),str(path))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
def shared(): return module('parameterized_alpha_2d.py', ALPHA_SHA)
def native_api(): return module('bcat_native_adapter.py',NATIVE_SHA,'projection2d')
def source_api(): return module('prepare_pmi_candidate.py',SOURCE_PREPARER_SHA,'projection2d')
def activation_api(): return module('parameterized_proton_activation_2d.py',ACTIVATION_SHA)


def validate_request(request):
    O=shared().operation()
    require(isinstance(request,dict) and set(request)==REQUEST_FIELDS,'exact versioned proton request fields required')
    for k,v in dict(schema=REQUEST_SCHEMA,kind='transient',source_case='Aproton',particle='proton',variant='main').items():
        require(request[k]==v,'unsupported first proton branch: '+k)
    for k,v in dict(dimension=2,gate_top_depth_nm=80,sn_junction_depth_nm=87,effective_width_nm=20,
                    energy_MeV=100,theta_deg=0,phi_deg=180,original_event_count=4).items():
        require(type(request[k]) is int and request[k]==v,'fixed development condition differs: '+k)
    require(type(request['stored_bit']) is int and request['stored_bit'] in (0,1),'integer bit required')
    require(type(request['event_id']) is int and request['event_id'] in EVENT_IDS,'explicit original event 0..3 required')
    require(type(request['transport_seed']) is int and request['transport_seed']>0,'actual native seed required')
    for k in ('d2_source_run','base_d2_source_run','matched_a0_run','transport_batch_package','pmi_source_inputs','pmi_build_operation'):
        require(isinstance(request[k],str) and request[k].strip(),'explicit real input path required: '+k)
    for k in ('operation_timing_sha256','base_operation_timing_sha256','numerical_relation_sha256'):
        require(O.digest_ok(request[k]),'explicit frozen timing/variant identity required')
    require(number(request['gate_high_V']) and request['gate_high_V']>-.5
            and number(request['source_epoch_s']) and request['source_epoch_s']>0,'explicit finite gate and epoch required')
    for k in ('mathematical_source_window_s','native_observation_window_s','simulation_window_s','charge_window_s'):
        w=request[k];require(isinstance(w,list) and len(w)==2 and all(number(x) for x in w)
            and 0<=w[0]<w[1],'explicit physical-second interval required: '+k)
    full=request['simulation_window_s'];require(full[0]==0 and full[0]<request['source_epoch_s']<full[1],'physical full operation required')
    for k in ('mathematical_source_window_s','native_observation_window_s','charge_window_s'):
        require(full[0]<=request[k][0]<request[k][1]<=full[1],'interval outside full operation: '+k)
    return obj(encoded(request))


def role_id(request):
    r=validate_request(request)
    return 'B2D-Aproton-parameterized-r1-main-b'+str(r['stored_bit'])+'-e'+str(r['event_id'])


def _runtime_bytes():
    out=shared()._runtime_bytes();out['parameterized_proton_2d.py']=Path(__file__).read_bytes()
    require(set(out)==set(RUNTIME_FILES),'closed guest runtime changed');return out


def verify_matched_a0(reader, manifest, inputs, request):
    S=shared();D=S.dimensional();O=S.operation();r=validate_request(request)
    S.alpha()._collection(reader,manifest,inputs,D)
    project=obj(reader.read('project.json'));cfg=project['s2_geometry'];context=obj(reader.read('execution-context.json'))
    wanted='B2D-A0-parameterized-r1-main-b'+str(r['stored_bit'])
    require(project.get('role')==cfg.get('role_id')==context.get('role_id')==wanted
        and cfg.get('parameterized_operating_branch')==S.parameterized().BRANCH
        and cfg.get('run_id')==manifest.get('run_id') and cfg.get('mode')=='reuse'
        and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
        and project.get('execution_enabled') is True and project.get('native_threads')==project.get('native_cores')==1
        and project.get('steps')==manifest.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))],
        'real same-bit r13 main A0/native serial source required')
    audited=S.baseline_api().audit_reader(reader,cfg)
    require(set(audited)=={'frozen','clock','metrics','identity'},'baseline replay API differs')
    frozen,clock,metrics=audited['frozen'],audited['clock'],audited['metrics'];timing=frozen['operation_timing']
    require(timing['origin']=='prescribed_input' and metrics['candidate_functional_pass'] is True
        and len(metrics['checks'])==5 and all(v is True for v in metrics['checks'].values()),
        'actual matching A0 five criteria/KCL not passed: '+json.dumps(metrics.get('checks'),sort_keys=True))
    require(clock['trace']==metrics['accepted_trace'] and metrics['time_coordinate_transformed'] is False
        and audited['identity']['complete_clock_evidence_verified'] is True,'original physical clock/rows required')
    common={name:reader.read(name) for name in S.SHARED}
    common.update({'operation-selection/'+name:reader.read('operation-selection/'+name)
                   for name in timing['selection_provenance']['references']})
    return dict(verified=frozen,project=project,cfg=cfg,role=frozen['role_contract'],device=reader.read('device.cmd'),
        metrics=metrics,clock=clock,reader_identity=audited['identity'],shared=common,
        input_manifest_sha256=reader.digest('input-manifest.json'),circuit_plt_sha256=reader.digest('circuit.plt'),
        collection_index_sha256=reader.digest('_collection-members.json'),operating_binding_sha256=reader.digest('parameterized-operating-binding.json'))


def request_matches(r, match, identity):
    cfg=match['cfg'];t=match['verified']['operation_timing'];O=shared().operation()
    for k in ('stored_bit','gate_top_depth_nm','sn_junction_depth_nm','effective_width_nm','gate_high_V',
              'operation_timing_sha256','base_operation_timing_sha256','numerical_relation_sha256'):
        require(r[k]==cfg[k]==identity[k],'real A0 input mismatch: '+k)
    require(cfg['numerical_variant']==r['variant']=='main'
        and O.source_name(r['matched_a0_run'])==identity['run_id']
        and O.source_name(r['d2_source_run'])==identity['producer_run_id']
        and O.source_name(r['base_d2_source_run'])==identity['base_producer_run_id'],'actual A0/D2 source differs')
    for k in ('source_epoch_s','mathematical_source_window_s','native_observation_window_s','simulation_window_s','charge_window_s'):
        require(r[k]==t[k],'request silently changes A0 physical timing: '+k)


def table_bytes(terms):
    """Exact serialization only; host also compares frozen M.source_table."""
    rows=sorted(t['p0_um']+t['p1_um']+[t['t0_s'],t['t1_s'],t['charge_fC'],t['width_um'],t['sigma_s']] for t in terms)
    return ('NUCLEAR_CLOSURE_SOURCE_V1 '+str(len(rows))+'\n'+''.join(' '.join(format(v,'.17g') for v in row)+'\n' for row in rows)).encode('ascii')


def context_bytes(window):
    return ('DRAM_SEE_V4_2D_SOURCE_CONTEXT_R1 0.02 '+' '.join(format(v,'.17g') for v in window)+'\n').encode('ascii')


def event_coverage(source, full, observation):
    terms=source['terms']
    for t in terms:
        vals=t['p0_um']+t['p1_um']+[t['t0_s'],t['t1_s'],t['charge_fC'],t['width_um'],t['sigma_s']]
        require(len(t['p0_um'])==len(t['p1_um'])==3 and all(number(x) for x in vals)
            and 0<=t['t0_s']<=t['t1_s'] and t['charge_fC']>0 and t['sigma_s']==SIGMA
            and t['width_um']==WIDTH_UM,'actual source term units/kernel differ')
    limits=[min(t['t0_s'] for t in terms),max(t['t1_s'] for t in terms)] if terms else None
    support=[limits[0]-SUPPORT_SIGMA*SIGMA,limits[1]+SUPPORT_SIGMA*SIGMA] if limits else None
    late=[t['uid'] for t in terms if t['t0_s']<full[0] or t['t1_s']>full[1]]
    return dict(event_id=source['event_id'],source_rows=len(terms),structural_zero=not terms,
        raw_deposition_interval_s=limits,required_8sigma_observation_s=support,raw_outside_full_uids=late,
        full_covers_raw=not late,full_covers_8sigma=(support is None or full[0]<=support[0]<=support[1]<=full[1]),
        observation_covers_8sigma=(support is None or observation[0]<=support[0]<=support[1]<=observation[1]),
        Gaussian_tails_truncated=False,Gaussian_tail_account='original complete-window five-charge ledger, never renormalized')


def source_time_contract(device, timing, request, sources):
    S=shared();O=S.operation();t=O.validate_timing(timing);r=validate_request(request)
    require([s['event_id'] for s in sources]==EVENT_IDS,'complete four-event denominator required')
    full=t['simulation_window_s'];obs=t['native_observation_window_s'];mathwin=t['mathematical_source_window_s'];charge=t['charge_window_s']
    inventory=[event_coverage(s,full,obs) for s in sources];chosen=inventory[r['event_id']]
    require(chosen['full_covers_raw'] and chosen['full_covers_8sigma'] and chosen['observation_covers_8sigma'],
        'selected complete event requires matching new A0 full/observation timing; retain all late records')
    support=chosen['required_8sigma_observation_s']
    require(support is None or mathwin[0]<=support[0]<=support[1]<=mathwin[1],
        'mathematical source interval does not cover original selected event plus 8 sigma')
    require(charge[0]<=obs[0]<obs[1]<=charge[1],'response charge interval must cover entire proton observation')
    clock=S.module('native_transient_clock.py',S.CLOCK_SHA);segments,_=clock._deck(device)
    require([(float(s['initial_literal']),float(s['final_literal'])) for s in segments]
        ==[(s['start_s'],s['end_s']) for s in t['segments']],'actual matching A0 segment boundaries differ')
    number_pattern=S.alpha().NUMBER.encode('ascii')
    windows=re.findall(rb'Plot\(FilePrefix="source_window" Time=\(Range=\(('+number_pattern+rb') ('+number_pattern+rb')\)\) NoOverwrite\)',device)
    actual=[[float(a),float(b)] for a,b in windows]
    expected=[[s['start_s'],s['end_s']] for s in t['segments'] if obs[0]<=s['start_s'] and s['end_s']<=obs[1]]
    require(actual and actual==expected and actual[0][0]==obs[0] and actual[-1][1]==obs[1]
        and all(a[1]==b[0] for a,b in zip(actual,actual[1:])),'original A0 must write all declared observation segments')
    return dict(schema=TIME_SCHEMA,source_epoch_s=r['source_epoch_s'],full_simulation_window_s=full,
        complete_PMI_context_window_s=full,mathematical_source_window_s=mathwin,native_observation_window_s=obs,
        response_charge_window_s=charge,native_observation_segment_literals=[[a.decode(),b.decode()] for a,b in windows],
        native_segments=segments,all_event_time_inventory=inventory,selected_event_id=r['event_id'],
        source_sigma_s=SIGMA,support_sigma_multiple=SUPPORT_SIGMA,support_rule_source='continuous/proton/couple.py:139',
        Gaussian_support_is_not_cutoff=True,source_reference_uses_complete_window=True,raw_Geant4_time_unchanged=True,
        time_translation='original raw ns * 1e-9 + explicitly bound epoch once',time_remapped=False,
        additional_normalization=False,native_source_clock_qualified=False)


def block(name, raw):
    return b'\n* BEGIN_PARAMETERIZED_PROTON_'+name.encode('ascii')+b'\n'+raw+b'* END_PARAMETERIZED_PROTON_'+name.encode('ascii')+b'\n'


def render_signal(a0, activation_files):
    require(b'PARAMETERIZED_PROTON_' not in a0 and re.search(rb'\b(HeavyIon|Optics|QuantumYield)\s*\(',a0) is None,
        'matched A0 already has a source/optics block')
    anchors=[('device-file',b'Parameter="physics.par"','activation-device-file.inc'),
        ('global-file',b'Output="transient"','activation-global-file.inc'),
        ('plot',b'Plot { ','activation-plot.inc'),('solve',b'Solve {\n','activation-initial-solve.inc')]
    value=a0
    for name,anchor,filename in anchors:
        raw=activation_files[filename];require(sha(raw)==FRAGMENTS[filename] and value.count(anchor)==1,'unknown A0 insertion shape')
        value=value.replace(anchor,anchor+block(name,raw),1)
    anchor=b' }\n}\nFile { Output="transient"'
    require(value.count(anchor)==1,'unknown Cell Physics closing shape')
    raw=activation_files['activation-physics.inc'];require(sha(raw)==FRAGMENTS['activation-physics.inc'],'Optics fragment changed')
    value=value.replace(anchor,block('physics',raw)+anchor,1)
    require(value.count(b'Math {')==1 and b'CurrentPlot {' not in a0,'unexpected original CurrentPlot/Math shape')
    return value.replace(b'Math {',block('currentplot',CURRENT_DIAGNOSTIC)+b'Math {',1)


def source_free_deck(device, activation_files):
    value=device
    for name,filename in [('device-file','activation-device-file.inc'),('global-file','activation-global-file.inc'),
        ('plot','activation-plot.inc'),('solve','activation-initial-solve.inc'),('physics','activation-physics.inc')]:
        part=block(name,activation_files[filename]);require(value.count(part)==1,'source removal must be exact and unique')
        value=value.replace(part,b'',1)
    part=block('currentplot',CURRENT_DIAGNOSTIC);require(value.count(part)==1,'complete optical current diagnostic is missing/duplicated')
    value=value.replace(part,b'',1)
    require(b'PARAMETERIZED_PROTON_' not in value,'unaccounted source insertion');return value


def _operation_archive(reader, receipt, inputs, required=()):
    """Original operation-v2 collection proof, using the existing safe reader."""
    D=shared().dimensional()
    require(receipt.get('schema')=='dram-see-v4-transport-operation-v2' and receipt.get('state')=='COLLECTED_PENDING_AUDIT'
        and receipt.get('collection_verified') is True and receipt.get('origin')=='native_pipeline'
        and receipt.get('synthetic') is False,'real complete original operation-v2 required')
    require(type(receipt.get('ssh_exit_code')) is int and all(type(receipt.get(k)) is int and receipt[k]==0
        for k in ('remote_exit_code','operation_task_exit_code','collection_exit_code')),'actual native operation exits absent/nonzero')
    inventory=obj(reader.read('_collection-members.json'))
    require(set(inventory)=={n for n,m in reader.members.items() if m.isfile()}-{'_collection-members.json'},'complete native inventory required')
    for name,row in inventory.items():require(row==dict(size=reader.size(name),sha256=reader.digest(name)),'native member changed: '+name)
    expected=receipt.get('input_sha256',{})
    require(expected and set(expected)=={n for n,m in inputs.members.items() if m.isfile()},'original operation input denominator differs')
    for name,digest in expected.items():require(inputs.digest(name)==reader.digest(name)==digest,'original operation input changed')
    for name in ('exit-code.txt','operation-task-exit-code.txt'):
        require(D._exit(reader.read(name))==0,'actual wrapper/task exit not zero')
    identity=obj(reader.read('process-identity.json'))
    require(identity==receipt.get('process_identity') and identity.get('schema')=='tcad-process-identity-r1'
        and identity.get('run_id')==receipt.get('label') and identity.get('cwd')==receipt.get('remote_directory')
        and type(identity.get('pid')) is int and identity['pid']>0
        and type(identity.get('start_ticks')) is int and identity['start_ticks']>0
        and identity.get('script_sha256')==receipt.get('script_sha256')==reader.digest('run.sh'),'original process/wrapper identity differs')
    for name in required:require(reader.exists(name),'required real operation artifact missing: '+name)
    return inventory


def frozen_operation(reader, prefix, kind):
    D=shared().dimensional();receipt=obj(reader.read(prefix+'operation.json'))
    require(receipt.get('archive_sha256')==reader.digest(prefix+'results.tar')
        and receipt.get('inputs_archive_sha256')==reader.digest(prefix+'inputs.tar'),'original operation outer archive mismatch')
    with reader.stream(prefix+'results.tar') as a,reader.stream(prefix+'inputs.tar') as i:
        with tarfile.open(fileobj=a,mode='r:*') as aa,tarfile.open(fileobj=i,mode='r:*') as ii:
            rr,ri=D.ArchiveReader(aa),D.ArchiveReader(ii)
            inventory=_operation_archive(rr,receipt,ri)
            result=dict(kind=kind,label=receipt['label'],receipt_sha256=reader.digest(prefix+'operation.json'),
                archive_sha256=reader.digest(prefix+'results.tar'),inputs_archive_sha256=reader.digest(prefix+'inputs.tar'),
                input_sha256=receipt['input_sha256'],inventory=inventory,
                actual_exits={k:receipt[k] for k in ('ssh_exit_code','remote_exit_code','operation_task_exit_code','collection_exit_code')})
            if kind=='pmi':
                pm=obj(rr.read('candidate-input-manifest.json'))
                require(rr.digest('candidate-input-manifest.json')==PMI_MANIFEST_SHA,'only frozen new 2D PMI compile package is accepted')
                names=set(pm['files'])|{'candidate-input-manifest.json','input-hashes.sha256'}
                require(set(receipt['input_sha256'])==names,'PMI compile input set differs')
                for name,digest in pm['files'].items():require(rr.digest(name)==digest,'PMI fixed input changed')
                for name,digest in [('pmi_projection_qy_r1.C',PMI_CPP_SHA),('projection_pmi_math_r1.hpp',PMI_MATH_SHA),('source_kernel_r12.hpp',PMI_HEADER_SHA)]:
                    require(rr.digest(name)==digest,'new 2D PMI source differs')
                require(D._exit(rr.read('cmi-exit-code.txt'))==D._exit(rr.read('context-exit-code.txt'))==0,'actual 2D PMI compiler/context exit failed')
                binary=rr.read(LIBRARY);require(binary.startswith(b'\x7fELF'),'actual ELF PMI library missing')
                hashes={line.split(None,1)[1].strip():line.split(None,1)[0] for line in rr.read('native-build-sha256.txt').decode().splitlines()}
                require(hashes.get(LIBRARY)==sha(binary),'new native library does not match actual build result')
                require(re.search(rb'\bT\s+new_PMI_OpticalQuantumYield\b',rr.read('exported-symbols.txt')) is not None,'native PMI factory absent')
                linked=rr.read('linked-libraries.txt');require(b'not found' not in linked and b'libstdc++.so.6' in linked and b'libgcc_s.so.1' in linked,'actual PMI linkage unresolved')
                result.update(library_sha256=sha(binary),library_size_bytes=len(binary),compiled=True,native_BE_activation_verified=False)
            elif kind=='transport':
                require(D._exit(rr.read('transport-exit-code.txt'))==0,'actual G4 transport exit failed')
                result.update(request=obj(rr.read('request.json')),metadata=obj(rr.read('metadata.json')),status=obj(rr.read('status.json')),
                    transport_binary_sha256=rr.digest('transport_bcat'))
            elif kind=='bcat-build':
                require(D._exit(rr.read('compile-exit-code.txt'))==0,'actual BCAT build failed')
                result.update(transport_binary_sha256=rr.digest('transport_bcat'))
            else:raise ValueError('Unknown original operation proof')
    return result


def _operation_originals(folder, prefix):
    D=shared().dimensional();folder=Path(folder).resolve()
    require((ROOT/'local_runtime/dram-see-v4/transport-probe/operations').resolve() in folder.parents
        and not folder.is_symlink(),'original operation directory required')
    return {prefix+n:dict(path=str(folder/n),sha256=D.file_sha(folder/n),size_bytes=(folder/n).stat().st_size)
            for n in ('operation.json','results.tar','inputs.tar')}


def _source_package_host(batch, source_folder, match, request):
    """Replay all actual source terms with fixed methods, never recompute old oracles."""
    M=source_api();N=native_api();replay=N.verify(batch);bound=replay['binding'];sources=replay['sources'];r=request
    require(bound['original_request_event_ids']==EVENT_IDS and bound['original_request_event_count']==4
        and bound['seed']==r['transport_seed'] and bound['epoch_s']==r['source_epoch_s'],'actual complete batch identity differs')
    folder=Path(source_folder);source_manifest=obj((folder/'candidate-input-manifest.json').read_bytes())
    actual_geometry=M.A.read_json(bound['geometry']['path'])
    # Geometry and material correspondence is checked by the frozen projection code.
    index=obj((folder/'all-event-source-inputs.json').read_bytes());response_bindings=index['response_bindings']
    for name,key in [('model.proposed.json','model'),('geometry-contract.json','geometry'),('dimensional-contract.json','dimensional_contract')]:
        path=Path(response_bindings[key]['path']);require(path.read_bytes()==match['shared'][name],'source response input differs from actual A0: '+name)
    response,binding=M.P.bcat_response(response_bindings['model']['path'],response_bindings['geometry']['path'],
        response_bindings['dimensional_contract']['path'],actual_geometry)
    require(binding==response_bindings,'original source geometry correspondence differs')
    expected={};entries=[];window=r['simulation_window_s']
    for source in sources:
        eid=source['event_id'];prefix='event-'+str(eid)+'/'
        ledger=M.K.integrate(source['terms'],response,window,bound['native_beam']['surface_position_um'],source['epoch_s'])
        late=ledger['raw_deposition_outside_window_uids']
        expected[prefix+'projection-sources3d.dat']=M.source_table(source['terms'])
        expected[prefix+'projection-context.dat']=M.context_bytes(window)
        expected[prefix+'input-only-projection-reference.json']=M.A.encoded(ledger)
        expected[prefix+'full-original-event-source.json']=M.A.encoded(source)
        entries.append(dict(event_id=eid,seed=source['seed'],source_rows=len(source['terms']),late_uids=late,
            readiness='RAW_LATE_SOURCE_REQUIRES_MATCHING_TIMING_EXTENSION' if late else 'CANDIDATE_INPUT_ONLY_APD_AND_NATIVE_QUALIFICATION_UNRESOLVED',
            source_present=bool(source['terms']),all_original_steps_retained=source['all_selected_event_steps_retained']))
    expected['all-event-source-inputs.json']=M.A.encoded(dict(schema='dram-see-v4-projection-native-source-input-candidate-r1',
        batch_binding=bound,response_bindings=binding,complete_window_s=list(window),events=entries,omitted_event_ids=[],
        reference_kernel=M.A.ref(M.HERE/'kernel.py'),source_adapter=M.A.ref(M.HERE/'bcat_native_adapter.py'),
        coordinate_map='native X=physical x, native Y=physical z, native Z=0; all physical y remains in original source rows',
        native_physics_fragment=None,APD_basis=None,native_source_qualified=False,pmi_r12_fixed=False))
    manifest=dict(schema='dram-see-v4-projection-candidate-inputs-r1',kind='all-original-BCAT-events-native-source-input-candidate-not-activated',
        files={n:M.A.sha(raw) for n,raw in sorted(expected.items())},preparer=M.A.ref(M.__file__),
        compiled=False,solver_dispatched=False,native_source_qualified=False,pmi_r12_fixed=False)
    require(source_manifest==manifest,'complete actual source-input manifest differs from replay')
    expected['candidate-input-manifest.json']=M.A.encoded(manifest)
    expected['input-hashes.sha256']=''.join(sha(raw)+'  '+n+'\n' for n,raw in sorted(expected.items())).encode('ascii')
    for n,raw in expected.items():require((folder/n).read_bytes()==raw,'source-input original/recomputation differs: '+n)
    require({p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}==set(expected),'unaccounted source-input member')
    packet={n:(Path(batch)/n).read_bytes() for n in ['adapter-manifest.json','native-batch-binding.json','replay-request.json']+
            ['event-'+str(i)+'-g3-source.json' for i in EVENT_IDS]}
    return dict(replay=replay,source_files=expected,batch_files=packet)


def _prefixed_files(reader, prefix, manifest_name, expected_names):
    manifest=obj(reader.read(prefix+manifest_name));files=manifest.get('files',{})
    require(set(files)==set(expected_names),'frozen package file denominator differs')
    for name,row in files.items():
        digest=row['sha256'] if isinstance(row,dict) else row
        require(reader.digest(prefix+name)==digest,'frozen package member changed: '+prefix+name)
        if isinstance(row,dict):require(reader.size(prefix+name)==row['size_bytes'],'frozen size differs')
    return manifest


def frozen_sources(reader, request, match, operations):
    r=request;expected_source={'all-event-source-inputs.json'}|{'event-'+str(e)+'/'+n for e in EVENT_IDS for n in SOURCE_FILES}
    sm=_prefixed_files(reader,SOURCE_PREFIX,'candidate-input-manifest.json',expected_source)
    require(sm['schema']=='dram-see-v4-projection-candidate-inputs-r1' and sm['preparer']['sha256']==SOURCE_PREPARER_SHA
        and sm['native_source_qualified'] is False,'frozen full source preparer differs')
    bm=_prefixed_files(reader,BATCH_PREFIX,'adapter-manifest.json',{'native-batch-binding.json','replay-request.json'}|
        {'event-'+str(i)+'-g3-source.json' for i in EVENT_IDS})
    bound=obj(reader.read(BATCH_PREFIX+'native-batch-binding.json'));source_index=obj(reader.read(SOURCE_PREFIX+'all-event-source-inputs.json'))
    transport,build=operations['transport'],operations['build'];native_request=transport['request'];meta=transport['metadata']
    require(bm['event_ids']==bound['original_request_event_ids']==EVENT_IDS and bound['original_request_event_count']==4
        and bound['no_event_filter'] is True and bound['epoch_s']==r['source_epoch_s']
        and source_index['batch_binding']==bound and source_index['omitted_event_ids']==[]
        and source_index['complete_window_s']==r['simulation_window_s'],'complete original event/time denominator differs')
    require(native_request['event_count']==4 and native_request['energy_MeV']==100 and native_request['theta_deg']==0
        and native_request['phi_deg']==180 and native_request['target_um']==[-.052,0.,0.]
        and native_request['seed']==r['transport_seed']==bound['seed'] and native_request['label']==transport['label']
        and native_request['source_operation_sha256']==build['receipt_sha256'],'actual native beam/build request differs')
    require(meta['primary_particle']=='proton' and meta['energy_MeV']==100 and meta['angle_deg']==0
        and meta['units']==dict(length='um',time='ns',energy='MeV',charge='eplus',direction='unit_vector')
        and transport['status']['events_completed']==transport['status']['events_requested']==4
        and transport['status']['state']=='COMPLETED','actual native completion/units differ')
    for key,op in [('operation',transport),('build_operation',build)]:
        require(bound[key]['sha256']==op['receipt_sha256'],'native operation binding differs')
    require(bound['archive']['sha256']==transport['archive_sha256'] and bound['build_archive']['sha256']==build['archive_sha256']
        and bound['binary']['sha256']==transport['transport_binary_sha256']==build['transport_binary_sha256'],'complete G4 build/run archive binding differs')
    for name,row in bound['raw_files'].items():require(row['sha256']==transport['inventory'][name]['sha256'],'actual full G4 raw member differs')
    for name,key in [('model.proposed.json','model'),('geometry-contract.json','geometry'),('dimensional-contract.json','dimensional_contract')]:
        require(source_index['response_bindings'][key]['sha256']==reader.digest(name),'source response geometry/model/width mismatch')
    sources=[]
    for eid in EVENT_IDS:
        prefix=SOURCE_PREFIX+'event-'+str(eid)+'/'
        raw=reader.read(prefix+'full-original-event-source.json')
        require(raw==reader.read(BATCH_PREFIX+'event-'+str(eid)+'-g3-source.json'),'event reconstruction bytes differ between original packages')
        source=obj(raw);sources.append(source)
        require(source['event_id']==eid and source['seed']==r['transport_seed'] and source['epoch_s']==r['source_epoch_s']
            and source['energy_MeV']==100 and source['angle_deg']==0 and source['all_selected_event_steps_retained'] is True
            and source['context']['original_request_denominator']==EVENT_IDS
            and source['context']['original_batch_binding_sha256']==sha(encoded(bound)), 'actual event/ancestry/full denominator differs')
        require(reader.read(prefix+'projection-sources3d.dat')==table_bytes(source['terms'])
            and reader.read(prefix+'projection-context.dat')==context_bytes(r['simulation_window_s']),'source table/context bytes differ')
        row=source_index['events'][eid]
        require(row['event_id']==eid and row['source_rows']==len(source['terms']) and row['all_original_steps_retained'] is True,'event source index mismatch')
    require([row['event_id'] for row in source_index['events']]==EVENT_IDS,'event index missing/duplicate members')
    chosen=SOURCE_PREFIX+'event-'+str(r['event_id'])+'/'
    for name in ('projection-sources3d.dat','projection-context.dat'):
        require(reader.read(name)==reader.read(chosen+name),'active source must be exactly requested complete event')
    time=source_time_contract(match['device'],match['verified']['operation_timing'],r,sources)
    return dict(binding=bound,index=source_index,manifest=sm,batch_manifest=bm,sources=sources,
        selected_ledger=obj(reader.read(chosen+'input-only-projection-reference.json')),
        guest_mathematical_replay=False,guest_full_G4_CSV_replay=False,
        host_replay_implementations=dict(native=NATIVE_SHA,source_preparer=SOURCE_PREPARER_SHA)),time


def frozen_activation(reader, match, request):
    names=set(FRAGMENTS)|{'activation-contract.json'}|{'original/'+n for n in ('geometry-contract.json','dimensional-contract.json','operation-timing.json')}
    manifest=_prefixed_files(reader,ACTIVATION_PREFIX,'candidate-input-manifest.json',names)
    require(manifest['implementation_sha256']==ACTIVATION_SHA and manifest['solver_project_generated'] is False,'activation implementation changed')
    files={n:reader.read(ACTIVATION_PREFIX+n) for n in FRAGMENTS}
    for name,digest in FRAGMENTS.items():
        require(sha(files[name])==digest,'fixed first-g80 APD activation fragment changed: '+name)
        if name.endswith(('.plx','.txt')):require(reader.read(name)==files[name],'active APD/spectrum differs')
    for name in ('geometry-contract.json','dimensional-contract.json','operation-timing.json'):
        require(reader.read(name)==reader.read(ACTIVATION_PREFIX+'original/'+name),'activation physical input differs')
    contract=obj(reader.read(ACTIVATION_PREFIX+'activation-contract.json'))
    require(contract['schema']=='dram-see-v4-parameterized-proton-activation-input-r1'
        and contract['source_model']['reference_APD_cm_minus3_s_minus1']==1e35
        and contract['source_model']['quantum_yield']=='G2_BE / Nref'
        and contract['source_model']['requested_to_loaded_intensity_ratio']==1
        and contract['physical_time']['complete_source_context_window_s']==request['simulation_window_s']
        and contract['physical_time']['epoch_s']==request['source_epoch_s']
        and contract['native_activation_verified'] is False and contract['pmi_r12_fixed'] is False,'activation units/time/qualification declaration differs')
    device=reader.read('device.cmd')
    require(device==render_signal(match['device'],files) and source_free_deck(device,files)==match['device'],
        'strip optical source/diagnostics must equal actual A0 device bytes')
    return dict(contract=contract,manifest=manifest,guest_full_activation_renderer_replay=False)


def source_contract(request, projected, operations, timing):
    r=request;selected=projected['sources'][r['event_id']]
    return dict(schema='dram-see-v4-parameterized-proton-source-contract-r1',particle='proton',dimension=2,
        source_family='complete-native-BCAT-event-projected-through-20nm-strip',event_id=r['event_id'],
        seed=r['transport_seed'],original_request_event_ids=EVENT_IDS,original_request_event_count=4,
        energy_MeV=100,theta_deg=0,phi_deg=180,energy_definition='original G4 gun kinetic energy; retain original TOF and all deposited-energy accounts',
        full_simulation_window_s=r['simulation_window_s'],source_epoch_s=r['source_epoch_s'],
        native_observation_window_s=r['native_observation_window_s'],charge_window_s=r['charge_window_s'],
        temporal_sigma_s=SIGMA,spatial_width_um=WIDTH_UM,effective_width_nm=20,
        source_context_window_s=r['simulation_window_s'],required_source_window_s=timing['all_event_time_inventory'][r['event_id']]['required_8sigma_observation_s'],
        selected_source_rows=len(selected['terms']),selected_structural_zero=not selected['terms'],
        original_positive_Si_charge_fC=selected['original_positive_Si_charge_fC'],
        complete_batch_binding_sha256=sha(encoded(projected['binding'])),
        actual_transport_operation_sha256=operations['transport']['receipt_sha256'],
        actual_transport_archive_sha256=operations['transport']['archive_sha256'],
        actual_PMI_build_operation_sha256=operations['pmi']['receipt_sha256'],
        actual_PMI_library_sha256=operations['pmi']['library_sha256'],
        reference_rate_cm_minus3_s_minus1=1e35,source_formula='fixed correlated 3D Gaussian segment -> exact y strip / 20nm -> actual BE interval average',
        source_clock='raw native PMI ReadTime/StepSize/StepType; no synthesis',additional_normalization=False,
        source_ledger_is_mathematical_input=True,native_source_qualified=False,pmi_r12_fixed=False,training_admitted=False)


def binding(reader,cfg,matched,originals,projected,operations):
    return dict(schema=BINDING_SCHEMA,source_branch=BRANCH,verifier_sha256=sha(Path(__file__).read_bytes()),
        shared_identity_implementation_sha256=ALPHA_SHA,activation_implementation_sha256=ACTIVATION_SHA,
        native_batch_adapter_sha256=NATIVE_SHA,source_preparer_sha256=SOURCE_PREPARER_SHA,
        stored_bit=cfg['stored_bit'],event_id=obj(reader.read('controlled-request.json'))['event_id'],
        producer_run_id=cfg['producer_run_id'],mesh_sha256=reader.digest('cell_msh.tdr'),
        operation_timing_sha256=reader.digest('operation-timing.json'),numerical_relation_sha256=reader.digest('numerical-relation.json'),
        physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        source_contract_sha256=reader.digest('source-contract.json'),source_time_contract_sha256=reader.digest('source-time-contract.json'),
        source_table_sha256=reader.digest('projection-sources3d.dat'),source_context_sha256=reader.digest('projection-context.dat'),
        complete_source_package_manifest_sha256=reader.digest(SOURCE_PREFIX+'candidate-input-manifest.json'),
        complete_batch_package_manifest_sha256=reader.digest(BATCH_PREFIX+'adapter-manifest.json'),
        activation_package_manifest_sha256=reader.digest(ACTIVATION_PREFIX+'candidate-input-manifest.json'),
        actual_PMI_library_sha256=reader.digest(LIBRARY),matched_a0=matched,original_files=originals,
        operations=operations,original_event_ids=EVENT_IDS,omitted_event_ids=[],
        all_event_source_rows=[len(s['terms']) for s in projected['sources']],
        guest_replay_scope='Complete original archives/inputs/exits + A0 clock/metrics + frozen source/activation consistency; G4 CSV/math replay is host-only',
        compiled_PMI_is_not_native_activation=True,source_native_activation_unverified=True,
        native_source_qualified=False,is_native_result=False,pmi_r12_fixed=False,training_admitted=False)


def source_spec(reader,r,binding_sha):
    source=obj(reader.read('source-contract.json'))
    return dict(schema=SPEC_SCHEMA,role='STRUCTURAL_ZERO' if source['selected_structural_zero'] else 'SIGNAL',
        source_case='Aproton',particle='proton',dimension=2,stored_bit=r['stored_bit'],numerical_variant='main',
        gate_top_depth_nm=80,sn_junction_depth_nm=87,event_id=r['event_id'],seed=r['transport_seed'],
        original_request_event_ids=EVENT_IDS,energy_MeV=100,theta_deg=0,phi_deg=180,source_configured=True,
        physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),source_contract_sha256=reader.digest('source-contract.json'),
        source_time_contract_sha256=reader.digest('source-time-contract.json'),parameterized_proton_binding_sha256=binding_sha,
        source_field='OpticalGeneration',common_pair_source=True,effective_width_applied_once=True,
        currentplot_domain='Semiconductor',currentplot_integration_unit='um',
        currentplot_is_diagnostic_not_field_qualification=True,
        native_source_qualified=False,pmi_r12_fixed=False)


def role_contract(match,r,binding_sha,source_sha):
    result=dict(match['role']);result.pop('parameterized_operating_binding_sha256')
    result.update(schema=ROLE_SCHEMA,role=role_id(r),case='Aproton',source_configured=True,
        parameterized_proton_binding_sha256=binding_sha,matched_a0_operating_binding_sha256=match['operating_binding_sha256'],
        event_id=r['event_id'],seed=r['transport_seed'],original_request_event_ids=EVENT_IDS,
        energy_MeV=100,theta_deg=0,phi_deg=180,source_contract_sha256=source_sha,
        native_syntax_verified=False,native_source_qualified=False,pmi_r12_fixed=False)
    return result


def verify_frozen(reader,cfg):
    S=shared();P=S.parameterized();D=S.dimensional()
    require(cfg.get('source_branch')==BRANCH and cfg.get('dimension_branch')==P.DIMENSION_BRANCH
        and cfg.get('mode')=='reuse' and 'parameterized_operating_branch' not in cfg,'explicit proton source root required')
    for name,raw in _runtime_bytes().items():require(reader.digest(name)==sha(raw),'fixed runtime differs: '+name)
    for name,(_,digest) in HOST_SOURCES.items():require(reader.digest('proton-implementations/'+name)==digest,'host replay snapshot differs')
    result,_,_=P._verify_sources(reader,cfg);r=validate_request(obj(reader.read('controlled-request.json')))
    bound=obj(reader.read('parameterized-proton-binding.json'))
    require(bound.get('schema')==BINDING_SCHEMA and reader.digest('parameterized-proton-binding.json')==cfg.get('parameterized_proton_binding_sha256'),
        'proton binding identity differs')
    originals=bound['original_files'];expected={A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}|{
        p+n for p in (TRANSPORT_PREFIX,BUILD_PREFIX,PMI_PREFIX) for n in ('operation.json','results.tar','inputs.tar')}
    require(set(originals)==expected,'all original A0/G4/build/PMI archives required')
    for name,row in originals.items():require(row==dict(sha256=reader.digest(name),size_bytes=reader.size(name)),'original proof bytes differ: '+name)
    operations={key:frozen_operation(reader,prefix,kind) for key,prefix,kind in
        [('transport',TRANSPORT_PREFIX,'transport'),('build',BUILD_PREFIX,'bcat-build'),('pmi',PMI_PREFIX,'pmi')]}
    require(reader.digest(LIBRARY)==operations['pmi']['library_sha256'],'active library is not actual new 2D compile output')
    require(reader.read('optical.currentplot.inc')==CURRENT_DIAGNOSTIC,'full accepted G diagnostic differs')
    manifest=obj(reader.read(A0_PREFIX+'manifest.json'))
    require(manifest.get('results_sha256')==reader.digest(A0_PREFIX+'results.tar')
        and manifest.get('inputs_archive_sha256')==reader.digest(A0_PREFIX+'inputs.tar'),'original A0 outer identity differs')
    with reader.stream(A0_PREFIX+'results.tar') as a,reader.stream(A0_PREFIX+'inputs.tar') as i:
        with tarfile.open(fileobj=a,mode='r:*') as aa,tarfile.open(fileobj=i,mode='r:*') as ii:
            prior=D.ArchiveReader(aa);match=verify_matched_a0(prior,manifest,D.ArchiveReader(ii),r)
            matched=S.matched_identity(match,manifest,reader.digest(A0_PREFIX+'manifest.json'),reader.digest(A0_PREFIX+'results.tar'))
            request_matches(r,match,matched)
            for name,raw in match['shared'].items():require(reader.read(name)==raw,'signal/A0 fixed physical or timing input differs: '+name)
            require(reader.digest('cell_msh.tdr')==prior.digest('cell_msh.tdr')==cfg['mesh_sha256']
                and reader.read('d2-source-binding.json')==prior.read('d2-source-binding.json'),'actual matching D2 mesh/source differs')
            projected,time=frozen_sources(reader,r,match,operations)
            activation=frozen_activation(reader,match,r)
    require(obj(reader.read('source-time-contract.json'))==time,'full source-time statement differs')
    require(obj(reader.read('source-contract.json'))==source_contract(r,projected,operations,time),'source definition differs')
    require(bound==binding(reader,cfg,matched,originals,projected,operations),'complete original proton binding differs')
    spec=source_spec(reader,r,reader.digest('parameterized-proton-binding.json'))
    role=role_contract(match,r,reader.digest('parameterized-proton-binding.json'),reader.digest('source-contract.json'))
    require(obj(reader.read('source-spec.json'))==spec and obj(reader.read('role-contract.json'))==role
        and cfg['role_id']==role['role'],'proton source/role declaration differs')
    result.update(operation_timing=match['verified']['operation_timing'],operating_binding=match['verified']['operating_binding'],
        numerical_relation=match['verified']['numerical_relation'],source_spec=spec,role_contract=role,
        projection=projected,proton_binding=bound,matched_a0=matched,source_time_contract=time,
        activation=activation,pmi_build=operations['pmi'],native_batch=operations['transport'])
    require(set(result)==FROZEN_RESULT_KEYS,'public result shape differs');return result


def require_input_coverage(reader,hashes):
    """Every consumed proof/source must be in the original runner input manifest."""
    S=shared();D=S.dimensional()
    needed=set(D.SHARED_INPUTS)|set(S.SHARED)|set(RUNTIME_FILES)|set(obj(reader.read('d2-source-binding.json'))['original_files'])
    needed|={'project.json','controlled-request.json','case_contract.py','geometry_bridge.py','mesh_resource_guard.py',
        'generator-prepare_case.py','task-authorization.json','resource-policy.json','provenance.json',
        'device.cmd','cell_msh.tdr','cell_msh.log','d2-source-binding.json','dimensional-contract.json',
        'source-contract.json','source-time-contract.json','parameterized-proton-binding.json','source-spec.json','role-contract.json',
        'projection-sources3d.dat','projection-context.dat',LIBRARY,'proton-reference-apd.plx','proton-reference-spectrum.txt',
        'optical.currentplot.inc'}
    needed|={A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}
    needed|={p+n for p in (TRANSPORT_PREFIX,BUILD_PREFIX,PMI_PREFIX) for n in ('operation.json','results.tar','inputs.tar')}
    needed|={BATCH_PREFIX+n for n in ['adapter-manifest.json','native-batch-binding.json','replay-request.json']+
        ['event-'+str(i)+'-g3-source.json' for i in EVENT_IDS]}
    needed|={SOURCE_PREFIX+n for n in ('candidate-input-manifest.json','input-hashes.sha256','all-event-source-inputs.json')}
    needed|={SOURCE_PREFIX+'event-'+str(i)+'/'+n for i in EVENT_IDS for n in SOURCE_FILES}
    needed|={ACTIVATION_PREFIX+n for n in list(FRAGMENTS)+['activation-contract.json','candidate-input-manifest.json']+
        ['original/'+n for n in ('geometry-contract.json','dimensional-contract.json','operation-timing.json')]}
    needed|={'proton-implementations/'+n for n in HOST_SOURCES}
    needed|={'operation-selection/'+n for n in obj(reader.read('operation-timing.json'))['selection_provenance']['references']}
    require(needed<=set(hashes),'runner input manifest omits consumed proof/source: '+str(sorted(needed-set(hashes))))
    return needed


def admit(project,spec,runner_sha,bridge):
    project=Path(project);S=shared();O=S.operation();D=S.dimensional();cfg=spec['s2_geometry']
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve()) and not (project/'SYNTHETIC_NOT_NATIVE').exists(),'UNIT cannot be submitted')
    r=validate_request(obj((project/'controlled-request.json').read_bytes()))
    require(cfg.get('schema')==bridge.GEOMETRY_SCHEMA and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
        and spec.get('execution_enabled') is True and spec.get('role')==cfg.get('role_id')==role_id(r)
        and O.plain_name(cfg.get('run_id')) and cfg['run_id'] not in (cfg['producer_run_id'],O.source_name(r['matched_a0_run']))
        and spec.get('native_threads')==spec.get('native_cores')==1
        and spec.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))],'native role/serial pipeline differs')
    bridge.geometry_context(project,cfg,runner_sha);hashes=bridge.geometry_input_hashes(project)
    manifest=obj((project/'input-manifest.json').read_bytes())
    require(manifest.get('run_id')==cfg['run_id'] and manifest.get('role_id')==cfg['role_id'],'input manifest identity differs')
    require_input_coverage(D.FolderReader(project),hashes)
    for name,digest in hashes.items():require(D.file_sha(bridge.geometry_path(project,name))==digest,'submitted byte changed: '+name)
    result=verify_frozen(D.FolderReader(project),cfg)
    require(result['operation_timing']['origin']=='prescribed_input','UNIT timing cannot be submitted')
    require(obj((project/'resource-policy.json').read_bytes())==dict(schema='dram-see-v4-actual-resource-policy-r1',role=cfg['role_id'],
        observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None),'actual observations only, no resource quotas')
    return cfg


class CompositeReader:
    """Small generated bytes plus immutable external originals; no extraction."""
    def __init__(self,files,external):self.files,self.external=files,external
    def read(self,name):
        if name in self.files:return self.files[name]
        return Path(self.external[name]['path']).read_bytes()
    def digest(self,name):
        if name in self.files:return sha(self.files[name])
        return shared().dimensional().file_sha(self.external[name]['path'])
    def size(self,name):
        if name in self.files:return len(self.files[name])
        return Path(self.external[name]['path']).stat().st_size
    def stream(self,name):
        if name in self.files:
            import io
            return io.BytesIO(self.files[name])
        return Path(self.external[name]['path']).open('rb')
    def exists(self,name):return name in self.files or name in self.external


def prepare(request,run_id,runner=None,output=None):
    """Create one original-runner input only after genuine complete dependency replay."""
    r=validate_request(request);S=shared();P=S.parameterized();O=S.operation();D=S.dimensional()
    C=module('case_contract.py');bridge=module('geometry_bridge.py')
    require(getattr(C,'SCHEMA_2D_PARAMETERIZED_PROTON',None)==REQUEST_SCHEMA and hasattr(bridge,'geometry_parameterized_proton_module'),
        'proton dispatch not integrated; no project created')
    require(O.plain_name(run_id) and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id
        and run_id not in (O.source_name(r['matched_a0_run']),O.source_name(r['d2_source_run'])),'new real run ID required')
    runner=Path(runner or ROOT/'scripts/tcad.py').resolve();require(runner==(ROOT/'scripts/tcad.py').resolve(),'original runner only')
    allowed=(ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/parameterized-proton-implementation-r1').resolve()
    target=Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target),'new explicit project path required')
    for k in ('d2_source_run','base_d2_source_run','matched_a0_run','transport_batch_package','pmi_source_inputs','pmi_build_operation'):
        r[k]=str(Path(r[k]).resolve())
    a0=Path(r['matched_a0_run']);require(a0.is_dir() and not a0.is_symlink()
        and 'fixture' not in str(a0).lower() and not (a0/'SYNTHETIC_NOT_NATIVE').exists(),'actual A0 originals required')
    host=S.baseline_api().reduce_archive(a0)
    require(host.get('native_engineering_chain_verified') is True and host.get('complete_clock_evidence_verified') is True
        and host.get('candidate_functional_pass') is True,'actual matching A0 original collection/clock/five criteria required')
    manifest_raw=(a0/'manifest.json').read_bytes();manifest=obj(manifest_raw)
    require(manifest.get('state')=='COLLECTED' and manifest.get('run_id')==a0.name,'actual A0 COLLECTED manifest required')
    originals={A0_PREFIX+n:dict(path=str(a0/n),sha256=D.file_sha(a0/n),size_bytes=(a0/n).stat().st_size)
               for n in ('manifest.json','results.tar','inputs.tar')}
    require(manifest.get('results_sha256')==originals[A0_PREFIX+'results.tar']['sha256']
        and manifest.get('inputs_archive_sha256')==originals[A0_PREFIX+'inputs.tar']['sha256'],'A0 original archive mismatch')
    with tarfile.open(str(a0/'results.tar'),'r:*') as aa,tarfile.open(str(a0/'inputs.tar'),'r:*') as ii:
        match=verify_matched_a0(D.ArchiveReader(aa),manifest,D.ArchiveReader(ii),r)
    require(host['candidate_metrics']==match['metrics'],'host/guest A0 replay differs')
    matched=S.matched_identity(match,manifest,sha(manifest_raw),originals[A0_PREFIX+'results.tar']['sha256']);request_matches(r,match,matched)
    source=_source_package_host(r['transport_batch_package'],r['pmi_source_inputs'],match,r)
    time=source_time_contract(match['device'],match['verified']['operation_timing'],r,source['replay']['sources'])
    native=source['replay']['binding'];N=native_api()
    # Reuse complete_operation for the actual new PMI build, never execute its task.
    with N.A.v1().proton_modules() as (old,_,__):
        pmi_folder,_=old.complete_operation(r['pmi_build_operation'],
            (LIBRARY,'cmi-exit-code.txt','context-exit-code.txt','native-build-sha256.txt','candidate-input-manifest.json',
             'pmi_projection_qy_r1.C','projection_pmi_math_r1.hpp','source_kernel_r12.hpp','exported-symbols.txt','linked-libraries.txt'))
    originals.update(_operation_originals(Path(native['operation']['path']).parent,TRANSPORT_PREFIX))
    originals.update(_operation_originals(Path(native['build_operation']['path']).parent,BUILD_PREFIX))
    originals.update(_operation_originals(pmi_folder,PMI_PREFIX))
    activation=activation_api().candidate_payload(match['shared']['geometry-contract.json'],match['shared']['dimensional-contract.json'],match['shared']['operation-timing.json'])
    files=dict(match['shared']);files['controlled-request.json']=encoded(r)
    files.update({BATCH_PREFIX+n:v for n,v in source['batch_files'].items()})
    files.update({SOURCE_PREFIX+n:v for n,v in source['source_files'].items()})
    files.update({ACTIVATION_PREFIX+n:v for n,v in activation['files'].items()})
    files['source-time-contract.json']=encoded(time)
    for name in ('projection-sources3d.dat','projection-context.dat'):
        files[name]=source['source_files']['event-'+str(r['event_id'])+'/'+name]
    for name in ('proton-reference-apd.plx','proton-reference-spectrum.txt'):files[name]=activation['files'][name]
    files['device.cmd']=render_signal(match['device'],activation['files'])
    files['optical.currentplot.inc']=CURRENT_DIAGNOSTIC
    files[LIBRARY]=(Path(pmi_folder)/'collected'/LIBRARY).read_bytes()
    role=role_id(r);cfg=dict(match['cfg']);cfg.pop('parameterized_operating_branch');cfg.pop('parameterized_operating_binding_sha256')
    cfg.update(role_id=role,run_id=run_id,source_branch=BRANCH,source_run_directory=r['d2_source_run'],
        base_source_run_directory=r['base_d2_source_run'],execution_enabled=True,synthetic=False)
    bundle=P.source_bundle(target,cfg)
    require(bundle['mesh_sha256']==match['cfg']['mesh_sha256'] and bundle['d2_source_binding_sha256']==match['cfg']['d2_source_binding_sha256'],
        'proton/A0 real D2 source identity differs')
    files.update(bundle['generated_files']);external=dict(originals)
    # Reuse the actual A0 mesh bytes, not a rebuilt or relabelled geometry.
    with tarfile.open(str(a0/'results.tar'),'r:*') as aa:
        mesh_reader=D.ArchiveReader(aa)
        require(mesh_reader.digest('cell_msh.tdr')==cfg['mesh_sha256'],'actual matching mesh differs')
        files['cell_msh.tdr']=mesh_reader.read('cell_msh.tdr')
    check=CompositeReader(files,external)
    operations={key:frozen_operation(check,prefix,kind) for key,prefix,kind in
        [('transport',TRANSPORT_PREFIX,'transport'),('build',BUILD_PREFIX,'bcat-build'),('pmi',PMI_PREFIX,'pmi')]}
    projected,again=frozen_sources(check,r,match,operations)
    require(again==time,'source timing changed after native/frozen replay')
    frozen_activation(check,match,r)
    files['source-contract.json']=encoded(source_contract(r,projected,operations,time))
    original_rows={n:{k:v for k,v in row.items() if k!='path'} for n,row in originals.items()}
    bound=binding(check,cfg,matched,original_rows,projected,operations)
    files['parameterized-proton-binding.json']=encoded(bound);cfg['parameterized_proton_binding_sha256']=sha(files['parameterized-proton-binding.json'])
    files['source-spec.json']=encoded(source_spec(check,r,cfg['parameterized_proton_binding_sha256']))
    files['role-contract.json']=encoded(role_contract(match,r,cfg['parameterized_proton_binding_sha256'],sha(files['source-contract.json'])))
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-'+role.lower(),role=role,execution_enabled=True,
        runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))])
    files.update({'project.json':encoded(spec),'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',
        role=role,observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',source='current_user_instruction',
            synthetic=False,role_ids=[role],instruction='真实完整四event G4与真实新二维PMI编译、匹配A0原证据后，沿原runner进行首个二维质子原生激活实验；保持原owner/共享锁与串行单核单线程，无项目额度。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',plan_sha256=D.file_sha(ROOT/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md'))),
        'provenance.json':encoded(dict(schema='dram-see-v4-parameterized-proton-input-provenance-r1',run_id=run_id,role=role,
            matched_a0=matched,host_A0_replayed=True,host_complete_G4_and_source_math_replayed=True,
            actual_new_PMI_build_replayed=True,all_original_event_ids=EVENT_IDS,selected_event_id=r['event_id'],
            source_free_deck_byte_identical=True,additional_normalization=False,actual_native_submissions=0,
            native_activation_verified=False,native_source_qualified=False,pmi_r12_fixed=False,training_admitted=False))})
    for name,(family,digest) in HOST_SOURCES.items():
        raw=(HERE.parent/family/name).read_bytes();require(sha(raw)==digest,'host replay source changed')
        files['proton-implementations/'+name]=raw
    for name in ('geometry_bridge.py','mesh_resource_guard.py','case_contract.py'):files[name]=(HERE/name).read_bytes()
    files.update(_runtime_bytes());files['generator-prepare_case.py']=(HERE/'prepare_case.py').read_bytes()
    hashes={n:sha(v) for n,v in files.items()}
    for n,digest in bundle['exports'].items():require(n not in hashes or hashes[n]==digest,'actual D2 import collision');hashes[n]=digest
    for n,row in originals.items():require(n not in hashes,'original proof collision');hashes[n]=row['sha256']
    files['input-manifest.json']=encoded(dict(schema='dram-see-v4-continuous-inputs-r1',role_id=role,run_id=run_id,files_sha256=hashes))
    runner_sha=D.file_sha(runner)
    files['execution-context.json']=encoded(dict(schema='dram-see-v4-continuous-run-context-r1',run_id=run_id,role_id=role,
        producer_run_id=cfg['producer_run_id'],synthetic=False,expected_runner_sha256=runner_sha,
        input_manifest_sha256=sha(files['input-manifest.json']),authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True,exist_ok=False)
    for name,raw in files.items():bridge.geometry_write(target/name,raw)
    for name,row in originals.items():
        require(D.file_sha(row['path'])==row['sha256'],'original dependency changed during prepare')
        path=target/name;path.parent.mkdir(parents=True,exist_ok=True)
        with Path(row['path']).open('rb') as src,path.open('xb') as dst:
            for chunk in iter(lambda:src.read(1048576),b''):dst.write(chunk)
        require(D.file_sha(path)==row['sha256'],'streamed original proof copy differs')
    bridge.geometry_stage_reuse(target,cfg);bridge.geometry_admit(target,spec,runner_sha)
    return dict(project=str(target),run_id=run_id,role_id=role,event_id=r['event_id'],original_event_ids=EVENT_IDS,
        parameterized_proton_binding_sha256=cfg['parameterized_proton_binding_sha256'],input_manifest_sha256=sha(files['input-manifest.json']),
        matched_a0=matched,native_submissions=0,native_source_qualified=False,pmi_r12_fixed=False,training_admitted=False)
