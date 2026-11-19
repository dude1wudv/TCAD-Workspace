"""Six-condition proton h2/dt2 runtime over actual same-condition D2/A0 and BCAT.

The original raw batch, all UID/steps and fixed CPP/PMI bytes remain distinct
from native source qualification. No role/schema is disguised as old main.
Guest closure is Python 3.6; full G4/source mathematics is host-only.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import tarfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
MAIN_SHA='d6270e76a8d9dd790ceed63be708a3eae22b0e62d23b623afb942c5401d284a0'
MULTI_NATIVE_SHA='44a207218fcdf7328f778cb6ee56b08504f6a7b014df843e87df4fe231b9dbd6'
def _main():
    path=HERE/'parameterized_proton_2d.py';raw=path.read_bytes()
    if path.is_symlink() or hashlib.sha256(raw).hexdigest()!=MAIN_SHA:
        raise ValueError('Fixed original proton runtime changed')
    spec=importlib.util.spec_from_file_location('_proton_multicondition_original',str(path))
    value=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),value.__dict__);return value
M=_main()
BRANCH='dram-see-v4-parameterized-proton-multicondition-refinement-2d-r1'
REQUEST_SCHEMA='dram-see-v4-parameterized-proton-multicondition-refinement-request-r1'
BINDING_SCHEMA='dram-see-v4-parameterized-proton-multicondition-refinement-binding-r1'
SPEC_SCHEMA='dram-see-v4-parameterized-proton-multicondition-refinement-source-spec-r1'
ROLE_SCHEMA='dram-see-v4-parameterized-proton-multicondition-refinement-role-r1'
TIME_SCHEMA='dram-see-v4-parameterized-proton-multicondition-refinement-native-time-r1'
SOURCE_CONTRACT_SCHEMA='dram-see-v4-parameterized-proton-multicondition-refinement-source-contract-r1'
NATIVE_BINDING_SCHEMA='dram-see-v4-bcat-multicondition-2d-r1-binding'
NATIVE_MANIFEST_SCHEMA='dram-see-v4-bcat-multicondition-2d-r1-batch'
SOURCE_INDEX_SCHEMA='dram-see-v4-bcat-multicondition-2d-r1-source-inputs'
SOURCE_MANIFEST_SCHEMA='dram-see-v4-bcat-multicondition-2d-r1-source-manifest'
DEVELOPMENT={'proton-T01':(70,50,0),'proton-T02':(70,100,0),'proton-T03':(80,50,0),
             'proton-T04':(80,100,0),'proton-T05':(70,50,30),'proton-T06':(80,100,30)}
REQUEST_FIELDS=M.REQUEST_FIELDS|{'condition_id'}
FROZEN_RESULT_KEYS=M.FROZEN_RESULT_KEYS
RUNTIME_FILES=M.RUNTIME_FILES+('parameterized_proton_multicondition_2d.py','parameterized_proton_multicondition_refinement_2d.py',)
MULTICONDITION_MAIN_SHA='04e8f859c9d10c7d8c58ac2924b8cdf875c8ef816e0f16379aad8112746bf71d'
REFERENCE_PREFIX='proton-multicondition-reference-inputs/'
REFERENCE_NAMES=('model.proposed.json','geometry-contract.json','dimensional-contract.json')
ALPHA_SHA=M.ALPHA_SHA
ACTIVATION_SHA=M.ACTIVATION_SHA
NATIVE_SHA=M.NATIVE_SHA
SOURCE_PREPARER_SHA=M.SOURCE_PREPARER_SHA
PMI_CPP_SHA=M.PMI_CPP_SHA
PMI_MATH_SHA=M.PMI_MATH_SHA
PMI_HEADER_SHA=M.PMI_HEADER_SHA
LIBRARY=M.LIBRARY
SIGMA=M.SIGMA
WIDTH_UM=M.WIDTH_UM
SUPPORT_SIGMA=M.SUPPORT_SIGMA
A0_PREFIX=M.A0_PREFIX
TRANSPORT_PREFIX=M.TRANSPORT_PREFIX
BUILD_PREFIX=M.BUILD_PREFIX
PMI_PREFIX=M.PMI_PREFIX
BATCH_PREFIX='proton-multicondition-batch/'
SOURCE_PREFIX='proton-multicondition-source/'
ACTIVATION_PREFIX=M.ACTIVATION_PREFIX
SOURCE_FILES=M.SOURCE_FILES
CURRENT_DIAGNOSTIC=M.CURRENT_DIAGNOSTIC
FRAGMENTS=M.FRAGMENTS
HOST_SOURCES=dict(M.HOST_SOURCES)
HOST_SOURCES.update({
 'bcat_multicondition_adapter.py':('projection2d',MULTI_NATIVE_SHA),
 'transport_prepare_v2.py':('proton','fac600ae7ad11a258db2d1bbd312411511ea46987c1269e476bcd840263ecf61'),
 'proton_geometry_v2.py':('proton','09aa8966d9320e0fa1981a516e5a78a2d228a0a74ca9199534efffe472f9c394'),
 'proton_common_v2.py':('proton','6e0fe5c77a0efcc1b4d8dfb93216f8126c2bc577ffee80cf124d64e4f8fa90c4')})
# Pure/shared boundaries do not reinterpret any role or request schema.
require=M.require
sha=M.sha
encoded=M.encoded
obj=M.obj
number=M.number
module=M.module
shared=M.shared
activation_api=M.activation_api
table_bytes=M.table_bytes
context_bytes=M.context_bytes
event_coverage=M.event_coverage
render_signal=M.render_signal
source_free_deck=M.source_free_deck
frozen_operation=M.frozen_operation
_operation_originals=M._operation_originals
_prefixed_files=M._prefixed_files
frozen_activation=M.frozen_activation
CompositeReader=M.CompositeReader

def main_runtime():
    return module('parameterized_proton_multicondition_2d.py',MULTICONDITION_MAIN_SHA)

def host_api():
    return module('bcat_multicondition_adapter.py',MULTI_NATIVE_SHA,'projection2d')

def event_ids(request):
    return list(range(request['original_event_count']))

def validate_request(request):
    O=shared().operation()
    require(isinstance(request,dict) and set(request)==REQUEST_FIELDS,'exact new multicondition request required')
    for key,value in dict(schema=REQUEST_SCHEMA,kind='transient',source_case='Aproton',particle='proton').items():
        require(request[key]==value,'explicit multicondition refinement branch differs: '+key)
    for key,value in dict(dimension=2,sn_junction_depth_nm=87,effective_width_nm=20,phi_deg=180).items():
        require(type(request[key]) is int and request[key]==value,'fixed representative-cell input differs: '+key)
    require(request['variant'] in ('h2','dt2'),'explicit h2/dt2 request required')
    cid=request['condition_id']
    require(cid in DEVELOPMENT and all(type(request[key]) is int for key in ('gate_top_depth_nm','energy_MeV','theta_deg'))
        and tuple(request[key] for key in ('gate_top_depth_nm','energy_MeV','theta_deg'))==DEVELOPMENT[cid],
        'condition outside this six-train-condition runtime; another explicit provider is needed')
    require(type(request['stored_bit']) is int and request['stored_bit'] in (0,1),'integer bit required')
    require(type(request['original_event_count']) is int and request['original_event_count']>0
        and type(request['event_id']) is int and 0<=request['event_id']<request['original_event_count'],
        'selected event must belong to the complete original positive request denominator')
    require(type(request['transport_seed']) is int and request['transport_seed']>0,'explicit actual seed required')
    for key in ('d2_source_run','base_d2_source_run','matched_a0_run','transport_batch_package','pmi_source_inputs','pmi_build_operation'):
        require(isinstance(request[key],str) and request[key].strip(),'explicit actual dependency path required: '+key)
    for key in ('operation_timing_sha256','base_operation_timing_sha256','numerical_relation_sha256'):
        require(O.digest_ok(request[key]),'explicit original timing/relation hash required')
    require(number(request['gate_high_V']) and request['gate_high_V']>-.5
        and number(request['source_epoch_s']) and request['source_epoch_s']>0,'finite explicit gate/epoch required')
    for key in ('mathematical_source_window_s','native_observation_window_s','simulation_window_s','charge_window_s'):
        interval=request[key]
        require(isinstance(interval,list) and len(interval)==2 and all(number(v) for v in interval)
            and 0<=interval[0]<interval[1],'explicit physical second interval required: '+key)
    full=request['simulation_window_s']
    require(full[0]==0 and full[0]<request['source_epoch_s']<full[1],'complete physical operation required')
    for key in ('mathematical_source_window_s','native_observation_window_s','charge_window_s'):
        require(full[0]<=request[key][0]<request[key][1]<=full[1],'interval outside full operation')
    return obj(encoded(request))

def role_id(request):
    r=validate_request(request)
    return 'B2D-Aproton-multicondition-refinement-r1-{}-g{}-p{}-a{}-b{}-e{}'.format(
        r['variant'],r['gate_top_depth_nm'],r['energy_MeV'],r['theta_deg'],r['stored_bit'],r['event_id'])

def _runtime_bytes():
    result=main_runtime()._runtime_bytes()
    require(sha(result['parameterized_proton_multicondition_2d.py'])==MULTICONDITION_MAIN_SHA,
        'fixed explicit multicondition parent runtime changed')
    result['parameterized_proton_multicondition_refinement_2d.py']=Path(__file__).read_bytes()
    require(set(result)==set(RUNTIME_FILES),'closed refinement runtime inventory differs')
    return result

def dependency_status(request):
    """Reference availability only; this cannot grant native or source evidence."""
    r=validate_request(request);rows=[]
    files={'d2_source_run':'manifest.json','base_d2_source_run':'manifest.json',
           'matched_a0_run':'manifest.json','transport_batch_package':'adapter-manifest.json',
           'pmi_source_inputs':'candidate-input-manifest.json','pmi_build_operation':'operation.json'}
    for key,name in files.items():
        original=Path(r[key]);path=original.resolve()
        safe=not original.is_symlink() and ROOT in path.parents
        candidate=path/name
        present=safe and candidate.is_file() and not candidate.is_symlink()
        rows.append(dict(dependency=key,path=str(path),required_original=name,present=present,
            reason=None if present else 'Missing original same-condition dependency reference; full replay has not run'))
    return dict(schema=BRANCH+'-dependency-status',condition_id=r['condition_id'],event_id=r['event_id'],
        original_event_ids=event_ids(r),references=rows,
        status='INPUT_REFERENCES_PRESENT_REPLAY_REQUIRED' if all(x['present'] for x in rows) else 'PENDING_ACTUAL_DEPENDENCIES',
        original_archives_verified=False,source_native_qualified=False,training_admitted=False,native_calls=0)

def batch_request_identity(bound,native_request,request):
    """Pure condition/seed/full-denominator join; not an operation verifier."""
    r=validate_request(request);condition=bound['condition']
    require(condition['condition_id']==r['condition_id'] and condition['split']=='train'
        and float(condition['gate_top_depth_nm'])==r['gate_top_depth_nm']
        and float(condition['energy_MeV'])==r['energy_MeV'] and float(condition['angle_deg'])==r['theta_deg'],
        'actual source condition differs from requested same-condition runtime')
    require(bound['original_request_event_ids']==event_ids(r)
        and bound['original_request_event_count']==native_request['event_count']==r['original_event_count'],
        'complete actual request denominator differs')
    require(bound['seed']==native_request['seed']==r['transport_seed']
        and native_request['energy_MeV']==r['energy_MeV'] and native_request['theta_deg']==r['theta_deg']
        and native_request['phi_deg']==180 and native_request['target_um']==[-.052,0.,0.]
        and bound['epoch_s']==r['source_epoch_s'],'actual native seed/beam/epoch differs')
    return dict(condition_id=r['condition_id'],seed=r['transport_seed'],event_ids=event_ids(r),
        selected_event_id=r['event_id'],binding_only=True,native_qualified=False)

def source_geometry_relation(reference, actual, frozen):
    """Compare original source domain to actual base/selected geometry, not labels."""
    P=shared().parameterized();b=frozen['binding']
    gate=obj(reference['model.proposed.json'])['geometry']['gate_top_depth_nm']
    require(gate in (70,80),'source reference needs an explicit supported development geometry')
    base=b['sources'][b['base_source_key']]['record']
    rows={}
    for name in ('model.proposed.json','geometry-contract.json'):
        require(sha(reference[name])==base['shared_sha256'][name],
                'source reference is not the actual base D2 input: '+name)
        rows[name]=dict(original_sha256=sha(reference[name]),actual_sha256=sha(actual[name]))
    require(reference['model.proposed.json']==actual['model.proposed.json'],'refinement changes physical model bytes')
    require(P._physical_geometry(reference['geometry-contract.json'],gate)==
            P._physical_geometry(actual['geometry-contract.json'],gate),'refinement changes source material/physical geometry')
    original=obj(reference['dimensional-contract.json']);selected=obj(actual['dimensional-contract.json'])
    require(original['producer_run_id']==base['run_id'] and original['mesh_sha256']==base['mesh_sha256']
        and original['geometry_contract_sha256']==sha(reference['geometry-contract.json'])
        and original['physics_manifest_sha256']==selected['physics_manifest_sha256'],
        'source width provenance is not actual base D2')
    provenance=('producer_run_id','mesh_sha256','geometry_contract_sha256')
    require({k:v for k,v in original.items() if k not in provenance}==
            {k:v for k,v in selected.items() if k not in provenance},'source width/units/current/capacitance meaning changes')
    rows['dimensional-contract.json']=dict(original_sha256=sha(reference['dimensional-contract.json']),
                                          actual_sha256=sha(actual['dimensional-contract.json']))
    return dict(schema='dram-see-v4-proton-multicondition-source-refinement-domain-relation-r1',
        original_base_producer_run_id=base['run_id'],actual_selected_producer_run_id=b['producer_run_id'],
        input_sha256=rows,physical_model_and_geometry_equal=True,physical_width_semantics_equal=True,
        distinct_provenance_keys=list(provenance),original_source_bytes_unchanged=True,
        mesh_relation_scope='Original ed336 full selected/base D2 replay; not a claim about every individual element diameter',
        native_source_qualified=False,training_admitted=False)

def reference_inputs_from_index(index):
    result={}
    for name,key in zip(REFERENCE_NAMES,('model','geometry','dimensional_contract')):
        row=index['response_bindings'][key];path=Path(row['path'])
        require(path.is_file() and not path.is_symlink(),'missing original source-domain input: '+name)
        raw=path.read_bytes();require(sha(raw)==row['sha256'],'original source-domain input changed: '+name)
        result[name]=raw
    return result


def _source_package_host(batch,source_folder,match,request):
    H=host_api();folder=Path(source_folder)
    index=obj((folder/'all-event-source-inputs.json').read_bytes())
    reference=reference_inputs_from_index(index)
    relation=source_geometry_relation(reference,match['shared'],match['verified'])
    refs=index['response_bindings']
    result=H.verify_source_package(batch,source_folder,refs['model']['path'],refs['geometry']['path'],
        refs['dimensional_contract']['path'],request['simulation_window_s'])
    bound=result['replay']['binding']
    require(H.ref(bound['request']['path'])==bound['request'],'original request changed after batch replay')
    batch_request_identity(bound,H.read(bound['request']['path']),request)
    result.update(reference_files=reference,source_geometry_relation=relation)
    return result

def geometry_relation(reader,match,operations,bound,request):
    D=shared().dimensional()
    with reader.stream(TRANSPORT_PREFIX+'results.tar') as stream:
        with tarfile.open(fileobj=stream,mode='r:*') as archive:
            original=D.ArchiveReader(archive)
            model=obj(original.read('model-input.json'));geometry=obj(original.read('geometry-contract.json'))
            for name,key in [('model-input.json','model'),('geometry-contract.json','geometry'),('transport_bcat.cc','compiled_exporter')]:
                require(original.digest(name)==bound[key]['sha256'],'original transport identity differs: '+name)
            require(original.digest('transport_bcat.cc')=='3954e216b0fca01610e213c9cc2242d225a7333156a44efd829343c83c1ababb',
                    'original BCAT C++ changed')
            for name in ('transport_bcat.cc','geometry.hh','geometry-contract.json','model-input.json','geometry-probes.tsv','build-sha256.txt'):
                require(operations['transport']['inventory'][name]['sha256']==operations['build']['inventory'][name]['sha256'],
                        'transport did not use its original corresponding build input: '+name)
    actual_model=obj(match['shared']['model.proposed.json']);g=obj(match['shared']['geometry-contract.json'])
    require(model['geometry']==actual_model['geometry'] and model['doping']==actual_model['doping'],
            'G4 and real A0 physical geometry/doping models differ')
    require(model['geometry']['gate_top_depth_nm']==request['gate_top_depth_nm']
        and model['geometry']['active_width_nm']==20 and model['doping']['sn_junction_depth_nm']==87,
        'actual source model condition differs')
    native=geometry['geometry']
    require(native['dimension']==3 and g['dimension']==2 and native['length_unit']==g['length_unit']=='um'
        and geometry['gate_transport_material']=='G4_Galactic','explicit corresponding 3D transport and 2D response domains required')
    for axis in ('x','z'):require(native['domain_um'][axis]==g['domain_um'][axis],'transport/response finite domain differs')
    require(native['domain_um']['y'][0]<=-.01 and native['domain_um']['y'][1]>=.01,'transport misses physical width')
    for region,keys in [('outer_trench',('x_half_width_um','radius_um','round_center_z_um','top_um','bottom_um','construction')),
                        ('gate_void',('x_half_width_um','radius_um','round_center_z_um','top_um','bottom_um'))]:
        require(all(native[region][key]==g[region][key] for key in keys)
            and native[region]['y_half_width_um']>=.01,'transport/response material boundary differs: '+region)
    require(g['sti']['included'] is False and native['sti']['included'] is True
        and all(max(a,-.01)>=min(b,.01) for a,b in native['sti']['y_intervals_um']),'STI intersects response strip')
    require(operations['transport']['metadata']['geometry']==geometry,'original embedded metadata geometry differs')
    return dict(actual_transport_geometry_sha256=bound['geometry']['sha256'],
        actual_response_geometry_sha256=reader.digest('geometry-contract.json'),
        actual_transport_model_sha256=bound['model']['sha256'],actual_response_model_sha256=reader.digest('model.proposed.json'),
        condition_id=request['condition_id'],physical_material_geometry_matched=True,
        effective_width_nm=20,guest_full_geometry_math_replayed=False,native_source_qualified=False)

def frozen_sources(reader,request,match,operations):
    r=request;ids=event_ids(r)
    expected_source={'all-event-source-inputs.json'}|{'event-'+str(e)+'/'+n for e in ids for n in SOURCE_FILES}
    sm=_prefixed_files(reader,SOURCE_PREFIX,'candidate-input-manifest.json',expected_source)
    legacy=sm['schema']=='dram-see-v4-projection-candidate-inputs-r1'
    require(sm['schema'] in ('dram-see-v4-projection-candidate-inputs-r1',SOURCE_MANIFEST_SCHEMA)
        and sm['preparer']['sha256']==(SOURCE_PREPARER_SHA if legacy else MULTI_NATIVE_SHA)
        and sm['native_source_qualified'] is False,'frozen source provider differs')
    bm=_prefixed_files(reader,BATCH_PREFIX,'adapter-manifest.json',{'native-batch-binding.json','replay-request.json'}|
        {'event-'+str(i)+'-g3-source.json' for i in ids})
    bound=obj(reader.read(BATCH_PREFIX+'native-batch-binding.json'))
    index=obj(reader.read(SOURCE_PREFIX+'all-event-source-inputs.json'))
    legacy_batch=bm['schema']=='dram-see-v4-bcat-native-adapter-package-r1'
    require(bm['schema'] in ('dram-see-v4-bcat-native-adapter-package-r1',NATIVE_MANIFEST_SCHEMA)
        and bound['schema']==('dram-see-v4-bcat-native-complete-batch-binding-r1' if legacy_batch else NATIVE_BINDING_SCHEMA)
        and bound['adapter_implementation']['sha256']==(NATIVE_SHA if legacy_batch else MULTI_NATIVE_SHA)
        and (legacy_batch or bm['implementation']['sha256']==MULTI_NATIVE_SHA)
        and (not legacy or legacy_batch),'explicit old/new batch format differs')
    require(index['schema']==('dram-see-v4-projection-native-source-input-candidate-r1' if legacy else SOURCE_INDEX_SCHEMA)
        and index['source_adapter']['sha256']==(NATIVE_SHA if legacy else MULTI_NATIVE_SHA),'explicit source index provider differs')
    transport,build=operations['transport'],operations['build'];native_request=transport['request'];meta=transport['metadata']
    batch_request_identity(bound,native_request,r)
    require(bm['event_ids']==bound['original_request_event_ids']==ids
        and bound['original_request_event_count']==r['original_event_count'] and bound['no_event_filter'] is True
        and bound['epoch_s']==r['source_epoch_s'] and index['batch_binding']==bound
        and index['omitted_event_ids']==[] and index['complete_window_s']==r['simulation_window_s'],
        'complete original batch/time denominator differs')
    condition=bound['condition']
    require(condition['condition_id']==r['condition_id'] and condition['split']=='train'
        and float(condition['gate_top_depth_nm'])==r['gate_top_depth_nm']
        and float(condition['energy_MeV'])==r['energy_MeV'] and float(condition['angle_deg'])==r['theta_deg'],
        'actual native batch belongs to another frozen condition')
    require(native_request['event_count']==r['original_event_count'] and native_request['energy_MeV']==r['energy_MeV']
        and native_request['theta_deg']==r['theta_deg'] and native_request['phi_deg']==180
        and native_request['target_um']==[-.052,0.,0.] and native_request['seed']==r['transport_seed']==bound['seed']
        and native_request['label']==transport['label'] and native_request['source_operation_sha256']==build['receipt_sha256'],
        'actual native request/seed/condition/build differs')
    require(meta['primary_particle']=='proton' and meta['energy_MeV']==r['energy_MeV'] and meta['angle_deg']==r['theta_deg']
        and meta['units']==dict(length='um',time='ns',energy='MeV',charge='eplus',direction='unit_vector')
        and transport['status']['events_completed']==transport['status']['events_requested']==r['original_event_count']
        and transport['status']['state']=='COMPLETED','actual native completion/units differ')
    for key,op in [('operation',transport),('build_operation',build)]:
        require(bound[key]['sha256']==op['receipt_sha256'],'native operation binding differs')
    require(bound['archive']['sha256']==transport['archive_sha256'] and bound['build_archive']['sha256']==build['archive_sha256']
        and bound['binary']['sha256']==transport['transport_binary_sha256']==build['transport_binary_sha256'],
        'corresponding actual G4 build/run archive differs')
    for name,row in bound['raw_files'].items():
        require(row['sha256']==transport['inventory'][name]['sha256'],'complete original native member differs: '+name)
    reference={name:reader.read(REFERENCE_PREFIX+name) for name in REFERENCE_NAMES}
    for name,key in zip(REFERENCE_NAMES,('model','geometry','dimensional_contract')):
        require(sha(reference[name])==index['response_bindings'][key]['sha256'],
            'original source-domain reference identity differs: '+name)
    source_relation=source_geometry_relation(reference,{n:reader.read(n) for n in REFERENCE_NAMES},match['verified'])
    relation=geometry_relation(reader,match,operations,bound,r)
    sources=[]
    for eid in ids:
        prefix=SOURCE_PREFIX+'event-'+str(eid)+'/'
        raw=reader.read(prefix+'full-original-event-source.json')
        require(raw==reader.read(BATCH_PREFIX+'event-'+str(eid)+'-g3-source.json'),'complete original event bytes differ')
        value=obj(raw);sources.append(value)
        require(value['event_id']==eid and value['seed']==r['transport_seed'] and value['epoch_s']==r['source_epoch_s']
            and value['energy_MeV']==r['energy_MeV'] and value['angle_deg']==r['theta_deg']
            and value['all_selected_event_steps_retained'] is True
            and value['context']['original_request_denominator']==ids
            and value['context']['original_batch_binding_sha256']==sha(encoded(bound)),
            'original event/ancestry/UID denominator differs')
        require(reader.read(prefix+'projection-sources3d.dat')==table_bytes(value['terms'])
            and reader.read(prefix+'projection-context.dat')==context_bytes(r['simulation_window_s']),
            'original source table/context bytes differ')
        row=index['events'][eid]
        require(row['event_id']==eid and row['source_rows']==len(value['terms'])
            and row['all_original_steps_retained'] is True,'complete source index differs')
    require([row['event_id'] for row in index['events']]==ids,'source index drops or duplicates event')
    chosen=SOURCE_PREFIX+'event-'+str(r['event_id'])+'/'
    for name in ('projection-sources3d.dat','projection-context.dat'):
        require(reader.read(name)==reader.read(chosen+name),'active table is not the complete selected original event')
    time=source_time_contract(match['device'],match['verified']['operation_timing'],r,sources)
    return dict(binding=bound,index=index,manifest=sm,batch_manifest=bm,sources=sources,
        selected_ledger=obj(reader.read(chosen+'input-only-projection-reference.json')),
        material_domain_relation=relation,source_geometry_relation=source_relation,guest_mathematical_replay=False,guest_full_G4_CSV_replay=False,
        host_replay_implementations=dict(native=MULTI_NATIVE_SHA,legacy_native=NATIVE_SHA,source_preparer=SOURCE_PREPARER_SHA)),time

def verify_matched_a0(reader, manifest, inputs, request):
    S=shared();D=S.dimensional();O=S.operation();r=validate_request(request)
    S.alpha()._collection(reader,manifest,inputs,D)
    project=obj(reader.read('project.json'));cfg=project['s2_geometry'];context=obj(reader.read('execution-context.json'))
    wanted='B2D-A0-parameterized-r1-'+r['variant']+'-b'+str(r['stored_bit'])
    require(project.get('role')==cfg.get('role_id')==context.get('role_id')==wanted
        and cfg.get('parameterized_operating_branch')==S.parameterized().BRANCH
        and cfg.get('run_id')==manifest.get('run_id') and cfg.get('mode')=='reuse'
        and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
        and project.get('execution_enabled') is True and project.get('native_threads')==project.get('native_cores')==1
        and project.get('steps')==manifest.get('steps')==[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))],
        'real same-bit same-variant r13 A0/native serial source required')
    audited=S.baseline_api().audit_reader(reader,cfg)
    require(set(audited)=={'frozen','clock','metrics','identity'},'baseline replay API differs')
    frozen,clock,metrics=audited['frozen'],audited['clock'],audited['metrics'];timing=frozen['operation_timing']
    require(timing['origin']=='prescribed_input' and metrics['candidate_functional_pass'] is True
        and len(metrics['checks'])==5 and all(v is True for v in metrics['checks'].values()),
        'actual matching A0 five criteria/KCL not passed: '+json.dumps(metrics.get('checks'),sort_keys=True))
    require(clock['trace']==metrics['accepted_trace'] and metrics['time_coordinate_transformed'] is False
        and audited['identity']['complete_clock_evidence_verified'] is True,'original physical clock/rows required')
    require(cfg.get('numerical_variant')==r['variant'],'actual A0 numerical variant differs')
    S.parameterized().timing_relation(reader.read('base-operation-timing.json'),reader.read('operation-timing.json'),r['variant'])
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
    require(cfg['numerical_variant']==r['variant']
        and O.source_name(r['matched_a0_run'])==identity['run_id']
        and O.source_name(r['d2_source_run'])==identity['producer_run_id']
        and O.source_name(r['base_d2_source_run'])==identity['base_producer_run_id'],'actual A0/D2 source differs')
    for k in ('source_epoch_s','mathematical_source_window_s','native_observation_window_s','simulation_window_s','charge_window_s'):
        require(r[k]==t[k],'request silently changes A0 physical timing: '+k)

def source_time_contract(device, timing, request, sources):
    S=shared();O=S.operation();t=O.validate_timing(timing);r=validate_request(request);ids=event_ids(r)
    require([s['event_id'] for s in sources]==ids,'complete original event denominator required')
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

def source_contract(request, projected, operations, timing):
    r=request;selected=projected['sources'][r['event_id']]
    return dict(schema=SOURCE_CONTRACT_SCHEMA,particle='proton',dimension=2,condition_id=r['condition_id'],gate_top_depth_nm=r['gate_top_depth_nm'],sn_junction_depth_nm=87,
        source_family='complete-native-BCAT-event-projected-through-20nm-strip',event_id=r['event_id'],
        seed=r['transport_seed'],numerical_variant=r['variant'],original_request_event_ids=event_ids(r),original_request_event_count=r['original_event_count'],
        energy_MeV=r['energy_MeV'],theta_deg=r['theta_deg'],phi_deg=180,energy_definition='original G4 gun kinetic energy; retain original TOF and all deposited-energy accounts',
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
    request=obj(reader.read('controlled-request.json'))
    return dict(schema=BINDING_SCHEMA,source_branch=BRANCH,verifier_sha256=sha(Path(__file__).read_bytes()),
        shared_identity_implementation_sha256=ALPHA_SHA,activation_implementation_sha256=ACTIVATION_SHA,
        native_batch_adapter_sha256=MULTI_NATIVE_SHA,source_preparer_sha256=SOURCE_PREPARER_SHA,
        condition_id=request['condition_id'],gate_top_depth_nm=request['gate_top_depth_nm'],energy_MeV=request['energy_MeV'],theta_deg=request['theta_deg'],
        numerical_variant=cfg['numerical_variant'],original_main_runtime_sha256=MULTICONDITION_MAIN_SHA,
        source_geometry_relation=projected['source_geometry_relation'],stored_bit=cfg['stored_bit'],event_id=obj(reader.read('controlled-request.json'))['event_id'],
        producer_run_id=cfg['producer_run_id'],mesh_sha256=reader.digest('cell_msh.tdr'),
        operation_timing_sha256=reader.digest('operation-timing.json'),numerical_relation_sha256=reader.digest('numerical-relation.json'),
        physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        source_contract_sha256=reader.digest('source-contract.json'),source_time_contract_sha256=reader.digest('source-time-contract.json'),
        source_table_sha256=reader.digest('projection-sources3d.dat'),source_context_sha256=reader.digest('projection-context.dat'),
        complete_source_package_manifest_sha256=reader.digest(SOURCE_PREFIX+'candidate-input-manifest.json'),
        complete_batch_package_manifest_sha256=reader.digest(BATCH_PREFIX+'adapter-manifest.json'),
        activation_package_manifest_sha256=reader.digest(ACTIVATION_PREFIX+'candidate-input-manifest.json'),
        actual_PMI_library_sha256=reader.digest(LIBRARY),matched_a0=matched,original_files=originals,
        operations=operations,original_event_ids=event_ids(request),omitted_event_ids=[],
        all_event_source_rows=[len(s['terms']) for s in projected['sources']],
        guest_replay_scope='Complete original archives/inputs/exits + A0 clock/metrics + frozen source/activation consistency; G4 CSV/math replay is host-only',
        compiled_PMI_is_not_native_activation=True,source_native_activation_unverified=True,
        native_source_qualified=False,is_native_result=False,pmi_r12_fixed=False,training_admitted=False)

def source_spec(reader,r,binding_sha):
    source=obj(reader.read('source-contract.json'))
    return dict(schema=SPEC_SCHEMA,role='STRUCTURAL_ZERO' if source['selected_structural_zero'] else 'SIGNAL',
        source_case='Aproton',condition_id=r['condition_id'],particle='proton',dimension=2,stored_bit=r['stored_bit'],numerical_variant=r['variant'],
        gate_top_depth_nm=r['gate_top_depth_nm'],sn_junction_depth_nm=87,event_id=r['event_id'],seed=r['transport_seed'],
        original_request_event_ids=event_ids(r),energy_MeV=r['energy_MeV'],theta_deg=r['theta_deg'],phi_deg=180,source_configured=True,
        physics_manifest_sha256=reader.digest('physics-manifest.json'),dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),source_contract_sha256=reader.digest('source-contract.json'),
        source_time_contract_sha256=reader.digest('source-time-contract.json'),parameterized_proton_multicondition_refinement_binding_sha256=binding_sha,
        source_field='OpticalGeneration',common_pair_source=True,effective_width_applied_once=True,
        currentplot_domain='Semiconductor',currentplot_integration_unit='um',
        currentplot_is_diagnostic_not_field_qualification=True,
        native_source_qualified=False,pmi_r12_fixed=False)

def role_contract(match,r,binding_sha,source_sha):
    result=dict(match['role']);result.pop('parameterized_operating_binding_sha256')
    result.update(schema=ROLE_SCHEMA,role=role_id(r),case='Aproton',condition_id=r['condition_id'],source_configured=True,
        parameterized_proton_multicondition_refinement_binding_sha256=binding_sha,matched_a0_operating_binding_sha256=match['operating_binding_sha256'],
        event_id=r['event_id'],seed=r['transport_seed'],original_request_event_ids=event_ids(r),
        energy_MeV=r['energy_MeV'],theta_deg=r['theta_deg'],phi_deg=180,source_contract_sha256=source_sha,
        native_syntax_verified=False,native_source_qualified=False,pmi_r12_fixed=False)
    return result

def verify_frozen(reader,cfg):
    S=shared();P=S.parameterized();D=S.dimensional()
    require(cfg.get('source_branch')==BRANCH and cfg.get('dimension_branch')==P.DIMENSION_BRANCH
        and cfg.get('mode')=='reuse' and 'parameterized_operating_branch' not in cfg,'explicit proton source root required')
    for name,raw in _runtime_bytes().items():require(reader.digest(name)==sha(raw),'fixed runtime differs: '+name)
    for name,(_,digest) in HOST_SOURCES.items():require(reader.digest('proton-implementations/'+name)==digest,'host replay snapshot differs')
    result,_,_=P._verify_sources(reader,cfg);r=validate_request(obj(reader.read('controlled-request.json')))
    bound=obj(reader.read('parameterized-proton-multicondition-refinement-binding.json'))
    require(bound.get('schema')==BINDING_SCHEMA and reader.digest('parameterized-proton-multicondition-refinement-binding.json')==cfg.get('parameterized_proton_multicondition_refinement_binding_sha256'),
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
    spec=source_spec(reader,r,reader.digest('parameterized-proton-multicondition-refinement-binding.json'))
    role=role_contract(match,r,reader.digest('parameterized-proton-multicondition-refinement-binding.json'),reader.digest('source-contract.json'))
    require(obj(reader.read('source-spec.json'))==spec and obj(reader.read('role-contract.json'))==role
        and cfg['role_id']==role['role'],'proton source/role declaration differs')
    result.update(operation_timing=match['verified']['operation_timing'],operating_binding=match['verified']['operating_binding'],
        numerical_relation=match['verified']['numerical_relation'],source_spec=spec,role_contract=role,
        projection=projected,proton_binding=bound,matched_a0=matched,source_time_contract=time,
        activation=activation,pmi_build=operations['pmi'],native_batch=operations['transport'])
    require(set(result)==FROZEN_RESULT_KEYS,'public result shape differs');return result

def require_input_coverage(reader,hashes):
    """Every consumed proof/source must be in the original runner input manifest."""
    S=shared();D=S.dimensional();r=validate_request(obj(reader.read('controlled-request.json')))
    needed=set(D.SHARED_INPUTS)|set(S.SHARED)|set(RUNTIME_FILES)|set(obj(reader.read('d2-source-binding.json'))['original_files'])
    needed|={'project.json','controlled-request.json','case_contract.py','geometry_bridge.py','mesh_resource_guard.py',
        'generator-prepare_case.py','task-authorization.json','resource-policy.json','provenance.json',
        'device.cmd','cell_msh.tdr','cell_msh.log','d2-source-binding.json','dimensional-contract.json',
        'source-contract.json','source-time-contract.json','parameterized-proton-multicondition-refinement-binding.json','source-spec.json','role-contract.json',
        'projection-sources3d.dat','projection-context.dat',LIBRARY,'proton-reference-apd.plx','proton-reference-spectrum.txt',
        'optical.currentplot.inc'}
    needed|={REFERENCE_PREFIX+n for n in REFERENCE_NAMES}
    needed|={A0_PREFIX+n for n in ('manifest.json','results.tar','inputs.tar')}
    needed|={p+n for p in (TRANSPORT_PREFIX,BUILD_PREFIX,PMI_PREFIX) for n in ('operation.json','results.tar','inputs.tar')}
    needed|={BATCH_PREFIX+n for n in ['adapter-manifest.json','native-batch-binding.json','replay-request.json']+
        ['event-'+str(i)+'-g3-source.json' for i in event_ids(r)]}
    needed|={SOURCE_PREFIX+n for n in ('candidate-input-manifest.json','input-hashes.sha256','all-event-source-inputs.json')}
    needed|={SOURCE_PREFIX+'event-'+str(i)+'/'+n for i in event_ids(r) for n in SOURCE_FILES}
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
    require(getattr(C,'SCHEMA_2D_PROTON_MULTICONDITION_REFINEMENT',None)==REQUEST_SCHEMA and hasattr(bridge,'geometry_proton_multicondition_refinement_module'),
        'proton dispatch not integrated; no project created')
    require(O.plain_name(run_id) and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id
        and run_id not in (O.source_name(r['matched_a0_run']),O.source_name(r['d2_source_run'])),'new real run ID required')
    runner=Path(runner or ROOT/'scripts/tcad.py').resolve();require(runner==(ROOT/'scripts/tcad.py').resolve(),'original runner only')
    allowed=(ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/proton-multicondition-refinement-r1').resolve()
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
    native=source['replay']['binding'];N=M.native_api()
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
    files.update({REFERENCE_PREFIX+n:v for n,v in source['reference_files'].items()})
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
    files['parameterized-proton-multicondition-refinement-binding.json']=encoded(bound);cfg['parameterized_proton_multicondition_refinement_binding_sha256']=sha(files['parameterized-proton-multicondition-refinement-binding.json'])
    files['source-spec.json']=encoded(source_spec(check,r,cfg['parameterized_proton_multicondition_refinement_binding_sha256']))
    files['role-contract.json']=encoded(role_contract(match,r,cfg['parameterized_proton_multicondition_refinement_binding_sha256'],sha(files['source-contract.json'])))
    spec=dict(schema='dram-see-v4-continuous-project-r1',name='v4-2d-'+role.lower(),role=role,execution_enabled=True,
        runner='original scripts/tcad.py',native_threads=1,native_cores=1,s2_geometry=cfg,
        steps=[dict(tool='sdevice',args=['device.cmd'],outputs=list(O.OUTPUTS))])
    files.update({'project.json':encoded(spec),'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',
        role=role,observation_only=True,imported_mesh_sha256=cfg['mesh_sha256'],resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',source='current_user_instruction',
            synthetic=False,role_ids=[role],instruction='真实同条件完整请求 G4与真实新二维PMI编译、匹配A0原证据后，沿原runner进行显式同条件 h2/dt2 二维质子细化实验；保持原owner/共享锁与串行单核单线程，无项目额度。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',plan_sha256=D.file_sha(ROOT/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md'))),
        'provenance.json':encoded(dict(schema='dram-see-v4-parameterized-proton-multicondition-refinement-input-provenance-r1',run_id=run_id,role=role,
            matched_a0=matched,numerical_variant=r['variant'],host_refinement_comparison=host['refinement_comparison'],
            refinement_qualified=False,host_A0_replayed=True,host_complete_G4_and_source_math_replayed=True,
            actual_new_PMI_build_replayed=True,all_original_event_ids=event_ids(r),selected_event_id=r['event_id'],
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
    return dict(project=str(target),run_id=run_id,role_id=role,event_id=r['event_id'],original_event_ids=event_ids(r),
        parameterized_proton_multicondition_refinement_binding_sha256=cfg['parameterized_proton_multicondition_refinement_binding_sha256'],input_manifest_sha256=sha(files['input-manifest.json']),
        matched_a0=matched,native_submissions=0,native_source_qualified=False,pmi_r12_fixed=False,training_admitted=False)

