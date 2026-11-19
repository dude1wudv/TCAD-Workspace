"""Unregistered alpha-v2 source packages and fully input-only recomputation.

This explicit entry point neither dispatches native work nor modifies v1.
Only fixed local implementations execute; packet paths select input bytes.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
RUNTIME=ROOT/'local_runtime/dram-see-v4/continuous/proton'
CONTRACT=HERE/'source-feature-contract-v2.json'
REFERENCE_SHA='82a5b47c685c9156f212787999c07d21d1aee249b22b3f783f89cf499da4e4ec'
FEATURES=('source_present','Q_Si_fC','M_x_fC_um','M_y_fC_um','M_z_fC_um','M_xx_fC_um2',
          'M_xy_fC_um2','M_xz_fC_um2','M_yy_fC_um2','M_yz_fC_um2','M_zz_fC_um2','M_t_fC_ps','M_tt_fC_ps2')


def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode()
def require(ok,message):
    if not ok:raise ValueError(message)
def read_json(path):
    return json.loads(Path(path).read_bytes(),parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite JSON: '+value)))
def ref(path):return dict(path=str(Path(path).resolve()),sha256=sha(Path(path).read_bytes()))


def module(filename,name,pinned_sha=None):
    path=HERE/filename;raw=path.read_bytes()
    require(pinned_sha is None or sha(raw)==pinned_sha,'Frozen reference implementation changed: '+filename)
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec)
    exec(compile(raw,str(path),'exec'),result.__dict__);result._loaded_source_sha256=sha(raw)
    return result


R=module('source_reference.py','_continuous_alpha_v2_reference',REFERENCE_SHA)
A=module('alpha_source_v2.py','_continuous_alpha_v2_source')
M=module('alpha_moments_v2.py','_continuous_alpha_v2_moments')
LOADED_SELF_SHA=sha(Path(__file__).read_bytes())


def contract_bytes(packet=None):
    raw=CONTRACT.read_bytes();value=json.loads(raw)
    require(value['schema']=='continuous-particle-source-feature-contract-v2' and value['version_id']=='v2-alpha-surface'
            and value['feature_order']==list(FEATURES) and value['numerics']['normalized_absolute']==R.ABS_TOL
            and value['numerics']['relative']==R.REL_TOL and value['numerics']['refinement_factor']==.25
            and value['numerics']['profile_spacing_um']==.01 and value['numerics']['profile_refinement_factor']==.5,
            'V2 numerical/feature contract does not match this implementation')
    if packet is not None:
        require(packet['feature_contract_sha256']==sha(raw) and packet['feature_contract']==value,'V2 feature contract changed')
    return raw


def stable_implementations():
    require(sha(Path(__file__).read_bytes())==LOADED_SELF_SHA and
            all(sha(Path(item.__file__).read_bytes())==item._loaded_source_sha256 for item in (R,A,M)),
            'V2 implementation changed after loading; reload before deriving features')
    return {name:ref(HERE/name) for name in ('source_features_v2.py','alpha_source_v2.py','alpha_moments_v2.py',
                                            'source_reference.py','ALPHA-V2-ASSUMPTIONS.md')}


def holdout_notice(model,request):
    gate=model['geometry']['gate_top_depth_nm'];energy=request['energy_MeV'];angle=request['theta_deg']
    protected=(gate==90 or energy==7 or (gate,energy,angle) in ((70,5,30),(80,3,30)))
    return dict(data_design_registered=False,permitted_use='MATHEMATICAL_INPUT_PREPARATION_ONLY',
                original_final_axes_or_condition=protected,
                source_input_does_not_authorize_fit_or_native=True,
                sn_axis_requires_separate_design_registration=True)


def derived_source_payload(model,geometry,request,table_raw):
    path=A.validate_inputs(model,geometry,request,R);stopping=A.Stopping(table_raw)
    rows,ledger=A.profile(stopping,request['energy_MeV'],path['length_um'])
    profile=A.profile_bytes(rows);physics,parameters=A.render(rows,request,path)
    window=[request['epoch_s']-8*request['sigma_ps']*1e-12,request['epoch_s']+8*request['sigma_ps']*1e-12]
    source=dict(schema='continuous-alpha-source-contract-v2',particle='alpha',source_amplitude=1.,
        source_status='PRESCRIBED_POSITIVE_SOURCE',surface_energy_MeV=request['energy_MeV'],epoch_s=request['epoch_s'],
        path=path,energy=ledger,astar_sha256=A.ASTAR_SHA256,
        stopping_definition='rho*1e-4*(Se+Sn) for total CSDA loss; charge only rho*1e-4*Se; no table extrapolation',
        conversion=dict(density_g_cm3=2.33,eV_per_pair=3.6,fC_per_MeV_electronic=A.FC_PER_MEV),
        source_files_sha256={'alpha-profile.csv':sha(profile),'heavyion.physics.inc':sha(physics),'source.par':sha(parameters)},
        temporal=dict(model='Common prescribed epoch Gaussian, no along-track TOF',sigma_s=request['sigma_ps']*1e-12,
                      all_time_relative_mean_ps=0.,all_time_relative_second_ps2=request['sigma_ps']**2),
        required_source_window_s=window,unrenormalized_window_mass=1-math.erfc(8/math.sqrt(2)),
        unrenormalized_outside_window_mass=math.erfc(8/math.sqrt(2)),
        required_native_checks=dict(accepted_clock='Real BE only; PLT/TDR/accepted-step bijection and full frames required',
            source_max_step_s=.04e-12,refined_source_max_step_s=.02e-12,
            field='Integrate actual HeavyIonGeneration over finite Si; compare charge, spatial moments and all source intervals',
            endpoint_semantics='Native HeavyIon must demonstrate the same finite perpendicular axial planes',
            electrical='Matched A0, same mesh/physics, both stored bits and actual solver exits required'),
        non_silicon_tails='Mask-only losses, no oxide traversal or energy-loss model for Gaussian tails',
        source_normalization='No finite-box, finite-Si or time-tail renormalization',
        data_design=holdout_notice(model,request),
        actual_clock=None,is_tcad_result=False,native_source_qualified=False,pmi_r12_fixed=False)
    payload={'alpha-profile.csv':profile,'heavyion.physics.inc':physics,'source.par':parameters,
             'source-contract.json':encoded(source)}
    return rows,path,ledger,source,payload


def comparison(coarse,fine,allocated):
    checks=[]
    for key,a,b in zip(FEATURES[1:],coarse,fine):
        gate=100*R.ABS_TOL*max(1.,allocated)+10*R.REL_TOL*abs(b)
        checks.append(dict(feature=key,difference=abs(a-b),gate=gate,passed=abs(a-b)<=gate))
    require(all(item['passed'] for item in checks),'V2 input-only moment resolution comparison did not converge')
    return dict(checks=checks,passed=True,meaning='Numerical repeatability, not a rigorous error bound or native qualification')


def interpretation(values,r0):
    q=values[0];mean=[v/q for v in values[1:4]];pairs=[(0,0),(0,1),(0,2),(1,1),(1,2),(2,2)]
    return dict(centroid_relative_um=mean,centroid_um=[a+b for a,b in zip(mean,r0)],
        covariance_um2=[v/q-mean[i]*mean[j] for v,(i,j) in zip(values[4:10],pairs)],
        covariance_order=['xx','xy','xz','yy','yz','zz'],time_centroid_ps=values[10]/q,
        time_variance_ps2=values[11]/q-(values[10]/q)**2)


def alpha_packet(source_dir,*,clock=None):
    require(clock is None,'Pre-TCAD v2 source features cannot consume an actual clock')
    implementations=stable_implementations();source_dir=Path(source_dir).resolve()
    model=read_json(source_dir/'model.proposed.json');geometry=read_json(source_dir/'geometry-contract.json')
    request=read_json(source_dir/'source-request.json');table=(source_dir/'alpha-astar-silicon.csv').read_bytes()
    origins=read_json(source_dir/'source-origins.json')
    require(origins['schema']=='continuous-alpha-v2-input-origins-v1' and
            set(origins['inputs'])=={'model.proposed.json','geometry-contract.json','alpha-astar-silicon.csv'},'Invalid original input binding')
    for name,item in origins['inputs'].items():
        require(set(item)=={'path','sha256'} and isinstance(item['path'],str) and
                sha((source_dir/name).read_bytes())==item['sha256'],'Original input snapshot hash mismatch: '+name)
    rows,path,ledger,source,payload=derived_source_payload(model,geometry,request,table)
    require(all((source_dir/name).read_bytes()==raw for name,raw in payload.items()),
            'Alpha v2 prescribed source files differ from original ASTAR/input-only recomputation')
    coarse=M.source_moments(rows,geometry,request,path,R,clock=None)
    refined=M.source_moments(rows,geometry,request,path,R,clock=None,abs_tol=R.ABS_TOL/4,rel_tol=R.REL_TOL/4)
    half_rows,half_ledger=A.profile(A.Stopping(table),request['energy_MeV'],path['length_um'],.005)
    half=M.source_moments(half_rows,geometry,request,path,R,clock=None,abs_tol=R.ABS_TOL/4,rel_tol=R.REL_TOL/4)
    values=coarse['raw_feature_moments'];allocated=ledger['tabulated_line_charge_fC']
    require(len(values)==12 and all(math.isfinite(v) for v in values) and values[0]>0,'Missing positive alpha v2 moments')
    names=['model.proposed.json','geometry-contract.json','source-request.json','alpha-astar-silicon.csv','source-origins.json',*payload]
    inputs={name:ref(source_dir/name) for name in names};input_hashes={name:value['sha256'] for name,value in sorted(inputs.items())}
    contract_raw=contract_bytes();contract=json.loads(contract_raw)
    stable_implementations()
    return dict(schema='continuous-particle-source-features-v2',version_id='v2-alpha-surface',particle='alpha',
        source_status='PRESCRIBED_POSITIVE_SOURCE',source_features=dict(zip(FEATURES,[1,*values])),
        r0_um=request['position_um'],epoch_s=request['epoch_s'],
        source_conditions=dict(gate_top_depth_nm=model['geometry']['gate_top_depth_nm'],
            sn_junction_depth_nm=model['doping']['sn_junction_depth_nm'],energy_MeV=request['energy_MeV'],angle_deg=request['theta_deg']),
        feature_contract=contract,feature_contract_sha256=sha(contract_raw),feature_contract_ref=ref(CONTRACT),
        inputs=inputs,source_package=dict(path=str(source_dir),kind='prescribed_source_input_subset',files_sha256=input_hashes,
                                         sha256=sha(encoded(input_hashes))),
        implementations=implementations,source_definition=source,allocated_all_space_all_time_fC=allocated,
        finite_domain_ledger=coarse,interpretation=interpretation(values,request['position_um']),
        numerical_refinement=dict(quadrature=comparison(values,refined['raw_feature_moments'],allocated),
            profile=comparison(refined['raw_feature_moments'],half['raw_feature_moments'],allocated),
            profile_spacing_um=.01,refined_profile_spacing_um=.005,refined_profile_energy=half_ledger,
            quadrature_coarse=dict(absolute=R.ABS_TOL,relative=R.REL_TOL),
            quadrature_refined=dict(absolute=R.ABS_TOL/4,relative=R.REL_TOL/4)),
        data_design=holdout_notice(model,request),clock=None,uses_tcad_outputs=False,is_tcad_result=False,
        native_source_qualified=False,pmi_r12_fixed=False,prediction_scope=contract['scope'])


def build_alpha(model_path,geometry_path,energy_MeV,angle_deg,output_dir):
    """Create a new complete input-only bundle, including source-features.json."""
    output_dir=Path(output_dir).resolve()
    require(output_dir.is_relative_to(RUNTIME.resolve()),'V2 output must stay in continuous/proton runtime')
    require(not output_dir.exists(),'V2 input packages are immutable; output directory already exists')
    snapshots={'model.proposed.json':Path(model_path).read_bytes(),'geometry-contract.json':Path(geometry_path).read_bytes(),
               'alpha-astar-silicon.csv':A.ASTAR.read_bytes()}
    request=A.make_request(energy_MeV,angle_deg)
    _,_,_,_,payload=derived_source_payload(json.loads(snapshots['model.proposed.json']),json.loads(snapshots['geometry-contract.json']),
                                         request,snapshots['alpha-astar-silicon.csv'])
    origins=dict(schema='continuous-alpha-v2-input-origins-v1',inputs={
        name:ref(path) for name,path in [('model.proposed.json',model_path),('geometry-contract.json',geometry_path),
                                        ('alpha-astar-silicon.csv',A.ASTAR)]})
    payload={**snapshots,'source-request.json':encoded(request),'source-origins.json':encoded(origins),**payload}
    output_dir.mkdir(parents=True)
    for name,raw in payload.items():
        with (output_dir/name).open('xb') as stream:stream.write(raw)
    # Failed mathematical validation leaves the truthful incomplete input
    # package in place. It never writes a success/qualification placeholder.
    packet=alpha_packet(output_dir)
    for name,raw in [('source-feature-contract.json',contract_bytes(packet)),('source-features.json',encoded(packet))]:
        with (output_dir/name).open('xb') as stream:stream.write(raw)
    return packet


def verify(packet_path,input_files=None):
    packet=read_json(packet_path)
    require(packet['schema']=='continuous-particle-source-features-v2' and packet['version_id']=='v2-alpha-surface'
            and packet['particle']=='alpha','Unknown independent v2 source version')
    contract_bytes(packet)
    actual=alpha_packet(packet['source_package']['path'],clock=None)
    require(actual==packet,'Alpha v2 packet differs from complete original-input recomputation')
    require((Path(packet_path).parent/'source-feature-contract.json').read_bytes()==contract_bytes(packet),'Frozen v2 contract bytes differ')
    if input_files is not None:
        require(isinstance(input_files,dict),'Current prescribed input subset must be a bytes mapping')
        for name,item in actual['inputs'].items():
            if name in input_files:
                require(isinstance(input_files[name],bytes) and sha(input_files[name])==item['sha256'],
                        'Current input subset differs from v2 source package: '+name)
    return actual


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('alpha');q.add_argument('--model',type=Path,required=True);q.add_argument('--geometry',type=Path,required=True)
    q.add_argument('--energy',type=int,required=True);q.add_argument('--angle',type=int,required=True);q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('verify');q.add_argument('--packet',type=Path,required=True)
    args=p.parse_args()
    result=verify(args.packet) if args.command=='verify' else build_alpha(args.model,args.geometry,args.energy,args.angle,args.output)
    print(json.dumps(dict(version_id=result['version_id'],source_features=result['source_features'],
                         source_conditions=result['source_conditions'],native_source_qualified=False),allow_nan=False))
