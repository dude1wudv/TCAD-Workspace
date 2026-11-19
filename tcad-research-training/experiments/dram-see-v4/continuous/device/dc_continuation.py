"""Reuse an original passed geometry packet; only the original runner executes DC.

All readers are data-only. Python 3.6 / standard library. No resource quota,
approval flag, launcher, native command or rewritten geometry report exists here.
"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import tarfile

SCHEMA='dram-see-v4-dc-geometry-source-binding-r1'
SELECTOR_SCHEMA='dram-see-v4-inherited-geometry-selector-r1'
COMPLETED_SCHEMA='dram-see-v4-completed-dc-proof-r1'
REQUEST_SCHEMA='dram-see-v4-controlled-device-request-r7'
RECIPE='native-v16-qualified-geometry-to-dc-r1'
MODE='produce_from_geometry'
PREFIX='dc-source-bindings/'
COMPLETED_PREFIX='dc-completed-bindings/'
SELECTOR_FILE='dc-geometry-selector.json'
REPORT_FILE=PREFIX+'geometry-validation.json'
METADATA_SHA='9104196c243ff6401e32d0375d2edd4aaa8feec077610d1005162adc8c31aa53'
RUNTIME_FILES=('dc_continuation.py','metadata_continuation.py','mesh_continuation.py')
CHECKS=('materials','contacts','doping','units')
OWN_GEOMETRY=('geometry-validation.json','material-measurements.csv','contact-measurements.csv',
    'doping-measurements.csv','current-mesh-before.json','current-mesh-after.json','geometry-hash-provider.csv',
    'geometry-inventory.csv','geometry-status.json','mesh-identity.csv','observation-context.json',
    'geometry-exit-sources.json','svisual-exit-code.txt')
CONTEXT_FILES=('project.json','execution-context.json','input-manifest.json','task-authorization.json','controlled-request.json')
WRAPPER_FILES=('run.sh','process-identity.json','shared-lock-evidence.txt','execution.log','exit-code.txt')
CAPTURE_SUFFIXES=('exit-code.txt','process-status.txt','process-observation.json','process-admission.json','process-admission-exit-code.txt')
SDE_OUTPUTS=('idvg_low_dc_des.plt','idvg_high_dc_des.plt','dc_final_des.tdr','dc_des.log')
SOURCE_PROOFS=CONTEXT_FILES+WRAPPER_FILES+tuple('step-005-svisual-'+s for s in CAPTURE_SUFFIXES)+(
    'step-006-sdevice-exit-code.txt','step-006-sdevice-process-observation.json','step-006-sdevice-process-status.txt')
COMPLETED_PROOFS=CONTEXT_FILES+WRAPPER_FILES+tuple('step-006-sdevice-'+s for s in CAPTURE_SUFFIXES)+SDE_OUTPUTS
CFG_SOURCE_FIELDS=('size_id','numerical_variant','sn_junction_depth_nm','parameter_id','mesh_policy_id',
    'mesh_policy_sha256','controlled_parameters_sha256','metadata_source_binding_sha256','geometry_observation_backend',
    'mesh_representation','origin_mesh_sha256','active_solver_mesh_sha256')
SELECTOR_CFG_FIELDS=('geometry_selector_file','geometry_selector_sha256','geometry_report_file','geometry_producer_run_id',
    'geometry_validation_sha256')
FORBIDDEN_CURRENT=tuple('step-{:03d}-{}-exit-code.txt'.format(i,t) for i,t in ((1,'sde'),(2,'snmesh'),(3,'tdx'),(4,'tdx'),(5,'svisual')))+OWN_GEOMETRY+(
    'tdx-converter-exit-code.txt','tdx-source-before.json','tdx-source-after.json','mesh-observed.grd','mesh-observed.dat')


def require(ok,message):
    if not ok:raise ValueError('DC continuation: '+message)


def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')
def obj(raw):
    value=json.loads(raw.decode('utf-8'));require(isinstance(value,dict),'expected JSON object');return value
def file_sha(path):
    path=Path(path);require(path.is_file() and not path.is_symlink(),'missing/linked file '+str(path))
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def metadata_module():
    path=Path(__file__).with_name('metadata_continuation.py')
    require(file_sha(path)==METADATA_SHA,'fixed r5/r6 source verifier changed')
    spec=importlib.util.spec_from_file_location('_dc_fixed_metadata',str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def stored_name(name):
    return PREFIX+name if name in set(OWN_GEOMETRY)|set(SOURCE_PROOFS) else name


class SourceReader:
    def __init__(self,reader):self.reader=reader
    def read(self,n):return self.reader.read(stored_name(n))
    def digest(self,n):return self.reader.digest(stored_name(n))
    def size(self,n):return self.reader.size(stored_name(n))
    def exists(self,n):return self.reader.exists(stored_name(n))
    def stream(self,n):return self.reader.stream(stored_name(n))


def validate_capture(reader,manifest,step,tool):
    """Current runner's observed root-to-native chain, with raw names preserved.

    Same native/exit/identity rules as fixed metadata_continuation.validate_capture
    (METADATA_SHA), except its leaf-first assumption is not valid for r12's real
    SVisual wrapper. scripts/tcad.py queues [root] then appends each child.
    The old verifier and all original observation bytes remain unchanged.
    """
    m=metadata_module();identity=m.validate_identity(reader,manifest)
    require(tool in ('svisual','sdevice'),'unsupported DC checkpoint capture tool')
    key='step-{:03d}-{}'.format(step,tool)
    expected=dict(step_index=step,tool=tool,raw_exit_file=key+'-exit-code.txt',process_status_file=key+'-process-status.txt',
        process_observation_file=key+'-process-observation.json',process_admission_file=key+'-process-admission.json',
        raw_process_admission_exit_file=key+'-process-admission-exit-code.txt')
    require(manifest.get('tool_evidence',{}).get(key)==expected,'capture mapping differs: '+key)
    require(m.exit_value(reader.read(expected['raw_exit_file']))==0
        and m.exit_value(reader.read(expected['raw_process_admission_exit_file']))==0,'actual native/admission nonzero: '+key)
    admission=obj(reader.read(expected['process_admission_file']));observed=obj(reader.read(expected['process_observation_file']))
    status_raw=reader.read(expected['process_status_file'])
    status=dict((k.strip(),v.strip()) for k,v in (line.split(':',1) for line in status_raw.decode().splitlines() if ':' in line))
    native='svisual_exec' if tool=='svisual' else tool;executable='svisual_bin/'+native if tool=='svisual' else native
    require(admission.get('schema')=='native-process-admission-r1' and admission.get('origin')=='native_pipeline'
        and admission.get('synthetic') is False and admission.get('requested_tool')==tool and admission.get('status')=='PASSED'
        and admission.get('errors')==[] and admission.get('actual_native_exit_is_separate') is True,'capture admission differs')
    require(observed.get('schema')=='native-process-observation-r1' and observed.get('origin')=='native_pipeline'
        and observed.get('synthetic') is False and observed.get('requested_tool')==tool and observed.get('status')=='OBSERVED'
        and observed.get('wrapper_pid')==identity['pid'] and observed.get('installation_root')=='/usr/synopsys/sentaurus/W-2024.09'
        and observed.get('native_executable')=='/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64/bin/'+executable
        and observed.get('status_file')==expected['process_status_file'] and observed.get('status_sha256')==sha(status_raw)
        and status.get('Name')==native and status.get('Pid')==str(observed.get('native_pid'))
        and status.get('Threads')==observed.get('observed_threads')=='1'
        and status.get('Cpus_allowed_list')==observed.get('observed_cpus_allowed_list')==admission.get('requested_cpu')
        and re.fullmatch(r'[0-9]+',status.get('Cpus_allowed_list','')) is not None,'native process identity/CPU/thread differs')
    chain=observed.get('parent_chain',[])
    require(chain and chain[0]==observed.get('root_identity') and chain[0].get('ppid')==identity['pid']
        and chain[0].get('pid')==observed.get('root_child_pid') and chain[-1].get('pid')==observed.get('native_pid')
        and chain[-1].get('start_ticks')==observed.get('native_start_ticks') and chain[-1].get('ppid')==int(status['PPid'])
        and chain[-1].get('name')==native and len({r.get('pid') for r in chain})==len(chain),
        'native root-to-leaf parent/start chain differs')
    for i,row in enumerate(chain):
        require(type(row.get('pid')) is int and row['pid']>1 and type(row.get('start_ticks')) is int
            and row['start_ticks']>=identity['start_ticks'],'child identity/start differs')
        if i:require(row['ppid']==chain[i-1]['pid'] and row['start_ticks']>=chain[i-1]['start_ticks'],
                     'broken root-to-leaf native parent chain')


def selector_for(report,report_sha):
    return dict(schema=SELECTOR_SCHEMA,report_file=REPORT_FILE,report_sha256=report_sha,
        producer_run_id=report['producer_run_id'],evidence_members={n:stored_name(n) for n in report['evidence_sha256']})


def report_validate(reader,manifest,source_cfg,source_binding):
    """Audit the original result and its complete evidence, without reevaluation."""
    report=obj(reader.read('geometry-validation.json'));plan=obj(reader.read('measurement-plan.json'))
    require(report.get('schema')=='s2-native-geometry-validation-r1' and report.get('origin')=='native_pipeline'
        and report.get('synthetic') is False and report.get('passed') is True and report.get('native_qualified') is False
        and report.get('role_id')=='B1-D3' and report.get('producer_run_id')==manifest['run_id']
        and all(report.get('checks',{}).get(k) is True and report.get('numeric_checks',{}).get(k) is True for k in CHECKS),
        'original geometry report is not a passed actual D3 observation')
    require(plan.get('schema')=='s2-geometry-measurement-plan-r1' and plan.get('dimension')==3
        and len(plan.get('measurements',[]))==148 and report.get('plan_sha256')==reader.digest('measurement-plan.json')
        and report.get('geometry_contract_sha256')==plan.get('geometry_contract_sha256')==reader.digest('geometry-contract.json'),
        'original fixed148 plan/geometry binding differs')
    expected_ids={i['id'] for i in plan['measurements']}|{'cad.contact.'+c['name'] for c in plan['expected_geometry']['contacts']}|{
        'cad.probe.'+i['id'] for i in plan['contact_probes']}|{'cad.material.'+i['id'] for i in plan['material_probes']}|{
        'native.hdf5.topology-and-fields'}
    comparisons=report.get('comparisons',[])
    require(len(comparisons)==len(expected_ids)==211 and {v.get('id') for v in comparisons}==expected_ids
        and all(v.get('passed') is True for v in comparisons),'original complete211 comparisons are missing/failed')
    require(report.get('mesh_sha256')==reader.digest('cell_msh.tdr')==source_binding['active_solver_mesh_sha256']
        and report.get('metadata_source_binding_sha256')==reader.digest('metadata-source-binding.json')
        and report.get('inherited_step_indices')==[1,2,3] and report.get('actual_geometry_step_indices')==[5],
        'geometry mesh/source/actual-step binding differs')
    for key in ('geometry_observation_backend','mesh_representation','origin_mesh_sha256','active_solver_mesh_sha256'):
        require(report.get(key)==source_cfg[key],'geometry representation differs: '+key)
    expected=report.get('evidence_sha256',{})
    required={'material-measurements.csv','contact-measurements.csv','doping-measurements.csv','observation-context.json',
        'geometry-exit-sources.json','geometry-producer-bindings/execution-context.json','geometry-producer-bindings/input-manifest.json',
        'step-005-svisual-exit-code.txt','geometry-hash-provider.csv'}
    require(required<=set(expected),'geometry measured evidence inventory is incomplete')
    for name,digest in expected.items():require(reader.digest(name)==digest,'original geometry evidence changed: '+name)
    m=metadata_module();graph=m.evidence_hashes(reader,source_binding)
    require(all(expected.get(n)==h for n,h in graph.items()),'geometry report lost original full source graph')
    for n in ('execution-context.json','input-manifest.json','task-authorization.json'):
        require(reader.read(n)==reader.read('geometry-producer-bindings/'+n),'original geometry producer context differs')
    context=obj(reader.read('observation-context.json'))
    require(context.get('schema')==m.ACTIVE_CONTEXT_SCHEMA and context.get('producer_run_id')==manifest['run_id']
        and context.get('origin')=='native_pipeline' and context.get('synthetic') is False
        and context.get('mesh_sha256')==source_binding['mesh_sha256']
        and context.get('metadata_source_binding_sha256')==reader.digest('metadata-source-binding.json'),
        'original observation context owner differs')
    return report


def verify(reader,cfg=None,request=None):
    m=metadata_module();binding=obj(reader.read('dc-source-binding.json'))
    require(binding.get('schema')==SCHEMA and binding.get('recipe')==RECIPE and binding.get('origin')=='native_pipeline'
        and binding.get('synthetic') is False and binding.get('inherited_step_indices')==[1,2,3,5]
        and binding.get('actual_step_indices')==[6],'wrong DC checkpoint schema/steps')
    manifest_raw=reader.read(PREFIX+'manifest.json');manifest=obj(manifest_raw)
    require(sha(manifest_raw)==binding['source_manifest_sha256'] and manifest.get('schema')=='tcad-native-run-r2'
        and manifest.get('run_id')==binding['source_run_id']==binding['geometry_producer_run_id']
        and manifest.get('state')==binding.get('source_state')=='FAILED_COLLECTED'
        and manifest.get('origin')=='native_pipeline' and manifest.get('synthetic') is False
        and manifest.get('collection_verified') is True and type(manifest.get('collection_exit_code')) is int
        and manifest['collection_exit_code']==0 and type(manifest.get('ssh_exit_code')) is int
        and manifest.get('results_sha256')==binding['source_archive_sha256']
        and manifest.get('inputs_archive_sha256')==binding['source_inputs_archive_sha256']==reader.digest(PREFIX+'inputs.tar'),
        'original r12 failed collection identity differs')
    require(manifest.get('tool_exit_codes')=={'step-005-svisual':0,'step-006-sdevice':137}
        and all(type(v) is int for v in manifest['tool_exit_codes'].values())
        and manifest.get('native_step_start_index')==5 and manifest.get('inherited_step_indices')==[1,2,3]
        and manifest.get('remote_exit_code')==binding.get('source_remote_exit_code')==137,'original005 success/006 failure must remain unchanged')
    index_raw=reader.read(PREFIX+'_collection-members.json');index=obj(index_raw)
    require(sha(index_raw)==binding['source_collection_index_sha256'],'original collection index changed')
    for name,digest in binding['proofs_sha256'].items():require(reader.digest(name)==digest,'frozen proof changed: '+name)
    require(binding['proofs_sha256']=={PREFIX+'manifest.json':sha(manifest_raw),PREFIX+'inputs.tar':binding['source_inputs_archive_sha256'],
        PREFIX+'_collection-members.json':sha(index_raw)},'source receipt proof inventory differs')
    for target,row in binding['imports'].items():
        require(target==stored_name(row['member']) and index.get(row['member'])==dict(size=row['size_bytes'],sha256=row['sha256'])
            and reader.size(target)==row['size_bytes'] and reader.digest(target)==row['sha256'],'source import/member/index differs: '+target)
    source=SourceReader(reader)
    for n in ('exit-code.txt','step-006-sdevice-exit-code.txt'):
        require(m.exit_value(source.read(n))==137,'original failed006/wrapper exit differs')
    needed=set(CONTEXT_FILES)|set(binding['identical_inputs_sha256'])
    with reader.stream(PREFIX+'inputs.tar') as stream:original=m.original_input_payload(stream,manifest,needed)
    source_spec=obj(original['project.json']);source_cfg=source_spec['s2_geometry'];source_request=obj(original['controlled-request.json'])
    require(source_cfg.get('mode')=='produce_from_metadata' and source_cfg.get('role_id')=='B1-D3'
        and source_cfg.get('run_id')==source_cfg.get('producer_run_id')==manifest['run_id']
        and source_spec.get('native_threads')==source_spec.get('native_cores')==1 and source_spec['steps']==manifest['steps']
        and [(s.get('tool'),s.get('args')) for s in manifest['steps']]==list(m.mesh_module().SIX_STEPS[4:])
        and source_spec['steps'][-1].get('outputs')==list(SDE_OUTPUTS),'source active-v16 producer shape differs')
    for name in CONTEXT_FILES:require(source.read(name)==original[name],'source archived context/input mismatch: '+name)
    scientific=set(m.mesh_module().IDENTICAL_INPUTS)-set(m.CHANGED_IMPLEMENTATIONS)
    require(set(binding['identical_inputs_sha256'])==scientific and len(scientific)==15,'scientific input identity set differs')
    for name,digest in binding['identical_inputs_sha256'].items():
        require(reader.digest(name)==digest==sha(original[name]),'scientific/numerical/measurement input changed: '+name)
    source_binding=m.verify(source,source_cfg,source_request)
    require(source_binding['schema']==m.ACTIVE_SCHEMA and binding['metadata_source_binding_sha256']==source.digest('metadata-source-binding.json')
        ==manifest.get('metadata_source_binding_sha256') and binding['mesh_sha256']==source_binding['active_solver_mesh_sha256'],
        'source metadata-r2/actual mesh identity differs')
    validate_capture(source,manifest,5,'svisual')
    report=report_validate(source,manifest,source_cfg,source_binding)
    selector_raw=reader.read(SELECTOR_FILE);selector=obj(selector_raw)
    require(selector==selector_for(report,source.digest('geometry-validation.json'))
        and binding['geometry_selector_file']==SELECTOR_FILE and binding['geometry_selector_sha256']==sha(selector_raw)
        and binding['geometry_report_sha256']==selector['report_sha256'],'original report selector/mapping differs')
    require(len(set(selector['evidence_members'].values()))==len(selector['evidence_members']),
        'original report member mapping has an alias collision')
    expected_members=set(report['evidence_sha256'])|set(SOURCE_PROOFS)|{'geometry-validation.json'}
    require(set(binding['imports'])=={stored_name(n) for n in expected_members},'geometry/prefix proof import inventory differs')
    if request is not None:
        require(request.get('schema')==REQUEST_SCHEMA and request.get('continuation_recipe')==RECIPE
            and request.get('dc_source_run')==binding['source_run_directory']
            and request.get('mesh_representation')==m.ACTIVE_REPRESENTATION,'DC-only request source/recipe differs')
        for n in ('gate_top_depth_nm','sn_junction_depth_nm','dimension','variant','mesh_policy'):
            require(request.get(n)==source_request.get(n),'DC-only request cannot change '+n)
    if cfg is not None:
        require(cfg.get('mode')==MODE and cfg.get('role_id')=='B1-D3' and cfg.get('run_id')==cfg.get('producer_run_id')!=manifest['run_id']
            and cfg.get('dc_source_binding_sha256')==reader.digest('dc-source-binding.json'),'current DC-only identity differs')
        for n in CFG_SOURCE_FIELDS:require(cfg.get(n)==source_cfg.get(n),'current DC changed original physics/mesh: '+n)
        wanted=dict(geometry_selector_file=SELECTOR_FILE,geometry_selector_sha256=sha(selector_raw),geometry_report_file=REPORT_FILE,
            geometry_producer_run_id=manifest['run_id'],geometry_validation_sha256=selector['report_sha256'])
        require(all(cfg.get(n)==v for n,v in wanted.items()),'current geometry selector identity differs')
    return binding,selector


def verify_folder(folder,cfg):
    m=metadata_module();reader=m.FolderReader(folder)
    for name in FORBIDDEN_CURRENT:require(not reader.exists(name),'inherited geometry cannot masquerade as current output: '+name)
    return verify(reader,cfg,obj(reader.read('controlled-request.json')))


def source_package(source_directory,request):
    m=metadata_module();source=Path(source_directory)
    require(source.is_absolute() and source.is_dir() and not source.is_symlink() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(source),'invalid original DC source directory')
    manifest_raw=(source/'manifest.json').read_bytes();manifest=obj(manifest_raw)
    archive_sha=file_sha(source/'results.tar');inputs_sha=file_sha(source/'inputs.tar')
    require(source.name==manifest.get('run_id') and archive_sha==manifest.get('results_sha256') and inputs_sha==manifest.get('inputs_archive_sha256'),
        'original failed DC archive/input identity differs')
    with tarfile.open(str(source/'results.tar'),'r:*') as archive:
        members=m.mesh_module().members(archive);reader=m.ArchiveReader(archive,members)
        index_raw=reader.read('_collection-members.json');index=obj(index_raw)
        require(set(index)=={n for n,v in members.items() if v.isfile()}-{'_collection-members.json'},'complete original archive inventory differs')
        m.check_index(reader,index)
        report=obj(reader.read('geometry-validation.json'))
        imports={stored_name(n):dict(member=n,sha256=index[n]['sha256'],size_bytes=index[n]['size'])
                 for n in sorted(set(report['evidence_sha256'])|set(SOURCE_PROOFS)|{'geometry-validation.json'})}
        scientific=set(m.mesh_module().IDENTICAL_INPUTS)-set(m.CHANGED_IMPLEMENTATIONS)
        files={n:reader.read(n) for n in sorted(scientific)}
        files[PREFIX+'manifest.json']=manifest_raw;files[PREFIX+'_collection-members.json']=index_raw
        selector=selector_for(report,reader.digest('geometry-validation.json'));files[SELECTOR_FILE]=encoded(selector)
        binding=dict(schema=SCHEMA,recipe=RECIPE,origin='native_pipeline',synthetic=False,source_run_id=source.name,
            source_run_directory=str(source),source_manifest_sha256=sha(manifest_raw),source_archive_sha256=archive_sha,
            source_archive_size_bytes=(source/'results.tar').stat().st_size,source_inputs_archive_sha256=inputs_sha,
            source_inputs_archive_size_bytes=(source/'inputs.tar').stat().st_size,source_collection_index_sha256=sha(index_raw),
            source_state=manifest['state'],source_remote_exit_code=manifest['remote_exit_code'],geometry_producer_run_id=source.name,
            geometry_selector_file=SELECTOR_FILE,geometry_selector_sha256=sha(files[SELECTOR_FILE]),
            geometry_report_sha256=selector['report_sha256'],metadata_source_binding_sha256=reader.digest('metadata-source-binding.json'),
            mesh_sha256=reader.digest('cell_msh.tdr'),identical_inputs_sha256={n:sha(files[n]) for n in sorted(scientific)},
            imports=imports,proofs_sha256={PREFIX+'manifest.json':sha(manifest_raw),PREFIX+'inputs.tar':inputs_sha,
                PREFIX+'_collection-members.json':sha(index_raw)},inherited_step_indices=[1,2,3,5],actual_step_indices=[6])
        files['dc-source-binding.json']=encoded(binding)
        class Prospective:
            def read(self,n):return files[n] if n in files else reader.read(imports[n]['member'])
            def digest(self,n):return sha(files[n]) if n in files else inputs_sha if n==PREFIX+'inputs.tar' else reader.digest(imports[n]['member'])
            def size(self,n):return len(files[n]) if n in files else (source/'inputs.tar').stat().st_size if n==PREFIX+'inputs.tar' else reader.size(imports[n]['member'])
            def stream(self,n):return (source/'inputs.tar').open('rb') if n==PREFIX+'inputs.tar' else io.BytesIO(files[n]) if n in files else reader.stream(imports[n]['member'])
            def exists(self,n):return n in files or n in imports or n==PREFIX+'inputs.tar'
        verify(Prospective(),request=request)
        source_cfg=obj(reader.read('project.json'))['s2_geometry']
    return dict(files=files,imports=imports,binding=binding,selector=selector,source_cfg=source_cfg,mesh_sha256=binding['mesh_sha256'])


def stage(folder,cfg):
    folder=Path(folder);m=metadata_module();binding=obj((folder/'dc-source-binding.json').read_bytes());source=Path(binding['source_run_directory'])
    require(file_sha(source/'results.tar')==binding['source_archive_sha256'] and file_sha(source/'inputs.tar')==binding['source_inputs_archive_sha256'],
        'original failed DC archive changed before staging')
    with tarfile.open(str(source/'results.tar'),'r:*') as archive:
        members=m.mesh_module().members(archive)
        rows=dict(binding['imports']);rows[PREFIX+'inputs.tar']=dict(external='inputs.tar',sha256=binding['source_inputs_archive_sha256'],
            size_bytes=binding['source_inputs_archive_size_bytes'])
        for name,row in rows.items():
            parts=name.split('/')
            namespaces=m.NAMESPACES+('geometry-producer-bindings','dc-source-bindings')
            require((len(parts)==1 or len(parts)==2 and parts[0] in namespaces)
                and all(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',p) for p in parts),'unsafe staged path')
            target=folder/name
            require(not target.is_symlink() and not target.parent.is_symlink(),'linked staged path')
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                require(file_sha(target)==row['sha256'] and target.stat().st_size==row['size_bytes'],'existing staged bytes differ');continue
            stream=(source/'inputs.tar').open('rb') if 'external' in row else archive.extractfile(members[row['member']])
            with stream,target.open('xb') as output:
                for b in iter(lambda:stream.read(1048576),b''):output.write(b)
            require(file_sha(target)==row['sha256'] and target.stat().st_size==row['size_bytes'],'staged original bytes differ')
    verify_folder(folder,cfg);return cfg


def evidence_hashes(reader,binding=None):
    binding=binding or obj(reader.read('dc-source-binding.json'))
    result={n:r['sha256'] for n,r in binding['imports'].items()};result.update(binding['proofs_sha256'])
    for n in ('dc-source-binding.json',SELECTOR_FILE):result[n]=reader.digest(n)
    return result


def validate_completed(reader,manifest,cfg,inputs_stream):
    m=metadata_module()
    require(manifest.get('schema')=='tcad-native-run-r2' and manifest.get('state')=='COLLECTED' and manifest.get('collection_verified') is True
        and manifest.get('origin')=='native_pipeline' and manifest.get('synthetic') is False
        and type(manifest.get('remote_exit_code')) is int and manifest['remote_exit_code']==0
        and type(manifest.get('collection_exit_code')) is int and manifest['collection_exit_code']==0
        and type(manifest.get('ssh_exit_code')) is int,'DC producer is not an actual completed collection')
    require(manifest.get('tool_exit_codes')=={'step-006-sdevice':0} and type(manifest['tool_exit_codes']['step-006-sdevice']) is int
        and set(manifest.get('tool_evidence',{}))=={'step-006-sdevice'} and manifest.get('native_step_start_index')==6
        and manifest.get('inherited_step_indices')==[1,2,3,5] and manifest.get('dc_source_binding_sha256')==reader.digest('dc-source-binding.json')
        and manifest.get('geometry_producer_run_id')==cfg.get('geometry_producer_run_id')
        and cfg.get('run_id')==cfg.get('producer_run_id')==manifest.get('run_id'),
        'DC producer actual006/inherited identity differs')
    for n in FORBIDDEN_CURRENT:require(not reader.exists(n),'DC-only producer has a fabricated current geometry output')
    original=m.original_input_payload(inputs_stream,manifest,set(CONTEXT_FILES))
    for n,h in manifest['input_sha256'].items():require(reader.digest(n)==h,'completed DC original input changed: '+n)
    spec=obj(original['project.json'])
    require(spec.get('s2_geometry')==cfg and spec.get('steps')==manifest.get('steps')
        and [(s.get('tool'),s.get('args')) for s in spec['steps']]==[('sdevice',['device.cmd'])]
        and spec['steps'][0].get('outputs')==list(SDE_OUTPUTS) and spec.get('native_threads')==spec.get('native_cores')==1,
        'completed DC serial step/device outputs differ')
    binding,selector=verify(reader,cfg,obj(original['controlled-request.json']))
    validate_capture(reader,manifest,6,'sdevice')
    require(m.exit_value(reader.read('exit-code.txt'))==0,'actual completed DC wrapper is nonzero')
    for n in SDE_OUTPUTS:require(reader.exists(n) and reader.size(n)>0,'completed DC declared output absent/empty: '+n)
    return binding,selector


def completed_bundle(source_directory,manifest_raw,archive,members,cfg):
    """Freeze successful DC proof for A0; no success is generated by this function."""
    source=Path(source_directory);m=metadata_module();manifest=obj(manifest_raw);reader=m.ArchiveReader(archive,members)
    index_raw=reader.read('_collection-members.json');index=obj(index_raw)
    require(set(index)=={n for n,v in members.items() if v.isfile()}-{'_collection-members.json'},'completed DC full archive index differs')
    m.check_index(reader,index)
    require(file_sha(source/'inputs.tar')==manifest.get('inputs_archive_sha256'),'completed DC original input archive differs')
    with (source/'inputs.tar').open('rb') as stream:binding,selector=validate_completed(reader,manifest,cfg,stream)
    original=Path(binding['source_run_directory'])
    require(file_sha(original/'results.tar')==binding['source_archive_sha256']
        and file_sha(original/'inputs.tar')==binding['source_inputs_archive_sha256'],'original geometry archive/input changed')
    metadata=obj(reader.read('metadata-source-binding.json'))
    for node in metadata['nodes'].values():
        original=Path(node['directory'])
        require(file_sha(original/'results.tar')==node['archive_sha256']
            and file_sha(original/'inputs.tar')==node['inputs_archive_sha256'],'original metadata/operation archive changed')
    ancestor=obj(reader.read('mesh-source-binding.json'));original=Path(ancestor['source_run_directory'])
    require(file_sha(original/'results.tar')==ancestor['source_archive_sha256']
        and file_sha(original/'inputs.tar')==ancestor['source_inputs_archive_sha256'],'original mesh prefix archive changed')
    runtime_files={n:reader.read(n) for n in RUNTIME_FILES}
    require(all(sha(b)==file_sha(Path(__file__).with_name(n)) for n,b in runtime_files.items()),
        'completed DC verifier version differs; explicit version support is required')
    exports=evidence_hashes(reader,binding);export_members={n:n for n in exports}
    for n in COMPLETED_PROOFS+('_collection-members.json',):
        target=COMPLETED_PREFIX+n;exports[target]=reader.digest(n);export_members[target]=n
    external={COMPLETED_PREFIX+'manifest.json':dict(path=str(source/'manifest.json'),sha256=sha(manifest_raw)),
              COMPLETED_PREFIX+'inputs.tar':dict(path=str(source/'inputs.tar'),sha256=manifest['inputs_archive_sha256'])}
    for n,row in external.items():exports[n]=row['sha256']
    proof=dict(schema=COMPLETED_SCHEMA,producer_run_id=manifest['run_id'],source_manifest_sha256=sha(manifest_raw),
        source_archive_sha256=manifest['results_sha256'],source_inputs_archive_sha256=manifest['inputs_archive_sha256'],
        source_collection_index_sha256=sha(index_raw),dc_source_binding_sha256=reader.digest('dc-source-binding.json'),
        geometry_selector_sha256=reader.digest(SELECTOR_FILE),files_sha256={n:h for n,h in exports.items() if n.startswith(COMPLETED_PREFIX)})
    generated={'dc-completed-binding.json':encoded(proof)};exports.update({n:sha(b) for n,b in generated.items()})
    names=('physics-manifest.json','physics.par','Silicon.par','Oxide.par','geometry-contract.json','model.proposed.json','numerical-method.json',
        'mesh-policy.json','mesh-policy-definition.json','mesh-policy-assumptions.md')
    producer_inputs={n:reader.read(n) for n in names}
    result=dict(archive=source/'results.tar',archive_sha256=manifest['results_sha256'],manifest_sha256=sha(manifest_raw),
        geometry_validation_sha256=selector['report_sha256'],mesh_sha256=binding['mesh_sha256'],producer_inputs=producer_inputs,
        physics_sha256={n:reader.digest(n) for n in names[:4]},producer_cfg=cfg,exports=exports,export_members=export_members,
        external_files=external,generated_files=generated,dc_completed_binding_sha256=sha(generated['dc-completed-binding.json']),
        runtime_files=runtime_files)
    result.update({n:cfg[n] for n in ('mesh_representation','origin_mesh_sha256','active_solver_mesh_sha256')+SELECTOR_CFG_FIELDS})
    return result


def verify_completed_frozen(reader,cfg):
    """Verify A0's frozen completed-DC proof using the same completed validator."""
    for name in RUNTIME_FILES:
        require(reader.digest(name)==file_sha(Path(__file__).with_name(name)),
            'frozen DC verifier version differs: '+name)
    m=metadata_module();proof=obj(reader.read('dc-completed-binding.json'))
    require(proof.get('schema')==COMPLETED_SCHEMA and reader.digest('dc-completed-binding.json')==cfg.get('dc_completed_binding_sha256'),
        'A0 completed DC proof selector differs')
    require(proof.get('producer_run_id')==cfg.get('producer_run_id') and proof.get('source_manifest_sha256')==cfg.get('source_manifest_sha256')
        and proof.get('source_archive_sha256')==cfg.get('source_archive_sha256'),'A0/DC producer receipt identity differs')
    for n,h in proof['files_sha256'].items():require(reader.digest(n)==h,'frozen completed DC member changed: '+n)
    expected={COMPLETED_PREFIX+n for n in COMPLETED_PROOFS+('_collection-members.json','manifest.json','inputs.tar')}
    require(set(proof['files_sha256'])==expected,'completed DC proof inventory differs')
    manifest_raw=reader.read(COMPLETED_PREFIX+'manifest.json');manifest=obj(manifest_raw)
    require(sha(manifest_raw)==proof['source_manifest_sha256'] and manifest.get('results_sha256')==proof['source_archive_sha256']
        and reader.digest(COMPLETED_PREFIX+'inputs.tar')==proof['source_inputs_archive_sha256']
        and reader.digest(COMPLETED_PREFIX+'_collection-members.json')==proof['source_collection_index_sha256'],
        'completed DC original receipt/index/input binding differs')
    index=obj(reader.read(COMPLETED_PREFIX+'_collection-members.json'))
    for n in COMPLETED_PROOFS:
        require(index.get(n)==dict(size=reader.size(COMPLETED_PREFIX+n),sha256=reader.digest(COMPLETED_PREFIX+n)),
                'completed DC original collection member/index differs')
    with reader.stream(COMPLETED_PREFIX+'inputs.tar') as stream,tarfile.open(fileobj=stream,mode='r:*') as inputs:
        listing=m.mesh_module().members(inputs);input_reader=m.ArchiveReader(inputs,listing)
        for n,h in manifest['input_sha256'].items():
            require(index.get(n)==dict(sha256=h,size=input_reader.size(n)),
                    'completed DC original inputs/collection index differ: '+n)
        class CompletedReader:
            def read(self,n):return input_reader.read(n) if n in listing else reader.read(COMPLETED_PREFIX+n)
            def digest(self,n):return input_reader.digest(n) if n in listing else reader.digest(COMPLETED_PREFIX+n)
            def size(self,n):return input_reader.size(n) if n in listing else reader.size(COMPLETED_PREFIX+n)
            def stream(self,n):return input_reader.stream(n) if n in listing else reader.stream(COMPLETED_PREFIX+n)
            def exists(self,n):return n in listing or reader.exists(COMPLETED_PREFIX+n)
        original_cfg=obj(input_reader.read('project.json'))['s2_geometry']
        with reader.stream(COMPLETED_PREFIX+'inputs.tar') as check_stream:
            binding,selector=validate_completed(CompletedReader(),manifest,original_cfg,check_stream)
    require(proof['dc_source_binding_sha256']==reader.digest('dc-source-binding.json')
        and proof['geometry_selector_sha256']==reader.digest(SELECTOR_FILE)==cfg.get('geometry_selector_sha256')
        and selector==obj(reader.read(SELECTOR_FILE)),'A0 changed the inherited geometry selector')
    # A0 has its own transient deck; recheck the inherited evidence, not a false
    # assertion that the current A0 device.cmd must be the original DC deck.
    current_binding=obj(reader.read('dc-source-binding.json'));current_selector=obj(reader.read(SELECTOR_FILE))
    require(current_binding==binding and current_selector==selector and cfg.get('mesh_sha256')==binding['mesh_sha256'],
        'A0 actual inherited geometry packet differs from completed DC')
    for n,h in evidence_hashes(reader,binding).items():require(reader.digest(n)==h,'A0 inherited evidence changed: '+n)
    for n in ('physics-manifest.json','physics.par','Silicon.par','Oxide.par','geometry-contract.json','model.proposed.json'):
        require(reader.digest(n)==binding['identical_inputs_sha256'][n],'A0 physics/geometry differs from completed DC: '+n)
    return dict(proof=proof,binding=binding,selector=selector)
