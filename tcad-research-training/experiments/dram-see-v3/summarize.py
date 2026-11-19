"""Rebuild stage snapshots from completed, audited v3 sources; retain every slot."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LOCAL = ROOT / 'local_runtime/dram-see-v3'
FAILURE_STATES = frozenset(('FAILED', 'FAILED_COLLECTED', 'FAILED_OR_DISCONNECTED',
                            'TRANSFER_OR_CONNECTION_FAILED', 'NUMERICAL_FAILED'))
# Keep the explicit ledger allowlist identical to prediction._verified.
CONTINUOUS_ACCEPTED = ('RAW_AUDIT_PASSED', 'MATCHED_REFINEMENT_PASSED', 'PASSED')


def module(name):
    path = HERE / (name + '.py')
    spec = importlib.util.spec_from_file_location('_v3_reporting_' + name, path)
    obj = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), obj.__dict__)
    return obj


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def json_write(path, value):
    with Path(path).open('x', encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def response_tag(event, bit):
    return 'v3-' + event['label'] + f'-b{bit}'


def control_tag(length, bit):
    return f'v3-control-l{round(length*100):03d}-b{bit}-ox5-s1-m1'


def neutral_tag(length):
    return f'v3-neutral-l{round(length*100):03d}-ox5-s1-m1'


def response_failed(tag, ledger, errors):
    return tag in errors or ledger.get('runs', {}).get(tag, {}).get('state') in FAILURE_STATES


def numerical_status(tag, margin_mV, numerical_reports, design, ledger_row=None):
    """Only completed paired step+mesh checks clear an unresolved boundary."""
    near = {e for e in design['thresholds_mV'] if abs(abs(margin_mV) - e) <= design['numerical']['near_boundary_mV']}
    comparisons = [row for report in numerical_reports for row in report.get('comparisons', []) if row['response_id'] == tag]
    # A repeated preregistered target in the boundary report is evidence, not a sample.
    variants = {(row['variation']['step'], row['variation']['mesh']) for row in comparisons}
    complete = {(.5, 1.), (1., .7)} <= variants
    comparison_failed = any(row.get('continuous_passed') is not True for row in comparisons)
    ledger_row = ledger_row or {}
    ledger_status = ledger_row.get('continuous_numerical_status')
    ledger_invalid = ((ledger_status is not None and ledger_status not in CONTINUOUS_ACCEPTED)
                      or ledger_row.get('continuous_numeric_valid') is False)
    failed = (comparison_failed or ledger_row.get('continuous_numeric_valid') is False
              or ledger_status in ('FAILED', 'NUMERICAL_FAILED'))
    invalid = comparison_failed or ledger_invalid
    affected = {epsilon * 1000 for row in comparisons for epsilon in row.get('numerically_uncertain_thresholds_V', [])}
    if invalid:
        affected.update(design['thresholds_mV'])
    if not complete:
        affected.update(near)
    return {'continuous_failed': failed, 'continuous_valid': not invalid,
            'ledger_continuous_numerical_status': ledger_status,
            'ledger_continuous_numeric_valid': ledger_row.get('continuous_numeric_valid'),
            'ledger_continuous_rejected': ledger_invalid, 'refinements_complete': complete,
            'near_boundary_thresholds_mV': sorted(near), 'numerically_uncertain_thresholds_mV': sorted(affected),
            'comparison_count': len(comparisons),
            'status': 'CONTINUOUS_FAILED' if failed else 'CONTINUOUS_UNRESOLVED' if invalid else 'REFINED' if complete else 'NEAR_BOUNDARY_PENDING' if near else 'NO_NEAR_BOUNDARY_FLAG'}


def prediction_observations(design, ledger, measured, reports, errors):
    """Same failure states and continuous gates as the complete response table."""
    observed = []
    for event in design['events']:
        if event['split'] == 'train':
            continue
        for bit in (0, 1):
            tag = response_tag(event, bit)
            if tag in measured:
                metric = measured[tag]
                numeric = numerical_status(tag, metric['M4_V'] * 1000, reports, design,
                                           ledger.get('runs', {}).get(tag))
                observed.append({'event_label': event['label'], 'stored_bit': bit,
                                 'continuous_valid': numeric['continuous_valid'],
                                 'targets': {'deltaQ_fC': metric['deltaQ_fC'], 'deltaM_mV': metric['deltaM_V'] * 1000}})
            elif response_failed(tag, ledger, errors):
                observed.append({'event_label': event['label'], 'stored_bit': bit, 'continuous_valid': False})
    return observed


class GateEvidenceError(ValueError):
    """A claimed-complete gate cannot be represented as validated evidence."""
    def __init__(self, progress):
        self.progress = progress
        bad = {stage: [case for case in row['cases'] if case['state'] != 'PASSED']
               for stage, row in progress.items() if row['claimed_verified'] and row['state'] != 'VERIFIED'}
        super().__init__('Reference/source-isolation gate evidence error: ' + json.dumps(bad, ensure_ascii=False))


def reference_gate_progress(design, ledger, load, compare, evidence, comparison_directory=None):
    """Recompute fixed 8+2 cases, bind prior comparison JSON, never load RUNNING.

    A completed physical archive in an unfinished stage is included in progress.
    A VERIFIED stage with missing/changed/failing evidence raises before a new
    snapshot or report can be emitted. No prior comparison is rewritten here.
    """
    directory = Path(comparison_directory) if comparison_directory else HERE / 'data/reference-validation'
    recipes = {'references': [], 'pilot': []}
    for length in (.18, .25, .35, .45):
        for bit in (0, 1):
            recipes['references'].append((f'v3-physical-l{round(length*100):03d}-b{bit}',
                                          control_tag(length, bit), neutral_tag(length)))
    for particle, angle, bit in (('alpha', 30, 1), ('proton', 0, 0)):
        events = [event for event in design['events'] if event['pilot'] and event['gate_length_um'] == .18
                  and event['particle'] == particle and event['angle_deg'] == angle]
        if len(events) != 1:
            raise ValueError('Frozen source-isolation event is ambiguous')
        recipes['pilot'].append((f'v3-isolation-{particle}-a{angle}-b{bit}', response_tag(events[0], bit), neutral_tag(.18)))
    progress = {}
    for stage, cases in recipes.items():
        claimed = ledger.get('stages', {}).get(stage, {}).get('state') == 'VERIFIED'
        results = []
        for physical_tag, signal_tag, neutral in cases:
            item = ledger.get('runs', {}).get(physical_tag, {})
            result = {'tag': physical_tag, 'signal_tag': signal_tag, 'neutral_tag': neutral,
                      'ledger_state': item.get('state', 'UNSUBMITTED'), 'run_id': item.get('run_id'),
                      'state': 'PENDING', 'reason': None}
            results.append(result)
            if item.get('state') != 'VERIFIED' or not item.get('run_id'):
                result['reason'] = 'Physical run not verified; raw output deliberately unread'
                continue
            try:
                # Loading the completed physical first records its raw evidence
                # even when an unfinished signal/neutral prerequisite is absent.
                physical = load(physical_tag)
                dependencies = []
                for tag in (signal_tag, neutral):
                    dep = ledger.get('runs', {}).get(tag, {})
                    dependencies.append(load(tag) if dep.get('state') == 'VERIFIED' and dep.get('run_id') else None)
                if physical is None or any(bundle is None for bundle in dependencies):
                    result.update(state='EVIDENCE_INCOMPLETE', reason='Completed physical or matched dependency failed audit/is unavailable')
                    continue
                actual = compare(physical, *dependencies)
                result.update(recomputed=actual, raw_archive_sources=actual.get('sources', {}))
                path = directory / (physical_tag + '.json')
                if not path.is_file():
                    result.update(state='COMPARISON_MISSING', reason='Prior comparison JSON is absent')
                    continue
                digest = sha(path)
                evidence[path.resolve().relative_to(ROOT).as_posix()] = digest
                result.update(comparison_file=path.resolve().relative_to(ROOT).as_posix(), comparison_sha256=digest)
                saved = json.loads(path.read_text(encoding='utf8'))
                if saved != actual:
                    result.update(state='COMPARISON_CHANGED', reason='Prior comparison differs from raw-archive recomputation')
                elif actual.get('passed') is not True:
                    result.update(state='FAILED', reason='Physical/offline voltage or classification agreement failed')
                else:
                    result['state'] = 'PASSED'
            except (ValueError, KeyError, OSError) as exc:
                result.update(state='EVIDENCE_ERROR', reason=type(exc).__name__ + ': ' + str(exc))
        passed = sum(row['state'] == 'PASSED' for row in results)
        progress[stage] = {'claimed_verified': claimed, 'planned_comparisons': len(cases),
                           'passed_comparisons': passed, 'completed_physical_runs': sum(row['ledger_state'] == 'VERIFIED' for row in results),
                           'state': 'VERIFIED' if claimed and passed == len(cases) else 'PARTIAL', 'cases': results}
    if any(row['claimed_verified'] and row['state'] != 'VERIFIED' for row in progress.values()):
        raise GateEvidenceError(progress)
    return progress


def native_targets(design):
    selected = design['numerical']['preregistered']
    events = [event for event in design['events'] if event['gate_length_um'] == selected['length_um']
              and all(event[key] == selected[key] for key in ('particle', 'angle_deg', 'replicate'))]
    if len(events) != 1:
        raise ValueError('Predeclared native-field event is ambiguous')
    return ['v3-physical-l018-b1', response_tag(events[0], selected['stored_bit'])]


def collect_native_evidence(design, ledger, load, evidence, native_directory=None, run_directory=None):
    """Bind native exports to audited final TDRs; image inspection remains pending.

    Optional directories exist only for isolated contract fixtures. This function
    neither imports the GUI launcher nor reads any unverified run's archive.
    """
    directory = Path(native_directory) if native_directory else HERE / 'figures/native'
    runs = Path(run_directory) if run_directory else ROOT / 'local_runtime/runs'
    targets = native_targets(design)
    records = []
    required = {'view.tcl', 'own-pid.txt', 'final-field-native.png', 'own-window.png', 'native-proof.txt', 'visual.log'}
    for path in sorted(directory.glob('*/evidence.json')):
        body = json.loads(path.read_text(encoding='utf8'))
        tag, run_id = body.get('ledger_tag'), body.get('run_id')
        item = ledger.get('runs', {}).get(tag, {})
        row = {'ledger_tag': tag, 'run_id': run_id, 'predeclared_target': tag in targets,
               'evidence_file': path.resolve().relative_to(ROOT).as_posix(), 'evidence_sha256': sha(path),
               'state': 'PENDING_RUN_VERIFICATION'}
        records.append(row)
        if item.get('state') != 'VERIFIED':
            row['reason'] = 'Run not VERIFIED; raw archive and native outputs deliberately unread'
            continue
        if (body.get('schema') != 'dram-see-v3-native-field-evidence' or item.get('run_id') != run_id
                or path.parent.name != run_id or Path(run_id).name != run_id):
            raise ValueError('Native evidence run/ledger identity differs: ' + str(path))
        bundle = load(tag)
        if bundle is None:
            raise ValueError('Native evidence source did not pass raw audit: ' + tag)
        audited = bundle['summary']
        archive_path = (runs / run_id / 'results.tar').resolve()
        if not archive_path.is_relative_to(runs.resolve()):
            raise ValueError('Native evidence archive escapes run directory')
        archive_hash = sha(archive_path)
        if body.get('archive_sha256') != archive_hash or archive_hash != audited['archive_sha256']:
            raise ValueError('Native evidence original archive changed: ' + tag)
        if body.get('tdr_member') != 'final_access_des.tdr':
            raise ValueError('Native evidence is not the declared final signal TDR')
        with tarfile.open(archive_path) as archive:
            members = [member for member in archive.getmembers() if Path(member.name).name == body['tdr_member'] and member.isfile()]
            if len(members) != 1:
                raise ValueError('Native source TDR missing or ambiguous')
            tdr_hash = hashlib.sha256(archive.extractfile(members[0]).read()).hexdigest()
        if (any(body.get(key) != tdr_hash for key in ('tdr_sha256', 'remote_source_sha256_before_load', 'remote_source_sha256_after_capture'))
                or audited.get('tdr_sha256', {}).get(body['tdr_member']) != tdr_hash):
            raise ValueError('Native evidence TDR identity differs: ' + tag)
        if body.get('condition') != bundle['parameters']:
            raise ValueError('Native evidence condition differs from audited input')
        if (body.get('field') != 'Abs(ElectricField-V)' or body.get('field_units') != 'V/cm'
                or body.get('coordinate_units') != 'um'
                or any(body.get(key, {}).get('exit_code') != 0 for key in ('launch_operation', 'capture_operation'))):
            raise ValueError('Native export field/units or operation completion differs')
        files = body.get('files_sha256', {})
        if not required <= set(files):
            raise ValueError('Native evidence file set is incomplete')
        bound = {}
        for name, digest in files.items():
            output = (path.parent / name).resolve()
            if Path(name).name != name or not output.is_relative_to(path.parent.resolve()) or name == 'evidence.json' or sha(output) != digest:
                raise ValueError('Native evidence output path/hash differs: ' + name)
            bound[output.relative_to(ROOT).as_posix()] = digest
        proof = (path.parent / 'native-proof.txt').read_text(encoding='utf8')
        if ('V3_NATIVE_FIELD_EXPORT_COMPLETED ' + run_id + ' ' + tdr_hash not in proof.splitlines()
                or 'Abs(ElectricField-V)' not in proof.split()):
            raise ValueError('Native proof does not bind final source/field')
        for name, digest in body.get('depended_source_files_sha256', {}).items():
            source = (ROOT / name).resolve()
            if not source.is_relative_to(ROOT) or sha(source) != digest:
                raise ValueError('Native capture dependency changed: ' + name)
            bound[source.relative_to(ROOT).as_posix()] = digest
        bound[archive_path.relative_to(ROOT).as_posix()] = archive_hash
        bound[row['evidence_file']] = row['evidence_sha256']
        evidence.update(bound)
        row.update(state='CAPTURED_PENDING_VISUAL_REVIEW', archive_sha256=archive_hash, tdr_sha256=tdr_hash,
                   tdr_member=body['tdr_member'], native_loaded_file=body.get('native_loaded_file'), condition=body['condition'],
                   field=body['field'], field_units=body['field_units'], coordinate_units=body['coordinate_units'],
                   screenshot=(path.parent / 'own-window.png').resolve().relative_to(ROOT).as_posix(),
                   native_export=(path.parent / 'final-field-native.png').resolve().relative_to(ROOT).as_posix(),
                   source_files_sha256=bound, scope=body.get('scope'), screenshot_kind=body.get('screenshot_kind'),
                   export_kind=body.get('export_kind'), visual_review_status=body.get('visual_review_status', 'pending image inspection'),
                   provenance_hashes_verified=True, visual_review_passed=False)
    captured = {row['ledger_tag'] for row in records if row['state'] == 'CAPTURED_PENDING_VISUAL_REVIEW'}
    return {'state': 'CAPTURED_PENDING_VISUAL_REVIEW' if set(targets) <= captured else 'PARTIAL' if captured else 'PENDING',
            'predeclared_targets': targets, 'pending_targets': [tag for tag in targets if tag not in captured],
            'captures': records, 'scope': 'Native 4 ns electric-field maps and actual SVisual windows; distinct from DATA PLOT and transient readout curves. Hash verification does not replace visual review.'}


def validate_snapshot_claims(summary):
    """Reject an old/unbound snapshot that claims completed reference gates."""
    checked = {}
    def bind(path, digest):
        source = (ROOT / path).resolve()
        if not source.is_relative_to(ROOT):
            raise ValueError('Snapshot evidence escapes repository')
        if path not in checked:
            checked[path] = sha(source)
        if checked[path] != digest or summary.get('source_files_sha256', {}).get(path) != digest:
            raise ValueError('Snapshot bound evidence changed or missing: ' + path)
    for stage, count in (('references', 8), ('pilot', 2)):
        if summary.get('stages', {}).get(stage, {}).get('state') != 'VERIFIED':
            continue
        progress = summary.get('reference_validation', {}).get(stage, {})
        cases = progress.get('cases', [])
        if (progress.get('state') != 'VERIFIED' or progress.get('passed_comparisons') != count
                or len(cases) != count or len({row.get('tag') for row in cases}) != count):
            raise ValueError('Snapshot claims unbound reference/source-isolation gate: ' + stage)
        for case in cases:
            if case.get('state') != 'PASSED' or case.get('recomputed', {}).get('passed') is not True:
                raise ValueError('Snapshot reference gate contains unpassed comparison')
            bind(case['comparison_file'], case['comparison_sha256'])
            if json.loads((ROOT / case['comparison_file']).read_text(encoding='utf8')) != case['recomputed']:
                raise ValueError('Snapshot comparison differs from recomputed proof')
            for source in case['recomputed']['sources'].values():
                bind('local_runtime/runs/' + source['run_id'] + '/results.tar', source['archive_sha256'])
    for capture in summary.get('native_evidence', {}).get('captures', []):
        if capture.get('state') == 'CAPTURED_PENDING_VISUAL_REVIEW':
            for path, digest in capture['source_files_sha256'].items():
                bind(path, digest)


def collect_request_demo(design_hash, evidence):
    path = HERE / 'data/demo/request-demonstration.json'
    if not path.is_file():
        return {'state': 'PENDING', 'student_demonstration': 'PENDING'}
    body = json.loads(path.read_text(encoding='utf8'))
    source = (ROOT / body['source']).resolve()
    parser = HERE / 'design.py'
    if (not source.is_relative_to(ROOT) or sha(source) != body.get('source_sha256')
            or body.get('design_sha256') != design_hash or sha(parser) != body.get('parser_sha256')
            or body.get('passed') is not True or body.get('nl_same_matrix') is not True
            or body.get('events') != 64 or body.get('responses') != 128 or len(body.get('rejections', [])) != 5):
        raise ValueError('Bounded request demonstration evidence differs')
    original = json.loads(source.read_text(encoding='utf8'))
    if any(original.get(key) != body.get(key) for key in ('utc', 'passed', 'events', 'responses', 'nl_request', 'nl_same_matrix', 'rejections')):
        raise ValueError('Bounded request demonstration differs from original validation')
    for item in (path, source, parser, HERE / 'demo.md'):
        evidence[item.relative_to(ROOT).as_posix()] = sha(item)
    return {'state': 'VERIFIED_BOUNDED_INTERFACE', 'evidence_file': path.relative_to(ROOT).as_posix(),
            'evidence_sha256': sha(path), 'guide': (HERE / 'demo.md').relative_to(ROOT).as_posix(),
            'utc': body['utc'], 'scope': body['scope'], 'student_demonstration': 'PENDING'}


def assemble(design, ledger, measured, audits, curves=None, numerical_reports=(), oxide=None,
             prediction_scores=None, errors=None, evidence=None, synthetic_fixture=False, reference_validation=None):
    """Pure assembly: measured/audits are previously audited data, never plans."""
    stats = module('statistics')
    errors, evidence, curves = errors or {}, evidence or {}, curves or {}
    expected = {response_tag(event, bit) for event in design['events'] for bit in (0, 1)}
    if len(expected) != 128 or len(design['events']) != 64 or not set(measured) <= expected:
        raise ValueError('Need the unchanged 64-event/128-response main matrix')
    responses, outcomes = [], []
    for event in design['events']:
        for bit in (0, 1):
            tag = response_tag(event, bit)
            item = ledger.get('runs', {}).get(tag, {})
            row = {key: event[key] for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'condition_id', 'replicate', 'split')}
            row.update(response_id=tag, event_label=event['label'], stored_bit=bit, oxide_nm=5., mesh_scale=1., step_scale=1.,
                       ledger_state=item.get('state', 'UNSUBMITTED'), run_id=item.get('run_id'), status='missing',
                       raw_classification={}, effective_classification={}, deltaQ_fC=None, deltaM_mV=None,
                       M_mV=None, D_mV=None, numerical=None, sources={}, failure_reason=None)
            if tag in measured:
                if item.get('state') != 'VERIFIED':
                    raise ValueError('Only VERIFIED completed responses can contribute measurements: ' + tag)
                metric = measured[tag]
                if metric['stored_bit'] != bit:
                    raise ValueError('Measured bit differs from fixed slot')
                row.update(status='measured', deltaQ_fC=metric['deltaQ_fC'], deltaM_mV=metric['deltaM_V'] * 1000,
                           M_mV=metric['M4_V'] * 1000, D_mV=metric['D4_V'] * 1000,
                           control_M_mV=metric['control_M4_V'] * 1000, read_window=metric['read_window'],
                           control_read_window=metric['control_read_window'], sources=metric['sources'])
                audited = audits.get(row['run_id'], {})
                if audited:
                    row.update(Qdep_fC=audited['parameters'].get('charge_pc', 0) * 1000,
                               initial_SN_V=audited.get('initial_SN_V'), initial_error_mV=audited.get('initial_error_V', 0) * 1000,
                               hold_end_SN_V=audited.get('hold_end_SN_V'), final_BL_V=audited.get('final_BL_V'),
                               source_integral=audited.get('radiation'), archive_sha256=audited['archive_sha256'])
                if any(not math.isfinite(row[k]) for k in ('deltaQ_fC', 'deltaM_mV', 'M_mV', 'D_mV')):
                    raise ValueError('Nonfinite measured response')
                row['numerical'] = numerical_status(tag, row['M_mV'], numerical_reports, design, item)
                for epsilon in design['thresholds_mV']:
                    raw = stats.classification(row['M_mV'], epsilon)
                    row['raw_classification'][str(epsilon)] = raw
                    row['effective_classification'][str(epsilon)] = ('numerically_uncertain'
                        if epsilon in row['numerical']['numerically_uncertain_thresholds_mV'] else raw)
                # Stage-level incompleteness stays distinct from a demonstrated numerical failure.
                pending = [name for name in ('references', 'pilot')
                           if (reference_validation or {}).get(name, {}).get('state') != 'VERIFIED']
                if ledger.get('stages', {}).get('numerical_preregistered', {}).get('state') != 'VERIFIED':
                    pending.append('numerical_preregistered')
                row['validation_pending'] = pending
            elif tag in errors:
                row.update(status='failed', failure_reason=errors[tag])
            elif response_failed(tag, ledger, errors):
                row.update(status='failed', failure_reason=item.get('failure_reason', item.get('error', 'Recorded failed/unresolved attempt')))
            else:
                row['missing_reason'] = ('matching/reference or audited curve unavailable' if item.get('state') == 'VERIFIED'
                                         else 'not completed; running output intentionally excluded' if item.get('state') == 'RUNNING' else 'not submitted')
            responses.append(row)
            outcome = {k: row[k] for k in ('event_label', 'stored_bit', 'status', 'M_mV')}
            if row['numerical']:
                outcome['numerically_uncertain_thresholds_mV'] = row['numerical']['numerically_uncertain_thresholds_mV']
            outcomes.append(outcome)
    statistics = stats.summarize_matrix(design, outcomes)
    measured_n = sum(row['status'] == 'measured' for row in responses)
    main_counts = {name: sum(row['effective_classification'].get(str(design['main_threshold_mV'])) == name for row in responses)
                   for name in ('correct', 'criterion_error', 'critical', 'numerically_uncertain')}
    main_counts.update(failed=sum(row['status'] == 'failed' for row in responses), missing=sum(row['status'] == 'missing' for row in responses))
    if sum(main_counts.values()) != 128:
        raise ValueError('Planned response accounting changed')
    solver_s = sum(row.get('charged_solver_s', row.get('elapsed_s', 0)) or 0 for row in ledger.get('runs', {}).values() if not row.get('inherited'))
    unfinished = [{'tag': tag, 'run_id': row.get('run_id'), 'state': row.get('state')}
                  for tag, row in ledger.get('runs', {}).items() if row.get('state') not in ('VERIFIED', 'FAILED')]
    return {'schema': 'dram-see-v3-stage-summary', 'generated_utc': datetime.now(timezone.utc).isoformat(),
            'synthetic_fixture': synthetic_fixture, 'design': design,
            'planned_independent_events': 64, 'planned_main_responses': 128,
            'measured_main_responses': measured_n,
            'events_with_any_measured_response': len({row['event_label'] for row in responses if row['status'] == 'measured'}),
            'events_with_both_measured_responses': sum(all(any(row['event_label'] == event['label'] and row['stored_bit'] == bit and row['status'] == 'measured'
                                                               for row in responses) for bit in (0, 1)) for event in design['events']),
            'main_threshold_counts': main_counts, 'responses': responses, 'statistics': statistics,
            'audited_runs': audits, 'curves': curves, 'numerical_reports': list(numerical_reports),
            'oxide': oxide, 'prediction_scores': prediction_scores, 'stages': ledger.get('stages', {}),
            'reference_validation': reference_validation or {},
            'budget': {'accounted_solver_s': solver_s, 'planned_budget_s': design['execution']['solver_budget_s'],
                       'running_or_unsettled': unfinished, 'running_time_not_yet_final': bool(unfinished)},
            'errors': errors, 'source_files_sha256': evidence,
            'scope': 'Stage snapshot; raw audits, physical-reference checks and numerical classification uncertainty remain separate. No commercial reliability or cross-section claim.'}


def _display_curve(bundle):
    raw = bundle['circuit']
    # Plot-only thinning: preserve phase boundaries and late readout, never use for metrics.
    stride = max(1, math.ceil(len(raw) / 600))
    indices = set(range(0, len(raw), stride)) | {len(raw) - 1}
    indices.update(i for i, row in enumerate(raw) if row['time'] >= 3.8e-9 or any(abs(row['time'] - t) < 1e-18 for t in (.6e-9, .95e-9, 1e-9, 1.05e-9, 2.8e-9, 3e-9)))
    return {'run_id': bundle['summary']['run_id'], 'archive_sha256': bundle['summary']['archive_sha256'],
            'parameters': bundle['parameters'], 'thinning': 'display only, regular sample plus boundaries and full 3.8-4ns window; metrics use original curves',
            'points': [{'time_ns': raw[i]['time'] * 1e9, 'SN_V': raw[i]['v(sn)'], 'BL_V': raw[i]['v(bl)'],
                        'WL_V': raw[i]['v(wl)'], 'REF_V': raw[i].get('v(ref)')} for i in sorted(indices)]}


def collect():
    """Read completed archives only; never inspect a RUNNING run's raw output."""
    design_path, ledger_path = HERE / 'stats-design.json', LOCAL / 'ledger.json'
    if sha(design_path) != (LOCAL / 'stats-design.sha256').read_text().strip():
        raise ValueError('Frozen design changed')
    design = json.loads(design_path.read_text(encoding='utf8'))
    ledger_bytes = ledger_path.read_bytes()
    ledger = json.loads(ledger_bytes)
    metrics = module('metrics')
    bundles, audits, curves, errors, measured = {}, {}, {}, {}, {}
    evidence = {design_path.relative_to(ROOT).as_posix(): sha(design_path)}
    def load(tag):
        row = ledger.get('runs', {}).get(tag)
        if not row or row.get('state') != 'VERIFIED' or not row.get('run_id'):
            return None
        run_id = row['run_id']
        if run_id in bundles:
            return bundles[run_id]
        try:
            bundle = metrics.audit_module.load_curves(run_id)
            bundles[run_id] = bundle
            audits[run_id] = bundle['summary']
            if bundle['parameters'].get('reference_mode') == 'offline':
                curves[run_id] = _display_curve(bundle)
            for name in ('manifest.json', 'inputs.tar', 'results.tar'):
                path = ROOT / 'local_runtime/runs' / run_id / name
                evidence[path.relative_to(ROOT).as_posix()] = sha(path)
            return bundle
        except (ValueError, KeyError, OSError) as exc:
            errors[tag] = type(exc).__name__ + ': ' + str(exc)
            return None
    # Initial-state evidence includes only the completed declared baseline/neutral runs.
    for length in (.18, .25, .35, .45):
        load(neutral_tag(length))
        for bit in (0, 1):
            load(control_tag(length, bit))
    for event in design['events']:
        for bit in (0, 1):
            tag = response_tag(event, bit)
            signal = load(tag)
            if signal is None:
                continue
            control, neutral = load(control_tag(event['gate_length_um'], bit)), load(neutral_tag(event['gate_length_um']))
            if control is None or neutral is None:
                continue
            try:
                p = signal['parameters']
                for key in ('gate_length_um', 'particle', 'angle_deg', 'seed'):
                    if p.get(key) != event[key]:
                        raise ValueError('Response identity differs from frozen slot: ' + key)
                if p.get('stored_bit') != bit or p.get('oxide_nm') != 5 or p.get('step_scale') != 1 or p.get('mesh_scale') != 1:
                    raise ValueError('Response is not the declared main condition')
                measured[tag] = metrics.compute_curves(signal, control, neutral)
            except (ValueError, KeyError) as exc:
                errors[tag] = type(exc).__name__ + ': ' + str(exc)
    reference_validation = reference_gate_progress(design, ledger, load, metrics.compare_physical_curves, evidence)
    reports, oxide = [], None
    for stage in ('numerical_preregistered', 'numerical_boundary', 'oxide'):
        state = ledger.get('stages', {}).get(stage, {})
        if not state.get('evidence'):
            continue
        path = (ROOT / state['evidence']).resolve()
        if not path.is_relative_to(HERE / 'data') or sha(path) != state.get('evidence_sha256'):
            raise ValueError('Stage evidence path/hash mismatch: ' + stage)
        body = json.loads(path.read_text(encoding='utf8'))
        if body.get('design_sha256') != sha(design_path):
            raise ValueError('Stage evidence belongs to a different design')
        evidence[path.relative_to(ROOT).as_posix()] = sha(path)
        def bind_sources(value):
            if isinstance(value, dict):
                if 'run_id' in value and 'archive_sha256' in value:
                    path = ROOT / 'local_runtime/runs' / value['run_id'] / 'results.tar'
                    if sha(path) != value['archive_sha256']:
                        raise ValueError('Stage raw source changed')
                    evidence[path.relative_to(ROOT).as_posix()] = sha(path)
                for child in value.values():
                    bind_sources(child)
            elif isinstance(value, list):
                for child in value:
                    bind_sources(child)
        bind_sources(body)
        if stage == 'oxide':
            oxide = body
        else:
            reports.append(body)
    scores = None
    frozen_path = HERE / 'data/predictions/freeze.json'
    if frozen_path.exists():
        frozen = json.loads(frozen_path.read_text(encoding='utf8'))
        if frozen['design_sha256'] != sha(design_path) or sha(frozen_path) != (frozen_path.parent / 'freeze.sha256').read_text().strip():
            raise ValueError('Prediction freeze changed')
        for name, digest in frozen['files_sha256'].items():
            if sha(ROOT / name) != digest:
                raise ValueError('Prediction input/artifact changed: ' + name)
        for name in ('freeze.json', 'freeze.sha256', 'predictions.json'):
            path = frozen_path.parent / name
            evidence[path.relative_to(ROOT).as_posix()] = sha(path)
        observed = prediction_observations(design, ledger, measured, reports, errors)
        if observed:
            scores = module('prediction').score_predictions(json.loads((frozen_path.parent / 'predictions.json').read_text()), observed, design)
    native_evidence = collect_native_evidence(design, ledger, load, evidence)
    request_demo = collect_request_demo(sha(design_path), evidence)
    if ledger_path.read_bytes() != ledger_bytes:
        raise ValueError('Ledger advanced while summarizing; rerun from a stable completed-state snapshot')
    summary = assemble(design, ledger, measured, audits, curves, reports, oxide, scores, errors, evidence,
                       reference_validation=reference_validation)
    summary['ledger_snapshot'] = ledger
    summary['native_evidence'] = native_evidence
    summary['request_demo'] = request_demo
    summary['ledger_snapshot_sha256'] = hashlib.sha256(ledger_bytes).hexdigest()
    summary['source_code_sha256'] = {str((HERE / (name + '.py')).relative_to(ROOT).as_posix()): sha(HERE / (name + '.py'))
                                     for name in ('summarize', 'statistics', 'metrics', 'audit', 'plot_results', 'report')}
    return summary


def _csv(path, rows, fields=None):
    if fields is None:
        fields = list(dict.fromkeys(key for row in rows for key in row))
    with Path(path).open('x', encoding='utf8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def write_snapshot(summary, out=None):
    """Derived snapshots are immutable; raw inputs and prior snapshots are untouched."""
    default = out is None
    if default:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        out = HERE / 'data/summary' / stamp
    out = Path(out).resolve()
    allowed = (HERE / 'data/summary', LOCAL / 'reporting-fixtures')
    if not any(out.is_relative_to(base) and out != base for base in allowed) or out.exists():
        raise ValueError('New reporting snapshot directory required')
    out.mkdir(parents=True)
    json_write(out / 'summary.json', summary)
    _csv(out / 'responses.csv', summary['responses'])
    _csv(out / 'statistics.csv', summary['statistics']['strata'])
    _csv(out / 'initial-state.csv', [{'run_id': run_id, 'archive_sha256': row['archive_sha256'],
        'gate_length_um': row['parameters']['gate_length_um'], 'stored_bit': row['parameters'].get('stored_bit'),
        'neutral': row['parameters']['neutral'], 'target_V': row['parameters']['target_voltage_V'],
        'initial_SN_V': row['initial_SN_V'], 'initial_error_mV': row['initial_error_V'] * 1000}
        for run_id, row in summary['audited_runs'].items()], ['run_id', 'archive_sha256', 'gate_length_um', 'stored_bit', 'neutral', 'target_V', 'initial_SN_V', 'initial_error_mV'])
    if summary.get('prediction_scores'):
        _csv(out / 'prediction-scores.csv', summary['prediction_scores']['scores'])
        _csv(out / 'prediction-residuals.csv', summary['prediction_scores']['stratified_residuals'])
    if summary.get('oxide'):
        _csv(out / 'oxide.csv', [{'response_id': row['response_id'], 'event_label': row['event']['label'],
            'stored_bit': row['stored_bit'], 'oxide_nm': row['oxide_nm'], **row['observation']['metrics']}
            for row in summary['oxide'].get('baseline_5nm', []) + summary['oxide'].get('responses', [])])
    json_write(out / 'sources.json', {'raw_files_sha256': summary.get('source_files_sha256', {}),
                                    'source_code_sha256': summary.get('source_code_sha256', {}),
                                    'audited_run_archives': {run: row['archive_sha256'] for run, row in summary['audited_runs'].items()},
                                    'summary_sha256': sha(out / 'summary.json')})
    if default:
        latest = out.parent / 'latest.json'
        temporary = latest.with_suffix('.tmp')
        temporary.write_text(json.dumps({'snapshot': out.relative_to(ROOT).as_posix(), 'summary_sha256': sha(out / 'summary.json')}, indent=2) + '\n')
        temporary.replace(latest)
    return out


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(write_snapshot(collect()))
