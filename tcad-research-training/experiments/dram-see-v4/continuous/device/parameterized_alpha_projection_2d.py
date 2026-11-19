"""Development gate70/80 alpha projection with physical E3/E5 ASTAR profiles.

Pure input mathematics only. The fixed 16d2 integral/render core is reused with
an explicitly checked new context, never patched or executed from package paths.
No native qualification, new operation choice, holdout, scheduler or training.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUTPUT = ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/parameterized-alpha-implementation-r1'
CORE_SHA = '16d2fe5e7a182d2ed11e17c197493dac822482ee1c6c6c0da0336a9c86a81f56'
SCHEMA = 'dram-see-v4-parameterized-alpha-projection-2d-r1'
REQUEST_SCHEMA = 'dram-see-v4-parameterized-alpha-projection-request-r1'
MANIFEST_SCHEMA = 'dram-see-v4-parameterized-alpha-2d-input-output-manifest-r1'

def require(ok, message):
    if not ok: raise ValueError('Parameterized alpha projection: '+message)

def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode('utf-8')
def read_json(path): return json.loads(Path(path).read_bytes())

core_path = HERE/'alpha_projection_2d.py'
core_raw = core_path.read_bytes()
require(sha(core_raw) == CORE_SHA and not core_path.is_symlink(), 'fixed 16d2 core changed')
spec = importlib.util.spec_from_file_location('_parameterized_alpha_fixed_core', str(core_path))
C = importlib.util.module_from_spec(spec)
exec(compile(core_raw, str(core_path), 'exec'), C.__dict__)
A, M, K, R = C.A, C.M, C.K, C.R
DEPENDENCIES = dict(C.DEPENDENCIES)
INPUT_NAMES = C.INPUT_NAMES
WIDTH_UM, REF_UM, W_UM, SIGMA_S = C.WIDTH_UM, C.REF_UM, C.W_UM, C.SIGMA_S
projected_integral, render = C.projected_integral, C.render
generation3d, generation2d = C.generation3d, C.generation2d

def mapping(amplitude, epoch_s):
    """The new version never exposes the legacy core's default epoch."""
    return C.mapping(amplitude, epoch_s)

def energy_provenance(ctx):
    """Trajectory energy and five charge destinations are distinct ledgers."""
    return dict(schema='dram-see-v4-alpha-electronic-energy-provenance-r1',
        energy_definition='kinetic energy at the Si surface entry; no pre-overlayer energy inference',
        incident_energy_MeV=ctx['request']['energy_MeV'],
        stopping_table_sha256=A.ASTAR_SHA256,stopping_source_sha256=DEPENDENCIES['alpha'][1],
        stopping_table_project_path='experiments/dram-see-v4/course-plan-r13/evidence/alpha-astar-silicon.csv',
        tabulated_unit='MeV cm^2/g',silicon_density_g_cm3=2.33,cm_per_um=1e-4,
        mass_stopping_to_MeV_per_um=A.RHO_FACTOR,
        electronic_and_nuclear_interpolation='Original piecewise linear stopping vs actual remaining energy; no extrapolation',
        energy_ode='dE/ds = -2.33e-4 * (S_e(E) + S_n(E)); s in um',
        path_length_um=ctx['path']['length_um'],
        eV_per_pair=3.6,elementary_charge_C=1.602176634e-19,
        electronic_fC_per_MeV=A.FC_PER_MEV,
        charge_definition='Only electronic energy loss / 3.6eV times elementary charge; nuclear loss is not converted to charge',
        trajectory_energy_ledger=ctx['energy'],
        five_charge_destinations='projection-ledger.json: original unbounded transverse/all-time line charge partition',
        kinetic_remainder_is_not_outside_domain_source_charge=True,
        profile_energy_is_not_a_relabelled_or_scaled_E5_profile=True,
        geometry_gate_top_depth_nm=ctx['request']['gate_top_depth_nm'],
        is_native_measurement=False,native_source_qualified=False)

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
    require(type(mg['gate_top_depth_nm']) is int and mg['gate_top_depth_nm'] in (70,80) and d['sn_junction_depth_nm'] == 87 and mg['active_width_nm'] == 20,
            'only development gate70/80, SN87 and width20; final geometry excluded')
    require(alpha['position_nm'] == [-52,0,0] and alpha['radial_Gaussian_w_nm'] == 50
            and alpha['temporal_sigma_ps'] == .2 and alpha['eV_per_pair'] == 3.6, 'original alpha kernel differs')
    tr = g['outer_trench']; gate = g['gate_void']
    require(tr['construction'] == 'rectangle/cuboid union circle/cylinder' and tr['x_half_width_um'] == tr['radius_um'] == .012
            and tr['round_center_z_um'] == .142 and tr['top_um'] == 0. and tr['bottom_um'] == .154
            and tr['y_half_width_um'] >= .01 and gate['top_um'] == mg['gate_top_depth_nm']/1000 and gate['bottom_um'] == .15,
            'actual central Si boundary differs')
    expected_asn = d['sn_junction_depth_nm']/1000/math.sqrt(math.log(d['peak_donor']/d['uniform_acceptor']))
    require(abs(g['doping']['a_sn_um']-expected_asn) <= 1e-14 and g['doping']['peak_cm3'] == d['peak_donor']
            and g['doping']['acceptor_cm3'] == d['uniform_acceptor'], 'D2 model/doping does not match source geometry')
    response = dict(kind='bcat_center_section', bounds_xz_um=[-1.,0.,1.,1.],
        outer_trench=dict(radius_um=tr['radius_um'], center_z_um=tr['round_center_z_um'], top_um=tr['top_um']))
    require(abs(2-(2*.012*.142+math.pi*.012**2/2)-g['measures']['silicon']) <= 1e-11,
            'D2 Si area is not the declared material mask')
    require(set(request) == {'schema','gate_top_depth_nm','energy_MeV','theta_deg','phi_deg','amplitude','epoch_s','simulation_window_s'}
            and request['schema'] == REQUEST_SCHEMA
            and type(request['gate_top_depth_nm']) is int and request['gate_top_depth_nm'] == mg['gate_top_depth_nm']
            and type(request['energy_MeV']) is int and request['energy_MeV'] in (3,5)
            and type(request['amplitude']) in (int,float) and request['amplitude'] == 1
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
    rows, energy = A.profile(A.Stopping(inputs['alpha-astar-silicon.csv']), request['energy_MeV'], path['length_um'])
    return dict(rows=rows, path=path, energy=energy, factors=factors, response=response,
        mask=K.ResponseMask(response), request=request, source_window_s=source_window, width=width)

def derive(inputs,request):
    ctx=_context(inputs,request); coarse=projected_integral(ctx); fine=projected_integral(ctx,True)
    differences={n:abs(v-fine[n]) for n,v in coarse.items() if type(v) in (int,float)}
    require(all(differences[n]<=coarse['offline_charge_gate_fC'] for n in differences if n.endswith('_fC')),
            'new projected charge integration did not converge')
    include,parameters=render(ctx)
    profile3=A.profile_bytes(ctx['rows'])
    rows2=[dict(r,LET_2d_pC_um=r['electronic_pC_um']*ctx['factors']['applied_LET_multiplier']) for r in ctx['rows']]
    profile2=A.profile_bytes(rows2)
    ledger=dict(schema='dram-see-v4-parameterized-alpha-2d-charge-ledger-r1',energy=ctx['energy'],coarse=coarse,refined=fine,
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
        core_projection_sha256=CORE_SHA,energy_source_provenance_sha256=sha(encoded(energy_provenance(ctx))),
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
        unsupported=['dy not zero or y-dependent axial geometry','non-Gaussian radial kernel','gate90 or energies outside development3/5MeV; no holdout access',
            'claiming projected 2D response equals 3D response'],
        PMI_required_by_this_separable_formula=False,PMI_may_be_needed_if_native_field_cannot_match=True,
        native_source_qualified=False,pmi_r12_fixed=False,is_tcad_result=False)
    payload=dict(inputs)
    payload.update({'projection-request.json':encoded(request),'alpha-profile-3d-reference.csv':profile3,
        'alpha-profile-2d-native.csv':profile2,'heavyion.physics.inc':include,'source.par':parameters,
        'projection-ledger.json':encoded(ledger),'energy-source-provenance.json':encoded(energy_provenance(ctx))})
    contract['derived_files_sha256']={n:sha(payload[n]) for n in ('alpha-profile-3d-reference.csv','alpha-profile-2d-native.csv',
                                                            'heavyion.physics.inc','source.par','projection-ledger.json','energy-source-provenance.json')}
    payload['source-contract.json']=encoded(contract)
    return payload,contract,ledger

def build(model,geometry,dimensional_contract,energy_MeV,theta_deg,epoch_s,simulation_window_s,output):
    output=Path(output).resolve()
    require(OUTPUT.resolve() in output.parents and not output.exists(), 'new output below parameterized-alpha-implementation-r1 required')
    paths=[Path(model),Path(geometry),Path(dimensional_contract),A.ASTAR]
    inputs={n:p.read_bytes() for n,p in zip(INPUT_NAMES,paths)}
    gate=json.loads(inputs['model.proposed.json'])['geometry']['gate_top_depth_nm']
    request=dict(schema=REQUEST_SCHEMA,gate_top_depth_nm=gate,energy_MeV=energy_MeV,
        theta_deg=theta_deg,phi_deg=180,amplitude=1.,epoch_s=epoch_s,simulation_window_s=list(simulation_window_s))
    payload,contract,ledger=derive(inputs,request)
    payload['input-origins.json']=encoded(dict(schema='dram-see-v4-parameterized-alpha-2d-input-origins-r1',
        inputs={n:dict(path=str(p.resolve()),sha256=sha(inputs[n])) for n,p in zip(INPUT_NAMES,paths)}))
    manifest=dict(schema=MANIFEST_SCHEMA,
        files={n:dict(sha256=sha(v),size_bytes=len(v)) for n,v in payload.items()},
        implementation_sha256=sha(Path(__file__).read_bytes()),core_projection_sha256=CORE_SHA,
        is_native_result=False,native_source_qualified=False)
    output.mkdir(parents=True)
    for n,raw in dict(payload,**{'input-output-manifest.json':encoded(manifest)}).items():
        with (output/n).open('xb') as stream:stream.write(raw)
    return dict(output=str(output),contract=contract,ledger=ledger,manifest=manifest)


def verify(package):
    package=Path(package); manifest=read_json(package/'input-output-manifest.json')
    require(manifest.get('schema')==MANIFEST_SCHEMA
        and manifest.get('implementation_sha256')==sha(Path(__file__).read_bytes())
        and manifest.get('core_projection_sha256')==CORE_SHA
        and manifest.get('is_native_result') is False and manifest.get('native_source_qualified') is False,
        'unknown/stale projection implementation or false native status')
    for n,row in manifest['files'].items():
        require(Path(n).name==n and not (package/n).is_symlink()
            and row==dict(sha256=sha((package/n).read_bytes()),size_bytes=(package/n).stat().st_size), 'projection bytes differ: '+n)
    inputs={n:(package/n).read_bytes() for n in INPUT_NAMES};request=read_json(package/'projection-request.json')
    payload,contract,ledger=derive(inputs,request)
    origins=read_json(package/'input-origins.json')
    require(origins['schema']=='dram-see-v4-parameterized-alpha-2d-input-origins-r1'
        and set(origins['inputs'])==set(INPUT_NAMES)
        and all(origins['inputs'][n]['sha256']==sha(raw) for n,raw in inputs.items()), 'pure input identities differ')
    require(set(manifest['files'])==set(payload)|{'input-origins.json'}, 'projection inventory differs')
    for n,raw in payload.items(): require((package/n).read_bytes()==raw,'projection differs from complete replay: '+n)
    return dict(contract=contract,ledger=ledger,manifest=manifest)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command')
    b=sub.add_parser('build')
    for n in ('model','geometry','dimensional-contract','output'):b.add_argument('--'+n,type=Path,required=True)
    b.add_argument('--energy',type=int,choices=(3,5),required=True)
    b.add_argument('--angle',type=int,choices=(0,30),required=True)
    b.add_argument('--epoch',type=float,required=True);b.add_argument('--simulation-window',type=float,nargs=2,required=True)
    v=sub.add_parser('verify');v.add_argument('--package',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='build':result=build(args.model,args.geometry,args.dimensional_contract,args.energy,args.angle,args.epoch,args.simulation_window,args.output)
    elif args.command=='verify':result=verify(args.package)
    else:parser.error('build or verify required')
    print(json.dumps(dict(contract_schema=result['contract']['schema'],request=result['contract']['request'],
        energy=result['ledger']['energy'],charge=result['ledger']['coarse'],native_source_qualified=False),ensure_ascii=False,indent=2))
