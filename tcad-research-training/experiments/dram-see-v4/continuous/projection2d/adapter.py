"""Read-only complete-event G3 adapters; preserve all native rows and identities.

No execution, collection, locking, scheduling, retry, or native API exists here.
The one historical replay is fixed before inspecting any device response.
"""
from __future__ import annotations
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tarfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
V1=HERE.parent/'proton'
HISTORICAL=ROOT/'local_runtime/dram-see-v4/transport-probe/operations/nc-r1-h-000'
KERNEL3=ROOT/'experiments/dram-see-v4/nuclear-closure-r1/source_kernel.py'
KERNEL3_SHA='2df1c3b86dc08e954f3f28d81cac7da41568bf885edb4d1ff559c48aec99aac4'
FC_PER_MEV=1e6/3.6*1.602176634e-19*1e15


def require(ok,message):
    if not ok:raise ValueError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def ref(path):return dict(path=str(Path(path).resolve()),sha256=digest(path))
def encoded(value):return (json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2)+'\n').encode()
def read_json(path):
    return json.loads(Path(path).read_bytes(),parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON '+v)))
def read_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream,strict=True);require(reader.fieldnames and len(reader.fieldnames)==len(set(reader.fieldnames)),'Missing/duplicate CSV columns')
        rows=list(reader)
    require(all(None not in row and all(v is not None for v in row.values()) for row in rows),'Malformed native CSV')
    return rows


def v1():
    manifest_path=ROOT/'local_runtime/dram-see-v4/continuous/proton/source-feature-v1-dependencies-r1/manifest.json'
    require(digest(manifest_path)=='9c4d7f042fc8685caae7c0af9cd65d88de05e53249dcdd28ff974ce4f876283c','Frozen v1 dependency manifest changed')
    manifest=read_json(manifest_path)
    for name in ('verifier','math','reference','proton_prepare','proton_coupler','proton_bundle'):
        item=manifest['dependencies'][name];path=ROOT/item['repository_relative_path']
        require(path.resolve()==Path(item['original_path']).resolve() and digest(path)==item['sha256'] and
                path.read_bytes()==(manifest_path.parent/item['backup_relative_path']).read_bytes(),'Frozen input auditor changed: '+name)
    path=V1/'source_features.py';spec=importlib.util.spec_from_file_location('_projection_fixed_v1_source',path)
    value=importlib.util.module_from_spec(spec);exec(compile(path.read_bytes(),str(path),'exec'),value.__dict__)
    return value


def reconstruct(event,tracks,steps,births,metadata,epoch_s,axis_map,context):
    require(math.isfinite(epoch_s) and epoch_s>=0,'Explicit finite input epoch is required')
    require(axis_map in ([0,1,2],[0,2,1]),'Unregistered transport coordinate mapping')
    require(digest(KERNEL3)==KERNEL3_SHA,'Original continuous G3 definition changed')
    F=v1()
    with F.proton_modules() as (_,__,B):tree=B.ancestry(event,tracks,steps,births)
    terms=[];records=[];material_energy={};lineage={row['track_id']:row for row in tree['lineage']}
    for row in steps:
        raw_energy=float(row['ionizing_MeV']);mat=row['pre_material'];material_energy.setdefault(mat,[]).append(raw_energy)
        pre=[float(row['pre_'+a+'_um']) for a in 'xyz'];post=[float(row['post_'+a+'_um']) for a in 'xyz']
        p0=[pre[i] for i in axis_map];p1=[post[i] for i in axis_map]
        identity={k:int(row[k]) for k in ('event_id','track_id','parent_id','step_id')}
        uid='e{event_id}:t{track_id}:p{parent_id}:s{step_id}'.format(**identity)
        t0=epoch_s+float(row['pre_t_ns'])*1e-9;t1=epoch_s+float(row['post_t_ns'])*1e-9
        require(all(math.isfinite(v) for v in (*p0,*p1,t0,t1)) and 0<=t0<=t1,'Nonfinite/rollback native source endpoint')
        disposition='NON_SILICON_ENERGY_ONLY' if mat!='G4_Si' else ('ZERO_IONIZING' if raw_energy==0 else 'ACTIVE_SILICON_KERNEL')
        record=dict(uid=uid,identity=identity,original_native_step=dict(row),physical_p0_um=p0,physical_p1_um=p1,
            physical_y_endpoints_um=[p0[1],p1[1]],input_epoch_s=epoch_s,physical_t0_s=t0,physical_t1_s=t1,
            disposition=disposition,ancestor_track_ids=lineage[identity['track_id']]['ancestor_track_ids'],
            original_birth_token=lineage[identity['track_id']]['birth_token'])
        records.append(record)
        if disposition=='ACTIVE_SILICON_KERNEL':
            terms.append(dict(uid=uid,p0_um=p0,p1_um=p1,t0_s=t0,t1_s=t1,charge_fC=raw_energy*FC_PER_MEV,
                width_um=.03,sigma_s=2e-12,identity=identity,zero_length_preserved=(p0==p1)))
    return dict(schema='dram-see-v4-reconstructed-proton-g3-event-r1',particle='proton',representation='correlated-endpoint-gaussian-r1',
        event_id=int(event['event_id']),seed=int(metadata['seed']),energy_MeV=float(metadata['energy_MeV']),
        angle_deg=float(metadata.get('theta_deg',metadata.get('angle_deg'))),epoch_s=epoch_s,
        axis_map_physical_from_original_indices=axis_map,original_native_axes_retained=True,
        original_event=event,original_tracks=tracks,original_birth_links=births,ancestry=tree,
        step_records=records,terms=terms,all_selected_event_steps_retained=len(records)==int(event['step_count']),
        all_material_ionizing_MeV={name:math.fsum(values) for name,values in sorted(material_energy.items())},
        non_silicon_ionizing_energy_MeV=math.fsum(float(row['ionizing_MeV']) for row in steps if row['pre_material']!='G4_Si'),
        original_positive_Si_charge_fC=math.fsum(term['charge_fC'] for term in terms),
        continuous_reconstruction_reference=ref(KERNEL3),context=context,
        is_native_G3_field=False,is_native_G2_field=False,native_source_qualified=False,pmi_r12_fixed=False)


def archive_matches(archive,folder,names):
    """Compare bytes with existing archive, never extract or collect any files."""
    with tarfile.open(archive,'r:') as tar:
        members={}
        for member in tar.getmembers():
            key=member.name.removeprefix('./')
            if key in names:
                require(key not in members and member.isfile(),'Ambiguous/non-file original archive member')
                members[key]=member
        require(set(members)==set(names),'Original archive lacks required event evidence')
        for name in names:
            stream=tar.extractfile(members[name]);require(stream is not None,'Missing archived raw stream')
            require(hashlib.file_digest(stream,'sha256').hexdigest()==digest(folder/name),'Collected bytes differ from original archive: '+name)


def historical_event0(epoch_s):
    """Fixed old planar request/event0 only; not admissible as an r14 BCAT source."""
    folder=HISTORICAL/'collected';operation=read_json(HISTORICAL/'operation.json')
    require(operation['schema']=='dram-see-v4-transport-operation-v1' and operation['label']=='nc-r1-h-000' and
            all(operation[key]==0 for key in ('ssh_exit_code','remote_exit_code','collection_exit_code')),'Original historical request is not complete')
    require(digest(HISTORICAL/'results.tar')==operation['archive_sha256'],'Original historical archive identity differs')
    names=('metadata.json','status.json','events.csv','tracks.csv','steps.csv','birth-links.csv','geometry-contract.json','request.json','exit-code.txt')
    archive_matches(HISTORICAL/'results.tar',folder,names)
    require(int((folder/'exit-code.txt').read_text())==0,'Historical native task failed')
    metadata=read_json(folder/'metadata.json');status=read_json(folder/'status.json')
    require(metadata['geometry_id']=='planar-l025-extruded-w100-3d-r1' and metadata['seed']==50150001 and
            metadata['energy_MeV']==100 and metadata['angle_deg']==0 and metadata['events_requested']==1000,
            'Fixed historical development replay identity differs')
    require(status['state']=='COMPLETED' and status['events_completed']==status['events_requested']==1000,'Historical request incomplete')
    for name,expected in operation['input_sha256'].items():
        require(digest(folder/name)==expected,'Original historical input changed: '+name)
    require(digest(folder/'geometry-contract.json')==metadata['geometry_sha256'],'Historical material geometry identity differs')
    events=read_csv(folder/'events.csv');tracks=read_csv(folder/'tracks.csv');steps=read_csv(folder/'steps.csv');births=read_csv(folder/'birth-links.csv')
    require([int(row['event_id']) for row in events]==list(range(1000)) and all(row['event_complete']=='1' for row in events),
            'Historical event denominator incomplete')
    require(len(tracks)==status['tracks_completed'] and len(steps)==status['steps_recorded'] and
            sum(int(e['track_count']) for e in events)==len(tracks) and sum(int(e['step_count']) for e in events)==len(steps),
            'Historical complete-request track/step denominator differs')
    selected=lambda rows:[row for row in rows if row['event_id']=='0']
    context=dict(scope='HISTORICAL_PLANAR_KERNEL_REPLAY_NOT_R14_SOURCE',registered_r14_source=False,
        selection='Fixed original nc-r1-h-000 event0; not selected using any device response',
        original_operation=ref(HISTORICAL/'operation.json'),original_archive=ref(HISTORICAL/'results.tar'),
        original_input_archive=ref(HISTORICAL/'inputs.tar'),original_binary=ref(folder/'transport_matched'),
        original_files={name:ref(folder/name) for name in names},original_request_denominator=events,
        unprojected_original_event_ids=list(range(1,1000)),unprojected_reason='Outside this fixed arithmetic replay; retained in original complete-request denominator',
        original_geometry=read_json(folder/'geometry-contract.json'))
    return reconstruct(events[0],selected(tracks),selected(steps),selected(births),metadata,epoch_s,[0,2,1],context)


def bcat_bundle(source_dir):
    """Original BCAT source bundle must exist and pass its full original auditor."""
    source_dir=Path(source_dir).resolve();bundle=read_json(source_dir/'source-bundle.json');source=read_json(source_dir/'source-contract.json')
    require(bundle['schema']=='continuous-proton-source-bundle-v1','Unsupported original BCAT source bundle')
    binding=bundle['binding'];row=binding['matrix_row']
    require(row['split']=='train' and float(row['energy_MeV'])<=100 and float(row['gate_top_depth_nm'])<=80,
            'Final holdout source is unavailable for projection development')
    F=v1()
    with F.proton_modules() as (_,C,B):
        operation=Path(binding['operation']['path']).parent;build=Path(binding['build_operation']['path']).parent
        require(B.audit_transport_event(operation,binding['transport_event_id'],build)==binding,'Original full event binding changed')
        payload=C.package_payload(operation,binding['transport_event_id'],source['epoch_s'],
            source['approximation']['let_node_width_fraction'],source['approximation']['max_segment_time_sigma_fraction'])
        require(all((source_dir/name).read_bytes()==raw for name,raw in payload.items()),'Original G3 source bundle differs from full event')
    raw=binding['raw_event_files'];events=read_csv(raw['events.csv']['path']);eid=binding['transport_event_id']
    select=lambda rows:[item for item in rows if int(item['event_id'])==eid]
    event=select(events);require(len(event)==1,'Original selected event missing')
    context=dict(scope='BCAT_SOURCE_MATHEMATICAL_PROJECTION_PENDING_NEW_RESPONSE_REGISTRATION',registered_r14_source=False,
        original_bundle=ref(source_dir/'source-bundle.json'),original_source_contract=ref(source_dir/'source-contract.json'),
        original_geometry=read_json(source_dir/'geometry-contract.json'),original_geometry_file=ref(source_dir/'geometry-contract.json'),
        original_binding=binding,original_request_denominator=events,
        unprojected_original_event_ids=[int(e['event_id']) for e in events if int(e['event_id'])!=eid],
        unprojected_reason='Other events remain in original request denominator; each requires its own projection')
    return reconstruct(event[0],select(read_csv(raw['tracks.csv']['path'])),select(read_csv(raw['steps.csv']['path'])),
        select(read_csv(raw['birth-links.csv']['path'])),source['metadata'],source['epoch_s'],[0,1,2],context)
