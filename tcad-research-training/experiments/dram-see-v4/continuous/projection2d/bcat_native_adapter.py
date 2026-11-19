"""Strict complete-request BCAT export adapter, using original collected archives.

Reads only. Never executes transport, operation helpers, SSH, or collection.
The existing complete_operation function is used solely as a file auditor.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.util
import math
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
RUNTIME=ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/projection-implementation'
BUILD=ROOT/'local_runtime/dram-see-v4/transport-probe/operations/cgoal-bcat-build-20261017t043911z'
CPP_SHA='3954e216b0fca01610e213c9cc2242d225a7333156a44efd829343c83c1ababb'
FROZEN={'adapter.py':'3d078e0aa6cd38bc11dc7a4ae7c91d26585bbd5f33cb6a90931a9b645391d952',
        'kernel.py':'c9b44b5f808212a018dfa37542bc218410048ba05d9ee211b2bf933bc4d78069',
        'project.py':'b73bd65d93e1a0052bfa9a338885188ab0c15258397a5c2942f430d75ad8251d'}


def frozen(name):
    path=HERE/name;raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=FROZEN[name]:raise ValueError('Frozen projection dependency changed: '+name)
    spec=importlib.util.spec_from_file_location('_bcat_native_'+name.replace('.','_'),path)
    module=importlib.util.module_from_spec(spec);exec(compile(raw,str(path),'exec'),module.__dict__);return module
A=frozen('adapter.py');require=A.require
UNITS=dict(length='um',time='ns',energy='MeV',charge='eplus',direction='unit_vector')
VOLUMES={'World':'G4_Galactic','R.Silicon':'G4_Si','R.Trench':'G4_SILICON_DIOXIDE',
         'R.STI.minus':'G4_SILICON_DIOXIDE','R.STI.plus':'G4_SILICON_DIOXIDE'}
RAW_TABLES=('events.csv','tracks.csv','steps.csv','birth-links.csv','material-energy.csv',
            'geometry-probes-native.csv','geometry-built.csv')


def export_headers(cpp):
    raw=Path(cpp).read_bytes();require(A.sha(raw)==CPP_SHA,'Unregistered compiled BCAT exporter source')
    found={}
    for name,columns in re.findall(r'\(\s*"([^"\n]+\.csv)"\s*,\s*"([^"\n]+)"\s*\)',raw.decode()):
        values=columns.split(',')
        require(name not in found or found[name]==values,'Ambiguous native CSV declaration')
        found[name]=values
    require(all(name in found for name in RAW_TABLES),'Compiled exporter does not declare complete native tables')
    return found


def exact_csv(path,columns):
    with Path(path).open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream,strict=True)
        require(reader.fieldnames==columns,'Native CSV columns/order differ from compiled BCAT exporter: '+Path(path).name)
        rows=list(reader)
    require(all(None not in row and all(v is not None for v in row.values()) for row in rows),'Malformed native export row')
    return rows


def validate_metadata(request,metadata,geometry,model,B):
    expected_keys={'label','mode','arm','seed','event_count','energy_MeV','theta_deg','phi_deg','target_um','source_operation_sha256'}
    require(set(request)==expected_keys,'Request is not the current compiled prepare.transport_run format')
    require(type(request['event_count']) is int and request['event_count']>0 and type(request['seed']) is int and request['seed']>0,
            'Explicit complete primary request is missing')
    require(geometry.get('schema')=='continuous-bcat-proton-geometry-v1' and
            geometry.get('coordinate_transform')=='identity: TCAD x,y,z_depth in um = Geant4 x,y,z in um',
            'Only identity-axis BCAT geometry is supported; planar/implicit transforms are rejected')
    B.validate_s2_geometry(geometry,model)
    require(metadata.get('schema')=='v4-matched-transport-r1' and metadata.get('units')==UNITS,
            'Native exported units/schema missing or different; units are never supplied by adapter')
    require(metadata['geometry']==geometry and metadata['geometry_id']==model['model_id'],
            'Native embedded BCAT geometry differs')
    require(request['mode']==metadata['mode']=='normal' and request['arm']==metadata['arm']=='H'
            and metadata['primary_particle']=='proton','Original complete proton H transport required')
    for a,b in [('seed','seed'),('event_count','events_requested'),('energy_MeV','energy_MeV'),('theta_deg','angle_deg'),('label','request_label')]:
        require(request[a]==metadata[b],'Actual request/metadata mismatch: '+a)
    require(request['target_um']==[-.052,0.,0.] and request['phi_deg']==180.,'Unregistered input beam origin/azimuth')
    condition=[row for row in B.conditions() if float(row['gate_top_depth_nm'])==model['geometry']['gate_top_depth_nm']
               and float(row['energy_MeV'])==request['energy_MeV'] and float(row['angle_deg'])==request['theta_deg']]
    require(len(condition)==1 and condition[0]['split']=='train','Final or unregistered physical condition is not admitted for development')
    require(metadata['requested_threads']==1 and metadata['multithreaded_run_manager'] is False
            and metadata['run_manager']=='G4RunManager' and metadata['geant4_version_number']==1073,
            'Native software/thread identity differs')
    require(metadata['user_track_killing'] is False and metadata['standard_neutron_time_limit_ns']==10000
            and metadata['step_limiter_charged_only'] is True and metadata['output_precision_digits']==17,
            'Native tracking/export policy differs')
    require(metadata['production_cut_um']==geometry['production_cut_um'] and metadata['max_step_um']==geometry['max_step_um'],
            'Native cut/step differs from actual input')
    return condition[0],B.native_beam(request,metadata)


def validate_population(tables,status,count,B):
    events,tracks,steps,births=[tables[name] for name in ('events.csv','tracks.csv','steps.csv','birth-links.csv')]
    require(status['schema']=='v4-matched-transport-status-r1' and status['state']=='COMPLETED'
            and status['events_requested']==status['events_completed']==count,'Original request is incomplete')
    require(sorted(B.integer(e,'event_id') for e in events)==list(range(count)) and
            all(e['event_complete']=='1' and e['primary_count']=='1' for e in events),'Missing/duplicate/aborted primary event denominator')
    require(status['tracks_completed']==len(tracks) and status['steps_recorded']==len(steps)
            and sum(B.integer(e,'track_count') for e in events)==len(tracks)
            and sum(B.integer(e,'step_count') for e in events)==len(steps)
            and len(births)==len(tracks)-count,'Complete request track/step/birth denominator differs')
    grouped={eid:{name:[] for name in ('tracks.csv','steps.csv','birth-links.csv')} for eid in range(count)}
    for name in grouped[0]:
        for row in tables[name]:
            eid=B.integer(row,'event_id');require(eid in grouped,'Export row belongs to an undeclared event')
            grouped[eid][name].append(row)
    for row in steps:
        for key,value in row.items():
            # Native zero-path steps have undefined local LET; retain the empty value.
            if key=='local_ionizing_MeV_per_um' and value=='':
                require(B.value(row,'step_um')==0,'Only zero-path steps may have undefined local LET')
                continue
            if key.endswith(('_um','_MeV','_ns')) or key in ('pre_dx','pre_dy','pre_dz','post_dx','post_dy','post_dz'):
                require(math.isfinite(float(value)),'Nonfinite physical native step field: '+key)
        require(row['pre_volume'] in VOLUMES and row['pre_material']==VOLUMES[row['pre_volume']],
                'Native step has undeclared volume/material identity')
        path=B.value(row,'step_um');chord=B.value(row,'chord_um');ion=B.value(row,'ionizing_MeV')
        actual=math.sqrt(math.fsum((B.value(row,'post_'+axis+'_um')-B.value(row,'pre_'+axis+'_um'))**2 for axis in 'xyz'))
        require(path>=0 and chord>=0 and B.close(chord,actual) and chord<=path+1e-12+1e-9*path,
                'Actual native endpoint/chord/path identity differs')
        kind='zero_ionizing' if ion==0 else ('point_zero_length' if path==0 else ('point_zero_chord' if chord==0 else 'finite_path'))
        require(row['deposit_kind']==kind,'Native zero-length/deposit-kind identity differs')
        if path>0:require(B.close(float(row['local_ionizing_MeV_per_um']),ion/path),'Native per-path deposition identity differs')
        else:require(row['local_ionizing_MeV_per_um']=='','Zero path cannot have invented local LET')
    # Independent material ledger: every declared material exists even at zero.
    keys={};materials=set(VOLUMES.values())
    for row in tables['material-energy.csv']:
        key=(row['scope'],B.integer(row,'event_id'),B.integer(row,'track_id'),row['material'])
        require(key not in keys and key[0] in ('event','track') and key[1] in grouped and key[3] in materials,
                'Duplicate/invalid material energy ledger row')
        keys[key]=row
    expected=set()
    for event in events:
        eid=B.integer(event,'event_id');rows=grouped[eid]['steps.csv']
        groups=[('event',0,rows)]+[('track',B.integer(t,'track_id'),[s for s in rows if s['track_id']==t['track_id']])
                                  for t in grouped[eid]['tracks.csv']]
        for scope,tid,subset in groups:
            for material in materials:
                key=(scope,eid,tid,material);expected.add(key);require(key in keys,'Missing material ledger group')
                selected=[r for r in subset if r['pre_material']==material];row=keys[key]
                require(B.integer(row,'step_count')==len(selected),'Material ledger step count differs')
                for field in ('edep_MeV','niel_MeV','ionizing_MeV'):
                    require(B.close(math.fsum(B.value(s,field) for s in selected),B.value(row,field)),'Material ledger energy differs')
    require(set(keys)==expected,'Unexplained material ledger rows')
    return sorted(events,key=lambda row:B.integer(row,'event_id')),grouped


def audit(operation,epoch_s,build=BUILD):
    """Verify original run and reconstruct every primary event, without filtering."""
    require(math.isfinite(epoch_s) and epoch_s>=0,'Declared source epoch must be finite and nonnegative')
    F=A.v1()
    with F.proton_modules() as (P,_,B):
        outputs=tuple(set(B.EVENT_OUTPUTS+B.CORE_INPUTS+('geometry-probes.tsv','build-sha256.txt','materials.csv','cuts.csv')))
        operation,receipt=P.complete_operation(operation,outputs)
        require(receipt.get('schema')=='dram-see-v4-transport-operation-v2','BCAT adapter requires original verified operation v2')
        folder=operation/'collected'
        build,build_receipt=P.complete_operation(build,('transport_bcat','transport_bcat.cc','geometry.hh','geometry-contract.json',
            'model-input.json','geometry-probes.tsv','compile-exit-code.txt','build-sha256.txt'))
        require((build/'collected/compile-exit-code.txt').read_bytes().strip()==b'0','Original BCAT compile failed')
        columns=export_headers(build/'collected/transport_bcat.cc')
        request=A.read_json(folder/'request.json');metadata=A.read_json(folder/'metadata.json')
        geometry=A.read_json(folder/'geometry-contract.json');model=A.read_json(folder/'model-input.json');status=A.read_json(folder/'status.json')
        condition,beam=validate_metadata(request,metadata,geometry,model,B)
        require(request['label']==operation.name and request['source_operation_sha256']==P.sha(build/'operation.json'),
                'Original request is not bound to this operation and compiled build')
        for name in ('transport_bcat','transport_bcat.cc','geometry.hh','geometry-contract.json','geometry-probes.tsv','model-input.json','build-sha256.txt'):
            require((folder/name).read_bytes()==(build/'collected'/name).read_bytes(),'Run input is not byte-identical to original compiled input: '+name)
        require(geometry['model_sha256']==P.sha(folder/'model-input.json') and
                metadata['geometry_sha256']==metadata['contract_sha256']==P.sha(folder/'geometry-contract.json'),
                'Actual native geometry/model hash differs')
        manifest=A.read_json(folder/'input-manifest.json')
        require(manifest['schema']=='continuous-proton-inputs-v1' and manifest['kind']=='geant4_native_transport',
                'Original transport input manifest differs')
        require(all(P.sha(folder/name)==digest for name,digest in manifest['files'].items()),'Submitted transport input hash changed')
        require((folder/'transport-exit-code.txt').read_bytes().strip()==b'0','Original transport did not actually exit0')
        tables={name:exact_csv(folder/name,columns[name]) for name in RAW_TABLES}
        probes=[line.split() for line in (folder/'geometry-probes.tsv').read_text().splitlines()]
        require(len(tables['geometry-probes-native.csv'])==len(probes)>0 and all(
            row['passed']=='1' and row['native_material']==row['expected_material']==p[3] and
            [float(row[a+'_um']) for a in 'xyz']==list(map(float,p[:3]))
            for row,p in zip(tables['geometry-probes-native.csv'],probes)),'Native material probes differ from declared inputs')
        built=tables['geometry-built.csv']
        require(len(built)==len(VOLUMES) and {r['volume'] for r in built}==set(VOLUMES) and
                all(r['material']==VOLUMES[r['volume']] and r['overlap_check_passed']=='1' for r in built),
                'Native geometry material/overlap validation differs')
        for row in built:
            if row['volume']!='World':
                require(abs(float(row['density_g_cm3'])-geometry['material_densities_g_cm3'][row['material']])<=1e-9 and
                        abs(float(row['charged_max_step_um'])-geometry['max_step_um'])<=1e-15,'Native material density/step differs')
        events,grouped=validate_population(tables,status,request['event_count'],B)
        binding=dict(schema='dram-see-v4-bcat-native-complete-batch-binding-r1',
            adapter_stage='development_only',
            final_scoring_adapter_status='NOT_IMPLEMENTED_REQUIRES_AUTOMATIC_FROZEN_PREDICTION_BEFORE_SCORE_BINDING',
            operation=A.ref(operation/'operation.json'),archive=A.ref(operation/'results.tar'),
            build_operation=A.ref(build/'operation.json'),build_archive=A.ref(build/'results.tar'),binary=A.ref(folder/'transport_bcat'),
            compiled_exporter=A.ref(folder/'transport_bcat.cc'),request=A.ref(folder/'request.json'),
            geometry=A.ref(folder/'geometry-contract.json'),model=A.ref(folder/'model-input.json'),
            raw_files={name:A.ref(folder/name) for name in (*RAW_TABLES,'metadata.json','status.json','materials.csv','cuts.csv')},
            raw_columns={name:columns[name] for name in RAW_TABLES},actual_exported_units=metadata['units'],
            coordinate_transform=geometry['coordinate_transform'],condition=condition,seed=request['seed'],native_beam=beam,
            original_request_event_count=request['event_count'],original_request_event_ids=list(range(request['event_count'])),
            all_event_summaries=events,no_event_filter=True,epoch_s=epoch_s,
            original_exits={k:receipt[k] for k in ('ssh_exit_code','remote_exit_code','operation_task_exit_code','collection_exit_code')},
            adapter_implementation=A.ref(__file__),native_source_qualified=False,pmi_r12_fixed=False)
    sources=[]
    for event in events:
        eid=int(event['event_id']);rows=grouped[eid]
        context=dict(scope='BCAT_COMPLETE_REQUEST_INPUT_PROJECTION_PENDING_NATIVE_SOURCE_VALIDATION',
            registered_r14_source=False,original_geometry=geometry,original_batch_binding_sha256=A.sha(A.encoded(binding)),
            original_request_denominator=list(range(request['event_count'])),unprojected_original_event_ids=[],
            unprojected_reason='None: all original primary events retained as separate sources in this batch',
            original_files=binding['raw_files'],selection='All originally requested primaries, no charge/response/event filtering')
        sources.append(A.reconstruct(event,rows['tracks.csv'],rows['steps.csv'],rows['birth-links.csv'],metadata,epoch_s,[0,1,2],context))
    require([s['event_id'] for s in sources]==binding['original_request_event_ids'],'Adapter lost a primary event')
    return dict(binding=binding,sources=sources)


def build_package(operation,epoch_s,output,build=BUILD):
    output=Path(output).resolve();require(output.is_relative_to(RUNTIME.resolve()) and not output.exists(),'BCAT adapter output must be new in projection evidence directory')
    result=audit(operation,epoch_s,build)
    payload={'native-batch-binding.json':A.encoded(result['binding']),
             'replay-request.json':A.encoded(dict(operation=str(Path(operation).resolve()),build=str(Path(build).resolve()),epoch_s=epoch_s))}
    for source in result['sources']:payload[f'event-{source["event_id"]}-g3-source.json']=A.encoded(source)
    manifest=dict(schema='dram-see-v4-bcat-native-adapter-package-r1',
        files={name:A.sha(raw) for name,raw in payload.items()},event_ids=result['binding']['original_request_event_ids'],
        native_source_qualified=False,pmi_r12_fixed=False)
    output.mkdir(parents=True)
    for name,raw in {**payload,'adapter-manifest.json':A.encoded(manifest)}.items():
        with (output/name).open('xb') as stream:stream.write(raw)
    return manifest


def verify(package):
    package=Path(package);request=A.read_json(package/'replay-request.json');original=A.read_json(package/'adapter-manifest.json')
    result=audit(request['operation'],request['epoch_s'],request['build'])
    expected={'native-batch-binding.json':A.encoded(result['binding']),'replay-request.json':A.encoded(request)}
    expected.update({f'event-{source["event_id"]}-g3-source.json':A.encoded(source) for source in result['sources']})
    manifest=dict(schema='dram-see-v4-bcat-native-adapter-package-r1',files={n:A.sha(v) for n,v in expected.items()},
        event_ids=result['binding']['original_request_event_ids'],native_source_qualified=False,pmi_r12_fixed=False)
    require(original==manifest and all((package/n).read_bytes()==v for n,v in expected.items()),'BCAT adapter package does not equal full original-request recomputation')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    q=sub.add_parser('build');q.add_argument('--operation',type=Path,required=True);q.add_argument('--build',type=Path,default=BUILD)
    q.add_argument('--epoch',type=float,required=True);q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('verify');q.add_argument('--package',type=Path,required=True)
    args=parser.parse_args()
    result=build_package(args.operation,args.epoch,args.output,args.build) if args.command=='build' else verify(args.package)['binding']
    print(A.encoded(result).decode())
