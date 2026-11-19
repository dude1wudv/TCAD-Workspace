"""One explicit native-alpha suffix from its real matched A0 saved state.

Python 3.6 guest closure; no scheduler. The original full alpha and A0 identities
remain nested evidence, never a relabelled new run or a fabricated time prefix.
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
HERE = Path(__file__).resolve().parent
BRANCH = 'dram-see-v4-parameterized-alpha-restored-suffix-2d-r1'
REQUEST_SCHEMA = 'dram-see-v4-parameterized-alpha-restart-request-r1'
BINDING_SCHEMA = 'dram-see-v4-alpha-restored-suffix-binding-r1'
SCOPE = 'RESTORED_ALPHA_SUFFIX_FROM_MATCHED_A0'
ROLE = 'B2D-Aalpha-restored-suffix-r1-main-b1'
PREFIX = 'reference-alpha-bindings/'
TRIPLE = ('manifest.json', 'results.tar', 'inputs.tar')
START_LITERAL = '7.6098400000000006e-08'
END_LITERAL = '8.8199999999999996e-08'
START_S, END_S = float(START_LITERAL), float(END_LITERAL)
TIMING_SHA = '78ba3c4258aa443b8a8ec76b9808eb3aa96df6427f3ee8576648afb9e222187b'
FIXED = {
    'parameterized_a0_restart_2d.py': '825a0229cdfbf07effc32344a0d8f66459babf0069347c469b00969640e00a9d',
    'parameterized_alpha_native_partition_2d.py': 'f94ee5fad28033886d48dd19a7954952e7cec05e1df401693512ba4ba6618fc3',
}
ORIGINAL_ALPHA = dict(
    run_id='20261020T033558Z-v4-2d-alpha-g80-2p4v-e5-theta0-native-partition-main-b1-r1',
    manifest='0fe8584efb81746cdfd5d388f725fa7b1cebcfac6954281b6b83e4de62a93237',
    results='9409d993e95b22a34995c6c3a00806dcc3f44d80d65f964d00a435f7eb46f1e7',
    inputs='82a6a46753b08881cbf64865e1365954f27ee0b01bfb4cf03207f56edcf9e0fd')
REQUEST_FIELDS = {
    'schema', 'kind', 'dimension', 'gate_top_depth_nm', 'sn_junction_depth_nm',
    'gate_high_V', 'effective_width_nm', 'stored_bit', 'variant', 'source_case',
    'particle', 'energy_MeV', 'theta_deg', 'phi_deg', 'amplitude',
    'original_alpha_run', 'original_a0_run', 'snapshot_prefix', 'restart_time_s',
    'final_time_s', 'operation_timing_sha256'}
FROZEN_KEYS = {
    'binding', 'report', 'source_cfg', 'dimensional_contract', 'operation_timing',
    'alpha_restart_binding', 'source_spec', 'role_contract', 'original_alpha_cfg',
    'original_alpha_frozen', 'original_alpha_complete_clock', 'original_a0_complete_clock',
    'original_a0_full_metrics', 'original_a0_reader_identity', 'pre_restart_source_tail'}


def require(ok, message):
    if not ok:
        raise ValueError('Alpha restored suffix: ' + message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf8')


def obj(raw):
    value = json.loads(raw.decode('utf8'))
    require(isinstance(value, dict), 'JSON object required')
    return value


def fixed(name):
    require(name in FIXED, 'unknown local dependency')
    path = HERE / name
    require(path.is_file() and not path.is_symlink(), 'fixed dependency missing/linked: ' + name)
    raw = path.read_bytes()
    require(sha(raw) == FIXED[name], 'fixed dependency changed: ' + name)
    spec = importlib.util.spec_from_file_location('_alpha_restart_' + name.replace('.', '_'), str(path))
    value = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), 'exec'), value.__dict__)
    return value


def a0():
    return fixed('parameterized_a0_restart_2d.py')


def alpha():
    return fixed('parameterized_alpha_native_partition_2d.py')


def runtime_bytes():
    result = alpha()._runtime_bytes()
    for name, raw in a0().runtime_bytes().items():
        require(name not in result or result[name] == raw, 'closed runtime collision')
        result[name] = raw
    result[Path(__file__).name] = Path(__file__).read_bytes()
    return result


def validate_request(request):
    require(isinstance(request, dict) and set(request) == REQUEST_FIELDS,
            'closed explicit alpha restart request required')
    r = copy.deepcopy(request)
    expected = dict(schema=REQUEST_SCHEMA, kind='transient', dimension=2,
        gate_top_depth_nm=80, sn_junction_depth_nm=87, gate_high_V=2.4, effective_width_nm=20,
        stored_bit=1, variant='main', source_case='Aalpha', particle='alpha',
        energy_MeV=5, theta_deg=0, phi_deg=180, amplitude=1.0,
        snapshot_prefix='source_window_0000', restart_time_s=START_S,
        final_time_s=END_S, operation_timing_sha256=TIMING_SHA)
    require(all(r[k] == v and type(r[k]) is type(v) for k, v in expected.items()),
            'only the explicit g80/E5/theta0/2.4V/main/bit1 absolute suffix is implemented')
    for name, expected_run in (
        ('original_alpha_run', ORIGINAL_ALPHA['run_id']),
        ('original_a0_run', a0().ORIGINALS[1]['run_id'])):
        require(isinstance(r[name], str) and Path(r[name]).name == expected_run,
                'wrong actual original/bit: ' + name)
    return r


def role_id(request):
    validate_request(request)
    return ROLE


def render(original_alpha_deck, original_a0_deck, original_include):
    """Exact original A0 suffix renderer plus the unchanged active alpha source."""
    A, R = alpha(), a0()
    require(A.source_free_deck(original_alpha_deck, original_include) == original_a0_deck,
            'full alpha is not the exact real matched A0 plus source')
    bare, a0_report = R.render(original_a0_deck)
    value = A.render_signal(bare, original_include)
    require(A.source_free_deck(value, original_include) == bare, 'source stripping changed suffix')
    marker = (' Transient(InitialTime=' + START_LITERAL + ' FinalTime=').encode('ascii')
    require(original_alpha_deck.count(marker) == value.count(marker) == 1,
            'original absolute suffix marker ambiguous')
    suffix = original_alpha_deck[original_alpha_deck.index(marker):]
    require(value[value.index(marker):] == suffix, 'actual alpha suffix Solve/numerics changed')
    require(value.count(R.LOAD.encode('utf8')) == 1
            and b' Set(sn=' not in value and b' Unset(' not in value,
            'Load must replace initialization, not reset its state')
    return value, dict(schema='dram-see-v4-alpha-suffix-render-r1',
        original_alpha_deck_sha256=sha(original_alpha_deck),
        original_a0_deck_sha256=sha(original_a0_deck),
        source_include_sha256=sha(original_include), rendered_deck_sha256=sha(value),
        source_free_suffix_sha256=sha(bare), original_alpha_suffix_sha256=sha(suffix),
        original_a0_renderer=a0_report, source_and_diagnostics_unchanged=True,
        time_remapped=False, original_prefix_fabricated=False, fresh_static_solve=False,
        original_early_write_reexecuted=False, native_Load_verified=False)


def pre_restart_tail(projected):
    """One-sided analytic time mass; reuse the fixed spatial ledger, no reintegration."""
    contract, ledger = projected['contract'], projected['ledger']['refined']
    epoch = contract['request']['epoch_s']
    sigma = contract['mapping']['sigma_s']
    require(epoch == 7.61e-8 and sigma == 2e-13
            and contract['full_simulation_window_s'] == [0.0, END_S]
            and contract['physical_time_tail_truncated'] is False, 'original source timing differs')
    prezero = .5 * math.erfc(epoch / (math.sqrt(2.0) * sigma))
    before = .5 * math.erfc((epoch - START_S) / (math.sqrt(2.0) * sigma))
    mass = before - prezero
    require(math.isfinite(mass) and 0 < mass < 1, 'nonzero finite original pre-load tail required')
    return dict(schema='dram-see-v4-alpha-restart-preload-tail-r1',
        source_epoch_s=epoch, sigma_s=sigma, restart_time_s=START_S,
        mathematical_full_original_window_s=[0.0, END_S], omitted_simulated_interval_s=[0.0, START_S],
        formula='0.5*erfc((epoch-start)/(sqrt(2)*sigma))-0.5*erfc(epoch/(sqrt(2)*sigma))',
        one_sided_all_real_before_restart_mass=before,
        prezero_mass_float64=prezero, prezero_underflow_is_not_structural_absence=True,
        original_positive_time_before_restart_mass=mass,
        finite_response_Si_pre_restart_input_charge_fC=ledger['response_silicon_all_time_fC'] * mass,
        declared_all_transverse_pre_restart_input_charge_fC=
            ledger['declared_axial_all_transverse_all_time_fC'] * mass,
        full_original_finite_Si_all_time_fC=ledger['response_silicon_all_time_fC'],
        strictly_zero=False, native_measurement=False, original_source_tables_truncated=False,
        tail_renormalized=False, charge_compensation_added=False,
        alpha_prefix_state_loaded=False, actual_loaded_state='original matched A0',
        predicted_electrical_equivalence=False,
        interpretation='Missing pre-load alpha history is explicit; only future actual suffix comparison can test its electrical effect')


def _reference(reader, inputs, manifest_raw):
    """Actual full-alpha record and its original matched A0; no role rewriting."""
    A, R = alpha(), a0()
    D = A.dimensional()
    manifest = obj(manifest_raw)
    require(sha(manifest_raw) == ORIGINAL_ALPHA['manifest']
            and manifest['run_id'] == ORIGINAL_ALPHA['run_id']
            and manifest['results_sha256'] == ORIGINAL_ALPHA['results']
            and manifest['inputs_archive_sha256'] == ORIGINAL_ALPHA['inputs'],
            'complete original full-alpha triple differs')
    A.alpha()._collection(reader, manifest, inputs, D)
    cfg = obj(reader.read('project.json'))['s2_geometry']
    require(cfg.get('role_id') == 'B2D-Aalpha-native-partition-r1-main-b1'
            and cfg.get('run_id') == ORIGINAL_ALPHA['run_id'], 'original full alpha role differs')
    frozen = A.verify_frozen(reader, cfg)
    require(frozen['matched_a0']['run_id'] == R.ORIGINALS[1]['run_id']
            and frozen['operation_timing']['source_epoch_s'] == 7.61e-8
            and reader.digest('operation-timing.json') == TIMING_SHA, 'wrong original matched A0/time')
    clock = A.baseline_api().runtime_module('native_transient_clock.py').audit(
        *(reader.read(n) for n in ('circuit.plt', 'access_device.plt', 'transient_des.log', 'device.cmd')))
    with reader.stream(A.A0_PREFIX + 'results.tar') as sr, reader.stream(A.A0_PREFIX + 'inputs.tar') as si:
        with tarfile.open(fileobj=sr, mode='r:*') as ar, tarfile.open(fileobj=si, mode='r:*') as ai:
            control = D.ArchiveReader(ar)
            a0_source = R._original(control, D.ArchiveReader(ai),
                reader.read(A.A0_PREFIX + 'manifest.json'), 1)
            require(A.source_free_deck(reader.read('device.cmd'), reader.read('heavyion.physics.inc')) ==
                    control.read('device.cmd'), 'full original source/control deck mismatch')
            states = {'restart-state/' + name: control.read(name) for name in R.PAIR}
            a0_device = control.read('device.cmd')
    return dict(cfg=cfg, frozen=frozen, manifest=manifest, complete_clock=clock,
                a0_source=a0_source, state_files=states, a0_device=a0_device,
                tail=pre_restart_tail(frozen['projection']))


def _root_files(reader, source, request):
    A, R = alpha(), a0()
    deck, render_report = render(reader.read('device.cmd'), source['a0_device'],
                                  reader.read('heavyion.physics.inc'))
    names = set(A.SHARED) | set(A.dimensional().SHARED_INPUTS) | {
        'cell_msh.tdr', 'cell_msh.log', 'd2-source-binding.json', 'source-contract.json',
        'source-time-contract.json', 'source.par', 'run-parameters.par', 'parameter-binding.json',
        'heavyion.physics.inc', 'heavyion.plot.inc', 'heavyion.currentplot.inc',
        'native-representation.json'}
    names.update(source['frozen']['binding']['original_files'])
    names.update('operation-selection/' + n for n in
                 source['frozen']['operation_timing']['selection_provenance']['references'])
    files = {n: reader.read(n) for n in sorted(names)}
    original_members = {n: dict(sha256=sha(v), size_bytes=len(v)) for n, v in files.items()}
    binding = dict(
        schema=BINDING_SCHEMA, branch_id=BRANCH, result_scope=SCOPE,
        verifier_file=Path(__file__).name, verifier_sha256=sha(Path(__file__).read_bytes()),
        request_sha256=sha(encoded(request)), stored_bit=1,
        original_alpha_three_files={n: ORIGINAL_ALPHA[n.split('.')[0]] for n in TRIPLE},
        original_alpha_run_id=ORIGINAL_ALPHA['run_id'],
        original_alpha_role=source['cfg']['role_id'],
        original_alpha_input_manifest_sha256=reader.digest('input-manifest.json'),
        original_alpha_clock_sha256=sha(encoded(source['complete_clock'])),
        original_alpha_frozen_identity=source['frozen']['alpha_binding'],
        original_A0=R._record(source['a0_source']),
        original_A0_nested_three_files={n: dict(sha256=reader.digest(A.A0_PREFIX + n),
                                               size_bytes=reader.size(A.A0_PREFIX + n)) for n in TRIPLE},
        original_input_members=original_members, render=render_report,
        restart_window_s=[START_S, END_S], full_original_window_s=[0.0, END_S],
        source_configured=True, original_preload_tail=source['tail'],
        native_Load_verified=False, electrical_suffix_equivalence_verified=False,
        carrier_state_restoration_verified=False, original_early_alpha_write_reexecuted=False,
        full_alpha_qualified=False, source_field_qualified=False,
        scientific_qualified=False, training_admitted=False,
        criteria=dict(voltage_difference_V=1e-5, charge_difference_fC=1e-4))
    source_spec = dict(
        schema='dram-see-v4-alpha-restored-suffix-source-spec-r1', particle='alpha',
        role='SIGNAL', source_case='Aalpha', dimension=2, stored_bit=1, source_configured=True,
        numerical_variant='main', gate_top_depth_nm=80, energy_MeV=5, theta_deg=0, phi_deg=180,
        amplitude=1.0, effective_width_nm=20, result_scope=SCOPE,
        active_suffix_window_s=[START_S, END_S], original_full_source_window_s=[0.0, END_S],
        source_epoch_s=7.61e-8, source_contract_sha256=sha(files['source-contract.json']),
        source_time_contract_sha256=sha(files['source-time-contract.json']),
        native_include_sha256=sha(files['heavyion.physics.inc']),
        native_parameter_sha256=sha(files['source.par']),
        native_representation_sha256=sha(files['native-representation.json']),
        native_renderer_sha256=A.RENDERER_SHA,
        alpha_restart_binding_sha256=sha(encoded(binding)), native_source_qualified=False)
    role_contract = dict(
        schema='dram-see-v4-alpha-restored-suffix-role-r1', role=ROLE, stored_bit=1,
        dimension=2, numerical_variant='main', source_case='Aalpha', source_configured=True,
        result_scope=SCOPE, effective_width_nm=20, Cstore_fF=20, Cbl_fF=200,
        operation_timing_sha256=TIMING_SHA, restart_window_s=[START_S, END_S],
        original_alpha_run_id=ORIGINAL_ALPHA['run_id'],
        actual_load_source_A0_run_id=R.ORIGINALS[1]['run_id'],
        original_early_write_counts_as_new_alpha_run=False)
    files.update(source['state_files'])
    files.update({
        'device.cmd': deck, 'controlled-request.json': encoded(request),
        'alpha-restart-binding.json': encoded(binding), 'restart-render.json': encoded(render_report),
        'restart-source-tail.json': encoded(source['tail']),
        'source-spec.json': encoded(source_spec), 'role-contract.json': encoded(role_contract),
        'restart-initialization.json': encoded(dict(
            schema='dram-see-v4-original-state-load-r1', scope=SCOPE,
            source_state='original matched A0 TDR and Circuit .sav', base_level_Load=True,
            systems=['Circuit', 'access'], initial_time_s=START_S,
            original_System_Set_sn_removed=True, no_static_equilibrium=True,
            rdrive_parameter_restored_from_saved_state_ohm=1e15, restored_parameter_verified=False)),
        'restart-time-contract.json': encoded(dict(
            schema='dram-see-v4-alpha-absolute-suffix-time-r1', result_scope=SCOPE,
            actual_suffix_window_s=[START_S, END_S], full_original_window_s=[0.0, END_S],
            original_timing_sha256=TIMING_SHA, original_suffix_solve_bytes_unchanged=True,
            omitted_prefix_not_fabricated=True, time_coordinate_transformed=False))})
    files.update(runtime_bytes())
    cfg = copy.deepcopy(source['cfg'])
    for name in ('run_id', 'source_branch', 'parameterized_alpha_binding_sha256'):
        cfg.pop(name, None)
    cfg.update(alpha_restart_branch=BRANCH, role_id=ROLE, result_scope=SCOPE,
               alpha_restart_binding_sha256=sha(files['alpha-restart-binding.json']),
               source_configured=True)
    return files, cfg, binding


def candidate_payload(request):
    """Fresh original proof; bytes/references only, not a formal project."""
    r = validate_request(request)
    A, R = alpha(), a0()
    D = A.dimensional()
    path = Path(r['original_alpha_run']).resolve()
    require(path.is_dir() and not path.is_symlink(), 'actual original alpha directory missing/linked')
    external = {}
    for name in TRIPLE:
        p = path / name
        actual = D.file_sha(p)
        require(actual == ORIGINAL_ALPHA[name.split('.')[0]], 'original alpha whole file changed: ' + name)
        external[PREFIX + name] = dict(path=str(p), sha256=actual, size_bytes=p.stat().st_size)
    a0_dir = Path(r['original_a0_run']).resolve()
    require(a0_dir.is_dir() and not a0_dir.is_symlink(), 'actual original A0 directory missing/linked')
    for name in TRIPLE:
        require(D.file_sha(a0_dir / name) == R.ORIGINALS[1][name.split('.')[0]],
                'explicit external matched A0 differs: ' + name)
    with tarfile.open(str(path / 'results.tar'), 'r:*') as ar, tarfile.open(str(path / 'inputs.tar'), 'r:*') as ai:
        reader = D.ArchiveReader(ar)
        source = _reference(reader, D.ArchiveReader(ai), (path / 'manifest.json').read_bytes())
        files, cfg, binding = _root_files(reader, source, r)
    return dict(files=files, cfg=cfg, external_files=external, binding=binding,
        manifest=dict(schema='dram-see-v4-alpha-suffix-candidate-payload-r1', result_scope=SCOPE,
            files_sha256={n: sha(v) for n, v in files.items()}, external_files=external,
            actual_A0_original_directory_verified=str(a0_dir),
            formal_project_created=False, native_submissions=0, native_Load_verified=False,
            source_field_qualified=False, scientific_qualified=False, training_admitted=False))


def verify_frozen(reader, cfg):
    r = validate_request(obj(reader.read('controlled-request.json')))
    require(cfg.get('alpha_restart_branch') == BRANCH and cfg.get('result_scope') == SCOPE
            and cfg.get('role_id') == ROLE and cfg.get('stored_bit') == 1
            and 'source_branch' not in cfg and 'a0_restart_branch' not in cfg
            and isinstance(cfg.get('run_id'), str) and cfg['run_id'] not in
                (ORIGINAL_ALPHA['run_id'], a0().ORIGINALS[1]['run_id']),
            'new explicit alpha suffix identity required')
    for name in TRIPLE:
        require(reader.digest(PREFIX + name) == ORIGINAL_ALPHA[name.split('.')[0]],
                'frozen complete reference alpha changed: ' + name)
    D = alpha().dimensional()
    with reader.stream(PREFIX + 'results.tar') as rs, reader.stream(PREFIX + 'inputs.tar') as ins:
        with tarfile.open(fileobj=rs, mode='r:*') as ar, tarfile.open(fileobj=ins, mode='r:*') as ai:
            original = D.ArchiveReader(ar)
            source = _reference(original, D.ArchiveReader(ai), reader.read(PREFIX + 'manifest.json'))
            files, expected_cfg, binding = _root_files(original, source, r)
    for name, raw in files.items():
        require(reader.digest(name) == sha(raw), 'frozen state/source/physical/runtime bytes differ: ' + name)
    expected_cfg['run_id'] = cfg['run_id']
    require(cfg == expected_cfg, 'suffix cfg is not the exact new original-bound object')
    frozen = alpha().parameterized()._verify_sources(reader, cfg)[0]
    frozen.update(operation_timing=source['frozen']['operation_timing'],
        alpha_restart_binding=binding, source_spec=obj(files['source-spec.json']),
        role_contract=obj(files['role-contract.json']), original_alpha_cfg=source['cfg'],
        original_alpha_frozen=source['frozen'], original_alpha_complete_clock=source['complete_clock'],
        original_a0_complete_clock=source['a0_source']['original_complete_clock'],
        original_a0_full_metrics=source['a0_source']['original_full_metrics'],
        original_a0_reader_identity=source['a0_source']['original_reader_identity'],
        pre_restart_source_tail=source['tail'])
    require(set(frozen) == FROZEN_KEYS, 'closed suffix reader interface changed')
    return frozen


def admit(project, spec, runner_sha, bridge):
    p = Path(project)
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(p.resolve()) and not (p / 'SYNTHETIC_NOT_NATIVE').exists(),
            'fixture cannot be admitted')
    A = alpha()
    D, O = A.dimensional(), A.operation()
    cfg = spec.get('s2_geometry', {})
    require(cfg.get('schema') == bridge.GEOMETRY_SCHEMA and cfg.get('mode') == 'reuse'
            and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
            and spec.get('execution_enabled') is True and spec.get('role') == cfg.get('role_id') == ROLE
            and spec.get('native_threads') == spec.get('native_cores') == 1
            and O.plain_name(cfg.get('run_id'))
            and spec.get('steps') == [dict(tool='sdevice', args=['device.cmd'], outputs=list(O.OUTPUTS))],
            'original serial SDevice execution contract differs')
    bridge.geometry_context(p, cfg, runner_sha)
    hashes = bridge.geometry_input_hashes(p)
    required = set(runtime_bytes()) | set(PREFIX + n for n in TRIPLE) | {
        'project.json', 'case_contract.py', 'geometry_bridge.py', 'mesh_resource_guard.py',
        'resource-policy.json', 'task-authorization.json', 'controlled-request.json',
        'device.cmd', 'alpha-restart-binding.json', 'restart-source-tail.json',
        'restart-render.json', 'restart-initialization.json', 'restart-time-contract.json',
        'source-spec.json', 'role-contract.json'}
    required.update('restart-state/' + n for n in a0().PAIR)
    require(required <= set(hashes), 'complete suffix manifest required')
    for name, digest in hashes.items():
        require(D.file_sha(bridge.geometry_path(p, name)) == digest, 'actual input changed: ' + name)
    verify_frozen(D.FolderReader(p), cfg)
    require(obj((p / 'input-manifest.json').read_bytes()).get('run_id') == cfg['run_id'],
            'input manifest run differs')
    require(obj((p / 'resource-policy.json').read_bytes()) == dict(
        schema='dram-see-v4-actual-resource-policy-r1', role=ROLE, observation_only=True,
        imported_mesh_sha256=cfg['mesh_sha256'], resource_limits=None), 'usage-only resource contract changed')
    return cfg


def prepare(request, run_id, runner=None, output=None):
    """Future root-owned original prepare; source/field approval is not a new gate."""
    r = validate_request(request)
    R, A = a0(), alpha()
    C, bridge = R._current_module('case_contract.py'), R._current_module('geometry_bridge.py')
    require(getattr(C, 'SCHEMA_2D_ALPHA_RESTART', None) == REQUEST_SCHEMA
            and hasattr(bridge, 'geometry_alpha_restart_module') and C.is_role(ROLE),
            'new dispatch is not integrated; no project created')
    D, O = A.dimensional(), A.operation()
    require(O.plain_name(run_id) and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id
            and run_id not in (ORIGINAL_ALPHA['run_id'], R.ORIGINALS[1]['run_id']), 'new native run ID required')
    root = HERE.parents[3]
    runner = Path(runner or root / 'scripts/tcad.py').resolve()
    require(runner == (root / 'scripts/tcad.py').resolve(), 'original runner only')
    allowed = root / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/alpha-restart-implementation-r1/projects'
    target = Path(output or allowed / run_id).resolve()
    require(allowed.resolve() in target.parents and target.name == run_id and not target.exists(),
            'new exclusive alpha suffix project required')
    payload = candidate_payload(r)
    files, cfg = payload['files'], payload['cfg']
    cfg['run_id'] = run_id
    runner_sha = D.file_sha(runner)
    spec = dict(schema='dram-see-v4-continuous-project-r1', name='v4-2d-' + ROLE.lower(),
        role=ROLE, execution_enabled=True, runner='original scripts/tcad.py', native_threads=1,
        native_cores=1, s2_geometry=cfg,
        steps=[dict(tool='sdevice', args=['device.cmd'], outputs=list(O.OUTPUTS))])
    files.update({
        'project.json': encoded(spec),
        'resource-policy.json': encoded(dict(schema='dram-see-v4-actual-resource-policy-r1',
            role=ROLE, observation_only=True, imported_mesh_sha256=cfg['mesh_sha256'], resource_limits=None)),
        'task-authorization.json': encoded(dict(schema='dram-see-v4-current-user-authorization-r1',
            source='current_user_instruction', synthetic=False, role_ids=[ROLE],
            instruction='沿原runner/owner/共享锁，以真实A0保存状态执行单个g80/E5/0deg/main/bit1绝对时钟α后缀；完整原件保留，不声明前段写入或科学资格。'))})
    for name in ('case_contract.py', 'geometry_bridge.py', 'mesh_resource_guard.py'):
        files[name] = (HERE / name).read_bytes()
    files['generator-prepare_case.py'] = (HERE / 'prepare_case.py').read_bytes()
    hashes = {n: sha(v) for n, v in files.items()}
    hashes.update({n: v['sha256'] for n, v in payload['external_files'].items()})
    files['input-manifest.json'] = encoded(dict(schema='dram-see-v4-continuous-inputs-r1',
        run_id=run_id, role_id=ROLE, files_sha256=hashes))
    files['execution-context.json'] = encoded(dict(schema='dram-see-v4-continuous-run-context-r1',
        run_id=run_id, role_id=ROLE, producer_run_id=cfg['producer_run_id'], synthetic=False,
        expected_runner_sha256=runner_sha, input_manifest_sha256=sha(files['input-manifest.json']),
        authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        bridge.geometry_write(target / name, raw)
    for name, value in payload['external_files'].items():
        src, dest = Path(value['path']), bridge.geometry_path(target, name)
        require(D.file_sha(src) == value['sha256'], 'external original changed before copy')
        dest.parent.mkdir(parents=True, exist_ok=True)
        with src.open('rb') as stream, dest.open('xb') as out:
            for block in iter(lambda: stream.read(1048576), b''):
                out.write(block)
        require(D.file_sha(dest) == value['sha256'], 'external original proof copy differs')
    bridge.geometry_admit(target, spec, runner_sha)
    return dict(project=str(target), run_id=run_id, role_id=ROLE, result_scope=SCOPE,
        input_manifest_sha256=sha(files['input-manifest.json']),
        alpha_restart_binding_sha256=cfg['alpha_restart_binding_sha256'],
        original_alpha_run_id=ORIGINAL_ALPHA['run_id'], actual_load_A0_run_id=R.ORIGINALS[1]['run_id'],
        native_submissions=0, native_Load_verified=False, source_field_qualified=False,
        electrical_suffix_equivalence_verified=False, scientific_qualified=False, training_admitted=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', required=True, help='new bytes manifest only; never a formal project')
    args = parser.parse_args()
    out = Path(args.output)
    require(not out.exists(), 'new output required')
    payload = candidate_payload(obj(Path(args.request).read_bytes()))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('xb') as stream:
        stream.write(encoded(payload['manifest']))
    print(json.dumps(dict(status='CANDIDATE_BYTES_ONLY_NOT_PREPARED', output=str(out),
                          source_tail=payload['binding']['original_preload_tail']), ensure_ascii=False))


if __name__ == '__main__':
    main()
