"""Offline advisor contracts; all model and runner boundaries are fixtures."""
import json
import subprocess
import threading
import tomllib
import unittest
from datetime import datetime, timezone
from unittest import mock

import test_controller as fixtures
import test_integration as integration


c = fixtures.c


class AdvisorTests(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.ControllerTests("runTest")
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)

    def test_native_role_pins_astra_high_without_changing_main_model_or_source(self):
        h = self.h
        source = h.source.read_bytes()
        c.prepare_codex(h.policy, c.route_at(h.policy))
        config = tomllib.loads((h.state / "codex-home/config.toml").read_text(encoding="utf-8"))
        role_path = h.state / "codex-home/agents/astra_advisor.toml"
        role = tomllib.loads(role_path.read_text(encoding="utf-8"))
        self.assertEqual(config["model"], "offline/model")
        self.assertEqual(role["model"], "auto/gpt-6-astra")
        self.assertEqual(role["model_reasoning_effort"], "high")
        self.assertEqual(config["agents"]["astra_advisor"]["config_file"], str(role_path))
        self.assertFalse(role["features"]["shell_tool"])
        self.assertFalse(role["features"]["apps"])
        self.assertFalse(role["features"]["plugins"])
        self.assertNotIn("sandbox_mode", role)  # Unsupported authority override.
        self.assertNotIn(fixtures.FAKE_SECRET, role_path.read_text(encoding="utf-8"))
        self.assertEqual(h.source.read_bytes(), source)

    def test_guidance_allows_immediate_consultation_and_native_session_recovery(self):
        prompt = c.prompt_for(self.h.policy, self.h.ready, None)
        for text in ("不要求先失败几次", "send_input", "resume_agent", "advisory-sessions.json"):
            self.assertIn(text, prompt)
        self.assertNotIn("advisory_required", prompt)

    def test_native_events_survive_partial_last_line_without_copying_entire_conversation(self):
        h = self.h
        cycle = h.state / "cycles" / "fixture"
        cycle.mkdir(parents=True)
        events = [
            {"type": "thread.started", "thread_id": "root-fixture"},
            {"type": "item.completed", "item": {"type": "collab_tool_call",
             "tool": "spawn_agent", "receiver_thread_ids": ["advisor-fixture"]}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "large answer"}},
        ]
        (cycle / "events.jsonl").write_text(
            "\n".join(json.dumps(x) for x in events) + '\n{"type":',
            encoding="utf-8")
        c.advisor_module().record_events(h.state, cycle)
        record = c.read_json(h.state / "advisory-sessions.json")
        self.assertEqual(record["root_thread_id"], "root-fixture")
        self.assertEqual(len(record["native_events"]), 1)
        self.assertNotIn("large answer", json.dumps(record))
        self.assertEqual(c.read_json(cycle / "advisory-sessions.json"), record)

    def test_model_wait_uses_one_process_and_sends_prompt_only_once(self):
        h = self.h
        calls, ticks = [], []
        children = []

        def make(argv, **kwargs):
            child = fixtures.Child(argv)
            original = child.communicate

            def wait(data, timeout):
                calls.append(data)
                if len(calls) <= 2:
                    raise subprocess.TimeoutExpired("fixture", timeout)
                return original(data, timeout)
            child.communicate = wait
            children.append(child)
            return child

        with mock.patch.object(c.subprocess, "Popen", side_effect=make) as popen:
            result = c.run_cycle(h.policy, h.ready, None, {"requested": False},
                                 supervise=lambda: ticks.append("original-runtime"))
        self.assertEqual(result["state"], "reported")
        self.assertEqual(popen.call_count, 1)
        self.assertIsInstance(calls[0], bytes)
        self.assertEqual(calls[1:], [None, None])
        self.assertEqual(len(ticks), 2)
        self.assertFalse(children[0].terminated)

    def test_v2_task_path_uuid_usage_and_answer_survive_next_ordinary_cycle(self):
        h = self.h
        day = datetime.now(timezone.utc)
        cycle = h.state / "cycles" / (day.strftime("%Y%m%d") + "T000000Z-native")
        cycle.mkdir(parents=True)
        (cycle / "events.jsonl").write_text(
            json.dumps({"type": "thread.started", "thread_id": "root"}) + "\n",
            encoding="utf-8")
        directory = h.state / "codex-home/sessions" / day.strftime("%Y/%m/%d")
        directory.mkdir(parents=True)
        rows = [
            {"type": "session_meta", "payload": {
                "id": "child", "agent_role": "astra_advisor", "agent_path": "/root/problem",
                "source": {"subagent": {"thread_spawn": {"parent_thread_id": "root"}}}}},
            {"type": "turn_context", "payload": {"model": "auto/gpt-6-astra", "effort": "high"}},
            {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "actual advice"}},
            {"type": "event_msg", "payload": {"type": "token_count",
             "info": {"total_token_usage": {"input_tokens": 100, "output_tokens": 20}}}},
        ]
        (directory / "child.jsonl").write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
        c.advisor_module().record_events(h.state, cycle)
        saved = c.read_json(h.state / "advisory-sessions.json")["advisor_sessions"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["session_id"], "child")
        self.assertEqual(saved[0]["task_name"], "/root/problem")
        self.assertEqual(saved[0]["last_answer"], "actual advice")
        self.assertEqual(saved[0]["usage"]["input_tokens"], 100)
        second = h.state / "cycles" / "ordinary"
        second.mkdir()
        (second / "events.jsonl").write_text(
            json.dumps({"type": "thread.started", "thread_id": "another-root"}), encoding="utf-8")
        c.advisor_module().record_events(h.state, second)
        self.assertEqual(c.read_json(h.state / "advisory-sessions.json")["advisor_sessions"], saved)

    def test_navigation_index_failure_does_not_retry_successful_paid_consultation(self):
        h = self.h
        _, patched = h.child_factory()
        with patched, mock.patch.object(c.advisor_module(), "record_events", side_effect=OSError("disk")):
            result = c.run_cycle(h.policy, h.ready, None, {"requested": False})
        self.assertEqual(result["state"], "reported")
        self.assertEqual(result["failure_count"], 0)
        self.assertIn("advisor_index_warning", result)

    def test_deadline_and_operator_stop_terminate_only_the_model_process(self):
        h = self.h
        for stopped in (False, True):
            with self.subTest(stopped=stopped):
                children, patched = h.child_factory(timeout=True)
                ticks = []
                times = [0, 0, 1000] if not stopped else [0, 0]
                with patched, mock.patch.object(c.time, "monotonic", side_effect=times):
                    result = c.run_cycle(h.policy, h.ready, None, {"requested": stopped},
                                         supervise=lambda: ticks.append(True))
                self.assertEqual(result["state"], "retry_wait")
                self.assertTrue(children[0].terminated)
                self.assertEqual(len(ticks), 0 if stopped else 1)
                self.assertFalse((h.state / "pause.json").exists())


class AdvisorSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.i = integration.ControllerRuntimeIntegrationTests("runTest")
        self.i.setUp()
        self.addCleanup(self.i.doCleanups)

    def _actual_async_components(self):
        import test_scheduler as scheduler_fixtures
        fixture=scheduler_fixtures.SchedulerTests('runTest')
        fixture.h=self.i.runner;fixture.engines=[]
        def factory(policy,ready):
            engine=c.scheduler_module('scheduler_engine').SchedulerEngine(policy,ready)
            fixture.engines.append(engine);engine.probe.probe=fixture.sample
            return engine
        c.create_runtime.side_effect=factory
        planner_module=c.scheduler_module('scheduler_planner')
        planner=planner_module.AsyncPlanner();self.addCleanup(planner.close)
        self.i.harness.policy['maximum_cycles_per_start']=1
        self.i.harness.save_policy()
        return fixture,planner_module,planner

    def test_slow_model_collects_and_refills_original_nine_slots_without_new_scheduler(self):
        i,h,r=self.i,self.i.harness,self.i.runner
        for n in range(10):r.task('advisor-wait-'+str(n))
        fixture,planner_module,planner=self._actual_async_components()
        nine=threading.Event();finished=threading.Event();refilled=threading.Event();captured={}
        original_model=i._model
        def slow_model(argv,**kwargs):
            child=original_model(argv,**kwargs);communicate=child.communicate
            def wait_for_research(data,timeout):
                self.assertTrue(nine.wait(5),'Scheduler failed to fill pool while planner was waiting')
                self.assertEqual(len(r.runs()),9)
                captured['original_ids']={key:value['run_id'] for key,value in i.intents().items()}
                r.finish('advisor-wait-0');finished.set()
                self.assertTrue(refilled.wait(5),'Scheduler failed to collect/refill during planner wait')
                self.assertEqual(len(r.runs()),10)
                return communicate(data,timeout)
            child.communicate=wait_for_research;return child
        def poll(*args,**kwargs):
            for engine in fixture.engines:
                for command,future in list(engine.channel.operations.values()):future.result(timeout=3)
            if len(r.runs())==9:
                nine.set();self.assertTrue(finished.wait(3))
            if len(r.runs())==10:
                refilled.set();planner.pending[1].result(timeout=3)
        i.model_mock.side_effect=slow_model
        with mock.patch.object(planner_module,'AsyncPlanner',return_value=planner),mock.patch.object(c,'sleep_poll',side_effect=poll),mock.patch.object(c.time,'time',return_value=1000):
            c.serve(h.policy_path)
        self.assertEqual(i.model_mock.call_count,1)
        intents=i.intents()
        for key,original_id in captured['original_ids'].items():self.assertEqual(intents[key]['run_id'],original_id)
        self.assertEqual(intents['advisor-wait-9']['slot'],intents['advisor-wait-0']['slot'])
        self.assertEqual(i.observation()['active_count'],9)
        self.assertFalse((h.state/'runtime-error.json').exists())
        checkpoint=c.read_json(h.state/'checkpoint.json')
        self.assertTrue(c.should_wake(h.policy,checkpoint,i.observation(),c.watch_key(h.policy,checkpoint,i.observation()),now=1061))

    def test_disarm_during_model_wait_prevents_any_further_submission(self):
        i,h,r=self.i,self.i.harness,self.i.runner
        for n in range(10):r.task('advisor-stop-'+str(n))
        fixture,planner_module,planner=self._actual_async_components()
        nine=threading.Event();disarmed=threading.Event();release=threading.Event();self.addCleanup(release.set)
        original_model=i._model
        def slow_model(argv,**kwargs):
            child=original_model(argv,**kwargs);communicate=child.communicate
            def wait_and_disarm(data,timeout):
                self.assertTrue(nine.wait(5));r.finish('advisor-stop-0')
                h.policy['enabled']=False;h.save_policy();disarmed.set()
                self.assertTrue(release.wait(3));return communicate(data,timeout)
            child.communicate=wait_and_disarm;return child
        def poll(*args,**kwargs):
            for engine in fixture.engines:
                for command,future in list(engine.channel.operations.values()):future.result(timeout=3)
            if len(r.runs())==9:
                nine.set();self.assertTrue(disarmed.wait(3));release.set()
        i.model_mock.side_effect=slow_model
        with mock.patch.object(planner_module,'AsyncPlanner',return_value=planner),mock.patch.object(c,'sleep_poll',side_effect=poll),mock.patch.object(c.time,'time',return_value=1000):
            c.serve(h.policy_path)
        self.assertEqual(len(r.runs()),9);self.assertNotIn('advisor-stop-9',i.intents())


if __name__ == "__main__":
    unittest.main()
