"""Offline controller contracts. Never call a real Codex, API, SSH or solver."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("tcad_server_controller", HERE / "controller.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

FAKE_SECRET = "offline-fixture-not-a-real-credential"
REPORT = {
    "status": "waiting",
    "summary": "原任务仍运行，未新增提交。",
    "next_step": "读取原run-id的status，不重新run。",
    "next_check_seconds": 300,
    "evidence": ["original-ledger/manifest.json"],
}


class Child:
    """Only writes the supplied fixture report; no process is started."""
    def __init__(self, argv, returncode=0, report=None, timeout=False, raw=None):
        self.output = Path(argv[argv.index("--output-last-message") + 1])
        self.desired_returncode = returncode
        self.returncode = None
        self.report = copy.deepcopy(REPORT if report is None else report)
        self.timeout = timeout
        self.raw = raw
        self.terminated = False
        self.killed = False
        self.received = None

    def communicate(self, data, timeout):
        self.received = data
        if self.timeout:
            raise subprocess.TimeoutExpired("offline-codex-fixture", timeout)
        self.returncode = self.desired_returncode
        if self.raw is not None:
            self.output.write_text(self.raw, encoding="utf-8")
        else:
            c.write_json(self.output, self.report)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout):
        return self.returncode


class Runtime:
    """A deterministic observation source; never invokes the actual runner."""
    def __init__(self, observation=None, on_tick=None):
        self.observation = copy.deepcopy(observation or {
            "fingerprint": "original-run-identity-active",
            "events": [],
            "active_count": 1,
            "pending_count": 0,
            "repair_requests": [],
            "blocked_tasks": [],
            "queue_complete": False,
            "discovery_uncertain": False,
        })
        self.on_tick = on_tick
        self.calls = []

    def tick(self, allow_submit=False):
        self.calls.append(allow_submit)
        if self.on_tick:
            self.on_tick(allow_submit)
        return copy.deepcopy(self.observation)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tcad-controller-offline-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.workspace = self.base / "workspace"
        self.state = self.base / "state"
        for name in (
            "AGENTS.md", "scripts/tcad.py",
            "experiments/dram-see-v4/nuclear-closure-r1/supervisor.py",
            "experiments/dram-see-v4/transport-probe/operation.py",
            "courses/README.md", "shared/research-brief.md",
        ):
            path = self.workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("offline source fixture\n", encoding="utf-8")
        self.source = self.base / "source.config.toml"
        self.source.write_text(
            'model_provider = "magpie"\n'
            'model = "offline/model"\n'
            'model_reasoning_effort = "high"\n'
            '[model_providers.magpie]\n'
            'name = "magpie"\n'
            'base_url = "http://127.0.0.1:3425/v1"\n'
            'wire_api = "responses"\n'
            'experimental_bearer_token = "' + FAKE_SECRET + '"\n',
            encoding="utf-8",
        )
        self.task = self.base / "operator-task.md"
        self.task.write_text("只接续原授权，不重投。\n", encoding="utf-8")
        self.plan = self.workspace / "shared/server-plan.md"
        self.plan.write_text("仅推进原冻结计划和原身份任务。\n", encoding="utf-8")
        self.queue = self.workspace / "local_runtime/server-codex/queue.json"
        c.write_json(self.queue, {"schema": "tcad-server-queue-v1", "tasks": []})
        self.policy = {
            "schema": c.SCHEMA,
            "enabled": False,
            "workspace": str(self.workspace),
            "state_dir": str(self.state),
            "source_codex_config": str(self.source),
            "codex_binary": sys.executable,
            "runner_python": sys.executable,
            "task_file": str(self.task),
            "plan_file": str(self.plan),
            "queue_file": str(self.queue),
            "cycle_timeout_seconds": 60,
            "minimum_interval_seconds": 60,
            "poll_interval_seconds": 30,
            "runner_timeout_seconds": 60,
            "failure_backoff_seconds": 300,
            "max_failure_backoff_seconds": 3600,
            "repair_attempt_limit": 2,
            "maximum_cycles_per_start": 3,
            "max_parallel_jobs": 1,
            "readiness": None,
        }
        self.policy_path = self.base / "policy.json"
        self.profile_path = self.base / "connection.json"
        self.profile = {
            "backend": "ssh-runtime",
            "ssh_target": "tcad-guest",
            "local_state_root": str(self.workspace / "local_runtime/cloud-benchmark/guest"),
            "remote_root": "/srv/tcad/runs",
            "runtime_entry": "/usr/local/bin/tcad-runtime",
            "tool_bin": "/opt/sentaurus/bin",
            "parallel_capacity": 9,
        }
        self.evidence = self.workspace / "shared/accepted-evidence.json"
        self.evidence.write_text('{"offline_fixture":true}\n', encoding="utf-8")
        self.ready_path = self.base / "readiness.json"
        self.ready = {
            "schema": c.SCHEMA,
            "new_jobs_authorized": True,
            "controller_owner": "server-codex",
            "sole_scheduler": True,
            "workspace": str(self.workspace),
            "max_parallel_jobs": 1,
            "plan_file": str(self.plan),
        }
        self.pin_ready()

    def pin_ready(self):
        c.write_json(self.profile_path, self.profile)
        self.ready["connection"] = {
            "path": str(self.profile_path), "sha256": c.digest(self.profile_path),
        }
        c.write_json(self.ready_path, self.ready)
        self.policy["readiness"] = {
            "path": str(self.ready_path), "sha256": c.digest(self.ready_path),
        }
        self.save_policy()

    def save_policy(self):
        c.write_json(self.policy_path, self.policy)

    def enable(self):
        self.policy["enabled"] = True
        self.save_policy()

    def test_readiness_multicore_four_limit_and_strict_resource_fields(self):
        self.profile.update(parallel_capacity=4, cpu_sets=[[0, 1], [2, 3], [4, 5], [6, 7]],
                            requested_threads=2)
        self.policy["max_parallel_jobs"] = self.ready["max_parallel_jobs"] = 4
        self.pin_ready()
        self.assertEqual(c.readiness_at(self.policy)["connection"], self.ready["connection"])
        self.policy["max_parallel_jobs"] = self.ready["max_parallel_jobs"] = 5
        self.pin_ready()
        with self.assertRaisesRegex(c.Refused, "exceeds"):
            c.readiness_at(self.policy)
        self.policy["max_parallel_jobs"] = self.ready["max_parallel_jobs"] = 4
        self.profile["cpu_sets"][0] = [False, 1]
        self.pin_ready()
        with self.assertRaisesRegex(c.Refused, "cpu_set"):
            c.readiness_at(self.policy)
        # Overlapping CPUs across slots must still be rejected.
        self.profile["cpu_sets"] = [[0, 1], [1, 2], [4, 5], [6, 7]]
        self.pin_ready()
        with self.assertRaisesRegex(c.Refused, "Overlapping"):
            c.readiness_at(self.policy)
        # Omitting requested_threads derives it cleanly from cpu_sets; mismatched value is refused.
        self.profile["cpu_sets"] = [[0, 1], [2, 3], [4, 5], [6, 7]]
        self.profile.pop("requested_threads")
        self.pin_ready()
        self.assertEqual(c.readiness_at(self.policy)["max_parallel_jobs"], 4)
        self.profile["requested_threads"] = 3
        self.pin_ready()
        with self.assertRaises(c.Refused):
            c.readiness_at(self.policy)

    def test_readiness_legacy_capacities_still_supported(self):
        for capacity in (3, 7, 9):
            with self.subTest(capacity=capacity):
                self.profile["parallel_capacity"] = capacity
                self.pin_ready()
                self.assertEqual(c.readiness_at(self.policy)["connection"], self.ready["connection"])
        self.profile.pop("parallel_capacity")
        self.pin_ready()
        c.readiness_at(self.policy)
        self.profile["requested_threads"] = 1
        self.pin_ready()
        with self.assertRaisesRegex(c.Refused, "Legacy"):
            c.readiness_at(self.policy)

    def test_prompt_current_profile_resources_override_generic_task_resources(self):
        self.profile.update(parallel_capacity=4, cpu_sets=[[0, 1], [2, 3], [4, 5], [6, 7]],
                            requested_threads=2)
        self.policy["max_parallel_jobs"] = self.ready["max_parallel_jobs"] = 4
        self.pin_ready()
        prompt = c.prompt_for(self.policy, self.ready, {})
        self.assertIn('"capacity": 4', prompt)
        self.assertIn('"requested_threads": 2', prompt)
        for text in ("override earlier", "native_threads=2", "native_cores=2", "Geant4",
                     "idle pool", "new run ID", "repair_of", "scientific", "OS thread count"):
            self.assertIn(text, prompt)

    def pin_transport(self):
        path = self.base / "connection-local-centos79-nine.json"
        cfg = dict(self.profile, parallel_capacity=9)
        cfg.pop("cpu_sets", None)
        cfg.pop("requested_threads", None)
        c.write_json(path, cfg)
        self.policy["transport_connection_file"] = str(path)
        self.ready["transport_connection"] = {"path": str(path), "sha256": c.digest(path)}
        self.pin_ready()
        return path, cfg

    def test_transport_readiness_validates_semantic_identity_without_sha_blocking(self):
        self.profile.update(parallel_capacity=4, cpu_sets=[[0, 1], [2, 3], [4, 5], [6, 7]],
                            requested_threads=2)
        self.policy["max_parallel_jobs"] = self.ready["max_parallel_jobs"] = 4
        path, cfg = self.pin_transport()
        accepted = c.readiness_at(self.policy)
        self.assertEqual(accepted["transport_connection"]["path"], str(path))
        prompt = c.prompt_for(self.policy, accepted, {})
        self.assertIn('"requested_threads": 1', prompt)
        self.assertIn('"requested_threads": 2', prompt)
        self.assertIn("drains and alternates", prompt)
        self.assertIn("do not duplicate tasks", prompt)
        self.assertIn(str(path).replace("\\", "\\\\"), prompt)

        original_stamp = c.identity_stamp(self.policy, accepted)
        # Harmless metadata/whitespace edit does NOT change semantic identity or block readiness.
        c.write_json(path, dict(cfg, note="harmless comment"))
        self.assertEqual(c.identity_stamp(self.policy, accepted), original_stamp)
        c.readiness_at(self.policy)

        # Changing ssh_target DOES change semantic identity and is rejected semantically.
        c.write_json(path, dict(cfg, ssh_target="other-guest"))
        self.assertNotEqual(c.identity_stamp(self.policy, accepted), original_stamp)
        with self.assertRaisesRegex(c.Refused, "same original"):
            c.readiness_at(self.policy)

        # Plain string path (no sha256 dict) also works cleanly for readiness & transport.
        c.write_json(path, cfg)
        self.ready["transport_connection"] = str(path)
        self.ready["connection"] = str(self.profile_path)
        self.policy["readiness"] = str(self.ready_path)
        c.write_json(self.ready_path, self.ready)
        self.save_policy()
        self.assertEqual(c.readiness_at(self.policy)["max_parallel_jobs"], 4)

        # Exceeding profile capacity is still rejected.
        self.policy["max_parallel_jobs"] = self.ready["max_parallel_jobs"] = 5
        c.write_json(self.ready_path, self.ready)
        self.save_policy()
        with self.assertRaisesRegex(c.Refused, "exceeds"):
            c.readiness_at(self.policy)

    def test_transport_configuration_requires_both_policy_and_readiness_pin(self):
        path, _ = self.pin_transport()
        self.ready.pop("transport_connection")
        self.pin_ready()
        with self.assertRaisesRegex(c.Refused, "readiness.transport_connection"):
            c.readiness_at(self.policy)
        self.ready["transport_connection"] = {"path": str(path), "sha256": c.digest(path)}
        self.policy.pop("transport_connection_file")
        self.pin_ready()
        with self.assertRaises(c.Refused):
            c.readiness_at(self.policy)
        self.policy["transport_connection_file"] = "relative.json"
        self.save_policy()
        with self.assertRaisesRegex(c.Refused, "absolute path"):
            c.policy_at(self.policy_path)

    def test_transport_policy_binding_change_is_detected(self):
        before = c.binding(self.policy)
        self.policy["transport_connection_file"] = str(self.base / "transport.json")
        self.assertNotEqual(before, c.binding(self.policy))

    def child_factory(self, **options):
        children = []
        def make(argv, **kwargs):
            child = Child(argv, **options)
            children.append(child)
            return child
        return children, mock.patch.object(c.subprocess, "Popen", side_effect=make)

    def cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = c.main(["--policy", str(self.policy_path)] + list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_disabled_serve_has_no_process_and_no_state_side_effect(self):
        with mock.patch.object(c.subprocess, "Popen") as popen, \
             mock.patch.object(c, "create_runtime") as create_runtime:
            with self.assertRaisesRegex(c.Refused, "disabled"):
                c.serve(self.policy_path)
        popen.assert_not_called()
        create_runtime.assert_not_called()
        self.assertFalse(self.state.exists())
        self.assertEqual(self.source.read_text(encoding="utf-8").count(FAKE_SECRET), 1)

    def test_status_and_plan_are_read_only_and_redact_secret(self):
        before = self.source.read_bytes()
        with mock.patch.object(c.subprocess, "Popen") as popen, \
             mock.patch.object(c, "create_runtime") as create_runtime:
            for command in ("status", "plan"):
                code, stdout, stderr = self.cli(command)
                self.assertEqual(code, 0, stderr)
                self.assertNotIn(FAKE_SECRET, stdout + stderr)
                self.assertFalse(json.loads(stdout)["ready_to_start"])
        popen.assert_not_called()
        create_runtime.assert_not_called()
        self.assertFalse(self.state.exists())
        self.assertEqual(self.source.read_bytes(), before)

    def test_readiness_validates_semantic_identity_without_sha_blocking(self):
        self.assertEqual(c.readiness_at(self.policy)["controller_owner"], "server-codex")
        self.ready["checks"] = {"guest_accepted": {"passed": False, "path": "/does-not-exist"}}
        self.pin_ready()
        self.assertTrue(c.readiness_at(self.policy)["sole_scheduler"])
        # Stale/omitted SHA256 metadata no longer blocks when semantic fields are valid.
        self.policy["readiness"]["sha256"] = "0" * 64
        self.assertTrue(c.readiness_at(self.policy)["sole_scheduler"])
        self.policy["readiness"] = str(self.ready_path)
        self.assertTrue(c.readiness_at(self.policy)["sole_scheduler"])
        for key, value in (("sole_scheduler", False), ("new_jobs_authorized", False),
                           ("controller_owner", "another-controller"),
                           ("workspace", str(self.base / "other")),
                           ("plan_file", str(self.workspace / "another-plan.md"))):
            with self.subTest(identity=key):
                saved = self.ready[key]
                self.ready[key] = value
                self.pin_ready()
                with self.assertRaises(c.Refused):
                    c.readiness_at(self.policy)
                self.ready[key] = saved
        self.pin_ready()

    def test_profile_pin_alias_and_checkout_identity_cannot_be_rebound(self):
        self.profile_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(c.Refused, "ssh-runtime"):
            c.readiness_at(self.policy)
        for alias in ("hk", "hk-tail", "hk-live", "sub2", "HK-TAIL", "SUB2",
                      "127.0.0.1", "user@tcad"):
            with self.subTest(alias=alias):
                self.profile["ssh_target"] = alias
                self.pin_ready()
                with self.assertRaisesRegex(c.Refused, "TCAD guest SSH alias"):
                    c.readiness_at(self.policy)
        self.profile["ssh_target"] = "tcad-guest"
        self.profile["local_state_root"] = str(self.base / "other-checkout")
        self.pin_ready()
        with self.assertRaisesRegex(c.Refused, "this server checkout"):
            c.readiness_at(self.policy)

    def test_policy_accepts_dynamic_capacities_and_rejects_out_of_bounds_scope(self):
        self.policy["max_parallel_jobs"] = 9
        self.policy["maximum_cycles_per_start"] = 0
        self.save_policy()
        self.assertEqual(c.policy_at(self.policy_path)["max_parallel_jobs"], 9)
        self.assertEqual(c.policy_at(self.policy_path)["maximum_cycles_per_start"], 0)
        self.ready["max_parallel_jobs"] = 9
        self.pin_ready()
        self.assertEqual(c.readiness_at(self.policy)["max_parallel_jobs"], 9)
        # 10-slot data-driven profile is accepted cleanly.
        self.profile.update(parallel_capacity=10, cpu_sets=[[i] for i in range(10)], requested_threads=1)
        self.policy["max_parallel_jobs"] = self.ready["max_parallel_jobs"] = 10
        self.pin_ready()
        self.assertEqual(c.readiness_at(self.policy)["max_parallel_jobs"], 10)
        # Legacy single-core without cpu_sets still rejects unknown capacity like 8.
        self.profile.pop("cpu_sets")
        self.profile.pop("requested_threads")
        self.profile["parallel_capacity"] = 8
        self.policy["max_parallel_jobs"] = self.ready["max_parallel_jobs"] = 8
        self.pin_ready()
        with self.assertRaises(c.Refused):
            c.readiness_at(self.policy)
        for limit in (0, 65, True):
            self.policy["max_parallel_jobs"] = limit
            self.save_policy()
            with self.assertRaisesRegex(c.Refused, "max_parallel_jobs"):
                c.policy_at(self.policy_path)
        self.policy["max_parallel_jobs"] = 1
        self.policy["plan_file"] = str(self.base / "outside-plan.md")
        self.save_policy()
        with self.assertRaises(c.Refused):
            c.policy_at(self.policy_path)
        self.policy["plan_file"] = str(self.plan)
        self.policy["state_dir"] = str(self.workspace / "controller-state")
        self.save_policy()
        with self.assertRaisesRegex(c.Refused, "outside"):
            c.policy_at(self.policy_path)

    def test_route_uses_server_loopback_and_key_only_in_child_environment(self):
        before = self.source.read_bytes()
        route = c.route_at(self.policy)
        with mock.patch.dict(os.environ, {
            "HTTP_PROXY": "http://laptop.invalid:7890",
            "HTTPS_PROXY": "http://laptop.invalid:7890",
            "OPENAI_API_KEY": "unrelated-fixture-key",
        }):
            env = c.prepare_codex(self.policy, route)
        config = self.state / "codex-home/config.toml"
        self.assertNotIn(FAKE_SECRET, config.read_text(encoding="utf-8"))
        self.assertIn('env_key = "TCAD_MAGPIE_API_KEY"', config.read_text(encoding="utf-8"))
        self.assertIn("requires_openai_auth = false", config.read_text(encoding="utf-8"))
        self.assertEqual(env["TCAD_MAGPIE_API_KEY"], FAKE_SECRET)
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "OPENAI_API_KEY"):
            self.assertNotIn(name, env)
        self.assertEqual(self.source.read_bytes(), before)
        self.source.write_text(before.decode().replace("127.0.0.1", "laptop.invalid"), encoding="utf-8")
        with self.assertRaisesRegex(c.Refused, "server-local"):
            c.route_at(self.policy)

    def test_route_accepts_source_env_key_without_changing_source(self):
        text = self.source.read_text(encoding="utf-8")
        text = text.replace('experimental_bearer_token = "' + FAKE_SECRET + '"',
                            'env_key = "OFFLINE_ROUTE_KEY"')
        self.source.write_text(text, encoding="utf-8")
        with mock.patch.dict(os.environ, {"OFFLINE_ROUTE_KEY": FAKE_SECRET}):
            self.assertEqual(c.route_at(self.policy)["secret"], FAKE_SECRET)
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(c.Refused, "credential unavailable"):
                c.route_at(self.policy)
        self.assertEqual(self.source.read_text(encoding="utf-8"), text)

    def test_runner_python_is_first_on_child_path_and_explicit_in_prompt_without_parent_changes(self):
        route = c.route_at(self.policy)
        with mock.patch.dict(os.environ, {"PATH": "offline-parent-path"}):
            before = dict(os.environ)
            env = c.prepare_codex(self.policy, route)
            prompt = c.prompt_for(self.policy, self.ready, None)
            self.assertEqual(dict(os.environ), before)
        parts = env["PATH"].split(os.pathsep)
        self.assertEqual(parts[0], str(Path(sys.executable).parent))
        self.assertIn("offline-parent-path", parts[1:])
        self.assertIn('"runner_python": ' + json.dumps(sys.executable), prompt)

    def test_toml_scalar_parser_rejects_duplicate_and_multiline_values(self):
        self.assertEqual(c.toml_string("model = 'literal' # comment\n", "", "model"), "literal")
        self.assertEqual(c.toml_string('model = "double" # comment\n', "", "model"), "double")
        with self.assertRaises(c.Refused):
            c.toml_string('model = "first"\nmodel = "second"\n', "", "model")
        with self.assertRaises((c.Refused, ValueError)):
            c.toml_string('model = """multi\nline"""\n', "", "model")

    def test_instance_lock_excludes_real_child_and_releases_without_deleting_file(self):
        lock = self.base / "lifecycle.lock"
        code = (
            "import importlib.util, pathlib, sys\n"
            "spec=importlib.util.spec_from_file_location('controller_child',sys.argv[1])\n"
            "c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)\n"
            "try:\n"
            " with c.instance_lock(pathlib.Path(sys.argv[2])): pass\n"
            "except c.Refused:\n"
            " sys.exit(75)\n"
        )
        command = [sys.executable, "-B", "-c", code, str(HERE / "controller.py"), str(lock)]
        with c.instance_lock(lock):
            inode = lock.stat().st_ino
            denied = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(denied.returncode, 75, denied.stderr)
        accepted = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(lock.stat().st_ino, inode)

    def test_restart_reconciles_running_identity_before_allowing_submission_without_pause(self):
        self.enable()
        for state in ("running", "uncertain"):
            with self.subTest(state=state):
                c.write_json(self.state / "checkpoint.json", {"state": state, "cycle": "original"})
                runtime = Runtime()
                _, child_patch = self.child_factory()
                with mock.patch.object(c, "create_runtime", return_value=runtime), child_patch:
                    c.serve(self.policy_path, once=True)
                self.assertTrue(runtime.calls)
                self.assertIs(runtime.calls[0], False)
                if True in runtime.calls:
                    self.assertLess(runtime.calls.index(False), runtime.calls.index(True))
                self.assertFalse((self.state / "pause.json").exists())

    def test_status_keeps_unfinished_checkpoint_local_and_does_not_create_a_pause(self):
        self.enable()
        for state in ("running", "uncertain"):
            with self.subTest(state=state):
                c.write_json(self.state / "checkpoint.json", {"state": state, "cycle": "original"})
                checked = c.inspect(self.policy)
                self.assertTrue(checked["prerequisites_passed"])
                self.assertEqual(checked["checkpoint"]["cycle"], "original")
                self.assertFalse((self.state / "pause.json").exists())

    def test_cycle_preparation_error_backs_off_before_any_child_without_global_pause(self):
        self.enable()
        with mock.patch.object(c, "prepare_codex", side_effect=OSError("offline preparation failure")), \
             mock.patch.object(c.subprocess, "Popen") as popen:
            checkpoint = c.run_cycle(self.policy, self.ready, None, {"requested": False})
        popen.assert_not_called()
        self.assertEqual(checkpoint["state"], "retry_wait")
        self.assertEqual(checkpoint["failure_count"], 1)
        self.assertGreater(checkpoint["retry_after"], 0)
        self.assertFalse((self.state / "pause.json").exists())

    def test_waiting_cycle_records_navigation_and_does_not_repeat_once(self):
        self.enable()
        children, patch = self.child_factory()
        with patch as popen, mock.patch.object(c, "create_runtime", return_value=Runtime()):
            c.serve(self.policy_path, once=True)
        self.assertEqual(popen.call_count, 1)
        checkpoint = c.read_json(self.state / "checkpoint.json")
        self.assertEqual(checkpoint["state"], "reported")
        self.assertEqual(checkpoint["report"], REPORT)
        self.assertIn("Navigation only", checkpoint["report_semantics"])
        self.assertFalse((self.state / "pause.json").exists())
        self.assertIn("不要", children[0].received.decode("utf-8"))

    def test_nonzero_timeout_and_bad_reports_use_bounded_backoff_and_no_global_pause(self):
        self.enable()
        cases = (
            {"returncode": 19},
            {"timeout": True},
            {"raw": "{broken-json"},
            {"report": dict(REPORT, status="invented")},
            {"report": dict(REPORT, next_check_seconds=True)},
        )
        for options in cases:
            with self.subTest(options=options):
                children, patch = self.child_factory(**options)
                with patch as popen:
                    checkpoint = c.run_cycle(self.policy, self.ready, None, {"requested": False})
                self.assertEqual(popen.call_count, 1)
                self.assertEqual(checkpoint["state"], "retry_wait")
                self.assertEqual(checkpoint["failure_count"], 1)
                self.assertFalse((self.state / "pause.json").exists())
                self.assertFalse(c.should_wake(self.policy, checkpoint, Runtime().observation, "same",
                                               now=checkpoint["retry_after"] - 1))
                self.assertTrue(c.should_wake(self.policy, checkpoint, Runtime().observation, "same",
                                              now=checkpoint["retry_after"] + 1))
                if options.get("timeout"):
                    self.assertTrue(children[0].terminated)

    def test_api_error_details_are_not_in_checkpoint_and_exponential_backoff_is_capped(self):
        self.enable()
        previous = None
        for failures in range(1, 7):
            with mock.patch.object(c.subprocess, "Popen", side_effect=OSError(FAKE_SECRET)), \
                 mock.patch.object(c.time, "time", return_value=1000):
                previous = c.run_cycle(self.policy, self.ready, previous, {"requested": False})
            self.assertEqual(previous["failure_count"], failures)
            expected = min(300 * (2 ** (failures - 1)), 3600)
            self.assertEqual(previous["retry_after"], 1000 + expected)
            self.assertNotIn(FAKE_SECRET, json.dumps(previous))
            self.assertFalse((self.state / "pause.json").exists())

    def test_should_wake_uses_real_changes_or_due_failure_not_waiting_poll_time(self):
        observation = Runtime().observation
        self.assertTrue(c.should_wake(self.policy, None, observation, "event-a", now=1000))
        for status in ("waiting", "blocked", "progress", "complete"):
            with self.subTest(status=status):
                checkpoint = {
                    "state": "reported", "event_key": "event-a",
                    "report": dict(REPORT, status=status), "finished_utc": "2000-01-01T00:00:00+00:00",
                }
                self.assertFalse(c.should_wake(self.policy, checkpoint, observation, "event-a", now=999999))
                self.assertTrue(c.should_wake(self.policy, checkpoint, observation, "event-b", now=999999))
        retry = {"state": "retry_wait", "event_key": "event-a", "retry_after": 1200, "failure_count": 1}
        self.assertFalse(c.should_wake(self.policy, retry, observation, "event-a", now=1199))
        self.assertTrue(c.should_wake(self.policy, retry, observation, "event-a", now=1200))

    def test_watch_key_tracks_plan_queue_evidence_and_runtime_but_not_unrelated_logs(self):
        observation = Runtime().observation
        previous = {"report": dict(REPORT, evidence=[str(self.evidence)])}
        first = c.watch_key(self.policy, previous, observation)
        self.assertEqual(first, c.watch_key(self.policy, previous, observation))
        unrelated = self.workspace / "unrelated-progress.log"
        unrelated.write_text("changing noise", encoding="utf-8")
        self.assertEqual(first, c.watch_key(self.policy, previous, observation))
        self.evidence.write_text("actual evidence changed", encoding="utf-8")
        second = c.watch_key(self.policy, previous, observation)
        self.assertNotEqual(first, second)
        self.plan.write_text("authorized plan changed", encoding="utf-8")
        third = c.watch_key(self.policy, previous, observation)
        self.assertNotEqual(second, third)
        c.write_json(self.queue, {"schema": "tcad-server-queue-v1", "tasks": [{"id": "new-task"}]})
        fourth = c.watch_key(self.policy, previous, observation)
        self.assertNotEqual(third, fourth)
        observation["fingerprint"] = "original-run-finished"
        self.assertNotEqual(fourth, c.watch_key(self.policy, previous, observation))

    def test_same_waiting_observation_across_restarts_does_not_call_llm_again(self):
        self.enable()
        _, patch = self.child_factory()
        with patch as popen, mock.patch.object(c, "create_runtime", return_value=Runtime()), \
             mock.patch.object(c.time, "time", return_value=1000):
            c.serve(self.policy_path, once=True)
        self.assertEqual(popen.call_count, 1)
        first = c.read_json(self.state / "checkpoint.json")
        self.assertIn("event_key", first)
        second_runtime = Runtime()
        with mock.patch.object(c.subprocess, "Popen") as popen, \
             mock.patch.object(c, "create_runtime", return_value=second_runtime), \
             mock.patch.object(c.time, "time", return_value=1061):
            c.serve(self.policy_path, once=True)
        popen.assert_not_called()
        self.assertIs(second_runtime.calls[0], False)
        self.assertFalse((self.state / "pause.json").exists())

    def test_progress_without_material_change_does_not_call_llm_after_minimum_interval(self):
        self.enable()
        # First reporting a navigation path that does not exist is not an
        # artifact change and must not create a self-sustaining continuation.
        _, patch = self.child_factory(report=dict(REPORT, status="progress"))
        with patch as popen, mock.patch.object(c, "create_runtime", return_value=Runtime()), \
             mock.patch.object(c.time, "time", return_value=1000):
            c.serve(self.policy_path, once=True)
        self.assertEqual(popen.call_count, 1)
        checkpoint = c.read_json(self.state / "checkpoint.json")
        self.assertFalse(checkpoint.get("continue_pending", False))
        with mock.patch.object(c.subprocess, "Popen") as popen, \
             mock.patch.object(c, "create_runtime", return_value=Runtime()), \
             mock.patch.object(c.time, "time", return_value=1061):
            c.serve(self.policy_path, once=True)
        popen.assert_not_called()

    def test_material_plan_change_records_progress_continuation_after_minimum_interval(self):
        self.enable()
        children = []
        def make(argv, **kwargs):
            child = Child(argv, report=dict(REPORT, status="progress", evidence=[]))
            communicate = child.communicate
            def material_progress(data, timeout):
                self.plan.write_text("已更新科研计划的下一阶段。\n", encoding="utf-8")
                return communicate(data, timeout)
            child.communicate = material_progress
            children.append(child)
            return child
        with mock.patch.object(c.subprocess, "Popen", side_effect=make) as popen, \
             mock.patch.object(c, "create_runtime", return_value=Runtime()), \
             mock.patch.object(c.time, "time", return_value=1000):
            c.serve(self.policy_path, once=True)
        self.assertEqual(popen.call_count, 1)
        checkpoint = c.read_json(self.state / "checkpoint.json")
        self.assertTrue(checkpoint["continue_pending"])
        event_key = c.watch_key(self.policy, checkpoint, Runtime().observation)
        self.assertFalse(c.should_wake(self.policy, checkpoint, Runtime().observation, event_key, now=1059))
        self.assertTrue(c.should_wake(self.policy, checkpoint, Runtime().observation, event_key, now=1060))

    def test_runtime_error_preserves_checkpoint_and_records_redacted_backoff_without_llm(self):
        self.enable()
        checkpoint = {"state": "retry_wait", "cycle": "original-cycle",
                      "failure_count": 2, "retry_after": 1500}
        c.write_json(self.state / "checkpoint.json", checkpoint)
        def unavailable(allow_submit):
            raise OSError(FAKE_SECRET)
        runtime = Runtime(on_tick=unavailable)
        with mock.patch.object(c.subprocess, "Popen") as popen, \
             mock.patch.object(c, "create_runtime", return_value=runtime), \
             mock.patch.object(c.time, "time", return_value=1000):
            c.serve(self.policy_path, once=True)
        self.assertEqual(runtime.calls, [False])
        popen.assert_not_called()
        self.assertEqual(c.read_json(self.state / "checkpoint.json"), checkpoint)
        error = c.read_json(self.state / "runtime-error.json")
        self.assertEqual(error["failure_count"], 1)
        self.assertEqual(error["retry_after"], 1300)
        self.assertNotIn(FAKE_SECRET, json.dumps(error))
        self.assertFalse((self.state / "pause.json").exists())

    def test_failure_restart_reconciles_before_backoff_retry_without_clearing_identity(self):
        self.enable()
        failure = {"state": "retry_wait", "failure_count": 2,
                   "retry_after": 9999999999, "event_key": "original-event",
                   "cycle": "original-cycle"}
        c.write_json(self.state / "checkpoint.json", failure)
        runtime = Runtime()
        with mock.patch.object(c.subprocess, "Popen") as popen, \
             mock.patch.object(c, "create_runtime", return_value=runtime):
            c.serve(self.policy_path, once=True)
        popen.assert_not_called()
        self.assertIs(runtime.calls[0], False)
        after = c.read_json(self.state / "checkpoint.json")
        self.assertEqual(after["cycle"], "original-cycle")
        self.assertEqual(after["failure_count"], 2)
        self.assertFalse((self.state / "pause.json").exists())

    def test_operator_disarm_during_reconciliation_prevents_submission_and_llm(self):
        self.enable()
        def disarm(allow_submit):
            if not allow_submit:
                self.policy["enabled"] = False
                self.save_policy()
        runtime = Runtime(on_tick=disarm)
        with mock.patch.object(c.subprocess, "Popen") as popen, \
             mock.patch.object(c, "create_runtime", return_value=runtime):
            c.serve(self.policy_path, once=True)
        self.assertTrue(runtime.calls)
        self.assertNotIn(True, runtime.calls)
        popen.assert_not_called()

    def test_report_complete_requires_empty_runtime_queue_before_idle(self):
        self.enable()
        _, patch = self.child_factory(report=dict(REPORT, status="complete"))
        active_runtime = Runtime()
        with patch as popen, mock.patch.object(c, "create_runtime", return_value=active_runtime), \
             mock.patch.object(c.time, "time", return_value=1000):
            c.serve(self.policy_path, once=True)
        self.assertEqual(popen.call_count, 1)
        self.assertNotEqual(c.read_json(self.state / "checkpoint.json")["state"], "idle")
        self.assertFalse((self.state / "pause.json").exists())
        empty = copy.deepcopy(active_runtime.observation)
        empty.update(fingerprint="all-original-jobs-collected", active_count=0, pending_count=0,
                     queue_complete=True)
        _, patch = self.child_factory(report=dict(REPORT, status="complete"))
        with patch as popen, mock.patch.object(c, "create_runtime", return_value=Runtime(empty)), \
             mock.patch.object(c.time, "time", return_value=1061):
            c.serve(self.policy_path, once=True)
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(c.read_json(self.state / "checkpoint.json")["state"], "idle")
        self.assertFalse((self.state / "pause.json").exists())

    def test_complete_report_cannot_idle_with_pending_repair_or_local_block(self):
        self.enable()
        for name, value in (("pending_count", 1), ("repair_requests", [{"id": "original-task"}]),
                            ("blocked_tasks", [{"id": "blocked-task"}])):
            with self.subTest(outstanding=name):
                checkpoint = self.state / "checkpoint.json"
                if checkpoint.exists():
                    checkpoint.unlink()
                observation = Runtime().observation
                observation.update(active_count=0, pending_count=0, queue_complete=True)
                observation[name] = value
                _, patch = self.child_factory(report=dict(REPORT, status="complete"))
                runtime = Runtime(observation)
                with patch as popen, mock.patch.object(c, "create_runtime", return_value=runtime):
                    c.serve(self.policy_path, once=True)
                self.assertEqual(popen.call_count, 1)
                self.assertNotEqual(c.read_json(checkpoint)["state"], "idle")
                self.assertFalse((self.state / "pause.json").exists())

    def test_invocation_uses_scoped_native_schema_and_stdin_without_credential_arguments(self):
        cycle = self.state / "cycles" / "offline-cycle"
        argv = c.invocation(self.policy, cycle)
        self.assertEqual(argv[:2], [self.policy["codex_binary"], "exec"])
        self.assertEqual(argv[argv.index("--cd") + 1], str(self.workspace))
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
        self.assertIn('approval_policy="never"', argv)
        self.assertEqual(Path(argv[argv.index("--output-schema") + 1]), HERE / "report.schema.json")
        self.assertEqual(Path(argv[argv.index("--output-last-message") + 1]), cycle / "report.json")
        self.assertEqual(argv[-1], "-")
        self.assertNotIn(FAKE_SECRET, json.dumps(argv))
        self.assertFalse(self.state.exists())

    def test_blocked_and_complete_reports_are_local_and_do_not_pause_controller(self):
        self.enable()
        for status in ("blocked", "complete"):
            with self.subTest(status=status):
                for name in ("pause.json", "checkpoint.json"):
                    path = self.state / name
                    if path.exists():
                        path.unlink()
                _, patch = self.child_factory(report=dict(REPORT, status=status))
                with patch as popen:
                    checkpoint = c.run_cycle(self.policy, self.ready, None, {"requested": False})
                self.assertEqual(popen.call_count, 1)
                self.assertEqual(checkpoint["state"], "reported")
                self.assertEqual(checkpoint["report"]["status"], status)
                self.assertFalse((self.state / "pause.json").exists())
        c.pause(self.policy, "operator stop")
        runtime = Runtime()
        with mock.patch.object(c.subprocess, "Popen") as popen, \
             mock.patch.object(c, "create_runtime", return_value=runtime):
            c.serve(self.policy_path, once=True)
        popen.assert_not_called()
        self.assertNotIn(True, runtime.calls)

    def test_operator_pause_during_a_cycle_finishes_checkpoint_without_new_cycle(self):
        self.enable()
        child = None
        def make(argv, **kwargs):
            nonlocal child
            child = Child(argv)
            communicate = child.communicate
            def finish_then_pause(data, timeout):
                communicate(data, timeout)
                c.pause(self.policy, "operator pause during bounded cycle")
            child.communicate = finish_then_pause
            return child
        with mock.patch.object(c.subprocess, "Popen", side_effect=make) as popen, \
             mock.patch.object(c, "create_runtime", return_value=Runtime()):
            c.serve(self.policy_path, once=True)
        self.assertEqual(popen.call_count, 1)
        self.assertFalse(child.terminated)
        self.assertFalse(child.killed)
        self.assertEqual(c.read_json(self.state / "checkpoint.json")["state"], "reported")

    def test_stop_signal_finishes_current_cycle_without_remote_or_local_kill(self):
        self.enable()
        child = None
        def make(argv, **kwargs):
            nonlocal child
            child = Child(argv)
            communicate = child.communicate
            def finish_after_stop(data, timeout):
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                communicate(data, timeout)
            child.communicate = finish_after_stop
            return child
        old_handler = signal.getsignal(signal.SIGTERM)
        with mock.patch.object(c.subprocess, "Popen", side_effect=make) as popen, \
             mock.patch.object(c, "create_runtime", return_value=Runtime()):
            c.serve(self.policy_path, once=True)
        self.assertEqual(popen.call_count, 1)
        self.assertFalse(child.terminated)
        self.assertFalse(child.killed)
        self.assertEqual(signal.getsignal(signal.SIGTERM), old_handler)
        self.assertEqual(c.read_json(self.state / "checkpoint.json")["state"], "reported")

    def test_clear_pause_requires_reconciliation_and_cannot_clear_live_lock(self):
        c.write_json(self.state / "checkpoint.json", {"state": "uncertain", "cycle": "original"})
        c.pause(self.policy, "unknown state", reconcile=True)
        code, _, stderr = self.cli("clear-pause")
        self.assertEqual(code, 2)
        self.assertIn("--reconciled", stderr)
        self.assertTrue((self.state / "pause.json").exists())
        with c.instance_lock(self.state / "controller.lock"):
            code, _, stderr = self.cli("clear-pause", "--reconciled")
            self.assertEqual(code, 2)
            self.assertIn("lifecycle lock", stderr)
            self.assertTrue((self.state / "pause.json").exists())
        code, stdout, stderr = self.cli("clear-pause", "--reconciled")
        self.assertEqual(code, 0, stderr)
        self.assertFalse((self.state / "pause.json").exists())
        self.assertEqual(c.read_json(self.state / "checkpoint.json")["state"], "operator_reconciled")
        self.assertFalse(json.loads(stdout)["codex_started"])

    def test_arm_pins_evidence_but_never_starts_a_process(self):
        self.policy["readiness"] = None
        self.save_policy()
        with mock.patch.object(c.subprocess, "Popen") as popen:
            code, stdout, stderr = self.cli("arm", "--readiness", str(self.ready_path))
        self.assertEqual(code, 0, stderr)
        popen.assert_not_called()
        self.assertFalse(json.loads(stdout)["codex_started"])
        armed = c.policy_at(self.policy_path)
        self.assertTrue(armed["enabled"])
        self.assertEqual(armed["readiness"]["sha256"], c.digest(self.ready_path))

    def test_v1_policy_is_explicitly_migrated_disabled_without_starting_anything(self):
        old = copy.deepcopy(self.policy)
        old.update(schema="tcad-server-codex-v1", enabled=True, max_parallel_jobs=3)
        for key in ("plan_file", "queue_file", "poll_interval_seconds", "runner_timeout_seconds",
                    "failure_backoff_seconds", "max_failure_backoff_seconds", "repair_attempt_limit"):
            old.pop(key, None)
        c.write_json(self.policy_path, old)
        with self.assertRaisesRegex(c.Refused, "migrat"):
            c.policy_at(self.policy_path)
        output = self.base / "policy-v2.json"
        with mock.patch.object(c.subprocess, "Popen") as popen, \
             mock.patch.object(c, "create_runtime") as runtime:
            code, _, stderr = self.cli("migrate", "--output", str(output))
        self.assertEqual(code, 0, stderr)
        popen.assert_not_called()
        runtime.assert_not_called()
        migrated = c.read_json(output)
        self.assertEqual(migrated["schema"], "tcad-server-codex-v2")
        self.assertFalse(migrated["enabled"])
        self.assertIsNone(migrated["readiness"])
        self.assertEqual(migrated["max_parallel_jobs"], 9)
        for key in ("workspace", "source_codex_config", "codex_binary", "runner_python"):
            self.assertEqual(migrated[key], old[key])
        self.assertTrue(Path(migrated["plan_file"]).is_absolute())
        self.assertTrue(Path(migrated["queue_file"]).is_absolute())
        self.assertEqual(c.read_json(self.policy_path), old)
        self.assertFalse(self.state.exists())

    def test_in_place_v1_migration_preserves_original_backup_bytes(self):
        old = copy.deepcopy(self.policy)
        old.update(schema="tcad-server-codex-v1", enabled=True)
        c.write_json(self.policy_path, old)
        original = self.policy_path.read_bytes()
        before = {str(path) for path in self.base.iterdir()}
        with mock.patch.object(c.subprocess, "Popen") as popen:
            code, _, stderr = self.cli("migrate")
        self.assertEqual(code, 0, stderr)
        popen.assert_not_called()
        new_files = [path for path in self.base.iterdir() if str(path) not in before and path.is_file()]
        self.assertTrue(any(path.read_bytes() == original for path in new_files))
        self.assertEqual(c.read_json(self.policy_path)["schema"], "tcad-server-codex-v2")
        self.assertFalse(c.read_json(self.policy_path)["enabled"])

    def test_serve_with_missing_readiness_cannot_submit_or_start_codex(self):
        self.enable()
        self.ready_path.unlink()
        runtime = Runtime()
        with mock.patch.object(c.subprocess, "Popen") as popen, \
             mock.patch.object(c, "create_runtime", return_value=runtime):
            with self.assertRaises(c.Refused):
                c.serve(self.policy_path, once=True)
        popen.assert_not_called()
        self.assertNotIn(True, runtime.calls)

    @unittest.skipUnless(os.name == "posix", "Requires native POSIX mode/owner metadata")
    def test_atomic_policy_update_preserves_mode_owner_and_new_files_are_private(self):
        os.chmod(self.policy_path, 0o640)
        before = self.policy_path.stat()
        code, _, stderr = self.cli("arm", "--readiness", str(self.ready_path))
        self.assertEqual(code, 0, stderr)
        after = self.policy_path.stat()
        self.assertEqual(stat.S_IMODE(after.st_mode), 0o640)
        self.assertEqual((after.st_uid, after.st_gid), (before.st_uid, before.st_gid))
        self.assertTrue(c.read_json(self.policy_path)["enabled"])
        new_file = self.base / "new-private.json"
        c.write_json(new_file, {"test_fixture": True})
        self.assertEqual(stat.S_IMODE(new_file.stat().st_mode), 0o600)
        self.assertEqual(list(self.base.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
