"""Build immutable artificial 2D source projects; no solver, SSH or scheduler."""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONTRACT = HERE / 'source_contract.json'
OUTPUT_ROOT = ROOT / 'local_runtime/dram-see-v4/source-interface-r2'
LEGACY = ROOT / 'experiments/dram-see-v3/r50-main/build_case.py'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def read_json(path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError('Duplicate JSON field: ' + k)
            result[k] = v
        return result
    def invalid(v):
        raise ValueError('Nonfinite JSON constant: ' + v)
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique, parse_constant=invalid)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def contract():
    c = read_json(CONTRACT)
    if c.get('schema') != 'dram-see-v4-source-interface-r2-contract' or c.get('revision') != 2:
        raise ValueError('Unsupported source contract')
    return c


def number(x):
    if type(x) not in (int, float) or not math.isfinite(x):
        raise ValueError('Finite numeric value required')
    return format(x, '.17g')


def make_spec(case):
    c = contract()
    if case not in c['case_ids']:
        raise ValueError('Unknown case')
    tracks = []
    count = 0 if case == 'A0' else 2 if case in ('A4', 'A5', 'A6', 'A7', 'A8S2') else 4 if case == 'A8S4' else 1
    for i in range(count):
        q, start, direction, length, time = 1 / count, [.425, .3, 0.], [0., 1., 0.], .6, 1e-9
        if case == 'A2':
            start, direction = [.575, .3401923788646684, 0.], [-.5, .8660254037844386, 0.]
        if case == 'A3':
            start[0] = 0.
        if case in ('A5', 'A6', 'A7'):
            start[0] = [.325, .525][i]
        if case == 'A6' and i == 1:
            time = 1.01e-9
        if case.startswith('A8'):
            length = .6 / count
            start[1] = .3 + i * length
        tracks.append({'track_id': 1 if case.startswith('A8') else i + 1,
                       'parent_id': 0, 'segment_id': i + 1, 'source_name': 'Ion' + str(i + 1),
                       'source_step_ids': ['artificial-step-' + str(i + 1)],
                       'q_fC': q, 'start_um': start, 'direction': direction, 'length_um': length,
                       'wt_hi_um': c['kernel']['width_um'], 's_hi_s': c['kernel']['s_hi_s'],
                       'time_s': time, 'let_pC_per_um': q * .001 / length})
    if case == 'A7':
        tracks.reverse()  # Preserve physical IDs/names; only input order changes.
    return {'schema': 'dram-see-v4-source-interface-r2-spec', 'case_id': case,
            'event_id': 'artificial-source-interface-r2-' + case.lower(),
            'synthetic': True, 'dimension': 2, 'projection': None,
            'units': c['units'], 'source_total_fC': 0. if case == 'A0' else 1., 'tracks': tracks}


def validate_spec(spec, frozen=True):
    if not isinstance(spec, dict) or spec.get('schema') != 'dram-see-v4-source-interface-r2-spec':
        raise ValueError('Unknown source schema')
    if type(spec.get('dimension')) is not int or spec['dimension'] != 2 or spec.get('synthetic') is not True or spec.get('projection') is not None:
        raise ValueError('Only artificial 2D sources; real 3D events and undefined projection rejected')
    if not isinstance(spec.get('event_id'), str) or not spec['event_id']:
        raise ValueError('Missing event identity, including zero-source events')
    if spec.get('units') != contract()['units'] or not isinstance(spec.get('tracks'), list):
        raise ValueError('Missing/conflicting units or track list')
    names, segments, step_ids = set(), set(), set()
    for track in spec['tracks']:
        for k in ('start_um', 'direction'):
            if not isinstance(track.get(k), list) or len(track[k]) != 3:
                raise ValueError('Preserve explicit xyz/direction triple')
            for v in track[k]:
                number(v)
        if track['start_um'][2] != 0 or track['direction'][2] != 0:
            raise ValueError('Nonzero z/direction-z cannot be silently dropped')
        if not math.isclose(sum(v*v for v in track['direction']), 1., rel_tol=0, abs_tol=1e-12):
            raise ValueError('Direction must be normalized')
        for k in ('q_fC', 'length_um', 'wt_hi_um', 's_hi_s', 'time_s', 'let_pC_per_um'):
            number(track.get(k))
            if track[k] <= 0:
                raise ValueError('Source dimensions, charge and time must be positive')
        if track['wt_hi_um'] != .03 or track['s_hi_s'] != 2e-12:
            raise ValueError('Source kernel differs from this revision')
        if not math.isclose(track['q_fC'], track['let_pC_per_um'] * track['length_um'] * 1e3, rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError('Segment LET/length/charge does not close')
        if not re.fullmatch(r'Ion[1-9][0-9]*', track.get('source_name', '')) or track['source_name'] in names:
            raise ValueError('Missing/duplicate source name')
        if type(track.get('segment_id')) is not int or track['segment_id'] in segments or track['segment_id'] <= 0:
            raise ValueError('Missing/duplicate segment ID')
        if type(track.get('track_id')) is not int or track['track_id'] <= 0 or track.get('parent_id') != 0:
            raise ValueError('Artificial parent/track identity differs')
        ids = track.get('source_step_ids')
        if not isinstance(ids, list) or not ids or any(not isinstance(k, str) or not k or k in step_ids for k in ids) or len(set(ids)) != len(ids):
            raise ValueError('Duplicate/missing source step ownership')
        step_ids.update(ids); names.add(track['source_name']); segments.add(track['segment_id'])
    number(spec.get('source_total_fC'))
    if not math.isclose(sum(t['q_fC'] for t in spec['tracks']), spec['source_total_fC'], rel_tol=1e-12, abs_tol=1e-15):
        raise ValueError('Source total does not equal segment charge sum')
    if frozen and encoded(spec) != encoded(make_spec(spec.get('case_id'))):
        raise ValueError('Source differs from the pre-registered case')
    return spec


def temporal(t, track):
    if t < 0:
        return 0.
    s, t0 = track['s_hi_s'], track['time_s']
    return math.exp(-((t-t0)/(2*s))**2)/(s*math.sqrt(math.pi)*(1+math.erf(t0/(2*s))))


def generation(spec, x, y, t):
    """Prescribed analytic density, not an observed TCAD field [pairs/cm^3/s]."""
    c = contract()
    parts = []
    for a in spec['tracks']:
        dx, dy = a['direction'][:2]
        rx, ry = x-a['start_um'][0], y-a['start_um'][1]
        longitudinal, transverse = rx*dx+ry*dy, -rx*dy+ry*dx
        if 0 <= longitudinal < a['length_um']:
            w = a['wt_hi_um']
            parts.append(a['q_fC']*1e-15/c['conversion']['elementary_charge_C'] * 1e12/c['device']['effective_thickness_um']
                         * math.exp(-(transverse/w)**2)/(math.sqrt(math.pi)*w*a['length_um'])*temporal(t, a))
    return math.fsum(parts)


def _simpson3(f, lo, hi, n):
    if hi <= lo:
        return (0., 0., 0.)
    h = (hi-lo)/n
    accum = [0., 0., 0.]
    for i in range(n+1):
        weight = 1 if i in (0, n) else 4 if i % 2 else 2
        val = f(lo+i*h)
        for j in range(3):
            accum[j] += weight*val[j]
    return tuple(v*h/3 for v in accum)


def rectangle_moments(track, rect, n=256):
    """Rotate rectangle into path coordinates; Gaussian transverse integral is analytic.

    Returns (fraction, integral x*dFraction, integral y*dFraction).
    Simpson integrates only longitudinal position, split at all projected corners.
    """
    x0, y0 = track['start_um'][:2]
    dx, dy = track['direction'][:2]
    w, length = track['wt_hi_um'], track['length_um']
    xmin, ymin, xmax, ymax = rect
    def at(s):
        bx, by = x0+dx*s, y0+dy*s
        low, high = -math.inf, math.inf
        for base, coeff, a, b in ((bx, -dy, xmin, xmax), (by, dx, ymin, ymax)):
            if abs(coeff) < 1e-14:
                if base < a-1e-14 or base > b+1e-14:
                    return (0., 0., 0.)
            else:
                v1, v2 = (a-base)/coeff, (b-base)/coeff
                low, high = max(low, min(v1,v2)), min(high, max(v1,v2))
        if low >= high:
            return (0., 0., 0.)
        frac = (math.erf(high/w)-math.erf(low/w))/2
        vm = w/(2*math.sqrt(math.pi))*(math.exp(-(low/w)**2)-math.exp(-(high/w)**2))
        return (frac/length, (bx*frac-dy*vm)/length, (by*frac+dx*vm)/length)
    cuts = sorted({0., length} | {max(0., min(length, (x-x0)*dx+(y-y0)*dy))
                   for x in (xmin, xmax) for y in (ymin,ymax)})
    # Endpoints at rectangle discontinuities have zero measure; avoid Simpson assigning a full sample there.
    def interior(a,b):
        eps = min((b-a)*1e-8, 1e-12)
        return _simpson3(lambda s: at(min(b-eps,max(a+eps,s))),a,b,n)
    values = [interior(a,b) for a,b in zip(cuts,cuts[1:])]
    return tuple(math.fsum(v[j] for v in values) for j in range(3))


def offline_check(spec):
    validate_spec(spec)
    c = contract()
    rois = {}
    for roi, rect in c['rois_um'].items():
        parts = []
        for a in spec['tracks']:
            m, fine = rectangle_moments(a,rect), rectangle_moments(a,rect,512)
            q = a['q_fC']
            tolerance = max(c['offline_tolerances']['charge_abs_fC'], c['offline_tolerances']['charge_relative']*q*fine[0])
            if abs(m[0]-fine[0])*q > tolerance:
                raise ValueError('Offline quadrature has not converged for ' + roi)
            parts.append({'source_name': a['source_name'], 'fraction': fine[0], 'q_fC': q*fine[0],
                          'x_moment_fC_um': q*fine[1], 'y_moment_fC_um': q*fine[2],
                          'quadrature_error_fC': q*(m[0]-fine[0])})
        q = math.fsum(p['q_fC'] for p in parts)
        rois[roi] = {'q_fC': q, 'tracks': parts,
                     'centroid_x_um': math.fsum(p['x_moment_fC_um'] for p in parts)/q if q else None,
                     'centroid_y_um': math.fsum(p['y_moment_fC_um'] for p in parts)/q if q else None}
    inside = rois['Total']['q_fC']
    return {'schema': 'dram-see-v4-source-interface-r2-offline', 'status': 'OFFLINE_ONLY', 'is_tcad_result': False,
            'case_id': spec['case_id'], 'source_total_fC': spec['source_total_fC'], 'domain_charge_fC': inside,
            'outside_domain_fC': spec['source_total_fC']-inside, 'rois': rois,
            'time_window_outside_fraction_upper_bound': math.erfc((1e-9)/(4e-12)),
            'normalization': 'No clipping renormalization; manufactured kernel only'}


def render_sources(spec):
    return '\n '.join('HeavyIon("'+a['source_name']+'") ( StartPoint=('+','.join(map(number,a['start_um'][:2]))
                     +') Direction=('+','.join(map(number,a['direction'][:2]))+') Time='+number(a['time_s'])
                     +' Length='+number(a['length_um'])+' Wt_hi='+number(a['wt_hi_um'])
                     +' LET_f='+number(a['let_pC_per_um'])+' Gaussian PicoCoulomb )' for a in spec['tracks'])


def render_parameters(spec):
    return '* Explicit frozen source coefficients, not installation defaults.\n' + ''.join(
        'HeavyIon("'+a['source_name']+'") {\n'+''.join('  '+k+' = '+number(v)+'\n' for k,v in contract()['heavyion_parameters'].items())+'}\n'
        for a in spec['tracks'])


def render_deck(spec, bit, variant):
    c = contract()
    legacy = load_module(LEGACY, '_r2_readonly_template')
    requests = []
    for name, (x0,y0,x1,y1) in c['rois_um'].items():
        coords = ' Coordinates' if name == 'Total' and spec['tracks'] else ''
        requests.append('Integrate(Name="G_'+name+'" Semiconductor Window[('+number(x0)+' '+number(y0)+') ('+number(x1)+' '+number(y1)+')]'+coords+')')
    cur = 'CurrentPlot { HeavyIonGeneration(\n '+'\n '.join(requests)+'\n) }'
    deck = legacy._single_device(.9 if bit else .1, 1., render_sources(spec), 'HeavyIonChargeDensity HeavyIonGeneration',cur)
    deck = legacy._replace_once(deck,'Plot="device.tdr"','Plot="device.tdr" Parameter="heavyion.par"')
    deck = legacy._replace_once(deck,'Math { RelErrControl','Math { CurrentPlot(IntegrationUnit=um Digits=12) RelErrControl')
    old = 'Transient(InitialTime=0.95e-9 FinalTime=1.05e-9 InitialStep=2e-13 MinStep=1e-18 MaxStep=1e-12 Increment=1.3)'
    step = c['variants'][variant]['pulse_max_step_s']
    new = 'Transient(InitialTime=0.95e-9 FinalTime=1.05e-9 InitialStep='+number(step/5)+' MinStep=1e-18 MaxStep='+number(step)+' Increment=1.3)'
    deck = legacy._replace_once(deck,old,new)
    plots = '\n '.join('Plot(FilePrefix="gfield_'+str(i)+'" Time=('+number(t)+'))' for i,t in enumerate(c['tdr_times_s']))
    return legacy._replace_once(deck,'Plot(FilePrefix="strike" Time=(1e-9))',plots)


def render_tdr_extractor():
    """Optional native SVisual batch extraction; root runs it on completed TDRs only."""
    lines = ['# svisual -b -tcl extract_fields.tcl ; optional postprocessing, no solver',
             'set out [open "tdr-spatial.csv" w]', 'puts $out "snapshot,time_s,roi,field,raw_integral_um2_cm3_s"']
    for i,t in enumerate(contract()['tdr_times_s']):
        lines += ['set data [load_file gfield_'+str(i)+'_access_des.tdr]',
                  'set fields [list_fields HeavyIonGeneration -dataset $data]',
                  'if {[llength $fields] != 1 || [lindex $fields 0] ne "HeavyIonGeneration"} {error "Missing/ambiguous actual HeavyIonGeneration field: $fields"}']
        for roi, rect in contract()['rois_um'].items():
            lines += ['set value [integrate_field -dataset $data -field HeavyIonGeneration -materials {Silicon} -window {'+' '.join(map(number,rect))+'}]',
                      'puts $out "'+str(i)+','+number(t)+','+roi+',HeavyIonGeneration,$value"']
    return '\n'.join(lines+['close $out','puts "R2_TDR_EXTRACTION_COMPLETED"','exit'])+'\n'


def check_role(case, bit, variant):
    if type(bit) is not int or [case, bit, variant] not in contract()['run_sequence']:
        raise ValueError('Not in the approved maximum-19-run sequence')


def code_hashes():
    files = [Path(__file__),CONTRACT,LEGACY,ROOT/'experiments/dram-see-v1/build_case.py',
             ROOT/'scripts/tcad.py',ROOT/'local_runtime/dram-see-v1/heavyion-reference.txt']
    return {p.relative_to(ROOT).as_posix():sha(p.read_bytes()) for p in files}


def build(out, case, bit=1, variant='base', supplied_spec=None):
    check_role(case,bit,variant)
    spec = make_spec(case) if supplied_spec is None else validate_spec(supplied_spec)
    if spec['case_id'] != case:
        raise ValueError('Case mismatch')
    proof = offline_check(spec)
    out = Path(out).resolve()
    if not out.is_relative_to(OUTPUT_ROOT.resolve()) or out == OUTPUT_ROOT.resolve() or out.exists():
        raise ValueError('Use a new child directory of local_runtime/dram-see-v4/source-interface-r2')
    if not re.fullmatch('v4-source-interface-r2-'+case.lower()+'-b'+str(bit)+'-'+variant+r'(?:-[a-z0-9_-]+)?',out.name):
        raise ValueError('Output name must bind revision, case, bit and variant')
    out.parent.mkdir(parents=True,exist_ok=True)
    legacy = load_module(LEGACY,'_r2_geometry_readonly')
    mesh = contract()['variants'][variant]['mesh_factor']
    geometry = legacy._geometry(.25,mesh,5.,out.parent)
    common = {'gate_length_um':.25,'oxide_nm':5.,'stored_bit':bit,'target_voltage_V':.9 if bit else .1,
              'reference_mode':'offline','neutral':False,'capacitance_F':1e-14,'bitline_capacitance_F':1e-13,
              'reference_capacitance_F':1e-13,'effective_thickness_um':1.,'temperature_K':300,
              'mesh_scale':mesh,'step_scale':1.,'variant':variant,
              'pulse_max_step_s':contract()['variants'][variant]['pulse_max_step_s'],
              'prestrike_s':.95e-9,'strike_s':1e-9,'hold_end_s':2.8e-9,'precharge_end_s':3e-9,'read_sample_s':4e-9,
              'geometry_sha256':sha(geometry),'physics':legacy.PHYSICS,'circuit_revision':legacy.CIRCUIT}
    code = code_hashes()
    p = {**common,'schema':'dram-see-v4-source-interface-r2','case_id':case,'event_id':spec['event_id'],
         'source_spec_sha256':sha(encoded(spec)),'source_contract_sha256':sha(CONTRACT.read_bytes()),
         'source_count':len(spec['tracks']),'source_charge_fC':spec['source_total_fC'],
         'domain_charge_fC':proof['domain_charge_fC'],'synthetic':True,'parent_run':None,
         'matching_contract':common,'matching_contract_sha256':sha(encoded(common)), 'source_code_sha256':code}
    outputs = ['circuit.plt','access_device.plt','final_access_des.tdr','transient_des.log']
    outputs += ['gfield_'+str(i)+'_access_des.tdr' for i in range(len(contract()['tdr_times_s']))]
    project = {'name':out.name,'steps':[{'tool':'sde','args':['-e','-l','geometry.scm'],'outputs':['cell_msh.tdr']},
                                      {'tool':'sdevice','args':['device.cmd'],'outputs':outputs}]}
    files = {'geometry.scm':geometry,'device.cmd':render_deck(spec,bit,variant).encode(),
             'heavyion.par':render_parameters(spec).encode(),'parameters.json':encoded(p),'project.json':encoded(project),
             'source-spec.json':encoded(spec),'source-contract.json':CONTRACT.read_bytes(),
             'offline-source-check.json':encoded(proof),'extract_fields.tcl':render_tdr_extractor().encode()}
    manifest = {'schema':'dram-see-v4-source-interface-r2-inputs','case_id':case,'stored_bit':bit,'variant':variant,
                'files_sha256':{n:sha(data) for n,data in files.items()},'source_code_sha256':code,'solver_started':False}
    out.mkdir()
    for name,data in {**files,'input-manifest.json':encoded(manifest)}.items():
        with (out/name).open('xb') as stream:
            stream.write(data)
    return check_project(out)


def check_project(project):
    folder = Path(project).resolve()
    if not folder.is_relative_to(OUTPUT_ROOT.resolve()) or folder == OUTPUT_ROOT.resolve():
        raise ValueError('Not an r2 project directory')
    m = read_json(folder/'input-manifest.json')
    if set(p.name for p in folder.iterdir()) != set(m['files_sha256'])|{'input-manifest.json'}:
        raise ValueError('Input file inventory mismatch')
    for name,digest in m['files_sha256'].items():
        if '/' in name or '\\' in name or (folder/name).is_symlink() or not (folder/name).is_file() or sha((folder/name).read_bytes()) != digest:
            raise ValueError('Input hash/file mismatch: '+name)
    if m['source_code_sha256'] != code_hashes() or (folder/'source-contract.json').read_bytes() != CONTRACT.read_bytes():
        raise ValueError('Implementation/reference/contract changed after freezing inputs')
    p, spec = read_json(folder/'parameters.json'), validate_spec(read_json(folder/'source-spec.json'))
    check_role(p['case_id'],p['stored_bit'],p['variant'])
    if (spec['case_id'] != p['case_id'] or p['event_id'] != spec['event_id'] or p['source_spec_sha256'] != sha(encoded(spec))
        or p['source_contract_sha256'] != sha(CONTRACT.read_bytes()) or p['matching_contract_sha256'] != sha(encoded(p['matching_contract']))
        or p['geometry_sha256'] != sha((folder/'geometry.scm').read_bytes()) or p['source_code_sha256'] != m['source_code_sha256']):
        raise ValueError('Identity/matching-contract/geometry mismatch')
    if any(p[k] != v for k,v in p['matching_contract'].items()):
        raise ValueError('Common parameter mismatch')
    if (folder/'device.cmd').read_text() != render_deck(spec,p['stored_bit'],p['variant']) or (folder/'heavyion.par').read_text() != render_parameters(spec):
        raise ValueError('Complete deck or named parameter file differs')
    proof = offline_check(spec)
    if encoded(read_json(folder/'offline-source-check.json')) != encoded(proof) or p['domain_charge_fC'] != proof['domain_charge_fC']:
        raise ValueError('Offline charge ledger differs')
    return {'status':'OFFLINE_INPUT_CHECK_PASSED','solver_started':False,'project':str(folder),
            'case_id':p['case_id'],'stored_bit':p['stored_bit'],'variant':p['variant'],
            'manifest_sha256':sha((folder/'input-manifest.json').read_bytes()),'offline_source_check':proof}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    b = sub.add_parser('build'); b.add_argument('output',type=Path); b.add_argument('--case',required=True,choices=contract()['case_ids'])
    b.add_argument('--bit',type=int,choices=(0,1),default=1); b.add_argument('--variant',choices=('base','time','mesh'),default='base'); b.add_argument('--spec',type=Path)
    k = sub.add_parser('check'); k.add_argument('project',type=Path)
    o = sub.add_parser('check-source'); o.add_argument('--case',required=True,choices=contract()['case_ids'])
    sub.add_parser('plan')
    args = parser.parse_args()
    if args.command == 'build':
        result = build(args.output,args.case,args.bit,args.variant,read_json(args.spec) if args.spec else None)
    elif args.command == 'check':
        result = check_project(args.project)
    elif args.command == 'check-source':
        result = offline_check(make_spec(args.case))
    else:
        result = {'run_sequence':contract()['run_sequence'],'maximum_tcad_runs':19,'solver_started':False}
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__ == '__main__':
    main()
