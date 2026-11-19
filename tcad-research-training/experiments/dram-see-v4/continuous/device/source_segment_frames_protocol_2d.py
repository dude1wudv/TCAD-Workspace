"""Explicit unique Plot prefixes per absolute Solve segment. Python 3.6 stdlib.

Only the output namespace changes. Native seconds, BE, solver controls and
segment-initial/accepted-endpoint evidence retain their original meanings.
"""
import hashlib
import importlib.util
import json
from decimal import Decimal
from pathlib import Path
import re

SCHEMA = 'dram-see-v4-source-segment-frames-protocol-r1'
O_SHA = '97a5ea8cf6fb64bdfe345adaf09f4aa8f222b8b443d84819fd64c0f447e937a5'
CLOCK_SHA = 'bf5d9a8c5520eda054ecadd14fa4fc06f2f3b7296f16483e5ded02ff20ab4387'
NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
PLOT = re.compile(r'Plot\(FilePrefix="(source_window[A-Za-z0-9_.-]*)" Time=\(Range=\((' + NUMBER + r') (' + NUMBER + r')\)\) NoOverwrite\)')
TRANSIENT = re.compile(r'Transient\(InitialTime=(' + NUMBER + r') FinalTime=(' + NUMBER + r')[^\n]*')
_O = None


def require(ok, message):
    if not ok:
        raise ValueError('Source segment frames: ' + message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def operation_api():
    global _O
    path = Path(__file__).with_name('operating_transient_2d.py')
    raw = path.read_bytes()
    require(digest(raw) == O_SHA and not path.is_symlink(), 'fixed O97 implementation differs')
    if _O is None:
        spec = importlib.util.spec_from_file_location('_source_segment_frames_O97', str(path))
        _O = importlib.util.module_from_spec(spec)
        exec(compile(raw, str(path), 'exec'), _O.__dict__)
    return _O


def plan(timing, timing_sha256):
    O = operation_api(); t = O.validate_timing(timing)
    require(isinstance(timing_sha256, str) and re.fullmatch('[0-9a-f]{64}', timing_sha256), 'actual timing bytes SHA required')
    low, high = t['native_observation_window_s']; rows = []
    for index, segment in enumerate(t['segments'], 1):
        if low <= segment['start_s'] and segment['end_s'] <= high:
            rows.append(dict(segment_index=index, prefix='source_window_s{:04d}'.format(index),
                start_s=segment['start_s'], end_s=segment['end_s'],
                start_literal=O.literal(segment['start_s']), end_literal=O.literal(segment['end_s']),
                NoOverwrite=True, segment_initial_frame_preserved=True,
                segment_initial_frame_contributes_to_BE_integral=False))
    require(rows and rows[0]['start_s'] == low and rows[-1]['end_s'] == high
            and all(a['end_s'] == b['start_s'] for a,b in zip(rows, rows[1:])), 'source segments do not cover exact native window')
    return dict(schema=SCHEMA, operation_timing_sha256=timing_sha256,
        numerical_segment_count=len(t['segments']), source_plot_count=len(rows), segment_plot_prefixes=rows,
        prefix_rule='source_window_s{global_1based_segment_index:04d}; minimum padding only, no segment-count cap',
        native_observation_window_s=list(t['native_observation_window_s']),
        absolute_simulation_window_s=list(t['simulation_window_s']),
        collision_namespace='One unique FilePrefix per source-containing Transient block',
        all_actual_Writing_records_required=True, filename_counter_is_not_a_time_source=True,
        no_time_remapping=True, no_state_or_current_rescaling=True,
        numerical_algorithm_changed=False, native_execution_verified=False)


def _plots(deck, timing, protocol, original=False):
    require(isinstance(deck, bytes), 'original deck bytes required')
    require(protocol == plan(timing, protocol.get('operation_timing_sha256')), 'frame protocol differs from deterministic plan')
    text = deck.decode('utf-8'); blocks = list(TRANSIENT.finditer(text))
    require(len(blocks) == len(timing['segments']), 'Solve segment count differs')
    wanted = {r['segment_index']: r for r in protocol['segment_plot_prefixes']}; observed = []
    for index, (block, segment) in enumerate(zip(blocks, timing['segments']), 1):
        O = operation_api()
        require(block.groups() == (O.literal(segment['start_s']), O.literal(segment['end_s'])), 'absolute Solve segment literals differ')
        stop = blocks[index].start() if index < len(blocks) else len(text)
        matches = list(PLOT.finditer(text, block.start(), stop))
        if index not in wanted:
            require(not matches, 'source Plot occurs outside its declared observation segment')
            continue
        require(len(matches) == 1, 'each source segment must contain exactly one native Plot')
        match = matches[0]; row = wanted[index]
        prefix = 'source_window' if original else row['prefix']
        require(match.groups() == (prefix, row['start_literal'], row['end_literal']), 'source Plot prefix/range does not belong to its absolute segment')
        observed.append((row, match))
    require(len(list(PLOT.finditer(text))) == len(observed) == protocol['source_plot_count'], 'unassigned source Plot')
    require(text.count('FilePrefix="source_window') == len(observed), 'unknown/malformed source-window Plot syntax')
    return text, observed


def replace_plot_prefixes(old_rendered_deck, timing, protocol):
    """Explicit new output transform on fixed O97 render, never old admission."""
    text, observed = _plots(old_rendered_deck, timing, protocol, original=True)
    for row, match in reversed(observed):
        start, end = match.span(1)
        text = text[:start] + row['prefix'] + text[end:]
    result = text.encode('utf-8')
    _plots(result, timing, protocol)
    return result


def observation_windows(deck, timing, protocol):
    _, observed = _plots(deck, timing, protocol)
    rows = [dict(row) for row, _ in observed]
    return dict(native_observation_window_s=timing['native_observation_window_s'],
        segment_literals=[[r['start_literal'],r['end_literal']] for r in rows],
        segment_windows_s=[[r['start_s'],r['end_s']] for r in rows],
        mathematical_source_window_s=timing['mathematical_source_window_s'],
        source_epoch_s=timing['source_epoch_s'], simulation_window_s=timing['simulation_window_s'],
        time_remapped=False, tail_renormalized=False,
        source_frame_protocol_sha256=digest(encoded(protocol)),
        source_frame_protocol_schema=SCHEMA, segment_plot_prefixes=rows)


def validate_frame_assignments(index, windows):
    """Join exact native Writing segment to frozen prefix; no inferred time."""
    rows = {r['segment_index']: r for r in windows['segment_plot_prefixes']}
    path = Path(__file__).with_name('native_transient_clock.py'); raw = path.read_bytes()
    require(digest(raw) == CLOCK_SHA and not path.is_symlink(), 'fixed bf5 clock differs')
    spec = importlib.util.spec_from_file_location('_source_segment_frames_bf5', str(path))
    C = importlib.util.module_from_spec(spec); exec(compile(raw, str(path), 'exec'), C.__dict__)
    spans = {}
    for segment, row in rows.items():
        accepted = [v for v in index['accepted_intervals'] if v['segment_index'] == segment]
        require(accepted, 'declared source segment has no original accepted interval')
        first, last = accepted[0], accepted[-1]
        require(C.printed(Decimal(row['start_literal']), first['start_time_token'])
            and C.printed(Decimal(row['end_literal']), last['end_time_token']),
            'source segment differs at original PLT print precision')
        spans[segment] = (first['start_s'], last['end_s'])
    records = []
    for frame in index['frames']:
        segment = frame['segment_index']
        require(segment in rows, 'actual source Writing is in an undeclared source segment')
        row = rows[segment]
        match = re.fullmatch(re.escape(row['prefix']) + r'_([0-9]+)_access_des\.tdr', frame['source_file'])
        require(match is not None, 'actual source filename prefix belongs to a different native segment')
        actual_start, actual_end = spans[segment]
        require(actual_start <= frame['end_s'] <= actual_end, 'actual mapped source frame time leaves its own accepted segment')
        if frame['frame_kind'] == 'segment_initial_state':
            require(frame['dt_s'] == 0 and not frame['contributes_to_BE_integral']
                and frame['accepted_index'] is None and frame['end_s'] == actual_start, 'segment initial frame must retain zero-duration semantics')
        else:
            require(frame['frame_kind'] == 'accepted_BE_endpoint' and frame['contributes_to_BE_integral']
                and frame['accepted_index'] is not None and frame['dt_s'] > 0
                and actual_start <= frame['start_s'] < frame['end_s'], 'unknown source endpoint/BE semantics')
        records.append(dict(source_file=frame['source_file'], segment_index=segment,
            declared_prefix=row['prefix'], native_counter_token=match.group(1),
            writing_log_line=frame['writing_log_line'], frame_kind=frame['frame_kind'],
            contributes_to_BE_integral=frame['contributes_to_BE_integral']))
    require(len(records) == len({r['source_file'] for r in records}), 'duplicate source file identities')
    return dict(schema='dram-see-v4-observed-source-segment-frame-assignment-r1',
        source_frame_protocol_sha256=windows['source_frame_protocol_sha256'], records=records,
        filename_used_as_time=False, all_boundary_frames_retained=True, native_source_qualified=False)
