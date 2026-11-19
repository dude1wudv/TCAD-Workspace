"""Native PMI field audit and read-only original-TDR operation preparation.

No SSH/subprocess dispatch occurs here. Source fields are validated against an
independent box-time oracle, with exact original BE intervals and complete PLTs.
"""
import argparse
import csv
import io
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import common as c
import build_cases as b

HERE,ROOT,RT=c.HERE,c.ROOT,c.RT
LIBRARIES={
 'experiments/dram-see-v4/source-probe/audit_probe.py':'d79c0c0989a15e074e39d6ec721b39b5430ded7d4b8f8b6c6f3de122f9fba1c1',
 'experiments/dram-see-v4/source-field-audit-r2/audit_fields.py':'5269653bccfabf0a30bd1d839d357fa5df9f5f738edd49df40b93c472d6d0272',
 'experiments/dram-see-v4/source-field-audit-3d-r1/audit_fields.py':'62a9273e780ef7d01ca18af3fc4b2e2a74fc5a54052a2652a27ccdd4bc2b1717',
 'experiments/dram-see-v4/source-field-audit-3d-r1/field_contract.json':'49b3283f32062192351043fb6c2c07c49c71e78519dc7f563d19c48aa5bd1ac2',
}
FRAME_RE=re.compile(r'gstep_b[0-9]+_[0-9]+_access_des\.tdr')
REFERENCE_MODE='referenced_original_tdr_not_copied'
CONVERSION=1e-12*1.602176634e-19*1e15
SCALAR='IntegrSemiconductor PMIRecombination'
NATIVE_FIELDS={'G':'NC_G','G_CHECK':'PMIUserField0','XG':'NC_XG','YG':'NC_YG','ZG':'NC_ZG','ONE':'NC_One'}
OTHER_FIELDS={'N':'eDensity','P':'hDensity','T_PMI':'PMIUserField1','DT_PMI':'PMIUserField2','STEP_PMI':'PMIUserField3'}
NATIVE_OUTPUTS={'field-measurements.csv','field-inventory.csv','tdr-state-metadata.csv','geometry-probes.csv',
                'source-reference-checks.csv','diagnostic-status.txt','svisual.log','svisual-exit-code.txt',
                'tool-versions.txt','affinity.txt'}
OP_INPUTS={'extract_fields.tcl','measurement-config.tcl','source-case.txt','source-directory.txt','tdr-files.txt',
           'tdr-sha256.txt','source-evidence.json','source-provenance.json','task.sh'}


def libraries():
    for name,sha in LIBRARIES.items():c.require(c.sha(ROOT/name)==sha,'Frozen audit helper changed: '+name)
    return c.module(HERE.parent/'source-field-audit-3d-r1/audit_fields.py','_nuclear_readonly_fields')


def roi_boxes(qualification):
    if not qualification:
        value=c.read(HERE.parent/'source-field-audit-3d-r1/field_contract.json')['rois_um6']
        return {key:[v[:3],v[3:]] for key,v in value.items()}
    lo,hi=b.QUAL_BOX
    result={'Total':[list(lo),list(hi)]}
    for axis,names,cuts in [(0,['Left','Right'],[-.09,0,.09]),
                             (1,['Low','Middle','High'],[-.09,-.03,.03,.09]),
                             (2,['ZNegative','ZPositive'],[-.09,0,.09])]:
        for name,a,z in zip(names,cuts,cuts[1:]):
            low,high=list(lo),list(hi);low[axis],high[axis]=a,z;result[name]=[low,high]
    return result


def geometry_points(qualification):
    if qualification:return [(name,0.,y,z) for name,y in [('lower',-.04),('center',0.),('upper',.04)] for z in (-.05,0.,.05)]
    return [(name,x,y,z) for name,x,y in [('source',.1,.02),('drain',.75,.02),('bulk',.425,.6)] for z in (-.4,0.,.4)]


def measurement_config(parameters):
    lines=['# Exact numeric-only extractor configuration; generated and hash-bound.','set windows {']
    for name,box in roi_boxes(parameters['qualification']).items():
        lines.append(' '+name+' {'+' '.join(b.number(x) for x in box[0]+box[1])+'}')
    points=geometry_points(parameters['qualification'])
    lines += ['}','set probePoints {']
    for name,x,y,z in points:lines.append(' '+name+' '+' '.join(map(b.number,(x,y,z))))
    lines += ['}','set expectedGeometryProbes '+str(len(points)),'']
    return '\n'.join(lines).encode()


def finite(value,label):
    result=float(value);c.require(math.isfinite(result),'Nonfinite '+label);return result


def curves(archive,parameters,report):
    old=libraries().old;result={}
    for key,name in [('circuit','circuit.plt'),('device','access_device.plt')]:
        names,raw=old.parse_plt(archive.read(name).decode('utf-8'))
        c.require('time' in names and raw,'Missing complete '+name)
        c.require(all(all(math.isfinite(float(v)) for v in row.values()) for row in raw),'Nonfinite native curve')
        rows=old.legacy.clean(raw)
        c.require(rows[0]['time']==0 and abs(rows[-1]['time']-4e-9)<=1e-18,'Curve does not cover complete 0-4ns')
        c.require(all(v['time']>u['time'] for u,v in zip(rows,rows[1:])),'Unordered native samples')
        result[key]=rows;result[key+'_raw']=raw
        report[key+'_datasets']=names;report[key+'_samples']=len(rows)
    ports=('source','drain') if parameters['qualification'] else ('source','drain','gate','body')
    required={port+' '+kind for port in ports for kind in ('TotalCurrent','eCurrent','hCurrent','DisplacementCurrent')}
    c.require(required|{SCALAR} <= set(result['device'][0]),'Missing native terminal/components/PMI scalar')
    circuit={'v(qs)','v(qd)','i(access,qs)','i(access,qd)'} if parameters['qualification'] else {
        'v(sn)','v(bl)','v(ref)','v(wl)','i(access,sn)','i(access,bl)','i(cstore,sn)','i(cbl,bl)',
        'i(cref,ref)','i(rsn,sn)','i(rbl,bl)','i(rref,ref)','i(rpre,bl)'}
    c.require(circuit<=set(result['circuit'][0]),'Missing circuit current/node observations')
    c.require(all(row[SCALAR]<=0 for row in result['device']),'Positive PMI net recombination is not the prescribed source')
    check_checkpoints(result['device'],parameters)
    check_checkpoints(result['circuit'],parameters)
    report['final_time_s']=4e-9
    return result


def check_checkpoints(rows,parameters):
    times=[row['time'] for row in rows]
    desired={v for block in parameters['time_blocks'] for v in
             [block['initial_s'],block['final_s']]+block['turning_points_s']}
    for target in sorted(desired):
        c.require(sum(abs(t-target)<=1e-18 for t in times)==1,'Missing/ambiguous original native checkpoint: '+str(target))
    for left,right in zip(times,times[1:]):
        candidates=[p for p in parameters['time_blocks'] if left>=p['initial_s']-1e-18 and right<=p['final_s']+1e-18]
        c.require(candidates and any(right-left<=p['max_step_s']+1e-18 for p in candidates),'Actual time step exceeds the frozen block maximum')
    return True


def index_frames(log,rows,files,parameters):
    # The old coordinate-independent parser is called without its old fixed window.
    index,boundary=libraries().prior.index_frames(log,rows,files,full=False)
    expected={i for i,(a,z) in enumerate(zip(rows,rows[1:]),1)
              if any(a['time']>=lo-1e-18 and z['time']<=hi+1e-18 for lo,hi in parameters['source_windows_s'])}
    c.require(expected and {f['accepted_index'] for f in index}==expected,'Missing/extra source-window accepted-step TDR')
    for item in index:
        candidates=[p for p in parameters['time_blocks'] if p['active_source'] and item['start_s']>=p['initial_s']-1e-18 and item['end_s']<=p['final_s']+1e-18]
        c.require(len(candidates)==1 and item['dt_s']<=candidates[0]['max_step_s']+1e-18,'TDR interval escapes a frozen active block')
        c.require(item['source_file'].startswith('gstep_b'+format(candidates[0]['index'],'03d')+'_'),'Frame block prefix differs from accepted interval')
    return index,boundary


def archived_inputs(archive,project=None):
    im=json.loads(archive.read('input-manifest.json'));p=json.loads(archive.read('parameters.json'))
    c.require(im['schema']=='nuclear-closure-inputs-r1' and p['role']==im['role'],'Wrong input role/schema')
    mesh=json.loads(archive.read('mesh-manifest.json'));event=None if p['qualification'] else mesh['event_source']
    c.require(mesh==(b.qualified_mesh() if p['qualification'] else b.freeze_mesh(event)),'Archived common mesh changed')
    binary=im['pmi_binary_name'];c.require(re.fullmatch(r'pmi_nuclear_source\.so\.[A-Za-z0-9_-]+',binary),'Unsafe library name')
    name=json.loads(archive.read('project.json'))['name']
    files,expected=b._files(p['role'],name,event,mesh,binary,archive.read(binary))
    c.require(im==expected,'Archived manifest/implementation differs')
    for item,raw in files.items():c.require(archive.read(item)==raw,'Archived input differs: '+item)
    if project is not None:b.check_project(project)
    source=json.loads(archive.read('source-spec.json'))
    c.require(b.digest(source)==p['source_sha256'],'Archived source identity differs')
    return p,source


def source_provenance(run,project=None):
    lib=libraries();old=lib.old;run=Path(run).resolve();report={}
    manifest=old._manifest(run,report)
    with old.Archive(run/'results.tar') as archive:
        old._provenance(archive,manifest,run,project,report)
        # Optional local-project validation must not change the archived source
        # identity reproduced later when collecting a reference-only operation.
        report.pop('project_path',None)
        parameters,source=archived_inputs(archive,project)
        parsed=curves(archive,parameters,report)
        names=sorted(n for n in archive.members if FRAME_RE.fullmatch(n))
        index,boundary=index_frames(archive.read('transient_des.log').decode('utf-8'),parsed['device'],names,parameters)
        resource=json.loads(archive.read('mesh-resource-report.json'))
        c.require(resource['passed'] is True and archive.read('mesh-resource-report.json')==archive.read('mesh-resource-passed.json'),'Native mesh guard did not pass')
        c.require(resource['mesh_sha256']==archive.digest('cell_msh.tdr') and resource['mesh_log_sha256']==archive.digest('cell_msh.log') and resource['input_manifest_sha256']==archive.digest('input-manifest.json'),'Mesh guard native identities differ')
        tetra=re.findall(r'NumberOfTetrahedr(?:a|ons|on)\s*=\s*(\d+)',archive.read('transient_des.log').decode())
        c.require(len(tetra)==1 and int(tetra[0])>0,'No unambiguous native tetrahedral mesh')
        report.update(role=parameters['role'],qualification=parameters['qualification'],parameters=parameters,
            source_sha256=b.digest(source),source=source,accepted_intervals=index,
            frame_count=len(names),tdr_sha256={n:archive.digest(n) for n in names},
            tdr_bytes={n:archive.members[n].size for n in names},native_tetrahedra=int(tetra[0]),
            boundary_frames_not_integrated=boundary,mesh_resource=resource,
            field_audit_sha256=c.sha(Path(__file__)),extractor_sha256=c.sha(HERE/'extract_fields.tcl'),
            contract_sha256=c.sha(HERE/'contract.json'),reference_mode=REFERENCE_MODE,tdr_payload_copied=False)
    return manifest,report


def render_task():
    return '\n'.join(['set -euo pipefail',
        '{',
        "printf 'svisual_requested=%s\\n' '/usr/synopsys/sentaurus/W-2024.09/bin/svisual'",
        'printf \'svisual_resolved=%s\\n\' "$(readlink -f -- /usr/synopsys/sentaurus/W-2024.09/bin/svisual)"',
        'printf \'OMP_NUM_THREADS=%s\\n\' "$OMP_NUM_THREADS"',
        'printf \'OPENBLAS_NUM_THREADS=%s\\n\' "$OPENBLAS_NUM_THREADS"',
        'printf \'MKL_NUM_THREADS=%s\\n\' "$MKL_NUM_THREADS"',
        '} > tool-versions.txt','set +e',
        '/usr/synopsys/sentaurus/W-2024.09/bin/svisual --threads 1 --max_threads 1 -b -tcl -script extract_fields.tcl > svisual.log 2>&1',
        'nc_field_rc=$?','printf "%s\\n" "$nc_field_rc" > svisual-exit-code.txt','set -e',
        "grep -E '^[[:space:]]*(Version |Changelist number: |Multithreading will use )' svisual.log >> tool-versions.txt",
        'test "$nc_field_rc" -eq 0',"grep -Fx 'FIELD_AUDIT_COMPLETED mandatory_errors=0' svisual.log",
        "grep -Fx 'mandatory_command_errors=0' diagnostic-status.txt",
        "grep -Fx 'reference_mode=referenced_original_tdr_not_copied' diagnostic-status.txt",
        'test -s source-reference-checks.csv','test -s field-measurements.csv','echo NUCLEAR_CLOSURE_NATIVE_FIELDS_COMPLETED',''])


def serial_metadata(metadata,affinity,native_log):
    """Check observed native banner and inherited execution constraints.

    Affinity is the original wrapper's /proc observation. The actual SVisual
    banner reports its worker count; an environment value alone is insufficient.
    No nonexistent historical parser or additional native invocation is used.
    """
    facts={}
    for line in metadata.splitlines():
        if '=' in line:
            key,value=line.split('=',1)
            c.require(key not in facts,'Duplicate native serial metadata')
            facts[key]=value
    c.require(set(facts)=={'svisual_requested','svisual_resolved','OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'},
              'Missing/unknown native serial metadata')
    prefix='/usr/synopsys/sentaurus/W-2024.09/'
    c.require(facts['svisual_requested']==prefix+'bin/svisual' and
              facts['svisual_resolved'].startswith(prefix) and '..' not in facts['svisual_resolved'].split('/'),
              'Native SVisual executable identity differs')
    c.require(all(facts[k]=='1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')),
              'Native thread environment is not serial')
    banners={}
    for key,pattern in [
        ('version',r'^\s*Version (.+)$'),
        ('changelist',r'^\s*Changelist number: (.+)$'),
        ('threads',r'^\s*Multithreading will use (.+)$')]:
        observed=re.findall(pattern,metadata,re.M);original=re.findall(pattern,native_log,re.M)
        c.require(len(observed)==1 and observed==original,'Native banner missing, ambiguous or not reproduced: '+key)
        banners[key]=observed[0].strip()
    c.require(re.fullmatch(r'W-2024\.09 for linux64 - .+',banners['version']) is not None,
              'Unexpected native SVisual version')
    c.require(re.fullmatch(r'9150440, Compile host: .+',banners['changelist']) is not None,
              'Unexpected native SVisual changelist')
    c.require(banners['threads']=='1 threads.','Actual SVisual worker count is not one')
    threads=re.findall(r'^Threads:\s*(\d+)\s*$',affinity,re.M)
    cpus=re.findall(r'^Cpus_allowed_list:\s*(\S+)\s*$',affinity,re.M)
    c.require(threads==['1'] and len(cpus)==1 and re.fullmatch(r'\d+',cpus[0]) is not None,
              'Original wrapper is not one thread on one CPU')
    return dict(passed=True,environment=facts,native_banner=banners,wrapper_cpu=int(cpus[0]),
                native_worker_threads=1,wrapper_threads=1,additional_native_invocations=0)


def operation_inputs(manifest,report):
    directory=libraries().remote_directory(manifest['remote_directory'],manifest['run_id'])
    names=sorted(report['tdr_sha256'])
    evidence=dict(schema='nuclear-closure-field-source-reference-r1',source_run_id=manifest['run_id'],
        source_archive_sha256=report['archive_sha256'],source_manifest_sha256=report['manifest_sha256'],
        extractor_sha256=c.sha(HERE/'extract_fields.tcl'),field_audit_sha256=c.sha(Path(__file__)),
        contract_sha256=c.sha(HERE/'contract.json'),tdr_sha256=report['tdr_sha256'],tdr_bytes=report['tdr_bytes'],
        source_remote_directory=directory,role=report['role'],reference_mode=REFERENCE_MODE,tdr_payload_copied=False)
    return {'extract_fields.tcl':(HERE/'extract_fields.tcl').read_bytes(),
        'measurement-config.tcl':measurement_config(report['parameters']),
        'source-case.txt':(report['role']+'\n').encode(),'source-directory.txt':(directory+'\n').encode(),
        'tdr-files.txt':(''.join(n+'\n' for n in names)).encode(),
        'tdr-sha256.txt':(''.join(report['tdr_sha256'][n]+'  '+n+'\n' for n in names)).encode(),
        'source-evidence.json':c.encoded(evidence),'source-provenance.json':c.encoded(report),
        'task.sh':render_task().encode()}


def prepare(run,operation_label,project=None,destination=None):
    c.require(re.fullmatch(r'nc-r1-[a-z0-9-]+',operation_label),'Explicit nc-r1 field operation label required')
    manifest,report=source_provenance(run,project)
    folder=(c.OLD_OPS/'inputs'/operation_label) if destination is None else Path(destination).resolve()
    allowed=(c.OLD_OPS/'inputs').resolve();dev=(RT/'device-dev').resolve()
    c.require(folder.resolve().is_relative_to(allowed) or folder.resolve().is_relative_to(dev),'Unregistered field input destination')
    c.require(folder.name==operation_label and not folder.exists(),'Field input exists or label differs')
    files=operation_inputs(manifest,report);folder.mkdir(parents=True,exist_ok=False)
    for name,raw in files.items():
        with (folder/name).open('xb') as stream:stream.write(raw)
    return dict(input=folder.relative_to(ROOT).as_posix(),role=report['role'],tdr_count=report['frame_count'],
        tdr_bytes=sum(report['tdr_bytes'].values()),max_frame_bytes=max(report['tdr_bytes'].values()),
        original_tdr_hash_read_bytes=4*sum(report['tdr_bytes'].values()),tdr_payload_copied=False,
        reference_mode=REFERENCE_MODE,new_solves=0,dispatched=False,
        numeric_commands_per_active_frame=6*(len(roi_boxes(report['qualification']))+1)+18,
        input_sha256={k:b.digest(v) for k,v in files.items()})


def parse_measurements(raw,names,parameters):
    reader=csv.DictReader(io.StringIO(raw));columns=['source_file','field','native_field','scope','operation','raw_value','command_status']
    c.require(reader.fieldnames==columns,'Unknown native measurement columns')
    scopes=['SILICON_NO_WINDOW']+list(roi_boxes(parameters['qualification']))
    expected={(role,scope,'integral') for role in NATIVE_FIELDS for scope in scopes}
    expected|={(axis,'SILICON_NO_WINDOW',op) for axis in 'XYZ' for op in ('-min','-max')}
    expected|={(role,'SILICON_NO_WINDOW','integral') for role in ('N','P')}
    expected|={(role,'SILICON_NO_WINDOW',op) for role in ('G','G_CHECK','T_PMI','DT_PMI','STEP_PMI') for op in ('-min','-max')}
    result={name:{} for name in names}
    mapping={**NATIVE_FIELDS,**OTHER_FIELDS,**{a:a for a in 'XYZ'}}
    for row in reader:
        c.require(None not in row and all(v is not None for v in row.values()) and row['command_status']=='OK','Failed/malformed native measurement')
        name=row['source_file'];c.require(name in result,'Unknown native source file')
        role,scope,op=row['field'],row['scope'],row['operation']
        if op in ('remove_plots','remove_datasets'):continue
        key=role,scope,op
        c.require(key in expected and row['native_field']==mapping[role] and key not in result[name],'Unexpected/duplicate native field identity')
        value=finite(row['raw_value'],'measurement')
        if role in ('G','G_CHECK','N','P'):c.require(value>=0,'Negative native generation/carrier density')
        if role=='ONE':c.require(value>0,'Empty silicon volume')
        result[name][key]=value
    c.require(all(set(values)==expected for values in result.values()),'Missing native moment/rate/clock/type/volume observation')
    return result


def geometry_metrics(raw,names,parameters):
    rows=list(csv.DictReader(io.StringIO(raw)));expected=geometry_points(parameters['qualification'])
    c.require(len(rows)==len(expected),'Missing native doping probe')
    observations=[]
    for row,(region,x,y,z) in zip(rows,expected):
        c.require(row['source_file']==names[0] and row['region_label']==region and row['native_field']=='DopingConcentration' and row['command_status']=='OK','Doping probe identity/status differs')
        c.require([float(row[k]) for k in ('x_um','y_um','z_um')]==[x,y,z],'Doping probe coordinates differ')
        value=finite(row['raw_value'],'native doping')
        c.require(value>0 if region in ('source','drain') else value<0,'Native doping sign differs')
        if parameters['qualification']:c.require(abs(value+1e17)<=1e15,'Qualification p-type doping differs')
        observations.append(dict(region=region,xyz_um=[x,y,z],value_cm3=value))
    for region in {x[0] for x in expected}:
        values=[v['value_cm3'] for v in observations if v['region']==region]
        c.require((max(values)-min(values))/abs(values[1])<=.01,'Doping varies unexpectedly across z')
    return dict(passed=True,observations=observations)


def operation_evidence(operation,manifest,report):
    lib=libraries();operation=Path(operation).resolve()
    if operation.name=='collected':operation=operation.parent
    folder=operation/'collected';op=c.read(operation/'operation.json')
    c.require(op['state']=='COLLECTED_PENDING_AUDIT' and all(type(op.get(k)) is int and op[k]==0 for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')),'Unknown/failed field operation')
    c.require(c.sha(operation/'results.tar')==op['archive_sha256'],'Field operation archive changed')
    expected=operation_inputs(manifest,report)
    c.require(set(op['input_sha256'])==OP_INPUTS==set(expected),'Field operation inputs differ')
    for name,raw in expected.items():
        c.require((folder/name).read_bytes()==raw and b.digest(raw)==op['input_sha256'][name],'Field source/implementation binding differs: '+name)
    actual={}
    for path in folder.iterdir():
        c.require(path.is_file() and not path.is_symlink() and path.suffix.lower()!='.tdr','Unexpected copied TDR/link/directory')
        actual[path.name]=c.sha(path)
    c.require(NATIVE_OUTPUTS<=set(actual),'Missing native extraction output')
    c.require(actual.get('run.sh')==op.get('wrapper_sha256')==c.sha(operation/'run.sh'),'Field wrapper changed')
    c.require((folder/'exit-code.txt').read_text().strip()=='0' and (folder/'svisual-exit-code.txt').read_text().strip()=='0','Nonzero/unknown native extraction exit')
    log=(folder/'execution.log').read_text(errors='replace').splitlines()
    c.require('V4_OPERATION_COMPLETED' in log and 'NUCLEAR_CLOSURE_NATIVE_FIELDS_COMPLETED' in log,'Native extraction completion marker missing')
    with lib.Archive(operation/'results.tar') as archive:
        c.require(set(archive.members)==set(actual),'Field collected/archive inventory differs')
        for name,digest in actual.items():c.require(archive.digest(name)==digest,'Field output/archived bytes differ: '+name)
    names=sorted(report['tdr_sha256'])
    status={}
    for line in (folder/'diagnostic-status.txt').read_text().splitlines():
        if '=' in line:
            key,value=line.split('=',1);c.require(key not in status,'Duplicate extraction status');status[key]=value
    c.require(status.get('schema')=='nuclear-closure-field-extraction-r1' and status.get('mandatory_command_errors')=='0' and
        status.get('dimension')=='3' and status.get('integration')=='volume_um3' and status.get('reference_mode')==REFERENCE_MODE,
        'Wrong/incomplete native field extraction status')
    c.require(status.get('files_requested')==status.get('files_completed')==str(len(names)) and status.get('geometry_probes_completed')==str(len(geometry_points(report['qualification']))),'Native extraction coverage incomplete')
    c.require(status.get('cleanup_success')=='exact_deleted_object_name' and status.get('memory_release')=='plot_then_dataset_per_frame','Native object release semantics differ')
    identity=lib.verify_reference_checks((folder/'source-reference-checks.csv').read_text(),names,report['tdr_sha256'],report['tdr_bytes'],manifest['remote_directory'])
    serial=serial_metadata((folder/'tool-versions.txt').read_text(),(folder/'affinity.txt').read_text(),
                           (folder/'svisual.log').read_text())
    raw=(folder/'field-measurements.csv').read_text()
    lib.prior.check_cleanup(raw,names,'exact_deleted_object_name',(folder/'field-inventory.csv').read_text())
    values=parse_measurements(raw,names,report['parameters'])
    geometry=geometry_metrics((folder/'geometry-probes.csv').read_text(),names,report['parameters'])
    receipt=dict(schema='nuclear-closure-native-field-receipt-r1',solver_run_id=manifest['run_id'],
        solver_archive_sha256=report['archive_sha256'],solver_manifest_sha256=report['manifest_sha256'],
        operation_record=c.ref(operation/'operation.json'),operation_archive=c.ref(operation/'results.tar'),
        extractor=c.ref(HERE/'extract_fields.tcl'),audit_code=c.ref(Path(__file__)),
        tdr_files_sha256=report['tdr_sha256'],tdr_sizes_bytes=report['tdr_bytes'],reference_checks=identity,
        native_outputs_sha256=actual,geometry=geometry,serial_metadata=serial,reference_mode=REFERENCE_MODE,tdr_payload_copied=False,
        svisual_exit_code=0,remote_exit_code=op['remote_exit_code'],runner_exit_code=op['ssh_exit_code'],collection_exit_code=op['collection_exit_code'],
        physical_acceptance=False,new_solver_calls=0)
    return values,receipt


def collect_receipt(operation):
    operation=Path(operation).resolve()
    if operation.name=='collected':operation=operation.parent
    evidence=c.read(operation/'collected/source-evidence.json')
    run=ROOT/'local_runtime/runs'/evidence['source_run_id'];manifest,report=source_provenance(run)
    _,receipt=operation_evidence(operation,manifest,report)
    record=operation/'field-extraction-record.json'
    if record.exists():
        c.require(record.is_file() and not record.is_symlink() and c.read(record)==receipt,
                  'Existing extraction receipt does not reproduce')
    else:c.write(record,receipt)
    return dict(receipt=c.ref(record),passed=True,physical_acceptance=False)


def native_metrics(index,values,device,source,parameters):
    kernel=b.kernel();tol=c.contract()['tolerances'];boxes=roi_boxes(parameters['qualification'])
    scopes=['SILICON_NO_WINDOW']+list(boxes);failures=[]
    def gate(ok,message):
        if not ok:failures.append(message)
    def value(frame,role,scope='SILICON_NO_WINDOW',op='integral'):
        return values[frame['source_file']][role,scope,op]
    box=boxes['Total'];total_source=math.fsum(s['charge_fC'] for s in source['steps'])
    expected_full={roi:kernel.integrated(source,region,[0,4e-9]) for roi,region in boxes.items()}
    expected_frames={roi:[kernel.integrated(source,region,[f['start_s'],f['end_s']]) for f in index] for roi,region in boxes.items()}
    observed={scope:math.fsum(value(f,'G',scope)*f['dt_s'] for f in index)*CONVERSION for scope in scopes}
    expected={roi:math.fsum(x['charge_fC'] for x in rows) for roi,rows in expected_frames.items()}
    for f in index:
        vals=values[f['source_file']]
        for key,wanted in [('T_PMI',f['end_s']),('DT_PMI',f['dt_s']),('STEP_PMI',3.)]:
            for op in ('-min','-max'):
                gate(abs(vals[key,'SILICON_NO_WINDOW',op]-wanted)<= (0 if key=='STEP_PMI' else 1e-18),'PMI native clock/step identity differs: '+key)
        for scope in scopes:
            region=box if scope=='SILICON_NO_WINDOW' else boxes[scope]
            volume=math.prod(z-a for a,z in zip(*region))
            gate(abs(value(f,'ONE',scope)-volume)<=tol['native_source_relative']*volume,'Native silicon volume differs: '+scope)
            cross=abs(value(f,'G_CHECK',scope)-value(f,'G',scope))
            gate(cross<=max(1e-12,abs(value(f,'G',scope))*1e-10),'PMI user rate differs from negative recombination: '+scope)
        for axis,j in zip('XYZ',range(3)):
            for op,wanted in [('-min',box[0][j]),('-max',box[1][j])]:
                gate(abs(vals[axis,'SILICON_NO_WINDOW',op]-wanted)<=tol['centroid_abs_um'],'Native extent differs: '+axis)
    full_charge=math.fsum(-z[SCALAR]*(z['time']-a['time']) for a,z in zip(device,device[1:]))*CONVERSION
    selected={f['accepted_index'] for f in index}
    scalar_inside=math.fsum(-device[i][SCALAR]*(device[i]['time']-device[i-1]['time']) for i in selected)*CONVERSION
    target=expected_full['Total']['charge_fC'];window_target=expected['Total'];total=observed['SILICON_NO_WINDOW']
    bound=tol['native_source_relative']*target
    gate(abs(full_charge-target)<=bound,'Full scalar 0-4ns charge exceeds source tolerance')
    gate(abs(total-window_target)<=bound,'Native source-window TDR charge exceeds source tolerance')
    gate(abs(total-scalar_inside)<=bound,'Native TDR and scalar source-window charges differ')
    rows=[];roi_metrics={}
    if total_source==0:
        gate(full_charge==0 and all(value(f,r,scope)==0 for f in index for r in ('G','G_CHECK','XG','YG','ZG') for scope in scopes),'Observed A0 PMI source/moment is nonzero')
    else:
        gate(total>0 and window_target>0,'Positive source has no native/window charge')
        for roi,region in boxes.items():
            scope='SILICON_NO_WINDOW' if roi=='Total' else roi
            measured=[value(f,'G',scope)*CONVERSION for f in index]
            wanted=[x['charge_fC']/f['dt_s'] for x,f in zip(expected_frames[roi],index)]
            peak=max(wanted);fraction=observed[scope]/total if total else 0
            desired_fraction=expected[roi]/window_target if window_target else 0
            waveform=max(abs(x-y) for x,y in zip(measured,wanted))/peak if peak else 0.
            gate(abs(fraction-desired_fraction)<=tol['roi_fraction_abs'],'ROI fraction differs: '+roi)
            center_error=[0.,0.,0.];active=0
            if desired_fraction>=.001:
                gate(waveform<=tol['be_waveform_relative'],'Native BE-average waveform differs: '+roi)
                observed_mass=math.fsum(x*f['dt_s'] for x,f in zip(measured,index))
                observed_time=math.fsum(x*f['dt_s']*(f['start_s']+f['end_s'])/2 for x,f in zip(measured,index))/observed_mass if observed_mass else None
                expected_mass=expected[roi]
                expected_time=math.fsum(x['time_first_moment_fC_s'] for x in expected_frames[roi])/expected_mass if expected_mass else None
                gate(observed_time is not None and expected_time is not None and abs(observed_time-expected_time)<=tol['time_centroid_abs_s'],'Native time centroid differs: '+roi)
                for frame,actual,target_frame in zip(index,measured,expected_frames[roi]):
                    if actual<max(measured)*.001:continue
                    ctr=target_frame['centroid_um'];native=value(frame,'G',scope)
                    gate(native>0 and ctr is not None,'Observed active source outside expected oracle support')
                    if native>0 and ctr is not None:
                        active+=1
                        for j,axis in enumerate('XYZ'):center_error[j]=max(center_error[j],abs(value(frame,axis+'G',scope)/native-ctr[j]))
                gate(active>0 and max(center_error)<=tol['centroid_abs_um'],'Native xyz centroid differs: '+roi)
            else:observed_time=expected_time=None
            roi_metrics[roi]=dict(observed_charge_fC=observed[scope],expected_charge_fC=expected[roi],observed_fraction=fraction,
                expected_fraction=desired_fraction,BE_peak_relative_error=waveform,centroid_max_abs_error_um=center_error,
                active_centroid_frames=active,observed_time_centroid_s=observed_time,expected_time_centroid_s=expected_time)
        for group in [('Left','Right'),('Low','Middle','High'),('ZNegative','ZPositive')]:
            qerr=abs(sum(observed[r] for r in group)-total)/total if total else math.inf
            maxrate=max(value(f,'G') for f in index)
            rerr=max(abs(sum(value(f,'G',r) for r in group)-value(f,'G')) for f in index)/maxrate if maxrate else math.inf
            gate(max(qerr,rerr)<=tol['partition_relative'],'Native ROI partition closure differs: '+','.join(group))
    for f in index:
        row=dict(f)
        for scope in scopes:
            for role in NATIVE_FIELDS:row[role+'_'+scope+'_raw']=value(f,role,scope)
        row.update(N_raw=value(f,'N'),P_raw=value(f,'P'))
        rows.append(row)
    result=dict(passed=not failures,errors=failures,volume_conversion_to_fC=CONVERSION,
        full_scalar_charge_fC=full_charge,scalar_window_charge_fC=scalar_inside,native_window_charge_fC=total,
        expected_full_domain_charge_fC=target,expected_window_charge_fC=window_target,
        expected_window_tail_fC=target-window_target,full_scalar_outside_frame_windows_fC=full_charge-scalar_inside,
        total_unclipped_source_charge_fC=total_source,expected_spatial_or_0to4ns_outside_fC=total_source-target,
        no_clipping_renormalization=True,roi_metrics=roi_metrics,independent_oracle='analytic box-time moments independent of native PMI spatial integration')
    return result,rows


def audit(run,operation,project=None,output=None):
    operation=Path(operation).resolve()
    if operation.name=='collected':operation=operation.parent
    out=dict(schema='nuclear-closure-field-audit-r1',passed=False,errors=[],checks={},dimension=3,
        scientific_calibration_passed=False,field_audit_sha256=c.sha(Path(__file__)),
        extractor_sha256=c.sha(HERE/'extract_fields.tcl'),contract_sha256=c.sha(HERE/'contract.json'))
    frames=[]
    try:
        manifest,report=source_provenance(run,project)
        out.update({k:report[k] for k in ('run_id','role','qualification','archive_sha256','manifest_sha256','mesh_sha256','source_sha256','accepted_intervals','mesh_resource')})
        out['checks']['original_native_solver_and_inputs']=True
        values,actual=operation_evidence(operation,manifest,report)
        stored=c.read(Path(operation)/'field-extraction-record.json')
        c.require(stored==actual,'Saved extraction receipt does not reproduce')
        out['extraction_record']=c.ref(Path(operation)/'field-extraction-record.json')
        out['geometry']=actual['geometry'];out['checks']['original_field_operation_and_reference_hashes']=True
        with libraries().Archive(Path(run)/'results.tar') as archive:
            parsed=curves(archive,report['parameters'],{})
        metrics,frames=native_metrics(report['accepted_intervals'],values,parsed['device'],report['source'],report['parameters'])
        out['native_metrics']=metrics
        c.require(metrics['passed'],'; '.join(metrics['errors']))
        out['checks']['native_PMI_BE_volume_xyz_time_and_scalar']=True
        c.require(c.sha(Path(run)/'results.tar')==report['archive_sha256'] and c.sha(Path(run)/'manifest.json')==report['manifest_sha256'],'Original archive changed during field audit')
        out['passed']=True
    except Exception as exc:out['errors'].append(type(exc).__name__+': '+str(exc))
    if output is not None:
        folder=Path(output).resolve();c.require(folder.is_relative_to(RT) and folder!=RT and not folder.exists(),'New nuclear-closure audit output required')
        folder.mkdir(parents=True,exist_ok=False)
        if frames:
            with (folder/'frames.csv').open('x',encoding='utf-8',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(frames[0]));writer.writeheader();writer.writerows(frames)
            out['frames_csv_path']=str(folder/'frames.csv');out['frames_csv_sha256']=c.sha(folder/'frames.csv')
        c.write(folder/'audit.json',out)
    return out


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('run',type=Path);p.add_argument('label');p.add_argument('--project',type=Path)
    p=sub.add_parser('collect');p.add_argument('operation',type=Path)
    p=sub.add_parser('audit');p.add_argument('run',type=Path);p.add_argument('operation',type=Path);p.add_argument('--project',type=Path);p.add_argument('--output',type=Path)
    a=parser.parse_args()
    result=prepare(a.run,a.label,a.project) if a.command=='prepare' else collect_receipt(a.operation) if a.command=='collect' else audit(a.run,a.operation,a.project,a.output)
    print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False));raise SystemExit(0 if result.get('passed',True) else 2)
