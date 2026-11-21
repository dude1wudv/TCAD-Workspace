"""Unit, fault-injection, and contract tests for Scheduler v3."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from scheduler_admission import ResourceAdmissionController
from scheduler_collector import AsyncCollectorPool, backoff_seconds_for, classify_collection_error
from scheduler_engine import SchedulerEngine
from scheduler_models import ErrorClass, PoolState, RemoteTelemetry, RunProbeSnapshot, TaskState
from scheduler_planner import AsyncPlannerSidecar
from scheduler_pool import PoolStateMachine, task_priority_key


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPoolStateMachine(unittest.TestCase):
    def test_idle_active_draining_switch_and_no_deadlock(self):
        sm = PoolStateMachine(config={"strategy": "priority_with_dwell", "min_profile_dwell_seconds": 600})
        t0 = 1000.0
        # 1. Idle -> ACTIVE on highest priority profile (geant4 prio 10 < tcad prio 100)
        tr = sm.reconcile(
            live_profiles=set(),
            ready_tasks_by_profile={
                "tcad": [{"id": "t1", "priority": 100}],
                "geant4": [{"id": "g1", "priority": 10}],
            },
            has_transport_profile=True,
            now=t0,
        )
        self.assertIsNotNone(tr)
        self.assertEqual(sm.state, PoolState.ACTIVE)
        self.assertEqual(sm.active_profile, "geant4")
        self.assertTrue(sm.can_admit("geant4")[0])
        self.assertFalse(sm.can_admit("tcad")[0])

        # 2. While geant4 is running AND still has ready work, tcad with higher prio must wait for min_dwell
        sm.reconcile(
            live_profiles={"geant4"},
            ready_tasks_by_profile={
                "tcad": [{"id": "t1", "priority": 5}],
                "geant4": [{"id": "g2", "priority": 10}],
            },
            has_transport_profile=True,
            now=t0 + 100.0,
        )
        self.assertEqual(sm.state, PoolState.ACTIVE)

        # 3. After min_dwell, higher-priority other profile triggers explicit DRAINING
        tr2 = sm.reconcile(
            live_profiles={"geant4"},
            ready_tasks_by_profile={
                "tcad": [{"id": "t1", "priority": 5}],
                "geant4": [{"id": "g2", "priority": 10}],
            },
            has_transport_profile=True,
            now=t0 + 700.0,
        )
        self.assertIsNotNone(tr2)
        self.assertEqual(sm.state, PoolState.DRAINING)
        self.assertEqual(sm.active_profile, "geant4")
        self.assertEqual(sm.target_profile, "tcad")
        # Both profiles blocked from NEW submissions during drain
        self.assertFalse(sm.can_admit("geant4")[0])
        self.assertFalse(sm.can_admit("tcad")[0])

        # 4. Once geant4 slots are released (live_profiles empty), immediately switches to tcad
        tr3 = sm.reconcile(
            live_profiles=set(),
            ready_tasks_by_profile={"tcad": [{"id": "t1", "priority": 5}]},
            has_transport_profile=True,
            now=t0 + 710.0,
        )
        self.assertIsNotNone(tr3)
        self.assertEqual(sm.state, PoolState.ACTIVE)
        self.assertEqual(sm.active_profile, "tcad")
        self.assertTrue(sm.can_admit("tcad")[0])
        self.assertGreaterEqual(sm.switches_total, 1)

    def test_drain_aborts_automatically_if_target_queue_clears(self):
        sm = PoolStateMachine(config={"strategy": "drain_on_empty"})
        sm.reconcile(live_profiles={"tcad"}, ready_tasks_by_profile={"geant4": [{"id": "g1"}]}, has_transport_profile=True, now=10.0)
        self.assertEqual(sm.state, PoolState.DRAINING)
        # Target geant4 disappears while tcad gets new ready work -> return to ACTIVE
        sm.reconcile(live_profiles={"tcad"}, ready_tasks_by_profile={"tcad": [{"id": "t2"}]}, has_transport_profile=True, now=20.0)
        self.assertEqual(sm.state, PoolState.ACTIVE)
        self.assertEqual(sm.active_profile, "tcad")

    def test_manual_drain_and_cancel_drain(self):
        sm = PoolStateMachine()
        sm.reconcile(live_profiles={"tcad"}, ready_tasks_by_profile={"tcad": [{"id": "t1"}]}, has_transport_profile=True, now=10.0)
        sm.request_manual_drain("geant4", "operator_switch", now=15.0)
        self.assertEqual(sm.state, PoolState.DRAINING)
        self.assertEqual(sm.target_profile, "geant4")
        sm.cancel_manual_drain(now=20.0)
        self.assertEqual(sm.state, PoolState.ACTIVE)
        self.assertIsNone(sm.target_profile)

    def test_priority_ordering_prefers_priority_then_repair_then_fifo(self):
        items = [
            {"id": "b", "priority": 100, "repair_of": None},
            {"id": "a", "priority": 100, "repair_of": "old-1"},
            {"id": "c", "priority": 10, "repair_of": None},
        ]
        ordered = [t["id"] for t in sorted(items, key=lambda x: task_priority_key(x, items.index(x)))]
        self.assertEqual(ordered, ["c", "a", "b"])


class TestResourceAdmission(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.policy = {
            "resources": {
                "enabled": True,
                "min_available_memory_gib": 3.5,
                "min_host_disk_free_gib": 20.0,
                "min_remote_disk_free_gib": 10.0,
                "require_tcad_license_alive": True,
            }
        }
        self.adm = ResourceAdmissionController(self.policy, Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_memory_admission_reserves_unramped_launches(self):
        # Raw MemAvailable is 8.0 GiB, but 2 recently launched 1-core TCAD jobs (est 1.5 GiB each)
        # currently measure 0.2 GiB RSS -> 2.6 GiB must be conservatively reserved!
        # Effective available = 8.0 - 2.6 = 5.4 GiB; launching a 4-core (est 4.0 GiB) leaves 1.4 < 3.5 -> blocked!
        telemetry = RemoteTelemetry(
            available=True,
            mem_available_gib=8.0,
            host_disk_free_gib=50.0,
            remote_disk_free_gib=40.0,
            license_daemons_alive=True,
            runs={
                "r1": RunProbeSnapshot(run_id="r1", backend="tcad", alive=True, rss_kib=int(0.2 * 1024 * 1024)),
                "r2": RunProbeSnapshot(run_id="r2", backend="tcad", alive=True, rss_kib=int(0.2 * 1024 * 1024)),
            },
        )
        running_intents = [
            {"run_id": "r1", "backend": "tcad", "requested_resources": {"requested_threads": 1}},
            {"run_id": "r2", "backend": "tcad", "requested_resources": {"requested_threads": 1}},
        ]
        reserve = self.adm.compute_pending_launch_reserve_gib(running_intents, telemetry)
        self.assertAlmostEqual(reserve, 2.6, places=1)
        verdict_4c = self.adm.check(
            task={"backend": "tcad"}, requested_threads=4, telemetry=telemetry, pending_launch_reserve_gib=reserve
        )
        self.assertFalse(verdict_4c.allowed)
        self.assertEqual(verdict_4c.blocking_dimension, "memory")

        # Launching a 1-core (est 1.5 GiB) leaves 5.4 - 1.5 = 3.9 >= 3.5 -> allowed!
        verdict_1c = self.adm.check(
            task={"backend": "tcad"}, requested_threads=1, telemetry=telemetry, pending_launch_reserve_gib=reserve
        )
        self.assertTrue(verdict_1c.allowed)

    def test_host_and_remote_disk_floors(self):
        t_host_low = RemoteTelemetry(available=True, mem_available_gib=20.0, host_disk_free_gib=12.0, remote_disk_free_gib=30.0, license_daemons_alive=True)
        v1 = self.adm.check(task={"backend": "tcad"}, requested_threads=1, telemetry=t_host_low)
        self.assertFalse(v1.allowed)
        self.assertEqual(v1.blocking_dimension, "disk_host")

        t_rem_low = RemoteTelemetry(available=True, mem_available_gib=20.0, host_disk_free_gib=50.0, remote_disk_free_gib=5.0, license_daemons_alive=True)
        v2 = self.adm.check(task={"backend": "geant4"}, requested_threads=1, telemetry=t_rem_low)
        self.assertFalse(v2.allowed)
        self.assertEqual(v2.blocking_dimension, "disk_remote")

    def test_license_gate_blocks_tcad_but_allows_geant4(self):
        t_no_lic = RemoteTelemetry(
            available=True, mem_available_gib=20.0, host_disk_free_gib=50.0, remote_disk_free_gib=30.0,
            license_daemons_alive=False, license_detail="lmgrd=down,snpslmd=down",
        )
        v_tcad = self.adm.check(task={"backend": "tcad"}, requested_threads=1, telemetry=t_no_lic)
        self.assertFalse(v_tcad.allowed)
        self.assertEqual(v_tcad.blocking_dimension, "license")

        v_g4 = self.adm.check(task={"backend": "geant4"}, requested_threads=1, telemetry=t_no_lic)
        self.assertTrue(v_g4.allowed)


class TestAsyncCollectorPool(unittest.TestCase):
    def test_error_classification_and_backoff(self):
        c1 = classify_collection_error({"kind": "runner_error", "returncode": 1, "detail": "ValueError: Success marker conflicts with raw native exits"})
        self.assertEqual(c1, ErrorClass.PERMANENT_CONTRACT_ERROR)
        self.assertIsNone(backoff_seconds_for(c1, 1))

        c2 = classify_collection_error({"kind": "runner_error", "returncode": 75, "detail": "exit status 75"})
        self.assertEqual(c2, ErrorClass.TRANSIENT_LOCK_BUSY)
        self.assertEqual(backoff_seconds_for(c2, 1), 2.0)

        c3 = classify_collection_error({"kind": "endpoint_unavailable", "returncode": 255, "detail": "Connection timed out"})
        self.assertEqual(c3, ErrorClass.TRANSIENT_NETWORK)
        self.assertEqual(backoff_seconds_for(c3, 1), 5.0)
        self.assertEqual(backoff_seconds_for(c3, 2), 15.0)

        c4 = classify_collection_error({"kind": "runner_error", "returncode": 1, "detail": "LOST_WITHOUT_EXIT"}, boot_changed=True)
        self.assertEqual(c4, ErrorClass.INTERRUPTED_REBOOT)

    def test_async_collection_wakes_engine_immediately(self):
        wake = threading.Event()
        started = threading.Event()

        def fake_invoke(intent, cmd, interrupted):
            started.set()
            time.sleep(0.05)
            return {"ok": True, "payload": {"status": "COLLECTED"}}

        pool = AsyncCollectorPool(fake_invoke, max_workers=2, wake_event=wake)
        try:
            self.assertTrue(pool.submit("task-1", {"run_id": "run-1", "backend": "tcad"}))
            self.assertTrue(started.wait(timeout=2.0))
            self.assertTrue(wake.wait(timeout=2.0))
            done = pool.drain_completed()
            self.assertEqual(len(done), 1)
            self.assertEqual(done[0].task_id, "task-1")
            self.assertTrue(done[0].outcome["ok"])
        finally:
            pool.shutdown(wait=True)


class TestCancelAndSignalTrap(unittest.TestCase):
    def test_signal_safe_run_sh_trap_writes_143_not_zero_on_sigterm(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            script = work / "run.sh"
            script.write_text(
                "#!/bin/bash\n"
                "set -euo pipefail\n"
                f"cd {work}\n"
                "_tcad_signal_rc=0\n"
                '_tcad_on_signal() { _tcad_signal_rc="$2"; printf "%s\\n" "$1" > termination-signal.txt; trap "" TERM INT HUP; kill -TERM -- -$$ 2>/dev/null || true; exit "$2"; }\n'
                "trap '_tcad_on_signal TERM 143' TERM\n"
                "trap '_tcad_on_signal INT 130' INT\n"
                "trap '_tcad_on_signal HUP 129' HUP\n"
                'trap \'rc=$?; if [ "$_tcad_signal_rc" -ne 0 ]; then rc="$_tcad_signal_rc"; fi; printf "%s\\n" "$rc" > exit-code.txt; date -u +%Y-%m-%dT%H:%M:%SZ > finished-utc.txt\' EXIT\n'
                "sleep 30 &\n"
                "wait $!\n",
                encoding="utf-8",
            )
            proc = subprocess.Popen(["bash", str(script)], start_new_session=True)
            time.sleep(0.25)
            os.killpg(proc.pid, signal.SIGTERM)
            rc = proc.wait(timeout=5)
            self.assertEqual(rc, 143)
            self.assertEqual((work / "exit-code.txt").read_text().strip(), "143")
            self.assertEqual((work / "termination-signal.txt").read_text().strip(), "TERM")
            self.assertTrue((work / "finished-utc.txt").is_file())

    def test_tcad_collect_accepts_terminated_archive_even_if_legacy_exit_was_zero(self):
        tcad = _load_module("_test_tcad_cancel", REPO_ROOT / "tcad-research-training/scripts/tcad.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_id = "run-term-001"
            folder = root / "runs" / run_id
            folder.mkdir(parents=True)
            run_sh = b"#!/bin/bash\necho test\n"
            run_sha = hashlib.sha256(run_sh).hexdigest()

            # Build a fake tar where legacy trap wrote exit-code.txt = 0, step exited 143,
            # expected output final_access_des.tdr is missing, and termination-request.json is present.
            members_data = {
                "run.sh": run_sh,
                "exit-code.txt": b"0\n",
                "metadata-sdevice-version-exit-code.txt": b"0\n",
                "step-001-sdevice-exit-code.txt": b"143\n",
                "termination-request.json": json.dumps({
                    "schema": "tcad-termination-request-v1",
                    "run_id": run_id,
                    "requested_by": "operator",
                    "reason": "stalled_manual_stop",
                    "requested_utc": "2026-11-20T00:00:00+00:00",
                }).encode("utf-8"),
            }
            index = {
                k: {"size": len(v), "sha256": hashlib.sha256(v).hexdigest()}
                for k, v in members_data.items()
            }
            tar_bytes_io = io.BytesIO()
            with tarfile.open(fileobj=tar_bytes_io, mode="w") as tf:
                for name, raw in members_data.items():
                    ti = tarfile.TarInfo(name)
                    ti.size = len(raw)
                    tf.addfile(ti, io.BytesIO(raw))
                idx_raw = json.dumps(index, sort_keys=True).encode("utf-8")
                ti = tarfile.TarInfo("_collection-members.json")
                ti.size = len(idx_raw)
                tf.addfile(ti, io.BytesIO(idx_raw))
            tar_bytes = tar_bytes_io.getvalue()
            tar_sha = hashlib.sha256(tar_bytes).hexdigest()

            manifest = {
                "schema": "tcad-native-run-r2",
                "run_id": run_id,
                "remote_directory": "/remote/runs/" + run_id,
                "script_sha256": run_sha,
                "input_sha256": {},
                "steps": [{"tool": "sdevice", "args": [], "outputs": ["final_access_des.tdr"]}],
                "tool_evidence": {"step-001-sdevice": {"raw_exit_file": "step-001-sdevice-exit-code.txt", "tool": "sdevice"}},
                "tool_exit_codes": {"step-001-sdevice": None},
                "ssh_exit_code": 0,
                "remote_exit_code": 0,
                "state": "EXECUTED",
            }
            (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            def fake_remote(ssh, cmd, **kwargs):
                if "TCAD_SNAPSHOT" in cmd:
                    return subprocess.CompletedProcess(
                        args=[], returncode=0,
                        stdout=json.dumps({"schema": "tcad-original-snapshot-r1", "sha256": tar_sha, "bytes": len(tar_bytes), "members": len(index)}),
                    )
                if "cat " in cmd:
                    kwargs["stdout"].write(tar_bytes)
                    return subprocess.CompletedProcess(args=[], returncode=0)
                raise AssertionError("Unexpected remote cmd: " + cmd)

            cfg = {"remote_root": "/remote", "local_state_root": str(root)}
            with mock.patch.object(tcad, "state_root", return_value=root), \
                 mock.patch.object(tcad, "status_run", return_value={"status": "FINISHED", "alive": False, "remote_exit_code": 0}), \
                 mock.patch.object(tcad, "remote", side_effect=fake_remote):
                res = tcad.collect_run(cfg, ["ssh", "dummy"], run_id)

            self.assertEqual(res["status"], "FAILED_COLLECTED")
            self.assertEqual(res["remote_exit_code"], 143)
            saved = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "FAILED_COLLECTED")
            self.assertEqual(saved["execution_outcome"], "TERMINATED_BY_OPERATOR")
            self.assertTrue(saved["collection_verified"])


class TestPlannerSidecar(unittest.TestCase):
    def test_disabled_mode_never_invokes_cycle(self):
        called = []
        sidecar = AsyncPlannerSidecar(
            mode="disabled",
            run_cycle_fn=lambda *a: called.append(a) or {},
            watch_key_fn=lambda *a: "k",
            should_wake_fn=lambda *a: True,
            new_artifact_fn=lambda *a: False,
            save_checkpoint_fn=lambda cp: None,
        )
        sidecar.maybe_trigger(policy={}, ready={}, checkpoint=None, observation={"needs_planning": True}, stop={"requested": False})
        self.assertEqual(called, [])
        self.assertFalse(sidecar.is_running)

    def test_on_demand_async_runs_off_hot_path_and_wakes(self):
        wake = threading.Event()
        saved = []

        def fake_cycle(pol, rdy, prev, stp, obs):
            time.sleep(0.05)
            return {"state": "reported", "report": {"status": "waiting"}}

        sidecar = AsyncPlannerSidecar(
            mode="on_demand_async",
            run_cycle_fn=fake_cycle,
            watch_key_fn=lambda *a: "k1",
            should_wake_fn=lambda *a: True,
            new_artifact_fn=lambda *a: False,
            save_checkpoint_fn=lambda cp: saved.append(cp),
            wake_event=wake,
        )
        t0 = time.monotonic()
        sidecar.maybe_trigger(
            policy={"minimum_interval_seconds": 300},
            ready={},
            checkpoint=None,
            observation={"needs_planning": True, "fingerprint": "fp"},
            stop={"requested": False},
        )
        # Must return immediately (non-blocking)
        self.assertLess(time.monotonic() - t0, 0.04)
        self.assertTrue(wake.wait(timeout=2.0))
        sidecar.join(timeout=2.0)
        self.assertEqual(len(saved), 1)
        self.assertEqual(sidecar.cycles_completed, 1)


class TestSchedulerEngineE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = self.root / "workspace"
        self.state_dir = self.root / "state"
        self.ws.mkdir()
        self.state_dir.mkdir()
        (self.ws / ".git").mkdir()

        self.cloud_root = self.ws / "local_runtime/cloud-benchmark"
        self.local_state_root = self.cloud_root / "guest-test"
        (self.local_state_root / "runs").mkdir(parents=True)
        (self.local_state_root / "dram-see-v4/transport-probe/operations").mkdir(parents=True)
        (self.cloud_root / "geant4-preparation/inputs/g4-1").mkdir(parents=True)
        (self.cloud_root / "geant4-preparation/inputs/g4-1/task.sh").write_text("#!/bin/bash\necho g4\n", encoding="utf-8")

        # 13-slot mixed TCAD profile (12x1 + 1x4, CPUs 0..15)
        self.tcad_profile = self.cloud_root / "connection-tcad.json"
        self.tcad_cfg = {
            "backend": "ssh-runtime",
            "ssh_target": "tcad-guest-sim",
            "runtime_entry": "/usr/local/bin/enter",
            "remote_root": "/home/tcad/research-training",
            "tool_bin": "/usr/synopsys/sentaurus/W-2024.09/bin",
            "local_state_root": str(self.local_state_root),
            "parallel_capacity": 13,
            "cpu_sets": [[i] for i in range(12)] + [[12, 13, 14, 15]],
        }
        self.tcad_profile.write_text(json.dumps(self.tcad_cfg), encoding="utf-8")

        # 9-slot single-core Geant4 profile
        self.g4_profile = self.cloud_root / "connection-g4.json"
        self.g4_cfg = {
            "backend": "ssh-runtime",
            "ssh_target": "tcad-guest-sim",
            "runtime_entry": "/usr/local/bin/enter",
            "remote_root": "/home/tcad/research-training",
            "tool_bin": "/usr/synopsys/sentaurus/W-2024.09/bin",
            "local_state_root": str(self.local_state_root),
            "parallel_capacity": 9,
        }
        self.g4_profile.write_text(json.dumps(self.g4_cfg), encoding="utf-8")

        self.queue_file = self.ws / "plans/work-items.json"
        self.queue_file.parent.mkdir(parents=True)
        self.policy = {
            "schema": "tcad-server-codex-v2",
            "enabled": True,
            "workspace": str(self.ws),
            "state_dir": str(self.state_dir),
            "queue_file": str(self.queue_file),
            "runner_python": sys.executable,
            "max_parallel_jobs": 13,
            "transport_connection_file": str(self.g4_profile),
            "transport_max_parallel_jobs": 9,
            "poll_interval_seconds": 5,
            "scheduler_version": "v3",
            "planner_mode": "disabled",
            "resources": {
                "enabled": True,
                "min_available_memory_gib": 3.5,
                "min_host_disk_free_gib": 1.0,
                "min_remote_disk_free_gib": 5.0,
                "require_tcad_license_alive": True,
            },
        }
        self.ready = {
            "schema": "tcad-server-codex-v2",
            "new_jobs_authorized": True,
            "controller_owner": "server-codex",
            "sole_scheduler": True,
            "connection": str(self.tcad_profile),
            "transport_connection": str(self.g4_profile),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _make_tcad_project(self, name: str, threads: int = 1) -> str:
        rel = f"experiments/{name}"
        folder = self.ws / rel
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "project.json").write_text(json.dumps({
            "name": name,
            "native_threads": threads,
            "native_cores": threads,
            "steps": [{"tool": "sdevice", "args": ["sim.cmd"], "outputs": ["out.tdr"]}],
        }), encoding="utf-8")
        return rel

    def _write_tcad_manifest(self, run_id: str, slot: int, project_rel: str, state: str = "RUNNING",
                             collected: bool = False, released: bool = False, exit_code: int | None = None):
        folder = self.local_state_root / "runs" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        cpu_set = self.tcad_cfg["cpu_sets"][slot]
        manifest = {
            "schema": "tcad-native-run-r2",
            "run_id": run_id,
            "project_directory": str((self.ws / project_rel).resolve()),
            "remote_directory": f"/home/tcad/research-training/runs/{run_id}",
            "connection_identity": {k: self.tcad_cfg[k] for k in ("backend", "ssh_target", "runtime_entry", "remote_root")},
            "input_sha256": {},
            "state": state,
            "remote_exit_code": exit_code,
            "collection_verified": collected,
            "parallel_slot_released": released,
            "parallel_policy": {
                "schema": "tcad-shared-gate-slots-v2",
                "slot": slot,
                "capacity": 13,
                "pool_root": "/home/tcad/research-training",
                "connection_identity": {k: self.tcad_cfg[k] for k in ("backend", "ssh_target", "runtime_entry", "remote_root")},
                "work_id": run_id,
                "remote_directory": f"/home/tcad/research-training/runs/{run_id}",
                "kind": "run",
                "cpu_set": cpu_set,
                "requested_threads": len(cpu_set),
                "cpu_sets": self.tcad_cfg["cpu_sets"],
            },
        }
        if collected:
            tar_path = folder / "results.tar"
            tar_path.write_bytes(b"fake-tar-content-" + run_id.encode())
            manifest["results_sha256"] = hashlib.sha256(tar_path.read_bytes()).hexdigest()
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_deadlock_regression_active2_running0_switches_cleanly_to_geant4(self):
        """Reproduce production failure #1: active=2, running=0 + ready Geant4 task must collect & switch cleanly."""
        p1 = self._make_tcad_project("tcad-1", 1)
        p2 = self._make_tcad_project("tcad-2", 1)
        self._write_tcad_manifest("run-t1", 0, p1, state="EXECUTED", collected=False, released=False, exit_code=0)
        self._write_tcad_manifest("run-t2", 1, p2, state="EXECUTED", collected=False, released=False, exit_code=0)

        self.queue_file.write_text(json.dumps({
            "schema": "tcad-work-items-v1",
            "tasks": [
                {"id": "tcad-1", "backend": "tcad", "project": p1, "depends_on": [], "requires": []},
                {"id": "tcad-2", "backend": "tcad", "project": p2, "depends_on": [], "requires": []},
                {"id": "g4-1", "backend": "geant4", "project": "local_runtime/cloud-benchmark/geant4-preparation/inputs/g4-1", "depends_on": [], "requires": []},
            ],
        }), encoding="utf-8")

        # Seed existing intents for tcad-1 and tcad-2
        engine = SchedulerEngine(self.policy, self.ready, async_collect=False, batch_probe_enabled=True)
        engine._profile()
        for tid, rid, slot, proj in (("tcad-1", "run-t1", 0, p1), ("tcad-2", "run-t2", 1, p2)):
            canon = {"id": tid, "backend": "tcad", "project": proj, "depends_on": [], "requires": [], "repair_of": None, "repair_reason": "", "adopt_run_id": None}
            engine.intents[tid] = {
                "run_id": rid, "backend": "tcad", "project": proj, "slot": slot,
                "connection": {"path": str(self.tcad_profile), "sha256": "x"},
                "task_digest": _load_module("_rt_h", HERE / "runtime.py").digest(canon),
                "input_sha256": {}, "input_digest": "x", "repair_of": None, "repair_reason": "",
                "requested_resources": engine._slot_resources(slot, self.tcad_cfg),
            }
        engine._save()

        # Fake batch probe reports both TCAD processes are dead with exit 0
        def fake_probe(cfg, active_runs, host_disk_free_gib=None):
            return RemoteTelemetry(
                observed_at=time.time(), available=True, boot_id="boot-1",
                mem_total_gib=28.0, mem_available_gib=22.0,
                host_disk_free_gib=50.0, remote_disk_free_gib=40.0,
                license_daemons_alive=True,
                runs={
                    "run-t1": RunProbeSnapshot(run_id="run-t1", backend="tcad", exists=True, alive=False, status="FINISHED", remote_exit_code=0),
                    "run-t2": RunProbeSnapshot(run_id="run-t2", backend="tcad", exists=True, alive=False, status="FINISHED", remote_exit_code=0),
                },
            )

        submitted_g4 = []

        def fake_invoke(intent, cmd, **kwargs):
            if cmd == "collect":
                slot = intent["slot"]
                proj = intent["project"]
                self._write_tcad_manifest(intent["run_id"], slot, proj, state="COLLECTED", collected=True, released=True, exit_code=0)
                return {"ok": True, "payload": {"status": "COLLECTED"}}
            if cmd == "run":
                submitted_g4.append(intent["run_id"])
                return {"ok": True, "payload": {"status": "RUNNING", "label": intent["run_id"]}}
            return {"ok": True, "payload": {}}

        with mock.patch.object(engine.probe, "probe", side_effect=fake_probe), \
             mock.patch.object(engine, "_invoke_command", side_effect=fake_invoke), \
             mock.patch.object(engine, "_invoke", side_effect=lambda intent, cmd: fake_invoke(intent, cmd)):
            obs = engine.tick(allow_submit=True)

        engine.close()
        # Both finished TCAD runs collected & released in the same tick, and Geant4 immediately dispatched!
        self.assertEqual(len(submitted_g4), 1)
        self.assertEqual(obs["scheduler"]["pool"]["state"], "ACTIVE")
        self.assertEqual(obs["scheduler"]["pool"]["active_profile"], "geant4")
        self.assertEqual(obs["scheduler"]["last_decision"]["action"], "dispatched")
        self.assertIn("g4-1", obs["scheduler"]["last_decision"]["dispatched"])

    def test_quarantined_slot_does_not_block_sibling_slots_and_is_status_checker_compatible(self):
        """Permanent contract error quarantines slot 0 (0 retries) while slot 1 still dispatches."""
        p1 = self._make_tcad_project("tcad-bad", 1)
        p2 = self._make_tcad_project("tcad-good", 1)
        self._write_tcad_manifest("run-bad", 0, p1, state="EXECUTED", collected=False, released=False, exit_code=0)

        self.queue_file.write_text(json.dumps({
            "schema": "tcad-work-items-v1",
            "tasks": [
                {"id": "tcad-bad", "backend": "tcad", "project": p1, "depends_on": [], "requires": []},
                {"id": "tcad-good", "backend": "tcad", "project": p2, "depends_on": [], "requires": []},
            ],
        }), encoding="utf-8")

        engine = SchedulerEngine(self.policy, self.ready, async_collect=False, batch_probe_enabled=True)
        engine._profile()
        canon_bad = {"id": "tcad-bad", "backend": "tcad", "project": p1, "depends_on": [], "requires": [], "repair_of": None, "repair_reason": "", "adopt_run_id": None}
        engine.intents["tcad-bad"] = {
            "run_id": "run-bad", "backend": "tcad", "project": p1, "slot": 0,
            "connection": {"path": str(self.tcad_profile), "sha256": "x"},
            "task_digest": _load_module("_rt_h2", HERE / "runtime.py").digest(canon_bad),
            "input_sha256": {}, "input_digest": "x", "repair_of": None, "repair_reason": "",
            "requested_resources": engine._slot_resources(0, self.tcad_cfg),
        }
        engine._save()

        def fake_probe(cfg, active_runs, host_disk_free_gib=None):
            return RemoteTelemetry(
                observed_at=time.time(), available=True, boot_id="boot-1",
                mem_total_gib=28.0, mem_available_gib=22.0,
                host_disk_free_gib=50.0, remote_disk_free_gib=40.0,
                license_daemons_alive=True,
                runs={
                    "run-bad": RunProbeSnapshot(run_id="run-bad", backend="tcad", exists=True, alive=False, status="FINISHED", remote_exit_code=0),
                },
            )

        def fake_invoke(intent, cmd, **kwargs):
            if cmd == "collect":
                return {"ok": False, "kind": "runner_error", "returncode": 1,
                        "detail": "ValueError: Success marker conflicts with raw native exits"}
            if cmd == "run":
                return {"ok": True, "payload": {"status": "RUNNING", "run_id": intent["run_id"]}}
            return {"ok": True, "payload": {}}

        with mock.patch.object(engine.probe, "probe", side_effect=fake_probe), \
             mock.patch.object(engine, "_invoke_command", side_effect=fake_invoke), \
             mock.patch.object(engine, "_invoke", side_effect=lambda intent, cmd: fake_invoke(intent, cmd)):
            obs = engine.tick(allow_submit=True)

        engine.close()
        # Slot 0 quarantined with 0 retries, while tcad-good was dispatched onto slot 1!
        self.assertTrue(engine.intents["tcad-bad"].get("quarantined"))
        self.assertIn("tcad-good", obs["scheduler"]["last_decision"]["dispatched"])
        self.assertEqual(engine.intents["tcad-good"]["slot"], 1)
        self.assertEqual(len(obs["scheduler"]["quarantined_tasks"]), 1)

        # Verify status-checker contract compatibility on produced observation.json
        sc_dir = REPO_ROOT / "xjtu-shop-site/status-checker"
        if str(sc_dir) not in sys.path:
            sys.path.insert(0, str(sc_dir))
        sc = _load_module("_test_status_checker", sc_dir / "status_checker.py")
        obs_payload = {"utc": "2026-11-20T14:20:00+00:00", **obs}
        obs_path = self.state_dir / "observation.json"
        obs_path.write_text(json.dumps(obs_payload), encoding="utf-8")
        summary = sc.simulation_status(
            obs_path,
            self.state_dir / "runtime.json",
            self.local_state_root / "runs",
            now=sc.parse_time("2026-11-20T14:20:10+00:00"),
        )
        self.assertIsInstance(summary, dict)
        self.assertIn("current_runs", summary)
        sc.check_public_payload(summary)


if __name__ == "__main__":
    unittest.main()
