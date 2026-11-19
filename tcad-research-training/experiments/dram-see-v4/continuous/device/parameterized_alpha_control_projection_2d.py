"""Input-only zero/half/finite-split controls of the fixed E5 normal alpha.

The parent ASTAR trajectory is never rescaled in energy or restarted per piece.
All original input/energy bytes remain in base-projection/. No native claim.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
BASE_SHA='f8e18b4c319dc10e170c5945b5b5b9ef7fa999f35ced4e21bf3f7267e97f1db4'
SCHEMA='dram-see-v4-parameterized-alpha-control-projection-2d-r1'
REQUEST_SCHEMA='dram-see-v4-parameterized-alpha-control-projection-request-r1'
MANIFEST_SCHEMA='dram-see-v4-parameterized-alpha-control-projection-manifest-r1'
OUTPUT=ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/parameterized-alpha-controls-implementation-r1'
BASE_FILES=('alpha-astar-silicon.csv','alpha-profile-2d-native.csv','alpha-profile-3d-reference.csv',
 'dimensional-contract.json','geometry-contract.json','heavyion.physics.inc','input-origins.json','model.proposed.json',
 'projection-ledger.json','projection-request.json','source-contract.json','source.par','energy-source-provenance.json','input-output-manifest.json')
CASES={'zero':dict(amplitude=0.,source_case='Z'),'half':dict(amplitude=.5,source_case='H'),
       'split':dict(amplitude=1.,source_case='split')}
CHARGES=('outside_y_strip_fC','inside_strip_outside_xz_box_fC','inside_strip_box_non_silicon_fC',
         'response_silicon_outside_observation_window_fC','accepted_observation_fC')

def require(ok,message):
    if not ok:raise ValueError('Alpha control projection: '+message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode('utf-8')
def obj(path):return json.loads(Path(path).read_bytes())
def base_api():
    path=HERE/'parameterized_alpha_projection_2d.py';raw=path.read_bytes()
    require(sha(raw)==BASE_SHA,'fixed parent projection changed')
    spec=importlib.util.spec_from_file_location('_alpha_control_fixed_base',path)
    module=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),module.__dict__)
    return module

def original(package):
    package=Path(package)
    require(package.is_dir() and set(p.name for p in package.iterdir())==set(BASE_FILES),'complete parent 14-file package required')
    request=obj(package/'projection-request.json')
    require(request.get('gate_top_depth_nm')==80 and request.get('energy_MeV')==5 and request.get('theta_deg')==0
        and request.get('phi_deg')==180 and request.get('amplitude')==1,'only original g80 E5 normal full source; no holdout or new energy')
    P=base_api();verified=P.verify(package)
    raw={n:(package/n).read_bytes() for n in BASE_FILES}
    inputs={n:raw[n] for n in P.INPUT_NAMES};ctx=P._context(inputs,request)
    require(ctx['path']['length_um']==1. and ctx['path']['direction']==[-0.,0.,1.]
        and ctx['path']['origin_um']==[-.052,0.,0.] and len(ctx['rows'])==101
        and ctx['rows'][50]['path_um']==.5,'fixed normal original LUT/coordinate contract differs')
    return P,verified,ctx,raw

def fragments(P,ctx,control):
    require(control in CASES,'unknown control')
    amp=CASES[control]['amplitude'];ranges=[(0,50),(50,100)] if control=='split' else [(0,100)]
    result=[]
    for index,(first,last) in enumerate(ranges):
        parent=ctx['rows'][first:last+1];start,end=parent[0]['path_um'],parent[-1]['path_um']
        rows=[dict(row,path_um=row['path_um']-start) for row in parent]
        origin=[ctx['path']['origin_um'][j]+start*ctx['path']['direction'][j] for j in range(3)]
        exit_point=[ctx['path']['origin_um'][j]+end*ctx['path']['direction'][j] for j in range(3)]
        path=dict(ctx['path'],origin_um=origin,entry_um=origin,exit_um=exit_point,length_um=end-start,
            entry_parameter_um=0.,exit_parameter_um=end-start)
        energy=dict(entry_energy_MeV=parent[0]['energy_MeV'],exit_energy_MeV=parent[-1]['energy_MeV'],
            electronic_deposition_MeV=parent[-1]['cumulative_electronic_MeV']-parent[0]['cumulative_electronic_MeV'],
            nuclear_deposition_MeV=parent[-1]['cumulative_nuclear_MeV']-parent[0]['cumulative_nuclear_MeV'],
            electronic_line_charge_fC=parent[-1]['cumulative_electronic_fC']-parent[0]['cumulative_electronic_fC'])
        energy['tabulated_line_charge_fC']=math.fsum((b['path_um']-a['path_um'])*(a['electronic_pC_um']+b['electronic_pC_um'])*500
            for a,b in zip(rows,rows[1:]))
        energy['lut_charge_error_fC']=energy['tabulated_line_charge_fC']-energy['electronic_line_charge_fC']
        energy['energy_balance_residual_MeV']=energy['entry_energy_MeV']-energy['exit_energy_MeV']-energy['electronic_deposition_MeV']-energy['nuclear_deposition_MeV']
        piece=dict(ctx,rows=rows,path=path,energy=energy,factors=P.mapping(amp,ctx['request']['epoch_s']))
        metadata=dict(index=index,name='AlphaStrip20nm2D' if index==0 else 'AlphaStrip20nm2D_split1',
            original_row_indices_inclusive=[first,last],original_s_interval_um=[start,end],
            local_s_interval_um=[0.,end-start],start_point_physical_um=origin,direction=path['direction'],
            half_open_domain='0 <= local_s < length_um',original_energy_account=energy,
            original_s_um=[r['path_um'] for r in parent],native_length_um=[r['path_um'] for r in rows],
            original_electronic_pC_um=[r['electronic_pC_um'] for r in parent],
            native_LET_f_pC_um=[r['electronic_pC_um']*piece['factors']['applied_LET_multiplier'] for r in parent],
            original_remaining_energy_MeV=[r['energy_MeV'] for r in parent],
            amplitude=amp,epoch_s=ctx['request']['epoch_s'],width_um=.05,sigma_s=.2e-12,
            profile_file='fragment-%03d-profile.csv'%index)
        result.append((piece,metadata))
    return result

def translate_moments(row,offset):
    value=copy.deepcopy(row);dx,dz=offset[0],offset[2]
    q=row['response_silicon_all_time_fC'];mx=row['response_Mx_relative_fC_um'];mz=row['response_Mz_relative_fC_um']
    value['response_Mx_relative_fC_um']=mx+dx*q
    value['response_Mz_relative_fC_um']=mz+dz*q
    value['response_Mxx_relative_fC_um2']=row['response_Mxx_relative_fC_um2']+2*dx*mx+dx*dx*q
    value['response_Mxz_relative_fC_um2']=row['response_Mxz_relative_fC_um2']+dx*mz+dz*mx+dx*dz*q
    value['response_Mzz_relative_fC_um2']=row['response_Mzz_relative_fC_um2']+2*dz*mz+dz*dz*q
    return value

def aggregate(rows):
    additive=[k for k,v in rows[0].items() if type(v) in (float,int)
        and k not in ('observation_time_mass','outside_observation_time_mass','offline_charge_gate_fC')]
    value={k:math.fsum(r[k] for r in rows) for k in additive}
    for k in ('observation_time_mass','outside_observation_time_mass'):
        require(all(r[k]==rows[0][k] for r in rows),'segments changed the original time distribution');value[k]=rows[0][k]
    value['charge_partition_residual_fC']=value['declared_axial_all_transverse_all_time_fC']-math.fsum(value[k] for k in CHARGES)
    value['offline_charge_gate_fC']=max(1e-6,.001*value['declared_axial_all_transverse_all_time_fC'])
    value['per_segment_numerical_settings']=[r['numerical_settings'] for r in rows]
    require(abs(value['charge_partition_residual_fC'])<=value['offline_charge_gate_fC'],'original five-Q offline gate failed')
    return value

def render(P,pieces):
    physics=[];parameters=[]
    for ctx,row in pieces:
        include,par=P.C.render(ctx)
        if row['index']:
            include=include.replace(b'AlphaStrip20nm2D',row['name'].encode())
            par=par.replace(b'AlphaStrip20nm2D',row['name'].encode())
        physics.append(include);parameters.append(par)
    return b''.join(physics),b''.join(parameters)

def generation2d(P,pieces,x_um,z_um,time_s,material=True):
    """Half-open finite track point oracle, G2 in cm^-3 s^-1."""
    values=[]
    for ctx,_ in pieces:
        p=ctx['path'];s=(x_um-p['origin_um'][0])*p['direction'][0]+(z_um-p['origin_um'][2])*p['direction'][2]
        if 0<=s<p['length_um']:values.append(P.generation2d(ctx,x_um,z_um,time_s,material))
    return math.fsum(values)

def derive(package,control):
    P,verified,ctx,base=original(package);pieces=fragments(P,ctx,control);amp=CASES[control]['amplitude']
    coarse=[];fine=[];segment_records=[];payload={'base-projection/'+n:raw for n,raw in base.items()}
    for piece,metadata in pieces:
        offset=[a-b for a,b in zip(piece['path']['origin_um'],ctx['path']['origin_um'])]
        c=translate_moments(P.projected_integral(piece),offset)
        f=translate_moments(P.projected_integral(piece,True),offset)
        coarse.append(c);fine.append(f);segment_records.append(dict(metadata,coarse=c,refined=f))
        payload[metadata['profile_file']]=P.A.profile_bytes([dict(r,original_s_um=s) for r,s in zip(piece['rows'],metadata['original_s_um'])])
    total_c,total_f=aggregate(coarse),aggregate(fine)
    differences={k:abs(total_c[k]-v) for k,v in total_f.items() if type(v) in (float,int)}
    require(all(differences[k]<=total_c['offline_charge_gate_fC'] for k in differences if k.endswith('_fC')),
        'existing offline charge refinement gate failed')
    expected={k:amp*v for k,v in verified['ledger']['refined'].items() if type(v) in (float,int)
        and (k.endswith('_fC') or k.endswith('_fC_um') or k.endswith('_fC_um2') or k.endswith('_fC_ps') or k.endswith('_fC_ps2'))}
    comparison={k:total_f[k]-v for k,v in expected.items() if k in total_f and k!='offline_charge_gate_fC'}
    require(all(abs(comparison[k])<=max(1e-6,.001*abs(expected[k])) for k in CHARGES),
        'control source differs from declared parent amplitude/partition')
    energy=dict(original_parent_energy=verified['ledger']['energy'],original_parent_provenance=obj(Path(package)/'energy-source-provenance.json'),
        segments=[r['original_energy_account'] for r in segment_records],
        incident_energy_counted_once=True,restarted_at_incident_energy_per_segment=False,
        configured_source_amplitude=amp,amplitude_is_not_incident_energy_scaling=True,
        reference_energy_unscaled=True,nuclear_energy_converted_to_charge=False)
    for key in ('electronic_deposition_MeV','nuclear_deposition_MeV','tabulated_line_charge_fC'):
        energy[key+'_partition_residual']=math.fsum(r['original_energy_account'][key] for r in segment_records)-verified['ledger']['energy'][key]
    request=dict(schema=REQUEST_SCHEMA,control=control,source_case=CASES[control]['source_case'],
        amplitude=amp,base_request=verified['contract']['request'],split_at_original_s_um=.5 if control=='split' else None)
    ledger=dict(schema='dram-see-v4-parameterized-alpha-control-charge-ledger-r1',coarse=total_c,refined=total_f,
        segments=segment_records,refinement_absolute_differences=differences,parent_scaled_reference=expected,
        difference_from_parent_scaled_reference=comparison,energy=energy,
        charge_partition_order=list(CHARGES),tail_renormalization=False,discarded_source_records=0,
        original_all_time_line_source_retained=True,actual_clock=None,is_native_measurement=False,
        native_zero_split_charge_limit_fC=1e-4,native_zero_split_voltage_limit_V=1e-5,
        native_zero_split_checks_executed=False,native_source_qualified=False)
    include,parameters=render(P,pieces)
    contract=dict(schema=SCHEMA,particle='alpha',dimension=2,request=request,
        base_source_contract_sha256=sha(base['source-contract.json']),base_projection_manifest_sha256=sha(base['input-output-manifest.json']),
        base_projection_implementation_sha256=BASE_SHA,base_request=ctx['request'],response=ctx['response'],
        path=ctx['path'],mapping=P.mapping(amp,ctx['request']['epoch_s']),base_mapping=ctx['factors'],configured_amplitude=amp,
        segments=[{k:v for k,v in m.items() if k not in ('coarse','refined')} for m in segment_records],
        input_sha256=verified['contract']['input_sha256'],mesh_sha256=verified['contract']['mesh_sha256'],
        physics_manifest_sha256=verified['contract']['physics_manifest_sha256'],
        source_window_s=ctx['source_window_s'],full_simulation_window_s=ctx['request']['simulation_window_s'],
        G2_unit='cm^-3 s^-1',native_to_physical_axes=dict(X='x',Y='z'),effective_width_cm=2e-6,
        original_reference_point_um=ctx['path']['origin_um'],moment_reference='All segment moments translated back to original input r0',
        domain='Finite perpendicular axial end planes plus original extruded Si mask; no tail renormalization',
        end_plane_oracle='0<=local_s<L; seam belongs only to second piece; G=0 at overall end',
        old_parent_endpoint_point_convention_unchanged=True,
        native_endpoint_and_seam_field_verification='PENDING; finite point values are not proved by zero-measure integral equivalence',
        vendor_basis=dict(version='W-2024.09',pages=[812,813,814,815,816,1728,1729],
            pdf_sha256='98f37002013ccc2e73c0316e3ea66fd7d06fd773abac7caaa3d362ea85d5c5b0'),
        base_energy_is_not_regenerated_per_piece=True,time_shift_s=0,additional_normalization=False,
        native_source_qualified=False,native_qualified=False,is_tcad_result=False,training_admitted=False,pmi_r12_fixed=False)
    payload.update({'control-request.json':encoded(request),'segments.json':encoded(segment_records),
        'projection-ledger.json':encoded(ledger),'energy-source-provenance.json':encoded(energy),
        'heavyion.physics.inc':include,'source.par':parameters})
    contract['derived_files_sha256']={n:sha(v) for n,v in payload.items() if not n.startswith('base-projection/')}
    payload['source-contract.json']=encoded(contract)
    return payload,contract,ledger

def manifest(payload):
    return dict(schema=MANIFEST_SCHEMA,implementation_sha256=sha(Path(__file__).read_bytes()),
        base_projection_sha256=BASE_SHA,files={n:dict(sha256=sha(v),size_bytes=len(v)) for n,v in payload.items()},
        native_source_qualified=False,is_native_result=False,training_admitted=False)

def build(base_package,control,output):
    output=Path(output).resolve();require(OUTPUT in output.parents and not output.exists(),'new control evidence directory required; no overwrite')
    payload,contract,ledger=derive(base_package,control)
    payload['input-output-manifest.json']=encoded(manifest(payload));output.mkdir(parents=True)
    for name,raw in payload.items():
        path=output/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)
    return dict(output=str(output),contract=contract,ledger=ledger)

def verify(package):
    package=Path(package);m=obj(package/'input-output-manifest.json')
    require(m.get('schema')==MANIFEST_SCHEMA and m.get('implementation_sha256')==sha(Path(__file__).read_bytes())
        and m.get('base_projection_sha256')==BASE_SHA and m.get('native_source_qualified') is False
        and m.get('is_native_result') is False and m.get('training_admitted') is False,'unknown or altered control version/qualification')
    require({str(p.relative_to(package)).replace('\\','/') for p in package.rglob('*') if p.is_file()}
        ==set(m['files'])|{'input-output-manifest.json'},'control package inventory differs')
    for name,row in m['files'].items():
        p=Path(name);require(not p.is_absolute() and '..' not in p.parts and not (package/name).is_symlink(),'invalid source member')
        raw=(package/name).read_bytes();require(row==dict(sha256=sha(raw),size_bytes=len(raw)),'control bytes differ: '+name)
    request=obj(package/'control-request.json')
    payload,contract,ledger=derive(package/'base-projection',request['control'])
    require(all((package/name).read_bytes()==raw for name,raw in payload.items())
        and m==manifest(payload),'control differs from full original-input replay')
    return dict(contract=contract,ledger=ledger,manifest=m)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    b=s.add_parser('build');b.add_argument('--base-package',type=Path,required=True);b.add_argument('--control',choices=tuple(CASES),required=True);b.add_argument('--output',type=Path,required=True)
    v=s.add_parser('verify');v.add_argument('--package',type=Path,required=True);a=p.parse_args()
    r=build(a.base_package,a.control,a.output) if a.command=='build' else verify(a.package)
    print(encoded(dict(control=r['contract']['request']['control'],charge=r['ledger']['refined'],native_source_qualified=False)).decode())
