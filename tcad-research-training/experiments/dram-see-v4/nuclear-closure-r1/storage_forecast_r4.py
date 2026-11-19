"""Inactive, read-only fixed-input/variable-output storage estimate.

No scheduler, release, status, filesystem mutation or native command is called.
This is a conditional cost screen, not a bound on nuclear secondary multiplicity.
"""
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import tarfile

ROOT=Path(__file__).resolve().parents[3]
RUNTIME=Path('local_runtime/dram-see-v4/nuclear-closure-r1')
OPERATIONS=Path('local_runtime/dram-see-v4/transport-probe/operations')
FIXED_INPUT_ALLOWLIST=frozenset({
    'transport_matched','transport_matched.cc','matched-contract.json','geometry.hh',
    'geometry-contract.json','environment.sh','environment-spec.json','dataset-inventory.json',
})
SAFETY_MULTIPLIER=4
MINIMUM_FORECAST_BYTES=32*1024**2
JSON_LIMIT=8*1024**2


def require(condition,message):
    if not condition:raise ValueError(message)


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda:stream.read(1024**2),b''):digest.update(data)
    return digest.hexdigest()


def decode_json(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'Duplicate JSON key: '+key);result[key]=value
        return result
    def bad(value):raise ValueError('Nonfinite JSON constant: '+value)
    return json.loads(raw,object_pairs_hook=unique,parse_constant=bad)


def read(path):return decode_json(Path(path).read_bytes())


def ref(path,root):
    path=Path(path).resolve()
    return dict(path=path.relative_to(root).as_posix(),sha256=sha(path))


def inside(root,path):
    value=Path(path)
    if not value.is_absolute():value=root/value
    for component in (value,*value.parents):
        require(not component.is_symlink() and not (hasattr(component,'is_junction') and component.is_junction()),
                'Linked evidence paths are not accepted')
        if component==root:break
    value=value.resolve()
    require(value.is_relative_to(root),'Evidence path escapes repository')
    return value


def check_ref(root,item):
    require(isinstance(item,dict) and set(item)=={'path','sha256'},'Malformed evidence reference')
    path=inside(root,item['path'])
    require(path.is_file() and not path.is_symlink() and sha(path)==item['sha256'],'Missing/changed evidence: '+item['path'])
    return path


def member_name(name):
    path=PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and '\\' not in name and ':' not in name,
            'Unsafe archive member')
    return path.as_posix()


def archive_inventory(path,json_members=()):
    """Hash every member without extracting it or loading large CSVs into RAM."""
    inventory={};documents={};initial=sha(path)
    with tarfile.open(path) as archive:
        for member in archive:
            name=member_name(member.name)
            if member.isdir():continue
            require(member.isfile() and name!='.' and name not in inventory,'Linked/duplicate/nonfile archive member')
            digest=hashlib.sha256();parts=[]
            if name in json_members:require(member.size<=JSON_LIMIT,'JSON evidence exceeds bounded metadata size')
            with archive.extractfile(member) as stream:
                for chunk in iter(lambda:stream.read(1024**2),b''):
                    digest.update(chunk)
                    if name in json_members:parts.append(chunk)
            inventory[name]=dict(sha256=digest.hexdigest(),bytes=member.size)
            if name in json_members:documents[name]=decode_json(b''.join(parts))
    require(sha(path)==initial,'Archive changed during read')
    return inventory,documents,initial


def complete_operation(root,folder,allow_failed):
    path=folder/'operation.json';before=sha(path);row=read(path)
    require(row.get('schema')=='dram-see-v4-transport-operation-v1','Unknown native operation schema')
    states={'COLLECTED_PENDING_AUDIT','FAILED_COLLECTED'} if allow_failed else {'COLLECTED_PENDING_AUDIT'}
    require(row.get('state') in states,'Operation is unfinished, unknown or uncollected')
    require(row.get('label')==folder.name,'Native operation label differs from directory')
    require(all(type(row.get(k)) is int for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')),
            'Native exits must be known integers')
    require(row['collection_exit_code']==0,'Native collection did not complete')
    if row['state']=='COLLECTED_PENDING_AUDIT':
        require(row['ssh_exit_code']==row['remote_exit_code']==0,'Successful operation has nonzero native exits')
    else:require(row['ssh_exit_code']!=0 or row['remote_exit_code']!=0,'Failure state lacks a failed execution')
    require(sha(folder/'results.tar')==row.get('archive_sha256'),'Native result archive hash differs')
    require(sha(path)==before,'Operation receipt changed during read')
    return row,dict(path=path.relative_to(root).as_posix(),sha256=before)


def build_evidence(root,origin):
    folder=inside(root,origin['build_operation_path'])
    require(folder.parent==(root/OPERATIONS).resolve(),'Build is outside the original operation namespace')
    operation,operation_ref=complete_operation(root,folder,False)
    require(operation_ref['sha256']==origin['build_operation_sha256'],'Build origin receipt hash differs')
    inventory,_,archive_sha=archive_inventory(folder/'results.tar')
    require(archive_sha==operation['archive_sha256'],'Build archive identity differs')
    require(all(name in inventory and inventory[name]['sha256']==digest
                for name,digest in operation['input_sha256'].items()),'Build inputs differ from original archive')
    for name,item in inventory.items():
        local=inside(root,folder/'collected'/member_name(name))
        require(local.is_file() and local.stat().st_size==item['bytes'] and sha(local)==item['sha256'],
                'Retained build output differs from its archive: '+name)
    return dict(operation=operation_ref,archive=ref(folder/'results.tar',root),inventory=inventory)


def classify_record(path,root,builds):
    path=inside(root,path);initial=sha(path);record=read(path)
    require(record.get('schema')=='dram-see-v4-matched-run-r1','Unknown canonical transport record')
    label=record['run_id'];folder=(root/RUNTIME/'transport/runs'/label).resolve()
    require(path==folder/'record.json','Record is not in its canonical run directory')
    opfolder=(root/OPERATIONS/label).resolve()
    op_path=check_ref(root,record['operation_evidence'])
    require(op_path==opfolder/'operation.json','Record belongs to a different original operation')
    operation,operation_ref=complete_operation(root,opfolder,True)
    for exported,original in [('runner_exit_code','ssh_exit_code'),('remote_exit_code','remote_exit_code'),('collection_exit_code','collection_exit_code')]:
        require(type(record.get(exported)) is int and record[exported]==operation[original],'Record/native exit differs')
    archive_path=check_ref(root,record['raw_archive'])
    require(archive_path==opfolder/'results.tar' and record['raw_archive']['sha256']==operation['archive_sha256'],
            'Record archive belongs to another native operation')
    inventory,documents,archive_sha=archive_inventory(archive_path,{'request.json','package-origin.json','matched-contract.json','status.json'})
    require(archive_sha==operation['archive_sha256'],'Archive receipt changed')
    require({n:r['sha256'] for n,r in inventory.items()}==record['output_sha256'],'Record/full archive inventory differs')
    require(record['input_sha256']==operation['input_sha256'],'Original input inventories differ')
    for name,digest in record['input_sha256'].items():
        require(name in inventory and inventory[name]['sha256']==digest,'Original input changed inside results: '+name)
    for name,item in inventory.items():
        local=inside(root,folder/member_name(name))
        require(local.is_relative_to(folder) and local.is_file() and not local.is_symlink() and
                local.stat().st_size==item['bytes'] and sha(local)==item['sha256'],'Canonical exported member changed: '+name)
    request=record['request'];status=documents['status.json'];contract=documents['matched-contract.json']
    require(documents['request.json']==request and request['label']==label,'Raw request identity differs')
    require(request in contract['requests'],'Original request is absent from its archived contract')
    require(type(request.get('event_count')) is int and request['event_count']>=0,'Invalid requested event count')
    completed=status.get('events_completed')
    require(type(completed) is int and 0<=completed<=request['event_count'],'Invalid native completed-event count')
    if operation['state']=='COLLECTED_PENDING_AUDIT':
        require(status.get('state')=='COMPLETED' and completed==request['event_count'],'Successful native sample is incomplete')
    else:require(status.get('state')=='FAILED','Failed native sample lacks final failure status')
    origin=documents['package-origin.json']
    build_key=(origin['build_operation_path'],origin['build_operation_sha256'])
    if build_key not in builds:builds[build_key]=build_evidence(root,origin)
    build=builds[build_key];fixed={};variable={}
    for name,item in inventory.items():
        eligible=(name in FIXED_INPUT_ALLOWLIST and name in record['input_sha256'] and
                  name in build['inventory'] and item==build['inventory'][name])
        (fixed if eligible else variable)[name]=dict(item,classification='fixed_same_build_input' if eligible else 'variable_or_unproven')
    fixed_bytes=sum(x['bytes'] for x in fixed.values());variable_bytes=sum(x['bytes'] for x in variable.values())
    # Zero-event and pre-first-event failures are retained as an explicit
    # conservative per-requested-primary floor, never labelled a measured rate.
    denominator=max(1,completed)
    reason='actual_completed_primaries' if completed else 'zero_completed_archive_conservative_one_primary_floor_not_a_measurement'
    require(sha(path)==initial and sha(op_path)==operation_ref['sha256'] and sha(archive_path)==archive_sha,
            'Canonical evidence changed while classifying costs')
    return dict(record=dict(path=path.relative_to(root).as_posix(),sha256=initial),operation=operation_ref,
        archive=record['raw_archive'],build_operation=build['operation'],build_archive=build['archive'],
        native_state=operation['state'],scientific_pass_required=False,request=request,archived_contract=contract,
        requested_primaries=request['event_count'],completed_primaries=completed,
        variable_density_denominator=denominator,variable_density_basis=reason,
        fixed_files=fixed,variable_files=variable,fixed_bytes=fixed_bytes,variable_bytes=variable_bytes,
        total_output_bytes=fixed_bytes+variable_bytes,
        legacy_total_bytes_per_requested_primary=(fixed_bytes+variable_bytes)/request['event_count'] if request['event_count'] else None)


def forecast(request,records,*,repository_root=ROOT):
    """Estimate one future request using all canonical completed local records.

    records: paths to record.json (or canonical run directories). Every canonical
    record must be included, including failed scientific/native results. A mixed
    build history is rejected rather than guessing which future binary is meant.
    repository_root exists for isolated fixtures; production uses this repository.
    """
    root=Path(repository_root).resolve()
    require(isinstance(request,dict) and type(request.get('event_count')) is int and request['event_count']>0,
            'Forecast requires an explicit positive-primary frozen request')
    paths=[]
    for value in records:
        path=inside(root,value)
        if path.is_dir():path=path/'record.json'
        paths.append(path)
    require(paths and len(paths)==len(set(paths)),'Missing or duplicate history records')
    canonical=set((root/RUNTIME/'transport/runs').glob('*/record.json'))
    require(set(paths)==canonical,'Forecast must retain every canonical history record, including failures')
    builds={};samples=[classify_record(path,root,builds) for path in sorted(paths)]
    require(len(builds)==1,'Mixed build history: explicit independent design required; no silent sample exclusion')
    require(all(request in s['archived_contract']['requests'] for s in samples),'Future request differs from the same-build frozen manifest')
    # A fixed byte counts once only if its exact same identity is proven in every
    # history record as well as in the same immutable build archive.
    fixed_names=set.intersection(*(set(s['fixed_files']) for s in samples))
    fixed_names={name for name in fixed_names if len({(s['fixed_files'][name]['sha256'],s['fixed_files'][name]['bytes']) for s in samples})==1}
    for sample in samples:
        for name in set(sample['fixed_files'])-fixed_names:
            item=sample['fixed_files'].pop(name);item['classification']='variable_not_common_to_all_history';sample['variable_files'][name]=item
        sample['fixed_bytes']=sum(v['bytes'] for v in sample['fixed_files'].values())
        sample['variable_bytes']=sample['total_output_bytes']-sample['fixed_bytes']
        sample.pop('archived_contract')
    fixed=max(s['fixed_bytes'] for s in samples)
    densities=[Fraction(s['variable_bytes'],s['variable_density_denominator']) for s in samples]
    maximum=max(densities);n=request['event_count']
    old_densities=[Fraction(s['total_output_bytes'],s['requested_primaries']) for s in samples if s['requested_primaries']]
    require(old_densities,'No positive-primary historical archive; keep the existing initial conservative forecast')
    legacy=max(old_densities)
    estimate=max(MINIMUM_FORECAST_BYTES,math.ceil(SAFETY_MULTIPLIER*(fixed+maximum*n)))
    old=max(MINIMUM_FORECAST_BYTES,int(SAFETY_MULTIPLIER*legacy*n))
    require(canonical==set((root/RUNTIME/'transport/runs').glob('*/record.json')),
            'Canonical history changed during forecast; do not publish a partial-history estimate')
    return dict(schema='nuclear-closure-storage-forecast-r4',active=False,scientific_acceptance=False,
        implementation_sha256=sha(Path(__file__)),
        request=request,records=[s['record'] for s in samples],history=samples,
        canonical_history_complete=True,history_count=len(samples),build=next(iter(builds.values()))['operation'],
        fixed_input_allowlist=sorted(FIXED_INPUT_ALLOWLIST),fixed_names=sorted(fixed_names),
        fixed_bytes=fixed,fixed_history_max_bytes=fixed,
        variable_per_primary=float(maximum),variable_per_primary_exact=dict(numerator=maximum.numerator,denominator=maximum.denominator),
        variable_history_max_record=[s['record'] for s,d in zip(samples,densities) if d==maximum],
        legacy_history_max_total_bytes_per_primary=float(legacy),legacy_estimated_output_bytes=old,
        safety_multiplier=SAFETY_MULTIPLIER,minimum_forecast_bytes=MINIMUM_FORECAST_BYTES,
        formula='max(32 MiB, ceil(4 * (max_history_fixed_bytes + max_history_variable_bytes_per_primary * requested_primaries)))',
        estimated_output_bytes=estimate,
        retained_resource_policy=dict(existing_local_bytes='must still use complete measured retained resources, including all failed/duplicate archives',
            existing_remote_bytes='must still measure all retained remote stage resources',
            remote_free_floor_GiB=8,local_free_floor_GiB=20,total_retained_cap_GiB=160,
            local_extra_copy_allowance=3,total_extra_copy_allowance=4,
            threshold_changes=False,resources_deleted=False),
        limitations=['Conditional estimate only; not an upper bound on nuclear multiplicity or logs.',
            'Particle/process/physics inventories and all unknown files remain variable.',
            'No history maximum is reduced after a larger batch; no failed canonical record is excluded.',
            'Zero-completed samples contribute a conservative one-primary variable floor, not a fabricated observed primary.',
            'Old failures with no canonical record still belong in measured retained local/remote usage; no subtraction is permitted.',
            'No running-entry, release, budget or resource guard is changed by this helper.'])
