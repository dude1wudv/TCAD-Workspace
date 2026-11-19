"""Re-audit original operations, without any new source/seed or solver call."""
from transport_material_r2 import *
def audit(label):
    record=c.RT/'transport/runs'/label/'record.json'
    dest=c.RT/'transport/audits-r3'/label
    if (dest/'audit.json').exists():
        result=c.read(dest/'audit.json')
        c.require(result['record_sha256']==c.sha(record) and result['audit_code_sha256']==c.sha(c.HERE/'transport_audit_r3.py'),'Audit binding changed')
        return result
    auditor=c.module(c.HERE/'transport_audit_r3.py','_nc_transport_audit')
    fun=auditor.audit_init if request(label)['mode']=='init' else auditor.audit_events
    result=fun(record.parent)
    prior=c.RT/'transport/audits'/label/'audit.json'
    result['prior_material_r2_audit']=dict(reference=c.ref(prior),passed=c.read(prior)['passed']) if prior.exists() else None
    result['recovery_scope']='New full audit of original bytes; no replay or alteration of the prior decision.'
    auditor._write(dest,result)
    return result


def choose(stage):
    """Selection only after all requests in a stage passed; no response ranking."""
    rows=[r for r in contract()['requests'] if r['closure_stage']==stage]
    reports=[]
    for r in rows:
        a=audit(r['label']);c.require(a['passed'] is True,'Incomplete/failed stage')
        reports.append((r,a))
    for r,a in reports:
        if r['arm']!='H' or r['mode']=='init':continue
        candidates=sorted(a['mechanism_summary']['qualifying_witnesses'],key=lambda w:(w['event_id'],w['parent_track_id'],w['parent_step_id']))
        if not candidates:continue
        run=c.RT/'transport/runs'/r['label']
        eligible={}
        with (run/'steps.csv').open(newline='',encoding='utf-8') as stream:
            for step in csv.DictReader(stream):
                event=int(step['event_id']);track=int(step['track_id'])
                if step['pre_material']!='G4_Si' or float(step['ionizing_MeV'])<=0:continue
                t0=float(step['pre_t_ns']);t1=float(step['post_t_ns'])
                # Original deposit time (not a shifted Gaussian tail) must intersect Geant 0..3 ns.
                if t0<3.0 and t1>=0.0 or t0==t1==3.0:
                    for n,w in enumerate(candidates):
                        if event==w['event_id'] and track in w['descendant_track_ids']:
                            fraction=1.0 if t1==t0 else max(0.0,min(t1,3.0)-max(t0,0.0))/(t1-t0)
                            amount=float(step['ionizing_MeV'])*fraction
                            entry=eligible.setdefault(n,{'energy':0.0,'steps':[]})
                            entry['energy']+=amount
                            if amount>0:entry['steps'].append([event,track,int(step['step_id'])])
        for n,w in enumerate(candidates):
            if eligible.get(n,{}).get('energy',0)>0:
                return dict(schema='nuclear-closure-selected-event-r1',transport_revision='audit-r3',selected_utc=c.utc(),stage=stage,
                    record=c.ref(run/'record.json'),audit=c.ref(c.RT/'transport/audits-r3'/r['label']/'audit.json'),
                    event_id=w['event_id'],request=r,
                    witness={**w,'window_descendant_si_ionizing_MeV':eligible[n]['energy'],'window_descendant_step_ids':eligible[n]['steps']},
                    selection_rule=c.contract()['transport']['selection'])
    return None


def check_release():
    path=c.HERE/'release-audit-r3.json'
    release=c.read(path)
    c.require(release['execution_enabled'] is True and release['contract_sha256']==c.sha(c.HERE/'contract.json'),'Audit r3 not released')
    for item in release['files']:c.check_ref(item)
    return c.ref(path)
