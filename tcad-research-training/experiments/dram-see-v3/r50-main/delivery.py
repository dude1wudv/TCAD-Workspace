"""Read-only R50-main evidence review and exclusive, honest course snapshots.

No controller, runner, transport or GUI entry point is imported or invoked.
Small named pure functions are extracted from frozen sources with an explicit
namespace. Model reconstruction is audit-only and uses frozen training rows.
"""
import argparse
import ast
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import tarfile
from types import SimpleNamespace
import zlib

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
LOCAL = ROOT / 'local_runtime/dram-see-v3'
DEV = LOCAL / 'r50-delivery-dev'
SCHEMA = 'dram-see-v3-r50-main'
REVISION = 'r50-main-r1'
DESIGN_SHA = '6d52749bb8b9716b13b5ff1aa562a3ee331e3d7a062f32287c23710a5d1cf740'
NATIVE_TAGS = ('v3-r50-main-physical-l018-b1', 'v3-r50-main-l018-alpha-a30-s202610311-b1')
MANIFESTS = ('source-manifest.json', 'followup-source-manifest.json', 'extensions-source-manifest.json',
             'reporting-manifest.json', 'gui-source-manifest.json')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def repo(path):
    result = (ROOT / path).resolve()
    if not result.is_relative_to(ROOT):
        raise ValueError('Path escapes repository')
    return result


def rel(path):
    return repo(path).relative_to(ROOT).as_posix()


def module(path, name):
    spec = importlib.util.spec_from_file_location('_delivery_' + name, path)
    result = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), str(path), 'exec'), result.__dict__)
    return result


def pure(path, names, namespace):
    """Execute only the named, reviewed function definitions, never module IO."""
    tree = ast.parse(Path(path).read_bytes())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes} != set(names):
        raise ValueError('Pure source function set changed')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def utc(value):
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if instant.utcoffset() != timedelta(0):
        raise ValueError('Require an explicit absolute UTC timestamp')
    return instant


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same(actual, expected, message):
    require(actual == expected, message)


def sources():
    path = HERE / 'delivery-source-manifest.json'
    value = json.loads(path.read_bytes())
    require(value.get('schema') == SCHEMA + '-delivery-sources' and value.get('design_sha256') == DESIGN_SHA,
            'Wrong delivery source manifest')
    expected = {}
    for filename in MANIFESTS:
        frozen = json.loads((HERE / filename).read_bytes())
        for name, digest in frozen['files_sha256'].items():
            require(name not in expected or expected[name] == digest, 'Dependency manifests conflict: ' + name)
            expected[name] = digest
        expected[rel(HERE / filename)] = sha(HERE / filename)
    for filename in ('delivery.py', 'delivery-implementation.md'):
        expected[rel(HERE / filename)] = sha(HERE / filename)
    same(value['files_sha256'], expected, 'Delivery fixed dependency inventory differs')
    for name, digest in value['files_sha256'].items():
        same(sha(repo(name)), digest, 'Delivery dependency changed: ' + name)
    return {**value['files_sha256'], rel(path): sha(path)}


def interfaces(design):
    """Explicit pure adapters preserve the registered selector and case order."""
    report = module(HERE / 'reporting.py', 'reporting')
    prediction = module(HERE / 'prediction.py', 'prediction')
    numerical = module(HERE / 'numerical.py', 'numerical')
    scope = {'C': SimpleNamespace(safe_tag=lambda v: v.replace('.', 'p')), 'BASE': BASE,
             'rel': rel, 'design': lambda: design}
    pure(HERE / 'controller.py', ('control_tag', 'neutral_tag', 'event_tag', 'refined_tag', 'event_path', 'target_event', 'cases'), scope)
    r = SimpleNamespace(**{name: scope[name] for name in ('control_tag', 'neutral_tag', 'event_tag', 'refined_tag', 'event_path', 'target_event')}, design=lambda: design)
    follow = pure(HERE / 'finish.py', ('cases',), {'R': r, 'rel': rel})
    ext = pure(HERE / 'extensions.py', ('oxide_events', 'oxide_control', 'oxide_neutral', 'oxide_tag', 'cases'),
               {'R': r, 'C': scope['C'], 'rel': rel})
    selector = pure(BASE / 'numerical.py', ('boundary_ranking',), {'_number': numerical._number})['boundary_ranking']
    png = pure(HERE / 'gui_evidence.py', ('_png',), {'zlib': zlib})['_png']
    return SimpleNamespace(B=report, P=prediction, N=numerical, R=r, first=scope['cases'](design),
                           test=follow['cases'](), ext=ext, ranking=selector, png=png)


class Review:
    def __init__(self, design, ledger, interface, evidence):
        self.d, self.ledger, self.i, self.ev = design, ledger, interface, evidence
        self.reader = interface.B.RawReader(ledger, evidence)
        self.errors, self.gates, self.plans, self.measured, self.observations = {}, {}, {}, {}, {}
        self.comparisons = []

    def attempt(self, name, path, action):
        if path is None or not repo(path).exists():
            self.gates[name] = {'state': 'MISSING', 'path': rel(path) if path else None}
            return None
        try:
            value = action(repo(path))
            self.gates[name] = {'state': 'VERIFIED', 'path': rel(path), 'sha256': self.ev.bind(path) if path.is_file() else None}
            return value
        except (ValueError, KeyError, OSError, TypeError, tarfile.TarError) as exc:
            self.errors[name] = type(exc).__name__ + ': ' + str(exc)
            self.gates[name] = {'state': 'EVIDENCE_ERROR', 'path': rel(path), 'reason': self.errors[name]}
            return None

    def hashes(self, mapping):
        for name, digest in mapping.items():
            same(self.ev.bind(repo(name)), digest, 'Bound evidence changed: ' + name)

    def plan(self, path, kind, expected=None):
        value = self.ev.read_json(path)
        schemas = {'first': '-execution-plan', 'followup': '-followup-plan', 'extension': '-extensions-plan'}
        same(value.get('schema'), SCHEMA + schemas[kind], 'Wrong ' + kind + ' plan schema')
        same(value.get('physical_revision'), REVISION, 'Wrong plan physical revision')
        same(value.get('design_sha256'), DESIGN_SHA, 'Wrong plan science design')
        same(self.ev.read_json(path.with_name('plan-sha256.json')).get('sha256'), self.ev.bind(path), 'Plan self hash differs')
        self.hashes(value['source_sha256'])
        for name, digest in value['source_sha256'].items():
            same(self.ev.bind(path.parent / 'source-snapshot' / name), digest, 'Plan source snapshot differs')
        self.hashes(value['frozen_files_sha256'])
        accepted = value.get('acceptance', {})
        require(accepted.get('approved') is True and accepted.get('design_sha256') == DESIGN_SHA, 'Independent activation acceptance missing')
        manifest = {'first': 'source-manifest.json', 'followup': 'followup-source-manifest.json', 'extension': 'extensions-source-manifest.json'}[kind]
        same(accepted.get('source_manifest_sha256'), self.ev.bind(HERE / manifest), 'Accepted source manifest differs')
        if expected is not None:
            same(value.get('planned_cases'), expected, 'Plan cases differ from exact registered recipes')
        before = self.ev.read_json(repo(value['ledger_before']))
        same(self.ev.bind(repo(value['ledger_before'])), value['ledger_before_sha256'], 'Pre-plan ledger changed')
        for key, old in before.items():
            if key not in ('runs', 'failures'):
                same(self.ledger.get(key), old, 'Global original ledger section changed: ' + key)
        for tag, old in before['runs'].items():
            same(self.ledger['runs'].get(tag), old, 'Protected old ledger record changed: ' + tag)
        same(self.ledger.get('failures', [])[:len(before.get('failures', []))], before.get('failures', []), 'Failure history changed')
        self.plans[kind] = (path, value)
        return value

    def case(self, case, kind):
        """Only complete VERIFIED raw; incomplete/failed rows are never opened."""
        tag = case['tag']; row = self.ledger['runs'].get(tag, {})
        if row.get('state') != 'VERIFIED':
            return None
        path, plan = self.plans[kind]
        bundle = self.reader.load(tag)
        require(bundle is not None, 'Raw audit unavailable: ' + tag)
        require(row.get('continuous_numeric_valid') is not False and row.get('continuous_numerical_status') in self.i.B.CONTINUOUS,
                'Known continuous numerical failure/unknown state: ' + tag)
        p = bundle['parameters']; kw = {'length': .25, 'bit': 1, 'neutral': False, 'step': 1., 'mesh': 1., 'oxide_nm': 5., 'reference': 'offline', **case['kwargs']}
        parent = self.ledger['runs'].get(case.get('parent_tag'), {}).get('run_id') if case.get('parent_tag') else None
        expected = {'gate_length_um': kw['length'], 'stored_bit': None if kw['neutral'] else kw['bit'], 'neutral': kw['neutral'],
                    'step_scale': kw['step'], 'mesh_scale': kw['mesh'], 'oxide_nm': kw['oxide_nm'], 'reference_mode': kw['reference'],
                    'source_event': kw.get('event'), 'parent_run': parent, 'target_voltage_V': .5 if kw['neutral'] else .1 if kw['bit'] == 0 else .9}
        same({key: p.get(key) for key in expected}, expected, 'Actual case recipe differs: ' + tag)
        if case.get('event'):
            event = case['event']; folder = self.i.R.event_path(event).parent
            same({key: p.get(key) for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'energy_MeV')},
                 {key: event[key] for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'energy_MeV')}, 'Actual event identity differs')
            expected_source = {'source-' + name: self.ev.bind(folder / name) for name in ('event.json', 'events.csv', 'steps.csv')}
            same(p.get('source_evidence_sha256'), expected_source, 'Case did not preserve the three fixed G4 bytes')
        else:
            require(not p.get('source_event') and not p.get('particle') and p.get('charge_pc') == 0 and not p.get('source_evidence_sha256'), 'Control contains a source')
        file = path.parent / 'case-freezes' / (tag + '.json'); frozen = self.ev.read_json(file)
        key = {'first': 'main_plan_sha256', 'followup': 'followup_plan_sha256', 'extension': 'extension_plan_sha256'}[kind]
        same(frozen.get(key), self.ev.bind(path), 'Case plan binding differs')
        same(frozen.get('case'), case, 'Case frozen recipe differs')
        same(frozen.get('source_sha256'), plan['source_sha256'], 'Case source binding differs')
        same(frozen.get('inputs'), {tag: row['input_sha256']}, 'Prepared input hashes differ')
        same(row.get('execution_freeze'), rel(file), 'Ledger case path differs')
        same(row.get('execution_freeze_sha256'), self.ev.bind(file), 'Ledger case hash differs')
        if kind in ('followup', 'extension'):
            same(frozen.get('prediction_freeze_sha256'), self.ev.bind(HERE / 'data/predictions/freeze.json'), 'Case predates/bypasses actual prediction freeze')
        if kind == 'extension':
            require(row.get('deterministic_extension_only') is True, 'Extension role missing')
        return bundle

    def observation(self, tag, control, neutral):
        bundles = [self.reader.load(t) for t in (tag, control, neutral)]
        require(all(b is not None for b in bundles), 'Matched complete triple unavailable: ' + tag)
        metrics = self.reader.metrics.compute_curves(*bundles)
        audit = self.reader.metrics.audit_module
        return {'metrics': metrics, 'readout_BL_V': {role: audit.sample(b['circuit'], 'v(bl)', 4e-9)
                for role, b in zip(('signal', 'control', 'neutral'), bundles)}}

    def main(self, stage_index):
        stages, note = self.i.B.stage_proofs(stage_index, self.ev) if stage_index and repo(stage_index).exists() else ({}, 'Missing first stage index')
        self.gates.update(self.i.B.reference_checks(self.d, self.reader, stages, self.ev, self.errors))
        self.comparisons, self.gates['numerical_preregistered'] = self.i.B.numerical_checks(self.d, self.reader, stages, self.ev, self.errors)
        for event in self.d['events']:
            for bit in (0, 1):
                tag = self.i.R.event_tag(event, bit)
                triple = (tag, self.i.R.control_tag(event['gate_length_um'], bit), self.i.R.neutral_tag(event['gate_length_um']))
                if any(self.reader.load(t) is None for t in triple):
                    continue
                try:
                    self.i.B.check_slot(self.reader.bundles[tag]['parameters'], event, bit)
                    observed = self.observation(*triple)
                    self.measured[tag], self.observations[tag] = observed['metrics'], observed
                except (ValueError, KeyError) as exc:
                    self.errors[tag] = str(exc)
        if 'first' in self.plans:
            good = []
            for case in self.i.first:
                try:
                    if self.case(case, 'first') is not None:
                        good.append(case['tag'])
                except (ValueError, KeyError, OSError) as exc:
                    self.errors[case['tag']] = str(exc)
            stage = stages.get('train', {}); body = stage.get('body', {})
            expected = [c for c in self.i.first if c['stage'] == 'train']
            declared = body.get('cases', [])
            complete = len(good) == 92 and stage.get('claimed_state') == 'VERIFIED'
            if complete:
                # The stage uses a tag -> raw source map, checked against current rows.
                same(set(declared), {c['tag'] for c in expected}, 'Training stage case set changed')
                for c in expected:
                    tag = c['tag']; metric_path = HERE / 'data/metrics' / (tag + '.json')
                    same(self.ev.read_json(metric_path), self.measured[tag], 'Saved training metric differs from raw')
                    same(declared[tag], {'state': 'VERIFIED', 'raw_audit_state': 'PASSED', 'run_id': self.ledger['runs'][tag]['run_id'],
                        'archive_sha256': self.reader.bundles[tag]['summary']['archive_sha256'], 'evidence': rel(metric_path),
                        'evidence_sha256': self.ev.bind(metric_path)}, 'Training stage raw case changed')
                same(body.get('training_response_ids'), [self.i.R.event_tag(e,b) for e in self.d['events'] if e['split']=='train' for b in (0,1)], 'Training64 identities changed')
                same((body.get('training_independent_events'), body.get('training_responses')), (32,64), 'Training stage counts changed')
            self.gates['train'] = {'state': 'VERIFIED' if complete and all(self.gates.get(k, {}).get('state') == 'VERIFIED' for k in ('references', 'pilot', 'numerical_preregistered')) else 'INCOMPLETE',
                'complete_first_cases': len(good), 'planned_first_cases': 92, 'claimed_state': stage.get('claimed_state')}
        return note

    def transport(self, event):
        """Raw validated G4 and collected operation, with no remote call."""
        event_audit = module(BASE / 'event_audit.py', 'event_audit')
        path = self.i.R.event_path(event)
        value = event_audit.validate_event(path, {key: event[key] for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'energy_MeV')})
        self.hashes({rel(path.parent / name): sha(path.parent / name) for name in ('event.json', 'events.csv', 'steps.csv')})
        operation = LOCAL / 'operations' / ('g4-' + event['label'])
        record = self.ev.read_json(operation / 'operation.json'); request = self.ev.read_json(operation / 'request.json')
        archive = operation / 'events.tar'; digest = self.ev.bind(archive)
        require(record.get('state') == 'VALIDATED' and record.get('exit_code') == 0 and record.get('collection_exit_code') == 0, 'G4 was not explicitly collected successfully')
        same(record.get('event_metadata_sha256'), self.ev.bind(path), 'G4 metadata binding differs')
        same(record.get('archive_sha256'), digest, 'G4 archive binding differs')
        same(value.get('operation_archive_sha256'), digest, 'G4 metadata original archive differs')
        same(record.get('request_sha256'), self.ev.bind(operation / 'request.json'), 'G4 request binding differs')
        for key in ('gate_length_um', 'particle', 'angle_deg', 'seed', 'energy_MeV'):
            same(request.get(key), event[key], 'G4 request identity differs')
        with tarfile.open(archive) as tf:
            members = tf.getmembers()
            require(len(members) == 3 and {m.name for m in members} == {'events.csv', 'steps.csv', 'transport-exit-code.txt'} and all(m.isfile() for m in members), 'G4 archive members differ')
            same(tf.extractfile('transport-exit-code.txt').read().strip(), b'0', 'G4 archive exit nonzero')
            for name in ('events.csv', 'steps.csv'):
                same(tf.extractfile(name).read(), (path.parent / name).read_bytes(), 'G4 CSV bytes changed')
        for name in ('command.sh', 'stdout.txt', 'stderr.txt', 'collection-command.txt', 'collection-stderr.txt'):
            self.ev.bind(operation / name)
        return value

    def prediction(self, folder):
        require(all(self.gates.get(name, {}).get('state') == 'VERIFIED' for name in ('references', 'pilot', 'numerical_preregistered', 'train')), 'Actual training/reference/pilot/numerical gates are incomplete')
        require('followup' in self.plans, 'Accepted followup plan missing')
        path, plan = self.plans['followup']; freeze_path = folder / 'freeze.json'
        frozen = self.ev.read_json(freeze_path); freeze_sha = self.ev.bind(freeze_path)
        same(frozen.get('schema'), SCHEMA + '-prediction-freeze', 'Wrong prediction schema')
        same(frozen.get('physical_revision'), REVISION, 'Wrong prediction revision')
        same(frozen.get('design_sha256'), DESIGN_SHA, 'Prediction science design differs')
        same(frozen.get('followup_plan_sha256'), self.ev.bind(path), 'Prediction followup binding differs')
        utc(frozen['frozen_utc'])
        self.ev.bind(folder / 'freeze.sha256')
        same((folder / 'freeze.sha256').read_text().strip(), freeze_sha, 'Prediction self hash differs')
        binding = self.ev.read_json(path.parent / 'prediction-binding.json')
        same(binding, {'freeze': rel(freeze_path), 'freeze_sha256': freeze_sha, 'followup_plan_sha256': self.ev.bind(path), 'frozen_utc': frozen['frozen_utc']}, 'Actual prediction binding differs')
        expected = {'training_independent_events': 32, 'training_responses': 64, 'test_independent_events': 32,
                    'test_paired_predictions': 64, 'models_per_bit_target': 4, 'test_responses_seen': 0}
        same({key: frozen.get(key) for key in expected}, expected, 'Frozen prediction counts/leakage declaration differs')
        names = ('models.json', 'training-data.json', 'test-inputs.json', 'predictions.json', 'ledger-snapshot.json', 'provenance.json')
        require({rel(folder / n) for n in names} <= set(frozen['files_sha256']), 'Prediction freeze omits artifacts')
        self.hashes(frozen['files_sha256'])
        train, test = (self.ev.read_json(folder / name) for name in ('training-data.json', 'test-inputs.json'))
        self.i.P._validated_rows(train, self.d, True); self.i.P._validated_rows(test, self.d, False)
        require(all(r.get('physical_revision') == REVISION for r in train + test), 'Predictor inputs contain another revision')
        by_event = {e['label']: e for e in self.d['events']}; transports = {}; required_frozen = set(plan['source_sha256']) | {rel(path)}
        for row in train + test:
            e = by_event[row['event_label']]; bit = row['stored_bit']; tag = self.i.R.event_tag(e, bit)
            if e['label'] not in transports:
                transports[e['label']] = self.transport(e)
                required_frozen.update(rel(self.i.R.event_path(e).parent / n) for n in ('event.json','events.csv','steps.csv'))
                required_frozen.update(rel(LOCAL / 'operations' / ('g4-'+e['label']) / n) for n in ('operation.json','request.json','events.tar','command.sh','stdout.txt','stderr.txt','collection-command.txt','collection-stderr.txt'))
            same(row['Qdep_fC'], transports[e['label']]['converted'][0]['charge_pc'] * 1000, 'Feature not actual G4 deposition')
            same(row.get('source_event_sha256'), self.ev.bind(self.i.R.event_path(e)), 'Frozen feature source differs')
            if e['split'] == 'train':
                obs = self.measured[tag]
                same(row['targets'], {'deltaQ_fC': obs['deltaQ_fC'], 'deltaM_mV': obs['deltaM_V'] * 1000}, 'Training target differs from raw matched archives')
                same(row['sources'], obs['sources'], 'Training raw source binding differs')
                same(row.get('classification'), obs['classification'], 'Frozen training classification was hidden/changed')
                same(row.get('metric_validity'), obs['validity'], 'Frozen training metric validity changed')
                require(self.i.B.numerical_status(tag, obs['M4_V'] * 1000, self.comparisons, self.ledger['runs'][tag], self.d)['continuous_valid'], 'Known continuous failure cannot train')
            else:
                control, neutral = self.i.R.control_tag(e['gate_length_um'], bit), self.i.R.neutral_tag(e['gate_length_um'])
                obs = self.observation(control, control, neutral)['metrics']
                same(row['sources'], {r: obs['sources'][r] for r in ('control', 'neutral')}, 'Predictor known-control source differs')
                sample = self.reader.metrics.audit_module.sample(self.reader.bundles[control]['circuit'], 'v(sn)', 2.8e-9)
                same(row['known_control'], {'M4_mV': obs['control_M4_V'] * 1000, 'hold_SN_V': sample}, 'Predictor known-control values differ')
            for source in row['sources'].values():
                required_frozen.update(rel(ROOT / 'local_runtime/runs' / source['run_id'] / n) for n in ('manifest.json','inputs.tar','results.tar'))
        require(required_frozen <= set(frozen['files_sha256']), 'Prediction freeze omits training/known-control/G4/code provenance')
        same(self.ev.read_json(folder / 'provenance.json').get('design_sha256'), DESIGN_SHA, 'Prediction provenance design differs')
        models = self.ev.read_json(folder / 'models.json')
        # Reconstruct ONLY from the frozen 64 training rows to verify every fold,
        # training-only scaler, coefficient and lambda. No test target is supplied.
        reconstructed = self.i.P.fit_models(train, self.d)
        same({k: v for k, v in models.items() if k != 'implementation'}, {k: v for k, v in reconstructed.items() if k != 'implementation'}, 'Model/CV/scaler was not fitted exclusively by the registered training algorithm')
        predictions = self.ev.read_json(folder / 'predictions.json')
        same(predictions, self.i.P.predict_inputs(models, test, self.d), 'Frozen predictions differ from coefficients/inputs')
        snapshot = self.ev.read_json(folder / 'ledger-snapshot.json'); provenance = self.ev.read_json(folder / 'provenance.json')
        same(provenance.get('ledger_snapshot_sha256'), self.ev.bind(folder / 'ledger-snapshot.json'), 'Exact frozen ledger bytes differ')
        same(provenance.get('source_sha256'), plan['source_sha256'], 'Predictor source provenance differs')
        same(provenance.get('test_responses_seen'), 0, 'Declared test leakage')
        for name in ('references', 'pilot', 'numerical_preregistered', 'train'):
            same(provenance.get('gates', {}).get(name, {}).get('state'), 'VERIFIED', 'Frozen gate incomplete')
        test_tags = {c['tag'] for c in self.i.test}
        for tag, row in snapshot['runs'].items():
            p = row.get('parameters', {})
            require(tag not in test_tags and not (p.get('physical_revision') == REVISION and p.get('source_event') and p.get('gate_length_um') in (.25, .45)), 'Actual test metadata exists in pre-freeze ledger')
            same(self.ledger['runs'].get(tag), row, 'Frozen training ledger record changed')
        self.test_metadata(frozen)
        return {'freeze': frozen, 'models': models, 'predictions': predictions, 'path': rel(freeze_path), 'sha256': freeze_sha}

    def test_metadata(self, frozen):
        """Inspect actual collected input metadata, never unknown response output."""
        fixed = {c['tag']: c for c in self.i.test}; extension = {}
        if 'extension' in self.plans:
            extension = {c['tag']: c for c in self.plans['extension'][1]['planned_cases']}
        seen = set(); instant = utc(frozen['frozen_utc'])
        for path in sorted((ROOT / 'local_runtime/runs').glob('*/manifest.json')):
            matches = [(t, r) for t, r in self.ledger['runs'].items() if r.get('run_id') == path.parent.name]
            # An active known case has no stable collected archive yet. Do not
            # read it; its main slot remains missing and cannot complete test.
            if matches and matches[0][1].get('state') not in self.i.B.FAILURES | {'VERIFIED'}:
                continue
            m = self.ev.read_json(path)
            # Even a failed solver submission has already consumed test input.
            # Inspect its stable input metadata; never inspect failed outputs.
            archive = path.parent / 'inputs.tar'; self.ev.bind(archive)
            with tarfile.open(archive) as tf:
                members = [x for x in tf.getmembers() if x.isfile() and Path(x.name).name == 'parameters.json']
                if not members and '-v3-' not in path.parent.name:
                    continue
                require(len(members) == 1, 'Ambiguous actual input metadata')
                data = tf.extractfile(members[0]).read(); p = json.loads(data)
                same(hashlib.sha256(data).hexdigest(), m.get('input_sha256', {}).get('parameters.json'), 'Actual input metadata SHA differs')
            if p.get('schema') != SCHEMA and p.get('physical_revision') != REVISION:
                continue
            self.i.B.identity(p)
            same(m.get('run_id'), path.parent.name, 'Actual manifest run identity differs')
            require(len(matches) == 1 and matches[0][1].get('parameters') == p, 'Actual R50 archive lacks unique exact ledger identity')
            tag, row = matches[0]
            if not p.get('source_event') or p.get('gate_length_um') not in (.25, .45):
                continue
            require(tag in fixed or tag in extension, 'Unplanned actual test-like archive')
            require(utc(row['started_utc']) > instant, 'Test submission was not strictly after prediction UTC')
            start = datetime.strptime(row['run_id'][:16], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            require(start + timedelta(seconds=1) > instant and start + timedelta(seconds=1) > utc(row['started_utc']), 'Runner identity predates freeze/dispatch')
            if tag in fixed:
                self.i.B.check_slot(p, fixed[tag]['event'], fixed[tag]['kwargs']['bit'])
                seen.add(tag)
        expected = {t for t in fixed if self.ledger['runs'].get(t, {}).get('state') == 'VERIFIED'}
        require(expected <= seen, 'Verified test lacks actual collected input metadata')

    def tests(self, prediction):
        path, plan = self.plans['followup']; valid = []
        for case in self.i.test:
            bundle = self.case(case, 'followup')
            if bundle is None:
                continue
            tag = case['tag']; m = self.measured[tag]
            same(self.ev.read_json(HERE / 'data/metrics' / (tag + '.json')), m, 'Saved test metric differs from raw')
            valid.append({'event_label': case['event']['label'], 'stored_bit': case['kwargs']['bit'], 'continuous_valid': True,
                'continuous_numerical_status': 'RAW_AUDIT_PASSED', 'targets': {'deltaQ_fC': m['deltaQ_fC'], 'deltaM_mV': m['deltaM_V'] * 1000},
                'classification': m['classification'], 'sources': m['sources']})
        file = path.parent / 'test-result.json'
        if not file.exists():
            return {'state': 'INCOMPLETE', 'observed_responses': len(valid), 'planned_responses': 64}
        result = self.ev.read_json(file)
        require(len(valid) == 64, 'Claimed test completion lacks all64 raw responses')
        for key, value in {'schema': SCHEMA + '-test-result', 'state': 'TEST_FINISHED_PENDING_EXTENSIONS', 'test_responses': 64,
                           'test_independent_events': 32, 'plan_sha256': self.ev.bind(path), 'prediction_freeze_sha256': prediction['sha256'], 'observations': valid}.items():
            same(result.get(key), value, 'Actual test result binding differs: ' + key)
        score_path = HERE / 'data/prediction-scores.json'; score = self.ev.read_json(score_path)
        same(result.get('evidence'), rel(score_path), 'Test scores path differs')
        same(result.get('evidence_sha256'), self.ev.bind(score_path), 'Test score hash differs')
        same(score, self.i.P.score_predictions(prediction['predictions'], valid, self.d), 'Original fixed-model score differs')
        return {'state': 'VERIFIED', 'observed_responses': 64, 'planned_responses': 64, 'original_score_sha256': self.ev.bind(score_path)}

    def extensions(self, path):
        require(self.gates.get('test', {}).get('state') == 'VERIFIED', 'Extensions require actual complete prediction/test gates')
        require(len(self.observations) == 128, 'Boundary population must be all128 main responses')
        population = [{'response_id': self.i.R.event_tag(e, b), 'event': e, 'stored_bit': b, 'state': 'VERIFIED',
            'M4_V': self.measured[self.i.R.event_tag(e, b)]['M4_V'], 'metric_sources': self.measured[self.i.R.event_tag(e, b)]['sources']}
            for e in self.d['events'] for b in (0, 1)]
        selection = self.i.ranking(population, self.d['numerical']['additional_count'], tuple(x / 1000 for x in self.d['thresholds_mV']))
        expected = self.i.ext['cases'](selection, self.d)
        plan = self.plan(path, 'extension', expected)
        same(plan['selection'], selection, 'Boundary selection changed from complete128 fixed ranking')
        same(plan['baseline'], self.observations, 'Extension frozen main baseline differs')
        first_path, _ = self.plans['first']; follow_path, _ = self.plans['followup']
        for key, value in {'first_plan_sha256': self.ev.bind(first_path), 'followup_plan_sha256': self.ev.bind(follow_path),
            'test_result_sha256': self.ev.bind(follow_path.parent / 'test-result.json'),
            'prediction_freeze_sha256': self.ev.bind(HERE / 'data/predictions/freeze.json')}.items():
            same(plan.get(key), value, 'Extension prerequisite binding differs: ' + key)
        reused = plan['reused_cases']; before = self.ev.read_json(repo(plan['ledger_before']))
        same(set(reused), {c['tag'] for c in expected if c['tag'] in before['runs']}, 'Extension reuse declaration differs')
        good = []; statuses = []
        for case in expected:
            tag = case['tag']; row = self.ledger['runs'].get(tag, {})
            if tag in reused:
                original = next((c for c in self.i.first if c['tag'] == tag and c['stage'] == 'numerical_preregistered'), None)
                require(original is not None, 'Extension reuse not preregistered')
                for key in ('kwargs', 'role', 'parent_tag'):
                    same(case[key], original[key], 'Reused case is not exact same role/bit/recipe')
                bundle = self.case(original, 'first')
                require(bundle is not None, 'Reused refinement raw missing')
                a = bundle['summary']; p = bundle['parameters']
                same(reused[tag], {'run_id': row['run_id'], 'archive_sha256': a['archive_sha256'],
                    'execution_freeze': row['execution_freeze'], 'execution_freeze_sha256': row['execution_freeze_sha256'],
                    'matching_contract_sha256': p['matching_contract_sha256'], 'mesh_sha256': a['mesh_sha256'],
                    'role': case['role'], 'reused': True, 'new_solver_charge_s': 0}, 'Reused source declaration changed')
            else:
                try:
                    bundle = self.case(case, 'extension')
                except (ValueError, KeyError, OSError) as exc:
                    # A bad boundary case must not hide an independently valid
                    # completed oxide stage. It still prevents overall completion.
                    self.errors[tag] = str(exc)
                    bundle = None
            if bundle is not None:
                good.append(tag)
            statuses.append({'tag': tag, 'run_id': row.get('run_id'), 'state': row.get('state', 'UNSUBMITTED'), 'raw_reviewed': bundle is not None,
                'reused': tag in reused, 'role': case['role'], 'stage': case['stage'], 'new_independent_event': False})
        return {'plan': plan, 'selection': selection, 'cases': statuses, 'complete_tags': good}

    def oxide(self, path, extension):
        plan = extension['plan']; ext = self.i.ext; expected = []; baseline = []
        planned = [c for c in plan['planned_cases'] if c['stage'] == 'oxide']
        require(len(planned) == 14 and all(c['tag'] in extension['complete_tags'] for c in planned), 'All14 oxide control/neutral/event raw cases are required')
        for event in ext['oxide_events'](self.d):
            for bit in (0, 1):
                identifier = self.i.R.event_tag(event, bit); old = self.observations[identifier]
                baseline.append({'response_id': identifier, 'event': event, 'stored_bit': bit, 'oxide_nm': 5., 'observation': old, 'reused': True})
                for thickness in (4., 6.):
                    tag = ext['oxide_tag'](event, bit, thickness)
                    obs = self.observation(tag, ext['oxide_control'](bit, thickness), ext['oxide_neutral'](thickness))
                    require(obs['metrics']['sources']['control']['mesh_sha256'] != old['metrics']['sources']['control']['mesh_sha256'], 'Oxide reused actual5nm mesh')
                    expected.append({'response_id': tag, 'main_response_id': identifier, 'event': event, 'stored_bit': bit, 'oxide_nm': thickness,
                        'observation': obs, 'differences_from_5nm': {k: obs['metrics'][k] - old['metrics'][k] for k in ('deltaQ_fC', 'D4_V', 'M4_V', 'control_D4_V', 'control_M4_V', 'deltaM_V')},
                        'baseline_classification': old['metrics']['classification'], 'classification': obs['metrics']['classification'], 'new_independent_event': False})
        value = self.ev.read_json(path)
        for key, wanted in {'schema': SCHEMA + '-oxide-sensitivity', 'physical_revision': REVISION, 'design_sha256': DESIGN_SHA, 'state': 'VERIFIED',
            'execution_plan': rel(self.plans['extension'][0]), 'execution_plan_sha256': self.ev.bind(self.plans['extension'][0]),
            'prediction_freeze_sha256': plan['prediction_freeze_sha256'], 'baseline_5nm': baseline, 'responses': expected, 'new_independent_events': 0,
            'new_response_count': 8, 'new_thicknesses': [4., 6.], 'included_in_length_prediction_scores': False}.items():
            same(value.get(key), wanted, 'Oxide evidence differs: ' + key)
        return value

    def boundary(self, path, extension):
        plan = extension['plan']; comparisons = []
        for target in extension['selection']['selected']:
            event, bit = target['event'], target['stored_bit']; identifier = self.i.R.event_tag(event, bit)
            for variation in self.d['numerical']['variations']:
                step, mesh = variation['step'], variation['mesh']; length = event['gate_length_um']
                names = (self.i.R.refined_tag(event, bit, step, mesh), self.i.R.control_tag(length, bit, step, mesh), self.i.R.neutral_tag(length, step, mesh))
                require(all(t in extension['complete_tags'] for t in names), 'Complete own matched refinements are required')
                refined = self.observation(*names)
                result = self.i.N.compare_observations(self.observations[identifier], refined, tuple(v / 1000 for v in self.d['thresholds_mV']),
                    self.d['gates']['numerical_readout_change_mV'] / 1000, self.d['gates']['numerical_deltaQ_change_fC'])
                comparisons.append({'response_id': identifier, 'event': event, 'stored_bit': bit, 'variation': variation, **result})
        value = self.ev.read_json(path); passed = all(c['continuous_passed'] for c in comparisons)
        for key, wanted in {'schema': SCHEMA + '-numerical-validation', 'physical_revision': REVISION, 'design_sha256': DESIGN_SHA,
            'stage': 'numerical_boundary', 'state': 'VERIFIED' if passed else 'NUMERICAL_FAILED', 'continuous_passed': passed,
            'classification_stable': all(c['classification_stable'] for c in comparisons), 'comparisons': comparisons,
            'selection': extension['selection'], 'reused_cases': plan['reused_cases'], 'new_independent_events': 0,
            'execution_plan': rel(self.plans['extension'][0]), 'execution_plan_sha256': self.ev.bind(self.plans['extension'][0])}.items():
            same(value.get(key), wanted, 'Boundary evidence differs: ' + key)
        scope = {'R': SimpleNamespace(design=lambda: self.d, A=self.reader.metrics.audit_module),
                 'read': self.ev.read_json, 'HERE': HERE}
        expected_status = pure(HERE / 'extensions.py', ('numerical_uncertainty',), scope)['numerical_uncertainty'](plan, comparisons)
        same(value.get('main_threshold_status'), expected_status, 'Boundary full128 uncertainty table differs')
        # Join only re-audited comparisons. Failure still propagates every threshold.
        self.comparisons += comparisons
        return value

    def native(self, folder, visual_review=None, targets=NATIVE_TAGS):
        review = self.ev.read_json(visual_review) if visual_review and repo(visual_review).exists() else None
        if review is not None:
            require(review.get('schema') == SCHEMA + '-visual-review' and review.get('physical_revision') == REVISION,
                    'Wrong explicit visual review record')
        result = []
        for tag in targets:
            row = self.ledger['runs'].get(tag, {}); file = folder / row.get('run_id', 'UNSUBMITTED') / 'evidence.json'
            if row.get('state') != 'VERIFIED' or not file.exists():
                result.append({'ledger_tag': tag, 'state': 'MISSING', 'visual_review': 'PENDING_ACTUAL_IMAGE_REVIEW'})
                continue
            value = self.ev.read_json(file); bundle = self.reader.load(tag)
            require(bundle is not None, 'Native target raw audit failed')
            case = next(c for c in self.i.first if c['tag'] == tag)
            require(self.case(case, 'first') is not None, 'Native accepted case missing')
            first_path = self.plans['first'][0]
            same(value.get('accepted_case_source'), {'plan_sha256': self.ev.bind(first_path),
                'case_freeze_sha256': self.ev.bind(first_path.parent / 'case-freezes' / (tag+'.json')), 'design_sha256': DESIGN_SHA}, 'Native accepted source binding differs')
            expected = {'schema': SCHEMA + '-native-field-evidence', 'physical_revision': REVISION, 'run_id': row['run_id'], 'ledger_tag': tag,
                'archive_sha256': bundle['summary']['archive_sha256'], 'condition': bundle['parameters'], 'tdr_member': 'final_access_des.tdr',
                'field': 'Abs(ElectricField-V)', 'field_units': 'V/cm', 'coordinate_units': 'um'}
            for key, wanted in expected.items():
                same(value.get(key), wanted, 'Native source/field declaration differs: ' + key)
            archive = ROOT / 'local_runtime/runs' / row['run_id'] / 'results.tar'
            with tarfile.open(archive) as tf:
                members = [m for m in tf.getmembers() if m.isfile() and Path(m.name).name == value['tdr_member']]
                require(len(members) == 1, 'Native TDR archive member ambiguous')
                digest = hashlib.sha256(tf.extractfile(members[0]).read()).hexdigest()
            same(bundle['summary'].get('tdr_sha256', {}).get('final_access_des.tdr'), digest, 'Audited final TDR binding differs')
            require(abs(bundle['summary'].get('final_time_s', 0) - 4e-9) <= 1e-18, 'Native final-time source differs')
            for key in ('tdr_sha256', 'remote_source_sha256_before_load', 'remote_source_sha256_after_capture'):
                same(value.get(key), digest, 'Native selected TDR hash differs')
            self.hashes(value['depended_source_files_sha256'])
            gui_manifest = self.ev.read_json(HERE / 'gui-source-manifest.json')
            same(value['depended_source_files_sha256'], {**gui_manifest['files_sha256'], rel(HERE / 'gui-source-manifest.json'): self.ev.bind(HERE / 'gui-source-manifest.json')}, 'Native source manifest differs')
            same(value.get('capture_helper_sha256'), self.ev.bind(BASE.parent / 'dram-see-v2/capture_guest_window.py'), 'Native capture helper differs')
            require({'final-field-native.png', 'own-window.png', 'view.tcl', 'own-pid.txt', 'native-proof.txt', 'visual.log'} <= set(value['files_sha256']), 'Native evidence files incomplete')
            for name, expected_sha in value['files_sha256'].items():
                require(Path(name).name == name and name != 'evidence.json', 'Native file escapes selected run')
                same(self.ev.bind(file.parent / name), expected_sha, 'Native file hash differs')
            for name in ('final-field-native.png', 'own-window.png'):
                same(self.i.png((file.parent / name).read_bytes(), name), value['image_dimensions'][name], 'Native PNG dimensions/CRC differ')
            same(value['image_dimensions']['final-field-native.png'], {'width': 1400, 'height': 1000}, 'Native export resolution differs')
            before, after = value['owned_launch_identity_before'], value['owned_launch_identity_after']
            require(before['pid'] == after['pid'] and before['start_ticks'] == after['start_ticks'], 'Captured owned PID identity changed')
            same(int((file.parent / 'own-pid.txt').read_text().strip()), before['pid'], 'Actual owned PID file differs')
            manifest = self.ev.read_json(ROOT / 'local_runtime/runs' / row['run_id'] / 'manifest.json')
            source = manifest['remote_directory']
            same(value['native_loaded_file'], source + '/final_access_des.tdr', 'Native loaded file is not the selected runner source')
            render_scope = pure(HERE / 'gui_evidence.py', ('render_tcl',), {})
            tcl, marker = render_scope['render_tcl'](source, before['cwd'], row['run_id'], digest)
            same((file.parent / 'view.tcl').read_bytes(), tcl.encode(), 'Actual native Tcl field/source/output differs')
            captures = re.findall(r'OWNED_WINDOW_CAPTURE pid=(\d+) window=(0x[0-9a-fA-F]+)L? width=(\d+) height=(\d+)', value['capture_stdout'])
            require(len(captures) == 1, 'Native unique capture record missing')
            pid, window, width, height = captures[0]
            same(int(pid), value['captured_process_identity']['pid'], 'Native captured process differs')
            same(window, value['window_id'], 'Native window ID differs')
            same({'width': int(width), 'height': int(height)}, value['image_dimensions']['own-window.png'], 'Captured window size differs')
            operation = repo(value['operation_directory'])
            process = pure(HERE / 'gui_evidence.py', ('parse_process',), {})['parse_process']
            for label, identity in (('owned-process-before', before), ('owned-process-after', after), ('captured-process-after', value['captured_process_identity'])):
                record = self.ev.read_json(operation / label / 'operation.json')
                same(record.get('exit_code'), 0, 'Owned process evidence command failed')
                same(self.ev.bind(operation / label / 'command.sh'), record['script_sha256'], 'Owned process evidence command differs')
                raw = operation / label / 'stdout.bin'; self.ev.bind(raw)
                same(process(raw.read_bytes(), identity['pid'], before['cwd']), identity, 'Actual process output differs from declaration')
            for label, expected_input in (('upload-view', self.ev.bind(file.parent / 'view.tcl')), ('upload-capture-helper', value['capture_helper_sha256'])):
                record = self.ev.read_json(operation / label / 'operation.json')
                require(record.get('exit_code') == 0 and record.get('stdin_sha256') == expected_input, 'Actual native uploaded script/helper differs')
            for label in ('source-hash-before', 'source-hash-after'):
                checked = self.ev.read_json(operation / label / 'operation.json')
                same(checked.get('exit_code'), 0, 'Remote selected TDR source verification failed')
                same(self.ev.bind(operation / label / 'command.sh'), checked['script_sha256'], 'Remote TDR verification command differs')
                output = operation / label / 'stdout.bin'; self.ev.bind(output)
                require(output.read_text().split() == [digest, source + '/final_access_des.tdr'], 'Actual remote TDR source hash differs')
            for kind in ('launch', 'capture'):
                record = value[kind + '_operation']; require(record.get('exit_code') == 0, 'Native operation nonzero')
                same(self.ev.read_json(operation / record['label'] / 'operation.json'), record, 'Native operation provenance differs')
                same(self.ev.bind(operation / record['label'] / 'command.sh'), record['script_sha256'], 'Native actual command differs')
            same((operation / value['capture_operation']['label'] / 'stdout.bin').read_text(encoding='utf8'), value['capture_stdout'], 'Native capture stdout differs')
            self.ev.bind(operation / value['capture_operation']['label'] / 'stdout.bin')
            proof = (file.parent / 'native-proof.txt').read_text(encoding='utf8')
            require(marker in proof.splitlines() and 'Abs(ElectricField-V)' in proof.split(), 'Native proof lacks run/TDR/field')
            same(value.get('visual_version_lines'), re.findall(r'[^\r\n]*Version [^\r\n]+', (file.parent / 'visual.log').read_text(errors='replace')), 'Native Visual version declaration differs')
            completion = self.ev.read_json(operation / 'completion.json')
            require(completion.get('state') == 'CAPTURED_PENDING_VISUAL_REVIEW' and completion.get('evidence') == rel(file)
                    and completion.get('evidence_sha256') == self.ev.bind(file), 'Actual native completion pointer differs')
            approved, rejected = False, False
            if review is not None:
                matches = [r for r in review.get('images', []) if r.get('run_id') == row['run_id']]
                require(len(matches) <= 1, 'Duplicate visual review')
                if matches:
                    checked = matches[0]
                    require(utc(checked['reviewed_utc']) >= utc(value['capture_operation']['finished_utc']), 'Visual review predates actual capture')
                    same(checked.get('evidence_sha256'), self.ev.bind(file), 'Visual review evidence hash differs')
                    same(checked.get('png_sha256'), {n: value['files_sha256'][n] for n in ('final-field-native.png', 'own-window.png')}, 'Visual review image hashes differ')
                    require(checked.get('reviewer') and checked.get('method') == 'actual_image_inspection', 'Visual review has no actual reviewer/method')
                    approved = checked.get('approved') is True and all(checked.get(k) is True for k in ('field_verified', 'units_verified', 'run_identity_verified', 'privacy_checked'))
                    rejected = not approved
            result.append({'ledger_tag': tag, 'run_id': row['run_id'], 'state': 'CAPTURED_VISUALLY_REVIEWED' if approved else 'VISUAL_REVIEW_REJECTED' if rejected else 'CAPTURED_PENDING_VISUAL_REVIEW',
                'evidence': rel(file), 'evidence_sha256': self.ev.bind(file), 'archive_sha256': value['archive_sha256'], 'tdr_sha256': digest,
                'files': {n: {'path': rel(file.parent / n), 'sha256': value['files_sha256'][n]} for n in ('final-field-native.png', 'own-window.png')},
                'visual_review': 'EXPLICIT_REVIEW_RECORDED' if approved else 'PENDING_ACTUAL_IMAGE_REVIEW', 'scope': value['scope']})
        return {'state': 'VERIFIED' if all(r['state'] == 'CAPTURED_VISUALLY_REVIEWED' for r in result) else 'PENDING_VISUAL_REVIEW' if all(r['state'].startswith('CAPTURED') for r in result) else 'INCOMPLETE', 'targets': result}


def effective_scores(summary, prediction, interface):
    observed = []
    for row in summary['responses']:
        if row['split'] == 'train' or row['status'] == 'missing':
            continue
        valid = row['status'] == 'measured' and row['numerical']['continuous_valid'] and not row.get('validation_pending')
        observed.append({'event_label': row['event_label'], 'stored_bit': row['stored_bit'], 'continuous_valid': valid,
            'status': row['status'], 'targets': {'deltaQ_fC': row['deltaQ_fC'], 'deltaM_mV': row['deltaM_mV']} if valid else {}})
    return interface.P.score_predictions(prediction['predictions'], observed, summary['design'])


def collect(design_path, ledger_path, stage_index, followup_plan, extension_plan, prediction_dir, native_root, visual_review=None):
    source_hashes = sources(); b = module(HERE / 'reporting.py', 'base')
    design = b.design_checked(design_path)
    same(repo(ledger_path), LOCAL / 'ledger.json', 'Only the unique global cost ledger is accepted')
    same(repo(prediction_dir), HERE / 'data/predictions', 'Prediction directory must be canonical R50-main')
    same(repo(native_root), HERE / 'figures/native', 'Native directory must be canonical R50-main')
    ev = b.Evidence(); ledger = ev.read_json(ledger_path); ev.read_json(design_path)
    ev.bind(HERE / 'plan.md')
    for file in ('docs/course-project-syllabus.md', 'reports/outline.md'):
        ev.bind(ROOT / file)
    interface = interfaces(design); r = Review(design, ledger, interface, ev)
    first_path = repo(stage_index).parent / 'plan.json' if stage_index else None
    r.attempt('first_plan', first_path, lambda p: r.plan(p, 'first', interface.first))
    r.attempt('followup_plan', followup_plan, lambda p: r.plan(p, 'followup', interface.test))
    # Read and validate the extension plan before test-input role inspection. It
    # cannot validate oxide/boundary until exact full-population checks below.
    ext_plan = r.attempt('extension_plan', extension_plan, lambda p: r.plan(p, 'extension'))
    allowed = {c['tag'] for c in interface.first + interface.test}
    if ext_plan:
        allowed.update(c['tag'] for c in ext_plan['planned_cases'])
    for tag, row in ledger['runs'].items():
        p = row.get('parameters', {})
        if (p.get('schema') == SCHEMA or p.get('physical_revision') == REVISION) and tag not in allowed:
            r.errors[tag] = 'Unplanned R50-main record retained outside the fixed main/accepted extension inventory'
    try:
        note = r.main(stage_index)
    except (ValueError, KeyError, OSError) as exc:
        note = 'First gate evidence error'; r.errors['first_gates'] = str(exc)
        r.gates['train'] = {'state': 'EVIDENCE_ERROR', 'reason': str(exc)}
    prediction = r.attempt('prediction_freeze', repo(prediction_dir) / 'freeze.json', lambda p: r.prediction(p.parent))
    if prediction:
        test = r.attempt('test', followup_plan, lambda p: r.tests(prediction))
        if test:
            r.gates['test'].update(test)
    else:
        r.gates['test'] = {'state': 'BLOCKED_PREDICTION_REVIEW'}
    extension = r.attempt('extension_prerequisites', extension_plan, r.extensions) if ext_plan else None
    oxide, boundary = None, None
    if extension:
        oxide = r.attempt('oxide', HERE / 'data/oxide/results.json', lambda p: r.oxide(p, extension))
        boundary = r.attempt('numerical_boundary', HERE / 'data/numerical/boundary.json', lambda p: r.boundary(p, extension))
        if boundary:
            r.gates['numerical_boundary'].update(state=boundary['state'], continuous_passed=boundary['continuous_passed'], classification_stable=boundary['classification_stable'])
    else:
        r.gates.update({k: {'state': 'MISSING_OR_BLOCKED'} for k in ('oxide', 'numerical_boundary')})
    native_rows = []
    for tag in NATIVE_TAGS:
        item = r.attempt('native:' + tag, native_root, lambda p, tag=tag: r.native(p, visual_review, (tag,)))
        native_rows += item['targets'] if item else [{'ledger_tag':tag, 'state':r.gates['native:'+tag]['state']}]
    native = {'state':'VERIFIED' if all(v['state']=='CAPTURED_VISUALLY_REVIEWED' for v in native_rows) else 'PENDING_OR_INCOMPLETE', 'targets':native_rows}
    r.gates['native'] = {'state': native['state']}
    r.errors.update(r.reader.errors)
    # An archive may have finite diagnostic values despite broken execution
    # provenance. Keep those values visible but never score/classify them as valid.
    diagnostic_ledger = json.loads(json.dumps(ledger))
    for tag, measured in r.measured.items():
        source_ids = {source.get('run_id') for source in measured['sources'].values()}
        matching_rows = [(t,row) for t,row in ledger['runs'].items() if row.get('run_id') in source_ids]
        if tag in r.errors or any(t in r.errors or row.get('continuous_numeric_valid') is False
                or row.get('continuous_numerical_status') not in b.CONTINUOUS for t,row in matching_rows):
            diagnostic_ledger['runs'][tag]['continuous_numeric_valid'] = False
            diagnostic_ledger['runs'][tag]['continuous_numerical_status'] = 'DELIVERY_PROVENANCE_ERROR'
    curves = {bundle['summary']['run_id']: b.display_curve(bundle) for bundle in r.reader.bundles.values() if bundle['parameters']['reference_mode'] == 'offline'}
    summary = b.assemble(design, diagnostic_ledger, r.measured, r.reader.audits, curves, r.comparisons, r.gates, b.global_budget(ledger), r.errors, ev.hashes)
    for row in summary['responses']:
        if row['numerical']:
            row['numerical']['boundary_followup'] = r.gates['numerical_boundary']['state']
    summary.update(schema=SCHEMA + '-delivery-snapshot', source_code_sha256=source_hashes, stage_index_note=note,
        numerical_comparisons=r.comparisons, oxide=oxide, numerical_boundary=boundary,
        extension_cases=extension['cases'] if extension else [], native_evidence=native,
        ledger_snapshot=ledger, ledger_snapshot_sha256=ev.bind(ledger_path), prediction_freeze=prediction,
        later_evidence={k: r.gates[k] for k in ('prediction_freeze', 'test', 'oxide', 'numerical_boundary', 'native')})
    summary['prediction_scores'] = effective_scores(summary, prediction, interface) if prediction else None
    scientific = ('references', 'pilot', 'numerical_preregistered', 'train', 'prediction_freeze', 'test', 'oxide', 'numerical_boundary')
    simulation_complete = summary['measured_main_responses'] == 128 and all(r.gates.get(k, {}).get('state') == 'VERIFIED' for k in scientific) and not r.errors
    summary['report_state'] = 'EVIDENCE_ERRORS_PARTIAL' if r.errors else 'SIMULATION_EVIDENCE_VERIFIED_PENDING_DELIVERY_REVIEW' if simulation_complete else 'PARTIAL_EVIDENCE_REVIEWED'
    summary['simulation_evidence_verified'] = simulation_complete
    summary['agent_materials_state'] = 'PENDING_SNAPSHOT_GENERATION'
    summary['course_state'] = 'PENDING_REAL_STUDENT_TEACHER_DEFENSE_ASSESSMENT'
    summary['data_plot_visual_review'] = 'PENDING_ROOT_ACTUAL_IMAGE_INSPECTION'
    summary['model_reconstruction_scope'] = 'Read-only audit from frozen64 training rows; no test target fitting, no new model/freeze or ledger mutation'
    summary['source_files_sha256'] = dict(ev.hashes)
    ev.stable(); same(source_hashes, sources(), 'Delivery source changed during collection')
    return summary


def write_json(path, value):
    with Path(path).open('x', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def materials(summary, output):
    """Agent-authored deliverables; never invent student or teacher activities."""
    folder = output / 'materials'; folder.mkdir()
    plan_link = (HERE / 'plan.md').as_posix(); design_link = (HERE / 'design.json').as_posix()
    status = summary['report_state']; synthetic = '**SYNTHETIC SOFTWARE FIXTURE — 非物理结果。**\n\n' if summary['synthetic_fixture'] else ''
    documents = {
        'feasibility.md': '# 可行性与范围\n\n'+synthetic+'目标是比较未校准二维1T1C在冻结64个独立硅入射事件下的配对0/1响应，并检查域内留出与域外预测。Windows控制、单VM许可证及串行求解复用原工具链。新R50支路只修改两侧导通预充为50 Ω；原100 Ω失败和probe保留且不并入新矩阵。\n\n预算统一86400 s，含旧版、probe、失败和所有验证；12小时窗口不是完成保证。真实预算与未结项见../summary.json。可行性不代表商业器件校准或课程验收。\n',
        'design-and-steps.md': '# 设计、步骤与进度\n\n'+synthetic+f'冻结[科学设计]({design_link})及[实施计划]({plan_link})。实际快照状态 `{status}`。\n\n1. 全新12个单器件基准/中性与8个物理参考。\n2. pilot8个主响应及2个源隔离，预登记完整匹配细化。\n3. 64训练响应后按8条件LOCO冻结四个bit/target模型和64条预测。\n4. 冻结后64测试响应，再14项氧化层、完整128中固定规则两边界响应细化。\n5. 两个预声明4 ns原生场及真实窗口，逐图检查后交付。\n\n各项已完成/失败/未提交以../responses.csv和../stage-verification.json为准。禁止根据输出换seed、改变阈值、删除失败或用细化增加独立样本。\n',
        'methods-and-ai.md': '# 方法、两端接口与AI披露\n\n'+synthetic+'Geant4三原始事件文件绑定粒子、5 MeV、0/30度方向、seed及几何；按3.6 eV/pair把真实电离沉积转Qdep，LET=Qdep/有限径迹，源归一因子固定1，实际TCAD源积分审计。氧化层只改变TCAD固定硅入射事件下的敏感性，不是新材料栈输运。\n\nΔQ在2.8 ns为Cstore(SN事件−SN对照)；D=BL信号−BL中性，M=(2b−1)D，ΔM=M对照−M事件在4 ns计算，另保留3.8–4 ns。2.5/5/10 mV全部报告。统计每层N=4，同事件两位不独立翻倍，Wilson最佳/最差包络保留未知。\n\nAI参与代码、可追溯核验、材料草拟；固定脚本执行数值步骤。未测对照效率，不宣称AI加速比。本材料不声明真实学生已阅读、操作、批准或独立答辩；模型和聊天服务具体版本需主代理按真实会话补充，不凭产品名称猜测。\n',
        'demonstration.md': '# 作品演示脚本（待实际执行）\n\n'+synthetic+'本文件是演示步骤，非现场完成记录。\n\n1. 展示冻结64事件/128位槽与参数来源，说明新R50物理版本。\n2. 展示限定自然语言请求→解析器→固定事件清单，并演示越界/未知参数拒绝；学生实际演示和R50入口映射验收待办，旧版本演示不能自动证明新入口通过。\n3. 任取已完成run，经sources.json定位G4三文件、TCAD inputs/results、raw审计及配对指标。\n4. 展示初态、0/1及中性读出、阈值窗口、统计区间；缺失数据不展示虚点。\n5. 若已通过，展示实际预测冻结UTC早于测试提交、域内与外推残差；否则说明阻塞。\n6. 区分DATA PLOT、SVisual原生导出及真实窗口；按实际目视记录解释色标、单位和run。\n\n建议现场使用已冻结真实归档并明示“预先运行”；本脚本不发起远端命令，不要求即时耗时求解。\n',
        'defense-outline.md': '# 答辩提纲与待办\n\n'+synthetic+'建议10–12页：题目/实际人员；课程目标；模型与参数；Geant4→TCAD；数值审计；自然语言接口；冻结统计与划分；真实结果/失败；预测验证；敏感性；结论/局限；证据入口。此为提纲，不是已完成答辩或已渲染幻灯片。\n\n应解释：为什么需中性曲线、临界与数值不确定的区别、预测未见测试响应的证据、氧化层不增独立N、原100 Ω失败为何保留、二维和理想初态为何不能推出商业DRAM截面或持久位翻转。\n\n真实2–3人分工、教师方案审核、资源交接、组内试讲、正式答辩和2–3教师验收待记录。评分按导师20%/报告20%/答辩演示60%，不预测成绩。\n',
        'handoff.md': '# 可复现资料交接\n\n'+synthetic+'报告入口../report.md；固定128槽../responses.csv；三阈值分层../statistics.csv；来源../sources.json；阶段../stage-verification.json；所有输出../snapshot-manifest.json。完整归档仍在受忽略local_runtime/runs，不复制许可证、密钥或商业文档。\n\n复核顺序：检查快照SHA清单→源码/设计→唯一ledger记录→COLLECTED原档及科学审计→匹配三联→冻结/提交时间→评分/扩展→PNG目视。任何新快照使用新目录，不覆盖本次。缺失原档则只说明无法复现，不能自动重跑。\n',
    }
    for name, content in documents.items():
        (folder / name).write_text(content, encoding='utf8')
    parameters = [
        ['L', '0.18/0.25/0.35/0.45', 'um', 'frozen design events', 'exploratory gate length; not process-node calibration'],
        ['Rpre_on', '50', 'ohm', 'R50 design physical_change + actual audited matching/model contracts', 'only physical change from100ohm; both signal/reference'],
        ['Rpre_off', '1e20', 'ohm', 'inherited frozen circuit', 'unchanged'],
        ['oxide', '5 baseline;4/6 controlled extension', 'nm', 'frozen oxide_extension', 'own geometry/mesh/control/neutral; same silicon-entry event'],
        ['SN0', '0.1/0.9;neutral0.5', 'V', 'controlled ideal initialization', 'not calibrated transistor write'],
        ['Cstore/Cbl', '10/100', 'fF', 'inherited uncalibrated lumped circuit', 'same for matched roles'],
        ['particles', 'alpha/proton;5;0/30', 'MeV;degree', 'design + actual event metadata', 'finite silicon track and geometric truncation retained'],
        ['thresholds', '2.5/5/10', 'mV', 'frozen design', 'all preserved; main5mV'],
        ['numerical tolerance', '0.5;0.01', 'mV;fC', 'frozen gates', 'complete matched step/mesh refinements'],
        ['source conversion', '3.6;factor1', 'eV/pair', 'frozen source contract', 'no output-dependent LET tuning'],
        ['budget', '86400 cumulative', 's', 'unique global ledger', 'failures/probe/old/validation included']]
    b = module(HERE / 'reporting.py', 'material_csv')
    b.csv_write(folder / 'parameter-sources.csv', [dict(zip(('parameter', 'value', 'units', 'source', 'limit'), r)) for r in parameters])
    index = {'schema': SCHEMA + '-agent-materials', 'physical_revision': REVISION, 'state': 'AGENT_DRAFT_MATERIALS_GENERATED',
             'technical_evidence_state': summary['report_state'], 'human_items': summary['course_pending'],
             'natural_language_actual_student_demo': 'PENDING_REAL_DEMONSTRATION_AND_R50_MAPPING_REVIEW',
             'data_plot_review': 'PENDING_ROOT_ACTUAL_IMAGE_INSPECTION', 'course_complete': False,
             'files': list(documents) + ['parameter-sources.csv'], 'grading': {'mentor': .2, 'report': .2, 'defense_demonstration': .6}}
    write_json(folder / 'index.json', index)
    lines = ['# 课程交付材料索引', synthetic, '以下是已生成的代理草稿；真实实验门槛、图片目视与人类课程活动分别验收。',
             *['- ['+name+']('+name+')' for name in index['files']],
             '\n实际课程事项：', *['- '+name+': '+state for name, state in summary['course_pending'].items()],
             '\n完整课程未通过；本程序不授予成绩，不替代学生阅读、研究判断或答辩。']
    (folder / 'index.md').write_text('\n\n'.join(lines)+'\n', encoding='utf8')
    return index


def render(summary, figures):
    label = '**SYNTHETIC SOFTWARE FIXTURE — 非物理结果。**\n\n' if summary['synthetic_fixture'] else ''
    lines = [label + '# R50-main证据与课程交付快照', f"UTC `{summary['generated_utc']}`，状态 `{summary['report_state']}`。",
        f"冻结64个独立事件、128个配对位响应；取得匹配指标{summary['measured_main_responses']}/128。0/1、氧化层和数值细化不增加独立事件数。原100 Ω、probe及诊断不并入本矩阵。",
        '这是未校准二维1T1C的条件模拟。理想初态不等于实际写入校准；判据误读不等于持久位翻转；不外推商业DRAM可靠性或辐射截面。',
        '| 5 mV分类 | 数量/128 |\n| --- | --- |\n'+'\n'.join(f'| {k} | {v} |' for k,v in summary['main_threshold_counts'].items()),
        '三阈值2.5/5/10 mV与每层计划N=4见[统计](statistics.csv)。失败、缺失、临界与数值不确定分别保留；Wilson95%最佳/最差包络使用计划分母，只有全部可判且零误读时才给单侧精确零事件上界。',
        '| 独立证据门槛 | 状态 |\n| --- | --- |\n'+'\n'.join(f"| {k} | {v['state']} |" for k,v in summary['stages'].items()),
        '预测只审计冻结64训练行、8条件LOCO、逐fold标准化和固定λ规则；实际64条预测的UTC与已收集测试输入元数据逐项比对。测试目标只用于固定预测评分，不调参。当前评分另传播已知连续数值失败；critical不自动排除连续量。',
        '氧化层固定14项、5 nm复用主响应；边界来自完整128主响应的预定距离排序，复用细化按唯一run绑定。近边界未完成两变体确认仍不确定，分类跨界和连续容差失败分别保留。',
        f"唯一全局账本当前已登记{summary['budget']['accounted_solver_s']:.2f}/86400 s，未结{len(summary['budget']['running_or_unsettled'])}项，费用缺项{len(summary['budget']['accounting_gaps'])}项。包含旧版/probe/失败；不把未结未来费用推作0。",
        '[完整槽位](responses.csv) · [阶段证据](stage-verification.json) · [所有来源](sources.json) · [代理课程材料](materials/index.md)',
        '以下为DATA PLOT；每图有来源和PNG/SVG哈希，均须主代理实际看图，不能代替原生场图或真实GUI窗口。']
    for item in figures['created']:
        png = next(x['file'] for x in item['files'] if x['file'].endswith('.png'))
        lines += [f"![{item['name']}](figures/{png})", item['description'] + f" [来源](figures/{item['sources']})；`PENDING_ROOT_ACTUAL_IMAGE_INSPECTION`。"]
    for row in (summary.get('native_evidence') or {}).get('targets', []):
        lines.append(f"原生目标 `{row['ledger_tag']}`：`{row['state']}`。")
        for name, item in row.get('files', {}).items():
            lines.append(f"[{name}]({repo(item['path']).as_posix()}) SHA256 `{item['sha256']}`。原生4 ns场与真实窗口只证明所声明范围，不能证明Workbench Run按钮流程。")
    if summary['errors']:
        lines += ['未解决证据错误：\n\n'+'\n'.join('- '+k+': '+str(v).replace('\n',' ') for k,v in summary['errors'].items())]
    lines += ['课程材料已生成草稿，真实2–3学生分工、教师审核、资源交接、答辩、考核与学生自然语言现场演示仍按真实待办。代理材料生成不等于课程全通过。']
    return '\n\n'.join(lines)+'\n'


def write_snapshot(summary, output, plots=True):
    output = repo(output); synthetic = summary.get('synthetic_fixture') is True
    allowed = DEV if synthetic else HERE / 'data/delivery'
    require(output.is_relative_to(allowed) and output != allowed and not output.exists(), 'Require a new exclusive snapshot inside the permitted scope')
    if not synthetic:
        same(summary['source_code_sha256'], sources(), 'Sources changed before snapshot')
        for name, digest in summary['source_files_sha256'].items():
            same(sha(repo(name)), digest, 'Input advanced before snapshot: ' + name)
    b = module(HERE / 'reporting.py', 'output')
    plotter = module(BASE / 'plot_results.py', 'plots') if plots else None
    output.mkdir(parents=True)
    summary = dict(summary, agent_materials_state='AGENT_DRAFT_MATERIALS_GENERATED',
                   rendering_environment={'python': sys.version, 'matplotlib': plotter.matplotlib.__version__ if plotter else None})
    write_json(output / 'summary.json', summary)
    b.csv_write(output / 'responses.csv', summary['responses'])
    b.csv_write(output / 'statistics.csv', summary['statistics']['strata'])
    b.csv_write(output / 'extension-cases.csv', summary['extension_cases'], ('tag','run_id','state','raw_reviewed','reused','role','stage','new_independent_event'))
    write_json(output / 'stage-verification.json', summary['stages'])
    if summary.get('prediction_scores'):
        b.csv_write(output / 'prediction-scores.csv', summary['prediction_scores']['scores'])
        b.csv_write(output / 'prediction-residuals.csv', summary['prediction_scores']['stratified_residuals'])
    write_json(output / 'sources.json', {'summary_sha256': sha(output / 'summary.json'), 'source_files_sha256': summary['source_files_sha256'],
        'source_code_sha256': summary['source_code_sha256'], 'audited_run_archives': {rid: a['archive_sha256'] for rid,a in summary['audited_runs'].items()}})
    figures = plotter.plot_snapshot(output) if plotter else {'created': [], 'skipped': [{'plot':'all','reason':'Explicit --no-plots'}]}
    write_json(output / 'figure-review-required.json', {'schema': SCHEMA + '-figure-review-required', 'state':'PENDING_ROOT_ACTUAL_IMAGE_INSPECTION',
        'kind':'DATA PLOT', 'figures':figures, 'native_separate': summary.get('native_evidence')})
    materials(summary, output)
    (output / 'report.md').write_text(render(summary, figures), encoding='utf8')
    files = {p.relative_to(output).as_posix(): sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
    write_json(output / 'snapshot-manifest.json', {'schema':SCHEMA+'-delivery-output', 'physical_revision':REVISION,
        'synthetic_fixture':synthetic, 'files_sha256':files, 'course_complete':False, 'new_solver_calls':0, 'new_ledger_charges':0})
    return {'snapshot':str(output), 'state':summary['report_state'], 'agent_materials_state':summary['agent_materials_state'],
            'source_errors':len(summary['errors']), 'new_solver_calls':0, 'new_ledger_charges':0, 'course_complete':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('design','ledger','stage-index','followup-plan','extension-plan','prediction-dir','native-root','snapshot'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--visual-review', type=Path)
    parser.add_argument('--no-plots', action='store_true')
    args = parser.parse_args()
    summary = collect(args.design,args.ledger,args.stage_index,args.followup_plan,args.extension_plan,args.prediction_dir,args.native_root,args.visual_review)
    print(json.dumps(write_snapshot(summary,args.snapshot,not args.no_plots),ensure_ascii=False,indent=2))
    return 2 if summary['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
