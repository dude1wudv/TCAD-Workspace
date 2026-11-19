"""Offline S2 ASTAR alpha preparation. Never dispatches or qualifies native jobs.

All lengths in the numerical oracle are um; charge is fC. The independent
oracle integrates actual Si, not the enclosing box. No clipped tail is renormalized.
"""
from bisect import bisect_right
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PLAN = HERE.parent / 'course-plan-r13'
PROFILE = PLAN / 'evidence/alpha-5MeV-1p0um-profile.csv'
E_CHARGE = 1.602176634e-19
CONVERSION = 1e-12 * E_CHARGE * 1e15
T0, SIGMA, WIDTH = 15e-9, .2e-12, .05
WINDOW = [T0-8*SIGMA, T0+8*SIGMA]
DOMAIN = [-1., -.25, 0., 1., .25, 1.]
ROIS = {
    'Total': DOMAIN,
    'XSN': [-1., -.25, 0., -.012, .25, 1.],
    'XGate': [-.012, -.25, 0., .012, .25, 1.],
    'XBL': [.012, -.25, 0., 1., .25, 1.],
    'YOuterMinus': [-1., -.25, 0., 1., -.06, 1.],
    'YSTIMinus': [-1., -.06, 0., 1., -.01, 1.],
    'YActive': [-1., -.01, 0., 1., .01, 1.],
    'YSTIPlus': [-1., .01, 0., 1., .06, 1.],
    'YOuterPlus': [-1., .06, 0., 1., .25, 1.],
    'ZShallow': [-1., -.25, 0., 1., .25, .087],
    'ZJunction': [-1., -.25, .087, 1., .25, .2],
    'ZBulk': [-1., -.25, .2, 1., .25, 1.],
    'SN': [-.072, -.01, 0., -.032, .01, .087],
    'BL': [.032, -.01, 0., .072, .01, .1375],
    'Channel': [-.032, -.01, .087, .032, .01, .2],
    'Core': [-.077, -.025, 0., -.027, .025, 1.],
}
PARTITIONS = [['XSN', 'XGate', 'XBL'],
              ['YOuterMinus', 'YSTIMinus', 'YActive', 'YSTIPlus', 'YOuterPlus'],
              ['ZShallow', 'ZJunction', 'ZBulk']]
TOL = dict(source_relative=.05, generation_waveform_relative=.05,
           centroid_abs_um=.002, time_centroid_abs_s=.04e-12,
           roi_fraction_abs=.05, partition_relative=.05,
           active_generation_fraction=.001, offline_charge_abs_fC=1e-6,
           offline_charge_relative=.001, final_time_abs_s=1e-18,
           zero_charge_fC=1e-6, equivalence_charge_abs_fC=1e-4,
           equivalence_voltage_abs_V=1e-5, refinement_charge_relative=.02,
           refinement_voltage_abs_V=.001, refinement_voltage_relative=.05)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), module.__dict__)
    return module


# These dimension-independent temporal routines already use stable erfc tails.
_CLOCK_PATH = HERE.parent / 'source-interface-3d-r1/oracle.py'
_CLOCK = _module(_CLOCK_PATH, '_s2_clock')
time_mass, step_average, time_moment = _CLOCK.time_mass, _CLOCK.step_average, _CLOCK.time_moment


def validate_model(model):
    g, a, n = model['geometry'], model['alpha'], model['numerics']
    expected_g = dict(gate_top_depth_nm=80, trench_outer_width_nm=24,
                      outer_rounding_radius_nm=12, rounding_center_z_nm=142,
                      oxide_outer_bottom_z_nm=154, active_width_nm=20,
                      sti_each_side_width_nm=50, sti_depth_nm=200)
    require(all(g.get(k) == v for k, v in expected_g.items()), 'Only the frozen S2 geometry is supported')
    require(g['silicon_domain_nm'] == dict(x=[-1000, 1000], y=[-250, 250], z=[0, 1000]),
            'Alpha table is bound to the frozen 1 um silicon path/domain')
    expected_a = dict(first_energy_MeV=5, angle_deg_from_positive_z=0,
                      position_nm=[-52, 0, 0], time_center_ns=15,
                      radial_Gaussian_w_nm=50, temporal_sigma_ps=.2, eV_per_pair=3.6)
    require(all(a.get(k) == v for k, v in expected_a.items()), 'Unsupported alpha energy, angle, position or kernel')
    require(n['time_integrator'] == 'BE' and n['source_window_sigma'] == 8 and
            n['source_max_step_ps'] == .04 and n['source_refined_max_step_ps'] == .02,
            'Frozen BE source-window semantics differ')
    return True


def load_profile(path=PROFILE):
    with Path(path).open(encoding='utf-8', newline='') as stream:
        rows = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(stream)]
    require(len(rows) == 101 and all(math.isfinite(v) for r in rows for v in r.values()), 'Invalid 101-node ASTAR table')
    require(all(abs(r['path_um']-i*.01) <= 1e-14 for i, r in enumerate(rows)), 'Changed table abscissae')
    require(rows[0]['energy_MeV'] == 5 and rows[-1]['energy_MeV'] > 0, 'Changed ASTAR entry/exit energy')
    require(all(a['energy_MeV'] > b['energy_MeV'] for a, b in zip(rows, rows[1:])), 'Energy is not decreasing')
    require(all(r['electronic_pC_um'] > 0 and r['nuclear_MeV_cm2_g'] > 0 for r in rows), 'Nonpositive stopping')
    for row in rows:
        expected = row['electronic_MeV_cm2_g'] * 2.33e-4 * 1e6 / 3.6 * E_CHARGE * 1e12
        require(abs(row['electronic_pC_um']-expected) <= 1e-11*expected, 'Stopping-to-pC conversion changed')
    q = math.fsum((b['path_um']-a['path_um'])*(a['electronic_pC_um']+b['electronic_pC_um'])*500
                  for a, b in zip(rows, rows[1:]))
    require(abs(q-rows[-1]['cumulative_electronic_fC']) <= max(1e-6, .001*q), 'Table integral differs from CSDA reference')
    return rows


def line_charge_density(z, rows):
    if not 0 <= z <= 1:
        return 0.
    index = min(99, max(0, bisect_right([r['path_um'] for r in rows], z)-1))
    a, b = rows[index:index+2]
    f = (z-a['path_um'])/(b['path_um']-a['path_um'])
    return 1000*(a['electronic_pC_um']+f*(b['electronic_pC_um']-a['electronic_pC_um']))


def trench_halfwidth(z):
    if 0 <= z <= .142:
        return .012
    if .142 < z < .154:
        return math.sqrt(max(0., .012**2-(z-.142)**2))
    return 0.


def model_mask(x, y, z):
    """Independent ideal-circle Si mask; interfaces have zero volume measure."""
    if not (-1 <= x <= 1 and -.25 <= y <= .25 and 0 <= z <= 1):
        return False
    if z < .2 and .01 < abs(y) < .06:
        return False
    if z < .154 and abs(y) <= .06 and abs(x) <= trench_halfwidth(z):
        return False
    return True


def _radial(lo, hi, center):
    if hi <= lo:
        return 0., 0.
    a, b = (lo-center)/WIDTH, (hi-center)/WIDTH
    if a >= 0:
        f = (math.erfc(a)-math.erfc(b))/2
    elif b <= 0:
        f = (math.erfc(-b)-math.erfc(-a))/2
    else:
        f = (math.erf(b)-math.erf(a))/2
    m = center*f+WIDTH/(2*math.sqrt(math.pi))*(math.exp(-a*a)-math.exp(-b*b))
    return f, m


def _slice(z, box):
    """Return Gaussian mass,x,y moments and actual Si area in one z slice."""
    xmin, ymin, _, xmax, ymax, _ = box
    ys = [(-.25, -.06), (-.01, .01), (.06, .25)] if z < .2 else [(-.25, .25)]
    result = [0., 0., 0., 0.]
    for low, high in ys:
        low, high = max(low, ymin), min(high, ymax)
        if high <= low:
            continue
        xs = [(xmin, xmax)]
        cut = trench_halfwidth(z)
        if cut and low >= -.01 and high <= .01:
            xs = [(xmin, min(xmax, -cut)), (max(xmin, cut), xmax)]
        fy, my = _radial(low, high, 0.)
        for left, right in xs:
            if right <= left:
                continue
            fx, mx = _radial(left, right, -.052)
            for i, value in enumerate((fx*fy, mx*fy, fx*my, (right-left)*(high-low))):
                result[i] += value
    return result


def _integrate_vector(fn, a, b, tolerance=1e-13, depth=18):
    fa, fm, fb = fn(a), fn((a+b)/2), fn(b)
    def simpson(x, y, u, v, w):
        return [(y-x)*(u[i]+4*v[i]+w[i])/6 for i in range(len(u))]
    initial = simpson(a, b, fa, fm, fb)
    def refine(x, y, u, v, w, coarse, tol, remaining):
        mid = (x+y)/2
        l, r = fn((x+mid)/2), fn((mid+y)/2)
        left, right = simpson(x, mid, u, l, v), simpson(mid, y, v, r, w)
        fine = [aa+bb for aa, bb in zip(left, right)]
        error = max(abs(aa-bb) for aa, bb in zip(fine, coarse))
        if error <= 15*tol:
            return [aa+(aa-bb)/15 for aa, bb in zip(fine, coarse)]
        require(remaining > 0, 'Independent geometry quadrature failed to converge')
        lval = refine(x, mid, u, l, v, left, tol/2, remaining-1)
        rval = refine(mid, y, v, r, w, right, tol/2, remaining-1)
        return [aa+bb for aa, bb in zip(lval, rval)]
    return refine(a, b, fa, fm, fb, initial, tolerance, depth)


def spatial_expected(rows, box=DOMAIN, tolerance=1e-13):
    require(len(box) == 6 and all(box[i] < box[i+3] for i in range(3)), 'Invalid ROI')
    bounds = [max(box[i], DOMAIN[i]) for i in range(3)]+[min(box[i+3], DOMAIN[i+3]) for i in range(3)]
    if any(bounds[i] >= bounds[i+3] for i in range(3)):
        return dict(q_fC=0., moments_fC_um=[0., 0., 0.], centroid_um=[None]*3, volume_um3=0.)
    lo, hi = bounds[2], bounds[5]
    breaks = sorted({lo, hi, *[r['path_um'] for r in rows if lo < r['path_um'] < hi],
                     *[v for v in (.142, .154, .2) if lo < v < hi]})
    values = []
    for a, b in zip(breaks, breaks[1:]):
        # Avoid selecting the material on the other side at an integration endpoint.
        def physical(z):
            zinside = min(math.nextafter(b, a), max(math.nextafter(a, b), z))
            f, mx, my, area = _slice(zinside, bounds)
            q = line_charge_density(zinside, rows)
            return [q*f, q*mx, q*my, q*f*zinside, area]
        if a >= .142 and b <= .154:
            ta = math.asin(max(0., min(1., (a-.142)/.012)))
            tb = math.asin(max(0., min(1., (b-.142)/.012)))
            def angular(theta):
                z = .142+.012*math.sin(theta)
                return [v*.012*math.cos(theta) for v in physical(z)]
            values.append(_integrate_vector(angular, ta, tb, tolerance))
        else:
            values.append(_integrate_vector(physical, a, b, tolerance))
    sums = [math.fsum(row[i] for row in values) for i in range(5)]
    return dict(q_fC=sums[0], moments_fC_um=sums[1:4],
                centroid_um=[v/sums[0] if sums[0] else None for v in sums[1:4]], volume_um3=sums[4])


def source_expected(model, rows=None):
    validate_model(model)
    rows = load_profile() if rows is None else rows
    rois = {name: spatial_expected(rows, box) for name, box in ROIS.items()}
    line = math.fsum((b['path_um']-a['path_um'])*(a['electronic_pC_um']+b['electronic_pC_um'])*500
                     for a, b in zip(rows, rows[1:]))
    outer_fx, _ = _radial(-1., 1., -.052)
    outer_fy, _ = _radial(-.25, .25, 0.)
    box_charge = line*outer_fx*outer_fy
    total = rois['Total']['q_fC']
    wm = time_mass(*WINDOW, T0, SIGMA)
    # Analytic primitive independent of the z quadrature, in um^3.
    exact_volume = 1.-2.*2.*.05*.2-.02*(.024*.142+math.pi*.012**2/2)
    require(abs(exact_volume-rois['Total']['volume_um3']) < 1e-11, 'Actual Si volume fails independent formula')
    closure = []
    for part in PARTITIONS:
        dq = math.fsum(rois[name]['q_fC'] for name in part)-total
        dv = math.fsum(rois[name]['volume_um3'] for name in part)-exact_volume
        require(abs(dq) < 1e-9 and abs(dv) < 1e-11, 'Independent Si partition does not close')
        closure.append(dict(rois=part, charge_residual_fC=dq, volume_residual_um3=dv))
    refined = spatial_expected(rows, tolerance=2.5e-14)
    require(abs(refined['q_fC']-total) <= max(1e-6, .001*line), 'Offline mapping error exceeds frozen gate')
    return dict(schema='s2-alpha-independent-reference-r1', is_tcad_result=False,
                geometry_basis='ideal_circle_actual_silicon_mask', cad_discretization_bound=False,
                line_charge_fC=line, enclosing_box_charge_fC=box_charge,
                domain_charge_fC=total, expected_window_charge_fC=total*wm,
                outer_boundary_loss_fC=line-box_charge, non_silicon_loss_fC=box_charge-total,
                time_window_mass=wm, time_tail_loss_fC=total*(1-wm),
                charge_closure_residual_fC=line-((line-box_charge)+(box_charge-total)+total*wm+total*(1-wm)),
                exit_energy_MeV=rows[-1]['energy_MeV'],
                quadrature_refinement_difference_fC=refined['q_fC']-total,
                expected_silicon_volume_um3=exact_volume, rois=rois, partitions=closure,
                normalization='none; finite-domain, non-Si and time losses retained',
                not_claimed=['native syntax', 'native BE semantics', 'native mesh', 'native source qualification', 'circuit response'])


def cad_binding(model, reference):
    """Compare independent oracle against CAD's public analytic description."""
    geometry_path = HERE/'geometry.py'
    geometry = _module(geometry_path, '_s2_cad_alpha_crosscheck')
    description = geometry.describe_geometry(model, dimension=3)
    trench = description['outer_trench']
    require(description['domain_um'] == dict(x=[-1., 1.], y=[-.25, .25], z=[0., 1.]), 'CAD domain differs from alpha mask')
    require(trench['x_half_width_um'] == .012 and abs(trench['y_half_width_um']-.06) < 1e-15 and
            trench['top_um'] == 0. and trench['round_center_z_um'] == .142 and trench['radius_um'] == .012 and
            trench['construction'] == 'rectangle/cuboid union circle/cylinder', 'CAD trench differs from independent exact-circle mask')
    sti = description['sti']
    require(sti['included'] is True and sti['x_um'] == [-1., 1.] and sti['z_um'] == [0, .2] and
            all(abs(a-b) < 1e-15 for aa, bb in zip(sti['y_intervals_um'], [[-.06, -.01], [.01, .06]]) for a, b in zip(aa, bb)),
            'CAD STI differs from alpha mask')
    require(abs(description['measures']['silicon']-reference['expected_silicon_volume_um3']) < 1e-12, 'Independent/CAD silicon volume differs')
    points = 0
    # Deliberately off material interfaces: material ownership at shared faces
    # has zero volume but different Boolean convention may assign the boundary.
    for x in (-.9, -.1, -.052, -.013, -.011, -.007, 0., .007, .011, .013, .052, .9):
        for y in (-.2, -.061, -.059, -.011, -.009, 0., .009, .011, .059, .061, .2):
            for z in (-.001, .001, .08, .141, .143, .149, .153, .155, .199, .201, .9, 1.001):
                require(bool(geometry.is_silicon(model, x, y, z)) == model_mask(x, y, z), 'CAD and independent Si mask differ')
                points += 1
    return dict(analytic_geometry_consistent=True, native_geometry_qualified=False,
                geometry_code_sha256=sha(geometry_path), nonboundary_mask_points=points,
                geometry_description_sha256=hashlib.sha256(json.dumps(description, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                exact_circle_no_polygon_discretization=True, native_mesh_error_still_unverified=True)


def source_spec(case='Aalpha', bit=0, variant='main'):
    require(case in ('A0', 'Aalpha', 'Z', 'H', 'split'), 'Unsupported source case')
    require(type(bit) is int and bit in (0, 1), 'Explicit bit0/bit1 required')
    require(variant in ('main', 'mesh', 'time'), 'Unknown numerical variant')
    require(case not in ('Z', 'H', 'split') or variant == 'main', 'Z/H/split only planned for main')
    return dict(case=case, stored_bit=bit, numerical_variant=variant,
                amplitude=0. if case in ('A0', 'Z') else .5 if case == 'H' else 1.,
                source_configured=case != 'A0', model='S2', energy_MeV=5,
                source_max_step_s=.02e-12 if variant == 'time' else .04e-12,
                source_window_s=WINDOW, matched_A0=dict(stored_bit=bit, numerical_variant=variant))


def render_source(rows, case='Aalpha'):
    spec = source_spec(case)
    if case == 'A0':
        return '* A0: no HeavyIon declaration. Missing native G is structural absence, never measured zero.\n', '* A0: no source parameter block.\n'
    segments = [(0, 50), (50, 100)] if case == 'split' else [(0, 100)]
    physics, parameters = [], []
    for number, (start, end) in enumerate(segments):
        name = 'S2ASTAR5MeV_'+str(number)
        points = rows[start:end+1]
        offset = points[0]['path_um']
        array = lambda values: '['+' '.join(format(v, '.17g') for v in values)+']'
        physics.append('HeavyIon("'+name+'") (\n  StartPoint=(-0.052,0,'+format(offset, '.17g')+') Direction=(0,0,1)\n'
                       '  Time=1.5e-8\n  Length='+array(r['path_um']-offset for r in points)+'\n'
                       '  LET_f='+array(r['electronic_pC_um']*spec['amplitude'] for r in points)+'\n'
                       '  Wt_hi='+array(.05 for _ in points)+'\n  Gaussian PicoCoulomb\n)\n')
        p = dict(a_1=0., a_2=0., a_3=0., a_4=0., k_hi=1., c_1=0., c_2=1., c_3=0., c_4=1., s_hi=SIGMA)
        parameters.append('HeavyIon("'+name+'") {\n'+''.join('  '+k+' = '+format(v, '.17g')+'\n' for k, v in p.items())+'}\n')
    return ''.join(physics), ''.join(parameters)


def field_contract():
    return dict(schema='s2-field-contract-r1', status='OFFLINE_REVIEW_ONLY', execution_enabled=False,
                dimension=3, window_s=WINDOW, final_time_s=25e-9,
                native_fields=dict(G='HeavyIonGeneration', ONE='S2_One', XG='S2_XG', YG='S2_YG', ZG='S2_ZG'),
                rois_um6=ROIS, partitions=PARTITIONS, audit_tolerances=TOL,
                conversion=dict(um3_to_cm3=1e-12, elementary_charge_C=E_CHARGE, C_to_fC=1e15),
                reference_mode='referenced_original_tdr_not_copied',
                full_accepted_BE_PLT_TDR_bijection=True, all_source_window_frames_required=True,
                missing_zero_field='structural_zero_not_measured_zero; measured charge null',
                original_file_integrity=['GROUP_BEFORE', 'FRAME_BEFORE', 'FRAME_AFTER', 'GROUP_AFTER'],
                current_audit=dict(required=True, implementation_owner='main circuit/metrics module',
                                   source_field_pass_is_circuit_pass=False, from_C_delta_V_alone_forbidden=True,
                                   required_observables=['all device contact currents', 'all mixed-mode branch currents',
                                                         'Cstore and Cbl native currents', 'SN/BL/WL/body/plate voltages'],
                                   residual_gate_fC='max(1e-4, 0.01*predeclared related charge scale)',
                                   matched_control='same bit, numerical variant, geometry, physics, waveform and mesh'),
                native_receipt_missing_action='REFUSE; no synthetic qualification',
                limits=['No native output exists in this preparation',
                        'Independent exact-circle mask is bound offline to CAD description; native mesh still unverified',
                        'Native source array endpoint and BE-average semantics need new-model qualification',
                        'Field-only pass never proves matched-A0/circuit/numerical convergence/physical calibration'])


def _write_new(path, content):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(content)


def prepare_audit(model: dict, output: Path) -> dict:
    """Write review-only alpha materials into a new directory or absent filenames."""
    validate_model(model)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = load_profile()
    reference = source_expected(model, rows)
    reference['cad_binding'] = cad_binding(model, reference)
    reference['cad_discretization_bound'] = True
    source = dict(schema='s2-alpha-source-contract-r1', status='OFFLINE_REVIEW_ONLY', execution_enabled=False,
                  native_calls=0, native_qualified=False, model_id=model['model_id'],
                  model_snapshot=model,
                  model_sha256=hashlib.sha256(json.dumps(model, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                  primary_source=dict(path=PROFILE.relative_to(ROOT).as_posix(), sha256=sha(PROFILE), nodes=101),
                  alpha=model['alpha'], geometry=model['geometry'], temporal_window_s=WINDOW,
                  source_semantics='positive carrier-pair source; electronic stopping only; nuclear stopping in CSDA loss',
                  geometry_mask='disjoint STI slabs plus active-width circular-bottom gate trench',
                  syntax_evidence='local_runtime/dram-see-v1/heavyion-reference.txt pp813-816, arrays use [ ... ]',
                  native_semantics_unverified=['Length zero-first-node', 'finite end/split endpoint', 'new-model BE average'],
                  dependency_sha256={str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in
                                     [_CLOCK_PATH, PROFILE, HERE/'alpha-assumptions.md', HERE/'alpha.py', HERE/'geometry.py', HERE/'extract_fields.tcl', HERE/'field_audit.py',
                                      HERE.parent/'source-field-audit-3d-r1/audit_fields.py', HERE.parent/'source-field-audit-3d-r1/field_contract.json']},
                  allowed_review_specs=[source_spec(case, bit, variant) for bit in (0, 1)
                                        for case in ('A0', 'Aalpha', 'Z', 'H', 'split')
                                        for variant in (('main', 'mesh', 'time') if case in ('A0', 'Aalpha') else ('main',))],
                  alpha_roles_added_to_first_four=0, compiled_PMI_dependency=False)
    files = {'source-contract.json': source, 'alpha-reference.json': reference, 'field-contract.json': field_contract()}
    for name, value in files.items():
        _write_new(output/name, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    with (output/'alpha-profile.csv').open('xb') as stream:
        stream.write(PROFILE.read_bytes())
    for case in ('Aalpha', 'Z', 'H', 'split', 'A0'):
        physics, parameters = render_source(rows, case)
        prefix = '' if case == 'Aalpha' else case+'.'
        _write_new(output/(prefix+'heavyion.physics.inc'), physics)
        _write_new(output/(prefix+'source.par'), parameters)
    _write_new(output/'heavyion.currentplot.inc', 'CurrentPlot {\n HeavyIonGeneration( Integrate(Semiconductor) )\n}\n')
    _write_new(output/'heavyion.plot.inc', 'HeavyIonGeneration HeavyIonChargeDensity\n')
    with (output/'extract_fields.tcl').open('xb') as stream:
        stream.write((HERE/'extract_fields.tcl').read_bytes())
    # This is data consumed by an explicitly released extractor, not an executable task.
    _write_new(output/'windows.tcldata', '\n'.join(name+' {'+' '.join(format(v, '.17g') for v in box)+'}' for name, box in ROIS.items())+'\n')
    _write_new(output/'README.txt', 'OFFLINE REVIEW ONLY. No native receipts, launch command, runner project, or execution release.\n'
               'Native audit requires full original solver and extraction archives; run field_audit.py only on completed evidence.\n'
               'A0/DC first-four inputs must not include heavyion.physics.inc or source.par.\n')
    return dict(status='OFFLINE_ALPHA_PREPARED_NATIVE_NOT_RUN', is_tcad_result=False, output=str(output),
                line_charge_fC=reference['line_charge_fC'], domain_charge_fC=reference['domain_charge_fC'],
                native_calls=0, native_qualified=False,
                sha256={p.name: sha(p) for p in sorted(output.iterdir()) if p.is_file()})
