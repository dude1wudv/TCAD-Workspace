"""Input-only 5 MeV alpha strip projection and documented 2D LET mapping.

No device-deck edits, native calls, response fields, clock observations or data
qualification. Existing alpha-v2 stopping/LUT and common projection primitives
are loaded only from fixed local paths with exact hashes.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUTPUT = ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/alpha-implementation'
DEPENDENCIES = {
    'alpha': ('../proton/alpha_source_v2.py', 'a75aade10dd65acbab0b3e6af03f86166112125d482e815abc590789a43eed43'),
    'moments': ('../proton/alpha_moments_v2.py', 'cf0c2b0d43baf8c4021989ed5de8bd162d7767a6fcfa5c68b5d35ade5c7c70c2'),
    'common': ('../projection2d/kernel.py', 'c9b44b5f808212a018dfa37542bc218410048ba05d9ee211b2bf933bc4d78069')}
SCHEMA = 'dram-see-v4-alpha-projection-2d-r1'
WIDTH_UM, REF_UM, W_UM, SIGMA_S = .02, 1., .05, .2e-12
E_C = 1.602176634e-19
INPUT_NAMES = ('model.proposed.json', 'geometry-contract.json', 'dimensional-contract.json', 'alpha-astar-silicon.csv')


def require(ok, message):
    if not ok:
        raise ValueError('Alpha 2D projection: '+message)


def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode('utf-8')
def read_json(path): return json.loads(Path(path).read_bytes())


def _module(key):
    relative, expected = DEPENDENCIES[key]
    path = (HERE/relative).resolve(); raw = path.read_bytes()
    require(sha(raw) == expected, 'fixed dependency changed: '+relative)
    spec = importlib.util.spec_from_file_location('_alpha_projection_2d_'+key, str(path))
    result = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(path), 'exec'), result.__dict__)
    return result


A, M, K = (_module(name) for name in ('alpha', 'moments', 'common'))
R = K.R


def mapping(amplitude=1., epoch_s=15e-9):
    require(type(amplitude) in (int, float) and amplitude in (0, .5, 1), 'only amplitudes 0, 0.5 and 1 are declared')
    require(type(epoch_s) in (int, float) and math.isfinite(epoch_s) and epoch_s >= 8*SIGMA_S,
            'epoch must be explicit and at least 8sigma after zero')
    fy = R.gaussian_interval(-WIDTH_UM/2, WIDTH_UM/2, 0., W_UM)[0]
    native_positive_time_mass = .5*(1+math.erf(epoch_s/(math.sqrt(2)*SIGMA_S)))
    return dict(effective_width_um=WIDTH_UM, effective_width_cm=WIDTH_UM*1e-4,
        native_reference_width_um=REF_UM, radial_width_um=W_UM, sigma_s=SIGMA_S, amplitude=float(amplitude),
        strip_gaussian_mass=fy, outside_strip_gaussian_mass=math.erfc(WIDTH_UM/(2*W_UM)),
        geometric_LET_multiplier=fy*REF_UM/WIDTH_UM,
        native_positive_time_mass=native_positive_time_mass,
        applied_LET_multiplier=amplitude*fy*REF_UM/WIDTH_UM*native_positive_time_mass,
        area_factor=.02, explicit_capacitance_rescale=False, port_current_additional_width_factor=1,
        positive_time_normalization='UG Eq810; correction applied to LET so native t>=0 rate matches the old all-real prescribed Gaussian',
        prezero_gaussian_mass_float64=.5*math.erfc(epoch_s/(math.sqrt(2)*SIGMA_S)),
        prezero_zero_is_underflow_not_structural_zero=True,
        applied_to='Original ASTAR per-position electronic_pC_um only; never multiply an already finite-Si charge by Fy again')


def _context(inputs, request):
    require(set(inputs) == set(INPUT_NAMES) and all(isinstance(v, bytes) for v in inputs.values()), 'exact pure-input byte set required')
    model = json.loads(inputs['model.proposed.json']); g = json.loads(inputs['geometry-contract.json'])
    width = json.loads(inputs['dimensional-contract.json'])
    expected = dict(schema='dram-see-v4-2d-equivalence-r1', native_dimension=2, physical_dimension=2,
        effective_width_nm=20, effective_width_um=.02, effective_width_cm=2e-6, native_reference_width_um=1,
        area_factor=.02, native_to_physical_axes=dict(X='x', Y='z', Z='omitted_y'), native_third_coordinate=0,
        out_of_plane_axis='y', native_coordinate_unit='um', port_current_already_width_scaled=True,
        explicit_capacitance_rescale=False, Cstore_fF=20, Cbl_fF=200, source_dimension=2,
        native_area_integral_unit='um^2', area_to_cm2_factor=1e-8, area_integral_to_effective_volume_cm3_factor=2e-14)
    require(all(width.get(k) == v for k, v in expected.items())
            and width['geometry_contract_sha256'] == sha(inputs['geometry-contract.json']), 'actual D2 width/axis contract differs')
    require(g.get('dimension') == 2 and g.get('schema') == 's2-bcat-analytic-geometry-r1' and g.get('length_unit') == 'um'
            and g['sti']['included'] is False and g['domain_um'] == dict(x=[-1.,1.], y=[-.25,.25], z=[0.,1.]),
            'original actual D2 central material section required')
    mg, d, alpha = model['geometry'], model['doping'], model['alpha']
    require(mg['gate_top_depth_nm'] == 80 and d['sn_junction_depth_nm'] == 87 and mg['active_width_nm'] == 20,
            'initial alpha projection supports only S2 gate80/SN87; no final geometry is read')
    require(alpha['position_nm'] == [-52,0,0] and alpha['radial_Gaussian_w_nm'] == 50
            and alpha['temporal_sigma_ps'] == .2 and alpha['eV_per_pair'] == 3.6, 'original alpha kernel differs')
    tr = g['outer_trench']; gate = g['gate_void']
    require(tr['construction'] == 'rectangle/cuboid union circle/cylinder' and tr['x_half_width_um'] == tr['radius_um'] == .012
            and tr['round_center_z_um'] == .142 and tr['top_um'] == 0. and tr['bottom_um'] == .154
            and tr['y_half_width_um'] >= .01 and gate['top_um'] == .08 and gate['bottom_um'] == .15,
            'actual central Si boundary differs')
    expected_asn = d['sn_junction_depth_nm']/1000/math.sqrt(math.log(d['peak_donor']/d['uniform_acceptor']))
    require(abs(g['doping']['a_sn_um']-expected_asn) <= 1e-14 and g['doping']['peak_cm3'] == d['peak_donor']
            and g['doping']['acceptor_cm3'] == d['uniform_acceptor'], 'D2 model/doping does not match source geometry')
    response = dict(kind='bcat_center_section', bounds_xz_um=[-1.,0.,1.,1.],
        outer_trench=dict(radius_um=tr['radius_um'], center_z_um=tr['round_center_z_um'], top_um=tr['top_um']))
    require(abs(2-(2*.012*.142+math.pi*.012**2/2)-g['measures']['silicon']) <= 1e-11,
            'D2 Si area is not the declared material mask')
    require(set(request) == {'schema','energy_MeV','theta_deg','phi_deg','amplitude','epoch_s','simulation_window_s'}
            and request['schema'] == 'dram-see-v4-alpha-projection-request-r1' and request['energy_MeV'] == 5
            and type(request['theta_deg']) is int and request['theta_deg'] in (0,30) and request['phi_deg'] == 180,
            'unsupported alpha projection request')
    factors = mapping(request['amplitude'], request['epoch_s'])
    window = request['simulation_window_s']
    source_window = [request['epoch_s']-8*SIGMA_S, request['epoch_s']+8*SIGMA_S]
    require(isinstance(window, list) and len(window) == 2 and all(type(v) in (int,float) and math.isfinite(v) for v in window)
            and 0 <= window[0] < source_window[0] < source_window[1] < window[1],
            'complete +/-8sigma source observation must fit explicit simulation window')
    theta = math.radians(request['theta_deg']); direction = [-math.sin(theta),0.,math.cos(theta)]
    origin = [-.052,0.,0.]
    path = A.ray_box(origin, direction, [-1.,-.01,0.,1.,.01,1.])
    require(path['entry_parameter_um'] == 0 and max(path['entry_um'][0], path['exit_um'][0]) < -.012,
            'full centerline is not proven Si; no oxide propagation may be inferred')
    path.update(direction=direction, origin_um=origin, transverse_u=[math.cos(theta),0.,math.sin(theta)],
                transverse_v=[0.,1.,0.], end_planes='Perpendicular to direction at s=0 and s=L')
    rows, energy = A.profile(A.Stopping(inputs['alpha-astar-silicon.csv']), 5, path['length_um'])
    return dict(rows=rows, path=path, energy=energy, factors=factors, response=response,
        mask=K.ResponseMask(response), request=request, source_window_s=source_window, width=width)


def _intersect(a, b):
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    return (lo, hi) if hi > lo else None


def _linear_interval(value, slope, lo, hi):
    if slope == 0:
        return (-math.inf, math.inf) if lo <= value <= hi else None
    a, b = (lo-value)/slope, (hi-value)/slope
    return (min(a,b), max(a,b))


def _rectangle_interval(x, z, ux, uz, box):
    a = _linear_interval(x, ux, box[0], box[2]); b = _linear_interval(z, uz, box[1], box[3])
    return _intersect(a, b) if a is not None and b is not None else None


def _u_partition(ctx, s):
    """Exact transverse line/rectangle and line/circular-cap intersections."""
    d, u, origin = ctx['path']['direction'], ctx['path']['transverse_u'], ctx['path']['origin_um']
    x, z = origin[0]+s*d[0], origin[2]+s*d[2]
    mask = ctx['mask']; box = _rectangle_interval(x,z,u[0],u[2],mask.box)
    if box is None:
        return None, [], []
    t = mask.trench; r, c, top = t['radius_um'], t['center_z_um'], t['top_um']
    excluded = []
    rect = _rectangle_interval(x,z,u[0],u[2],[-r,top,r,c])
    if rect is not None:
        row = _intersect(box,rect)
        if row is not None: excluded.append(row)
    projection = x*u[0]+(z-c)*u[2]
    axial_offset = x*d[0]+(z-c)*d[2]
    discriminant = (r-abs(axial_offset))*(r+abs(axial_offset))
    if discriminant > 0:
        a = (-projection-math.sqrt(discriminant), -projection+math.sqrt(discriminant))
        lower_cap = _linear_interval(z,u[2],c,c+r)
        if lower_cap is not None:
            a = _intersect(a,lower_cap)
            if a is not None:
                a = _intersect(a,box)
                if a is not None: excluded.append(a)
    merged = []
    for a,b in sorted(excluded):
        if merged and a <= merged[-1][1]: merged[-1] = (merged[-1][0],max(b,merged[-1][1]))
        else: merged.append((a,b))
    silicon = []; cursor = box[0]
    for a,b in merged:
        if a > cursor: silicon.append((cursor,a))
        cursor = max(cursor,b)
    if cursor < box[1]: silicon.append((cursor,box[1]))
    return box, merged, silicon


def _primitives(intervals):
    return R.add_vectors([M.gaussian_primitives(a,b,W_UM,R)[:3] for a,b in intervals], 3)


def projected_integral(ctx, refined=False):
    """Positive charge categories; no old finite-Si Q is multiplied by Fy."""
    path = ctx['path']; d, u, origin = path['direction'], path['transverse_u'], path['origin_um']
    mask = ctx['mask']; length = path['length_um']; rows = ctx['rows']
    splits = {0.,length} | {r['path_um'] for r in rows}
    r, c, top = (mask.trench[k] for k in ('radius_um','center_z_um','top_um'))
    for box in (mask.box,[-r,top,r,c]):
        for x in (box[0],box[2]):
            for z in (box[1],box[3]):
                s = (x-origin[0])*d[0]+(z-origin[2])*d[2]
                if 0 < s < length: splits.add(s)
    center_s = -origin[0]*d[0]+(c-origin[2])*d[2]
    for s in (center_s-r,center_s,center_s+r):
        if 0 < s < length: splits.add(s)
    splits = sorted(splits); pieces = []
    factor = .25 if refined else 1.
    for lo,hi in zip(splits,splits[1:]):
        def point(s):
            s = min(math.nextafter(hi,lo),max(math.nextafter(lo,hi),s))
            box, non_si, si = _u_partition(ctx,s)
            f,m,second = _primitives(si); fn = _primitives(non_si)[0]
            outside = 1. if box is None else K.tails(box[0],box[1],0.,W_UM)
            sx,sz = s*d[0],s*d[2]
            values = [outside,fn,f,sx*f+u[0]*m,sz*f+u[2]*m,
                sx*sx*f+2*sx*u[0]*m+u[0]**2*second,
                sx*sz*f+(sx*u[2]+sz*u[0])*m+u[0]*u[2]*second,
                sz*sz*f+2*sz*u[2]*m+u[2]**2*second]
            return [A.line_density(s,rows)*v for v in values]
        if lo>=center_s-r and hi<=center_s+r:
            a=math.asin(max(-1.,min(1.,(lo-center_s)/r)))
            b=math.asin(max(-1.,min(1.,(hi-center_s)/r)))
            pieces.append(R.integrate_vector(lambda angle:[v*r*math.cos(angle) for v in point(center_s+r*math.sin(angle))],
                a,b,K.ABS_TOL*factor/len(splits),K.REL_TOL*factor))
        else:
            pieces.append(R.integrate_vector(point,lo,hi,K.ABS_TOL*factor/len(splits),K.REL_TOL*factor))
    v = R.add_vectors(pieces,8); amp = ctx['factors']['amplitude']; fy = ctx['factors']['strip_gaussian_mass']
    v = [amp*fy*x for x in v]
    line = amp*ctx['energy']['tabulated_line_charge_fC']
    outer_y = amp*ctx['energy']['tabulated_line_charge_fC']*ctx['factors']['outside_strip_gaussian_mass']
    epoch = ctx['request']['epoch_s']; win = ctx['source_window_s']
    tmass, tfirst = R.temporal_interval(win[0]-epoch,win[1]-epoch,0.,SIGMA_S)
    outside_time = K.tails(win[0],win[1],epoch,math.sqrt(2)*SIGMA_S)
    full = ctx['request']['simulation_window_s']
    full_mass = R.temporal_interval(full[0]-epoch,full[1]-epoch,0.,SIGMA_S)[0]
    names = ('inside_strip_outside_xz_box_fC','inside_strip_box_non_silicon_fC','response_silicon_all_time_fC',
             'response_Mx_relative_fC_um','response_Mz_relative_fC_um','response_Mxx_relative_fC_um2',
             'response_Mxz_relative_fC_um2','response_Mzz_relative_fC_um2')
    result = dict(zip(names,v))
    result.update(declared_axial_all_transverse_all_time_fC=line, outside_y_strip_fC=outer_y,
        response_silicon_outside_observation_window_fC=v[2]*outside_time,
        accepted_observation_fC=v[2]*tmass, observation_time_mass=tmass, outside_observation_time_mass=outside_time,
        response_silicon_in_full_simulation_window_fC=v[2]*full_mass,
        accepted_Mt_relative_fC_ps=v[2]*tfirst*1e12, all_time_Mtt_relative_fC_ps2=v[2]*(SIGMA_S*1e12)**2,
        charge_partition_residual_fC=line-math.fsum([outer_y,v[0],v[1],v[2]*outside_time,v[2]*tmass]),
        numerical_settings=dict(normalized_absolute=K.ABS_TOL*factor,relative=K.REL_TOL*factor,axial_partitions=len(splits)-1))
    require(all(math.isfinite(x) for x in v) and all(x>=0 for x in [line,outer_y,v[0],v[1],v[2]]),
            'nonfinite or negative projected charge category')
    result['offline_charge_gate_fC'] = max(1e-6,.001*line)
    require(abs(result['charge_partition_residual_fC']) <= result['offline_charge_gate_fC'], 'positive charge partition failed closure')
    return result


def generation3d(ctx,x_um,y_um,z_um,time_s,material=True):
    """Original transverse kernel; material=True uses extruded central Si only.

    Projection queries y inside the strip. This is not the old full-width STI
    material mask outside the strip; those source tails have their own ledger.
    """
    require(all(math.isfinite(v) for v in (x_um,y_um,z_um,time_s)), 'nonfinite source query')
    p = ctx['path']; dx,dz = x_um-p['origin_um'][0],z_um-p['origin_um'][2]
    s = dx*p['direction'][0]+dz*p['direction'][2]
    u = dx*p['transverse_u'][0]+dz*p['transverse_u'][2]
    if not 0 <= s <= p['length_um'] or (material and not ctx['mask'].contains(x_um,z_um)): return 0.
    pairs_per_um = A.line_density(s,ctx['rows'])*1e-15/E_C
    spatial = math.exp(-(u*u+y_um*y_um)/W_UM**2)/(math.pi*W_UM**2)
    temporal = math.exp(-.5*((time_s-ctx['request']['epoch_s'])/SIGMA_S)**2)/(math.sqrt(2*math.pi)*SIGMA_S)
    return ctx['factors']['amplitude']*pairs_per_um*spatial*temporal*1e12


def generation2d(ctx,x_um,z_um,time_s,material=True):
    """Exact y-average; observation windows do not truncate this Gaussian."""
    require(all(math.isfinite(v) for v in (x_um,z_um,time_s)), 'nonfinite source query')
    p = ctx['path']; dx,dz = x_um-p['origin_um'][0],z_um-p['origin_um'][2]
    s = dx*p['direction'][0]+dz*p['direction'][2]
    u = dx*p['transverse_u'][0]+dz*p['transverse_u'][2]
    if not 0 <= s <= p['length_um'] or (material and not ctx['mask'].contains(x_um,z_um)): return 0.
    pairs_per_um = A.line_density(s,ctx['rows'])*1e-15/E_C
    temporal = math.exp(-.5*((time_s-ctx['request']['epoch_s'])/SIGMA_S)**2)/(math.sqrt(2*math.pi)*SIGMA_S)
    return ctx['factors']['amplitude']*pairs_per_um*ctx['factors']['strip_gaussian_mass']/WIDTH_UM*\
        math.exp(-(u/W_UM)**2)/(math.sqrt(math.pi)*W_UM)*temporal*1e12


def render(ctx):
    number=lambda x:format(x,'.17g')
    array=lambda xs:'['+' '.join(number(x) for x in xs)+']'
    vector=lambda xs:'('+','.join(number(x) for x in xs)+')'
    name='AlphaStrip20nm2D'; p=ctx['path']; f=ctx['factors']['applied_LET_multiplier']
    include='HeavyIon("'+name+'") (\n StartPoint='+vector([p['entry_um'][0],p['entry_um'][2]])+' Direction='+vector([p['direction'][0],p['direction'][2]])+'\n'
    include+=' Time='+number(ctx['request']['epoch_s'])+'\n Length='+array(r['path_um'] for r in ctx['rows'])+'\n'
    include+=' LET_f='+array(r['electronic_pC_um']*f for r in ctx['rows'])+'\n Wt_hi='+array(W_UM for _ in ctx['rows'])+'\n Gaussian PicoCoulomb\n)\n'
    parameters=dict(a_1=0.,a_2=0.,a_3=0.,a_4=0.,k_hi=1.,c_1=0.,c_2=1.,c_3=0.,c_4=1.,s_hi=SIGMA_S)
    parameter='HeavyIon("'+name+'") {\n'+''.join(' '+k+' = '+number(v)+'\n' for k,v in parameters.items())+'}\n'
    return include.encode('utf-8'),parameter.encode('utf-8')


def derive(inputs,request):
    ctx=_context(inputs,request); coarse=projected_integral(ctx); fine=projected_integral(ctx,True)
    differences={n:abs(v-fine[n]) for n,v in coarse.items() if type(v) in (int,float)}
    require(all(differences[n]<=coarse['offline_charge_gate_fC'] for n in differences if n.endswith('_fC')),
            'new projected charge integration did not converge')
    include,parameters=render(ctx)
    profile3=A.profile_bytes(ctx['rows'])
    rows2=[dict(r,LET_2d_pC_um=r['electronic_pC_um']*ctx['factors']['applied_LET_multiplier']) for r in ctx['rows']]
    profile2=A.profile_bytes(rows2)
    ledger=dict(schema='dram-see-v4-alpha-2d-charge-ledger-r1',energy=ctx['energy'],coarse=coarse,refined=fine,
        refinement_absolute_differences=differences,
        charge_partition_order=['outside_y_strip','inside_strip_outside_xz_box','inside_strip_box_non_silicon',
            'response_silicon_outside_observation_window','accepted_observation'],
        ledger_start='Declared finite axial length, unbounded transverse normalized Gaussian, all-time electronic line charge',
        existing_finite_Si_charge_reused_or_multiplied=False,tail_renormalization=False,
        original_remaining_kinetic_energy_is_not_clipped_charge=True,is_native_measurement=False,actual_clock=None)
    contract=dict(schema=SCHEMA,particle='alpha',dimension=2,request=request,path=ctx['path'],response=ctx['response'],mapping=ctx['factors'],
        input_sha256={n:sha(v) for n,v in inputs.items()},mesh_sha256=ctx['width']['mesh_sha256'],
        physics_manifest_sha256=ctx['width']['physics_manifest_sha256'],
        dependency_sha256={key:dict(path=relative,sha256=h) for key,(relative,h) in DEPENDENCIES.items()},
        independent_reference_sha256=K.REFERENCE_SHA,astar_sha256=A.ASTAR_SHA256,
        G2_unit='cm^-3 s^-1',raw_native_area_integral_to_pairs_per_s=2e-14,
        source_window_s=ctx['source_window_s'],full_simulation_window_s=request['simulation_window_s'],
        source_window_is_observation_only=True,physical_time_tail_truncated=False,
        native_coordinates=dict(X='physical_x',Y='physical_z'),
        native_model_candidate='Gaussian PicoCoulomb HeavyIon; 2D LET mapped with documented 1um reference thickness',
        native_endpoint_requirement='Measure actual finite perpendicular end-plane behavior; UG l>=L is zero while endpoint equality is a zero-measure oracle convention',
        native_required=['A0 actual write/read functionality first','Native 2D source/Si field and full accepted source-window frames',
            '5% source charge/waveform, ROI and centroid/moment gates','Matched source-free A0 and same width/mesh/physics',
            'Actual temporal/spatial refinement; no extra AreaFactor/current/capacitance scaling'],
        unsupported=['dy not zero or y-dependent axial geometry','non-Gaussian radial kernel','different energy/geometry without explicit new version',
            'claiming projected 2D response equals 3D response'],
        PMI_required_by_this_separable_formula=False,PMI_may_be_needed_if_native_field_cannot_match=True,
        native_source_qualified=False,pmi_r12_fixed=False,is_tcad_result=False)
    payload=dict(inputs)
    payload.update({'projection-request.json':encoded(request),'alpha-profile-3d-reference.csv':profile3,
        'alpha-profile-2d-native.csv':profile2,'heavyion.physics.inc':include,'source.par':parameters,
        'projection-ledger.json':encoded(ledger)})
    contract['derived_files_sha256']={n:sha(payload[n]) for n in ('alpha-profile-3d-reference.csv','alpha-profile-2d-native.csv',
                                                            'heavyion.physics.inc','source.par','projection-ledger.json')}
    payload['source-contract.json']=encoded(contract)
    return payload,contract,ledger


def build(model,geometry,dimensional_contract,theta_deg,amplitude,epoch_s,simulation_window_s,output):
    output=Path(output).resolve()
    require(OUTPUT.resolve() in output.parents and not output.exists(), 'new output below alpha-implementation required')
    paths=[Path(model),Path(geometry),Path(dimensional_contract),A.ASTAR]
    inputs={n:p.read_bytes() for n,p in zip(INPUT_NAMES,paths)}
    request=dict(schema='dram-see-v4-alpha-projection-request-r1',energy_MeV=5,theta_deg=theta_deg,phi_deg=180,
                 amplitude=amplitude,epoch_s=epoch_s,simulation_window_s=list(simulation_window_s))
    payload,contract,ledger=derive(inputs,request)
    payload['input-origins.json']=encoded(dict(schema='dram-see-v4-alpha-2d-input-origins-r1',
        inputs={n:dict(path=str(p.resolve()),sha256=sha(inputs[n])) for n,p in zip(INPUT_NAMES,paths)}))
    manifest=dict(schema='dram-see-v4-alpha-2d-input-output-manifest-r1',
        files={n:dict(sha256=sha(v),size_bytes=len(v)) for n,v in payload.items()},
        implementation_sha256=sha(Path(__file__).read_bytes()),is_native_result=False,native_source_qualified=False)
    output.mkdir(parents=True)
    for n,raw in dict(payload,**{'input-output-manifest.json':encoded(manifest)}).items():
        with (output/n).open('xb') as stream:stream.write(raw)
    return dict(output=str(output),contract=contract,ledger=ledger,manifest=manifest)


def verify(package):
    package=Path(package); manifest=read_json(package/'input-output-manifest.json')
    require(manifest.get('schema')=='dram-see-v4-alpha-2d-input-output-manifest-r1'
            and manifest.get('implementation_sha256')==sha(Path(__file__).read_bytes())
            and manifest.get('is_native_result') is False and manifest.get('native_source_qualified') is False,
            'unknown/stale projection implementation or false native status')
    for n,row in manifest['files'].items():
        require(Path(n).name==n and sha((package/n).read_bytes())==row['sha256'] and (package/n).stat().st_size==row['size_bytes'],
                'projection input/output bytes differ: '+n)
    inputs={n:(package/n).read_bytes() for n in INPUT_NAMES};request=read_json(package/'projection-request.json')
    payload,contract,ledger=derive(inputs,request)
    origins=read_json(package/'input-origins.json')
    require(origins['schema']=='dram-see-v4-alpha-2d-input-origins-r1' and set(origins['inputs'])==set(INPUT_NAMES)
            and all(origins['inputs'][n]['sha256']==sha(raw) for n,raw in inputs.items()), 'original pure input identities differ')
    require(set(manifest['files'])==set(payload)|{'input-origins.json'}, 'projection file inventory differs')
    for n,raw in payload.items():require((package/n).read_bytes()==raw,'projection differs from complete input replay: '+n)
    return dict(contract=contract,ledger=ledger,manifest=manifest)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command')
    b=sub.add_parser('build')
    for n in ('model','geometry','dimensional-contract','output'):b.add_argument('--'+n,type=Path,required=True)
    b.add_argument('--angle',type=int,choices=(0,30),required=True);b.add_argument('--amplitude',type=float,choices=(0,.5,1),default=1)
    b.add_argument('--epoch',type=float,required=True);b.add_argument('--simulation-window',type=float,nargs=2,required=True)
    v=sub.add_parser('verify');v.add_argument('--package',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='build':result=build(args.model,args.geometry,args.dimensional_contract,args.angle,args.amplitude,args.epoch,args.simulation_window,args.output)
    elif args.command=='verify':result=verify(args.package)
    else:parser.error('build or verify required')
    print(json.dumps(dict(contract_schema=result['contract']['schema'],mapping=result['contract']['mapping'],
        charge=result['ledger']['coarse'],native_source_qualified=False),ensure_ascii=False,indent=2))
