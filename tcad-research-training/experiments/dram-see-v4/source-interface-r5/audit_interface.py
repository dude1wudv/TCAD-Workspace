"""Read-only r5 archive, source, field and matched-response acceptance."""
import argparse
import csv
import importlib.util
import io
import json
import math
from pathlib import Path
import re
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
V4 = HERE.parent
OUTPUT = ROOT / 'local_runtime/dram-see-v4/source-interface-r5'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), obj.__dict__)
    return obj


m = module(V4 / 'stage2/audit_mesh_diagnostic.py', '_r5_frozen_mesh_audit')
old, r2, r3, o = m.old, m.r2, m.r3, m.o
require, Checks, Archive = old.require, old.Checks, old.Archive
T, CONVERSION = m.T, m.CONVERSION


def builder():
    return module(HERE / 'build_interface.py', '_r5_builder_for_audit')


def report(schema):
    return dict(schema=schema, passed=False, status='FAILED_OR_INCOMPLETE', checks={}, errors=[],
                audit_tolerances=T, audit_code_sha256=old.sha_file(Path(__file__)),
                contract_sha256=old.sha_file(HERE / 'source_contract.json'),
                scientific_calibration_passed=False, numerical_convergence_validated=False,
                overall_source_interface_passed=False,
                limits=['Artificial 2D interface only; no calibrated device, 3D, upset or probability claim.',
                        'Each nonzero role still needs a matched A0 and its registered comparisons.',
                        'Window CurrentPlot is diagnostic only; native TDR measurements supply spatial evidence.'])


def accepted(summary):
    require(summary.get('passed') is True and not summary.get('errors'), 'Input audit failed or incomplete')
    require(summary.get('checks') and all(x.get('passed') is True for x in summary['checks'].values()),
            'Input audit has missing/failed checks')
    require(summary.get('audit_tolerances') == T, 'Input audit uses different thresholds')
    return True


def canonical_matching(bundle):
    p = bundle['parameters']
    common = dict(p['matching_contract'])
    require(p['matching_contract_sha256'] == old.sha_bytes(old.encoded(common)), 'Matching hash invalid')
    require(all(p.get(k) == v for k, v in common.items()), 'Conflicting physical parameters')
    if p['schema'] == 'dram-see-v4-source-interface-r4':
        bridge = bundle['summary'].get('reuse_bridge', {})
        require(bridge.get('passed') is True and p['variant'] == 'mesh'
                and bridge.get('canonical_variant') == 'main', 'Unregistered r4 alias')
        require(p['case_id'] in ('A0', 'A1') and p['stored_bit'] == 1, 'Unregistered legacy role')
        common['variant'] = 'main'
    else:
        require(p['schema'] == 'dram-see-v4-source-interface-r5', 'Unknown source revision')
    return common


def matched_control(signal, control):
    """Return evidence or raise; both bundles must already pass individual audits."""
    accepted(signal['summary']); accepted(control['summary'])
    require(control['parameters']['case_id'] == 'A0', 'Matched control must be A0')
    require(signal['parameters']['stored_bit'] == control['parameters']['stored_bit'], 'Different stored states')
    a, b = canonical_matching(signal), canonical_matching(control)
    require(a == b, 'Signal/control physical model, initialization, timing or numerics differ')
    require(signal['summary']['mesh_sha256'] == control['summary']['mesh_sha256'], 'Actual signal/control mesh differs')
    return dict(passed=True, signal_run_id=signal['summary']['run_id'], control_run_id=control['summary']['run_id'],
                canonical_matching_sha256=old.sha_bytes(old.encoded(a)),
                actual_mesh_sha256=signal['summary']['mesh_sha256'], stored_bit=a['stored_bit'],
                canonical_variant=a['variant'])


def check_contract(archive, project, out):
    b = builder(); c = b.contract()
    require(c['audit_tolerances'] == T, 'Frozen numerical thresholds changed')
    p = old.json_load(archive.read('parameters.json'))
    require(p['schema'] == 'dram-see-v4-source-interface-r5', 'Wrong source revision')
    case, bit, variant = p['case_id'], p['stored_bit'], p['variant']
    b.check_role(case, bit, variant)
    if project is not None:
        out['input_check'] = b.check_project(project)
    spec = old.json_load(archive.read('source-spec.json'))
    require(b.encoded(spec) == b.encoded(b.source_spec(case)), 'Physical source differs from registered case')
    require(archive.read('source-contract.json') == b.CONTRACT.read_bytes(), 'Frozen r5 contract differs')
    require(p['source_code_sha256'] == b.code_hashes(), 'Frozen builder dependencies changed')
    require(archive.read('device.cmd').decode() == b.render_deck(case, bit, variant), 'Complete source/circuit deck differs')
    require(archive.read('heavyion.par').decode() == b.r2.render_parameters(spec), 'HeavyIon parameters differ')
    for key, name in [('source_spec_sha256', 'source-spec.json'), ('source_contract_sha256', 'source-contract.json'),
                      ('geometry_sha256', 'geometry.scm')]:
        require(p[key] == archive.digest(name), 'Input digest differs: ' + name)
    proof = b.offline_proof(spec)
    require(old.json_load(archive.read('offline-source-check.json')) == proof, 'Offline ledger differs')
    require(p['source_count'] == len(spec['tracks']) and p['source_charge_fC'] == spec['source_total_fC']
            and p['domain_charge_fC'] == proof['domain_charge_fC'], 'Declared source/domain charge differs')
    require(p['event_id'] == spec['event_id'] and spec['case_id'] == case, 'Event identity differs')
    im = old.json_load(archive.read('input-manifest.json'))
    require(im['source_code_sha256'] == b.code_hashes(), 'Input manifest code hashes differ')
    for name, digest in im['files_sha256'].items():
        require(archive.digest(name) == digest, 'Input manifest member differs: ' + name)
    common = canonical_matching({'parameters': p, 'summary': out})
    require(common == b.expected_common(bit, variant, p['geometry_sha256']), 'Actual physical contract differs')
    require(archive.read('geometry.scm') == b.render_geometry(variant), 'Actual geometry content differs')
    frames = {n: member.size for n, member in archive.members.items() if re.fullmatch(r'gstep_[0-9]+_access_des\.tdr', n)}
    require(frames, 'No accepted-step field files')
    out.update(case_id=case, stored_bit=bit, variant=variant, parameters=p, event_id=spec['event_id'],
               dynamic_tdr_count=len(frames), dynamic_tdr_bytes=sum(frames.values()),
               canonical_matching_contract=common, canonical_matching_contract_sha256=old.sha_bytes(old.encoded(common)))
    return p, spec, proof


def source_curve(curves, p, spec, proof, out):
    rows = curves['device']; key = 'IntegrSemiconductor HeavyIonGeneration'
    out['injection_output_cadence'] = r2.cadence(curves, p)
    observed = [k for k in rows[0] if k.endswith('HeavyIonGeneration')]
    if p['case_id'] == 'A0':
        require(not spec['tracks'] and spec['source_total_fC'] == proof['domain_charge_fC'] == 0, 'A0 contains a source')
        require(all(row[k] == 0 for row in rows for k in observed), 'A0 observed generation is nonzero')
        q = 0. if key in rows[0] else None
        out['radiation'] = dict(source_free=True, generated_fC=q, legacy_generated_fC=q, target_domain_fC=0.,
                                time_centroid_s=None, evidence='observed_native_zero' if q is not None else 'structural_zero_not_measured_zero')
        return True
    require(key in rows[0] and all(row[key] >= 0 for row in rows), 'Missing/negative unwindowed native total')
    target = proof['domain_charge_fC']; mass = o.rectangular(rows, key); q = mass * CONVERSION
    require(target > 0 and mass > 0, 'Zero native or expected source')
    expected = [r3.average_profile(spec, proof, 'Total', a['time'], z['time'])[0] for a, z in zip(rows, rows[1:])]
    peak = max(expected)
    error = max(abs(row[key] * CONVERSION - wanted) for row, wanted in zip(rows[1:], expected)) / peak
    sources = {tr['source_name']: tr for tr in spec['tracks']}
    tc_expected = math.fsum(term['q_fC'] * sources[term['source_name']]['time_s']
                            for term in proof['rois']['Total']['tracks']) / target
    tc = o.rectangular(rows, key, True) / mass
    out['radiation'] = dict(source_free=False, generated_fC=q, legacy_generated_fC=q,
        declared_total_fC=spec['source_total_fC'], target_domain_fC=target, outside_domain_fC=proof['outside_domain_fC'],
        legacy_waveform_relative_error=error, time_centroid_s=tc, expected_time_centroid_s=tc_expected,
        charge_integral='Native accepted BE intervals; right rectangle; midpoint time moment',
        old_trapezoid_fC=old.integral(rows, 'time', key) * CONVERSION, windowed_CurrentPlot_used_for_acceptance=False)
    require(abs(q - target) <= T['source_relative'] * target, 'Native total differs from precomputed domain charge by >5%')
    require(error <= T['generation_waveform_relative'], 'Native BE waveform exceeds frozen 5%')
    require(abs(tc - tc_expected) <= T['time_centroid_abs_s'], 'Charge-weighted source time centroid exceeds frozen 0.5ps')
    return True


def field_frames(path, out, curves, archive, revision='r2'):
    """Bind report, receipt and raw native CSV; never reconstruct a ROI analytically."""
    path = Path(path).resolve(); raw_report = path.read_bytes(); f = old.json_load(raw_report)
    accepted(f)
    require(f['schema'] == 'source-field-audit-' + revision and f['mode'] == 'full'
            and f['field_measurements_passed'] is True, 'Full native all-frame audit required')
    for key in ('run_id', 'archive_sha256', 'manifest_sha256', 'mesh_sha256'):
        require(f[key] == out[key], 'Field report belongs to another input: ' + key)
    field_dir = V4 / ('source-field-audit-' + revision)
    require(f['audit_sha256'] == old.sha_file(field_dir / 'audit_fields.py'), 'Field auditor changed')
    require(f['field_contract_sha256'] == old.sha_file(field_dir / 'field_contract.json'), 'Field contract changed')
    require(not f.get('field_gate_failures'), 'Native spatial/temporal field gates failed')
    receipt = f['extraction_record']; operation = (ROOT / receipt['operation_record']).resolve().parent
    receipt_path = operation / 'field-extraction-record.json'
    require(old.sha_file(receipt_path) == f['extraction_record_sha256']
            and old.json_load(receipt_path.read_bytes()) == receipt, 'Field extraction receipt changed')
    for key in ('svisual_exit_code', 'remote_exit_code', 'runner_exit_code', 'collection_exit_code'):
        require(type(receipt[key]) is int and receipt[key] == 0, 'Unknown/nonzero field extraction exit')
    for key, target in [('solver_run_id', 'run_id'), ('solver_archive_sha256', 'archive_sha256'), ('solver_manifest_sha256', 'manifest_sha256')]:
        require(receipt[key] == out[target], 'Native receipt input binding differs')
    require(old.sha_file(operation / 'operation.json') == receipt['operation_record_sha256'], 'Native operation record changed')
    require(old.sha_file(operation / 'results.tar') == receipt['operation_archive_sha256'], 'Native operation archive changed')
    native = operation / 'collected'
    for name, digest in receipt['native_outputs_sha256'].items():
        require(re.fullmatch(r'[A-Za-z0-9_.-]+', name) and old.sha_file(native / name) == digest, 'Native output changed: ' + name)
    measure_path = native / 'field-measurements.csv'
    require('field-measurements.csv' in receipt['native_outputs_sha256'], 'Unbound native measurement CSV')
    files = list(receipt['tdr_files_sha256'])
    frame_auditor = module(field_dir / 'audit_fields.py', '_r5_field_frame_parser_' + revision)
    index, boundary = frame_auditor.index_frames(archive.read('transient_des.log').decode(errors='replace'), curves['device'], files, True)
    require(index == f['accepted_intervals'] and len(index) == f['frame_count'], 'Accepted native frame intervals differ')
    for name, digest in receipt['tdr_files_sha256'].items():
        require(archive.digest(name) == digest == receipt['tdr_before_sha256'][name] == receipt['tdr_after_sha256'][name], 'Native frame is not original')
    values = frame_auditor.parse_measurements(measure_path.read_text(encoding='utf-8'), files)
    fc = old.json_load((field_dir / 'field_contract.json').read_bytes())
    rows = []
    require(len(boundary) == 1, 'Native comparison needs the measured window-start frame')
    # Keep the measured initial boundary for curve comparisons, not for integration.
    for interval in sorted(boundary + index, key=lambda x: x['end_s']):
        row = {'time': interval['end_s'], 'start_s': interval['start_s'], 'source_file': interval['source_file']}
        for roi in fc['rois_um']:
            row[roi] = values[interval['source_file']][('G', roi)] * CONVERSION
        rows.append(row)
    if revision == 'r2':
        frame_path = Path(f['frames_csv_path']).resolve()
        require(frame_path == path.parent / 'frames.csv' and old.sha_file(frame_path) == f['frames_csv_sha256'], 'Published frame CSV changed')
        require(f['field_measurements_sha256'] == receipt['native_outputs_sha256']['field-measurements.csv'], 'Field measurement digest differs')
    require(old.sha_file(path) == old.sha_bytes(raw_report), 'Native field audit changed while binding')
    out['native_field_audit'] = dict(path=str(path), sha256=old.sha_bytes(raw_report), report=f,
        field_measurements_sha256=receipt['native_outputs_sha256']['field-measurements.csv'],
        native_curves_from='Bound original field-measurements.csv and exact accepted PLT intervals')
    return rows


def load(run, project=None, field_audit=None):
    run = Path(run).resolve()
    # Revision dispatch is read-only; the bridge applies its exact allowlist.
    try:
        with Archive(run / 'inputs.tar') as inputs:
            revision = old.json_load(inputs.read('parameters.json'))['schema']
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        out = report('dram-see-v4-source-interface-r5-audit')
        out['errors'].append({'check': 'revision_dispatch', 'error': str(exc)})
        out['checks']['revision_dispatch'] = {'passed': False}
        return {'summary': out}
    if revision == 'dram-see-v4-source-interface-r4':
        bridge = module(HERE / 'reuse_bridge.py', '_r5_reuse_bridge')
        return bridge.load(run, reference_project=project, field_audit=field_audit)
    out = report('dram-see-v4-source-interface-r5-audit'); out['run_path'] = str(run)
    bundle = {'summary': out}; checks = Checks(out)
    manifest = checks.call('manifest_and_inputs', lambda: old._manifest(run, out))
    if manifest is None:
        return bundle
    def inspect():
        with Archive(run / 'results.tar') as archive:
            checks.call('original_serial_execution', lambda: old._provenance(archive, manifest, run, project, out))
            data = checks.call('frozen_r5_inputs', lambda: check_contract(archive, project, out))
            curves = checks.call('full_finite_raw_curves', lambda: old._curves(archive, out))
            if curves is not None:
                bundle['curves'] = curves
            if data is not None:
                p, spec, proof = data; bundle.update(parameters=p, source=spec, proof=proof)
                if curves is not None:
                    checks.call('native_total_and_timing', lambda: source_curve(curves, p, spec, proof, out))
                    checks.call('voltage_current_conservation', lambda: old._response(p, curves, out))
                    if p['case_id'] != 'A0':
                        def bind():
                            require(field_audit is not None, 'Native full-frame field audit required')
                            bundle['native_curves'] = field_frames(field_audit, out, curves, archive)
                            return True
                        checks.call('native_all_frame_source', bind)
        require(old.sha_file(run / 'manifest.json') == out['manifest_sha256']
                and old.sha_file(run / 'results.tar') == out['archive_sha256'], 'Archive changed during audit')
        return True
    checks.call('archive_stability', inspect)
    needed = 7 if out.get('case_id') == 'A0' else 8
    out['passed'] = not out['errors'] and len(out['checks']) == needed
    if out['passed']:
        out['status'] = 'R5_A0_MATCHED_CONTROL_READY' if out['case_id'] == 'A0' else 'R5_INDIVIDUAL_PASSED_CONTROL_AND_COMPARISONS_REQUIRED'
    return bundle


def compare(a, b, ca, cb, mode='equivalent', output=None):
    out = report('dram-see-v4-source-interface-r5-comparison'); checks = Checks(out)
    out['comparison_mode'] = mode
    bundles = dict(a=a, b=b, control_a=ca, control_b=cb)
    out['runs'] = {key: value['summary'] for key, value in bundles.items()}
    def prerequisites():
        out['matched_controls'] = {'a': matched_control(a, ca), 'b': matched_control(b, cb)}
        require(a['summary']['run_id'] != b['summary']['run_id'], 'Distinct signal runs required')
        pa, pb = a['parameters'], b['parameters']; x, y = canonical_matching(a), canonical_matching(b)
        require(pa['stored_bit'] == pb['stored_bit'], 'Stored states differ')
        roles = {pa['case_id'], pb['case_id']}
        if mode == 'equivalent':
            require(roles in ({'A1', 'A4'}, {'A5', 'A7'}), 'Unregistered equivalent-source pair')
            require(x == y and a['summary']['mesh_sha256'] == b['summary']['mesh_sha256'], 'Equivalent-source numerics or actual mesh differ')
        elif mode == 'segment':
            require(pa['case_id'] == 'A1' and pb['case_id'] in ('A8S2', 'A8S4')
                    and x['variant'] == y['variant'] == 'main' and x == y, 'Order must be main A1 -> A8S2/A8S4')
            require(a['summary']['mesh_sha256'] == b['summary']['mesh_sha256'], 'Segmentation changed actual mesh')
        elif mode == 'refinement':
            require(pa['case_id'] == pb['case_id'] and x['variant'] == 'main'
                    and y['variant'] in ('time', 'fine'), 'Order must be same-case main -> time/fine')
            differences = {k for k in set(x) | set(y) if x.get(k) != y.get(k)}
            wanted = {'variant', 'pulse_max_step_s'} if y['variant'] == 'time' else {'variant', 'mesh_scale', 'geometry_sha256'}
            require(differences == wanted, 'Refinement changed additional physics, initial state or circuit parameters')
            same_mesh = a['summary']['mesh_sha256'] == b['summary']['mesh_sha256']
            require(same_mesh == (y['variant'] == 'time'), 'Actual mesh violates registered refinement')
            require(a['source'] == b['source'], 'Numerical refinement changed physical source')
        else:
            raise ValueError('Unknown comparison mode')
        return True
    if checks.call('matched_comparison_prerequisites', prerequisites):
        def generation():
            qa, qb = (v['summary']['radiation']['legacy_generated_fC'] for v in (a, b))
            require(qa > 0 and qb > 0, 'Comparison requires measured positive charge')
            limit = T['pair_generated_charge_abs_fC'] if mode == 'equivalent' else T['refinement_charge_relative'] * abs(qa)
            out['source_charge_comparison'] = dict(a_fC=qa, b_fC=qb, absolute_difference_fC=abs(qa-qb), limit_fC=limit,
                denominator='a main baseline for segment/refinement', observable='Native unwindowed total BE integral')
            require(abs(qa-qb) <= limit, 'Generated charge comparison exceeds frozen threshold')
            if mode == 'equivalent':
                rois = set(m.C['rois_um'])
                if a['parameters']['case_id'] in ('A5', 'A7'):
                    rois |= {'SourceLeft', 'SourceRight'}
                result = {roi: old._pair_curve(a['native_curves'], b['native_curves'], roi,
                          relative=T['pair_generation_curve_relative']) for roi in sorted(rois)}
                out['equivalent_native_roi_curves'] = result
                require(all(x['passed'] for x in result.values()), 'Equivalent native ROI waveform differs')
            return True
        checks.call('generation_comparison', generation)
        def response():
            if mode == 'equivalent':
                result = {key: old._pair_curve(a['curves']['circuit'], b['curves']['circuit'], key,
                         absolute=T['pair_voltage_abs_V']) for key in ('v(sn)', 'v(bl)', 'v(ref)', 'v(wl)')}
                for key in ('i(access,sn)', 'i(access,bl)'):
                    result[key] = old._pair_curve(a['curves']['circuit'], b['curves']['circuit'], key,
                        absolute=T['pair_current_abs_A'], relative=T['pair_current_relative'])
                for port in ('source', 'drain', 'gate', 'body'):
                    key = port + ' TotalCurrent'
                    result[key] = old._pair_curve(a['curves']['device'], b['curves']['device'], key,
                        absolute=T['pair_current_abs_A'], relative=T['pair_current_relative'])
            else:
                result = {key: r2.perturbation(a, ca, b, cb, key) for key in ('v(sn)', 'v(bl)')}
            out['continuous_response_comparison'] = result
            require(all(x['passed'] for x in result.values()), 'Continuous response comparison exceeds frozen threshold')
            return True
        checks.call('continuous_response_comparison', response)
    out['passed'] = not out['errors'] and len(out['checks']) == 3
    out['registered_refinement_comparison_passed'] = out['passed'] and mode in ('segment', 'refinement')
    if out['passed']:
        out['status'] = 'R5_' + mode.upper() + '_COMPARISON_PASSED'
    if output is not None:
        write(output, {'summary': out, 'curves': comparison_curves(a, b, ca, cb) if out['passed'] else {}})
    return out


def comparison_curves(a, b, ca, cb):
    series = [v['curves']['circuit'] for v in (a, ca, b, cb)]
    times = sorted({r['time'] for rows in series for r in rows if r['time'] >= .95e-9})
    values = {k: [old._sample_series(rows, k, times) for rows in series] for k in ('v(sn)', 'v(bl)')}
    rows = []
    for i, t in enumerate(times):
        row = {'time_s': t}
        for key, v in values.items():
            row['a_delta_' + key + '_V'] = v[0][i] - v[1][i]
            row['b_delta_' + key + '_V'] = v[2][i] - v[3][i]
        rows.append(row)
    return {'control-relative-curves': rows}


def write(output, bundle):
    dest = Path(output).resolve()
    require(dest.is_relative_to(OUTPUT.resolve()) and dest != OUTPUT.resolve(), 'Output must be a new r5 runtime child')
    dest.mkdir(parents=True, exist_ok=False)
    summary = bundle['summary']; name = 'comparison.json' if summary['schema'].endswith('-comparison') else 'audit.json'
    (dest / name).write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    curves = dict(bundle.get('curves', {}))
    if bundle.get('native_curves'):
        curves['native-field-curves'] = bundle['native_curves']
    for label, rows in curves.items():
        require(re.fullmatch(r'[A-Za-z0-9_-]+', label), 'Unsafe curve label')
        if rows:
            with (dest / (label + '.csv')).open('x', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('audit'); a.add_argument('run', type=Path); a.add_argument('--project', type=Path); a.add_argument('--field-audit', type=Path)
    a.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('compare')
    for role in ('a', 'b', 'ca', 'cb'):
        p.add_argument('--' + role, required=True, help='Key in evidence registry')
    p.add_argument('--registry', type=Path, required=True); p.add_argument('--mode', choices=('equivalent', 'segment', 'refinement'), required=True)
    p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'audit':
        bundle = load(args.run, args.project, args.field_audit); write(args.output, bundle); result = bundle['summary']
    else:
        registry = old.json_load(args.registry.read_bytes()); cache = {}
        def get(key):
            if key not in cache:
                row = registry['runs'][key]
                if row.get('field_audit_sha256'):
                    require(old.sha_file(Path(row['field_audit'])) == row['field_audit_sha256'], 'Registry field report changed')
                value = load(row['run'], row.get('project'), row.get('field_audit'))
                expected = row['role']; require([value['parameters']['case_id'], value['parameters']['stored_bit'],
                    canonical_matching(value)['variant']] == expected, 'Registry role differs from actual input')
                cache[key] = value
            return cache[key]
        result = compare(*(get(getattr(args, k)) for k in ('a', 'b', 'ca', 'cb')), args.mode, args.output)
    print(json.dumps({k: result.get(k) for k in ('passed', 'status', 'errors')}, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
