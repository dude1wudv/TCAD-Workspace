"""Single dispatch entry; approved completion contract supersedes frozen historical policy."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import msvcrt
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
RUNTIME_BASE=ROOT/'local_runtime/dram-see-v4'
APPROVED_REVISIONS=('r2','r3','r4')

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def utc(): return datetime.now(timezone.utc).isoformat()

def resolve_request(project,label):
    project=Path(project).resolve()
    for revision in APPROVED_REVISIONS:
        runtime=RUNTIME_BASE/f'source-interface-{revision}'
        if project.is_relative_to((runtime/'inputs').resolve()) and re.fullmatch(revision+'-[a-z0-9-]+',label):
            return revision,runtime,project
    raise ValueError('Explicit approved revision project/label required')

def validate_history(previous,identity,revision):
    if len(previous)>=19: raise ValueError('Maximum 19 new solver invocations reached across all revisions')
    for p in previous:
        old=read(p)
        if old['state'] not in ('RUNNER_EXITED','LOCAL_INVOCATION_ERROR') or old.get('runner_exit_code') is None:
            raise ValueError('Previous local/remote job state unknown; reconcile read-only')
        if old.get('runner_exit_code')==0 and (old.get('ssh_exit_code')!=0 or old.get('runner_manifest_state')!='COLLECTED'):
            raise ValueError('Previous remote/collection state unknown; reconcile read-only')
        old_revision=old.get('interface_revision') or p.parents[2].name.removeprefix('source-interface-')
        if old_revision==revision and old.get('identity')==identity and old.get('runner_exit_code')==0:
            raise ValueError('Completed frozen request exists; do not repeat')

def invoke(project,label,category='primary',repair_ticket=None):
    campaign=ROOT/'experiments/dram-see-v4/interface-completion-r1/campaign.json'
    if campaign.is_file():
        source=campaign.parent/'control.py'
        spec=importlib.util.spec_from_file_location('_approved_completion_controller',source)
        controller=importlib.util.module_from_spec(spec)
        exec(compile(source.read_bytes(),str(source),'exec'),controller.__dict__)
        return controller.invoke(project,label,category,repair_ticket)
    revision,runtime,project=resolve_request(project,label)
    here=ROOT/f'experiments/dram-see-v4/source-interface-{revision}'
    spec=importlib.util.spec_from_file_location('_input_checker_'+revision,here/'build_interface.py')
    builder=importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    proof=builder.check_project(project)
    lockpath=ROOT/'local_runtime/dram-see-v4/source-probe/execution.lock'
    lock=lockpath.open('a+b')
    if lock.seek(0,2)==0: lock.write(b'0'); lock.flush()
    lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    folder=runtime/'launches'/label
    try:
        previous=sorted(RUNTIME_BASE.glob('source-interface-*/launches/*/execution.json'))
        identity=[proof['case_id'],proof['stored_bit'],proof['variant']]
        validate_history(previous,identity,revision)
        folder.mkdir(parents=True,exist_ok=False)
        state=folder/'execution.json'
        record=dict(schema='dram-see-v4-source-runner-invocation-v2',label=label,identity=identity,interface_revision=revision,
            started_utc=utc(),launcher_pid=os.getpid(),project=project.relative_to(ROOT).as_posix(),
            state='PREPARING',runner_exit_code=None,automatic_retry=False,solver_runner='scripts/tcad.py',
            runner_sha256=sha(ROOT/'scripts/tcad.py'),offline_input_check=proof,
            source_input_sha256={p.relative_to(project).as_posix():sha(p) for p in sorted(project.rglob('*')) if p.is_file()},
            invocation_budget_position=len(previous)+1,maximum_invocations=19,
            prior_invocations=[p.relative_to(ROOT).as_posix() for p in previous],
            invocation_controller_sha256=sha(Path(__file__)))
        def save():
            temp=state.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8',newline='\n');temp.replace(state)
        save()
        try:
            argv=[sys.executable,'-B',str(ROOT/'scripts/tcad.py'),'run',str(project)]
            record['argv']=argv
            with (folder/'stdout.log').open('xb') as out,(folder/'stderr.log').open('xb') as err:
                child=subprocess.Popen(argv,cwd=ROOT,stdout=out,stderr=err)
                record.update(state='RUNNING',runner_pid=child.pid);save()
                record['runner_exit_code']=child.wait()
            record['state']='RUNNER_EXITED'
            stdout=(folder/'stdout.log').read_text(encoding='utf-8',errors='replace')
            match=re.search(r'^Run evidence:\s*(.+)$',stdout,re.MULTILINE)
            if match:
                run=Path(match.group(1).strip()).resolve()
                if not run.is_relative_to((ROOT/'local_runtime/runs').resolve()):
                    raise ValueError('Unexpected evidence root')
                record['run_id']=run.name
                mp=run/'manifest.json'
                if mp.is_file():
                    manifest=read(mp)
                    record.update(runner_manifest_state=manifest.get('state'),ssh_exit_code=manifest.get('ssh_exit_code'),
                        result_archive_sha256=manifest.get('results_sha256'),
                        manifest_input_matches_project=manifest.get('input_sha256')==record['source_input_sha256'])
            record['scientific_status']='PENDING_AUDIT'
        except Exception as exc:
            record.update(state='LOCAL_INVOCATION_ERROR',error=repr(exc),scientific_status='NOT_VERIFIED')
        finally:
            record['finished_utc']=utc();save()
        print(json.dumps({k:record.get(k) for k in ('label','state','run_id','runner_exit_code','runner_manifest_state','ssh_exit_code')}),flush=True)
        return 0 if record['state']=='RUNNER_EXITED' and record['runner_exit_code']==0 and record.get('manifest_input_matches_project') is True else 1
    finally:
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project',type=Path);p.add_argument('label')
    p.add_argument('--category',choices=('primary','reserve'),default='primary');p.add_argument('--repair-ticket',type=Path)
    a=p.parse_args();raise SystemExit(invoke(a.project,a.label,a.category,a.repair_ticket))
