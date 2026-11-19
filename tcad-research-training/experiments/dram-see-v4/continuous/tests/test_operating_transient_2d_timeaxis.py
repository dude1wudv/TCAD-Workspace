"""UNIT_FIXTURE_NOT_NATIVE: time-axis and render checks; never a selected operation."""
import copy
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = ROOT / 'experiments/dram-see-v4/continuous/device/operating_transient_2d.py'
TIMING_FIXTURE = (ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/'
    'operating-transient-implementation-r1/fixture-timing-UNIT_FIXTURE_NOT_NATIVE.json')
TEMPLATE_PATH = (ROOT / 'local_runtime/dram-see-v4/continuous/control-transition-r14-2d/'
    'device-implementation/candidates/20261019T104330Z-v4-2d-a0-main-b0-input-r2/device.cmd')
SPEC = importlib.util.spec_from_file_location('_unit_fixture_operating_transient_2d', str(MODULE_PATH))
OP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OP)


def non25ns_timing():
    """A 40 ns, 22 ns-epoch contract used only to exercise pure rendering."""
    timing = json.loads(TIMING_FIXTURE.read_text(encoding='utf-8'))
    timing.update(timing_id='UNIT_FIXTURE_NOT_NATIVE-40ns-epoch22ns',
        simulation_window_s=[0., 40e-9], write_end_s=10e-9, precharge_time_s=12e-9,
        hold_window_s=[12e-9, 32e-9], read_window_s=[35e-9, 36e-9], source_epoch_s=22e-9,
        native_observation_window_s=[21.99984e-9, 22.00016e-9],
        mathematical_source_window_s=[21.999839999999998e-9, 22.000160000000002e-9],
        write_rise_window_s=[4e-9, 4.2e-9], write_fall_window_s=[10e-9, 10.2e-9],
        precharge_transition_window_s=[10.2e-9, 10.4e-9], driver_isolate_s=12e-9,
        read_rise_window_s=[34e-9, 34.2e-9], read_fall_window_s=[36.2e-9, 36.4e-9],
        charge_window_s=[20e-9, 32e-9], origin='UNIT_FIXTURE_NOT_NATIVE',
        selection_provenance=dict(description='UNIT_FIXTURE_NOT_NATIVE non-25ns renderer-only schedule', references={}))
    boundaries = sorted(set([0., 4e-9, 4.2e-9, 10e-9, 10.2e-9, 10.4e-9, 12e-9,
        20e-9, 21.99984e-9, 22.00016e-9, 32e-9, 34e-9, 34.2e-9,
        35e-9, 36e-9, 36.2e-9, 36.4e-9, 40e-9]))
    timing['segments'] = []
    for start, end in zip(boundaries, boundaries[1:]):
        observation = (start >= timing['native_observation_window_s'][0]
                       and end <= timing['native_observation_window_s'][1])
        timing['segments'].append(dict(start_s=start, end_s=end,
            initial_step_s=4e-15 if observation else 1e-13,
            min_step_s=1e-18, max_step_s=4e-14 if observation else 1e-10,
            increment=1.3, decrement=2, time_integrator='BE'))
    return timing


def block(raw, name):
    match = re.search(rb'(?m)^\s*' + name.encode('ascii') + rb'\s*\{', raw)
    if not match:
        raise AssertionError('missing block ' + name)
    depth, pos = 1, match.end()
    while depth and pos < len(raw):
        if raw[pos:pos+1] == b'{': depth += 1
        elif raw[pos:pos+1] == b'}': depth -= 1
        pos += 1
    if depth:
        raise AssertionError('unterminated block ' + name)
    return raw[match.start():pos]


class ExplicitTransientTimeAxisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.timing = OP.validate_timing(non25ns_timing())
        cls.template = TEMPLATE_PATH.read_bytes()
        cls.rendered = OP.render(cls.template, 1, cls.timing)
        cls.text = cls.rendered.decode('utf-8')

    def test_explicit_40ns_contract_drives_pwl_solve_and_observation_frames(self):
        t = self.timing
        self.assertEqual(t['origin'], 'UNIT_FIXTURE_NOT_NATIVE')
        self.assertEqual(t['simulation_window_s'], [0., 40e-9])
        self.assertEqual(t['source_epoch_s'], 22e-9)
        self.assertNotEqual(t['simulation_window_s'][1], 25e-9)
        self.assertNotEqual(t['source_epoch_s'], 15e-9)
        self.assertEqual(OP.rendered_timing(t)['read_scoring_window_s'], [35e-9, 36e-9])
        self.assertEqual(OP.rendered_timing(t)['read_WL_plateau_s'], [34.2e-9, 36.2e-9])
        self.assertLessEqual(t['read_window_s'][0], t['read_window_s'][1])
        self.assertGreaterEqual(t['read_window_s'][0], t['read_rise_window_s'][1])
        self.assertLessEqual(t['read_window_s'][1], t['read_fall_window_s'][0])

        transient_pairs = [(float(a), float(b)) for a, b in re.findall(
            r'Transient\(InitialTime=([^ ]+) FinalTime=([^ ]+)', self.text)]
        self.assertEqual(transient_pairs, [(s['start_s'], s['end_s']) for s in t['segments']])
        self.assertEqual(transient_pairs[0][0], t['simulation_window_s'][0])
        self.assertEqual(transient_pairs[-1][1], t['simulation_window_s'][1])
        self.assertTrue(all(a[1] == b[0] for a, b in zip(transient_pairs, transient_pairs[1:])))

        obs0, obs1 = t['native_observation_window_s']
        frame = ('Plot(FilePrefix="source_window" Time=(Range=('+OP.literal(obs0)+' '
                 +OP.literal(obs1)+')) NoOverwrite)')
        self.assertEqual(self.text.count(frame), 1)
        self.assertIn('Plot(FilePrefix="final" Time=('+OP.literal(t['simulation_window_s'][1])+'))', self.text)
        self.assertNotIn('Plot(FilePrefix="source_window" Time=(Range=(1.5e-08', self.text)

        wl = next(line for line in self.text.splitlines() if 'Vsource_pset vwl ' in line)
        drive = next(line for line in self.text.splitlines() if 'Vsource_pset vdrive ' in line)
        self.assertTrue(wl.endswith(OP.literal(40e-9)+' -0.5)}'))
        self.assertTrue(drive.endswith(OP.literal(40e-9)+' '+OP.literal(.6)+')}'))
        self.assertIn(OP.literal(t['read_rise_window_s'][1])+' 1.8', wl)
        self.assertIn(OP.literal(t['read_fall_window_s'][0])+' 1.8', wl)
        self.assertIn(OP.literal(22e-9), OP.rendered_timing(t)['numeric_literals']['/source_epoch_s']['native_literal'])

    def test_only_two_diagnostic_outputs_are_added_to_math(self):
        original_math = block(self.template, 'Math')
        rendered_math = block(self.rendered, 'Math')
        expected_math = original_math.replace(b'PrintLinearSolver\n',
            b'PrintLinearSolver\n CNormPrint\n PrintRhsPerEquation\n')
        self.assertEqual(rendered_math, expected_math)
        self.assertEqual(self.text.count('CNormPrint'), 1)
        self.assertEqual(self.text.count('PrintRhsPerEquation'), 1)
        self.assertEqual(block(self.template, 'Electrode'), block(self.rendered, 'Electrode'))
        self.assertEqual(block(self.template, 'Physics'), block(self.rendered, 'Physics'))
        self.assertEqual(block(self.template, 'Plot'), block(self.rendered, 'Plot'))
        self.assertEqual(OP.metrics_api().criteria()['write0_max_V'], .12)
        self.assertEqual(OP.metrics_api().criteria()['write1_min_V'], 1.08)
        self.assertEqual(OP.metrics_api().criteria()['hold_drift_max_V'], .005)
        self.assertEqual(OP.metrics_api().criteria()['precharge_error_max_V'], .001)
        self.assertEqual(OP.metrics_api().criteria()['signed_read_margin_min_V'], .020)

    def test_epoch_does_not_become_a_hidden_segment_boundary(self):
        t = self.timing
        boundaries = {s['start_s'] for s in t['segments']} | {t['segments'][-1]['end_s']}
        self.assertNotIn(t['source_epoch_s'], boundaries)
        self.assertTrue(any(s['start_s'] < t['source_epoch_s'] < s['end_s'] for s in t['segments']))
        self.assertTrue(OP.rendered_timing(t)['source_epoch_is_not_automatically_a_native_segment_boundary'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
