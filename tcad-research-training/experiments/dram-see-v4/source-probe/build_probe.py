"""Build immutable A0/A1/A4 source-interface inputs; never contact or run a solver."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONTRACT = HERE / 'source_contract.json'
OUTPUT_ROOT = ROOT / 'local_runtime/dram-see-v4/source-probe'
LEGACY = ROOT / 'experiments/dram-see-v3/r50-main/build_case.py'
V1 = ROOT / 'experiments/dram-see-v1/build_case.py'
REFERENCE = ROOT / 'local_runtime/dram-see-v1/heavyion-reference.txt'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON field: ' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON constant: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=invalid)


def load_contract():
    value = read_json(CONTRACT)
    if value.get('schema') != 'dram-see-v4-source-probe-contract' or value.get('revision') != 1:
        raise ValueError('Unknown source contract')
    if value['device'] != {'gate_length_um': .25, 'oxide_nm': 5., 'silicon_x_um': [0., .85],
                          'silicon_y_um': [0., 1.2], 'dimension': 2,
                          'effective_thickness_um': 1., 'mesh_scale': 1., 'step_scale': 1.}:
        raise ValueError('Source probe device is frozen')
    required_kernel = {'shape': 'Gaussian', 'start_mode': 'StartPoint', 'start_um': [.425, .3],
                       'direction': [0., 1.], 'length_um': .6, 'wt_hi_um': .03,
                       'time_s': 1e-9, 's_hi_s': 2e-12, 'time_domain_s': [0., 4e-9]}
    if any(value['kernel'].get(k) != v for k, v in required_kernel.items()):
        raise ValueError('Source kernel is frozen')
    return value


def make_spec(case_id, contract=None):
    c = load_contract() if contract is None else contract
    if case_id not in ('A0', 'A1', 'A4'):
        raise ValueError('Unknown probe case')
    kernel = c['kernel']
    tracks = []
    for index, q in enumerate(c['cases'][case_id]['track_charges_fC'], 1):
        tracks.append({'track_id': index, 'parent_id': 0, 'source_name': 'Ion' + str(index),
                       'q_fC': q, 'start_um': kernel['start_um'],
                       'direction': kernel['direction'], 'length_um': kernel['length_um'],
                       'wt_hi_um': kernel['wt_hi_um'], 'time_s': kernel['time_s'],
                       's_hi_s': kernel['s_hi_s'],
                       'let_pC_per_um': q * c['conversion']['fC_to_pC'] / kernel['length_um']})
    return {'schema': 'dram-see-v4-source-spec', 'case_id': case_id,
            'event_id': 'synthetic-v4-source-probe-' + case_id.lower(),
            'synthetic': True, 'dimension': 2, 'source_total_fC': c['cases'][case_id]['total_charge_fC'],
            'tracks': tracks, 'units': c['units']}


def validate_spec(spec, case_id=None):
    if not isinstance(spec, dict):
        raise ValueError('Source specification must be an object')
    case = spec.get('case_id') if case_id is None else case_id
    expected = make_spec(case)
    # Exact schema prevents silently defaulting missing, unknown, conflicting or bool fields.
    if canonical(spec) != canonical(expected):
        raise ValueError('Source specification differs from the frozen probe; missing/conflicting fields rejected')
    return expected


def _simpson(function, a, b, n=2048):
    if b <= a:
        return 0.
    h = (b - a) / n
    return h / 3 * (function(a) + function(b)
                    + 4 * math.fsum(function(a + i * h) for i in range(1, n, 2))
                    + 2 * math.fsum(function(a + i * h) for i in range(2, n, 2)))


def temporal(t, track):
    if t < 0:
        return 0.
    s, t0 = track['s_hi_s'], track['time_s']
    return math.exp(-((t - t0) / (2 * s)) ** 2) / (s * math.sqrt(math.pi) * (1 + math.erf(t0 / (2 * s))))


def generation(spec, x, y, t):
    """Manufactured kernel [pairs/cm^3/s]; not a sampled TCAD field."""
    c = load_contract()
    e, d = c['conversion']['elementary_charge_C'], c['device']['effective_thickness_um']
    result = []
    for track in spec['tracks']:
        x0, y0 = track['start_um']
        if y0 <= y < y0 + track['length_um']:
            w = track['wt_hi_um']
            px = math.exp(-((x - x0) / w) ** 2) / (math.sqrt(math.pi) * w)
            # 1 um^3 = 1e-12 cm^3; the 2D reference thickness is explicit.
            result.append(track['q_fC'] * 1e-15 / e * px / track['length_um'] / d * 1e12 * temporal(t, track))
    return math.fsum(result)


def offline_check(spec):
    spec = validate_spec(spec)
    c = load_contract()
    xlo, xhi = c['device']['silicon_x_um']
    ylo, yhi = c['device']['silicon_y_um']
    tlo, thi = c['kernel']['time_domain_s']
    parts = []
    for track in spec['tracks']:
        x0, y0 = track['start_um']
        w, length, s, t0 = (track[k] for k in ('wt_hi_um', 'length_um', 's_hi_s', 'time_s'))
        fx = (math.erf((xhi - x0) / w) - math.erf((xlo - x0) / w)) / 2
        fy = max(0., min(yhi, y0 + length) - max(ylo, y0)) / length
        ft = (math.erf((thi - t0) / (2 * s)) - math.erf((tlo - t0) / (2 * s))) / (1 + math.erf(t0 / (2 * s)))
        nx = _simpson(lambda x: math.exp(-((x - x0) / w) ** 2) / (math.sqrt(math.pi) * w), xlo, xhi)
        # This window omits <erfc(12) of normalized Gaussian mass; avoid missing the narrow pulse.
        nt = _simpson(lambda t: temporal(t, track), max(tlo, t0 - 24 * s), min(thi, t0 + 24 * s))
        analytic = track['q_fC'] * fx * fy * ft
        numerical = track['q_fC'] * nx * fy * nt
        tol = max(c['offline_tolerances']['charge_abs_fC'], c['offline_tolerances']['charge_relative'] * analytic)
        if abs(analytic - numerical) > tol:
            raise ValueError('Manufactured source quadrature does not close')
        if not math.isclose(track['let_pC_per_um'] * length * 1e3, track['q_fC'], rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError('LET length charge units do not close')
        parts.append({'track_id': track['track_id'], 'declared_fC': track['q_fC'],
                      'domain_fraction': fx * fy, 'time_fraction': ft,
                      'analytic_fC': analytic, 'numerical_fC': numerical,
                      'quadrature_error_fC': numerical - analytic,
                      'electron_hole_pairs': analytic * 1e-15 / c['conversion']['elementary_charge_C']})
    total = math.fsum(p['analytic_fC'] for p in parts)
    if abs(total - spec['source_total_fC']) > max(1e-6, .001 * spec['source_total_fC']):
        raise ValueError('Unexpected domain or time clipping in interior probe')
    single, double = make_spec('A1'), make_spec('A4')
    error = 0.
    # Independent source summation; includes off-axis and pre/post-pulse points.
    for x in (.0, .3, .395, .425, .455, .55, .85):
        for y in (.0, .299, .3, .6, .899, .901, 1.2):
            for offset in (-12, -4, -1, 0, 1, 4, 12):
                t = 1e-9 + offset * 2e-12
                g1, g4 = generation(single, x, y, t), generation(double, x, y, t)
                error = max(error, abs(g1 - g4) / max(abs(g1), 1.))
    if error > 1e-12:
        raise ValueError('A4 two half sources are not field-equivalent to A1')
    return {'schema': 'dram-see-v4-source-offline-check', 'case_id': spec['case_id'],
            'status': 'SYNTHETIC_OFFLINE_CHECK_PASSED', 'is_tcad_result': False,
            'analytic_charge_fC': total, 'tracks': parts,
            'A1_A4_manufactured_field_max_relative_difference': error,
            'scope': 'Prescribed analytic kernel and unit arithmetic only; not actual Sentaurus parsing, generation or response'}


def _legacy_module():
    spec = importlib.util.spec_from_file_location('_v4_source_probe_readonly_legacy', LEGACY)
    module = importlib.util.module_from_spec(spec)
    exec(compile(LEGACY.read_bytes(), str(LEGACY), 'exec'), module.__dict__)
    return module


def _number(value):
    return format(value, '.17g')


def render_sources(spec):
    blocks = []
    for track in spec['tracks']:
        x, y = map(_number, track['start_um'])
        blocks.append('HeavyIon("' + track['source_name'] + '") ( '
                      + f'StartPoint=({x},{y}) Direction=(0,1) Time={_number(track["time_s"])} '
                      + f'Length={_number(track["length_um"])} Wt_hi={_number(track["wt_hi_um"])} '
                      + f'LET_f={_number(track["let_pC_per_um"])} Gaussian PicoCoulomb )')
    return '\n '.join(blocks)


def render_parameters(spec):
    c = load_contract()
    blocks = ['* W-2024.09 table 143 and page 816; explicit named source coefficients.']
    for track in spec['tracks']:
        blocks.append('HeavyIon("' + track['source_name'] + '") {\n'
                      + '\n'.join('  ' + k + ' = ' + _number(v) for k, v in c['heavyion_parameters'].items()) + '\n}')
    return '\n'.join(blocks) + '\n'


def build(out, case_id, bit=1, supplied_spec=None):
    if type(bit) is not int or bit not in (0, 1):
        raise ValueError('stored_bit must be integer 0 or 1')
    spec = make_spec(case_id) if supplied_spec is None else validate_spec(supplied_spec, case_id)
    proof = offline_check(spec)
    out = Path(out).resolve()
    allowed = OUTPUT_ROOT.resolve()
    if not out.is_relative_to(allowed) or out == allowed:
        raise ValueError('Inputs must stay under local_runtime/dram-see-v4/source-probe')
    if not re.fullmatch(r'v4-source-probe-' + case_id.lower() + '-b' + str(bit) + r'(?:-[a-z0-9_-]+)?', out.name):
        raise ValueError('Output name must bind v4 probe case and bit')
    if out.exists():
        raise ValueError('Immutable output already exists; do not overwrite or resubmit')
    c = load_contract()
    legacy = _legacy_module()
    target = .1 if bit == 0 else .9
    out.parent.mkdir(parents=True, exist_ok=True)
    geometry = legacy._geometry(.25, 1., 5., out.parent)
    base_deck = legacy._single_device(target, 1.)
    deck = legacy._single_device(target, 1., render_sources(spec),
                                 'HeavyIonChargeDensity HeavyIonGeneration',
                                 'CurrentPlot { HeavyIonGeneration(Integrate(Semiconductor)) }')
    deck = legacy._replace_once(deck, 'Plot="device.tdr"', 'Plot="device.tdr" Parameter="heavyion.par"')
    common = {'gate_length_um': .25, 'oxide_nm': 5., 'stored_bit': bit, 'target_voltage_V': target,
              'reference_mode': 'offline', 'neutral': False, 'capacitance_F': 1e-14,
              'bitline_capacitance_F': 1e-13, 'reference_capacitance_F': 1e-13,
              'effective_thickness_um': 1., 'temperature_K': 300, 'prestrike_s': .95e-9,
              'strike_s': 1e-9, 'hold_end_s': 2.8e-9, 'precharge_end_s': 3e-9,
              'read_sample_s': 4e-9, 'clamp_release_s': .6e-9,
              'precharge_V': .5, 'precharge_resistance_on_ohm': 50.,
              'precharge_resistance_off_ohm': 1e20, 'precharge_ramp_end_s': 2.9e-9,
              'wordline_rise_start_s': 3.05e-9, 'wordline_rise_end_s': 3.10e-9,
              'wordline_read_V': 1.8, 'mesh_scale': 1., 'step_scale': 1.,
              'geometry_sha256': sha(geometry), 'physics': legacy.PHYSICS,
              'circuit_revision': legacy.CIRCUIT, 'base_control_deck_sha256': sha(base_deck.encode())}
    code = {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in
            (Path(__file__), CONTRACT, LEGACY, V1, ROOT / 'scripts/tcad.py', REFERENCE,
             ROOT / 'local_runtime/dram-see-v4/preflight/hadronic-and-parameters/stdout.txt')}
    parameters = {**common, 'schema': 'dram-see-v4-source-probe', 'case_id': case_id,
                  'event_id': spec['event_id'], 'synthetic': True, 'source_count': len(spec['tracks']),
                  'source_charge_fC': spec['source_total_fC'], 'total_charge_fC': spec['source_total_fC'],
                  'charge_pc': spec['source_total_fC'] * .001, 'parent_run': None,
                  'source_spec_file': 'source-spec.json', 'source_contract_file': 'source-contract.json',
                  'source_spec_sha256': sha(encoded(spec)), 'source_contract_sha256': sha(CONTRACT.read_bytes()),
                  'matching_contract': common, 'matching_contract_sha256': sha(encoded(common)),
                  'source_code_sha256': code, 'scope': c['scope'],
                  'initialization': 'Inherited ideal SN clamp; no calibrated transistor write',
                  'execution_authorization': 'Main agent only; initial real probe limited to bit 1 A0/A1/A4'}
    outputs = ['circuit.plt', 'access_device.plt', 'final_access_des.tdr', 'transient_des.log']
    project = {'name': out.name, 'steps': [
        {'tool': 'sde', 'args': ['-e', '-l', 'geometry.scm'], 'outputs': ['cell_msh.tdr']},
        {'tool': 'sdevice', 'args': ['device.cmd'], 'outputs': outputs}]}
    files = {'geometry.scm': geometry, 'device.cmd': deck.encode(),
             'heavyion.par': render_parameters(spec).encode(), 'parameters.json': encoded(parameters),
             'project.json': encoded(project), 'source-spec.json': encoded(spec),
             'source-contract.json': CONTRACT.read_bytes(), 'offline-source-check.json': encoded(proof),
             'generator-sha256.txt': (sha(Path(__file__).read_bytes()) + '\n').encode()}
    manifest = {'schema': 'dram-see-v4-source-input-manifest', 'case_id': case_id, 'stored_bit': bit,
                'event_id': spec['event_id'], 'files_sha256': {name: sha(data) for name, data in files.items()},
                'source_code_sha256': code, 'solver_started': False}
    out.mkdir(exist_ok=False)
    for name, data in {**files, 'input-manifest.json': encoded(manifest)}.items():
        with (out / name).open('xb') as stream:
            stream.write(data)
    return check_project(out)


def check_project(project):
    project = Path(project).resolve()
    if not project.is_relative_to(OUTPUT_ROOT.resolve()) or project == OUTPUT_ROOT.resolve():
        raise ValueError('Not a v4 source-probe input directory')
    manifest = read_json(project / 'input-manifest.json')
    expected_files = set(manifest['files_sha256']) | {'input-manifest.json'}
    if {p.name for p in project.iterdir()} != expected_files or any(p.is_symlink() or not p.is_file() for p in project.iterdir()):
        raise ValueError('Input inventory differs or contains directories/symlinks')
    for name, digest in manifest['files_sha256'].items():
        if '/' in name or '\\' in name or sha((project / name).read_bytes()) != digest:
            raise ValueError('Input hash mismatch: ' + name)
    if (project / 'source-contract.json').read_bytes() != CONTRACT.read_bytes():
        raise ValueError('Source contract differs from frozen revision')
    for name, digest in manifest['source_code_sha256'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or sha(path.read_bytes()) != digest:
            raise ValueError('Generator/reference/runner changed: ' + name)
    spec = validate_spec(read_json(project / 'source-spec.json'))
    p = read_json(project / 'parameters.json')
    if (p.get('schema') != 'dram-see-v4-source-probe' or type(p.get('stored_bit')) is not int
            or p['stored_bit'] not in (0, 1) or p['case_id'] != spec['case_id']
            or p['source_spec_sha256'] != sha(encoded(spec)) or p['event_id'] != spec['event_id']
            or p['source_contract_sha256'] != sha(CONTRACT.read_bytes())):
        raise ValueError('Parameter/source identity mismatch')
    if (p['charge_pc'] != spec['source_total_fC'] * .001 or p['total_charge_fC'] != spec['source_total_fC']
            or p['source_charge_fC'] != spec['source_total_fC'] or p['source_count'] != len(spec['tracks'])
            or p['source_code_sha256'] != manifest['source_code_sha256']
            or p['matching_contract_sha256'] != sha(encoded(p['matching_contract']))):
        raise ValueError('Source totals conflict')
    if any(p.get(key) != value for key, value in p['matching_contract'].items()):
        raise ValueError('Parameters differ from their matching contract')
    if p['geometry_sha256'] != sha((project / 'geometry.scm').read_bytes()):
        raise ValueError('Geometry differs from matching contract')
    if (project / 'heavyion.par').read_text() != render_parameters(spec):
        raise ValueError('Named source parameter file differs')
    expected_source = render_sources(spec)
    deck = (project / 'device.cmd').read_text()
    if (expected_source and expected_source not in deck) or len(re.findall(r'\bHeavyIon\s*\(', deck)) != len(spec['tracks']):
        raise ValueError('Source deck count or values differ')
    legacy = _legacy_module()
    target = .1 if p['stored_bit'] == 0 else .9
    expected_deck = legacy._single_device(target, 1., expected_source,
                                         'HeavyIonChargeDensity HeavyIonGeneration',
                                         'CurrentPlot { HeavyIonGeneration(Integrate(Semiconductor)) }')
    expected_deck = legacy._replace_once(expected_deck, 'Plot="device.tdr"', 'Plot="device.tdr" Parameter="heavyion.par"')
    if deck != expected_deck or p['target_voltage_V'] != target:
        raise ValueError('Device, initial state or readout differs from inherited frozen template')
    runner = read_json(project / 'project.json')
    if runner['name'] != project.name or manifest['case_id'] != p['case_id'] or manifest['stored_bit'] != p['stored_bit']:
        raise ValueError('Project name/case/bit mismatch')
    return {'schema': 'dram-see-v4-source-input-check', 'status': 'OFFLINE_INPUT_CHECK_PASSED',
            'project': project.relative_to(ROOT).as_posix(), 'case_id': p['case_id'],
            'stored_bit': p['stored_bit'], 'input_manifest_sha256': sha((project / 'input-manifest.json').read_bytes()),
            'offline_source_check': offline_check(spec), 'solver_started': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    make = sub.add_parser('build')
    make.add_argument('output', type=Path)
    make.add_argument('--case', choices=('A0', 'A1', 'A4'), required=True)
    make.add_argument('--bit', type=int, choices=(0, 1), default=1)
    make.add_argument('--spec', type=Path)
    inspect = sub.add_parser('check')
    inspect.add_argument('project', type=Path)
    pure = sub.add_parser('check-source')
    pure.add_argument('--case', choices=('A0', 'A1', 'A4'), required=True)
    args = parser.parse_args()
    if args.command == 'build':
        result = build(args.output, args.case, args.bit, read_json(args.spec) if args.spec else None)
    elif args.command == 'check':
        result = check_project(args.project)
    else:
        result = offline_check(make_spec(args.case))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
