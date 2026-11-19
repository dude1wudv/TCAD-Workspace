"""UNIT_FIXTURE_NOT_NATIVE: explicit non-25ns timing checks for pure metrics only."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / 'experiments/dram-see-v4/continuous/data/operating_metrics_2d.py'
SPEC = importlib.util.spec_from_file_location('_unit_fixture_operating_metrics_2d', str(SOURCE))
METRICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METRICS)


def timing_contract():
    # Forty nanoseconds is a software fixture; it is not a selected experiment schedule.
    return dict(schema=METRICS.TIMING_SCHEMA, timing_id='UNIT_FIXTURE_NOT_NATIVE_40ns',
        time_unit='s', simulation_window_s=[0., 40e-9], write_end_s=10e-9,
        precharge_time_s=15e-9, hold_window_s=[15e-9, 29e-9],
        read_window_s=[32e-9, 34e-9], source_epoch_s=22e-9,
        native_observation_window_s=[21.9e-9, 22.1e-9],
        mathematical_source_window_s=[21.9e-9, 22.1e-9],
        purpose='UNIT_FIXTURE_ONLY_NOT_A_SELECTED_TIMING')


def trace_fixture():
    times = [0., 10e-9, 15e-9, 20e-9, 25e-9, 29e-9, 32e-9, 34e-9, 40e-9]
    sn = [.6, .05, .05, .05, .05, .05, .05, .05, .05]
    bl = [.6, .6, .6, .6, .6, .6, .55, .55, .55]
    # Endpoint BE current cancels the first capacitive increment over its true 10 ns dt.
    current = [0., 1.1e-6, 0., 0., 0., 0., 0., 0., 0.]
    return dict(time_s=times, v_sn_V=sn, v_bl_V=bl, i_sn_A=current)


class ExplicitNon25nsTimingTests(unittest.TestCase):
    def test_baseline_uses_contract_windows_and_preserves_40ns_axis(self):
        timing = timing_contract()
        trace = trace_fixture()
        result = METRICS.baseline(trace, 0, timing)
        self.assertEqual(METRICS.criteria(), dict(Cstore_fF=20, Cbl_fF=200, plate_V=.6,
            precharge_target_V=.6, write0_max_V=.12, write1_min_V=1.08,
            hold_drift_max_V=.005, precharge_error_max_V=.001,
            signed_read_margin_min_V=.020, kcl_absolute_fC=1e-4, kcl_relative=.01,
            current_direction='total_terminal_current_into_device_at_SN',
            port_current_multiplier=1, explicit_capacitance_multiplier=1))
        self.assertEqual(result['timing_contract'], timing)
        self.assertEqual(result['actual_time_bounds_s'], [0., 40e-9])
        self.assertEqual(result['actual_minus_declared_bounds_s'], [0., 0.])
        self.assertFalse(result['time_coordinate_transformed'])
        self.assertFalse(result['accepted_trace_resampled'])
        self.assertEqual(result['written_vsn_V'], .05)
        self.assertEqual(result['precharge_vbl_V'], .6)
        self.assertEqual(result['mean_read_vbl_V'], .55)
        self.assertAlmostEqual(result['signed_read_margin_V'], .05, places=14)
        self.assertEqual(result['derived_voltage_windows']['hold']['time_s'][0], 15e-9)
        self.assertEqual(result['derived_voltage_windows']['hold']['time_s'][-1], 29e-9)
        self.assertEqual(result['derived_voltage_windows']['read']['time_s'][0], 32e-9)
        self.assertEqual(result['derived_voltage_windows']['read']['time_s'][-1], 34e-9)
        self.assertEqual(len(result['accepted_trace']['time_s']), 9)
        self.assertEqual(result['kcl']['per_step'][0]['dt_s'], 10e-9)
        self.assertTrue(result['checks']['per_BE_KCL'])
        for field in ('native_qualified', 'scientific_evidence_verified', 'training_admitted',
                      'G1_qualified', 'native_engineering_chain_verified', 'is_tcad_result'):
            self.assertFalse(result[field], field)

    def test_kcl_integral_uses_physical_seconds_not_25ns_normalization(self):
        timing = timing_contract()
        rows = METRICS.kcl(trace_fixture(), timing)['per_step']
        first = rows[0]
        self.assertEqual(first['dt_s'], 10e-9)
        self.assertAlmostEqual(first['terminal_integral_fC'], 11., places=12)
        self.assertAlmostEqual(first['capacitor_delta_fC'], -11., places=12)
        self.assertAlmostEqual(first['residual_fC'], 0., places=12)
        self.assertEqual(rows[-1]['end_s'], 40e-9)
        self.assertTrue(all(row['passed'] for row in rows))

    def test_incomplete_or_mismatched_trace_window_is_rejected(self):
        timing = timing_contract()
        short = trace_fixture()
        for column in ('time_s', 'v_sn_V', 'v_bl_V', 'i_sn_A'):
            short[column] = short[column][:-1]
        with self.assertRaisesRegex(ValueError, 'does not cover the explicit operation endpoints'):
            METRICS.validate_trace(short, timing)
        mismatch = copy.deepcopy(timing)
        mismatch['simulation_window_s'] = [0., 39e-9]
        with self.assertRaisesRegex(ValueError, 'does not cover the explicit operation endpoints'):
            METRICS.validate_trace(trace_fixture(), mismatch)

    def test_adverse_kcl_interval_is_retained_and_never_qualifies(self):
        timing = timing_contract()
        trace = trace_fixture()
        trace['i_sn_A'][1] = -1.1e-6
        result = METRICS.baseline(trace, 0, timing)
        self.assertFalse(result['checks']['per_BE_KCL'])
        self.assertFalse(result['candidate_functional_pass'])
        self.assertEqual(len(result['kcl']['per_step']), len(trace['time_s']) - 1)
        self.assertEqual(result['kcl']['failed_end_indices_0based'], [1])
        self.assertTrue(result['kcl']['all_intervals_retained'])
        self.assertEqual(result['accepted_trace'], trace)
        for field in ('native_qualified', 'scientific_evidence_verified', 'training_admitted',
                      'G1_qualified', 'native_engineering_chain_verified', 'is_tcad_result'):
            self.assertFalse(result[field], field)


if __name__ == '__main__':
    unittest.main(verbosity=2)
