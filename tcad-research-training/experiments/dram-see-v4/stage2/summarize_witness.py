"""Summarize the entire frozen campaign and plot its preregistered first witness."""
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

ROOT=Path(__file__).resolve().parents[3]
V4=ROOT/'experiments/dram-see-v4'
RT=ROOT/'local_runtime/dram-see-v4/transport-probe'
HERE=V4/'mechanism-witness'
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(p):
    with p.open(encoding='utf-8',newline='') as f: return list(csv.DictReader(f))
def save(p,data):
    with p.open('x',encoding='utf-8',newline='\n') as f: json.dump(data,f,indent=2,ensure_ascii=False);f.write('\n')
def audit_for(run):
    matches=[]
    for p in (RT/'audits').glob(run.name+'*/audit.json'):
        a=read(p)
        if a.get('passed') and a.get('record_sha256')==sha(run/'record.json'):
            matches.append((a.get('audit_code_sha256')==sha(HERE/'audit_witness.py'),p,a))
    if not matches: raise ValueError('No passed audit for '+run.name)
    matches.sort(key=lambda item:(item[0],item[1].name))
    return matches[-1][1:]
def main():
    contract=read(HERE/'witness-contract.json')
    table=[];selected=None;species=Counter();terminations=Counter();ancestry=Counter();total=0;links=0
    all_events=[]
    for req in contract['requests']:
        run=RT/'runs'/req['label']; rec=read(run/'record.json')
        if rec['request']!=req: raise ValueError('Frozen request differs')
        ap,a=audit_for(run)
        event_rows=rows(run/'events.csv'); track_rows=rows(run/'tracks.csv')
        total+=len(event_rows)
        mechanism=a['mechanism_summary'];links+=mechanism['stable_birth_links']
        species.update(t['particle'] for t in track_rows)
        terminations.update(mechanism['termination_reason_counts']);ancestry.update(mechanism['ancestry_classification_counts'])
        qualifying=mechanism['qualifying_witnesses']
        if selected is None and req['arm']=='H' and qualifying:
            selected={'run_id':run.name,'request':req,**qualifying[0],'audit_path':ap.relative_to(ROOT).as_posix(),'audit_sha256':sha(ap)}
        table.append(dict(label=req['label'],arm=req['arm'],seed=req['seed'],stage=req['stage'],events=len(event_rows),
            tracks=len(track_rows),steps=sum(int(e['step_count']) for e in event_rows),birth_links=mechanism['stable_birth_links'],
            proton_inelastic_witness_events=sorted({e['event_id'] for e in qualifying}),
            nuclear_interaction_witnesses=len(qualifying),audit_path=ap.relative_to(ROOT).as_posix(),audit_sha256=sha(ap),
            receipt_sha256=sha(run/'record.json'),mechanism=mechanism))
        for e in event_rows: all_events.append({'run_id':run.name,'arm':req['arm'],'seed':req['seed'],**e})
    if total!=212: raise ValueError('Incomplete fixed campaign')
    out=HERE/'results/campaign-r1';out.mkdir(exist_ok=False)
    summary=dict(schema='dram-see-v4-nuclear-witness-summary-r1',contract_sha256=sha(HERE/'witness-contract.json'),
        total_primary_events=total,run_table=table,track_species=dict(species),stable_birth_links=links,
        termination_reason_counts=dict(terminations),ancestry_classification_counts=dict(ancestry),
        witness_found=selected is not None,selected_witness=selected,
        all_fixed_events_retained=True,for_probability=False,for_DRAM_training=False,tcad_coupling_demonstrated=False,
        limits=['10mm Si diagnostic with coarse cuts/steps; not a DRAM model',
                'Energy accounting checks recorded components, not a closed rest-mass/Q-value balance',
                'Birth energy distribution is this fixed diagnostic sample, not a fluence-normalized spectrum'])
    save(out/'summary.json',summary)
    with (out/'all-events.csv').open('x',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(all_events[0]));w.writeheader();w.writerows(all_events)
    if selected:
        run=RT/'runs'/selected['run_id'];eid=selected['event_id']
        tracks=[t for t in rows(run/'tracks.csv') if int(t['event_id'])==eid]
        steps=[s for s in rows(run/'steps.csv') if int(s['event_id'])==eid]
        births=[b for b in rows(run/'birth-links.csv') if int(b['event_id'])==eid]
        for name,data in [('selected-tracks.csv',tracks),('selected-birth-links.csv',births),('selected-steps.csv',steps)]:
            with (out/name).open('x',encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
        plot_case(out,selected,tracks,steps)
        modpath=V4/'source-ledger/build_manifest.py'
        spec=importlib.util.spec_from_file_location('native_ledger',modpath);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        manifest=mod.build(run,eid,ROOT/'local_runtime/dram-see-v4/source-ledger'/(run.name+f'-e{eid}-r2'))
        save(out/'source-ledger-summary.json',{'run_id':run.name,'event_id':eid,'totals':manifest['totals'],'tcad_ready':False})
    print(json.dumps({'primaries':total,'tracks':sum(species.values()),'birth_links':links,'witness':selected,'path':str(out)}))

def plot_case(out,selected,tracks,steps):
    title=f"{selected['run_id']} / event {selected['event_id']}"
    byid={int(t['track_id']):t for t in tracks}
    parent={int(t['track_id']):int(t['parent_id']) for t in tracks}
    def depth(t): return 0 if parent[t]==0 else 1+depth(parent[t])
    levels=defaultdict(list)
    for t in byid: levels[depth(t)].append(t)
    pos={t:(d,(i+1)/(len(ts)+1)) for d,ts in levels.items() for i,t in enumerate(sorted(ts))}
    fig,ax=plt.subplots(figsize=(max(10,len(levels)*2.8),max(7,min(20,max(map(len,levels.values()))*.30))))
    nuclear=set(selected['descendant_track_ids'])
    for t,p in parent.items():
        if p:
            ax.annotate('',xy=pos[t],xytext=pos[p],arrowprops={'arrowstyle':'->','lw':.6,'alpha':.5,'color':'#ca5b35' if t in nuclear else '#87969d'})
    for t,(x,y) in pos.items():
        label=f"{t}: {byid[t]['particle']}\n{float(byid[t]['birth_ke_MeV']):.3g} MeV"
        ax.text(x,y,label,fontsize=6.5,ha='center',va='center',bbox={'boxstyle':'round,pad=.25','fc':'#fff0e5' if t in nuclear else '#eef4f6','ec':'#bd6a4c' if t in nuclear else '#8ba1ac','lw':.6})
    ax.set_xlim(-.5,max(levels)+.5);ax.set_ylim(0,1);ax.axis('off')
    ax.set_title(title+f" / primary track {selected['parent_track_id']}, step {selected['parent_step_id']}"+'\nExact birth links; highlighted protonInelastic descendants',fontsize=11)
    fig.tight_layout();fig.savefig(out/'selected-ancestry.png',dpi=180);plt.close(fig)
    fig=plt.figure(figsize=(13,5.5));ax=fig.add_subplot(121,projection='3d');hist=fig.add_subplot(122)
    palette={'proton':'#cc5544','e-':'#477ca8','neutron':'#3b9368','gamma':'#bb9742',
             'alpha':'#e28328','Li7':'#9258a6','O15':'#70412b'}
    seen=set()
    for s in steps:
        if s['pre_material']!='G4_Si': continue
        name=s['particle'];color=palette.get(name,'#9258a6')
        xyz=[[float(s[p+'_'+v+'_um'])/1000 for p in ('pre','post')] for v in 'xyz']
        ax.plot(*xyz,color=color,lw=.7,alpha=.8,label=name if name not in seen else None);seen.add(name)
    ax.set(xlabel='x [mm]',ylabel='y [mm]',zlabel='z [mm]',xlim=(-5,5),ylim=(-5,5),zlim=(-5,5),title='Native 10 mm Si domain (no DRAM rescaling)')
    ax.legend(fontsize=7,loc='upper left')
    secondaries=[t for t in tracks if int(t['parent_id'])>0]
    positive=[float(t['birth_ke_MeV']) for t in secondaries if float(t['birth_ke_MeV'])>0]
    if positive:
        lower=min(positive);upper=max(positive);bins=np.geomspace(lower*.9,upper*1.1,20)
        groups=defaultdict(list)
        for t in secondaries:
            e=float(t['birth_ke_MeV'])
            if e>0: groups[t['particle']].append(e)
        for kind,data in groups.items():hist.hist(data,bins=bins,histtype='step',lw=1.4,label=kind,color=palette.get(kind))
        hist.set_xscale('log');hist.legend(fontsize=7)
    hist.set(xlabel='Recorded secondary birth energy [MeV]',ylabel='Tracks / bin',title='Selected mechanism witness; no rate inference')
    hist.yaxis.set_major_locator(MaxNLocator(integer=True))
    fig.suptitle(title);fig.tight_layout();fig.savefig(out/'selected-tracks-and-birth-energies.png',dpi=180);plt.close(fig)

if __name__=='__main__':main()
