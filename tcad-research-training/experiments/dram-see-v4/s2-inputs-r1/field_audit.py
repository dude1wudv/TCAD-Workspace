"""Read-only S2 full-frame source audit. No native launcher or synthetic receipt.

`measurements_metrics` and `index_frames` are pure offline calculations and cannot
grant native qualification. `audit_native` requires independently revalidated,
released original solver/extractor archives and their real execution receipts.
"""
import argparse
import csv
import io
import json
import math
from pathlib import Path
import re
import tarfile

HERE = Path(__file__).resolve().parent


def _module(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), result.__dict__)
    return result


A = _module(HERE/'alpha.py', '_s2_alpha_audit')
OLD = _module(HERE.parent/'source-field-audit-3d-r1/audit_fields.py', '_s2_original_reference_audit')
PRIOR = OLD.prior
require, sha, Archive = A.require, OLD.sha, OLD.Archive
read_json = OLD.read_json
FIELDS = A.field_contract()['native_fields']
SCOPES = ['SILICON_NO_WINDOW']+list(A.ROIS)
LEGACY = 'IntegrSemiconductor HeavyIonGeneration'
FRAME = re.compile(r'source_window[A-Za-z0-9_.-]*\.tdr')


def finite(value, label):
    value = float(value)
    require(math.isfinite(value), 'Nonfinite '+label)
    return value


def validate_spec(spec):
    expected = A.source_spec(spec.get('case'), spec.get('stored_bit'), spec.get('numerical_variant'))
    require(spec == expected, 'Source specification differs from frozen S2/bit/variant contract')
    return expected


def clean_source_times(raw_rows):
    """Keep accepted endpoint before repeated segment initial state; never fill G."""
    require(raw_rows and 'time' in raw_rows[0], 'Missing complete source PLT rows')
    fields = [key for key in raw_rows[0] if key.endswith('HeavyIonGeneration')]
    result, duplicate_count = [], 0
    for row in raw_rows:
        require(set(row) == set(raw_rows[0]) and all(math.isfinite(float(v)) for v in row.values()), 'Nonfinite/inconsistent PLT columns')
        if result:
            require(row['time'] >= result[-1]['time'], 'PLT time rollback')
            if row['time'] == result[-1]['time']:
                require(all(row[key] == result[-1][key] for key in fields), 'Generation changes at duplicate PLT timestamp')
                duplicate_count += 1
                continue
        result.append(row)
    return result, dict(raw_PLT_rows=len(raw_rows), duplicate_segment_initial_rows=duplicate_count,
                        duplicate_rule='strictly equal time and all native generation columns; retain accepted endpoint')


def index_frames(log, rows, files, spec):
    """Bind all accepted BE intervals to precise PLT and source-window TDR writes.

    Log tokens are compared at their printed precision using the frozen prior
    helper. TDR file sequence never defines time. Every accepted interval in the
    full 0..25 ns PLT must have a successful, unrejected BE log step.
    """
    validate_spec(spec)
    require(files and len(files) == len(set(files)) and all(FRAME.fullmatch(f) for f in files), 'Invalid/duplicate/missing native frame names')
    require(len(rows) >= 2 and all('time' in r and all(math.isfinite(float(v)) for v in r.values()) for r in rows), 'Missing/nonfinite complete PLT')
    require(abs(rows[0]['time']) <= 1e-18 and abs(rows[-1]['time']-25e-9) <= 1e-18, 'PLT must cover complete 0..25 ns')
    intervals = [(i, a['time'], b['time']) for i, (a, b) in enumerate(zip(rows, rows[1:]), 1)]
    require(all(b > a for _, a, b in intervals), 'PLT accepted times are not strictly increasing')
    steps, step = [], None
    for line_number, line in enumerate(log.splitlines(), 1):
        match = PRIOR.BE.match(line)
        if match:
            if step is not None:
                steps.append(step)
            step = dict(tokens=match.groups(), BE_log_line=line_number, successful=False, rejected=False, writes=[])
        if step is not None:
            if 'Error smaller than 1' in line or 'Rhs smaller than' in line:
                step['successful'] = True
            if any(token in line for token in ("Newton didn't converge", 'time step rejected', 'Time step rejected')):
                step['rejected'] = True
        match = PRIOR.WRITING.match(line)
        if match and FRAME.fullmatch(match[1]):
            require(step is not None, 'Source-window TDR lacks BE step')
            step['writes'].append((match[1], line_number))
    if step is not None:
        steps.append(step)
    accepted, rejected, found = {}, [], {}
    for step in steps:
        if not step['successful'] or step['rejected']:
            require(not step['writes'], 'Rejected/unconverged BE step wrote source field')
            rejected.append({k: v for k, v in step.items() if k != 'writes'})
            continue
        start, end, delta = step['tokens']
        candidates = [(i, a, b) for i, a, b in intervals if PRIOR.printed_match(a, start) and
                      PRIOR.printed_match(b, end) and PRIOR.printed_match(b-a, delta)]
        require(len(candidates) == 1, 'Successful BE log step/precise PLT mapping is absent or ambiguous')
        i, a, b = candidates[0]
        require(i not in accepted, 'Multiple successful log steps map to one accepted interval')
        accepted[i] = dict(accepted_index=i, start_s=a, end_s=b, dt_s=b-a, BE_log_line=step['BE_log_line'])
        for name, line_number in step['writes']:
            require(name in files and name not in found, 'Unarchived or duplicate source-window TDR write')
            found[name] = dict(accepted[i], source_file=name, writing_log_line=line_number,
                               direct_TDR_timestamp_verified=False,
                               binding='original Writing record + precise PLT accepted interval + archived TDR hash')
    require(set(accepted) == {i for i, _, _ in intervals}, 'Full accepted BE log/PLT sequence has missing intervals')
    require(set(found) == set(files), 'Missing real TDR Writing record')
    indexes = [frame['accepted_index'] for frame in found.values()]
    require(len(indexes) == len(set(indexes)), 'Two source-window TDRs refer to one accepted interval')
    lo, hi = A.WINDOW
    eps = A.TOL['final_time_abs_s']
    ordered = sorted(found.values(), key=lambda f: f['accepted_index'])
    boundary = [f for f in ordered if abs(f['end_s']-lo) <= eps]
    frames = [f for f in ordered if f not in boundary]
    expected = {i for i, a, b in intervals if a >= lo-eps and b <= hi+eps and b > lo+eps}
    require(len(boundary) == 1, 'Source-window initial bracketing frame is missing or duplicated')
    require({f['accepted_index'] for f in frames} == expected and expected, 'Missing/extra source-window accepted frame')
    require(abs(frames[0]['start_s']-lo) <= eps and abs(frames[-1]['end_s']-hi) <= eps, 'BE field coverage does not close source window')
    require(all(f['dt_s'] <= spec['source_max_step_s']+eps for f in frames), 'Source-window accepted step exceeds frozen maximum')
    return dict(frames=frames, boundary_frames=boundary, rejected_log_steps=rejected,
                accepted_BE_count=len(accepted), complete_PLT_rows=len(rows))


def parse_measurements(raw, files, spec):
    validate_spec(spec)
    result = {name: {} for name in files}
    reader = csv.DictReader(io.StringIO(raw))
    require(reader.fieldnames == ['source_file', 'field', 'native_field', 'scope', 'operation', 'raw_value', 'command_status'], 'Unknown measurement CSV schema')
    for row in reader:
        require(None not in row and all(v is not None for v in row.values()), 'Malformed measurement row')
        name, role, scope, operation = [row[k] for k in ('source_file', 'field', 'scope', 'operation')]
        require(name in result and row['command_status'] == 'OK', 'Unknown frame or failed native command')
        if operation in ('remove_plots', 'remove_datasets'):
            continue
        if operation == 'integral':
            require(role in FIELDS and scope in SCOPES and row['native_field'] == FIELDS[role], 'Wrong native field/scope identity')
            key = role, scope
        else:
            require(operation in ('-min', '-max') and role in ('X', 'Y', 'Z') and row['native_field'] == role and scope == 'SILICON_NO_WINDOW', 'Unknown native measurement operation')
            key = role, operation
        require(key not in result[name], 'Duplicate native measurement')
        value = finite(row['raw_value'], 'native measurement')
        if role in ('G', 'ONE'):
            require(value >= 0, 'Negative native generation/volume')
        result[name][key] = value
    base = {('ONE', scope) for scope in SCOPES} | {(axis, operation) for axis in 'XYZ' for operation in ('-min', '-max')}
    active = {(role, scope) for role in ('G', 'XG', 'YG', 'ZG') for scope in SCOPES}
    for name, values in result.items():
        require(set(values) == base | active or (spec['case'] in ('A0', 'Z') and set(values) == base), 'Missing generation/moment/geometry observations: '+name)
    return result


def verify_inventory_metadata(inventory_raw, metadata_raw, files, values):
    inventory = csv.DictReader(io.StringIO(inventory_raw))
    require(inventory.fieldnames == ['source_file', 'dataset', 'object_type', 'native_name'], 'Unknown native inventory schema')
    fields = {name: [] for name in files}
    for row in inventory:
        require(row['source_file'] in fields, 'Native inventory contains an unknown TDR')
        if row['object_type'] == 'field':
            fields[row['source_file']].append(row['native_name'])
    metadata = csv.DictReader(io.StringIO(metadata_raw))
    require(metadata.fieldnames == ['source_file', 'property', 'raw_value', 'command_status'], 'Unknown native metadata schema')
    observed = {name: {} for name in files}
    for row in metadata:
        name, key = row['source_file'], row['property']
        require(name in observed and row['command_status'] == 'OK' and key not in observed[name], 'Failed or duplicate native state metadata')
        observed[name][key] = row['raw_value']
    for name in files:
        require(all(fields[name].count(axis) == 1 for axis in 'XYZ') and fields[name].count('HeavyIonGeneration') <= 1, 'Ambiguous native coordinate/source inventory')
        present = ('G', 'SILICON_NO_WINDOW') in values[name]
        require((fields[name].count('HeavyIonGeneration') == 1) == present, 'Measured G presence differs from native field inventory')
        meta = observed[name]
        require(set(meta) == {'state_names', 'current_state', 'current_state_index', 'generation_evidence'}, 'Incomplete native state metadata')
        # The installed API returns state names, not a reliable physical time.
        require(meta['state_names'].strip() == 'state_0' and meta['current_state_index'].strip() == '1', 'Multiple/ambiguous native TDR states')
        require(meta['generation_evidence'] == ('observed_native_field' if present else 'structural_zero_not_measured_zero'), 'Missing-zero semantics differs from native inventory')
    return dict(frames=len(files), direct_TDR_timestamp_verified=False,
                time_binding='original Writing/PLT accepted interval, preserved TDR hashes')


def measurements_metrics(mapping, values, rows, spec, reference):
    """Pure numerical gates only; always is_tcad_result=False, native_qualified=False."""
    validate_spec(spec)
    frames = mapping['frames']
    all_frames = frames+mapping['boundary_frames']
    require(set(values) == {f['source_file'] for f in all_frames}, 'Frame/measurement inventory differs')
    failures, geometry = [], {}
    def gate(ok, message):
        if not ok:
            failures.append(message)
    for scope in SCOPES:
        roi = 'Total' if scope == 'SILICON_NO_WINDOW' else scope
        expected = reference['rois'][roi]['volume_um3']
        observations = [values[f['source_file']]['ONE', scope] for f in all_frames]
        gate(all(abs(v-expected) <= .05*expected+1e-14 for v in observations), 'Actual Si volume differs: '+scope)
        geometry[scope] = dict(expected_um3=expected, min_um3=min(observations), max_um3=max(observations))
    for axis, i in zip('XYZ', range(3)):
        for operation, target in (('-min', A.DOMAIN[i]), ('-max', A.DOMAIN[i+3])):
            gate(all(abs(values[f['source_file']][axis, operation]-target) <= .002 for f in all_frames), 'Actual Si extent differs: '+axis+operation)
    for part in A.PARTITIONS:
        gate(all(abs(math.fsum(values[f['source_file']]['ONE', roi] for roi in part)-values[f['source_file']]['ONE', 'SILICON_NO_WINDOW']) <= .05*reference['expected_silicon_volume_um3'] for f in all_frames), 'Native Si volume partition differs')
    out = dict(schema='s2-source-numerical-gates-r1', is_tcad_result=False, native_qualified=False,
               passed=False, stored_bit=spec['stored_bit'], source_case=spec['case'], numerical_variant=spec['numerical_variant'],
               volume_diagnostics=geometry, failures=failures)
    if spec['case'] in ('A0', 'Z'):
        missing = [f['source_file'] for f in all_frames if ('G', 'SILICON_NO_WINDOW') not in values[f['source_file']]]
        for f in all_frames:
            v = values[f['source_file']]
            if ('G', 'SILICON_NO_WINDOW') in v:
                gate(all(v[role, scope] == 0. for role in ('G', 'XG', 'YG', 'ZG') for scope in SCOPES), 'A0/Z measured native source is nonzero')
        source_fields = [key for key in rows[0] if key.endswith('HeavyIonGeneration')]
        gate(all(row[key] == 0. for row in rows for key in source_fields), 'A0/Z native PLT source is nonzero')
        out['zero_source'] = dict(structural_zero=True, missing_generation_frames=missing,
                                  generation_evidence='structural_zero_not_measured_zero' if missing else 'observed_native_zero_all_frames',
                                  measured_window_charge_fC=None if missing else 0.,
                                  native_zero_observed_all_frames=not missing)
        out['passed'] = not failures
        return out
    require(all((role, scope) in v for v in values.values() for role in FIELDS for scope in SCOPES), 'Missing nonzero native source fields')
    require(all(LEGACY in row and row[LEGACY] >= 0 for row in rows), 'Missing/negative native PLT generation')
    amp = spec['amplitude']
    q = {scope: math.fsum(values[f['source_file']]['G', scope]*f['dt_s'] for f in frames)*A.CONVERSION for scope in SCOPES}
    target = reference['expected_window_charge_fC']*amp
    total = q['SILICON_NO_WINDOW']
    require(target > 0 and total > 0, 'Expected or measured active source is empty')
    gate(abs(total-target) <= .05*target, 'Native source total exceeds 5%')
    reference_peak = max(reference['domain_charge_fC']*amp*A.step_average(f['start_s'], f['end_s'], A.T0, A.SIGMA) for f in frames)
    gate(abs(q['Total']-total) <= .05*target and
         all(abs(values[f['source_file']]['G', 'Total']-values[f['source_file']]['G', 'SILICON_NO_WINDOW'])*A.CONVERSION <= .05*reference_peak for f in frames),
         'Total window differs from unwindowed silicon generation')
    selected = {f['accepted_index'] for f in frames}
    inside = math.fsum(rows[i][LEGACY]*(rows[i]['time']-rows[i-1]['time']) for i in selected)*A.CONVERSION
    full = math.fsum(b[LEGACY]*(b['time']-a['time']) for a, b in zip(rows, rows[1:]))*A.CONVERSION
    gate(abs(inside-total) <= .05*target, 'TDR and exact-time PLT charge disagree')
    gate(abs(full-reference['domain_charge_fC']*amp) <= .05*reference['domain_charge_fC']*amp, 'Full 0..25 ns PLT source charge differs')
    out['charge'] = dict(measured_window_fC=total, expected_window_fC=target,
                        PLT_window_fC=inside, PLT_full_fC=full, PLT_outside_window_fC=full-inside,
                        no_clipping_renormalization=True, by_scope_fC=q)
    roi_results = {}
    for roi, expected in reference['rois'].items():
        scope = 'SILICON_NO_WINDOW' if roi == 'Total' else roi
        fraction = expected['q_fC']/reference['domain_charge_fC']
        gate(abs(q[scope]/total-fraction) <= .05, 'Native ROI fraction differs: '+roi)
        rates = [expected['q_fC']*amp*A.step_average(f['start_s'], f['end_s'], A.T0, A.SIGMA) for f in frames]
        measured = [values[f['source_file']]['G', scope]*A.CONVERSION for f in frames]
        peak = max(rates)
        waveform = max(abs(x-y) for x, y in zip(rates, measured))/peak if peak else None
        # The denominator is independently predicted peak, never selected from observations.
        gate(waveform is not None and waveform <= .05, 'Every-frame BE-average waveform exceeds 5%: '+roi)
        result = dict(expected_fraction=fraction, measured_fraction=q[scope]/total,
                      BE_average_peak_relative_error=waveform, active_centroid_frames=0)
        if fraction >= .001:
            errors = [0., 0., 0.]
            for f, rate, measured_rate in zip(frames, rates, measured):
                if rate < peak*.001:
                    continue
                v = values[f['source_file']]
                gate(measured_rate > 0, 'Predicted active frame has no observed source: '+roi)
                if measured_rate <= 0:
                    continue
                result['active_centroid_frames'] += 1
                for i, axis in enumerate('XYZ'):
                    errors[i] = max(errors[i], abs(v[axis+'G', scope]/v['G', scope]-expected['centroid_um'][i]))
            gate(result['active_centroid_frames'] > 0 and max(errors) <= .002, 'Truncated-Si centroid exceeds 2 nm: '+roi)
            mass = math.fsum(rate*f['dt_s'] for rate, f in zip(measured, frames))
            tc = math.fsum(rate*f['dt_s']*(f['start_s']+f['end_s'])/2 for rate, f in zip(measured, frames))/mass if mass else None
            # Same accepted-interval midpoint convention on both sides, plus analytic center.
            wanted_mass = math.fsum(rate*f['dt_s'] for rate, f in zip(rates, frames))
            wanted_tc = math.fsum(rate*f['dt_s']*(f['start_s']+f['end_s'])/2 for rate, f in zip(rates, frames))/wanted_mass
            gate(tc is not None and abs(tc-wanted_tc) <= .04e-12 and abs(tc-A.T0) <= .04e-12, 'Native time centroid exceeds 0.04 ps: '+roi)
            result.update(centroid_max_abs_error_um=errors, time_centroid_s=tc, expected_BE_time_centroid_s=wanted_tc)
        roi_results[roi] = result
    out['rois'] = roi_results
    full_peak = max(values[f['source_file']]['G', 'SILICON_NO_WINDOW'] for f in frames)
    for part in A.PARTITIONS:
        charge_error = abs(math.fsum(q[roi] for roi in part)-total)/total
        waveform_error = max(abs(math.fsum(values[f['source_file']]['G', roi] for roi in part)-values[f['source_file']]['G', 'SILICON_NO_WINDOW']) for f in frames)/full_peak
        gate(max(charge_error, waveform_error) <= .05, 'Native source partition fails charge/waveform closure')
    out['passed'] = not failures
    return out


def _receipt(path, schema):
    require(Path(path).is_file() and not Path(path).is_symlink(), 'Native receipt missing; offline or synthetic data cannot qualify: '+str(path))
    value = read_json(Path(path).read_bytes())
    require(value.get('schema') == schema and value.get('origin') == 'native_pipeline' and value.get('synthetic') is False, 'Unknown/non-native receipt')
    for key in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code'):
        require(type(value.get(key)) is int and value[key] == 0, 'Native receipt has unknown/nonzero '+key)
    return value


def _archive_checked(folder, record, manifest_name):
    folder = Path(folder).resolve()
    manifest = read_json((folder/manifest_name).read_bytes())
    require(sha(folder/manifest_name) == record['manifest_sha256'], 'Original manifest hash differs from native receipt')
    require(sha(folder/'results.tar') == record['archive_sha256'], 'Original archive hash differs from native receipt')
    require(manifest.get('state') in ('COLLECTED', 'COLLECTED_PENDING_AUDIT'), 'Native manifest is not complete')
    require(type(manifest.get('ssh_exit_code')) is int and manifest['ssh_exit_code'] == 0, 'Original SSH outcome not integer zero')
    require(manifest.get('results_sha256', manifest.get('archive_sha256')) == record['archive_sha256'], 'Manifest/archive binding differs')
    hashes = manifest.get('input_sha256')
    require(isinstance(hashes, dict) and hashes, 'Missing frozen native inputs')
    for name, digest in hashes.items():
        require(OLD.old.safe_name(name) == name and re.fullmatch(r'[0-9a-f]{64}', digest or ''), 'Unsafe/unhashed frozen input')
    return folder, manifest, hashes


def _check_execution(archive, native_tool, record):
    require(archive.read('exit-code.txt').strip() == b'0', 'Raw remote native operation exit is nonzero/unknown')
    require(archive.read(native_tool+'-exit-code.txt').strip() == b'0', 'Raw native tool exit is nonzero/unknown')
    require(record.get(native_tool+'_exit_code') == 0 and type(record.get(native_tool+'_exit_code')) is int, 'Native tool receipt exit is nonzero/unknown')
    require(record.get('threads') == 1 and record.get('cpu_count') == 1, 'Native receipt violates serial single-core/thread contract')
    affinity = archive.read('affinity.txt').decode().strip()
    require(re.fullmatch(r'[0-9]+', affinity), 'Native affinity must identify exactly one CPU')
    require(affinity == str(record.get('cpu_affinity')), 'Native affinity differs from receipt')
    require(record.get('shared_lock_acquired') is True and record.get('scheduler') == 'root', 'Missing unique scheduler/shared lock evidence')
    require(record.get('shared_lock_evidence_file') in archive.members, 'Missing raw shared-lock evidence')
    require(archive.digest(record['shared_lock_evidence_file']) == record.get('shared_lock_evidence_sha256'), 'Shared-lock raw evidence hash differs')


def audit_native(solver, extraction, package):
    """Read only complete native evidence; current review inputs necessarily refuse.

    The native pipeline must supply the described receipts after execution. This
    function deliberately never creates them and cannot consume a synthetic unit
    fixture as a qualification result.
    """
    out = dict(schema='s2-native-field-audit-r1', passed=False, native_qualified=False,
               overall_source_interface_passed=False, circuit_audit_passed=False,
               status='REFUSED_MISSING_OR_INVALID_NATIVE_EVIDENCE', errors=[], native_jobs_started=0)
    try:
        solver, extraction, package = map(Path, (solver, extraction, package))
        sr = _receipt(solver/'native-source-receipt.json', 's2-native-source-receipt-r1')
        er = _receipt(extraction/'field-extraction-record.json', 's2-native-field-receipt-r1')
        OLD.check_dependencies()
        solver, sm, sh = _archive_checked(solver, sr, 'manifest.json')
        extraction, em, eh = _archive_checked(extraction, er, 'operation.json')
        require(sr['run_id'] == solver.name == sm['run_id'] and er['solver_run_id'] == sr['run_id'], 'Native run identity differs')
        require(er['solver_archive_sha256'] == sr['archive_sha256'] and er['solver_manifest_sha256'] == sr['manifest_sha256'], 'Extractor/source evidence binding differs')
        with Archive(solver/'results.tar') as sa, Archive(extraction/'results.tar') as ea:
            for archive, hashes in ((sa, sh), (ea, eh)):
                for name, digest in hashes.items():
                    require(archive.digest(name) == digest, 'Original archived input changed: '+name)
            with Archive(solver/'inputs.tar') as inputs:
                require(set(inputs.members) == set(sh), 'Original frozen inputs inventory differs')
                require(all(inputs.digest(name) == digest for name, digest in sh.items()), 'Original frozen input bytes differ')
            _check_execution(sa, 'sdevice', sr)
            _check_execution(ea, 'svisual', er)
            require('ENGINEERING_RUN_COMPLETED' in sa.read('execution.log').decode().splitlines(), 'Missing original solver completion sentinel')
            require('FIELD_AUDIT_COMPLETED mandatory_errors=0' in ea.read('svisual.log').decode().splitlines(), 'Missing original extractor completion sentinel')
            require('NATIVE_FIELD_POSTPROCESS_COMPLETED' in ea.read('execution.log').decode().splitlines(), 'Missing original extraction operation completion sentinel')
            release = read_json(sa.read('execution-release.json'))
            require(release.get('status') == 'RELEASED' and release.get('execution_enabled') is True and release.get('explicit_native_authorization') is True, 'Review-only or unauthorized input cannot qualify')
            require(release.get('scheduler') == 'root' and release.get('threads') == 1 and release.get('cpu_count') == 1, 'Release violates single scheduler/core/thread contract')
            require(release.get('budget_id') and release.get('budget_reservation_id') and release.get('budget_ledger_sha256'), 'Missing immutable budget/release reference')
            spec = read_json(sa.read('source-spec.json'))
            validate_spec(spec)
            require(sr['source_spec'] == er['source_spec'] == spec, 'Native bit/case/variant binding differs')
            require(sr.get('sdevice_version') == 'W-2024.09' and er.get('svisual_version') == 'W-2024.09', 'Native tool edition differs from installed-manual contract')
            device_text = sa.read(sr['device_input_file']).decode()
            if spec['case'] == 'A0':
                require(re.search(r'\bHeavyIon\s*\(', device_text) is None, 'A0 archived device activates a particle source')
                require(sr.get('activated_source_include_files') == [], 'A0 has activated source include')
            else:
                prefix = '' if spec['case'] == 'Aalpha' else spec['case']+'.'
                expected_inputs = [prefix+'heavyion.physics.inc', prefix+'source.par']
                require(sr.get('activated_source_include_files') == expected_inputs, 'Activated source include binding differs')
                require(all(sa.digest(name) == sha(package/name) for name in expected_inputs), 'Actual source table/parameters differ from reviewed source case')
            for name in ('source-contract.json', 'field-contract.json', 'alpha-reference.json', 'alpha-profile.csv'):
                require(sa.digest(name) == sha(package/name), 'Source input differs from reviewed package: '+name)
            require(ea.digest('field-contract.json') == sha(package/'field-contract.json'), 'Extractor field contract differs')
            require(ea.digest('extract_fields.tcl') == sha(HERE/'extract_fields.tcl') == sha(package/'extract_fields.tcl'), 'Executed extractor code differs')
            require(ea.digest('windows.tcldata') == sha(package/'windows.tcldata'), 'Native windows differ from reviewed Si geometry')
            source_contract = read_json(sa.read('source-contract.json'))
            for name, digest in source_contract['dependency_sha256'].items():
                require(sha(A.ROOT/name) == digest, 'Frozen alpha/reference dependency changed: '+name)
            require(sr.get('geometry_mask_bound') is True and sr.get('geometry_manifest_sha256') == sa.digest('geometry-manifest.json'), 'Actual geometry mask not bound to source contract')
            require(sr.get('mesh_sha256') == sa.digest(sr['mesh_file']), 'Native mesh identity differs')
            files = ea.read('tdr-files.txt').decode().splitlines()
            expected_files = {name for name in sa.members if FRAME.fullmatch(name)}
            require(set(files) == expected_files and len(files) == len(expected_files), 'Extraction omitted/duplicated original source-window TDRs')
            require(not any(name.lower().endswith('.tdr') for name in ea.members), 'Extractor copied original TDR payload')
            hashes = {name: sa.digest(name) for name in files}
            sizes = {name: sa.members[name].size for name in files}
            require(ea.read('tdr-sha256.txt').decode() == ''.join(hashes[name]+'  '+name+'\n' for name in files), 'Original TDR hash inventory differs')
            directory = ea.read('source-directory.txt').decode().strip()
            require(re.fullmatch(r'(/[A-Za-z0-9_.-]+)+', directory) and directory == sr['remote_directory'] == sm['remote_directory'], 'Source original directory differs')
            require(ea.read('source-case.txt').decode().strip() == spec['case'], 'Extractor source case differs')
            reference_checks = OLD.verify_reference_checks(ea.read('source-reference-checks.csv').decode(), files, hashes, sizes, directory)
            raw = ea.read('field-measurements.csv').decode()
            inventory_raw = ea.read('field-inventory.csv').decode()
            PRIOR.check_cleanup(raw, files, 'exact_deleted_object_name', inventory_raw)
            status = dict(line.split('=', 1) for line in ea.read('diagnostic-status.txt').decode().splitlines() if '=' in line)
            require(status.get('schema') == 's2-native-field-extraction-r1' and status.get('dimension') == '3' and status.get('integration') == 'volume_um3' and status.get('mandatory_command_errors') == '0', 'Native extractor status invalid')
            require(status.get('files_requested') == status.get('files_completed') == str(len(files)), 'Native extractor frame count differs')
            require(status.get('reference_mode') == 'referenced_original_tdr_not_copied' and status.get('memory_release') == 'plot_then_dataset_per_frame' and status.get('cleanup_success') == 'exact_deleted_object_name', 'Native original-reference/cleanup mode differs')
            native_log = sa.read(sr['transient_log_file']).decode()
            require('Sentaurus Device simulation finished' in native_log, 'Original native solver completion marker missing')
            _, raw_rows = OLD.old.parse_plt(sa.read(sr['device_plt_file']).decode())
            rows, plt_duplicates = clean_source_times(raw_rows)
            mapping = index_frames(native_log, rows, files, spec)
            mapping['PLT_duplicate_handling'] = plt_duplicates
            values = parse_measurements(raw, files, spec)
            metadata_check = verify_inventory_metadata(inventory_raw, ea.read('tdr-state-metadata.csv').decode(), files, values)
            reference = read_json((package/'alpha-reference.json').read_bytes())
            reproduced = A.source_expected(source_contract['model_snapshot'])
            reproduced['cad_binding'] = A.cad_binding(source_contract['model_snapshot'], reproduced)
            reproduced['cad_discretization_bound'] = True
            require(reference == reproduced, 'Saved alpha expectation differs from independently recalculated Si/table/time reference')
            metrics = measurements_metrics(mapping, values, rows, spec, reference)
            require(metrics['passed'], '; '.join(metrics['failures']))
            # Recheck both immutable archives after all reads, not just receipt creation.
            require(sha(solver/'results.tar') == sr['archive_sha256'] and sha(solver/'manifest.json') == sr['manifest_sha256'], 'Solver evidence changed during audit')
            require(sha(extraction/'results.tar') == er['archive_sha256'] and sha(extraction/'operation.json') == er['manifest_sha256'], 'Extractor evidence changed during audit')
            out.update(passed=True, native_qualified=False, status='NATIVE_FIELD_GATES_PASSED_MATCHED_A0_CIRCUIT_AND_REFINEMENT_STILL_REQUIRED',
                       field_measurements_passed=spec['case'] not in ('A0', 'Z'), numerical_gates=metrics,
                       mapping=mapping, metadata_check=metadata_check, original_reference_checks=reference_checks,
                       native_evidence_sha256=dict(solver_archive=sr['archive_sha256'], extraction_archive=er['archive_sha256']))
    except (ValueError, OSError, KeyError, TypeError, IndexError, ZeroDivisionError, UnicodeError, tarfile.TarError) as exc:
        out['errors'].append(str(exc))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--solver', required=True, type=Path)
    parser.add_argument('--extraction', required=True, type=Path)
    parser.add_argument('--package', required=True, type=Path)
    args = parser.parse_args()
    result = audit_native(args.solver, args.extraction, args.package)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
