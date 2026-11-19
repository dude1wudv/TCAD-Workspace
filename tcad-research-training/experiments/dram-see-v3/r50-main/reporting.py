"""Explicit, read-only R50-main reporting; immutable snapshots, never dispatches.

Only current R50 raw archives can supply electrical observations. Old/probe data
remain in the unique global cost ledger, never in this matrix's response slots.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
LOCAL = ROOT / 'local_runtime/dram-see-v3'
DEV = LOCAL / 'r50-report-dev'
SCHEMA = 'dram-see-v3-r50-main'
REVISION = 'r50-main-r1'
DESIGN_SHA = '6d52749bb8b9716b13b5ff1aa562a3ee331e3d7a062f32287c23710a5d1cf740'
FAILURES = frozenset(('FAILED', 'FAILED_COLLECTED', 'FAILED_OR_DISCONNECTED', 'TRANSFER_OR_CONNECTION_FAILED', 'NUMERICAL_FAILED'))
CONTINUOUS = (None, 'RAW_AUDIT_PASSED', 'MATCHED_REFINEMENT_PASSED', 'PASSED')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def module(path, name):
    path = Path(path)
    spec = importlib.util.spec_from_file_location('_r50_report_' + name, path)
    result = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), result.__dict__)
    return result


def write_json(path, value):
    with Path(path).open('x', encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def repo(path):
    path = Path(path)
    result = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if not result.is_relative_to(ROOT):
        raise ValueError('Evidence path escapes repository')
    return result


def rel(path):
    return repo(path).relative_to(ROOT).as_posix()


def event_tag(event, bit):
    return 'v3-r50-main-' + event['label'] + '-b' + str(bit)


def control_tag(length, bit):
    return f'v3-r50-main-control-l{round(length * 100):03d}-b{bit}-ox5-s1-m1'


def neutral_tag(length):
    return f'v3-r50-main-neutral-l{round(length * 100):03d}-ox5-s1-m1'


def identity(p):
    required = {'schema': SCHEMA, 'physical_revision': REVISION, 'physical_revision_probe_only': False,
                'precharge_resistance_on_ohm': 50, 'precharge_resistance_off_ohm': 1e20}
    if any(p.get(key) != value for key, value in required.items()):
        raise ValueError('Old 100-ohm/probe/other physical revision is not an R50-main observation')


def named_role(tag, p):
    """A same-version archive may still be assigned to the wrong named slot."""
    short = f"l{round(p['gate_length_um'] * 100):03d}"
    variation = f"ox5-s{p['step_scale']:g}-m{p['mesh_scale']:g}".replace('.', 'p')
    if tag.startswith('v3-r50-main-control-') or tag.startswith('v3-r50-main-neutral-'):
        if p.get('source_event') or p.get('particle') or p.get('charge_pc') != 0 or p.get('parent_run') or p.get('oxide_nm') != 5 or p.get('reference_mode') != 'offline':
            raise ValueError('Baseline/neutral must be a fresh complete 5 nm no-particle single-cell run')
        expected = ('v3-r50-main-neutral-' + short + '-' + variation if p['neutral']
                    else 'v3-r50-main-control-' + short + f"-b{p['stored_bit']}-" + variation)
        if tag != expected:
            raise ValueError('Baseline/neutral archive mapped to a different geometry/bit/variant slot')
    elif tag.startswith('v3-r50-main-physical-'):
        expected = 'v3-r50-main-physical-' + short + f"-b{p['stored_bit']}"
        if (tag != expected or p.get('source_event') or p.get('charge_pc') != 0 or p.get('neutral')
                or p.get('reference_mode') != 'physical' or p['step_scale'] != 1 or p['mesh_scale'] != 1 or p['oxide_nm'] != 5):
            raise ValueError('Physical baseline mapped to a different condition')


def design_checked(path):
    path = repo(path)
    if path != HERE / 'design.json' or sha(path) != DESIGN_SHA:
        raise ValueError('Expected the exact frozen R50-main design')
    design = json.loads(path.read_bytes())
    if (design.get('schema') != SCHEMA or design.get('physical_revision') != REVISION
            or len(design['events']) != 64 or len({event_tag(e, b) for e in design['events'] for b in (0, 1)}) != 128
            or design['statistics']['planned_n_each'] != 4 or design['thresholds_mV'] != [2.5, 5., 10.]):
        raise ValueError('Frozen matrix/statistics identity differs')
    return design


def reporting_manifest():
    path = HERE / 'reporting-manifest.json'
    body = json.loads(path.read_bytes())
    if (body.get('schema') != 'r50-main-reporting-source-manifest' or body.get('physical_revision') != REVISION
            or body.get('design_sha256') != DESIGN_SHA or rel(Path(__file__)) not in body.get('files_sha256', {})):
        raise ValueError('Reporting source manifest is incomplete')
    for name, digest in body['files_sha256'].items():
        if sha(repo(name)) != digest:
            raise ValueError('Reporting dependency changed: ' + name)
    return {**body['files_sha256'], rel(path): sha(path)}


def global_budget(ledger):
    """Describe existing charges only: never create ledger rows or new charges."""
    total, groups, unsettled, accounting_errors, seen = 0., {}, [], [], set()
    for tag, row in ledger.get('runs', {}).items():
        if row.get('inherited'):
            continue
        run_id = row.get('run_id')
        if run_id and run_id in seen:
            raise ValueError('Duplicate charged run ID in unique global ledger: ' + run_id)
        if run_id:
            seen.add(run_id)
        value = row.get('charged_solver_s')
        source = 'charged_solver_s'
        if value is None:
            value, source = row.get('elapsed_s'), 'elapsed_s'
        if value is None:
            accounting_errors.append({'tag': tag, 'state': row.get('state'), 'reason': 'No settled cost yet'})
            value = 0.
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid global cost: ' + tag)
        p = row.get('parameters', {})
        group = 'R50-main' if p.get('schema') == SCHEMA and p.get('physical_revision') == REVISION else 'old_revision_probes_and_other_v3'
        groups[group] = groups.get(group, 0.) + value
        total += value
        if row.get('state') not in FAILURES | {'VERIFIED'}:
            unsettled.append({'tag': tag, 'run_id': run_id, 'state': row.get('state'), 'already_recorded_s': value, 'time_source': source})
    return {'accounted_solver_s': total, 'planned_budget_s': 86400, 'by_scope_s': groups,
            'running_or_unsettled': unsettled, 'running_time_not_yet_final': bool(unsettled),
            'accounting_gaps': accounting_errors, 'complete_cost_accounting': not unsettled and not accounting_errors,
            'policy': 'Read-only sum of unique global ledger; inherited=0; no second charge, budget reset or dispatch authorization'}


class Evidence:
    def __init__(self):
        self.hashes, self.bytes = {}, {}

    def bind(self, path):
        path = repo(path)
        value = sha(path)
        name = rel(path)
        if name in self.hashes and self.hashes[name] != value:
            raise ValueError('Evidence changed while reporting: ' + name)
        self.hashes[name] = value
        return value

    def read_json(self, path):
        path = repo(path)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if rel(path) in self.hashes and self.hashes[rel(path)] != digest:
            raise ValueError('JSON changed while reporting: ' + rel(path))
        self.hashes[rel(path)], self.bytes[rel(path)] = digest, data
        return json.loads(data)

    def stable(self):
        for name, data in self.bytes.items():
            if repo(name).read_bytes() != data:
                raise ValueError('Input advanced while reporting; retry from a stable boundary: ' + name)
        for name, digest in self.hashes.items():
            if sha(repo(name)) != digest:
                raise ValueError('Bound source changed while reporting: ' + name)


class RawReader:
    def __init__(self, ledger, evidence):
        self.ledger, self.evidence = ledger, evidence
        self.metrics = module(HERE / 'metrics.py', 'metrics')
        self.audits, self.bundles, self.errors = {}, {}, {}

    def load(self, tag):
        row = self.ledger.get('runs', {}).get(tag, {})
        if row.get('state') != 'VERIFIED':
            return None  # Never open RUNNING, failed, unknown, or merely COLLECTED raw output.
        if tag in self.bundles:
            return self.bundles[tag]
        if tag in self.errors:
            return None
        try:
            if row.get('inherited') or row.get('runner_exit_code') != 0:
                raise ValueError('R50-main requires a fresh completed runner with exit 0')
            identity(row.get('parameters', {}))
            if row.get('physical_revision') != REVISION or row.get('physical_revision_probe_only') is not False:
                raise ValueError('Global ledger physical revision differs')
            value = self.metrics.audit_module.load_curves(row['run_id'])
            p, audit = value['parameters'], value['summary']
            identity(p)
            named_role(tag, p)
            if (p != row['parameters'] or audit['archive_sha256'] != row.get('audit_archive_sha256')
                    or audit['input_sha256'] != row.get('input_sha256')):
                raise ValueError('Raw archive and global ledger provenance disagree')
            if any(other != tag and item.get('run_id') == row['run_id'] for other, item in self.ledger['runs'].items()):
                raise ValueError('One run ID is assigned to multiple global slots')
            for name in ('manifest.json', 'inputs.tar', 'results.tar'):
                self.evidence.bind(ROOT / 'local_runtime/runs' / row['run_id'] / name)
            self.audits[row['run_id']] = audit
            self.bundles[tag] = value
            return value
        except (ValueError, KeyError, OSError) as exc:
            self.errors[tag] = type(exc).__name__ + ': ' + str(exc)
            return None

    def by_source(self, source):
        found = [tag for tag, row in self.ledger['runs'].items() if row.get('run_id') == source.get('run_id')]
        if len(found) != 1:
            raise ValueError('Numerical source is missing/ambiguous in global ledger')
        bundle = self.load(found[0])
        if bundle is None or bundle['summary']['archive_sha256'] != source.get('archive_sha256'):
            raise ValueError('Numerical raw source is unverified or changed')
        return bundle


def check_slot(p, event, bit, step=1., mesh=1.):
    identity(p)
    for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'energy_MeV'):
        if p.get(key) != event[key]:
            raise ValueError('Raw response differs from frozen event slot: ' + key)
    expected = {'stored_bit': bit, 'neutral': False, 'reference_mode': 'offline', 'oxide_nm': 5., 'step_scale': step, 'mesh_scale': mesh}
    if any(p.get(key) != value for key, value in expected.items()):
        raise ValueError('Wrong bit/oxide/reference/numerical variant in main slot')


def stage_proofs(path, evidence):
    if path is None or not Path(path).exists():
        return {}, 'Stage index not supplied or not yet created; no stage completion inferred'
    path = repo(path)
    body = evidence.read_json(path)
    if body.get('schema') != SCHEMA + '-stage-index' or body.get('physical_revision') != REVISION:
        raise ValueError('Stage index belongs to old/probe/other revision')
    plan_path = path.parent / 'plan.json'
    plan = evidence.read_json(plan_path)
    marker = evidence.read_json(path.parent / 'plan-sha256.json')
    plan_hash = sha(plan_path)
    if (body.get('plan_sha256') != plan_hash or marker.get('sha256') != plan_hash
            or plan.get('schema') != SCHEMA + '-execution-plan'
            or plan.get('design_sha256') != DESIGN_SHA or plan.get('physical_revision') != REVISION):
        raise ValueError('Stage index plan/design binding differs')
    stages = {}
    for name, pointer in body.get('stages', {}).items():
        target = repo(pointer['evidence'])
        stage = evidence.read_json(target)
        if (sha(target) != pointer['evidence_sha256'] or stage.get('schema') != SCHEMA + '-stage'
                or stage.get('physical_revision') != REVISION or stage.get('design_sha256') != DESIGN_SHA
                or stage.get('plan_sha256') != plan_hash or stage.get('stage') != name or stage.get('state') != pointer.get('state')):
            raise ValueError('Stage evidence identity/hash differs: ' + name)
        stages[name] = {'state': 'UNVERIFIED', 'claimed_state': stage['state'], 'body': stage,
                        'path': rel(target), 'sha256': sha(target)}
    return stages, None


def reference_checks(design, reader, stages, evidence, errors):
    recipes = {'references': [], 'pilot': []}
    for length in (.18, .25, .35, .45):
        for bit in (0, 1):
            recipes['references'].append((f'v3-r50-main-physical-l{round(length*100):03d}-b{bit}', control_tag(length, bit), neutral_tag(length)))
    for particle, angle, bit in (('alpha', 30, 1), ('proton', 0, 0)):
        event = next(e for e in design['events'] if e['pilot'] and e['particle'] == particle and e['angle_deg'] == angle)
        recipes['pilot'].append((f'v3-r50-main-isolation-{particle}-a{angle}-b{bit}', event_tag(event, bit), neutral_tag(.18)))
    output = {}
    for stage, triples in recipes.items():
        checks = []
        for tags in triples:
            item = {'tag': tags[0], 'state': 'MISSING_OR_UNVERIFIED'}
            checks.append(item)
            values = [reader.load(tag) for tag in tags]
            if any(v is None for v in values):
                continue
            try:
                if stage == 'pilot':
                    fixed = next(e for e in design['events'] if event_tag(e, values[1]['parameters']['stored_bit']) == tags[1])
                    check_slot(values[1]['parameters'], fixed, values[1]['parameters']['stored_bit'])
                comparison = reader.metrics.compare_physical_curves(*values)
                saved = HERE / 'data/reference-validation' / (tags[0] + '.json')
                item.update(recomputed=comparison)
                if not comparison['passed']:
                    errors[tags[0]] = 'Physical/offline reference comparison failed'
                if not saved.exists():
                    item['state'] = 'RAW_PASSED_EVIDENCE_MISSING' if comparison['passed'] else 'FAILED'
                    continue
                if evidence.read_json(saved) != comparison:
                    raise ValueError('Saved reference comparison differs from raw re-audit')
                item.update(state='PASSED' if comparison['passed'] else 'FAILED', evidence=rel(saved), evidence_sha256=sha(saved))
                if not comparison['passed']:
                    errors[tags[0]] = 'Physical/offline reference comparison failed'
            except (ValueError, KeyError, OSError) as exc:
                item.update(state='FAILED', error=str(exc))
                errors[tags[0]] = str(exc)
        claimed = stages.get(stage, {}).get('claimed_state') == 'VERIFIED'
        passed = sum(c['state'] == 'PASSED' for c in checks)
        stage_cases_passed = True
        if claimed:
            cases = stages[stage]['body'].get('cases', {})
            expected_cases = ({control_tag(length, bit) for length in (.18, .25, .35, .45) for bit in (0, 1)}
                              | {neutral_tag(length) for length in (.18, .25, .35, .45)}
                              | {triple[0] for triple in triples}) if stage == 'references' else (
                                  {event_tag(e, bit) for e in design['events'] if e['pilot'] for bit in (0, 1)} | {triple[0] for triple in triples})
            if set(cases) != expected_cases:
                stage_cases_passed = False
            for tag, item in cases.items():
                value = reader.load(tag)
                if (value is None or item.get('state') != 'VERIFIED' or item.get('run_id') != value['summary']['run_id']
                        or item.get('archive_sha256') != value['summary']['archive_sha256']):
                    stage_cases_passed = False
        output[stage] = {'state': 'VERIFIED' if claimed and passed == len(triples) else 'UNVERIFIED',
                         'planned_comparisons': len(triples), 'passed_comparisons': passed, 'cases': checks}
        if not stage_cases_passed:
            output[stage]['state'] = 'UNVERIFIED'
        if claimed and (passed != len(triples) or not stage_cases_passed):
            errors['stage:' + stage] = 'Claimed VERIFIED stage lacks all raw-recomputed comparison proofs'
    return output


def numerical_checks(design, reader, stages, evidence, errors):
    stage = stages.get('numerical_preregistered')
    if not stage:
        return [], {'state': 'MISSING_OR_UNVERIFIED'}
    try:
        pointer = stage['body']
        path = repo(pointer['evidence'])
        body = evidence.read_json(path)
        if (sha(path) != pointer['evidence_sha256'] or body.get('schema') != SCHEMA + '-numerical-validation'
                or body.get('physical_revision') != REVISION or body.get('design_sha256') != DESIGN_SHA
                or body.get('plan_sha256') != pointer['plan_sha256']):
            raise ValueError('Wrong numerical report version/hash')
        fixed = design['numerical']['preregistered']
        event = next(e for e in design['events'] if e['gate_length_um'] == fixed['length_um'] and all(e[k] == fixed[k] for k in ('particle', 'angle_deg', 'replicate')))
        bit = fixed['stored_bit']
        comparisons = body.get('comparisons', [])
        if len(comparisons) != 2 or {(c['variation']['step'], c['variation']['mesh']) for c in comparisons} != {(.5, 1.), (1., .7)}:
            raise ValueError('Need exactly both preregistered refinement variants')
        pure = module(HERE / 'numerical.py', 'numerical')
        result = []
        for comparison in comparisons:
            if comparison['response_id'] != event_tag(event, bit) or comparison['event'] != event or comparison['stored_bit'] != bit:
                raise ValueError('Numerical comparison is not the predeclared response')
            observations = []
            for prefix in ('baseline', 'refined'):
                sources = comparison[prefix + '_sources']
                if set(sources) != {'signal', 'control', 'neutral'}:
                    raise ValueError('Incomplete numerical matching triple')
                values = {role: reader.by_source(source) for role, source in sources.items()}
                step, mesh = (1., 1.) if prefix == 'baseline' else (comparison['variation']['step'], comparison['variation']['mesh'])
                check_slot(values['signal']['parameters'], event, bit, step, mesh)
                observations.append({'metrics': reader.metrics.compute_curves(*(values[role] for role in ('signal', 'control', 'neutral'))),
                    'readout_BL_V': {role: reader.metrics.sample(value['circuit'], 'v(bl)', 4e-9) for role, value in values.items()}})
            actual = pure.compare_observations(*observations, tuple(e / 1000 for e in design['thresholds_mV']),
                                               design['gates']['numerical_readout_change_mV'] / 1000, design['gates']['numerical_deltaQ_change_fC'])
            if any(comparison.get(key) != value for key, value in actual.items()):
                raise ValueError('Numerical comparison differs from raw recomputation')
            result.append(comparison)
        passed = all(c['continuous_passed'] for c in result)
        stable = all(c['classification_stable'] for c in result)
        if (body['continuous_passed'] != passed or (body['state'] == 'VERIFIED') != passed
                or body.get('classification_stable') != stable or pointer.get('state') != body['state']
                or pointer.get('continuous_passed') != passed or pointer.get('classification_stable') != stable):
            raise ValueError('Numerical stage state disagrees with actual continuous result')
        expected_runs = {source['run_id']: source['archive_sha256'] for c in result for source in c['refined_sources'].values()}
        cases = pointer.get('cases', {})
        if len(cases) != 6 or len(expected_runs) != 6 or {c.get('run_id') for c in cases.values()} != set(expected_runs):
            raise ValueError('Numerical stage must bind the exact six independent refinement archives')
        for tag, case in cases.items():
            value = reader.load(tag)
            if (case.get('state') != 'VERIFIED' or value is None or case['run_id'] != value['summary']['run_id']
                    or case.get('archive_sha256') != expected_runs[case['run_id']]):
                raise ValueError('Numerical stage case is not its current completed raw archive')
        return result, {'state': 'VERIFIED' if passed else 'NUMERICAL_FAILED', 'continuous_passed': passed,
                        'classification_stable': stable, 'evidence': rel(path), 'evidence_sha256': sha(path)}
    except (ValueError, KeyError, OSError) as exc:
        errors['stage:numerical_preregistered'] = str(exc)
        return [], {'state': 'UNVERIFIED', 'error': str(exc)}


def numerical_status(tag, margin_mV, comparisons, row, design):
    selected = [c for c in comparisons if c['response_id'] == tag]
    complete = {(c['variation']['step'], c['variation']['mesh']) for c in selected} >= {(.5, 1.), (1., .7)}
    invalid = (row.get('continuous_numeric_valid') is False or row.get('continuous_numerical_status') not in CONTINUOUS
               or any(c.get('continuous_passed') is not True for c in selected))
    near = {e for e in design['thresholds_mV'] if abs(abs(margin_mV) - e) <= design['numerical']['near_boundary_mV']}
    affected = {1000 * e for c in selected for e in c.get('numerically_uncertain_thresholds_V', [])}
    if invalid:
        affected.update(design['thresholds_mV'])
    if not complete:
        affected.update(near)
    return {'continuous_valid': not invalid, 'refinements_complete': complete,
            'near_boundary_thresholds_mV': sorted(near), 'numerically_uncertain_thresholds_mV': sorted(affected),
            'boundary_followup': 'UNREVIEWED_INTERFACE; no boundary evidence used to clear uncertainty'}


def display_curve(bundle):
    raw = bundle['circuit']
    stride = max(1, math.ceil(len(raw) / 600))
    indices = set(range(0, len(raw), stride)) | {len(raw) - 1}
    indices.update(i for i, row in enumerate(raw) if row['time'] >= 3.8e-9 or any(abs(row['time'] - t) < 1e-18 for t in (.6e-9, .95e-9, 1e-9, 1.05e-9, 2.8e-9, 3e-9)))
    return {'run_id': bundle['summary']['run_id'], 'archive_sha256': bundle['summary']['archive_sha256'],
            'parameters': bundle['parameters'], 'thinning': 'display only; phase boundaries and entire 3.8-4 ns retained',
            'points': [{'time_ns': raw[i]['time'] * 1e9, 'SN_V': raw[i]['v(sn)'], 'BL_V': raw[i]['v(bl)'],
                        'WL_V': raw[i]['v(wl)'], 'REF_V': raw[i].get('v(ref)')} for i in sorted(indices)]}


def assemble(design, ledger, measured, audits, curves, comparisons, gates, budget, errors, evidence, synthetic=False):
    stats = module(BASE / 'statistics.py', 'statistics')
    responses, outcomes = [], []
    for event in design['events']:
        for bit in (0, 1):
            tag = event_tag(event, bit)
            item = ledger.get('runs', {}).get(tag, {})
            row = {k: event[k] for k in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'condition_id', 'replicate', 'split')}
            row.update(response_id=tag, event_label=event['label'], stored_bit=bit, oxide_nm=5., step_scale=1., mesh_scale=1.,
                       status='missing', ledger_state=item.get('state', 'UNSUBMITTED'), run_id=item.get('run_id'),
                       deltaQ_fC=None, deltaM_mV=None, M_mV=None, D_mV=None, numerical=None,
                       raw_classification={}, effective_classification={}, sources={})
            if tag in measured:
                if item.get('state') != 'VERIFIED':
                    raise ValueError('Only completed VERIFIED responses may supply measurements')
                m = measured[tag]
                if m['stored_bit'] != bit or any(not math.isfinite(m[k]) for k in ('deltaQ_fC', 'deltaM_V', 'D4_V', 'M4_V')):
                    raise ValueError('Invalid matched observation')
                row.update(status='measured', deltaQ_fC=m['deltaQ_fC'], deltaM_mV=m['deltaM_V'] * 1000,
                           M_mV=m['M4_V'] * 1000, D_mV=m['D4_V'] * 1000, control_M_mV=m['control_M4_V'] * 1000,
                           sources=m['sources'], read_window=m['read_window'], control_read_window=m['control_read_window'])
                row['numerical'] = numerical_status(tag, row['M_mV'], comparisons, item, design)
                for threshold in design['thresholds_mV']:
                    value = stats.classification(row['M_mV'], threshold)
                    row['raw_classification'][str(threshold)] = value
                    row['effective_classification'][str(threshold)] = 'numerically_uncertain' if threshold in row['numerical']['numerically_uncertain_thresholds_mV'] else value
                row['validation_pending'] = [name for name in ('references', 'pilot', 'numerical_preregistered') if gates.get(name, {}).get('state') != 'VERIFIED']
            elif tag in errors or item.get('state') in FAILURES:
                row.update(status='failed', reason=errors.get(tag, item.get('failure_reason', item.get('error', 'Recorded failed attempt'))))
            else:
                row['reason'] = 'No complete audited R50-main matching triple; running/unknown raw deliberately unread'
            responses.append(row)
            outcome = {k: row[k] for k in ('event_label', 'stored_bit', 'status', 'M_mV')}
            if row['numerical']:
                outcome['numerically_uncertain_thresholds_mV'] = row['numerical']['numerically_uncertain_thresholds_mV']
            outcomes.append(outcome)
    expected = {event_tag(e, bit) for e in design['events'] for bit in (0, 1)}
    if len(responses) != 128 or not set(measured) <= expected:
        raise ValueError('Fixed main matrix changed')
    counts = {name: sum(row['effective_classification'].get(str(design['main_threshold_mV'])) == name for row in responses)
              for name in ('correct', 'criterion_error', 'critical', 'numerically_uncertain')}
    counts.update(failed=sum(r['status'] == 'failed' for r in responses), missing=sum(r['status'] == 'missing' for r in responses))
    if sum(counts.values()) != 128:
        raise ValueError('Fixed planned denominator lost a response')
    measured_n = sum(r['status'] == 'measured' for r in responses)
    return {'schema': SCHEMA + '-report-snapshot', 'physical_revision': REVISION, 'design_sha256': DESIGN_SHA,
            'generated_utc': datetime.now(timezone.utc).isoformat(), 'synthetic_fixture': synthetic,
            'report_state': 'PARTIAL_WITH_EVIDENCE_ERRORS' if errors else 'MAIN_MATRIX_OBSERVED_LATER_GATES_UNREVIEWED' if measured_n == 128 else 'PARTIAL',
            'design': design, 'planned_independent_events': 64, 'planned_main_responses': 128,
            'measured_main_responses': measured_n, 'events_with_any_measured_response': len({r['event_label'] for r in responses if r['status'] == 'measured'}),
            'events_with_both_measured_responses': sum(all(any(r['event_label'] == e['label'] and r['stored_bit'] == b and r['status'] == 'measured' for r in responses) for b in (0, 1)) for e in design['events']),
            'responses': responses, 'main_threshold_counts': counts, 'statistics': stats.summarize_matrix(design, outcomes),
            'audited_runs': audits, 'curves': curves, 'stages': gates, 'budget': budget, 'errors': errors,
            'source_files_sha256': dict(evidence), 'prediction_scores': None, 'oxide': None,
            'later_evidence': {name: {'state': 'UNREVIEWED_OR_MISSING', 'reason': 'No accepted R50 reporting adapter; no completion inferred'}
                               for name in ('prediction_freeze', 'prediction_scores', 'oxide', 'numerical_boundary', 'native_visual')},
            'course_pending': {name: 'PENDING_HUMAN_EVIDENCE' for name in design['course_pending']},
            'scope': 'Fresh R50-main only; old100ohm and probe electrical values excluded; no calibrated reliability, radiation cross-section or full-course-completion claim'}


def collect(design_path, ledger_path, stage_index=None):
    design = design_checked(design_path)
    ledger_path = repo(ledger_path)
    if ledger_path != LOCAL / 'ledger.json':
        raise ValueError('Use the unique global ledger; an R50 stage index is not a cost ledger')
    evidence = Evidence()
    evidence.read_json(design_path)
    ledger = evidence.read_json(ledger_path)
    if not isinstance(ledger.get('runs'), dict):
        raise ValueError('Missing global runs ledger')
    errors = {}
    try:
        stages, missing_index = stage_proofs(stage_index, evidence)
    except (ValueError, KeyError, OSError) as exc:
        stages, missing_index = {}, None
        errors['stage-index'] = type(exc).__name__ + ': ' + str(exc)
    reader = RawReader(ledger, evidence)
    measured = {}
    for length in (.18, .25, .35, .45):
        reader.load(neutral_tag(length))
        for bit in (0, 1):
            reader.load(control_tag(length, bit))
    for event in design['events']:
        for bit in (0, 1):
            tag = event_tag(event, bit)
            values = [reader.load(name) for name in (tag, control_tag(event['gate_length_um'], bit), neutral_tag(event['gate_length_um']))]
            if any(value is None for value in values):
                continue
            try:
                check_slot(values[0]['parameters'], event, bit)
                measured[tag] = reader.metrics.compute_curves(*values)
            except (ValueError, KeyError) as exc:
                errors[tag] = type(exc).__name__ + ': ' + str(exc)
    gates = reference_checks(design, reader, stages, evidence, errors)
    comparisons, gates['numerical_preregistered'] = numerical_checks(design, reader, stages, evidence, errors)
    errors.update(reader.errors)
    curves = {v['summary']['run_id']: display_curve(v) for v in reader.bundles.values() if v['parameters']['reference_mode'] == 'offline'}
    summary = assemble(design, ledger, measured, reader.audits, curves, comparisons, gates, global_budget(ledger), errors, evidence.hashes)
    summary.update(stage_index_note=missing_index, ledger_snapshot=ledger, ledger_snapshot_sha256=sha(ledger_path), numerical_comparisons=comparisons)
    summary['source_code_sha256'] = reporting_manifest()
    evidence.stable()
    return summary


def csv_write(path, rows, fields=None):
    fields = fields or list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('x', encoding='utf8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def render(summary, figures):
    label = '**SYNTHETIC FIXTURE — 非实验结果，不得发布。**\n\n' if summary['synthetic_fixture'] else ''
    counts = summary['main_threshold_counts']
    lines = [label + '# R50-main r1 阶段数据报告',
        f"快照UTC：`{summary['generated_utc']}`。状态：`{summary['report_state']}`。",
        '本报告仅包含 schema `dram-see-v3-r50-main`、revision `r50-main-r1` 的新原始电学归档。信号及物理参考预充导通电阻为50 Ω；原100 Ω设计与50 Ω probe保留，不进入本矩阵的训练、指标或评分。',
        f"计划64个独立事件、128个配对位响应；已取得匹配指标 {summary['measured_main_responses']}/128。两位都有指标的独立事件 {summary['events_with_both_measured_responses']}/64。0/1、细化及氧化层变体不增加独立事件数。",
        '| 主阈值±5 mV类别 | 响应数/128 |', '| --- | --- |',
        *[f'| {name} | {counts[name]} |' for name in ('correct', 'criterion_error', 'critical', 'numerically_uncertain', 'failed', 'missing')],
        '\n每个尺寸×粒子×方向×存储位计划N=4，三阈值2.5/5/10 mV均保留。失败、缺失、临界和数值不确定分别计数；Wilson双侧95%最佳/最差赋值包络使用计划分母。仅全部可判且零误读时给出单侧95%零事件上界（N=4约52.7%）。这不是多重比较同时覆盖或商业可靠性估计。',
        '`ΔQ=Cstore(SN事件−SN对照)` 在2.8 ns以fC保留符号；`D=BL信号−BL中性`，`M=(2b−1)D(4 ns)`，`ΔM=M对照−M事件`。另报3.8–4 ns窗口。完整同版本匹配，不减固定offset。critical不自动筛除连续观测；已知连续数值失败保留诊断原值但标无效。',
        '完整槽位与分层：[responses.csv](responses.csv)、[statistics.csv](statistics.csv)。初态与归档：[initial-state.csv](initial-state.csv)。输入、输出、源码哈希：[sources.json](sources.json)。',
        '\n## 验证状态', '| 门槛 | 当前证据状态 |', '| --- | --- |',
        *[f"| {name} | {row['state']} |" for name, row in summary['stages'].items()],
        '参考验证逐项从完整原档重算；预登记细化重新审计自身信号/对照/中性。缺证据保持未验证，近边界未确认结果保留数值不确定。',
        '\n## 预算与后续范围',
        f"唯一全局ledger已登记累计 {summary['budget']['accounted_solver_s']:.2f}/86400 s，包含旧版、probe、验证及失败；本报告未计入任何新费用。未结运行 {len(summary['budget']['running_or_unsettled'])} 项，成本缺项 {len(summary['budget']['accounting_gaps'])} 项，未结最终时间未推定为0。",
        '预测冻结、测试评分、氧化层、最近边界后续及native图接口尚未由本报告版本审查；不读取旧设计缓存、不猜测通过、不补造MAE/残差或native。即便128个响应齐全，也不宣称全流程或课程完成。',
        '\n## 可追溯数据图', '以下均为DATA PLOT，不是Sentaurus Visual原生导出或真实GUI截图。']
    for row in figures['created']:
        png = next(x['file'] for x in row['files'] if x['file'].endswith('.png'))
        lines += [f"![{row['name']}](figures/{png})", f"{row['description']} [来源及哈希](figures/{row['sources']})。"]
    if figures['skipped']:
        lines += ['未生成项：', *[f"- {r['plot']}：{r['reason']}" for r in figures['skipped']]]
    lines += ['\n## 课程材料与边界',
        '[课程草案索引](materials/index.md)覆盖可行性、设计、进度、参数来源、联合链路和总结入口。实际2–3学生分工、教师审核、实验室交接、答辩、考核均待人工真实证据。',
        '这是未校准二维1T1C探索模型；理想钳位初态不代表实际写入校准，判据误读不等于持久位翻转，不外推商业DRAM辐射截面。']
    if summary['errors']:
        lines += ['\n## 未解决证据错误', *['- ' + tag + ': ' + str(error).replace('\n', ' ') for tag, error in summary['errors'].items()]]
    # Preserve contiguous Markdown tables/list items while separating prose.
    blocks = []
    for line in lines:
        if blocks and ((line.startswith('|') and blocks[-1].splitlines()[-1].startswith('|'))
                       or (line.startswith('- ') and blocks[-1].splitlines()[-1].startswith('- '))):
            blocks[-1] += '\n' + line
        else:
            blocks.append(line)
    return '\n\n'.join(blocks) + '\n'


def write_snapshot(summary, output, plots=True):
    output = repo(output)
    allowed = DEV if summary.get('synthetic_fixture') else HERE / 'data/reporting'
    if not output.is_relative_to(allowed) or output == allowed or output.exists():
        raise ValueError('Require a new immutable snapshot directory within the permitted scope')
    if not summary.get('synthetic_fixture') and summary.get('source_code_sha256') != reporting_manifest():
        raise ValueError('Report sources changed between collection and rendering')
    # Fail before any output if the requested rendering dependency is unavailable.
    plotter = module(BASE / 'plot_results.py', 'plots') if plots else None
    summary = dict(summary, rendering_environment={'python': sys.version, 'matplotlib': plotter.matplotlib.__version__ if plotter else None,
        'numpy': plotter.np.__version__ if plotter else None, 'native_visual': False})
    output.mkdir(parents=True)
    write_json(output / 'summary.json', summary)
    csv_write(output / 'responses.csv', summary['responses'])
    csv_write(output / 'statistics.csv', summary['statistics']['strata'])
    fields = ['run_id', 'archive_sha256', 'gate_length_um', 'stored_bit', 'neutral', 'target_V', 'initial_SN_V', 'initial_error_mV']
    csv_write(output / 'initial-state.csv', [dict(zip(fields, (rid, a['archive_sha256'], a['parameters']['gate_length_um'], a['parameters']['stored_bit'],
        a['parameters']['neutral'], a['parameters']['target_voltage_V'], a['initial_SN_V'], a['initial_error_V'] * 1000))) for rid, a in summary['audited_runs'].items()], fields)
    write_json(output / 'sources.json', {'summary_sha256': sha(output / 'summary.json'), 'source_files_sha256': summary['source_files_sha256'],
        'source_code_sha256': summary.get('source_code_sha256', {}), 'audited_run_archives': {rid: a['archive_sha256'] for rid, a in summary['audited_runs'].items()}})
    figures = plotter.plot_snapshot(output) if plotter else {'created': [], 'skipped': [{'plot': 'all', 'reason': 'Explicit --no-plots; CSV/JSON only'}]}
    folder = output / 'materials'
    folder.mkdir()
    write_json(folder / 'index.json', {'schema': 'r50-main-course-draft', 'physical_revision': REVISION, 'human_items': summary['course_pending'],
        'native_visual': 'UNREVIEWED_OR_MISSING', 'natural_language_student_demo': 'PENDING', 'report_state': summary['report_state']})
    text = ('# R50-main 课程材料草案\n\n' + ('**SYNTHETIC，仅软件验证。**\n\n' if summary['synthetic_fixture'] else '')
        + '| 材料 | 证据入口与状态 |\n| --- | --- |\n'
        + '| 可行性与设计 | 冻结design/plan哈希见../sources.json；完整预算不保证本窗口完成 |\n'
        + '| 参数来源 | schema/revision及参数合同见../summary.json；唯一50 Ω物理修订 |\n'
        + '| 设计与实际进度 | ../responses.csv固定128槽位；../statistics.csv固定N=4 |\n'
        + '| Geant4–TCAD链路 | 同版本原始归档、源证据、匹配基准哈希见../summary.json |\n'
        + '| 图表及报告 | ../figures/index.json；../report.md；DATA PLOT不能代替原生图 |\n'
        + '| 自然语言参数演示 | 本报告未核验R50演示，不复用旧版完成声明 |\n'
        + '| 拟合/外推/氧化层/native | 此报告版本未审查接口，均保持未审查/缺失 |\n'
        + '| 人工课程事项 | 实际2–3学生分工、教师审核、资源交接、答辩、考核均PENDING |\n')
    (folder / 'index.md').write_text(text, encoding='utf8')
    (output / 'report.md').write_text(render(summary, figures), encoding='utf8')
    files = {p.relative_to(output).as_posix(): sha(p) for p in output.rglob('*') if p.is_file()}
    write_json(output / 'snapshot-manifest.json', {'schema': 'r50-main-report-output-manifest', 'physical_revision': REVISION,
        'synthetic_fixture': summary['synthetic_fixture'], 'files_sha256': files, 'native_evidence': False})
    return {'snapshot': str(output), 'state': summary['report_state'], 'summary_sha256': sha(output / 'summary.json'),
            'source_errors': len(summary['errors']), 'new_solver_calls': 0, 'new_ledger_charges': 0, 'png_count': len(figures['created'])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design', required=True, type=Path)
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--stage-index', type=Path)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--no-plots', action='store_true')
    args = parser.parse_args()
    reporting_manifest()
    summary = collect(args.design, args.ledger, args.stage_index)
    result = write_snapshot(summary, args.snapshot, not args.no_plots)
    print(json.dumps(result, indent=2))
    return 2 if summary['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
