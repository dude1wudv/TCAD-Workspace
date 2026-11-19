"""Compare matched control-relative curves, retaining the failed coarse spatial gate."""
import argparse
import csv
import json
from pathlib import Path
import importlib.util

spec=importlib.util.spec_from_file_location('_mesh_integrator',Path(__file__).with_name('audit_mesh_diagnostic.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
old,r2,r3,require=m.old,m.r2,m.r3,m.require

def legacy_baseline(bundle):
    summary=bundle['summary']
    require([r['check'] for r in summary['errors']]==['native_spatial_temporal_source'],
            'Coarse baseline has additional or different failures; cannot use its independent legacy measurement')
    rad=summary['radiation'];target=bundle['source']['source_total_fC']
    require(abs(rad['legacy_generated_fC']-target)<=m.T['source_relative']*target,'Coarse native legacy total invalid')
    require(rad['waveform_checks']['legacy']['relative_error']<=m.T['generation_waveform_relative'],'Coarse native legacy time profile invalid')
    return True

def charge_comparison(fine,coarse):
    require(coarse>0,'Coarse source charge must be positive')
    return dict(fine_fC=fine,coarse_fC=coarse,relative_difference=abs(fine-coarse)/abs(coarse),
                limit=m.T['refinement_charge_relative'],denominator='coarse baseline, same as frozen r2 refinement rule',
                same_observable='Native unwindowed semiconductor total; accepted BE rectangular integral')

def compare(signal,control,coarse_signal,coarse_control,field_audit,signal_project,control_project,output):
    out=dict(schema='dram-see-v4-mesh-diagnostic-comparison',passed=False,numerical_comparison_passed=False,
             numerical_convergence_validated=False,main_grid_accepted=False,checks={},errors=[],
             prior_spatial_failures_promoted=False,audit_code_sha256=old.sha_file(Path(__file__)),
             integration_audit_sha256=old.sha_file(Path(__file__).with_name('audit_mesh_diagnostic.py')),
             scope='Original mesh refinement pair only; passing metrics cannot erase the coarse-grid spatial failure',audit_tolerances=m.T)
    checks=old.Checks(out)
    a=m.load(signal,signal_project,field_audit);ca=m.load(control,control_project)
    b=r3.load_run(coarse_signal);cb=r2.load_run(coarse_control)
    out['input_reports']={k:v['summary'] for k,v in [('fine_A1',a),('fine_A0',ca),('coarse_A1',b),('coarse_A0',cb)]}
    checks.call('fine_source_and_control_accepted',lambda:require(a['summary']['passed'] and ca['summary']['passed'],'Fine source/control gates not both passed'))
    checks.call('coarse_control_and_legacy_measurement',lambda:(require(cb['summary']['passed'],'Coarse control failed'),legacy_baseline(b)))
    def matching():
        r2.matched_control(a,ca);r2.matched_control(b,cb)
        require(m.b.encoded(a['source'])==m.b.encoded(b['source']),'Different physical source specification')
        x,y=a['parameters']['matching_contract'],b['parameters']['matching_contract']
        differences={k for k in set(x)|set(y) if x.get(k)!=y.get(k)}
        require(differences=={'geometry_sha256','mesh_scale','variant'},'Refinement changed additional circuit/device/time conditions')
        require([x['mesh_scale'],y['mesh_scale'],x['variant'],y['variant']]==[.5,1.,'mesh','base'],'Not the registered mesh refinement')
        require(a['summary']['mesh_sha256']!=b['summary']['mesh_sha256'],'Actual mesh did not change')
        return True
    matched=checks.call('physical_source_and_control_matching',matching)
    derived=[]
    if matched is not None:
        def metrics():
            qa=a['summary']['radiation']['legacy_generated_fC'];qb=b['summary']['radiation']['legacy_generated_fC']
            out['generated_charge_comparison']=charge_comparison(qa,qb)
            qerr=out['generated_charge_comparison']['relative_difference']
            v={key:r2.perturbation(a,ca,b,cb,key) for key in ('v(sn)','v(bl)')}
            out['control_relative_voltage']=v
            rows=[x['curves']['circuit'] for x in (a,ca,b,cb)]
            times=sorted({r['time'] for series in rows for r in series if r['time']>=.95e-9})
            arrays={key:[old._sample_series(row,key,times) for row in rows] for key in ('v(sn)','v(bl)')}
            for i,t in enumerate(times):
                row={'time_s':t}
                for key,values in arrays.items():
                    row['fine_delta_'+key+'_V']=values[0][i]-values[1][i]
                    row['coarse_delta_'+key+'_V']=values[2][i]-values[3][i]
                derived.append(row)
            out['numerical_comparison_passed']=qerr<=m.T['refinement_charge_relative'] and all(r['passed'] for r in v.values())
            require(out['numerical_comparison_passed'],'Registered charge or control-relative voltage refinement gate failed')
            return True
        checks.call('registered_refinement_metrics',metrics)
    out['passed']=not out['errors'] and len(out['checks'])==4
    out['status']='REFINEMENT_METRICS_PASSED_COARSE_SPATIAL_FAILURE_RETAINED' if out['passed'] else 'FAILED_OR_INCOMPLETE'
    dest=Path(output).resolve();require(dest.is_relative_to(m.OUT) and dest!=m.OUT,'r4 output directory required')
    dest.mkdir(parents=True,exist_ok=False)
    (dest/'comparison.json').write_text(json.dumps(out,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    if derived:
        with (dest/'control-relative-curves.csv').open('x',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(derived[0]));w.writeheader();w.writerows(derived)
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('signal','control','coarse-signal','coarse-control','field-audit','signal-project','control-project','output'):
        p.add_argument('--'+name,type=Path,required=True)
    result=compare(**{k.replace('-','_'):v for k,v in vars(p.parse_args()).items()})
    print(json.dumps({k:result.get(k) for k in ('passed','status','numerical_comparison_passed','errors')},ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 1)
