"""Independent storage prediction; original owner, budget and adapter preserved."""
from supervisor import *
import supervisor as base


def assert_no_competing_scheduler(rows):
    base.assert_no_competing_scheduler(rows)
    parents={int(r['ProcessId']):int(r['ParentProcessId']) for r in rows}
    ancestors={os.getpid()};pid=os.getpid()
    while parents.get(pid) and parents[pid] not in ancestors:
        pid=parents[pid];ancestors.add(pid)
    for row in rows:
        cmd=row.get('CommandLine') or ''
        scheduler=re.search(r'(?:continue(?:_[a-z0-9]+)*|campaign_runner|pilot_runner)\.py(?:[\s"\']|$)',cmd,re.I)
        if scheduler and int(row['ProcessId']) not in ancestors:
            raise RuntimeError('Other live scheduler PID '+str(row['ProcessId']))


def preflight(label,request=None):
    rows=local_processes();assert_no_competing_scheduler(rows)
    remote=remote_probe();limits=c.contract()['budgets']
    free=shutil.disk_usage(c.ROOT).free;used=storage_bytes()
    forecast=0;detail=None
    if request and request['event_count']:
        import storage_forecast_r4 as cost
        detail=cost.forecast(request,sorted((c.RT/'transport/runs').glob('*/record.json')))
        forecast=detail['estimated_output_bytes']
    result=dict(utc=c.utc(),label=label,local_processes=rows,remote=remote,local_free_bytes=free,
                conditional_transport_output_bytes=forecast,transport_forecast_evidence=detail,
                stage_local_bytes=used,budget=budget())
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    c.write(c.RT/'preflights'/stamp/'evidence.json',result)
    c.require(not remote['active_solver_lines'] and remote['values']['LOCK_FREE']==1,'Remote solver/lock busy; protect original job')
    c.require(free>=limits['minimum_local_free_GiB']*GIB+forecast*3,'Local free storage below floor plus archive allowance')
    c.require(remote['values']['FREE_KIB']*1024>=limits['minimum_remote_free_GiB']*GIB+forecast,'Remote free storage below floor plus batch allowance')
    c.require(remote['values']['AVAILABLE_MEMORY_KIB']*1024>=limits['minimum_remote_available_memory_GiB']*GIB,'Remote memory below floor')
    c.require(used+remote['values']['STAGE_KIB']*1024+forecast*4<limits['storage_GiB']*GIB,'Combined retained storage cap reached')
    return c.ref(c.RT/'preflights'/stamp/'evidence.json')


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
    corrective=bool(request and request.get('corrective_of'))
    if kind=='transport':
        import transport_material_r2 as transport
        c.require(request==transport.request(label),'Unregistered transport request')
        if corrective:
            c.require(label=='nc-r1-init-h-c1' and request['corrective_of']=='nc-r1-init-h','Unregistered correction')
            prior=c.read(c.OLD_OPS/'operations/nc-r1-init-h/operation.json')
            c.require(prior['state']=='FAILED_COLLECTED' and prior['ssh_exit_code']==prior['remote_exit_code']==2 and prior['collection_exit_code']==0,'Original failure not known')
            c.require(b['transport_corrective_calls']<c.contract()['budgets']['transport_corrective_calls'],'Correction allocation exhausted')
            c.require(b['transport_replay_primaries']+request['event_count']<=c.contract()['budgets']['transport_replay_primaries'],'Replay cap exhausted')
        else:c.require(b['transport_normal_calls']<c.contract()['budgets']['transport_primary_calls'],'Normal transport allocation exhausted')
        c.require(b['transport_unique_primaries_requested']+request['event_count']<=c.contract()['budgets']['transport_unique_primaries'],'Unique primary allocation exhausted')
    else:c.require(request is None,'Nontransport operation cannot declare events')
    before=preflight(label,request)
    row=dict(schema='nuclear-closure-attempt-r1',label=label,kind=kind,request=request,corrective=corrective,
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
