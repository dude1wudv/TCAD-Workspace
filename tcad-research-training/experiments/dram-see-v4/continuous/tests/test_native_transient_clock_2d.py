"""Targeted replay checks for the sealed original 2D A0 transient evidence."""
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[4]
CLOCK_PATH = ROOT/'experiments/dram-see-v4/continuous/device/native_transient_clock.py'
RUN = ROOT/'local_runtime/runs/20261019T104330Z-v4-2d-a0-main-b0-input-r2'
EVIDENCE = ROOT/'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/a0-b0-extraction-duplicate-r1'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def printed_interval(value, token):
    printed = Decimal(token)
    half_quantum = Decimal(5).scaleb(printed.as_tuple().exponent-1)
    return abs(value-printed) <= half_quantum


def insert_duplicate_plt_row(raw, parsed, row_1based):
    text = raw.decode('utf-8')
    data = re.search(r'\bData\s*\{(.*?)\}', text, re.S)
    tokens = list(re.finditer(r'\S+', data.group(1)))
    width = len(parsed['columns'])
    row_tokens = [token.group(0) for token in tokens[(row_1based-1)*width:row_1based*width]]
    position = data.start(1)+tokens[row_1based*width-1].end()
    return (text[:position]+'\n  '+' '.join(row_tokens)+'\n'+text[position:]).encode('utf-8')


def replace_plt_value(raw, parsed, row_1based, column, value):
    text = raw.decode('utf-8')
    data = re.search(r'\bData\s*\{(.*?)\}', text, re.S)
    tokens = list(re.finditer(r'\S+', data.group(1)))
    width = len(parsed['columns'])
    col = parsed['columns'].index(column)
    token = tokens[(row_1based-1)*width+col]
    start, end = data.start(1)+token.start(), data.start(1)+token.end()
    return (text[:start]+value+text[end:]).encode('utf-8')


class NativeTransientClock2DTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clock = load(CLOCK_PATH, 'native_transient_clock_2d_actual_fixture')
        cls.raw = {
            'circuit': (EVIDENCE/'original-circuit.plt').read_bytes(),
            'device': (EVIDENCE/'original-access_device.plt').read_bytes(),
            'log': (EVIDENCE/'original-transient_des.log').read_bytes(),
            'deck': (EVIDENCE/'original-device.cmd').read_bytes(),
        }
        cls.summary = json.loads((EVIDENCE/'summary.json').read_text(encoding='utf-8'))
        cls.old_index = json.loads((EVIDENCE/'new-source-index-actual-r1.json').read_text(encoding='utf-8'))
        cls.audit = cls.clock.audit(cls.raw['circuit'], cls.raw['device'], cls.raw['log'], cls.raw['deck'])
        cls.source = cls.clock.source_index(cls.audit,
            [frame['source_file'] for frame in cls.old_index['frames']],
            'HeavyIonGeneration', cls.old_index['source_window_s'], False)

    def test_original_raw_copies_match_sealed_run_archive_members(self):
        members = self.summary['original_members']
        for name, raw in (('circuit.plt', self.raw['circuit']),
                          ('access_device.plt', self.raw['device']),
                          ('transient_des.log', self.raw['log']),
                          ('device.cmd', self.raw['deck'])):
            with self.subTest(member=name):
                self.assertEqual(hashlib.sha256(raw).hexdigest(), members[name]['sha256'])
                self.assertEqual(len(raw), members[name]['bytes'])
        self.assertEqual(file_sha(RUN/'results.tar'), self.summary['archive_sha256'])
        self.assertEqual(file_sha(RUN/'manifest.json'), self.summary['manifest_sha256'])

    def test_actual_be_to_plt_clock_mapping_and_a0_source_windows(self):
        self.assertEqual(hashlib.sha256(CLOCK_PATH.read_bytes()).hexdigest(),
                         'bf5d9a8c5520eda054ecadd14fa4fc06f2f3b7296f16483e5ded02ff20ab4387')
        self.assertEqual(self.audit['schema'], 'dram-see-v4-native-transient-clock-r2')
        attempts = self.audit['attempts']
        accepted = self.audit['accepted_intervals']
        rejected = self.audit['rejected_or_unconverged_attempts']
        self.assertEqual((len(attempts), len(accepted), len(rejected)), (686, 679, 7))
        successful = [item for item in attempts if item['success'] and not item['rejected']]
        self.assertEqual(len(successful), 679)

        previous_end = None
        for index, (interval, attempt) in enumerate(zip(accepted, successful), 1):
            self.assertEqual(interval['accepted_index'], index)
            self.assertEqual(interval['attempt_index'], attempt['attempt_index'])
            self.assertEqual(interval['raw_log_tokens'], attempt['raw_log_tokens'])
            start = Decimal(interval['start_time_token'])
            end = Decimal(interval['end_time_token'])
            if previous_end is not None:
                self.assertEqual(start, previous_end)
            previous_end = end
            self.assertTrue(printed_interval(start, attempt['raw_log_tokens'][0]))
            self.assertTrue(printed_interval(end, attempt['raw_log_tokens'][1]))
            self.assertTrue(printed_interval(end-start, attempt['raw_log_tokens'][2]))
            self.assertGreater(interval['device_row_1based'], 0)
            self.assertGreater(interval['circuit_end_row_1based'], interval['circuit_start_row_1based'])

        circuit_rows = self.audit['circuit']['raw_rows']
        self.assertEqual(len(circuit_rows), 696)
        self.assertEqual(len(self.audit['canonical_circuit_row_indices']), 680)
        self.assertEqual(len(self.audit['initialization']['circuit_rows']), 3)
        self.assertEqual(len(self.audit['initialization']['device_rows']), 2)
        self.assertEqual(len(self.audit['zero_duration_events']), 14)
        self.assertEqual(len(self.audit['zero_duration_events'])+1, 15)

        frames = self.source['frames']
        self.assertEqual(len(frames), 85)
        self.assertEqual(sum(frame['dt_s'] == 0 for frame in frames), 1)
        self.assertEqual(sum(frame['contributes_to_BE_integral'] for frame in frames), 84)
        self.assertFalse(self.source['source_present'])
        self.assertEqual(self.source['generation_columns'], [])
        self.assertTrue(all(frame['direct_TDR_timestamp_verified'] is False for frame in frames))
        self.assertEqual(set(frame['source_file'] for frame in frames),
                         set(frame['source_file'] for frame in self.old_index['frames']))
        self.assertEqual(set(self.source['required_source_window_indices']),
            {frame['accepted_index'] for frame in frames if frame['contributes_to_BE_integral']})
        self.assertEqual(len(self.source['required_source_window_indices']), 84)

    def test_all_positive_source_system_current_pairs_are_exact_opposites(self):
        mapping = self.audit['current_mapping']
        self.assertEqual(mapping['actual_input_column'], 'source TotalCurrent')
        self.assertEqual(mapping['raw_system_column'], 'i(access,sn)')
        self.assertEqual(mapping['raw_system_to_target_multiplier'], -1)
        self.assertEqual(mapping['positive_endpoint_exact_opposite_count'], 679)
        self.assertFalse(mapping['initial_current_integrated'])
        crows = {row['row_1based']: row for row in self.audit['circuit']['raw_rows']}
        drows = {row['row_1based']: row for row in self.audit['device']['raw_rows']}
        for interval in self.audit['accepted_intervals']:
            system = Decimal(crows[interval['circuit_end_row_1based']]['tokens']['i(access,sn)'])
            device = Decimal(drows[interval['device_row_1based']]['tokens']['source TotalCurrent'])
            self.assertEqual(system+device, Decimal(0))
            self.assertEqual(self.audit['trace']['i_sn_A'][interval['accepted_index']],
                             drows[interval['device_row_1based']]['values']['source TotalCurrent'])

    def test_unknown_circuit_duplicate_at_nonboundary_is_rejected(self):
        parsed = self.clock.parse_plt(self.raw['circuit'])
        mutated = insert_duplicate_plt_row(self.raw['circuit'], parsed, 4)
        with self.assertRaisesRegex(ValueError, 'Unexpected circuit rows at a non-boundary'):
            self.clock.audit(mutated, self.raw['device'], self.raw['log'], self.raw['deck'])

    def test_printed_be_step_mismatch_is_rejected(self):
        text = self.raw['log'].decode('utf-8')
        offset = 0
        match = None
        for line in text.splitlines(keepends=True):
            candidate = self.clock.BE.match(line.rstrip('\r\n'))
            if candidate is not None:
                match = candidate
                break
            offset += len(line)
        self.assertIsNotNone(match)
        start, end = offset+match.start(3), offset+match.end(3)
        changed = text[:start]+'2.0000e-13'+text[end:]
        with self.assertRaisesRegex(ValueError, 'Ordered BE / original PLT start, end or dt disagrees'):
            self.clock.audit(self.raw['circuit'], self.raw['device'], changed.encode('utf-8'), self.raw['deck'])

    def test_full_port_device_current_mismatch_is_rejected(self):
        parsed = self.clock.parse_plt(self.raw['device'])
        first_positive = next(row for row in parsed['raw_rows'] if Decimal(row['tokens']['time']) > 0)
        original = Decimal(first_positive['tokens']['source TotalCurrent'])
        changed = replace_plt_value(self.raw['device'], parsed, first_positive['row_1based'],
                                    'source TotalCurrent', str(original+Decimal('1e-9')))
        with self.assertRaisesRegex(ValueError, 'Circuit BE endpoint does not exactly match'):
            self.clock.audit(self.raw['circuit'], changed, self.raw['log'], self.raw['deck'])

    def test_source_index_rejects_duplicate_or_unknown_writing_files(self):
        files = [frame['source_file'] for frame in self.old_index['frames']]
        with self.assertRaisesRegex(ValueError, 'duplicate original field inventory'):
            self.clock.source_index(self.audit, files+[files[0]], 'HeavyIonGeneration',
                                    self.old_index['source_window_s'], False)
        with self.assertRaisesRegex(ValueError, 'Source files do not map once'):
            self.clock.source_index(self.audit, files[:-1]+['unknown-access.tdr'], 'HeavyIonGeneration',
                                    self.old_index['source_window_s'], False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
