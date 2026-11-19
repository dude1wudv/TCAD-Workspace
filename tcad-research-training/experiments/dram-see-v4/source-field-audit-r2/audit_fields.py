"""Read-only native TDR field audit; never simulates or fills missing observations."""
import argparse
import csv
import io
import json
import math
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUTPUT=ROOT/'local_runtime/dram-see-v4/source-field-audit-r2/audit-dev'


def module(path,name):
    import importlib.util
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),m.__dict__)
    return m


old=module(ROOT/'experiments/dram-see-v4/source-probe/audit_probe.py','_sfa_readonly_archive')
r3=module(ROOT/'experiments/dram-see-v4/source-interface-r3/audit_interface.py','_sfa_frozen_reference')
require,Archive=old.require,old.Archive
C=old.json_load((HERE/'field_contract.json').read_bytes());T=C['audit_tolerances']
CONVERSION=C['device']['effective_thickness_um']*1e-12*C['conversion']['elementary_charge_C']*1e15
SCOPES=['SILICON_NO_WINDOW']+list(C['rois_um'])
ROLES=C['native_fields']
EXTRACTORS={'e7b05794444fa0a0406efced528360a75e04325441d994b098e836ffd6df386e':'extract_fields.tcl'}

LEGACY='IntegrSemiconductor HeavyIonGeneration'
NUMBER=r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?'
BE=re.compile(r'^Computing BE-step from ('+NUMBER+r') s to ('+NUMBER+r') s \(Stepsize: ('+NUMBER+r') s\)')
WRITING=re.compile(r"^\s*Writing plot '([^']+)' \(TDR format\) \.\.\. done\.")


def finite(text,label):
    v=float(text);require(math.isfinite(v),'Nonfinite '+label);return v


def printed_match(value,token):
    """Match only rounding precision actually present in a log numeric token."""
    mantissa,_,exponent=token.lower().partition('e')
    decimals=len(mantissa.partition('.')[2])
    half_unit=.500001*10**(int(exponent or '0')-decimals)
    return abs(value-float(token))<=half_unit


def index_frames(log,rows,files,full=False):
    require(len(files)==len(set(files)) and files,'Missing/duplicate frame list')
    intervals=[(i,a['time'],b['time']) for i,(a,b) in enumerate(zip(rows,rows[1:]),1)]
    require(all(b>a for _,a,b in intervals),'PLT accepted times are not strictly increasing')
    found={};step=None
    for lineno,line in enumerate(log.splitlines(),1):
        m=BE.match(line)
        if m:step={'tokens':m.groups(),'line':lineno,'success':False,'failed':False}
        if step is not None:
            if 'Error smaller than 1' in line or 'Rhs smaller than' in line:step['success']=True
            if any(v in line for v in ("Newton didn't converge",'time step rejected','Time step rejected')):step['failed']=True
        m=WRITING.match(line)
        if not m or m[1] not in files:continue
        name=m[1]
        require(name not in found,'TDR written more than once: '+name)
        require(step is not None and step['success'] and not step['failed'],'TDR lacks a successful BE step: '+name)
        start,end,delta=step['tokens']
        candidates=[(i,a,b) for i,a,b in intervals if printed_match(a,start) and printed_match(b,end) and printed_match(b-a,delta)]
        require(len(candidates)==1,'Log/precise PLT interval is missing or ambiguous: '+name)
        i,a,b=candidates[0]
        found[name]={'source_file':name,'accepted_index':i,'start_s':a,'end_s':b,'dt_s':b-a,
                     'BE_log_line':step['line'],'writing_log_line':lineno,'direct_TDR_timestamp_verified':False}
    require(set(found)==set(files),'Missing real TDR Writing record')
    indexes=[r['accepted_index'] for r in found.values()]
    require(len(indexes)==len(set(indexes)),'Two listed TDR frames refer to one accepted interval')
    ordered=sorted(found.values(),key=lambda x:x['accepted_index'])
    if full:
        lo,hi=C['window_s'];eps=T['final_time_abs_s']
        expected={i for i,a,b in intervals if a>=lo-eps and b<=hi+eps and b>lo+eps}
        # The start-boundary saved state is diagnostic, not another source interval.
        boundary=[r for r in ordered if abs(r['end_s']-lo)<=eps]
        active=[r for r in ordered if r not in boundary]
        require({r['accepted_index'] for r in active}==expected,'Missing/extra injection-window accepted-step frame')
        require(expected and abs(active[0]['start_s']-lo)<=eps and abs(active[-1]['end_s']-hi)<=eps,'TDR interval coverage does not close the injection window')
        return active,boundary
    return ordered,[]


def parse_measurements(raw,files):
    result={name:{} for name in files}
    reader=csv.DictReader(io.StringIO(raw))
    expected=['source_file','field','native_field','scope','operation','raw_value','command_status']
    require(reader.fieldnames==expected,'Unknown measurement CSV schema')
    for row in reader:
        require(None not in row and all(v is not None for v in row.values()),'Malformed CSV row')
        name=row['source_file'];require(name in result,'Unrequested TDR measurement')
        require(row['command_status']=='OK','Native command failed: '+str(row))
        if row['operation']!='integral':continue
        role,scope=row['field'],row['scope'];require(role in ROLES and scope in SCOPES,'Unknown native integral role/scope')
        require(row['native_field']==ROLES[role],'Native field identity differs')
        key=(role,scope);require(key not in result[name],'Duplicate native integral')
        value=finite(row['raw_value'],'native integral')
        if role in ('G','ONE'):require(value>=0,'Negative native '+role)
        if role=='ONE':require(value>0,'Empty native ROI')
        result[name][key]=value
    for name,values in result.items():
        require(set(values)=={(r,s) for r in ROLES for s in SCOPES},'Incomplete native fields/scopes: '+name)
    return result


def checked_extractor(digest,executed):
    require(C['extractor_revisions']==EXTRACTORS,'Extractor whitelist contract differs')
    require(digest in EXTRACTORS,'Unregistered extractor revision')
    source=EXTRACTORS[digest]
    require(old.sha_file(HERE/source)==digest,'Frozen corresponding extractor source differs')
    require(old.sha_file(executed)==digest,'Executed extractor hash differs')
    return source


def check_cleanup(raw,files,semantics='integer_zero',inventory_raw=None):
    require(semantics in ('integer_zero','exact_deleted_object_name'),'Unknown native cleanup semantics')
    objects={name:{} for name in files}
    if semantics=='exact_deleted_object_name':
        inventory=csv.DictReader(io.StringIO(inventory_raw or ''))
        require(inventory.fieldnames==['source_file','dataset','object_type','native_name'],'Native inventory schema missing for cleanup')
        for row in inventory:
            if row['object_type'] not in ('plot','geometry'):continue
            name=row['source_file'];require(name in objects,'Native object for unknown TDR')
            kind=row['object_type'];require(kind not in objects[name],'Duplicate native object identity')
            require(re.fullmatch(r'[A-Za-z0-9_.-]+',row['native_name']) is not None,'Native object identity is not a simple name')
            objects[name][kind]=row['native_name']
        require(all(set(v)=={'plot','geometry'} for v in objects.values()),'Incomplete native object identity')
    found={name:[] for name in files}
    for row in csv.DictReader(io.StringIO(raw)):
        if row['operation'] not in ('remove_plots','remove_datasets'):continue
        require(row['source_file'] in found,'Cleanup for unknown TDR')
        require(row['command_status']=='OK','Native memory cleanup failed')
        if semantics=='integer_zero':
            require(row['raw_value']=='0','Native memory cleanup failed')
        else:
            kind='plot' if row['operation']=='remove_plots' else 'geometry'
            expected=objects[row['source_file']][kind]
            require(row['native_field']==expected and row['raw_value'].strip()==expected,'Deleted object name differs from native inventory')
        found[row['source_file']].append(row['operation'])
    require(all(v==['remove_plots','remove_datasets'] for v in found.values()),'Missing/duplicate/out-of-order native memory cleanup')
    return True


def extraction_evidence(folder,archive,solver_report,out):
    folder=Path(folder).resolve()
    operation=folder.parent if folder.name=='collected' else folder
    folder=operation/'collected'
    receipt=operation/'field-extraction-record.json';record=old.json_load(receipt.read_bytes())
    require(record.get('schema')=='dram-see-v4-native-field-extraction-receipt-r1','Unknown extraction receipt')
    for key in ('svisual_exit_code','remote_exit_code','runner_exit_code','collection_exit_code'):
        require(type(record.get(key)) is int and record[key]==0,'Unknown/nonzero extraction exit: '+key)
    require(record['solver_run_id']==solver_report['run_id'] and record['solver_archive_sha256']==solver_report['archive_sha256'],'Extraction does not identify original solver archive')
    require(record['solver_manifest_sha256']==solver_report['manifest_sha256'],'Extraction solver manifest differs')
    require((ROOT/record['operation_record']).resolve()==operation/'operation.json' and (ROOT/record['operation_archive']).resolve()==operation/'results.tar','Extraction operation identity differs')
    require(old.sha_file(operation/'operation.json')==record['operation_record_sha256'],'Operation receipt hash differs')
    require(old.sha_file(operation/'results.tar')==record['operation_archive_sha256'],'Operation archive hash differs')
    op=old.json_load((operation/'operation.json').read_bytes())
    require(op['state']=='COLLECTED_PENDING_AUDIT' and op['archive_sha256']==record['operation_archive_sha256'],'Operation not known collected')
    for key,rawkey in [('runner_exit_code','ssh_exit_code'),('remote_exit_code','remote_exit_code'),('collection_exit_code','collection_exit_code')]:
        require(type(op.get(rawkey)) is int and op[rawkey]==record[key]==0,'Operation actual exit differs')
    extractor=checked_extractor(record['extractor_sha256'],folder/'extract_fields.tcl')
    out['extractor_source_file']=extractor
    out['extractor_execution_basename']='extract_fields.tcl'
    files=(folder/'tdr-files.txt').read_text().splitlines()
    require(files and len(files)==len(set(files)),'Missing/duplicate TDR list')
    require(all(re.fullmatch(r'[A-Za-z0-9_.-]+\.tdr',name) for name in files),'Unsafe TDR basename')
    hashes=record['tdr_files_sha256']
    require(set(files)==set(hashes)==set(record['tdr_before_sha256'])==set(record['tdr_after_sha256']),'TDR hash inventory differs')
    for name,digest in hashes.items():
        require(digest==archive.digest(name)==old.sha_file(folder/name)==record['tdr_before_sha256'][name]==record['tdr_after_sha256'][name],'TDR changed or not original: '+name)
    status={}
    for line in (folder/'diagnostic-status.txt').read_text().splitlines():
        if '=' in line:
            key,value=line.split('=',1);require(key not in status,'Duplicate extraction status key');status[key]=value
    require(status.get('schema')=='source-field-audit-r2-extraction' and status.get('mandatory_command_errors')=='0','Missing native extraction completion status')
    require(status.get('files_requested')==status.get('files_completed')==str(len(files)),'Native extraction count differs')
    require('FIELD_AUDIT_COMPLETED mandatory_errors=0' in (folder/'svisual.log').read_text(errors='replace').splitlines(),'Native completion sentinel missing')
    require((folder/'svisual-exit-code.txt').read_text().strip()=='0','Raw SVisual exit not zero')
    with Archive(operation/'results.tar') as extracted:
        for name,digest in record['native_outputs_sha256'].items():
            require(re.fullmatch(r'[A-Za-z0-9_.-]+',name) and old.sha_file(folder/name)==digest==extracted.digest(name),'Extraction output hash differs')
        for name,digest in hashes.items():require(extracted.digest(name)==digest,'Operation TDR hash differs')
    require({'field-measurements.csv','field-inventory.csv','tdr-state-metadata.csv','diagnostic-status.txt','svisual.log','svisual-exit-code.txt'}<=set(record['native_outputs_sha256']),'Unbound native output evidence')
    out['extraction_record']=record;out['extraction_record_sha256']=old.sha_file(receipt)
    raw=(folder/'field-measurements.csv').read_text()
    require(status.get('memory_release')=='plot_then_dataset_per_frame','Bounded extractor status differs')
    require(status.get('cleanup_success')=='exact_deleted_object_name','Named cleanup status differs')
    out['native_memory_cleanup_verified']=check_cleanup(raw,files,'exact_deleted_object_name',(folder/'field-inventory.csv').read_text())
    out['native_memory_cleanup_semantics']='exact_deleted_object_name'
    out['extraction_directory']=str(folder)
    out['field_measurements_sha256']=record['native_outputs_sha256']['field-measurements.csv']
    return files,parse_measurements(raw,files)


def summarize_snapshots(index,values):
    rows=[]
    for step in index:
        v=values[step['source_file']];g=v['G','SILICON_NO_WINDOW']
        row={**step,'G_silicon_raw':g,'G_Total_raw':v['G','Total'],
             'XG_silicon_raw':v['XG','SILICON_NO_WINDOW'],'YG_silicon_raw':v['YG','SILICON_NO_WINDOW'],
             'centroid_x_um':v['XG','SILICON_NO_WINDOW']/g if g else None,
             'centroid_y_um':v['YG','SILICON_NO_WINDOW']/g if g else None,
             'Center_fraction':v['G','Center']/g if g else None,
             'silicon_area_um2':v['ONE','SILICON_NO_WINDOW']}
        for roi in C['rois_um']:
            for role in ROLES:row[role+'_'+roi+'_raw']=v[role,roi]
        rows.append(row)
    return rows


def gating_rois(case):
    require(case in C['source_case_ids'],'Unknown source case')
    return C['legacy_rois']+(C['local_source_rois'] if case in C['local_source_roi_cases'] else [])


def full_metrics(index,values,rows,spec,proof,out):
    failures=[]
    def gate(ok,message):
        if not ok:failures.append(message)
    case=spec['case_id'];gated=gating_rois(case);lo,hi=C['window_s']
    require(all(LEGACY in row and row[LEGACY]>=0 for row in rows),'Missing/negative native legacy total')
    trmap={t['source_name']:t for t in spec['tracks']}
    require(set(proof['rois'])==set(C['rois_um']),'Offline spatial proof must declare all eleven ROIs')
    def expected_charge(roi):
        return math.fsum(t['q_fC']*r3.o.mass(lo,hi,trmap[t['source_name']]['time_s'],trmap[t['source_name']]['s_hi_s']) for t in proof['rois'][roi]['tracks'])
    def expected_time(roi):
        mass=expected_charge(roi)
        return math.fsum(t['q_fC']*r3.o.mass(lo,hi,trmap[t['source_name']]['time_s'],trmap[t['source_name']]['s_hi_s'])*trmap[t['source_name']]['time_s'] for t in proof['rois'][roi]['tracks'])/mass if mass>0 else None
    selected={r['accepted_index'] for r in index}
    legacy_full=r3.o.rectangular(rows,LEGACY)*CONVERSION
    legacy_in=math.fsum(rows[i][LEGACY]*(rows[i]['time']-rows[i-1]['time']) for i in selected)*CONVERSION
    legacy_out=math.fsum(b[LEGACY]*(b['time']-a['time']) for i,(a,b) in enumerate(zip(rows,rows[1:]),1) if i not in selected)*CONVERSION
    q={scope:math.fsum(values[r['source_file']]['G',scope]*r['dt_s'] for r in index)*CONVERSION for scope in SCOPES}
    target=proof['domain_charge_fC'];total=q['SILICON_NO_WINDOW'];wanted_window=expected_charge('Total')
    require(target>0 and wanted_window>0,'Zero source does not define an active field audit')
    out['charge']={'prescribed_total_fC':spec['source_total_fC'],'domain_target_fC':target,'clipping_not_renormalized':True,
                  'legacy_full_fC':legacy_full,'legacy_window_fC':legacy_in,'legacy_outside_window_fC':legacy_out,
                  'TDR_window_fC':total,'TDR_roi_window_fC':q,'expected_window_fC':wanted_window,
                  'TDR_plus_measured_legacy_outside_fC':total+legacy_out,'hybrid_is_explicit':True,
                  'no_unobserved_time_filled':True,'old_legacy_trapezoid_fC':old.integral(rows,'time',LEGACY)*CONVERSION}
    gate(abs(legacy_full-target)<=T['source_relative']*target,'Legacy full generated charge exceeds5% of domain target')
    gate(abs(total-wanted_window)<=T['source_relative']*wanted_window,'Native TDR window generated charge exceeds5% of clipped domain target')
    gate(abs(total-legacy_in)<=T['source_relative']*max(legacy_in,wanted_window),'TDR and native legacy window charge differ by>5%')
    out['gated_rois']=gated;out['roi_fraction_checks']={};out['time_checks']={};out['partition_checks']=[]
    for roi in C['rois_um']:
        observed=q[roi]/total if total>0 else None;expected=expected_charge(roi)/wanted_window;enabled=roi in gated
        out['roi_fraction_checks'][roi]={'observed':observed,'expected':expected,'abs_error':abs(observed-expected) if observed is not None else None,'gated':enabled}
        if enabled:gate(observed is not None and abs(observed-expected)<=T['roi_fraction_abs'],'ROI fraction differs: '+roi)
        if expected>=T['active_generation_fraction']:
            weights=[values[r['source_file']]['G',roi]*r['dt_s'] for r in index]
            mass=math.fsum(weights);tc=math.fsum(w*(r['start_s']+r['end_s'])/2 for w,r in zip(weights,index))/mass if mass else None
            wanted=expected_time(roi)
            out['time_checks'][roi]={'observed_s':tc,'expected_s':wanted,'abs_error_s':abs(tc-wanted) if tc is not None else None,'gated':enabled}
            if enabled:gate(tc is not None and abs(tc-wanted)<=T['time_centroid_abs_s'],'TDR time centroid exceeds0.5ps: '+roi)
    peak=max(values[r['source_file']]['G','SILICON_NO_WINDOW'] for r in index)
    for part in C['partitions']:
        curve=max(abs(math.fsum(values[r['source_file']]['G',roi] for roi in part)-values[r['source_file']]['G','SILICON_NO_WINDOW']) for r in index)/peak if peak else None
        charge=abs(math.fsum(q[roi] for roi in part)-total)/total if total else None
        out['partition_checks'].append({'rois':part,'curve_relative_error':curve,'charge_relative_error':charge})
        gate(curve is not None and charge is not None and max(curve,charge)<=T['partition_relative'],'Native TDR ROI partition fails')
    out['spatial_centroid']={'rois':{},'definition':'Each effective ROI true native XG/G,YG/G at active accepted intervals'}
    for roi in gated:
        if expected_charge(roi)/wanted_window<T['active_generation_fraction']:continue
        errors={'x':0.,'y':0.};active=0;roi_peak=max(values[r['source_file']]['G',roi] for r in index)
        for r in index:
            v=values[r['source_file']];g=v['G',roi]
            if roi_peak<=0 or g<roi_peak*T['active_generation_fraction']:continue
            rate,x,y=r3.average_profile(spec,proof,roi,r['start_s'],r['end_s'])
            active+=1
            for axis,wanted in [('x',x),('y',y)]:
                if wanted is None:failures.append('Active native ROI outside analytic interval: '+roi);continue
                errors[axis]=max(errors[axis],abs(v[axis.upper()+'G',roi]/g-wanted))
        out['spatial_centroid']['rois'][roi]={'active_samples':active,'max_abs_error_um':errors}
        gate(active>0 and max(errors.values())<=T['centroid_abs_um'],'Native moment centroid exceeds0.01um: '+roi)
    wave_rois=['Total']+(C['local_source_rois'] if case in C['local_source_roi_cases'] else [])
    out['waveform']={}
    for roi in wave_rois:
        scope='SILICON_NO_WINDOW' if roi=='Total' else roi
        expected=[r3.average_profile(spec,proof,roi,r['start_s'],r['end_s'])[0] for r in index]
        observed=[values[r['source_file']]['G',scope]*CONVERSION for r in index]
        error=max(abs(a-b) for a,b in zip(expected,observed))/max(expected)
        out['waveform'][roi]={'BE_interval_average_peak_relative_error':error,'no_fitted_amplitude':True}
        gate(error<=T['generation_waveform_relative'],'Native TDR BE-average waveform exceeds5%: '+roi)
    if case=='A6':
        left,right=[out['time_checks'].get(roi,{}) for roi in C['local_source_rois']]
        observed=(right.get('observed_s')-left.get('observed_s')) if left.get('observed_s') is not None and right.get('observed_s') is not None else None
        wanted=expected_time('SourceRight')-expected_time('SourceLeft')
        out['A6_local_delay']={'observed_s':observed,'expected_local_weighted_s':wanted,'declared_track_delay_s':C['A6_delay_s'],
                               'abs_error_s':abs(observed-wanted) if observed is not None else None,'tolerance_s':T['time_centroid_abs_s']}
        gate(observed is not None and abs(observed-wanted)<=T['time_centroid_abs_s'],'A6 SourceRight-SourceLeft delay differs from10ps')
    out['area_diagnostics']={scope:{'min_um2':min(v['ONE',scope] for v in values.values()),'max_um2':max(v['ONE',scope] for v in values.values())} for scope in SCOPES}
    out['field_gate_failures']=failures
    require(not failures,'; '.join(failures))
    return True


def audit(run,extraction,mode='full',output=None):
    require(mode in ('snapshots','full'),'Explicit snapshots/full mode required')
    folder=Path(run).resolve()
    out={'schema':'source-field-audit-r2','audit_revision':1,'mode':mode,'passed':False,'field_measurements_passed':False,
         'scientific_calibration_passed':False,'overall_source_interface_passed':False,'checks':{},'errors':[],
         'audit_tolerances':T,'audit_sha256':old.sha_file(Path(__file__)),'field_contract_sha256':old.sha_file(HERE/'field_contract.json')}
    require(C['frozen_reference_contract_sha256']==old.sha_file(r3.b.CONTRACT) and C['audit_tolerances']==r3.T,'Frozen field gate dependencies changed')
    for name,digest in C['frozen_library_sha256'].items():
        require(old.sha_file(ROOT/name)==digest,'Frozen field library dependency changed: '+name)
    checks=old.Checks(out);manifest=checks.call('solver_manifest',lambda:old._manifest(folder,out));frames=[]
    if manifest is not None:
        def inspect():
            nonlocal frames
            with Archive(folder/'results.tar') as archive:
                checks.call('real_solver_provenance',lambda:old._provenance(archive,manifest,folder,None,out))
                curves=checks.call('full_raw_curves',lambda:old._curves(archive,out))
                evidence=checks.call('native_extraction_provenance',lambda:extraction_evidence(extraction,archive,out,out))
                if curves is None or evidence is None:return False
                files,values=evidence
                source_parameters=old.json_load(archive.read('parameters.json'))
                require(source_parameters.get('case_id') in C['source_case_ids'] and source_parameters.get('source_charge_fC',0)>0,'This field audit requires an actual source; it never fabricates A0 fields')
                def mapping():
                    if mode=='full':
                        actual={name for name in archive.members if re.fullmatch(r'gstep(?:_[A-Za-z0-9]+)+\.tdr',name)}
                        require(actual==set(files),'All archived gstep TDRs must be included exactly once')
                    index,boundary=index_frames(archive.read('transient_des.log').decode(errors='replace'),curves['device'],files,mode=='full')
                    out['boundary_frames_not_integrated']=boundary
                    out['accepted_intervals']=index
                    return index
                index=checks.call('actual_BE_frame_bijection',mapping)
                if index is not None:
                    frames=summarize_snapshots(index,values);out['frame_count']=len(frames)
                    if mode=='full':
                        def physical():
                            build=module(ROOT/'experiments/dram-see-v4/source-interface-r5/build_interface.py','_sfa_r5_build')
                            p=old.json_load(archive.read('parameters.json'));spec=old.json_load(archive.read('source-spec.json'))
                            contract=old.json_load(archive.read('source-contract.json'))
                            require(p['schema']=='dram-see-v4-source-interface-r5' and p['case_id'] in C['source_case_ids'],'Only frozen r5 nonzero-source roles support full field audit')
                            build.check_role(p['case_id'],p['stored_bit'],p['variant'])
                            require(contract['audit_tolerances']==T and contract['rois_um']==C['rois_um'],'Field thresholds/ROIs differ')
                            require(contract['additional_roi_gate_cases']==C['local_source_roi_cases'] and contract['additional_rois']==C['local_source_rois']
                                    and contract['legacy_roi_names']==C['legacy_rois'],'Additional ROI gate scope differs')
                            require(archive.read('source-contract.json')==build.CONTRACT.read_bytes(),'r5 contract hash differs')
                            require(p['source_contract_sha256']==archive.digest('source-contract.json'),'r5 parameter contract hash differs')
                            require(p['source_code_sha256']==build.code_hashes(),'r5 code dependency differs')
                            require(build.encoded(spec)==build.encoded(build.source_spec(p['case_id'])),'r5 source specification differs')
                            require(archive.read('device.cmd').decode()==build.render_deck(p['case_id'],p['stored_bit'],p['variant']),'r5 deck differs')
                            proof=build.offline_proof(spec)
                            out['source_parameters']=p
                            out.update(case_id=p['case_id'],stored_bit=p['stored_bit'],variant=p['variant'])
                            out['cadence']=r3.r2.cadence(curves,p)
                            return p,spec,proof
                        data=checks.call('frozen_r5_measurement_contract',physical)
                        if data is not None:
                            p,spec,proof=data
                            checks.call('native_full_field_gates',lambda:full_metrics(index,values,curves['device'],spec,proof,out))
                            checks.call('terminal_voltage_current_conservation',lambda:old._response(p,curves,out))
                require(old.sha_file(folder/'results.tar')==out['archive_sha256'] and old.sha_file(folder/'manifest.json')==out['manifest_sha256'],'Original solver archive changed during audit')
                return True
        checks.call('safe_archive_read',inspect)
    out['passed']=not out['errors'] and len(out['checks'])==(9 if mode=='full' else 6)
    out['field_measurements_passed']=out['passed'] and mode=='full'
    out['status']='NATIVE_SNAPSHOT_EXTRACTION_VERIFIED_NO_FULL_SOURCE_CLAIM' if out['passed'] and mode=='snapshots' else ('NATIVE_FULL_FIELD_GATES_PASSED_CONTROL_STILL_REQUIRED' if out['passed'] else 'FAILED_OR_INCOMPLETE')
    frame_bytes=None
    if frames:
        buf=io.StringIO(newline='');writer=csv.DictWriter(buf,fieldnames=list(frames[0]));writer.writeheader();writer.writerows(frames)
        frame_bytes=buf.getvalue().encode('utf-8')
        out['frames_csv_sha256']=old.sha_bytes(frame_bytes)
        out['frames_csv_schema']='source-field-audit-r2-native-11roi-frames'
        out['frames_csv_path']=None
    if output is not None:
        dest=Path(output).resolve();require(dest.is_relative_to(OUTPUT.resolve()) and dest!=OUTPUT.resolve(),'Audit output scope only')
        dest.mkdir(parents=True,exist_ok=True)
        if frame_bytes is not None:
            with (dest/'frames.csv').open('xb') as f:f.write(frame_bytes)
            out['frames_csv_path']=str(dest/'frames.csv')
        with (dest/'audit.json').open('x',encoding='utf-8') as f:json.dump(out,f,indent=2,ensure_ascii=False,allow_nan=False)
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=('snapshots','full'));p.add_argument('run',type=Path)
    p.add_argument('--extraction',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit(a.run,a.extraction,a.mode,a.output);print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
