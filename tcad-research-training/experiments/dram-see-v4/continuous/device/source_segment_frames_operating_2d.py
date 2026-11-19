"""Explicit unique-source-segment-frame A0 input version, Python 3.6.

No native launcher. Actual D2 source verification is delegated to fixed ed336;
only the new output protocol transforms fixed O97's pure rendered Plot names.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import tarfile
sys.dont_write_bytecode = True

BRANCH = 'dram-see-v4-source-segment-frames-operating-2d-r1'
DIMENSION_BRANCH = 'dram-see-v4-parameterized-d2-source-r1'
REQUEST_SCHEMA = 'dram-see-v4-source-segment-frames-operating-request-r1'
SOURCE_BINDING_SCHEMA = 'dram-see-v4-parameterized-d2-source-binding-r1'
RELATION_SCHEMA = 'dram-see-v4-2d-numerical-relation-r1'
PARENT_SHA = 'ed3363e8891dd261c29508f7fab3d78e9ef3ab10f8687db60ac83494723bfe65'
PROTOCOL_SHA = '311065aa132d66b1f2657c936f7a0503985976ce2e61a621555bd90763c7fec5'
O_SHA = '97a5ea8cf6fb64bdfe345adaf09f4aa8f222b8b443d84819fd64c0f447e937a5'
D2_SHA = 'c09b52ad56fcdf7e22dfb70ce750b04fd9fa383e1bda8a68ac9121ed768055cd'
CLOCK_SHA = 'bf5d9a8c5520eda054ecadd14fa4fc06f2f3b7296f16483e5ded02ff20ab4387'
METRICS_SHA = '0083e300fd1242d77616597f7a47e075386fff36d991070dd662b414e6f97bc2'
LEGACY_SHA = '14681b6fae30bce49a8b1063b3f8abd7e790e51c6afe58f74da094cd574b2d6e'
RUNTIME_FILES = ('parameterized_operating_2d.py','two_dimensional.py','operating_transient_2d.py',
    'native_transient_clock.py','operating_metrics_2d.py','legacy-circuit-metrics.py',
    'source_segment_frames_protocol_2d.py','source_segment_frames_operating_2d.py')
COMMON_REQUEST = {'schema','kind','dimension','gate_top_depth_nm','sn_junction_depth_nm',
                  'effective_width_nm','variant','base_d2_source_run'}
A0_REQUEST = COMMON_REQUEST | {'stored_bit','source_case','d2_source_run','a0_template_project',
    'operation_timing_file','operation_timing_sha256','base_operation_timing_file',
    'base_operation_timing_sha256','operation_evidence_files'}
FROZEN_RESULT_KEYS = {'binding','report','source_cfg','dimensional_contract','operation_timing',
    'operating_binding','source_spec','role_contract','numerical_relation','source_frame_protocol'}
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


class BytesReader:
    """Small pure payload reader. Large original files stay in file-backed readers."""
    def __init__(self, values):
        self.values = values
    def read(self, name):
        return self.values[name]
    def digest(self, name):
        return sha(self.values[name])


def parent_api():
    return local_module('parameterized_operating_2d.py', PARENT_SHA)

def protocol_api():
    return local_module('source_segment_frames_protocol_2d.py', PROTOCOL_SHA)

def source_bundle(project, cfg, execution=None):
    return parent_api().source_bundle(project, cfg, execution)

def _verify_sources(reader, cfg):
    return parent_api()._verify_sources(reader, cfg)

def dimensional_contract(binding):
    return parent_api().dimensional_contract(binding)

def verify_template(reader):
    return parent_api().verify_template(reader)

def _runtime_bytes():
    result = parent_api()._runtime_bytes()
    require(sha(result['parameterized_operating_2d.py']) == PARENT_SHA, 'fixed D2 verifier changed')
    for name in RUNTIME_FILES[-2:]:
        path = Path(__file__).with_name(name)
        require(path.is_file() and not path.is_symlink(), 'missing new fixed local runtime '+name)
        raw = path.read_bytes()
        if name == 'source_segment_frames_protocol_2d.py':
            require(sha(raw) == PROTOCOL_SHA, 'explicit output protocol implementation differs')
        result[name] = raw
    require(tuple(result) == RUNTIME_FILES, 'closed source-frame runtime set differs')
    return result

def _verify_runtime(reader):
    for name, raw in _runtime_bytes().items():
        require(reader.digest(name) == sha(raw), 'frozen explicit runtime differs: '+name)



def validate_request(request):
    require(isinstance(request, dict) and request.get('schema') == REQUEST_SCHEMA, 'explicit source-segment-frame request required')
    require(request.get('kind') == 'transient', 'only source-frame A0 transient kind is supported')
    dc = False
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
    return 'B2D-A0-source-segment-frames-r1-{}-b{}'.format(r['variant'], r['stored_bit'])


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
    timing = obj(selected_timing_raw)
    protocol = protocol_api().plan(timing, sha(selected_timing_raw))
    old_rendered = operation_api().render(template_deck, bit, timing)
    return protocol_api().replace_plot_prefixes(old_rendered, timing, protocol)



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
    files['source-frame-protocol.json'] = encoded(protocol_api().plan(t, sha(selected_raw)))
    source = dict(schema='dram-see-v4-2d-source-segment-frames-control-source-spec-r1', role='CONTROL', source_case='A0',
        source_configured=False, structural_source_absence=True, dimension=2, stored_bit=r['stored_bit'],
        numerical_variant=r['variant'], gate_top_depth_nm=r['gate_top_depth_nm'], sn_junction_depth_nm=87,
        operation_timing_sha256=sha(selected_raw), numerical_relation_sha256=sha(files['numerical-relation.json']),
        dimensional_contract_sha256=sha(shared['dimensional-contract.json']),
        physics_manifest_sha256=sha(shared['physics-manifest.json']), particle_source_qualified=False)
    files['source-spec.json'] = encoded(source)
    files['source-contract.json'] = encoded(dict(schema='dram-see-v4-2d-source-segment-frames-structural-control-r1',
        source_configured=False, source_dimension=2, structural_source_absence=True,
        source_field_absence='structural absence, never measured zero', operation_timing_sha256=sha(selected_raw),
        native_observation_window_s=t['native_observation_window_s'], mathematical_source_window_s=t['mathematical_source_window_s'],
        source_epoch_s=t['source_epoch_s'], native_source_qualified=False, native_A0_functionality_qualified=False))
    files['functional-criteria.json'] = encoded(dict(schema='dram-see-v4-2d-source-segment-frames-functional-criteria-r1',
        operation_timing_sha256=sha(selected_raw), implementation_sha256=METRICS_SHA,
        criteria=O.metrics_api().criteria(), thresholds_changed=False))
    files['numerical-method.json'] = encoded(dict(schema='dram-see-v4-2d-source-segment-frames-numerics-r1',
        original_numerical_method=obj(template['numerical-method.json']), original_numerical_sha256=sha(template['numerical-method.json']),
        original_method_source_is_historical_not_current_producer=True, actual_producer_run_id=source_binding['producer_run_id'],
        diagnostic_output=['CNormPrint', 'PrintRhsPerEquation'], algorithm_or_convergence_criteria_changed=False,
        numerical_relation_sha256=sha(files['numerical-relation.json']), actual_native_diagnostic_syntax_verified=False))
    files['parameter-binding.json'] = encoded(dict(schema='dram-see-v4-active-parameters-r1', base_file='physics.par',
        base_sha256=sha(shared['physics.par']), source_file=None, source_sha256=None, source_physics_file=None,
        source_physics_sha256=None, active_file='physics.par', active_sha256=sha(shared['physics.par']), aggregation='base_only'))
    binding = dict(schema='dram-see-v4-source-segment-frames-operating-binding-r1', branch_id=BRANCH,
        stored_bit=r['stored_bit'], numerical_variant=r['variant'], gate_top_depth_nm=r['gate_top_depth_nm'],
        producer_run_id=source_binding['producer_run_id'], d2_source_binding_sha256=sha(encoded(source_binding)),
        template_run_id=O.TEMPLATE_RUN, template_manifest_sha256=O.TEMPLATE_MANIFEST_SHA,
        operation_timing_sha256=sha(selected_raw), base_operation_timing_sha256=sha(base_raw),
        numerical_relation_sha256=sha(files['numerical-relation.json']), gate_high_V=t['voltage_levels_V']['gate_high_V'],
        dimensional_contract_sha256=sha(shared['dimensional-contract.json']), verifier_sha256=d2_api().file_sha(__file__),
        clock_sha256=CLOCK_SHA, metrics_sha256=METRICS_SHA, legacy_helper_sha256=LEGACY_SHA,
        source_frame_protocol_sha256=sha(files['source-frame-protocol.json']), protocol_implementation_sha256=PROTOCOL_SHA,
        original_renderer_sha256=O_SHA, physical_deck_changes='only source Plot prefixes',
        files_sha256={name: sha(raw) for name, raw in files.items()}, physics_cards_unchanged=True,
        selected_D2_mesh_unchanged=True, native_run_completed=False, native_A0_functionality_qualified=False,
        mesh_or_time_convergence_qualified=False, scientific_evidence_verified=False, training_admitted=False)
    files['source-segment-frames-operating-binding.json'] = encoded(binding)
    return files


def role_contract(cfg, timing):
    return dict(schema='dram-see-v4-2d-source-segment-frames-control-role-r1', role=cfg['role_id'], dimension=2, case='A0',
        stored_bit=cfg['stored_bit'], numerical_variant=cfg['numerical_variant'], gate_top_depth_nm=cfg['gate_top_depth_nm'],
        sn_junction_depth_nm=87, source_configured=False, source_dimension=2, effective_width_nm=20,
        area_factor=.02, Cstore_fF=20, Cbl_fF=200, gate_high_V=timing['voltage_levels_V']['gate_high_V'],
        operation_timing_sha256=cfg['operation_timing_sha256'], base_operation_timing_sha256=cfg['base_operation_timing_sha256'],
        numerical_relation_sha256=cfg['numerical_relation_sha256'],
        source_frame_protocol_sha256=cfg['source_frame_protocol_sha256'],
        source_segment_frames_operating_binding_sha256=cfg['source_segment_frames_operating_binding_sha256'],
        dimensional_contract_sha256=cfg['dimensional_contract_sha256'], producer_run_id=cfg['producer_run_id'],
        mesh_sha256=cfg['mesh_sha256'], actual_read_WL_plateau_s=[timing['read_rise_window_s'][1], timing['read_fall_window_s'][0]],
        read_scoring_window_s=timing['read_window_s'], source_observation_window_s=timing['native_observation_window_s'],
        full_physical_window_s=timing['simulation_window_s'], native_syntax_verified=False,
        native_A0_functionality_qualified=False, mesh_or_time_convergence_qualified=False,
        response_admission='Actual two-bit clocks, unchanged functional/KCL and separate field/refinement evidence remain required')


def verify_frozen(reader, cfg):
    """Exact ten-key public result; no local path or archived code execution."""
    require(cfg.get('source_segment_frames_branch') == BRANCH and cfg.get('mode') == 'reuse', 'explicit new A0 branch required')
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
            and cfg.get('source_segment_frames_operating_binding_sha256') == reader.digest('source-segment-frames-operating-binding.json')
            and cfg.get('numerical_relation_sha256') == reader.digest('numerical-relation.json'), 'frozen role/relation identity differs')
    local_module('native_transient_clock.py', CLOCK_SHA)._deck(reader.read('device.cmd'))
    result.update(operation_timing=t, operating_binding=obj(expected['source-segment-frames-operating-binding.json']),
                  source_spec=obj(expected['source-spec.json']), role_contract=role,
                  numerical_relation=obj(expected['numerical-relation.json']),
                  source_frame_protocol=obj(expected['source-frame-protocol.json']))
    require(cfg.get('source_frame_protocol_sha256') == sha(expected['source-frame-protocol.json']), 'frame protocol binding differs')
    protocol_api().observation_windows(reader.read('device.cmd'), t, result['source_frame_protocol'])
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
        'rendered-operation-timing.json', 'numerical-relation.json', 'source-segment-frames-operating-binding.json',
        'initialization-contract.json', 'source-spec.json', 'source-contract.json', 'functional-criteria.json',
        'numerical-method.json', 'parameter-binding.json', 'source-frame-protocol.json'} | {'operation-template/'+n for n in operation_api().TEMPLATE_FILES}
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
    D = d2_api(); O = operation_api(); bridge = local_module('geometry_bridge.py')
    require(hasattr(bridge, 'geometry_source_segment_frames_module'), 'new original-runner bridge route not integrated; no input directory created')
    require(O.plain_name(run_id) and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id, 'new nonfixture run ID required')
    here = Path(__file__).resolve().parent; root = here.parents[3]
    runner = Path(runner or root/'scripts/tcad.py').resolve()
    require(runner == (root/'scripts/tcad.py').resolve() and runner.is_file(), 'original scripts/tcad.py required')
    allowed = (root/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/source-segment-frames-a0-implementation-r1').resolve()
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
        source_segment_frames_branch=BRANCH, role_id=role, run_id=run_id, producer_run_id=name_of(r['d2_source_run']),
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
    cfg.update(source_segment_frames_operating_binding_sha256=sha(files['source-segment-frames-operating-binding.json']),
               numerical_relation_sha256=sha(files['numerical-relation.json']),
               source_frame_protocol_sha256=sha(files['source-frame-protocol.json']))
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
    files['provenance.json'] = encoded(dict(schema='dram-see-v4-source-segment-frames-operating-input-provenance-r1',
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
        source_frame_protocol_sha256=cfg['source_frame_protocol_sha256'], status='PREPARED_NOT_SUBMITTED',
        native_submissions=0, native_run_completed=False, native_A0_functionality_qualified=False, mesh_or_time_convergence_qualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = prepare(obj(args.request.read_bytes()), args.run_id, output=args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, ArithmeticError, tarfile.TarError) as exc:
        print(json.dumps(dict(status='REFUSED', error=str(exc)), ensure_ascii=False)); return 2

if __name__ == '__main__':
    raise SystemExit(main())
