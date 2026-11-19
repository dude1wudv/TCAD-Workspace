# Independent field-parser and acceptance binding; original solver inputs unchanged.
# Independent stable-index-auditor binding; native device science unchanged.
# Independent event-auditor binding; released device science and budgets unchanged.
"""Root-reviewed device continuation, using scripts/tcad.py without replacement."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import common as c
import supervisor as s


def tcad(role,project):
    label='nc-r1-'+role;path=c.RT/'attempts'/(label+'.json')
    builder=c.module(c.HERE/'build_cases.py','_nc_campaign_builder')
    proof=builder.check_project(project)
    inputs={p.relative_to(project).as_posix():c.sha(p) for p in sorted(project.rglob('*')) if p.is_file()}
    if path.exists():
        row=c.read(path)
        c.require(row['role']==role and row['input_hashes']==inputs,'Previously reserved TCAD inputs differ')
        c.require(row.get('exit_code')==0 and row.get('run_directory'),'Previous original runner outcome unknown/failed; inspect its original directory')
        run=c.ROOT/row['run_directory']
        c.require(c.read(run/'manifest.json').get('state')=='COLLECTED','Prior original manifest incomplete')
        return run,path
    b=s.budget();limits=c.contract()['budgets']
    c.require(b['tcad_calls']<limits['tcad_primary'],'Primary 14-call allocation exhausted')
    before=s.preflight(label)
    pattern='*-v4-nuclear-closure-r1-'+role+'-*'
    old={p.name for p in (c.ROOT/'local_runtime/runs').glob(pattern)}
    c.require(not old,'An original run already exists without this attempt; reconcile only')
    row=dict(schema='nuclear-closure-attempt-r1',label=label,kind='tcad',role=role,corrective=False,
       created_utc=c.utc(),owner_pid=os.getpid(),preflight=before,exit_code=None,state='RESERVED',
       input_directory=project.relative_to(c.ROOT).as_posix(),input_hashes=inputs,offline_proof=proof,
       runner=c.ref(c.ROOT/'scripts/tcad.py'))
    c.write(path,row)
    command=[sys.executable,'-B',str(c.ROOT/'scripts/tcad.py'),'run',str(project)]
    log=c.RT/'logs'/label;log.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    with (log/'stdout.log').open('xb') as out,(log/'stderr.log').open('xb') as err:
        child=subprocess.Popen(command,cwd=c.ROOT,stdout=out,stderr=err)
        row.update(state='RUNNING',pid=child.pid,argv=command);c.write(path,row,exclusive=False)
        s.update_status(state='RUNNING_TCAD',owner_pid=os.getpid(),active_child=child.pid,active_label=label)
        row['exit_code']=child.wait()
    candidates=list((c.ROOT/'local_runtime/runs').glob(pattern))
    row.update(state='EXECUTED' if row['exit_code']==0 else 'FAILED_OR_UNKNOWN',finished_utc=c.utc(),wall_seconds=time.monotonic()-started)
    if len(candidates)==1:row['run_directory']=candidates[0].relative_to(c.ROOT).as_posix()
    row['candidate_runs']=[p.relative_to(c.ROOT).as_posix() for p in candidates]
    c.write(path,row,exclusive=False);c.write(c.RT/'budget.json',s.budget(),exclusive=False)
    s.update_status(active_child=None,active_label=None)
    c.require(len(candidates)==1,'Cannot identify one original TCAD run')
    run=candidates[0];manifest=c.read(run/'manifest.json')
    c.require(manifest.get('input_sha256')==inputs,'Runner inputs differ from reservation')
    c.require(row['exit_code']==0 and manifest.get('ssh_exit_code')==0 and manifest.get('state')=='COLLECTED','TCAD execution failed or unknown')
    return run,path


def pmi_binary():
    """Compilation provenance is independent of solver qualification."""
    value=c.read(c.RT/'pmi/build.json')
    c.require(value['compiled'] is True and value['qualified'] is False,'Expected compilation-only receipt')
    for item in value['evidence']:c.check_ref(item)
    return c.check_ref(value['binary'])


def role_run(role,event,mesh_path):
    a=c.module(c.HERE/'acceptance_field_r7.py','_nc_campaign_acceptance')
    if (c.RT/'device/gates'/(role+'.json')).exists():return a.gate(role)
    b=c.module(c.HERE/'build_cases.py','_nc_case_builder')
    f=c.module(c.HERE/'field_audit_index_r7.py','_nc_case_fields')
    project=c.RT/'inputs'/role
    if not project.exists():b.build(role,project,event,pmi_binary(),mesh_path)
    b.check_project(project)
    run,attempt=tcad(role,project)
    label='nc-r1-fields-'+role;op=c.OLD_OPS/'operations'/label
    inp=c.OLD_OPS/'inputs'/label
    if not (c.RT/'attempts'/(label+'.json')).exists():
        if inp.exists():
            manifest,proof=f.source_provenance(run,project)
            expected=f.operation_inputs(manifest,proof)
            c.require({p.name for p in inp.iterdir()}==set(expected),'Interrupted field input inventory differs')
            for name,raw in expected.items():
                c.require((inp/name).is_file() and not (inp/name).is_symlink() and (inp/name).read_bytes()==raw,
                          'Interrupted field input bytes differ: '+name)
        else:f.prepare(run,label,project)
        # API may return a path or a receipt; canonical original-adapter input is fixed.
        c.require((inp/'task.sh').is_file(),'Field package not prepared in original adapter namespace')
    s.operation(label,inp,'postprocess',timeout=172800)
    f.collect_receipt(op)
    output=c.RT/'device/fields'/role
    field_path=output/'audit.json'
    if field_path.exists():
        field=c.read(field_path)
        c.require(field.get('passed') is True,'Prior native full-frame audit failed')
    else:
        field=f.audit(run,op,project,output=output)
    result=a.accept(role,run,project,field_path,attempt)
    c.require(result['passed'] is True,'Response acceptance failed: '+role)
    return a.gate(role)


def qualification():
    """Both carriers must increase in the independent native volume integral."""
    import csv
    a=c.module(c.HERE/'acceptance_field_r7.py','_nc_qualification_acceptance')
    zero,point=(a.load(r) for r in ('qualification-zero','qualification-point'))
    c.require(zero['field']['mesh_sha256']==point['field']['mesh_sha256'],'Qualification meshes differ')
    b=c.module(c.HERE/'build_cases.py','_nc_qualification_builder')
    b.check_control(zero['project'],point['project'])
    # Native carrier evidence columns are specified by the field extraction contract.
    fields=[]
    for x in (zero,point):
        path=Path(x['field']['frames_csv_path'])
        c.require(c.sha(path)==x['field']['frames_csv_sha256'],'Qualification frame evidence changed')
        with path.open(newline='',encoding='utf-8') as stream:fields.append(list(csv.DictReader(stream)))
    result=dict(schema='nuclear-closure-pmi-qualification-r1',passed=False,utc=c.utc(),
                evidence=[c.ref(c.RT/'device/gates'/(r+'.json')) for r in ('qualification-zero','qualification-point')])
    # Details are filled from explicit independently extracted carrier fields;
    # a missing native observable is a failure, never an inferred pass.
    paired=[dict(time=float(row['end_s']),N_raw=float(row['N_raw']),P_raw=float(row['P_raw'])) for row in fields[0]]
    active=[dict(time=float(row['end_s']),N_raw=float(row['N_raw']),P_raw=float(row['P_raw'])) for row in fields[1]]
    c.require(paired and active,'Missing qualification carrier volume samples')
    start=max(paired[0]['time'],active[0]['time']);end=min(paired[-1]['time'],active[-1]['time'])
    times=sorted({r['time'] for rows in (paired,active) for r in rows if start<=r['time']<=end})
    comparison=[dict(time_s=t) for t in times]
    for key in ('N_raw','P_raw'):
        baseline=a.samples(paired,key,times);values=a.samples(active,key,times)
        delta=[v-z for v,z in zip(values,baseline)]
        result[key+'_increase']=max(delta)
        result[key+'_increase_time_s']=times[delta.index(max(delta))]
        for row,v,z,d in zip(comparison,values,baseline,delta):row['point_'+key]=v;row['zero_'+key]=z;row['delta_'+key]=d
        c.require(result[key+'_increase']>0,'No positive native carrier increase: '+key)
    csv_path=c.RT/'pmi/paired-native-carriers.csv'
    a.csv_verify_or_write(csv_path,comparison)
    result['evidence'].append(c.ref(csv_path));result['paired_frame_interval_s']=[start,end]
    result['passed']=True
    c.write(c.RT/'pmi/qualification.json',result)
    return result


def qualify():
    for role in ('qualification-zero','qualification-point'):role_run(role,None,None)
    if not (c.RT/'pmi/qualification.json').exists():qualification()
    result=c.read(c.RT/'pmi/qualification.json')
    for item in result['evidence']:c.check_ref(item)
    c.require(result['passed'] is True,'PMI environment qualification not passed')
    return result


def failure_cause(role,error):
    """Classify only from retained evidence. Unexplained failures stop dispatch."""
    value=dict(role=role,error=repr(error),root_cause='UNCLASSIFIED_REQUIRES_DIAGNOSIS',shared=True)
    path=c.RT/'attempts'/('nc-r1-'+role+'.json')
    if not path.exists():return value
    attempt=c.read(path);value['attempt']=c.ref(path)
    run=c.ROOT/attempt.get('run_directory','__missing__')
    if (run/'manifest.json').exists():
        manifest=c.read(run/'manifest.json')
        if manifest.get('state') not in ('COLLECTED','FAILED_COLLECTED'):
            value['root_cause']='UNKNOWN_ORIGINAL_RUN';return value
        import acceptance_field_r7 as a
        if (run/'results.tar').exists():
            with a.original().Archive(run/'results.tar') as archive:
                if 'mesh-resource-report.json' in archive.members:
                    resource=__import__('json').loads(archive.read('mesh-resource-report.json'))
                    if resource.get('passed') is False:
                        value.update(root_cause='NATIVE_RESOURCE_GATE',resource=resource);return value
                # A parameter echo containing MinStep does not establish the
                # cause of a failed native run. Without an independently
                # diagnosed terminal failure, keep the shared pause below.
    response=c.RT/'device/audits'/role/'audit.json'
    if response.exists():
        audit=c.read(response)
        if audit.get('circuit_balance',{}).get('passed') is False:
            value.update(root_cause='INDEPENDENT_CIRCUIT_CONSERVATION',shared=False);return value
    return value


def run():
    import acceptance_field_r7 as a
    selection=c.read(c.RT/'selected-event.json')
    revision=selection.get('transport_revision')
    c.require(revision in (None,'material-r2','audit-index-r5'),'Unknown selected transport revision')
    source=c.module(c.HERE/('event_source_index_r5.py' if revision=='audit-index-r5' else 'event_source_material_r2.py' if revision=='material-r2' else 'event_source.py'),'_nc_selected_source')
    b=c.module(c.HERE/'build_cases.py','_nc_frozen_mesh')
    selected=c.RT/'selected-event.json'
    c.require(selected.exists(),'Select a native event before device mesh freezing')
    output=c.RT/'source/event-source.json'
    value=source.from_selected(selected)
    for path,key in [(output,'source'),(c.RT/'source/ledger.json','ledger')]:
        if path.exists():c.require(c.read(path)==value[key],'Selected event/source ledger no longer reproduces')
        else:c.write(path,value[key])
    event=c.read(output);mesh=c.RT/'mesh-manifest.json'
    if not mesh.exists():c.write(mesh,b.freeze_mesh(event))
    c.require(c.read(mesh)==b.freeze_mesh(event),'Frozen shared event mesh changed')
    qualify()
    failures=[]
    artificial_failed=False
    cause_counts={};shared_pause=None
    for role in c.contract()['primary_roles'][2:]:
        c.check_release('device')
        if shared_pause:
            failures.append(dict(role=role,reason='SHARED_DEPENDENCY_PAUSED',cause=shared_pause));continue
        if role.startswith('artificial-') and artificial_failed:
            failures.append(dict(role=role,reason='SHARED_SOURCE_FAILURE_REQUIRES_DIAGNOSIS'));continue
        if role.startswith('event-'):
            if artificial_failed or not all((c.RT/'device/gates'/(r+'.json')).exists() for r in
                ('artificial-line','artificial-point','artificial-mixed','artificial-segmented')):
                failures.append(dict(role=role,reason='ARTIFICIAL_SOURCE_VALIDATION_NOT_ACCEPTED'));continue
            eqpath=c.RT/'device/equivalent-source.json'
            if not eqpath.exists():
                eq,rows=a.compare_roles('artificial-mixed','artificial-segmented','equivalent')
                a.csv_verify_or_write(c.RT/'device/equivalent-source.csv',rows);c.write(eqpath,eq)
            if not c.read(eqpath)['passed']:
                failures.append(dict(role=role,reason='EQUIVALENT_SEGMENTATION_FAILED'));continue
        if role.startswith('event-') or role.startswith('artificial-'):
            control='a0-m0-t0' if role.startswith('artificial-') else role.replace('event-','a0-',1)
            if not (c.RT/'device/gates'/(control+'.json')).exists():
                failures.append(dict(role=role,reason='MATCHED_A0_NOT_ACCEPTED'));continue
        if '-m1-' in role:
            # The actual M0 baseline has completed and its resource record is preserved before fine work.
            a.gate('a0-m0-t0')
        try:role_run(role,event,mesh)
        except Exception as exc:
            cause=failure_cause(role,exc)
            cause_counts[cause['root_cause']]=cause_counts.get(cause['root_cause'],0)+1
            if cause['shared'] or cause_counts[cause['root_cause']]>=2:shared_pause=cause['root_cause']
            failures.append(dict(role=role,reason=repr(exc),cause=cause,
                same_cause_count=cause_counts[cause['root_cause']],automatic_retry=False))
            if role.startswith('artificial-'):artificial_failed=True
            s.update_status(state='DEPENDENT_BRANCH_FAILED',role_failure=failures[-1])
            # Unknown/live remote work must block all further launch attempts.
            site=s.remote_probe()
            if site['active_solver_lines'] or site['values']['LOCK_FREE']!=1:raise
            for path in (c.RT/'attempts').glob('*.json'):
                record=c.read(path)
                if record.get('exit_code') is None:raise RuntimeError('Unknown original attempt blocks continuation: '+record['label'])
                if record['kind']=='tcad' and record.get('run_directory'):
                    manifest=c.read(c.ROOT/record['run_directory']/'manifest.json')
                    if manifest.get('state') not in ('COLLECTED','FAILED_COLLECTED'):
                        raise RuntimeError('Unreconciled original TCAD run blocks continuation: '+record['label'])
    if failures:
        c.write(c.RT/'device/branch-failures.json',dict(utc=c.utc(),failures=failures))
        s.update_status(state='DEVICE_BRANCHES_INCOMPLETE',scientific_passed=False);return
    result=a.complete_matrix()
    s.update_status(state='FIRST_MILESTONE_PASSED' if result['passed'] else 'NUMERICAL_MATRIX_FAILED',
                    scientific_passed=result['passed'],numerical_matrix=c.ref(c.RT/'device/matrix/summary.json'))
