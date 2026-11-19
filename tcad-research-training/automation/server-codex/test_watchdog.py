"""Offline watchdog tests using Sentaurus log tails and mocked runner probes."""
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import controller
import watchdog
from runtime import Runtime


STEP = "Computing BE-step from 3.0933e-08 s to 3.0934e-08 s (Stepsize: 2.8680e-14 s)"
REJECT = "Newton didn't converge, trying again with smaller timestep..."
FINISH = "Finished, because |RHS| is less than 1.0000e-10."


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"enabled": True}
        self.intent = {}
        self.progress = {"sim_time_ns": 30.0, "stepsize_s": 1e-14, "consecutive_rejections": 0}

    def evaluate(self, now=0, width=1, **progress):
        return watchdog.evaluate_watchdog(self.cfg, self.intent, dict(self.progress, **progress), now, width)

    def test_parse_blank_unrelated_and_partial_tail(self):
        for tail in ("", "sdevice starting\n", STEP[:-2], "3e-09 s (Stepsize: 1e-14 s)"):
            with self.subTest(tail=tail):
                self.assertEqual(watchdog.parse_transient_progress(tail), {
                    "sim_time_ns": None, "stepsize_s": None, "consecutive_rejections": 0})

    def test_parse_latest_step_and_trailing_rejections(self):
        log = "\r\n".join([
            "Computing BE-step from 0 s to 1E-12 s (Stepsize: 1E-12 s)",
            REJECT, FINISH, "  " + STEP, REJECT, "    Newton solver iterations", REJECT,
        ])
        progress = watchdog.parse_transient_progress(log)
        self.assertEqual(progress["sim_time_ns"], 30.933)
        self.assertEqual(progress["stepsize_s"], 2.8680e-14)
        self.assertEqual(progress["consecutive_rejections"], 2)
        self.assertEqual(watchdog.parse_transient_progress(log + "\n" + FINISH)["consecutive_rejections"], 0)
        self.assertEqual(watchdog.parse_transient_progress(REJECT), {
            "sim_time_ns": None, "stepsize_s": None, "consecutive_rejections": 1})

    def test_exempt_windows_are_inclusive(self):
        windows = [[21.95, 22.15], [40, 41]]
        for value in (21.95, 22, 22.15, 40.5):
            self.assertTrue(watchdog.in_exempt_window(value, windows))
        for value in (None, 21.94, 22.16, 39):
            self.assertFalse(watchdog.in_exempt_window(value, windows))
        self.assertFalse(watchdog.in_exempt_window(22, []))

    def test_disabled_policy_does_not_change_intent(self):
        for cfg in ({}, {"enabled": False}, {"enabled": 1}):
            self.cfg = cfg
            self.intent = {"started_at": 0}
            self.assertFalse(self.evaluate(30000, consecutive_rejections=50)["triggered"])
            self.assertEqual(self.intent, {"started_at": 0})

    def test_wall_cap_defaults_overrides_and_exemption(self):
        self.intent["started_at"] = 100
        self.cfg["exempt_windows_ns"] = [[21.95, 22.15]]
        for width, limit in ((1, 28800), (2, 21600)):
            with self.subTest(width=width):
                self.assertFalse(self.evaluate(100 + limit, width, sim_time_ns=22)["triggered"])
                result = self.evaluate(101 + limit, width, sim_time_ns=22, consecutive_rejections=50)
                self.assertEqual(result["reason"], "wall_time_exceeded")
                self.assertEqual(result["metrics"]["elapsed_seconds"], limit + 1)
        self.cfg["max_wall_seconds_by_width"] = {"1": 50, "4": 75}
        self.assertEqual(self.evaluate(151, sim_time_ns=None)["reason"], "wall_time_exceeded")
        self.assertEqual(self.evaluate(176, 4, sim_time_ns=None)["reason"], "wall_time_exceeded")
        self.assertFalse(self.evaluate(30000, 3, sim_time_ns=None)["triggered"])
        self.assertEqual(self.evaluate(30000, 2, sim_time_ns=None)["reason"], "wall_time_exceeded")

    def test_rejections_require_small_steps_and_respect_exempt_window(self):
        self.cfg["exempt_windows_ns"] = [[21.95, 22.15]]
        self.assertEqual(self.evaluate(consecutive_rejections=40)["reason"], "consecutive_rejections_stalled")
        self.assertFalse(self.evaluate(consecutive_rejections=39)["triggered"])
        for step in (None, 1e-13, 1e-12):
            self.assertFalse(self.evaluate(consecutive_rejections=40, stepsize_s=step)["triggered"])
        self.assertFalse(self.evaluate(consecutive_rejections=40, sim_time_ns=22)["triggered"])

    def test_low_progress_requires_the_full_window_and_counts_small_advances(self):
        for unknown in (None, 0.0):
            self.assertFalse(self.evaluate(sim_time_ns=unknown)["triggered"])
            self.assertNotIn("watchdog_anchor", self.intent)
        self.evaluate(100)
        self.assertEqual(self.intent["watchdog_anchor"], {"time": 100, "sim_time_ns": 30.0})
        self.assertFalse(self.evaluate(2799, sim_time_ns=30.01)["triggered"])
        result = self.evaluate(2800, sim_time_ns=30.02)
        self.assertEqual(result["reason"], "low_progress_rate")
        self.assertAlmostEqual(result["metrics"]["rate_ns_per_hour"], 0.02 / 0.75)
        self.assertFalse(self.evaluate(2801, sim_time_ns=30.1)["triggered"])
        self.assertEqual(self.intent["watchdog_anchor"], {"time": 2801, "sim_time_ns": 30.1})

    def test_anchor_resets_on_progress_and_both_exempt_boundaries(self):
        self.cfg["exempt_windows_ns"] = [[21.95, 22.15]]
        self.evaluate(0, sim_time_ns=21.8)
        self.evaluate(100, sim_time_ns=21.9)
        self.assertEqual(self.intent["watchdog_anchor"]["time"], 100)
        self.assertFalse(self.evaluate(3000, sim_time_ns=21.95)["triggered"])
        self.assertEqual(self.intent["watchdog_anchor"]["time"], 3000)
        self.assertFalse(self.evaluate(9000, sim_time_ns=22.15)["triggered"])
        self.assertFalse(self.evaluate(9001, sim_time_ns=22.16)["triggered"])
        self.assertEqual(self.intent["watchdog_anchor"]["time"], 9001)
        self.assertEqual(self.evaluate(11701, sim_time_ns=22.16)["reason"], "low_progress_rate")


class WatchdogPolicyTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parent
        self.policy = controller.read_json(base / "policy.example.json")
        workspace = base / "workspace-fixture"
        self.policy.update(workspace=str(workspace), state_dir=str(base / "state-fixture"),
                           plan_file=str(workspace / "plan.md"), queue_file=str(workspace / "work-items.json"))
        for key in ("source_codex_config", "codex_binary", "runner_python", "task_file"):
            self.policy[key] = str(base / key)

    def load_policy(self):
        with patch.object(controller, "read_json", return_value=self.policy):
            return controller.policy_at("policy.json")

    def test_absent_and_valid_watchdog_policy(self):
        self.assertNotIn("watchdog", self.load_policy())
        for cfg in ({"enabled": True}, {"enabled": False, "auto_stop": False, "stall_window_seconds": 120,
                    "min_progress_ns_per_hour": 0.1, "max_consecutive_rejections": 20, "min_stepsize_s": 1e-14,
                    "max_wall_seconds_by_width": {"2": 5000.5}, "exempt_windows_ns": [[0, 1], [21.95, 22.15]]}):
            self.policy["watchdog"] = cfg
            self.assertEqual(self.load_policy()["watchdog"], cfg)

    def test_invalid_watchdog_policy(self):
        for cfg in (None, [], {}, {"enabled": 1}, {"enabled": False, "auto_stop": "true"}):
            with self.subTest(cfg=cfg):
                self.policy["watchdog"] = cfg
                with self.assertRaisesRegex(controller.Refused, "watchdog"):
                    self.load_policy()
        invalid = {
            "stall_window_seconds": (0, True, float("inf")),
            "min_progress_ns_per_hour": (-1, "0.1", float("nan")),
            "min_stepsize_s": (0, None),
            "max_consecutive_rejections": (0, True, 1.5),
            "max_wall_seconds_by_width": ([], {"0": 100}, {"2": -1}, {"2": True}),
            "exempt_windows_ns": ({}, [[2, 1]], [[1]], [[-1, 2]], [[0, True]], [[0, float("inf")]]),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.policy["watchdog"] = {"enabled": True, field: value}
                    with self.assertRaisesRegex(controller.Refused, field):
                        self.load_policy()


class WatchdogObservationTests(unittest.TestCase):
    def setUp(self):
        self.engine = Runtime.__new__(Runtime)
        self.engine.policy = {"watchdog": {"enabled": True, "max_wall_seconds_by_width": {"2": 100}}}
        self.engine.state = {}
        self.intent = {"run_id": "original", "backend": "tcad", "slot": 0}
        self.record = {"state": "RUNNING", "started_utc": "1970-01-01T00:00:01+00:00"}
        self.observed = {"status": "RUNNING", "alive": True, "run_id": "original", "log_tail": STEP}
        self.events = []
        mocks = patch.multiple(self.engine, **{
            "_record": Mock(return_value=self.record),
            "_manifest_path": Mock(),
            "_intent_profile": Mock(),
            "_slot_resources": Mock(return_value={"requested_threads": 2}),
            "_unlaunched": Mock(return_value=False),
            "_receipt": Mock(return_value=False),
            "_invoke": Mock(return_value={"ok": True, "payload": self.observed}),
            "_save": Mock(),
        })
        mocks.start()
        self.addCleanup(mocks.stop)

    def observe(self, now=102, probe=True):
        with patch("runtime.time.time", return_value=now):
            return self.engine._observe("task", self.intent, self.events, probe=probe)

    def test_watchdog_records_progress_event_and_original_start_time(self):
        with patch.object(self.engine, "_stop_stalled") as stop:
            view = self.observe()
            self.assertEqual(view["status"], "running")
            self.assertEqual(view["progress"], self.intent["watchdog_state"])
            self.assertAlmostEqual(view["progress"]["sim_time_ns"], 30.933)
            self.assertTrue(view["watchdog_triggered"])
            self.assertEqual(view["watchdog_reason"], "wall_time_exceeded")
            self.assertEqual(self.intent["started_at"], 1)
            self.assertEqual(self.intent["watchdog_triggered"], {"reason": "wall_time_exceeded", "triggered_at": 102})
            self.assertTrue(self.observe(now=103)["watchdog_triggered"])
            self.assertEqual(self.events, [{"type": "watchdog_triggered", "id": "task", "run_id": "original",
                                           "reason": "wall_time_exceeded"}])
            stop.assert_not_called()
        self.engine._save.assert_called()

    def test_auto_stop_hook_runs_once_and_prefers_transient_tail(self):
        self.engine.policy["watchdog"].update(auto_stop=True, max_consecutive_rejections=1)
        self.observed["log_tail"] = "wrapper output"
        self.observed["transient_log_tail"] = STEP + "\n" + REJECT
        with patch.object(self.engine, "_stop_stalled", return_value={"status": "requested"}) as stop:
            view = self.observe(now=50)
            self.assertEqual(view["watchdog_reason"], "consecutive_rejections_stalled")
            self.assertEqual(view["progress"]["consecutive_rejections"], 1)
            self.observe(now=51)
            stop.assert_called_once_with(self.intent, "consecutive_rejections_stalled")
        self.assertEqual(view["watchdog_stop"], {"status": "requested"})

    def test_unconfigured_stop_hook_reports_unavailable(self):
        self.engine.policy["watchdog"]["auto_stop"] = True
        view = self.observe()
        self.assertEqual(view["watchdog_stop"]["status"], "unavailable")
        self.engine._invoke.assert_called_once_with(self.intent, "status")

    def test_missing_policy_tail_other_backend_and_no_probe_leave_intent_alone(self):
        cfg = self.engine.policy.pop("watchdog")
        tail = self.observed["log_tail"]
        self.assertNotIn("progress", self.observe())
        self.engine.policy["watchdog"] = cfg
        self.observed.pop("log_tail")
        self.assertNotIn("progress", self.observe())
        self.observed["log_tail"] = tail
        self.assertNotIn("progress", self.observe(probe=False))
        self.intent["backend"] = "geant4"
        self.assertNotIn("progress", self.observe())
        self.assertNotIn("watchdog_state", self.intent)
        self.assertEqual(self.events, [])

    def test_finished_probe_collects_without_watchdog_alert(self):
        self.observed.update(status="FINISHED", alive=False)
        view = self.observe()
        self.assertIn("progress", view)
        self.assertNotIn("watchdog_triggered", view)
        self.engine._invoke.assert_called_with(self.intent, "collect")
        self.assertEqual(self.events, [{"type": "collected", "id": "task", "run_id": "original"}])
