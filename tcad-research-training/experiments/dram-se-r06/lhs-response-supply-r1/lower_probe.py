"""Prepare a frozen 3x development probe after accepted same-primary 10x and 30x readouts."""

import argparse
from decimal import Decimal, localcontext
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, '/opt/tcad-autonomy/current')
import month_one_response as response
import month_one_supply as supply
import month_one_wave as wave
import r06_gate as gate
import scheduler_supply


def prepare(policy, prefix, publish):
    work = Path(policy['workspace'])
    contract = gate.read_reference(work, policy['scientific_gate']['contract'])
    manifest = gate.read_reference(work, contract['manifest'])
    cases = {case['case_id']: case for case in manifest['cases']}
    target = cases[f'{prefix}-x3-b1']
    case_id = target['case_id']
    task = case_id + '-supply-r1'
    state = Path(policy['state_dir'])
    intents = gate.read(state / 'runtime.json')['intents']
    _, queue = scheduler_supply._queue(gate, Path(policy['queue_file']))
    if case_id in response.claimed_cases(work, gate, contract, queue, intents):
        return 'already claimed'
    results = gate.path_at(work, contract['production_admissions_dir']).parent / 'results/case-acceptance'
    if (results / (case_id + '.json')).exists():
        return 'already reviewed'
    output = work / 'local_runtime/server-codex/r06-case-reconciliation-r1' / task

    def ref(path):
        return dict(path=path.relative_to(work).as_posix(), sha256=gate.sha(path))

    def store(path, raw):
        with TemporaryDirectory(dir=output) as temporary:
            staged = Path(temporary) / path.name
            staged.write_bytes(raw)
            wave._install(gate, staged, path)
        return ref(path)

    def freeze(name, document):
        return store(output / name, wave._json_bytes(document))

    earlier = [results / f'{prefix}-x{scale}-b1.json' for scale in (10, 30)]
    if not all(path.is_file() for path in earlier):
        return 'awaiting original 10x and 30x acceptance'
    gate.need(target['block'] == 'T' and target['split'] == 'development' and target['holdout'] is None
              and target['bracket_role'] == 'low_or_bracket' and target['scale_factor'] == 3,
              'Target is outside the frozen lower-probe design')
    refs = [ref(path) for path in earlier]
    records = [gate.read_reference(work, item) for item in refs]
    by_run = {intent['run_id']: key for key, intent in intents.items()}
    keys = [by_run[record['run_id']] for record in records]
    zero_key = by_run[records[0]['matched_zero_run_id']]
    for scale, path, record, key in zip((10, 30), earlier, records, keys, strict=True):
        binding = intents[key]['scientific_admission']
        previous = cases[path.stem]
        gate.need(binding['case_id'] == record['case_id'] == previous['case_id'] and
                  all(previous[name] == target[name] for name in
                      ('source_shape_id', 'profile_id', 'radiation_id', 'stored_bit', 'crn_group_id', 'deck_timing_version')) and
                  record['schema'] == 'tcad-r06-case-acceptance-v1' and record['status'] == 'accepted' and
                  record['scale_factor'] == previous['scale_factor'] == scale and record['readout_error'] == 0 and
                  Decimal(str(record['signed_read_margin_V'])) > 0 and record['manifest_sha256'] == contract['manifest']['sha256']
                  and all(record[name] == records[0][name] for name in
                          ('event_id', 'matched_zero_run_id', 'matched_zero_results_sha256', 'source_time_ns', 'deck_timing_version')),
                  'Prior feedback differs from the frozen same-primary lower probe')
    sys.path.insert(0, str(work / 'experiments/dram-se-r06/development-transport-first-wave-r1'))
    from read_production_pair_v3 import RUNS as run_root
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    native = [response._native(work, gate, intents, key, ref(run_root / intents[key]['run_id'] / 'manifest.json'))
              for key in [*keys, zero_key]]
    middle, high, zero = native
    primary = json.loads(middle[3]['provenance.json'])['source_primary_id']
    proof = json.loads(high[3]['provenance.json'])
    for record, event in zip(records, (middle, high), strict=True):
        gate.need(record['input_sha256'] == event[0]['input_sha256'] and record['results_sha256'] == event[0]['results_sha256']
                  and record['matched_zero_results_sha256'] == zero[0]['results_sha256']
                  and event[1]['event_id'] == record['event_id'] and
                  json.loads(event[3]['provenance.json'])['source_primary_id'] == primary and
                  event[3]['device.cmd'] == zero[3]['device.cmd'] and event[3]['cell_msh.tdr'] == zero[3]['cell_msh.tdr'],
                  'Collected event, native mesh or electrical control changed')
    with localcontext() as precision:
        precision.prec = 60
        expected = Decimal(proof['reintegrated_pairs']) / 10
        raw, rows, allocations, pairs = response._nodal(gate, high[3]['nodal-source.dat'], zero[3]['nodal-source.dat'],
                                                       high[5], Decimal('0.1'), expected)
    identity = {name: target[name] for name in ('case_id', 'block', 'profile_id', 'radiation_id', 'stored_bit', 'scale_factor')}
    decision = freeze('decision.json', dict(schema='tcad-r06-threshold-probe-decision-v1', **identity,
                      decision='run_frozen_low_probe', purpose='Measure the low-dose margin on the same primary and control.',
                      prior_acceptance=refs, prior_run_ids=[record['run_id'] for record in records],
                      source_primary_id=primary, event_id=records[0]['event_id'], matched_zero_run_id=zero[0]['run_id'],
                      threshold_bracket_observed=False, statistics_eligible=False))
    project = output / 'input'
    project.mkdir(mode=0o700, exist_ok=True)
    files = {**high[3], 'nodal-source.dat': raw, 'project.json': wave._json_bytes(dict(high[4], name=task)),
             'protocol.json': wave._json_bytes(dict(high[5], **identity, source=dict(high[5]['source'], scale_factor=3,
                      required_source_rows=rows, required_allocations=allocations, native_integral_qualified=False))),
             'provenance.json': wave._json_bytes(dict(proof, **identity, source=decision, evidence=[decision, *refs],
                      source_primary_id=primary, matched_zero_task_id=zero_key, probe_id='probe03',
                      previous_probe_run_id=high[0]['run_id'], reintegrated_pairs=pairs))}
    hashes = {name: store(project / name, data)['sha256'] for name, data in files.items()}
    relative = project.relative_to(work).as_posix()
    proposal = freeze('proposal.json', dict(schema='tcad-work-items-v1', tasks=[dict(id=task, backend='tcad',
                      project=relative, depends_on=[*keys, zero_key], requires=[], repair_of=None, repair_reason='')]))
    admission = freeze('admission.json', dict(high[1], **identity, task_id=task, project=relative,
                       input_sha256=hashes, event_provenance=ref(project / 'provenance.json'), created_at=high[0]['collected_utc']))
    entries = [dict(proposal=proposal, admission=admission, evidence=[*refs, decision, high[2], zero[2]])]
    check = wave.prepare_entries(policy, gate, entries, profiles={target['profile_id']}, post_p2=True, validate_only=True)
    gate.need(check['prepared'] == [task] and not check['blocked'], f'Original gate held the lower probe: {check}')
    batch = freeze('approved-supply.json', dict(schema=supply.INTAKE_SCHEMA, entries=entries, manifest_sha256=contract['manifest']['sha256']))
    return supply.publish_approval(policy, gate, batch) if publish else batch


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    print(prepare(gate.read(args.policy), args.prefix, args.publish))
