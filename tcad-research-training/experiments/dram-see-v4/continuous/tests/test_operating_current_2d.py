"""UNIT_FIXTURE_NOT_SCIENTIFIC tests for 2D quasi-static passage estimates."""
import importlib.util
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT/'experiments/dram-see-v4/continuous/data'
DEVICE = ROOT/'experiments/dram-see-v4/continuous/device'
sys.path.insert(0, str(DEVICE))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def point(row, source_v, source_i, drain_v=0.6, drain_i=0.0, gate_v=0.2, body_i=0.0):
    currents = dict(gate=0.0, drain=drain_i, source=source_i, body=body_i)
    voltages = dict(gate=gate_v, drain=drain_v, source=source_v, body=0.0)
    return dict(row_1based=row, voltage_V=voltages, current_into_device_A=currents,
                terminal_KCL_A=math.fsum(currents.values()), relative_terminal_KCL=None)


def synthetic_dc_plt(rows):
    columns = ['time']
    for port in ('gate', 'drain', 'source', 'body'):
        columns.extend([port+' OuterVoltage', port+' TotalCurrent'])
    functions = ['Time']+['Voltage', 'Current']*4
    header = 'DF-ISE text\nInfo {\n type = xyplot\n datasets = [\n'
    header += ''.join(' "'+name+'"\n' for name in columns)
    header += ']\n functions = [\n'+' '.join(functions)+'\n ]\n}\nData {\n'
    data = []
    for time, source_v, source_i, drain_v, drain_i in rows:
        values = [time, .2, 0., drain_v, drain_i, source_v, source_i, 0., 0.]
        data.append(' '.join(format(v, '.16g') for v in values))
    return (header+'\n'.join(data)+'\n}\n').encode('ascii')


class OperatingCurrent2DTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load(DATA/'operating_current_2d.py', 'operating_current_2d_unit_test')
        cls.clock = load(DEVICE/'native_transient_clock.py', 'operating_current_clock_test')

    def test_constant_and_linear_current_integrals_match_independent_analytic_values(self):
        dv, current, capacitance = 0.2, 10e-9, 20e-15
        constant = self.mod.inverse_linear_integral(dv, current, current, capacitance)
        self.assertAlmostEqual(constant, capacitance*dv/current, delta=1e-15*constant)

        ia, ib = 2e-9, 8e-9
        expected = capacitance*dv*math.log(ib/ia)/(ib-ia)
        result = self.mod.inverse_linear_integral(dv, ia, ib, capacitance)
        self.assertAlmostEqual(result, expected, delta=1e-15*expected)

        write_points = [point(1, 0.0, -ia), point(2, dv, -ib)]
        passage = self.mod.passage(write_points, 'write')
        self.assertEqual(passage['status'], 'QUASI_STATIC_ESTIMATE_ONLY')
        self.assertAlmostEqual(passage['estimated_seconds'], expected, delta=1e-15*expected)
        self.assertFalse(passage['native_functional_qualification'])

    def test_read_source_drain_direction_and_effective_capacitance_ratio(self):
        points = [point(1, .2, 10e-9, .688, -10e-9),
                  point(2, 0., 10e-9, .708, -10e-9)]
        source = self.mod.passage(points, 'read', 'source')
        drain = self.mod.passage(points, 'read', 'drain')
        self.assertEqual(source['current_direction_multiplier'], 1)
        self.assertEqual(drain['current_direction_multiplier'], -1)
        self.assertEqual(source['capacitance_F'], 20e-15)
        self.assertEqual(drain['capacitance_F'], 200e-15)
        self.assertEqual(drain['voltage_factor'], .1)
        self.assertAlmostEqual(drain['estimated_seconds']/source['estimated_seconds'], 1.0, places=14)
        self.assertEqual(source['status'], 'QUASI_STATIC_ESTIMATE_ONLY')
        self.assertEqual(drain['status'], 'QUASI_STATIC_ESTIMATE_ONLY')

    def test_zero_and_reverse_directed_currents_remain_visible_without_finite_time(self):
        zero = [point(1, 0., -10e-9), point(2, .1, 0.), point(3, .2, -10e-9)]
        result = self.mod.passage(zero, 'write')
        self.assertEqual(result['status'], 'NO_FINITE_DIRECTED_PASSAGE_ESTIMATE')
        self.assertIsNone(result['estimated_seconds'])
        self.assertEqual([row['row_1based'] for row in result['nonpositive_directed_current_rows']], [2])
        self.assertEqual(len(result['intervals']), 2)
        self.assertTrue(all(interval['estimated_seconds'] is None for interval in result['intervals']))

        reversed_current = [point(1, 0., 10e-9), point(2, .2, 10e-9)]
        reverse = self.mod.passage(reversed_current, 'write')
        self.assertEqual(reverse['status'], 'NO_FINITE_DIRECTED_PASSAGE_ESTIMATE')
        self.assertIsNone(reverse['estimated_seconds'])
        self.assertEqual([row['row_1based'] for row in reverse['nonpositive_directed_current_rows']], [1, 2])

    def test_original_plt_rows_and_repeated_biases_are_not_removed(self):
        raw = synthetic_dc_plt([
            (0., 0., -2e-9, .6, 0.),
            (1., .1, -3e-9, .6, 0.),
            (2., .1, -4e-9, .6, 0.),
            (3., .2, -5e-9, .6, 0.),
        ])
        parsed = self.clock.parse_plt(raw)
        table = self.mod.table(raw, lambda value: self.clock.parse_plt(value))
        self.assertEqual(table['rows'], 4)
        self.assertEqual(table['removed_rows'], 0)
        self.assertEqual([row['row_1based'] for row in table['points']], [1, 2, 3, 4])
        self.assertEqual(table['original']['raw_rows'], parsed['raw_rows'])
        repeated = self.mod.passage(table['points'], 'write')
        self.assertEqual(len(repeated['repeated_voltage_rows']), 1)
        self.assertEqual(repeated['repeated_voltage_rows'][0]['adjacent_pair_1based'], 2)
        self.assertTrue(repeated['repeated_voltage_rows'][0]['same_voltage'])
        self.assertFalse(repeated['repeated_voltage_rows'][0]['same_current'])
        self.assertEqual(len(repeated['intervals']), 2)

    def test_wrong_bias_order_and_resolution_do_not_generate_passage(self):
        points = [point(1, 0., -10e-9), point(2, .1, -10e-9), point(3, .2, -10e-9)]
        spec = {'source_V': [0., .2]}
        paths = {'gate_V': .2, 'max_source_voltage_step_V': .1,
                 'write': {'drain_fixed_V': .6}}
        valid = self.mod.segment_checks(points, spec, 'write', paths)
        self.assertTrue(all(valid.values()))

        wrong_bias = [point(1, 0., -10e-9), point(2, .1, -10e-9, .55), point(3, .2, -10e-9)]
        self.assertFalse(self.mod.segment_checks(wrong_bias, spec, 'write', paths)['drain_bias_path'])

        coarse = dict(paths, max_source_voltage_step_V=.05)
        self.assertFalse(self.mod.segment_checks(points, spec, 'write', coarse)['voltage_resolution'])

        reversed_path = list(reversed(points))
        self.assertFalse(self.mod.segment_checks(reversed_path, spec, 'write', paths)['ordered_voltage_path'])

    def test_wrong_archive_role_is_refused_without_opening_an_archive(self):
        observation = {'execution_context': {'role_id': 'B2D-A0-main-b0'}}
        with patch.object(self.mod.E, 'inspect', return_value=observation), \
             patch.object(self.mod.E, 'require_native_observations'):
            result = self.mod.reduce_archive(ROOT/'NO_NATIVE_ARCHIVE_FIXTURE')
        self.assertEqual(result['status'], 'REFUSED_MISSING_OR_INVALID_NATIVE_DIAGNOSTIC')
        self.assertFalse(result['diagnostic_extraction_verified'])
        self.assertFalse(result['native_qualified'])
        self.assertFalse(result['training_admitted'])
        self.assertIn('Not the explicit operating-DC diagnostic role', result['errors'][0])

    def test_missing_terminal_port_or_invalid_passage_inputs_reject(self):
        incomplete = {'columns': ['time'], 'raw_rows': [{'row_1based': 1, 'values': {'time': 0.}}]}
        with self.assertRaisesRegex(ValueError, 'Missing/ambiguous original DC column'):
            self.mod.table(b'UNIT_FIXTURE_NOT_SCIENTIFIC', lambda raw: incomplete)
        for args in ((.2, 0., 1e-9, 20e-15), (.2, 1e-9, -1e-9, 20e-15),
                     (.2, 1e-9, 1e-9, 0.)):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'Finite passage time requires'):
                self.mod.inverse_linear_integral(*args)


if __name__ == '__main__':
    unittest.main(verbosity=2)
