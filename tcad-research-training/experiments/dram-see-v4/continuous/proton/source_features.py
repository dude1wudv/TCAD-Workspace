"""Immutable source-only features, before TCAD. All reads use explicit input files.

CLI output is not native qualification. Recompute validates dependency hashes
and the input source representation; it never trusts a no-TCAD boolean.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
CONTRACT=HERE/'source-feature-contract.json'
FEATURES=('source_present','Q_Si_fC','M_x_fC_um','M_y_fC_um','M_z_fC_um','M_xx_fC_um2',
          'M_xy_fC_um2','M_xz_fC_um2','M_yy_fC_um2','M_yz_fC_um2','M_zz_fC_um2','M_t_fC_ps','M_tt_fC_ps2')


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec)
    raw=Path(path).read_bytes();exec(compile(raw,str(path),'exec'),result.__dict__)
    result._loaded_source_sha256=hashlib.sha256(raw).hexdigest()
    return result


R=module(HERE/'source_reference.py','_continuous_feature_reference')
M=module(HERE/'source_feature_math.py','_continuous_feature_math')
require=R.require
read_json=R.read_json


def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode()
def ref(path):return dict(path=str(Path(path).resolve()),sha256=R.digest(path))
LOADED_SELF_SHA=sha(Path(__file__).read_bytes())


def contract_bytes(packet=None):
    raw=CONTRACT.read_bytes();contract=json.loads(raw)
    require(contract['feature_order']==list(FEATURES) and contract['numerics']['normalized_absolute']==R.ABS_TOL
            and contract['numerics']['relative']==R.REL_TOL and contract['numerics']['refinement_factor']==.25,
            'Feature schema/tolerances differ from the implemented numerical contract')
    if packet is not None:
        require(packet['feature_contract_sha256']==sha(raw) and packet['feature_contract']==json.loads(raw),
                'Feature contract changed')
    return raw


def alpha_reference():
    return module(HERE.parent/'device/alpha_source.py','_continuous_feature_alpha_reference')


@contextmanager
def proton_modules():
    """Legacy absolute imports get exact private dependencies, then are restored."""
    saved={name:sys.modules.get(name) for name in ('prepare','couple','source_reference')}
    try:
        prepare=module(HERE/'prepare.py','_continuous_feature_prepare');sys.modules['prepare']=prepare
        couple=module(HERE/'couple.py','_continuous_feature_couple');sys.modules['couple']=couple
        sys.modules['source_reference']=R
        bundle=module(HERE/'source_bundle.py','_continuous_feature_bundle')
        yield prepare,couple,bundle
    finally:
        for name,prior in saved.items():
            if prior is None:sys.modules.pop(name,None)
            else:sys.modules[name]=prior


def geometry_s2(geometry,model):
    g=geometry.get('geometry',geometry);mg=model['geometry']
    require(mg['gate_top_depth_nm']==80 and mg['active_width_nm']==20 and mg['metal_bottom_z_nm']==150
            and model['doping']['sn_junction_depth_nm']==87,'Feature input is not the current S2 model')
    require(g['gate_void']['top_um']==.08 and g['gate_void']['bottom_um']==.15,'Feature geometry is not current S2')
    mask=R.SiliconMask(geometry)
    require(mask.domain==[-1.,-.25,0.,1.,.25,1.] and mask.r==.012 and mask.center==.142 and mask.top==0.
            and math.isclose(mask.hy,.06,abs_tol=1e-15) and mask.sti_z==[0.,.2]
            and len(mask.sti_y)==2 and all(abs(x-y)<1e-15 for a,b in zip(mask.sti_y,[[-.06,-.01],[.01,.06]]) for x,y in zip(a,b)),
            'Unsupported finite-Si geometry')
    require(abs(mask.volume()-g['measures']['silicon'])<=1e-11,'Input Si volume disagrees with independent mask')
    return g


def refinement(coarse,fine,allocated,contract):
    settings=contract['numerics'];checks=[]
    for key,a,b in zip(contract['feature_order'][1:],coarse,fine):
        gate=100*settings['normalized_absolute']*max(1.,allocated)+10*settings['relative']*abs(b)
        checks.append(dict(feature=key,difference=abs(a-b),gate=gate,passed=abs(a-b)<=gate))
    require(all(item['passed'] for item in checks),'Independent source-feature quadrature did not converge')
    return dict(checks=checks,passed=True,coarse=dict(absolute=settings['normalized_absolute'],relative=settings['relative']),
                refined=dict(absolute=settings['normalized_absolute']*.25,relative=settings['relative']*.25),
                meaning=settings['interpretation'])


def interpretation(values,r0):
    q=values[0]
    if q==0:return dict(centroid_relative_um=None,centroid_um=None,covariance_um2=None,time_centroid_ps=None,time_variance_ps2=None)
    mean=[v/q for v in values[1:4]];pairs=[(0,0),(0,1),(0,2),(1,1),(1,2),(2,2)]
    covariance=[v/q-mean[i]*mean[j] for v,(i,j) in zip(values[4:10],pairs)]
    return dict(centroid_relative_um=mean,centroid_um=[a+b for a,b in zip(mean,r0)],covariance_um2=covariance,
                covariance_order=['xx','xy','xz','yy','yz','zz'],time_centroid_ps=values[10]/q,
                time_variance_ps2=values[11]/q-(values[10]/q)**2)


def finish(particle,source_dir,inputs,values,fine,present,allocated,r0,epoch,extra,conditions,implementations):
    require(R.digest(__file__)==LOADED_SELF_SHA and all(R.digest(item.__file__)==item._loaded_source_sha256 for item in (R,M)),
            'Source-feature implementation changed after loading; reload before deriving features')
    raw=contract_bytes();contract=json.loads(raw)
    require(len(values)==12 and all(math.isfinite(v) for v in values),'Incomplete/nonfinite source features')
    require(type(present) is int and present in (0,1),'Invalid source-presence indicator')
    require(values[0]>0 if present else all(v==0 for v in values),'Source zero/positive semantics conflict')
    numerical=refinement(values,fine,allocated,contract)
    input_hashes={name:value['sha256'] for name,value in sorted(inputs.items())}
    return dict(schema='continuous-particle-source-features-v1',particle=particle,
        source_status='PRESCRIBED_POSITIVE_SOURCE' if present else 'PRESCRIBED_STRUCTURAL_ZERO',
        source_features=dict(zip(contract['feature_order'],[present,*values])),r0_um=r0,epoch_s=epoch,
        feature_contract=contract,feature_contract_sha256=sha(raw),feature_contract_ref=ref(CONTRACT),
        inputs=inputs,source_package=dict(path=str(Path(source_dir).resolve()),kind='prescribed_source_input_subset',
            files_sha256=input_hashes,sha256=sha(encoded(input_hashes))),
        implementations={**{name:ref(HERE/name) for name in ('source_features.py','source_feature_math.py','source_reference.py')},**implementations},
        source_definition=extra,source_conditions=conditions,allocated_all_space_all_time_fC=allocated,
        numerical_refinement=numerical,interpretation=interpretation(values,r0),
        clock=None,uses_tcad_outputs=False,is_tcad_result=False,native_source_qualified=False,pmi_r12_fixed=False,
        prediction_scope=contract['scope'])


def alpha_packet(source_dir):
    source_dir=Path(source_dir).resolve();A=alpha_reference()
    names=['model.proposed.json','geometry-contract.json','alpha-profile.csv']
    model=read_json(source_dir/names[0]);geometry=read_json(source_dir/names[1]);profile=source_dir/names[2]
    A.validate_model(model);geometry_s2(geometry,model)
    require(R.digest(profile)==R.digest(A.PROFILE),'Alpha input is not the original ASTAR table')
    rows=A.load_profile(profile);matches=[]
    for case in ('Aalpha','Z','H','split'):
        prefix='' if case=='Aalpha' else case+'.';physical=prefix+'heavyion.physics.inc';parameters=prefix+'source.par'
        if (source_dir/physical).is_file() and (source_dir/parameters).is_file():
            expected=A.render_source(rows,case)
            if (source_dir/physical).read_bytes()==expected[0].encode() and (source_dir/parameters).read_bytes()==expected[1].encode():
                matches.append((case,physical,parameters))
    require(len(matches)==1,'Alpha source input must identify exactly one supported original source pair')
    case,physical,parameters=matches[0];names += [physical,parameters]
    inputs={name:ref(source_dir/name) for name in names}
    r0=[float(Decimal(str(v))/1000) for v in model['alpha']['position_nm']]
    epoch=float(Decimal(str(model['alpha']['time_center_ns']))/Decimal('1e9'))
    amplitude=A.source_spec(case)['amplitude'];present=int(amplitude>0)
    allocated=amplitude*math.fsum((b['path_um']-a['path_um'])*(a['electronic_pC_um']+b['electronic_pC_um'])*500
                                for a,b in zip(rows,rows[1:]))
    args=(rows,geometry,r0,epoch,R,A)
    values=M.alpha_moments(*args,amplitude=amplitude,clock=None)
    fine=M.alpha_moments(*args,amplitude=amplitude,clock=None,abs_tol=R.ABS_TOL/4,rel_tol=R.REL_TOL/4)
    return finish('alpha',source_dir,inputs,values,fine,present,allocated,r0,epoch,
        dict(kernel='ASTAR_longitudinal_LUT_transverse_Gaussian',case=case,amplitude=amplitude,
             spatial_width_um=.05,temporal_sigma_ps=.2,longitudinal_convolution=False),
        dict(gate_top_depth_nm=model['geometry']['gate_top_depth_nm'],sn_junction_depth_nm=model['doping']['sn_junction_depth_nm'],
             energy_MeV=model['alpha']['first_energy_MeV'],angle_deg=model['alpha']['angle_deg_from_positive_z']),
        {'alpha_source.py':ref(A.__file__),'alpha-temporal-oracle.py':ref(A._CLOCK_PATH)})


def proton_packet(source_dir):
    source_dir=Path(source_dir).resolve();source=read_json(source_dir/'source-contract.json')
    bundle=read_json(source_dir/'source-bundle.json');binding=bundle['binding']
    require(bundle['schema']=='continuous-proton-source-bundle-v1','Unknown original event source bundle')
    require(source['epoch_s']==binding['source_time_s'] and bundle['source_contract_sha256']==R.digest(source_dir/'source-contract.json'),
            'Event bundle/source epoch or source-contract identity differs')
    operation=Path(binding['operation']['path']).parent;build=Path(binding['build_operation']['path']).parent
    with proton_modules() as (P,C,B):
        require(B.audit_transport_event(operation,binding['transport_event_id'],build)==binding,'Original complete-event source binding changed')
        payload=C.package_payload(operation,binding['transport_event_id'],source['epoch_s'],
            source['approximation']['let_node_width_fraction'],source['approximation']['max_segment_time_sigma_fraction'])
        require(all((source_dir/name).read_bytes()==raw for name,raw in payload.items()),'Prescribed source differs from original full Geant4 event')
        require(all(bundle['source_payload_sha256'].get(name)==sha(raw) for name,raw in payload.items()),'Original event source payload identity differs')
    names=['source-bundle.json','geometry-contract.json',*payload]
    inputs={name:ref(source_dir/name) for name in names}
    for name,key in [('request.json','request'),('model-input.json','model_input')]:
        inputs[name]=dict(binding[key]);require(R.digest(inputs[name]['path'])==inputs[name]['sha256'],'Original prescribed input identity changed')
    request=read_json(inputs['request.json']['path']);model=read_json(inputs['model-input.json']['path'])
    geometry=read_json(source_dir/'geometry-contract.json')
    require(R.digest(source_dir/'geometry-contract.json')==binding['geometry_contract']['sha256'],'Source input geometry changed')
    geometry_s2(geometry,model);rows=R.load_sources(source_dir/'sources.dat')
    r0=request['target_um'];epoch=source['epoch_s'];allocated=math.fsum(row[8] for row in rows)
    values=M.proton_moments(rows,geometry,r0,epoch,R,clock=None)
    fine=M.proton_moments(rows,geometry,r0,epoch,R,clock=None,abs_tol=R.ABS_TOL/4,rel_tol=R.REL_TOL/4)
    return finish('proton',source_dir,inputs,values,fine,int(bool(rows)),allocated,r0,epoch,
        dict(kernel='original_Gaussian3D_segment_convolution',spatial_width_um=.03,temporal_sigma_ps=2.,
            complete_event_source_rows=len(rows),seed=request['seed'],transport_event_id=binding['transport_event_id'],
            all_late_rows_retained=True),
        dict(gate_top_depth_nm=model['geometry']['gate_top_depth_nm'],sn_junction_depth_nm=model['doping']['sn_junction_depth_nm'],
             energy_MeV=request['energy_MeV'],angle_deg=request['theta_deg'],seed=request['seed'],transport_event_id=binding['transport_event_id']),
        {name:ref(HERE/name) for name in ('prepare.py','couple.py','source_bundle.py')})


def build_alpha(source_dir,output):
    packet=alpha_packet(source_dir);R.write_new(output,packet);return packet


def build_proton(source_dir,output):
    packet=proton_packet(source_dir);R.write_new(output,packet);return packet


def verify(packet_path,input_files=None):
    packet=read_json(packet_path)
    require(packet['schema']=='continuous-particle-source-features-v1','Unknown source-feature packet')
    contract_bytes(packet)
    compute={'alpha':alpha_packet,'proton':proton_packet}
    require(packet['particle'] in compute,'Unsupported feature particle')
    # Recompute first from a fixed filename allowlist, never dereference arbitrary
    # packet-supplied dependency paths which could point at TCAD output fields.
    actual=compute[packet['particle']](packet['source_package']['path'])
    require(actual==packet,'Source-feature packet does not equal independent input-only recomputation')
    if input_files is not None:
        require(isinstance(input_files,dict),'Current prescribed source inputs must be a bytes mapping')
        # The caller owns its required archive-file set. Supplied source subset
        # bytes must match; omitted dependencies were fully read/recomputed above.
        # In particular a TCAD descriptor is not the proton transport wrapper
        # merely because both files are named geometry-contract.json.
        for name,item in actual['inputs'].items():
            if name not in input_files:continue
            require(isinstance(input_files[name],bytes) and sha(input_files[name])==item['sha256'],
                    'Current source input differs from the shared feature input: '+name)
    return actual


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    for particle in ('alpha','proton'):
        q=sub.add_parser(particle);q.add_argument('--source-dir',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('verify');q.add_argument('--packet',type=Path,required=True)
    args=p.parse_args()
    result=verify(args.packet) if args.command=='verify' else globals()['build_'+args.command](args.source_dir,args.output)
    print(json.dumps(dict(particle=result['particle'],source_features=result['source_features'],native_source_qualified=False),allow_nan=False))
