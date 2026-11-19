"""Versioned complete native proton event audit for supplied BCAT D3 inputs."""
from __future__ import annotations
import argparse
from decimal import Decimal
import importlib.util
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('_proton_bundle_prepare_v2',HERE/'transport_prepare_v2.py')
T=importlib.util.module_from_spec(spec);exec(compile((HERE/'transport_prepare_v2.py').read_bytes(),str(HERE/'transport_prepare_v2.py'),'exec'),T.__dict__)
F=T.F;require=F.require
EVENT_OUTPUTS=F.B.EVENT_OUTPUTS
CORE_INPUTS=T.RUN_INPUTS+('request.json','input-manifest.json','task.sh')


def audit_transport_event(operation,event_id,build):
    """Read only actual original v2 operation archives; never fabricate a receipt."""
    F.stable();operation,receipt=F.P.complete_operation(operation,EVENT_OUTPUTS+CORE_INPUTS)
    require(receipt.get('schema')=='dram-see-v4-transport-operation-v2','Actual original operation v2 required')
    folder=operation/'collected';request=F.read(folder/'request.json');metadata=F.read(folder/'metadata.json')
    status=F.read(folder/'status.json');geometry=F.read(folder/'geometry-contract.json')
    require(request.get('schema')=='continuous-proton-transport-request-v2' and request.get('version_id')=='v2-proton-bcat',
            'Unknown multi-condition original request')
    require(type(event_id) is int and 0<=event_id<request['event_count'],'Event ID is outside the complete original request')
    condition=T.condition(request['condition_id'],request['seed'])
    build,build_receipt,semantic=T.audit_build(build)
    require(T.G.validate_files(folder)==semantic,'Run geometry differs from its actual compiled device')
    require(request==T.request_payload(build,request['label'],condition,request['seed'],request['event_count'],semantic),
            'Original request/condition/SN/seed binding changed')
    for name in T.RUN_INPUTS:
        require((folder/name).read_bytes()==(build/'collected'/name).read_bytes(),'Run input differs from original compile: '+name)
    input_manifest=F.read(folder/'input-manifest.json')
    require(input_manifest['schema']=='continuous-proton-inputs-v2' and input_manifest['version_id']=='v2-proton-bcat',
            'Unknown native submitted input manifest')
    for name,digest in input_manifest['files'].items():
        require(F.sha((folder/name).read_bytes())==digest,'Native submitted input hash differs: '+name)
    require(request['arm']==metadata['arm']=='H' and request['mode']==metadata['mode']=='normal'
            and metadata['primary_particle']=='proton','Actual complete proton H-arm transport required')
    require(request['seed']==metadata['seed'] and request['energy_MeV']==metadata['energy_MeV']
            and request['theta_deg']==metadata['angle_deg'] and request['event_count']==metadata['events_requested'],
            'Actual native beam/request differs')
    beam=F.B.native_beam(request,metadata)
    require(metadata['requested_threads']==1 and metadata['multithreaded_run_manager'] is False
            and metadata['run_manager']=='G4RunManager' and metadata['geant4_version_number']==1073,
            'Actual original software/thread protocol differs')
    require(metadata['user_track_killing'] is False and metadata['standard_neutron_time_limit_ns']==10000
            and metadata['step_limiter_charged_only'] is True,'Original secondary tracking policy differs')
    require(metadata['production_cut_um']==geometry['production_cut_um'] and metadata['max_step_um']==geometry['max_step_um'],
            'Actual native cut/step differs from the compiled input')
    require(status['state']=='COMPLETED' and status['events_completed']==request['event_count']
            and (folder/'transport-exit-code.txt').read_bytes().strip()==b'0','Actual original transport is incomplete or failed')
    probes=F.B.read_csv(folder/'geometry-probes-native.csv')
    requested=[line.split() for line in (folder/'geometry-probes.tsv').read_text().splitlines()]
    require(len(probes)==len(requested)>0 and all(
        row['passed']=='1' and row['expected_material']==row['native_material']==raw[3]
        and [F.B.value(row,axis+'_um') for axis in 'xyz']==list(map(float,raw[:3]))
        for row,raw in zip(probes,requested)),'Actual native material probes do not match the exact supplied geometry probes')
    built=F.B.read_csv(folder/'geometry-built.csv')
    expected_materials={'World':'G4_Galactic','R.Silicon':'G4_Si','R.Trench':'G4_SILICON_DIOXIDE',
                        'R.STI.minus':'G4_SILICON_DIOXIDE','R.STI.plus':'G4_SILICON_DIOXIDE'}
    require(len(built)==len(expected_materials) and {row['volume'] for row in built}==set(expected_materials)
            and all(row['overlap_check_passed']=='1' and row['material']==expected_materials[row['volume']] for row in built),
            'Actual native materials/overlap results differ')
    require(all(row['volume']=='World' or (abs(F.B.value(row,'density_g_cm3')-geometry['material_densities_g_cm3'][row['material']])<=1e-9
            and abs(F.B.value(row,'charged_max_step_um')-geometry['max_step_um'])<=1e-15) for row in built),
            'Actual native density/max-step differs')
    events=F.B.read_csv(folder/'events.csv')
    require(sorted(F.B.integer(row,'event_id') for row in events)==list(range(request['event_count']))
            and all(row['event_complete']=='1' for row in events),'Original full event denominator differs')
    tracks=F.B.read_csv(folder/'tracks.csv');steps=F.B.read_csv(folder/'steps.csv');births=F.B.read_csv(folder/'birth-links.csv')
    require(status['tracks_completed']==len(tracks) and status['steps_recorded']==len(steps),'Global native track/step completion differs')
    require(all(0<=F.B.integer(row,'event_id')<request['event_count'] for rows in (tracks,steps,births) for row in rows)
            and sum(F.B.integer(row,'track_count') for row in events)==len(tracks)
            and sum(F.B.integer(row,'step_count') for row in events)==len(steps)
            and len(births)==len(tracks)-sum(F.B.integer(row,'primary_count') for row in events),
            'Original event/ancestry population differs')
    event=next(row for row in events if F.B.integer(row,'event_id')==event_id)
    selected=lambda rows:[row for row in rows if F.B.integer(row,'event_id')==event_id]
    ancestry=F.B.ancestry(event,selected(tracks),selected(steps),selected(births))
    require(metadata['geometry']==geometry and metadata['geometry_sha256']==F.P.sha(folder/'geometry-contract.json')
            and metadata['contract_sha256']==metadata['geometry_sha256'],'Native embedded geometry differs from actual compiled input')
    return dict(schema='continuous-proton-native-event-binding-v2',version_id='v2-proton-bcat',
        condition_id=condition['condition_id'],split=condition['split'],final_holdout=condition['split']!='train',
        final_holdout_policy='never_for_tuning',particle='proton',source_family='geant4_complete_event',
        seed=request['seed'],transport_event_id=event_id,energy_MeV=request['energy_MeV'],angle_deg=request['theta_deg'],
        azimuth_deg=request['phi_deg'],position_um=request['target_um'],native_beam=beam,
        source_time_s=float(Decimal(condition['source_time_ns'])/Decimal('1e9')),geometry=semantic,
        geometry_contract=F.ref(folder/'geometry-contract.json'),device_geometry=F.ref(folder/'device-geometry-contract.json'),
        model_input=F.ref(folder/'model-input.json'),operation=F.ref(operation/'operation.json'),archive=F.ref(operation/'results.tar'),
        binary=F.ref(folder/'transport_bcat'),build_operation=F.ref(build/'operation.json'),build_archive=F.ref(build/'results.tar'),
        request=F.ref(folder/'request.json'),submitted_inputs_sha256=receipt['input_sha256'],
        original_event_count=request['event_count'],original_event_ids=list(range(request['event_count'])),
        original_ssh_exit_code=receipt['ssh_exit_code'],original_task_exit_code=receipt['operation_task_exit_code'],
        original_remote_exit_code=receipt['remote_exit_code'],original_collection_exit_code=receipt['collection_exit_code'],
        raw_event_files={name:F.ref(folder/name) for name in ('events.csv','tracks.csv','steps.csv','birth-links.csv','material-energy.csv')},
        process_inventory={name:F.ref(folder/name) for name in ('processes.csv','hadronic-models.csv','particles.csv')},
        matrix=F.ref(F.MATRIX),matrix_row=condition,ancestry=ancestry,implementation=F.ref(__file__),
        original_helpers=F.stable(),sn_axis_data_design_registered=False,
        shared_random_stream_key=condition['condition_id']+'-seed'+str(request['seed'])+'-event'+str(event_id),
        independent_sample_warning='Different SN variants sharing this stream are correlated, not extra independent primaries',
        native_source_qualified=False,pmi_r12_fixed=False)


def payload(operation,event_id,build,output,spacing_fraction=1/12,time_fraction=1/8):
    binding=audit_transport_event(operation,event_id,build)
    files=F.C.package_payload(operation,event_id,binding['source_time_s'],spacing_fraction,time_fraction)
    source=F.parse(files['source-contract.json'])
    rows=[list(map(float,line.split())) for line in files['sources.dat'].decode().splitlines()[1:]]
    geometry=F.read(binding['geometry_contract']['path'])
    reference=F.R.reference(rows,geometry);fine=F.R.reference(rows,geometry,abs_tol=F.R.ABS_TOL/4,rel_tol=F.R.REL_TOL/4)
    reference['refinement']=F.R.convergence(reference,fine)
    require(reference['refinement']['offline_charge_gate_passed'],'Original finite-Si charge quadrature did not converge')
    reference.update(stage='PRE_CLOCK_SOURCE_REFERENCE_NOT_NATIVE_QUALIFICATION',implementation=F.ref(F.R.__file__),
        inputs=dict(sources=dict(path=str(Path(output).resolve()/'sources.dat'),sha256=F.sha(files['sources.dat'])),
                    geometry=dict(path=str(Path(output).resolve()/'geometry-contract.json'),sha256=binding['geometry_contract']['sha256'])))
    files['source-reference-pre-clock.json']=F.encoded(reference)
    identity=binding['shared_random_stream_key']+'-sn'+str(binding['geometry']['sn_junction_depth_nm'])
    suggestions=[dict(response_id=identity+'-b'+str(bit),group_id=identity,event_identity=identity,
        condition_id=binding['condition_id'],particle='proton',split=binding['split'],
        gate_top_depth_nm=binding['geometry']['gate_top_depth_nm'],sn_junction_depth_nm=binding['geometry']['sn_junction_depth_nm'],
        energy_MeV=binding['energy_MeV'],angle_deg=binding['angle_deg'],stored_bit=bit,source_family='geant4_complete_event',
        seed=binding['seed'],transport_event_id=event_id) for bit in (0,1)]
    bundle=dict(schema='continuous-proton-source-bundle-v2',version_id='v2-proton-bcat',binding=binding,
        source_contract_sha256=F.sha(files['source-contract.json']),source_payload_sha256={name:F.sha(raw) for name,raw in files.items()},
        data_input_suggestions=suggestions,data_input_suggestions_are_registered=False,
        shared_random_stream_key=binding['shared_random_stream_key'],sn_axis_data_design_registered=False,
        role='SIGNAL' if source['fragment_count'] else 'STRUCTURAL_ZERO',
        all_event_steps_retained=binding['ancestry']['all_steps_retained'],no_late_secondary_clipping=True,
        required_source_window_s=source['required_source_window_s'],candidate_source_max_BE_dt_s=F.C.SIGMA/5,
        candidate_refined_source_max_BE_dt_s=F.C.SIGMA/10,
        actual_device_bindings_required=['matching original D3 model/geometry','actual successful D3 and matched A0',
            'physics_manifest_sha256','response contract and registered data input','source-wide actual BE/field/carrier qualification'],
        native_source_qualified=False,pmi_r12_fixed=False,
        boundary='Original transport event evidence only; HeavyIon and source features remain unregistered candidates')
    folder=Path(operation)/'collected'
    for name in ('geometry-contract.json','device-geometry-contract.json','model-input.json','request.json'):
        files[name]=(folder/name).read_bytes()
    files['event-binding.json']=F.encoded(binding);files['source-bundle.json']=F.encoded(bundle)
    files['data-input-suggestions.json']=F.encoded(suggestions)
    return files


def bundle(operation,event_id,build,output,spacing_fraction=1/12,time_fraction=1/8):
    files=payload(operation,event_id,build,output,spacing_fraction,time_fraction)
    return F.write_package(output,files,'complete_native_multi_condition_proton_event_candidate',
                           [__file__,T.__file__,T.G.__file__,F.__file__])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--operation',type=Path,required=True)
    p.add_argument('--event-id',type=int,required=True);p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--spacing-fraction',type=float,default=1/12);p.add_argument('--time-fraction',type=float,default=1/8)
    print(bundle(**vars(p.parse_args())))
