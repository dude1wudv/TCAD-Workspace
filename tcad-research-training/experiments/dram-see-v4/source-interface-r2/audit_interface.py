"""Audit completed r2 archives and matched comparisons; never run or recover a solver."""
import argparse
import csv
import json
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _module(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(),str(path),'exec'),module.__dict__)
    return module


build = _module(HERE/'build_interface.py','_r2_builder_readonly')
old = _module(ROOT/'experiments/dram-see-v4/source-probe/audit_probe.py','_r2_archive_curve_readonly')
require, Archive, Checks = old.require, old.Archive, old.Checks
C = build.contract()
T = C['audit_tolerances']
CONVERSION = C['device']['effective_thickness_um'] * 1e-12 * C['conversion']['elementary_charge_C'] * 1e15
LIMITS = ['Artificial zero-z 2D sources only; no 3D event projection or nuclear witness.',
          'Uncalibrated inherited 0.25um device and ideal initialized storage clamp.',
          'Raw voltages and control-relative changes; no neutral-reference classification or upset labels.',
          'A successful run is not a refinement test; only an explicit matched comparison tests the registered conditions.',
          'ROI and centroid gates are interface checks, not microscopic ion-track validation.',
          'Optional TDR field extraction is separate evidence; file existence alone is never reported as extracted field verification.']


def report(schema):
    return {'schema':schema,'passed':False,'status':'FAILED_OR_INCOMPLETE','checks':{},'errors':[],
            'audit_tolerances':T,'limits':LIMITS,'scientific_calibration_passed':False,
            'numerical_convergence_validated':False,'audit_code_sha256':old.sha_file(Path(__file__)),
            'contract_sha256':old.sha_file(build.CONTRACT),'parser_source_sha256':old.sha_file(ROOT/'experiments/dram-see-v4/source-probe/audit_probe.py')}


def contracts(archive, out):
    p = old.json_load(archive.read('parameters.json'))
    spec = build.validate_spec(old.json_load(archive.read('source-spec.json')))
    require(archive.read('source-contract.json') == build.CONTRACT.read_bytes(),'Frozen contract differs')
    require(p.get('schema') == 'dram-see-v4-source-interface-r2','Not an r2 source project')
    build.check_role(p['case_id'],p['stored_bit'],p['variant'])
    require(p['case_id'] == spec['case_id'] and p['event_id'] == spec['event_id'],'Source/event identity mismatch')
    require(p['source_spec_sha256'] == archive.digest('source-spec.json') and p['source_contract_sha256'] == archive.digest('source-contract.json'),'Source/contract digest mismatch')
    require(p['source_code_sha256'] == build.code_hashes(),'Frozen source dependencies changed')
    require(p['matching_contract_sha256'] == build.sha(build.encoded(p['matching_contract'])),'Matching hash differs')
    require(all(p[k] == v for k,v in p['matching_contract'].items()),'Conflicting matching parameters')
    expected = {'gate_length_um':.25,'oxide_nm':5.,'effective_thickness_um':1.,'capacitance_F':1e-14,
                'bitline_capacitance_F':1e-13,'reference_capacitance_F':1e-13,'read_sample_s':4e-9,
                'reference_mode':'offline','neutral':False,'temperature_K':300,'step_scale':1.,
                'target_voltage_V':.9 if p['stored_bit'] else .1,
                'mesh_scale':C['variants'][p['variant']]['mesh_factor'],
                'pulse_max_step_s':C['variants'][p['variant']]['pulse_max_step_s']}
    require(all(p.get(k) == v for k,v in expected.items()),'Inherited circuit/device or numerical settings differ')
    require(p['geometry_sha256'] == archive.digest('geometry.scm'),'Geometry hash differs')
    require(archive.read('device.cmd').decode() == build.render_deck(spec,p['stored_bit'],p['variant']),'Full rendered source/circuit/output deck differs')
    require(archive.read('heavyion.par').decode() == build.render_parameters(spec),'Explicit source parameters differ')
    proof = build.offline_check(spec)
    require(build.encoded(old.json_load(archive.read('offline-source-check.json'))) == build.encoded(proof),'Offline ledger differs')
    require(p['source_count'] == len(spec['tracks']) and p['source_charge_fC'] == spec['source_total_fC']
            and p['domain_charge_fC'] == proof['domain_charge_fC'],'Source totals conflict')
    manifest = old.json_load(archive.read('input-manifest.json'))
    require(manifest['schema'] == 'dram-see-v4-source-interface-r2-inputs' and manifest['source_code_sha256'] == p['source_code_sha256'],'Input manifest differs')
    for name,digest in manifest['files_sha256'].items():
        require(archive.digest(name) == digest,'Builder manifest hash differs: '+name)
    out.update(case_id=p['case_id'],stored_bit=p['stored_bit'],variant=p['variant'],event_id=p['event_id'],parameters=p,offline_source=proof)
    out['tdr_artifacts'] = {name:archive.digest(name) for name in archive.members if re.fullmatch(r'gfield_[0-4]_access_des\.tdr',name)}
    require(len(out['tdr_artifacts']) == 5,'Missing spatial field snapshots')
    out['tdr_field_extraction_verified'] = False
    return p,spec,proof


def resolve_fields(names, nonzero, explicit=None):
    # Exact W-2024.09 spellings observed in the completed r2 A1 raw PLT.
    # Integr is an operation prefix attached to Name, not a separate word.
    expected = {'rois': {roi:'IntegrG_'+roi+' HeavyIonGeneration' for roi in C['rois_um']},
                'centroid': {axis:'IntegrG_Total '+axis.upper()+'_HeavyIonGeneration' for axis in ('x','y')}}
    require(isinstance(names,list) and all(isinstance(k,str) for k in names),'Raw dataset names must be strings')
    require(len(names) == len(set(names)),'Duplicate raw dataset name')
    known = set(expected['rois'].values()) | set(expected['centroid'].values())
    require(all(k in known for k in names if 'HeavyIonGeneration' in k),
            'Unknown native generation dataset spelling; inspect the actual PLT header')
    if explicit is not None:
        # Apply an explicit map before automatic missing-field decisions. It may
        # select only the correct native role; it cannot alias x as G, swap x/y,
        # invent a field, change values, or bypass completeness/uniqueness below.
        require(isinstance(explicit,dict) and set(explicit) == {'rois','centroid'},'Unknown explicit field-map keys')
        for group, entries in explicit.items():
            require(isinstance(entries,dict) and set(entries) <= set(expected[group]),'Unknown field-map role')
            for role,key in entries.items():
                require(isinstance(key,str) and key in names and key == expected[group][role],
                        'Explicit map must point to the exact native generation field for its role')
        mapping = {group:dict(entries) for group,entries in explicit.items()}
    else:
        mapping = {group:{role:key for role,key in entries.items() if key in names}
                   for group,entries in expected.items()}
    if nonzero:
        require(set(mapping['rois']) == set(C['rois_um']), 'Missing native ROI dataset; inspect the actual PLT header')
        require(set(mapping['centroid']) == {'x','y'},'Missing native centroid components')
    mapped = list(mapping['rois'].values())+list(mapping['centroid'].values())
    require(len(mapped) == len(set(mapped)),'A raw dataset is assigned to multiple roles')
    # An explicit empty/partial map must not hide observed native source fields,
    # particularly in A0 where absent fields carry only structural-zero evidence.
    require(set(mapped) == set(names) & known,'Explicit field map omits observed native generation data')
    return mapping


def area(rows,key,weighted_time=False):
    return math.fsum((b['time']-a['time'])*(a[key]*(a['time'] if weighted_time else 1)+b[key]*(b['time'] if weighted_time else 1))/2
                     for a,b in zip(rows,rows[1:]))


def expected_profile(spec, proof, roi, time):
    sources = {a['source_name']:a for a in spec['tracks']}
    terms = proof['rois'][roi]['tracks']
    q = math.fsum(a['q_fC']*build.temporal(time,sources[a['source_name']]) for a in terms)
    x = math.fsum(a['x_moment_fC_um']*build.temporal(time,sources[a['source_name']]) for a in terms)
    y = math.fsum(a['y_moment_fC_um']*build.temporal(time,sources[a['source_name']]) for a in terms)
    return q,(x/q if q else None),(y/q if q else None)


def cadence(curves,p):
    lo,hi = C['pulse_output_window_s']
    result = {}
    for label in ('device','circuit'):
        rows = curves[label]
        selected = [r for r in rows if lo-1e-18 <= r['time'] <= hi+1e-18]
        require(selected and abs(selected[0]['time']-lo) <= 1e-18 and abs(selected[-1]['time']-hi) <= 1e-18,'Missing injection-window output boundaries')
        maximum = max(b['time']-a['time'] for a,b in zip(selected,selected[1:]))
        require(maximum <= p['pulse_max_step_s']+T['output_step_roundoff_s'],'Accepted output spacing exceeds frozen injection-window maximum')
        result[label] = {'max_output_spacing_s':maximum,'window_samples':len(selected)}
    return result


def audit_source(curves,p,spec,proof,out,field_map=None):
    rows = curves['device']
    nonzero = bool(spec['tracks'])
    fields = resolve_fields(list(rows[0]),nonzero,field_map)
    out['raw_generation_fields'] = fields
    out['injection_output_cadence'] = cadence(curves,p)
    roi_q = {}
    for roi,key in fields['rois'].items():
        require(all(math.isfinite(r[key]) and r[key] >= 0 for r in rows),'Negative/nonfinite native generation in '+roi)
        roi_q[roi] = area(rows,key)*CONVERSION
    if not nonzero:
        require(not fields['rois'] or set(fields['rois']) == set(C['rois_um']),
                'A0 has a partial native spatial dataset set; absence cannot fill missing measurements')
        require(all(q <= T['zero_charge_fC'] for q in roi_q.values()),'A0 native generation is nonzero')
        out['radiation'] = {'target_domain_fC':0.,'generated_fC':roi_q.get('Total'),'roi_charge_fC':roi_q,
                            'evidence':'native_zero_integrals' if roi_q else 'source_free_deck_only',
                            'source_disabled_deck_verified':True,'all_roi_output_requests_verified':True,
                            'numerical_zero_observed':bool(roi_q),'time_centroid_s':None}
        return True
    q = roi_q['Total']; target = proof['domain_charge_fC']
    require(target > 0 and abs(q-target) <= T['source_relative']*target,'Native total generated charge differs from precomputed domain charge by >5%')
    require(q > 0,'No observed generation')
    radiation = {'target_domain_fC':target,'declared_total_fC':spec['source_total_fC'],
                 'outside_domain_fC':proof['outside_domain_fC'],'generated_fC':q,
                 'roi_charge_fC':roi_q,'roi_fraction_checks':{},'roi_time_checks':{},
                 'waveform_checks':{},'partition_checks':[],
                 'conversion':'integral_dt(native_2D_G_integral)*effective_thickness_um*1e-12*e_C*1e15',
                 'effective_thickness_um':C['device']['effective_thickness_um']}
    out['radiation'] = radiation
    for roi,key in fields['rois'].items():
        wanted = proof['rois'][roi]['q_fC']/target
        fraction = roi_q[roi]/q
        radiation['roi_fraction_checks'][roi] = {'observed':fraction,'expected':wanted,'abs_error':abs(fraction-wanted)}
        require(abs(fraction-wanted) <= T['roi_fraction_abs'],'Spatial ROI fraction differs: '+roi)
        expected = [expected_profile(spec,proof,roi,r['time'])[0] for r in rows]
        peak = max(expected)
        if wanted >= T['active_generation_fraction']:
            difference = max(abs(r[key]*CONVERSION-v) for r,v in zip(rows,expected))
            radiation['waveform_checks'][roi] = {'expected_peak_fC_s':peak,'max_error_fC_s':difference,'relative_error':difference/peak}
            # The registered 5% waveform gate is for total G; ROI amplitudes use
            # the registered absolute fraction gate, not an extra 5%-of-small-ROI gate.
            radiation['waveform_checks'][roi]['diagnostic_only'] = roi != 'Total'
            if roi == 'Total':
                require(difference <= T['generation_waveform_relative']*peak,'Native temporal waveform differs: '+roi)
            tc = area(rows,key,True)/area(rows,key)
            sources = {a['source_name']:a for a in spec['tracks']}
            wanted_tc = math.fsum(a['q_fC']*sources[a['source_name']]['time_s'] for a in proof['rois'][roi]['tracks'])/proof['rois'][roi]['q_fC']
            radiation['roi_time_checks'][roi] = {'observed_s':tc,'expected_s':wanted_tc,'abs_error_s':abs(tc-wanted_tc)}
            require(abs(tc-wanted_tc) <= T['time_centroid_abs_s'],'Source temporal centroid differs: '+roi)
    radiation['time_centroid_s'] = radiation['roi_time_checks']['Total']['observed_s']
    total_key = fields['rois']['Total']; total_peak = max(r[total_key] for r in rows)
    for partition in C['partitions']:
        error = max(abs(sum(r[fields['rois'][roi]] for roi in partition)-r[total_key]) for r in rows)/total_peak
        charge_error = abs(sum(roi_q[roi] for roi in partition)-q)/q
        radiation['partition_checks'].append({'rois':partition,'curve_relative_error':error,'charge_relative_error':charge_error})
        require(max(error,charge_error) <= T['partition_relative'],'Native spatial partition does not close')
    maxima = {'x':0.,'y':0.}
    selected = 0
    for row in rows:
        if row[total_key] < T['active_generation_fraction']*total_peak:
            continue
        selected += 1
        rate,x,y = expected_profile(spec,proof,'Total',row['time'])
        require(rate > 0,'Observed active source outside expected time window')
        for axis,wanted in (('x',x),('y',y)):
            actual = row[fields['centroid'][axis]]
            require(math.isfinite(actual),'Nonfinite active native source centroid')
            maxima[axis] = max(maxima[axis],abs(actual-wanted))
    out['spatial_centroid'] = {'max_abs_error_um':maxima,'active_samples':selected,'active_fraction':T['active_generation_fraction']}
    require(selected > 0 and max(maxima.values()) <= T['centroid_abs_um'],'Native source centroid differs by >0.01um')
    return True


def load_run(run_path,project_path=None,field_map=None):
    folder = Path(run_path).resolve()
    out = report('dram-see-v4-source-interface-r2-audit')
    out['run_path'] = str(folder)
    checks = Checks(out)
    manifest = checks.call('manifest_and_inputs',lambda:old._manifest(folder,out))
    bundle = {'summary':out}
    if manifest is None:
        return bundle
    def inspect():
        with Archive(folder/'results.tar') as archive:
            checks.call('execution_and_raw_archive',lambda:old._provenance(archive,manifest,folder,project_path,out))
            valid = checks.call('frozen_r2_contract_and_complete_deck',lambda:contracts(archive,out))
            curves = checks.call('full_finite_raw_curves',lambda:old._curves(archive,out))
            if curves is not None:
                bundle['curves'] = curves
            if valid is not None:
                p,spec,proof = valid
                bundle.update(parameters=p,source=spec,proof=proof)
                if curves is not None:
                    checks.call('spatial_and_temporal_generation',lambda:audit_source(curves,p,spec,proof,out,field_map))
                    checks.call('inherited_voltage_current_and_conservation',lambda:old._response(p,curves,out))
        require(old.sha_file(folder/'manifest.json') == out['manifest_sha256'],'Manifest changed during audit')
        require(old.sha_file(folder/'results.tar') == out['archive_sha256'],'Archive changed during audit')
        return True
    checks.call('safe_archive_and_stability',inspect)
    out['passed'] = not out['errors'] and len(out['checks']) == 7
    if out['passed']:
        out['status'] = 'R2_RUN_SOURCE_SPATIAL_TEMPORAL_CHECKS_PASSED'
    return bundle


def write_output(directory,out,curves=None):
    if directory is None:
        return
    dest = Path(directory).resolve()
    require(dest.is_relative_to(build.OUTPUT_ROOT.resolve()) and dest != build.OUTPUT_ROOT.resolve(),'Output must be under r2 local_runtime')
    dest.mkdir(parents=True,exist_ok=True)
    # Never overwrite an audit silently; failure evidence stays reviewable.
    with (dest/'audit.json').open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(out,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    for label,rows in (curves or {}).items():
        with (dest/(label+'.csv')).open('x',encoding='utf-8',newline='') as stream:
            writer = csv.DictWriter(stream,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def audit(run_path,project_path=None,output=None,field_map=None):
    bundle = load_run(run_path,project_path,field_map)
    write_output(output,bundle['summary'],bundle.get('curves'))
    return bundle['summary']


def matched_control(signal,control):
    require(control['parameters']['case_id'] == 'A0','Control is not A0')
    require(signal['parameters']['matching_contract_sha256'] == control['parameters']['matching_contract_sha256'],'Signal/control model or numerics differ')
    require(signal['summary']['mesh_sha256'] == control['summary']['mesh_sha256'],'Signal/control actual mesh bytes differ')


def perturbation(a,ca,b,cb,key):
    rows = [p['curves']['circuit'] for p in (a,ca,b,cb)]
    times = sorted({r['time'] for series in rows for r in series if r['time'] >= .95e-9})
    series = [old._sample_series(row,key,times) for row in rows]
    av = [x-y for x,y in zip(series[0],series[1])]
    bv = [x-y for x,y in zip(series[2],series[3])]
    peak = max(map(abs,av+bv))
    error = max(abs(x-y) for x,y in zip(av,bv))
    limit = max(T['refinement_voltage_abs_V'],T['refinement_voltage_relative']*peak)
    return {'passed':error <= limit,'max_abs_difference_V':error,'paired_perturbation_peak_V':peak,'limit_V':limit,
            'definition':'Each signal minus its own same-bit same-numerics A0, from 0.95ns to 4ns'}


def compare(a_run,b_run,control_a,control_b,mode='equivalent',output=None,field_map=None):
    out = report('dram-see-v4-source-interface-r2-comparison')
    checks = Checks(out)
    bundles = {label:load_run(path,field_map=field_map) for label,path in
               [('a',a_run),('b',b_run),('control_a',control_a),('control_b',control_b)]}
    out['runs'] = {k:v['summary'] for k,v in bundles.items()}
    a,b,ca,cb = (bundles[k] for k in ('a','b','control_a','control_b'))
    def prerequisites():
        require(all(v['summary']['passed'] for v in bundles.values()),'Every signal/control must pass its raw audit')
        require(a['summary']['run_id'] != b['summary']['run_id'],'Comparison needs distinct signal runs')
        matched_control(a,ca); matched_control(b,cb)
        pa,pb = a['parameters'],b['parameters']
        require(pa['stored_bit'] == pb['stored_bit'],'Different stored states cannot be compared as equivalent/refined')
        roles = {pa['case_id'],pb['case_id']}
        if mode == 'equivalent':
            require(roles in ({'A1','A4'},{'A5','A7'}),'Only registered A1/A4 or A5/A7 exact-source comparisons')
            require(pa['matching_contract_sha256'] == pb['matching_contract_sha256'] and a['summary']['mesh_sha256'] == b['summary']['mesh_sha256'],'Equivalent sources require common actual mesh and numerics')
        elif mode == 'refinement':
            is_split = pa['case_id'] == 'A1' and pb['case_id'] in ('A8S2','A8S4') and pa['variant'] == pb['variant'] == 'base'
            is_refined = pa['case_id'] == pb['case_id'] and pa['variant'] == 'base' and pb['variant'] in ('time','mesh')
            require(is_split or is_refined,'Refinement order must be base A1->A8S2/A8S4 or same case base->time/mesh')
            if is_split or pb['variant'] == 'time':
                require(a['summary']['mesh_sha256'] == b['summary']['mesh_sha256'],'Segmentation/time refinement must preserve actual mesh')
            if is_refined and pb['variant'] == 'mesh':
                require(a['summary']['mesh_sha256'] != b['summary']['mesh_sha256'],'Mesh refinement did not change actual mesh')
        else:
            raise ValueError('Unknown comparison mode')
        out['comparison_mode'] = mode
        return True
    if checks.call('matched_comparison_prerequisites',prerequisites):
        def source():
            qa,qb = (v['summary']['radiation']['generated_fC'] for v in (a,b))
            difference = abs(qa-qb)
            limit = T['pair_generated_charge_abs_fC'] if mode == 'equivalent' else T['refinement_charge_relative']*abs(qa)
            out['source_charge_comparison'] = {'a_fC':qa,'b_fC':qb,'absolute_difference_fC':difference,'limit_fC':limit}
            require(difference <= limit,'Generated charge comparison exceeds frozen gate')
            if mode == 'equivalent':
                comparisons = {}
                for roi in C['rois_um']:
                    ka,kb = (v['summary']['raw_generation_fields']['rois'][roi] for v in (a,b))
                    comparisons[roi] = old._pair_curve(a['curves']['device'],b['curves']['device'],ka,kb,relative=T['pair_generation_curve_relative'])
                out['equivalent_roi_curves'] = comparisons
                require(all(v['passed'] for v in comparisons.values()),'Equivalent native ROI curves differ')
            return True
        checks.call('generation_comparison',source)
        def response():
            if mode == 'equivalent':
                result = {key:old._pair_curve(a['curves']['circuit'],b['curves']['circuit'],key,absolute=T['pair_voltage_abs_V'])
                          for key in ('v(sn)','v(bl)','v(ref)','v(wl)')}
                for key in ('i(access,sn)','i(access,bl)'):
                    result[key] = old._pair_curve(a['curves']['circuit'],b['curves']['circuit'],key,absolute=T['pair_current_abs_A'],relative=T['pair_current_relative'])
                for port in ('source','drain','gate','body'):
                    key = port+' TotalCurrent'
                    result[key] = old._pair_curve(a['curves']['device'],b['curves']['device'],key,absolute=T['pair_current_abs_A'],relative=T['pair_current_relative'])
            else:
                result = {key:perturbation(a,ca,b,cb,key) for key in ('v(sn)','v(bl)')}
            out['continuous_response_comparison'] = result
            require(all(v['passed'] for v in result.values()),'Response comparison exceeds frozen gate')
            return True
        checks.call('continuous_response_comparison',response)
        diagnostics = {}
        for label,signal,control in [('a',a,ca),('b',b,cb)]:
            rows,baseline = signal['curves']['circuit'],control['curves']['circuit']
            sn = old.legacy.sample(rows,'v(sn)',2.8e-9)-old.legacy.sample(baseline,'v(sn)',2.8e-9)
            bl = old.legacy.sample(rows,'v(bl)',4e-9)-old.legacy.sample(baseline,'v(bl)',4e-9)
            diagnostics[label] = {'delta_SN_hold_V':sn,'delta_BL_read_V':bl,'C_times_delta_SN_fC':1e-14*sn*1e15,
                                  'charge_definition':'Algebraic C*dV diagnostic, not independently measured collected charge',
                                  'port_integrals':signal['summary']['terminal_currents']}
        out['control_relative_diagnostics'] = diagnostics
    out['passed'] = not out['errors'] and len(out['checks']) == 3
    if out['passed']:
        out['status'] = 'R2_'+mode.upper()+'_COMPARISON_PASSED'
    out['registered_refinement_comparison_passed'] = out['passed'] and mode == 'refinement'
    write_output(output,out)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    a = sub.add_parser('audit'); a.add_argument('run_path',type=Path); a.add_argument('--project',type=Path)
    pair = sub.add_parser('compare'); pair.add_argument('a_run',type=Path); pair.add_argument('b_run',type=Path)
    pair.add_argument('--control-a',required=True,type=Path); pair.add_argument('--control-b',required=True,type=Path)
    pair.add_argument('--mode',choices=('equivalent','refinement'),required=True)
    for p in (a,pair):
        p.add_argument('--output',type=Path); p.add_argument('--field-map',type=Path)
    args = parser.parse_args()
    mapping = build.read_json(args.field_map) if args.field_map else None
    if args.command == 'audit':
        result = audit(args.run_path,args.project,args.output,mapping)
    else:
        result = compare(args.a_run,args.b_run,args.control_a,args.control_b,args.mode,args.output,mapping)
    print(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
