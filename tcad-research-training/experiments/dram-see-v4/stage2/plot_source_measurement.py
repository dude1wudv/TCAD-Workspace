"""Plot observed r3 CurrentPlot data; never substitutes an analytic source."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

def load(p):
    with p.open(encoding='utf-8',newline='') as f:
        rows=list(csv.DictReader(f))
    return {k:np.array([float(row[k]) for row in rows]) for k in rows[0]}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audit_dir',type=Path);parser.add_argument('control_dir',type=Path);parser.add_argument('output',type=Path)
    a=parser.parse_args();audit=json.loads((a.audit_dir/'audit.json').read_text(encoding='utf-8'))
    d=load(a.audit_dir/'device.csv');c=load(a.audit_dir/'circuit.csv');base=load(a.control_dir/'circuit.csv')
    fig,axes=plt.subplots(1,3,figsize=(15,4.2),layout='constrained')
    mapping=audit['raw_generation_fields'];conv=1.602176634e-16
    for name,label,color,style in [('legacy','Legacy total','#4477aa','-'),('plain','Generic without window','#66ccee','--'),
                                  ('two_dimensional','2-coordinate window','#cc6677',':'),('Total','3-coordinate window','#228833','-.')]:
        key=mapping['rois'][name] if name=='Total' else mapping[name]
        axes[0].plot((d['time']-1e-9)*1e12,d[key]*conv*1e-12,label=label,color=color,ls=style,lw=1.8)
    axes[0].set(xlim=(-12,12),xlabel='Time from source center (ps)',ylabel='Observed generation (fC/ps)')
    axes[0].legend(fontsize=8);axes[0].set_title('A1: measurement paths')
    q=audit['radiation']['roi_fraction_checks'];names=[n for n in q if n!='Total']
    pos=np.arange(len(names));expected=[q[n]['expected'] for n in names]
    observed=[np.nan if q[n]['observed'] is None else q[n]['observed'] for n in names]
    axes[1].bar(pos-.18,expected,.36,label='Declared spatial oracle',color='#bbbbbb')
    axes[1].bar(pos+.18,observed,.36,label='Observed 3-coordinate',color='#228833')
    if all(np.isnan(x) for x in observed):
        axes[1].text(.98,.97,'Window signal: 0\nFractions: undefined',transform=axes[1].transAxes,
                     ha='right',va='top',fontsize=9,color='#aa3377',bbox=dict(facecolor='white',edgecolor='#aa3377',alpha=.9))
    axes[1].set_xticks(pos,names,rotation=65,ha='right');axes[1].set(ylabel='Fraction of total generated charge',ylim=(0,1.05))
    axes[1].set_title('Spatial fractions (gate: absolute 0.05)');axes[1].legend(fontsize=8,loc='center right',bbox_to_anchor=(1,.65))
    time=c['time']
    for key,label,color in [('v(sn)','Storage node','#4477aa'),('v(bl)','Bit line','#cc6677')]:
        delta=(c[key]-np.interp(time,base['time'],base[key]))*1000
        axes[2].plot(time*1e9,delta,label=label,color=color)
    axes[2].set(xlabel='Time (ns)',ylabel='Change from matched A0 (mV)')
    axes[2].set_title('Continuous response; no upset labels');axes[2].legend(fontsize=8)
    for ax in axes:ax.grid(alpha=.2)
    status='PASS' if audit['passed'] else 'FAIL / INCOMPLETE'
    fig.suptitle('DRAM SEE v4 | r3 A1 bit1 base | '+status,fontsize=13)
    a.output.mkdir(parents=True,exist_ok=False);fig.savefig(a.output/'source-measurement.png',dpi=180);plt.close(fig)
    dependencies=[a.audit_dir/'audit.json',a.audit_dir/'device.csv',a.audit_dir/'circuit.csv',a.control_dir/'circuit.csv',Path(__file__)]
    evidence={'measured_data_only':True,'classification_generated':False,'input_sha256':
              {str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies}}
    (a.output/'plot-provenance.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    print(str((a.output/'source-measurement.png').resolve()))

if __name__=='__main__':main()
