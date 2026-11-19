# Independent binding to device-miss audit r3; source mathematics unchanged.
# Independent bound-auditor revision for the unchanged event-source mathematics.
"""Bind one selected natural event to all of its positive Si step deposits.

No selection, sampling, solver, output mutation, birth-energy injection or source
renormalization occurs here. The caller persists the returned source and ledger.
"""
import csv
import hashlib
import math
from pathlib import Path

import common
import source_kernel as kernel

require = common.require
AUDIT_CHECKS = {'real_exits_and_frozen_hashes', 'binary_source_environment_data_provenance',
    'initialized_mode_request_and_geometry', 'serial_affinity', 'actual_physics_inventory',
    'native_geometry_and_cost', 'primary_events_tracks_steps_and_zero_events',
    'stable_births_process_identity_points_and_termination', 'all_material_energy_and_native_particle_coverage',
    'receipt_stable'}


def _number(row, key):
    value = float(row[key])
    require(math.isfinite(value), 'Nonfinite raw field: ' + key)
    return value


def _integer(row, key):
    text = row[key]
    value = int(text)
    require(str(value) == text, 'Noncanonical integer raw field: ' + key)
    return value


def _close(a, b):
    return abs(a - b) <= 1e-12 + 1e-9 * max(abs(a), abs(b))


def _rows(path, event_id):
    selected = []
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream, strict=True)
        require(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)), 'Missing/duplicate raw CSV columns')
        for row in reader:
            require(None not in row and all(x is not None for x in row.values()), 'Malformed raw CSV row')
            if _integer(row, 'event_id') == event_id:
                selected.append(row)
    return selected


def _raw_window_fraction(t0, t1, window):
    if t0 == t1:
        return float(window[0] <= t0 <= window[1])
    return max(0., min(t1, window[1]) - max(t0, window[0])) / (t1 - t0)


def _witness(selection, tracks, links, steps, offset, window):
    w = selection['witness']
    require(w['event_id'] == selection['event_id'] and w.get('process') == 'protonInelastic' and
            w.get('process_type') == 4, 'Selected nuclear witness identity differs')
    bytrack = {_integer(t, 'track_id'): t for t in tracks}
    require(len(bytrack) == len(tracks), 'Duplicate selected-event track')
    bystep = {(_integer(s, 'track_id'), _integer(s, 'step_id')): s for s in steps}
    require(len(bystep) == len(steps), 'Duplicate selected-event step')
    trigger = bystep[(w['parent_track_id'], w['parent_step_id'])]
    require(trigger['particle'] == 'proton' and trigger['post_process'] == 'protonInelastic' and
            _integer(trigger, 'post_process_type') == 4 and
            _integer(trigger, 'post_process_subtype') == w['process_subtype'], 'Raw native protonInelastic witness missing')
    roots = set()
    for link in links:
        if (_integer(link, 'parent_track_id'), _integer(link, 'parent_step_id')) != (w['parent_track_id'], w['parent_step_id']):
            continue
        if link['creator_process'] == 'protonInelastic' and _integer(link, 'creator_type') == 4 and _integer(link, 'creator_subtype') == w['process_subtype']:
            child = _integer(link, 'child_track_id')
            require(child in bytrack and _integer(bytrack[child], 'parent_id') == w['parent_track_id'] and
                    bytrack[child]['creator_process'] == 'protonInelastic' and
                    bytrack[child]['birth_token'] == link['birth_token'], 'Nuclear birth-link identity differs')
            roots.add(child)
    require(roots and sorted(roots) == w['direct_child_track_ids'], 'Nuclear witness roots differ from raw birth links')
    descendants = set()
    for track_id in bytrack:
        current, seen = track_id, set()
        while current:
            require(current in bytrack and current not in seen, 'Missing/cyclic ancestry')
            seen.add(current)
            if current in roots:
                descendants.add(track_id)
                break
            current = _integer(bytrack[current], 'parent_id')
    require(sorted(descendants) == w['descendant_track_ids'], 'Raw descendant ancestry differs')
    deposits = []
    for step in steps:
        if _integer(step, 'track_id') not in descendants or step['pre_material'] != 'G4_Si':
            continue
        t0, t1 = offset + _number(step, 'pre_t_ns') * 1e-9, offset + _number(step, 'post_t_ns') * 1e-9
        require(t1 >= t0, 'Raw nuclear descendant time is reversed')
        energy = _number(step, 'ionizing_MeV') * _raw_window_fraction(t0, t1, window)
        if energy > 0:
            deposits.append({'track_id': _integer(step, 'track_id'), 'step_id': _integer(step, 'step_id'), 'window_ionizing_MeV': energy})
    total = math.fsum(d['window_ionizing_MeV'] for d in deposits)
    require(total > 0 and _close(total, w['window_descendant_si_ionizing_MeV']), 'No matching positive in-window nuclear-descendant Si deposition')
    require(sorted(w['window_descendant_step_ids']) == sorted([selection['event_id'], d['track_id'], d['step_id']] for d in deposits),
            'Selected nuclear window step IDs differ')
    return {'direct_child_track_ids': sorted(roots), 'descendant_track_ids': sorted(descendants),
            'window_descendant_si_ionizing_MeV': total, 'window_descendant_steps': deposits,
            'selection_uses_kernel_tails': False}


def from_selected(selection_path):
    selection_path = Path(selection_path).resolve()
    require(selection_path.is_relative_to(common.RT.resolve()) and selection_path.is_file(), 'Selection must be a closure runtime record')
    selection = common.read(selection_path)
    record_path, audit_path = common.check_ref(selection['record']), common.check_ref(selection['audit'])
    record, audit = common.read(record_path), common.read(audit_path)
    request, event_id = selection['request'], selection['event_id']
    require(type(event_id) is int and 0 <= event_id < request['event_count'], 'Selected event ID outside the request')
    manifest_path=common.HERE / 'transport-contract-material-r2.json'
    require(request in common.read(manifest_path)['requests'], 'Selected request is not in the frozen material-r2 sequence')
    require(request.get('arm') == 'H' and request['mode'] not in ('init',), 'A non-hadronic/initialization request cannot provide this source')
    require(record_path.parent == (common.RT / 'transport/runs' / request['label']).resolve(), 'Selected record path differs from its request')
    require(record['run_id'] == request['label'] and record['request'] == request, 'Selected transport record/request differs')
    require(audit.get('schema') == 'dram-see-v4-nuclear-closure-transport-audit-r1' and audit.get('passed') is True and
            not audit.get('errors') and set(audit.get('checks', {})) == AUDIT_CHECKS and all(x.get('passed') is True for x in audit['checks'].values()),
            'Selected transport audit failed or is incomplete')
    require(audit['audit_code_sha256'] == common.sha(common.HERE / 'transport_audit_r3.py'), 'Selected transport auditor changed')
    require(audit['matched_contract_sha256']==common.sha(manifest_path) and
            record['input_sha256']['matched-contract.json']==common.sha(manifest_path),
            'Selected material-r2 manifest is not bound to the native input and audit')
    base_witness = {k: v for k, v in selection['witness'].items() if k not in ('window_descendant_si_ionizing_MeV', 'window_descendant_step_ids')}
    require(base_witness in audit['mechanism_summary']['qualifying_witnesses'], 'Selected witness absent from the bound native audit')
    require(audit['record_sha256'] == selection['record']['sha256'] and audit['request'] == request and
            audit['run_id'] == request['label'] and Path(audit['run_dir']).resolve() == record_path.parent, 'Audit belongs to another run/record')
    for key in ('runner_exit_code', 'remote_exit_code', 'collection_exit_code'):
        require(type(record.get(key)) is int and record[key] == 0, 'Unknown/nonzero transport exit: ' + key)
    geometry_sha = common.sha(common.GEOMETRY)
    require(geometry_sha == common.contract()['geometry']['sha256'] == request['geometry_sha256'], 'Current geometry differs from selected transport')
    bound = {**record['input_sha256'], **record['output_sha256']}
    names = ('steps.csv', 'tracks.csv', 'birth-links.csv', 'events.csv', 'geometry-contract.json')
    for name in names:
        require(name in bound and common.sha(record_path.parent / name) == bound[name], 'Selected raw member changed: ' + name)
    require(bound['geometry-contract.json'] == geometry_sha, 'Native transport geometry snapshot differs')
    raw_steps = _rows(record_path.parent / 'steps.csv', event_id)
    tracks = _rows(record_path.parent / 'tracks.csv', event_id)
    links = _rows(record_path.parent / 'birth-links.csv', event_id)
    events = _rows(record_path.parent / 'events.csv', event_id)
    require(len(events) == 1 and events[0]['event_complete'] == '1' and raw_steps and tracks, 'Selected event is missing/incomplete')
    require(len(raw_steps) == _integer(events[0], 'step_count') and len(tracks) == _integer(events[0], 'track_count'), 'Selected event raw counts differ')
    c = common.contract()['source']; offset, window = c['device_time_offset_s'], c['device_window_s']
    witness = _witness(selection, tracks, links, raw_steps, offset, window)
    base = {'schema': kernel.SCHEMA, 'geometry_sha256': geometry_sha, 'steps': [],
            'provenance': {'kind': 'all-event-positive-silicon-ionization', 'selection': common.ref(selection_path),
                           'record': selection['record'], 'audit': selection['audit'], 'event_id': event_id,
                           'request': request, 'time_offset_s': offset, 'birth_kinetic_energy_added': False}}
    allocations, energy_terms = [], {'all_MeV': [], 'si_MeV': [], 'non_si_MeV': [], 'si_raw_in_window_MeV': []}
    for raw in raw_steps:
        tid, sid = _integer(raw, 'track_id'), _integer(raw, 'step_id')
        ion, edep, niel = (_number(raw, k) for k in ('ionizing_MeV', 'edep_MeV', 'niel_MeV'))
        require(ion >= 0 and edep >= 0 and niel >= 0 and _close(ion, max(0., edep - niel)), 'Raw ionizing energy identity differs')
        t0, t1 = (offset + _number(raw, k) * 1e-9 for k in ('pre_t_ns', 'post_t_ns'))
        require(t0 >= 0 and t1 >= t0, 'Raw step time differs from the ordered unchanged clock')
        r0, r1 = ([_number(raw, prefix + axis + '_um') for axis in ('x', 'y', 'z')] for prefix in ('pre_', 'post_'))
        uid = f"{request['label']}:e{event_id}:t{tid}:s{sid}"
        is_si = raw['pre_material'] == 'G4_Si'
        energy_terms['all_MeV'].append(ion); energy_terms['si_MeV' if is_si else 'non_si_MeV'].append(ion)
        fraction = _raw_window_fraction(t0, t1, window)
        if is_si:
            energy_terms['si_raw_in_window_MeV'].append(ion * fraction)
        disposition = 'zero_ionizing' if ion == 0 else 'non_silicon' if not is_si else 'active_si_source_including_late'
        row = {'uid': uid, 'raw': dict(raw), 'disposition': disposition, 'device_t0_s': t0, 'device_t1_s': t1,
               'raw_window_fraction': fraction, 'raw_window_ionizing_MeV': ion * fraction,
               'nuclear_descendant': tid in witness['descendant_track_ids'], 'source_charge_fC': None}
        if is_si and ion > 0:
            require(_number(raw, 'step_um') != 0 or r0 == r1, 'Zero transport length with distinct endpoints needs explicit review; do not invent a path')
            q = ion * 1e6 / c['silicon_eV_per_pair'] * c['elementary_charge_C'] * 1e15
            row['source_charge_fC'] = q
            base['steps'].append({'uid': uid, 'r0_um': r0, 'r1_um': r1, 't0_s': t0, 't1_s': t1,
                'charge_fC': q, 'w_um': c['spatial_w_um'], 'sigma_s': c['temporal_sigma_s'],
                'kind': 'point' if r0 == r1 else 'segment',
                'provenance': {'event_id': event_id, 'track_id': tid, 'step_id': sid,
                    'raw_steps_sha256': bound['steps.csv'], 'ionizing_MeV': ion, 'pre_material': raw['pre_material'],
                    'recorded_transport_step_um': _number(raw, 'step_um'), 'recorded_deposit_kind': raw['deposit_kind'],
                    'nuclear_descendant': row['nuclear_descendant'], 'birth_kinetic_energy_added': False}})
        allocations.append(row)
    energy = {k: math.fsum(v) for k, v in energy_terms.items()}
    require(_close(energy['all_MeV'], _number(events[0], 'ionizing_all_MeV')) and
            _close(energy['si_MeV'], _number(events[0], 'ionizing_si_MeV')), 'Source event energy does not close to raw event totals')
    source = kernel.canonical_source(base)
    require(source['steps'], 'Selected qualifying event has no positive silicon source')
    si = next(s for s in common.read(common.GEOMETRY)['solids'] if s['geant4_material'] == 'G4_Si')
    box = [si['min_um'], si['max_um']]
    unbounded = [[-math.inf] * 3, [math.inf] * 3]
    spatial = kernel.integrated(source, box, [-math.inf, math.inf])
    temporal = kernel.integrated(source, unbounded, window)
    joint = kernel.integrated(source, box, window)
    total = math.fsum(step['charge_fC'] for step in source['steps'])
    partition = {'inside_si_inside_window_fC': joint['charge_fC'],
                 'outside_si_inside_window_fC': temporal['charge_fC'] - joint['charge_fC'],
                 'inside_si_outside_window_fC': spatial['charge_fC'] - joint['charge_fC'],
                 'outside_si_outside_window_fC': total - spatial['charge_fC'] - temporal['charge_fC'] + joint['charge_fC']}
    allowance = spatial['estimated_abs_error_fC'] + temporal['estimated_abs_error_fC'] + joint['estimated_abs_error_fC'] + 1e-12 * total
    require(min(partition.values()) >= -allowance, 'Source clipping ledger is inconsistent beyond oracle roundoff')
    ledger = {'schema': 'nuclear-closure-event-source-ledger-r1', 'event_id': event_id, 'request': request,
        'selection': common.ref(selection_path), 'record': selection['record'], 'audit': selection['audit'],
        'raw_archive': record['raw_archive'], 'raw_members_sha256': {n: bound[n] for n in names},
        'geometry_sha256': geometry_sha, 'source_sha256': hashlib.sha256(common.encoded(source)).hexdigest(),
        'source_step_count': len(source['steps']), 'all_raw_event_step_count': len(raw_steps),
        'witness_reconstructed': witness, 'energy': energy, 'raw_step_ledger': allocations,
        'total_si_charge_fC': total, 'kernel_allocation': partition, 'kernel_joint_integral': joint,
        'allocation_roundoff_allowance_fC': allowance, 'renormalized': False,
        'time_offset_s': offset, 'window_s': window, 'late_si_steps_retained_in_source': True,
        'birth_energy_added': False, 'outside_material_energy_converted_as_silicon': False,
        'limits': ['One selected event, not a rate or probability.', 'Gaussian width and duration are mapping assumptions.',
                   'Window allocation concerns the Gaussian model; witness eligibility uses unchanged raw step times.']}
    require(common.sha(record_path) == selection['record']['sha256'] and common.sha(audit_path) == selection['audit']['sha256'], 'Selected evidence changed during conversion')
    for name in names:
        require(common.sha(record_path.parent / name) == bound[name], 'Raw source member changed during conversion')
    return {'source': source, 'ledger': ledger}
