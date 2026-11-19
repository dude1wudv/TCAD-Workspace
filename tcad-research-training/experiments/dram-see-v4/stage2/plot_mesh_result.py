"""Scientific plots from native fields and paired response CSVs only."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

def rows(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def vals(data,key):return np.array([float(r[key]) if r[key] else np.nan for r in data])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('field-audit','source-audit','coarse-frames','comparison','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();f=json.loads(a.field_audit.read_text(encoding='utf-8'));c=json.loads(a.comparison.read_text(encoding='utf-8'))
    frame_path=a.field_audit.with_name('frames.csv');device_path=a.source_audit.with_name('device.csv')
    delta_path=a.comparison.with_name('control-relative-curves.csv')
    frame=rows(frame_path);coarse=rows(a.coarse_frames);device=rows(device_path);delta=rows(delta_path)
    if f['mode']!='full':raise ValueError('This figure requires the real full-frame audit')
    time=(vals(frame,'start_s')+vals(frame,'end_s'))*.5
    rate=vals(frame,'G_silicon_raw')*1.602176634e-28
    native={float(r['time']):float(r['IntegrSemiconductor HeavyIonGeneration'])*1.602176634e-28 for r in device}
    legacy=np.array([native[float(r['end_s'])] for r in frame])
    fig,ax=plt.subplots(2,2,figsize=(12,7),layout='constrained')
    ax[0,0].plot((time-1e-9)*1e12,rate,label='Native TDR fields',color='#228833',lw=2)
    ax[0,0].plot((time-1e-9)*1e12,legacy,label='Native unwindowed CurrentPlot',color='#4477aa',ls='--',lw=1.2)
    ax[0,0].set(xlim=(-10,10),xlabel='BE interval midpoint from source center (ps)',ylabel='Generation (fC/ps)',title='Refined mesh: observed source rates')
    ax[0,0].legend(fontsize=8)
    expected=float(coarse[0]['Center_expected_erf1']);tol=f['audit_tolerances']['roi_fraction_abs']
    ax[0,1].axhspan(expected-tol,expected+tol,color='#cccccc',alpha=.4,label='Declared target +/- 0.05')
    ax[0,1].axhline(expected,color='#777777',ls=':',lw=1)
    active=rate>=np.max(rate)*f['audit_tolerances']['active_generation_fraction']
    ax[0,1].plot((time[active]-1e-9)*1e12,vals(frame,'Center_fraction')[active],color='#228833',label='Refined mesh, active frames')
    ct=(vals(coarse,'start_s')+vals(coarse,'end_s'))*.5
    ax[0,1].scatter((ct-1e-9)*1e12,vals(coarse,'Center_fraction'),color='#cc6677',s=30,label='Original mesh, 5 snapshots')
    ax[0,1].set(xlim=(-7,16),ylim=(min(.76,float(np.nanmin(vals(frame,'Center_fraction')[active]))-.01),.91),
                xlabel='BE interval midpoint from source center (ps)',ylabel='Center-region fraction',title='Spatial diagnostic: measurements, no filled frames')
    ax[0,1].legend(fontsize=8,loc='upper right')
    for axis,key,title in [(ax[1,0],'v(sn)','Storage node'),(ax[1,1],'v(bl)','Bit line')]:
        t=vals(delta,'time_s')*1e9
        axis.plot(t,vals(delta,'coarse_delta_'+key+'_V')*1000,label='Original mesh - its A0',color='#cc6677')
        axis.plot(t,vals(delta,'fine_delta_'+key+'_V')*1000,label='Refined mesh - its A0',color='#228833',ls='--')
        axis.set(xlabel='Time (ns)',ylabel='Control-relative voltage (mV)',title=title+'; no upset classification')
        axis.legend(fontsize=8)
    for axis in ax.flat:axis.grid(alpha=.2)
    source='PASS' if f['field_measurements_passed'] else 'FAIL / INCOMPLETE'
    metrics='PASS' if c['numerical_comparison_passed'] else 'FAIL / INCOMPLETE'
    fig.suptitle('DRAM SEE v4 | A1 bit1 | Native field gates: '+source+' | Refinement metrics: '+metrics+'\nOriginal mesh spatial failure remains recorded',fontsize=11)
    a.output.mkdir(parents=True,exist_ok=False);fig.savefig(a.output/'mesh-diagnostic.png',dpi=180);plt.close(fig)
    inputs=[a.field_audit,a.source_audit,a.coarse_frames,a.comparison,frame_path,device_path,delta_path,Path(__file__)]
    (a.output/'plot-provenance.json').write_text(json.dumps(dict(measured_data_only=True,missing_frames_filled=False,
        input_sha256={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}),indent=2)+'\n',encoding='utf-8')
    print(str((a.output/'mesh-diagnostic.png').resolve()))

if __name__=='__main__':main()
