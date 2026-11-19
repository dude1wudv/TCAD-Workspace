"""Pure, closed provenance for a D3 mesh whose original step 3 failed.

No native process or archived Python/Tcl is executed. Python 3.6 compatible.
The source archive remains FAILED_COLLECTED; this is input inheritance only.
"""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

SCHEMA = 'dram-see-v4-mesh-source-binding-r1'
PREFIX = 'mesh-source-bindings/'
IDENTICAL_INPUTS = (
    'physics.par', 'physics-manifest.json', 'Silicon.par', 'Oxide.par',
    'model.proposed.json', 'geometry-contract.json', 'measurement-plan.json',
    'geometry-with-measurements.scm', 'measure-geometry.tcl', 'device.cmd',
    'numerical-method.json', 'controlled-parameters.json',
    'mesh-policy.json', 'mesh-policy-definition.json', 'mesh-policy-assumptions.md',
    'evaluate.py', 'dfise_observer.py',
)
IMPORTED_OUTPUTS = (
    'cell_msh.tdr', 'cell_msh.log', 'cell_bnd.tdr', 'cell.cmd',
    'sde-contact-measurements.csv', 'sde-contact-probes.csv',
    'sde-material-probes.csv', 'sde-geometry-status.txt',
    'sde-exit-code.txt', 'mesh-exit-code.txt',
)
PREFIX_PROOF = tuple('step-{:03d}-{}-{}'.format(i, tool, suffix)
    for i, tool in ((1, 'sde'), (2, 'snmesh'))
    for suffix in ('exit-code.txt', 'process-status.txt', 'process-observation.json',
                   'process-admission.json', 'process-admission-exit-code.txt'))
PROOF_MEMBERS = PREFIX_PROOF + (
    'process-identity.json', 'shared-lock-evidence.txt', 'run.sh', 'execution.log',
    'exit-code.txt', 'step-003-tdx-exit-code.txt', 'tdx-metadata-exit-code.txt',
    'tdx-source-before.json', 'project.json', 'execution-context.json',
    'input-manifest.json', 'task-authorization.json', 'controlled-request.json',
)
SIX_STEPS = (
    ('sde',['-e','-l','geometry-with-measurements.scm']),
    ('snmesh',['--threads','1','--max_threads','1','cell']),
    ('tdx',['-tcl','observe_tdr_topology.tcl','cell_msh.tdr']),
    ('tdx',['-dd','-M','0','-S','0','cell_msh.tdr','mesh-observed']),
    ('svisual',['--threads','1','--max_threads','1','-b','-tcl','-script','measure-geometry.tcl']),
    ('sdevice',['device.cmd']),
)


def require(ok, message):
    if not ok:
        raise ValueError('Mesh inheritance: ' + message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def stream_sha(stream):
    value = hashlib.sha256()
    for block in iter(lambda: stream.read(1048576), b''):
        value.update(block)
    return value.hexdigest()


def file_sha(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'missing or linked ' + str(path))
    with path.open('rb') as stream:
        return stream_sha(stream)


def obj(raw):
    result = json.loads(raw.decode('utf-8'))
    require(isinstance(result, dict), 'JSON object required')
    return result


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n').encode('utf-8')


def members(archive):
    result = {}
    for member in archive.getmembers():
        name = member.name
        while name.startswith('./'):
            name = name[2:]
        if name in ('', '.') and member.isdir():
            continue
        path = PurePosixPath(name)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in name and ':' not in name,
                'unsafe archive member')
        name = path.as_posix()
        require(name not in result and (member.isfile() or member.isdir()), 'duplicate/link archive member')
        result[name] = member
    return result


def raw_member(archive, listing, name):
    require(name in listing and listing[name].isfile(), 'missing original member ' + name)
    with archive.extractfile(listing[name]) as stream:
        return stream.read()


def exit_value(raw):
    require(re.fullmatch(rb'[0-9]+\s*', raw) is not None and 0 <= int(raw) <= 255, 'invalid original exit')
    return int(raw)


def validate_source_manifest(manifest):
    require(manifest.get('schema') == 'tcad-native-run-r2' and manifest.get('origin') == 'native_pipeline'
            and manifest.get('synthetic') is False and manifest.get('collection_verified') is True
            and manifest.get('state') == 'FAILED_COLLECTED', 'source must retain its real failed collection state')
    require(type(manifest.get('collection_exit_code')) is int and manifest['collection_exit_code'] == 0
            and type(manifest.get('ssh_exit_code')) is int, 'source collection/transport evidence missing')
    exits = manifest.get('tool_exit_codes', {})
    require(set(exits) == {'step-001-sde','step-002-snmesh','step-003-tdx','step-004-tdx','step-005-svisual','step-006-sdevice'},
            'source six-step attempt identity differs')
    require(all(type(exits[k]) is int and exits[k] == 0 for k in ('step-001-sde','step-002-snmesh'))
            and type(exits['step-003-tdx']) is int and 0 < exits['step-003-tdx'] <= 255
            and all(exits[k] is None for k in ('step-004-tdx','step-005-svisual','step-006-sdevice'))
            and type(manifest.get('remote_exit_code')) is int
            and manifest['remote_exit_code'] == exits['step-003-tdx'],
            'only the original successful prefix followed by failed metadata step is supported')


def validate_prefix(get, manifest):
    identity = obj(get('process-identity.json'))
    require(identity.get('schema') == 'tcad-process-identity-r1'
            and identity.get('run_id') == manifest['run_id']
            and identity.get('cwd') == manifest['remote_directory']
            and identity.get('script_sha256') == manifest['script_sha256'] == sha(get('run.sh'))
            and identity == manifest.get('last_observation', {}).get('identity')
            and type(identity.get('pid')) is int and identity['pid'] > 1
            and type(identity.get('start_ticks')) is int and identity['start_ticks'] > 0
            and re.fullmatch(r'[a-f0-9-]{36}', identity.get('boot_id', '')) is not None,
            'source wrapper PID/start/boot/script identity differs')
    lock = dict(line.split('=', 1) for line in get('shared-lock-evidence.txt').decode().splitlines() if '=' in line)
    require(lock.get('status') == 'ACQUIRED' and lock.get('fd') == '9'
            and lock.get('lock_path') == '/home/tcad/research-training/.solver.lock'
            and lock.get('pid') == str(identity['pid']), 'source shared lock evidence differs')
    for i, tool, canonical in ((1,'sde','sde-exit-code.txt'),(2,'snmesh','mesh-exit-code.txt')):
        prefix = 'step-{:03d}-{}'.format(i,tool)
        evidence = manifest.get('tool_evidence', {}).get(prefix, {})
        names = dict(raw_exit_file=prefix+'-exit-code.txt', process_status_file=prefix+'-process-status.txt',
            process_observation_file=prefix+'-process-observation.json', process_admission_file=prefix+'-process-admission.json',
            raw_process_admission_exit_file=prefix+'-process-admission-exit-code.txt')
        require(evidence == dict(names, step_index=i, tool=tool), 'original capture file mapping differs')
        require(exit_value(get(names['raw_exit_file'])) == 0 and get(canonical) == get(names['raw_exit_file'])
                and exit_value(get(names['raw_process_admission_exit_file'])) == 0, 'source native/admission exit differs')
        admission = obj(get(names['process_admission_file']))
        observed = obj(get(names['process_observation_file']))
        status_raw = get(names['process_status_file'])
        status = dict((k.strip(),v.strip()) for k,v in
                      (line.split(':',1) for line in status_raw.decode().splitlines() if ':' in line))
        require(admission.get('schema') == 'native-process-admission-r1' and admission.get('origin') == 'native_pipeline'
                and admission.get('synthetic') is False and admission.get('requested_tool') == tool
                and admission.get('status') == 'PASSED' and admission.get('errors') == []
                and admission.get('actual_native_exit_is_separate') is True, 'source process admission differs')
        require(observed.get('schema') == 'native-process-observation-r1' and observed.get('origin') == 'native_pipeline'
                and observed.get('synthetic') is False and observed.get('status') == 'OBSERVED'
                and observed.get('requested_tool') == tool and observed.get('wrapper_pid') == identity['pid']
                and observed.get('installation_root') == '/usr/synopsys/sentaurus/W-2024.09'
                and observed.get('native_executable') == '/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64/bin/'+tool
                and observed.get('native_candidate_count') == 1 and observed.get('selection_method') == 'single_exact_native'
                and observed.get('status_file') == names['process_status_file'] and observed.get('status_sha256') == sha(status_raw),
                'source native tool/installation/raw observation differs')
        cpu = admission.get('requested_cpu')
        require(isinstance(cpu,str) and re.fullmatch(r'[0-9]+',cpu) is not None
                and observed.get('observed_threads') == status.get('Threads') == '1'
                and observed.get('observed_cpus_allowed_list') == status.get('Cpus_allowed_list') == cpu
                and status.get('Name') == tool and status.get('Pid') == str(observed.get('native_pid')),
                'source observed native CPU/thread/name differs')
        chain = observed.get('parent_chain')
        require(isinstance(chain,list) and chain and chain[0].get('pid') == observed.get('native_pid')
                and chain[0].get('start_ticks') == observed.get('native_start_ticks')
                and chain[0].get('ppid') == int(status['PPid']) and chain[0].get('name') == tool
                and chain[-1].get('pid') == observed.get('root_child_pid')
                and chain[-1] == observed.get('root_identity') and chain[-1].get('ppid') == identity['pid'],
                'source parent chain differs')
        for position,row in enumerate(chain):
            require(type(row.get('pid')) is int and type(row.get('start_ticks')) is int
                    and row['start_ticks'] >= identity['start_ticks'], 'source child start identity invalid')
            if position+1 < len(chain):
                require(row['ppid'] == chain[position+1]['pid'], 'broken source parent chain')
    require(exit_value(get('exit-code.txt')) == manifest['remote_exit_code']
            == exit_value(get('step-003-tdx-exit-code.txt')) == exit_value(get('tdx-metadata-exit-code.txt')),
            'original failed exit must be preserved')
    require(get('sde-geometry-status.txt') == b'S2_SDE_GEOMETRY_OBSERVATION_COMPLETED\n', 'SDE observation incomplete')


def original_inputs(raw, manifest):
    require(sha(raw) == manifest['inputs_archive_sha256'], 'original input archive changed')
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:*') as archive:
        listing = members(archive)
        files = {name:raw_member(archive,listing,name) for name,item in listing.items() if item.isfile()}
    require(set(files) == set(manifest['input_sha256']), 'original input archive membership differs')
    require(all(sha(raw) == manifest['input_sha256'][name] for name,raw in files.items()), 'original input archive bytes differ')
    context, declared = obj(files['execution-context.json']),obj(files['input-manifest.json'])
    source_id = manifest['run_id']
    require(declared.get('schema') == 'dram-see-v4-continuous-inputs-r1' and declared.get('run_id') == source_id
            and declared.get('role_id') == 'B1-D3'
            and set(declared['files_sha256']) == set(files)-{'execution-context.json','input-manifest.json'}
            and all(sha(files[n]) == h for n,h in declared['files_sha256'].items()), 'original declared input inventory differs')
    authority = obj(files['task-authorization.json'])
    require(context.get('schema') == 'dram-see-v4-continuous-run-context-r1' and context.get('synthetic') is False
            and context.get('run_id') == context.get('producer_run_id') == source_id and context.get('role_id') == 'B1-D3'
            and context.get('input_manifest_sha256') == sha(files['input-manifest.json'])
            and context.get('expected_runner_sha256') == manifest['runner_sha256']
            and context.get('authorization_sha256') == sha(files['task-authorization.json'])
            and authority.get('schema') == 'dram-see-v4-current-user-authorization-r1'
            and authority.get('synthetic') is False and authority.get('source') == 'current_user_instruction'
            and 'B1-D3' in authority.get('role_ids',[]) and authority.get('instruction'), 'original authorization/context differs')
    return files


def source_package(source, request, frozen_manifest=None):
    """Read and verify the real original archive; return a prospective payload."""
    source = Path(source)
    require(source.is_absolute() and source.is_dir() and not source.is_symlink()
            and 'UNIT_FIXTURE_NOT_NATIVE' not in str(source) and not (source/'SYNTHETIC_NOT_NATIVE').exists(), 'invalid source directory')
    manifest_raw = (source/'manifest.json').read_bytes() if frozen_manifest is None else frozen_manifest
    manifest = obj(manifest_raw)
    validate_source_manifest(manifest)
    require(source.name == manifest['run_id'], 'source directory/run identity differs')
    archive_path = source/'results.tar'
    archive_sha = file_sha(archive_path)
    require(manifest['results_sha256'] == archive_sha, 'source archive hash differs')
    input_raw = (source/'inputs.tar').read_bytes()
    inputs = original_inputs(input_raw,manifest)
    with tarfile.open(str(archive_path),'r:*') as archive:
        listing = members(archive)
        get = lambda name: raw_member(archive,listing,name)
        index_raw = get('_collection-members.json')
        index = obj(index_raw)
        require(set(index) == {n for n,v in listing.items() if v.isfile()}-{'_collection-members.json'}, 'source complete index membership differs')
        for name,row in index.items():
            require(isinstance(row,dict) and set(row) == {'sha256','size'} and type(row['size']) is int
                    and listing[name].size == row['size'], 'source index size/schema differs: '+name)
            with archive.extractfile(listing[name]) as stream:
                require(stream_sha(stream) == row['sha256'], 'source indexed bytes differ: '+name)
        for name,raw in inputs.items():
            require(index.get(name,{}).get('sha256') == sha(raw), 'source result/input archive mismatch: '+name)
        validate_prefix(get,manifest)
        files = {name:inputs[name] for name in IDENTICAL_INPUTS}
        files.update({PREFIX+name:get(name) for name in PROOF_MEMBERS})
        files.update({PREFIX+'manifest.json':manifest_raw,PREFIX+'inputs.tar':input_raw,PREFIX+'_collection-members.json':index_raw})
        for name in IMPORTED_OUTPUTS:
            require(name in index and index[name]['size'] > 0, 'missing/empty source output '+name)
            if name != 'cell_msh.tdr':
                files[name] = get(name)
        imports = {name:dict(member=name,sha256=index[name]['sha256'],size_bytes=index[name]['size']) for name in IMPORTED_OUTPUTS}
    binding = dict(schema=SCHEMA,origin='native_pipeline',synthetic=False,source_run_id=source.name,
        source_run_directory=str(source),source_manifest_sha256=sha(manifest_raw),source_archive_sha256=archive_sha,
        source_archive_size_bytes=archive_path.stat().st_size,source_inputs_archive_sha256=sha(input_raw),
        source_collection_index_sha256=sha(index_raw),source_input_manifest_sha256=sha(inputs['input-manifest.json']),
        inherited_step_indices=[1,2],actual_step_indices=[3,4,5,6],
        source_remote_exit_code=manifest['remote_exit_code'],source_state=manifest['state'],
        identical_inputs_sha256={name:sha(inputs[name]) for name in IDENTICAL_INPUTS},
        imports=imports,proofs_sha256={name:sha(raw) for name,raw in files.items() if name.startswith(PREFIX)},
        mesh_sha256=index['cell_msh.tdr']['sha256'],mesh_size_bytes=index['cell_msh.tdr']['size'],
        interpretation='Inherited successful native prefix only; no completed geometry or electrical qualification')
    files['mesh-source-binding.json'] = json_bytes(binding)
    get = lambda name: files[name]
    hashes = {name:sha(raw) for name,raw in files.items()}
    hashes['cell_msh.tdr'] = binding['mesh_sha256']
    verify_packet(get,lambda name:hashes[name],request=request)
    return dict(files=files,imports=imports,binding=binding,archive=archive_path,archive_sha256=archive_sha,
                mesh_sha256=binding['mesh_sha256'])


def verify_packet(get, get_hash, cfg=None, request=None):
    """Verify frozen bytes. The mutable original manifest is never reopened."""
    binding = obj(get('mesh-source-binding.json'))
    require(binding.get('schema') == SCHEMA and binding.get('origin') == 'native_pipeline'
            and binding.get('synthetic') is False and binding.get('inherited_step_indices') == [1,2]
            and binding.get('actual_step_indices') == [3,4,5,6], 'binding schema/scope differs')
    expected_proofs = {PREFIX+n for n in PROOF_MEMBERS} | {PREFIX+'manifest.json',PREFIX+'inputs.tar',PREFIX+'_collection-members.json'}
    require(set(binding.get('proofs_sha256',{})) == expected_proofs, 'inherited proof set differs')
    for name,value in binding['proofs_sha256'].items():
        require(get_hash(name) == value, 'frozen source proof changed: '+name)
    manifest = obj(get(PREFIX+'manifest.json'))
    validate_source_manifest(manifest)
    for key,name in (('source_manifest_sha256','manifest.json'),('source_inputs_archive_sha256','inputs.tar'),
                     ('source_collection_index_sha256','_collection-members.json'),('source_input_manifest_sha256','input-manifest.json')):
        require(binding.get(key) == get_hash(PREFIX+name), 'frozen source identity differs: '+key)
    require(binding.get('source_run_id') == manifest['run_id']
            and binding.get('source_archive_sha256') == manifest['results_sha256']
            and binding.get('source_remote_exit_code') == manifest['remote_exit_code']
            and binding.get('source_state') == manifest['state'], 'source manifest/binding differs')
    inputs = original_inputs(get(PREFIX+'inputs.tar'),manifest)
    index = obj(get(PREFIX+'_collection-members.json'))
    for name,raw in inputs.items():
        require(index.get(name) == dict(size=len(raw),sha256=sha(raw)), 'frozen original input/result index differs: '+name)
    for name in PROOF_MEMBERS:
        raw = get(PREFIX+name)
        require(index.get(name) == dict(size=len(raw),sha256=sha(raw)), 'original proof/index mismatch: '+name)
    require(set(binding.get('identical_inputs_sha256',{})) == set(IDENTICAL_INPUTS), 'scientific input set differs')
    for name in IDENTICAL_INPUTS:
        require(get_hash(name) == binding['identical_inputs_sha256'][name] == sha(inputs[name]), 'scientific input changed: '+name)
    require(set(binding.get('imports',{})) == set(IMPORTED_OUTPUTS), 'import set differs')
    for name,row in binding['imports'].items():
        require(row == dict(member=name,sha256=index[name]['sha256'],size_bytes=index[name]['size'])
                and get_hash(name) == row['sha256'], 'imported original output differs: '+name)
    require(binding.get('mesh_sha256') == binding['imports']['cell_msh.tdr']['sha256']
            and binding.get('mesh_size_bytes') == binding['imports']['cell_msh.tdr']['size_bytes'], 'mesh identity differs')
    prefix_get = lambda name: get(name if name in IMPORTED_OUTPUTS else PREFIX+name)
    validate_prefix(prefix_get,manifest)
    before = obj(get(PREFIX+'tdx-source-before.json'))
    require(before == dict(schema='dram-see-v4-tdx-source-identity-r1',phase='BEFORE',run_id=manifest['run_id'],
        path=manifest['remote_directory']+'/cell_msh.tdr',sha256=binding['mesh_sha256']), 'original pre-TDX mesh identity differs')
    original_spec = obj(inputs['project.json'])
    original_cfg = original_spec.get('s2_geometry',{})
    require(original_cfg.get('schema') == 'dram-see-v4-continuous-geometry-r2'
            and original_cfg.get('mode') == 'produce' and original_cfg.get('role_id') == 'B1-D3'
            and original_cfg.get('synthetic') is False and original_cfg.get('execution_enabled') is True
            and original_cfg.get('run_id') == original_cfg.get('producer_run_id') == manifest['run_id']
            and original_spec.get('native_threads') == original_spec.get('native_cores') == 1
            and manifest['steps'] == original_spec.get('steps')
            and [(s.get('tool'),s.get('args')) for s in original_spec.get('steps',[])] == list(SIX_STEPS),
            'original producer shape differs')
    original_request = obj(inputs['controlled-request.json'])
    model = obj(inputs['model.proposed.json'])
    require(original_request.get('kind') == 'dc' and original_request.get('dimension') == 3,
            'source was not a 3D DC producer')
    if request is not None:
        require(request.get('schema') == 'dram-see-v4-controlled-device-request-r4'
                and request.get('kind') == 'dc' and request.get('dimension') == 3
                and request.get('mesh_source_run') == binding['source_run_directory'], 'continuation request source differs')
        for name in ('gate_top_depth_nm','sn_junction_depth_nm','dimension','variant','mesh_policy'):
            require(request.get(name) == original_request.get(name), 'continuation cannot change '+name)
    if cfg is not None:
        require(cfg.get('mode') == 'produce_from_mesh' and cfg.get('role_id') == 'B1-D3'
                and cfg.get('producer_run_id') == cfg.get('run_id') != manifest['run_id']
                and cfg.get('mesh_source_binding_sha256') == get_hash('mesh-source-binding.json'), 'continuation config/binding differs')
        for name in ('size_id','sn_junction_depth_nm','numerical_variant','parameter_id','mesh_policy_id','mesh_policy_sha256','controlled_parameters_sha256'):
            require(cfg.get(name) == original_cfg.get(name), 'original numerical/physical identity differs: '+name)
    require(model['geometry']['gate_top_depth_nm'] == original_request['gate_top_depth_nm']
            and model['doping']['sn_junction_depth_nm'] == original_request['sn_junction_depth_nm'], 'source model/request differs')
    return binding


def verify_folder(folder, cfg, allow_deferred=False):
    folder = Path(folder)
    request = obj((folder/'controlled-request.json').read_bytes())
    binding = obj((folder/'mesh-source-binding.json').read_bytes())
    for name in ('step-001-sde-exit-code.txt','step-002-snmesh-exit-code.txt'):
        require(not (folder/name).exists(), 'inherited prefix cannot masquerade as current native exits')
    def get_hash(name):
        path = folder/name
        if allow_deferred and not path.exists() and name == 'cell_msh.tdr':
            return binding['mesh_sha256']
        return file_sha(path)
    return verify_packet(lambda name:(folder/name).read_bytes(),get_hash,cfg,request)


def validate_completed(get, get_hash, manifest, cfg, inputs_archive_raw):
    """Additional gates for a genuinely complete composite D3 source.

    This returns no success receipt. The caller still enforces the unchanged
    original geometry report, all its raw hashes and current wrapper exit.
    """
    require(manifest.get('state') == 'COLLECTED' and manifest.get('collection_verified') is True
            and manifest.get('origin') == 'native_pipeline' and manifest.get('synthetic') is False
            and type(manifest.get('remote_exit_code')) is int and manifest['remote_exit_code'] == 0
            and type(manifest.get('collection_exit_code')) is int and manifest['collection_exit_code'] == 0,
            'composite D3 has no completed original collection')
    expected_keys = {'step-003-tdx','step-004-tdx','step-005-svisual','step-006-sdevice'}
    require(set(manifest.get('tool_exit_codes',{})) == expected_keys
            and set(manifest.get('tool_evidence',{})) == expected_keys
            and all(type(v) is int and v == 0 for v in manifest['tool_exit_codes'].values())
            and manifest.get('inherited_step_indices') == [1,2]
            and manifest.get('mesh_source_binding_sha256') == get_hash('mesh-source-binding.json'),
            'composite must contain only four actual successful tail exits')
    inputs = original_inputs(inputs_archive_raw,manifest)
    for name,raw in inputs.items():
        require(get_hash(name) == sha(raw), 'completed producer original input changed: '+name)
    request = obj(get('controlled-request.json'))
    binding = verify_packet(get,get_hash,cfg,request)
    require([(s.get('tool'),s.get('args')) for s in manifest['steps']] == list(SIX_STEPS[2:]),
            'completed producer steps differ')
    identity = obj(get('process-identity.json'))
    require(identity.get('schema') == 'tcad-process-identity-r1' and identity.get('run_id') == manifest['run_id']
            and identity.get('cwd') == manifest['remote_directory'] and identity.get('script_sha256')
            == manifest['script_sha256'] == get_hash('run.sh')
            and identity == manifest.get('last_observation',{}).get('identity'), 'completed producer wrapper identity differs')
    lock = dict(line.split('=',1) for line in get('shared-lock-evidence.txt').decode().splitlines() if '=' in line)
    require(lock.get('status') == 'ACQUIRED' and lock.get('pid') == str(identity.get('pid'))
            and lock.get('fd') == '9' and lock.get('lock_path') == '/home/tcad/research-training/.solver.lock',
            'completed producer lock differs')
    for i,tool in ((3,'tdx'),(4,'tdx'),(5,'svisual'),(6,'sdevice')):
        prefix = 'step-{:03d}-{}'.format(i,tool)
        evidence = manifest['tool_evidence'][prefix]
        require(evidence == dict(step_index=i,tool=tool,raw_exit_file=prefix+'-exit-code.txt',
            process_status_file=prefix+'-process-status.txt',process_observation_file=prefix+'-process-observation.json',
            process_admission_file=prefix+'-process-admission.json',raw_process_admission_exit_file=prefix+'-process-admission-exit-code.txt'),
            'completed producer capture mapping differs')
        require(exit_value(get(evidence['raw_exit_file'])) == 0
                and exit_value(get(evidence['raw_process_admission_exit_file'])) == 0,
                'completed producer actual native/admission exit differs')
        admission = obj(get(evidence['process_admission_file']))
        observed = obj(get(evidence['process_observation_file']))
        raw_status = get(evidence['process_status_file'])
        status = dict((k.strip(),v.strip()) for k,v in
                      (line.split(':',1) for line in raw_status.decode().splitlines() if ':' in line))
        executable = ('svisual_bin/svisual_exec' if tool == 'svisual' else tool)
        name = 'svisual_exec' if tool == 'svisual' else tool
        require(admission.get('schema') == 'native-process-admission-r1' and admission.get('synthetic') is False
                and admission.get('origin') == 'native_pipeline' and admission.get('status') == 'PASSED'
                and admission.get('errors') == [] and admission.get('requested_tool') == tool
                and admission.get('actual_native_exit_is_separate') is True,
                'completed producer capture admission differs')
        require(observed.get('schema') == 'native-process-observation-r1' and observed.get('status') == 'OBSERVED'
                and observed.get('origin') == 'native_pipeline' and observed.get('synthetic') is False
                and observed.get('requested_tool') == tool and observed.get('wrapper_pid') == identity['pid']
                and observed.get('installation_root') == '/usr/synopsys/sentaurus/W-2024.09'
                and observed.get('native_executable') == '/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64/bin/'+executable
                and observed.get('status_sha256') == sha(raw_status) and observed.get('status_file') == evidence['process_status_file']
                and status.get('Name') == name and status.get('Pid') == str(observed.get('native_pid'))
                and status.get('Threads') == observed.get('observed_threads') == '1'
                and status.get('Cpus_allowed_list') == observed.get('observed_cpus_allowed_list') == admission.get('requested_cpu')
                and re.fullmatch(r'[0-9]+',status.get('Cpus_allowed_list','')) is not None,
                'completed producer raw native identity/thread/CPU differs')
        chain = observed.get('parent_chain')
        require(isinstance(chain,list) and chain and chain[0].get('pid') == observed.get('native_pid')
                and chain[0].get('start_ticks') == observed.get('native_start_ticks')
                and chain[0].get('name') == name and chain[0].get('ppid') == int(status['PPid'])
                and chain[-1].get('ppid') == identity['pid'] and chain[-1] == observed.get('root_identity'),
                'completed producer PID/start/parent chain differs')
        for position,row in enumerate(chain):
            require(type(row.get('start_ticks')) is int and row['start_ticks'] >= identity['start_ticks'],
                    'completed producer child start differs')
            if position+1 < len(chain):
                require(row.get('ppid') == chain[position+1].get('pid'), 'completed producer chain is broken')
    for name in obj(get('project.json'))['steps'][-1].get('outputs',[]):
        require(get(name), 'completed producer SDevice output missing or empty: '+name)
    return binding


def stage(folder, cfg):
    """Idempotent exact-byte staging; no skipped-tool result is manufactured."""
    folder = Path(folder)
    binding = verify_folder(folder,cfg,allow_deferred=True)
    source = Path(binding['source_run_directory'])
    require(source.is_absolute() and source.name == binding['source_run_id'] and not source.is_symlink(),
            'source staging directory differs')
    archive_path = source/'results.tar'
    # The full archive/index/prefix audit was frozen at source_package. Matching
    # the complete archive hash reuses that audit without rerunning the tools or
    # the entire semantic inspection, and never reads a mutable source manifest.
    require(file_sha(archive_path) == binding['source_archive_sha256']
            and archive_path.stat().st_size == binding['source_archive_size_bytes']
            and file_sha(source/'inputs.tar') == binding['source_inputs_archive_sha256'],
            'source archive or original inputs changed before staging')
    with tarfile.open(str(archive_path),'r:*') as archive:
        listing = members(archive)
        require(sha(raw_member(archive,listing,'_collection-members.json')) == binding['source_collection_index_sha256'],
                'original collection index changed before staging')
        for name,row in binding['imports'].items():
            path = folder/name
            if path.exists():
                require(file_sha(path) == row['sha256'], 'existing staged output changed: '+name)
                continue
            with archive.extractfile(listing[row['member']]) as stream, path.open('xb') as output:
                for block in iter(lambda:stream.read(1048576),b''):
                    output.write(block)
            require(path.stat().st_size == row['size_bytes'] and file_sha(path) == row['sha256'], 'staged output mismatch: '+name)
    require(file_sha(archive_path) == binding['source_archive_sha256'], 'source archive changed during staging')
    verify_folder(folder,cfg)
    return cfg
