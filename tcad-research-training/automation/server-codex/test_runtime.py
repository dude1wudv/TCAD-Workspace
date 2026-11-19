"""Offline contract tests. Every original-runner invocation is intercepted."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("autonomy_runtime_tested", HERE / "runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        (self.workspace / ".git").mkdir()
        self.original_root = self.workspace / "local_runtime/cloud-benchmark/profile"
        self.profile = self.workspace / "connection.json"
        self.cfg = {
            "backend": "ssh-runtime", "ssh_target": "fixture-only",
            "runtime_entry": "/fixture/runtime", "remote_root": "/fixture/pool",
            "local_state_root": str(self.original_root), "parallel_capacity": 9,
        }
        self.save(self.profile, self.cfg)
        self.queue = self.workspace / "work-items.json"
        self.policy = {
            "workspace": str(self.workspace), "state_dir": str(self.base / "state"),
            "runner_python": sys.executable, "queue_file": str(self.queue),
            "max_parallel_jobs": 9, "runner_timeout_seconds": 1,
            "repair_attempt_limit": 2, "failure_backoff_seconds": 0,
            "max_failure_backoff_seconds": 0,
        }
        self.ready = {"connection": {"path": str(self.profile),
                                     "sha256": runtime.file_digest(self.profile)},
                      "new_jobs_authorized": True}
        self.tasks = []
        self.calls = []
        self.behavior = {}
        self.collect_failures = set()
        self.patcher = patch.object(runtime.subprocess, "run", side_effect=self.fake_runner)
        self.mock_runner = self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def queue_tasks(self, tasks=None):
        self.save(self.queue, {"schema": runtime.QUEUE_SCHEMA,
                               "tasks": self.tasks if tasks is None else tasks})

    def engine(self):
        return runtime.Runtime(self.policy, self.ready)

    def task(self, task_id, backend="tcad", value=None, **options):
        relative = ("projects/" + task_id if backend == "tcad" else
                    "local_runtime/cloud-benchmark/geant4-preparation/inputs/" + task_id)
        project = self.workspace / relative
        project.mkdir(parents=True)
        if backend == "tcad":
            self.save(project / "project.json", {
                "name": task_id, "steps": [
                    {"tool": "sdevice", "args": ["deck.cmd"], "outputs": ["result.tdr"]}]})
            if "cpu_sets" in self.cfg:
                path = project / "project.json"
                threads = self.cfg.get("requested_threads", len(self.cfg["cpu_sets"][0]))
                if isinstance(threads, int):
                    self.save(path, dict(runtime.read_json(path), native_threads=threads, native_cores=threads))
            (project / "deck.cmd").write_text(value or task_id, encoding="utf-8")
        else:
            (project / "task.sh").write_text("#!/bin/sh\n" + (value or task_id) + "\n", encoding="utf-8")
        task = {"id": task_id, "backend": backend, "project": relative,
                "depends_on": [], "requires": [], "repair_of": None, "repair_reason": ""}
        task.update(options)
        self.tasks.append(task)
        self.queue_tasks()
        return task

    def record_path(self, backend, run_id, root=None):
        root = self.original_root if root is None else root
        if backend == "tcad":
            return root / "runs" / run_id / "manifest.json"
        return root / "dram-see-v4/transport-probe/operations" / run_id / "operation.json"

    def make_record(self, backend, run_id, project, slot, root=None, capacity=None):
        cfg = self.cfg if capacity is None else dict(self.cfg, parallel_capacity=capacity)
        if capacity is not None and capacity != self.cfg.get("parallel_capacity"):
            cfg.pop("cpu_sets", None)
            cfg.pop("requested_threads", None)
            if capacity == 4:
                cfg.update(cpu_sets=[[0, 1], [2, 3], [4, 5], [6, 7]], requested_threads=2)
        resources = runtime.profile_resources(cfg)
        capacity = resources["capacity"]
        is_mc = "cpu_sets" in cfg
        identity = {key: cfg[key] for key in
                    ("backend", "ssh_target", "runtime_entry", "remote_root")}
        directory = cfg["remote_root"] + (
            "/runs/" if backend == "tcad" else "/dram-see-v4/transport-probe/operations/") + run_id
        policy = {"schema": resources["schema"],
                  "slot": slot, "pool_root": cfg["remote_root"],
                  "connection_identity": identity, "work_id": run_id,
                  "remote_directory": directory, "kind": "run" if backend == "tcad" else "operation"}
        if capacity != 3 or is_mc:
            policy["capacity"] = capacity
        if is_mc:
            cpu_set = resources["cpu_sets"][slot]
            policy.update(cpu_set=cpu_set, requested_threads=len(cpu_set))
            if resources["schema"] == runtime.DYNAMIC_SLOTS_SCHEMA:
                policy["cpu_sets"] = resources["cpu_sets"]
        else:
            policy["cpu"] = slot
        record = {
            "schema": "tcad-native-run-r2" if backend == "tcad" else "dram-see-v4-transport-operation-v2",
            "run_id" if backend == "tcad" else "label": run_id,
            "project_directory" if backend == "tcad" else "input_directory": str(project),
            "state": "RUNNING", "connection_identity": identity, "remote_directory": directory,
            "parallel_policy": policy, "parallel_slot_released": False, "remote_exit_code": None,
            "input_sha256": {p.relative_to(project).as_posix(): runtime.file_digest(p)
                             for p in project.rglob("*") if p.is_file()},
        }
        self.save(self.record_path(backend, run_id, root), record)
        return record

    def fake_runner(self, argv, **kwargs):
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(argv[2], "--connection")
        backend = "tcad" if Path(argv[1]).name == "tcad.py" else "geant4"
        rest = argv[4:]
        if rest[0] in ("status", "collect"):
            command, run_id = rest[:2]
            self.assertEqual(rest[2:], ["--json"])
        elif backend == "tcad":
            self.assertEqual(rest[0], "run")
            command, project = "run", Path(rest[1])
            run_id = rest[rest.index("--run-id") + 1]
        else:
            command, run_id, project = "run", rest[0], Path(rest[1])
        target = (self.policy.get("transport_connection_file", str(self.profile))
                  if backend == "geant4" else str(self.profile))
        state_path = self.base / "state/runtime.json"
        if command != "run" and state_path.exists():
            intent = next(v for v in runtime.read_json(state_path)["intents"].values()
                          if v["run_id"] == run_id and v["backend"] == backend)
            target = intent["connection"]["path"]
        self.assertEqual(Path(argv[3]), Path(target).resolve())
        if not hasattr(self, "connection_calls"):
            self.connection_calls = []
        self.connection_calls.append((backend, command, run_id, str(Path(argv[3]))))
        self.calls.append((backend, command, run_id))
        path = self.record_path(backend, run_id)
        if command == "run":
            slot = int(rest[rest.index("--parallel-slot") + 1])
            self.assertIn("--detach", rest)
            # The most important crash-safety invariant: persisted BEFORE invocation.
            durable = runtime.read_json(self.base / "state/runtime.json")
            self.assertTrue(any(v["run_id"] == run_id and v["slot"] == slot
                                for v in durable["intents"].values()))
            mode = self.behavior.get(project.name)
            if mode != "timeout_without_manifest":
                cfg = runtime.read_json(argv[3])
                self.make_record(backend, run_id, project, slot, capacity=cfg.get("parallel_capacity", 3))
            if mode in ("timeout_after_launch", "timeout_without_manifest"):
                raise subprocess.TimeoutExpired(argv, 1)
            if mode == "nonzero":
                return subprocess.CompletedProcess(argv, 1, "", "Slot reservation or staging refused")
            if mode == "invalid_json":
                return subprocess.CompletedProcess(argv, 0, "unexpected banner", "")
            if mode == "finished_nonzero":
                record = runtime.read_json(path)
                identity = {
                    "schema": "tcad-process-identity-r1", "run_id": run_id,
                    "pid": 24465, "start_ticks": 816103,
                    "boot_id": "0c84fe9f-17b6-4e71-9aad-a6412f1cf920",
                    "cwd": record["remote_directory"], "script_sha256": "a" * 64,
                }
                observed = {
                    "label": run_id, "directory": record["remote_directory"],
                    "exists": True, "status": "FINISHED", "alive": False,
                    "remote_exit_code": 1, "identity": identity,
                    "log_tail": "task.sh: line 7: geant4.sh: No such file or directory",
                }
                record.update(state="EXECUTED", remote_exit_code=1, ssh_exit_code=0,
                              script_sha256=identity["script_sha256"],
                              process_identity=identity, last_observation=observed)
                self.save(path, record)
                value = dict(observed, local_state="EXECUTED", ssh_exit_code=0)
                return subprocess.CompletedProcess(
                    argv, 1, json.dumps(value),
                    "/etc/profile: line 77: /opt/rh/devtoolset-8/enable: No such file or directory")
            return subprocess.CompletedProcess(argv, 0, json.dumps({"status": "RUNNING", "alive": True}), "")
        if not path.exists():
            return subprocess.CompletedProcess(argv, 1, "", "Original manifest missing")
        record = runtime.read_json(path)
        if command == "status":
            record["updated_utc"] = str(len(self.calls))
            self.save(path, record)
            state = record["state"]
            value = {"status": "FINISHED" if state in (*runtime.TERMINAL, "EXECUTED") else
                     "RUNNING" if state == "RUNNING" else "NOT_LAUNCHED",
                     "alive": state == "RUNNING", "local_state": state,
                     "remote_exit_code": record.get("remote_exit_code")}
        else:
            if run_id in self.collect_failures:
                return subprocess.CompletedProcess(argv, 1, "", "Collection disconnected")
            self.assertIn(record["state"], (*runtime.TERMINAL, "EXECUTED"))
            self.collect_receipt(backend, run_id)
            record = runtime.read_json(path)
            value = {"status" if backend == "tcad" else "state": record["state"],
                     "remote_exit_code": record["remote_exit_code"]}
        return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")

    def finish(self, task_id, exit_code=0):
        intent = runtime.read_json(self.base / "state/runtime.json")["intents"][task_id]
        path = self.record_path(intent["backend"], intent["run_id"])
        record = runtime.read_json(path)
        record.update(state="EXECUTED", remote_exit_code=exit_code)
        self.save(path, record)
        return intent

    def collect_receipt(self, backend, run_id, released=True):
        path = self.record_path(backend, run_id)
        record = runtime.read_json(path)
        archive = path.parent / "results.tar"
        archive.write_bytes(b"offline fixture; original runner validation mocked")
        record.update(
            state=("COLLECTED" if backend == "tcad" else "COLLECTED_PENDING_AUDIT")
            if record.get("remote_exit_code") == 0 else "FAILED_COLLECTED",
            collection_verified=True, collection_exit_code=0, parallel_slot_released=released)
        record["results_sha256" if backend == "tcad" else "archive_sha256"] = runtime.file_digest(archive)
        self.save(path, record)

    def runs(self):
        return [item for item in self.calls if item[1] == "run"]

    def multicore_profile(self):
        # Keep the original profile file immutable for old persisted intents.
        self.profile = self.workspace / "connection-centos79-guest-mc2-four.json"
        self.cfg = dict(self.cfg, parallel_capacity=4,
                        cpu_sets=[[0, 1], [2, 3], [4, 5], [6, 7]], requested_threads=2)
        self.save(self.profile, self.cfg)
        self.ready["connection"] = {"path": str(self.profile),
                                     "sha256": runtime.file_digest(self.profile)}
        self.policy["max_parallel_jobs"] = 4

    def enable_transport(self, path=None):
        if path is None:
            path = self.workspace / "connection-local-centos79-nine.json"
            cfg = dict(self.cfg, parallel_capacity=9)
            cfg.pop("cpu_sets", None)
            cfg.pop("requested_threads", None)
            self.save(path, cfg)
        self.policy["transport_connection_file"] = str(path)
        self.ready["transport_connection"] = {"path": str(path), "sha256": runtime.file_digest(path)}
        return path

    def test_backend_phases_drain_alternate_restart_and_keep_global_four_limit(self):
        self.multicore_profile()
        transport = self.enable_transport()
        for i in range(5):
            self.task("mc" + str(i))
        for i in range(5):
            self.task("g" + str(i), backend="geant4")
        first = self.engine().tick()
        self.assertEqual(first["active_count"], 4)
        self.assertEqual(len(self.runs()), 4)
        original = runtime.read_json(self.base / "state/runtime.json")["intents"]
        self.finish("mc0")
        partial = self.engine().tick()
        self.assertEqual((partial["active_count"], len(self.runs())), (3, 4))
        self.assertTrue(partial["pool_phase"]["draining"])
        self.assertTrue(any(v["reason"] == "pool_profile_waiting_for_idle"
                            for v in partial["pending_tasks"]))
        self.engine().tick()  # restart must retain the drain and all original IDs
        self.assertEqual(len(self.runs()), 4)
        for i in range(1, 4):
            self.finish("mc" + str(i))
        switched = self.engine().tick()
        self.assertEqual((switched["active_count"], len(self.runs())), (4, 8))
        intents = runtime.read_json(self.base / "state/runtime.json")["intents"]
        for i in range(4):
            self.assertEqual(intents["g" + str(i)]["connection"]["path"], str(transport))
            self.assertEqual(intents["g" + str(i)]["requested_resources"]["requested_threads"], 1)
            self.assertEqual(intents["g" + str(i)]["requested_resources"]["cpu_set"], [i])
            self.assertEqual(intents["mc" + str(i)]["run_id"], original["mc" + str(i)]["run_id"])
        self.assertNotIn("mc4", intents)
        self.assertNotIn("g4", intents)
        for i in range(4):
            self.finish("g" + str(i))
        back = self.engine().tick()
        self.assertEqual((back["active_count"], len(self.runs())), (1, 9))
        self.assertEqual(back["pool_phase"]["schema"], "tcad-shared-gate-slots-r4")
        self.finish("mc4")
        last = self.engine().tick()
        self.assertEqual((last["active_count"], len(self.runs())), (1, 10))
        self.assertEqual(len({v[2] for v in self.runs()}), 10)
        self.assertEqual(last["backend_resources"]["geant4"]["requested_threads"], 1)
        self.assertEqual(last["scientific_acceptance"], "not_assessed")

    def test_backend_phase_waits_for_release_without_retrying_original_id(self):
        self.multicore_profile()
        self.enable_transport()
        self.task("mc")
        self.engine().tick()
        old = self.finish("mc")
        self.collect_receipt("tcad", old["run_id"], released=False)
        self.collect_failures.add(old["run_id"])
        self.task("transport", backend="geant4")
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertTrue(result["pool_phase"]["draining"])
        self.assertEqual(result["active_count"], 1)
        self.collect_failures.clear()
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 2)
        self.assertEqual(result["pool_phase"]["schema"], "tcad-shared-gate-slots-r3")

    def test_backend_phase_does_not_treat_string_release_flag_as_idle(self):
        self.multicore_profile()
        self.enable_transport()
        self.task("mc")
        self.engine().tick()
        old = self.finish("mc")
        self.collect_receipt("tcad", old["run_id"])
        path = self.record_path("tcad", old["run_id"])
        record = runtime.read_json(path)
        record["parallel_slot_released"] = "false"
        self.save(path, record)
        self.collect_failures.add(old["run_id"])
        self.task("transport", backend="geant4")
        result = self.engine().tick()
        self.assertEqual((result["active_count"], len(self.runs())), (1, 1))
        self.assertTrue(result["pool_phase"]["draining"])

    def test_backend_external_release_requires_archive_verification_before_switch(self):
        self.multicore_profile()
        self.enable_transport()
        project = self.workspace / "external"
        project.mkdir()
        self.make_record("geant4", "external", project, 8, capacity=9)
        self.collect_receipt("geant4", "external")
        archive = self.record_path("geant4", "external").parent / "results.tar"
        frozen = archive.read_bytes()
        archive.write_bytes(b"invalid")
        self.task("mc")
        result = self.engine().tick()
        self.assertEqual(result["active_count"], 1)
        self.assertTrue(result["pool_phase"]["draining"])
        self.assertEqual(self.calls, [])
        archive.write_bytes(frozen)
        result = self.engine().tick()
        self.assertEqual((result["active_count"], len(self.runs())), (1, 1))
        self.assertEqual(self.runs()[0][0], "tcad")

    def test_backend_transport_failure_proposes_single_thread_repair_and_never_replays(self):
        self.multicore_profile()
        transport = self.enable_transport()
        self.task("transport", backend="geant4")
        self.behavior["transport"] = "finished_nonzero"
        first = self.engine().tick()
        old = runtime.read_json(self.base / "state/runtime.json")["intents"]["transport"]
        # The original failed run is collected before proposing any repair.
        result = self.engine().tick()
        self.assertEqual(result["active_count"], 0)
        request = result["repair_requests"][0]
        self.assertEqual(request["required_resources"]["requested_threads"], 1)
        self.assertEqual(request["required_resources"]["capacity"], 9)
        self.task("transport-fix", backend="geant4", value="corrected environment setup",
                  repair_of="transport", repair_reason="Use the collected environment failure")
        result = self.engine().tick()
        intents = runtime.read_json(self.base / "state/runtime.json")["intents"]
        self.assertEqual(intents["transport-fix"]["connection"]["path"], str(transport))
        self.assertNotEqual(intents["transport-fix"]["run_id"], old["run_id"])
        self.assertEqual(len(self.runs()), 2)
        self.assertEqual(sum(v[2] == old["run_id"] for v in self.runs()), 1)
        self.assertEqual(result["active_count"], 1)

    def test_backend_uncertain_transport_launch_never_replays_or_switches(self):
        self.multicore_profile()
        self.enable_transport()
        self.task("transport", backend="geant4")
        self.behavior["transport"] = "timeout_without_manifest"
        self.engine().tick()
        self.task("mc")
        for _ in range(2):
            result = self.engine().tick()
            self.assertEqual(result["active_count"], 1)
            self.assertTrue(result["pool_phase"]["draining"])
            self.assertEqual(result["repair_requests"], [])
        self.assertEqual(len(self.runs()), 1)

    def test_backend_recovers_old_tcad_with_its_nine_profile_then_new_mc_repair(self):
        old_profile = self.profile
        self.task("old")
        self.engine().tick()
        old = self.finish("old", 143)
        self.multicore_profile()
        self.enable_transport(old_profile)
        self.task("repair", repair_of="old", repair_reason="Use new two-thread inputs")
        before = len(self.calls)
        result = self.engine().tick()
        self.assertFalse(result["discovery_uncertain"])
        calls = self.connection_calls[before:]
        self.assertEqual([v[1] for v in calls[:2]], ["status", "collect"])
        self.assertTrue(all(v[3] == str(old_profile) for v in calls[:2]))
        self.assertTrue(all(v[2] != old["run_id"] for v in self.runs()[1:]))
        self.assertEqual(len(self.runs()), 2)
        self.assertEqual(result["repair_requests"], [])
        intents = runtime.read_json(self.base / "state/runtime.json")["intents"]
        self.assertEqual(intents["old"]["connection"], old["connection"])
        self.assertEqual(intents["repair"]["requested_resources"]["requested_threads"], 2)

    def test_backend_mixed_capacity_external_work_waits_then_explicitly_collects(self):
        self.multicore_profile()
        self.enable_transport()
        a = self.task("recover-mc", adopt_run_id="probe-mc")
        b = self.task("recover-g", backend="geant4", adopt_run_id="probe-g")
        self.make_record("tcad", "probe-mc", self.workspace / a["project"], 0, capacity=4)
        self.make_record("geant4", "probe-g", self.workspace / b["project"], 0, capacity=9)
        self.task("new-mc")
        # First only discover the external records, without implicitly adopting.
        self.queue_tasks([self.tasks[-1]])
        result = self.engine().tick()
        self.assertTrue(result["discovery_uncertain"])
        self.assertEqual(result["active_count"], 2)  # Both use slot 0; count jobs.
        self.assertEqual(self.calls, [])
        for backend, run_id in (("tcad", "probe-mc"), ("geant4", "probe-g")):
            path = self.record_path(backend, run_id)
            record = runtime.read_json(path)
            record.update(state="EXECUTED", remote_exit_code=0)
            self.save(path, record)
        self.queue_tasks()
        result = self.engine().tick(allow_submit=False)
        self.assertFalse(result["discovery_uncertain"])
        self.assertEqual(result["active_count"], 0)
        self.assertEqual([v[1] for v in self.calls], ["status", "collect", "status", "collect"])
        self.assertEqual(self.runs(), [])

    def test_backend_invalid_tcad_candidate_does_not_starve_ready_transport(self):
        self.multicore_profile()
        self.enable_transport()
        task = self.task("invalid-mc")
        path = self.workspace / task["project"] / "project.json"
        spec = runtime.read_json(path)
        spec.pop("native_threads")
        self.save(path, spec)
        self.task("transport", backend="geant4")
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(self.runs()[0][0], "geant4")
        self.assertEqual(result["active_count"], 1)

    def test_backend_profile_must_be_same_pool_and_single_thread_without_sha_blocking(self):
        self.multicore_profile()
        path = self.enable_transport()
        original = runtime.read_json(path)
        for update in ({"remote_root": "/other/pool"}, {"ssh_target": "other-guest"},
                       {"local_state_root": str(self.workspace / "local_runtime/cloud-benchmark/other")},
                       {"parallel_capacity": 4, "cpu_sets": [[0, 1], [2, 3], [4, 5], [6, 7]], "requested_threads": 2}):
            with self.subTest(update=update):
                self.save(path, dict(original, **update))
                with self.assertRaises(ValueError):
                    self.engine().tick()
        # Stale/omitted sha256 on transport_connection no longer blocks when semantics match.
        self.save(path, original)
        self.ready["transport_connection"]["sha256"] = "a" * 64
        self.engine().tick()
        self.ready["transport_connection"] = str(path)
        self.engine().tick()
        self.assertEqual(self.calls, [])

    def test_multicore_four_slots_restart_collection_and_refill(self):
        self.multicore_profile()
        for index in range(5):
            self.task("mc" + str(index))
        result = self.engine().tick()
        self.assertEqual((result["active_count"], result["pending_count"]), (4, 1))
        original = runtime.read_json(self.base / "state/runtime.json")["intents"]
        for index in range(4):
            requested = original["mc" + str(index)]["requested_resources"]
            self.assertEqual(requested, {
                "schema": "tcad-shared-gate-slots-r4", "capacity": 4,
                "cpu_set": [2 * index, 2 * index + 1], "requested_threads": 2})
        self.engine().tick(allow_submit=False)
        self.assertEqual(len(self.runs()), 4)
        old = self.finish("mc0")
        result = self.engine().tick()
        self.assertEqual((len(self.runs()), result["active_count"]), (5, 4))
        now = runtime.read_json(self.base / "state/runtime.json")["intents"]
        self.assertEqual(now["mc4"]["slot"], old["slot"])
        self.assertEqual(now["mc0"]["run_id"], old["run_id"])
        self.assertEqual(result["scientific_acceptance"], "not_assessed")
        self.assertEqual(result["profile_resources"]["requested_threads"], 2)

    def test_multicore_metadata_required_without_mutating_inputs(self):
        self.multicore_profile()
        for key, value in (("native_threads", None), ("native_threads", 1),
                           ("native_cores", 1), ("native_threads", True)):
            with self.subTest(key=key, value=value):
                task = self.task("bad-" + str(len(self.tasks)))
                path = self.workspace / task["project"] / "project.json"
                spec = runtime.read_json(path)
                if value is None:
                    spec.pop(key)
                else:
                    spec[key] = value
                self.save(path, spec)
                before = path.read_bytes()
                result = self.engine().tick()
                self.assertEqual(self.calls, [])
                self.assertTrue(any(v["id"] == task["id"] and "native_threads=2" in v.get("detail", "")
                                    for v in result["blocked_tasks"]))
                self.assertEqual(path.read_bytes(), before)

    def test_multicore_geant4_refused_without_switching_profile(self):
        self.multicore_profile()
        self.task("transport", backend="geant4")
        self.task("device")
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertTrue(all(v[0] == "tcad" for v in self.calls))
        self.assertTrue(any("idle pool" in v.get("detail", "") for v in result["blocked_tasks"]))
        self.assertEqual(result["active_count"], 1)

    def test_multicore_discovery_rejects_every_resource_policy_mismatch(self):
        self.multicore_profile()
        project = self.workspace / "external"
        project.mkdir()
        self.task("device")
        path = self.record_path("tcad", "external")
        for key, value in (("cpu_set", [1, 2]), ("requested_threads", 1),
                           ("requested_threads", True), ("schema", "tcad-shared-gate-slots-r3"),
                           ("capacity", 9), ("cpu", 0)):
            with self.subTest(key=key):
                record = self.make_record("tcad", "external", project, 0)
                record["parallel_policy"][key] = value
                self.save(path, record)
                result = self.engine().tick()
                self.assertTrue(result["discovery_uncertain"])
                self.assertEqual(self.calls, [])

    def test_multicore_adopt_and_collect_in_recovery_only_mode(self):
        self.multicore_profile()
        task = self.task("recover", adopt_run_id="probe-r4")
        record = self.make_record("tcad", "probe-r4", self.workspace / task["project"], 3)
        record.update(state="EXECUTED", remote_exit_code=0)
        self.save(self.record_path("tcad", "probe-r4"), record)
        self.task("new-device")
        result = self.engine().tick(allow_submit=False)
        self.assertEqual([v[1] for v in self.calls], ["status", "collect"])
        self.assertEqual(result["active_count"], 0)
        self.assertTrue(result["runs"][0]["collected"])
        self.assertEqual(result["runs"][0]["requested_resources"]["cpu_set"], [6, 7])

    def test_multicore_verified_old_failure_is_readonly_repair_parent(self):
        task = self.task("aborted", value="physics unchanged")
        self.engine().tick()
        # Existing pre-MC2 intent files do not have the new resource metadata.
        state_path = self.base / "state/runtime.json"
        state = runtime.read_json(state_path)
        state["intents"]["aborted"].pop("requested_resources")
        self.save(state_path, state)
        old = self.finish("aborted", 143)
        self.collect_receipt("tcad", old["run_id"])
        original_bytes = self.record_path("tcad", old["run_id"]).read_bytes()
        old_inputs = (self.workspace / task["project"] / "project.json").read_bytes()
        before = len(self.calls)
        self.multicore_profile()
        self.task("repair-mc", value="physics unchanged", repair_of="aborted",
                  repair_reason="Use two numerical threads in a new input project")
        result = self.engine().tick()
        self.assertFalse(result["discovery_uncertain"])
        self.assertEqual(len(self.runs()), 2)
        self.assertTrue(all(v[2] != old["run_id"] for v in self.calls[before:]))
        intents = runtime.read_json(self.base / "state/runtime.json")["intents"]
        self.assertEqual(intents["aborted"], old)
        repair = intents["repair-mc"]
        self.assertEqual(repair["repair_of"], "aborted")
        self.assertNotEqual(repair["run_id"], old["run_id"])
        self.assertEqual(repair["requested_resources"]["requested_threads"], 2)
        self.assertEqual(self.record_path("tcad", old["run_id"]).read_bytes(), original_bytes)
        self.assertEqual((self.workspace / task["project"] / "project.json").read_bytes(), old_inputs)
        self.assertEqual(result["scientific_acceptance"], "not_assessed")

    def test_multicore_unverified_old_intents_block_all_submission_without_calls(self):
        # Slot 8 is deliberately outside r4: counting occupied slots alone is insufficient.
        for mode in ("running", "unreleased", "unverified", "string-verification",
                     "bad-archive", "changed-profile", "missing"):
            with self.subTest(mode=mode):
                # A fresh fixture avoids any historical state left by a prior subtest.
                h = RuntimeTests("runTest")
                h.setUp()
                try:
                    for i in range(9):
                        h.task("old-" + str(i))
                    h.engine().tick()
                    for i in range(8):
                        old = h.finish("old-" + str(i), 143)
                        h.collect_receipt("tcad", old["run_id"])
                    old = h.finish("old-8", 143)
                    path = h.record_path("tcad", old["run_id"])
                    if mode != "running":
                        h.collect_receipt("tcad", old["run_id"], released=mode != "unreleased")
                    if mode == "bad-archive":
                        (path.parent / "results.tar").write_bytes(b"changed")
                    if mode in ("unverified", "string-verification"):
                        record = runtime.read_json(path)
                        record["collection_verified"] = False if mode == "unverified" else "true"
                        h.save(path, record)
                    if mode == "changed-profile":
                        h.save(h.profile, dict(h.cfg, ssh_target="foreign-guest"))
                    if mode == "missing":
                        path.unlink()
                    before = len(h.calls)
                    h.multicore_profile()
                    h.task("new-device")
                    result = h.engine().tick()
                    self.assertTrue(result["discovery_uncertain"])
                    self.assertEqual(len(h.calls), before)
                    self.assertEqual(len(h.runs()), 9)
                finally:
                    h.doCleanups()

    def test_resource_profiles_validate_topology_and_legacy_contract(self):
        for capacity in (3, 7, 9):
            cfg = dict(self.cfg, parallel_capacity=capacity)
            resource = runtime.profile_resources(cfg)
            self.assertEqual(resource["cpu_sets"], [[i] for i in range(capacity)])
            self.assertEqual(resource["requested_threads"], 1)
            with self.assertRaises(ValueError):
                runtime.profile_resources(dict(cfg, requested_threads=1))
        legacy = dict(self.cfg)
        legacy.pop("parallel_capacity")
        self.assertEqual(runtime.profile_resources(legacy)["capacity"], 3)
        self.multicore_profile()
        for update in ({"cpu_sets": [[0, 1]] * 4}, {"cpu_sets": [[False, 1], [2, 3], [4, 5], [6, 7]]},
                       {"requested_threads": True}, {"requested_threads": 1}, {"parallel_capacity": True}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                runtime.profile_resources(dict(self.cfg, **update))
        self.policy["max_parallel_jobs"] = 5
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self.engine().tick()

    def test_multicore_valid_external_slot_counts_toward_four(self):
        self.multicore_profile()
        project = self.workspace / "external"
        project.mkdir()
        self.make_record("tcad", "external", project, 3)
        for i in range(4):
            self.task("device-" + str(i))
        result = self.engine().tick()
        self.assertFalse(result["discovery_uncertain"])
        self.assertEqual((len(self.runs()), result["active_count"]), (3, 4))
        self.assertEqual({v["slot"] for v in result["runs"]}, {0, 1, 2})
        self.assertEqual(result["external_runs"][0]["requested_resources"]["cpu_set"], [6, 7])

    def test_mixed_pool_matches_frozen_width_and_runs_single_core_when_dual_busy(self):
        self.cfg.update(parallel_capacity=8, cpu_sets=[[0], [1], [2], [3], [4], [5], [6, 7], [8, 9]],
                        requested_threads=[1, 1, 1, 1, 1, 1, 2, 2])
        self.save(self.profile, self.cfg)
        self.policy["max_parallel_jobs"] = 8
        for name in ("dual-a", "dual-b", "dual-wait"):
            task = self.task(name)
            path = self.workspace / task["project"] / "project.json"
            self.save(path, dict(runtime.read_json(path), native_threads=2, native_cores=2))
        self.task("single-a")
        result = self.engine().tick()
        self.assertEqual({run["id"]: run["slot"] for run in result["runs"]},
                         {"dual-a": 6, "dual-b": 7, "single-a": 0})
        waiting = next(row for row in result["pending_tasks"] if row["id"] == "dual-wait")
        self.assertEqual(waiting["eligible_slots"], [6, 7])

    def test_multicore_historical_transport_failure_defers_until_idle_original_profile(self):
        self.task("old-transport", backend="geant4")
        self.engine().tick()
        old = self.finish("old-transport", 1)
        self.collect_receipt("geant4", old["run_id"])
        before = len(self.calls)
        self.multicore_profile()
        result = self.engine().tick()
        self.assertEqual(result["repair_requests"], [])
        self.assertEqual(result["active_count"], 0)
        self.assertEqual(len(self.calls), before)
        self.assertTrue(any(v["reason"] == "geant4_requires_idle_single_core_profile"
                            for v in result["blocked_tasks"]))

    def test_resource_contract_changes_observation_fingerprint(self):
        self.queue_tasks()
        old = self.engine().tick(allow_submit=False)
        self.multicore_profile()
        new = self.engine().tick(allow_submit=False)
        self.assertNotEqual(old["fingerprint"], new["fingerprint"])
        self.assertEqual(self.calls, [])

    def test_multicore_tampered_owned_policy_blocks_other_slots(self):
        self.multicore_profile()
        self.task("original")
        self.engine().tick()
        intent = runtime.read_json(self.base / "state/runtime.json")["intents"]["original"]
        path = self.record_path("tcad", intent["run_id"])
        record = runtime.read_json(path)
        record["parallel_policy"]["cpu_set"] = [2, 3]
        self.save(path, record)
        self.task("other")
        before = len(self.calls)
        result = self.engine().tick()
        self.assertTrue(result["discovery_uncertain"])
        self.assertEqual(len(self.calls), before)
        self.assertEqual(len(self.runs()), 1)

    def test_legacy_three_and_seven_capacity_submission_unchanged(self):
        for capacity in (3, 7):
            with self.subTest(capacity=capacity):
                h = RuntimeTests("runTest")
                h.setUp()
                try:
                    h.cfg["parallel_capacity"] = capacity
                    h.policy["max_parallel_jobs"] = capacity
                    h.save(h.profile, h.cfg)
                    h.ready["connection"]["sha256"] = runtime.file_digest(h.profile)
                    for i in range(capacity + 1):
                        h.task("legacy-" + str(i))
                    result = h.engine().tick()
                    self.assertEqual((len(h.runs()), result["active_count"]), (capacity, capacity))
                    self.assertEqual(result["profile_resources"]["requested_threads"], 1)
                    self.assertTrue(all(v["requested_resources"]["cpu_set"] == [v["slot"]]
                                        for v in result["runs"]))
                finally:
                    h.doCleanups()

    def test_nine_slots_tenth_waits_then_refills(self):
        for index in range(10):
            self.task("t" + str(index))
        first = self.engine().tick()
        self.assertEqual((first["active_count"], first["pending_count"]), (9, 1))
        self.assertEqual({v["slot"] for v in first["runs"]}, set(range(9)))
        self.assertEqual(len(self.runs()), 9)
        self.finish("t0")
        second = self.engine().tick()
        self.assertEqual((second["active_count"], second["pending_count"]), (9, 0))
        self.assertEqual(len(self.runs()), 10)
        self.assertEqual(next(v for v in second["runs"] if v["id"] == "t9")["slot"], 0)

    def test_failed_task_requests_repair_without_blocking_independent_work(self):
        self.task("bad")
        self.engine().tick()
        self.finish("bad", 2)
        self.task("next")
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 2)
        self.assertEqual(result["repair_requests"][0]["id"], "bad")
        self.assertEqual(result["active_count"], 1)
        self.assertEqual(result["runs"][0]["status"], "failed")

    def test_repair_changed_inputs_and_success_unblocks_parent_dependency(self):
        self.task("parent", value="mesh=10")
        self.task("dependent", depends_on=["parent"])
        self.engine().tick()
        self.finish("parent", 3)
        self.task("fix", value="mesh=5", repair_of="parent", repair_reason="Refine mesh after divergence")
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 2)
        self.assertTrue(any(v["id"] == "fix" for v in result["runs"]))
        self.finish("fix", 0)
        self.engine().tick()
        self.assertEqual(len(self.runs()), 3)
        parent = runtime.read_json(self.base / "state/runtime.json")["intents"]["parent"]
        self.assertEqual(runtime.read_json(self.record_path("tcad", parent["run_id"]))["state"], "FAILED_COLLECTED")

    def test_same_scientific_inputs_with_renamed_project_are_rejected(self):
        self.task("parent", value="same")
        self.engine().tick()
        self.finish("parent", 1)
        self.task("renamed", value="same", repair_of="parent", repair_reason="Blind retry")
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertTrue(any("unchanged inputs" in v.get("detail", "") for v in result["blocked_tasks"]))

    def test_repair_requires_terminal_collection_and_new_project(self):
        parent = self.task("parent")
        self.engine().tick()
        self.task("fix", repair_of="parent", repair_reason="Change solver")
        first = self.engine().tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertTrue(any("terminal collection" in v.get("detail", "") for v in first["blocked_tasks"]))
        self.finish("parent", 1)
        self.tasks[-1]["project"] = parent["project"]
        self.queue_tasks()
        second = self.engine().tick()
        self.assertTrue(any("new project" in v.get("detail", "") for v in second["blocked_tasks"]))

    def test_repair_budget_is_per_lineage_and_does_not_pause_others(self):
        self.policy["repair_attempt_limit"] = 1
        self.task("first")
        self.engine().tick()
        self.finish("first", 1)
        self.task("second", repair_of="first", repair_reason="Revised numerical solver")
        self.engine().tick()
        self.finish("second", 2)
        self.task("third", repair_of="second", repair_reason="Another revision")
        self.task("independent")
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 3)
        self.assertTrue(any(v["id"] == "third" and v["reason"] == "repair_budget_exhausted"
                            for v in result["blocked_tasks"]))

    def test_unknown_launch_survives_restart_without_replay(self):
        self.task("disconnect")
        self.behavior["disconnect"] = "timeout_after_launch"
        first = self.engine().tick()
        original_id = first["runs"][0]["run_id"]
        recovered = self.engine().tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(recovered["runs"][0]["run_id"], original_id)
        self.assertIn(("tcad", "status", original_id), self.calls)
        self.finish("disconnect")
        self.assertTrue(self.engine().tick()["queue_complete"])
        self.assertEqual(len(self.runs()), 1)

    def test_manifest_missing_never_resubmits_and_retains_slot(self):
        self.task("missing")
        self.behavior["missing"] = "timeout_without_manifest"
        first = self.engine().tick()
        second = self.engine().tick()
        third = self.engine().tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(third["active_count"], 1)
        self.assertEqual(first["runs"][0]["run_id"], third["runs"][0]["run_id"])
        self.assertEqual(second["fingerprint"], third["fingerprint"])
        self.assertEqual(third["runs"][0]["reason"], "original_manifest_missing_launch_unknown")

    def test_crash_after_intent_persistence_before_invocation_is_not_replayed(self):
        self.task("interrupted")
        with patch.object(runtime.Runtime, "_invoke", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.engine().tick()
        self.assertEqual(len(self.runs()), 0)
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 0)
        self.assertEqual(result["active_count"], 1)
        self.assertEqual(result["runs"][0]["status"], "reconciliation_pending")

    def test_invalid_success_output_and_nonzero_are_not_resubmitted(self):
        self.policy.update(failure_backoff_seconds=300, max_failure_backoff_seconds=300)
        for task_id, mode in (("unknown", "invalid_json"), ("refused", "nonzero")):
            self.task(task_id)
            self.behavior[task_id] = mode
        self.engine().tick()
        self.engine().tick()
        self.assertEqual(len(self.runs()), 2)
        self.assertEqual(len(self.calls), 2)
        intents = runtime.read_json(self.base / "state/runtime.json")["intents"]
        for intent in intents.values():
            self.assertEqual(intent["probe_failures"], 1)
            self.assertGreater(intent["next_probe_at"], runtime.time.time())

    def test_confirmed_transport_failure_collects_without_backoff_or_relaunch(self):
        self.policy.update(failure_backoff_seconds=300, max_failure_backoff_seconds=300)
        self.task("fast-failure", backend="geant4")
        self.behavior["fast-failure"] = "finished_nonzero"
        first = self.engine().tick()
        intent = runtime.read_json(self.base / "state/runtime.json")["intents"]["fast-failure"]
        original_id = intent["run_id"]
        self.assertNotIn("reconciliation_error", intent)
        self.assertNotIn("next_probe_at", intent)
        self.assertEqual(first["runs"][0]["remote_exit_code"], 1)
        self.assertFalse(first["runs"][0]["collected"])
        second = self.engine().tick()
        self.assertEqual(second["active_count"], 0)
        self.assertEqual(second["runs"][0]["status"], "failed")
        self.assertEqual(second["runs"][0]["original_state"], "FAILED_COLLECTED")
        self.assertEqual(second["repair_requests"][0]["run_id"], original_id)
        self.assertFalse(second["queue_complete"])
        record = runtime.read_json(self.record_path("geant4", original_id))
        self.assertEqual(record["remote_exit_code"], 1)
        self.assertTrue(record["parallel_slot_released"])
        self.assertIn("geant4.sh", record["last_observation"]["log_tail"])
        self.engine().tick()
        self.assertEqual(self.calls, [("geant4", command, original_id)
                                     for command in ("run", "status", "collect")])

    def test_unproven_transport_failure_keeps_original_id_and_backoff(self):
        self.policy.update(failure_backoff_seconds=300, max_failure_backoff_seconds=300)
        cases = ("missing-manifest", "wrong-id", "changed-identity", "unknown-launch",
                 "ledger-exit-mismatch", "missing-identity", "invalid-json")
        for case in cases:
            self.task(case, backend="geant4")
            self.behavior[case] = "finished_nonzero"

        def unproven_result(argv, **kwargs):
            result = self.fake_runner(argv, **kwargs)
            payload = json.loads(result.stdout)
            path = self.record_path("geant4", payload["label"])
            case = Path(argv[5]).name
            if case == "missing-manifest":
                path.unlink()
            elif case == "wrong-id":
                payload["label"] = "a-different-original-run"
            elif case == "changed-identity":
                payload["identity"]["start_ticks"] += 1
            elif case == "unknown-launch":
                payload.update(status="START_UNCONFIRMED", alive=None)
            elif case == "ledger-exit-mismatch":
                record = runtime.read_json(path)
                record["remote_exit_code"] = 2
                self.save(path, record)
            elif case == "missing-identity":
                payload.pop("identity")
            result.stdout = "incomplete JSON {" if case == "invalid-json" else json.dumps(payload)
            return result

        with patch.object(runtime.subprocess, "run", side_effect=unproven_result):
            first = self.engine().tick()
            second = self.engine().tick()
        intents = runtime.read_json(self.base / "state/runtime.json")["intents"]
        self.assertEqual(len(intents), len(cases))
        for case, intent in intents.items():
            with self.subTest(case=case):
                self.assertEqual(intent["reconciliation_error"]["kind"], "runner_error")
                self.assertEqual(intent["probe_failures"], 1)
                self.assertGreater(intent["next_probe_at"], runtime.time.time())
        self.assertEqual(len(self.calls), len(cases))
        self.assertEqual(len(self.runs()), len(cases))
        self.assertEqual({item["run_id"] for item in first["runs"]},
                         {item["run_id"] for item in second["runs"]})
        self.assertFalse(any(item["collected"] for item in second["runs"]))

    def test_shared_transport_and_tcad_slots_and_different_collection_keys(self):
        self.task("tcad")
        self.task("transport", backend="geant4")
        first = self.engine().tick()
        self.assertEqual({v["slot"] for v in first["runs"]}, {0, 1})
        self.finish("tcad", 0)
        self.finish("transport", 0)
        result = self.engine().tick()
        self.assertTrue(result["queue_complete"])
        self.assertEqual(result["active_count"], 0)
        self.assertEqual(result["scientific_acceptance"], "not_assessed")
        self.assertEqual({v["original_state"] for v in result["runs"]},
                         {"COLLECTED", "COLLECTED_PENDING_AUDIT"})

    def test_disabled_submission_and_ready_authorization(self):
        self.task("pending")
        self.assertEqual(self.engine().tick(allow_submit=False)["pending_count"], 1)
        self.ready["new_jobs_authorized"] = False
        self.assertEqual(self.engine().tick()["pending_count"], 1)
        self.assertEqual(self.calls, [])

    def test_recovery_only_still_collects_original_work(self):
        self.task("original")
        self.engine().tick()
        self.finish("original")
        self.task("new")
        self.ready["new_jobs_authorized"] = False
        result = self.engine().tick(allow_submit=False)
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(result["active_count"], 0)
        self.assertEqual(result["pending_count"], 1)

    def test_external_slots_not_overwritten_or_collected(self):
        external = self.workspace / "external"
        external.mkdir()
        self.make_record("geant4", "external", external, 3)
        for index in range(9):
            self.task("new-" + str(index))
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 8)
        self.assertEqual(result["active_count"], 9)
        self.assertNotIn(3, {v["slot"] for v in result["runs"]})
        self.assertFalse(any(v[2] == "external" for v in self.calls))

    def test_old_capacity_cross_profile_is_not_rebound(self):
        external = self.workspace / "external"
        external.mkdir()
        other_root = self.workspace / "local_runtime/cloud-benchmark/old-profile"
        self.make_record("tcad", "old", external, 1, root=other_root, capacity=3)
        self.task("new")
        result = self.engine().tick()
        self.assertTrue(result["discovery_uncertain"])
        self.assertEqual(self.calls, [])

    def test_adopts_original_run_and_collects_without_launch(self):
        task = self.task("recovery", adopt_run_id="old-run")
        project = self.workspace / task["project"]
        self.make_record("tcad", "old-run", project, 4)
        path = self.record_path("tcad", "old-run")
        data = runtime.read_json(path)
        data.update(state="EXECUTED", remote_exit_code=0)
        self.save(path, data)
        result = self.engine().tick(allow_submit=False)
        self.assertEqual(len(self.runs()), 0)
        self.assertTrue(result["queue_complete"])

    def test_collected_receipt_releases_slot_without_repeating_status(self):
        self.task("original")
        self.engine().tick()
        intent = self.finish("original")
        self.collect_receipt("tcad", intent["run_id"], released=False)
        before = len(self.calls)
        result = self.engine().tick()
        self.assertEqual([item[1] for item in self.calls[before:]], ["collect"])
        self.assertEqual(result["active_count"], 0)
        before = len(self.calls)
        self.engine().tick()
        self.assertEqual(len(self.calls), before)

    def test_archive_tampering_is_not_success(self):
        self.task("original")
        self.engine().tick()
        intent = self.finish("original")
        self.engine().tick()
        path = self.record_path("tcad", intent["run_id"])
        (path.parent / "results.tar").write_bytes(b"changed")
        self.collect_failures.add(intent["run_id"])
        result = self.engine().tick()
        self.assertFalse(result["queue_complete"])
        self.assertFalse(result["runs"][0]["success"])

    def test_retained_archive_remains_collected_without_recollection(self):
        self.task("retained")
        engine = self.engine()
        engine.tick()
        intent = self.finish("retained")
        engine.tick()
        path = self.record_path("tcad", intent["run_id"])
        raw = path.parent / "results.tar"
        with tarfile.open(raw, "w") as archive:
            payload = b"t,V\n0,1\n1,0\n"
            member = tarfile.TarInfo("numerics.plt")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
        manifest = runtime.read_json(path)
        manifest.update(results_sha256=runtime.file_digest(raw), collected_bytes=raw.stat().st_size)
        self.save(path, manifest)
        engine._retention_module().compact(path.parent)
        self.assertFalse(raw.exists())
        before = len(self.calls)
        self.assertTrue(self.engine().tick()["queue_complete"])
        self.assertEqual(len(self.calls), before)
        # A changed compact result must never be accepted from a stale digest.
        capsule = path.parent / "results.essential.tar.gz"
        capsule.write_bytes(b"changed")
        self.collect_failures.add(intent["run_id"])
        result = self.engine().tick()
        self.assertFalse(result["queue_complete"])
        self.assertFalse(result["runs"][0]["success"])

    def test_collection_disconnect_retries_original_collection_only(self):
        self.task("original")
        self.engine().tick()
        intent = self.finish("original")
        self.collect_failures.add(intent["run_id"])
        self.assertEqual(self.engine().tick()["active_count"], 1)
        self.collect_failures.clear()
        self.assertTrue(self.engine().tick()["queue_complete"])
        self.assertEqual(len(self.runs()), 1)

    def test_artifact_readiness_does_not_require_whole_work_package(self):
        self.task("waiting", requires=["artifacts/model.tdr"])
        first = self.engine().tick()
        self.assertEqual(first["pending_count"], 1)
        artifact = self.workspace / "artifacts/model.tdr"
        artifact.parent.mkdir()
        artifact.write_bytes(b"model")
        second = self.engine().tick()
        self.assertEqual(second["active_count"], 1)

    def test_stable_fingerprint_ignores_poll_timestamps(self):
        self.task("steady")
        self.engine().tick()
        first = self.engine().tick()
        second = self.engine().tick()
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(second["events"], [])

    def test_timeout_does_not_create_nine_more_launch_intents(self):
        self.policy.update(failure_backoff_seconds=300, max_failure_backoff_seconds=3600)
        for index in range(9):
            self.task("job-" + str(index))
        self.behavior["job-0"] = "timeout_after_launch"
        result = self.engine().tick()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual((result["active_count"], result["pending_count"]), (1, 8))
        self.engine().tick()
        self.assertEqual(len(self.calls), 1)

    def test_empty_queue_requests_planning_not_research_completion(self):
        self.queue_tasks()
        result = self.engine().tick()
        self.assertTrue(result["needs_planning"])
        self.assertFalse(result["queue_complete"])
        self.assertEqual(self.calls, [])

    def test_path_escape_invalid_task_does_not_block_independent_task(self):
        self.task("valid")
        self.tasks.append({"id": "escape", "backend": "tcad", "project": "../outside"})
        self.queue_tasks()
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertTrue(any(v["id"] == "escape" for v in result["blocked_tasks"]))

    def test_profile_semantic_validation_without_sha_blocking(self):
        self.task("valid")
        # Stale SHA256 or harmless whitespace edit does NOT block submission.
        self.ready["connection"]["sha256"] = "0" * 64
        self.save(self.profile, dict(self.cfg, note="reformatted"))
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(result["active_count"], 1)

        # Invalid backend or broken topology IS still refused semantically.
        self.save(self.profile, dict(self.cfg, backend="vmware"))
        with self.assertRaisesRegex(ValueError, "ssh-runtime"):
            self.engine().tick()

    def test_dynamic_v2_topology_and_preflight_exit_75_rollback(self):
        # Data-driven 3x3 layout works without any hardcoded schema registration.
        self.cfg = dict(self.cfg, parallel_capacity=3,
                        cpu_sets=[[0, 1, 2], [3, 4, 5], [6, 7, 8]], requested_threads=3)
        self.profile = self.base / "connection-three-three.json"
        self.save(self.profile, self.cfg)
        self.policy["max_parallel_jobs"] = 3
        self.ready["connection"] = str(self.profile)
        self.task("job-v2")

        # Simulate runner returning PREFLIGHT_EXIT_CODE (75) with no manifest written:
        # Runtime rolls back the ghost intent cleanly so the task can be retried.
        def reject_preflight(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 75, "", "PREFLIGHT_REJECTED: slot busy\n")
        with patch.object(runtime.subprocess, "run", side_effect=reject_preflight):
            first = self.engine().tick()
        self.assertEqual(first["active_count"], 0)
        self.assertTrue(any(e.get("type") == "preflight_rejected" for e in first["events"]))
        self.assertTrue(any(p["id"] == "job-v2" and p["reason"] == "preflight_rejected"
                            for p in first["pending_tasks"]))
        state = runtime.read_json(self.base / "state/runtime.json")
        self.assertNotIn("job-v2", state["intents"])

        # Next tick after pool clears submits cleanly under tcad-shared-gate-slots-v2!
        second = self.engine().tick()
        self.assertEqual(second["active_count"], 1)
        state = runtime.read_json(self.base / "state/runtime.json")
        self.assertEqual(state["intents"]["job-v2"]["requested_resources"], {
            "schema": "tcad-shared-gate-slots-v2", "capacity": 3,
            "cpu_set": [0, 1, 2], "requested_threads": 3,
        })

    def test_dynamic_disarm_after_first_submission_stops_remaining_batch(self):
        for index in range(9):
            self.task("job-" + str(index))
        engine = self.engine()
        engine.can_submit = lambda: not self.runs()
        result = engine.tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(result["pending_count"], 8)
        self.assertEqual(len(runtime.read_json(self.base / "state/runtime.json")["intents"]), 1)

    def test_missing_git_metadata_does_not_leave_uncertain_intent(self):
        self.task("pending")
        (self.workspace / ".git").rmdir()
        result = self.engine().tick()
        self.assertEqual(self.calls, [])
        self.assertFalse((self.base / "state/runtime.json").exists())
        self.assertTrue(any("Git metadata" in item.get("detail", "") for item in result["blocked_tasks"]))

    def test_lower_job_limit_counts_external_slot_outside_low_slot_range(self):
        self.policy["max_parallel_jobs"] = 3
        external = self.workspace / "external"
        external.mkdir()
        self.make_record("tcad", "external", external, 8)
        for index in range(4):
            self.task("task-" + str(index))
        result = self.engine().tick()
        self.assertFalse(result["discovery_uncertain"])
        self.assertEqual(len(self.runs()), 2)
        self.assertEqual(result["active_count"], 3)

    def test_dependency_cycle_and_unknown_dependency_are_local(self):
        self.task("a", depends_on=["b"])
        self.task("b", depends_on=["a"])
        self.task("c", depends_on=["missing"])
        self.task("independent")
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual({item["reason"] for item in result["blocked_tasks"]},
                         {"dependency_cycle", "unknown_dependency"})

    def test_geometry_retains_original_immutable_id_without_new_gate(self):
        task = self.task("geometry")
        path = self.workspace / task["project"] / "project.json"
        spec = runtime.read_json(path)
        spec["s2_geometry"] = {"run_id": "original-fixed-geometry-id"}
        self.save(path, spec)
        result = self.engine().tick()
        self.assertEqual(result["runs"][0]["run_id"], "original-fixed-geometry-id")

    def test_geometry_existing_id_requires_explicit_adoption(self):
        task = self.task("geometry")
        path = self.workspace / task["project"] / "project.json"
        spec = runtime.read_json(path)
        spec["s2_geometry"] = {"run_id": "existing"}
        self.save(path, spec)
        self.make_record("tcad", "existing", self.workspace / task["project"], 0)
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 0)
        self.assertTrue(any("adopt_run_id" in item.get("detail", "") for item in result["blocked_tasks"]))

    def test_runner_generated_binding_files_are_not_a_second_admission_gate(self):
        task = self.task("geometry")
        self.engine().tick()
        intent = runtime.read_json(self.base / "state/runtime.json")["intents"]["geometry"]
        path = self.record_path("tcad", intent["run_id"])
        record = runtime.read_json(path)
        record["input_sha256"]["runner-generated-binding.json"] = "0" * 64
        self.save(path, record)
        result = self.engine().tick()
        self.assertEqual(result["runs"][0]["status"], "running")

    def test_stdout_id_mismatch_is_not_allowed_to_collect(self):
        self.task("original")
        self.engine().tick()
        with patch.object(runtime.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, json.dumps({"status": "FINISHED", "alive": False, "run_id": "different"}), "")):
            result = self.engine().tick()
        self.assertEqual(result["runs"][0]["reason"], "original_record_unusable")

    def test_full_pool_never_hashes_waiting_tenth_project(self):
        for index in range(10):
            self.task("job-" + str(index))
        engine = self.engine()
        tenth = (self.workspace / self.tasks[-1]["project"]).resolve()
        with patch.object(runtime, "file_digest", wraps=runtime.file_digest) as hashing:
            engine.tick()
            first_calls = len(hashing.call_args_list)
            second = engine.tick()
            third = engine.tick()
            self.assertGreater(len(hashing.call_args_list), first_calls)  # Pinned profile still checked.
            self.assertFalse(any(Path(item.args[0]).resolve().is_relative_to(tenth)
                                 for item in hashing.call_args_list))
            self.assertEqual(second["pending_count"], 1)
            self.assertEqual(second["fingerprint"], third["fingerprint"])

    def test_input_cache_rehashes_only_changed_file(self):
        task = self.task("cached")
        engine = self.engine()
        engine._profile()
        with patch.object(runtime, "file_digest", wraps=runtime.file_digest) as hashing:
            first = engine._inputs(task)
            self.assertEqual(hashing.call_count, 2)
            self.assertEqual(engine._inputs(task), first)
            self.assertEqual(hashing.call_count, 2)
            (self.workspace / task["project"] / "deck.cmd").write_text("different and longer", encoding="utf-8")
            revised = engine._inputs(task)
            self.assertNotEqual(revised, first)
            self.assertEqual(hashing.call_count, 3)
            self.assertEqual(engine._inputs(task), revised)
            self.assertEqual(hashing.call_count, 3)

    def test_inputs_changed_before_submit_leave_no_intent(self):
        task = self.task("mutable")
        engine = self.engine()
        engine._profile()
        inputs, snapshot = engine._inputs(task)
        (self.workspace / task["project"] / "deck.cmd").write_text("new input content", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inputs changed before submission"):
            engine._submit(task, 0, inputs, snapshot, [])
        self.assertEqual(self.calls, [])
        self.assertFalse((self.base / "state/runtime.json").exists())

    def test_runner_environment_strips_proxy_and_llm_secrets_without_mutating_parent(self):
        self.task("isolated")
        excluded = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
                    "OPENAI_API_KEY", "OPENAI_BASE_URL", "TCAD_MAGPIE_API_KEY")
        sentinels = {key: "fixture-sensitive-value" for key in excluded}
        sentinels.update(PATH="fixture-inherited-path", GIT_TERMINAL_PROMPT="1", KEEP_ME="kept")
        with patch.dict(runtime.os.environ, sentinels, clear=True):
            before = dict(runtime.os.environ)
            self.engine().tick()
            environment = self.mock_runner.call_args.kwargs["env"]
            self.assertEqual(dict(runtime.os.environ), before)
            self.assertFalse(any(key.upper() in {item.upper() for item in excluded} for key in environment))
            self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")
            self.assertEqual(environment["KEEP_ME"], "kept")
            self.assertEqual(environment["PATH"],
                             str(Path(sys.executable).resolve().parent) + runtime.os.pathsep + "fixture-inherited-path")

    def test_successful_parent_cannot_be_recast_as_failed_repair(self):
        self.task("successful")
        self.engine().tick()
        self.finish("successful", 0)
        self.task("revision", repair_of="successful", repair_reason="Scientific improvement")
        self.task("ordinary-followup")
        result = self.engine().tick()
        self.assertEqual(len(self.runs()), 2)
        self.assertTrue(any("new ordinary research task" in item.get("detail", "")
                            for item in result["blocked_tasks"]))

    def test_verified_intent_sidecar_is_failed_terminal_and_never_success_or_collection(self):
        import types
        from unittest.mock import Mock
        engine = self.engine()
        engine._profile()
        intent = dict(backend="tcad", run_id="auto-sidecar", slot=0,
                      connection=engine.connection, repair_of=None)
        engine.intents["original"] = intent
        self.save(engine.state_dir / "intent-reconciliations/auto-sidecar.json", {})
        module = types.SimpleNamespace(verified_receipt=Mock(return_value=True))
        spec = types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda value: None))
        with patch.object(runtime.importlib.util, "spec_from_file_location", return_value=spec), \
                patch.object(runtime.importlib.util, "module_from_spec", return_value=module):
            view = engine._observe("original", intent, [])
        self.assertEqual(view["status"], "failed_unlaunched")
        self.assertTrue(view["terminal_reconciled"])
        self.assertFalse(view["occupied"])
        self.assertFalse(view["success"])
        self.assertFalse(view["collected"])
        self.assertIsNone(view["remote_exit_code"])
        self.assertFalse(engine._successful("original", {"original": view}))
        self.assertEqual(self.calls, [])

    def test_invalid_intent_sidecar_preserves_unknown_occupancy(self):
        import types
        from unittest.mock import Mock
        engine = self.engine()
        engine._profile()
        intent = dict(backend="tcad", run_id="auto-sidecar", slot=0, connection=engine.connection)
        self.save(engine.state_dir / "intent-reconciliations/auto-sidecar.json", {})
        module = types.SimpleNamespace(verified_receipt=Mock(side_effect=ValueError("changed evidence")))
        spec = types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda value: None))
        with patch.object(runtime.importlib.util, "spec_from_file_location", return_value=spec), \
                patch.object(runtime.importlib.util, "module_from_spec", return_value=module):
            view = engine._observe("original", intent, [])
        self.assertTrue(view["occupied"])
        self.assertFalse(view["success"])
        self.assertEqual(view["reason"], "original_record_unusable")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
