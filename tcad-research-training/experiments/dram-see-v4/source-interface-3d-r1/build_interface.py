"""Prepare only the two registered 3D A0/A1 bit1 inputs; never run a solver."""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUT_ROOT = ROOT / 'local_runtime/dram-see-v4/source-interface-3d-r1'
CONTRACT = HERE / 'source_contract.json'
GEOMETRY_CONTRACT = HERE / 'geometry-contract.json'

# Load only this revision's pure oracle, without writing a bytecode cache.
_spec = importlib.util.spec_from_file_location('_dram_source_3d_oracle', HERE / 'oracle.py')
oracle = importlib.util.module_from_spec(_spec)
exec(compile((HERE / 'oracle.py').read_bytes(), str(HERE / 'oracle.py'), 'exec'), oracle.__dict__)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def number(value):
    if not oracle.finite(value):
        raise ValueError('Finite non-boolean number required')
    return format(value, '.17g')


def _replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Missing or ambiguous frozen template token: ' + before)
    return text.replace(before, after, 1)


def geometry_contract():
    g = read_json(GEOMETRY_CONTRACT)
    if (g.get('schema') != 'dram-see-v4-shared-geometry-3d-r1' or g.get('dimension') != 3
            or g.get('coordinate_system') != 'AsIs' or g.get('units', {}).get('length') != 'um'
            or g.get('tcad_ready_for_real_transport_events') is not False):
        raise ValueError('Wrong 3D geometry schema, coordinates or real-event status')
    expected = [('R.Si', [0., 0., -.5], [.85, 1.2, .5], 'Silicon'),
                ('R.Ox', [.3, -.005, -.5], [.55, 0., .5], 'Oxide')]
    if len(g.get('solids', [])) != len(expected):
        raise ValueError('Only the registered Si and oxide solids are permitted')
    for solid, (name, low, high, material) in zip(g['solids'], expected):
        if (solid.get('id') != name or solid.get('shape') != 'cuboid'
                or solid.get('min_um') != low or solid.get('max_um') != high or solid.get('sde_material') != material):
            raise ValueError('Unexpected solid geometry or material')
    if [x['name'] for x in g['contacts']] != ['source', 'drain', 'gate', 'body'] or g['boundaries']['z_contact_names']:
        raise ValueError('Contact topology differs')
    return g


def contract():
    c = read_json(CONTRACT)
    if (c.get('schema') != 'dram-see-v4-source-interface-3d-r1-contract' or c.get('revision') != 1
            or c.get('allowed_roles') != [['A0', 1, 'main'], ['A1', 1, 'main']]
            or c.get('tcad_ready') is not False):
        raise ValueError('Wrong 3D scope or contract')
    if c['geometry_contract_sha256'] != sha(GEOMETRY_CONTRACT.read_bytes()):
        raise ValueError('Shared geometry contract bytes changed')
    geometry_contract()
    for name, digest in c['frozen_dependency_sha256'].items():
        if sha((ROOT / name).read_bytes()) != digest:
            raise ValueError('Frozen 2D/reference dependency changed: ' + name)
    if (c['device']['dimension'] != 3 or c['device']['area_factor'] != 1
            or c['device']['physical_width_um'] != 1 or 'effective_thickness_um' in c['device']
            or c['device']['capacitance_F'] != 1e-14 or c['device']['bitline_capacitance_F'] != 1e-13
            or c['device']['reference_capacitance_F'] != 1e-13):
        raise ValueError('Dimension, normalization or fixed physical capacitance differs')
    if (c['kernel']['dimension'] != 3 or c['kernel']['time_sigma_equals_s_hi'] is not True
            or c['heavyion_parameters']['s_hi'] != 2e-12
            or c['timing']['pulse_max_step_s'] != .5e-12 or c['timing']['read_sample_s'] != 4e-9):
        raise ValueError('Frozen source/timing differs')
    return c


def check_role(case, bit=1, variant='main'):
    if type(bit) is not int or [case, bit, variant] not in contract()['allowed_roles']:
        raise ValueError('Only registered A0/A1 bit1 main is supported')


def source_spec(case):
    c = contract()
    if case not in ('A0', 'A1'):
        raise ValueError('Only A0/A1 artificial sources are registered')
    old = read_json(ROOT / c['references'][case] / 'source-spec.json')
    spec = copy.deepcopy(old)
    spec.update(schema='dram-see-v4-source-interface-3d-r1-spec', dimension=3,
                event_id='artificial-source-interface-3d-r1-' + case.lower(),
                tcad_ready=False, geometry_contract_sha256=c['geometry_contract_sha256'],
                units=c['units'], projection=None)
    return spec


def validate_spec(spec):
    if not isinstance(spec, dict) or spec.get('case_id') not in ('A0', 'A1'):
        raise ValueError('Missing or unknown case')
    if spec.get('dimension') != 3 or spec.get('synthetic') is not True or spec.get('projection') is not None or spec.get('tcad_ready') is not False:
        raise ValueError('Only unprojected artificial 3D sources are supported')
    tracks = spec.get('tracks')
    if not isinstance(tracks, list):
        raise ValueError('Tracks must be explicit, including an empty A0 list')
    owners = set()
    for track in tracks:
        for key in ('q_fC', 'length_um', 'let_pC_per_um', 'wt_hi_um', 's_hi_s', 'time_s'):
            if not oracle.finite(track.get(key)):
                raise ValueError('Missing or nonfinite track value: ' + key)
        if track['length_um'] <= 0:
            raise ValueError('Zero-length positive deposition is unsupported; no invented length or charge split')
        if track['q_fC'] <= 0 or track['wt_hi_um'] <= 0 or track['s_hi_s'] <= 0:
            raise ValueError('Source charge, width and sigma must be positive')
        if not math.isclose(track['let_pC_per_um'] * track['length_um'], track['q_fC'] * .001, rel_tol=1e-14, abs_tol=0):
            raise ValueError('Charge/LET/length allocation does not close')
        oracle.box_moments(track, [0, 0, -.5, .85, 1.2, .5])
        for step in track.get('source_step_ids', []):
            if step in owners:
                raise ValueError('A source step was assigned more than once')
            owners.add(step)
    if not math.isclose(math.fsum(t['q_fC'] for t in tracks), spec.get('source_total_fC', math.nan), rel_tol=0, abs_tol=1e-15):
        raise ValueError('Event charge sum differs')
    # Exact registered input, not a permissive import interface for real tracks.
    if encoded(spec) != encoded(source_spec(spec['case_id'])):
        raise ValueError('Source fields differ from the unique registered artificial case')
    return spec


def offline_proof(spec):
    validate_spec(spec)
    c = contract()
    rois = {}
    for name, bounds in c['rois_um6'].items():
        parts = []
        for track in spec['tracks']:
            f, mx, my, mz = oracle.box_moments(track, bounds)
            q = track['q_fC']
            parts.append({'source_name': track['source_name'], 'fraction': f, 'q_fC': q*f,
                          'x_moment_fC_um': q*mx, 'y_moment_fC_um': q*my, 'z_moment_fC_um': q*mz,
                          'quadrature_error_fC': 0., 'time_s': track['time_s'], 's_hi_s': track['s_hi_s']})
        charge = math.fsum(p['q_fC'] for p in parts)
        tq = math.fsum(p['q_fC']*oracle.time_mass(0, 4e-9, p['time_s'], p['s_hi_s']) for p in parts)
        tm = math.fsum(p['q_fC']*oracle.time_moment(0, 4e-9, p['time_s'], p['s_hi_s']) for p in parts)
        rois[name] = {'q_fC': charge, 'tracks': parts,
                      **{'centroid_'+axis+'_um': math.fsum(p[axis+'_moment_fC_um'] for p in parts)/charge if charge else None for axis in 'xyz'},
                      'time_centroid_s': tm/tq if tq else None}
    inside = rois['Total']['q_fC']
    return {'schema': 'dram-see-v4-source-interface-3d-r1-offline', 'status': 'OFFLINE_ONLY',
            'is_tcad_result': False, 'tcad_ready': False, 'dimension': 3, 'case_id': spec['case_id'],
            'source_total_fC': spec['source_total_fC'], 'domain_charge_fC': inside,
            'outside_domain_fC': spec['source_total_fC']-inside, 'rois': rois,
            'method': 'closed-form separable 3D Gaussian x/z moments and uniform finite y segment',
            'normalization': '1/(pi*w^2*length), volume in um^3; no implicit thickness multiplier',
            'temporal_mass_0_to_4ns_by_source': {t['source_name']: oracle.time_mass(0, 4e-9, t['time_s'], t['s_hi_s']) for t in spec['tracks']},
            'temporal_mass_pulse_window_by_source': {t['source_name']: oracle.time_mass(*c['pulse_output_window_s'], t['time_s'], t['s_hi_s']) for t in spec['tracks']}}


def generation(spec, x, y, z, t):
    validate_spec(spec)
    c = contract()
    return math.fsum(a['q_fC']*1e-15/c['conversion']['elementary_charge_C']*1e12
                     * oracle.spatial_density(a, x, y, z)*oracle.time_density(t, a['time_s'], a['s_hi_s'])
                     for a in spec['tracks'])


def _position(p):
    return '(position ' + ' '.join(map(number, p)) + ')'


def render_geometry():
    c, g = contract(), geometry_contract()
    lines = ['; 3D representative extrusion. Lengths in um; AsIs x/y/z.',
             '; All physical solids/contacts/doping come from geometry-contract.json.',
             '(sde:clear)', '(sdegeo:set-default-boolean "ABA")']
    for s in g['solids']:
        lines.append('(sdegeo:create-cuboid '+_position(s['min_um'])+' '+_position(s['max_um'])+' "'+s['sde_material']+'" "'+s['id']+'")')
    for p, color in zip(g['contacts'], ('1 0 0', '0 0 1', '0 1 0', '0 0 0')):
        name = p['name']
        lines += ['(sdegeo:define-contact-set "'+name+'" 4 (color:rgb '+color+') "##")',
                  '(define face-'+name+' (find-face-id '+_position(p['face_probe_um'])+'))',
                  '(if (not (= (length face-'+name+') 1)) (sde:error "Expected one '+name+' contact face"))',
                  '(sdegeo:set-contact face-'+name+' "'+name+'")']
    body, implant = g['doping']['body'], g['doping']['source_drain']
    lines += ['(sdedr:define-constant-profile "P.Body" "'+body['species']+'" '+number(body['value_cm3'])+')',
              '(sdedr:define-constant-profile-region "P.Body.Place" "P.Body" "'+body['region']+'")']
    for b in implant['baselines']:
        x0, y, z0 = b['min_um']; x1, _, z1 = b['max_um']
        # Explicit closed polygon: +z cross +x gives +y. SDE UG pp242,567-568.
        points = ([x0,y,z0], [x0,y,z1], [x1,y,z1], [x1,y,z0], [x0,y,z0])
        lines.append('(sdedr:define-refeval-window "'+b['id']+'" "Polygon" (list '+' '.join(_position(p) for p in points)+'))')
    lines += ['(sdedr:define-gaussian-profile "N.SD" "'+implant['species']+'" "PeakPos" '+number(implant['peak_position_um'])
              +' "PeakVal" '+number(implant['peak_value_cm3'])+' "ValueAtDepth" '+number(implant['value_at_depth_cm3'])
              +' "Depth" '+number(implant['depth_um'])+' "Gauss" "Factor" '+number(implant['lateral_gauss_factor'])+')']
    for b in implant['baselines']:
        lines.append('(sdedr:define-analytical-profile-placement "'+b['id'].split('.')[0]+'.Place" "N.SD" "'+b['id']+'" "Positive" "NoReplace" "Eval")')
    for w in c['mesh']['windows']:
        name = w['name']
        lines += ['(sdedr:define-refeval-window "'+name+'" "Cuboid" '+_position(w['min_um'])+' '+_position(w['max_um'])+')',
                  '(sdedr:define-refinement-size "Mesh.'+name+'" '+' '.join(map(number, w['max_size_um']+w['min_size_um']))+')',
                  '(sdedr:define-refinement-placement "'+name+'.Place" "Mesh.'+name+'" "'+name+'")']
    lines += ['(sdedr:define-refinement-function "Mesh.All" "DopingConcentration" "MaxTransDiff" '+number(c['mesh']['doping_refinement_max_trans_diff'])+')',
              '; Uncontacted z faces remain natural Neumann/no-carrier-flux boundaries.',
              '(sde:build-mesh "snmesh" "" "cell")',
              '; Same-SDE-stage admission only; no additional solver is started.',
              '(define resource-guard-status (system:command "/usr/bin/python3 mesh_resource_guard.py"))',
              '(if (not (equal? resource-guard-status 0)) (sde:error "Mesh resource guard blocked SDevice; see mesh-resource-report.json"))']
    return ('\n'.join(lines)+'\n').encode()


def render_sources(spec):
    validate_spec(spec)
    return '\n '.join('HeavyIon("'+a['source_name']+'") ( StartPoint=('+','.join(map(number,a['start_um']))
                       +') Direction=('+','.join(map(number,a['direction']))+') Time='+number(a['time_s'])
                       +' Length='+number(a['length_um'])+' Wt_hi='+number(a['wt_hi_um'])
                       +' LET_f='+number(a['let_pC_per_um'])+' Gaussian PicoCoulomb )' for a in spec['tracks'])


def render_parameters(spec):
    validate_spec(spec)
    return '* Explicit frozen coefficients, not installation defaults; native 3D normalization.\n'+''.join(
        'HeavyIon("'+t['source_name']+'") {\n'+''.join('  '+k+' = '+number(v)+'\n' for k,v in contract()['heavyion_parameters'].items())+'}\n'
        for t in spec['tracks'])


def current_plot(case):
    c = contract()
    coords = ' Coordinates' if case == 'A1' else ''
    lines = ['CurrentPlot {', ' HeavyIonGeneration(', '  Integrate(Semiconductor)',
             '  Integrate(Name="G_Plain" Semiconductor'+coords+')']
    for name, b in c['rois_um6'].items():
        window = ' Window[('+' '.join(map(number,b[:3]))+') ('+' '.join(map(number,b[3:]))+')]'
        lines.append('  Integrate(Name="G_'+name+'" Semiconductor'+window+')')
    lines += [' )', ' Temperature(', '  Integrate(Name="TemperatureVolume" Semiconductor)', ' )', '}']
    return '\n'.join(lines)


def render_deck(case, bit=1, variant='main'):
    check_role(case, bit, variant)
    c, spec = contract(), source_spec(case)
    # Frozen text only. No legacy module is executed or its globals modified.
    original = (ROOT / c['references'][case] / 'device.cmd').read_text(encoding='utf-8')
    old_spec = read_json(ROOT / c['references'][case] / 'source-spec.json')
    deck = original
    if case == 'A1':
        a = old_spec['tracks'][0]
        old_source = 'HeavyIon("'+a['source_name']+'") ( StartPoint=('+','.join(map(number,a['start_um'][:2]))+') Direction=('+','.join(map(number,a['direction'][:2]))+') Time='+number(a['time_s'])+' Length='+number(a['length_um'])+' Wt_hi='+number(a['wt_hi_um'])+' LET_f='+number(a['let_pC_per_um'])+' Gaussian PicoCoulomb )'
        deck = _replace_once(deck, old_source, render_sources(spec))
    start, end = deck.index('CurrentPlot {'), deck.index('\nMath {')
    deck = deck[:start]+current_plot(case)+deck[end:]
    deck = _replace_once(deck, 'Math { CurrentPlot(', 'Math { CoordinateSystem { AsIs } CurrentPlot(')
    deck = _replace_once(deck, 'hCurrent/Vector HeavyIonChargeDensity', 'hCurrent/Vector Temperature HeavyIonChargeDensity')
    if c['measurement']['dynamic_plot_command'] not in deck or 'Intervals=' in deck:
        raise ValueError('Accepted-step output contract differs')
    # Full circuit and transient sequence inherited exactly from the frozen bit1 input.
    if deck[deck.index('\nSystem {'):] != original[original.index('\nSystem {'):]:
        raise ValueError('Circuit, state or complete 4ns timing differs from frozen r5')
    return deck


def code_hashes():
    files = (Path(__file__), HERE/'oracle.py', HERE/'mesh_resource_guard.py', CONTRACT, GEOMETRY_CONTRACT)
    return {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in files}


def expected_common():
    c = contract()
    old = read_json(ROOT / c['references']['A0'] / 'parameters.json')['matching_contract']
    common = {k:v for k,v in old.items() if k != 'effective_thickness_um'}
    common.update(dimension=3, variant='main', area_factor=1., physical_width_um=1.,
                  geometry_sha256=sha(render_geometry()), geometry_contract_sha256=c['geometry_contract_sha256'],
                  mesh_revision='3d-r1-anisotropic-diagnostic', mesh_contract_sha256=sha(encoded(c['mesh'])),
                  coordinate_system='AsIs')
    return common


def expected_files(case, project_name):
    check_role(case)
    c, spec = contract(), source_spec(case)
    proof, common, code = offline_proof(spec), expected_common(), code_hashes()
    p = {**common, 'schema':'dram-see-v4-source-interface-3d-r1', 'case_id':case, 'event_id':spec['event_id'],
         'source_spec_sha256':sha(encoded(spec)), 'source_contract_sha256':sha(CONTRACT.read_bytes()),
         'source_count':len(spec['tracks']), 'source_charge_fC':spec['source_total_fC'],
         'domain_charge_fC':proof['domain_charge_fC'], 'synthetic':True, 'tcad_ready':False, 'parent_run':None,
         'matching_contract':common, 'matching_contract_sha256':sha(encoded(common)), 'source_code_sha256':code,
         'control_case_id':'A0', 'a0_generation_semantics':c['measurement']['a0_missing_generation']}
    outputs = ['circuit.plt','access_device.plt','final_access_des.tdr','transient_des.log']
    outputs += ['gfield_'+str(i)+'_access_des.tdr' for i in range(len(c['tdr_times_s']))]
    project = {'name':project_name, 'steps':[{'tool':'sde','args':['-e','-l','geometry.scm'],'outputs':['cell_msh.tdr','mesh-resource-passed.json']},
                                           {'tool':'sdevice','args':['device.cmd'],'outputs':outputs}]}
    return {'geometry.scm':render_geometry(), 'device.cmd':render_deck(case).encode(),
            'heavyion.par':render_parameters(spec).encode(), 'parameters.json':encoded(p),
            'project.json':encoded(project), 'source-spec.json':encoded(spec),
            'geometry-contract.json':GEOMETRY_CONTRACT.read_bytes(), 'source-contract.json':CONTRACT.read_bytes(),
            'offline-source-check.json':encoded(proof), 'mesh_resource_guard.py':(HERE/'mesh_resource_guard.py').read_bytes()}


def _destination(path):
    p = Path(path).resolve()
    base = OUTPUT_ROOT.resolve()
    if not p.is_relative_to(base) or p == base:
        raise ValueError('Output must be inside the new 3D runtime tree')
    return p


def _project_name(name, case):
    if not re.fullmatch('v4-source-interface-3d-r1-'+case.lower()+r'-b1-main(?:-[a-z0-9_-]+)?', name):
        raise ValueError('Project name must bind 3D revision, case, bit1 and main')


def _manifest(case, files):
    return {'schema':'dram-see-v4-source-interface-3d-r1-inputs', 'case_id':case, 'stored_bit':1,
            'variant':'main', 'dimension':3, 'files_sha256':{n:sha(v) for n,v in files.items()},
            'source_code_sha256':code_hashes(), 'solver_started':False, 'tcad_ready':False}


def build(output, case, bit=1, variant='main', supplied_spec=None):
    check_role(case, bit, variant)
    if supplied_spec is not None:
        validate_spec(supplied_spec)
        if supplied_spec['case_id'] != case:
            raise ValueError('Supplied case differs from requested case')
    out = _destination(output)
    _project_name(out.name, case)
    if out.exists():
        raise ValueError('Refusing duplicate or existing output; use a new directory')
    files = expected_files(case, out.name)
    out.mkdir(parents=True, exist_ok=False)
    for name, raw in {**files, 'input-manifest.json':encoded(_manifest(case, files))}.items():
        with (out/name).open('xb') as stream:
            stream.write(raw)
    return check_project(out)


def check_project(project):
    folder = _destination(project)
    m = read_json(folder/'input-manifest.json')
    case = m.get('case_id')
    check_role(case, m.get('stored_bit'), m.get('variant'))
    _project_name(folder.name, case)
    files = expected_files(case, folder.name)
    if m != _manifest(case, files):
        raise ValueError('Manifest, implementation hashes or allowed role differs')
    expected = {**files, 'input-manifest.json':encoded(_manifest(case, files))}
    if {p.name for p in folder.iterdir()} != set(expected):
        raise ValueError('Input file inventory differs; this is an input checker, not a completed-run checker')
    for name, raw in expected.items():
        p = folder/name
        if p.is_symlink() or not p.is_file() or p.read_bytes() != raw:
            raise ValueError('Full expected input bytes differ: '+name)
    return {'status':'OFFLINE_INPUT_CHECK_PASSED', 'solver_started':False, 'tcad_ready':False,
            'project':str(folder), 'case_id':case, 'stored_bit':1, 'variant':'main', 'dimension':3,
            'manifest_sha256':sha((folder/'input-manifest.json').read_bytes()),
            'geometry_contract_sha256':contract()['geometry_contract_sha256'],
            'offline_source_check':offline_proof(source_spec(case))}


def check_control(a0, a1):
    results = [check_project(a0), check_project(a1)]
    if [r['case_id'] for r in results] != ['A0', 'A1']:
        raise ValueError('Control pair must be A0 then A1')
    p0, p1 = (read_json(Path(x)/'parameters.json') for x in (a0, a1))
    if p0['matching_contract'] != p1['matching_contract'] or (Path(a0)/'geometry.scm').read_bytes() != (Path(a1)/'geometry.scm').read_bytes():
        raise ValueError('Geometry/numerics/state/timing/control mismatch')
    return {'status':'OFFLINE_MATCHED_CONTROL_PASSED', 'is_tcad_result':False,
            'matching_contract_sha256':p0['matching_contract_sha256'],
            'case_manifests':[r['manifest_sha256'] for r in results]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build'); b.add_argument('output', type=Path); b.add_argument('--case', choices=('A0','A1'), required=True)
    b.add_argument('--bit', type=int, choices=(1,), default=1); b.add_argument('--variant', choices=('main',), default='main'); b.add_argument('--spec', type=Path)
    k = sub.add_parser('check'); k.add_argument('project', type=Path)
    o = sub.add_parser('check-source'); o.add_argument('--case', choices=('A0','A1'), required=True)
    pair = sub.add_parser('check-control'); pair.add_argument('a0', type=Path); pair.add_argument('a1', type=Path)
    sub.add_parser('plan')
    args = parser.parse_args()
    if args.command == 'build':
        result = build(args.output, args.case, args.bit, args.variant, read_json(args.spec) if args.spec else None)
    elif args.command == 'check':
        result = check_project(args.project)
    elif args.command == 'check-source':
        result = offline_proof(source_spec(args.case))
    elif args.command == 'check-control':
        result = check_control(args.a0, args.a1)
    else:
        result = {'allowed_roles':contract()['allowed_roles'], 'budget':contract()['budget'], 'solver_started':False}
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
