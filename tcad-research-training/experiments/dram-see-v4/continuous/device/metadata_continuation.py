"""Frozen r9 -> r10 metadata -> native TDR/HDF5 provenance, without launchers.

The old mesh continuation verifier is byte-preserved. This branch never invents
DF-ISE output or a successful logical step004. Python 3.6 / standard library.
"""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import tarfile

SCHEMA = 'dram-see-v4-metadata-hdf5-source-binding-r1'
REQUEST_SCHEMA = 'dram-see-v4-controlled-device-request-r5'
RECIPE = 'native-hdf5-v16-r1'
ACTIVE_SCHEMA = 'dram-see-v4-metadata-hdf5-source-binding-r2'
ACTIVE_REQUEST_SCHEMA = 'dram-see-v4-controlled-device-request-r6'
ACTIVE_RECIPE = 'native-hdf5-v16-active-mesh-r1'
ACTIVE_REPRESENTATION = 'tdr-hdf5-v16'
ORIGIN_FILE = 'scientific-origin-mesh.tdr'
ORIGIN_BINDING_FILE = 'metadata-origin-binding.json'
ACTIVE_CFG_FIELDS = ('mesh_representation','origin_mesh_sha256','active_solver_mesh_sha256')
BACKEND = 'native_hdf5_v16_export'
CONTEXT_SCHEMA = 'dram-see-v4-hdf5-geometry-observation-context-r1'
ACTIVE_CONTEXT_SCHEMA = 'dram-see-v4-hdf5-geometry-observation-context-r2'
MESH_VERIFIER_SHA = '9c3f6be4f6d5759d7eec793e0d47efb742389958f34ca6cca2f1672a12683fdf'
OPERATION_ADAPTER_SHA = '95613896f92a9569e39dc7d67767f228d89f7f13c812d28439ce24ea1187012d'
OPERATION_RUNNER_SHA = '060d9e17b6ae88386a16998f310d9e84db4ec1c32db948d636086d4c95d03751'
RECIPE_INPUTS = {
    'conversion': {'task.sh':'3a29659c4c8ecb7f95d9d9776f0bee1f860915efcab1601bf910222d283645bd',
                   'inspect_format.py':'b965137c36eef39a6ef5ee49b391fce706086bf3622aaad60ad01ffac32acaa5'},
    'export': {'task.sh':'62403eb9a0cc5b1102d89f7749a7f2086efebd11b39758a5837863c8d80ef020',
               'export_hdf5.py':'d7e1a4d49ab231d8b76d4444c4b549458d38418009f7ecea062e5c579b760edc'},
}
NAMESPACES = ('metadata-source-bindings','tdr-conversion-bindings','hdf5-export-bindings','hdf5-export','mesh-source-bindings')
METADATA_FILES = ('tdr-geometry.csv','tdr-region-datasets.csv','tdr-topology-identity.csv',
                  'tdr-region-status.json','tdr-hash-provider.csv')
METADATA_PROOF = ('project.json','input-manifest.json','execution-context.json','task-authorization.json',
    'controlled-request.json','run.sh','process-identity.json','shared-lock-evidence.txt','execution.log',
    'exit-code.txt','tdx-source-before.json','tdx-metadata-exit-code.txt','tdx-converter-exit-code.txt',
    'step-003-tdx-exit-code.txt','step-003-tdx-process-admission-exit-code.txt',
    'step-003-tdx-process-admission.json','step-003-tdx-process-observation.json','step-003-tdx-process-status.txt',
    'step-004-tdx-exit-code.txt','step-004-tdx-process-observation.json','step-004-tdx-process-status.txt') + METADATA_FILES
CHANGED_IMPLEMENTATIONS = ('measure-geometry.tcl','evaluate.py')
FORBIDDEN_CURRENT = ('step-001-sde-exit-code.txt','step-002-snmesh-exit-code.txt','step-003-tdx-exit-code.txt',
    'step-004-tdx-exit-code.txt','tdx-converter-exit-code.txt','tdx-source-before.json','tdx-source-after.json',
    'mesh-observed.grd','mesh-observed.dat')


def require(ok,message):
    if not ok:raise ValueError('Metadata continuation: '+message)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def stream_sha(stream):
    h=hashlib.sha256()
    for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def file_sha(path):
    path=Path(path)
    require(path.is_file() and not path.is_symlink(),'missing or linked file '+str(path))
    with path.open('rb') as stream:return stream_sha(stream)


def obj(raw):
    value=json.loads(raw.decode('utf-8'));require(isinstance(value,dict),'expected JSON object');return value


def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')


def mesh_module():
    path=Path(__file__).with_name('mesh_continuation.py')
    require(file_sha(path)==MESH_VERIFIER_SHA,'fixed original mesh-prefix verifier changed')
    spec=importlib.util.spec_from_file_location('_metadata_fixed_mesh_prefix',str(path))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class FolderReader:
    def __init__(self,folder):self.folder=Path(folder)
    def read(self,name):return (self.folder/name).read_bytes()
    def digest(self,name):return file_sha(self.folder/name)
    def size(self,name):return (self.folder/name).stat().st_size
    def stream(self,name):
        path=self.folder/name
        require(path.is_file() and not path.is_symlink(),'missing/linked stream '+name)
        return path.open('rb')
    def exists(self,name):return (self.folder/name).exists()


class ArchiveReader:
    def __init__(self,archive,members):self.archive,self.members=archive,members
    def stream(self,name):
        require(name in self.members and self.members[name].isfile(),'missing archive member '+name)
        return self.archive.extractfile(self.members[name])
    def read(self,name):
        with self.stream(name) as stream:return stream.read()
    def digest(self,name):
        with self.stream(name) as stream:return stream_sha(stream)
    def size(self,name):return self.members[name].size
    def exists(self,name):return name in self.members


class OriginReader:
    """Fixed logical view of the intact r1 packet, never an input-defined alias."""
    def __init__(self,reader):self.reader=reader
    def name(self,name):
        return {'cell_msh.tdr':ORIGIN_FILE,'metadata-source-binding.json':ORIGIN_BINDING_FILE}.get(name,name)
    def read(self,name):return self.reader.read(self.name(name))
    def digest(self,name):return self.reader.digest(self.name(name))
    def size(self,name):return self.reader.size(self.name(name))
    def exists(self,name):return self.reader.exists(self.name(name))
    def stream(self,name):return self.reader.stream(self.name(name))


def active_binding(origin_raw):
    """The sole registered representation transform of a complete original graph."""
    binding=obj(origin_raw)
    require(binding.get('schema')==SCHEMA and binding.get('recipe')==RECIPE,'active branch requires the original r1 graph')
    original_sha,original_size=binding['mesh_sha256'],binding['mesh_size_bytes']
    active_sha,active_size=binding['hdf5_sha256'],binding['hdf5_size_bytes']
    require(original_sha!=active_sha,'active representation must retain distinct original/converted bytes')
    binding['imports'][ORIGIN_FILE]=binding['imports'].pop('cell_msh.tdr')
    binding['imports']['cell_msh.tdr']=dict(owner='conversion',member='mesh-v16.tdr',sha256=active_sha,size_bytes=active_size)
    binding.update(schema=ACTIVE_SCHEMA,recipe=ACTIVE_RECIPE,mesh_representation=ACTIVE_REPRESENTATION,
        origin_binding_file=ORIGIN_BINDING_FILE,origin_binding_sha256=sha(origin_raw),
        origin_mesh_file=ORIGIN_FILE,origin_mesh_sha256=original_sha,origin_mesh_size_bytes=original_size,
        active_solver_mesh_file='cell_msh.tdr',active_solver_mesh_sha256=active_sha,active_solver_mesh_size_bytes=active_size,
        mesh_sha256=active_sha,mesh_size_bytes=active_size)
    return binding


def verify_active(reader,binding,cfg,request):
    origin_raw=reader.read(ORIGIN_BINDING_FILE)
    require(binding==active_binding(origin_raw),'active representation mapping differs from the exact registered r1 transform')
    require(reader.digest('cell_msh.tdr')==binding['active_solver_mesh_sha256']
        and reader.size('cell_msh.tdr')==binding['active_solver_mesh_size_bytes'],'actual active mesh differs from original converted member')
    origin_cfg=None if cfg is None else dict(cfg)
    if cfg is not None:
        require(cfg.get('metadata_source_binding_sha256')==reader.digest('metadata-source-binding.json')
            and cfg.get('mesh_representation')==ACTIVE_REPRESENTATION
            and cfg.get('origin_mesh_sha256')==binding['origin_mesh_sha256']
            and cfg.get('active_solver_mesh_sha256')==binding['active_solver_mesh_sha256'],
            'current origin/active representation identity differs')
        for key in ACTIVE_CFG_FIELDS:origin_cfg.pop(key,None)
        origin_cfg['metadata_source_binding_sha256']=binding['origin_binding_sha256']
    origin_request=None if request is None else dict(request)
    if request is not None:
        require(request.get('schema')==ACTIVE_REQUEST_SCHEMA and request.get('continuation_recipe')==ACTIVE_RECIPE
            and request.get('mesh_representation')==ACTIVE_REPRESENTATION,'active request recipe/representation differs')
        origin_request.update(schema=REQUEST_SCHEMA,continuation_recipe=RECIPE)
        origin_request.pop('mesh_representation')
    # Every original source/operation/input/native gate is unchanged and is
    # evaluated against its original f01 file, not against the active bd4 file.
    verify(OriginReader(reader),origin_cfg,origin_request)
    return binding


def exit_value(raw):
    require(re.fullmatch(rb'[0-9]+\s*',raw) is not None and 0<=int(raw)<=255,'invalid original exit')
    return int(raw)


def check_index(reader,index):
    for name,row in index.items():
        require(isinstance(row,dict) and set(row)=={'sha256','size'} and type(row['size']) is int
                and reader.size(name)==row['size'] and reader.digest(name)==row['sha256'],'indexed bytes differ: '+name)


def validate_graph_inventory(reader,binding):
    """Bind each selected byte to its owner's original complete collection index."""
    expected_nodes = {'metadata':('metadata-source-bindings/','manifest.json'),
                      'conversion':('tdr-conversion-bindings/','operation.json'),
                      'export':('hdf5-export-bindings/','operation.json')}
    expected_snapshots={};indices={}
    for key,(prefix,receipt) in expected_nodes.items():
        node=binding['nodes'][key]
        require(node.get('receipt_file')==prefix+receipt and node.get('input_archive_file')==prefix+'inputs.tar'
                and node.get('collection_index_file')==prefix+'_collection-members.json'
                and node.get('data_prefix')==('hdf5-export/' if key=='export' else prefix),'source namespace differs')
        expected_snapshots[prefix+receipt]=node['receipt_sha256']
        index_raw=reader.read(prefix+'_collection-members.json');indices[key]=obj(index_raw)
        require(sha(index_raw)==node['collection_index_sha256'],'frozen original collection index differs')
        for name,row in indices[key].items():
            require(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]*',name) is not None
                    and '..' not in name.split('/') and isinstance(row,dict) and set(row)=={'sha256','size'}
                    and type(row['size']) is int and row['size']>=0
                    and re.fullmatch(r'[a-f0-9]{64}',row['sha256']) is not None,'invalid original indexed member')
    require(binding['snapshots_sha256']==expected_snapshots,'receipt snapshot set differs')
    for target,row in binding['imports'].items():
        parts=target.split('/')
        require((len(parts)==1 or len(parts)==2 and parts[0] in NAMESPACES)
                and all(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',part) for part in parts),'unsafe import target')
        require(row.get('owner') in expected_nodes,'unknown import owner')
        node=binding['nodes'][row['owner']]
        if 'external' in row:
            require(set(row)=={'owner','external','sha256','size_bytes'} and row['external']=='inputs.tar'
                    and target==node['input_archive_file'] and row['sha256']==node['inputs_archive_sha256'],
                    'external import is not the original input archive')
        else:
            require(set(row)=={'owner','member','sha256','size_bytes'},'unexpected indexed import fields')
            name=row['member']
            expected=(dict(sha256=node['collection_index_sha256'],size=len(reader.read(node['collection_index_file'])))
                      if name=='_collection-members.json' else indices[row['owner']].get(name))
            require(expected==dict(sha256=row['sha256'],size=row['size_bytes']),'import/original collection index mismatch: '+target)
    # The HDF5 observer receives the entire original export collected directory.
    expected_export={'hdf5-export/'+n for n in indices['export']}|{'hdf5-export/_collection-members.json'}
    require({n for n in binding['imports'] if n.startswith('hdf5-export/')}==expected_export,'incomplete original HDF5 collection')
    expected_conversion={'tdr-conversion-bindings/'+n for n in indices['conversion'] if n!='mesh-v16.tdr'}|{
        'tdr-conversion-bindings/_collection-members.json','tdr-conversion-bindings/inputs.tar'}
    require({n for n in binding['imports'] if n.startswith('tdr-conversion-bindings/')}==expected_conversion,
            'conversion proof inventory differs')
    require(indices['conversion'].get('mesh-v16.tdr')==dict(sha256=binding['hdf5_sha256'],size=binding['hdf5_size_bytes']),
            'native converted file/index identity differs')
    for target,row in binding['imports'].items():
        if 'external' in row:continue
        if row['owner']=='conversion':expected_member=target[len('tdr-conversion-bindings/'):]
        elif row['owner']=='export':
            require(target.startswith(('hdf5-export/','hdf5-export-bindings/')),'export escaped original namespace')
            expected_member=target.split('/',1)[1]
        else:
            expected_member=target[len('metadata-source-bindings/'):] if target.startswith('metadata-source-bindings/') else target
        require(row['member']==expected_member,'original indexed member was relabelled: '+target)
    return indices


def original_input_payload(stream,manifest,needed):
    """Hash every original input, retain only named small contracts in memory."""
    m=mesh_module();payload={};seen=set()
    with tarfile.open(fileobj=stream,mode='r:*') as archive:
        listing=m.members(archive)
        for name,member in listing.items():
            if not member.isfile():continue
            require(name in manifest['input_sha256'],'undeclared original input '+name)
            with archive.extractfile(member) as source:
                if name in needed:
                    raw=source.read();actual=sha(raw);payload[name]=raw
                else:actual=stream_sha(source)
            require(actual==manifest['input_sha256'][name],'original input bytes differ: '+name);seen.add(name)
    require(seen==set(manifest['input_sha256']) and set(needed)<=seen,'original input inventory incomplete')
    declared=obj(payload['input-manifest.json']);context=obj(payload['execution-context.json'])
    require(declared.get('schema')=='dram-see-v4-continuous-inputs-r1'
            and set(declared['files_sha256'])==seen-{'execution-context.json','input-manifest.json'}
            and all(manifest['input_sha256'][n]==h for n,h in declared['files_sha256'].items()),'original declared input set differs')
    require(context.get('schema')=='dram-see-v4-continuous-run-context-r1' and context.get('synthetic') is False
            and context.get('run_id')==context.get('producer_run_id')==manifest['run_id']
            and context.get('role_id')=='B1-D3' and context.get('expected_runner_sha256')==manifest['runner_sha256']
            and context.get('input_manifest_sha256')==sha(payload['input-manifest.json'])
            and context.get('authorization_sha256')==sha(payload['task-authorization.json']), 'original current-run context differs')
    authority=obj(payload['task-authorization.json'])
    require(authority.get('schema')=='dram-see-v4-current-user-authorization-r1' and authority.get('synthetic') is False
            and authority.get('source')=='current_user_instruction' and 'B1-D3' in authority.get('role_ids',[]),
            'original task authorization missing')
    return payload


def validate_identity(reader,manifest,prefix='',operation=False):
    get=lambda name:reader.read(prefix+name)
    identity=obj(get('process-identity.json'))
    run_id=manifest['label'] if operation else manifest['run_id']
    require(identity.get('schema')=='tcad-process-identity-r1' and identity.get('run_id')==run_id
            and identity.get('cwd')==manifest['remote_directory'] and identity.get('script_sha256')
            ==manifest['script_sha256']==sha(get('run.sh'))
            and identity==manifest.get('last_observation',{}).get('identity')
            and type(identity.get('pid')) is int and identity['pid']>1
            and type(identity.get('start_ticks')) is int and identity['start_ticks']>0
            and re.fullmatch(r'[a-f0-9-]{36}',identity.get('boot_id','')) is not None,'wrapper PID/start/boot/script differs')
    if operation:require(identity==manifest.get('process_identity') and manifest.get('wrapper_sha256')==manifest['script_sha256'],'operation identity differs')
    lock=dict(line.split('=',1) for line in get('shared-lock-evidence.txt').decode().splitlines() if '=' in line)
    require(lock.get('status')=='ACQUIRED' and lock.get('pid')==str(identity['pid']) and lock.get('fd')=='9'
            and lock.get('lock_path')=='/home/tcad/research-training/.solver.lock','original shared lock differs')
    if operation:
        status=dict((k.strip(),v.strip()) for k,v in
            (line.split(':',1) for line in get('affinity.txt').decode().splitlines() if ':' in line))
        require(status.get('Threads')=='1' and re.fullmatch(r'[0-9]+',status.get('Cpus_allowed_list','')) is not None,
                'original wrapper affinity differs')
    return identity


def validate_capture(reader,manifest,step,tool,prefix=''):
    identity=validate_identity(reader,manifest,prefix)
    key='step-{:03d}-{}'.format(step,tool)
    evidence=manifest.get('tool_evidence',{}).get(key,{})
    expected=dict(step_index=step,tool=tool,raw_exit_file=key+'-exit-code.txt',process_status_file=key+'-process-status.txt',
        process_observation_file=key+'-process-observation.json',process_admission_file=key+'-process-admission.json',
        raw_process_admission_exit_file=key+'-process-admission-exit-code.txt')
    require(evidence==expected,'capture mapping differs: '+key)
    get=lambda name:reader.read(prefix+name)
    require(exit_value(get(evidence['raw_exit_file']))==0 and exit_value(get(evidence['raw_process_admission_exit_file']))==0,
            'actual native/admission nonzero: '+key)
    admission=obj(get(evidence['process_admission_file']));observed=obj(get(evidence['process_observation_file']))
    status_raw=get(evidence['process_status_file'])
    status=dict((k.strip(),v.strip()) for k,v in (line.split(':',1) for line in status_raw.decode().splitlines() if ':' in line))
    native='svisual_exec' if tool=='svisual' else tool
    executable='svisual_bin/'+native if tool=='svisual' else native
    require(admission.get('schema')=='native-process-admission-r1' and admission.get('origin')=='native_pipeline'
        and admission.get('synthetic') is False and admission.get('requested_tool')==tool and admission.get('status')=='PASSED'
        and admission.get('errors')==[] and admission.get('actual_native_exit_is_separate') is True,'capture admission differs')
    require(observed.get('schema')=='native-process-observation-r1' and observed.get('origin')=='native_pipeline'
        and observed.get('synthetic') is False and observed.get('requested_tool')==tool and observed.get('status')=='OBSERVED'
        and observed.get('wrapper_pid')==identity['pid'] and observed.get('installation_root')=='/usr/synopsys/sentaurus/W-2024.09'
        and observed.get('native_executable')=='/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64/bin/'+executable
        and observed.get('status_file')==evidence['process_status_file'] and observed.get('status_sha256')==sha(status_raw)
        and status.get('Name')==native and status.get('Pid')==str(observed.get('native_pid'))
        and status.get('Threads')==observed.get('observed_threads')=='1'
        and status.get('Cpus_allowed_list')==observed.get('observed_cpus_allowed_list')==admission.get('requested_cpu')
        and re.fullmatch(r'[0-9]+',status.get('Cpus_allowed_list','')) is not None,'native process identity/CPU/thread differs')
    chain=observed.get('parent_chain',[])
    require(chain and chain[0].get('pid')==observed.get('native_pid') and chain[0].get('start_ticks')==observed.get('native_start_ticks')
        and chain[0].get('ppid')==int(status['PPid']) and chain[0].get('name')==native
        and chain[-1]==observed.get('root_identity') and chain[-1].get('ppid')==identity['pid'],'native parent/start chain differs')
    for i,row in enumerate(chain):
        require(type(row.get('start_ticks')) is int and row['start_ticks']>=identity['start_ticks'],'child start differs')
        if i+1<len(chain):require(row['ppid']==chain[i+1]['pid'],'broken native parent chain')


def operation_receipt(reader,prefix,node):
    manifest=obj(reader.read(prefix+'operation.json'))
    require(manifest.get('schema')=='dram-see-v4-transport-operation-v2'
        and manifest.get('state')=='COLLECTED_PENDING_AUDIT' and manifest.get('origin')=='native_pipeline'
        and manifest.get('synthetic') is False and manifest.get('collection_verified') is True
        and manifest.get('label')==node['id'] and manifest.get('archive_sha256')==node['archive_sha256']
        and manifest.get('inputs_archive_sha256')==reader.digest(prefix+'inputs.tar')
        and manifest.get('runner_sha256')==OPERATION_RUNNER_SHA and manifest.get('adapter_sha256')==OPERATION_ADAPTER_SHA,
        'original operation receipt differs')
    for key in ('remote_exit_code','collection_exit_code','operation_task_exit_code'):
        require(type(manifest.get(key)) is int and manifest[key]==0,'operation exit missing/nonzero: '+key)
    require(type(manifest.get('ssh_exit_code')) is int and manifest.get('capture_svisual_requested') is False
            and manifest.get('tool_exit_codes')=={},'operation capture scope differs; do not invent admission')
    data_prefix=node['data_prefix']
    require(exit_value(reader.read(data_prefix+'exit-code.txt'))==0
            and exit_value(reader.read(data_prefix+'operation-task-exit-code.txt'))==0,'operation raw exits differ')
    validate_identity(reader,manifest,data_prefix,operation=True)
    recipe_key='conversion' if prefix=='tdr-conversion-bindings/' else 'export'
    for name,expected in RECIPE_INPUTS[recipe_key].items():
        require(manifest.get('input_sha256',{}).get(name)==expected==reader.digest(data_prefix+name),
                'unregistered native data task implementation: '+name)
    m=mesh_module()
    with reader.stream(prefix+'inputs.tar') as stream,tarfile.open(fileobj=stream,mode='r:*') as archive:
        listing=m.members(archive);names={n for n,v in listing.items() if v.isfile()}
        require(names==set(manifest['input_sha256']),'operation original inputs incomplete')
        for name in names:
            with archive.extractfile(listing[name]) as raw:
                require(stream_sha(raw)==manifest['input_sha256'][name]==reader.digest(data_prefix+name),'operation input differs: '+name)
    return manifest


def validate_metadata_interval(reader,source_cfg,mesh_sha):
    prefix='metadata-source-bindings/'
    status=obj(reader.read('tdr-region-status.json'))
    require(status.get('schema')=='dram-see-v4-tdr-region-observation-r2' and status.get('completed') is True
            and status.get('conversion_performed') is False and status.get('source_modified') is False
            and status.get('original_mesh_sha256')==mesh_sha,'original metadata status differs')
    rows=list(csv.DictReader(reader.read('tdr-topology-identity.csv').decode().splitlines()))
    before=obj(reader.read(prefix+'tdx-source-before.json'))
    path=before.get('path')
    require(before==dict(schema='dram-see-v4-tdx-source-identity-r1',phase='BEFORE',run_id=source_cfg['run_id'],path=path,sha256=mesh_sha)
        and path==obj(reader.read(prefix+'manifest.json'))['remote_directory']+'/cell_msh.tdr'
        and len(rows)==2 and {r.get('phase') for r in rows}=={'BEFORE','AFTER'}
        and all(set(r)=={'phase','path','sha256'} and r['path']==path and r['sha256']==mesh_sha for r in rows),
        'original metadata native interval/path differs')
    for name in METADATA_FILES:
        require(reader.read(name)==reader.read(prefix+name),'metadata copy differs from original: '+name)
    return path


def verify(reader,cfg=None,request=None,allow_deferred=False):
    """Verify frozen selected original bytes, not current mutable receipts."""
    require(not allow_deferred,'metadata source admission requires all original imported bytes')
    binding=obj(reader.read('metadata-source-binding.json'))
    if binding.get('schema')==ACTIVE_SCHEMA:return verify_active(reader,binding,cfg,request)
    require(cfg is None or not set(ACTIVE_CFG_FIELDS)&set(cfg),'r1 cannot select an active representation identity')
    require(binding.get('schema')==SCHEMA and binding.get('recipe')==RECIPE and binding.get('backend')==BACKEND
        and binding.get('inherited_step_indices')==[1,2,3] and binding.get('actual_step_indices')==[5,6]
        and binding.get('origin')=='native_pipeline' and binding.get('synthetic') is False,'wrong metadata branch contract')
    require(set(binding['nodes'])=={'metadata','conversion','export'},'source node set differs')
    indices=validate_graph_inventory(reader,binding)
    for name,row in binding['imports'].items():
        if allow_deferred and not reader.exists(name):continue
        require(reader.size(name)==row['size_bytes'] and reader.digest(name)==row['sha256'],'inherited member changed: '+name)
    for name,expected in binding['snapshots_sha256'].items():
        require(reader.digest(name)==expected,'frozen receipt changed: '+name)
    node=binding['nodes']['metadata'];prefix='metadata-source-bindings/'
    manifest=obj(reader.read(prefix+'manifest.json'))
    require(manifest.get('schema')=='tcad-native-run-r2' and manifest.get('state')=='FAILED_COLLECTED'
        and manifest.get('origin')=='native_pipeline' and manifest.get('synthetic') is False and manifest.get('collection_verified') is True
        and manifest.get('run_id')==node['id'] and manifest.get('results_sha256')==node['archive_sha256']
        and manifest.get('inputs_archive_sha256')==reader.digest(prefix+'inputs.tar')
        and type(manifest.get('ssh_exit_code')) is int and type(manifest.get('collection_exit_code')) is int
        and manifest['collection_exit_code']==0,'metadata source original receipt differs')
    exits=manifest.get('tool_exit_codes',{})
    require(set(exits)=={'step-003-tdx','step-004-tdx','step-005-svisual','step-006-sdevice'}
        and type(exits['step-003-tdx']) is int and exits['step-003-tdx']==0
        and type(exits['step-004-tdx']) is int and 0<exits['step-004-tdx']<=255
        and exits['step-005-svisual'] is None and exits['step-006-sdevice'] is None
        and manifest['remote_exit_code']==exits['step-004-tdx']==exit_value(reader.read(prefix+'exit-code.txt'))
        ==exit_value(reader.read(prefix+'step-004-tdx-exit-code.txt'))==exit_value(reader.read(prefix+'tdx-converter-exit-code.txt')),
        'metadata source failed004/unfinished tail must remain original')
    m=mesh_module()
    needed=set(m.IDENTICAL_INPUTS)|{'project.json','controlled-request.json','input-manifest.json','execution-context.json',
        'task-authorization.json','mesh-source-binding.json','sde-exit-code.txt','mesh-exit-code.txt',
        'sde-geometry-status.txt'}|set(binding['ancestor_proofs_sha256'])
    with reader.stream(prefix+'inputs.tar') as stream:original=original_input_payload(stream,manifest,needed)
    source_cfg=obj(original['project.json'])['s2_geometry'];source_request=obj(original['controlled-request.json'])
    ancestor=m.verify_packet(original.__getitem__,manifest['input_sha256'].__getitem__,source_cfg,source_request)
    expected_metadata=set(ancestor['proofs_sha256'])|set(m.IMPORTED_OUTPUTS)|{
        'metadata-source-bindings/'+n for n in METADATA_PROOF}|set(METADATA_FILES)|{
        'tdx-metadata-exit-code.txt','metadata-source-bindings/inputs.tar','metadata-source-bindings/_collection-members.json'}
    require({n for n,r in binding['imports'].items() if r['owner']=='metadata'}==expected_metadata,
            'metadata/ancestor proof inventory differs')
    require({n for n,r in binding['imports'].items() if r['owner']=='export'}==
        {'hdf5-export/'+n for n in indices['export']}|{'hdf5-export/_collection-members.json',
        'hdf5-export-bindings/inputs.tar','hdf5-export-bindings/_collection-members.json'},'export owner proof inventory differs')
    source_spec=obj(original['project.json'])
    require(manifest.get('steps')==source_spec.get('steps')
        and [(s.get('tool'),s.get('args')) for s in source_spec['steps']]==list(m.SIX_STEPS[2:])
        and source_spec.get('native_threads')==source_spec.get('native_cores')==1,
        'metadata producer original serial steps differ')
    require(manifest.get('native_step_start_index')==3 and manifest.get('inherited_step_indices')==[1,2]
        and manifest.get('mesh_source_binding_sha256')==sha(original['mesh-source-binding.json'])
        ==binding['ancestor_mesh_binding_sha256']==reader.digest('mesh-source-binding.json'), 'metadata/r9 ancestry differs')
    for name,expected in ancestor['proofs_sha256'].items():
        require(binding['ancestor_proofs_sha256'].get(name)==expected and reader.digest(name)==expected,'ancestor proof differs: '+name)
    require(binding['mesh_sha256']==ancestor['mesh_sha256'] and binding['mesh_size_bytes']==ancestor['mesh_size_bytes'], 'ancestor mesh differs')
    require(binding.get('failed_step004')==dict(owner=manifest['run_id'],exit_code=exits['step-004-tdx']),
            'original failed004 provenance differs')
    identical=set(m.IDENTICAL_INPUTS)-set(CHANGED_IMPLEMENTATIONS)
    require(set(binding['identical_scientific_inputs_sha256'])==identical,'scientific input set differs')
    require(binding.get('original_implementation_sha256')=={n:sha(original[n]) for n in CHANGED_IMPLEMENTATIONS}
        and binding.get('scientific_qualification') is False,'original implementation snapshot/scope differs')
    for name in identical:
        require(reader.digest(name)==binding['identical_scientific_inputs_sha256'][name]==sha(original[name]),'scientific input changed: '+name)
    validate_capture(reader,manifest,3,'tdx',prefix)
    require(reader.read('tdx-metadata-exit-code.txt')==reader.read(prefix+'step-003-tdx-exit-code.txt'), 'inherited metadata exit differs')
    metadata_path=validate_metadata_interval(reader,source_cfg,binding['mesh_sha256'])
    conversion=operation_receipt(reader,'tdr-conversion-bindings/',binding['nodes']['conversion'])
    cp='tdr-conversion-bindings/'
    declaration=obj(reader.read(cp+'assumptions-and-input-binding.json'))
    original_path=obj(original['mesh-source-bindings/manifest.json'])['remote_directory']+'/cell_msh.tdr'
    require(declaration.get('schema')=='dram-see-v4-tdr-version-conversion-candidate-r1'
        and declaration.get('source_run_id')==ancestor['source_run_id'] and declaration.get('source_sha256')==binding['mesh_sha256']
        and declaration.get('source_archive_sha256')==ancestor['source_archive_sha256']
        and declaration.get('source_tdr_remote_path')==original_path and declaration.get('source_bytes')==binding['mesh_size_bytes']
        and declaration.get('metadata_run_id')==manifest['run_id'] and declaration.get('metadata_archive_sha256')==manifest['results_sha256']
        and declaration.get('command')==['/usr/synopsys/sentaurus/W-2024.09/bin/tdx','--tdr2tdr','--version-16',original_path,'mesh-v16.tdr'],
        'conversion input/official command relationship differs')
    expected_line=(binding['mesh_sha256']+'  '+original_path+'\n').encode()
    require(reader.read(cp+'source-before.sha256')==reader.read(cp+'source-after.sha256')==expected_line
        and exit_value(reader.read(cp+'converter-exit-code.txt'))==0 and exit_value(reader.read(cp+'hdf5-header-exit-code.txt'))==0,
        'conversion raw exit/source interval differs')
    require(reader.read(cp+'destination.sha256')==(binding['hdf5_sha256']+'  mesh-v16.tdr\n').encode(), 'converted destination hash differs')
    fmt=obj(reader.read(cp+'file-format.json'))
    require(fmt.get('path')=='mesh-v16.tdr' and fmt.get('bytes')==binding['hdf5_size_bytes']
        and fmt.get('hdf5_signature_at_zero') is True and fmt.get('ogawa_signature_at_zero') is False,'converted container format differs')
    export=operation_receipt(reader,'hdf5-export-bindings/',binding['nodes']['export'])
    export_request=obj(reader.read('hdf5-export/export-request.json'))
    require(export_request.get('schema')=='dram-see-v4-hdf5-raw-export-request-r1'
        and export_request.get('label')==export['label'] and export_request.get('source_operation')==conversion['label']
        and export_request.get('source_operation_archive_sha256')==conversion['archive_sha256']
        and export_request.get('source')==conversion['remote_directory']+'/mesh-v16.tdr'
        and export_request.get('source_sha256')==binding['hdf5_sha256'] and export_request.get('source_bytes')==binding['hdf5_size_bytes']
        and export_request.get('original_mesh_source')==original_path and export_request.get('original_mesh_sha256')==binding['mesh_sha256']
        and export_request.get('binary_format')=='FILE', 'HDF5 export/conversion/original mesh edge differs')
    for name in ('source-before.json','source-after.json'):
        row=obj(reader.read('hdf5-export/'+name))
        require(row.get('source')==export_request['source'] and row.get('sha256')==binding['hdf5_sha256']
            and row.get('original_source')==original_path and row.get('original_sha256')==binding['mesh_sha256'], 'export source interval differs')
    exported=obj(reader.read('hdf5-export/raw-export-manifest.json'))
    require(exported.get('schema')=='dram-see-v4-hdf5-raw-export-r1' and exported.get('completed') is True
        and exported.get('source_sha256')==binding['hdf5_sha256'] and exported.get('original_mesh_sha256')==binding['mesh_sha256']
        and exported.get('native_command_count')==35 and exported.get('all_native_exit_codes')==[0]*35
        and exported.get('binary_format')=='FILE' and len(exported.get('exports',[]))==34
        and [r.get('path') for r in exported['exports']]==export_request['datasets'], 'complete native export inventory differs')
    h5dump='/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64/bin/h5dump'
    for i,row in enumerate(exported['exports']):
        base='dataset-{:02d}'.format(i)
        require(row.get('file')==base+'.bin' and row.get('command_record')==base+'-command.json'
            and row.get('native_ddl')==base+'-stdout.txt', 'export member mapping differs')
        record=obj(reader.read('hdf5-export/'+row['command_record']))
        require(type(record.get('exit_code')) is int and record['exit_code']==0
            and record.get('command')==[h5dump,'-d',row['path'],'-b','FILE','-o',row['file'],export_request['source']], 'raw h5dump command/exit differs')
        imported=binding['imports']['hdf5-export/'+row['file']]
        require(row.get('sha256')==imported['sha256'] and row.get('bytes')==imported['size_bytes'], 'raw binary digest differs')
    attributes=obj(reader.read('hdf5-export/hdf5-attributes-command.json'))
    require(type(attributes.get('exit_code')) is int and attributes['exit_code']==0
        and attributes.get('command')==[h5dump,'-A','-m','%.17g',export_request['source']], 'native complete attributes command differs')
    if request is not None:
        require(request.get('schema')==REQUEST_SCHEMA and request.get('continuation_recipe')==RECIPE,'new request recipe differs')
        for field,key in (('metadata_source_run','metadata'),('tdr_conversion_operation','conversion'),('hdf5_export_operation','export')):
            require(request.get(field)==binding['nodes'][key]['directory'],'source directory differs: '+field)
        for field in ('gate_top_depth_nm','sn_junction_depth_nm','dimension','variant','mesh_policy'):
            require(request.get(field)==source_request.get(field),'original requested physics/numerics changed: '+field)
    if cfg is not None:
        require(cfg.get('mode')=='produce_from_metadata' and cfg.get('role_id')=='B1-D3'
            and cfg.get('producer_run_id')==cfg.get('run_id') not in (manifest['run_id'],ancestor['source_run_id'])
            and cfg.get('metadata_source_binding_sha256')==reader.digest('metadata-source-binding.json')
            and cfg.get('geometry_observation_backend')==BACKEND,'current metadata producer identity differs')
        for name in ('size_id','sn_junction_depth_nm','numerical_variant','parameter_id','mesh_policy_id','mesh_policy_sha256','controlled_parameters_sha256'):
            require(cfg.get(name)==source_cfg.get(name),'current producer physics/numerics differ: '+name)
    require(binding.get('metadata_original_path')==metadata_path,'metadata original path binding differs')
    return binding


def evidence_hashes(reader,binding=None):
    """Source proofs exported with a completed producer, including empty originals."""
    binding=binding or obj(reader.read('metadata-source-binding.json'))
    result={name:row['sha256'] for name,row in binding['imports'].items()}
    result.update(binding['snapshots_sha256'])
    result['metadata-source-binding.json']=reader.digest('metadata-source-binding.json')
    result['mesh-source-binding.json']=reader.digest('mesh-source-binding.json')
    if binding.get('schema')==ACTIVE_SCHEMA:
        result[ORIGIN_BINDING_FILE]=reader.digest(ORIGIN_BINDING_FILE)
    return result


def validate_completed(reader,manifest,cfg,inputs_stream):
    """Actual successful005/006 plus the frozen independent source graph."""
    require(manifest.get('state')=='COLLECTED' and manifest.get('collection_verified') is True
        and manifest.get('origin')=='native_pipeline' and manifest.get('synthetic') is False
        and type(manifest.get('remote_exit_code')) is int and manifest['remote_exit_code']==0
        and type(manifest.get('collection_exit_code')) is int and manifest['collection_exit_code']==0
        and type(manifest.get('ssh_exit_code')) is int,'metadata producer lacks completed original collection')
    keys={'step-005-svisual','step-006-sdevice'}
    require(set(manifest.get('tool_exit_codes',{}))==keys and set(manifest.get('tool_evidence',{}))==keys
        and all(type(v) is int and v==0 for v in manifest['tool_exit_codes'].values())
        and manifest.get('native_step_start_index')==5 and manifest.get('inherited_step_indices')==[1,2,3]
        and manifest.get('metadata_source_binding_sha256')==reader.digest('metadata-source-binding.json')
        and manifest.get('geometry_observation_backend')==BACKEND,'metadata producer actual exit/source set differs')
    for name in FORBIDDEN_CURRENT:require(not reader.exists(name),'completed producer has fabricated/legacy current member '+name)
    needed={'project.json','input-manifest.json','execution-context.json','task-authorization.json','controlled-request.json'}
    original=original_input_payload(inputs_stream,manifest,needed)
    # Every frozen input must still be its original byte sequence in the archive.
    for name,expected in manifest['input_sha256'].items():
        require(reader.digest(name)==expected,'completed producer input changed: '+name)
    spec=obj(original['project.json'])
    require(spec.get('s2_geometry')==cfg and manifest['steps']==spec.get('steps')
        and [(s.get('tool'),s.get('args')) for s in spec['steps']]==list(mesh_module().SIX_STEPS[4:])
        and spec.get('native_threads')==spec.get('native_cores')==1,'completed metadata producer steps differ')
    binding=verify(reader,cfg,obj(original['controlled-request.json']))
    for step,tool in ((5,'svisual'),(6,'sdevice')):validate_capture(reader,manifest,step,tool)
    require(exit_value(reader.read('exit-code.txt'))==0,'completed producer raw wrapper nonzero')
    for name in spec['steps'][-1].get('outputs',[]):
        require(reader.exists(name) and reader.size(name)>0,'actual SDevice output absent/empty: '+name)
    return binding


def source_package(request):
    """Verify all four original owners, return small payload plus streaming imports."""
    m=mesh_module();files={};imports={};nodes={};readers={};opened=[]
    def imported(target,owner,member,reader):
        imports[target]=dict(owner=owner,member=member,sha256=reader.digest(member),size_bytes=reader.size(member))
    try:
        for key,field,receipt_name,prefix in (
            ('metadata','metadata_source_run','manifest.json','metadata-source-bindings/'),
            ('conversion','tdr_conversion_operation','operation.json','tdr-conversion-bindings/'),
            ('export','hdf5_export_operation','operation.json','hdf5-export-bindings/')):
            folder=Path(request[field])
            require(folder.is_absolute() and folder.is_dir() and not folder.is_symlink()
                and 'UNIT_FIXTURE_NOT_NATIVE' not in str(folder),'invalid original source folder')
            receipt=(folder/receipt_name).read_bytes();manifest=obj(receipt)
            id_value=manifest.get('run_id') if key=='metadata' else manifest.get('label')
            require(folder.name==id_value,'source directory identity differs')
            archive_sha=file_sha(folder/'results.tar')
            require(archive_sha==manifest.get('results_sha256' if key=='metadata' else 'archive_sha256'), 'source archive differs')
            archive=tarfile.open(str(folder/'results.tar'),'r:*');opened.append(archive)
            listing=m.members(archive);reader=ArchiveReader(archive,listing);readers[key]=reader
            index_raw=reader.read('_collection-members.json');index=obj(index_raw)
            require(set(index)=={n for n,v in listing.items() if v.isfile()}-{'_collection-members.json'},'full collection member set differs')
            check_index(reader,index)
            require(file_sha(folder/'inputs.tar')==manifest.get('inputs_archive_sha256'),'source original input archive differs')
            files[prefix+receipt_name]=receipt
            imports[prefix+'inputs.tar']=dict(owner=key,external='inputs.tar',sha256=manifest['inputs_archive_sha256'],size_bytes=(folder/'inputs.tar').stat().st_size)
            imported(prefix+'_collection-members.json',key,'_collection-members.json',reader)
            nodes[key]=dict(id=id_value,directory=str(folder),archive_sha256=archive_sha,archive_size_bytes=(folder/'results.tar').stat().st_size,
                receipt_file=prefix+receipt_name,receipt_sha256=sha(receipt),input_archive_file=prefix+'inputs.tar',
                inputs_archive_sha256=manifest['inputs_archive_sha256'],collection_index_file=prefix+'_collection-members.json',
                collection_index_sha256=sha(index_raw),data_prefix=('hdf5-export/' if key=='export' else prefix))
        meta=readers['metadata'];manifest=obj(files['metadata-source-bindings/manifest.json'])
        ancestor=obj(meta.read('mesh-source-binding.json'))
        ancestor_folder=Path(ancestor['source_run_directory'])
        require(file_sha(ancestor_folder/'results.tar')==ancestor['source_archive_sha256']
            and file_sha(ancestor_folder/'inputs.tar')==ancestor['source_inputs_archive_sha256'],
            'original r9 prefix archives changed')
        for name in m.IDENTICAL_INPUTS:
            files[name]=meta.read(name)
        files['mesh-source-binding.json']=meta.read('mesh-source-binding.json')
        for name in ancestor['proofs_sha256']:imported(name,'metadata',name,meta)
        for name in m.IMPORTED_OUTPUTS:imported(name,'metadata',name,meta)
        for name in METADATA_PROOF:imported('metadata-source-bindings/'+name,'metadata',name,meta)
        for name in METADATA_FILES+('tdx-metadata-exit-code.txt',):imported(name,'metadata',name,meta)
        conversion=readers['conversion']
        for name,member in conversion.members.items():
            if member.isfile() and name!='mesh-v16.tdr':imported('tdr-conversion-bindings/'+name,'conversion',name,conversion)
        export=readers['export']
        for name,member in export.members.items():
            if member.isfile():imported('hdf5-export/'+name,'export',name,export)
        binding=dict(schema=SCHEMA,recipe=RECIPE,backend=BACKEND,origin='native_pipeline',synthetic=False,nodes=nodes,
            inherited_step_indices=[1,2,3],actual_step_indices=[5,6],
            failed_step004=dict(owner=nodes['metadata']['id'],exit_code=manifest['tool_exit_codes']['step-004-tdx']),
            ancestor_mesh_binding_sha256=sha(files['mesh-source-binding.json']),ancestor_proofs_sha256=ancestor['proofs_sha256'],
            mesh_sha256=ancestor['mesh_sha256'],mesh_size_bytes=ancestor['mesh_size_bytes'],
            hdf5_sha256=conversion.digest('mesh-v16.tdr'),hdf5_size_bytes=conversion.size('mesh-v16.tdr'),
            metadata_original_path=obj(meta.read('tdx-source-before.json'))['path'],
            identical_scientific_inputs_sha256={n:sha(files[n]) for n in m.IDENTICAL_INPUTS if n not in CHANGED_IMPLEMENTATIONS},
            original_implementation_sha256={n:sha(files[n]) for n in CHANGED_IMPLEMENTATIONS},
            snapshots_sha256={n:sha(raw) for n,raw in files.items() if n.endswith(('/manifest.json','/operation.json'))},imports=imports,
            external_native_capture_scope='Original operation tasks did not request Sentaurus process capture; wrapper identity/affinity and real task/tool exits are retained',
            scientific_qualification=False)
        files['metadata-source-binding.json']=encoded(binding)
        # A prospective reader uses originals directly. It executes no original scripts.
        class ProspectiveReader:
            def exists(self,name):return name in files or name in imports
            def stream(self,name):
                row=imports[name]
                if 'external' in row:return (Path(nodes[row['owner']]['directory'])/row['external']).open('rb')
                return readers[row['owner']].stream(row['member'])
            def read(self,name):
                if name in files:return files[name]
                with self.stream(name) as stream:return stream.read()
            def digest(self,name):return sha(files[name]) if name in files else imports[name]['sha256']
            def size(self,name):return len(files[name]) if name in files else imports[name]['size_bytes']
        if request.get('schema')==ACTIVE_REQUEST_SCHEMA:
            origin_raw=files['metadata-source-binding.json']
            binding=active_binding(origin_raw)
            files[ORIGIN_BINDING_FILE]=origin_raw
            files['metadata-source-binding.json']=encoded(binding)
            imports=binding['imports']
        verify(ProspectiveReader(),request=request)
        return dict(files=files,imports=imports,binding=binding,mesh_sha256=binding['mesh_sha256'])
    finally:
        for archive in opened:archive.close()


def verify_folder(folder,cfg,allow_deferred=False):
    reader=FolderReader(folder)
    for name in FORBIDDEN_CURRENT:require(not reader.exists(name),'forbidden fabricated/current legacy output '+name)
    return verify(reader,cfg,obj(reader.read('controlled-request.json')),allow_deferred)


def stage(folder,cfg):
    """Verify frozen graph, copy exact indexed members with no mutable receipts."""
    folder=Path(folder);binding=obj((folder/'metadata-source-binding.json').read_bytes());m=mesh_module()
    if binding.get('schema')==ACTIVE_SCHEMA:
        require(binding==active_binding((folder/ORIGIN_BINDING_FILE).read_bytes()),'active stage mapping differs before copying')
    for name in binding['imports']:
        parts=name.split('/')
        require((len(parts)==1 or len(parts)==2 and parts[0] in NAMESPACES)
            and all(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',part) for part in parts),'unsafe staged import target')
    ancestor=obj((folder/'mesh-source-binding.json').read_bytes());ancestor_folder=Path(ancestor['source_run_directory'])
    require(file_sha(ancestor_folder/'results.tar')==ancestor['source_archive_sha256']
        and file_sha(ancestor_folder/'inputs.tar')==ancestor['source_inputs_archive_sha256'],'original prefix archives changed before stage')
    for key,node in binding['nodes'].items():
        source=Path(node['directory']);archive_path=source/'results.tar'
        require(source.is_absolute() and source.name==node['id'] and not source.is_symlink()
            and file_sha(archive_path)==node['archive_sha256'] and archive_path.stat().st_size==node['archive_size_bytes']
            and file_sha(source/'inputs.tar')==node['inputs_archive_sha256'],'original graph node changed before stage: '+key)
        with tarfile.open(str(archive_path),'r:*') as archive:
            listing=m.members(archive)
            for name,row in binding['imports'].items():
                if row['owner']!=key:continue
                target=folder/name;target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    require(file_sha(target)==row['sha256'] and target.stat().st_size==row['size_bytes'],'existing inherited member differs: '+name);continue
                stream=(source/row['external']).open('rb') if 'external' in row else archive.extractfile(listing[row['member']])
                with stream,target.open('xb') as output:
                    for block in iter(lambda:stream.read(1048576),b''):output.write(block)
                require(file_sha(target)==row['sha256'] and target.stat().st_size==row['size_bytes'],'staged member differs: '+name)
        require(file_sha(archive_path)==node['archive_sha256'],'original node archive changed during stage: '+key)
    verify_folder(folder,cfg)
    return cfg
