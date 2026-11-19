"""Single ownership, original-directory reconciliation and conservative budgets."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import common as c

OWNER_LOCK=c.ROOT/'local_runtime/dram-see-v4/interface-completion-r1/recovery-20261014/continuation/owner.lock'
GIB=1024**3


@contextmanager
def ownership(path=OWNER_LOCK):
    windows=sys.platform=='win32'
    if windows:
        import msvcrt
    else:
        import fcntl
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    stream=path.open('a+b')
    if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
    stream.seek(0)
    try:
        if windows:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BaseException:stream.close();raise RuntimeError('Another scheduler owns the shared local lock')
    try:yield
    finally:
        try:
            stream.seek(0)
            if windows:msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
        finally:stream.close()


def local_processes():
    script="Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|ssh).*' } | Select-Object ProcessId,ParentProcessId,CreationDate,Name,CommandLine | ConvertTo-Json -Depth 3 -Compress"
    p=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,timeout=30)
    c.require(p.returncode==0,'Cannot verify local process ownership')
    data=json.loads(p.stdout.decode('utf-8-sig') or '[]')
    return data if isinstance(data,list) else [data]


def assert_no_competing_scheduler(rows):
    parents={int(r['ProcessId']):int(r['ParentProcessId']) for r in rows}
    ancestors={os.getpid()};pid=os.getpid()
    while parents.get(pid) and parents[pid] not in ancestors:
        pid=parents[pid];ancestors.add(pid)
    for row in rows:
        cmd=row.get('CommandLine') or ''
        scheduler=re.search(r'(?:continue|campaign_runner|pilot_runner)\.py(?:[\s"\']|$)',cmd,re.I)
        if scheduler and int(row['ProcessId']) not in ancestors:
            raise RuntimeError('Other live scheduler PID '+str(row['ProcessId']))


def remote_probe():
    tcad=c.module(c.ROOT/'scripts/tcad.py','_nc_strict_connection')
    cfg,ssh,_=tcad.connection();base=cfg['remote_root'].rstrip('/')
    # These are observation commands. The lock probe holds it only for the true builtin.
    script='\n'.join(['set -eu',
      "printf 'UTC '; date -u +%Y-%m-%dT%H:%M:%SZ",
      "printf 'FREE_KIB '; df -Pk "+shlex.quote(base)+" | awk 'NR==2{print $4}'",
      "awk '/^MemAvailable:/{print \"AVAILABLE_MEMORY_KIB \" $2}' /proc/meminfo",
      "printf 'STAGE_KIB '; du -sk "+shlex.quote(base+'/dram-see-v4/transport-probe/operations')+"/nc-r1-* "+shlex.quote(base+'/runs')+"/*nuclear-closure* 2>/dev/null | awk '{s+=$1} END{print s+0}'",
      'if flock -n '+shlex.quote(base+'/.solver.lock')+' -c true; then echo LOCK_FREE 1; else echo LOCK_FREE 0; fi',
      'for d in /proc/[0-9]*; do',
      ' name=$(cat "$d/comm" 2>/dev/null || true)',
      ' case "$name" in sdevice*|snmesh*|sde|transport_mat*)',
      ' printf "ACTIVE %s %s " "${d##*/}" "$name"; readlink "$d/cwd" || true;',
      " awk '/^(Threads|Cpus_allowed_list):/' \"$d/status\" ;; esac",'done',''])
    p=subprocess.run(ssh+['bash -s'],input=script.encode(),capture_output=True,timeout=45)
    c.require(p.returncode==0,'Strict SSH observation failed: '+p.stderr.decode(errors='replace')[-1200:])
    text=p.stdout.decode(errors='replace');values={}
    for line in text.splitlines():
        parts=line.split()
        if len(parts)==2 and parts[0] in ('FREE_KIB','AVAILABLE_MEMORY_KIB','STAGE_KIB','LOCK_FREE'):
            values[parts[0]]=int(parts[1])
    c.require(all(k in values for k in ('FREE_KIB','AVAILABLE_MEMORY_KIB','STAGE_KIB','LOCK_FREE')),'Incomplete remote observation')
    return dict(utc=c.utc(),raw_stdout=text,raw_stderr=p.stderr.decode(errors='replace'),values=values,
                active_solver_lines=[s for s in text.splitlines() if s.startswith('ACTIVE ')])


def storage_bytes():
    # Includes original archives, all extracted copies, failed outputs and implementation evidence.
    bases=[c.RT]+list((c.OLD_OPS/'operations').glob('nc-r1-*'))+list((c.OLD_OPS/'inputs').glob('nc-r1-*'))
    for a in (c.RT/'attempts').glob('*.json'):
        row=c.read(a)
        if row.get('run_directory'):bases.append(c.ROOT/row['run_directory'])
    files={p.resolve() for base in bases for p in base.rglob('*') if p.is_file()}
    return sum(p.stat().st_size for p in files)


def budget():
    attempts=[c.read(p) for p in sorted((c.RT/'attempts').glob('*.json'))]
    labels=[r['label'] for r in attempts]
    c.require(len(labels)==len(set(labels)),'Duplicate attempt identity')
    transport=[a for a in attempts if a['kind']=='transport']
    tcad=[a for a in attempts if a['kind']=='tcad']
    primary=[a for a in transport if not a.get('corrective',False)]
    corrections=[a for a in transport if a.get('corrective',False)]
    unique={a['request']['label']:a['request']['event_count'] for a in primary}
    c.require(len(unique)==len(primary),'Duplicate independent request')
    reserved=set(labels)
    for p in (c.OLD_OPS/'operations').glob('nc-r1-*/operation.json'):
        c.require(p.parent.name in reserved,'Untracked original operation: '+p.parent.name)
    result=dict(schema='nuclear-closure-budget-r1',utc=c.utc(),transport_normal_calls=len(primary),
        transport_corrective_calls=len(corrections),transport_unique_primaries_requested=sum(unique.values()),
        transport_replay_primaries=sum(a['request']['event_count'] for a in corrections),tcad_calls=len(tcad),
        tcad_corrective_calls=sum(a.get('corrective',False) for a in tcad),
        compile_calls=sum(a['kind']=='compile' for a in attempts),postprocess_calls=sum(a['kind']=='postprocess' for a in attempts),
        reservations=len(attempts),cost_semantics='Every reserved launch counts conservatively, including unknown and failed attempts. Reconciliation adds no attempt.',
        old_budget=c.contract()['old_plan'],limits=c.contract()['budgets'])
    b=result['limits']
    c.require(result['transport_normal_calls']<=b['transport_primary_calls'] and result['transport_corrective_calls']<=b['transport_corrective_calls'],'Transport call limit exceeded')
    c.require(result['transport_unique_primaries_requested']<=b['transport_unique_primaries'] and result['transport_replay_primaries']<=b['transport_replay_primaries'],'Primary/replay limit exceeded')
    c.require(result['tcad_calls']<=b['tcad_total'] and result['tcad_corrective_calls']<=b['tcad_corrective'],'TCAD limit exceeded')
    return result


def preflight(label,request=None):
    rows=local_processes();assert_no_competing_scheduler(rows)
    remote=remote_probe();limits=c.contract()['budgets']
    free=shutil.disk_usage(c.ROOT).free;used=storage_bytes()
    forecast=0
    if request and request['event_count']:
        densities=[]
        for p in (c.RT/'transport/runs').glob('*/record.json'):
            row=c.read(p);n=row['request']['event_count']
            if n>0:
                densities.append(sum((p.parent/name).stat().st_size for name in row['output_sha256'])/n)
        # Conditional conservative screen, not a deterministic bound on nuclear multiplicity.
        forecast=max(32*1024**2, int(4*max(densities,default=65536)*request['event_count']))
    result=dict(utc=c.utc(),label=label,local_processes=rows,remote=remote,local_free_bytes=free,
                conditional_transport_output_bytes=forecast,
                stage_local_bytes=used,budget=budget())
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    c.write(c.RT/'preflights'/stamp/'evidence.json',result)
    c.require(not remote['active_solver_lines'] and remote['values']['LOCK_FREE']==1,'Remote solver/lock busy; protect original job')
    c.require(free>=limits['minimum_local_free_GiB']*GIB+forecast*3,'Local free storage below floor plus archive allowance')
    c.require(remote['values']['FREE_KIB']*1024>=limits['minimum_remote_free_GiB']*GIB+forecast,'Remote free storage below floor plus batch allowance')
    c.require(remote['values']['AVAILABLE_MEMORY_KIB']*1024>=limits['minimum_remote_available_memory_GiB']*GIB,'Remote memory below floor')
    c.require(used+remote['values']['STAGE_KIB']*1024+forecast*4<limits['storage_GiB']*GIB,'Combined retained storage cap reached')
    return c.ref(c.RT/'preflights'/stamp/'evidence.json')


def update_status(**fields):
    p=c.RT/'status.json';value=c.read(p) if p.exists() else {'schema':'nuclear-closure-status-r1'}
    value.update(fields,updated_utc=c.utc())
    c.write(p,value,exclusive=False)


def operation(label,inputs,kind,request=None,timeout=172800):
    """One serialized original-adapter launch. Existing attempt never spawns again."""
    path=c.RT/'attempts'/(label+'.json');op=c.OLD_OPS/'operations'/label
    if path.exists():
        row=c.read(path)
        c.require(row['kind']==kind,'Attempt kind changed')
        if request is not None:c.require(row['request']==request,'Attempt request changed')
        # This is reconciliation of existing evidence, not a second invocation.
        c.require((op/'operation.json').exists(),'Reserved attempt has no original receipt; inspect before repair')
        current=c.read(op/'operation.json')
        c.require(current.get('state')=='COLLECTED_PENDING_AUDIT','Prior attempt unknown/failed; no blind resubmission')
        c.require(all(current.get(k)==0 for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')),'Original operation exits unknown/failed')
        return op
    c.require(not op.exists(),'Original operation exists outside ledger')
    c.require(kind in ('compile','transport','postprocess'),'Unknown operation cost category')
    b=budget()
    if kind=='transport':
        import transport
        c.require(request==transport.request(label),'Unregistered transport request')
        c.require(b['transport_normal_calls']<c.contract()['budgets']['transport_primary_calls'],'Normal transport allocation exhausted')
        c.require(b['transport_unique_primaries_requested']+request['event_count']<=c.contract()['budgets']['transport_unique_primaries'],'Unique primary allocation exhausted')
    else:c.require(request is None,'Nontransport operation cannot declare events')
    before=preflight(label,request)
    row=dict(schema='nuclear-closure-attempt-r1',label=label,kind=kind,request=request,corrective=False,
        created_utc=c.utc(),owner_pid=os.getpid(),preflight=before,exit_code=None,state='RESERVED',
        input_directory=Path(inputs).relative_to(c.ROOT).as_posix(),
        input_hashes={p.relative_to(inputs).as_posix():c.sha(p) for p in sorted(Path(inputs).rglob('*')) if p.is_file()})
    c.write(path,row);budget()
    command=[sys.executable,'-B',str(c.HERE.parent/'transport-probe/operation.py'),label,str(inputs),'--timeout',str(timeout)]
    log=c.RT/'logs'/label;log.mkdir(parents=True,exist_ok=False)
    with (log/'stdout.log').open('xb') as out,(log/'stderr.log').open('xb') as err:
        child=subprocess.Popen(command,cwd=c.ROOT,stdout=out,stderr=err)
        row.update(state='RUNNING',pid=child.pid,argv=command);c.write(path,row,exclusive=False)
        update_status(state='RUNNING',owner_pid=os.getpid(),active_child=child.pid,active_label=label)
        row['exit_code']=child.wait()
    row.update(state='EXECUTED' if row['exit_code']==0 else 'FAILED_OR_UNKNOWN',finished_utc=c.utc())
    c.write(path,row,exclusive=False);c.write(c.RT/'budget.json',budget(),exclusive=False)
    update_status(active_child=None,active_label=None)
    c.require(row['exit_code']==0,'Operation failed or unknown; original evidence retained: '+label)
    return op
