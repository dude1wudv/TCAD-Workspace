"""Current S2 run input / complete-event source bundle; never dispatch native work.

Existing prepare.py owns receipt semantics. Existing couple.py owns the source
representation. Existing data/field_adapter.py owns native field extraction.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import couple
import prepare
import source_reference as REF

HERE=Path(__file__).resolve().parent
ROOT=prepare.ROOT
MATRIX=ROOT/'experiments/dram-see-v4/course-plan-r13/finite-matrix.proposed.csv'
COMPILED=ROOT/'local_runtime/dram-see-v4/transport-probe/operations/cgoal-bcat-build-20261017t043911z'
TOL=dict(energy_abs_MeV=1e-12,energy_relative=1e-9)
require=REF.require
read_json=REF.read_json
CORE_INPUTS=('transport_bcat','transport_bcat.cc','geometry.hh','geometry-contract.json','model-input.json',
             'request.json','environment.sh','dataset-inventory.json','input-manifest.json','task.sh')
EVENT_OUTPUTS=('transport-exit-code.txt','status.json','metadata.json','events.csv','tracks.csv','steps.csv','birth-links.csv',
               'geometry-probes-native.csv','geometry-built.csv','processes.csv','hadronic-models.csv','particles.csv','material-energy.csv')


def ref(path):return dict(path=str(Path(path).resolve()),sha256=prepare.sha(path))


def conditions():
    with MATRIX.open(encoding='utf-8-sig',newline='') as stream:
        return [row for row in csv.DictReader(stream) if row['particle']=='proton']


def condition(condition_id,seed,development=False):
    found=[row for row in conditions() if row['condition_id']==condition_id]
    require(len(found)==1,'Condition is absent/ambiguous in the preserved proton matrix')
    row=found[0]
    require(row['size_id']=='S2' and float(row['gate_top_depth_nm'])==80.,
            'Current compiled transport is S2 only; S1/S3 need their actual D3 geometry and separate compile')
    require(type(seed) is int and seed in [int(x) for x in row['proposed_seeds'].split('|')],
            'Seed must belong to the explicit current condition; new sampling needs an explicit design record')
    if development:require(row['split']=='train','Final holdout is unavailable to the current development run entry')
    require(float(row['energy_MeV']) in (50.,100.,150.) and float(row['angle_deg']) in (0.,30.),'Unexpected proton matrix axes')
    require(float(row['azimuth_deg'])==180. and [float(row['start_'+a+'_nm']) for a in 'xyz']==[-52.,0.,0.],
            'Proton incidence position/azimuth changed')
    return row


def condition_for_request(request):
    found=[row for row in conditions() if row['size_id']=='S2' and float(row['energy_MeV'])==request['energy_MeV']
           and float(row['angle_deg'])==request['theta_deg'] and request['seed'] in [int(x) for x in row['proposed_seeds'].split('|')]]
    require(len(found)==1,'Original request does not identify one preserved condition/seed')
    return condition(found[0]['condition_id'],request['seed'])


def validate_s2_geometry(geometry,model):
    g=model['geometry'];d=model['doping'];actual=geometry['geometry']
    require(g['gate_top_depth_nm']==80 and d['sn_junction_depth_nm']==87 and g['active_width_nm']==20
            and g['metal_bottom_z_nm']==150,'S2 compiled-model semantic identity changed')
    require(actual['dimension']==3 and actual['length_unit']=='um' and actual['gate_void']['top_um']==.08
            and actual['gate_void']['bottom_um']==.15,'Compiled transport geometry is not the current S2 3D model')
    require(geometry['gate_transport_material']=='G4_Galactic','Unregistered gate transport-material change')
    return dict(size_id='S2',gate_top_depth_nm=80.,sn_junction_depth_nm=87.,active_width_nm=20.,
                metal_deepest_nm=150.,coordinate_transform=geometry['coordinate_transform'],
                gate_transport_material='G4_Galactic',gate_limitation=geometry['gate_limitation'])


def prepare_run(output,label,condition_id='proton-T04',seed=61017041,events=1,build=COMPILED,initialization_only=False):
    row=condition(condition_id,seed,development=True)
    build,receipt=prepare.complete_operation(build,('transport_bcat','compile-exit-code.txt','build-sha256.txt'))
    folder=build/'collected';geometry=read_json(folder/'geometry-contract.json');model=read_json(folder/'model-input.json')
    validate_s2_geometry(geometry,model)
    require(geometry['model_sha256']==prepare.sha(folder/'model-input.json'),'Compiled model/geometry identity mismatch')
    require(type(events) is int and events>0,'Physical batch size must be explicit and positive, not a resource quota')
    return prepare.transport_run(output=output,operation=build,label=label,arm='H',seed=seed,
        events=0 if initialization_only else events,energy=float(row['energy_MeV']),theta=float(row['angle_deg']),
        target_x=-.052,target_y=0.,phi=180.)


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream,strict=True)
        require(reader.fieldnames and len(set(reader.fieldnames))==len(reader.fieldnames),'Missing/duplicate CSV columns')
        rows=list(reader)
    require(all(None not in row and all(v is not None for v in row.values()) for row in rows),'Malformed CSV record')
    return rows


def integer(row,key):
    value=row[key];require(re.fullmatch(r'-?\d+',value) is not None,'Invalid native integer '+key)
    return int(value)


def value(row,key):
    result=float(row[key]);require(math.isfinite(result),'Nonfinite native '+key);return result


def close(a,b):return abs(a-b)<=TOL['energy_abs_MeV']+TOL['energy_relative']*max(abs(a),abs(b))


def native_beam(request,metadata):
    """Check measured native setup against the submitted surface-target request."""
    theta=math.radians(request['theta_deg']);phi=math.radians(request['phi_deg'])
    direction=[math.sin(theta)*math.cos(phi),math.sin(theta)*math.sin(phi),math.cos(theta)]
    start=[x-d/direction[2] for x,d in zip(request['target_um'],direction)]
    # This tolerance only covers 17-digit serialization/trigonometric roundoff,
    # not a beam-position or direction acceptance tolerance for the experiment.
    for key,expected in [('surface_position_um',request['target_um']),('beam_direction',direction),('beam_position_um',start)]:
        actual=metadata[key]
        require(isinstance(actual,list) and len(actual)==3 and all(math.isfinite(v) and abs(v-e)<=1e-12
                for v,e in zip(actual,expected)),'Actual native beam setup differs: '+key)
    require(metadata['request_label']==request['label'],'Native request label differs from submitted label')
    return dict(surface_position_um=metadata['surface_position_um'],beam_start_um=metadata['beam_position_um'],
                direction=metadata['beam_direction'],serialization_tolerance=1e-12,
                tolerance_units='um for positions, dimensionless for direction')


def ancestry(event,tracks,steps,births):
    """Reconstruct all selected-event ancestry from native IDs and exact birth tokens.

    This does not impose deposited energy <= primary kinetic energy, discard
    secondaries, demand a nuclear event, or turn a replay into a new primary.
    """
    eid=integer(event,'event_id')
    require(event['event_complete']=='1' and integer(event,'primary_count')==1,'Incomplete/aborted or non-single-primary event')
    require(all(integer(row,'event_id')==eid for rows in (tracks,steps,births) for row in rows),'Mixed native event IDs')
    by_track={integer(row,'track_id'):row for row in tracks}
    require(len(by_track)==len(tracks)==integer(event,'track_count') and all(t>0 for t in by_track),'Duplicate/missing native track')
    primaries=[t for t,row in by_track.items() if integer(row,'parent_id')==0]
    require(len(primaries)==1 and by_track[primaries[0]]['particle']=='proton','Single true proton primary not retained')
    primary=primaries[0];by_step={};track_steps=defaultdict(list)
    require(integer(by_track[primary],'pdg')==2212 and by_track[primary]['creator_process']=='none' and
            integer(by_track[primary],'creator_type')==-1 and integer(by_track[primary],'creator_subtype')==-1,
            'Original primary creator/particle identity differs')
    event_hadronic=False;track_hadronic=defaultdict(bool)
    for row in steps:
        tid=integer(row,'track_id');sid=integer(row,'step_id');key=(tid,sid)
        require(tid in by_track and sid>0 and key not in by_step,'Orphan/duplicate native step')
        track=by_track[tid]
        require(integer(row,'parent_id')==integer(track,'parent_id') and row['particle']==track['particle']
                and integer(row,'pdg')==integer(track,'pdg'),'Step/track identity mismatch')
        energies=[value(row,k) for k in ('edep_MeV','niel_MeV','ionizing_MeV')]
        require(all(v>=0 for v in energies) and close(energies[0]-energies[1],energies[2]),'Invalid original step energy split')
        require(value(row,'post_t_ns')>=value(row,'pre_t_ns'),'Native step time rollback')
        interaction=integer(row,'post_process_type')==4
        require(integer(row,'track_hadronic_before')==int(track_hadronic[tid]) and
                integer(row,'track_hadronic_after')==int(track_hadronic[tid] or interaction),
                'Step hadronic state differs from actual native process history')
        require(integer(row,'primary_hadronic_seen_before')==int(event_hadronic),'Event primary hadronic history differs')
        track_hadronic[tid]=track_hadronic[tid] or interaction
        event_hadronic=event_hadronic or (tid==primary and interaction)
        require(integer(row,'primary_hadronic_seen_after')==int(event_hadronic),'Event primary transition differs')
        by_step[key]=row;track_steps[tid].append(row)
    require(len(steps)==integer(event,'step_count'),'Missing event steps')
    for tid,track in by_track.items():
        selected=track_steps[tid]
        require(sorted(integer(row,'step_id') for row in selected)==list(range(1,integer(track,'step_count')+1)),
                'Native step sequence incomplete for track '+str(tid))
        for field,native in [('edep','edep_MeV'),('niel','niel_MeV'),('ionizing','ionizing_MeV')]:
            for scope,subset in [('all',selected),('si',[row for row in selected if row['pre_material']=='G4_Si'])]:
                require(close(math.fsum(value(row,native) for row in subset),value(track,field+'_'+scope+'_MeV')),
                        'Track step/energy ledger does not close')
    require(sum(row['pre_material']=='G4_Si' for row in steps)==integer(event,'si_step_count'),'Si step count differs')
    for field,native in [('edep','edep_MeV'),('niel','niel_MeV'),('ionizing','ionizing_MeV')]:
        for scope,subset in [('all',steps),('si',[row for row in steps if row['pre_material']=='G4_Si']),
                             ('world',[row for row in steps if row['pre_volume']=='World'])]:
            require(close(math.fsum(value(row,native) for row in subset),value(event,field+'_'+scope+'_MeV')),
                    'Complete event step/energy ledger does not close')
    by_child={};by_parent_step=defaultdict(list);tokens=set()
    for link in births:
        child=integer(link,'child_track_id');parent=integer(link,'parent_track_id');sid=integer(link,'parent_step_id')
        ordinal=integer(link,'secondary_ordinal');key=(parent,sid)
        require(child in by_track and parent in by_track and key in by_step and child not in by_child,'Orphan/duplicate exact birth binding')
        token=f'e{eid}:t{parent}:s{sid}:n{ordinal}'
        require(ordinal>0 and link['birth_token']==token and token not in tokens,'Native birth token collision/mismatch')
        track=by_track[child];step=by_step[key]
        require(integer(track,'parent_id')==parent and integer(track,'parent_step_id')==sid and track['birth_token']==token,
                'Track and native birth-link identity differ')
        require(all(track[k]==link[k] for k in ('creator_process','creator_type','creator_subtype')),'Child creator identity differs')
        require(link['parent_hadronic_before']==step['track_hadronic_before'] and link['parent_hadronic_after']==step['track_hadronic_after'],
                'Parent hadronic transition binding differs')
        by_child[child]=link;by_parent_step[key].append(link);tokens.add(token)
    require(set(by_child)==set(by_track)-{primary},'Every transported secondary must retain one actual birth link')
    for key,step in by_step.items():
        require(sorted(integer(row,'secondary_ordinal') for row in by_parent_step[key])==list(range(1,integer(step,'secondary_count')+1)),
                'Current-step secondary enumeration is incomplete')
    lineage=[]
    for tid,track in sorted(by_track.items()):
        ids=[];cursor=tid
        while cursor:
            require(cursor in by_track and cursor not in ids,'Missing ancestor or cycle in native track graph')
            ids.append(cursor);cursor=integer(by_track[cursor],'parent_id')
        require(ids[-1]==primary,'Track does not descend from the original proton')
        direct=integer(track,'creator_type')==4
        hadronic=any(integer(by_track[t],'creator_type')==4 for t in ids)
        if tid==primary:
            require(track['birth_token']=='primary' and integer(track,'parent_step_id')==0,'Primary falsely has a secondary binding')
        else:
            link=by_child[tid];parent=integer(track,'parent_id');em=integer(track,'creator_type')==2
            flags=dict(direct_hadronic_child=direct,creator_lineage_hadronic=hadronic,
                em_from_hadronic_lineage=em and any(integer(by_track[t],'creator_type')==4 for t in ids[1:]),
                em_from_post_hadronic_primary=em and parent==primary and link['parent_hadronic_before']=='1',
                em_in_primary_hadronic_transition_step=em and parent==primary and link['parent_hadronic_before']=='0' and link['parent_hadronic_after']=='1')
            require(all(integer(track,k)==int(v) for k,v in flags.items()),'Native ancestry flags differ from reconstructed parent chain')
        lineage.append(dict(track_id=tid,parent_id=integer(track,'parent_id'),ancestor_track_ids=ids[1:],
            birth_token=track['birth_token'],parent_step_id=integer(track,'parent_step_id'),particle=track['particle'],
            creator_process=track['creator_process'],creator_type=integer(track,'creator_type'),
            native_step_ids=sorted(integer(row,'step_id') for row in track_steps[tid]),
            has_hadronic_creator_ancestry=hadronic))
    return dict(schema='continuous-proton-complete-event-ancestry-v1',event_id=eid,primary_track_id=primary,
        track_count=len(tracks),step_count=len(steps),birth_link_count=len(births),all_steps_retained=True,
        zero_length_positive_si_steps=sum(row['pre_material']=='G4_Si' and value(row,'ionizing_MeV')>0 and
            all(value(row,'pre_'+axis+'_um')==value(row,'post_'+axis+'_um') for axis in 'xyz') for row in steps),
        actual_time_bounds_ns=[min(value(row,'pre_t_ns') for row in steps),max(value(row,'post_t_ns') for row in steps)] if steps else None,
        lineage=lineage,arithmetic_tolerances=TOL,passed=True,
        limits=['No nuclear/escaped/rest-mass energy balance claim','No particle-flux probability or transport convergence claim'])


def audit_transport_event(operation,event_id,build=COMPILED):
    """Public read-only recomputation interface used by data/source_bridge.py."""
    operation,receipt=prepare.complete_operation(operation,EVENT_OUTPUTS+CORE_INPUTS)
    require(receipt.get('schema')=='dram-see-v4-transport-operation-v2','Current source bundle requires v2 native original operation')
    folder=operation/'collected';request=read_json(folder/'request.json');metadata=read_json(folder/'metadata.json')
    status=read_json(folder/'status.json');geometry=read_json(folder/'geometry-contract.json');model=read_json(folder/'model-input.json')
    require(type(event_id) is int and 0<=event_id<request['event_count'],'Original event index outside recorded request')
    condition_row=condition_for_request(request);semantic=validate_s2_geometry(geometry,model)
    build,build_receipt=prepare.complete_operation(build,('transport_bcat','compile-exit-code.txt','build-sha256.txt'))
    require(request['source_operation_sha256']==prepare.sha(build/'operation.json') and
            prepare.sha(folder/'transport_bcat')==prepare.sha(build/'collected/transport_bcat'),
            'Native run is not bound to the selected original compiled binary')
    require(geometry['model_sha256']==prepare.sha(folder/'model-input.json'),'Source geometry/model identity differs')
    require(request['arm']==metadata['arm']=='H' and request['mode']==metadata['mode']=='normal' and metadata['primary_particle']=='proton',
            'Complete proton hadronic transport required')
    require(request['seed']==metadata['seed'] and request['energy_MeV']==metadata['energy_MeV'] and
            request['theta_deg']==metadata['angle_deg'] and request['event_count']==metadata['events_requested'],
            'Actual native beam/request identity differs')
    require(request['phi_deg']==180. and request['target_um']==[-.052,0.,0.], 'Original incidence point/azimuth differs')
    beam=native_beam(request,metadata)
    require(metadata['requested_threads']==1 and metadata['multithreaded_run_manager'] is False,'Original transport not single-threaded')
    require(status['state']=='COMPLETED' and status['events_completed']==request['event_count'] and
            (folder/'transport-exit-code.txt').read_bytes().strip()==b'0','Original transport incomplete/failed')
    for name in ('geometry-probes-native.csv','geometry-built.csv'):
        rows=read_csv(folder/name);key='passed' if name.startswith('geometry-probes') else 'overlap_check_passed'
        require(rows and all(row[key]=='1' for row in rows),'Original native geometry validation failed')
    events=read_csv(folder/'events.csv')
    require(sorted(integer(row,'event_id') for row in events)==list(range(request['event_count'])) and all(row['event_complete']=='1' for row in events),
            'Original completed-event denominator differs from requested primaries')
    all_tracks=read_csv(folder/'tracks.csv');all_steps=read_csv(folder/'steps.csv');all_births=read_csv(folder/'birth-links.csv')
    require(status['tracks_completed']==len(all_tracks) and status['steps_recorded']==len(all_steps),'Global native track/step completion differs')
    require(all(0<=integer(row,'event_id')<request['event_count'] for rows in (all_tracks,all_steps,all_births) for row in rows)
            and sum(integer(row,'track_count') for row in events)==len(all_tracks)
            and sum(integer(row,'step_count') for row in events)==len(all_steps)
            and len(all_births)==len(all_tracks)-sum(integer(row,'primary_count') for row in events),
            'Original multi-event population/ancestry denominator differs')
    event=next(row for row in events if integer(row,'event_id')==event_id)
    selected=lambda rows:[row for row in rows if integer(row,'event_id')==event_id]
    tree=ancestry(event,selected(all_tracks),selected(all_steps),selected(all_births))
    build_hash=next(digest for digest,name in (line.split(None,1) for line in (folder/'build-sha256.txt').read_text().splitlines())
                    if name.strip()=='transport_bcat')
    require(build_hash==prepare.sha(folder/'transport_bcat'),'Actual native transport binary differs from compiled identity')
    source=metadata['geometry'];require(source==geometry and metadata['geometry_sha256']==prepare.sha(folder/'geometry-contract.json'),
            'Native metadata geometry identity differs from actual input')
    # The metadata embeds the compile contract; its hash is over that exact JSON.
    return dict(schema='continuous-proton-native-event-binding-v1',condition_id=condition_row['condition_id'],
        split=condition_row['split'],final_holdout=condition_row['split']!='train',final_holdout_policy='never_for_tuning',
        particle='proton',source_family='geant4_complete_event',seed=request['seed'],transport_event_id=event_id,
        energy_MeV=request['energy_MeV'],angle_deg=request['theta_deg'],azimuth_deg=request['phi_deg'],
        position_um=request['target_um'],native_beam=beam,source_time_s=float(condition_row['source_time_ns'])*1e-9,
        geometry=semantic,geometry_contract=ref(folder/'geometry-contract.json'),model_input=ref(folder/'model-input.json'),
        operation=ref(operation/'operation.json'),archive=ref(operation/'results.tar'),binary=ref(folder/'transport_bcat'),
        build_operation=ref(build/'operation.json'),build_archive=ref(build/'results.tar'),
        request=ref(folder/'request.json'),submitted_inputs_sha256=receipt['input_sha256'],
        original_event_count=request['event_count'],original_event_ids=list(range(request['event_count'])),
        original_ssh_exit_code=receipt['ssh_exit_code'],original_task_exit_code=receipt['operation_task_exit_code'],
        original_remote_exit_code=receipt['remote_exit_code'],original_collection_exit_code=receipt['collection_exit_code'],
        raw_event_files={name:ref(folder/name) for name in ('events.csv','tracks.csv','steps.csv','birth-links.csv','material-energy.csv')},
        process_inventory={name:ref(folder/name) for name in ('processes.csv','hadronic-models.csv','particles.csv')},
        matrix=ref(MATRIX),matrix_row=condition_row,ancestry=tree,implementation_sha256=prepare.sha(__file__),
        native_source_qualified=False,pmi_r12_fixed=False)


def bundle(operation,event_id,output,spacing_fraction=1/12,time_fraction=1/8,build=COMPILED):
    binding=audit_transport_event(operation,event_id,build)
    files=couple.package_payload(operation,event_id,binding['source_time_s'],spacing_fraction,time_fraction)
    source_contract=json.loads(files['source-contract.json']);source_hash=hashlib.sha256(files['source-contract.json']).hexdigest()
    identity=binding['condition_id']+'-seed'+str(binding['seed'])+'-event'+str(event_id)
    suggestions=[]
    for bit in (0,1):
        suggestions.append(dict(response_id=identity+'-b'+str(bit),group_id=identity,event_identity=identity,
            condition_id=binding['condition_id'],particle='proton',split=binding['split'],gate_top_depth_nm=80.,sn_junction_depth_nm=87.,
            energy_MeV=binding['energy_MeV'],angle_deg=binding['angle_deg'],stored_bit=bit,source_family='geant4_complete_event',
            seed=binding['seed'],transport_event_id=event_id))
    rows=[list(map(float,line.split())) for line in files['sources.dat'].decode().splitlines()[1:]]
    geometry=read_json(binding['geometry_contract']['path'])
    initial_reference=REF.reference(rows,geometry)
    fine=REF.reference(rows,geometry,abs_tol=REF.ABS_TOL/4,rel_tol=REF.REL_TOL/4)
    initial_reference['refinement']=REF.convergence(initial_reference,fine)
    require(initial_reference['refinement']['offline_charge_gate_passed'],'Independent finite-Si quadrature did not converge')
    initial_reference.update(stage='PRE_CLOCK_SOURCE_REFERENCE_NOT_NATIVE_QUALIFICATION',implementation_sha256=prepare.sha(REF.__file__),
        inputs=dict(sources=dict(path=str(Path(output).resolve()/'sources.dat'),sha256=hashlib.sha256(files['sources.dat']).hexdigest()),
                    geometry=dict(path=str(Path(output).resolve()/'geometry-contract.json'),sha256=binding['geometry_contract']['sha256'])))
    files['source-reference-pre-clock.json']=prepare.encoded(initial_reference)
    contract=dict(schema='continuous-proton-source-bundle-v1',binding=binding,source_contract_sha256=source_hash,
        source_payload_sha256={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()},
        data_input_suggestions=suggestions,data_input_suggestions_are_registered=False,
        actual_device_bindings_required=['same actual D3 geometry','physics_manifest_sha256','circuit_contract_sha256','registered data-input identity'],
        source_spec_required=dict(schema='continuous-particle-source-spec-v1',particle='proton',
            role='SIGNAL' if source_contract['fragment_count'] else 'STRUCTURAL_ZERO',
            required_keys=['stored_bit','physics_manifest_sha256','source_contract_sha256','data_input_sha256']),
        native_field_interface=dict(adapter='experiments/dram-see-v4/continuous/data/field_adapter.py',
            field='HeavyIonGeneration',roles=['G','XG','YG','ZG','ONE'],carriers=['eDensity','hDensity']),
        time_requirements=dict(epoch_s=binding['source_time_s'],required_source_window_s=source_contract['required_source_window_s'],
            no_late_secondary_clipping=True,no_PMI_clock_synthesis=True,
            candidate_max_source_BE_dt_s=couple.SIGMA/5,candidate_refined_source_BE_dt_s=couple.SIGMA/10,
            source_dt_status='candidate numerical settings; actual BE source semantics and refinement unverified',
            collection_window_rule='Qcol and endpoint delta must use the same source-aware window; do not inherit alpha sigma=0.2ps start'),
        reference_interface=dict(module='experiments/dram-see-v4/continuous/proton/source_reference.py',
            pre_clock_reference_file='source-reference-pre-clock.json',
            command='source_reference.py --source BUNDLE/sources.dat --geometry BUNDLE/geometry-contract.json --clock ACTUAL_CLOCK --output NEW_REFERENCE',
            pre_clock_reference_is_not_native_qualification=True),
        final_holdout_policy='never_for_tuning',native_source_qualified=False,pmi_r12_fixed=False)
    files['geometry-contract.json']=Path(binding['geometry_contract']['path']).read_bytes()
    files['event-binding.json']=prepare.encoded(binding)
    files['source-bundle.json']=prepare.encoded(contract)
    files['data-input-suggestions.json']=prepare.encoded(suggestions)
    return prepare.write_package(output,files,'complete_native_proton_event_source_bundle')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('prepare-run');q.add_argument('--output',type=Path,required=True);q.add_argument('--label',required=True)
    q.add_argument('--build',type=Path,default=COMPILED);q.add_argument('--condition-id',default='proton-T04')
    q.add_argument('--seed',type=int,default=61017041);q.add_argument('--events',type=int,default=1);q.add_argument('--initialization-only',action='store_true')
    q=sub.add_parser('bundle');q.add_argument('--operation',type=Path,required=True);q.add_argument('--event-id',type=int,default=0)
    q.add_argument('--output',type=Path,required=True);q.add_argument('--spacing-fraction',type=float,default=1/12)
    q.add_argument('--time-fraction',type=float,default=1/8);q.add_argument('--build',type=Path,default=COMPILED)
    args=vars(p.parse_args());command=args.pop('command').replace('-','_');print(globals()[command](**args))
