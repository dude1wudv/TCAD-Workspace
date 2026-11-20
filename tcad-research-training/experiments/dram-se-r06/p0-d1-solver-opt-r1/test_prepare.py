"""Exercise D1 deck edits and A/B metrics with native-format snippets."""

from decimal import Decimal
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from analyze_ab import compare_metrics, diagnose, parse_circuit, parse_log
from prepare import block, freeze_project, transients, transform_deck


DECK = '''* Original D1 zero-source deck
Device Cell {
 File { Grid="cell_msh.tdr" Current="device.plt" }
}
File { Output="transient" }
Math { Number_Of_Threads=1 CoordinateSystem {AsIs} RelErrControl Digits=5
 ErrRef(electron)=1e7 ErrRef(hole)=1e7 Iterations=30 NotDamped=100 ExitOnFailure
 Transient=BE Method=Blocked SubMethod=ILS(set=1) PrintLinearSolver }
System {
 Cell access ("SN1"=sn1 "SN2"=sn2 "BL"=bl)
 Vsource_pset vdrive (drive 0) {pwl=(0 1.2 18.1e-9 1.2 18.2e-9 0.6 35e-9 0.6)}
 Resistor_pset rdrive (bl drive) {resistance=1000}
 Set(sn1=0.6) Set(sn2=0.6) Set(bl=0)
 Plot "circuit.plt" (time() v(sn1) v(sn2) v(bl))
}
Solve {
 access.Optics
 Coupled(Iterations=100) {Poisson}
 Coupled(Iterations=100) {Poisson Electron Hole Contact Circuit}
 Plot(FilePrefix="initial")
 Unset(sn1) Unset(sn2)
 Transient(InitialTime=0 FinalTime=1.8200000000000001e-08 InitialStep=1e-13 MinStep=1e-18 MaxStep=5e-10) {
  Coupled {Poisson Electron Hole Contact Circuit}
 }
 Transient(InitialTime=1.8200000000000001e-08 FinalTime=2.9900000000000003e-08 InitialStep=1e-13 MinStep=1e-18 MaxStep=5e-10) {
  Coupled {Poisson Electron Hole Contact Circuit}
 }
 Transient(InitialTime=2.9900000000000003e-08 FinalTime=3.0000000000000004e-08 InitialStep=1e-13 MinStep=1e-18 MaxStep=2e-11) {
  Coupled {Poisson Electron Hole Contact Circuit}
 }
 Set(rdrive."resistance"=1e15)
 Transient(InitialTime=3.0000000000000004e-08 FinalTime=3.1900000000000001e-08 InitialStep=1e-13 MinStep=1e-18 MaxStep=2e-11) {
  Coupled {Poisson Electron Hole Contact Circuit}
 }
 Transient(InitialTime=3.1900000000000001e-08 FinalTime=3.2100000000000003e-08 InitialStep=1e-13 MinStep=1e-18 MaxStep=2e-11) {
  Coupled {Poisson Electron Hole Contact Circuit}
 }
 Transient(InitialTime=3.2100000000000003e-08 FinalTime=3.5000000000000002e-08 InitialStep=1e-13 MinStep=1e-18 MaxStep=5e-10) {
  Coupled {Poisson Electron Hole Contact Circuit}
  Plot(FilePrefix="final" Time=(35e-9))
 }
}
'''

LOG = '''  Linear solver (submethod) : ILS ( Set = 2 )
Starting solve of next problem:
Coupled (
Finished, because...
Error smaller than 1 ( 3.2000E-02 ).
Accumulated times:
Assembly time:        0.50 s
Solve time:           0.25 s
Total time:           0.76 s

Starting solve of next problem:
Transient (
Computing BE-step from 3.1800e-08 s to 3.1900e-08 s (Stepsize: 1.0000e-10 s)
Iteration   |Rhs|      factor     |step|     error   #inner  #iterative  time
------------------------------------------------------------------------------
    0      8.49e+07                                                      0.20
    1      1.03e+03   1.00e+00   8.42e-03   8.75e-01    0         17      0.80
Finished, because...
Error smaller than 1 ( 8.7471E-01 ).
Accumulated times:
Assembly time:        0.50 s
Solve time:           0.25 s
Total time:           0.80 s

Computing BE-step from 3.1900e-08 s to 3.2100e-08 s (Stepsize: 2.0000e-10 s)
Iteration   |Rhs|      factor     |step|     error   #inner  #iterative  time
------------------------------------------------------------------------------
    0      8.49e+07                                                      0.40
    1      1.03e+03   1.00e+00   8.42e-03   1.88e+02    0         42      3.20
Finished, because...
#iterations larger than 25.
Accumulated times:
Assembly time:        1.25 s
Solve time:           1.75 s
Total time:           3.20 s
Newton didn't converge, trying again with smaller timestep...

Computing BE-step from 3.1900e-08 s to 3.2000e-08 s (Stepsize: 1.0000e-10 s)
Finished, because |RHS| is less than 1.0000e-10.
Accumulated times:
Assembly time:        0.25 s
Solve time:           0.00 s
Total time:           0.25 s

Sentaurus Device simulation times:
  wallclock: 6.0 s (0 h:0 m:6 s)
'''

PLT = '''DF-ISE text

Info {
  version = 1.0
  type = xyplot
  datasets = [ "time" "v(sn1)" "v(bl)" "i(rdrive,bl)" ]
  functions = [ Time Voltage Voltage Current ]
}
Data {
 3.18000000000000E-08
 5.95000000000000E-01 6.00000000000000E-01 0.0
 3.19000000000000E-08
 5.94000000000000E-01 6.01200000000000D-01 1e-14
 3.19000000000000E-08
 5.94000000000000E-01 6.01300000000000E-01 1e-14
 3.20000000000000E-08
 5.93000000000000E-01 6.01400000000000E-01 1e-14
}
'''


def times(deck):
    start, stop = block(deck, "Solve")
    return [(round(float(first), 12), round(float(last), 12))
            for _, _, _, first, last in transients(deck[start:stop])]


class DeckTests(unittest.TestCase):
    def test_solver_only_freeze_preserves_physics_resources_and_endpoint(self):
        with TemporaryDirectory() as folder, patch("prepare.HERE", Path(folder)):
            project = Path(folder) / "baseline"
            project.mkdir()
            source = DECK.replace("\n", "\r\n").encode()
            (project / "device.cmd").write_bytes(source)
            spec = dict(name="original", native_threads=1, native_cores=1, steps=[])
            (project / "project.json").write_text(json.dumps(spec))
            (project / "source.dat").write_bytes(b"unchanged")
            candidate = freeze_project(project, "pardiso_only")
            self.assertEqual((candidate / "device.cmd").read_bytes(), source.replace(b"ILS(set=1)", b"ParDiSo"))
            self.assertEqual(json.loads((candidate / "project.json").read_bytes()), spec | {"name": "pardiso_only"})
            self.assertEqual((candidate / "source.dat").read_bytes(), b"unchanged")
            self.assertEqual((project / "device.cmd").read_bytes(), source)
            with self.assertRaises(FileExistsError):
                freeze_project(project, "pardiso_only")
            with self.assertRaisesRegex(ValueError, "preserves"):
                freeze_project(project, "ils2_only", end_ns=30.925)
            with self.assertRaisesRegex(ValueError, "already uses"):
                freeze_project(candidate, "pardiso_only")

    def test_pardiso_updates_only_global_solver_settings(self):
        deck = transform_deck(DECK)
        for token in ("Number_Of_Threads=2", "Iterations=25", "NotDamped=8", "RHSMin=1e-10",
                      "Method=Blocked SubMethod=ParDiSo", 'Set(rdrive."resistance"=1e12)',
                      "Coupled(Iterations=100)", "Resistor_pset rdrive (bl drive) {resistance=1000}"):
            self.assertIn(token, deck)
        self.assertNotIn('Set(rdrive."resistance"=1e15)', deck)
        self.assertEqual(deck, transform_deck(DECK))

    def test_ils_replaces_old_set_and_rhs_min_without_duplicates(self):
        source = DECK.replace("RelErrControl", "RHSMin=1e-12 RelErrControl")
        deck = transform_deck(source, submethod="ILS(set=2)", threads=4, iterations=20, not_damped=5,
                              rhs_min="1e-11", rdrive_read_ohm="1e13")
        for token in ("SubMethod=ILS(set=2)", "Number_Of_Threads=4", "Iterations=20",
                      "NotDamped=5", 'Set(rdrive."resistance"=1e13)'):
            self.assertIn(token, deck)
        self.assertEqual(deck.count("RHSMin="), 1)
        self.assertIn("RHSMin=1e-11", deck)
        self.assertNotIn("ILS(set=1)", deck)
        self.assertIn("RHSMin=1e-12", transform_deck(source, rhs_min=None))
        self.assertNotIn("RHSMin=", transform_deck(DECK, rhs_min=None))

    def test_exact_endpoint_truncates_at_native_segment_boundary(self):
        deck = transform_deck(DECK)
        self.assertEqual(times(deck)[-1], (31.9, 32.1))
        self.assertIn('  Plot(FilePrefix="final" Time=(32.1e-9))\n }\n}\n', deck)
        self.assertNotIn("FinalTime=3.5000000000000002e-08", deck)
        self.assertEqual(deck.count('Plot(FilePrefix="final"'), 1)

    def test_inside_segment_adjusts_final_time_and_updates_existing_plot(self):
        deck = transform_deck(DECK, end_ns=33.25)
        self.assertEqual(times(deck)[-1], (32.1, 33.25))
        self.assertIn('Plot(FilePrefix="final" Time=(33.25e-9))', deck)
        self.assertNotIn("Time=(35e-9)", deck)
        self.assertEqual(times(transform_deck(DECK, end_ns=None))[-1], (32.1, 35.0))

    def test_save_splits_hold_and_retains_both_coupled_bodies(self):
        deck = transform_deck(DECK, save_checkpoint_ns=21.9)
        self.assertEqual(times(deck)[1:3], [(18.2, 21.9), (21.9, 29.9)])
        self.assertEqual(deck.count("MinStep=1e-18 MaxStep=5e-10"), 3)
        self.assertIn('FinalTime=21.9e-9 InitialStep=1e-13 MinStep=1e-18 MaxStep=5e-10', deck)
        self.assertIn('}\n Save(FilePrefix="hold_21p9ns")\n Transient(InitialTime=21.9e-9', deck)
        self.assertEqual(deck.count("Coupled {Poisson Electron Hole Contact Circuit}"), len(times(deck)))
        self.assertIn('Set(sn1=0.6) Set(sn2=0.6)', deck)

    def test_save_can_end_the_prefix_at_checkpoint(self):
        deck = transform_deck(DECK, end_ns=21.9, save_checkpoint_ns=21.9)
        self.assertEqual(times(deck)[-1], (18.2, 21.9))
        self.assertTrue(deck.endswith(' }\n Save(FilePrefix="hold_21p9ns")\n}\n'))

    def test_load_from_original_and_split_decks_retains_only_suffix(self):
        for source in (DECK, transform_deck(DECK, save_checkpoint_ns=21.9)):
            with self.subTest(source_was_split=source != DECK):
                deck = transform_deck(source, load_checkpoint="hold_21p9ns")
                self.assertEqual(times(deck), [(21.9, 29.9), (29.9, 30.0), (30.0, 31.9), (31.9, 32.1)])
                self.assertIn('Solve {\n Load(FilePrefix="hold_21p9ns")\n Transient(InitialTime=21.9e-9', deck)
                self.assertIn('Set(rdrive."resistance"=1e12)', deck)
                self.assertIn('Set(bl=0)', deck)
                self.assertIn('Vsource_pset vdrive (drive 0) {pwl=(0 1.2 18.1e-9 1.2 18.2e-9 0.6 35e-9 0.6)}', deck)
                for skipped in ('access.Optics', 'Iterations=100', 'FilePrefix="initial"', 'Unset(sn1)',
                                'Set(sn1=0.6)', 'Set(sn2=0.6)', 'Save(FilePrefix='):
                    self.assertNotIn(skipped, deck)

    def test_invalid_boundary_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "reaches checkpoint"):
            transform_deck(DECK, end_ns=20, save_checkpoint_ns=21.9)
        with self.assertRaisesRegex(ValueError, "No Transient continues"):
            transform_deck(DECK, load_checkpoint="hold_40ns")


class AnalysisTests(unittest.TestCase):
    def test_comparable_window_and_readout(self):
        window = diagnose(StringIO(LOG), (31.8, 32.0))
        baseline = parse_log(LOG) | parse_circuit(PLT) | {"first_attempt_ns": 31.8, "rejection_window": window}
        result = compare_metrics(baseline, baseline)
        self.assertEqual(result["delta_window_attempt_wall_s"], 0)
        self.assertEqual(result["delta_window_rejected_steps"], 0)
        self.assertTrue(result["readout_sign_preserved"])
        for changes, message in (({"last_sim_time_ns": 31.9}, "span"),
                                 ({"sample_time_ns": 31.8}, "readout time"),
                                 ({"rejection_window": window | {"bounds_ns": [31.8, 31.9]}}, "same bounds")):
            with self.assertRaisesRegex(ValueError, message):
                compare_metrics(baseline, baseline | changes)
        partial = baseline | {"rejection_window": window | {"timed_steps": 0}}
        self.assertIsNone(compare_metrics(baseline, partial)["delta_window_attempt_wall_s"])
        positive = baseline | {"write1_margin_V": 0.00001}
        negative = baseline | {"write1_margin_V": -0.00001}
        result = compare_metrics(positive, negative)
        self.assertTrue(result["margin_pass"])
        self.assertFalse(result["readout_sign_preserved"])

    def test_native_timer_summary_and_ils_max_include_rejected_work(self):
        self.assertEqual(parse_log(LOG), {
            "accepted_steps": 2, "rejected_steps": 1, "total_assembly_s": 2.5, "total_solve_s": 2.25,
            "total_wall_s": 6.0, "last_sim_time_ns": 32.0, "max_ils_iters": 42,
        })

    def test_incomplete_step_does_not_advance_clock_or_count_as_rejection(self):
        incomplete = LOG.split("Sentaurus Device simulation times:")[0]
        incomplete += "Computing BE-step from 3.2000e-08 s to 3.2100e-08 s (Stepsize: 1.0e-10 s)\n"
        metrics = parse_log(incomplete)
        self.assertEqual((metrics["accepted_steps"], metrics["rejected_steps"]), (2, 1))
        self.assertEqual(metrics["last_sim_time_ns"], 32.0)
        self.assertIsNone(metrics["total_wall_s"])

    def test_pardiso_iterative_column_is_not_ils_evidence(self):
        self.assertIsNone(parse_log(LOG.replace("ILS ( Set = 2 )", "Pardiso"))["max_ils_iters"])

    def test_dfise_signed_margins_and_first_duplicate(self):
        self.assertEqual(parse_circuit(PLT), {
            "sample_time_ns": 31.9, "v_bl_V": 0.6012, "write1_margin_V": 0.0012, "write0_margin_V": -0.0012,
        })

    def test_csv_nearest_sample_and_tolerance(self):
        csv = "time_ns,V(BL)\n31.8994,0.599\n31.9003,0.5988\n32.1,0.5992\n"
        metrics = parse_circuit(csv)
        self.assertEqual(metrics["sample_time_ns"], 31.9003)
        self.assertEqual(metrics["write0_margin_V"], 0.0012)
        self.assertEqual(metrics["write1_margin_V"], -0.0012)
        with self.assertRaisesRegex(ValueError, "No circuit sample"):
            parse_circuit(csv, tolerance_ns=0.0001)
        self.assertEqual(parse_circuit("time_s,v_bl_V\n3.19e-8,0.6\n")["sample_time_ns"], 31.9)

    def test_missing_or_truncated_circuit_samples_fail(self):
        with self.assertRaisesRegex(ValueError, "Malformed DF-ISE rows"):
            parse_circuit(PLT.replace("6.01400000000000E-01 1e-14", "6.01400000000000E-01"))
        with self.assertRaisesRegex(ValueError, "No circuit sample"):
            parse_circuit("time,V(BL)\n3.182e-8,0.601\n")

    def test_compare_json_strict_threshold_and_signed_delta(self):
        baseline = json.loads(json.dumps(parse_log(LOG) | parse_circuit(PLT)))
        candidate = baseline | {"rejected_steps": 0, "total_wall_s": 3.0, "max_ils_iters": None}
        for delta, passed in (("0.000099", True), ("0.0001", False), ("-0.0001", False), ("0.000101", False)):
            with self.subTest(delta=delta):
                value = Decimal(str(baseline["write1_margin_V"])) + Decimal(delta)
                result = compare_metrics(baseline, candidate | {"write1_margin_V": float(value)})
                self.assertEqual(result["margin_pass"], passed)
                self.assertEqual(result["delta_margin_V"], float(delta))
                self.assertEqual(result["delta_metrics"]["total_wall_s"], -3.0)
                self.assertEqual(result["delta_metrics"]["rejected_steps"], -1)
                self.assertNotIn("max_ils_iters", result["delta_metrics"])
        result = compare_metrics(baseline, candidate | {"write0_margin_V": -0.00125}, stored_bit=0)
        self.assertTrue(result["margin_pass"])
        self.assertEqual(result["delta_margin_V"], -0.00005)


if __name__ == "__main__":
    unittest.main()
