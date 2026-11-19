# Independent completion of original PMI build validation; selected-event science unchanged.
# Stable-index audit with reviewed storage-r4 preflight and original-input reconciliation.
# Independent storage forecast and never-launched input reconciliation.
# Independent read-only audit recovery; original material-r2 operations are reused.
# Independent material-realization continuation; old entry and failed attempt retained.
"""Only nuclear-closure scheduler. Existing attempts are observed, never resubmitted."""
from datetime import datetime,timezone,timedelta
import os
import sys
import traceback
import common as c
import supervisor_storage_r4 as s
import prepared_inputs_r4 as prepared
import transport_index_r5 as t


def check_release():
    path=c.HERE/'release-pmi-r6.json'
    release=c.read(path)
    c.require(release['execution_enabled'] is True and release['contract_sha256']==c.sha(c.HERE/'contract.json'),'PMI recovery r6 not released')
    for item in release['files']:c.check_ref(item)
    return c.ref(path)


def transport_stage():
    check_release()
    t.check_release()
    build=c.OLD_OPS/'operations'/t.BUILD_LABEL
    if not (c.RT/'attempts'/(t.BUILD_LABEL+'.json')).exists():
        inputs=t.compile_inputs()
    else:inputs=c.OLD_OPS/'inputs'/t.BUILD_LABEL
    s.operation(t.BUILD_LABEL,inputs,'compile',timeout=1800)
    t.assert_operation_complete(build)
    if (c.RT/'selected-event.json').exists():
        chosen=c.read(c.RT/'selected-event.json')
        c.check_ref(chosen['record']);c.check_ref(chosen['audit'])
        c.require(chosen.get('transport_revision')=='audit-index-r5','Existing selection belongs to another audit revision; reconcile original evidence')
        c.require(c.read(c.check_ref(chosen['audit']))['audit_code_sha256']==c.sha(c.HERE/'transport_audit_indexed_r5.py'),'Selected audit code differs')
        return True
    for stage in c.contract()['transport']['stage_order']:
        stagefile=c.RT/'transport/stages-index-r5'/(stage+'.json')
        if stagefile.exists():
            evidence=c.read(stagefile)
            c.require(evidence['passed'] is True,'Previously failed stage')
            for item in evidence['audits']:c.check_ref(item)
            if evidence['qualifying_event_found']:
                chosen=t.choose(stage)
                c.require(chosen is not None,'Prior stage witness no longer reproduces')
                c.write(c.RT/'selected-event.json',chosen)
                s.update_status(state='NATURAL_EVENT_SELECTED',selected_event=c.ref(c.RT/'selected-event.json'))
                return True
            continue
        rows=[r for r in t.contract()['requests'] if r['closure_stage']==stage]
        for r in rows:
            check_release()
            t.check_release()
            label=r['label'];attempt=c.RT/'attempts'/(label+'.json')
            if stage!='P0' and not attempt.exists():
                window=c.RT/'transport/sampling-window.json'
                if not window.exists():
                    now=datetime.now(timezone.utc)
                    c.write(window,dict(started_utc=now.isoformat(),deadline_utc=(now+timedelta(hours=48)).isoformat()))
                deadline=datetime.fromisoformat(c.read(window)['deadline_utc'])
                if datetime.now(timezone.utc)>=deadline:
                    s.update_status(state='NO_WITNESS_DISPATCH_WINDOW_EXHAUSTED',scientific_passed=False,partial_stage=stage)
                    return False
            inputs=c.OLD_OPS/'inputs'/label
            if not attempt.exists():inputs=prepared.reuse_or_prepare(label,build)
            operation=s.operation(label,inputs,'transport',r)
            t.collect(operation);audit=t.audit(label)
            c.require(audit['passed'] is True,'Transport record gate failed: '+label)
            print('TRANSPORT_ACCEPTED '+label,flush=True)
        chosen=t.choose(stage)
        c.write(stagefile,dict(schema='nuclear-closure-transport-stage-r1',stage=stage,passed=True,
            finished_utc=c.utc(),audits=[c.ref(c.RT/'transport/audits-index-r5'/r['label']/'audit.json') for r in rows],
            qualifying_event_found=chosen is not None))
        if chosen is not None:
            c.write(c.RT/'selected-event.json',chosen)
            s.update_status(state='NATURAL_EVENT_SELECTED',selected_event=c.ref(c.RT/'selected-event.json'))
            return True
    s.update_status(state='NO_WITNESS_EVENT_CAP_EXHAUSTED',scientific_passed=False)
    return False


def main():
    with s.ownership():
        s.assert_no_competing_scheduler(s.local_processes())
        s.update_status(owner_pid=os.getpid(),active_child=None,state='CHECKING_RELEASE',scientific_passed=False)
        try:
            if not transport_stage():return 0
            if not (c.HERE/'release-source.json').exists():
                s.update_status(state='WAITING_SOURCE_RELEASE',scientific_passed=False);return 0
            c.check_release('source')
            pmi=c.module(c.HERE/'native_compile_r2.py','_nc_pmi_compile')
            pmi.ensure_compiled()
            campaign=c.module(c.HERE/'campaign_index_r5.py','_nc_device_campaign')
            campaign.qualify()
            if not (c.HERE/'release-device.json').exists():
                s.update_status(state='WAITING_DEVICE_RELEASE',scientific_passed=False);return 0
            c.check_release('device')
            campaign.run()
            return 0
        except Exception as exc:
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            c.write(c.RT/'failures'/(stamp+'.json'),dict(utc=c.utc(),error=repr(exc),traceback=traceback.format_exc(),
                budget=s.budget(),automatic_resubmit=False))
            s.update_status(state='PAUSED_RECORDED_FAILURE_OR_UNKNOWN',error=repr(exc),active_child=None,scientific_passed=False)
            traceback.print_exc();return 2
        finally:
            s.update_status(owner_pid=None,active_child=None)
            c.write(c.RT/'budget.json',s.budget(),exclusive=False)


if __name__=='__main__':
    if len(sys.argv)!=1:raise SystemExit('No adopt/force/retry interface; inspect original attempts')
    raise SystemExit(main())
