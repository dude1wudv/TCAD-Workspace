"""Approved r5 dispatch through the existing tcad runner; one root scheduler."""
import importlib.util
import json
import msvcrt
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime,timezone
import hashlib
import tarfile

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
RT=ROOT/'local_runtime/dram-see-v4'
CAMPAIGN=HERE/'campaign.json'
STATE=RT/'interface-completion-r1'

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def utc():return datetime.now(timezone.utc).isoformat()
def module(p,name):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s)
    exec(compile(Path(p).read_bytes(),str(p),'exec'),m.__dict__);return m
def require(ok,text):
    if not ok:raise ValueError(text)
def ref(p):return Path(p).resolve().relative_to(ROOT).as_posix()

def check_evidence(evidence,require_pass=False):
    require(isinstance(evidence,list) and bool(evidence),'Missing evidence references')
    for e in evidence:
        p=(ROOT/e['path']).resolve()
        require(p.is_relative_to(ROOT) and p.is_file() and not p.is_symlink(),'Evidence path outside project or missing')
        require(sha(p)==e['sha256'],'Evidence digest changed: '+e['path'])
        if e.get('requires_pass',require_pass):require(read(p).get('passed') is True,'Referenced evidence did not pass')

def check_gate(role):
    require(re.fullmatch(r'[a-z0-9-]+',role),'Unsafe dependency ID')
    p=STATE/'gates'/(role+'.json')
    require(p.is_file(),'Dependency gate missing: '+role)
    d=read(p)
    require(d.get('schema')=='dram-see-v4-completion-role-gate-r1' and d.get('role_id')==role and d.get('passed') is True,'Dependency gate failed: '+role)
    require(d.get('campaign_sha256')==sha(CAMPAIGN),'Dependency belongs to another campaign')
    check_evidence(d.get('evidence'))
    return dict(path=ref(p),sha256=sha(p),role_id=role)

def known_solver_failure(record):
    """A nonzero local runner alone does not establish the remote solver's fate."""
    require(record.get('runner_manifest_state')=='FAILED_COLLECTED' and type(record.get('ssh_exit_code')) is int
            and 0<record['ssh_exit_code']<255,'Failed invocation remote/collection state unknown; reconcile original job')
    require(re.fullmatch(r'[A-Za-z0-9_-]+',record.get('run_id','')),'Failed run ID missing')
    run=ROOT/'local_runtime/runs'/record['run_id'];manifest=read(run/'manifest.json');archive=run/'results.tar'
    require(manifest['state']=='FAILED_COLLECTED' and manifest['ssh_exit_code']==record['ssh_exit_code'],'Failure manifest differs')
    digest=hashlib.sha256()
    with archive.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    require(digest.hexdigest()==manifest['results_sha256']==record['result_archive_sha256'],'Failure archive hash differs')
    with tarfile.open(archive) as tar:
        matches=[m for m in tar.getmembers() if m.name.removeprefix('./')=='exit-code.txt']
        require(len(matches)==1 and matches[0].isfile() and matches[0].size<32,'Failed original remote exit missing/ambiguous')
        raw=tar.extractfile(matches[0]).read().strip()
    require(re.fullmatch(rb'\d+',raw) and int(raw)==record['ssh_exit_code'],'Original failed remote exit differs/unknown')
    return dict(passed=True,known_remote_failure=True,remote_exit_code=int(raw),archive_sha256=digest.hexdigest(),
                manifest_sha256=sha(run/'manifest.json'),run_id=run.name)

def validate_history(previous,c,role,category,ticket=None):
    require(category in ('primary','reserve'),'Unknown budget category')
    require(len(previous)<c['maximum_global_attempts'],'Cumulative26 attempt cap reached')
    old_paths={str((ROOT/e['path']).resolve()):e['sha256'] for e in c['historical_records']}
    require(len(old_paths)==5 and all(Path(p).is_file() and sha(p)==s for p,s in old_paths.items()),'Historical five attempts changed')
    new=[]
    for p in previous:
        d=read(p)
        require(d.get('state') in ('RUNNER_EXITED','LOCAL_INVOCATION_ERROR') and d.get('runner_exit_code') is not None,'Previous job state unknown; reconcile read-only')
        if d.get('runner_exit_code')==0:
            require(d.get('ssh_exit_code')==0 and d.get('runner_manifest_state')=='COLLECTED','Previous remote/collection state unknown')
        else:known_solver_failure(d)
        if str(p.resolve()) not in old_paths:
            require(d.get('campaign_sha256')==sha(CAMPAIGN) and d.get('budget_category') in ('primary','reserve'),'Unregistered post-start invocation')
            new.append(d)
    require(len(new)<c['maximum_new_attempts'],'Next-round21 attempt cap reached')
    require(sum(d['budget_category']=='reserve' for d in new)<=c['reserve_attempts'],'Reserve ledger already exceeds cap')
    primary_roles={r['role_id'] for r in c['roles']}
    if category=='primary':
        require(role in primary_roles,'Role is not a primary request')
        require(not any(d.get('role_id')==role for d in new),'Role already attempted; corrective ticket required')
        require(ticket is None,'Primary request cannot consume repair ticket')
    else:
        require(sum(d['budget_category']=='reserve' for d in new)<c['reserve_attempts'],'Four corrective attempts exhausted')
        require(role in primary_roles|{'a0-b1-main','a1-b1-main'},'Unknown corrective role')
        require(ticket is not None,'Corrective ticket required')
        require(ticket['record'].get('role_id')==role and ticket['record'].get('root_cause') and ticket['record'].get('repair_description'),'Repair cause and scope missing')
        require(ticket['record'].get('automatic_retry') is False and ticket['record'].get('max_additional_attempts')==1,'Each repair ticket permits exactly one intentional attempt')
        require(ticket['record'].get('same_root_cause_consecutive_failures')==1,'Two consecutive same-cause failures pause the branch')
        check_evidence(ticket['record'].get('failed_evidence'))
        require(any(read(ROOT/e['path']).get('passed') is False or read(ROOT/e['path']).get('runner_exit_code') not in (0,None) for e in ticket['record']['failed_evidence']),'No known failure justifies repair')
        check_evidence(ticket['record'].get('offline_checks'),True)
        require(not any((d.get('repair_ticket') or {}).get('sha256')==ticket['sha256'] for d in new),'Repair ticket already consumed')
        same=[d for d in new if (d.get('repair_ticket') or {}).get('root_cause')==ticket['record']['root_cause']]
        for d in same:
            outcome=STATE/'outcomes'/(d['label']+'.json')
            require(outcome.is_file(),'Prior same-cause corrective scientific outcome unresolved')
            require(read(outcome).get('passed') is True,'Same cause failed after correction; pause branch')
    return new

def unresolved_postprocessing():
    bad=[]
    for p in (RT/'transport-probe/operations').glob('*/operation.json'):
        d=read(p)
        if d.get('state') not in ('COLLECTED_PENDING_AUDIT','FAILED_COLLECTED'):bad.append(ref(p))
    require(not bad,'Original postprocessing/transport outcome unresolved: '+','.join(bad))

def invoke(project,label,category='primary',repair_ticket=None):
    c=read(CAMPAIGN);project=Path(project).resolve()
    require(project.is_relative_to((RT/'source-interface-r5/inputs').resolve()),'Historic/unknown input revision frozen; use registered r5 input')
    require(re.fullmatch(r'r5-[a-z0-9-]+',label),'Explicit r5 label required')
    b=module(ROOT/'experiments/dram-see-v4/source-interface-r5/build_interface.py','_completion_builder')
    proof=b.check_project(project);identity=[proof['case_id'],proof['stored_bit'],proof['variant']]
    role=f'{identity[0].lower()}-b{identity[1]}-{identity[2]}'
    requests={r['role_id']:r for r in c['roles']}
    ticket=None
    if repair_ticket:
        p=Path(repair_ticket).resolve();require(p.is_relative_to((STATE/'repairs').resolve()),'Repair ticket must be in campaign repairs')
        ticket=dict(path=ref(p),sha256=sha(p),record=read(p))
        require(ticket['record'].get('input_manifest_sha256')==proof['manifest_sha256'],'Repair ticket input differs')
    lockpath=RT/'source-probe/execution.lock';lock=lockpath.open('a+b')
    if lock.seek(0,2)==0:lock.write(b'0');lock.flush()
    lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    try:
        previous=sorted(RT.glob('source-interface-*/launches/*/execution.json'))
        new=validate_history(previous,c,role,category,ticket);unresolved_postprocessing()
        requires=requests[role]['requires'] if role in requests else []
        gates=[check_gate(r) for r in requires]
        resource=module(HERE/'resources.py','_completion_resources').check(identity[2],label)
        require(resource['passed'],'Storage/process readiness failed')
        folder=RT/'source-interface-r5/launches'/label;folder.mkdir(parents=True,exist_ok=False)
        path=folder/'execution.json'
        record=dict(schema='dram-see-v4-source-runner-invocation-v3',label=label,identity=identity,role_id=role,
            interface_revision='r5',campaign_sha256=sha(CAMPAIGN),budget_category=category,
            invocation_budget_position=len(previous)+1,maximum_invocations=26,new_round_position=len(new)+1,
            repair_ticket=({k:ticket[k] for k in ('path','sha256')}|{'root_cause':ticket['record']['root_cause']}) if ticket else None,
            dependency_gates=gates,resource_check=resource,started_utc=utc(),launcher_pid=os.getpid(),state='PREPARING',
            project=ref(project),runner_exit_code=None,automatic_retry=False,solver_runner='scripts/tcad.py',
            runner_sha256=sha(ROOT/'scripts/tcad.py'),invocation_controller_sha256=sha(Path(__file__)),offline_input_check=proof,
            source_input_sha256={p.relative_to(project).as_posix():sha(p) for p in sorted(project.rglob('*')) if p.is_file()},
            prior_invocations=[ref(p) for p in previous])
        def save():
            temp=path.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');temp.replace(path)
        save()
        try:
            argv=[sys.executable,'-B',str(ROOT/'scripts/tcad.py'),'run',str(project)];record['argv']=argv
            with (folder/'stdout.log').open('xb') as out,(folder/'stderr.log').open('xb') as err:
                child=subprocess.Popen(argv,cwd=ROOT,stdout=out,stderr=err)
                record.update(state='RUNNING',runner_pid=child.pid);save();record['runner_exit_code']=child.wait()
            record['state']='RUNNER_EXITED'
            match=re.search(r'^Run evidence:\s*(.+)$',(folder/'stdout.log').read_text(encoding='utf-8',errors='replace'),re.MULTILINE)
            if match:
                run=Path(match.group(1).strip()).resolve();require(run.is_relative_to((ROOT/'local_runtime/runs').resolve()),'Unexpected runner evidence path')
                record['run_id']=run.name
                if (run/'manifest.json').is_file():
                    m=read(run/'manifest.json');record.update(runner_manifest_state=m['state'],ssh_exit_code=m.get('ssh_exit_code'),
                        result_archive_sha256=m.get('results_sha256'),manifest_input_matches_project=m.get('input_sha256')==record['source_input_sha256'])
            record['scientific_status']='PENDING_AUDIT'
        except Exception as exc:record.update(state='LOCAL_INVOCATION_ERROR',error=repr(exc),scientific_status='NOT_VERIFIED')
        finally:record['finished_utc']=utc();save()
        print(json.dumps({k:record.get(k) for k in ('label','state','run_id','runner_exit_code','runner_manifest_state','ssh_exit_code','invocation_budget_position')}),flush=True)
        return 0 if record['state']=='RUNNER_EXITED' and record['runner_exit_code']==0 and record.get('manifest_input_matches_project') is True else 1
    finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
