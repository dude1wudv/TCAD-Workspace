"""Audit r3 native measurements plus an independently audited frozen r2 A0."""
import argparse
import csv
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent


def module(path,name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),m.__dict__)
    return m


b=module(HERE/'build_interface.py','_r3_build')
o=module(HERE/'oracle.py','_r3_oracle')
r2=module(b.R2/'audit_interface.py','_r3_frozen_control_auditor')
old=r2.old
require,Checks,Archive=old.require,old.Checks,old.Archive
C=b.contract();T=C['audit_tolerances']
CONVERSION=C['device']['effective_thickness_um']*1e-12*C['conversion']['elementary_charge_C']*1e15


def initial_report():
    return {'schema':'dram-see-v4-source-interface-r3-audit','passed':False,'status':'FAILED_OR_INCOMPLETE',
            'checks':{},'errors':[],'audit_tolerances':T,'scientific_calibration_passed':False,
            'numerical_convergence_validated':False,'audit_code_sha256':old.sha_file(Path(__file__)),
            'oracle_sha256':old.sha_file(HERE/'oracle.py'),'source_contract_sha256':old.sha_file(b.CONTRACT),
            'limits':['A1 bit1 base artificial 2D measurement candidate only; no 3D event projection.',
                      'Global maximum19 attempts includes prior r2 attempts; this auditor has no runner.',
                      '3-coordinate windows are the predeclared acceptance path; legacy/generic/2D diagnostic paths cannot replace a failing ROI.',
                      'TDR postprocessing and native solver integrals are distinct; no interchangeability assumed.',
                      'No calibration, complete convergence, upset classification or training claim.']}


def check_contract(archive,out):
    p=old.json_load(archive.read('parameters.json'))
    require(p['schema']=='dram-see-v4-source-interface-r3' and [p['case_id'],p['stored_bit'],p['variant']]==['A1',1,'base'],'Not the approved r3 A1 candidate')
    require(archive.read('source-contract.json')==b.CONTRACT.read_bytes(),'Archived r3 contract differs')
    require(p['source_contract_sha256']==archive.digest('source-contract.json'),'Source contract digest differs')
    require(p['source_code_sha256']==b.code_hashes(),'Frozen r2/r3 code dependencies differ')
    spec=b.r2.validate_spec(old.json_load(archive.read('source-spec.json')))
    require(b.encoded(spec)==b.encoded(b.source_spec()),'Physical source specification changed')
    require(p['source_spec_sha256']==archive.digest('source-spec.json'),'Source identity hash differs')
    require(archive.read('device.cmd').decode()==b.render_deck(),'Full physical deck or measurement specification differs')
    require(archive.read('heavyion.par').decode()==b.r2.render_parameters(spec),'HeavyIon parameters changed')
    reference=old.json_load(archive.read('r2-reference-parameters.json'))
    require(reference['schema']=='dram-see-v4-source-interface-r2','Missing physical r2 reference')
    require(p['matching_contract_sha256']==reference['matching_contract_sha256']
            and b.encoded(p['matching_contract'])==b.encoded(reference['matching_contract']),'Physical matching contract changed')
    require(p['matching_contract_sha256']==b.sha(b.encoded(p['matching_contract'])),'Physical matching hash inconsistent')
    require(all(p[k]==v for k,v in p['matching_contract'].items()),'Physical parameters conflict')
    require(archive.read('r2-reference-device.cmd').decode()==b.r2.render_deck(spec,1,'base'),'Original r2 full device reference differs')
    require(p['geometry_sha256']==archive.digest('geometry.scm')==reference['geometry_sha256'],'Physical geometry changed')
    require(p['event_id']==spec['event_id'] and p['source_charge_fC']==1. and p['domain_charge_fC']==1.,'Event/charge identity differs')
    manifest=old.json_load(archive.read('input-manifest.json'))
    require(manifest['schema']=='dram-see-v4-source-interface-r3-inputs' and manifest['source_code_sha256']==b.code_hashes(),'Builder manifest differs')
    for name,digest in manifest['files_sha256'].items():require(archive.digest(name)==digest,'Builder file hash differs: '+name)
    prior=old.json_load(archive.read('r2-reference-input-manifest.json'))
    require(archive.digest('r2-reference-input-manifest.json')==p['r2_reference_manifest_sha256'],'Original r2 manifest digest differs')
    for name in ('geometry.scm','heavyion.par','source-spec.json'):
        require(archive.digest(name)==prior['files_sha256'][name],'Physical input differs from frozen r2 manifest: '+name)
    out.update(case_id='A1',stored_bit=1,variant='base',parameters=p,event_id=p['event_id'])
    out['tdr_artifacts']={name:archive.digest(name) for name in ['gfield_'+str(i)+'_access_des.tdr' for i in range(5)]}
    out['tdr_field_extraction_verified']=False
    return p,spec,b.offline_proof(spec)


def fields(names):
    def exact(key):
        require(names.count(key)==1,'Missing/ambiguous native dataset: '+key)
        return key
    mapped={'legacy':exact('IntegrSemiconductor HeavyIonGeneration'),
            'plain':exact('IntegrG_Plain HeavyIonGeneration'),'two_dimensional':exact('IntegrG_2DTotal HeavyIonGeneration'),
            'rois':{roi:exact('IntegrG_'+roi+' HeavyIonGeneration') for roi in C['rois_um']},
            'centroid':{axis:exact('IntegrG_Total '+axis.upper()+'_HeavyIonGeneration') for axis in ('x','y')},
            'area':{}}
    for roi in ['Plain','2DTotal']+list(C['rois_um']):
        candidates=[key for key in names if key in ('IntegrArea_'+roi+' LatticeTemperature','IntegrArea_'+roi+' Temperature')]
        require(len(candidates)==1,'Missing/ambiguous native temperature area dataset: '+roi)
        mapped['area'][roi]=candidates[0]
    return mapped


def average_profile(spec,proof,roi,start,end):
    sources={a['source_name']:a for a in spec['tracks']}
    total=x=y=0.
    for a in proof['rois'][roi]['tracks']:
        tr=sources[a['source_name']]
        rate=o.step_average(start,end,tr['time_s'],tr['s_hi_s'])
        total+=a['q_fC']*rate;x+=a['x_moment_fC_um']*rate;y+=a['y_moment_fC_um']*rate
    return total,(x/total if total else None),(y/total if total else None)


def check_source(curves,p,spec,proof,out):
    rows=curves['device'];mapping=fields(list(rows[0]));out['raw_generation_fields']=mapping
    out['injection_output_cadence']=r2.cadence(curves,p)
    failures=[]
    def gate(condition,message):
        if not condition:failures.append(message)
    scalar_keys=[mapping[k] for k in ('legacy','plain','two_dimensional')]+list(mapping['rois'].values())
    for key in scalar_keys:gate(all(row[key]>=0 for row in rows),'Negative observed generation: '+key)
    q={roi:o.rectangular(rows,key)*CONVERSION for roi,key in mapping['rois'].items()}
    target=proof['domain_charge_fC'];total=q['Total']
    out['radiation']={'declared_fC':spec['source_total_fC'],'target_domain_fC':target,'generated_fC':total,
                      'charge_integration':'sum G_i*dt_i on original accepted BE intervals',
                      'old_trapezoid_fC':old.integral(rows,'time',mapping['rois']['Total'])*CONVERSION,
                      'legacy_generated_fC':o.rectangular(rows,mapping['legacy'])*CONVERSION,
                      'legacy_old_trapezoid_fC':old.integral(rows,'time',mapping['legacy'])*CONVERSION,
                      'plain_generated_fC':o.rectangular(rows,mapping['plain'])*CONVERSION,
                      'two_dimensional_generated_fC':o.rectangular(rows,mapping['two_dimensional'])*CONVERSION,
                      'plain_and_2D_paths_diagnostic_only':True,'roi_charge_fC':q,
                      'roi_fraction_checks':{},'partition_checks':[],'time_checks':{},'waveform_checks':{}}
    rad=out['radiation']
    gate(abs(total-target)<=T['source_relative']*target,'3-coordinate native source charge exceeds frozen5% gate')
    gate(abs(rad['legacy_generated_fC']-target)<=T['source_relative']*target,'Legacy native total charge exceeds frozen5% gate')
    out['area_diagnostics']={}
    for roi,key in mapping['area'].items():
        values=[row[key]/p['temperature_K'] for row in rows]
        rect=C['device']['silicon_bounds_um'] if roi in ('Plain','2DTotal') else C['rois_um'][roi]
        wanted=(rect[2]-rect[0])*(rect[3]-rect[1])
        out['area_diagnostics'][roi]={'raw_dataset':key,'temperature_K':p['temperature_K'],'expected_area_um2':wanted,
                                     'observed_min_um2':min(values),'observed_max_um2':max(values),'diagnostic_only':True}
    for roi,key in mapping['rois'].items():
        wanted=proof['rois'][roi]['q_fC']/target;fraction=q[roi]/total if total>0 else None
        rad['roi_fraction_checks'][roi]={'expected':wanted,'observed':fraction,'abs_error':abs(fraction-wanted) if fraction is not None else None}
        gate(fraction is not None and abs(fraction-wanted)<=T['roi_fraction_abs'],'ROI fraction differs: '+roi)
        if wanted>=T['active_generation_fraction']:
            obs_mass=o.rectangular(rows,key)
            tc=o.rectangular(rows,key,True)/obs_mass if obs_mass>0 else None
            sources={a['source_name']:a for a in spec['tracks']}
            expected_tc=sum(a['q_fC']*sources[a['source_name']]['time_s'] for a in proof['rois'][roi]['tracks'])/proof['rois'][roi]['q_fC']
            rad['time_checks'][roi]={'observed_s':tc,'expected_s':expected_tc,'abs_error_s':abs(tc-expected_tc) if tc is not None else None}
            gate(tc is not None and abs(tc-expected_tc)<=T['time_centroid_abs_s'],'BE interval time centroid differs: '+roi)
    for role,key in [('legacy',mapping['legacy']),('Total',mapping['rois']['Total'])]:
        expected=[average_profile(spec,proof,'Total',a['time'],z['time'])[0] for a,z in zip(rows,rows[1:])]
        peak=max(expected);error=max(abs(row[key]*CONVERSION-e) for row,e in zip(rows[1:],expected))
        rad['waveform_checks'][role]={'expected_BE_average_peak_fC_s':peak,'max_error_fC_s':error,'relative_error':error/peak,
                                     'no_measured_value_replaced':True}
        gate(error<=T['generation_waveform_relative']*peak,'Native BE-average temporal waveform exceeds5%: '+role)
    total_key=mapping['rois']['Total'];peak=max(row[total_key] for row in rows)
    for part in C['partitions']:
        err=max(abs(sum(row[mapping['rois'][roi]] for roi in part)-row[total_key]) for row in rows)/peak if peak>0 else None
        qerr=abs(sum(q[roi] for roi in part)-total)/total if total>0 else None
        rad['partition_checks'].append({'rois':part,'curve_relative_error':err,'charge_relative_error':qerr})
        gate(err is not None and qerr is not None and max(err,qerr)<=T['partition_relative'],'Native ROI partition fails')
    errors={'x':0.,'y':0.};active=0
    for prev,row in zip(rows,rows[1:]):
        if peak<=0 or row[total_key]<peak*T['active_generation_fraction']:continue
        active+=1;rate,x,y=average_profile(spec,proof,'Total',prev['time'],row['time'])
        if rate<=0:
            failures.append('Observed active source outside expected BE interval');continue
        for axis,wanted in [('x',x),('y',y)]:errors[axis]=max(errors[axis],abs(row[mapping['centroid'][axis]]-wanted))
    out['spatial_centroid']={'active_samples':active,'max_abs_error_um':errors}
    gate(active>0 and max(errors.values())<=T['centroid_abs_um'],'Native spatial centroid exceeds0.01um')
    out['source_gate_failures']=failures
    require(not failures,'; '.join(failures))
    return True


def load_run(run_path,project_path=None):
    folder=Path(run_path).resolve();out=initial_report();out['run_path']=str(folder);checks=Checks(out);bundle={'summary':out}
    manifest=checks.call('manifest_and_inputs',lambda:old._manifest(folder,out))
    if manifest is None:return bundle
    def inspect():
        with Archive(folder/'results.tar') as archive:
            checks.call('execution_and_raw_archive',lambda:old._provenance(archive,manifest,folder,project_path,out))
            valid=checks.call('r3_observer_frozen_physics',lambda:check_contract(archive,out))
            curves=checks.call('full_finite_raw_curves',lambda:old._curves(archive,out))
            if curves is not None:bundle['curves']=curves
            if valid is not None:
                p,spec,proof=valid;bundle.update(parameters=p,source=spec,proof=proof)
                if curves is not None:
                    checks.call('native_spatial_temporal_source',lambda:check_source(curves,p,spec,proof,out))
                    checks.call('inherited_voltage_current_conservation',lambda:old._response(p,curves,out))
        require(old.sha_file(folder/'manifest.json')==out['manifest_sha256'],'Manifest changed while auditing')
        require(old.sha_file(folder/'results.tar')==out['archive_sha256'],'Archive changed while auditing')
        return True
    checks.call('archive_safety_and_stability',inspect)
    return bundle


def reuse_control(signal,control_run,out):
    control=r2.load_run(control_run)  # Executes only the frozen original read-only r2 audit.
    out['reused_r2_control_audit']=control['summary']
    require(control['summary']['passed'],'Original frozen r2 control audit failed')
    p=control['parameters'];s=signal['parameters']
    require(p['schema']=='dram-see-v4-source-interface-r2' and [p['case_id'],p['stored_bit'],p['variant']]==['A0',1,'base'],'Only a genuinely audited r2 A0 bit1 base may be reused')
    require(p['matching_contract_sha256']==s['matching_contract_sha256'] and b.encoded(p['matching_contract'])==b.encoded(s['matching_contract']),'Control physical matching hash/content differ')
    require(signal['summary']['mesh_sha256']==control['summary']['mesh_sha256'],'Actual signal/control mesh bytes differ')
    require(p['source_contract_sha256']==C['frozen_references']['r2_contract_sha256']
            and control['summary']['contract_sha256']==C['frozen_references']['r2_contract_sha256'],'Control retains its own frozen r2 source revision')
    rows,base=signal['curves']['circuit'],control['curves']['circuit']
    delta_sn=old.legacy.sample(rows,'v(sn)',2.8e-9)-old.legacy.sample(base,'v(sn)',2.8e-9)
    out['control_relative_observables']={'control_reused':True,'control_run_id':control['summary']['run_id'],
         'delta_SN_hold_V':delta_sn,'delta_BL_read_V':old.legacy.sample(rows,'v(bl)',4e-9)-old.legacy.sample(base,'v(bl)',4e-9),
         'C_times_delta_SN_fC':s['capacitance_F']*delta_sn*1e15,'charge_definition':'Algebraic C*dV only; no independent collected-charge claim'}
    return True


def audit(run_path,control_run,project_path=None,output=None):
    bundle=load_run(run_path,project_path);out=bundle['summary'];checks=Checks(out)
    if 'parameters' in bundle and 'curves' in bundle:
        checks.call('strict_original_r2_A0_reuse',lambda:reuse_control(bundle,control_run,out))
    out['passed']=not out['errors'] and len(out['checks'])==8
    if out['passed']:out['status']='R3_A1_NATIVE_MEASUREMENT_CHECKS_PASSED'
    if output is not None:
        dest=Path(output).resolve();require(dest.is_relative_to(b.OUTPUT_ROOT.resolve()) and dest!=b.OUTPUT_ROOT.resolve(),'r3 output scope only')
        dest.mkdir(parents=True,exist_ok=True)
        with (dest/'audit.json').open('x',encoding='utf-8') as f:f.write(json.dumps(out,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
        for label,rows in bundle.get('curves',{}).items():
            with (dest/(label+'.csv')).open('x',encoding='utf-8',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run_path',type=Path);p.add_argument('--control',type=Path,required=True)
    p.add_argument('--project',type=Path);p.add_argument('--output',type=Path);args=p.parse_args()
    result=audit(args.run_path,args.control,args.project,args.output);print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
