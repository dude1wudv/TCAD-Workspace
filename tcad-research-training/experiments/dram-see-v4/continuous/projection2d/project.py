"""Immutable input-only 20nm projection packages; no native output is invented."""
from __future__ import annotations
import argparse
import importlib.util
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
RUNTIME=ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/projection-implementation'
CONTRACT=HERE/'projection-kernel-contract.json'


def module(name):
    path=HERE/(name+'.py');spec=importlib.util.spec_from_file_location('_r14_projection_'+name,path)
    result=importlib.util.module_from_spec(spec);exec(compile(path.read_bytes(),str(path),'exec'),result.__dict__)
    return result
K=module('kernel');A=module('adapter');require=A.require


def dimensional(path,geometry_path):
    value=A.read_json(path)
    expected=dict(schema='dram-see-v4-2d-equivalence-r1',native_dimension=2,physical_dimension=2,
        effective_width_nm=20,effective_width_um=.02,effective_width_cm=2e-6,native_reference_width_um=1,
        area_factor=.02,native_to_physical_axes=dict(X='x',Y='z',Z='omitted_y'),native_third_coordinate=0,
        out_of_plane_axis='y',native_coordinate_unit='um',port_current_already_width_scaled=True,
        explicit_capacitance_rescale=False,native_area_integral_unit='um^2',area_to_cm2_factor=1e-8,
        area_integral_to_effective_volume_cm3_factor=2e-14,source_dimension=2)
    require(all(value.get(key)==v for key,v in expected.items()),'Actual dimensional contract differs from 20nm 2D semantics')
    require(value['geometry_contract_sha256']==A.digest(geometry_path),'Width contract is not bound to supplied actual D2 geometry')
    return value


def bcat_response(model_path,geometry_path,dimensional_path,transport_geometry):
    model=A.read_json(model_path);g=A.read_json(geometry_path);width=dimensional(dimensional_path,geometry_path)
    t=transport_geometry.get('geometry',transport_geometry)
    require(g['dimension']==2 and t['dimension']==3 and g['length_unit']==t['length_unit']=='um',
            'Actual D2 and physical 3D material geometry are required')
    require(g['schema']==t['schema']=='s2-bcat-analytic-geometry-r1' and g['sti']['included'] is False and t['sti']['included'] is True,
            'Unregistered transport/response material geometry')
    require(model['geometry']['active_width_nm']==20 and model['doping']['sn_junction_depth_nm']==87 and
            model['geometry']['gate_top_depth_nm'] in (70,80),'Projection development domain excludes final geometry/SN extension')
    require(g['gate_void']['top_um']==model['geometry']['gate_top_depth_nm']/1000,'Model gate differs from actual D2 input')
    doping=model['doping'];asn=doping['sn_junction_depth_nm']/1000/math.sqrt(math.log(doping['peak_donor']/doping['uniform_acceptor']))
    require(math.isclose(g['doping']['a_sn_um'],asn,rel_tol=0,abs_tol=1e-14) and
            g['doping']['peak_cm3']==doping['peak_donor'] and g['doping']['acceptor_cm3']==doping['uniform_acceptor'],
            'Actual D2 model and geometry doping inputs differ')
    for name in ('x','z'):require(g['domain_um'][name]==t['domain_um'][name],'Transport/response finite domain differs')
    require(t['domain_um']['y'][0]<=-.01 and t['domain_um']['y'][1]>=.01,'Transport lacks complete response strip')
    for key in ('x_half_width_um','radius_um','round_center_z_um','top_um','bottom_um','construction'):
        require(g['outer_trench'][key]==t['outer_trench'][key],'Transport/response Si trench differs: '+key)
    for key in ('x_half_width_um','radius_um','round_center_z_um','top_um','bottom_um'):
        require(g['gate_void'][key]==t['gate_void'][key],'Transport/response gate material boundary differs: '+key)
    require(t['outer_trench']['y_half_width_um']>=.01 and t['gate_void']['y_half_width_um']>=.01,
            'Material boundaries are not uniform through the response strip')
    require(all(max(a,-.01)>=min(b,.01) for a,b in t['sti']['y_intervals_um']),
            'Transport STI intersects the declared extruded central Si response strip')
    require(transport_geometry.get('gate_transport_material')=='G4_Galactic','Unregistered gate-volume material')
    box=[g['domain_um']['x'][0],g['domain_um']['z'][0],g['domain_um']['x'][1],g['domain_um']['z'][1]]
    tr=g['outer_trench'];r,c,top=tr['radius_um'],tr['round_center_z_um'],tr['top_um']
    area=(box[2]-box[0])*(box[3]-box[1])-(2*r*(c-top)+math.pi*r*r/2)
    require(abs(area-g['measures']['silicon'])<=1e-11,'Actual D2 Si area differs from declared analytic mask')
    response=dict(kind='bcat_center_section',bounds_xz_um=box,
        outer_trench=dict(radius_um=r,center_z_um=c,top_um=top))
    return response,dict(model=A.ref(model_path),geometry=A.ref(geometry_path),dimensional_contract=A.ref(dimensional_path),
        mesh_sha256=width['mesh_sha256'],physics_manifest_sha256=width['physics_manifest_sha256'],
        material_correspondence='Input geometry equality through y in [-0.01,0.01]um; native geometry/source still requires its own proof',
        actual_native_axes=width['native_to_physical_axes'],effective_width_cm=width['effective_width_cm'])


def response_for_historical(source):
    geometry=source['context']['original_geometry'];si=[s for s in geometry['solids'] if s['id']=='R.Si']
    require(len(si)==1 and si[0]['shape']=='cuboid' and si[0]['geant4_material']=='G4_Si','Historical Si solid differs')
    body=si[0];lo,hi=body['min_um'],body['max_um']
    require(lo[2]<=-.01 and hi[2]>=.01,'Historical original width does not contain the declared strip')
    return dict(kind='historical_planar_rectangle',bounds_xz_um=[lo[0],lo[1],hi[0],hi[1]],outer_trench=None)


def derivation(source,response,window,origin,bindings):
    raw=CONTRACT.read_bytes();contract=json.loads(raw)
    require(contract['effective_width_cm']==K.WIDTH_CM and contract['effective_width_um']==K.WIDTH_UM and
            contract['raw_native_area_to_pairs_per_s']==1e-8*K.WIDTH_CM,'Fixed projection units differ')
    coarse=K.integrate(source['terms'],response,window,origin,source['epoch_s'])
    fine=K.integrate(source['terms'],response,window,origin,source['epoch_s'],refined=True)
    checks=[]
    for key,a in coarse['totals'].items():
        delta=abs(a-fine['totals'][key]);gate=coarse['offline_charge_gate_fC']
        # Moment repeatability is reported in each explicit moment unit; only
        # actual charge categories use the existing source-charge acceptance gate.
        checks.append(dict(name=key,difference=delta,unit=('fC um' if 'Mx_' in key or 'Mz_' in key else 'fC ps' if 'Mt_' in key else 'fC'),
                           offline_charge_gate_passed=(delta<=gate if '_M' not in key else None)))
    require(all(check['offline_charge_gate_passed'] is not False for check in checks),'Conservative charge integral did not converge')
    q=coarse['totals']['accepted_fC'];dt=window[1]-window[0]
    # Identities for future area-integrated native G. These are predictions from
    # source inputs, not manufactured native measurements.
    area_time=q*1e-15/(K.E_C*K.WIDTH_CM*1e-8)
    reconstructed=K.E_C*K.WIDTH_CM*1e-8*area_time*1e15
    impl={name:A.ref(HERE/name) for name in ('kernel.py','adapter.py','project.py','ASSUMPTIONS.md')}
    projection_contract=dict(schema='dram-see-v4-conservative-projection-contract-r1',
        version_id=contract['version_id'],particle='proton',dimension=2,
        kernel_contract=contract,kernel_contract_ref=A.ref(CONTRACT),kernel_contract_sha256=A.sha(raw),
        source_representation=source['representation'],source_sha256=A.sha(A.encoded(source)),response=response,
        response_bindings=bindings,geometry_provenance_scope=source['context']['scope'],
        physical_y_bounds_um=list(K.Y_BOUNDS),effective_width_cm=K.WIDTH_CM,
        native_to_physical_axes=dict(X='x',Y='z',Z='omitted_y'),G2_unit='cm^-3 s^-1',
        time_window_s=window,r0_um=origin,epoch_s=source['epoch_s'],
        raw_native_moment_origin='Absolute physical x/z from native X/Y; relative source moments separately labelled',
        implementations=impl,original_G3_definition=source['continuous_reconstruction_reference'],
        continuous_reference=A.ref(K.REFERENCE),nonrenormalization=True,
        source_representability=('RAW_DEPOSITION_OUTSIDE_WINDOW_REQUIRES_TIMING_REVIEW' if coarse['raw_deposition_outside_window_uids'] else 'INPUT_DEPOSITION_CENTERS_WITHIN_WINDOW_NATIVE_REPRESENTATION_STILL_UNIMPLEMENTED'),
        native_source_representation='UNIMPLEMENTED_PENDING_NATIVE_FIELD_VERIFICATION',
        dimensional_model='20nm uniformly extruded 2D equivalent, not full 3D response',
        native_source_qualified=False,pmi_r12_fixed=False)
    ledger=dict(schema='dram-see-v4-conservative-projection-ledger-r1',coarse=coarse,refined=fine,
        refinement=checks,original_non_silicon_ionizing_MeV=source['non_silicon_ionizing_energy_MeV'],
        all_original_material_ionizing_MeV=source['all_material_ionizing_MeV'],
        mathematical_charge_identity=dict(Q3_accepted_fC=q,Q2_from_width_and_area_integral_fC=reconstructed,
            residual_fC=reconstructed-q,integral_G2_dA_um2_dt_cm_minus3=area_time,
            mean_G2_area_integral_cm_minus3_per_s_um2=area_time/dt,
            expected_raw_XG_area_time=coarse['totals']['accepted_Mx_absolute_fC_um']*1e-15/(K.E_C*K.WIDTH_CM*1e-8),
            expected_raw_ZG_area_time=coarse['totals']['accepted_Mz_absolute_fC_um']*1e-15/(K.E_C*K.WIDTH_CM*1e-8),
            is_native_measurement=False),
        all_source_step_records_retained=source['all_selected_event_steps_retained'],
        original_request_event_denominator=len(source['context']['original_request_denominator']),
        omitted_event_ids=source['context']['unprojected_original_event_ids'],
        omission_reason=source['context']['unprojected_reason'],
        discarded_records=0,native_source_qualified=False,actual_BE_clock=None)
    return projection_contract,ledger


def write_package(source,response,window,origin,bindings,replay,output):
    output=Path(output).resolve();require(output.is_relative_to(RUNTIME.resolve()) and not output.exists(),
        'Projection output must be new and inside the dedicated evidence directory')
    contract,ledger=derivation(source,response,list(window),list(origin),bindings)
    payload={'replay-request.json':A.encoded(replay),'projection-source.json':A.encoded(source),
        'projection-contract.json':A.encoded(contract),'projection-ledger.json':A.encoded(ledger),
        'projection-kernel-contract.json':CONTRACT.read_bytes()}
    manifest=dict(schema='dram-see-v4-projection-input-output-manifest-r1',
        files={name:dict(sha256=A.sha(raw),bytes=len(raw)) for name,raw in payload.items()},
        is_native_result=False,native_source_qualified=False)
    output.mkdir(parents=True)
    for name,raw in {**payload,'input-output-manifest.json':A.encoded(manifest)}.items():
        with (output/name).open('xb') as stream:stream.write(raw)
    return dict(output=str(output),contract=contract,ledger=ledger,manifest=manifest)


def build_historical(output,window,epoch_s=15e-9):
    source=A.historical_event0(epoch_s);response=response_for_historical(source)
    origin=[.7,0.,0.]
    replay=dict(schema='dram-see-v4-projection-replay-request-r1',adapter='fixed-historical-event0',epoch_s=epoch_s,
                window_s=list(window),origin_um=origin,native_or_training_admission=False)
    return write_package(source,response,window,origin,dict(historical_geometry=source['context']['original_files']['geometry-contract.json'],
        corresponding_actual_D2_BCAT_geometry=None,not_a_BCAT_mapping=True),replay,output)


def build_bcat(source_bundle,model,geometry,dimensional_contract,window,output):
    source=A.bcat_bundle(source_bundle)
    response,bindings=bcat_response(model,geometry,dimensional_contract,source['context']['original_geometry'])
    request=A.read_json(source['context']['original_binding']['request']['path']);origin=request['target_um']
    replay=dict(schema='dram-see-v4-projection-replay-request-r1',adapter='original-bcat-bundle',source_bundle=str(Path(source_bundle).resolve()),
        model=str(Path(model).resolve()),geometry=str(Path(geometry).resolve()),dimensional_contract=str(Path(dimensional_contract).resolve()),
        window_s=list(window),origin_um=origin,native_or_training_admission=False)
    return write_package(source,response,window,origin,bindings,replay,output)


def verify(output):
    output=Path(output).resolve();manifest=A.read_json(output/'input-output-manifest.json');request=A.read_json(output/'replay-request.json')
    names={'replay-request.json','projection-source.json','projection-contract.json','projection-ledger.json','projection-kernel-contract.json'}
    expected_manifest=dict(schema='dram-see-v4-projection-input-output-manifest-r1',
        files={name:dict(sha256=A.digest(output/name),bytes=(output/name).stat().st_size) for name in names},
        is_native_result=False,native_source_qualified=False)
    require(manifest==expected_manifest,'Unknown/tampered projection manifest or native qualification flag')
    for name,item in manifest['files'].items():
        require(Path(name).name==name and A.digest(output/name)==item['sha256'] and (output/name).stat().st_size==item['bytes'],
                'Projection file identity differs: '+name)
    require((output/'projection-kernel-contract.json').read_bytes()==CONTRACT.read_bytes(),'Projection kernel contract changed')
    if request['adapter']=='fixed-historical-event0':
        source=A.historical_event0(request['epoch_s']);response=response_for_historical(source)
        bindings=dict(historical_geometry=source['context']['original_files']['geometry-contract.json'],corresponding_actual_D2_BCAT_geometry=None,not_a_BCAT_mapping=True)
    elif request['adapter']=='original-bcat-bundle':
        source=A.bcat_bundle(request['source_bundle'])
        response,bindings=bcat_response(request['model'],request['geometry'],request['dimensional_contract'],source['context']['original_geometry'])
    else:raise ValueError('Unimplemented/unregistered projection adapter')
    contract,ledger=derivation(source,response,request['window_s'],request['origin_um'],bindings)
    for name,value in [('projection-source.json',source),('projection-contract.json',contract),('projection-ledger.json',ledger)]:
        require((output/name).read_bytes()==A.encoded(value),'Projection does not equal complete original-input recomputation: '+name)
    return dict(contract=contract,ledger=ledger,manifest=manifest)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('historical');q.add_argument('--output',type=Path,required=True);q.add_argument('--window',type=float,nargs=2,required=True);q.add_argument('--epoch',type=float,default=15e-9)
    q=sub.add_parser('bcat');q.add_argument('--source-bundle',type=Path,required=True);q.add_argument('--model',type=Path,required=True)
    q.add_argument('--geometry',type=Path,required=True);q.add_argument('--dimensional-contract',type=Path,required=True)
    q.add_argument('--window',type=float,nargs=2,required=True);q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('verify');q.add_argument('--package',type=Path,required=True)
    args=p.parse_args()
    if args.command=='historical':result=build_historical(args.output,args.window,args.epoch)
    elif args.command=='bcat':result=build_bcat(args.source_bundle,args.model,args.geometry,args.dimensional_contract,args.window,args.output)
    else:result=verify(args.package)
    print(json.dumps(dict(totals=result['ledger']['coarse']['totals'],native_source_qualified=False),allow_nan=False))
