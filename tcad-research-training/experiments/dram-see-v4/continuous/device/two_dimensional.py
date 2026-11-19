"""Versioned 2D control provenance and width contract; data only, Python 3.6.

The original complete D2 archive is preserved, never relabelled as D3.
No native launcher, source injection, scientific success flag or quota lives here.
"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

BRANCH = 'dram-see-v4-2d-control-r1'
SCHEMA = 'dram-see-v4-d2-source-binding-r1'
WIDTH_SCHEMA = 'dram-see-v4-2d-equivalence-r1'
RUNTIME_FILES = ('two_dimensional.py',)
PREFIX = 'd2-producer-bindings/'
TOOLS = ('sde', 'snmesh', 'tdx', 'tdx', 'svisual', 'sdevice')
SHARED_INPUTS = ('physics.par', 'physics-manifest.json', 'Silicon.par', 'Oxide.par',
                 'geometry-contract.json', 'model.proposed.json')
DC_OUTPUTS = ('idvg_low_dc_des.plt', 'idvg_high_dc_des.plt', 'dc_final_des.tdr', 'dc_des.log')
A0_OUTPUTS = ('circuit.plt', 'access_device.plt', 'initial_access_des.tdr', 'final_access_des.tdr', 'transient_des.log')


def require(ok, message):
    if not ok:
        raise ValueError('2D control: ' + message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def stream_sha(stream):
    value = hashlib.sha256()
    for block in iter(lambda: stream.read(1048576), b''):
        value.update(block)
    return value.hexdigest()


def file_sha(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'missing or linked file ' + str(path))
    with path.open('rb') as stream:
        return stream_sha(stream)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def obj(raw):
    result = json.loads(raw.decode('utf-8'))
    require(isinstance(result, dict), 'expected JSON object')
    return result


def members(archive):
    result = {}
    for row in archive.getmembers():
        name = row.name
        while name.startswith('./'):
            name = name[2:]
        if name in ('', '.') and row.isdir():
            continue
        p = PurePosixPath(name)
        require(not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name
                and name not in result and (row.isfile() or row.isdir()), 'unsafe or duplicate archive member')
        result[p.as_posix()] = row
    return result


class ArchiveReader:
    def __init__(self, archive):
        self.archive, self.members = archive, members(archive)

    def stream(self, name):
        require(name in self.members and self.members[name].isfile(), 'missing original member ' + name)
        return self.archive.extractfile(self.members[name])

    def read(self, name):
        with self.stream(name) as stream:
            return stream.read()

    def digest(self, name):
        with self.stream(name) as stream:
            return stream_sha(stream)

    def size(self, name):
        require(name in self.members and self.members[name].isfile(), 'missing original member ' + name)
        return self.members[name].size

    def exists(self, name):
        return name in self.members and self.members[name].isfile()


class FolderReader:
    def __init__(self, folder):
        self.folder = Path(folder)

    def path(self, name):
        p = PurePosixPath(name)
        require(not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name,
                'unsafe frozen path')
        target = self.folder.joinpath(*p.parts)
        require(not target.is_symlink() and not target.parent.is_symlink(), 'linked frozen input')
        return target

    def stream(self, name): return self.path(name).open('rb')
    def read(self, name): return self.path(name).read_bytes()
    def digest(self, name): return file_sha(self.path(name))
    def size(self, name): return self.path(name).stat().st_size
    def exists(self, name): return self.path(name).is_file()


def _exit(raw):
    require(re.fullmatch(rb'[0-9]+\s*', raw) is not None, 'missing actual exit')
    return int(raw)


def _capture(reader, manifest, identity, index, tool):
    key = 'step-{:03d}-{}'.format(index, tool)
    mapping = dict(step_index=index, tool=tool, raw_exit_file=key+'-exit-code.txt',
        process_status_file=key+'-process-status.txt', process_observation_file=key+'-process-observation.json',
        process_admission_file=key+'-process-admission.json',
        raw_process_admission_exit_file=key+'-process-admission-exit-code.txt')
    require(manifest['tool_evidence'].get(key) == mapping, 'original capture mapping differs')
    require(_exit(reader.read(mapping['raw_exit_file'])) == 0
            and _exit(reader.read(mapping['raw_process_admission_exit_file'])) == 0, 'nonzero original tool/admission')
    admission = obj(reader.read(mapping['process_admission_file']))
    observed = obj(reader.read(mapping['process_observation_file']))
    raw = reader.read(mapping['process_status_file'])
    status = dict((k.strip(), v.strip()) for k, v in
                  (line.split(':', 1) for line in raw.decode().splitlines() if ':' in line))
    native = 'svisual_exec' if tool == 'svisual' else tool
    executable = 'svisual_bin/'+native if tool == 'svisual' else native
    require(admission.get('schema') == 'native-process-admission-r1' and admission.get('status') == 'PASSED'
            and admission.get('errors') == [] and admission.get('origin') == 'native_pipeline'
            and admission.get('synthetic') is False and admission.get('requested_tool') == tool
            and admission.get('actual_native_exit_is_separate') is True, 'original admission differs')
    require(observed.get('schema') == 'native-process-observation-r1' and observed.get('status') == 'OBSERVED'
            and observed.get('origin') == 'native_pipeline' and observed.get('synthetic') is False
            and observed.get('requested_tool') == tool and observed.get('wrapper_pid') == identity['pid']
            and observed.get('installation_root') == '/usr/synopsys/sentaurus/W-2024.09'
            and observed.get('native_executable') == '/usr/synopsys/sentaurus/W-2024.09/tcad/W-2024.09/linux64/bin/'+executable
            and observed.get('status_file') == mapping['process_status_file'] and observed.get('status_sha256') == sha(raw)
            and status.get('Name') == native and status.get('Pid') == str(observed.get('native_pid'))
            and status.get('Threads') == observed.get('observed_threads') == '1'
            and status.get('Cpus_allowed_list') == observed.get('observed_cpus_allowed_list') == admission.get('requested_cpu')
            and re.fullmatch(r'[0-9]+', status.get('Cpus_allowed_list', '')) is not None, 'original native identity/CPU/thread differs')
    chain = observed.get('parent_chain', [])
    require(chain and chain[0] == observed.get('root_identity') and chain[0].get('ppid') == identity['pid']
            and chain[0].get('pid') == observed.get('root_child_pid') and chain[-1].get('pid') == observed.get('native_pid')
            and chain[-1].get('start_ticks') == observed.get('native_start_ticks')
            and chain[-1].get('ppid') == int(status['PPid']) and chain[-1].get('name') == native
            and len({r['pid'] for r in chain}) == len(chain), 'original root-to-native chain differs')
    for i, row in enumerate(chain):
        require(type(row.get('pid')) is int and row['pid'] > 1 and type(row.get('start_ticks')) is int
                and row['start_ticks'] >= identity['start_ticks'], 'original process identity differs')
        if i:
            require(row['ppid'] == chain[i-1]['pid'] and row['start_ticks'] >= chain[i-1]['start_ticks'],
                    'broken original parent chain')


def _validate_source(reader, manifest, inputs):
    require(manifest.get('schema') == 'tcad-native-run-r2' and manifest.get('state') == 'COLLECTED'
            and manifest.get('collection_verified') is True and manifest.get('origin') == 'native_pipeline'
            and manifest.get('synthetic') is False, 'D2 source is not an original completed native run')
    for key in ('remote_exit_code', 'collection_exit_code'):
        require(type(manifest.get(key)) is int and manifest[key] == 0, 'D2 source exit nonzero/unknown')
    require(type(manifest.get('ssh_exit_code')) is int, 'original SSH exit missing')
    expected = {'step-{:03d}-{}'.format(i, tool): 0 for i, tool in enumerate(TOOLS, 1)}
    require(manifest.get('tool_exit_codes') == expected and all(type(v) is int for v in manifest['tool_exit_codes'].values())
            and set(manifest.get('tool_evidence', {})) == set(expected), 'D2 source six actual exits differ')
    inventory = obj(reader.read('_collection-members.json'))
    require(set(inventory) == {n for n, v in reader.members.items() if v.isfile()}-{'_collection-members.json'},
            'original complete collection inventory differs')
    for n, row in inventory.items():
        require(row == dict(size=reader.size(n), sha256=reader.digest(n)), 'original collection bytes differ: '+n)
    require(set(manifest.get('input_sha256', {})) == {n for n, v in inputs.members.items() if v.isfile()},
            'original input archive inventory differs')
    for n, h in manifest['input_sha256'].items():
        require(inputs.digest(n) == h == reader.digest(n), 'original input bytes differ: '+n)
    spec = obj(inputs.read('project.json')); cfg = spec.get('s2_geometry', {})
    require(spec.get('steps') == manifest.get('steps') and [s.get('tool') for s in spec['steps']] == list(TOOLS)
            and spec.get('native_threads') == spec.get('native_cores') == 1
            and cfg.get('schema') == 'dram-see-v4-continuous-geometry-r2' and cfg.get('mode') == 'produce'
            and cfg.get('role_id') == 'B1-D2' and cfg.get('synthetic') is False
            and cfg.get('run_id') == cfg.get('producer_run_id') == manifest['run_id'], 'D2 source project identity differs')
    identity = obj(reader.read('process-identity.json'))
    require(identity.get('schema') == 'tcad-process-identity-r1' and identity.get('run_id') == manifest['run_id']
            and identity.get('cwd') == manifest.get('remote_directory')
            and identity.get('script_sha256') == manifest.get('script_sha256') == reader.digest('run.sh')
            and identity == manifest.get('last_observation', {}).get('identity')
            and type(identity.get('pid')) is int and identity['pid'] > 1 and type(identity.get('start_ticks')) is int
            and identity['start_ticks'] > 0 and re.fullmatch(r'[a-f0-9-]{36}', identity.get('boot_id', '')) is not None,
            'original wrapper identity differs')
    lock = dict(line.split('=', 1) for line in reader.read('shared-lock-evidence.txt').decode().splitlines() if '=' in line)
    require(lock.get('status') == 'ACQUIRED' and lock.get('pid') == str(identity['pid']) and lock.get('fd') == '9'
            and lock.get('lock_path') == '/home/tcad/research-training/.solver.lock', 'original shared lock differs')
    for i, tool in enumerate(TOOLS, 1):
        _capture(reader, manifest, identity, i, tool)
    require(_exit(reader.read('exit-code.txt')) == 0 and all(reader.size(n) > 0 for n in DC_OUTPUTS),
            'D2 DC completion/output missing')
    require(b'Sentaurus Device simulation finished' in reader.read('dc_des.log'), 'D2 DC finish marker missing')
    report = obj(reader.read('geometry-validation.json')); plan = obj(reader.read('measurement-plan.json'))
    geometry = obj(reader.read('geometry-contract.json')); context = obj(reader.read('observation-context.json'))
    model = obj(reader.read('model.proposed.json'))
    require(geometry.get('dimension') == plan.get('dimension') == context.get('dimension') == 2
            and report.get('role_id') == plan.get('role_id') == context.get('role_id') == 'B1-D2'
            and report.get('producer_run_id') == context.get('producer_run_id') == manifest['run_id']
            and report.get('origin') == 'native_pipeline' and report.get('synthetic') is False
            and report.get('passed') is True and report.get('native_qualified') is False
            and all(report.get('checks', {}).get(k) is True and report.get('numeric_checks', {}).get(k) is True
                    for k in ('materials', 'contacts', 'doping', 'units'))
            and report.get('comparisons') and all(r.get('passed') is True for r in report['comparisons']),
            'original actual 2D geometry report differs')
    require(report.get('plan_sha256') == reader.digest('measurement-plan.json')
            and report.get('geometry_contract_sha256') == reader.digest('geometry-contract.json')
            and report.get('mesh_sha256') == context.get('mesh_sha256') == reader.digest('cell_msh.tdr'),
            'original 2D mesh/geometry identity differs')
    for n, h in report.get('evidence_sha256', {}).items():
        require(reader.digest(n) == h, 'original geometry evidence differs: '+n)
    require(model['geometry']['gate_top_depth_nm'] == 80 and model['geometry']['active_width_nm'] == 20
            and model['doping']['sn_junction_depth_nm'] == 87
            and re.findall(r'AreaFactor\s*=\s*([^\s}]+)', reader.read('device.cmd').decode()) == ['0.02'],
            'first 2D control only supports original gate80/SN87/20nm D2')
    return report, cfg


def dimensional_contract(binding):
    return dict(schema=WIDTH_SCHEMA, branch_id=BRANCH, native_dimension=2, physical_dimension=2,
        effective_width_nm=20, effective_width_um=.02, effective_width_cm=2e-6,
        native_reference_width_um=1, area_factor=.02, native_to_physical_axes=dict(X='x', Y='z', Z='omitted_y'),
        native_third_coordinate=0, out_of_plane_axis='y', native_coordinate_unit='um',
        port_current_already_width_scaled=True, explicit_capacitance_rescale=False, Cstore_fF=20, Cbl_fF=200,
        native_area_integral_unit='um^2', area_to_cm2_factor=1e-8,
        area_integral_to_effective_volume_cm3_factor=2e-14,
        source_dimension=2, producer_run_id=binding['producer_run_id'], mesh_sha256=binding['mesh_sha256'],
        geometry_contract_sha256=binding['shared_input_sha256']['geometry-contract.json'],
        physics_manifest_sha256=binding['shared_input_sha256']['physics-manifest.json'],
        scope='Central x-z section with uniform effective y width; not a completed 3D result',
        source_projection_qualified=False, native_A0_functionality_qualified=False)


def source_bundle(project, cfg, bridge, execution=None):
    source = Path(cfg.get('source_run_directory', ''))
    require(source.is_absolute() and source.is_dir() and not source.is_symlink()
            and source.name == cfg.get('producer_run_id') and 'UNIT_FIXTURE_NOT_NATIVE' not in str(source)
            and not (source/'SYNTHETIC_NOT_NATIVE').exists(), 'actual original D2 directory required')
    manifest_raw = (source/'manifest.json').read_bytes(); manifest = obj(manifest_raw)
    archive_sha, inputs_sha = file_sha(source/'results.tar'), file_sha(source/'inputs.tar')
    require(manifest.get('results_sha256') == archive_sha and manifest.get('inputs_archive_sha256') == inputs_sha,
            'original D2 receipt/archive mismatch')
    with tarfile.open(str(source/'results.tar'), 'r:*') as archive, tarfile.open(str(source/'inputs.tar'), 'r:*') as inp:
        reader = ArchiveReader(archive); report, source_cfg = _validate_source(reader, manifest, ArchiveReader(inp))
        producer_inputs = {n: reader.read(n) for n in SHARED_INPUTS}
        binding = dict(schema=SCHEMA, branch_id=BRANCH, source_dimension=2, producer_role_id='B1-D2',
            producer_run_id=source.name, source_manifest_sha256=sha(manifest_raw), source_archive_sha256=archive_sha,
            source_inputs_archive_sha256=inputs_sha, source_collection_index_sha256=reader.digest('_collection-members.json'),
            geometry_report_member='geometry-validation.json', geometry_validation_sha256=reader.digest('geometry-validation.json'),
            mesh_sha256=reader.digest('cell_msh.tdr'), mesh_log_sha256=reader.digest('cell_msh.log'),
            shared_input_sha256={n: sha(v) for n, v in producer_inputs.items()},
            actual_original_tool_exit_codes=manifest['tool_exit_codes'], source_dc_execution_completed=True,
            source_dc_calibrated=False, source_A0_functionality_qualified=False,
            verifier_file='two_dimensional.py', verifier_sha256=file_sha(__file__),
            original_files={PREFIX+'manifest.json':dict(sha256=sha(manifest_raw), size_bytes=len(manifest_raw)),
                PREFIX+'results.tar':dict(sha256=archive_sha, size_bytes=(source/'results.tar').stat().st_size),
                PREFIX+'inputs.tar':dict(sha256=inputs_sha, size_bytes=(source/'inputs.tar').stat().st_size)})
        generated = {'d2-source-binding.json': encoded(binding)}
        exports = {'cell_msh.tdr': binding['mesh_sha256'], 'cell_msh.log': binding['mesh_log_sha256']}
        exports.update({n: r['sha256'] for n, r in binding['original_files'].items()})
        exports.update({n: sha(v) for n, v in generated.items()})
    for n, actual in (('source_manifest_sha256', sha(manifest_raw)), ('source_archive_sha256', archive_sha),
                      ('mesh_sha256', binding['mesh_sha256']), ('geometry_validation_sha256', binding['geometry_validation_sha256']),
                      ('d2_source_binding_sha256', sha(generated['d2-source-binding.json']))):
        if execution is not None or n in cfg:
            require(cfg.get(n) == actual, '2D producer binding mismatch: '+n)
    for n, raw in producer_inputs.items():
        current = Path(project)/n
        if current.exists():
            require(file_sha(current) == sha(raw), '2D physics/model/geometry changed: '+n)
    return dict(archive=source/'results.tar', archive_sha256=archive_sha, manifest_sha256=sha(manifest_raw),
        mesh_sha256=binding['mesh_sha256'], geometry_validation_sha256=binding['geometry_validation_sha256'],
        producer_inputs=producer_inputs, physics_sha256={n: sha(producer_inputs[n]) for n in SHARED_INPUTS[:4]},
        producer_cfg=source_cfg, exports=exports, generated_files=generated,
        external_files={n:dict(path=str(source/n.split('/')[-1]), sha256=row['sha256']) for n, row in binding['original_files'].items()},
        d2_binding=binding, d2_source_binding_sha256=sha(generated['d2-source-binding.json']))


def verify_frozen(reader, cfg):
    binding_raw = reader.read('d2-source-binding.json'); binding = obj(binding_raw)
    require(binding.get('schema') == SCHEMA and binding.get('branch_id') == BRANCH and binding.get('source_dimension') == 2
            and cfg.get('dimension_branch') == BRANCH and cfg.get('source_dimension') == 2
            and cfg.get('producer_run_id') == binding.get('producer_run_id')
            and cfg.get('d2_source_binding_sha256') == sha(binding_raw), 'frozen 2D producer identity differs')
    require(binding.get('verifier_file') == 'two_dimensional.py'
            and binding.get('verifier_sha256') == reader.digest('two_dimensional.py') == file_sha(__file__),
            'frozen 2D verifier version differs; explicit version support required')
    for n, row in binding['original_files'].items():
        require(reader.digest(n) == row['sha256'] and reader.size(n) == row['size_bytes'], 'frozen D2 original differs: '+n)
    require(set(binding['original_files']) == {PREFIX+n for n in ('manifest.json', 'results.tar', 'inputs.tar')},
            'frozen D2 proof inventory differs')
    manifest = obj(reader.read(PREFIX+'manifest.json'))
    require(binding.get('actual_original_tool_exit_codes') == manifest.get('tool_exit_codes')
            and binding.get('producer_role_id') == 'B1-D2' and binding.get('source_dc_execution_completed') is True
            and binding.get('source_dc_calibrated') is False and binding.get('source_A0_functionality_qualified') is False,
            '2D source completion must not imply calibration or A0 qualification')
    require(reader.digest(PREFIX+'manifest.json') == cfg.get('source_manifest_sha256') == binding['source_manifest_sha256']
            and reader.digest(PREFIX+'results.tar') == cfg.get('source_archive_sha256') == binding['source_archive_sha256'] == manifest['results_sha256']
            and reader.digest(PREFIX+'inputs.tar') == binding['source_inputs_archive_sha256'] == manifest['inputs_archive_sha256'],
            'frozen D2 receipt/archive identity differs')
    with reader.stream(PREFIX+'results.tar') as a, reader.stream(PREFIX+'inputs.tar') as i:
        with tarfile.open(fileobj=a, mode='r:*') as archive, tarfile.open(fileobj=i, mode='r:*') as inp:
            original = ArchiveReader(archive)
            report, source_cfg = _validate_source(original, manifest, ArchiveReader(inp))
            require(binding['source_collection_index_sha256'] == original.digest('_collection-members.json')
                    and binding['geometry_report_member'] == 'geometry-validation.json'
                    and binding['geometry_validation_sha256'] == cfg.get('geometry_validation_sha256') == original.digest('geometry-validation.json')
                    and binding['mesh_sha256'] == cfg.get('mesh_sha256') == original.digest('cell_msh.tdr') == reader.digest('cell_msh.tdr')
                    and binding['mesh_log_sha256'] == original.digest('cell_msh.log') == reader.digest('cell_msh.log'), 'frozen 2D mesh/report differs')
            require(set(binding['shared_input_sha256']) == set(SHARED_INPUTS), 'frozen 2D shared input set differs')
            for n, h in binding['shared_input_sha256'].items():
                require(h == original.digest(n) == reader.digest(n), 'frozen 2D shared input changed: '+n)
    width = obj(reader.read('dimensional-contract.json'))
    require(width == dimensional_contract(binding) and reader.digest('dimensional-contract.json') == cfg.get('dimensional_contract_sha256')
            and cfg.get('effective_width_nm') == 20 and cfg.get('area_factor') == .02, '2D effective width/unit binding differs')
    return dict(binding=binding, report=report, source_cfg=source_cfg, dimensional_contract=width)


def admit(project, spec, runner_sha, bridge):
    project = Path(project); cfg = spec['s2_geometry']
    require(cfg.get('schema') == bridge.GEOMETRY_SCHEMA and cfg.get('mode') == 'reuse'
            and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
            and spec.get('execution_enabled') is True and cfg.get('dimension_branch') == BRANCH,
            'explicit native 2D reuse context required')
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve()) and not (project/'SYNTHETIC_NOT_NATIVE').exists(),
            'synthetic input cannot be submitted')
    request = obj((project/'controlled-request.json').read_bytes())
    contract_path = Path(__file__).with_name('case_contract.py')
    contract_spec = importlib.util.spec_from_file_location('two_dimensional_case_contract', str(contract_path))
    case_contract = importlib.util.module_from_spec(contract_spec)
    contract_spec.loader.exec_module(case_contract)
    request = case_contract.validate(request)
    require(request['schema'] == case_contract.SCHEMA_2D and cfg.get('role_id') == spec.get('role') == case_contract.role_id(request)
            and cfg.get('producer_run_id') != cfg.get('run_id') and cfg.get('producer_run_id') == Path(request['d2_source_run']).name
            and spec.get('native_threads') == spec.get('native_cores') == 1
            and spec.get('steps') == [dict(tool='sdevice', args=['device.cmd'], outputs=list(A0_OUTPUTS))], '2D role/steps differ')
    bridge.geometry_context(project, cfg, runner_sha)
    hashes = bridge.geometry_input_hashes(project)
    required = set(SHARED_INPUTS)|set(RUNTIME_FILES)|set(PREFIX+n for n in ('manifest.json','results.tar','inputs.tar'))|{
        'project.json','geometry_bridge.py','mesh_resource_guard.py','case_contract.py','resource-policy.json','task-authorization.json',
        'controlled-request.json','device.cmd','cell_msh.tdr','cell_msh.log','d2-source-binding.json','dimensional-contract.json',
        'source-spec.json','source-contract.json','parameter-binding.json','numerical-method.json','role-contract.json','initialization-contract.json'}
    require(required <= set(hashes), 'mandatory 2D input missing')
    for n, h in hashes.items():
        require(file_sha(bridge.geometry_path(project, n)) == h, 'frozen 2D input changed: '+n)
    verified = verify_frozen(FolderReader(project), cfg)
    device = (project/'device.cmd').read_text(encoding='utf-8')
    require(re.findall(r'AreaFactor\s*=\s*([^\s}]+)', device) == ['0.02']
            and device.count('Capacitor_pset cstore (sn plate) {capacitance=2e-14}') == 1
            and device.count('Capacitor_pset cbl (bl 0) {capacitance=2e-13}') == 1
            and re.findall(r'\bParameter\s*=\s*"([^"]+)"', device) == ['physics.par']
            and 'Band2Band(Model=Hurkx DensityCorrection=None)' in device and 'NonlocalPath' not in device
            and re.search(r'\bHeavyIon\s*\(', device) is None and re.search(r'\bLoad\s*\(', device) is None,
            '2D width/capacitance/physics/source contract differs')
    require(device.count('Set(sn=0.6)') == device.count('Unset(sn)') == 1
            and device.index('Set(sn=0.6)') < device.index('Unset(sn)') < device.index(' Transient(')
            and re.findall(r'(?<![A-Za-z])Set\(sn=([^)]*)\)', device) == ['0.6']
            and 'pwl=(0 -0.5 2e-9 -0.5 2.1e-9 1.8' in device,
            '2D shared neutral initialization/release differs')
    vwrite = format(1.2*request['stored_bit'], '.17g')
    require('Vsource_pset vdrive (drive 0) {pwl=(0 '+vwrite+' 6.1e-9 '+vwrite+' 6.2e-9 0.6 25e-9 0.6)' in device,
            '2D bit must be selected by the real write driver')
    require('Transient=BE Method=Blocked SubMethod=ParDiSo' in device
            and 'NumberOfThreads=1 NumberOfAssemblyThreads=1 NumberOfSolverThreads=1' in device
            and 'RelErrControl Digits=5 ErrRef(electron)=1e7 ErrRef(hole)=1e7' in device
            and 'Iterations=30 Notdamped=100 ExitOnFailure' in device, '2D numerical controls differ')
    source = obj((project/'source-spec.json').read_bytes())
    require(source.get('schema') == 'dram-see-v4-2d-control-source-spec-r1' and source.get('role') == 'CONTROL'
            and source.get('source_configured') is False and source.get('stored_bit') == request['stored_bit']
            and source.get('dimension') == 2 and source.get('physics_manifest_sha256') == verified['binding']['shared_input_sha256']['physics-manifest.json'],
            '2D structural no-source identity differs')
    return cfg
