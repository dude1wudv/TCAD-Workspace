"""Unregistered fixed-kernel proton features for multi-condition native bundles.

The full packet requires original transport receipts and complete-event audit.
The public pure_moments helper is input mathematics only, never native evidence.
"""
from __future__ import annotations
import argparse
import importlib.util
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_source_features_proton_bundle_v2',HERE/'source_bundle_proton_v2.py')
B=importlib.util.module_from_spec(spec);exec(compile((HERE/'source_bundle_proton_v2.py').read_bytes(),str(HERE/'source_bundle_proton_v2.py'),'exec'),B.__dict__)
F=B.F;require=F.require
CONTRACT=HERE/'source-feature-contract-proton-v2.json'
FEATURES=('source_present','Q_Si_fC','M_x_fC_um','M_y_fC_um','M_z_fC_um','M_xx_fC_um2','M_xy_fC_um2',
          'M_xz_fC_um2','M_yy_fC_um2','M_yz_fC_um2','M_zz_fC_um2','M_t_fC_ps','M_tt_fC_ps2')
OWN_FILES=(Path(__file__),Path(B.__file__),Path(B.T.__file__),Path(B.T.G.__file__),Path(F.__file__),
           HERE/'PROTON-V2-ASSUMPTIONS.md',CONTRACT)
LOADED={str(path.resolve()):F.sha(path.read_bytes()) for path in OWN_FILES}


def stable_implementations():
    original=F.stable()
    require(all(F.sha(Path(path).read_bytes())==digest for path,digest in LOADED.items()),
            'Multi-condition candidate changed after loading')
    return {Path(path).name:dict(path=path,sha256=digest) for path,digest in LOADED.items()}|{
        Path(item['path']).name:item for item in original.values()}


def contract_bytes(packet=None):
    raw=CONTRACT.read_bytes();value=F.parse(raw)
    require(value['schema']=='continuous-particle-source-feature-contract-proton-v2' and value['version_id']=='v2-proton-bcat'
            and value['feature_order']==list(FEATURES) and value['numerics']['normalized_absolute']==F.R.ABS_TOL
            and value['numerics']['relative']==F.R.REL_TOL and value['numerics']['refinement_factor']==.25,
            'Unregistered proton v2 feature/numerical contract differs')
    if packet is not None:
        require(packet['feature_contract_sha256']==F.sha(raw) and packet['feature_contract']==value
                and packet['feature_contract_ref']==F.ref(CONTRACT),'Proton v2 fixed contract identity differs')
    return raw


def pure_moments(rows,model,geometry,r0=(-.052,0.,0.),epoch_s=15e-9):
    """No file/response inputs; retain all rows including late and point deposits."""
    semantic=B.T.G.validate(model,geometry)
    require(list(r0)==[-.052,0.,0.] and epoch_s==15e-9,'Unsupported prescribed proton origin/epoch')
    contract=F.parse(contract_bytes())
    values=F.M.proton_moments(rows,geometry,list(r0),epoch_s,F.R,clock=None)
    fine=F.M.proton_moments(rows,geometry,list(r0),epoch_s,F.R,clock=None,abs_tol=F.R.ABS_TOL/4,rel_tol=F.R.REL_TOL/4)
    allocated=math.fsum(row[8] for row in rows);checks=[]
    for key,a,b in zip(FEATURES[1:],values,fine):
        gate=100*F.R.ABS_TOL*max(1.,allocated)+10*F.R.REL_TOL*abs(b)
        checks.append(dict(feature=key,difference=abs(a-b),gate=gate,passed=abs(a-b)<=gate))
    require(all(item['passed'] for item in checks),'Original proton moment refinement did not converge')
    present=int(bool(rows));require(values[0]>0 if present else all(value==0 for value in values),'Explicit zero/positive source conflict')
    q=values[0]
    if q==0:interpretation=dict(centroid_relative_um=None,centroid_um=None,covariance_um2=None,time_centroid_ps=None,time_variance_ps2=None)
    else:
        mean=[value/q for value in values[1:4]];pairs=[(0,0),(0,1),(0,2),(1,1),(1,2),(2,2)]
        interpretation=dict(centroid_relative_um=mean,centroid_um=[a+b for a,b in zip(mean,r0)],
            covariance_um2=[value/q-mean[i]*mean[j] for value,(i,j) in zip(values[4:10],pairs)],
            covariance_order=['xx','xy','xz','yy','yz','zz'],time_centroid_ps=values[10]/q,
            time_variance_ps2=values[11]/q-(values[10]/q)**2)
    return dict(source_features=dict(zip(FEATURES,[present,*values])),allocated_all_space_all_time_fC=allocated,
        interpretation=interpretation,numerical_refinement=dict(checks=checks,passed=True,
            coarse=dict(absolute=F.R.ABS_TOL,relative=F.R.REL_TOL),refined=dict(absolute=F.R.ABS_TOL/4,relative=F.R.REL_TOL/4),
            meaning=contract['numerics']['interpretation']),device_parameters=semantic,
        source_row_count=len(rows),all_late_rows_retained=True,clock=None,native_source_qualified=False)


def proton_packet(source_dir):
    implementations=stable_implementations();source_dir=Path(source_dir).resolve()
    bundle=F.read(source_dir/'source-bundle.json');source=F.read(source_dir/'source-contract.json')
    require(bundle['schema']=='continuous-proton-source-bundle-v2' and bundle['version_id']=='v2-proton-bcat',
            'Original source bundle is not the multi-condition proton version')
    binding=bundle['binding'];operation=Path(binding['operation']['path']).parent;build=Path(binding['build_operation']['path']).parent
    actual=B.payload(operation,binding['transport_event_id'],build,source_dir,
        source['approximation']['let_node_width_fraction'],source['approximation']['max_segment_time_sigma_fraction'])
    require(all((source_dir/name).read_bytes()==raw for name,raw in actual.items()),
            'Original multi-condition source bundle does not reproduce from its complete native event')
    request=F.read(source_dir/'request.json');model=F.read(source_dir/'model-input.json');geometry=F.read(source_dir/'geometry-contract.json')
    rows=F.R.load_sources(source_dir/'sources.dat');r0=request['target_um'];epoch=binding['source_time_s']
    require(source['epoch_s']==epoch,'Source clock origin differs from original condition input')
    summary=pure_moments(rows,model,geometry,r0,epoch)
    inputs={name:F.ref(source_dir/name) for name in actual};hashes={name:item['sha256'] for name,item in sorted(inputs.items())}
    raw=contract_bytes();contract=F.parse(raw);semantic=summary.pop('device_parameters')
    require(stable_implementations()==implementations,'Candidate implementations changed during source recomputation')
    return dict(schema='continuous-particle-source-features-v2',version_id='v2-proton-bcat',particle='proton',
        source_status='PRESCRIBED_POSITIVE_SOURCE' if rows else 'PRESCRIBED_STRUCTURAL_ZERO',
        r0_um=r0,epoch_s=epoch,feature_contract=contract,feature_contract_sha256=F.sha(raw),feature_contract_ref=F.ref(CONTRACT),
        inputs=inputs,source_package=dict(path=str(source_dir),kind='prescribed_complete_native_event_input_subset',
            files_sha256=hashes,sha256=F.sha(F.encoded(hashes))),implementations=implementations,
        source_definition=dict(kernel='original_Gaussian3D_segment_convolution',spatial_width_um=.03,temporal_sigma_ps=2.,
            complete_event_source_rows=len(rows),seed=request['seed'],transport_event_id=binding['transport_event_id'],
            original_operation=binding['operation'],original_archive=binding['archive'],all_late_rows_retained=True,
            geometry_contract=binding['geometry_contract'],device_geometry=binding['device_geometry'],
            shared_random_stream_key=binding['shared_random_stream_key']),
        source_conditions=dict(gate_top_depth_nm=semantic['gate_top_depth_nm'],sn_junction_depth_nm=semantic['sn_junction_depth_nm'],
            energy_MeV=request['energy_MeV'],angle_deg=request['theta_deg'],seed=request['seed'],transport_event_id=binding['transport_event_id']),
        data_design=dict(registered=False,original_condition_id=binding['condition_id'],original_split=binding['split'],
            final_holdout=binding['final_holdout'],final_holdout_policy='never_for_tuning',sn_axis_requires_explicit_registration=True),
        uses_tcad_outputs=False,is_tcad_result=False,pmi_r12_fixed=False,registered_in_dispatcher=False,
        prediction_scope=contract['scope'],**summary)


def build(source_dir,output):
    output=Path(output).resolve()
    require(output.is_relative_to(F.RUNTIME.resolve()) and not output.exists(),'New immutable proton feature output required')
    packet=proton_packet(source_dir);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as stream:stream.write(F.encoded(packet))
    return packet


def verify(packet_path,input_files=None):
    packet_path=Path(packet_path).resolve();original=packet_path.read_bytes();packet=F.parse(original)
    require(packet.get('schema')=='continuous-particle-source-features-v2' and packet.get('version_id')=='v2-proton-bcat'
            and packet.get('particle')=='proton','Unknown independent proton v2 packet')
    require(packet.get('implementations')==stable_implementations(),'Packet implementation paths/hashes differ from fixed original modules')
    contract_bytes(packet);actual=proton_packet(packet['source_package']['path'])
    require(actual==packet and packet_path.read_bytes()==original,'Proton v2 packet differs from complete original-input recomputation')
    if input_files is not None:
        require(isinstance(input_files,dict),'Current prescribed input subset must be a bytes map')
        for name,item in actual['inputs'].items():
            if name in input_files:
                require(isinstance(input_files[name],bytes) and F.sha(input_files[name])==item['sha256'],
                        'Current source input differs from original multi-condition bundle: '+name)
    return actual


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('build');q.add_argument('--source-dir',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('verify');q.add_argument('--packet-path',type=Path,required=True)
    args=vars(p.parse_args());command=args.pop('command');result=globals()[command](**args)
    print(F.encoded(dict(version_id=result['version_id'],source_features=result['source_features'],native_source_qualified=False)).decode())
