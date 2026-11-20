"""Unit tests for data-driven v2 slot scheduling and atomic preflight reserve in scripts/tcad.py."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunnerSchedulerV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_ctx.cleanup)
        self.tmp = Path(self.tmp_ctx.name)
        self.tcad = load_module(ROOT / "scripts/tcad.py", "_test_tcad_v2")
        self.state_root = self.tmp / "state"
        self.state_root.mkdir()
        self.tcad.STATE_ROOT = self.state_root
        self.base_cfg = {
            "backend": "ssh-runtime",
            "ssh_target": "tcad-guest-sim",
            "runtime_entry": "/usr/bin/env",
            "remote_root": "/home/tcad/research-training",
            "tool_bin": "/usr/synopsys/sentaurus/W-2024.09/bin",
            "local_state_root": str(self.state_root),
        }

    def test_data_driven_v2_and_legacy_r1_to_r9_policies(self):
        # Legacy r4..r9 keep exact legacy schemas for backward compatibility.
        r4 = dict(self.base_cfg, parallel_capacity=4,
                  cpu_sets=[[0, 1], [2, 3], [4, 5], [6, 7]], requested_threads=2)
        p4 = self.tcad.parallel_policy(r4, 1, "job-r4", "/home/tcad/research-training/runs/job-r4")
        self.assertEqual(p4["schema"], "tcad-shared-gate-slots-r4")
        self.assertNotIn("cpu_sets", p4)

        r8 = dict(self.base_cfg, parallel_capacity=10,
                  cpu_sets=[[i] for i in range(10)], requested_threads=1)
        p8 = self.tcad.parallel_policy(r8, 9, "job-r8", "/home/tcad/research-training/runs/job-r8")
        self.assertEqual(p8["schema"], "tcad-shared-gate-slots-r8")

        # Arbitrary new layout (3x3) automatically uses tcad-shared-gate-slots-v2.
        v2 = dict(self.base_cfg, parallel_capacity=3,
                  cpu_sets=[[0, 1, 2], [3, 4, 5], [6, 7, 8]], requested_threads=3)
        pv2 = self.tcad.parallel_policy(v2, 2, "job-3x3", "/home/tcad/research-training/runs/job-3x3")
        self.assertEqual(pv2["schema"], "tcad-shared-gate-slots-v2")
        self.assertEqual(pv2["cpu_set"], [6, 7, 8])
        self.assertEqual(pv2["requested_threads"], 3)
        self.assertEqual(pv2["cpu_sets"], [[0, 1, 2], [3, 4, 5], [6, 7, 8]])

        # Heterogeneous v2 layout works when per-slot requested_threads matches or is omitted.
        het = dict(self.base_cfg, parallel_capacity=3, cpu_sets=[[0], [1, 2], [3, 4, 5]])
        phet = self.tcad.parallel_policy(het, 1, "job-het", "/home/tcad/research-training/runs/job-het")
        self.assertEqual(phet["schema"], "tcad-shared-gate-slots-v2")
        self.assertEqual(phet["requested_threads"], 2)

        # Overlapping CPUs across slots must be rejected.
        bad_overlap = dict(self.base_cfg, parallel_capacity=2, cpu_sets=[[0, 1], [1, 2]], requested_threads=2)
        with self.assertRaisesRegex(ValueError, "Overlapping CPU"):
            self.tcad.parallel_capacity(bad_overlap)

        # Mismatched requested_threads must be rejected.
        bad_threads = dict(self.base_cfg, parallel_capacity=2, cpu_sets=[[0, 1], [2, 3]], requested_threads=4)
        with self.assertRaisesRegex(ValueError, "requested_threads"):
            self.tcad.parallel_capacity(bad_threads)

    def test_thirteen_slot_policy_preserves_pool_identity(self):
        cpu_sets = [[cpu] for cpu in range(12)] + [[12, 13, 14, 15]]
        cfg = dict(self.base_cfg, parallel_capacity=13, cpu_sets=cpu_sets,
                   requested_threads=[1] * 12 + [4])
        directory = "/home/tcad/research-training/runs/new-job"
        policy = self.tcad.parallel_policy(cfg, 12, "new-job", directory)

        self.assertEqual(policy["schema"], "tcad-shared-gate-slots-v2")
        self.assertEqual(policy["pool_root"], self.base_cfg["remote_root"])
        self.assertEqual(policy["connection_identity"], self.tcad.connection_identity(self.base_cfg))
        self.assertEqual(policy["cpu_sets"], cpu_sets)
        self.assertEqual(policy["cpu_set"], [12, 13, 14, 15])
        self.assertEqual(policy["requested_threads"], 4)
        with self.assertRaises(ValueError):
            self.tcad.parallel_policy(cfg, 13, "new-job", directory)

    def test_preflight_reserve_rejection_rolls_back_staging_without_dirty_manifest(self):
        cfg = dict(self.base_cfg, parallel_capacity=3,
                   cpu_sets=[[0, 1, 2], [3, 4, 5], [6, 7, 8]], requested_threads=3)
        project = self.tmp / "proj-a"
        project.mkdir()
        (project / "project.json").write_text(json.dumps({
            "name": "proj-a",
            "native_threads": 3,
            "native_cores": 3,
            "steps": [{"tool": "sdevice", "args": ["device.cmd"], "outputs": ["out.plt"]}],
        }), encoding="utf-8")
        (project / "device.cmd").write_text("# test\n", encoding="utf-8")

        fake_git = subprocess.CompletedProcess(["git"], 0, stdout="deadbeef\n", stderr="")
        reject = subprocess.CalledProcessError(
            75, ["ssh"], stderr="TCAD_RESERVE_REJECTED: Slot reserved until verified collection")
        with patch.object(self.tcad, "execute", return_value=fake_git), \
             patch.object(self.tcad, "parallel_query", side_effect=reject):
            with self.assertRaises(self.tcad.PreflightRejected):
                self.tcad._run_project(cfg, ["ssh", "tcad-guest-sim"], project,
                                       run_id="clean-retry-id", detach=True, parallel_slot=0)

        # No runs/clean-retry-id directory or .staging-* leftover remains!
        self.assertFalse((self.state_root / "runs" / "clean-retry-id").exists())
        staging_leftovers = list((self.state_root / "runs").glob(".staging-*"))
        self.assertEqual(staging_leftovers, [])
        # Diagnostic file was recorded with timestamp.
        diags = list((self.state_root / "preflight-failures").glob("*-clean-retry-id-*.json"))
        self.assertEqual(len(diags), 1)
        self.assertTrue(json.loads(diags[0].read_text(encoding="utf-8"))["preflight_rejected"])

    def test_uncertain_reservation_preserves_manifest_for_recovery(self):
        cfg = dict(self.base_cfg, parallel_capacity=3,
                   cpu_sets=[[0, 1, 2], [3, 4, 5], [6, 7, 8]], requested_threads=3)
        project = self.tmp / "proj-b"
        project.mkdir()
        (project / "project.json").write_text(json.dumps({
            "name": "proj-b",
            "native_threads": 3,
            "native_cores": 3,
            "steps": [{"tool": "sdevice", "args": ["device.cmd"], "outputs": ["out.plt"]}],
        }), encoding="utf-8")
        (project / "device.cmd").write_text("# test\n", encoding="utf-8")

        fake_git = subprocess.CompletedProcess(["git"], 0, stdout="deadbeef\n", stderr="")
        failures = [
            subprocess.CalledProcessError(255, ["ssh"], stderr="Connection closed"),
            subprocess.CalledProcessError(75, ["ssh"], stderr="No reservation receipt"),
            ValueError("Missing original reservation receipt"),
        ]
        for number, failure in enumerate(failures):
            with self.subTest(failure=failure):
                run_id = "uncertain-reserve-{}".format(number)
                with patch.object(self.tcad, "execute", return_value=fake_git), \
                     patch.object(self.tcad, "parallel_query", side_effect=failure):
                    with self.assertRaises(type(failure)):
                        self.tcad._run_project(cfg, ["ssh", "tcad-guest-sim"], project,
                                               run_id=run_id, detach=True, parallel_slot=0)
                manifest_file = self.state_root / "runs" / run_id / "manifest.json"
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                self.assertEqual(data["state"], "TRANSFER_OR_CONNECTION_FAILED")
                self.assertEqual(data["ssh_exit_code"], getattr(failure, "returncode", None))


@unittest.skipUnless(sys.platform.startswith("linux"), "Requires Linux /proc, flock, O_NOFOLLOW")
class LinuxProtocolV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_ctx.cleanup)
        self.tmp = Path(self.tmp_ctx.name)
        self.tcad = load_module(ROOT / "scripts/tcad.py", "_test_tcad_linux_v2")
        self.root = self.tmp / "pool"
        self.store = self.root / ".solver-slots"
        self.store.mkdir(parents=True)
        for p in [self.root / ".solver.lock", self.store / "allocation.lock"] + [
            self.store / f"slot-{i}.lock" for i in range(10)
        ]:
            p.touch()
        self.cfg = {
            "backend": "ssh-runtime",
            "ssh_target": "tcad-guest-sim",
            "runtime_entry": "/usr/bin/env",
            "remote_root": str(self.root),
            "tool_bin": "/usr/synopsys/sentaurus/W-2024.09/bin",
            "local_state_root": str(self.tmp / "state"),
        }

    def run_protocol(self, request: dict) -> dict:
        proc = subprocess.run(
            [sys.executable, "-c", self.tcad.PARALLEL_CODE, json.dumps(request, sort_keys=True)],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"protocol exit {proc.returncode}: {proc.stderr}")
        return json.loads(proc.stdout)

    def test_idle_pool_with_unknown_future_collected_lease_allows_v2_reserve(self):
        # Seed slot-0 with a closed COLLECTED lease from an unrecognized schema (like r99)
        # and a foreign capacity.json, simulating cross-version history in an idle pool.
        (self.store / "slot-0.json").write_text(json.dumps({
            "state": "COLLECTED",
            "script_sha256": "a" * 64,
            "policy": {
                "schema": "tcad-shared-gate-slots-r99",
                "capacity": 1,
                "slot": 0,
                "pool_root": str(self.root),
                "connection_identity": self.tcad.connection_identity(self.cfg),
                "work_id": "future-history-job",
                "remote_directory": str(self.root / "runs/future-history-job"),
                "kind": "run",
            },
        }), encoding="utf-8")
        (self.store / "capacity.json").write_text(json.dumps({
            "schema": "tcad-slot-pool-r99", "capacity": 1, "cpu_sets": [[0]], "requested_threads": 1,
        }), encoding="utf-8")

        # Reserve using a brand-new dynamic v2 layout (e.g. 2x1 on available online CPUs).
        import os
        online = sorted(os.sched_getaffinity(0))
        chosen = [[online[0]]] if len(online) == 1 else [[online[0]], [online[1]]]
        v2_cfg = dict(self.cfg, parallel_capacity=len(chosen), cpu_sets=chosen, requested_threads=1)
        policy = self.tcad.parallel_policy(v2_cfg, 0, "new-v2-job", str(self.root / "runs/new-v2-job"))
        self.assertEqual(policy["schema"], "tcad-shared-gate-slots-v2")

        lease = self.run_protocol({"policy": policy, "action": "reserve", "script_sha256": "b" * 64})
        self.assertEqual(lease["state"], "RESERVED")
        cap = json.loads((self.store / "capacity.json").read_text(encoding="utf-8"))
        self.assertEqual(cap["schema"], "tcad-slot-pool-v2")
        self.assertEqual(cap["cpu_sets"], chosen)

        competing = dict(policy, work_id="competing-job",
                         remote_directory=str(self.root / "runs/competing-job"))
        request = {"policy": competing, "action": "reserve", "script_sha256": "e" * 64}
        probe = subprocess.run(
            [sys.executable, "-c", self.tcad.PARALLEL_CODE, json.dumps(request)],
            capture_output=True, text=True,
        )
        self.assertEqual(probe.returncode, 75)
        self.assertIn("TCAD_RESERVE_REJECTED: Slot reserved until verified collection", probe.stderr)
        self.assertEqual(json.loads((self.store / "slot-0.json").read_text()), lease)

    def test_v2_history_passes_unlaunched_proof_and_launch_reconciliation_validator(self):
        # Seed slot-0 with a COLLECTED v2 lease and capacity.json with tcad-slot-pool-v2.
        v2_cfg = dict(self.cfg, parallel_capacity=3,
                      cpu_sets=[[0, 1, 2], [3, 4, 5], [6, 7, 8]], requested_threads=3)
        v2_policy = self.tcad.parallel_policy(v2_cfg, 0, "hist-v2", str(self.root / "runs/hist-v2"))
        (self.store / "slot-0.json").write_text(json.dumps({
            "state": "COLLECTED", "script_sha256": "c" * 64, "policy": v2_policy,
        }), encoding="utf-8")
        (self.store / "capacity.json").write_text(json.dumps(
            self.tcad._MULTICORE_HELPERS["mc_pool_configuration"]("tcad-shared-gate-slots-v2", v2_cfg["cpu_sets"])
        ), encoding="utf-8")

        nine_cfg = dict(self.cfg, parallel_capacity=9)
        label = "never-launched-v2"
        directory = self.root / "dram-see-v4/transport-probe/operations" / label
        directory.parent.mkdir(parents=True)
        op_policy = self.tcad.parallel_policy(nine_cfg, 1, label, str(directory), "operation")
        validator = load_module(ROOT / "experiments/dram-see-v4/transport-probe/launch_reconciliation.py",
                                "_test_lr_v2")
        subject = {
            "label": label, "remote_directory": str(directory),
            "parallel_policy": op_policy, "connection_identity": self.tcad.connection_identity(nine_cfg),
            "script_sha256": "a" * 64,
        }
        request = {
            "policy": op_policy, "action": "prove-unlaunched",
            "script_sha256": "a" * 64, "subject_sha256": validator.canonical_sha256(subject),
        }

        proc = self.tmp / "proc"
        (proc / "sys/kernel/random").mkdir(parents=True)
        (proc / "sys/kernel/random/boot_id").write_text("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        for pid, parent in ((1, 0), (100, 1)):
            p = proc / str(pid)
            p.mkdir(exist_ok=True)
            fields = ["0"] * 22
            fields[0], fields[1], fields[19] = "R", str(parent), str(1000 + pid)
            (p / "stat").write_text(f"{pid} (python) {' '.join(fields)}")
            (p / "comm").write_text("python")
            (p / "cmdline").write_bytes(b"python proof")
            (p / "cwd").symlink_to(self.tmp)

        ns = {}
        source = self.tcad.PARALLEL_CODE.split("safe_path(root);need(root.is_dir()")[0]
        with patch.object(sys, "argv", ["protocol", json.dumps(request)]):
            exec(compile(source, "<v2 protocol>", "exec"), ns)
        ns["proc"] = proc
        real_os = ns["os"]
        ns["os"] = types.SimpleNamespace(**{n: getattr(real_os, n) for n in dir(real_os)})
        ns["os"].getpid = lambda: 100
        proof = ns["prove_unlaunched"]()
        self.assertTrue(validator.validate_proof(proof, subject))


if __name__ == "__main__":
    unittest.main()
