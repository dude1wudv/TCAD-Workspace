"""Read-only audits of the frozen A0/A1/A4 source-interface probe archives.

No solver, SSH, archive extraction, training, legacy export, or ledger mutation.
Passing this audit is not DRAM calibration or a mesh/time-step convergence study.
"""
import argparse
import bisect
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath
import re
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V3 = ROOT / 'experiments/dram-see-v3/r50-main'
E_C = 1.602176634e-19
TOLERANCES = {
    'source_relative': .05,
    'zero_charge_fC': 1e-6,
    'final_time_abs_s': 1e-18,
    'pair_generated_charge_abs_fC': 1e-4,
    'pair_generation_curve_relative': 1e-3,
    'pair_voltage_abs_V': 1e-5,
    'pair_current_abs_A': 1e-12,
    'pair_current_relative': 1e-3,
}
LIMITS = [
    'Synthetic LET source-interface probes, not real particle-transport events.',
    'Uncalibrated inherited 2D device, effective thickness 1 um and AreaFactor=1.',
    'No mesh/time-step convergence or critical-readout classification validation.',
    'No 3D source validation, nuclear reaction, event probability, training or calibration.',
    'No matched neutral-cell readout reference or upset/margin classification.',
    'Terminal/capacitor conservation uses the inherited R50 BE circuit contract.',
]


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # Avoid importing caches or calling the legacy audit/export entry points.
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


legacy = _module(V3 / 'audit.py', '_v4_probe_readonly_numerics')
parse_plt, integral = legacy.parse_plt, legacy.integral


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def json_load(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)


def encoded(value):
    """The input builder's frozen, newline-terminated JSON representation."""
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def safe_name(name):
    require(isinstance(name, str) and name and '\\' not in name and ':' not in name,
            'Unsafe archive/input path')
    while name.startswith('./'):
        name = name[2:]
    p = PurePosixPath(name)
    require(not p.is_absolute() and '..' not in p.parts, 'Archive path traversal')
    return p.as_posix()


class Archive:
    """Validate the complete member namespace; read files without extraction."""
    def __init__(self, path):
        self.tf = tarfile.open(path, 'r:*')
        self.members = {}
        try:
            for member in self.tf.getmembers():
                name = safe_name(member.name)
                require(member.isfile() or member.isdir(),
                        'Archive links/devices/special members are forbidden: ' + name)
                if member.isdir():
                    continue
                require(name not in self.members, 'Duplicate archive member: ' + name)
                self.members[name] = member
        except Exception:
            self.tf.close()
            raise

    def read(self, name):
        name = safe_name(name)
        require(name in self.members, 'Missing archive member: ' + name)
        # Large TDRs are hashed separately; textual inputs/curves have a bound.
        require(self.members[name].size <= 128 * 1024 * 1024, 'Text member too large: ' + name)
        return self.tf.extractfile(self.members[name]).read()

    def digest(self, name):
        name = safe_name(name)
        require(name in self.members, 'Missing archive member: ' + name)
        digest = hashlib.sha256()
        with self.tf.extractfile(self.members[name]) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return digest.hexdigest()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.tf.close()


class Checks:
    def __init__(self, report):
        self.report = report

    def call(self, name, function):
        try:
            value = function()
            self.report['checks'][name] = {'passed': True}
            return value
        except (ValueError, OSError, KeyError, TypeError, IndexError, ZeroDivisionError,
                UnicodeError, tarfile.TarError) as exc:
            detail = str(exc)
            self.report['checks'][name] = {'passed': False, 'error': detail}
            self.report['errors'].append({'check': name, 'error': detail})
            return None


def _report(schema):
    return {
        'schema': schema, 'passed': False, 'status': 'FAILED_OR_INCOMPLETE',
        'checks': {}, 'errors': [], 'limits': list(LIMITS),
        'scientific_calibration_passed': False, 'numerical_convergence_validated': False,
        'audit_tolerances': dict(TOLERANCES),
        'audit_code_sha256': sha_file(Path(__file__)),
        'parser_source_sha256': {
            str(path.relative_to(ROOT)).replace('\\', '/'): sha_file(path)
            for path in (V3 / 'audit.py', V3 / 'build_case.py', ROOT / 'experiments/dram-see-v1/analyze.py')
        },
    }


def _manifest(folder, report):
    raw = (folder / 'manifest.json').read_bytes()
    m = json_load(raw)
    report['run_id'] = m.get('run_id')
    report['manifest_sha256'] = sha_bytes(raw)
    report['engineering_evidence'] = {
        'state': m.get('state'), 'ssh_exit_code': m.get('ssh_exit_code'),
        'remote_exit_code': None,
        'archive_transfer_exit_code': m.get('archive_transfer_exit_code'),
        'archive_transfer_exit_evidence': 'Runner COLLECTED transition is checked; runner does not persist a separate archive-transfer exit code.',
    }
    require(m.get('run_id') == folder.name, 'Manifest run_id does not match run directory')
    require(m.get('state') == 'COLLECTED', 'Run is not COLLECTED')
    require(type(m.get('ssh_exit_code')) is int and m['ssh_exit_code'] == 0,
            'SSH exit must be the actual integer 0; unknown/nonzero is rejected')
    require(not m.get('ssh_exit_code_scope') and
            ('original_execution_ssh_exit_code' not in m or
             type(m['original_execution_ssh_exit_code']) is int and m['original_execution_ssh_exit_code'] == 0),
            'Recovery cannot replace an unknown original execution exit code')
    hashes = m.get('input_sha256')
    require(isinstance(hashes, dict) and hashes, 'Missing frozen input hashes')
    required = {'project.json', 'parameters.json', 'geometry.scm', 'device.cmd',
                'source-spec.json', 'source-contract.json'}
    require(required <= set(hashes), 'Missing required frozen v4 inputs')
    for name, digest in hashes.items():
        require(safe_name(name) == name and re.fullmatch(r'[0-9a-f]{64}', digest or ''),
                'Invalid input filename or SHA256')
    actual = sha_file(folder / 'results.tar')
    report['archive_sha256'] = actual
    require(actual == m.get('results_sha256'), 'Results archive SHA256 mismatch')
    report['input_sha256'] = hashes
    report['inputs_tar_sha256'] = sha_file(folder / 'inputs.tar')
    with Archive(folder / 'inputs.tar') as inputs:
        require(set(inputs.members) == set(hashes), 'inputs.tar file set differs from manifest')
        for name, digest in hashes.items():
            require(inputs.digest(name) == digest, 'Frozen input hash mismatch: ' + name)
    return m


def _provenance(archive, manifest, folder, project_path, report):
    for name, digest in manifest['input_sha256'].items():
        require(archive.digest(name) == digest, 'Archived input changed: ' + name)
    if project_path is not None:
        project = Path(project_path).resolve()
        for name, digest in manifest['input_sha256'].items():
            path = (project / name).resolve()
            require(path.is_relative_to(project), 'Project path escapes input directory')
            require(sha_file(path) == digest, 'Current project differs from archived input: ' + name)
        report['project_path'] = str(project)
    exit_raw = archive.read('exit-code.txt').strip()
    require(re.fullmatch(rb'-?\d+', exit_raw) is not None, 'Unknown/malformed remote exit code')
    report['engineering_evidence']['remote_exit_code'] = int(exit_raw)
    require(int(exit_raw) == 0, 'Nonzero remote runner exit')
    execution = archive.read('execution.log').decode('utf-8', errors='replace')
    require('ENGINEERING_RUN_COMPLETED' in execution.splitlines(), 'Missing original runner completion marker')
    project = json_load(archive.read('project.json'))
    require(project.get('steps') == manifest.get('steps'), 'Manifest/project steps differ')
    require(any(step.get('tool') == 'sdevice' for step in project['steps']), 'No SDevice step')
    for step in project['steps']:
        require(step.get('outputs'), 'Step has no expected outputs')
        for output in step['outputs']:
            require(output in archive.members and archive.members[output].size > 0,
                    'Missing/empty required output: ' + output)
    log_names = {output for step in project['steps'] if step['tool'] == 'sdevice'
                 for output in step['outputs'] if output in ('transient_des.log', 'transient.log')}
    require(len(log_names) == 1, 'Project must declare exactly one recognized SDevice output log')
    log_name = next(iter(log_names))
    log = archive.read(log_name).decode('utf-8', errors='replace')
    require('Sentaurus Device simulation finished' in log, 'Missing SDevice completion marker')
    report['solver_log_member'] = log_name
    script = archive.read('run.sh')
    require(script == (folder / 'run.sh').read_bytes(), 'Local/remote runner script differs')
    script_text = script.decode('utf-8')
    for token in ('set -euo pipefail', '--threads 1 --exit-on-failure', 'OMP_NUM_THREADS=1', 'flock -n 9'):
        require(token in script_text, 'Missing inherited serial-runner constraint: ' + token)
    report['run_script_sha256'] = sha_bytes(script)
    report['solver_finished'] = True
    report['newton_retries'] = log.count("Newton didn't converge")
    wall = re.search(r'wallclock:\s*([\d.]+) s', log)
    report['solver_wallclock_s'] = float(wall[1]) if wall else None
    report['mesh_sha256'] = archive.digest('cell_msh.tdr')
    return project


def _number(value, name):
    require(type(value) in (int, float) and math.isfinite(value), 'Invalid number: ' + name)
    return value


def _contracts(archive, report):
    p = json_load(archive.read('parameters.json'))
    source = json_load(archive.read('source-spec.json'))
    contract_raw = archive.read('source-contract.json')
    contract = json_load(contract_raw)
    report['parameters'] = p
    report['source_spec'] = source
    report['source_contract_sha256'] = sha_bytes(contract_raw)
    require(p.get('schema') == 'dram-see-v4-source-probe', 'Not a v4 source-probe input')
    require(source.get('schema') == 'dram-see-v4-source-spec', 'Wrong source-spec schema')
    require(contract_raw == (HERE / 'source_contract.json').read_bytes(),
            'Archived source contract differs from frozen repository contract')
    require(contract.get('audit_tolerances') == TOLERANCES, 'Audit tolerances differ from frozen decision')
    case = p.get('case_id')
    require(case in ('A0', 'A1', 'A4') and source.get('case_id') == case, 'Unknown/mismatched probe case')
    require(type(p.get('stored_bit')) is int and p['stored_bit'] == 1, 'Only frozen stored-bit-1 probe is authorized')
    event = p.get('event_id')
    require(isinstance(event, str) and event and source.get('event_id') == event, 'Missing/mismatched event identity')
    require(source.get('synthetic') is True, 'Probe must be identified as synthetic')
    require(p.get('source_spec_file') == 'source-spec.json' and
            p.get('source_contract_file') == 'source-contract.json', 'Wrong source evidence names')
    require(p.get('source_contract_sha256') == sha_bytes(contract_raw), 'Parameter/contract hash mismatch')
    require(p.get('source_spec_sha256') == sha_bytes(archive.read('source-spec.json')),
            'Parameter/source-spec hash mismatch')
    require(contract.get('units', {}).get('generation') == 'pairs/cm^3/s' and
            contract.get('device', {}).get('dimension') == 2 and
            contract['device'].get('effective_thickness_um') == 1,
            'Missing/ambiguous spatial-generation normalization contract')
    matching = p.get('matching_contract')
    require(isinstance(matching, dict) and matching, 'Missing complete matching contract')
    require(p.get('matching_contract_sha256') == sha_bytes(encoded(matching)),
            'Common matching contract hash mismatch')
    for key, value in matching.items():
        if key in p:
            require(p[key] == value, 'Matching contract/parameter differs: ' + key)
    require(p.get('geometry_sha256') == archive.digest('geometry.scm'), 'Actual geometry script hash differs')
    for key, value in {'effective_thickness_um': 1, 'capacitance_F': 1e-14,
                       'read_sample_s': 4e-9, 'reference_mode': 'offline',
                       'target_voltage_V': .9, 'step_scale': 1, 'mesh_scale': 1}.items():
        require(p.get(key) == value, 'Inherited model/numerical setting differs: ' + key)
    expected_q, expected_count = {'A0': (0., 0), 'A1': (1., 1), 'A4': (1., 2)}[case]
    require(p.get('source_charge_fC') == expected_q and p.get('total_charge_fC') == expected_q
            and source.get('source_total_fC') == expected_q
            and p.get('charge_pc') == expected_q / 1000, 'Wrong declared total source charge')
    tracks = source.get('tracks')
    require(isinstance(tracks, list) and len(tracks) == expected_count
            and p.get('source_count') == expected_count, 'Wrong source count')
    ids, names = set(), set()
    for track in tracks:
        require(track.get('track_id') not in ids and track.get('source_name') not in names,
                'Duplicate track ID/source name')
        require(track.get('track_id') is not None and isinstance(track.get('source_name'), str)
                and track['source_name'], 'Missing track identity')
        ids.add(track['track_id']); names.add(track['source_name'])
        q = _number(track.get('q_fC'), 'track q_fC')
        require(q == expected_q / expected_count, 'Wrong per-track charge')
        for key in ('start_um', 'direction'):
            require(isinstance(track.get(key), list) and len(track[key]) in (2, 3), 'Invalid source vector: ' + key)
            for value in track[key]:
                _number(value, key)
        require(math.isclose(sum(x*x for x in track['direction']), 1, abs_tol=1e-12), 'Direction not normalized')
        if len(track['start_um']) == 3:
            require(track['start_um'][2] == 0 and track['direction'][2] == 0, '2D probe must explicitly lie in z=0 plane')
        length = _number(track.get('length_um'), 'length_um')
        require(length > 0 and track.get('wt_hi_um') == .03 and track.get('time_s') == 1e-9
                and track.get('s_hi_s') == 2e-12, 'Source spatial/time kernel differs')
        for key in ('start_um', 'direction', 'length_um', 'wt_hi_um', 'time_s', 's_hi_s'):
            require(track.get(key) == contract['kernel'].get(key), 'Track differs from frozen kernel: ' + key)
        require(math.isclose(_number(track.get('let_pC_per_um'), 'LET') * length * 1000,
                             q, rel_tol=1e-12, abs_tol=1e-12), 'LET/length/charge does not close')
    if case == 'A4':
        for key in ('start_um', 'direction', 'length_um', 'wt_hi_um', 'time_s', 's_hi_s'):
            require(tracks[0][key] == tracks[1][key], 'A4 tracks do not overlap: ' + key)
    report['case_id'] = case
    report['event_id'] = event
    return p, source, contract


def _curves(archive, report):
    curves = {}
    for label, name in [('circuit', 'circuit.plt'), ('device', 'access_device.plt')]:
        names, raw = parse_plt(archive.read(name).decode('utf-8'))
        require('time' in names, 'Missing time dataset: ' + name)
        rows = legacy.clean(raw)
        require(abs(rows[-1]['time'] - 4e-9) <= TOLERANCES['final_time_abs_s'], name + ' does not reach 4 ns')
        require(rows[0]['time'] == 0, name + ' has no full-initialization time zero')
        curves[label] = rows
        curves[label + '_raw'] = raw
        report[label + '_samples'] = len(rows)
        report[label + '_datasets'] = names
    circuit_keys = {'v(sn)', 'v(bl)', 'v(ref)', 'v(wl)', 'i(access,sn)', 'i(access,bl)',
                    'i(cstore,sn)', 'i(cbl,bl)', 'i(cref,ref)', 'i(rsn,sn)', 'i(rbl,bl)',
                    'i(rref,ref)', 'i(rpre,bl)'}
    require(circuit_keys <= set(curves['circuit'][0]), 'Missing required circuit voltage/current data')
    device_keys = {port + ' ' + quantity for port in ('source', 'drain', 'gate', 'body')
                   for quantity in ('TotalCurrent', 'eCurrent', 'hCurrent', 'DisplacementCurrent')}
    require(device_keys <= set(curves['device'][0]), 'Missing required terminal/component currents')
    report['final_time_s'] = curves['circuit'][-1]['time']
    return curves


def _named_ion_blocks(text, opener='('):
    blocks = []
    closer = ')' if opener == '(' else '}'
    pattern = r'\bHeavyIon\s*\(\s*"([^"\r\n]+)"\s*\)\s*' + re.escape(opener)
    for match in re.finditer(pattern, text):
        depth, end = 1, match.end()
        while depth and end < len(text):
            depth += (text[end] == opener) - (text[end] == closer)
            end += 1
        require(depth == 0, 'Malformed named HeavyIon block')
        blocks.append({'name': match[1], 'body': text[match.end():end - 1],
                       'start': match.start(), 'end': end})
    require(len(blocks) == len(re.findall(r'\bHeavyIon\s*\(', text)), 'Unnamed/malformed HeavyIon statement')
    require(len({b['name'] for b in blocks}) == len(blocks), 'Duplicate named HeavyIon statement')
    return blocks


def _scalar(body, key):
    hits = re.findall(r'\b' + re.escape(key) + r'\s*=\s*([-+\d.eE]+)', body)
    require(len(hits) == 1, 'Missing/duplicate source scalar: ' + key)
    return _number(float(hits[0]), key)


def _vector(body, key):
    hits = re.findall(r'\b' + re.escape(key) + r'\s*=\s*\(([^()]*)\)', body)
    require(len(hits) == 1, 'Missing/duplicate source vector: ' + key)
    return [_number(float(v), key) for v in re.split(r'[,\s]+', hits[0].strip()) if v]


def _deck_checked(archive, p, source, contract):
    deck = archive.read('device.cmd').decode('utf-8')
    blocks = _named_ion_blocks(deck)
    expected = {track['source_name']: track for track in source['tracks']}
    require({block['name'] for block in blocks} == set(expected), 'Actual source names differ')
    for block in blocks:
        track, body = expected[block['name']], block['body']
        for key, field in [('StartPoint', 'start_um'), ('Direction', 'direction')]:
            require(_vector(body, key) == track[field], 'Actual source vector differs: ' + key)
        for key, field in [('Time', 'time_s'), ('Length', 'length_um'), ('Wt_hi', 'wt_hi_um'), ('LET_f', 'let_pC_per_um')]:
            require(math.isclose(_scalar(body, key), track[field], rel_tol=1e-12, abs_tol=0),
                    'Actual source scalar differs: ' + key)
        require(re.search(r'\bGaussian\b', body) and re.search(r'\bPicoCoulomb\b', body),
                'Source kernel or LET unit flag differs')
    parameter_files = re.findall(r'\bParameter\s*=\s*"([^"\r\n]+)"', deck)
    require(len(parameter_files) == 1, 'Missing/ambiguous HeavyIon parameter file')
    parameters = archive.read(parameter_files[0]).decode('utf-8')
    parameter_blocks = _named_ion_blocks(parameters, '{')
    require({b['name'] for b in parameter_blocks} == set(expected), 'Parameter-file source names differ')
    for block in parameter_blocks:
        assignments = re.findall(r'\b([a-zA-Z_]\w*)\s*=', block['body'])
        require(set(assignments) == set(contract['heavyion_parameters']) and
                len(assignments) == len(contract['heavyion_parameters']), 'Incomplete/extra HeavyIon coefficients')
        for key, value in contract['heavyion_parameters'].items():
            require(_scalar(block['body'], key) == value, 'HeavyIon parameter differs: ' + key)
    # Verify the complete circuit/physics/timing remains the known R50 template.
    stripped = deck
    for block in reversed(blocks):
        stripped = stripped[:block['start']] + stripped[block['end']:]
    stripped = re.sub(r'\bParameter\s*=\s*"[^"\r\n]+"', '', stripped)
    base = _module(V3 / 'build_case.py', '_v4_probe_readonly_deck_template')
    expected_deck = base._single_device(p['target_voltage_V'], p['step_scale'],
                                        rad='HeavyIonChargeDensity HeavyIonGeneration',
                                        cur='CurrentPlot { HeavyIonGeneration(Integrate(Semiconductor)) }')
    require(re.sub(r'\s+', '', stripped) == re.sub(r'\s+', '', expected_deck),
            'Actual physics/circuit/timing differs from inherited full-initialization template')
    return deck, len(blocks), parameter_files[0]


def _source_audit(archive, p, source, curves, report):
    contract = json_load(archive.read('source-contract.json'))
    deck, count, parameter_file = _deck_checked(archive, p, source, contract)
    require(re.search(r'\bAreaFactor\s*=\s*1(?:\s|\b)', deck), 'Missing AreaFactor=1')
    require(count == len(source['tracks']), 'Actual HeavyIon source count differs')
    require('HeavyIonGeneration(Integrate(Semiconductor))' in re.sub(r'\s+', '', deck),
            'Missing semiconductor-integrated HeavyIonGeneration output request')
    names = [name for name in curves['device'][0] if 'HeavyIonGeneration' in name]
    require(len(names) <= 1, 'Ambiguous generation output; raw dataset identity must be reviewed')
    q = p['source_charge_fC']
    require(q == 0 or len(names) == 1, 'Missing total HeavyIonGeneration output for nonzero source')
    values = [r[names[0]] for r in curves['device']] if names else []
    require(not values or min(values) >= 0, 'Negative HeavyIonGeneration')
    spatial_time_integral = integral(curves['device'], 'time', names[0]) if names else 0.
    # The inherited output spatial measure is um^3 for this 2D effective-1um model.
    pairs = spatial_time_integral * 1e-12
    generated = pairs * E_C * 1e15
    error = abs(generated - q)
    radiation = {
        'target_fC': q, 'generated_fC': generated, 'generated_pairs': pairs,
        'absolute_error_fC': error, 'relative_error': error / q if q else None,
        'generation_dataset': names[0] if names else None,
        'generation_evidence': 'raw_spatial_generation_integral' if names else 'source_free_deck_without_generation_dataset',
        'numerical_zero_field_observed': bool(names) and all(value == 0 for value in values),
        'raw_spatial_time_integral': spatial_time_integral,
        'integration': 'trapezoid on original accepted times after duplicate-time cleanup',
        'units': {'density': 'cm^-3 s^-1', 'spatial_measure': 'um^3 (2D effective thickness 1 um)',
                  'time': 's', 'um3_to_cm3': 1e-12, 'elementary_charge_C': E_C,
                  'formula': 'Q[fC] = integral(G_integrated dt) * 1e-12 * e[C] * 1e15'},
        'pair_charge_convention': 'one elementary charge per electron-hole pair; no factor of two',
        'dimension_scope': 'Inherited normalization checked structurally, not an independent 3D volume calibration.',
        'source_parameter_file': parameter_file,
    }
    report['radiation'] = radiation
    if q:
        require(error / q <= TOLERANCES['source_relative'], 'TCAD source integral exceeds frozen 5% tolerance')
    else:
        require(count == 0 and generated <= TOLERANCES['zero_charge_fC'], 'A0 is not a zero source')
    return radiation


def _response(p, curves, report):
    rows = curves['circuit']
    checkpoints = {}
    for label, time in [('prestrike', .95e-9), ('hold_end', 2.8e-9), ('precharge_end', 3e-9), ('read', 4e-9)]:
        checkpoints[label] = {'time_s': time, **{key: legacy.sample(rows, key, time)
                                              for key in ('v(sn)', 'v(bl)', 'v(ref)', 'v(wl)')}}
    report['voltages'] = checkpoints
    report['terminal_currents'] = {}
    for port in ('source', 'drain', 'gate', 'body'):
        report['terminal_currents'][port] = {}
        for quantity in ('TotalCurrent', 'eCurrent', 'hCurrent', 'DisplacementCurrent'):
            key = port + ' ' + quantity
            report['terminal_currents'][port][quantity] = {
                'peak_abs_A': max(abs(r[key]) for r in curves['device']),
                'full_integral_trapezoid_fC': integral(curves['device'], 'time', key) * 1e15,
            }
    require(abs(checkpoints['prestrike']['v(sn)'] - p['target_voltage_V']) <= .001,
            'Initial SN target differs by more than inherited 1 mV')
    require(abs(checkpoints['precharge_end']['v(bl)'] - .5) <= 1e-5 and
            abs(checkpoints['precharge_end']['v(ref)'] - .5) <= 1e-5, 'Precharge endpoint differs')
    for row in rows:
        expected = 1.8 * min(1, max(0, (row['time'] - 3.05e-9) / .05e-9))
        require(abs(row['v(wl)'] - expected) <= 1e-7, 'Read wordline waveform differs')
    phases, balances, kcl, ports, closure = legacy.conservation(curves['circuit_raw'], {'access': curves['device']}, p)
    report['conservation'] = {'BE_charge_checks': balances, 'max_kcl_A': kcl,
                              'read_port_integrals_fC': ports, 'four_terminal_closure': closure,
                              'tolerance_basis': 'Unchanged inherited R50 conservation checks; see parser_source_sha256.'}
    return True


def _load_run(run_path, project_path=None):
    folder = Path(run_path).resolve()
    report = _report('dram-see-v4-source-probe-audit')
    report['run_path'] = str(folder)
    checks = Checks(report)
    manifest = checks.call('manifest_and_frozen_inputs', lambda: _manifest(folder, report))
    bundle = {'summary': report}
    if manifest is None:
        return bundle
    def inspect():
        with Archive(folder / 'results.tar') as archive:
            checks.call('execution_and_archived_input_provenance',
                        lambda: _provenance(archive, manifest, folder, project_path, report))
            contracts = checks.call('frozen_source_and_model_contract', lambda: _contracts(archive, report))
            curves = checks.call('finite_complete_raw_curves', lambda: _curves(archive, report))
            if curves is not None:
                bundle['curves'] = curves
            if contracts is not None:
                p, source, contract = contracts
                bundle.update(parameters=p, source=source, contract=contract)
                if curves is not None:
                    checks.call('source_charge_and_dimension', lambda: _source_audit(archive, p, source, curves, report))
                    checks.call('response_and_circuit_conservation', lambda: _response(p, curves, report))
        require(sha_file(folder / 'manifest.json') == report['manifest_sha256'], 'Manifest changed during audit')
        require(sha_file(folder / 'results.tar') == report['archive_sha256'], 'Archive changed during audit')
        return True
    checks.call('archive_safety_and_stability', inspect)
    report['passed'] = not report['errors'] and len(report['checks']) == 7
    if report['passed']:
        report['status'] = 'SOURCE_PROBE_RUN_CHECKS_PASSED'
    return bundle


def _csv(path, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _output(directory, report, curves=None):
    if directory is None:
        return
    destination = Path(directory).resolve()
    allowed = (ROOT / 'local_runtime/dram-see-v4/source-probe', HERE / 'data', HERE / 'results')
    require(any(destination.is_relative_to(base) and destination != base for base in allowed),
            'Output must be a child of local_runtime/dram-see-v4/source-probe or source-probe/data')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'audit.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    if curves:
        for label, rows in curves.items():
            _csv(destination / (label + '.csv'), rows)


def audit(run_path, project_path=None, output=None):
    """Return failures as JSON; output is an explicit, scoped export directory."""
    bundle = _load_run(run_path, project_path)
    _output(output, bundle['summary'], bundle.get('curves'))
    return bundle['summary']


def _sample_series(rows, key, times):
    observed = [row['time'] for row in rows]
    values = []
    for time in times:
        require(observed[0] <= time <= observed[-1], 'Pair comparison would extrapolate')
        index = bisect.bisect_left(observed, time)
        if index < len(rows) and observed[index] == time:
            values.append(rows[index][key])
        else:
            a, b = rows[index - 1], rows[index]
            fraction = (time - a['time']) / (b['time'] - a['time'])
            values.append(a[key] + fraction * (b[key] - a[key]))
    return values


def _pair_curve(a, b, key_a, key_b=None, absolute=0., relative=0.):
    times = sorted({row['time'] for row in a} | {row['time'] for row in b})
    av, bv = _sample_series(a, key_a, times), _sample_series(b, key_b or key_a, times)
    differences = [abs(x - y) for x, y in zip(av, bv)]
    worst = max(range(len(times)), key=differences.__getitem__)
    scale = max(map(abs, av + bv))
    tolerance = absolute + relative * scale
    return {'passed': differences[worst] <= tolerance, 'max_abs_difference': differences[worst],
            'paired_peak_abs': scale, 'limit': tolerance, 'worst_time_s': times[worst],
            'samples_union': len(times), 'normalized_max_difference': differences[worst] / scale if scale else 0.,
            'method': 'piecewise-linear union of original time grids; no extrapolation'}


def compare(a0_run, a1_run, a4_run, project_paths=None, output=None):
    """Re-audit three archives; compare equivalent sources and continuous responses."""
    report = _report('dram-see-v4-source-probe-comparison')
    checks = Checks(report)
    project_paths = project_paths or {}
    bundles = {case: _load_run(run, project_paths.get(case)) for case, run in
               [('A0', a0_run), ('A1', a1_run), ('A4', a4_run)]}
    report['runs'] = {case: bundle['summary'] for case, bundle in bundles.items()}
    def ready():
        for case, bundle in bundles.items():
            require(bundle['summary']['passed'], case + ' did not pass its own raw audit')
            require(bundle['summary'].get('case_id') == case, 'Wrong comparison role: ' + case)
        require(len({b['summary']['run_id'] for b in bundles.values()}) == 3, 'Runs must be distinct')
        return True
    if checks.call('three_independent_audited_cases', ready):
        def matching():
            hashes = [b['summary'].get('mesh_sha256') for b in bundles.values()]
            require(all(hashes) and len(set(hashes)) == 1, 'Actual mesh bytes differ; geometry equality is insufficient')
            require(len({b['summary']['source_contract_sha256'] for b in bundles.values()}) == 1,
                    'Source contracts differ')
            matches = [b['parameters'].get('matching_contract_sha256') for b in bundles.values()]
            require(all(matches) and len(set(matches)) == 1, 'Common model/timing matching contracts differ')
            return True
        checks.call('same_actual_mesh_and_common_model', matching)
        a, b = bundles['A1'], bundles['A4']
        def source_pair():
            qa, qb = a['summary']['radiation']['generated_fC'], b['summary']['radiation']['generated_fC']
            report['generated_charge_difference_fC'] = abs(qa - qb)
            report['generation_curve'] = _pair_curve(
                a['curves']['device'], b['curves']['device'],
                a['summary']['radiation']['generation_dataset'], b['summary']['radiation']['generation_dataset'],
                relative=TOLERANCES['pair_generation_curve_relative'])
            require(abs(qa - qb) <= TOLERANCES['pair_generated_charge_abs_fC'], 'A1/A4 generated charge differs')
            require(report['generation_curve']['passed'], 'A1/A4 total generation curves differ')
            return True
        checks.call('equivalent_total_generation', source_pair)
        def response_pair():
            response = {}
            for key in ('v(sn)', 'v(bl)', 'v(ref)', 'v(wl)'):
                response[key] = _pair_curve(a['curves']['circuit'], b['curves']['circuit'], key,
                                            absolute=TOLERANCES['pair_voltage_abs_V'])
            for key in ('i(access,sn)', 'i(access,bl)'):
                response[key] = _pair_curve(a['curves']['circuit'], b['curves']['circuit'], key,
                                            absolute=TOLERANCES['pair_current_abs_A'], relative=TOLERANCES['pair_current_relative'])
            for port in ('source', 'drain', 'gate', 'body'):
                key = port + ' TotalCurrent'
                response[key] = _pair_curve(a['curves']['device'], b['curves']['device'], key,
                                            absolute=TOLERANCES['pair_current_abs_A'], relative=TOLERANCES['pair_current_relative'])
            report['continuous_response_equivalence'] = response
            require(all(value['passed'] for value in response.values()), 'A1/A4 voltage or terminal-current curve differs')
            return True
        checks.call('equivalent_continuous_response', response_pair)
        def deltas():
            control = bundles['A0']['curves']['circuit']
            result = {}
            for case in ('A1', 'A4'):
                bundle = bundles[case]
                rows = bundle['curves']['circuit']
                delta_sn = legacy.sample(rows, 'v(sn)', 2.8e-9) - legacy.sample(control, 'v(sn)', 2.8e-9)
                delta_bl = legacy.sample(rows, 'v(bl)', 4e-9) - legacy.sample(control, 'v(bl)', 4e-9)
                result[case] = {'delta_SN_hold_V': delta_sn,
                                'delta_Qstore_hold_fC': bundle['parameters']['capacitance_F'] * delta_sn * 1e15,
                                'delta_BL_read_V': delta_bl,
                                'definition': 'signal minus same-bit A0; no neutral-cell classification'}
            report['responses_relative_to_A0'] = result
            return True
        checks.call('control_relative_continuous_observables', deltas)
    report['passed'] = not report['errors'] and len(report['checks']) == 5
    if report['passed']:
        report['status'] = 'A0_A1_A4_SOURCE_EQUIVALENCE_CHECKS_PASSED'
    _output(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    one = commands.add_parser('audit')
    one.add_argument('run_path', type=Path)
    one.add_argument('--project', type=Path)
    one.add_argument('--output', type=Path)
    pair = commands.add_parser('compare')
    for case in ('a0', 'a1', 'a4'):
        pair.add_argument(case + '_run', type=Path)
        pair.add_argument('--' + case + '-project', type=Path)
    pair.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'audit':
        result = audit(args.run_path, args.project, args.output)
    else:
        result = compare(args.a0_run, args.a1_run, args.a4_run,
                         {'A0': args.a0_project, 'A1': args.a1_project, 'A4': args.a4_project}, args.output)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
