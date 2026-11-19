"""Freeze campaign choices and historical protection before new solver work."""
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
V4=HERE.parent
RT=ROOT/'local_runtime/dram-see-v4'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,d):
    with p.open('x',encoding='utf-8') as f:json.dump(d,f,indent=2,ensure_ascii=False)

def main():
    sequence=[('A4',1,'main'),('A5',1,'main'),('A0',1,'fine'),('A6',1,'main'),('A7',1,'main'),
              ('A2',1,'main'),('A3',1,'main'),('A8S2',1,'main'),('A8S4',1,'main'),
              ('A0',0,'main'),('A1',0,'main'),('A4',0,'main'),('A0',1,'time'),('A1',1,'time'),
              ('A6',1,'time'),('A1',1,'fine'),('A5',1,'fine')]
    def key(case,bit=1,variant='main'):return f'{case.lower()}-b{bit}-{variant}'
    reuse='reuse-main-b1'
    dependencies={
      key('A4'):[reuse],key('A5'):[reuse,key('A4')],key('A0',1,'fine'):[reuse],
      key('A6'):[reuse,key('A4'),key('A5')],key('A7'):[reuse,key('A4'),key('A5')],
      key('A2'):[reuse],key('A3'):[reuse],key('A8S2'):[reuse,key('A4')],key('A8S4'):[reuse,key('A4')],
      key('A0',0):[],key('A1',0):[key('A0',0),reuse],key('A4',0):[key('A0',0),key('A1',0),key('A4')],
      key('A0',1,'time'):[reuse],key('A1',1,'time'):[reuse,key('A0',1,'time')],
      key('A6',1,'time'):[key('A6'),key('A0',1,'time'),key('A1',1,'time')],
      key('A1',1,'fine'):[reuse,key('A0',1,'fine')],key('A5',1,'fine'):[key('A5'),key('A0',1,'fine'),key('A1',1,'fine')]}
    roles=[]
    for i,(case,bit,variant) in enumerate(sequence,1):
        role=key(case,bit,variant)
        mode='equivalent' if case in ('A4','A7') else 'segment' if case.startswith('A8') else 'refinement' if case!='A0' and variant!='main' else None
        roles.append(dict(position=i,role_id=role,case_id=case,stored_bit=bit,variant=variant,
                          requires=dependencies[role],comparison_mode=mode,
                          project=f'local_runtime/dram-see-v4/source-interface-r5/inputs/v4-source-interface-r5-{role}'))
    history=sorted(RT.glob('source-interface-*/launches/*/execution.json'))
    assert len(history)==5 and len(roles)==17 and len({r['role_id'] for r in roles})==17
    for p in history:
        d=json.loads(p.read_text());assert d['state']=='RUNNER_EXITED' and d['runner_exit_code']==0 and d['runner_manifest_state']=='COLLECTED'
    immutable={}
    for p in V4.rglob('*'):
        if not p.is_file() or '__pycache__' in p.parts:continue
        rel=p.relative_to(V4)
        if rel.parts[0] in ('interface-completion-r1','source-interface-r5','source-field-audit-r2'):continue
        if rel.as_posix()=='stage2/source_control.py':continue
        immutable[p.relative_to(ROOT).as_posix()]=sha(p)
    prior=json.loads((V4/'stage2/protected-before.json').read_text())
    for r in prior['anchors']+prior['old_probe_files']:
        p=ROOT/r['path'];assert sha(p)==r['sha256'];immutable[r['path']]=r['sha256']
    snap=HERE/'revisions/pre-completion-controller';snap.mkdir(parents=True,exist_ok=False)
    for n in ('source_control.py','test_source_control.py'):(snap/n).write_bytes((V4/'stage2'/n).read_bytes())
    write(HERE/'protected-before.json',dict(created_utc=datetime.now(timezone.utc).isoformat(),immutable_files=immutable,
        mutable_controller=dict(path='experiments/dram-see-v4/stage2/source_control.py',before_sha256=sha(V4/'stage2/source_control.py'),snapshot='revisions/pre-completion-controller/source_control.py')))
    write(HERE/'campaign.json',dict(schema='dram-see-v4-interface-completion-campaign-r1',
        authority='User approved complete 2D plan, 17 primary plus 4 corrective attempts, cross-day serial execution and verified successful duplicate TDR cleanup.',
        historical_attempts_at_freeze=5,maximum_global_attempts=26,maximum_new_attempts=21,primary_roles=17,reserve_attempts=4,
        local_reserve_GiB=80,remote_minimum_free_after_peak_GiB=8,roles=roles,
        historical_records=[dict(path=p.relative_to(ROOT).as_posix(),sha256=sha(p)) for p in history],
        profiles=dict(main=dict(mesh_scale=.5,pulse_max_step_s=5e-13),time=dict(mesh_scale=.5,pulse_max_step_s=2.5e-13),fine=dict(mesh_scale=.25,pulse_max_step_s=5e-13)),
        default_resource_forecast=dict(main_raw_GiB=.65,time_raw_GiB=1.3,fine_raw_GiB=2.6,
             remote_peak_multiplier=3,local_peak_multiplier=4,basis='Conservative initial forecasts; measured same-profile archives may increase these estimates, never silently decrease before finer-grid probe.'),
        old_heartbeat='paused',solver_threads=1,scheduler='root',automatic_retry=False))
    write(HERE/'coordination.json',dict(schema='dram-see-v4-interface-completion-state-r1',state='IMPLEMENTING',
        updated_utc=datetime.now(timezone.utc).isoformat(),active_job=None,completed_roles=[],pending_roles=[r['role_id'] for r in roles],
        historical_attempts=5,new_attempts=0,reserve_used=0,gate_directory='local_runtime/dram-see-v4/interface-completion-r1/gates'))
    (RT/'interface-completion-r1/gates').mkdir(parents=True,exist_ok=False)
    print(json.dumps(dict(protected_files=len(immutable),primary_roles=len(roles),historical_attempts=len(history))))

if __name__=='__main__':main()
