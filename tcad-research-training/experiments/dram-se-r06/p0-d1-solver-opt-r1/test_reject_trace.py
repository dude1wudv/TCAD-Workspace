import io
import unittest

from reject_trace import summarize_attempts


# Adapted from the local W-2024.09 initial-clock-diagnosis transient log.
FAILED = """Computing BE-step from 8.1129e-08 s to 8.1137e-08 s (Stepsize: 8.6504e-12 s)
Iteration   |Rhs|      factor     |step|     error   #inner  #iterative  time
------------------------------------------------------------------------------
    0      7.03e-01                                                      1.00
C-norm_equation  max_error  vertex  coordinate [um]  value
 electron: 4.980616e-04 66611 (3.515625e-02, 1.416016e-01) 1.773757e+04
   29      1.89e-01   1.00e+00   7.76e-02   2.80e+00    0         4     86.00
 poisson: 2.334139e-14 68205 (4.785156e-02, 1.826172e-01) -8.100380e-05
C-norm_equation  max_error  vertex  coordinate [um]  value
 electron: 2.863334e-03 67909 (4.980469e-02, 1.630859e-01) 2.362853e+02
 hole: 1.764925e-12 67558 (4.589844e-02, 1.640625e-01) 2.067609e+06
   30      1.89e-01   1.00e+00   7.76e-02   2.80e+00    0         4     89.02
Finished, because...
#iterations larger than 30.

Accumulated times:
Assembly time:       48.19 s
Solve time:     40.43 s
Total time:     89.02 s

Newton didn't converge, trying again with smaller timestep...
"""


class TestAttemptSummary(unittest.TestCase):
    def test_retries_count_last_cnorm_round_and_native_stepsize(self):
        retry = FAILED.replace("8.1137e-08", "8.1133e-08").replace("8.6504e-12", "4.3252e-12")
        retry = retry.replace("89.02", "91.00")
        # Exercise the t-step marker and a three-coordinate C-norm row.
        retry = retry.replace("4.980469e-02, 1.630859e-01)", "4.980469e-02, 1.630859e-01, -1e-3)")
        result = summarize_attempts(io.StringIO(FAILED + "t-step rejection\n" + retry))
        self.assertEqual(result["rejected_steps"], 2)
        self.assertEqual(result["timed_steps"], 2)
        self.assertEqual(result["rejected_steps_with_cnorm"], 2)
        self.assertEqual(result["rejected_wall_s"], 180.02)
        self.assertEqual(result["attempt_wall_s"], 180.02)
        worst = result["worst_rejected_attempt"]
        self.assertEqual(worst["line_number"], len(FAILED.splitlines()) + 2)
        self.assertEqual((worst["start_ns"], worst["end_ns"], worst["step_ns"]),
                         (81.129, 81.133, 0.0043252))
        self.assertEqual(worst["rejection_reason"], "newton")
        self.assertEqual(worst["cnorm_iteration"], 30)
        self.assertEqual([item["node"] for item in worst["cnorm_hotspots"]], [67909, 67558, 68205])
        self.assertEqual(worst["cnorm_hotspots"][0]["coordinates_um"], [0.04980469, 0.1630859, -0.001])
        self.assertEqual(result["repeated_hotspots"][0],
                         dict(equation="electron", node=67909, rejected_steps=2))
        self.assertEqual(len(result["repeated_hotspots"]), 3)

    def test_inclusive_window_uses_printed_target_across_segments(self):
        result = summarize_attempts(io.StringIO("""\
Computing BE-step from 8.1128e-08 s to 8.1133e-08 s (Stepsize: 5e-12 s)
Newton didn't converge, trying again with smaller timestep...
Computing BE-step from 8.1129e-08 s to 8.1133e-08 s (Stepsize: 4.3252e-12 s)
Finished, because...
Error smaller than 1 ( 3.20E-02 ).
Accumulated times:
Assembly time: 0.5 s
Solve time: 0.25 s
Total time: 0.80 s
Curve trace finished.
Starting solve of next problem:
Accumulated times:
Total time: 100.00 s
Computing BE-step from 8.1133e-08 s to 8.1134e-08 s (Stepsize: 1e-12 s)
Finished, because |RHS| is less than 1e-10.
Sentaurus Device simulation times:
  wallclock: 150.0 s
"""), start_ns=81.129, end_ns=81.133)
        self.assertEqual(result["accepted_steps"], 1)
        self.assertEqual(result["rejected_steps"], 1)
        self.assertEqual(result["last_accepted_ns"], 81.133)
        self.assertEqual(result["attempt_wall_s"], 0.8)

    def test_open_window_excludes_rounded_target_at_boundary(self):
        result = summarize_attempts(io.StringIO(FAILED), start_ns=81.12, end_ns=81.137, open_window=True)
        self.assertEqual(result["rejected_steps"], 0)

    def test_t_step_rejection_overrides_convergence_and_missing_timing(self):
        result = summarize_attempts(io.StringIO("""\
Computing BE-step from 8.1129e-08 s to 8.1137e-08 s (Stepsize: 8.6504e-12 s)
Finished, because...
Error smaller than 1 ( 3.20E-02 ).
Accumulated times:
Assembly time: 0.5 s
Solve time: 0.25 s
t-step rejection
Sentaurus Device simulation times:
  wallclock: 150.0 s
"""))
        self.assertEqual(result["accepted_steps"], 0)
        self.assertEqual(result["rejected_steps"], 1)
        self.assertEqual(result["timed_steps"], 0)
        self.assertIsNone(result["rejected_wall_s"])
        self.assertIsNone(result["attempt_wall_s"])
        self.assertIsNone(result["worst_rejected_attempt"])

    def test_eof_after_newton_convergence_is_uncertain(self):
        result = summarize_attempts(iter([
            "Computing BE-step from 8.1129e-08 s to 8.1137e-08 s (Stepsize: 8.6504e-12 s)",
            "Finished, because...",
            "|RHS| less than 1e-10.",
            "Accumulated times:",
            "Total time: 0.80 s",
        ]))
        self.assertEqual(result["accepted_steps"], 0)
        self.assertEqual(result["rejected_steps"], 0)
        self.assertEqual(result["incomplete_steps"], 1)
        self.assertEqual(result["timed_steps"], 0)


if __name__ == "__main__":
    unittest.main()
