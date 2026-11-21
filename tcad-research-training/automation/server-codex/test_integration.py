"""Offline controller/Runtime wiring tests; all process boundaries are fake."""
import copy
import json
from pathlib import Path
import unittest
from unittest import mock

import test_controller as controller_fixtures
import test_runtime as runtime_fixtures


c = controller_fixtures.c


class ControllerRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        # Compose helpers without exporting/inheriting their TestCase classes:
        # unittest must discover only the four integration scenarios below.
        self.harness = controller_fixtures.ControllerTests("runTest")
        self.harness.setUp()
        self.addCleanup(self.harness.doCleanups)
        h = self.harness
        (h.workspace / ".git").mkdir()
        h.policy["max_parallel_jobs"] = 9
        h.ready["max_parallel_jobs"] = 9
        h.pin_ready()
        h.enable()

        r = self.runner = runtime_fixtures.RuntimeTests("runTest")
        r.base, r.workspace = h.base, h.workspace
        r.original_root = Path(h.profile["local_state_root"])
        r.profile, r.cfg, r.queue = h.profile_path, h.profile, h.queue
        r.policy, r.ready = h.policy, h.ready
        r.tasks, r.calls, r.behavior, r.collect_failures = [], [], {}, set()
        r.queue_tasks()

        self.model_actions = []
        self.raw_reports = {}
        self.children = []
        self.after_launch = None
        self.runner_patch = mock.patch.object(c.subprocess, "run", side_effect=self._runner)
        self.runner_mock = self.runner_patch.start()
        self.addCleanup(self.runner_patch.stop)
        self.model_patch = mock.patch.object(c.subprocess, "Popen", side_effect=self._model)
        self.model_mock = self.model_patch.start()
        self.addCleanup(self.model_patch.stop)

    def _runner(self, argv, **kwargs):
        # Runtime's real command construction and process contract are checked
        # by this original-runner fixture, including the durable launch intent.
        result = self.runner.fake_runner(argv, **kwargs)
        if self.runner.calls[-1][1] == "run" and self.after_launch:
            self.after_launch()
        return result

    def _model(self, argv, **kwargs):
        h = self.harness
        self.assertEqual(argv[:2], [h.policy["codex_binary"], "exec"])
        self.assertEqual(kwargs["cwd"], str(h.workspace))
        self.assertNotIn(controller_fixtures.FAKE_SECRET, json.dumps(argv))
        index = len(self.children)
        child = controller_fixtures.Child(argv, report=dict(
            controller_fixtures.REPORT, evidence=[]), raw=self.raw_reports.get(index))
        communicate = child.communicate

        def propose(data, timeout):
            if self.model_actions:
                self.model_actions.pop(0)(data.decode("utf-8"))
            return communicate(data, timeout)

        child.communicate = propose
        self.children.append(child)
        return child

    def serve_once(self, now):
        # create_runtime is deliberately not patched: each invocation imports
        # and constructs the production Runtime, reopening its durable state.
        with mock.patch.object(c.time, "time", return_value=now):
            c.serve(self.harness.policy_path, once=True)
        error = self.harness.state / "runtime-error.json"
        self.assertFalse(error.exists(), error.read_text() if error.exists() else "")

    def observation(self):
        return c.read_json(self.harness.state / "observation.json")

    def intents(self):
        return c.read_json(self.harness.state / "runtime.json")["intents"]

    def test_multicore_real_runtime_four_slots_recovery_collect_refill(self):
        h, r = self.harness, self.runner
        h.profile.update(parallel_capacity=4, cpu_sets=[[0, 1], [2, 3], [4, 5], [6, 7]],
                         requested_threads=2)
        h.policy["max_parallel_jobs"] = h.ready["max_parallel_jobs"] = 4
        h.pin_ready()
        for index in range(5):
            r.task("mc" + str(index))
        self.serve_once(1000)
        self.assertEqual((len(r.runs()), self.observation()["active_count"]), (4, 4))
        original = copy.deepcopy(self.intents())
        self.serve_once(1061)
        self.assertEqual(len(r.runs()), 4)
        r.finish("mc0", 143)
        self.serve_once(1122)
        self.assertEqual((len(r.runs()), self.observation()["active_count"]), (5, 4))
        self.assertEqual(self.intents()["mc0"]["run_id"], original["mc0"]["run_id"])
        self.assertEqual(self.intents()["mc4"]["requested_resources"], {
            "schema": "tcad-shared-gate-slots-r4", "capacity": 4,
            "cpu_set": [0, 1], "requested_threads": 2})
        self.assertEqual(self.observation()["scientific_acceptance"], "not_assessed")
        failed = c.read_json(r.record_path("tcad", original["mc0"]["run_id"]))
        self.assertEqual(failed["state"], "FAILED_COLLECTED")
        self.assertTrue(failed["parallel_slot_released"])

    def test_explicit_transport_profile_drains_mc_and_progresses_without_model_retries(self):
        h, r = self.harness, self.runner
        h.profile.update(parallel_capacity=4, cpu_sets=[[0, 1], [2, 3], [4, 5], [6, 7]],
                         requested_threads=2)
        h.policy["max_parallel_jobs"] = h.ready["max_parallel_jobs"] = 4
        transport, _ = h.pin_transport()
        # r.policy/ready reference the same fixture dictionaries, as in production.
        r.task("mc")
        self.serve_once(1000)
        first = copy.deepcopy(self.intents()["mc"])
        r.task("g", backend="geant4")
        r.task("mc-next")
        c._enqueue_control_command(h.state, {"action": "drain", "target_profile": "geant4", "reason": "test_switch"})
        self.serve_once(1061)
        self.assertEqual(len(r.runs()), 1)
        self.assertTrue(self.observation()["pool_phase"]["draining"])
        self.assertEqual(self.observation()["scheduler"]["pool"]["state"], "DRAINING")
        self.assertEqual(self.observation()["scheduler"]["pool"]["target_profile"], "geant4")
        self.assertTrue(any(v["reason"] == "pool_profile_waiting_for_idle"
                            for v in self.observation()["pending_tasks"]))
        r.finish("mc")
        self.serve_once(1122)
        self.assertEqual(len(r.runs()), 2)
        self.assertEqual(self.intents()["g"]["connection"]["path"], str(transport))
        self.assertNotIn("mc-next", self.intents())
        r.finish("g")
        self.serve_once(1183)
        self.assertEqual(len(r.runs()), 3)
        self.assertEqual(self.intents()["mc"]["run_id"], first["run_id"])
        self.assertEqual(self.intents()["mc-next"]["requested_resources"]["requested_threads"], 2)
        self.assertEqual(self.observation()["active_count"], 1)
        self.assertEqual(len({v[2] for v in r.runs()}), 3)
        self.assertEqual(self.observation()["scientific_acceptance"], "not_assessed")

    def test_nine_slots_bad_model_report_restart_and_verified_collection_refill(self):
        r = self.runner
        self.model_actions.append(lambda _: [r.task("t" + str(i)) for i in range(10)])
        self.raw_reports[1] = "{offline-malformed-model-report"

        self.serve_once(1000)
        self.assertEqual(len(r.tasks), 10)
        self.assertEqual(r.runs(), [])
        self.assertEqual(self.model_mock.call_count, 1)

        self.serve_once(1061)
        self.assertEqual(len(r.runs()), 9)
        self.assertEqual((self.observation()["active_count"],
                          self.observation()["pending_count"]), (9, 1))
        original = copy.deepcopy(self.intents())
        self.assertEqual({v["slot"] for v in original.values()}, set(range(9)))
        checkpoint = c.read_json(self.harness.state / "checkpoint.json")
        self.assertEqual(checkpoint["state"], "retry_wait")
        self.assertEqual(self.model_mock.call_count, 2)

        # Fresh controller + real Runtime instances recover original identities
        # while the failed model turn remains in backoff, without launching again.
        self.serve_once(1122)
        self.serve_once(1183)
        self.assertEqual(len(r.runs()), 9)
        self.assertEqual(self.model_mock.call_count, 2)
        self.assertEqual({k: v["run_id"] for k, v in original.items()},
                         {k: v["run_id"] for k, v in self.intents().items()})

        finished = r.finish("t0")
        self.serve_once(1244)
        self.assertEqual(len(r.runs()), 10)
        self.assertEqual(self.model_mock.call_count, 2)
        self.assertEqual((self.observation()["active_count"],
                          self.observation()["pending_count"]), (9, 0))
        self.assertEqual(self.intents()["t9"]["slot"], finished["slot"])
        record_path = r.record_path("tcad", finished["run_id"])
        record = c.read_json(record_path)
        self.assertEqual(record["state"], "COLLECTED")
        self.assertTrue(record["collection_verified"])
        self.assertTrue(record["parallel_slot_released"])
        self.assertEqual(record["results_sha256"], c.digest(record_path.parent / "results.tar"))

        # The changed collection event eventually wakes planning once. Further
        # unchanged polling, beyond the minimum model interval, is lightweight.
        self.serve_once(1420)
        self.assertEqual(self.model_mock.call_count, 3)
        self.serve_once(1481)
        self.assertEqual(self.model_mock.call_count, 3)
        self.assertEqual(len(r.runs()), 10)
        self.assertEqual(len({call[2] for call in r.runs()}), 10)
        self.assertTrue(all(not child.terminated for child in self.children))

    def test_failed_collection_new_project_repair_preserves_independent_original_run(self):
        r = self.runner

        def initial(_):
            r.task("bad", value="mesh=10")
            r.task("independent", value="mesh=20")

        self.model_actions.extend([initial, lambda _: None])
        self.serve_once(1000)
        self.serve_once(1061)
        self.assertEqual(len(r.runs()), 2)
        original = copy.deepcopy(self.intents())
        r.finish("bad", exit_code=2)

        def repair(prompt):
            self.assertIn("original_run_failed_collected", prompt)
            self.assertIn(original["bad"]["run_id"], prompt)
            r.task("repair-bad", value="mesh=5", repair_of="bad",
                   repair_reason="Refine mesh after the collected divergence")

        self.model_actions.append(repair)
        self.serve_once(1122)
        failed = c.read_json(r.record_path("tcad", original["bad"]["run_id"]))
        self.assertEqual(failed["state"], "FAILED_COLLECTED")
        self.assertEqual(failed["remote_exit_code"], 2)
        self.assertNotIn("repair-bad", self.intents())
        self.assertEqual(self.observation()["active_count"], 1)

        self.serve_once(1183)
        intents = self.intents()
        self.assertEqual(len(r.runs()), 3)
        self.assertEqual(self.observation()["active_count"], 2)
        self.assertEqual(intents["independent"]["run_id"], original["independent"]["run_id"])
        self.assertEqual(intents["bad"]["run_id"], original["bad"]["run_id"])
        self.assertEqual(intents["repair-bad"]["repair_of"], "bad")
        self.assertNotEqual(intents["repair-bad"]["run_id"], original["bad"]["run_id"])
        self.assertNotEqual(intents["repair-bad"]["project"], original["bad"]["project"])
        self.assertNotEqual(c.digest(r.workspace / "projects/bad/deck.cmd"),
                            c.digest(r.workspace / "projects/repair-bad/deck.cmd"))
        for key in ("bad", "independent"):
            self.assertEqual(sum(call[2] == original[key]["run_id"] for call in r.runs()), 1)
        self.assertEqual(c.read_json(r.record_path(
            "tcad", original["bad"]["run_id"]))["state"], "FAILED_COLLECTED")

    def operator_stop_mid_batch(self, mode):
        r, h = self.runner, self.harness
        for index in range(10):
            r.task("t" + str(index))

        def stop():
            if mode == "pause":
                c.pause(h.policy, "Offline integration operator pause")
            else:
                h.policy["enabled"] = False
                h.save_policy()

        self.after_launch = stop
        self.serve_once(1000)
        self.assertEqual(len(r.runs()), 1)
        self.assertEqual(len(self.intents()), 1)
        self.model_mock.assert_not_called()
        record = c.read_json(r.record_path("tcad", r.runs()[0][2]))
        self.assertEqual(record["state"], "RUNNING")
        self.assertFalse(record["parallel_slot_released"])
        self.assertFalse(self.children)

    def test_pause_mid_batch_stops_later_submissions_without_killing_original(self):
        self.operator_stop_mid_batch("pause")

    def test_disarm_mid_batch_stops_later_submissions_without_killing_original(self):
        self.operator_stop_mid_batch("disarm")


if __name__ == "__main__":
    unittest.main()
