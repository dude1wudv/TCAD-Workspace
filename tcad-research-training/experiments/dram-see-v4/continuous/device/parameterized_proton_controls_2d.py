"""Versioned proton Z/H/split inputs, using the complete fixed real batch.

This module never relabels a control root as the main proton/A0 role. Host
replays the fixed control relation and native transport; guest reads a pinned
complete mathematical package plus actual original operation/A0 archives.
Compilation and input admission are not native source/field qualifications.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tarfile
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BRANCH = 'dram-see-v4-parameterized-proton-control-2d-r1'
REQUEST_SCHEMA = 'dram-see-v4-parameterized-proton-control-request-r1'
BINDING_SCHEMA = 'dram-see-v4-parameterized-proton-control-binding-r1'
SPEC_SCHEMA = 'dram-see-v4-parameterized-proton-control-source-spec-r1'
ROLE_SCHEMA = 'dram-see-v4-parameterized-proton-control-role-r1'
TIME_SCHEMA = 'dram-see-v4-parameterized-proton-control-native-time-r1'
MAIN_SHA = 'd6270e76a8d9dd790ceed63be708a3eae22b0e62d23b623afb942c5401d284a0'
CONTROL_SHA = 'adc3dc95488cfc476512ffd46b7008d3b7ae1d3b24f84c5e5af5b484b6061063'
CONTROL_MANIFEST = 'proton-control-input-manifest.json'
CONTROL_MANIFEST_SHA = '7fe542189f2f439e569750db901b0f0cdff53e79b12c48a907e27f3b6577c48d'
TIMING_SHA = 'fdd2d332695f525dd00cde2297dd063ae7ed70e75a55bf74387d097934b0e395'
CONTROL_PREFIX = 'proton-control-inputs/'
BATCH_PREFIX = CONTROL_PREFIX + 'parents/batch/'
SOURCE_PREFIX = CONTROL_PREFIX + 'parents/source-inputs/'
CONTROL_CASES = {'Z': 'zero', 'H': 'half', 'split': 'split'}
CONTROL_FILES = ('projection-sources3d.dat', 'projection-context.dat',
                 'source-terms.json', 'parent-child-map.json',
                 'input-only-linear-reference.json', 'control-contract.json')


def require(ok, message):
    if not ok:
        raise ValueError('Parameterized proton controls: ' + message)


def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode('utf-8')
def obj(raw):
    value=json.loads(raw.decode('utf-8'));require(isinstance(value,dict),'JSON object required');return value
def number(value): return type(value) in (int,float) and math.isfinite(value)


def module(name, expected=None, family='device'):
    path = HERE/name if family == 'device' else HERE.parent/family/name
    require(path.is_file() and not path.is_symlink(), 'missing fixed local module ' + name)
    require(expected is None or sha(path.read_bytes()) == expected, 'fixed source changed: ' + name)
    spec=importlib.util.spec_from_file_location('_proton_controls_'+name.replace('.','_'),str(path))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


M = module('parameterized_proton_2d.py', MAIN_SHA)
# These helpers inspect original operations or manipulate optical fragments;
# none changes a control role/configuration into a main role/configuration.
shared = M.shared
native_api = M.native_api
activation_api = M.activation_api
request_matches = M.request_matches
table_bytes = M.table_bytes
context_bytes = M.context_bytes
event_coverage = M.event_coverage
render_signal = M.render_signal
source_free_deck = M.source_free_deck
frozen_operation = M.frozen_operation
_operation_originals = M._operation_originals
_prefixed_files = M._prefixed_files
frozen_activation = M.frozen_activation
CompositeReader = M.CompositeReader
ALPHA_SHA, ACTIVATION_SHA = M.ALPHA_SHA, M.ACTIVATION_SHA
NATIVE_SHA, SOURCE_PREPARER_SHA = M.NATIVE_SHA, M.SOURCE_PREPARER_SHA
SIGMA, WIDTH_UM, SUPPORT_SIGMA, EVENT_IDS = M.SIGMA, M.WIDTH_UM, M.SUPPORT_SIGMA, M.EVENT_IDS
A0_PREFIX, TRANSPORT_PREFIX, BUILD_PREFIX, PMI_PREFIX = M.A0_PREFIX, M.TRANSPORT_PREFIX, M.BUILD_PREFIX, M.PMI_PREFIX
ACTIVATION_PREFIX, FRAGMENTS, LIBRARY = M.ACTIVATION_PREFIX, M.FRAGMENTS, M.LIBRARY
SOURCE_FILES, CURRENT_DIAGNOSTIC = M.SOURCE_FILES, M.CURRENT_DIAGNOSTIC
HOST_SOURCES = dict(M.HOST_SOURCES, **{'prepare_proton_controls.py': ('projection2d', CONTROL_SHA)})
REQUEST_FIELDS = M.REQUEST_FIELDS | {'control_package', 'control_package_manifest_sha256'}
FROZEN_RESULT_KEYS = (M.FROZEN_RESULT_KEYS - {'proton_binding'}) | {'proton_control_binding'}
RUNTIME_FILES = M.RUNTIME_FILES + ('parameterized_proton_controls_2d.py',)


def control_math():
    """Host-only; never load a Python file from an input/archive package."""
    return module('prepare_proton_controls.py', CONTROL_SHA, 'projection2d')


def _runtime_bytes():
    out=M._runtime_bytes()
    require(sha(out['parameterized_proton_2d.py']) == MAIN_SHA, 'main helper runtime changed')
    out['parameterized_proton_controls_2d.py']=Path(__file__).read_bytes()
    require(set(out)==set(RUNTIME_FILES), 'closed guest runtime differs')
    return out



def validate_request(request):
    O=shared().operation()
    require(isinstance(request,dict) and set(request)==REQUEST_FIELDS,'exact versioned proton request fields required')
    for k,v in dict(schema=REQUEST_SCHEMA,kind='transient',particle='proton',variant='main').items():
        require(request[k]==v,'unsupported explicit control branch: '+k)
    require(request['source_case'] in CONTROL_CASES, 'explicit Z/H/split control required')
    for k,v in dict(dimension=2,gate_top_depth_nm=80,sn_junction_depth_nm=87,effective_width_nm=20,
                    energy_MeV=100,theta_deg=0,phi_deg=180,original_event_count=4).items():
        require(type(request[k]) is int and request[k]==v,'fixed development condition differs: '+k)
    require(type(request['stored_bit']) is int and request['stored_bit'] in (0,1),'integer bit required')
    require(type(request['event_id']) is int and request['event_id'] in EVENT_IDS,'explicit original event 0..3 required')
    require(type(request['transport_seed']) is int and request['transport_seed']>0,'actual native seed required')
    for k in ('d2_source_run','base_d2_source_run','matched_a0_run','transport_batch_package','pmi_source_inputs','pmi_build_operation','control_package'):
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
    require(request['control_package_manifest_sha256']==CONTROL_MANIFEST_SHA, 'fixed complete control package required')
    require(request['operation_timing_sha256']==request['base_operation_timing_sha256']==TIMING_SHA,
        'only actual fdd2 broad-window A0 is supported; alpha A0 cannot be substituted')
    require(request['transport_seed']==61017041 and request['gate_high_V']==2.4
        and request['source_epoch_s']==7.61e-8 and request['simulation_window_s']==[0,8.82e-8]
        and request['native_observation_window_s']==[7.6084e-8,7.61161e-8],
        'fixed original batch/physical operation differs')
    return obj(encoded(request))


def role_id(request):
    r=validate_request(request)
    return 'B2D-'+r['source_case']+'-proton-control-r1-main-b'+str(r['stored_bit'])+'-e'+str(r['event_id'])


def a0_input_scope(request, cfg, timing_raw):
    """Early identity check only; never substitutes for real archive/clock replay."""
    r=validate_request(request)
    require(sha(timing_raw)==TIMING_SHA, 'actual A0 is not the exact fdd2 proton timing')
    for k in ('stored_bit','gate_top_depth_nm','sn_junction_depth_nm','effective_width_nm','gate_high_V',
              'operation_timing_sha256','base_operation_timing_sha256','numerical_relation_sha256'):
        require(cfg[k]==r[k], 'actual A0/control identity mismatch: '+k)
    require(cfg['numerical_variant']=='main' and
        cfg['role_id']=='B2D-A0-parameterized-r1-main-b'+str(r['stored_bit']),
        'actual same-bit main A0 required')
    timing=obj(timing_raw)
    for k in ('source_epoch_s','mathematical_source_window_s','native_observation_window_s',
              'simulation_window_s','charge_window_s'):
        require(r[k]==timing[k], 'actual A0/control time mismatch: '+k)



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
    a0_input_scope(r,cfg,reader.read('operation-timing.json'))
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


def source_time_contract(device, timing, request, sources):
    S=shared();O=S.operation();t=O.validate_timing(timing);r=validate_request(request)
    require([s['event_id'] for s in sources]==EVENT_IDS,'complete four-event denominator required')
    full=t['simulation_window_s'];obs=t['native_observation_window_s'];mathwin=t['mathematical_source_window_s'];charge=t['charge_window_s']
    inventory=[event_coverage(s,full,obs) for s in sources];chosen=inventory[r['event_id']]
    require(all(row['full_covers_raw'] and row['full_covers_8sigma'] and row['observation_covers_8sigma'] for row in inventory),
        'all four original events require matching new A0 full/observation timing; retain all late records')
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


def control_package_files():
    """Exact permitted names, independent of a packet-provided path."""
    names={CONTROL_MANIFEST,'parent-bindings.json','control-input-index.json','parents/operation-timing.json'}
    names|={'parents/batch/'+n for n in ['adapter-manifest.json','native-batch-binding.json','replay-request.json']+
             ['event-'+str(i)+'-g3-source.json' for i in EVENT_IDS]}
    names|={'parents/source-inputs/'+n for n in ('candidate-input-manifest.json','input-hashes.sha256','all-event-source-inputs.json')}
    names|={'parents/source-inputs/event-'+str(i)+'/'+n for i in EVENT_IDS for n in SOURCE_FILES}
    names|={c+'/event-'+str(i)+'/'+n for c in CONTROL_CASES.values() for i in EVENT_IDS for n in CONTROL_FILES}
    return names


def frozen_control_package(reader, request):
    r=validate_request(request)
    raw=reader.read(CONTROL_PREFIX+CONTROL_MANIFEST)
    require(sha(raw)==CONTROL_MANIFEST_SHA==r['control_package_manifest_sha256'], 'wrong/falsified control package')
    manifest=obj(raw);names=control_package_files()
    require(set(manifest['files'])|{CONTROL_MANIFEST}==names and len(names)==102
        and manifest['implementation_sha256']==CONTROL_SHA, 'complete sealed control denominator differs')
    for name,row in manifest['files'].items():
        require(row==dict(sha256=reader.digest(CONTROL_PREFIX+name),size_bytes=reader.size(CONTROL_PREFIX+name)),
            'control package member differs: '+name)
    require(reader.digest(CONTROL_PREFIX+'parents/operation-timing.json')==TIMING_SHA
        and reader.read('operation-timing.json')==reader.read(CONTROL_PREFIX+'parents/operation-timing.json'),
        'control timing cannot replace actual A0 timing')
    index=obj(reader.read(CONTROL_PREFIX+'control-input-index.json'))
    require(index['original_request_event_ids']==EVENT_IDS and index['original_event_denominator']==4
        and index['original_step_denominator']==2012 and index['original_empty_LET_denominator']==4
        and len(index['entries'])==12, 'original event/step/undefined-LET denominator differs')
    control=CONTROL_CASES[r['source_case']];prefix=control+'/event-'+str(r['event_id'])+'/'
    rows=[e for e in index['entries'] if e['control']==control and e['original_event_id']==r['event_id']]
    require(len(rows)==1 and rows[0]['prefix']==prefix, 'control/event selection differs')
    selected={name:reader.read(CONTROL_PREFIX+prefix+name) for name in CONTROL_FILES}
    contract=obj(selected['control-contract.json'])
    require(contract['control']==control and contract['event_id']==r['event_id']
        and contract['represented_source_count']=={'zero':0,'half':500,'split':1000}[control],
        'control native representation differs')
    for name in ('projection-sources3d.dat','projection-context.dat'):
        require(reader.read(name)==selected[name], 'active control table/context differs: '+name)
    return dict(manifest=manifest,index=index,parent_binding=obj(reader.read(CONTROL_PREFIX+'parent-bindings.json')),
        selected_contract=contract,selected_uid_map=obj(selected['parent-child-map.json']),
        selected_ledger=obj(selected['input-only-linear-reference.json']),
        selected_terms=obj(selected['source-terms.json']),selected_prefix=prefix,
        guest_control_math_replayed=False,guest_complete_pinned_package_verified=True)


def _source_package_host(batch, source_folder, match, request):
    """Actual batch replay plus sealed control replay; no original quadrature rerun."""
    r=validate_request(request);C=control_math();folder=Path(r['control_package'])
    raw=C.directory_bytes(folder)
    require(sha(raw.get(CONTROL_MANIFEST,b''))==CONTROL_MANIFEST_SHA, 'wrong source/control package')
    require(set(raw)==control_package_files(), 'complete control package required')
    C.verify_payload(raw)
    batch_files=C.directory_bytes(batch);source_files=C.directory_bytes(source_folder)
    require({'parents/batch/'+n:v for n,v in batch_files.items()}==
        {n:v for n,v in raw.items() if n.startswith('parents/batch/')}, 'request batch differs from complete control parent')
    require({'parents/source-inputs/'+n:v for n,v in source_files.items()}==
        {n:v for n,v in raw.items() if n.startswith('parents/source-inputs/')}, 'request source inputs differ from complete control parent')
    require(match['shared']['operation-timing.json']==raw['parents/operation-timing.json'],
        'actual A0 is not the frozen proton-wide-window operation')
    replay=native_api().verify(batch)
    require(replay['binding']==obj(raw['parents/batch/native-batch-binding.json'])
        and replay['sources']==[obj(raw['parents/batch/event-'+str(i)+'-g3-source.json']) for i in EVENT_IDS],
        'actual full native batch replay differs')
    index=obj(raw['parents/source-inputs/all-event-source-inputs.json'])
    for name,key in [('model.proposed.json','model'),('geometry-contract.json','geometry'),('dimensional-contract.json','dimensional_contract')]:
        require(sha(match['shared'][name])==index['response_bindings'][key]['sha256'],
            'control parent response differs from true matching A0: '+name)
    selected=CONTROL_CASES[r['source_case']]+'/event-'+str(r['event_id'])+'/'
    return dict(replay=replay,control_files=raw,selected_files={n:raw[selected+n] for n in CONTROL_FILES})



def frozen_sources(reader, request, match, operations):
    control=frozen_control_package(reader,request)
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
    time=source_time_contract(match['device'],match['verified']['operation_timing'],r,sources)
    return dict(binding=bound,index=source_index,manifest=sm,batch_manifest=bm,sources=sources,
        selected_parent_ledger=obj(reader.read(chosen+'input-only-projection-reference.json')),
        selected_ledger=control['selected_ledger'],control=control,
        guest_mathematical_replay=False,guest_full_G4_CSV_replay=False,
        host_replay_implementations=dict(native=NATIVE_SHA,source_preparer=SOURCE_PREPARER_SHA)),time


def source_contract(request, projected, operations, timing):
    r=request;selected=projected['sources'][r['event_id']]
    return dict(schema='dram-see-v4-parameterized-proton-control-source-contract-r1',particle='proton',dimension=2,
        source_case=r['source_case'],control=CONTROL_CASES[r['source_case']],source_family='weighted-control-of-complete-native-BCAT-event',event_id=r['event_id'],
        seed=r['transport_seed'],original_request_event_ids=EVENT_IDS,original_request_event_count=4,
        energy_MeV=100,theta_deg=0,phi_deg=180,energy_definition='original G4 gun kinetic energy; retain original TOF and all deposited-energy accounts',
        full_simulation_window_s=r['simulation_window_s'],source_epoch_s=r['source_epoch_s'],
        native_observation_window_s=r['native_observation_window_s'],charge_window_s=r['charge_window_s'],
        temporal_sigma_s=SIGMA,spatial_width_um=WIDTH_UM,effective_width_nm=20,
        source_context_window_s=r['simulation_window_s'],required_source_window_s=timing['all_event_time_inventory'][r['event_id']]['required_8sigma_observation_s'],
        selected_source_rows=projected['control']['selected_contract']['represented_source_count'],
        configured_zero=(r['source_case']=='Z'),original_parent_is_structural_zero=not selected['terms'],
        control_package_manifest_sha256=CONTROL_MANIFEST_SHA,
        control_contract=projected['control']['selected_contract'],
        original_five_destination_ledger=projected['selected_parent_ledger'],
        controlled_linear_ledger=projected['selected_ledger'],
        independent_physical_event_count=4,half_device_linearity_required=False,
        original_positive_Si_charge_fC=selected['original_positive_Si_charge_fC'],
        complete_batch_binding_sha256=sha(encoded(projected['binding'])),
        actual_transport_operation_sha256=operations['transport']['receipt_sha256'],
        actual_transport_archive_sha256=operations['transport']['archive_sha256'],
        actual_PMI_build_operation_sha256=operations['pmi']['receipt_sha256'],
        actual_PMI_library_sha256=operations['pmi']['library_sha256'],
        reference_rate_cm_minus3_s_minus1=1e35,source_formula='fixed correlated 3D Gaussian segment -> exact y strip / 20nm -> actual BE interval average',
        source_clock='raw native PMI ReadTime/StepSize/StepType; no synthesis',additional_normalization=False,
        source_ledger_is_mathematical_input=True,native_source_qualified=False,pmi_r12_fixed=False,
        scientific_evidence_verified=False,training_admitted=False)


def binding(reader,cfg,matched,originals,projected,operations):
    return dict(schema=BINDING_SCHEMA,source_branch=BRANCH,verifier_sha256=sha(Path(__file__).read_bytes()),
        shared_identity_implementation_sha256=ALPHA_SHA,activation_implementation_sha256=ACTIVATION_SHA,
        native_batch_adapter_sha256=NATIVE_SHA,source_preparer_sha256=SOURCE_PREPARER_SHA,
        main_helper_sha256=MAIN_SHA,control_math_sha256=CONTROL_SHA,
        control_package_manifest_sha256=CONTROL_MANIFEST_SHA,
        native_control_representation_sha256=reader.digest('native-control-representation.json'),
        stored_bit=cfg['stored_bit'],event_id=obj(reader.read('controlled-request.json'))['event_id'],
        source_case=obj(reader.read('controlled-request.json'))['source_case'],
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
        guest_replay_scope='Original operation archives/inputs/exits + A0 clock/metrics + pinned complete control package/activation; G4/control math replay host-only',
        compiled_PMI_is_not_native_activation=True,source_native_activation_unverified=True,
        native_source_qualified=False,is_native_result=False,pmi_r12_fixed=False,
        scientific_evidence_verified=False,training_admitted=False)


def source_spec(reader,r,binding_sha):
    source=obj(reader.read('source-contract.json'))
    return dict(schema=SPEC_SCHEMA,role='CONFIGURED_ZERO' if r['source_case']=='Z' else 'CONTROL',
        source_case=r['source_case'],control=CONTROL_CASES[r['source_case']],particle='proton',dimension=2,stored_bit=r['stored_bit'],numerical_variant='main',
        gate_top_depth_nm=80,sn_junction_depth_nm=87,event_id=r['event_id'],seed=r['transport_seed'],
        original_request_event_ids=EVENT_IDS,energy_MeV=100,theta_deg=0,phi_deg=180,source_configured=True,
        physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),source_contract_sha256=reader.digest('source-contract.json'),
        source_time_contract_sha256=reader.digest('source-time-contract.json'),parameterized_proton_control_binding_sha256=binding_sha,
        source_field='OpticalGeneration',common_pair_source=True,effective_width_applied_once=True,
        currentplot_domain='Semiconductor',currentplot_integration_unit='um',
        currentplot_is_diagnostic_not_field_qualification=True,
        native_source_qualified=False,pmi_r12_fixed=False,scientific_evidence_verified=False,training_admitted=False,
        control_field_replay_supported=False,control_response_replay_supported=False)


def role_contract(match,r,binding_sha,source_sha):
    result=dict(match['role']);result.pop('parameterized_operating_binding_sha256')
    result.update(schema=ROLE_SCHEMA,role=role_id(r),case=r['source_case'],source_configured=True,
        parameterized_proton_control_binding_sha256=binding_sha,matched_a0_operating_binding_sha256=match['operating_binding_sha256'],
        event_id=r['event_id'],seed=r['transport_seed'],original_request_event_ids=EVENT_IDS,
        energy_MeV=100,theta_deg=0,phi_deg=180,source_contract_sha256=source_sha,
        native_syntax_verified=False,native_source_qualified=False,pmi_r12_fixed=False,
        scientific_evidence_verified=False,training_admitted=False)
    return result


def native_representation(reader,r):
    prefix=CONTROL_PREFIX+CONTROL_CASES[r['source_case']]+'/event-'+str(r['event_id'])+'/'
    return dict(schema='dram-see-v4-proton-control-native-representation-r1',
        source_case=r['source_case'],control=CONTROL_CASES[r['source_case']],event_id=r['event_id'],
        stored_bit=r['stored_bit'],role_id=role_id(r),source_branch=BRANCH,
        control_package_manifest_sha256=CONTROL_MANIFEST_SHA,original_event_ids=EVENT_IDS,
        original_step_count=2012,original_empty_LET_count=4,parent_kernel_count=500,
        active_rows={'Z':0,'H':500,'split':1000}[r['source_case']],
        source_table_sha256=reader.digest('projection-sources3d.dat'),
        context_sha256=reader.digest('projection-context.dat'),
        parent_child_map_sha256=reader.digest(prefix+'parent-child-map.json'),
        control_contract_sha256=reader.digest(prefix+'control-contract.json'),
        linear_reference_sha256=reader.digest(prefix+'input-only-linear-reference.json'),
        parser_sha256=M.PMI_HEADER_SHA,callback_sha256=M.PMI_CPP_SHA,math_header_sha256=M.PMI_MATH_SHA,
        operation_timing_sha256=TIMING_SHA,raw_Geant4_records_unchanged=True,
        new_physical_events=False,half_device_linearity_required=False,
        compiled_library_does_not_prove_control_activation=True,
        native_executed=False,native_source_qualified=False,scientific_evidence_verified=False,training_admitted=False)



def verify_frozen(reader,cfg):
    S=shared();P=S.parameterized();D=S.dimensional()
    require(cfg.get('source_branch')==BRANCH and cfg.get('dimension_branch')==P.DIMENSION_BRANCH
        and cfg.get('mode')=='reuse' and 'parameterized_operating_branch' not in cfg,'explicit proton source root required')
    for name,raw in _runtime_bytes().items():require(reader.digest(name)==sha(raw),'fixed runtime differs: '+name)
    for name,(_,digest) in HOST_SOURCES.items():require(reader.digest('proton-implementations/'+name)==digest,'host replay snapshot differs')
    result,_,_=P._verify_sources(reader,cfg);r=validate_request(obj(reader.read('controlled-request.json')))
    bound=obj(reader.read('parameterized-proton-control-binding.json'))
    require(bound.get('schema')==BINDING_SCHEMA and reader.digest('parameterized-proton-control-binding.json')==cfg.get('parameterized_proton_control_binding_sha256'),
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
    require(obj(reader.read('native-control-representation.json'))==native_representation(reader,r),
        'control representation/identity differs')
    for k in ('stored_bit','gate_top_depth_nm','sn_junction_depth_nm','effective_width_nm','gate_high_V',
              'operation_timing_sha256','base_operation_timing_sha256','numerical_relation_sha256',
              'mesh_sha256','producer_run_id','base_producer_run_id','numerical_variant'):
        require(cfg[k]==match['cfg'][k], 'control cfg differs from actual A0: '+k)
    require(obj(reader.read('source-time-contract.json'))==time,'full source-time statement differs')
    require(obj(reader.read('source-contract.json'))==source_contract(r,projected,operations,time),'source definition differs')
    require(bound==binding(reader,cfg,matched,originals,projected,operations),'complete original proton binding differs')
    spec=source_spec(reader,r,reader.digest('parameterized-proton-control-binding.json'))
    role=role_contract(match,r,reader.digest('parameterized-proton-control-binding.json'),reader.digest('source-contract.json'))
    require(obj(reader.read('source-spec.json'))==spec and obj(reader.read('role-contract.json'))==role
        and cfg['role_id']==role['role'],'proton source/role declaration differs')
    result.update(operation_timing=match['verified']['operation_timing'],operating_binding=match['verified']['operating_binding'],
        numerical_relation=match['verified']['numerical_relation'],source_spec=spec,role_contract=role,
        projection=projected,proton_control_binding=bound,matched_a0=matched,source_time_contract=time,
        activation=activation,pmi_build=operations['pmi'],native_batch=operations['transport'])
    require(set(result)==FROZEN_RESULT_KEYS,'public result shape differs');return result


def require_input_coverage(reader,hashes):
    """Every consumed proof/source must be in the original runner input manifest."""
    S=shared();D=S.dimensional()
    needed=set(D.SHARED_INPUTS)|set(S.SHARED)|set(RUNTIME_FILES)|set(obj(reader.read('d2-source-binding.json'))['original_files'])
    needed|={'project.json','controlled-request.json','case_contract.py','geometry_bridge.py','mesh_resource_guard.py',
        'generator-prepare_case.py','task-authorization.json','resource-policy.json','provenance.json',
        'device.cmd','cell_msh.tdr','cell_msh.log','d2-source-binding.json','dimensional-contract.json',
        'source-contract.json','source-time-contract.json','parameterized-proton-control-binding.json','source-spec.json','role-contract.json',
        'projection-sources3d.dat','projection-context.dat',LIBRARY,'proton-reference-apd.plx','proton-reference-spectrum.txt',
        'optical.currentplot.inc','native-control-representation.json'}
    needed|={A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}
    needed|={p+n for p in (TRANSPORT_PREFIX,BUILD_PREFIX,PMI_PREFIX) for n in ('operation.json','results.tar','inputs.tar')}
    needed|={CONTROL_PREFIX+n for n in control_package_files()}
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


def prepare(request,run_id,runner=None,output=None):
    """Create one original-runner input only after genuine complete dependency replay."""
    r=validate_request(request);S=shared();P=S.parameterized();O=S.operation();D=S.dimensional()
    C=module('case_contract.py');bridge=module('geometry_bridge.py')
    require(getattr(C,'SCHEMA_2D_PARAMETERIZED_PROTON_CONTROL',None)==REQUEST_SCHEMA and hasattr(bridge,'geometry_parameterized_proton_controls_module'),
        'proton dispatch not integrated; no project created')
    require(O.plain_name(run_id) and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id
        and run_id not in (O.source_name(r['matched_a0_run']),O.source_name(r['d2_source_run'])),'new real run ID required')
    runner=Path(runner or ROOT/'scripts/tcad.py').resolve();require(runner==(ROOT/'scripts/tcad.py').resolve(),'original runner only')
    allowed=(ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/proton-controls-runtime-r1').resolve()
    target=Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target),'new explicit project path required')
    for k in ('d2_source_run','base_d2_source_run','matched_a0_run','transport_batch_package','pmi_source_inputs','pmi_build_operation','control_package'):
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
    files.update({CONTROL_PREFIX+n:v for n,v in source['control_files'].items()})
    files.update({ACTIVATION_PREFIX+n:v for n,v in activation['files'].items()})
    files['source-time-contract.json']=encoded(time)
    for name in ('projection-sources3d.dat','projection-context.dat'):
        files[name]=source['selected_files'][name]
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
    files['native-control-representation.json']=encoded(native_representation(check,r))
    files['source-contract.json']=encoded(source_contract(r,projected,operations,time))
    original_rows={n:{k:v for k,v in row.items() if k!='path'} for n,row in originals.items()}
    bound=binding(check,cfg,matched,original_rows,projected,operations)
    files['parameterized-proton-control-binding.json']=encoded(bound);cfg['parameterized_proton_control_binding_sha256']=sha(files['parameterized-proton-control-binding.json'])
    files['source-spec.json']=encoded(source_spec(check,r,cfg['parameterized_proton_control_binding_sha256']))
    files['role-contract.json']=encoded(role_contract(match,r,cfg['parameterized_proton_control_binding_sha256'],sha(files['source-contract.json'])))
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-'+role.lower(),role=role,execution_enabled=True,
        runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))])
    files.update({'project.json':encoded(spec),'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',
        role=role,observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',source='current_user_instruction',
            synthetic=False,role_ids=[role],instruction='真实完整四event G4、固定控制包和实际二维PMI编译、匹配宽窗A0原证据后，沿原runner进行显式质子控制实验；保持原owner/共享锁与串行单核单线程，无项目额度。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',plan_sha256=D.file_sha(ROOT/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md'))),
        'provenance.json':encoded(dict(schema='dram-see-v4-parameterized-proton-control-input-provenance-r1',run_id=run_id,role=role,
            matched_a0=matched,host_A0_replayed=True,host_complete_G4_and_control_relation_replayed=True,original_parent_quadrature_reused=True,
            actual_new_PMI_build_replayed=True,all_original_event_ids=EVENT_IDS,selected_event_id=r['event_id'],
            source_free_deck_byte_identical=True,additional_normalization=False,actual_native_submissions=0,
            native_activation_verified=False,native_source_qualified=False,pmi_r12_fixed=False,
            scientific_evidence_verified=False,training_admitted=False))})
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
        parameterized_proton_control_binding_sha256=cfg['parameterized_proton_control_binding_sha256'],input_manifest_sha256=sha(files['input-manifest.json']),
        matched_a0=matched,native_submissions=0,native_source_qualified=False,pmi_r12_fixed=False,
        scientific_evidence_verified=False,training_admitted=False)
