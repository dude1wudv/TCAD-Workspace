#!/usr/bin/env python3
"""Offline analysis of two pinned old zero caches; no reader or solver import.

Decimal preserves cached decimal values, not precision absent from the cache.
Only --write modifies files, exclusively this package's evidence directory.
"""
import argparse
import csv
from decimal import Decimal as D, getcontext
import hashlib
import io
import json
from pathlib import Path

getcontext().prec = 50
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NS, REF = D('1e-9'), D('0.6')
SIGNALS = ('v(sn1)', 'v(sn2)', 'v(bl)', 'v(wl1)', 'v(wl2)', 'v(drive)')
TIMES = tuple(map(D, ('21', '22', '24')))
PINS = {
    0: {'extraction.json': '9cd425eb2edb56e4bd98cd223da82931425b6919185879b5c11f5af25abf3caa',
        'receipt.json': '398dd5b18b9f444283503a7e700e6763a4004c1b26faaa38a1c43db1fe16d731'},
    1: {'extraction.json': 'cb09f89a1db3913df2ac21cc88e6022190548b98a65364f705c3c8ffe6953160',
        'receipt.json': 'b35e320601fc93bd32c81f5ba6fd5bb91ed950e3a6f9fa543a6883aa521b7908'},
}


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    return json.loads(path.read_text(), parse_float=D)


def encode(value):
    def default(x):
        if isinstance(x, D):
            return str(x)
        raise TypeError(type(x).__name__)
    return (json.dumps(value, ensure_ascii=False, indent=2,
                       default=default, allow_nan=False) + '\n').encode()


def row_view(row, cache):
    # The frozen row-hash index normalizes E-08 to E-8; retain the trace's
    # original time token, and match only the index key numerically.
    token_hash = next((v for k, v in cache['canonical_row_token_sha256'].items()
                       if D(k) == D(row['time_token_s'])), None)
    return {'raw_row_1based': row['raw_row_1based'],
            'time_token_s': row['time_token_s'],
            'values_V': {k: row['values'][k] for k in SIGNALS},
            'cached_canonical_row_token_sha256': token_hash}


def sample(trace, ns, cache):
    target = ns * NS
    for i, row in enumerate(trace):
        time = D(row['time_token_s'])
        if time == target:
            return {'method': 'exact_cached_row', 'time_ns': ns,
                    'values_V': {k: row['values'][k] for k in SIGNALS},
                    'neighbors': [row_view(row, cache)], 'right_weight': D(0), 'bracket_width_ns': D(0)}
        if time > target:
            assert i > 0
            left = trace[i - 1]
            lt = D(left['time_token_s'])
            w = (target - lt) / (time - lt)
            assert 0 < w < 1
            return {'method': 'linear_interpolation_between_actual_cached_rows', 'time_ns': ns,
                    'values_V': {k: left['values'][k] + w * (row['values'][k] - left['values'][k]) for k in SIGNALS},
                    'neighbors': [row_view(left, cache), row_view(row, cache)],
                    'right_weight': w, 'bracket_width_ns': (time - lt) / NS,
                    'neighbor_secant_V_per_ns': {k: (row['values'][k] - left['values'][k]) / ((time - lt) / NS) for k in SIGNALS}}
    raise ValueError(f'Target outside cached trace: {ns} ns')


def window(trace, start, end, cache):
    left, right = sample(trace, start, cache), sample(trace, end, cache)
    middle = [r for r in trace if start * NS < D(r['time_token_s']) < end * NS]
    vals = [left['values_V']] + [r['values'] for r in middle] + [right['values_V']]
    out = {'start_ns': start, 'end_ns': end, 'start_method': left['method'],
           'end_method': right['method'], 'interior_actual_row_count': len(middle),
           'range_scope': 'cached rows plus interpolated endpoints, not a continuous-time bound', 'signals': {}}
    for k in SIGNALS:
        v = [r[k] for r in vals]
        out['signals'][k] = {'start_V': v[0], 'end_V': v[-1], 'delta_V': v[-1] - v[0],
                             'min_V': min(v), 'max_V': max(v), 'peak_to_peak_V': max(v) - min(v)}
    out['BL_max_abs_bias_from_0p6_V'] = max(abs(r['v(bl)'] - REF) for r in vals)
    return out


def inspect(bit):
    cache_dir = ROOT / f'local_runtime/dram-se-r04/mc2-zero-b{bit}-native-r1'
    hashes = {k: sha(cache_dir / k) for k in PINS[bit]}
    assert hashes == PINS[bit], 'Frozen cache hash changed'
    c, receipt = load(cache_dir / 'extraction.json'), load(cache_dir / 'receipt.json')
    assert receipt['extraction_sha256'] == hashes['extraction.json']
    assert c['provenance'] == receipt['provenance']
    assert c['mc2_reader_sha256'] == receipt['mc2_reader_sha256']
    assert c['synthetic'] is False and c['formal_training'] is False
    assert receipt['is_scientific_acceptance'] is False
    p = c['provenance']
    assert p['variant'] == 'zero' and p['stored_pattern'] == str(bit) * 2
    inputs = ROOT / p['input_directory']
    assert inputs.resolve().is_relative_to(ROOT / 'experiments/dram-se-r04')
    expected = p['input_sha256']
    assert set(expected) == {x.name for x in inputs.iterdir() if x.is_file()}
    actual = {k: sha(inputs / k) for k in expected}
    assert actual == expected == p['submission_intent']['input_sha256']
    protocol, old_prov = load(inputs / 'protocol.json'), load(inputs / 'provenance.json')
    assert old_prov['device_model_id'] == 'l08-saddle-fin-r04-baseline-v1'
    assert protocol['read']['sample_ns'] == D('31.9')
    assert c['clock_audit']['contract']['deck_sha256'] == actual['device.cmd']
    deck = (inputs / 'device.cmd').read_text()
    with (inputs / 'nodal-source.dat').open() as f:
        header = f.readline().strip()
        counts = {}
        source_units = None
        for line in f:
            if line.strip() and not line.startswith('#'):
                key = line.split()[0]
                counts[key] = counts.get(key, 0) + 1
                if key == 'units':
                    source_units = line.strip()
    assert header == 'R04_NODAL_SOURCE 1 10170 0 0' and counts == {'units': 1, 'N': 10170}
    assert source_units == 'units um s cm3 cm^-3_s^-1 pairs'
    s = c['source']
    assert s['native_loaded_counts'] == ['10170', '0', '0'] and s['cache_zero_through_35ns'] is True
    assert all(D(x) == 0 for x in s['actual_native_generation_pairs'].values())
    assert all(D(x['native_generation_pairs']) == 0 for x in s['accepted_BE_steps'])
    pmi = (inputs / 'pmi_r04_nodal.C').read_text()
    lines = [{'line_1based': i, 'text': text.strip()} for i, text in enumerate(pmi.splitlines(), 1)
             if 'callbacks_' in text or '#include <atomic>' in text]
    assert 'std::atomic<std::uint64_t> callbacks_{0};' in pmi and 'r06-o2-global-r1' not in pmi
    tr = c['observations']['trace']
    t, raw = [D(r['time_token_s']) for r in tr], [r['raw_row_1based'] for r in tr]
    assert all(b > a for a, b in zip(t, t[1:])) and all(b > a for a, b in zip(raw, raw[1:]))
    assert t[0] == 0 and t[-1] == D('35') * NS
    clock = c['clock_audit']
    assert len(tr) == clock['accepted_BE_count'] + 1
    assert [D(r['end_s']) for r in clock['accepted_intervals']] == t[1:]
    assert all(D(r['values']['time']) == time for r, time in zip(tr, t))
    assert all(D(v).is_finite() for r in tr for v in r['values'].values())
    hash_times = [D(k) for k in c['canonical_row_token_sha256']]
    assert len(hash_times) == len(set(hash_times))
    assert hash_times == t[1:]
    assert all(r['values']['v(wl1)'] == 0 and r['values']['v(wl2)'] == 0
               for r in tr if D('18.2') * NS <= D(r['time_token_s']) <= D('30') * NS)
    start, end, read = [sample(tr, D(x), c) for x in ('18.2', '30', '31.9')]
    margin = (1 if bit else -1) * (read['values_V']['v(bl)'] - REF)
    assert read['method'] == 'exact_cached_row'
    assert margin == D(c['observations']['signed_read_margin_decimal_V'])
    candidates = []
    for ns in TIMES:
        v = sample(tr, ns, c)
        v.update({'delay_to_read_ns': D('31.9') - ns,
                  'elapsed_since_WL1_release_ns': ns - D('18.1'),
                  'elapsed_since_drive_ramp_end_ns': ns - D('18.2'),
                  'BL_bias_from_0p6_V': v['values_V']['v(bl)'] - REF,
                  'BL_max_actual_neighbor_abs_bias_V': max(abs(r['values_V']['v(bl)'] - REF) for r in v['neighbors']),
                  'SN1_delta_from_18p2ns_V': v['values_V']['v(sn1)'] - start['values_V']['v(sn1)'],
                  'SN1_delta_to_30ns_V': end['values_V']['v(sn1)'] - v['values_V']['v(sn1)']})
        candidates.append(v)
    evidence = {'state': f'b{bit}', 'run_id': p['run_id'], 'task_id': p['task_id'],
                'cache_directory': str(cache_dir.relative_to(ROOT)), 'cache_sha256': hashes,
                'input_directory': p['input_directory'], 'input_sha256': actual,
                'historical_hashes_from_receipt_not_reaudited': {k: p[k] for k in
                    ('manifest_sha256', 'archive_sha256', 'inputs_archive_sha256', 'submission_intent_sha256')},
                'input_digest_from_frozen_intent': p['submission_intent']['input_digest'],
                'frozen_mc2_reader_sha256': receipt['mc2_reader_sha256'],
                'device_model_id': old_prov['device_model_id'], 'old_per_instance_atomic_log_lines': lines,
                'Optics_PMI_still_enabled': all(x in deck for x in ('access.Optics', 'PMIPath="."', 'pmiModel="pmi_r04_nodal"')),
                'source_header': header, 'source_record_counts': counts, 'source_units_directive': source_units,
                'native_source_cache': {k: s[k] for k in ('actual_native_generation_pairs', 'relative_error', 'native_loaded_counts',
                    'cache_zero_through_35ns', 'TDR_point_fields_decoded', 'all_assembly_calls_and_retry_rollback_verified')},
                'row_count': len(tr), 'accepted_BE_count': clock['accepted_BE_count'],
                'rejected_or_unconverged_attempt_count': len(clock['rejected_or_unconverged_attempts']),
                'excluded_zero_duration_event_count': len(clock['zero_duration_events']),
                'finite_values_strict_order_and_accepted_clock_alignment_verified': True,
                'legacy_plugin_segments': [x for x in clock['contract']['segments'] if x['plugin_required']],
                'protocol': {k: protocol[k] for k in ('assumptions', 'initialization', 'write', 'hold', 'read', 'transient')},
                'cache_status': c['status'], 'cache_pairing_status': c['pairing_status'], 'is_scientific_acceptance': False}
    result = {'state': f'b{bit}', 'run_id': p['run_id'],
              'windows': [window(tr, D(a), D(b), c) for a, b in
                          (('18.2', '30'), ('21', '24'), ('21', '30'), ('22', '30'), ('24', '30'))],
              'candidate_points': candidates,
              'readout_31p9ns': {'point': read, 'signed_BL_margin_V': margin, 'formula': 'Vbl-0.6' if bit else '0.6-Vbl'},
              'edge_observations': {k: row_view(v, c) for k, v in c['observations']['samples'].items() if k in
                  ('sn1_write_on_end', 'sn1_write_released', 'precharge_end', 'hold_end', 'after_isolation')}}
    selected = [row_view(r, c) for r in tr if D('18.2') * NS <= D(r['time_token_s']) <= D('30') * NS
                or D(r['time_token_s']) == D('31.9') * NS]
    return evidence, result, selected


def csv_data(rows):
    text = io.StringIO(newline='')
    writer = csv.DictWriter(text, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode()


def outputs():
    evidence, states, flat_candidates, flat_trace = [], [], [], []
    for bit in (0, 1):
        e, r, trace = inspect(bit)
        evidence.append(e)
        states.append(r)
        for v in r['candidate_points']:
            n = v['neighbors']
            flat_candidates.append({'state': f'b{bit}', 'time_ns': v['time_ns'], 'method': v['method'],
                'left_raw_row_1based': n[0]['raw_row_1based'], 'left_time_token_s': n[0]['time_token_s'],
                'right_raw_row_1based': n[-1]['raw_row_1based'], 'right_time_token_s': n[-1]['time_token_s'],
                **{k + '_estimate_V': v['values_V'][k] for k in SIGNALS},
                **{k: v[k] for k in ('BL_bias_from_0p6_V', 'BL_max_actual_neighbor_abs_bias_V',
                    'SN1_delta_from_18p2ns_V', 'SN1_delta_to_30ns_V', 'delay_to_read_ns')}})
        for v in trace:
            flat_trace.append({'state': f'b{bit}', 'raw_row_1based': v['raw_row_1based'], 'time_token_s': v['time_token_s'],
                **{k + '_V': v['values_V'][k] for k in SIGNALS}, 'cached_canonical_row_token_sha256': v['cached_canonical_row_token_sha256']})
    for name in ('cell_msh.tdr', 'pmi_r04_nodal.C', 'pmi_r04_nodal.so.linux64', 'protocol.json'):
        assert evidence[0]['input_sha256'][name] == evidence[1]['input_sha256'][name]
    pair = [{'time_ns': a['time_ns'],
             'SN1_b1_minus_b0_V': b['values_V']['v(sn1)'] - a['values_V']['v(sn1)'],
             'BL_b1_minus_b0_V': b['values_V']['v(bl)'] - a['values_V']['v(bl)']}
            for a, b in zip(states[0]['candidate_points'], states[1]['candidate_points'])]
    analysis = {'schema': 'dram-se-r06-old-zero-hold-window-observation-r1',
                'scope': 'old_r04_L08_p000_prototype_no_particle_observations_only',
                'units': {'time_token_s': 's', 'voltages': 'V', 'reported_times': 'ns'},
                'method': 'Original cached row order retained; Decimal arithmetic; linear interpolation explicitly marked with real neighbors.',
                'candidate_basis': 'P0-2 reference times 21/22/24ns; only zero caches read; no particle outcome selection.',
                'formal_timing_frozen': False, 'r06_D0_qualified': False, 'Z_completion_credit': 0,
                'formal_case_credit': 0, 'statistics_eligible': False, 'scientific_gate_status': 'not_evaluated',
                'states': states, 'cross_state_candidate_separation': pair,
                'limitations': ['Old r04 L08/p000 is not certified r06 D0.',
                    'Old per-instance atomic PMI and 15ns refresh/fine-step window are not new O2 or 22ns matched controls.',
                    '18.2ns ends the drive ramp; BL is still settling.',
                    'Candidate brackets up to 0.5ns and interpolation do not bound continuous-time or numerical error.',
                    '31.9ns destructive SN1 charge-sharing margin is not a persistent particle flip label.',
                    'Zero source has relative_error=null and cannot validate nonzero-source integral tolerance.',
                    'No mesh/time refinement, repeatability acceptance, new qualification or gate evaluation; old rejected attempts retained.']}
    return {'provenance.json': encode({'schema': 'dram-se-r06-old-zero-analysis-provenance-r1',
                                      'analyzer_sha256': sha(Path(__file__)), 'states': evidence}),
            'analysis.json': encode(analysis), 'candidate-points.csv': csv_data(flat_candidates),
            'actual-trace-selected.csv': csv_data(flat_trace)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--write', action='store_true', help='write deterministic evidence in this package only')
    group.add_argument('--check', action='store_true', help='recompute and byte-compare existing evidence without writing')
    args = parser.parse_args()
    data = outputs()
    for name, content in data.items():
        path = HERE / 'evidence' / name
        if args.write:
            path.write_bytes(content)
        else:
            assert path.read_bytes() == content, f'Generated evidence differs: {name}'
    print(json.dumps({'operation': 'write' if args.write else 'check', 'files': len(data),
                      'verified_cache_files': 4, 'verified_input_files': 32,
                      'scientific_gate_status': 'not_evaluated', 'Z_completion_credit': 0}))


if __name__ == '__main__':
    main()
