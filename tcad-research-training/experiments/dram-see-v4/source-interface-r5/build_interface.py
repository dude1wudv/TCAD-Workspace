"""Frozen r5 artificial 2D source inputs and offline proofs; never runs a solver."""
import argparse
import ast
import importlib.util
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONTRACT = HERE / 'source_contract.json'
OUTPUT_ROOT = ROOT / 'local_runtime/dram-see-v4/source-interface-r5'
R2 = ROOT / 'experiments/dram-see-v4/source-interface-r2'
R3 = ROOT / 'experiments/dram-see-v4/source-interface-r3'
R4 = ROOT / 'experiments/dram-see-v4/source-interface-r4'
V1 = ROOT / 'experiments/dram-see-v1/build_case.py'
DYNAMIC_PLOT = 'Plot(FilePrefix="gstep" Time=(Range=(0.95e-9 1.05e-9)) NoOverwrite)'
PRIMARY_ROLES = [
    ['A4', 1, 'main'], ['A5', 1, 'main'], ['A0', 1, 'fine'],
    ['A6', 1, 'main'], ['A7', 1, 'main'], ['A2', 1, 'main'], ['A3', 1, 'main'],
    ['A8S2', 1, 'main'], ['A8S4', 1, 'main'],
    ['A0', 0, 'main'], ['A1', 0, 'main'], ['A4', 0, 'main'],
    ['A0', 1, 'time'], ['A1', 1, 'time'], ['A6', 1, 'time'],
    ['A1', 1, 'fine'], ['A5', 1, 'fine']]
REUSE_ROLES = [['A0', 1, 'main'], ['A1', 1, 'main']]
PROFILES = {'main': {'mesh_factor': .5, 'pulse_max_step_s': 5e-13},
            'time': {'mesh_factor': .5, 'pulse_max_step_s': 2.5e-13},
            'fine': {'mesh_factor': .25, 'pulse_max_step_s': 5e-13}}


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), m.__dict__)
    return m


r2 = module(R2 / 'build_interface.py', '_r5_frozen_r2')
r3 = module(R3 / 'build_interface.py', '_r5_frozen_r3')
r4 = module(R4 / 'build_interface.py', '_r5_frozen_r4')
read_json, encoded, sha, number = r2.read_json, r2.encoded, r2.sha, r2.number
oracle = r3.oracle


def _geometry_bytes(mesh):
    """Render the exact frozen v1 geometry expression, without its old run-domain gate.

    v1 build() only allowed mesh>=0.4. The r5-authorized 0.25 factor uses the
    same geometry f-string, not a patched old function or an independently
    maintained device. No solver or temporary project is involved.
    """
    if type(mesh) not in (int, float) or mesh not in (.5, .25):
        raise ValueError('Only the approved 0.5/0.25 mesh factors may be rendered')
    source = V1.read_bytes()
    if sha(source) != '7a22e53bc939b236b0b612f42e382b952c362042b28e187414e481e77b9916bd':
        raise ValueError('Frozen geometry source SHA differs')
    tree = ast.parse(source, filename=str(V1))
    builds = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build']
    if len(builds) != 1:
        raise ValueError('Frozen geometry build function is missing or ambiguous')
    build = builds[0]
    assignments = [n for n in build.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'geometry' for t in n.targets)]
    if len(assignments) != 1 or not isinstance(assignments[0].value, ast.JoinedStr):
        raise ValueError('Frozen geometry expression is missing or ambiguous')
    expression = ast.Expression(body=assignments[0].value)
    names = {n.id for n in ast.walk(expression) if isinstance(n, ast.Name)}
    allowed = (ast.Expression, ast.JoinedStr, ast.FormattedValue, ast.Constant,
               ast.BinOp, ast.Name, ast.Load, ast.Add, ast.Mult, ast.Div)
    if names != {'length', 'width', 'mesh'} or any(not isinstance(n, allowed) for n in ast.walk(expression)):
        raise ValueError('Unexpected geometry expression dependency')
    # Match frozen v1 write_text bytes on the Windows project host; old r4
    # geometry is explicitly checked below. No arbitrary function executes.
    text = eval(compile(expression, str(V1), 'eval'), {'__builtins__': {}},
                {'length': .25, 'width': .25 + .6, 'mesh': mesh})
    reference = ROOT / 'local_runtime/dram-see-v4/source-interface-r4/inputs/v4-source-interface-r4-a0-b1-mesh/geometry.scm'
    newline = b'\r\n' if b'\r\n' in reference.read_bytes() else b'\n'
    return text.encode().replace(b'\n', newline)


def contract():
    c = read_json(CONTRACT)
    if c.get('schema') != 'dram-see-v4-source-interface-r5-contract' or c.get('revision') != 5:
        raise ValueError('Wrong r5 contract')
    for name, digest in c['frozen_dependency_sha256'].items():
        if sha((ROOT / name).read_bytes()) != digest:
            raise ValueError('Frozen dependency changed: ' + name)
    if c['primary_roles'] != PRIMARY_ROLES or c['run_sequence'] != PRIMARY_ROLES or c['reuse_candidate_roles'] != REUSE_ROLES:
        raise ValueError('Approved role order changed')
    if c['variants'] != PROFILES or c['audit_tolerances'] != r4.contract()['audit_tolerances']:
        raise ValueError('Numerical profile or frozen tolerance changed')
    for key in ('device', 'units', 'conversion', 'heavyion_parameters', 'offline_tolerances',
                'partitions', 'pulse_output_window_s', 'tdr_times_s', 'case_ids'):
        if c[key] != r2.contract()[key]:
            raise ValueError('Frozen physical/offline definition changed: ' + key)
    expected_rois = dict(r2.contract()['rois_um'])
    expected_rois.update(SourceLeft=[.295, 0., .355, 1.2], SourceRight=[.495, 0., .555, 1.2])
    if c['rois_um'] != expected_rois or c['additional_roi_gate_cases'] != ['A5', 'A6', 'A7']:
        raise ValueError('ROI scope changed')
    if c['kernel'] != {**r3.contract()['kernel'], 'time_sigma_equals_s_hi': True}:
        raise ValueError('Source kernel differs from corrected r3 oracle')
    budget = c['global_budget']
    if [budget[k] for k in ('historical_attempts_at_freeze', 'maximum_tcad_attempts',
                            'this_round_maximum_attempts', 'primary_attempts', 'reserve_attempts')] != [5, 26, 21, 17, 4]:
        raise ValueError('Frozen campaign budget changed')
    if c['measurement']['dynamic_plot_command'] != DYNAMIC_PLOT or c['measurement']['window_can_pass_acceptance'] is not False:
        raise ValueError('Observation route differs')
    return c


def check_role(case, bit=1, variant='main'):
    c = contract()
    if type(bit) is not int or [case, bit, variant] not in c['primary_roles'] + c['reuse_candidate_roles']:
        raise ValueError('Not an approved primary role or offline reuse reference')


def source_spec(case):
    contract()
    return r2.make_spec(case)


def _temporal_moment(a, b, track):
    t0, sigma = track['time_s'], track['s_hi_s']
    a = max(a, 0.)
    return t0 * oracle.mass(a, b, t0, sigma) + sigma ** 2 * (
        oracle.instantaneous(a, t0, sigma) - oracle.instantaneous(b, t0, sigma))


def offline_proof(spec):
    """Analytic 11-ROI source ledger. This is never native TCAD evidence."""
    r2.validate_spec(spec)
    c = contract()
    rois = {}
    for roi, rect in c['rois_um'].items():
        parts = []
        for track in spec['tracks']:
            rough = r2.rectangle_moments(track, rect, 256)
            fine = r2.rectangle_moments(track, rect, 512)
            q = track['q_fC']
            tol = max(c['offline_tolerances']['charge_abs_fC'], c['offline_tolerances']['charge_relative'] * q * fine[0])
            if abs(rough[0] - fine[0]) * q > tol:
                raise ValueError('Offline spatial quadrature not converged: ' + roi)
            parts.append({'source_name': track['source_name'], 'fraction': fine[0], 'q_fC': q * fine[0],
                          'x_moment_fC_um': q * fine[1], 'y_moment_fC_um': q * fine[2],
                          'quadrature_error_fC': q * (rough[0] - fine[0]),
                          'time_s': track['time_s'], 's_hi_s': track['s_hi_s']})
        charge = math.fsum(p['q_fC'] for p in parts)
        temporal_charge = math.fsum(p['q_fC'] * oracle.mass(0., 4e-9, t['time_s'], t['s_hi_s'])
                                   for p, t in zip(parts, spec['tracks']))
        temporal_moment = math.fsum(p['q_fC'] * _temporal_moment(0., 4e-9, t)
                                   for p, t in zip(parts, spec['tracks']))
        rois[roi] = {'q_fC': charge, 'tracks': parts,
                     'centroid_x_um': math.fsum(p['x_moment_fC_um'] for p in parts) / charge if charge else None,
                     'centroid_y_um': math.fsum(p['y_moment_fC_um'] for p in parts) / charge if charge else None,
                     'time_centroid_s': temporal_moment / temporal_charge if temporal_charge else None}
    inside = rois['Total']['q_fC']
    return {'schema': 'dram-see-v4-source-interface-r5-offline', 'status': 'OFFLINE_ONLY', 'is_tcad_result': False,
            'case_id': spec['case_id'], 'source_total_fC': spec['source_total_fC'], 'domain_charge_fC': inside,
            'outside_domain_fC': spec['source_total_fC'] - inside, 'rois': rois,
            'time_kernel': 'UG p813 Eq810 sigma=s_hi; r3 corrected oracle; not measured data',
            'temporal_mass_0_to_4ns_by_source': {t['source_name']: oracle.mass(0., 4e-9, t['time_s'], t['s_hi_s']) for t in spec['tracks']},
            'temporal_mass_pulse_window_by_source': {t['source_name']: oracle.mass(*c['pulse_output_window_s'], t['time_s'], t['s_hi_s']) for t in spec['tracks']},
            'normalization': 'No clipping renormalization; each artificial segment owns its charge once',
            'additional_roi_gate_cases': c['additional_roi_gate_cases']}


def generation(spec, x, y, t):
    """Prescribed density [pairs/cm^3/s], not a measured field; sigma=s_hi."""
    r2.validate_spec(spec)
    c = contract()
    parts = []
    for track in spec['tracks']:
        dx, dy = track['direction'][:2]
        rx, ry = x - track['start_um'][0], y - track['start_um'][1]
        longitudinal, transverse = rx * dx + ry * dy, -rx * dy + ry * dx
        if 0 <= longitudinal < track['length_um']:
            width = track['wt_hi_um']
            parts.append(track['q_fC'] * 1e-15 / c['conversion']['elementary_charge_C'] * 1e12
                         / c['device']['effective_thickness_um'] * math.exp(-(transverse / width) ** 2)
                         / (math.sqrt(math.pi) * width * track['length_um'])
                         * oracle.instantaneous(t, track['time_s'], track['s_hi_s']))
    return math.fsum(parts)


def render_geometry(variant):
    c = contract()
    if variant not in PROFILES:
        raise ValueError('Unknown numerical profile')
    raw = _geometry_bytes(PROFILES[variant]['mesh_factor'])
    if sha(raw) != c['geometry_sha256_by_profile'][variant]:
        raise ValueError('Frozen geometry bytes differ')
    if variant in ('main', 'time'):
        for role in c['reuse_roles']:
            if raw != (ROOT / role['project_path'] / 'geometry.scm').read_bytes():
                raise ValueError('Main geometry must equal both registered r4 geometries')
    return raw


def current_plot(case):
    # Preserve successful r4 native diagnostic requests. The two extra ROIs
    # are independent offline/native-TDR windows, not a repaired Window path.
    source_spec(case)
    return r3.current_plot().replace(' Coordinates', '') if case == 'A0' else r3.current_plot()


def physical_deck(case, bit=1, variant='main'):
    check_role(case, bit, variant)
    return r2.render_deck(source_spec(case), bit, 'time' if variant == 'time' else 'mesh')


def render_deck(case, bit=1, variant='main'):
    deck = physical_deck(case, bit, variant)
    start = deck.index('CurrentPlot { HeavyIonGeneration(')
    end = deck.index('\nMath {', start)
    deck = deck[:start] + current_plot(case) + deck[end:]
    anchor = 'Coupled {Poisson Electron Hole Contact Circuit} Plot(FilePrefix="gfield_0"'
    if deck.count(anchor) != 1:
        raise ValueError('Injection output anchor changed')
    return deck.replace(anchor, 'Coupled {Poisson Electron Hole Contact Circuit}\n ' + DYNAMIC_PLOT + '\n Plot(FilePrefix="gfield_0"', 1)


def strip_observers(deck, case, bit=1, variant='main'):
    """Strictly restore the entire r2 physical deck, including original outputs."""
    original = physical_deck(case, bit, variant)
    expected = current_plot(case)
    start = original.index('CurrentPlot { HeavyIonGeneration(')
    end = original.index('\nMath {', start)
    if deck.count(expected) != 1 or deck.count(DYNAMIC_PLOT) != 1:
        raise ValueError('Observer block missing or duplicated')
    deck = deck.replace(expected, original[start:end], 1)
    injected = 'Coupled {Poisson Electron Hole Contact Circuit}\n ' + DYNAMIC_PLOT + '\n Plot(FilePrefix="gfield_0"'
    if deck.count(injected) != 1:
        raise ValueError('Dynamic plot outside injection transient')
    return deck.replace(injected, 'Coupled {Poisson Electron Hole Contact Circuit} Plot(FilePrefix="gfield_0"', 1)


def expected_common(bit, variant, geometry_sha256):
    c = contract()
    if type(bit) is not int or bit not in (0, 1) or variant not in PROFILES:
        raise ValueError('Invalid bit or numerical profile')
    if geometry_sha256 != c['geometry_sha256_by_profile'][variant]:
        raise ValueError('Wrong geometry for numerical profile')
    legacy = module(r2.LEGACY, '_r5_frozen_physics')
    return {'gate_length_um': .25, 'oxide_nm': 5., 'stored_bit': bit, 'target_voltage_V': .9 if bit else .1,
            'reference_mode': 'offline', 'neutral': False, 'capacitance_F': 1e-14, 'bitline_capacitance_F': 1e-13,
            'reference_capacitance_F': 1e-13, 'effective_thickness_um': 1., 'temperature_K': 300,
            'mesh_scale': PROFILES[variant]['mesh_factor'], 'step_scale': 1., 'variant': variant,
            'pulse_max_step_s': PROFILES[variant]['pulse_max_step_s'],
            'prestrike_s': .95e-9, 'strike_s': 1e-9, 'hold_end_s': 2.8e-9, 'precharge_end_s': 3e-9,
            'read_sample_s': 4e-9, 'geometry_sha256': geometry_sha256, 'physics': legacy.PHYSICS, 'circuit_revision': legacy.CIRCUIT}


def code_hashes():
    c = contract()
    return {**c['frozen_dependency_sha256'], Path(__file__).relative_to(ROOT).as_posix(): sha(Path(__file__).read_bytes()),
            CONTRACT.relative_to(ROOT).as_posix(): sha(CONTRACT.read_bytes())}


def _parameters(case, bit, variant, spec, proof, common):
    reuse = [case, bit, variant] in REUSE_ROLES
    return {**common, 'schema': 'dram-see-v4-source-interface-r5', 'measurement_revision': 5,
            'case_id': case, 'event_id': spec['event_id'], 'source_spec_sha256': sha(encoded(spec)),
            'source_contract_sha256': sha(CONTRACT.read_bytes()), 'source_count': len(spec['tracks']),
            'source_charge_fC': spec['source_total_fC'], 'domain_charge_fC': proof['domain_charge_fC'],
            'synthetic': True, 'parent_run': None, 'matching_contract': common,
            'matching_contract_sha256': sha(encoded(common)), 'source_code_sha256': code_hashes(),
            'numerical_profile': variant, 'build_purpose': 'offline_reuse_reference' if reuse else 'primary_candidate',
            'primary_solver_eligible': not reuse, 'recalculation_requires_reserve': reuse}


def _project(name):
    return {'name': name, 'steps': [
        {'tool': 'sde', 'args': ['-e', '-l', 'geometry.scm'], 'outputs': ['cell_msh.tdr']},
        {'tool': 'sdevice', 'args': ['device.cmd'], 'outputs': ['circuit.plt', 'access_device.plt',
         'final_access_des.tdr', 'transient_des.log'] + ['gfield_' + str(i) + '_access_des.tdr' for i in range(5)]}]}


def _check_path(output, case, bit, variant):
    out = Path(output).resolve()
    if not out.is_relative_to(OUTPUT_ROOT.resolve()) or out == OUTPUT_ROOT.resolve():
        raise ValueError('Use a new child directory under r5 runtime')
    if not re.fullmatch('v4-source-interface-r5-' + case.lower() + '-b' + str(bit) + '-' + variant + r'(?:-[a-z0-9_-]+)?', out.name):
        raise ValueError('Output name must bind revision, case, bit and numerical profile')
    return out


def build(output, case, bit=1, variant='main'):
    check_role(case, bit, variant)
    out = _check_path(output, case, bit, variant)
    if out.exists():
        raise ValueError('Refuse duplicate output; never overwrite an input')
    spec = source_spec(case)
    proof = offline_proof(spec)
    geometry = render_geometry(variant)
    common = expected_common(bit, variant, sha(geometry))
    p = _parameters(case, bit, variant, spec, proof, common)
    files = {'geometry.scm': geometry, 'device.cmd': render_deck(case, bit, variant).encode(),
             'heavyion.par': r2.render_parameters(spec).encode(), 'parameters.json': encoded(p),
             'project.json': encoded(_project(out.name)), 'source-spec.json': encoded(spec),
             'source-contract.json': CONTRACT.read_bytes(), 'offline-source-check.json': encoded(proof)}
    manifest = {'schema': 'dram-see-v4-source-interface-r5-inputs', 'case_id': case, 'stored_bit': bit, 'variant': variant,
                'files_sha256': {n: sha(data) for n, data in files.items()}, 'source_code_sha256': code_hashes(),
                'solver_started': False, 'build_purpose': p['build_purpose'],
                'budget': contract()['global_budget'],
                'dynamic_outputs': 'Original runner full-project tar must retain every accepted-step gstep TDR; fixed output list is not completeness proof'}
    out.mkdir(parents=True)
    for name, data in {**files, 'input-manifest.json': encoded(manifest)}.items():
        with (out / name).open('xb') as stream:
            stream.write(data)
    return check_project(out)


def check_project(project):
    contract()
    folder = Path(project).resolve()
    m, p = read_json(folder / 'input-manifest.json'), read_json(folder / 'parameters.json')
    case, bit, variant = p['case_id'], p['stored_bit'], p['variant']
    check_role(case, bit, variant)
    _check_path(folder, case, bit, variant)
    expected_names = {'geometry.scm', 'device.cmd', 'heavyion.par', 'parameters.json', 'project.json',
                      'source-spec.json', 'source-contract.json', 'offline-source-check.json'}
    if set(m['files_sha256']) != expected_names or {x.name for x in folder.iterdir()} != expected_names | {'input-manifest.json'}:
        raise ValueError('Input inventory differs')
    for name, digest in m['files_sha256'].items():
        if (folder / name).is_symlink() or not (folder / name).is_file() or sha((folder / name).read_bytes()) != digest:
            raise ValueError('Input file/hash differs: ' + name)
    spec = r2.validate_spec(read_json(folder / 'source-spec.json'))
    if spec != source_spec(case):
        raise ValueError('Source identity or frozen fields differ')
    proof = offline_proof(spec)
    geometry = render_geometry(variant)
    common = expected_common(bit, variant, sha(geometry))
    if p != _parameters(case, bit, variant, spec, proof, common):
        raise ValueError('Parameters, matching contract, source provenance or budget role differs')
    if (folder / 'geometry.scm').read_bytes() != geometry or (folder / 'device.cmd').read_text() != render_deck(case, bit, variant):
        raise ValueError('Geometry or full deck differs')
    if strip_observers((folder / 'device.cmd').read_text(), case, bit, variant) != physical_deck(case, bit, variant):
        raise ValueError('Physical deck changed outside observers')
    if (folder / 'heavyion.par').read_text() != r2.render_parameters(spec) or (folder / 'source-contract.json').read_bytes() != CONTRACT.read_bytes():
        raise ValueError('Named source coefficients or contract differ')
    if read_json(folder / 'offline-source-check.json') != proof or read_json(folder / 'project.json') != _project(folder.name):
        raise ValueError('Offline source ledger or original runner steps differ')
    if (m.get('schema') != 'dram-see-v4-source-interface-r5-inputs' or m['source_code_sha256'] != code_hashes()
        or [m['case_id'], m['stored_bit'], m['variant']] != [case, bit, variant] or m['solver_started'] is not False
        or m['build_purpose'] != p['build_purpose'] or m['budget'] != contract()['global_budget']):
        raise ValueError('Manifest metadata differs')
    return {'status': 'OFFLINE_INPUT_CHECK_PASSED', 'solver_started': False, 'project': str(folder),
            'case_id': case, 'stored_bit': bit, 'variant': variant, 'measurement_revision': 5,
            'manifest_sha256': sha((folder / 'input-manifest.json').read_bytes()),
            'matching_contract_sha256': p['matching_contract_sha256'], 'build_purpose': p['build_purpose'],
            'primary_solver_eligible': p['primary_solver_eligible'], 'recalculation_requires_reserve': p['recalculation_requires_reserve'],
            'global_budget_limit': 26, 'prior_attempts_at_revision_freeze': 5,
            'dynamic_frames_require_separate_native_audit': True, 'offline_source_check': proof}


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build')
    b.add_argument('output', type=Path)
    b.add_argument('--case', required=True, choices=contract()['case_ids'])
    b.add_argument('--bit', type=int, choices=(0, 1), default=1)
    b.add_argument('--variant', choices=tuple(PROFILES), default='main')
    k = sub.add_parser('check')
    k.add_argument('project', type=Path)
    sub.add_parser('plan')
    args = parser.parse_args()
    if args.command == 'build':
        result = build(args.output, args.case, args.bit, args.variant)
    elif args.command == 'check':
        result = check_project(args.project)
    else:
        result = {k: contract()[k] for k in ('primary_roles', 'reuse_candidate_roles', 'variants', 'global_budget')}
        result['solver_started'] = False
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
