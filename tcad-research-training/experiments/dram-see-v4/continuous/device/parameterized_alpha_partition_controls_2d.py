"""Versioned 2/4-table controls of the fixed normal-alpha mathematical source.

Python 3.6 stdlib guest closure. Host preparation replays the unchanged a259
mathematics and actual r13 A0 originals. No launcher or qualification shortcut.
"""
import hashlib
import importlib.util
import json
from decimal import Decimal, localcontext
from pathlib import Path
import re
import sys
import tarfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BRANCH = 'dram-see-v4-parameterized-alpha-partition-controls-2d-r1'
REQUEST_SCHEMA = 'dram-see-v4-parameterized-alpha-partition-control-request-r1'
BINDING_SCHEMA = 'dram-see-v4-alpha-partition-control-binding-r1'
RUNTIME_SCHEMA = 'dram-see-v4-alpha-partition-control-runtime-r1'
SPEC_SCHEMA = 'dram-see-v4-alpha-partition-control-source-spec-r1'
ROLE_SCHEMA = 'dram-see-v4-alpha-partition-control-role-r1'
REPRESENTATION_SCHEMA = 'dram-see-v4-alpha-partition-control-native-representation-r1'
MAIN_SHA = 'f94ee5fad28033886d48dd19a7954952e7cec05e1df401693512ba4ba6618fc3'
CONTROL_RUNTIME_SHA = '80301b4ede5a94e78597f9f200e108504b6812109aae24f784acc283d85324bb'
CONTROL_MATH_SHA = 'a2593ddcf1cf6e776d69cafb4c174d82885f81b221dcf6c9577fe5577d3e90dc'
PREFIX = 'alpha-control-projection/'
A0_PREFIX = 'matched-a0-bindings/'
REPRESENTATION_FILE = 'native-control-representation.json'
BINDING_FILE = 'parameterized-alpha-partition-control-binding.json'
RUNTIME_BINDING_FILE = 'parameterized-alpha-partition-control-runtime-binding.json'
CASES = {'zero': ('Z', 0.), 'half': ('H', .5), 'split': ('split', 1.)}
FROZEN_RESULT_KEYS = {
    'binding', 'report', 'source_cfg', 'dimensional_contract', 'operation_timing',
    'operating_binding', 'source_spec', 'role_contract', 'numerical_relation',
    'projection', 'control_binding', 'control_runtime_binding', 'matched_a0',
    'source_time_contract', 'native_representation'}
LOGICAL_VIEW_MAPPING = {
    name: PREFIX+name for name in ('source-contract.json', 'heavyion.physics.inc', 'source.par')}


def require(ok, message):
    if not ok:
        raise ValueError('Alpha partition controls: '+message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode('utf-8')


def obj(raw):
    value = json.loads(raw.decode('utf-8'))
    require(isinstance(value, dict), 'JSON object required')
    return value


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def fixed(name, expected):
    path = HERE/name
    require(path.is_file() and not path.is_symlink() and file_sha(path) == expected,
            'fixed local implementation changed: '+name)
    spec = importlib.util.spec_from_file_location('_alpha_partition_controls_'+name.replace('.', '_'), str(path))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def main_api():
    return fixed('parameterized_alpha_native_partition_2d.py', MAIN_SHA)


def old_control():
    return fixed('parameterized_alpha_control_runtime_2d.py', CONTROL_RUNTIME_SHA)


def control_math():
    """Host-only mathematical replay; never called by guest admission."""
    return fixed('parameterized_alpha_control_projection_2d.py', CONTROL_MATH_SHA)


def validate_request(request):
    require(isinstance(request, dict) and set(request) == {
        'schema', 'control', 'control_projection_package', 'reference_alpha_request'},
        'exact independent partition-control request required')
    require(request['schema'] == REQUEST_SCHEMA and request['control'] in CASES,
            'explicit new control schema/case required')
    require(isinstance(request['control_projection_package'], str)
            and request['control_projection_package'].strip(), 'control mathematical package path required')
    reference = main_api().validate_request(request['reference_alpha_request'])
    require(reference['gate_top_depth_nm'] == 80 and reference['energy_MeV'] == 5
            and reference['theta_deg'] == 0 and reference['variant'] == 'main',
            'only actual g80 E5 normal main controls')
    result = obj(encoded(request))
    result['reference_alpha_request'] = reference
    return result


def role_id(request):
    r = validate_request(request)
    return 'B2D-'+CASES[r['control']][0]+'-native-partition-control-r1-main-b'+str(r['reference_alpha_request']['stored_bit'])


class BytesReader:
    def __init__(self, files):
        self.files = files

    def read(self, name):
        return self.files[name]

    def digest(self, name):
        return sha(self.read(name))

    def size(self, name):
        return len(self.read(name))


class LogicalControlView:
    """Only three data aliases for 8030 math bytes; never aliases native identity."""
    def __init__(self, reader):
        self.reader = reader

    def read(self, name):
        return self.reader.read(LOGICAL_VIEW_MAPPING.get(name, name))

    def digest(self, name):
        return self.reader.digest(LOGICAL_VIEW_MAPPING.get(name, name))

    def size(self, name):
        return self.reader.size(LOGICAL_VIEW_MAPPING.get(name, name))


def native_representation(base_include, base_parameters, control_include, control_parameters, control):
    """Exact original interval partition; no integrations of new source physics."""
    require(control in CASES, 'unknown native control')
    renderer = main_api().renderer()
    # This also binds the immutable actual E5 normal source and parameter bytes.
    main = renderer.render(base_include, base_parameters)
    _, full_tokens, _ = renderer.parse(base_include)
    chosen = base_include if control == 'split' else control_include
    parameters = base_parameters if control == 'split' else control_parameters
    found, tokens, values = renderer.parse(chosen)
    require(parameters == base_parameters, 'control changed temporal/material parameter bytes')
    name = renderer.NAME.encode('ascii')
    prefix = b' StartPoint=(-0.051999999999999998,0) Direction=(-0,1)\n'
    require(chosen.startswith(b'HeavyIon("'+name+b'") (\n')
            and chosen.endswith(b' Gaussian PicoCoulomb\n)\n') and chosen.count(prefix) == 1,
            'original single normal-source syntax differs')
    require(tokens['Length'] == full_tokens['Length'] and tokens['Wt_hi'] == full_tokens['Wt_hi'],
            'control changed original coordinates/width')
    amp = CASES[control][1]
    require(all(float(c) == amp*float(f) for c, f in zip(tokens['LET_f'], full_tokens['LET_f'])),
            'control LET is not the declared original binary64 amplitude')
    let_match = found[1]
    normalized = chosen[:let_match.start(2)]+b' '.join(full_tokens['LET_f'])+chosen[let_match.end(2):]
    require(normalized == base_include, 'control changes more than its source LET amplitude')
    ranges = ((0, 25), (25, 50), (50, 75), (75, 100)) if control == 'split' else ((0, 50), (50, 100))
    pieces, declarations, coverage = [], [], []
    with localcontext() as context:
        context.prec = 100
        require([values['Length'][i] for i in (0, 25, 50, 75, 100)]
                == [Decimal('0'), Decimal('.25'), Decimal('.5'), Decimal('.75'), Decimal('1')],
                'original quarter nodes differ')
        for index, (first, last) in enumerate(ranges):
            start, end = values['Length'][first], values['Length'][last]
            local_name = name if index == 0 else name+b'_native_control_part'+str(index).encode('ascii')
            include = chosen
            for match in reversed(found):
                key = match.group(1).decode('ascii')
                entries = ([renderer.number(v-start) for v in values[key][first:last+1]]
                           if key == 'Length' else tokens[key][first:last+1])
                include = include[:match.start(2)]+b' '.join(entries)+include[match.end(2):]
            include = include.replace(b'HeavyIon("'+name+b'")', b'HeavyIon("'+local_name+b'")', 1)
            include = include.replace(prefix,
                b' StartPoint=(-0.051999999999999998,'+renderer.number(start)+b') Direction=(-0,1)\n', 1)
            par = parameters.replace(b'HeavyIon("'+name+b'")', b'HeavyIon("'+local_name+b'")', 1)
            intervals = list(range(first, last))
            coverage.extend(intervals)
            piece_integral = sum((values['Length'][i+1]-values['Length'][i]) *
                (values['LET_f'][i]+values['LET_f'][i+1])/2 for i in intervals)
            pieces.append((include, par, piece_integral))
            declarations.append(dict(index=index, name=local_name.decode(),
                original_node_indices_inclusive=[first, last], original_interval_indices=intervals,
                original_s_interval_um=[str(start), str(end)], native_node_count=last-first+1,
                native_local_s_tokens=[renderer.number(v-start).decode() for v in values['Length'][first:last+1]],
                original_LET_tokens=[v.decode() for v in tokens['LET_f'][first:last+1]],
                original_width_tokens=[v.decode() for v in tokens['Wt_hi'][first:last+1]],
                exact_decimal_line_integral_pC=str(piece_integral),
                expected_finite_interval='0 <= local_s < length; original interpolation intervals owned once',
                actual_native_endpoint_or_junction_verified=False))
        original_integral = sum((values['Length'][i+1]-values['Length'][i]) *
            (values['LET_f'][i]+values['LET_f'][i+1])/2 for i in range(100))
        partition_integral = sum(p[2] for p in pieces)
        require(coverage == list(range(100)) and original_integral == partition_integral,
                'original interval coverage or exact decimal line integral changed')
    active_include = b''.join(p[0] for p in pieces)
    active_parameters = b''.join(p[1] for p in pieces)
    contract = dict(schema=REPRESENTATION_SCHEMA, control=control, amplitude=amp,
        reference_main_runtime_sha256=MAIN_SHA, logical_control_math_sha256=CONTROL_MATH_SHA,
        parent_include_sha256=sha(base_include), parent_parameter_sha256=sha(base_parameters),
        logical_control_include_sha256=sha(control_include), logical_control_parameter_sha256=sha(control_parameters),
        reference_main_native_include_sha256=sha(main['heavyion_physics_inc']),
        reference_main_native_parameter_sha256=sha(main['source_par']),
        active_include_sha256=sha(active_include), active_parameter_sha256=sha(active_parameters),
        parent_node_count=101, parent_interval_count=100, pieces=declarations,
        all_original_interpolation_intervals_retained=True, omitted_original_interval_indices=[],
        original_control_line_integral_pC=str(original_integral),
        partition_line_integral_pC=str(partition_integral), exact_decimal_partition_delta_pC='0',
        split_has_distinct_native_partition=control == 'split',
        old_two_segment_split_used_as_logical_reference_only=control == 'split',
        source_amplitude_binary64_relation_verified=True,
        source_epoch_literal=re.search(rb'\bTime=([^\s]+)', chosen).group(1).decode('ascii'),
        units=dict(Length='um', LET_f='pC/um', Wt_hi='um', Time='s'),
        gaussian_or_time_or_energy_renormalized=False, original_reference_energy_unscaled=True,
        original_half_device_response_linearity_required=False,
        native_table_count_limit_claimed=False, native_endpoint_field_qualification=False,
        native_source_qualified=False, scientific_evidence_verified=False, training_admitted=False)
    return dict(heavyion_physics_inc=active_include, source_par=active_parameters, contract=contract)


def _runtime_bytes():
    result = main_api()._runtime_bytes()
    for name, raw in old_control()._runtime_bytes().items():
        require(name not in result or result[name] == raw, 'fixed runtime collision: '+name)
        result[name] = raw
    result['parameterized_alpha_partition_controls_2d.py'] = Path(__file__).read_bytes()
    return result


def _snapshots():
    return old_control()._mathematical_snapshots()


def projection(reader, timing, reference, control):
    """Closed logical-reference bytes plus separate actual native expression."""
    C = old_control()
    logical = C._projection_bytes(LogicalControlView(reader), timing, reference, control)
    native = native_representation(
        reader.read(PREFIX+'base-projection/heavyion.physics.inc'),
        reader.read(PREFIX+'base-projection/source.par'),
        reader.read(PREFIX+'heavyion.physics.inc'), reader.read(PREFIX+'source.par'), control)
    require(reader.read('heavyion.physics.inc') == native['heavyion_physics_inc']
            and reader.read('source.par') == native['source_par'],
            'active native tables differ from exact original-interval renderer')
    require(reader.read('source-contract.json') == reader.read(PREFIX+'source-contract.json'),
            'logical source contract changed')
    require(obj(reader.read(REPRESENTATION_FILE)) == native['contract'],
            'native/control logical representation binding differs')
    logical.update(logical_reference_only=True, logical_view_mapping=LOGICAL_VIEW_MAPPING,
                   native_expression_replayed=True)
    return logical, native['contract']


def _declarations(reader, cfg, request, match, matched, originals):
    control = request['control']
    reference = request['reference_alpha_request']
    case, amp = CASES[control]
    bound = dict(schema=BINDING_SCHEMA, source_branch=BRANCH, run_id=cfg['run_id'],
        role_id=role_id(request), control=control, source_case=case, amplitude=amp,
        implementation_sha256=file_sha(__file__), reference_main_runtime_sha256=MAIN_SHA,
        logical_control_runtime_sha256=CONTROL_RUNTIME_SHA, logical_control_math_sha256=CONTROL_MATH_SHA,
        logical_control_manifest_sha256=reader.digest(PREFIX+'input-output-manifest.json'),
        logical_source_contract_sha256=reader.digest('source-contract.json'),
        native_representation_sha256=reader.digest(REPRESENTATION_FILE),
        active_include_sha256=reader.digest('heavyion.physics.inc'), active_parameter_sha256=reader.digest('source.par'),
        source_time_contract_sha256=reader.digest('source-time-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),
        mesh_sha256=reader.digest('cell_msh.tdr'), physics_manifest_sha256=reader.digest('physics-manifest.json'),
        dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        matched_a0=matched, matched_a0_original_files=originals,
        logical_guest_view_mapping=LOGICAL_VIEW_MAPPING,
        actual_root_identity_never_aliased=True, source_free_deck_byte_identical=True,
        half_response_linearity_required=False, native_source_qualified=False, training_admitted=False)
    bound_sha = sha(encoded(bound))
    spec = dict(schema=SPEC_SCHEMA, source_branch=BRANCH, particle='alpha', role='SIGNAL',
        source_case=case, control=control, amplitude=amp, stored_bit=reference['stored_bit'],
        numerical_variant='main', dimension=2, gate_top_depth_nm=80, sn_junction_depth_nm=87,
        effective_width_nm=20, energy_MeV=5, theta_deg=0, phi_deg=180,
        source_configured=True, input_structural_zero=control == 'zero',
        structural_zero_is_not_measured_G_zero=True, control_binding_sha256=bound_sha,
        source_contract_sha256=reader.digest('source-contract.json'),
        native_representation_sha256=reader.digest(REPRESENTATION_FILE),
        source_time_contract_sha256=reader.digest('source-time-contract.json'),
        operation_timing_sha256=reader.digest('operation-timing.json'),
        physics_manifest_sha256=reader.digest('physics-manifest.json'),
        dimensional_contract_sha256=reader.digest('dimensional-contract.json'),
        reference_main_runtime_sha256=MAIN_SHA, source_native_relative_tolerance=.05,
        zero_split_response_charge_limit_fC=1e-4, zero_split_response_voltage_limit_V=1e-5,
        half_response_linearity_required=False, source_field_comparison_required=True,
        configured_amplitude_is_not_incident_energy_scaling=True,
        native_source_qualified=False, scientific_evidence_verified=False, training_admitted=False)
    role = dict(schema=ROLE_SCHEMA, role=role_id(request), source_branch=BRANCH,
        source_case=case, stored_bit=reference['stored_bit'], matched_A0_role=match['role'],
        source_spec_sha256=sha(encoded(spec)), control_binding_sha256=bound_sha,
        native_representation_sha256=reader.digest(REPRESENTATION_FILE),
        source_configured=True, native_syntax_verified=False, native_source_qualified=False)
    return bound, spec, role


def runtime_binding(reader, cfg):
    return dict(schema=RUNTIME_SCHEMA, source_branch=BRANCH, run_id=cfg['run_id'], role_id=cfg['role_id'],
        implementation_sha256=file_sha(__file__),
        runtime_sha256={n:sha(v) for n,v in _runtime_bytes().items()},
        files_sha256={n:reader.digest(n) for n in (
            'controlled-request.json', BINDING_FILE, REPRESENTATION_FILE, 'source-spec.json',
            'role-contract.json', 'device.cmd', 'heavyion.physics.inc', 'source.par',
            'source-contract.json', 'source-time-contract.json')},
        guest_mathematical_integrals_replayed=False, guest_native_representation_replayed=True,
        guest_uses_closed_local_runtime=True, native_source_qualified=False, training_admitted=False)


def verify_frozen(reader, cfg):
    R = main_api()
    P, D, A = R.parameterized(), R.dimensional(), R.alpha()
    require(cfg.get('source_branch') == BRANCH and cfg.get('dimension_branch') == P.DIMENSION_BRANCH
            and cfg.get('mode') == 'reuse' and 'parameterized_operating_branch' not in cfg,
            'explicit new partition-control root required')
    request = validate_request(obj(reader.read('controlled-request.json')))
    reference = request['reference_alpha_request']
    require(cfg.get('role_id') == role_id(request) and cfg.get('stored_bit') == reference['stored_bit'],
            'actual new control role/bit differs')
    for name, raw in _runtime_bytes().items():
        require(reader.digest(name) == sha(raw), 'closed runtime changed: '+name)
    result, _, _ = P._verify_sources(reader, cfg)
    bound = obj(reader.read(BINDING_FILE))
    require(bound.get('schema') == BINDING_SCHEMA and reader.digest(BINDING_FILE)
            == cfg.get('parameterized_alpha_partition_control_binding_sha256'), 'new control binding differs')
    originals = bound.get('matched_a0_original_files', {})
    require(set(originals) == {A0_PREFIX+n for n in ('manifest.json', 'results.tar', 'inputs.tar')},
            'all three original matched A0 files required')
    for name, row in originals.items():
        require(row == dict(sha256=reader.digest(name), size_bytes=reader.size(name)),
                'actual matching A0 original changed: '+name)
    manifest = obj(reader.read(A0_PREFIX+'manifest.json'))
    require(manifest.get('results_sha256') == reader.digest(A0_PREFIX+'results.tar')
            and manifest.get('inputs_archive_sha256') == reader.digest(A0_PREFIX+'inputs.tar'),
            'outer original A0 archive hashes differ')
    with reader.stream(A0_PREFIX+'results.tar') as a, reader.stream(A0_PREFIX+'inputs.tar') as i:
        with tarfile.open(fileobj=a, mode='r:*') as ar, tarfile.open(fileobj=i, mode='r:*') as ir:
            prior = D.ArchiveReader(ar)
            match = R.verify_matched_a0(prior, manifest, D.ArchiveReader(ir), reference)
            matched = R.matched_identity(match, manifest, reader.digest(A0_PREFIX+'manifest.json'),
                                         reader.digest(A0_PREFIX+'results.tar'))
            for name, raw in match['shared'].items():
                require(reader.read(name) == raw, 'control/A0 physical input differs: '+name)
            require(reader.digest('cell_msh.tdr') == prior.digest('cell_msh.tdr') == cfg['mesh_sha256']
                    and reader.read('d2-source-binding.json') == prior.read('d2-source-binding.json'),
                    'actual control/A0 mesh or source differs')
            timing = match['verified']['operation_timing']
            R.request_matches(reference, timing, matched, cfg)
            logical, native = projection(reader, timing, reference, request['control'])
            time = R.source_time_contract(match['device'], logical['base_projection']['contract'], timing, reference)
            include = reader.read('heavyion.physics.inc')
            require(reader.read('device.cmd') == A.render_signal(match['device'], include)
                    and A.source_free_deck(reader.read('device.cmd'), include) == match['device'],
                    'source-free deck differs from actual same-bit A0')
            require(obj(reader.read('source-time-contract.json')) == time, 'source/native physical time changed')
    require(reader.read('run-parameters.par') == reader.read('physics.par')+b'\n'+reader.read('source.par')
            and obj(reader.read('parameter-binding.json')) == A.parameter_binding(reader),
            'actual base/source parameter binding differs')
    expected, spec, role = _declarations(reader, cfg, request, match, matched, originals)
    require(bound == expected and obj(reader.read('source-spec.json')) == spec
            and obj(reader.read('role-contract.json')) == role, 'new root source/role declarations differ')
    runtime = runtime_binding(reader, cfg)
    require(obj(reader.read(RUNTIME_BINDING_FILE)) == runtime and reader.digest(RUNTIME_BINDING_FILE)
            == cfg.get('parameterized_alpha_partition_control_runtime_sha256'), 'new runtime binding differs')
    require(reader.read('heavyion.plot.inc') == A.PLOT.rstrip()+b'\n'
            and reader.read('heavyion.currentplot.inc') == A.CURRENT, 'original source diagnostics differ')
    result.update(operation_timing=timing, operating_binding=match['verified']['operating_binding'],
        numerical_relation=match['verified']['numerical_relation'], source_spec=spec, role_contract=role,
        projection=logical, control_binding=bound, control_runtime_binding=runtime,
        matched_a0=matched, source_time_contract=time, native_representation=native)
    require(set(result) == FROZEN_RESULT_KEYS, 'new 15-key result differs')
    return result


def candidate_payload(request):
    """Return bytes/import identities after real A0 and unchanged host math replay.

    No project.json, execution context, native exit or scientific positive is
    manufactured. The complete matched-A0 original archives are copied only by
    formal prepare after the integrated original dispatch has been verified.
    """
    request = validate_request(request)
    reference = request['reference_alpha_request']
    R, C = main_api(), old_control()
    # The existing helper accepts the explicitly supplied fixed new reference
    # API; it does not relabel the A0, execute archived code or call old admit.
    host, match, matched, originals, source_bytes = C.candidate()._actual_match(reference, R)
    package = Path(request['control_projection_package']).resolve()
    CP = control_math()
    logical = CP.verify(package)
    require(logical['contract']['request']['control'] == request['control'], 'control package/case differs')
    parent = package/'base-projection'
    actual_parent = Path(reference['alpha_projection_package']).resolve()
    require(actual_parent.is_dir() and not actual_parent.is_symlink(), 'actual full-alpha parent package missing')
    for name in CP.BASE_FILES:
        require((parent/name).read_bytes() == (actual_parent/name).read_bytes(),
                'unchanged control parent source differs: '+name)
    base_contract = obj((parent/'source-contract.json').read_bytes())
    timing = match['verified']['operation_timing']
    R.source_request(base_contract['request'], timing, reference)
    for name in ('model.proposed.json', 'geometry-contract.json', 'dimensional-contract.json'):
        require(match['shared'][name] == (parent/name).read_bytes(),
                'actual control/A0 model, material or width differs: '+name)
    require(logical['contract']['mesh_sha256'] == sha(source_bytes['cell_msh.tdr'])
            and logical['contract']['physics_manifest_sha256'] == sha(match['shared']['physics-manifest.json']),
            'control reference actual mesh/physics differs')
    packet = {name:(package/name).read_bytes() for name in logical['manifest']['files']}
    packet['input-output-manifest.json'] = (package/'input-output-manifest.json').read_bytes()
    require(obj(packet['input-output-manifest.json']) == logical['manifest']
            and all(sha(packet[n]) == v['sha256'] and len(packet[n]) == v['size_bytes']
                    for n,v in logical['manifest']['files'].items()), 'control changed after host mathematical replay')
    native = native_representation(packet['base-projection/heavyion.physics.inc'],
        packet['base-projection/source.par'], packet['heavyion.physics.inc'], packet['source.par'], request['control'])
    files = dict(match['shared'])
    files.update(source_bytes)
    files.update({PREFIX+n:raw for n,raw in packet.items()})
    files['source-contract.json'] = packet['source-contract.json']
    files['heavyion.physics.inc'] = native['heavyion_physics_inc']
    files['source.par'] = native['source_par']
    files[REPRESENTATION_FILE] = encoded(native['contract'])
    A = R.alpha()
    files['device.cmd'] = A.render_signal(match['device'], files['heavyion.physics.inc'])
    require(A.source_free_deck(files['device.cmd'], files['heavyion.physics.inc']) == match['device'],
            'source-free candidate does not equal original matching A0')
    files['run-parameters.par'] = files['physics.par']+b'\n'+files['source.par']
    files['heavyion.plot.inc'] = A.PLOT.rstrip()+b'\n'
    files['heavyion.currentplot.inc'] = A.CURRENT
    files['source-time-contract.json'] = encoded(R.source_time_contract(match['device'], base_contract, timing, reference))
    files['parameter-binding.json'] = encoded(A.parameter_binding(BytesReader(files)))
    files['controlled-request.json'] = encoded(request)
    files.update(_runtime_bytes())
    files.update(_snapshots())
    # Reuse the old *data-only* mathematical reference check, then verify the
    # separately rendered native 2/4-table expression. This is not old admission.
    checked, native_check = projection(BytesReader(files), timing, reference, request['control'])
    require(checked['contract'] == logical['contract'] and native_check == native['contract'],
            'host/frozen mathematical reference or native expression differs')
    return dict(files=files, imports=originals, request=request, match=match, host_a0_report=host,
                matched_a0=matched, projection=checked, native_representation=native['contract'],
                status='CANDIDATE_BYTES_ONLY_NO_PROJECT_NO_NATIVE_CONTROL_RESULT',
                native_source_qualified=False, training_admitted=False)


def _add_declarations(files, cfg, request, match, matched, originals):
    reader = BytesReader(files)
    bound, spec, role = _declarations(reader, cfg, request, match, matched, originals)
    files[BINDING_FILE] = encoded(bound)
    cfg['parameterized_alpha_partition_control_binding_sha256'] = sha(files[BINDING_FILE])
    files['source-spec.json'] = encoded(spec)
    files['role-contract.json'] = encoded(role)
    files[RUNTIME_BINDING_FILE] = encoded(runtime_binding(reader, cfg))
    cfg['parameterized_alpha_partition_control_runtime_sha256'] = sha(files[RUNTIME_BINDING_FILE])


def admit(project, spec, runner_sha, bridge):
    R = main_api()
    D, O = R.dimensional(), R.operation()
    project = Path(project)
    cfg = spec['s2_geometry']
    require('fixture' not in str(project.resolve()).lower() and not (project/'SYNTHETIC_NOT_NATIVE').exists(),
            'fixture cannot be admitted')
    request = validate_request(obj((project/'controlled-request.json').read_bytes()))
    reference = request['reference_alpha_request']
    require(cfg.get('schema') == bridge.GEOMETRY_SCHEMA and cfg.get('synthetic') is False
            and cfg.get('execution_enabled') is True and spec.get('execution_enabled') is True
            and spec.get('role') == cfg.get('role_id') == role_id(request)
            and O.plain_name(cfg.get('run_id'))
            and cfg['run_id'] not in (cfg['producer_run_id'], O.source_name(reference['matched_a0_run']))
            and spec.get('native_threads') == spec.get('native_cores') == 1
            and spec.get('steps') == [dict(tool='sdevice', args=['device.cmd'], outputs=list(O.OUTPUTS))],
            'original-runner actual role, identity or serial-step contract differs')
    bridge.geometry_context(project, cfg, runner_sha)
    hashes = bridge.geometry_input_hashes(project)
    d2 = obj((project/'d2-source-binding.json').read_bytes())
    mathematical = obj((project/PREFIX/'input-output-manifest.json').read_bytes())
    required = set(D.SHARED_INPUTS)|set(_runtime_bytes())|set(R.SHARED)|set(d2['original_files'])
    required |= set(old_control()._snapshot_map())|{PREFIX+n for n in mathematical['files']}
    required |= {A0_PREFIX+n for n in ('manifest.json', 'results.tar', 'inputs.tar')}
    required |= {
        'project.json', 'controlled-request.json', 'case_contract.py', 'geometry_bridge.py', 'mesh_resource_guard.py',
        'task-authorization.json', 'resource-policy.json', 'device.cmd', 'cell_msh.tdr', 'cell_msh.log',
        'd2-source-binding.json', 'source-contract.json', 'source.par', 'heavyion.physics.inc', 'heavyion.plot.inc',
        'heavyion.currentplot.inc', 'run-parameters.par', 'parameter-binding.json', 'source-time-contract.json',
        BINDING_FILE, RUNTIME_BINDING_FILE, REPRESENTATION_FILE, 'source-spec.json', 'role-contract.json',
        PREFIX+'input-output-manifest.json'}
    require(required <= set(hashes), 'mandatory actual source, runtime or original proof missing')
    for name, h in hashes.items():
        require(D.file_sha(bridge.geometry_path(project, name)) == h, 'frozen input changed: '+name)
    manifest = obj((project/'input-manifest.json').read_bytes())
    require(manifest.get('run_id') == cfg['run_id'] and manifest.get('role_id') == cfg['role_id'],
            'input manifest native identity differs')
    verified = verify_frozen(D.FolderReader(project), cfg)
    require(verified['operation_timing']['origin'] == 'prescribed_input', 'UNIT timing cannot be submitted')
    require(obj((project/'resource-policy.json').read_bytes()) == dict(
        schema='dram-see-v4-actual-resource-policy-r1', role=cfg['role_id'],
        observation_only=True, imported_mesh_sha256=cfg['mesh_sha256'], resource_limits=None),
        'actual resource observation only; no quota or approval')
    return cfg


def prepare(request, run_id, runner=None, output=None):
    """Prepare one real control input; never submit or create an operation."""
    request = validate_request(request)
    R = main_api()
    P, D, O = R.parameterized(), R.dimensional(), R.operation()
    C, bridge = R.module('case_contract.py'), R.module('geometry_bridge.py')
    require(getattr(C, 'SCHEMA_2D_ALPHA_PARTITION_CONTROL', None) == REQUEST_SCHEMA
            and hasattr(bridge, 'geometry_alpha_partition_control_module'),
            'PENDING_DISPATCH: explicit new control route not integrated; no project created')
    require(O.plain_name(run_id) and 'fixture' not in run_id.lower(), 'new nonfixture run ID required')
    runner = Path(runner or ROOT/'scripts/tcad.py').resolve()
    require(runner == (ROOT/'scripts/tcad.py').resolve() and runner.is_file(), 'original runner required')
    allowed = (ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/alpha-partition-controls-implementation-r1').resolve()
    target = Path(output or allowed/'projects'/run_id).resolve()
    require(allowed in target.parents and not target.exists() and 'fixture' not in str(target).lower(),
            'new allowed input directory required')
    request = obj(encoded(request))
    request['control_projection_package'] = str(Path(request['control_projection_package']).resolve())
    reference = request['reference_alpha_request']
    for name in ('d2_source_run', 'base_d2_source_run', 'matched_a0_run', 'alpha_projection_package'):
        reference[name] = str(Path(reference[name]).resolve())
    require(run_id not in (O.source_name(reference['d2_source_run']), O.source_name(reference['matched_a0_run'])),
            'new signal identity must differ from all real producers')
    payload = candidate_payload(request)
    files, originals = dict(payload['files']), payload['imports']
    match, matched = payload['match'], payload['matched_a0']
    role = role_id(request)
    cfg = dict(match['cfg'])
    cfg.pop('parameterized_operating_branch')
    cfg.pop('parameterized_operating_binding_sha256')
    cfg.update(role_id=role, run_id=run_id, source_branch=BRANCH,
               source_run_directory=reference['d2_source_run'],
               base_source_run_directory=reference['base_d2_source_run'], execution_enabled=True, synthetic=False)
    R.request_matches(reference, match['verified']['operation_timing'], matched, cfg)
    bundle = P.source_bundle(target, cfg)
    require(bundle['mesh_sha256'] == match['cfg']['mesh_sha256']
            and bundle['d2_source_binding_sha256'] == match['cfg']['d2_source_binding_sha256'],
            'actual signal/A0 source pair differs')
    files.update(bundle['generated_files'])
    original_identity = {n:{k:v for k,v in row.items() if k != 'path'} for n,row in originals.items()}
    _add_declarations(files, cfg, request, match, matched, original_identity)
    spec = dict(schema='dram-see-v4-continuous-project-r1', name='v4-2d-'+role.lower(), role=role,
        execution_enabled=True, runner='original scripts/tcad.py', native_threads=1, native_cores=1,
        s2_geometry=cfg, steps=[dict(tool='sdevice', args=['device.cmd'], outputs=list(O.OUTPUTS))])
    files.update({
        'project.json':encoded(spec),
        'resource-policy.json':encoded(dict(schema='dram-see-v4-actual-resource-policy-r1', role=role,
            observation_only=True, imported_mesh_sha256=cfg['mesh_sha256'], resource_limits=None)),
        'task-authorization.json':encoded(dict(schema='dram-see-v4-current-user-authorization-r1',
            source='current_user_instruction', synthetic=False, role_ids=[role],
            instruction='已授权真实r13同bit A0匹配的g80 E5/0主源分段控制输入；原源和判据保持，zero/half两段、split四段，原runner/owner/共享锁串行单核单线程。',
            plan_path='experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md',
            plan_sha256=D.file_sha(ROOT/'experiments/dram-see-v4/CONTINUOUS-GOAL-PLAN.md'))),
        'provenance.json':encoded(dict(schema='dram-see-v4-alpha-partition-control-input-provenance-r1',
            run_id=run_id, role=role, matched_a0=matched, reference_main_runtime_sha256=MAIN_SHA,
            logical_control_math_sha256=CONTROL_MATH_SHA,
            logical_control_manifest_sha256=sha(files[PREFIX+'input-output-manifest.json']),
            native_representation_sha256=sha(files[REPRESENTATION_FILE]),
            host_original_A0_chain_and_metrics_replayed=True, host_control_mathematics_replayed=True,
            new_time_or_gate_selected_by_generator=False, actual_root_identity_never_aliased=True,
            logical_guest_view_mapping=LOGICAL_VIEW_MAPPING, native_run_completed=False,
            source_free_deck_byte_identical=True, half_device_response_linearity_required=False,
            independent_split_control_qualified=False, native_source_qualified=False, training_admitted=False)),
    })
    for name in ('geometry_bridge.py', 'case_contract.py', 'mesh_resource_guard.py'):
        files[name] = (HERE/name).read_bytes()
    files['generator-prepare_case.py'] = (HERE/'prepare_case.py').read_bytes()
    hashes = {n:sha(v) for n,v in files.items()}
    for name, h in bundle['exports'].items():
        require(name not in hashes or hashes[name] == h, 'actual D2 export collision: '+name)
        hashes[name] = h
    for name, row in originals.items():
        require(name not in hashes, 'actual A0 original import collision: '+name)
        hashes[name] = row['sha256']
    files['input-manifest.json'] = encoded(dict(schema='dram-see-v4-continuous-inputs-r1',
        run_id=run_id, role_id=role, files_sha256=hashes))
    runner_sha = D.file_sha(runner)
    files['execution-context.json'] = encoded(dict(schema='dram-see-v4-continuous-run-context-r1',
        run_id=run_id, role_id=role, producer_run_id=cfg['producer_run_id'], synthetic=False,
        expected_runner_sha256=runner_sha, input_manifest_sha256=sha(files['input-manifest.json']),
        authorization_sha256=sha(files['task-authorization.json'])))
    target.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        bridge.geometry_write(target/name, raw)
    for name, row in originals.items():
        require(file_sha(row['path']) == row['sha256'], 'original matched A0 changed while preparing')
        destination = target/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Path(row['path']).open('rb') as inp, destination.open('xb') as out:
            for block in iter(lambda: inp.read(1048576), b''):
                out.write(block)
        require(file_sha(destination) == row['sha256'], 'original A0 copy differs')
    bridge.geometry_stage_reuse(target, cfg)
    bridge.geometry_admit(target, spec, runner_sha)
    return dict(project=str(target), run_id=run_id, role_id=role, matched_a0=matched,
        operation_timing_sha256=cfg['operation_timing_sha256'],
        input_manifest_sha256=sha(files['input-manifest.json']),
        control_binding_sha256=cfg['parameterized_alpha_partition_control_binding_sha256'],
        control_runtime_sha256=cfg['parameterized_alpha_partition_control_runtime_sha256'],
        native_representation_sha256=sha(files[REPRESENTATION_FILE]), native_submissions=0,
        independent_split_control_qualified=False, native_source_qualified=False, training_admitted=False)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(encoded(prepare(obj(args.request.read_bytes()), args.run_id, output=args.output)).decode('utf-8'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
