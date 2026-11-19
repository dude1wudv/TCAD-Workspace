"""Integrate frozen r4 mesh inputs, real curves, native fields and matched controls."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[3]
V4=ROOT/'experiments/dram-see-v4'
OUT=ROOT/'local_runtime/dram-see-v4/source-interface-r4'

def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),m.__dict__);return m

b=module(V4/'source-interface-r4/build_interface.py','_mesh_builder')
r3=module(V4/'source-interface-r3/audit_interface.py','_mesh_frozen_r3')
r2=r3.r2;old=r3.old;o=r3.o
require,Checks,Archive=old.require,old.Checks,old.Archive
C=b.contract();T=C['audit_tolerances'];CONVERSION=r3.CONVERSION

def new_report():
    return dict(schema='dram-see-v4-r4-mesh-diagnostic',passed=False,status='FAILED_OR_INCOMPLETE',checks={},errors=[],
        audit_tolerances=T,audit_code_sha256=old.sha_file(Path(__file__)),
        contract_sha256=old.sha_file(b.CONTRACT),scientific_calibration_passed=False,numerical_convergence_validated=False,
        limits=['Only the two originally planned A0/A1 bit1 mesh diagnostics.',
                'Prior r2/r3 spatial failures are retained; this does not establish a new main mesh or release other roles.',
                'No 3D device response, upset label, probability or training claim.'])

def contract_check(archive,project,out):
    proof=b.check_project(project)
    p=old.json_load(archive.read('parameters.json'));spec=old.json_load(archive.read('source-spec.json'))
    case=p['case_id'];b.check_role(case,p['stored_bit'],p['variant'])
    require(p['schema']=='dram-see-v4-source-interface-r4','Wrong source revision')
    require(archive.read('source-contract.json')==b.CONTRACT.read_bytes(),'Frozen r4 contract differs')
    require(p['source_code_sha256']==b.code_hashes(),'Frozen builder dependencies differ')
    require(archive.read('device.cmd').decode()==b.render_deck(case),'Exact observer/device deck differs')
    require(b.encoded(spec)==b.encoded(b.source_spec(case)),'Physical source differs')
    require(p['source_spec_sha256']==archive.digest('source-spec.json'),'Source digest differs')
    require(p['source_contract_sha256']==archive.digest('source-contract.json'),'Contract digest differs')
    require(p['geometry_sha256']==archive.digest('geometry.scm'),'Geometry digest differs')
    require(p['matching_contract_sha256']==b.sha(b.encoded(p['matching_contract'])),'Matching contract digest differs')
    require(all(p[k]==v for k,v in p['matching_contract'].items()),'Conflicting physical parameters')
    expected=b.r3.offline_proof(spec);expected['schema']='dram-see-v4-source-interface-r4-offline'
    require(b.encoded(old.json_load(archive.read('offline-source-check.json')))==b.encoded(expected),'Offline source ledger differs')
    require(p['source_count']==len(spec['tracks']) and p['source_charge_fC']==spec['source_total_fC'],'Source count/charge differs')
    frames={name:archive.members[name].size for name in archive.members if re.fullmatch(r'gstep_[0-9]+_access_des\.tdr',name)}
    require(bool(frames),'No accepted-step field files saved')
    out.update(case_id=case,stored_bit=1,variant='mesh',parameters=p,input_check=proof,
               dynamic_tdr_count=len(frames),dynamic_tdr_bytes=sum(frames.values()),
               dynamic_frame_completeness='Native field audit required for A1; filenames alone are insufficient')
    return p,spec

def source_curve(curves,p,spec,out):
    rows=curves['device'];key='IntegrSemiconductor HeavyIonGeneration'
    out['injection_output_cadence']=r2.cadence(curves,p)
    present=[k for k in rows[0] if k.endswith('HeavyIonGeneration')]
    if p['case_id']=='A0':
        require(spec['tracks']==[] and spec['source_total_fC']==0,'A0 is not structurally source-free')
        require(all(row[k]==0 for row in rows for k in present),'A0 observed generation or centroid is nonzero')
        out['radiation']=dict(source_free=True,generated_fC=0. if key in rows[0] else None,
            evidence='observed_all_native_generation_fields_zero' if key in rows[0] else 'source_free_deck_only_no_numeric_zero_claim')
        return True
    require(key in rows[0],'Missing legacy native total')
    require(all(row[key]>=0 for row in rows),'Negative native source')
    target=spec['source_total_fC'];q=o.rectangular(rows,key)*CONVERSION
    proof=b.r3.offline_proof(spec)
    expected=[r3.average_profile(spec,proof,'Total',a['time'],z['time'])[0] for a,z in zip(rows,rows[1:])]
    peak=max(expected);error=max(abs(r[key]*CONVERSION-v) for r,v in zip(rows[1:],expected))/peak
    mass=o.rectangular(rows,key);tc=o.rectangular(rows,key,True)/mass if mass>0 else None
    out['radiation']=dict(source_free=False,legacy_generated_fC=q,target_fC=target,legacy_waveform_relative_error=error,
        time_centroid_s=tc,charge_integral='Native accepted BE intervals, rectangular',
        old_trapezoid_fC=old.integral(rows,'time',key)*CONVERSION,windowed_CurrentPlot_used_for_acceptance=False)
    require(abs(q-target)<=T['source_relative']*target,'Native total exceeds5%')
    require(error<=T['generation_waveform_relative'],'Native temporal waveform exceeds5%')
    require(tc is not None and abs(tc-spec['tracks'][0]['time_s'])<=T['time_centroid_abs_s'],'Native time centroid exceeds0.5ps')
    return True

def field_binding(path,out):
    path=Path(path).resolve();f=old.json_load(path.read_bytes())
    out['native_field_audit']=dict(path=str(path),sha256=old.sha_file(path),report=f)
    require(f['schema']=='source-field-audit-r1' and f['mode']=='full','Only a full-frame native field audit can satisfy this gate')
    require(f['passed'] is True and f['field_measurements_passed'] is True,'Native full-field gates failed or incomplete')
    require(f['run_id']==out['run_id'] and f['archive_sha256']==out['archive_sha256'] and f['manifest_sha256']==out['manifest_sha256'],'Native fields bound to another run/archive')
    require(f['audit_tolerances']==T,'Native field gates differ')
    require(f['audit_sha256']==old.sha_file(V4/'source-field-audit-r1/audit_fields.py'),'Native field auditor changed')
    require(f['field_contract_sha256']==old.sha_file(V4/'source-field-audit-r1/field_contract.json'),'Native field contract changed')
    return True

def load(run,project,field_audit=None):
    run=Path(run).resolve();out=new_report();bundle={'summary':out};checks=Checks(out)
    manifest=checks.call('manifest_and_inputs',lambda:old._manifest(run,out))
    if manifest is None:return bundle
    def inspect():
        with Archive(run/'results.tar') as archive:
            checks.call('original_serial_execution',lambda:old._provenance(archive,manifest,run,project,out))
            data=checks.call('frozen_r4_inputs',lambda:contract_check(archive,project,out))
            curves=checks.call('full_finite_raw_curves',lambda:old._curves(archive,out))
            if curves is not None:bundle['curves']=curves
            if data is not None:
                p,spec=data;bundle.update(parameters=p,source=spec)
                if curves is not None:
                    checks.call('native_total_and_timing',lambda:source_curve(curves,p,spec,out))
                    checks.call('voltage_current_conservation',lambda:old._response(p,curves,out))
                if p['case_id']=='A1':
                    checks.call('native_all_frame_source',lambda:field_binding(field_audit,out) if field_audit else require(False,'Full native field audit required'))
        require(old.sha_file(run/'manifest.json')==out['manifest_sha256'] and old.sha_file(run/'results.tar')==out['archive_sha256'],'Evidence changed during audit')
        return True
    checks.call('archive_stability',inspect)
    needed=7 if out.get('case_id')=='A0' else 8
    out['passed']=not out['errors'] and len(out['checks'])==needed
    if out['passed']:out['status']='R4_A0_MATCHED_CONTROL_READY' if out['case_id']=='A0' else 'R4_A1_SOURCE_READY_CONTROL_COMPARISON_REQUIRED'
    return bundle

def write(output,bundle):
    dest=Path(output).resolve();require(dest.is_relative_to(OUT) and dest!=OUT,'r4 audit output only')
    dest.mkdir(parents=True,exist_ok=False)
    (dest/'audit.json').write_text(json.dumps(bundle['summary'],indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    for name,rows in bundle.get('curves',{}).items():
        with (dest/(name+'.csv')).open('x',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--project',required=True,type=Path)
    p.add_argument('--field-audit',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    result=load(a.run,a.project,a.field_audit);write(a.output,result)
    print(json.dumps({'passed':result['summary']['passed'],'status':result['summary']['status'],'errors':result['summary']['errors']},ensure_ascii=False))
    raise SystemExit(0 if result['summary']['passed'] else 1)
