"""A dormant successor waits for the old scheduler, then runs only this pilot."""
import argparse
import math
import os
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
import control as c
import report as reporter

CURRENT = dict(schema='dram-see-v4-3d-pilot-state-r1', scheduler_pid=os.getpid(), automatic_retry=False)


def update(state, **kwargs):
    CURRENT.update(state=state, updated_utc=c.utc(), **kwargs)
    c.save(c.STATE/'coordination.json', CURRENT)
    path=c.STATE/'events.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    import json
    with path.open('a',encoding='utf-8') as stream:
        stream.write(json.dumps(CURRENT,ensure_ascii=False)+'\n')


def wait_old(wait):
    old=c.module(c.V4/'interface-completion-r1/campaign_runner.py','_successor_old')
    last=None
    while True:
        d=c.read(c.OLD/'coordination.json')
        alive=old.pid_alive(d['scheduler_pid'])
        signature=(d.get('state'),d.get('active_job'),alive)
        if signature!=last:
            update('WAITING_OLD_SCHEDULER', old_state=d.get('state'),old_job=d.get('active_job'), old_scheduler_alive=alive)
            last=signature
        if not alive:
            with c.lock(c.OLD/'scheduler.lock'):
                c.old_queue_gate()
            return
        if not wait:
            raise ValueError('Old scheduler is running; no pilot work dispatched')
        time.sleep(30)


def stage_result(name, value):
    path=c.STATE/'stage-results'/(name+'.json')
    if path.exists():
        c.require(c.read(path)==value, 'Stage result changed; explicit reviewed revision required')
    else:
        c.save(path,value,new=True)
    CURRENT['latest_report']=reporter.generate()


def completed_operation(package,label,kind,role=None,timeout=900):
    p=c.STATE/('calls' if kind=='geant' else 'operations')/label/'execution.json'
    if p.exists():
        d=c.read(p);c.verify_history([d])
    else:
        update('OPERATION_RUNNING',active_job=label,kind=kind)
        d=c.invoke_operation(package,label,kind,role,timeout)
    c.require(d['state'] in ('COMPLETED','KNOWN_FAILURE'),'Original operation unknown; stop all dispatch')
    return d['state']=='COMPLETED'


def tcad_role(case):
    label='pilot3d-'+case.lower()+'-b1-r1';role=case.lower()+'-b1-3d'
    if (c.STATE/'gates'/(role+'.json')).exists():
        c.pilot_gate(role);return True
    project=c.RT/'source-interface-3d-r1/inputs'/('v4-source-interface-3d-r1-'+case.lower()+'-b1-main')
    call=c.STATE/'calls'/label/'execution.json'
    if call.exists():
        record=c.read(call);c.verify_history([record])
    else:
        update('TCAD_RUNNING',active_job=label)
        # This covers the mesh-stage prefix. The same SDE step performs the
        # actual-mesh conditional full-field resource gate before SDevice.
        record=c.invoke_tcad(project,label,1024**3)
    c.require(record['state'] in ('COMPLETED','KNOWN_FAILURE'),'Original TCAD call unknown; stop all dispatch')
    if record['state']=='KNOWN_FAILURE':
        stage_result(label,dict(passed=False,known_failure=True,call=c.reference(call)));return False
    field=c.module(c.V4/'source-field-audit-3d-r1/audit_fields.py','_successor_field')
    run=c.ROOT/'local_runtime/runs'/record['run_id'];op_label=label+'-fields'
    inputs=c.RT/'transport-probe/inputs'/op_label
    op=c.RT/'transport-probe/operations'/op_label
    if not inputs.exists():
        prepared=field.prepare(run,op_label,project)
        c.save(c.STATE/'field-preparation'/(op_label+'.json'),prepared,new=True)
    else:
        c.require((c.STATE/'field-preparation'/(op_label+'.json')).exists(),'Orphan prepared fields require review')
    prepared=c.read(c.STATE/'field-preparation'/(op_label+'.json'))
    # Conservative conditional budget from measured old main-frame throughput,
    # scaled by total bytes and 4x allowance. It is not a measured 3D runtime.
    timeout=math.ceil(max(1800,prepared['tdr_bytes']/2931715.59*3.0833*4+600))
    c.require(timeout<=86400,'Field estimate exceeds one-day operation bound; root must review cost')
    if not completed_operation(inputs,op_label,'field',timeout=timeout):
        stage_result(op_label,dict(passed=False,known_failure=True));return False
    if not (op/'field-extraction-record.json').exists():
        field.collect_receipt(op)
    field_out=c.RT/'source-field-audit-3d-r1/audits'/label
    if not field_out.exists():
        result=field.audit(run,op,project,field_out)
    else:
        result=c.read(field_out/'audit.json')
    if not result['passed']:
        stage_result(op_label,dict(passed=False,field_audit=c.reference(field_out/'audit.json')));return False
    acceptance=c.module(c.HERE/'acceptance.py','_successor_acceptance')
    if not (c.STATE/'audits'/label/'audit.json').exists():
        accepted=acceptance.accept(label,field_out/'audit.json')
    else:
        accepted=c.read(c.STATE/'audits'/label/'audit.json')
    stage_result(label,dict(passed=accepted['passed'],audit=c.reference(c.STATE/'audits'/label/'audit.json')))
    return accepted['passed']


def transport_pilot():
    transport=c.module(c.V4/'matched-transport-r1/control.py','_successor_transport')
    audit=c.module(c.V4/'matched-transport-r1/audit_matched.py','_successor_transport_audit')
    label='matched-build-r1';build=c.RT/'transport-probe/operations'/label
    package=c.RT/'matched-transport-r1/inputs'/label
    if not completed_operation(package,label,'build'):
        stage_result(label,dict(passed=False,known_failure=True));return False
    requests=transport.contract()['requests']
    states={}
    for request in requests:
        label=request['label'];role=request['mode']+'-'+request['arm'].lower()
        if request['mode']!='init':
            if not all(states.get('matched-init-'+arm+'-r1') is True for arm in ('h','e')):
                stage_result(label,dict(passed=False,dispatched=False,blocked_by=['matched H/E initialization']))
                states[label]=False
                continue
            transport.require_initialization_gate()
        package=c.RT/'matched-transport-r1/inputs'/label
        if not package.exists():package=transport.prepare(label,build)
        if not completed_operation(package,label,'geant',role):
            stage_result(label,dict(passed=False,known_failure=True));states[label]=False
            continue
        native=c.RT/'transport-probe/operations'/label
        run=c.RT/'matched-transport-r1/runs'/label
        if not (run/'record.json').exists():transport.collect(native)
        output=c.RT/'matched-transport-r1/audits'/label
        # Audit CLI is used so the exact public entrypoint remains the witness.
        if not (output/'audit.json').exists():
            import subprocess
            log=c.STATE/'stage-logs';log.mkdir(parents=True,exist_ok=True)
            argv=[sys.executable,'-B',str(c.V4/'matched-transport-r1/audit_matched.py'),
                  'init' if request['mode']=='init' else 'events',str(run),'--output',str(output)]
            with (log/(label+'.stdout.log')).open('xb') as out,(log/(label+'.stderr.log')).open('xb') as err:
                result=subprocess.run(argv,cwd=c.ROOT,stdout=out,stderr=err)
            c.save(log/(label+'.command.json'),dict(argv=argv,exit_code=result.returncode),new=True)
        result=c.read(output/'audit.json')
        stage_result(label,dict(passed=result['passed'],audit=c.reference(output/'audit.json')))
        states[label]=result['passed']
        if request is requests[1] and all(states.get('matched-init-'+arm+'-r1') is True for arm in ('h','e')) and not (c.RT/'matched-transport-r1/gates/initialization.json').exists():
            transport.gate_initialization()
    return all(states.values()) and len(states)==len(requests)


def main(wait=False):
    with c.lock(c.STATE/'scheduler.lock'):
        try:
            c.check_release();wait_old(wait)
            update('OLD_QUEUE_RELEASED',active_job=None)
            a0=tcad_role('A0');a1=tcad_role('A1') if a0 else False
            # Known TCAD/field failures pause only that branch; unknown remote
            # outcomes raise and stop everything until a root reconciliation.
            transport=transport_pilot()
            update('PILOT_COMPLETE' if a0 and a1 and transport else 'PILOT_PAUSED_WITH_RECORDED_FAILURE',
                   active_job=None,tcad_a0_passed=a0,tcad_a1_passed=a1,transport_passed=transport,
                   future_batches_started=False,latest_report=reporter.generate())
            return 0 if a0 and a1 and transport else 2
        except Exception as exc:
            update('REQUIRES_ROOT_REVIEW_NO_RESUBMIT',error=repr(exc),traceback=traceback.format_exc(),
                   latest_report=reporter.generate())
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--wait-for-old',action='store_true')
    raise SystemExit(main(parser.parse_args().wait_for_old))
