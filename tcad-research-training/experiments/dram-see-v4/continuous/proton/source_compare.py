"""Compare measured native HeavyIonGeneration against independent finite-Si G.

This verifies numerical fields supplied by an upstream native extraction adapter.
It does not certify that adapter, fabricate PMI clocks, or grant source qualification.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
from source_reference import NATIVE_TO_FC,require,read_json,digest,write_new


def compare(reference,clock,measurements):
    require(clock['schema']=='continuous-proton-source-clock-v1' and clock['source_field']=='HeavyIonGeneration',
            'Actual HeavyIon clock/scalar evidence required')
    require(measurements.get('schema')=='continuous-proton-native-field-measurements-v1' and
            measurements.get('field_name')=='HeavyIonGeneration','Wrong native generation field identity')
    require(measurements.get('roi_boxes_um')==reference['rois_um'],'Native ROI boxes differ from independent reference')
    require(measurements.get('units')==dict(G='cm^-3 s^-1 um^3',XG='cm^-3 s^-1 um^4',
        YG='cm^-3 s^-1 um^4',ZG='cm^-3 s^-1 um^4',ONE='um^3'),'Wrong/missing native integral units')
    tol=reference['comparison_tolerances']['values'];errors=[]
    def gate(ok,message):
        if not ok:errors.append(message)
    expected={r['interval']['accepted_index']:r for r in reference['accepted_interval_expectations']}
    frames={f['source_file']:f for f in clock['frames']};observed={}
    for row in measurements['frames']:
        name=row['source_file'];require(name in frames and name not in observed,'Unknown/duplicate measured native frame')
        require(row['source_sha256']==frames[name]['source_sha256'] and row['accepted_index']==frames[name]['accepted_index'],
                'Measured frame TDR hash or interval differs from original archive')
        require(set(row['rois'])==set(reference['rois_um']),'Missing/extra measured ROI')
        for roi,values in row['rois'].items():
            require(set(values)=={'G','XG','YG','ZG','ONE'} and all(type(v) in (int,float) and math.isfinite(v) for v in values.values()),
                    'Missing/extra/nonfinite native field integral')
            require(values['G']>=0 and values['ONE']>=0,'Negative native generation or volume')
            volume=reference['roi_silicon_volumes_um3'][roi]
            gate(abs(values['ONE']-volume)<=tol['native_source_relative']*volume,'Native Si volume differs: '+name+'/'+roi)
        observed[name]=row
    require(set(observed)==set(frames) and frames,'Complete original source-window frames are required')
    ordered=sorted(frames.values(),key=lambda x:x['accepted_index'])
    required=set(clock['required_source_window_indices'])
    require(required.issubset(f['accepted_index'] for f in ordered),'Native source-window BE interval coverage is incomplete')
    totals={roi:math.fsum(observed[f['source_file']]['rois'][roi]['G']*f['dt_s']*NATIVE_TO_FC for f in ordered)
            for roi in reference['rois_um']}
    desired={roi:math.fsum(expected[f['accepted_index']]['rois'][roi]['q_fC'] for f in ordered)
             for roi in reference['rois_um']}
    scalar='IntegrSemiconductor HeavyIonGeneration'
    require(scalar in clock['generation_columns'],'Unambiguous complete native scalar integral is missing')
    raw=clock['source_scalars'];selected={f['accepted_index'] for f in ordered}
    scalar_full=math.fsum(b[scalar]*(b['time']-a['time'])*NATIVE_TO_FC for a,b in zip(raw,raw[1:]))
    scalar_inside=math.fsum(raw[i][scalar]*(raw[i]['time']-raw[i-1]['time'])*NATIVE_TO_FC for i in selected)
    full_target=reference['simulation_window']['Total']['q_fC']
    gate(abs(scalar_full-full_target)<=tol['native_source_relative']*full_target,'Full native scalar charge differs from finite-Si reference')
    gate(abs(totals['Total']-desired['Total'])<=tol['native_source_relative']*full_target,'TDR source charge differs from finite-Si reference')
    gate(abs(totals['Total']-scalar_inside)<=tol['native_source_relative']*full_target,'TDR/scalar source-window charges differ')
    roi_metrics={}
    if reference['allocated_all_space_all_time_fC']==0:
        gate(scalar_full==0 and all(v[r]==0 for row in observed.values() for v in row['rois'].values()
                                  for r in ('G','XG','YG','ZG')),'Zero source has nonzero native generation/moment')
    else:
        gate(totals['Total']>0 and desired['Total']>0,'Positive source has no native/reference in-window charge')
        for roi in reference['rois_um']:
            actual=[observed[f['source_file']]['rois'][roi]['G']*NATIVE_TO_FC for f in ordered]
            target=[expected[f['accepted_index']]['rois'][roi]['q_fC']/f['dt_s'] for f in ordered]
            peak=max(target);actual_peak=max(actual)
            fraction=totals[roi]/totals['Total'] if totals['Total'] else 0.
            want_fraction=desired[roi]/desired['Total'] if desired['Total'] else 0.
            waveform=max(abs(a-b) for a,b in zip(actual,target))/peak if peak else None
            gate(abs(fraction-want_fraction)<=tol['roi_fraction_abs'],'Native ROI fraction differs: '+roi)
            centroid_error=[0.,0.,0.];active=0;actual_time=target_time=None
            if want_fraction>=.001:
                gate(waveform is not None and waveform<=tol['be_waveform_relative'],'Native BE-average waveform differs: '+roi)
                actual_time=math.fsum(g*f['dt_s']*(f['start_s']+f['end_s'])/2 for g,f in zip(actual,ordered))/totals[roi] if totals[roi] else None
                target_time=math.fsum(expected[f['accepted_index']]['rois'][roi]['time_moment_fC_s'] for f in ordered)/desired[roi] if desired[roi] else None
                gate(actual_time is not None and target_time is not None and abs(actual_time-target_time)<=tol['time_centroid_abs_s'],
                     'Native time centroid differs: '+roi)
                for f,a,t in zip(ordered,actual,target):
                    # Include expected-active frames as well, so a vanished peak
                    # cannot exclude itself from the spatial centroid checks.
                    if a<actual_peak*.001 and t<peak*.001:continue
                    values=observed[f['source_file']]['rois'][roi];ctr=expected[f['accepted_index']]['rois'][roi]['centroid_um']
                    gate(values['G']>0 and all(v is not None for v in ctr),'Active native/reference source support differs: '+roi)
                    if values['G']>0 and all(v is not None for v in ctr):
                        active+=1
                        for j,key in enumerate(('XG','YG','ZG')):centroid_error[j]=max(centroid_error[j],abs(values[key]/values['G']-ctr[j]))
                gate(active>0 and max(centroid_error)<=tol['centroid_abs_um'],'Native spatial centroid differs: '+roi)
            roi_metrics[roi]=dict(observed_charge_fC=totals[roi],expected_charge_fC=desired[roi],
                observed_fraction=fraction,expected_fraction=want_fraction,BE_peak_relative_error=waveform,
                centroid_max_abs_error_um=centroid_error,active_centroid_frames=active,
                observed_time_centroid_s=actual_time,expected_time_centroid_s=target_time)
        for group in reference['partitions']:
            charge_error=abs(math.fsum(totals[r] for r in group)-totals['Total'])/totals['Total'] if totals['Total'] else math.inf
            gate(charge_error<=tol['partition_relative'],'Native ROI partition does not close: '+','.join(group))
    return dict(schema='continuous-proton-source-comparison-v1',comparison_passed=not errors,errors=errors,
        native_qualified=False,pmi_r12_fixed=False,upstream_extraction_provenance_verified=False,
        observed_full_scalar_charge_fC=scalar_full,expected_full_scalar_charge_fC=full_target,
        observed_TDR_charge_fC=totals['Total'],observed_scalar_frame_charge_fC=scalar_inside,
        expected_TDR_charge_fC=desired['Total'],roi_metrics=roi_metrics,
        limitation='Field arithmetic only; main pipeline must verify original extraction receipts, exact grid and both-carrier/matched-control evidence')


def build(reference,clock,measurements,output):
    r,c,m=map(read_json,(reference,clock,measurements))
    require(m.get('reference_sha256')==digest(reference) and m.get('clock_sha256')==digest(clock),
            'Measurement/reference/clock identity mismatch')
    require(r['inputs']['clock']['sha256']==digest(clock),'Reference was computed for another native clock')
    result=compare(r,c,m)
    result['inputs']={name:dict(path=str(Path(path).resolve()),sha256=digest(path))
                      for name,path in [('reference',reference),('clock',clock),('measurements',measurements)]}
    result['implementation_sha256']=digest(__file__)
    write_new(output,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('reference','clock','measurements','output'):p.add_argument('--'+name,type=Path,required=True)
    result=build(**vars(p.parse_args()))
    print(json.dumps(dict(comparison_passed=result['comparison_passed'],native_qualified=False,errors=result['errors'])))
    raise SystemExit(0 if result['comparison_passed'] else 1)
