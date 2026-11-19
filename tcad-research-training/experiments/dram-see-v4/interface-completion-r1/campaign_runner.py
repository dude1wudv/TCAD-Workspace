"""One-shot serial executor for the approved 17 roles; never automatically retries."""
import argparse
import ctypes
from datetime import datetime, timezone
import importlib.util
import json
import math
import msvcrt
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import shlex
import csv

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
V4 = HERE.parent
RT = ROOT / 'local_runtime/dram-see-v4'
STATE = RT / 'interface-completion-r1'
R5 = RT / 'source-interface-r5'
PYTHON = sys.executable

def module(p, name):
    spec = importlib.util.spec_from_file_location(name, p); obj = importlib.util.module_from_spec(spec)
    exec(compile(Path(p).read_bytes(), str(p), 'exec'), obj.__dict__); return obj

a = module(HERE / 'acceptance.py', '_serial_acceptance')
read, sha, utc, rel, require = a.read, a.sha, a.utc, a.rel, a.api().require
CURRENT = dict(schema='dram-see-v4-interface-completion-state-r1', scheduler_pid=os.getpid(), automatic_retry=False)

def update(state, **kw):
    CURRENT.update(state=state, updated_utc=utc(), **kw)
    executions = [read(p) for p in (R5 / 'launches').glob('*/execution.json')]
    campaign = read(HERE / 'campaign.json')
    done = [r['role_id'] for r in campaign['roles'] if (STATE / 'gates' / (r['role_id'] + '.json')).exists()]
    CURRENT.update(completed_roles=done, pending_roles=[r['role_id'] for r in campaign['roles'] if r['role_id'] not in done],
                   historical_attempts=5, new_attempts=len(executions), reserve_used=sum(d['budget_category']=='reserve' for d in executions))
    tmp = STATE / 'coordination.tmp'; tmp.write_text(json.dumps(CURRENT, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(STATE / 'coordination.json')
    with (STATE / 'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(CURRENT, ensure_ascii=False) + '\n')

def check_release():
    release = read(HERE / 'release.json')
    require(release['passed'] is True and release['campaign_sha256']==sha(HERE/'campaign.json'), 'Release/campaign differs')
    for path, digest in release['files_sha256'].items(): require(sha(ROOT/path)==digest, 'Frozen implementation changed: '+path)
    protected = read(HERE/'protected-before.json')
    for path, digest in protected['immutable_files'].items(): require(sha(ROOT/path)==digest, 'Historical protected file changed: '+path)

def pid_alive(pid):
    # Windows query only; do not use os.kill(pid, 0), whose Windows semantics differ.
    kernel=ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x1000,False,int(pid))
    if not handle:return False
    try:
        code=ctypes.c_ulong();return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
    finally:kernel.CloseHandle(handle)

def call(argv, stem):
    folder=STATE/'stage-logs';folder.mkdir(exist_ok=True)
    with (folder/(stem+'.stdout.log')).open('xb') as out, (folder/(stem+'.stderr.log')).open('xb') as err:
        child=subprocess.Popen([PYTHON,'-B']+[str(x) for x in argv],cwd=ROOT,stdout=out,stderr=err)
        update('STAGE_RUNNING', active_child_pid=child.pid, active_stage=stem)
        code=child.wait()
    a.save_new(folder/(stem+'.json'),dict(argv=[str(x) for x in argv],exit_code=code,finished_utc=utc()))
    return code

def budget():
    reporter=module(HERE/'budget_report.py','_serial_budget')
    result=reporter.generate()
    report=module(HERE/'make_report.py','_serial_report').generate(result)
    update(CURRENT.get('state','BUDGET_UPDATED'),latest_budget=result['output_directory'],
           latest_report=report.get('output_directory'),report_publication_ready=report.get('publication_ready',False),
           report_errors=report.get('report_errors',[]))
    return result

def known_operation_failure(opdir):
    """Separate a collected native nonzero exit from a disconnected/unknown job."""
    import tarfile
    op=read(opdir/'operation.json')
    require(op['state']=='FAILED_COLLECTED' and op.get('collection_exit_code')==0 and
            type(op.get('ssh_exit_code')) is int and 0<op['ssh_exit_code']<255 and
            op.get('remote_exit_code')==op['ssh_exit_code'],'Operation outcome unknown; inspect original process before proceeding')
    require(sha(opdir/'results.tar')==op['archive_sha256'],'Failure collection archive changed')
    with tarfile.open(opdir/'results.tar') as tar:
        found=[m for m in tar.getmembers() if m.name.removeprefix('./')=='exit-code.txt']
        require(len(found)==1 and found[0].isfile() and found[0].size<32,'Original operation exit missing/ambiguous')
        raw=tar.extractfile(found[0]).read().strip()
    require(re.fullmatch(rb'\d+',raw) and int(raw)==op['remote_exit_code'],'Original operation exit differs')
    return dict(passed=False,known_failure=True,remote_exit_code=int(raw),operation_record=a.reference(opdir/'operation.json'))

def postprocess(label, run):
    opname=label+'-fields';opdir=RT/'transport-probe/operations'/opname
    inputs=RT/'transport-probe/inputs'/opname
    if not opdir.exists():
        require(not inputs.exists(), 'Prepared postprocessing state needs explicit reconciliation; no automatic resubmit')
        invocation=read(R5/'launches'/label/'execution.json')
        readiness=module(HERE/'resources.py','_postprocess_resources').check(invocation['identity'][2],opname+'-resource')
        require(readiness['passed'],'Postprocessing resource/process check failed before invocation')
        require(call([HERE/'prepare_fields.py',run.name,V4/'source-field-audit-r2/extract_fields.tcl',opname,'--family','gstep'],opname+'-prepare')==0,'Field preparation failed')
        evidence=read(inputs/'source-evidence.json');frames=len(evidence['tdr_sha256'])
        # Measured r4: 205 frames / 852.132342 s including transfer. r5 has 52 vs44 numeric commands.
        old_op=RT/'transport-probe/operations/r4-a1-mesh-tdr-diagnostic-r2/operation.json'
        previous=read(old_op);old_elapsed=(datetime.fromisoformat(previous['finished_utc'])-datetime.fromisoformat(previous['started_utc'])).total_seconds()
        manifest=read(run/'manifest.json')
        import tarfile
        with tarfile.open(run/'results.tar') as archive:
            sizes=[m.size for m in archive.getmembers() if m.isfile() and m.name.removeprefix('./') in evidence['tdr_sha256']]
        require(len(sizes)==frames,'Postprocessing frame count/size binding failed')
        scale=max(1.,sum(sizes)/frames/(573.01*2**20/205))
        estimate=old_elapsed*frames/205*(52/44)*scale
        timeout=math.ceil(max(900,3*estimate+300))
        a.save_new(STATE/'postprocess-budgets'/(opname+'.json'),dict(schema='dram-see-v4-postprocess-time-budget-r1',
            frames=frames,tdr_bytes=sum(sizes),reference_operation=rel(old_op),reference_operation_sha256=sha(old_op),
            reference_frames=205,reference_elapsed_s=old_elapsed,numeric_commands_scale=52/44,
            per_frame_bytes_scale=scale,estimated_operation_s=estimate,ssh_timeout_s=timeout,
            collection_timeout_s=180,unknown_outcome_action='Read-only reconciliation; never automatic resubmit'))
        call([V4/'transport-probe/operation.py',opname,inputs,'--timeout',str(timeout)],opname+'-run')
    op=read(opdir/'operation.json')
    if op.get('state')=='FAILED_COLLECTED':
        failure=known_operation_failure(opdir)
        path=STATE/'postprocess-failures'/(opname+'.json')
        if not path.exists():a.save_new(path,failure)
        return None
    require(op['state']=='COLLECTED_PENDING_AUDIT' and all(op.get(k)==0 for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')),'Postprocessing outcome failed/unknown')
    if not (opdir/'field-extraction-record.json').exists():
        require(call([V4/'stage2/collect_field_audit.py',opname],opname+'-receipt')==0,'Native extraction receipt failed')
    out=RT/'source-field-audit-r2/audit-dev'/label
    if not (out/'audit.json').exists():
        # Nonzero return is a recorded scientific failure, not permission to repeat the solve or extraction.
        call([V4/'source-field-audit-r2/audit_fields.py','full',run,'--extraction',opdir,'--output',out],opname+'-audit')
    require((out/'audit.json').is_file(),'No complete field audit; stop for investigation')
    return out/'audit.json'

def cleanup_task(plan):
    remote_evidence=plan['remote_target']+'/cleanup-'+plan['plan_id']
    return '\n'.join(['set -uo pipefail','set +e','bash remote-cleanup.sh','cleanup_rc=$?',
        'printf "%s\\n" "$cleanup_rc" > cleanup-exit-code.txt',
        'if [ -d '+shlex.quote(remote_evidence)+' ]; then cp -a -- '+shlex.quote(remote_evidence)+' ./cleanup-evidence; copy_rc=$?; else copy_rc=72; fi',
        'if [ "$cleanup_rc" -ne 0 ]; then exit "$cleanup_rc"; fi','exit "$copy_rc"',''])

def verify_cleanup_inputs(planner, inputs, plan):
    require((inputs/'remote-cleanup.sh').read_bytes()==planner.render_script(plan)
            and sha(inputs/'remote-cleanup.sh')==plan['script_sha256'],'Cleanup script differs from approved generated plan')
    require((inputs/'task.sh').read_bytes()==cleanup_task(plan).encode(),'Cleanup entry task differs from approved collection wrapper')

def cleanup_duplicates(role, label):
    """Only verified remote postprocess duplicates; every original/local TDR stays."""
    record_path=STATE/'cleanup-outcomes'/(label+'.json')
    if record_path.exists():return read(record_path)
    opname=label+'-cleanup';opdir=RT/'transport-probe/operations'/opname
    inputs=RT/'transport-probe/inputs'/opname
    planner=module(HERE/'cleanup_plan.py','_serial_cleanup_plan')
    if not opdir.exists():
        require(not inputs.exists(),'Prepared cleanup needs original-state review; no automatic retry')
        output=STATE/'cleanup-dev'/label
        require(not output.exists(),'Prepared cleanup plan needs original-state review')
        plan=planner.prepare(label+'-fields',role['role_id'],output)
        inputs.mkdir(parents=True,exist_ok=False)
        (inputs/'plan.json').write_bytes((output/'plan.json').read_bytes())
        (inputs/'remote-cleanup.sh').write_bytes((output/'remote-cleanup.sh').read_bytes())
        script=cleanup_task(plan)
        (inputs/'task.sh').write_text(script,encoding='utf-8',newline='\n')
        verify_cleanup_inputs(planner,inputs,plan)
        # Hash verification scales with bytes; 3 min minimum, conservative 10 MiB/s plus allowance.
        timeout=math.ceil(max(180,plan['registered_duplicate_bytes']*8/(10*2**20)+120))
        call([V4/'transport-probe/operation.py',opname,inputs,'--timeout',str(timeout)],opname+'-run')
    operation=read(opdir/'operation.json')
    require(operation['state'] in ('COLLECTED_PENDING_AUDIT','FAILED_COLLECTED') and all(operation.get(k) is not None for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')),
            'Cleanup outcome unknown; reconcile original process before any further submission')
    require(operation['collection_exit_code']==0,'Cleanup collection incomplete')
    plan=read(inputs/'plan.json');details=opdir/'collected/cleanup-evidence'
    verify_cleanup_inputs(planner,inputs,plan)
    outcome=dict(schema='dram-see-v4-duplicate-cleanup-outcome-r1',passed=False,role_id=role['role_id'],
        operation_label=opname,plan_id=plan['plan_id'],created_utc=utc(),automatic_retry=False,
        original_and_local_tdr_retained=True,evidence=[a.reference(opdir/'operation.json'),a.reference(inputs/'plan.json')],errors=[])
    if all(operation.get(k)==0 for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')):
        require(sha(opdir/'results.tar')==operation['archive_sha256'],'Cleanup archive hash changed')
        require(operation['adapter_sha256']==sha(V4/'transport-probe/operation.py'),'Cleanup adapter changed')
        require(operation['wrapper_sha256']==sha(opdir/'run.sh')==sha(opdir/'collected/run.sh'),'Cleanup shared-lock wrapper changed')
        with planner.Archive(opdir/'results.tar') as archived:
            for name,digest in operation['input_sha256'].items():
                require(sha(inputs/name)==sha(opdir/'collected'/name)==archived.digest(name)==digest,'Cleanup invocation input differs')
            for name in ('actions.tsv','source-after.tsv','verified-before.tsv','disk-before.txt','disk-after.txt','exit-code.txt','status.txt','allowlist.tsv'):
                require(sha(details/name)==archived.digest('cleanup-evidence/'+name),'Cleanup collected output differs from archive')
        require((details/'exit-code.txt').read_text().strip()=='0','Cleanup script failed')
        with (details/'actions.tsv').open(encoding='utf-8') as f:actions=list(csv.DictReader(f,delimiter='\t'))
        with (details/'source-after.tsv').open(encoding='utf-8') as f:originals=list(csv.DictReader(f,delimiter='\t'))
        names={x['name']:x for x in plan['files']}
        require(len(actions)==2*len(names) and len(originals)==len(names),'Incomplete cleanup per-file evidence')
        require({x['name'] for x in actions}==set(names)=={x['name'] for x in originals},'Cleanup inventory differs')
        for name,row in names.items():
            rows=[v for v in actions if v['name']==name]
            require([v['removed'] for v in rows]==['0','1'] and all(v['sha256']==row['sha256']==v['source_sha256'] and int(v['bytes'])==row['bytes'] for v in rows),'Cleanup action mismatch')
        require(all(v['unchanged']=='1' and v['actual_sha256']==v['expected_sha256']==names[v['name']]['sha256'] for v in originals),'Original source TDR changed')
        outcome.update(passed=True,removed_duplicate_files=len(names),removed_duplicate_bytes=sum(v['bytes'] for v in names.values()))
    else:
        outcome['native_failure']=known_operation_failure(opdir)
        outcome['errors'].append('Known failed cleanup preserved; no automatic retry, next job still requires live space preflight')
    a.save_new(record_path,outcome)
    return outcome

def fine_cost(label, run):
    result_path=STATE/'cost-outcomes'/(label+'.json')
    if result_path.exists():return read(result_path)
    probe=module(HERE/'fine_cost_probe.py','_serial_fine_cost')
    opname=label+'-cost';opdir=RT/'transport-probe/operations'/opname;inputs=RT/'transport-probe/inputs'/opname
    if not opdir.exists():
        require(not inputs.exists(),'Prepared fine cost operation needs original-state review')
        # A reviewed recovery needs a fresh preflight; preserve any earlier check.
        resource_label=opname+'-resource-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ').lower()
        readiness=module(HERE/'resources.py','_fine_cost_resources').check('fine',resource_label)
        require(readiness['passed'],'Fine cost probe readiness failed')
        probe.prepare(run.name,opname)
        evidence=read(inputs/'source-evidence.json')
        # Five frames only; based on the prior successful native five-frame operation, then byte-scaled.
        prior_path=RT/'transport-probe/operations/r5-extractor-five-r1/operation.json';prior=read(prior_path)
        elapsed=(datetime.fromisoformat(prior['finished_utc'])-datetime.fromisoformat(prior['started_utc'])).total_seconds()
        prior_bytes=sum(p.stat().st_size for p in (prior_path.parent/'collected').glob('gfield_*_access_des.tdr'))
        require(prior_bytes>0,'Missing native five-frame cost basis')
        timeout=math.ceil(max(300,elapsed*sum(evidence['tdr_bytes'].values())/prior_bytes*4+120))
        a.save_new(STATE/'postprocess-budgets'/(opname+'.json'),dict(frames=5,prior_operation=rel(prior_path),
            prior_sha256=sha(prior_path),prior_elapsed_s=elapsed,ssh_timeout_s=timeout,collection_timeout_s=180,
            measurement_scope='load/inventory/release only; no full ROI measured speed'))
        call([V4/'transport-probe/operation.py',opname,inputs,'--timeout',str(timeout)],opname+'-run')
    op=read(opdir/'operation.json')
    require(op['state'] in ('COLLECTED_PENDING_AUDIT','FAILED_COLLECTED') and all(op.get(k) is not None for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')),'Fine cost probe original process outcome unknown')
    require(op['collection_exit_code']==0,'Fine cost probe collection incomplete')
    outcome=dict(schema='dram-see-v4-fine-cost-outcome-r1',passed=False,role_id='a0-b1-fine',
        label=label,created_utc=utc(),automatic_retry=False,operation_label=opname,evidence=[a.reference(opdir/'operation.json')],errors=[])
    if all(op[k]==0 for k in ('ssh_exit_code','remote_exit_code','collection_exit_code')):
        output=STATE/'cost-probes'/opname
        if not output.exists():probe.summarize(opdir,output)
        measured=read(output/'cost.json')
        require(measured['passed'] is True and measured['source_run_id']==run.name,'Fine cost receipt failed')
        outcome.update(passed=True,mesh_node_count=measured['mesh_node_count'],solver_wallclock_s=measured['solver_wallclock_s'])
        outcome['evidence'] += [a.reference(output/'cost.json',True),a.reference(output/'cost-probe-receipt.json',True)]
    else:
        outcome['native_failure']=known_operation_failure(opdir)
        outcome['errors'].append('Known native cost probe failure; retain evidence and pause dependent fine-cost release')
    a.save_new(result_path,outcome)
    return outcome

def process_finished(role, label):
    execution=read(R5/'launches'/label/'execution.json')
    a.validate_invocation(execution,role,label)
    require(execution['role_id']==role['role_id'],'Wrong existing role')
    require(execution['state']=='RUNNER_EXITED' and execution.get('runner_exit_code') is not None,'Invocation unresolved')
    if execution['runner_exit_code']!=0:
        known=module(HERE/'control.py','_serial_failed_invocation').known_solver_failure(execution)
        outcome=STATE/'outcomes'/(label+'.json')
        if not outcome.exists():a.save_new(outcome,dict(schema='dram-see-v4-completion-outcome-r1',passed=False,label=label,
            role_id=role['role_id'],errors=['Known runner failure; no automatic retry'],runner_exit_code=execution['runner_exit_code'],
            original_remote_failure=known,evidence=[a.reference(R5/'launches'/label/'execution.json')]))
        return False
    run=ROOT/'local_runtime/runs'/execution['run_id']
    field=postprocess(label,run) if role['case_id']!='A0' else None
    outcome=STATE/'outcomes'/(label+'.json')
    if outcome.exists():result=read(outcome)
    else:
        update('SCIENTIFIC_AUDIT',active_stage=role['role_id'],active_job=execution['run_id'])
        result=a.accept(role['role_id'],label,field)
    if result['passed'] and role['case_id']!='A0':
        update('VERIFIED_DUPLICATE_CLEANUP',active_stage=role['role_id'],active_job=execution['run_id'])
        cleanup_duplicates(role,label)
    if result['passed'] and role['role_id']=='a0-b1-fine':
        update('FINE_A0_COST_PROBE',active_stage=role['role_id'],active_job=execution['run_id'])
        fine_cost(label,run)
    budget()
    return result['passed']

def run(adopt=None):
    check_release();controller=module(HERE/'control.py','_serial_control')
    campaign=read(HERE/'campaign.json');roles={r['role_id']:r for r in campaign['roles']}
    lockpath=STATE/'scheduler.lock';lock=lockpath.open('a+b')
    if lock.seek(0,2)==0:lock.write(b'0');lock.flush()
    lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    try:
        update('STARTED',active_job=None,active_child_pid=None,active_stage=None)
        if adopt:
            require(re.fullmatch(r'r5-[a-z0-9-]+',adopt),'Unsafe adoption label')
            path=R5/'launches'/adopt/'execution.json'
            while True:
                current=read(path)
                require(current['campaign_sha256']==sha(HERE/'campaign.json'),'Adopted campaign differs')
                require(current['role_id'] in roles, 'Adopted role is not registered')
                a.validate_invocation(current, roles[current['role_id']], adopt)
                if current['state'] not in ('PREPARING','RUNNING'):break
                require(pid_alive(current['launcher_pid']),'Original controller disappeared; reconcile original run, never resubmit')
                update('WAITING_ORIGINAL_INVOCATION',active_job=adopt,active_child_pid=current['launcher_pid'],active_stage='adopt')
                time.sleep(30)
            process_finished(roles[current['role_id']],adopt)
        for role in campaign['roles']:
            check_release()
            key=role['role_id'];gatefile=STATE/'gates'/(key+'.json')
            if gatefile.exists():
                controller.check_gate(key)
                if key=='a0-b1-fine':
                    previous=[read(p) for p in (R5/'launches').glob('*/execution.json') if read(p).get('run_id')==read(gatefile).get('run_id')]
                    require(len(previous)==1,'Fine A0 gate invocation not unique')
                    fine_cost(previous[0]['label'],ROOT/'local_runtime/runs'/previous[0]['run_id'])
                continue
            prior=[(p,read(p)) for p in (R5/'launches').glob('*/execution.json') if read(p).get('role_id')==key]
            if prior:
                # Existing calls are never submitted again. Known completed jobs can finish their single pending audit.
                for _,record in prior:process_finished(role,record['label'])
                continue
            missing=[dep for dep in role['requires'] if not (STATE/'gates'/(dep+'.json')).exists()]
            if missing:
                update('DEPENDENCY_PAUSED',active_stage=key,active_job=None,blocked_dependencies=missing);continue
            if role['variant']=='fine' and role['case_id']!='A0':
                cost_records=list((STATE/'cost-outcomes').glob('*.json'))
                verified=[]
                for path in cost_records:
                    cost=read(path)
                    if cost.get('passed') is True:
                        controller.check_evidence(cost['evidence']);verified.append(cost)
                if not verified:
                    update('DEPENDENCY_PAUSED',active_stage=key,active_job=None,blocked_dependencies=['fine-a0-cost-probe']);continue
            for dep in role['requires']:controller.check_gate(dep)
            project=ROOT/role['project'];builder=module(V4/'source-interface-r5/build_interface.py','_serial_builder')
            if not project.exists():builder.build(project,role['case_id'],role['stored_bit'],role['variant'])
            else:builder.check_project(project)
            label='r5-'+key+'-r1'
            update('DISPATCHING',active_stage=key,active_job=label,blocked_dependencies=[])
            code=call([V4/'stage2/source_control.py',project,label],label+'-invoke')
            require((R5/'launches'/label/'execution.json').exists(),'Preflight rejected before counting a solve; inspect stage logs')
            process_finished(role,label)
        remaining=[r['role_id'] for r in campaign['roles'] if not (STATE/'gates'/(r['role_id']+'.json')).exists()]
        update('ALL_PRIMARY_ROLES_PASSED' if not remaining else 'PRIMARY_PASS_COMPLETE_WITH_FAILURES_OR_DEPENDENCIES',
               active_job=None,active_child_pid=None,active_stage=None,remaining_roles=remaining)
        budget()
        return 0 if not remaining else 2
    except Exception as exc:
        update('REQUIRES_ROOT_REVIEW_NO_AUTOMATIC_RESUBMIT',error=repr(exc))
        raise
    finally:
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--adopt')
    args=parser.parse_args();raise SystemExit(run(args.adopt))
