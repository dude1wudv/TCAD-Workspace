"""Read-only 3D native-field audit and explicit preparation; never dispatches jobs.

Preparation writes only a new requested operation-input folder. Audit reads original
solver/operation archives; output, if requested, is append-only in this revision's
runtime directory. Synthetic unit fixtures are not experimental evidence.
"""
import argparse
import csv
import importlib.util
import io
import json
import math
from pathlib import Path
import re
import shlex

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUTPUT = ROOT / 'local_runtime/dram-see-v4/source-field-audit-3d-r1'
INPUTS = ROOT / 'local_runtime/dram-see-v4/transport-probe/inputs'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), obj.__dict__)
    return obj


prior = module(HERE.parent / 'source-field-audit-r2/audit_fields.py', '_field3d_predecessor')
old = prior.old
require, Archive, sha, read_json = old.require, old.Archive, old.sha_file, old.json_load
C = read_json((HERE / 'field_contract.json').read_bytes())
T = C['audit_tolerances']
ROLES = C['native_fields']
SCOPES = ['SILICON_NO_WINDOW'] + list(C['rois_um6'])
CONVERSION = C['conversion']['um3_to_cm3'] * C['conversion']['elementary_charge_C'] * C['conversion']['C_to_fC']
LEGACY = 'IntegrSemiconductor HeavyIonGeneration'
FRAME_RE = re.compile(r'gstep_[0-9]+_access_des\.tdr')
NATIVE_OUTPUTS = {'field-measurements.csv', 'field-inventory.csv', 'tdr-state-metadata.csv',
                  'diagnostic-status.txt', 'svisual.log', 'svisual-exit-code.txt'}


def builder():
    return module(HERE.parent / 'source-interface-3d-r1/build_interface.py', '_field3d_builder')


def check_dependencies():
    for name, digest in C['frozen_library_sha256'].items():
        require(sha(ROOT/name) == digest, 'Frozen read-only helper changed: '+name)
    document = C['native_api_evidence']
    require(sha(ROOT/document['private_document']) == document['sha256'], 'Installed API guide changed')
    return True


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def finite(value, name):
    value = float(value)
    require(math.isfinite(value), 'Nonfinite ' + name)
    return value


def index_frames(log, rows, files):
    # This helper is coordinate-independent. Freeze its relevant contract rather
    # than changing its module globals or constructing times from filenames.
    require(C['window_s'] == prior.C['window_s'] and T['final_time_abs_s'] == prior.T['final_time_abs_s'],
            'Accepted-frame helper time contract changed')
    result = prior.index_frames(log, rows, files, full=True)
    require(all(item['dt_s'] <= 5e-13 + T['final_time_abs_s'] for item in result[0]),
            'Injection-window accepted time step exceeds frozen 0.5 ps')
    return result


def validate_spec(spec):
    require(spec.get('case_id') in ('A0', 'A1') and spec.get('synthetic') is True,
            'This revision supports only artificial A0/A1, not real events')
    tracks = spec.get('tracks')
    require(isinstance(tracks, list), 'Missing track list')
    require(len(tracks) == (0 if spec['case_id'] == 'A0' else 1), 'Wrong source count or duplicate deposition')
    require(spec.get('source_total_fC') == (0 if not tracks else 1), 'Wrong source total')
    if tracks:
        tr = tracks[0]
        expected = {'start_um': [.425, .3, 0.], 'direction': [0., 1., 0.], 'length_um': .6,
                    'q_fC': 1., 'wt_hi_um': .03, 'time_s': 1e-9, 's_hi_s': 2e-12}
        require(all(tr.get(k) == v for k, v in expected.items()), 'A1 differs from frozen spatial/time kernel')
        require(tr.get('track_id') is not None and tr.get('source_name'), 'Missing source identity')
        require(math.isclose(tr.get('let_pC_per_um', -1) * .6 * 1000, 1., rel_tol=1e-12),
                'Source charge/length closure failed')
    return True


def temporal_mass(a, b, time, sigma):
    """Independent normal-CDF integral of native sigma=s_hi, truncated at t=0."""
    require(sigma > 0 and b >= a, 'Invalid temporal interval')
    a = max(0., a)
    if b <= a:
        return 0.
    lo, hi = (a-time)/(math.sqrt(2)*sigma), (b-time)/(math.sqrt(2)*sigma)
    if lo >= 0:
        diff = math.erfc(lo)-math.erfc(hi)
    elif hi <= 0:
        diff = math.erfc(-hi)-math.erfc(-lo)
    else:
        diff = math.erf(hi)-math.erf(lo)
    return diff/(1+math.erf(time/(math.sqrt(2)*sigma)))


def box_moments(track, box):
    """Exact rectangular integral for the frozen y-directed finite line.

    exp(-((x-x0)^2+(z-z0)^2)/w^2)/(pi*w^2) is normalized on the
    transverse plane; longitudinal density is uniform on the finite segment.
    Return fraction and its first moments [um]. No end-cap convolution.
    """
    x, y, z = track['start_um']; width, length = track['wt_hi_um'], track['length_um']
    require(track['direction'] == [0., 1., 0.] and length > 0, 'Unvalidated orientation/point kernel')
    xmin, ymin, zmin, xmax, ymax, zmax = box
    require(xmin < xmax and ymin < ymax and zmin < zmax, 'Invalid 3D box')
    low, high = max(y, ymin), min(y+length, ymax)
    if high <= low:
        return (0., 0., 0., 0.)
    def radial(a, b, center):
        mass = (math.erf((b-center)/width)-math.erf((a-center)/width))/2
        moment = center*mass + width/(2*math.sqrt(math.pi))*(
            math.exp(-((a-center)/width)**2)-math.exp(-((b-center)/width)**2))
        return mass, moment
    fx, mx = radial(xmin, xmax, x); fz, mz = radial(zmin, zmax, z)
    fy = (high-low)/length
    fraction = fx*fy*fz
    return fraction, mx*fy*fz, fraction*(low+high)/2, mz*fy*fx


def offline_proof(spec):
    validate_spec(spec)
    rois = {}
    for roi, box in C['rois_um6'].items():
        terms = []
        for tr in spec['tracks']:
            f, x, y, z = box_moments(tr, box); q = tr['q_fC']
            terms.append(dict(source_name=tr['source_name'], q_fC=q*f,
                              x_moment_fC_um=q*x, y_moment_fC_um=q*y, z_moment_fC_um=q*z))
        rois[roi] = dict(q_fC=math.fsum(t['q_fC'] for t in terms), tracks=terms)
    total = rois['Total']['q_fC']; outside = spec['source_total_fC']-total
    require(outside >= -T['offline_charge_abs_fC'], 'Negative clipped charge')
    residual = total+outside-spec['source_total_fC']
    require(abs(residual) <= max(T['offline_charge_abs_fC'], T['offline_charge_relative']*spec['source_total_fC']),
            'Offline source charge does not close')
    return dict(schema='source-field-audit-3d-r1-independent-oracle', is_tcad_result=False,
                domain_charge_fC=total, outside_domain_fC=outside, residual_fC=residual, rois=rois)


def interval_expected(spec, proof, roi, start, end):
    source = {tr['source_name']: tr for tr in spec['tracks']}
    terms = proof['rois'][roi]['tracks']
    rates = {name: temporal_mass(start, end, tr['time_s'], tr['s_hi_s'])/(end-start)
             for name, tr in source.items()}
    q = math.fsum(term['q_fC']*rates[term['source_name']] for term in terms)
    moments = [math.fsum(term[axis+'_moment_fC_um']*rates[term['source_name']] for term in terms)
               for axis in 'xyz']
    return q, [value/q if q else None for value in moments]


def parse_measurements(raw, files, case):
    result = {name: {} for name in files}
    reader = csv.DictReader(io.StringIO(raw))
    require(reader.fieldnames == ['source_file', 'field', 'native_field', 'scope', 'operation', 'raw_value', 'command_status'],
            'Unknown measurement CSV schema')
    for row in reader:
        require(None not in row and all(v is not None for v in row.values()), 'Malformed measurement row')
        name, role, scope, op = (row[key] for key in ('source_file', 'field', 'scope', 'operation'))
        require(name in result and row['command_status'] == 'OK', 'Unknown frame or failed native command')
        if op not in ('integral', '-min', '-max'):
            require(op in ('remove_plots', 'remove_datasets'), 'Unrecognized measurement operation')
            continue
        if op == 'integral':
            require(role in ROLES and scope in SCOPES and row['native_field'] == ROLES[role], 'Unknown field/scope identity')
            key = (role, scope)
        else:
            require(role in 'XYZ' and row['native_field'] == role and scope == 'SILICON_NO_WINDOW', 'Unknown coordinate diagnostic')
            key = (role, op)
        require(key not in result[name], 'Duplicate native measurement')
        value = finite(row['raw_value'], 'native measurement')
        if role == 'G': require(value >= 0, 'Negative generation')
        if role == 'ONE': require(value > 0, 'Empty native 3D volume')
        result[name][key] = value
    base = {('ONE', scope) for scope in SCOPES} | {(axis, op) for axis in 'XYZ' for op in ('-min', '-max')}
    active = {(role, scope) for role in ('G', 'XG', 'YG', 'ZG') for scope in SCOPES}
    for name, values in result.items():
        require(set(values) == base | active or case == 'A0' and set(values) == base,
                'Missing native field, moment, volume or coordinate: ' + name)
    return result


def summarize_snapshots(index, values):
    rows = []
    for frame in index:
        data = values[frame['source_file']]; g = data.get(('G', 'SILICON_NO_WINDOW'))
        row = dict(frame, generation_evidence='observed_native_field' if g is not None else 'structural_zero_not_measured_zero')
        for role in ROLES:
            for scope in SCOPES:
                row[role+'_'+scope+'_raw'] = data.get((role, scope))
        for axis in 'xyz':
            row['centroid_'+axis+'_um'] = data.get((axis.upper()+'G', 'SILICON_NO_WINDOW'))/g if g else None
        rows.append(row)
    return rows


def full_metrics(index, values, device_rows, spec, out):
    validate_spec(spec); proof = offline_proof(spec); failures = []
    def gate(ok, message):
        if not ok: failures.append(message)
    out['independent_offline_proof'] = proof
    out['volume_conversion_to_fC'] = CONVERSION
    out['volume_diagnostics'] = {}
    for scope in SCOPES:
        roi = 'Total' if scope == 'SILICON_NO_WINDOW' else scope
        box = C['rois_um6'][roi]
        expected = math.prod(box[j+3]-box[j] for j in range(3))
        observed = [v['ONE', scope] for v in values.values()]
        out['volume_diagnostics'][scope] = dict(expected_um3=expected, min_um3=min(observed), max_um3=max(observed))
        gate(max(abs(v-expected) for v in observed) <= T['source_relative']*expected, 'Native 3D volume differs: '+scope)
    bounds = C['rois_um6']['Total']
    for axis, i in zip('XYZ', range(3)):
        for op, wanted in [('-min', bounds[i]), ('-max', bounds[i+3])]:
            gate(all(abs(v[axis, op]-wanted) <= T['centroid_abs_um'] for v in values.values()), 'Native XYZ extent differs: '+axis+op)
    if spec['case_id'] == 'A0':
        observed = [f for f in index if ('G', 'SILICON_NO_WINDOW') in values[f['source_file']]]
        missing = [f['source_file'] for f in index if ('G', 'SILICON_NO_WINDOW') not in values[f['source_file']]]
        for frame in observed:
            v = values[frame['source_file']]
            gate(all(v[role, scope] == 0 for role in ('G', 'XG', 'YG', 'ZG') for scope in SCOPES), 'A0 native generation/moment is nonzero')
        native_keys = [key for key in device_rows[0] if key.endswith('HeavyIonGeneration')]
        gate(all(row[key] == 0 for row in device_rows for key in native_keys), 'A0 PLT generation is nonzero')
        out['zero_source'] = dict(structural_zero=True, native_zero_observed_all_frames=not missing,
            missing_generation_frames=missing, measured_window_charge_fC=0. if not missing else None,
            centroid_x_um=None, centroid_y_um=None, centroid_z_um=None, time_centroid_s=None,
            native_PLT_generation_fields=native_keys, missing_is_never_measured_zero=True)
    else:
        require(all((role, scope) in v for v in values.values() for role in ROLES for scope in SCOPES), 'Missing A1 generation field/moment')
        require(all(LEGACY in row and row[LEGACY] >= 0 for row in device_rows), 'Missing/negative native unwindowed PLT generation')
        q = {scope: math.fsum(values[f['source_file']]['G', scope]*f['dt_s'] for f in index)*CONVERSION for scope in SCOPES}
        lo, hi = C['window_s']; expected = {roi: interval_expected(spec, proof, roi, lo, hi)[0]*(hi-lo) for roi in C['rois_um6']}
        total, target = q['SILICON_NO_WINDOW'], expected['Total']
        require(total > 0 and target > 0, 'A1 native or expected total is zero')
        selected = {f['accepted_index'] for f in index}
        legacy_in = math.fsum(device_rows[i][LEGACY]*(device_rows[i]['time']-device_rows[i-1]['time']) for i in selected)*CONVERSION
        legacy_out = math.fsum(b[LEGACY]*(b['time']-a['time']) for i, (a, b) in enumerate(zip(device_rows, device_rows[1:]), 1) if i not in selected)*CONVERSION
        gate(abs(total-target) <= .05*target, 'TDR generated charge exceeds 5% of precomputed domain/window amount')
        gate(abs(legacy_in+legacy_out-proof['domain_charge_fC']) <= .05*proof['domain_charge_fC'], 'Full PLT charge exceeds 5% of domain amount')
        gate(abs(total-legacy_in) <= .05*target, 'TDR and PLT window charge disagree by >5%')
        out['charge'] = dict(TDR_window_fC=total, TDR_roi_window_fC=q, expected_window_fC=target,
                             legacy_window_fC=legacy_in, legacy_outside_window_fC=legacy_out,
                             domain_target_fC=proof['domain_charge_fC'], clipping_not_renormalized=True)
        out['roi_checks'], out['partitions'] = {}, []
        for roi in C['rois_um6']:
            scope = 'SILICON_NO_WINDOW' if roi == 'Total' else roi
            fraction, wanted_fraction = q[scope]/total, expected[roi]/target
            gate(abs(fraction-wanted_fraction) <= T['roi_fraction_abs'], 'ROI fraction differs: '+roi)
            peak = max(values[f['source_file']]['G', scope] for f in index)
            expected_rates = [interval_expected(spec, proof, roi, f['start_s'], f['end_s'])[0] for f in index]
            observed_rates = [values[f['source_file']]['G', scope]*CONVERSION for f in index]
            expected_peak = max(expected_rates)
            waveform = max(abs(a-b) for a,b in zip(observed_rates,expected_rates))/expected_peak if expected_peak else None
            row = dict(observed_fraction=fraction, expected_fraction=wanted_fraction,
                       BE_interval_average_peak_relative_error=waveform, centroid_max_abs_error_um=None,
                       observed_time_centroid_s=None, expected_time_centroid_s=None)
            if wanted_fraction >= T['active_generation_fraction']:
                gate(waveform is not None and waveform <= T['generation_waveform_relative'], 'BE-average waveform exceeds 5%: '+roi)
                mass = math.fsum(values[f['source_file']]['G', scope]*f['dt_s'] for f in index)
                tc = math.fsum(values[f['source_file']]['G', scope]*f['dt_s']*(f['start_s']+f['end_s'])/2 for f in index)/mass if mass else None
                target_time = spec['tracks'][0]['time_s']
                row.update(observed_time_centroid_s=tc, expected_time_centroid_s=target_time)
                gate(tc is not None and abs(tc-target_time) <= T['time_centroid_abs_s'], 'Time centroid exceeds 0.5ps: '+roi)
                errors = [0., 0., 0.]; count = 0
                for f in index:
                    v = values[f['source_file']]; g = v['G', scope]
                    if peak <= 0 or g < peak*T['active_generation_fraction']: continue
                    rate, center = interval_expected(spec, proof, roi, f['start_s'], f['end_s'])
                    require(rate > 0 and all(c is not None for c in center), 'Observed active frame outside oracle interval')
                    count += 1
                    for i, axis in enumerate('XYZ'):
                        errors[i] = max(errors[i], abs(v[axis+'G', scope]/g-center[i]))
                row.update(centroid_max_abs_error_um=dict(zip('xyz', errors)), active_centroid_frames=count)
                gate(count > 0 and max(errors) <= T['centroid_abs_um'], 'XYZ centroid exceeds 0.01um: '+roi)
            out['roi_checks'][roi] = row
        full_peak = max(values[f['source_file']]['G', 'SILICON_NO_WINDOW'] for f in index)
        for part in C['partitions']:
            charge_error = abs(math.fsum(q[roi] for roi in part)-total)/total
            curve_error = max(abs(math.fsum(values[f['source_file']]['G', roi] for roi in part)-values[f['source_file']]['G', 'SILICON_NO_WINDOW']) for f in index)/full_peak
            out['partitions'].append(dict(rois=part, charge_relative_error=charge_error, curve_relative_error=curve_error))
            gate(max(charge_error, curve_error) <= T['partition_relative'], 'ROI partition does not close')
    out['field_gate_failures'] = failures
    require(not failures, '; '.join(failures))
    return True


def check_builder_archive(archive, project=None):
    b = builder(); c = b.contract()
    require(c['rois_um6'] == C['rois_um6'], 'Builder/field audit ROI definitions differ')
    for key in ('source_relative', 'zero_charge_fC', 'centroid_abs_um', 'roi_fraction_abs',
                'partition_relative', 'time_centroid_abs_s', 'generation_waveform_relative', 'active_generation_fraction'):
        require(c['audit_tolerances'][key] == T[key], 'Builder/field threshold differs: '+key)
    if project is not None: b.check_project(Path(project))
    p = read_json(archive.read('parameters.json')); spec = read_json(archive.read('source-spec.json'))
    validate_spec(spec)
    require(p['case_id'] == spec['case_id'] and p['stored_bit'] == 1, 'Wrong source/state')
    project_name = read_json(archive.read('project.json'))['name']
    expected_files = b.expected_files(spec['case_id'], project_name)
    for name, raw in expected_files.items():
        require(archive.read(name) == raw, 'Complete expected 3D input differs: '+name)
    require(archive.read('source-contract.json') == b.CONTRACT.read_bytes(), 'Frozen 3D source contract changed')
    require(old.encoded(spec) == old.encoded(b.source_spec(spec['case_id'])), 'Frozen 3D source changed')
    require(archive.read('device.cmd').decode('utf-8') == b.render_deck(spec['case_id']), 'Source/circuit deck changed')
    require(archive.read('geometry-contract.json') == (b.HERE/'geometry-contract.json').read_bytes(), 'Shared geometry changed')
    for key, name in [('source_spec_sha256', 'source-spec.json'), ('source_contract_sha256', 'source-contract.json'), ('geometry_sha256', 'geometry.scm')]:
        require(p[key] == archive.digest(name), 'Declared hash differs: '+name)
    im = read_json(archive.read('input-manifest.json'))
    require(im['source_code_sha256'] == b.code_hashes() and p['source_code_sha256'] == b.code_hashes(), 'Builder implementation hash changed')
    require(set(im['files_sha256']) == set(expected_files), 'Incomplete frozen input manifest')
    for name, digest in im['files_sha256'].items(): require(archive.digest(name) == digest, 'Frozen input manifest differs: '+name)
    proof = offline_proof(spec); comparison = b.offline_proof(spec)
    for roi in C['rois_um6']:
        require(abs(comparison['rois'][roi]['q_fC']-proof['rois'][roi]['q_fC']) <= max(T['offline_charge_abs_fC'], T['offline_charge_relative']*spec['source_total_fC']),
                'Independent 3D spatial oracle disagrees: '+roi)
    return p, spec


def source_provenance(run, project=None):
    """Read-only complete original archive and input binding, no new artifacts."""
    check_dependencies()
    run = Path(run).resolve(); out = {}
    manifest = old._manifest(run, out)
    with Archive(run/'results.tar') as archive:
        old._provenance(archive, manifest, run, project, out)
        p, spec = check_builder_archive(archive, project)
        curves = old._curves(archive, out)
        files = sorted(name for name in archive.members if FRAME_RE.fullmatch(name))
        require(files, 'No complete accepted-step TDR family')
        index, boundary = index_frames(archive.read('transient_des.log').decode(errors='replace'), curves['device'], files)
        hashes = {name: archive.digest(name) for name in files}
        out.update(case_id=p['case_id'], frame_count=len(files), active_frame_count=len(index),
                   tdr_sha256=hashes, tdr_bytes={name: archive.members[name].size for name in files},
                   accepted_intervals=index, boundary_frames_not_integrated=boundary,
                   field_contract_sha256=sha(HERE/'field_contract.json'), extractor_sha256=sha(HERE/'extract_fields.tcl'))
    return manifest, out


def prepare(run, label, project=None):
    """Create inputs for the existing operation.py; root must invoke it explicitly."""
    require(re.fullmatch(r'[a-z0-9][a-z0-9-]*', label) is not None, 'Unsafe operation label')
    manifest, proof = source_provenance(run, project)
    remote = manifest['remote_directory']; run_id = manifest['run_id']
    require(remote.endswith('/runs/'+run_id) and remote.startswith('/'), 'Wrong remote solver directory')
    folder = INPUTS/label; require(not folder.exists(), 'Prepared operation exists; reconcile it, never overwrite or resubmit')
    folder.mkdir(parents=True, exist_ok=False)
    files, hashes = sorted(proof['tdr_sha256']), proof['tdr_sha256']
    (folder/'extract_fields.tcl').write_bytes((HERE/'extract_fields.tcl').read_bytes())
    (folder/'field-contract.json').write_bytes((HERE/'field_contract.json').read_bytes())
    (folder/'source-case.txt').write_text(proof['case_id']+'\n', encoding='utf-8', newline='\n')
    (folder/'tdr-files.txt').write_text(''.join(name+'\n' for name in files), encoding='utf-8', newline='\n')
    (folder/'tdr-sha256.txt').write_text(''.join(hashes[name]+'  '+name+'\n' for name in files), encoding='utf-8', newline='\n')
    evidence = dict(schema='dram-see-v4-native-field-postprocess-r1', revision='source-field-audit-3d-r1',
                    source_run_id=run_id, source_archive_sha256=proof['archive_sha256'],
                    source_manifest_sha256=proof['manifest_sha256'], script_sha256=proof['extractor_sha256'],
                    field_contract_sha256=proof['field_contract_sha256'], tdr_sha256=hashes, tdr_bytes=proof['tdr_bytes'],
                    new_sdevice_solves=0, threads=1, dimension=3,
                    time_binding='Exact original accepted BE intervals, original Writing log and native PLT. Filenames are identifiers only.')
    save_new(folder/'source-evidence.json', evidence); save_new(folder/'source-provenance.json', proof)
    commands = ['set -euo pipefail'] + ['cp -- '+shlex.quote(remote+'/'+name)+' '+shlex.quote(name) for name in files]
    commands += ['sha256sum -c tdr-sha256.txt', 'set +e',
        '/usr/synopsys/sentaurus/W-2024.09/bin/svisual --threads 1 --max_threads 1 -b -tcl -script extract_fields.tcl > svisual.log 2>&1',
        'v4_field_rc=$?', 'printf "%s\\n" "$v4_field_rc" > svisual-exit-code.txt', 'set -e',
        'test "$v4_field_rc" -eq 0', "grep -Fx 'FIELD_AUDIT_COMPLETED mandatory_errors=0' svisual.log",
        "grep -Fx 'mandatory_command_errors=0' diagnostic-status.txt", 'sha256sum -c tdr-sha256.txt',
        'test -s field-inventory.csv', 'test -s field-measurements.csv', 'echo NATIVE_FIELD_POSTPROCESS_COMPLETED']
    (folder/'task.sh').write_text('\n'.join(commands)+'\n', encoding='utf-8', newline='\n')
    return dict(input=folder.relative_to(ROOT).as_posix(), tdr_count=len(files), tdr_bytes=sum(proof['tdr_bytes'].values()),
                max_frame_bytes=max(proof['tdr_bytes'].values()), numeric_commands_per_active_frame=71,
                numeric_commands_per_structural_zero_frame=19, new_solves=0, dispatched=False)


def extraction_evidence(operation, solver_archive, solver_report):
    operation = Path(operation).resolve()
    if operation.name == 'collected': operation = operation.parent
    folder = operation/'collected'; record = read_json((operation/'field-extraction-record.json').read_bytes())
    require(record.get('schema') == 'dram-see-v4-native-field-extraction-receipt-r1', 'Unknown extraction receipt')
    for key in ('svisual_exit_code', 'remote_exit_code', 'runner_exit_code', 'collection_exit_code'):
        require(type(record.get(key)) is int and record[key] == 0, 'Unknown/nonzero extraction exit: '+key)
    for key, source in [('solver_run_id', 'run_id'), ('solver_archive_sha256', 'archive_sha256'), ('solver_manifest_sha256', 'manifest_sha256')]:
        require(record[key] == solver_report[source], 'Extraction source binding differs: '+key)
    require((ROOT/record['operation_record']).resolve() == operation/'operation.json' and
            (ROOT/record['operation_archive']).resolve() == operation/'results.tar', 'Operation identity differs')
    require(sha(operation/'operation.json') == record['operation_record_sha256'], 'Operation receipt hash differs')
    require(sha(operation/'results.tar') == record['operation_archive_sha256'], 'Operation archive hash differs')
    op = read_json((operation/'operation.json').read_bytes())
    require(op['state'] == 'COLLECTED_PENDING_AUDIT' and op['archive_sha256'] == record['operation_archive_sha256'], 'Unknown/failed operation')
    for key in ('ssh_exit_code', 'remote_exit_code', 'collection_exit_code'):
        require(type(op.get(key)) is int and op[key] == 0, 'Operation outcome unknown/nonzero')
    require(record['extractor_sha256'] == sha(HERE/'extract_fields.tcl') == sha(folder/'extract_fields.tcl'), 'Extractor source changed')
    require(sha(folder/'field-contract.json') == sha(HERE/'field_contract.json'), 'Field contract changed')
    require((folder/'source-case.txt').read_text().strip() == solver_report['case_id'], 'Extraction case differs')
    files = (folder/'tdr-files.txt').read_text().splitlines()
    require(files and len(files) == len(set(files)) and all(FRAME_RE.fullmatch(name) for name in files), 'Unsafe/missing/duplicate TDR list')
    expected_files = {name for name in solver_archive.members if FRAME_RE.fullmatch(name)}
    require(set(files) == expected_files, 'Incomplete or extra original accepted-frame family')
    hashes = record['tdr_files_sha256']
    require(set(files) == set(hashes) == set(record['tdr_before_sha256']) == set(record['tdr_after_sha256']), 'TDR hash inventory differs')
    with Archive(operation/'results.tar') as archive:
        for name, digest in op['input_sha256'].items():
            require(old.safe_name(name) == name, 'Unsafe operation input path')
            require(sha(folder/name) == archive.digest(name) == digest, 'Original operation input changed: '+name)
        for name, digest in hashes.items():
            require(digest == solver_archive.digest(name) == archive.digest(name) == sha(folder/name)
                    == record['tdr_before_sha256'][name] == record['tdr_after_sha256'][name], 'TDR changed or is not original: '+name)
        for name, digest in record['native_outputs_sha256'].items():
            require(re.fullmatch(r'[A-Za-z0-9_.-]+', name) and sha(folder/name) == digest == archive.digest(name), 'Unbound native output')
    require(NATIVE_OUTPUTS <= set(record['native_outputs_sha256']), 'Missing native output evidence')
    evidence = read_json((folder/'source-evidence.json').read_bytes())
    require(evidence['source_run_id'] == solver_report['run_id'] and evidence['tdr_sha256'] == hashes and
            evidence['script_sha256'] == record['extractor_sha256'] and evidence['field_contract_sha256'] == sha(HERE/'field_contract.json') and
            evidence['source_archive_sha256'] == solver_report['archive_sha256'] and evidence['source_manifest_sha256'] == solver_report['manifest_sha256'],
            'Preparation/receipt source identity differs')
    status = {}
    for line in (folder/'diagnostic-status.txt').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1); require(key not in status, 'Duplicate extraction status'); status[key] = value
    require(status.get('schema') == 'source-field-audit-3d-r1-extraction' and status.get('dimension') == '3' and
            status.get('integration') == 'volume_um3' and status.get('mandatory_command_errors') == '0', 'Native 3D extraction status missing')
    require(status.get('files_requested') == status.get('files_completed') == str(len(files)), 'Native frame count differs')
    require('FIELD_AUDIT_COMPLETED mandatory_errors=0' in (folder/'svisual.log').read_text(errors='replace').splitlines(), 'Native completion sentinel missing')
    require((folder/'svisual-exit-code.txt').read_text().strip() == '0', 'Raw native exit is not zero')
    require(status.get('memory_release') == 'plot_then_dataset_per_frame' and status.get('cleanup_success') == 'exact_deleted_object_name', 'Bounded cleanup status differs')
    raw = (folder/'field-measurements.csv').read_text()
    prior.check_cleanup(raw, files, 'exact_deleted_object_name', (folder/'field-inventory.csv').read_text())
    return files, parse_measurements(raw, files, solver_report['case_id']), record


def audit(run, extraction, project=None, output=None):
    run = Path(run).resolve()
    out = dict(schema='source-field-audit-3d-r1', mode='full', dimension=3, passed=False,
        field_measurements_passed=False, overall_source_interface_passed=False,
        scientific_calibration_passed=False, numerical_convergence_validated=False,
        three_dimensional_nuclear_coupling_passed=False, checks={}, errors=[],
        field_contract_sha256=sha(HERE/'field_contract.json'), audit_code_sha256=sha(Path(__file__)),
        audit_tolerances=T, limits=C['limits'])
    checks = old.Checks(out)
    checks.call('frozen_readonly_dependencies', check_dependencies)
    manifest = checks.call('solver_manifest', lambda: old._manifest(run, out)); frames = []
    if manifest is not None:
        def inspect():
            nonlocal frames
            with Archive(run/'results.tar') as archive:
                checks.call('original_solver_provenance', lambda: old._provenance(archive, manifest, run, project, out))
                data = checks.call('frozen_3d_source_contract', lambda: check_builder_archive(archive, project))
                curves = checks.call('complete_raw_curves', lambda: old._curves(archive, out))
                if data is None or curves is None: return False
                p, spec = data; out.update(case_id=p['case_id'], stored_bit=p['stored_bit'])
                evidence = checks.call('original_extraction_provenance', lambda: extraction_evidence(extraction, archive, out))
                if evidence is None: return False
                files, values, receipt = evidence
                out.update(extraction_record=receipt, extraction_record_sha256=sha(Path(extraction).parent/'field-extraction-record.json') if Path(extraction).name == 'collected' else sha(Path(extraction)/'field-extraction-record.json'))
                mapping = checks.call('accepted_BE_Writing_PLT_bijection', lambda: index_frames(archive.read('transient_des.log').decode(errors='replace'), curves['device'], files))
                if mapping is not None:
                    index, boundary = mapping
                    out.update(accepted_intervals=index, boundary_frames_not_integrated=boundary, frame_count=len(index))
                    frames = summarize_snapshots(index, values)
                    checks.call('native_3d_volume_field_gates', lambda: full_metrics(index, values, curves['device'], spec, out))
                require(sha(run/'results.tar') == out['archive_sha256'] and sha(run/'manifest.json') == out['manifest_sha256'], 'Original solver evidence changed during audit')
            return True
        checks.call('safe_original_archive_read', inspect)
    out['passed'] = not out['errors'] and len(out['checks']) == 9
    out['field_measurements_passed'] = out['passed'] and out.get('case_id') == 'A1'
    out['status'] = ('NATIVE_3D_FIELD_GATES_PASSED_MATCHED_A0_STILL_REQUIRED' if out.get('case_id') == 'A1' else 'STRUCTURAL_ZERO_AND_NATIVE_VOLUME_GATES_PASSED') if out['passed'] else 'FAILED_OR_INCOMPLETE'
    if output is not None:
        output = Path(output).resolve()
        require(output.is_relative_to(OUTPUT.resolve()) and output != OUTPUT.resolve() and not output.exists(), 'Use a new revision-local output directory')
        output.mkdir(parents=True, exist_ok=False)
        if frames:
            with (output/'frames.csv').open('x', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(frames[0])); writer.writeheader(); writer.writerows(frames)
            out['frames_csv_sha256'] = sha(output/'frames.csv')
            out['frames_csv_path'] = str(output/'frames.csv')
        save_new(output/'audit.json', out)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('run', type=Path); p.add_argument('label'); p.add_argument('--project', type=Path)
    p = sub.add_parser('audit'); p.add_argument('run', type=Path); p.add_argument('--extraction', type=Path, required=True); p.add_argument('--project', type=Path); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.run, args.label, args.project) if args.command == 'prepare' else audit(args.run, args.extraction, args.project, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result.get('passed', True) else 1


if __name__ == '__main__': raise SystemExit(main())
