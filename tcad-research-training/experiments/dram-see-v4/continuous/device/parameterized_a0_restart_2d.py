"""Explicit original-state A0 suffix, g80/2.4 V/main only; Python 3.6.

No launcher. The callable prepare entry is for the original runner after the
separate dispatch patch is applied. candidate_payload only returns input bytes
and immutable external-file references. Saved state bytes are never generated.
"""
import argparse
import copy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tarfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BRANCH = 'dram-see-v4-parameterized-a0-restored-suffix-2d-r1'
REQUEST_SCHEMA = 'dram-see-v4-parameterized-a0-restart-request-r1'
BINDING_SCHEMA = 'dram-see-v4-a0-restored-suffix-binding-r1'
SCOPE = 'RESTORED_A0_SUFFIX'
START_LITERAL = '7.6098400000000006e-08'
END_LITERAL = '8.8199999999999996e-08'
START_S, END_S = float(START_LITERAL), float(END_LITERAL)
TIMING_SHA = '78ba3c4258aa443b8a8ec76b9808eb3aa96df6427f3ee8576648afb9e222187b'
PREFIX = 'reference-a0-bindings/'
PAIR = ('source_window_0000_access_des.tdr', 'source_window_0000_circuit_des.sav')
LOAD = ' Load(FilePrefix="restart-state/source_window_0000") { Circuit access }\n'
FIXED = {
    'parameterized_operating_2d.py': 'ed3363e8891dd261c29508f7fab3d78e9ef3ab10f8687db60ac83494723bfe65',
    'parameterized_baseline_2d.py': '8f9a759b26617fff6a416e8336fa57a56d36199d175959a6ed1ba1b49ccb89a2',
    'alpha_native_2d.py': '9ed322fdc16eb28bf99f82ca32f8b62c3a15219188aaadfd96c1882c1e7b77f7',
    'two_dimensional.py': 'c09b52ad56fcdf7e22dfb70ce750b04fd9fa383e1bda8a68ac9121ed768055cd',
}
ORIGINALS = {
    0: dict(run_id='20261019T193936Z-v4-2d-a0-g80-2p4v-main-b0-r1',
        manifest='30e236af5b99c9b274ce70ca3cc5d396b6f7ea3dfaef9bc454451518a4c220ed',
        results='22bb438493918fc280bf5b0ec4aa83cc75abdc8879e8acfc51f6dc7320dd8b3f',
        inputs='e443e64c1e90c4728487e5dcb8fee11260cf8f5ef7f9d88c60bfb7cfc2bb1972'),
    1: dict(run_id='20261019T193936Z-v4-2d-a0-g80-2p4v-main-b1-r1',
        manifest='84a55d7f91080689236fd27501208b3f48cf36c7107526caa2360a2a0a274d2d',
        results='e74408d365dbe396661660e79e399ddb13654fff246d82fc0411d8ac327b1fee',
        inputs='51ecade47846647b2118dbb15e611b3d7f4123c6498a4b3b68e4c663d9a8b246'),
}
TRIPLE = ('manifest.json', 'results.tar', 'inputs.tar')
FIELDS = {'schema', 'kind', 'dimension', 'gate_top_depth_nm', 'sn_junction_depth_nm',
          'gate_high_V', 'effective_width_nm', 'stored_bit', 'variant', 'source_case',
          'original_a0_run', 'snapshot_prefix', 'restart_time_s', 'final_time_s',
          'operation_timing_sha256'}


def require(ok, message):
    if not ok:
        raise ValueError('A0 restored suffix: '+message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False)+'\n').encode('utf-8')


def obj(raw):
    value = json.loads(raw.decode('utf-8'))
    require(isinstance(value, dict), 'JSON object required')
    return value


def local_path(name):
    require(name in FIXED, 'unknown fixed dependency')
    path = HERE/name
    if not path.exists() and name == 'parameterized_baseline_2d.py':
        path = HERE.parent/'data'/name
    return path


def fixed(name):
    path = local_path(name)
    require(path.is_file() and not path.is_symlink(), 'missing/linked local dependency '+name)
    raw = path.read_bytes()
    require(sha(raw) == FIXED[name], 'fixed dependency changed '+name)
    spec = importlib.util.spec_from_file_location('_a0_suffix_'+name.replace('.', '_'), str(path))
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def runtime_bytes():
    result = fixed('parameterized_operating_2d.py')._runtime_bytes()
    for name in FIXED:
        raw = local_path(name).read_bytes()
        require(sha(raw) == FIXED[name], 'runtime changed '+name)
        require(name not in result or result[name] == raw, 'runtime collision')
        result[name] = raw
    result[Path(__file__).name] = Path(__file__).read_bytes()
    return result


def validate_request(request):
    require(isinstance(request, dict) and set(request) == FIELDS, 'explicit closed request fields required')
    r = copy.deepcopy(request)
    expected = dict(schema=REQUEST_SCHEMA, kind='transient', dimension=2, gate_top_depth_nm=80,
        sn_junction_depth_nm=87, gate_high_V=2.4, effective_width_nm=20, variant='main',
        source_case='A0', snapshot_prefix='source_window_0000',
        restart_time_s=START_S, final_time_s=END_S, operation_timing_sha256=TIMING_SHA)
    require(all(r.get(k) == v and type(r[k]) is type(v) for k, v in expected.items()),
            'only explicit g80/SN87/2.4V/main/20nm A0 at the original suffix window is supported')
    require(type(r['stored_bit']) is int and r['stored_bit'] in (0, 1), 'integer bit0/1 required')
    require(isinstance(r['original_a0_run'], str) and Path(r['original_a0_run']).name ==
            ORIGINALS[r['stored_bit']]['run_id'], 'wrong original A0/bit; relabelling is forbidden')
    return r


def role_id(request):
    return 'B2D-A0-restored-suffix-r1-main-b'+str(validate_request(request)['stored_bit'])


def render(original_deck):
    """Preserve complete System/PWL and actual suffix bytes; no numerical edits."""
    text = original_deck.decode('utf-8')
    require(text.count('\nSolve {\n') == 1 and text.count(' Set(sn=0.6)\n') == 1,
            'original full A0 initialization shape differs')
    head, solve = text.split('\nSolve {\n')
    require('Load(' not in text and 'Save(' not in text and 'HeavyIon' not in text
            and 'OpticalGeneration' not in text, 'not the original no-particle A0 deck')
    clock = fixed('parameterized_baseline_2d.py').runtime_module('native_transient_clock.py')
    segments, change = clock._deck(original_deck)
    selected = [v for v in segments if Decimal(v['initial_literal']) == Decimal(START_LITERAL)]
    require(len(selected) == 1 and selected[0]['segment_index'] == 8
            and Decimal(segments[-1]['final_literal']) == Decimal(END_LITERAL),
            'original source snapshot phase/end differs')
    marker = ' Transient(InitialTime='+START_LITERAL+' FinalTime='
    require(solve.count(marker) == 1, 'snapshot literal not uniquely in original deck')
    suffix = solve[solve.index(marker):]
    require(not re.search(r'\b(?:Set|Unset|Load|Save)\s*\(', suffix), 'unexpected suffix state mutation')
    prefix = head.replace(' Set(sn=0.6)\n', '')+'\nSolve {\n'+LOAD+' Plot(FilePrefix="initial")\n'
    value = (prefix+suffix).encode('utf-8')
    return value, dict(schema='dram-see-v4-a0-suffix-render-r1',
        original_deck_sha256=sha(original_deck), rendered_deck_sha256=sha(value),
        unchanged_suffix_sha256=sha(suffix.encode('utf-8')), original_first_segment_index=8,
        original_segment_count=len(segments), suffix_segment_count=len(segments)-7,
        initial_time_literal=START_LITERAL, final_time_literal=END_LITERAL,
        load_statement=LOAD.strip(), load_systems=['Circuit', 'access'],
        system_change='remove only Set(sn=0.6); saved state restores floating SN and compact-model state',
        original_resistor_change=change, original_PWL_preserved=True,
        static_equilibrium_repeated=False, target_bit_preset=False, time_rebased=False,
        carrier_state_restoration_verified=False, native_Load_verified=False)


def _original(reader, inputs, manifest_raw, bit):
    """Fresh complete original collection and full-r13 reader replay, on host/guest."""
    D = fixed('two_dimensional.py'); B = fixed('parameterized_baseline_2d.py')
    manifest = obj(manifest_raw); expected = ORIGINALS[bit]
    require(sha(manifest_raw) == expected['manifest'] and manifest.get('run_id') == expected['run_id']
            and manifest.get('results_sha256') == expected['results']
            and manifest.get('inputs_archive_sha256') == expected['inputs'], 'original three-file identity mismatch')
    fixed('alpha_native_2d.py')._collection(reader, manifest, inputs, D)
    cfg = obj(reader.read('project.json'))['s2_geometry']
    require(cfg.get('stored_bit') == bit and cfg.get('gate_top_depth_nm') == 80
            and cfg.get('sn_junction_depth_nm') == 87 and cfg.get('gate_high_V') == 2.4
            and cfg.get('numerical_variant') == 'main' and cfg.get('effective_width_nm') == 20,
            'original physical bit/geometry/operation differs')
    require(reader.digest('operation-timing.json') == TIMING_SHA, 'original full timing differs')
    replay = B.audit_reader(reader, cfg)
    require(replay['metrics']['candidate_functional_pass'] is True, 'original full A0 five checks failed')
    clock = replay['clock']
    # The first snapshot is a zero-duration initial frame of actual segment 8.
    writes = [w for w in clock['writing_records'] if w['source_file'] == PAIR[0]]
    require(len(writes) == 1 and writes[0]['segment_index'] == 8 and writes[0]['attempt_index'] is None,
            'snapshot is not the original segment-initial native Writing')
    segment = clock['segments'][7]
    require(segment['start_actual_s'] == START_S, 'actual original snapshot time differs')
    log_lines = reader.read('transient_des.log').decode('utf-8').splitlines()
    sav_writes = [dict(log_line=i+1, text=line) for i, line in enumerate(log_lines)
                  if "Writing circuit '"+PAIR[1]+"'" in line]
    # Actual native text is preserved; accept only one explicit write of this exact sidecar.
    if not sav_writes:
        sav_writes = [dict(log_line=i+1, text=line) for i, line in enumerate(log_lines)
                      if PAIR[1] in line and 'Writing' in line and 'done' in line]
    require(len(sav_writes) == 1 and abs(sav_writes[0]['log_line']-writes[0]['writing_log_line']) <= 3,
            'original paired Circuit write missing or detached')
    members = {n: dict(sha256=reader.digest(n), size_bytes=reader.size(n)) for n in PAIR}
    require(all(v['size_bytes'] > 0 for v in members.values()), 'empty original snapshot member')
    sav = reader.read(PAIR[1])
    require(b'SLP_k_Save_State' in sav and b'SLP_k_CircuitNodes' in sav,
            'original Circuit saved-state signature missing')
    return dict(cfg=cfg, frozen=replay['frozen'], original_reader_identity=replay['identity'],
        original_complete_clock=clock, original_full_metrics=replay['metrics'],
        original_manifest=manifest, original_members=members,
        actual_snapshot=dict(time_s=START_S, time_literal=START_LITERAL, native_TDR_writing=writes[0],
            native_Circuit_writing=sav_writes[0], direct_TDR_timestamp_verified=False,
            binding='Original segment 8 initial Writing + full bf5 accepted clock + paired Circuit write'))


def _record(source):
    f = source['frozen']; cfg = source['cfg']
    return dict(run_id=cfg['run_id'], role_id=cfg['role_id'], stored_bit=cfg['stored_bit'],
        numerical_variant=cfg['numerical_variant'], mesh_sha256=cfg['mesh_sha256'],
        operation_timing_sha256=TIMING_SHA, physics_manifest_sha256=
        source['original_reader_identity']['physics_manifest_sha256'],
        d2_source_binding_sha256=cfg['d2_source_binding_sha256'],
        dimensional_contract_sha256=cfg['dimensional_contract_sha256'],
        complete_original_A0_functional_pass=source['original_full_metrics']['candidate_functional_pass'],
        complete_original_clock_verified=True, original_members=source['original_members'],
        actual_snapshot=source['actual_snapshot'], original_geometry_binding=f['binding'])


def contract(request, source, render_report):
    return dict(schema=BINDING_SCHEMA, branch_id=BRANCH, result_scope=SCOPE,
        verifier_file=Path(__file__).name, verifier_sha256=sha(Path(__file__).read_bytes()),
        stored_bit=request['stored_bit'], request_sha256=sha(encoded(request)),
        original_three_files={n: ORIGINALS[request['stored_bit']][n.split('.')[0]] for n in TRIPLE},
        original=_record(source), render=render_report, restart_window_s=[START_S, END_S],
        full_original_simulation_window_s=[0., END_S], source_configured=False,
        initial_time_is_absolute_physical_time=True, original_state_bytes_modified=False,
        original_prefix_native_rows_replayed_or_fabricated=False, native_Load_verified=False,
        carrier_state_restoration_verified=False, electrical_suffix_equivalence_verified=False,
        full_A0_qualified=False, particle_restart_qualified=False, scientific_qualified=False,
        training_admitted=False, criteria=dict(voltage_difference_V=1e-5, charge_difference_fC=1e-4),
        documentation=dict(version='W-2024.09', pages=[192, 193, 233, 234, 1776, 1788],
            scope='Solve base-level complete Circuit/access Load; explicit InitialTime in separate run'))


def _root_files(original, source, r):
    """Small original physics plus exact state; large original proofs stay references."""
    P = fixed('parameterized_operating_2d.py'); D = fixed('two_dimensional.py')
    deck, report = render(original.read('device.cmd'))
    binding = contract(r, source, report)
    names = tuple(D.SHARED_INPUTS)+('cell_msh.tdr', 'cell_msh.log', 'd2-source-binding.json',
        'dimensional-contract.json', 'operation-timing.json', 'base-operation-timing.json',
        'physics-manifest.json', 'functional-criteria.json')
    files = {n: original.read(n) for n in names}
    # Original D2 proof is immutable and independently checked by P._verify_sources.
    for n in source['frozen']['binding']['original_files']:
        # These nested producer archives are small compared with the full A0.
        files[n] = original.read(n)
    files.update({'restart-state/'+n: original.read(n) for n in PAIR})
    files.update({'device.cmd': deck, 'controlled-request.json': encoded(r),
        'restart-binding.json': encoded(binding), 'restart-render.json': encoded(report),
        'restart-initialization.json': encoded(dict(schema='dram-see-v4-original-state-load-r1',
            scope=SCOPE, source_state='paired original loadable TDR and Circuit .sav',
            base_level_Load=True, systems=['Circuit', 'access'], initial_time_s=START_S,
            original_System_Set_sn_removed=True, no_static_equilibrium=True,
            rdrive_parameter_restored_from_saved_state_ohm=1e15, restored_parameter_verified=False)),
        'numerical-method.json': encoded(dict(schema='dram-see-v4-a0-suffix-numerics-r1',
            time_method='BE', original_suffix_deck_sha256=report['unchanged_suffix_sha256'],
            actual_full_timing_sha256=TIMING_SHA, output_scope=SCOPE,
            original_segment_parameters_unchanged=True, all_rejected_attempts_retained=True)),
        'source-spec.json': encoded(dict(schema='dram-see-v4-a0-restored-suffix-source-spec-r1',
            particle=None, role='CONTROL', source_case='A0', source_configured=False,
            structural_source_absence=True, measured_generation_zero=False,
            stored_bit=r['stored_bit'], dimension=2, effective_width_nm=20, output_scope=SCOPE)),
    })
    files.update(runtime_bytes())
    cfg = copy.deepcopy(source['cfg'])
    for key in ('parameterized_operating_branch', 'parameterized_operating_binding_sha256',
                'numerical_relation_sha256'):
        cfg.pop(key, None)
    cfg.update(a0_restart_branch=BRANCH, role_id=role_id(r), result_scope=SCOPE,
        restart_binding_sha256=sha(files['restart-binding.json']), source_configured=False)
    files['role-contract.json'] = encoded(dict(schema='dram-see-v4-a0-restored-suffix-role-r1',
        role=cfg['role_id'], stored_bit=r['stored_bit'], dimension=2, numerical_variant='main',
        source_case='A0', source_configured=False, result_scope=SCOPE, effective_width_nm=20,
        Cstore_fF=20, Cbl_fF=200, operation_timing_sha256=TIMING_SHA,
        restart_window_s=[START_S, END_S], complete_original_A0_run_id=source['cfg']['run_id']))
    return files, cfg, binding


def candidate_payload(request):
    """Fresh original proof; return files/cfg/external_files, never a formal project."""
    r = validate_request(request); path = Path(r['original_a0_run']).resolve()
    require(not path.is_symlink(), 'linked original A0 directory')
    D = fixed('two_dimensional.py')
    expected = ORIGINALS[r['stored_bit']]
    external = {}
    for name in TRIPLE:
        p = path/name
        require(p.is_file() and not p.is_symlink(), 'missing/linked original '+name)
        digest = D.file_sha(p)
        require(digest == expected[name.split('.')[0]], 'original whole file changed '+name)
        external[PREFIX+name] = dict(path=str(p), sha256=digest, size_bytes=p.stat().st_size)
    with tarfile.open(str(path/'results.tar'), 'r:*') as results, tarfile.open(str(path/'inputs.tar'), 'r:*') as inputs:
        reader = D.ArchiveReader(results)
        source = _original(reader, D.ArchiveReader(inputs), (path/'manifest.json').read_bytes(), r['stored_bit'])
        files, cfg, binding = _root_files(reader, source, r)
    return dict(files=files, cfg=cfg, external_files=external, binding=binding,
        original_full_metrics=source['original_full_metrics'],
        original_complete_clock=source['original_complete_clock'],
        manifest=dict(schema='dram-see-v4-a0-suffix-candidate-payload-r1', result_scope=SCOPE,
            files_sha256={n:sha(v) for n, v in files.items()}, external_files=external,
            formal_project_created=False, native_submissions=0, native_Load_verified=False))


def verify_frozen(reader, cfg):
    """Known local source only; reconstruct root bytes from original three-file proof."""
    r = validate_request(obj(reader.read('controlled-request.json')))
    require(cfg.get('a0_restart_branch') == BRANCH and cfg.get('result_scope') == SCOPE
            and cfg.get('role_id') == role_id(r) and cfg.get('stored_bit') == r['stored_bit']
            and cfg.get('run_id') != ORIGINALS[r['stored_bit']]['run_id'],
            'restart identity must stay distinct from its original full A0')
    expected = ORIGINALS[r['stored_bit']]
    for name in TRIPLE:
        require(reader.digest(PREFIX+name) == expected[name.split('.')[0]], 'frozen original triple changed '+name)
    D = fixed('two_dimensional.py')
    with reader.stream(PREFIX+'results.tar') as rs, reader.stream(PREFIX+'inputs.tar') as ins:
        with tarfile.open(fileobj=rs, mode='r:*') as rt, tarfile.open(fileobj=ins, mode='r:*') as it:
            original = D.ArchiveReader(rt)
            source = _original(original, D.ArchiveReader(it), reader.read(PREFIX+'manifest.json'), r['stored_bit'])
            files, expected_cfg, binding = _root_files(original, source, r)
    for name, raw in files.items():
        require(reader.digest(name) == sha(raw), 'frozen actual source/physics/deck/runtime differs '+name)
    expected_cfg['run_id'] = cfg['run_id']
    require(cfg == expected_cfg, 'restart configuration differs from actual original condition')
    frozen = fixed('parameterized_operating_2d.py')._verify_sources(reader, cfg)[0]
    frozen.update(operation_timing=source['frozen']['operation_timing'], restart_binding=binding,
        source_spec=obj(files['source-spec.json']), role_contract=obj(files['role-contract.json']),
        original_full_metrics=source['original_full_metrics'],
        original_complete_clock=source['original_complete_clock'],
        original_reader_identity=source['original_reader_identity'])
    return frozen


def admit(project, spec, runner_sha, bridge):
    p = Path(project); cfg = spec.get('s2_geometry', {})
    require('UNIT_FIXTURE_NOT_NATIVE' not in str(p.resolve()) and not (p/'SYNTHETIC_NOT_NATIVE').exists(),
            'fixture cannot be admitted')
    D = fixed('two_dimensional.py'); O = fixed('parameterized_operating_2d.py').operation_api()
    require(cfg.get('schema') == bridge.GEOMETRY_SCHEMA and cfg.get('mode') == 'reuse'
            and cfg.get('synthetic') is False and cfg.get('execution_enabled') is True
            and spec.get('execution_enabled') is True and spec.get('role') == cfg.get('role_id')
            and spec.get('native_threads') == spec.get('native_cores') == 1
            and O.plain_name(cfg.get('run_id'))
            and spec.get('steps') == [dict(tool='sdevice', args=['device.cmd'], outputs=list(O.OUTPUTS))],
            'original single SDevice runner contract differs')
    bridge.geometry_context(p, cfg, runner_sha)
    hashes = bridge.geometry_input_hashes(p)
    required = set(runtime_bytes()) | set(PREFIX+n for n in TRIPLE) | {'project.json',
        'case_contract.py', 'geometry_bridge.py', 'mesh_resource_guard.py', 'resource-policy.json',
        'task-authorization.json', 'controlled-request.json', 'device.cmd', 'restart-binding.json',
        'restart-render.json', 'restart-initialization.json', 'source-spec.json', 'role-contract.json'}
    required.update('restart-state/'+n for n in PAIR)
    require(required <= set(hashes), 'restart frozen input manifest incomplete')
    for name, digest in hashes.items():
        require(D.file_sha(bridge.geometry_path(p, name)) == digest, 'frozen payload changed '+name)
    frozen = verify_frozen(D.FolderReader(p), cfg)
    require(obj((p/'input-manifest.json').read_bytes()).get('run_id') == cfg['run_id'],
            'input manifest run identity differs')
    require(obj((p/'resource-policy.json').read_bytes()) == dict(
        schema='dram-see-v4-actual-resource-policy-r1', role=cfg['role_id'], observation_only=True,
        imported_mesh_sha256=cfg['mesh_sha256'], resource_limits=None), 'resource policy is not usage-only')
    return cfg


def _current_module(name):
    """Only fixed local dispatcher names, never a filename selected by data."""
    require(name in ('case_contract.py', 'geometry_bridge.py'), 'unknown dispatcher')
    path = HERE/name; raw = path.read_bytes()
    spec = importlib.util.spec_from_file_location('_a0_suffix_dispatch_'+name.replace('.', '_'), str(path))
    value = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), 'exec'), value.__dict__)
    return value


def prepare(request, run_id, runner=None, output=None):
    """Future original-runner input creation; no admission bypass and no submission."""
    r = validate_request(request)
    C, bridge = _current_module('case_contract.py'), _current_module('geometry_bridge.py')
    require(getattr(C, 'SCHEMA_2D_A0_RESTART', None) == REQUEST_SCHEMA
            and hasattr(bridge, 'geometry_a0_restart_module') and C.is_role(role_id(r)),
            'restart dispatch patch is not integrated; no project created')
    P = fixed('parameterized_operating_2d.py'); D = fixed('two_dimensional.py'); O = P.operation_api()
    require(O.plain_name(run_id) and 'UNIT_FIXTURE_NOT_NATIVE' not in run_id, 'new native run ID required')
    root = HERE.parents[3]; runner = Path(runner or root/'scripts/tcad.py').resolve()
    require(runner == (root/'scripts/tcad.py').resolve(), 'original runner required')
    allowed = root/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/a0-restart-implementation-r1/projects'
    target = Path(output or allowed/run_id).resolve()
    require(allowed.resolve() in target.parents and not target.exists() and target.name == run_id,
            'new exclusive restart project path required')
    payload = candidate_payload(r); files = payload['files']; cfg = payload['cfg']; cfg['run_id'] = run_id
    role = cfg['role_id']; runner_sha = D.file_sha(runner)
    spec = dict(schema='dram-see-v4-continuous-project-r1', name='v4-2d-'+role.lower(), role=role,
        execution_enabled=True, runner='original scripts/tcad.py', native_threads=1, native_cores=1,
        s2_geometry=cfg, steps=[dict(tool='sdevice', args=['device.cmd'], outputs=list(O.OUTPUTS))])
    files.update({'project.json': encoded(spec),
        'resource-policy.json': encoded(dict(schema='dram-see-v4-actual-resource-policy-r1', role=role,
            observation_only=True, imported_mesh_sha256=cfg['mesh_sha256'], resource_limits=None)),
        'task-authorization.json': encoded(dict(schema='dram-see-v4-current-user-authorization-r1',
            source='current_user_instruction', synthetic=False, role_ids=[role],
            instruction='沿原runner/owner/共享锁，仅g80/2.4V/main两bit A0原状态后缀恢复；保留原字节与独立后缀身份，不扩为粒子或完整A0资格。')),
    })
    for name in ('case_contract.py', 'geometry_bridge.py', 'mesh_resource_guard.py'):
        files[name] = (HERE/name).read_bytes()
    files['generator-prepare_case.py'] = (HERE/'prepare_case.py').read_bytes()
    hashes = {n:sha(v) for n, v in files.items()}
    hashes.update({n:v['sha256'] for n, v in payload['external_files'].items()})
    files['input-manifest.json'] = encoded(dict(schema='dram-see-v4-continuous-inputs-r1',
        run_id=run_id, role_id=role, files_sha256=hashes))
    files['execution-context.json'] = encoded(dict(schema='dram-see-v4-continuous-run-context-r1',
        run_id=run_id, role_id=role, producer_run_id=cfg['producer_run_id'], synthetic=False,
        expected_runner_sha256=runner_sha, input_manifest_sha256=sha(files['input-manifest.json']),
        authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        bridge.geometry_write(target/name, raw)
    for name, row in payload['external_files'].items():
        src = Path(row['path']); dest = bridge.geometry_path(target, name)
        require(D.file_sha(src) == row['sha256'], 'external original changed before copy')
        dest.parent.mkdir(parents=True, exist_ok=True)
        with src.open('rb') as stream, dest.open('xb') as out:
            for chunk in iter(lambda: stream.read(1048576), b''):
                out.write(chunk)
        require(D.file_sha(dest) == row['sha256'], 'original proof copy differs')
    bridge.geometry_admit(target, spec, runner_sha)
    return dict(project=str(target), run_id=run_id, role_id=role, result_scope=SCOPE,
        input_manifest_sha256=sha(files['input-manifest.json']),
        restart_binding_sha256=cfg['restart_binding_sha256'], operation_timing_sha256=TIMING_SHA,
        original_A0_run_id=ORIGINALS[r['stored_bit']]['run_id'], native_submissions=0,
        native_Load_verified=False, electrical_suffix_equivalence_verified=False, training_admitted=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', required=True, help='new candidate manifest only; no formal project')
    args = parser.parse_args()
    out = Path(args.output)
    require(not out.exists(), 'refuse overwrite')
    value = candidate_payload(obj(Path(args.request).read_bytes()))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('xb') as stream:
        stream.write(encoded(value['manifest']))


if __name__ == '__main__':
    main()
