"""Record one approved r2 invocation of scripts/tcad.py; no alternate solver runner."""
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
HERE=ROOT/'experiments/dram-see-v4/source-interface-r2'
RUNTIME=ROOT/'local_runtime/dram-see-v4/source-interface-r2'

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def utc(): return datetime.now(timezone.utc).isoformat()

def invoke(project,label):
    project=Path(project).resolve()
    if not project.is_relative_to(RUNTIME.resolve()) or not re.fullmatch('r2-[a-z0-9-]+',label):
        raise ValueError('Explicit new r2 project/label required')
    spec=importlib.util.spec_from_file_location('_r2_input_checker',HERE/'build_interface.py')
    builder=importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    proof=builder.check_project(project)
    lockpath=ROOT/'local_runtime/dram-see-v4/source-probe/execution.lock'
    lock=lockpath.open('a+b')
    if lock.seek(0,2)==0: lock.write(b'0'); lock.flush()
    lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    folder=RUNTIME/'launches'/label
    try:
        previous=list((RUNTIME/'launches').glob('*/execution.json'))
        if len(previous)>=19: raise ValueError('Maximum 19 new solver invocations reached')
        identity=[proof['case_id'],proof['stored_bit'],proof['variant']]
        for p in previous:
            old=read(p)
            if old['state'] not in ('RUNNER_EXITED','LOCAL_INVOCATION_ERROR') or old.get('runner_exit_code') is None:
                raise ValueError('Previous local/remote job state unknown; reconcile read-only')
            if old.get('identity')==identity and old.get('runner_exit_code')==0:
                raise ValueError('Completed frozen request exists; do not repeat')
        folder.mkdir(parents=True,exist_ok=False)
        state=folder/'execution.json'
        record=dict(schema='dram-see-v4-r2-runner-invocation-v1',label=label,identity=identity,
            started_utc=utc(),launcher_pid=os.getpid(),project=project.relative_to(ROOT).as_posix(),
            state='PREPARING',runner_exit_code=None,automatic_retry=False,solver_runner='scripts/tcad.py',
            runner_sha256=sha(ROOT/'scripts/tcad.py'),offline_input_check=proof,
            source_input_sha256={p.relative_to(project).as_posix():sha(p) for p in sorted(project.rglob('*')) if p.is_file()},
            invocation_budget_position=len(previous)+1,maximum_invocations=19)
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
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project',type=Path);p.add_argument('label');a=p.parse_args()
    raise SystemExit(invoke(a.project,a.label))
