"""Explicit development-only 2D A0/DC adapter. Python 3.6, no native launcher.

Old c09/O97 bindings stay immutable. A main/h2/dt2 input relationship is not a
native result, mesh accuracy result, functional qualification, or training row.
"""
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import tarfile

BRANCH = 'dram-see-v4-parameterized-operating-2d-r1'
DIMENSION_BRANCH = 'dram-see-v4-parameterized-d2-source-r1'
REQUEST_SCHEMA = 'dram-see-v4-controlled-device-request-r13'
SOURCE_BINDING_SCHEMA = 'dram-see-v4-parameterized-d2-source-binding-r1'
RELATION_SCHEMA = 'dram-see-v4-2d-numerical-relation-r1'
O_SHA = '97a5ea8cf6fb64bdfe345adaf09f4aa8f222b8b443d84819fd64c0f447e937a5'
D2_SHA = 'c09b52ad56fcdf7e22dfb70ce750b04fd9fa383e1bda8a68ac9121ed768055cd'
CLOCK_SHA = 'bf5d9a8c5520eda054ecadd14fa4fc06f2f3b7296f16483e5ded02ff20ab4387'
METRICS_SHA = '0083e300fd1242d77616597f7a47e075386fff36d991070dd662b414e6f97bc2'
LEGACY_SHA = '14681b6fae30bce49a8b1063b3f8abd7e790e51c6afe58f74da094cd574b2d6e'
LEGACY_D2_RUN = '20261017T051217Z-v4-continuous-b1-d2-r8'
LEGACY_D2_FILES = {
    'manifest.json': '383689b64dbec91ecbb9d33d145ae5897551b02665f7d9df633bbe94175f3f28',
    'results.tar': '0623ea193df1821314e57afb17223a187f9ea5659d67c35fe6e92cd2736b4532',
    'inputs.tar': 'd17517649a835cbec3a395963acfbac73e6ebc8622fcb9cf7994f0d237c9ae1e'}
RUNTIME_FILES = ('parameterized_operating_2d.py', 'two_dimensional.py',
                 'operating_transient_2d.py', 'native_transient_clock.py',
                 'operating_metrics_2d.py', 'legacy-circuit-metrics.py')
COMMON_REQUEST = {'schema', 'kind', 'dimension', 'gate_top_depth_nm',
                  'sn_junction_depth_nm', 'effective_width_nm', 'variant', 'base_d2_source_run'}
A0_REQUEST = COMMON_REQUEST | {'stored_bit', 'source_case', 'd2_source_run',
    'a0_template_project', 'operation_timing_file', 'operation_timing_sha256',
    'base_operation_timing_file', 'base_operation_timing_sha256', 'operation_evidence_files'}
FROZEN_RESULT_KEYS = {'binding', 'report', 'source_cfg', 'dimensional_contract',
                     'operation_timing', 'operating_binding', 'source_spec', 'role_contract', 'numerical_relation'}
_MODULES = {}


def require(ok, message):
    if not ok:
        raise ValueError('Parameterized 2D: ' + message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def obj(raw):
    value = json.loads(raw.decode('utf-8'))
    require(isinstance(value, dict), 'JSON object required')
    return value


def name_of(value):
    return re.split(r'[\\/]', value.rstrip('/\\'))[-1]


def local_module(name, expected=None):
    path = Path(__file__).with_name(name)
    if name == 'operating_metrics_2d.py' and not path.exists():
        path = path.parent.parent/'data'/name
    require(path.is_file() and not path.is_symlink(), 'missing fixed local module ' + name)
    raw = path.read_bytes()
    if expected is not None:
        require(sha(raw) == expected, 'fixed implementation changed: ' + name)
    key = (str(path), sha(raw))
    if key not in _MODULES:
        spec = importlib.util.spec_from_file_location('_parameterized_2d_' + name.replace('.', '_'), str(path))
        module = importlib.util.module_from_spec(spec)
        if name == 'prepare_case.py' and str(path.parent) not in sys.path:
            sys.path.insert(0, str(path.parent))
            try:
                spec.loader.exec_module(module)
            finally:
                sys.path.remove(str(path.parent))
        else:
            spec.loader.exec_module(module)
        _MODULES[key] = module
    return _MODULES[key]


def d2_api():
    return local_module('two_dimensional.py', D2_SHA)


def operation_api():
    return local_module('operating_transient_2d.py', O_SHA)


def validate_request(request):
    require(isinstance(request, dict) and request.get('schema') == REQUEST_SCHEMA, 'explicit r13 request required')
    require(request.get('kind') in ('dc', 'transient'), 'DC or A0 kind required')
    dc = request['kind'] == 'dc'
    require(set(request) == (COMMON_REQUEST if dc else A0_REQUEST), 'request fields differ')
    require(type(request['gate_top_depth_nm']) is int and request['gate_top_depth_nm'] in (70, 80),
            'only the current 70/80nm development geometry is supported')
    for field, value in (('dimension', 2), ('sn_junction_depth_nm', 87), ('effective_width_nm', 20)):
        require(type(request[field]) is int and request[field] == value, 'fixed physical condition differs: ' + field)
    require(request['variant'] in (('main', 'mesh') if dc else ('main', 'h2', 'dt2')), 'unknown numerical variant')
    paths = ['base_d2_source_run']
    if not dc:
        require(request['source_case'] == 'A0' and type(request['stored_bit']) is int and request['stored_bit'] in (0, 1),
                'source-free A0 bit required')
        paths += ['d2_source_run', 'a0_template_project', 'operation_timing_file', 'base_operation_timing_file']
        for key in ('operation_timing_sha256', 'base_operation_timing_sha256'):
            require(operation_api().digest_ok(request[key]), 'explicit timing SHA required: ' + key)
        refs = request['operation_evidence_files']
        require(isinstance(refs, dict) and all(operation_api().plain_name(k) and isinstance(v, str) and v.strip()
                                             for k, v in refs.items()), 'selection evidence file mapping differs')
        require(name_of(request['a0_template_project']) == operation_api().TEMPLATE_RUN,
                'only the original small A0 electrical template is supported')
    for key in paths:
        require(isinstance(request[key], str) and request[key].strip(), 'explicit source/path required: ' + key)
    return obj(encoded(request))


def role_id(request):
    r = validate_request(request)
    return 'B1-D2' if r['kind'] == 'dc' else 'B2D-A0-parameterized-r1-{}-b{}'.format(r['variant'], r['stored_bit'])


def timing_relation(base_raw, selected_raw, variant):
    """A relationship between explicit physical inputs, never actual accepted dt."""
    O = operation_api()
    base, selected = O.validate_timing(obj(base_raw)), O.validate_timing(obj(selected_raw))
    require(variant in ('main', 'h2', 'dt2'), 'unknown timing relation')
    if variant in ('main', 'h2'):
        require(selected_raw == base_raw, 'main/h2 must preserve exact base physical timing and steps')
    else:
        expected = copy.deepcopy(base)
        expected['timing_id'] = selected['timing_id']
        require(selected['timing_id'] != base['timing_id'], 'dt2 requires an explicit distinct timing identity')
        for row in expected['segments']:
            row['initial_step_s'] *= .5
            row['max_step_s'] *= .5
        require(selected == expected, 'dt2 changes more than timing identity and InitialStep/MaxStep halves')
    return dict(schema=RELATION_SCHEMA, variant=variant, base_operation_timing_sha256=sha(base_raw),
        operation_timing_sha256=sha(selected_raw), physical_time_axis_unchanged=True,
        physical_voltage_levels_unchanged=True, initial_and_max_step_scale=.5 if variant == 'dt2' else 1.,
        minimum_step_and_solver_controls_unchanged=True, actual_accepted_steps_verified=False,
        actual_mesh_or_time_convergence_qualified=False)


def render(template_deck, bit, selected_timing_raw, base_timing_raw, variant):
    timing_relation(base_timing_raw, selected_timing_raw, variant)
    return operation_api().render(template_deck, bit, obj(selected_timing_raw))


def mesh_recipe(raw):
    """Read every actual declared refinement length, not mesh node estimates."""
    text = raw.decode('utf-8')
    sizes = {}
    pattern = r'\(sdedr:define-refinement-size\s+"([^"]+)"\s+([^()]+)\)'
    for match in re.finditer(pattern, text):
        name, fields = match.groups()
        values = [float(v) for v in fields.split()]
        require(name not in sizes and len(values) == 4 and all(math.isfinite(v) and v > 0 for v in values),
                '2D refinement size is duplicate/nonfinite/incomplete')
        sizes[name] = values
    require(set(sizes) == {'Mesh.All', 'Mesh.Junction', 'Mesh.GateOxide', 'Mesh.AlphaTrack',
                           'Mesh.Interfaces', 'Mesh.ActiveDoping'}, 'original complete refinement inventory differs')
    function = r'\(sdedr:define-refinement-function\s+"Mesh.Interfaces"\s+"MaxLenInt"\s+"Silicon"\s+"SiO2"\s+([^\s()]+)\s+([^\s()]+)\s+"DoubleSide"\)'
    matches = list(re.finditer(function, text))
    require(len(matches) == 1 and text.count('(sdedr:define-refinement-function') == 1,
            'original interface refinement inventory differs')
    length, factor = map(float, matches[0].groups())
    require(math.isfinite(length) and length > 0 and factor == 1.5, 'interface refinement controls differ')
    # Every window and placement remains literal input evidence. Only lengths
    # are removed from this comparison; locations/physical sizes are not scaled.
    normalized = re.sub(pattern, lambda m: '(sdedr:define-refinement-size "' + m[1] + '" LENGTHS)', text)
    normalized = re.sub(function, '(sdedr:define-refinement-function "Mesh.Interfaces" "MaxLenInt" "Silicon" "SiO2" LENGTH 1.5 "DoubleSide")', normalized)
    lines = [line.split(';', 1)[0].strip() for line in normalized.splitlines()]
    refinement_context = [re.sub(r'\s+', ' ', line) for line in lines if line and
                          ('(sdedr:define-refinement' in line or '(sdedr:define-refeval-window "Window.' in line)]
    canonical = '\n'.join(re.sub(r'\s+', ' ', line) for line in lines if line)
    return dict(sizes_um=sizes, interface_first_step_um=length, interface_growth_factor=factor,
                refinement_context=refinement_context, non_refinement_sde_sha256=sha(canonical.encode('utf-8')))


def mesh_relation(base, selected, scale, same_physical_sde=False):
    a, b = mesh_recipe(base), mesh_recipe(selected)
    require(scale in (1., .5), 'only declared main/h2 input scale is supported')
    require(b['sizes_um'] == {k: [v * scale for v in values] for k, values in a['sizes_um'].items()}
            and b['interface_first_step_um'] == a['interface_first_step_um'] * scale
            and b['refinement_context'] == a['refinement_context'], 'mesh lengths/window/placement relation differs')
    if same_physical_sde:
        require(a['non_refinement_sde_sha256'] == b['non_refinement_sde_sha256'],
                'h2 changed a physical, doping, contact or observation SDE command')
    return dict(base_recipe=a, selected_recipe=b, declared_length_scale=scale,
                window_locations_unchanged=True, actual_element_lengths_or_convergence_verified=False)


def _validate_source(reader, manifest, inputs, manifest_sha):
    """c09 original-run checks retained; only fixed-80 policy is versioned here."""
    D = d2_api()
    require(manifest.get('schema') == 'tcad-native-run-r2' and manifest.get('state') == 'COLLECTED'
            and manifest.get('collection_verified') is True and manifest.get('origin') == 'native_pipeline'
            and manifest.get('synthetic') is False, 'original completed native D2 required')
    for key in ('remote_exit_code', 'collection_exit_code'):
        require(type(manifest.get(key)) is int and manifest[key] == 0, 'D2 real exit nonzero/unknown: ' + key)
    require(type(manifest.get('ssh_exit_code')) is int, 'D2 original SSH exit absent')
    expected = {'step-{:03d}-{}'.format(i, tool): 0 for i, tool in enumerate(D.TOOLS, 1)}
    require(manifest.get('tool_exit_codes') == expected and all(type(v) is int for v in manifest['tool_exit_codes'].values())
            and set(manifest.get('tool_evidence', {})) == set(expected), 'six actual native exits/evidence differ')
    inventory = obj(reader.read('_collection-members.json'))
    require(set(inventory) == {n for n, v in reader.members.items() if v.isfile()} - {'_collection-members.json'},
            'complete original collection inventory differs')
    for n, row in inventory.items():
        require(row == dict(size=reader.size(n), sha256=reader.digest(n)), 'original collected member changed: ' + n)
    require(set(manifest.get('input_sha256', {})) == {n for n, v in inputs.members.items() if v.isfile()},
            'original input archive inventory differs')
    for n, digest in manifest['input_sha256'].items():
        require(inputs.digest(n) == digest == reader.digest(n), 'original input bytes differ: ' + n)
    spec = obj(inputs.read('project.json')); cfg = spec.get('s2_geometry', {})
    require(spec.get('steps') == manifest.get('steps') and [s.get('tool') for s in spec['steps']] == list(D.TOOLS)
            and spec.get('native_threads') == spec.get('native_cores') == 1
            and cfg.get('schema') == 'dram-see-v4-continuous-geometry-r2' and cfg.get('mode') == 'produce'
            and cfg.get('role_id') == 'B1-D2' and cfg.get('synthetic') is False
            and cfg.get('run_id') == cfg.get('producer_run_id') == manifest['run_id'], 'D2 producer identity differs')
    identity = obj(reader.read('process-identity.json'))
    require(identity.get('schema') == 'tcad-process-identity-r1' and identity.get('run_id') == manifest['run_id']
            and identity.get('cwd') == manifest.get('remote_directory')
            and identity.get('script_sha256') == manifest.get('script_sha256') == reader.digest('run.sh')
            and identity == manifest.get('last_observation', {}).get('identity')
            and type(identity.get('pid')) is int and identity['pid'] > 1 and type(identity.get('start_ticks')) is int
            and identity['start_ticks'] > 0 and re.fullmatch(r'[a-f0-9-]{36}', identity.get('boot_id', '')) is not None,
            'original wrapper/process identity differs')
    lock = dict(line.split('=', 1) for line in reader.read('shared-lock-evidence.txt').decode().splitlines() if '=' in line)
    require(lock.get('status') == 'ACQUIRED' and lock.get('pid') == str(identity['pid']) and lock.get('fd') == '9'
            and lock.get('lock_path') == '/home/tcad/research-training/.solver.lock', 'original shared solver lock differs')
    for i, tool in enumerate(D.TOOLS, 1):
        D._capture(reader, manifest, identity, i, tool)
    require(D._exit(reader.read('exit-code.txt')) == 0 and all(reader.size(n) > 0 for n in D.DC_OUTPUTS)
            and b'Sentaurus Device simulation finished' in reader.read('dc_des.log'), 'D2 DC completion/outputs absent')
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
            and report.get('comparisons') and all(row.get('passed') is True for row in report['comparisons']),
            'actual D2 geometry report differs')
    require(report.get('plan_sha256') == reader.digest('measurement-plan.json')
            and report.get('geometry_contract_sha256') == reader.digest('geometry-contract.json')
            and report.get('mesh_sha256') == context.get('mesh_sha256') == reader.digest('cell_msh.tdr'),
            'original D2 mesh/geometry identity differs')
    for n, digest in report.get('evidence_sha256', {}).items():
        require(reader.digest(n) == digest, 'original geometry evidence changed: ' + n)
    require(type(model['geometry']['gate_top_depth_nm']) is int and model['geometry']['gate_top_depth_nm'] in (70, 80)
            and model['geometry']['active_width_nm'] == 20 and model['doping']['sn_junction_depth_nm'] == 87
            and re.findall(r'AreaFactor\s*=\s*([^\s}]+)', reader.read('device.cmd').decode()) == ['0.02'],
            'actual D2 is outside the selected 70/80nm, SN87, 20nm development scope')
    if reader.exists('controlled-request.json'):
        request = validate_request(obj(reader.read('controlled-request.json')))
        require(request['kind'] == 'dc' and request['gate_top_depth_nm'] == model['geometry']['gate_top_depth_nm']
                and cfg.get('numerical_variant') == request['variant'], 'explicit producer request/actual condition differs')
        verify_d2_inputs(reader, cfg)
        variant, basis = request['variant'], 'explicit_r13_original_input'
    else:
        require(manifest['run_id'] == LEGACY_D2_RUN and manifest_sha == LEGACY_D2_FILES['manifest.json']
                and manifest['results_sha256'] == LEGACY_D2_FILES['results.tar']
                and manifest['inputs_archive_sha256'] == LEGACY_D2_FILES['inputs.tar']
                and model['geometry']['gate_top_depth_nm'] == 80, 'unknown unversioned D2 source')
        variant, basis = 'main', 'exact_original_r8_without_synthetic_request_or_scale'
    return report, cfg, variant, basis


def _record(reader, manifest, manifest_sha, report, cfg, variant, basis):
    D = d2_api()
    return dict(run_id=manifest['run_id'], manifest_sha256=manifest_sha,
        archive_sha256=manifest['results_sha256'], inputs_sha256=manifest['inputs_archive_sha256'],
        collection_index_sha256=reader.digest('_collection-members.json'),
        geometry_validation_sha256=reader.digest('geometry-validation.json'), mesh_sha256=reader.digest('cell_msh.tdr'),
        mesh_log_sha256=reader.digest('cell_msh.log'), shared_sha256={n: reader.digest(n) for n in D.SHARED_INPUTS},
        declared_variant=variant, variant_evidence=basis,
        gate_top_depth_nm=obj(reader.read('model.proposed.json'))['geometry']['gate_top_depth_nm'],
        actual_tool_exit_codes=manifest['tool_exit_codes'], source_cfg=cfg, mesh_recipe=mesh_recipe(reader.read('geometry-with-measurements.scm')),
        dc_execution_completed=True, dc_calibrated=False, a0_functionality_qualified=False)


def _opened_source(reader, inputs, manifest_raw):
    manifest = obj(manifest_raw)
    report, cfg, variant, basis = _validate_source(reader, manifest, inputs, sha(manifest_raw))
    record = _record(reader, manifest, sha(manifest_raw), report, cfg, variant, basis)
    small = {n: reader.read(n) for n in d2_api().SHARED_INPUTS + ('device.cmd', 'geometry-with-measurements.scm')}
    return dict(record=record, report=report, source_cfg=cfg, small=small)


def read_source(path):
    """Read one real original D2; never submit, extract, rewrite or relabel it."""
    D = d2_api(); path = Path(path)
    require(path.is_absolute() and path.is_dir() and not path.is_symlink()
            and 'UNIT_FIXTURE_NOT_NATIVE' not in str(path) and not (path/'SYNTHETIC_NOT_NATIVE').exists(),
            'actual original D2 directory required')
    manifest_raw = (path/'manifest.json').read_bytes(); manifest = obj(manifest_raw)
    require(manifest.get('run_id') == path.name and D.file_sha(path/'results.tar') == manifest.get('results_sha256')
            and D.file_sha(path/'inputs.tar') == manifest.get('inputs_archive_sha256'), 'original D2 archive receipt differs')
    with tarfile.open(str(path/'results.tar'), 'r:*') as archive, tarfile.open(str(path/'inputs.tar'), 'r:*') as inputs:
        result = _opened_source(D.ArchiveReader(archive), D.ArchiveReader(inputs), manifest_raw)
    result['files'] = {n: dict(path=str(path/n), sha256=D.file_sha(path/n), size_bytes=(path/n).stat().st_size)
                       for n in ('manifest.json', 'results.tar', 'inputs.tar')}
    return result


def _frozen_source(reader, prefix, files):
    D = d2_api()
    require(set(files) == {'manifest.json', 'results.tar', 'inputs.tar'}, 'complete original D2 three-file proof required')
    for name, row in files.items():
        require(set(row) == {'sha256', 'size_bytes'} and reader.digest(prefix+name) == row['sha256']
                and reader.size(prefix+name) == row['size_bytes'], 'frozen original D2 file changed: ' + prefix+name)
    raw = reader.read(prefix+'manifest.json'); manifest = obj(raw)
    require(files['results.tar']['sha256'] == manifest.get('results_sha256')
            and files['inputs.tar']['sha256'] == manifest.get('inputs_archive_sha256'), 'frozen D2 archive receipt differs')
    with reader.stream(prefix+'results.tar') as a, reader.stream(prefix+'inputs.tar') as i:
        with tarfile.open(fileobj=a, mode='r:*') as archive, tarfile.open(fileobj=i, mode='r:*') as inputs:
            return _opened_source(D.ArchiveReader(archive), D.ArchiveReader(inputs), raw)


def _check_pair(selected, base, gate, variant):
    D = d2_api(); a, b = base['record'], selected['record']
    require(a['gate_top_depth_nm'] == b['gate_top_depth_nm'] == gate and a['declared_variant'] == 'main',
            'selected/base actual D2 condition or base-main identity differs')
    if variant != 'h2':
        require(a == b and b['declared_variant'] == 'main', 'main/dt2 must reuse the same complete main D2 and mesh')
        return mesh_relation(base['small']['geometry-with-measurements.scm'], selected['small']['geometry-with-measurements.scm'], 1.)
    require(b['declared_variant'] == 'mesh' and a['run_id'] != b['run_id'] and a['mesh_sha256'] != b['mesh_sha256'],
            'h2 needs its actual independent mesh producer, not a relabelled main mesh')
    require(obj(selected['small']['model.proposed.json']) == obj(base['small']['model.proposed.json']), 'h2 changes physical model')
    for n in D.SHARED_INPUTS[:4]:
        require(selected['small'][n] == base['small'][n], 'h2 changes physical cards: ' + n)
    ga, gb = (_physical_geometry(v['small']['geometry-contract.json'], gate) for v in (base, selected))
    require(ga == gb, 'h2 changes geometric dimensions or physical expected geometry')
    return mesh_relation(base['small']['geometry-with-measurements.scm'], selected['small']['geometry-with-measurements.scm'], .5, True)


def _physical_geometry(raw, gate):
    value = obj(raw)
    value.pop('mesh')
    value.pop('legacy_size_label', None)
    labels = ('S2', 'gate-top-depth-80nm') if gate == 80 else ('gate-top-depth-70nm',)
    require(value['size_id'] in labels, 'unrecognized geometry display identity')
    value['size_id'] = 'gate-top-depth-{}nm'.format(gate)
    require(value['dimension'] == 2 and value['length_unit'] == 'um' and value['measure_unit'] == 'um^2'
            and value['gate_void']['top_um'] == gate/1000. and value['nominal_oxide_um']['top_cap'] == gate/1000.,
            'actual geometry gate coordinate or unit differs from selected physical model')
    return value


def source_bundle(project, cfg, execution=None):
    D = d2_api()
    selected = read_source(Path(cfg['source_run_directory']))
    base_path = Path(cfg['base_source_run_directory'])
    base = selected if base_path.resolve() == Path(cfg['source_run_directory']).resolve() else read_source(base_path)
    _check_pair(selected, base, cfg['gate_top_depth_nm'], cfg['numerical_variant'])
    require(cfg['producer_run_id'] == selected['record']['run_id'], 'selected source run identity differs')
    slots = {'selected': dict(prefix='d2-producer-bindings/', value=selected)}
    same = selected['record'] == base['record']
    if not same:
        slots['base'] = dict(prefix='d2-base-bindings/', value=base)
    original, external, records = {}, {}, {}
    for key, slot in slots.items():
        records[key] = dict(prefix=slot['prefix'], record=slot['value']['record'],
                            files={n: {k: v[k] for k in ('sha256', 'size_bytes')} for n, v in slot['value']['files'].items()})
        for n, row in slot['value']['files'].items():
            target = slot['prefix']+n
            original[target] = {k: row[k] for k in ('sha256', 'size_bytes')}
            external[target] = dict(path=row['path'], sha256=row['sha256'])
    current = selected['record']
    binding = dict(schema=SOURCE_BINDING_SCHEMA, branch_id=DIMENSION_BRANCH, source_dimension=2,
        producer_role_id='B1-D2', producer_run_id=current['run_id'], source_manifest_sha256=current['manifest_sha256'],
        source_archive_sha256=current['archive_sha256'], source_inputs_archive_sha256=current['inputs_sha256'],
        geometry_validation_sha256=current['geometry_validation_sha256'], mesh_sha256=current['mesh_sha256'],
        mesh_log_sha256=current['mesh_log_sha256'], shared_input_sha256=current['shared_sha256'],
        sources=records, base_source_key='selected' if same else 'base', original_files=original,
        verifier_file='parameterized_operating_2d.py', verifier_sha256=D.file_sha(__file__),
        source_dc_execution_completed=True, source_dc_calibrated=False, source_A0_functionality_qualified=False)
    raw = encoded(binding); generated = {'d2-source-binding.json': raw}
    exports = {'cell_msh.tdr': current['mesh_sha256'], 'cell_msh.log': current['mesh_log_sha256'], 'd2-source-binding.json': sha(raw)}
    exports.update({n: row['sha256'] for n, row in original.items()})
    for key, actual in (('source_manifest_sha256', current['manifest_sha256']), ('source_archive_sha256', current['archive_sha256']),
                        ('mesh_sha256', current['mesh_sha256']), ('geometry_validation_sha256', current['geometry_validation_sha256']),
                        ('d2_source_binding_sha256', sha(raw))):
        if execution is not None or key in cfg:
            require(cfg.get(key) == actual, 'actual producer binding differs: '+key)
    shared = {n: selected['small'][n] for n in D.SHARED_INPUTS}
    for n, raw_value in shared.items():
        path = Path(project)/n
        if path.exists():
            require(D.file_sha(path) == sha(raw_value), 'actual selected shared input differs: '+n)
    return dict(archive=Path(cfg['source_run_directory'])/'results.tar', archive_sha256=current['archive_sha256'],
        manifest_sha256=current['manifest_sha256'], mesh_sha256=current['mesh_sha256'],
        geometry_validation_sha256=current['geometry_validation_sha256'], producer_inputs=shared,
        producer_cfg=selected['source_cfg'], exports=exports, generated_files=generated, external_files=external,
        d2_binding=binding, d2_source_binding_sha256=sha(encoded(binding)), selected=selected, base=base)


def dimensional_contract(binding):
    value = d2_api().dimensional_contract(binding)
    value['branch_id'] = DIMENSION_BRANCH
    return value


def _verify_sources(reader, cfg):
    D = d2_api(); binding_raw = reader.read('d2-source-binding.json'); binding = obj(binding_raw)
    require(binding.get('schema') == SOURCE_BINDING_SCHEMA and binding.get('branch_id') == DIMENSION_BRANCH
            and cfg.get('dimension_branch') == DIMENSION_BRANCH and cfg.get('source_dimension') == 2
            and cfg.get('d2_source_binding_sha256') == sha(binding_raw)
            and binding.get('verifier_sha256') == D.file_sha(__file__) == reader.digest('parameterized_operating_2d.py'),
            'explicit source version identity differs')
    require(binding.get('verifier_file') == 'parameterized_operating_2d.py' and binding.get('producer_role_id') == 'B1-D2'
            and binding.get('source_dimension') == 2 and binding.get('source_dc_execution_completed') is True
            and binding.get('source_dc_calibrated') is False and binding.get('source_A0_functionality_qualified') is False,
            'source binding promotes execution into scientific qualification')
    require(binding.get('base_source_key') in ('selected', 'base') and set(binding['sources']) ==
            ({'selected'} if binding['base_source_key'] == 'selected' else {'selected', 'base'}), 'unexpected source identity set')
    verified, originals = {}, {}
    for key, row in binding['sources'].items():
        prefix = 'd2-producer-bindings/' if key == 'selected' else 'd2-base-bindings/'
        require(set(row) == {'prefix', 'record', 'files'} and row['prefix'] == prefix, 'source proof layout differs')
        source = _frozen_source(reader, prefix, row['files'])
        require(source['record'] == row['record'], 'original source record cannot be relabelled')
        verified[key] = source
        originals.update({prefix+n: v for n, v in row['files'].items()})
    require(binding['original_files'] == originals, 'original full source inventory differs')
    selected, base = verified['selected'], verified[binding['base_source_key']]
    _check_pair(selected, base, cfg['gate_top_depth_nm'], cfg['numerical_variant'])
    current = selected['record']
    for name, value in (('producer_run_id', current['run_id']), ('source_manifest_sha256', current['manifest_sha256']),
                        ('source_archive_sha256', current['archive_sha256']), ('mesh_sha256', current['mesh_sha256']),
                        ('geometry_validation_sha256', current['geometry_validation_sha256'])):
        require(binding.get(name) == cfg.get(name) == value, 'original source/current identity differs: '+name)
    require(binding['source_inputs_archive_sha256'] == current['inputs_sha256']
            and binding['mesh_log_sha256'] == current['mesh_log_sha256'] == reader.digest('cell_msh.log')
            and reader.digest('cell_msh.tdr') == current['mesh_sha256']
            and binding['shared_input_sha256'] == current['shared_sha256'], 'actual mesh/shared source bytes differ')
    for name, digest in current['shared_sha256'].items():
        require(reader.digest(name) == digest, 'root model/geometry/physics differs from actual selected D2: '+name)
    width = dimensional_contract(binding)
    require(obj(reader.read('dimensional-contract.json')) == width
            and reader.digest('dimensional-contract.json') == cfg.get('dimensional_contract_sha256')
            and cfg.get('effective_width_nm') == 20 and cfg.get('area_factor') == .02, 'width/units/current scaling differs')
    return dict(binding=binding, report=selected['report'], source_cfg=selected['source_cfg'],
                dimensional_contract=width), selected, base


def _runtime_bytes():
    here = Path(__file__).resolve().parent
    result = {}
    fixed = {'two_dimensional.py': D2_SHA, 'operating_transient_2d.py': O_SHA,
             'native_transient_clock.py': CLOCK_SHA, 'operating_metrics_2d.py': METRICS_SHA,
             'legacy-circuit-metrics.py': LEGACY_SHA}
    for name in RUNTIME_FILES:
        path = here/name
        if name == 'operating_metrics_2d.py' and not path.exists():
            path = here.parent/'data'/name
        if name == 'legacy-circuit-metrics.py' and not path.exists():
            path = here.parents[1]/'s2-inputs-r1/metrics.py'
        raw = path.read_bytes()
        if name in fixed:
            require(sha(raw) == fixed[name], 'runtime dependency changed: '+name)
        result[name] = raw
    return result


def _verify_runtime(reader):
    for name, raw in _runtime_bytes().items():
        require(reader.digest(name) == sha(raw), 'frozen fixed runtime differs: '+name)


def _producer_relation(reader, request, base):
    r = validate_request(request)
    require(r['kind'] == 'dc', 'producer relation needs DC request')
    previous = base['record']; gate = r['gate_top_depth_nm']; fine = r['variant'] == 'mesh'
    require(previous['declared_variant'] == 'main' and name_of(r['base_d2_source_run']) == previous['run_id'],
            'producer must bind its actual base main D2')
    if fine:
        require(previous['gate_top_depth_nm'] == gate, 'h2 cannot change the physical condition')
    else:
        require(previous['run_id'] == LEGACY_D2_RUN and previous['manifest_sha256'] == LEGACY_D2_FILES['manifest.json'],
                'development main changes only gate depth from the original actual r8 reference')
    expected_model = obj(base['small']['model.proposed.json'])
    expected_model['geometry']['gate_top_depth_nm'] = gate
    require(obj(reader.read('model.proposed.json')) == expected_model, 'producer changes a model parameter beyond its declared gate change')
    for name in d2_api().SHARED_INPUTS[:4] + ('device.cmd',):
        require(reader.read(name) == base['small'][name], 'producer physics, numerical method or DC bias recipe changed: '+name)
    actual_geometry = _physical_geometry(reader.read('geometry-contract.json'), gate)
    if fine:
        require(actual_geometry == _physical_geometry(base['small']['geometry-contract.json'], gate),
                'h2 changes physical expected geometry')
    g = obj(reader.read('geometry-contract.json'))
    require(g['mesh'].get('scale') == (.5 if fine else 1) and g['mesh'].get('numerical_variant') == r['variant'],
            'new producer must declare its actual numerical mesh variant')
    refinement = mesh_relation(base['small']['geometry-with-measurements.scm'], reader.read('geometry-with-measurements.scm'),
                               .5 if fine else 1., same_physical_sde=fine)
    return dict(schema='dram-see-v4-2d-producer-relation-r1', base_source=previous,
        request_sha256=sha(encoded(r)), gate_top_depth_nm=gate, sn_junction_depth_nm=87,
        variant=r['variant'], base_model_sha256=previous['shared_sha256']['model.proposed.json'],
        model_sha256=reader.digest('model.proposed.json'), geometry_contract_sha256=reader.digest('geometry-contract.json'),
        sde_sha256=reader.digest('geometry-with-measurements.scm'), device_sha256=reader.digest('device.cmd'),
        declared_refinement=refinement, changed_physical_parameter=None if fine else 'gate_top_depth_nm_only',
        comparison_thresholds_changed=False, native_run_completed=False, actual_mesh_convergence_qualified=False)


class BytesReader:
    """Small pure payload reader. Large original files stay in file-backed readers."""
    def __init__(self, values):
        self.values = values
    def read(self, name):
        return self.values[name]
    def digest(self, name):
        return sha(self.values[name])


def producer_payload(request):
    """Explicit new DC path, using the existing producer generator unchanged."""
    r = validate_request(request)
    require(r['kind'] == 'dc', 'DC payload required')
    case = local_module('case_contract.py')
    require(getattr(case, 'SCHEMA_2D_PARAMETERIZED', None) == REQUEST_SCHEMA,
            'r13 dispatch patch not integrated; original r1 validation remains intact')
    base = read_source(Path(r['base_d2_source_run']).resolve())
    # prepare_case.producer_payload itself remains unchanged. It validates the
    # new explicit schema through the separately integrated case dispatch.
    P = local_module('prepare_case.py')
    files, model = P.producer_payload(r)
    relation = _producer_relation(BytesReader(files), r, base)
    proof = {n: {key: row[key] for key in ('sha256', 'size_bytes')} for n, row in base['files'].items()}
    binding = dict(schema='dram-see-v4-d2-refinement-base-binding-r1', prefix='d2-refinement-base/', files=proof,
                   source_record=base['record'], verifier_sha256=d2_api().file_sha(__file__))
    files['d2-refinement-base-binding.json'] = encoded(binding)
    files['d2-producer-relation.json'] = encoded(relation)
    for n, row in base['files'].items():
        raw = Path(row['path']).read_bytes()
        require(sha(raw) == row['sha256'] and len(raw) == row['size_bytes'], 'original base changed while freezing: '+n)
        files['d2-refinement-base/'+n] = raw
    files.update(_runtime_bytes())
    return files, model


def verify_d2_inputs(reader, cfg):
    """Verify new producer inputs, including the original actual main source."""
    r = validate_request(obj(reader.read('controlled-request.json')))
    require(r['kind'] == 'dc' and cfg.get('mode') == 'produce' and cfg.get('role_id') == 'B1-D2'
            and cfg.get('numerical_variant') == r['variant'] and cfg.get('run_id') == cfg.get('producer_run_id'),
            'r13 actual producer configuration differs')
    _verify_runtime(reader)
    binding = obj(reader.read('d2-refinement-base-binding.json'))
    require(set(binding) == {'schema', 'prefix', 'files', 'source_record', 'verifier_sha256'}
            and binding['schema'] == 'dram-see-v4-d2-refinement-base-binding-r1'
            and binding['prefix'] == 'd2-refinement-base/' and binding['verifier_sha256'] == d2_api().file_sha(__file__),
            'explicit original base proof version differs')
    base = _frozen_source(reader, binding['prefix'], binding['files'])
    require(base['record'] == binding['source_record'], 'actual base record differs')
    relation = _producer_relation(reader, r, base)
    require(obj(reader.read('d2-producer-relation.json')) == relation, 'actual producer numerical relation differs')
    require(cfg['run_id'] != base['record']['run_id'], 'new D2 producer cannot rename its original base')
    return relation


def prepare_d2(request, run_id, runner=None, output=None):
    """One future D2 through original prepare_case/runner six-step recipe."""
    r = validate_request(request)
    require(r['kind'] == 'dc', 'DC branch required')
    C = local_module('case_contract.py')
    require(getattr(C, 'SCHEMA_2D_PARAMETERIZED', None) == REQUEST_SCHEMA, 'r13 patch not integrated; no output created')
    r['base_d2_source_run'] = str(Path(r['base_d2_source_run']).resolve())
    # The patch routes only r13 transient requests to prepare(); DC continues
    # through the existing generic prepare_case.prepare and producer role.
    P = local_module('prepare_case.py'); directory = str(Path(__file__).resolve().parent)
    added = directory not in sys.path
    if added:
        sys.path.insert(0, directory)
    try:
        return P.prepare(r, run_id, runner, output)
    finally:
        if added:
            sys.path.remove(directory)


def verify_template(reader):
    O = operation_api(); D = d2_api(); prefix = 'operation-template/'
    raw = reader.read(prefix+'input-manifest.json')
    require(sha(raw) == O.TEMPLATE_MANIFEST_SHA, 'original small electrical template manifest changed')
    manifest = obj(raw)
    require(manifest.get('run_id') == O.TEMPLATE_RUN and manifest.get('role_id') == 'B2D-A0-main-b0',
            'original electrical template identity differs')
    for name in O.TEMPLATE_FILES[1:]:
        require(reader.digest(prefix+name) == manifest['files_sha256'][name], 'original electrical template member changed: '+name)
    require(reader.digest(prefix+'device.cmd') == O.TEMPLATE_SHA, 'original fixed electrical deck changed')
    # Geometry/model/width-source identity belongs to the actual selected D2.
    # Only the original physical cards are shared with the small 80nm template.
    for name in D.SHARED_INPUTS[:4]:
        require(reader.digest(name) == manifest['files_sha256'][name], 'original electrical physics/cards differ: '+name)
    return {n: reader.read(prefix+n) for n in O.TEMPLATE_FILES}


def numerical_relation(request, base_raw, selected_raw, source_binding):
    r = validate_request(request)
    require(r['kind'] == 'transient', 'A0 relation required')
    selected = source_binding['sources']['selected']['record']
    base = source_binding['sources'][source_binding['base_source_key']]['record']
    require(name_of(r['d2_source_run']) == selected['run_id'] and name_of(r['base_d2_source_run']) == base['run_id'],
            'request source identity differs from original records')
    require(base['gate_top_depth_nm'] == selected['gate_top_depth_nm'] == r['gate_top_depth_nm']
            and base['declared_variant'] == 'main'
            and selected['declared_variant'] == ('mesh' if r['variant'] == 'h2' else 'main'),
            'pure input cannot relabel source geometry or mesh variant')
    relation = timing_relation(base_raw, selected_raw, r['variant'])
    require(r['base_operation_timing_sha256'] == sha(base_raw) and r['operation_timing_sha256'] == sha(selected_raw),
            'request/base timing byte identity differs')
    relation.update(gate_top_depth_nm=r['gate_top_depth_nm'], sn_junction_depth_nm=87,
        effective_width_nm=20, base_producer_run_id=base['run_id'], producer_run_id=selected['run_id'],
        base_mesh_sha256=base['mesh_sha256'], mesh_sha256=selected['mesh_sha256'],
        base_source_manifest_sha256=base['manifest_sha256'], source_manifest_sha256=selected['manifest_sha256'],
        declared_mesh_length_scale=.5 if r['variant'] == 'h2' else 1.,
        selected_mesh_reused_byte_for_byte=True, numerical_axes_combined=False)
    return relation


def payload(template, shared, cfg, request, selected_raw, base_raw, selection_files, source_binding):
    """Pure input bytes; source or UNIT rendering is never a native positive."""
    r = validate_request(request); O = operation_api()
    require(r['kind'] == 'transient', 'A0 payload required')
    t = O.validate_timing(obj(selected_raw)); relation = numerical_relation(r, base_raw, selected_raw, source_binding)
    require(set(selection_files) == set(r['operation_evidence_files']) == set(t['selection_provenance']['references']),
            'complete explicit operation-selection references required')
    for name, digest in t['selection_provenance']['references'].items():
        require(sha(selection_files[name]) == digest, 'actual selection evidence differs: '+name)
    files = {'operation-template/'+name: raw for name, raw in template.items()}
    files.update({'operation-selection/'+name: raw for name, raw in selection_files.items()})
    files['operation-timing.json'] = selected_raw
    files['base-operation-timing.json'] = base_raw
    files['rendered-operation-timing.json'] = encoded(O.rendered_timing(t))
    files['numerical-relation.json'] = encoded(relation)
    files['device.cmd'] = render(template['device.cmd'], r['stored_bit'], selected_raw, base_raw, r['variant'])
    files['initialization-contract.json'] = template['initialization-contract.json']
    source = dict(schema='dram-see-v4-2d-parameterized-control-source-spec-r1', role='CONTROL', source_case='A0',
        source_configured=False, structural_source_absence=True, dimension=2, stored_bit=r['stored_bit'],
        numerical_variant=r['variant'], gate_top_depth_nm=r['gate_top_depth_nm'], sn_junction_depth_nm=87,
        operation_timing_sha256=sha(selected_raw), numerical_relation_sha256=sha(files['numerical-relation.json']),
        dimensional_contract_sha256=sha(shared['dimensional-contract.json']),
        physics_manifest_sha256=sha(shared['physics-manifest.json']), particle_source_qualified=False)
    files['source-spec.json'] = encoded(source)
    files['source-contract.json'] = encoded(dict(schema='dram-see-v4-2d-parameterized-structural-control-r1',
        source_configured=False, source_dimension=2, structural_source_absence=True,
        source_field_absence='structural absence, never measured zero', operation_timing_sha256=sha(selected_raw),
        native_observation_window_s=t['native_observation_window_s'], mathematical_source_window_s=t['mathematical_source_window_s'],
        source_epoch_s=t['source_epoch_s'], native_source_qualified=False, native_A0_functionality_qualified=False))
    files['functional-criteria.json'] = encoded(dict(schema='dram-see-v4-2d-parameterized-functional-criteria-r1',
        operation_timing_sha256=sha(selected_raw), implementation_sha256=METRICS_SHA,
        criteria=O.metrics_api().criteria(), thresholds_changed=False))
    files['numerical-method.json'] = encoded(dict(schema='dram-see-v4-2d-parameterized-numerics-r1',
        original_numerical_method=obj(template['numerical-method.json']), original_numerical_sha256=sha(template['numerical-method.json']),
        original_method_source_is_historical_not_current_producer=True, actual_producer_run_id=source_binding['producer_run_id'],
        diagnostic_output=['CNormPrint', 'PrintRhsPerEquation'], algorithm_or_convergence_criteria_changed=False,
        numerical_relation_sha256=sha(files['numerical-relation.json']), actual_native_diagnostic_syntax_verified=False))
    files['parameter-binding.json'] = encoded(dict(schema='dram-see-v4-active-parameters-r1', base_file='physics.par',
        base_sha256=sha(shared['physics.par']), source_file=None, source_sha256=None, source_physics_file=None,
        source_physics_sha256=None, active_file='physics.par', active_sha256=sha(shared['physics.par']), aggregation='base_only'))
    binding = dict(schema='dram-see-v4-parameterized-operating-binding-r1', branch_id=BRANCH,
        stored_bit=r['stored_bit'], numerical_variant=r['variant'], gate_top_depth_nm=r['gate_top_depth_nm'],
        producer_run_id=source_binding['producer_run_id'], d2_source_binding_sha256=sha(encoded(source_binding)),
        template_run_id=O.TEMPLATE_RUN, template_manifest_sha256=O.TEMPLATE_MANIFEST_SHA,
        operation_timing_sha256=sha(selected_raw), base_operation_timing_sha256=sha(base_raw),
        numerical_relation_sha256=sha(files['numerical-relation.json']), gate_high_V=t['voltage_levels_V']['gate_high_V'],
        dimensional_contract_sha256=sha(shared['dimensional-contract.json']), verifier_sha256=d2_api().file_sha(__file__),
        clock_sha256=CLOCK_SHA, metrics_sha256=METRICS_SHA, legacy_helper_sha256=LEGACY_SHA,
        files_sha256={name: sha(raw) for name, raw in files.items()}, physics_cards_unchanged=True,
        selected_D2_mesh_unchanged=True, native_run_completed=False, native_A0_functionality_qualified=False,
        mesh_or_time_convergence_qualified=False, scientific_evidence_verified=False, training_admitted=False)
    files['parameterized-operating-binding.json'] = encoded(binding)
    return files


def role_contract(cfg, timing):
    return dict(schema='dram-see-v4-2d-parameterized-control-role-r1', role=cfg['role_id'], dimension=2, case='A0',
        stored_bit=cfg['stored_bit'], numerical_variant=cfg['numerical_variant'], gate_top_depth_nm=cfg['gate_top_depth_nm'],
        sn_junction_depth_nm=87, source_configured=False, source_dimension=2, effective_width_nm=20,
        area_factor=.02, Cstore_fF=20, Cbl_fF=200, gate_high_V=timing['voltage_levels_V']['gate_high_V'],
        operation_timing_sha256=cfg['operation_timing_sha256'], base_operation_timing_sha256=cfg['base_operation_timing_sha256'],
        numerical_relation_sha256=cfg['numerical_relation_sha256'],
        parameterized_operating_binding_sha256=cfg['parameterized_operating_binding_sha256'],
        dimensional_contract_sha256=cfg['dimensional_contract_sha256'], producer_run_id=cfg['producer_run_id'],
        mesh_sha256=cfg['mesh_sha256'], actual_read_WL_plateau_s=[timing['read_rise_window_s'][1], timing['read_fall_window_s'][0]],
        read_scoring_window_s=timing['read_window_s'], source_observation_window_s=timing['native_observation_window_s'],
        full_physical_window_s=timing['simulation_window_s'], native_syntax_verified=False,
        native_A0_functionality_qualified=False, mesh_or_time_convergence_qualified=False,
        response_admission='Actual two-bit clocks, unchanged functional/KCL and separate field/refinement evidence remain required')


def verify_frozen(reader, cfg):
    """Exact nine-key public result; no local path or archived code execution."""
    require(cfg.get('parameterized_operating_branch') == BRANCH and cfg.get('mode') == 'reuse', 'explicit new A0 branch required')
    r = validate_request(obj(reader.read('controlled-request.json')))
    require(r['kind'] == 'transient' and cfg.get('role_id') == role_id(r) and cfg.get('stored_bit') == r['stored_bit']
            and cfg.get('numerical_variant') == r['variant'] and cfg.get('gate_top_depth_nm') == r['gate_top_depth_nm']
            and cfg.get('sn_junction_depth_nm') == 87
            and cfg.get('size_id') == 'gate-top-depth-{}nm'.format(r['gate_top_depth_nm'])
            and cfg.get('parameter_id') == 'gate-top-depth-{}nm__sn-junction-depth-87nm'.format(r['gate_top_depth_nm']),
            'actual A0 role/condition differs')
    _verify_runtime(reader)
    result, selected, base = _verify_sources(reader, cfg)
    selected_raw, base_raw = reader.read('operation-timing.json'), reader.read('base-operation-timing.json')
    t = operation_api().validate_timing(obj(selected_raw))
    require(cfg.get('operation_timing_sha256') == r['operation_timing_sha256'] == sha(selected_raw)
            and cfg.get('base_operation_timing_sha256') == r['base_operation_timing_sha256'] == sha(base_raw)
            and cfg.get('gate_high_V') == t['voltage_levels_V']['gate_high_V'], 'actual physical timing/gate identity differs')
    template = verify_template(reader)
    shared = {n: reader.read(n) for n in d2_api().SHARED_INPUTS + ('dimensional-contract.json',)}
    selections = {n: reader.read('operation-selection/'+n) for n in t['selection_provenance']['references']}
    expected = payload(template, shared, cfg, r, selected_raw, base_raw, selections, result['binding'])
    for name, raw in expected.items():
        require(reader.read(name) == raw, 'deterministic frozen input differs: '+name)
    role = role_contract(cfg, t)
    require(obj(reader.read('role-contract.json')) == role
            and cfg.get('parameterized_operating_binding_sha256') == reader.digest('parameterized-operating-binding.json')
            and cfg.get('numerical_relation_sha256') == reader.digest('numerical-relation.json'), 'frozen role/relation identity differs')
    local_module('native_transient_clock.py', CLOCK_SHA)._deck(reader.read('device.cmd'))
    result.update(operation_timing=t, operating_binding=obj(expected['parameterized-operating-binding.json']),
                  source_spec=obj(expected['source-spec.json']), role_contract=role,
                  numerical_relation=obj(expected['numerical-relation.json']))
    require(set(result) == FROZEN_RESULT_KEYS, 'public frozen return schema differs')
    return result


def admit(project, spec, runner_sha, bridge):
    project = Path(project); cfg = spec['s2_geometry']
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(project.resolve()) and not (project/'SYNTHETIC_NOT_NATIVE').exists(),
            'UNIT fixture cannot be submitted')
    r = validate_request(obj((project/'controlled-request.json').read_bytes()))
    require(r['kind'] == 'transient' and cfg.get('schema') == bridge.GEOMETRY_SCHEMA and cfg.get('mode') == 'reuse'
            and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True and spec.get('execution_enabled') is True
            and spec.get('role') == cfg.get('role_id') == role_id(r) and cfg.get('run_id') != cfg.get('producer_run_id')
            and operation_api().plain_name(cfg.get('run_id')) and spec.get('native_threads') == spec.get('native_cores') == 1
            and spec.get('steps') == [dict(tool='sdevice', args=['device.cmd'], outputs=list(operation_api().OUTPUTS))],
            'native original-runner A0 identity/step contract differs')
    bridge.geometry_context(project, cfg, runner_sha)
    hashes = bridge.geometry_input_hashes(project)
    binding = obj((project/'d2-source-binding.json').read_bytes())
    required = set(d2_api().SHARED_INPUTS) | set(RUNTIME_FILES) | set(binding['original_files']) | {
        'project.json', 'case_contract.py', 'geometry_bridge.py', 'mesh_resource_guard.py', 'controlled-request.json',
        'resource-policy.json', 'task-authorization.json', 'role-contract.json', 'device.cmd', 'cell_msh.tdr', 'cell_msh.log',
        'd2-source-binding.json', 'dimensional-contract.json', 'operation-timing.json', 'base-operation-timing.json',
        'rendered-operation-timing.json', 'numerical-relation.json', 'parameterized-operating-binding.json',
        'initialization-contract.json', 'source-spec.json', 'source-contract.json', 'functional-criteria.json',
        'numerical-method.json', 'parameter-binding.json'} | {'operation-template/'+n for n in operation_api().TEMPLATE_FILES}
    require(required <= set(hashes), 'mandatory actual source/operation input missing')
    for name, digest in hashes.items():
        require(d2_api().file_sha(bridge.geometry_path(project, name)) == digest, 'frozen A0 input changed: '+name)
    manifest = obj((project/'input-manifest.json').read_bytes())
    require(manifest.get('run_id') == cfg['run_id'] and manifest.get('role_id') == cfg['role_id'], 'original input manifest identity differs')
    result = verify_frozen(d2_api().FolderReader(project), cfg)
    require(result['operation_timing']['origin'] == 'prescribed_input', 'UNIT timing cannot be submitted')
    require({'operation-selection/'+n for n in r['operation_evidence_files']} <= set(hashes), 'operation evidence not frozen')
    require(obj((project/'resource-policy.json').read_bytes()) == dict(schema='dram-see-v4-actual-resource-policy-r1',
        role=cfg['role_id'], observation_only=True, imported_mesh_sha256=cfg['mesh_sha256'], resource_limits=None),
        'resource observations cannot become a quota or approval gate')
    return cfg


def prepare(request, run_id, runner=None, output=None):
    """Prepare one future explicit input; no submit, lock, SSH or native call."""
    r = validate_request(request)
    if r['kind'] == 'dc':
        return prepare_d2(r, run_id, runner, output)
    D = d2_api(); O = operation_api(); C = local_module('case_contract.py'); bridge = local_module('geometry_bridge.py')
    require(getattr(C, 'SCHEMA_2D_PARAMETERIZED', None) == REQUEST_SCHEMA
            and hasattr(bridge, 'geometry_parameterized_operating_module'), 'r13 dispatch patch not integrated; no input directory created')
    require(O.plain_name(run_id) and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id, 'new nonfixture run ID required')
    here = Path(__file__).resolve().parent; root = here.parents[3]
    runner = Path(runner or root/'scripts/tcad.py').resolve()
    require(runner == (root/'scripts/tcad.py').resolve() and runner.is_file(), 'original scripts/tcad.py required')
    allowed = (root/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/parameterized-2d-implementation-r1').resolve()
    target = Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'UNIT_FIXTURE_NOT_NATIVE' not in str(target), 'new allowed project directory required')
    selected_raw = Path(r['operation_timing_file']).read_bytes(); base_raw = Path(r['base_operation_timing_file']).read_bytes()
    t = O.validate_timing(obj(selected_raw))
    require(t['origin'] == 'prescribed_input', 'actual explicit operation selection required; no UNIT project')
    timing_relation(base_raw, selected_raw, r['variant'])
    selections = {name: Path(path).read_bytes() for name, path in r['operation_evidence_files'].items()}
    for name in ('d2_source_run', 'base_d2_source_run'):
        r[name] = str(Path(r[name]).resolve())
    role = role_id(r); runner_sha = D.file_sha(runner)
    cfg = dict(schema=bridge.GEOMETRY_SCHEMA, mode='reuse', dimension_branch=DIMENSION_BRANCH,
        parameterized_operating_branch=BRANCH, role_id=role, run_id=run_id, producer_run_id=name_of(r['d2_source_run']),
        stored_bit=r['stored_bit'], gate_top_depth_nm=r['gate_top_depth_nm'], sn_junction_depth_nm=87,
        numerical_variant=r['variant'], execution_enabled=True, synthetic=False, source_run_directory=r['d2_source_run'],
        base_source_run_directory=r['base_d2_source_run'], source_dimension=2, effective_width_nm=20, area_factor=.02,
        size_id='gate-top-depth-{}nm'.format(r['gate_top_depth_nm']),
        parameter_id='gate-top-depth-{}nm__sn-junction-depth-87nm'.format(r['gate_top_depth_nm']))
    bundle = source_bundle(target, cfg)
    cfg.update(source_manifest_sha256=bundle['manifest_sha256'], source_archive_sha256=bundle['archive_sha256'],
        mesh_sha256=bundle['mesh_sha256'], geometry_validation_sha256=bundle['geometry_validation_sha256'],
        d2_source_binding_sha256=bundle['d2_source_binding_sha256'])
    files = dict(bundle['producer_inputs']); files.update(bundle['generated_files'])
    files['dimensional-contract.json'] = encoded(dimensional_contract(bundle['d2_binding']))
    cfg.update(dimensional_contract_sha256=sha(files['dimensional-contract.json']), operation_timing_sha256=sha(selected_raw),
        base_operation_timing_sha256=sha(base_raw), gate_high_V=t['voltage_levels_V']['gate_high_V'])
    template_dir = Path(r['a0_template_project']).resolve()
    require(template_dir.name == O.TEMPLATE_RUN and not template_dir.is_symlink(), 'actual small template directory differs')
    template = {n: (template_dir/n).read_bytes() for n in O.TEMPLATE_FILES}
    small = dict(files); small.update({'operation-template/'+n: raw for n, raw in template.items()})
    verify_template(BytesReader(small))
    files.update(payload(template, files, cfg, r, selected_raw, base_raw, selections, bundle['d2_binding']))
    cfg.update(parameterized_operating_binding_sha256=sha(files['parameterized-operating-binding.json']),
               numerical_relation_sha256=sha(files['numerical-relation.json']))
    files['role-contract.json'] = encoded(role_contract(cfg, t))
    spec = dict(schema='dram-see-v4-continuous-project-r1', name='v4-2d-'+role.lower(), role=role, execution_enabled=True,
        runner='original scripts/tcad.py', native_threads=1, native_cores=1, s2_geometry=cfg,
        steps=[dict(tool='sdevice', args=['device.cmd'], outputs=list(O.OUTPUTS))])
    files.update({'project.json': encoded(spec), 'controlled-request.json': encoded(r),
        'resource-policy.json': encoded(dict(schema='dram-see-v4-actual-resource-policy-r1', role=role,
            observation_only=True, imported_mesh_sha256=cfg['mesh_sha256'], resource_limits=None)),
        'task-authorization.json': encoded(dict(schema='dram-see-v4-current-user-authorization-r1', source='current_user_instruction',
            synthetic=False, role_ids=[role], instruction='原runner/owner/共享锁下进行70与80nm开发二维A0及明确h2/dt2；真实D2来源、20nm、20/200fF、neutral初始化、完整时钟和原判据不变。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',
            plan_sha256=D.file_sha(root/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md')))})
    for name in ('geometry_bridge.py', 'mesh_resource_guard.py', 'case_contract.py'):
        files[name] = (here/name).read_bytes()
    files.update(_runtime_bytes())
    files['generator-prepare_case.py'] = (here/'prepare_case.py').read_bytes()
    files['provenance.json'] = encoded(dict(schema='dram-see-v4-parameterized-operating-input-provenance-r1',
        run_id=run_id, role=role, producer_run_id=cfg['producer_run_id'], complete_original_D2_archives_retained=True,
        template_run_id=O.TEMPLATE_RUN, full_old_A0_result_archive_copied=False,
        operation_timing_sha256=sha(selected_raw), numerical_relation_sha256=cfg['numerical_relation_sha256'],
        new_time_or_voltage_selected_by_generator=False, source_configured=False, physics_cards_unchanged=True,
        selected_D2_mesh_unchanged=True, neutral_common_initialization=True, target_bit_preset=False, thresholds_changed=False,
        native_run_completed=False, native_A0_functionality_qualified=False, mesh_or_time_convergence_qualified=False, training_admitted=False))
    hashes = {name: sha(raw) for name, raw in files.items()}
    for name, digest in bundle['exports'].items():
        require(name not in hashes or hashes[name] == digest, 'original D2 import collision: '+name)
        hashes[name] = digest
    files['input-manifest.json'] = encoded(dict(schema='dram-see-v4-continuous-inputs-r1', role_id=role, run_id=run_id, files_sha256=hashes))
    files['execution-context.json'] = encoded(dict(schema='dram-see-v4-continuous-run-context-r1', run_id=run_id, role_id=role,
        producer_run_id=cfg['producer_run_id'], synthetic=False, expected_runner_sha256=runner_sha,
        input_manifest_sha256=sha(files['input-manifest.json']), authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        bridge.geometry_write(target/name, raw)
    bridge.geometry_stage_reuse(target, cfg)
    bridge.geometry_admit(target, spec, runner_sha)
    return dict(project=str(target), run_id=run_id, role_id=role, producer_run_id=cfg['producer_run_id'],
        mesh_sha256=cfg['mesh_sha256'], operation_timing_sha256=sha(selected_raw), numerical_relation_sha256=cfg['numerical_relation_sha256'],
        input_manifest_sha256=sha(files['input-manifest.json']), expected_runner_sha256=runner_sha,
        native_submissions=0, native_run_completed=False, native_A0_functionality_qualified=False, mesh_or_time_convergence_qualified=False)
