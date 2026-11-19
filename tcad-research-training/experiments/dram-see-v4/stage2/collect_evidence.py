"""Read-only evidence index. Never starts, resumes, or resubmits a job."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
RT=ROOT/'local_runtime/dram-see-v4'
HERE=Path(__file__).resolve().parent

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ref(p):return p.relative_to(ROOT).as_posix()
def dump(p,data):p.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')

def collect(output):
    output=Path(output).resolve()
    if not output.is_relative_to(HERE):raise ValueError('Output must remain in stage2')
    output.mkdir(parents=True,exist_ok=False)
    now=datetime.now(timezone.utc).isoformat()
    protected=read(HERE/'protected-before.json')
    checks=[]
    for old in protected['anchors']+protected['old_probe_files']:
        p=ROOT/old['path'];actual=sha(p) if p.is_file() else None
        checks.append(dict(**old,actual_sha256=actual,unchanged=actual==old['sha256']))
    dump(output/'protected-check.json',dict(checked_utc=now,passed=all(r['unchanged'] for r in checks),files=checks))
    audits=[]
    paths=list((RT/'transport-probe/audits').glob('witness-*/audit.json'))
    paths+=list(RT.glob('source-interface-*/audits/*/audit.json'))
    paths+=list(RT.glob('source-interface-*/comparisons/*/comparison.json'))
    paths+=list((RT/'source-field-audit-r1/audit-dev').glob('*/audit.json'))
    for p in sorted(paths):
        r=read(p)
        audits.append(dict(path=ref(p),sha256=sha(p),passed=r.get('passed'),schema=r.get('schema'),mode=r.get('mode'),
                          field_measurements_passed=r.get('field_measurements_passed'),status=r.get('status'),
                          run_id=r.get('run_id'),errors=r.get('errors',[]),
                          checks={k:v for k,v in r.get('checks',{}).items() if v.get('passed') is not True}))
    operations=[]
    for p in sorted((RT/'transport-probe/operations').glob('*/operation.json')):
        if not (p.parent.name.startswith('witness-') or '-tdr-diagnostic-' in p.parent.name):continue
        r=read(p)
        operations.append(dict(path=ref(p),sha256=sha(p),**{k:r.get(k) for k in
            ('label','state','ssh_exit_code','remote_exit_code','collection_exit_code','started_utc','finished_utc')}))
    sources=[]
    for p in sorted(RT.glob('source-interface-*/launches/*/execution.json')):
        r=read(p)
        sources.append(dict(path=ref(p),sha256=sha(p),**{k:r.get(k) for k in
            ('label','identity','state','run_id','runner_exit_code','ssh_exit_code','runner_manifest_state',
             'invocation_budget_position','started_utc','finished_utc','manifest_input_matches_project')}))
    failures=[dict(kind='audit',**r) for r in audits if r['passed'] is not True]
    failures+=[dict(kind='operation',**r) for r in operations
               if any(r[k]!=0 for k in ('ssh_exit_code','remote_exit_code','collection_exit_code'))]
    failures+=[dict(kind='source_invocation',**r) for r in sources
               if r['runner_exit_code']!=0 or r['runner_manifest_state']!='COLLECTED']
    for p in sorted((RT/'stage2-live').glob('*/record.json')):
        r=read(p)
        if r.get('ssh_exit_code')!=0:
            failures.append(dict(kind='read_only_progress_probe',path=ref(p),sha256=sha(p),record=r,
                                 note='Progress probe failure is not a solver failure; original job is reconciled read-only.'))
    ledgers=[dict(path=ref(p),sha256=sha(p)) for p in sorted((RT/'source-ledger').glob('*/source_manifest.json'))]
    dump(output/'all-audits.json',audits)
    dump(output/'failures.json',dict(scope='All retained audit and execution failures in this campaign; later corrections do not erase them.',records=failures))
    dump(output/'operations.json',operations)
    dump(output/'source-invocations.json',sources)
    dump(output/'source-ledgers.json',ledgers)
    active=[r for r in sources if r['state'] not in ('RUNNER_EXITED','LOCAL_INVOCATION_ERROR')]
    active+=[r for r in operations if r['state'] not in ('COLLECTED_PENDING_AUDIT','FAILED_COLLECTED')]
    result=dict(created_utc=now,tcad_invocations=len(sources),tcad_cap=19,tcad_remaining=max(0,19-len(sources)),
                protected_files=len(checks),protected_unchanged=all(r['unchanged'] for r in checks),
                audit_records=len(audits),failure_records=len(failures),native_3d_manifests=len(ledgers),
                locally_unresolved_operations=active,
                limitations=['This index does not replace raw run audits or a live remote process/lock check.',
                             'Scientific failure and successful collection are separate states.'])
    dump(output/'summary.json',result);print(json.dumps(result,ensure_ascii=False))
    return 0 if result['protected_unchanged'] and len(sources)<=19 and not active else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path)
    raise SystemExit(collect(p.parse_args().output))
