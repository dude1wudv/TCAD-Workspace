"""Post-prediction 4/6 nm sensitivity with the original registered silicon events."""
import argparse
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('_v3_numerical_for_oxide', HERE / 'numerical.py')
N = importlib.util.module_from_spec(_spec)
exec(compile((HERE / 'numerical.py').read_bytes(), str(HERE / 'numerical.py'), 'exec'), N.__dict__)
C, ROOT, LOCAL = N.C, N.ROOT, N.LOCAL


def event_tag(event, bit, oxide_nm):
    return C.safe_tag('v3-oxide-' + event['label'] + f'-b{bit}-ox{oxide_nm:g}')


def selected_events(design):
    extension = design['oxide_extension']
    return [next(event for event in design['events']
                 if event['gate_length_um'] == extension['length_um'] and event['particle'] == particle
                 and event['angle_deg'] == extension['angle_deg'] and event['replicate'] == extension['replicate'])
            for particle in extension['particles']]


def planned_cases(design, events):
    extension = design['oxide_extension']
    length = extension['length_um']
    cases = []
    for thickness in extension['oxide_nm']:
        if thickness == extension['baseline_nm']:
            continue
        controls = {bit: C.safe_tag(C.tag_base(length, bit, oxide=thickness)) for bit in extension['paired_bits']}
        neutral = C.safe_tag(C.tag_neutral(length, oxide=thickness))
        for bit, tag in controls.items():
            cases.append({'tag': tag, 'role': 'control', 'kwargs': {'length': length, 'bit': bit, 'oxide_nm': thickness},
                          'parent_tag': None, 'matching_tags': [], 'estimate_s': 600})
        cases.append({'tag': neutral, 'role': 'neutral', 'kwargs': {'length': length, 'neutral': True, 'oxide_nm': thickness},
                      'parent_tag': None, 'matching_tags': [], 'estimate_s': 600})
        for event in events:
            for bit in extension['paired_bits']:
                kwargs = {'length': length, 'bit': bit, 'oxide_nm': thickness,
                          'event': (HERE / 'data/geant4' / event['label'] / 'event.json').relative_to(ROOT).as_posix()}
                cases.append({'tag': event_tag(event, bit, thickness), 'role': 'event', 'kwargs': kwargs,
                              'parent_tag': controls[bit], 'matching_tags': list(controls.values()) + [neutral], 'estimate_s': 600})
    return cases


def main_matrix_complete(design):
    ledger = C.load()
    missing = [{'response_id': N.event_tag(event, bit),
                'state': ledger['runs'].get(N.event_tag(event, bit), {}).get('state', 'MISSING')}
               for event in design['events'] for bit in event['paired_bits']
               if ledger['runs'].get(N.event_tag(event, bit), {}).get('state') != 'VERIFIED']
    if missing:
        raise ValueError('Main matrix is not complete; oxide cannot replace unresolved responses: ' + json.dumps(missing))


def _finish(path, plan):
    N.check_plan(path)
    d = C.design()
    extension = d['oxide_extension']
    results = []
    baseline_sources = []
    for event in plan['context']['events']:
        for bit in extension['paired_bits']:
            identifier = N.event_tag(event, bit)
            baseline = N.original_observation(event, bit)
            if baseline != plan['context']['baseline'][identifier]:
                raise ValueError('Frozen 5 nm baseline changed during oxide extension')
            baseline_sources.append({'response_id': identifier, 'event': event, 'stored_bit': bit,
                                     'oxide_nm': extension['baseline_nm'], 'observation': baseline, 'reused': True})
            for thickness in extension['oxide_nm']:
                if thickness == extension['baseline_nm']:
                    continue
                observed = N.observation(C.resolve(event_tag(event, bit, thickness)),
                                        C.resolve(C.tag_base(extension['length_um'], bit, oxide=thickness)),
                                        C.resolve(C.tag_neutral(extension['length_um'], oxide=thickness)))
                if observed['metrics']['sources']['control']['mesh_sha256'] == baseline['metrics']['sources']['control']['mesh_sha256']:
                    raise ValueError('Different oxide thickness reused the 5 nm mesh bytes')
                changes = {key: N._number(observed['metrics'][key]) - N._number(baseline['metrics'][key])
                           for key in ('deltaQ_fC', 'D4_V', 'M4_V', 'control_D4_V', 'control_M4_V', 'deltaM_V')}
                results.append({'response_id': event_tag(event, bit, thickness), 'main_response_id': identifier,
                                'event': event, 'stored_bit': bit, 'oxide_nm': thickness,
                                'observation': observed, 'differences_from_5nm': changes,
                                'baseline_classification': baseline['metrics']['classification'],
                                'classification': observed['metrics']['classification'],
                                'new_independent_event': False})
    report = {'schema': 'dram-see-v3-oxide-sensitivity', 'state': 'VERIFIED',
              'design_sha256': plan['design_sha256'], 'execution_plan': Path(path).relative_to(ROOT).as_posix(),
              'execution_plan_sha256': C.sha(path), 'prediction_freeze_sha256': plan['context']['prediction_freeze_sha256'],
              'baseline_5nm': baseline_sources, 'responses': results,
              'new_thicknesses': [v for v in extension['oxide_nm'] if v != extension['baseline_nm']],
              'new_independent_events': 0, 'new_response_count': len(results),
              'parameter_source': extension['source'], 'transport_scope': extension['transport_scope'],
              'included_in_length_prediction_scores': False,
              'interpretation': 'Controlled TCAD oxide-thickness sensitivity at fixed silicon-entry events; raw criterion changes, no full-stack transport or calibrated process inference'}
    evidence = HERE / 'data/oxide/results.json'
    N._immutable_result(evidence, report)
    ledger = C.load()
    ledger['stages']['oxide'] = {'state': 'VERIFIED', 'utc': C.now(), 'evidence': evidence.relative_to(ROOT).as_posix(),
                               'evidence_sha256': C.sha(evidence), 'new_independent_events': 0,
                               'new_responses': len(results)}
    C.save(ledger)
    N._record_status(path, 'VERIFIED')
    return report


def execute(label='r1', limit=None):
    with C.controller_lock():
        d = C.design()
        C.check_preservation()
        C.check_prediction_freeze()
        N.require_stage('test')
        main_matrix_complete(d)
        path = N.stage_folder('oxide', label) / 'plan.json'
        if path.exists():
            plan = N.check_plan(path)
        else:
            events = selected_events(d)
            targets = [{'event': event, 'stored_bit': bit} for event in events for bit in d['oxide_extension']['paired_bits']]
            baseline, frozen = N._baseline_snapshot(targets)
            prediction = HERE / 'data/predictions/freeze.json'
            frozen[prediction.relative_to(ROOT).as_posix()] = C.sha(prediction)
            context = {'events': events, 'baseline': baseline, 'new_independent_events': 0,
                       'prediction_freeze_sha256': C.sha(prediction), 'extension': d['oxide_extension']}
            path, plan = N.freeze_plan('oxide', label, planned_cases(d, events), context, frozen)
        status = N.execute_cases(path, limit)
        if status['state'] != 'CASES_VERIFIED':
            return status
        return _finish(path, plan)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='r1')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    print(json.dumps(execute(args.label, args.limit), indent=2))
