"""Offline unit tests for scripts/batch_runner.py (no SSH, no solver, no VM mutations)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_batch_runner():
    spec = importlib.util.spec_from_file_location("_test_batch_runner", ROOT / "scripts/batch_runner.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BatchRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_ctx.cleanup)
        self.tmp = Path(self.tmp_ctx.name)
        self.br = load_batch_runner()
        self.work_dir = self.tmp / "work"
        self.state_root = self.tmp / "state"
        self.work_dir.mkdir()
        self.state_root.mkdir()
        self.profile_path = self.tmp / "connection-test.json"
        self.profile = {
            "backend": "ssh-runtime",
            "ssh_target": "tcad-guest-sim",
            "runtime_entry": "/usr/bin/env",
            "remote_root": "/home/tcad/research-training",
            "tool_bin": "/usr/synopsys/sentaurus/W-2024.09/bin",
            "local_state_root": str(self.state_root),
            "parallel_capacity": 3,
            "cpu_sets": [[0, 1, 2], [3, 4, 5], [6, 7, 8]],
            "requested_threads": 3,
        }
        self.profile_path.write_text(json.dumps(self.profile), encoding="utf-8")

        self.projects = {}
        jobs = []
        for idx, run_id in enumerate(("run-a", "run-b")):
            proj = self.work_dir / "projects" / run_id
            proj.mkdir(parents=True)
            (proj / "project.json").write_text(json.dumps({"name": run_id, "steps": []}), encoding="utf-8")
            (proj / "device.cmd").write_text(f"# case {run_id}\n", encoding="utf-8")
            self.projects[run_id] = proj
            jobs.append({
                "compare_run_id": run_id,
                "slot": idx,
                "input_sha256": {
                    "device.cmd": sha(proj / "device.cmd"),
                    "project.json": sha(proj / "project.json"),
                },
            })
        self.jobs_path = self.work_dir / "jobs.json"
        self.jobs_path.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")

    def test_attempts_are_timestamp_isolated_and_retries_never_collide(self):
        first = self.br.execute_batch(
            profile_path=self.profile_path,
            jobs_path=self.jobs_path,
            work_dir=self.work_dir,
            phase="three-three",
            dry_run=True,
            skip_controller_guard=True,
            skip_idle_check=True,
        )
        second = self.br.execute_batch(
            profile_path=self.profile_path,
            jobs_path=self.jobs_path,
            work_dir=self.work_dir,
            phase="three-three",
            dry_run=True,
            skip_controller_guard=True,
            skip_idle_check=True,
        )
        self.assertNotEqual(first["attempt_dir"], second["attempt_dir"])
        self.assertTrue(Path(first["attempt_dir"]).is_dir())
        self.assertTrue(Path(second["attempt_dir"]).is_dir())
        self.assertEqual(first["to_submit"], ["run-a", "run-b"])

    def test_frozen_input_data_drift_is_still_caught(self):
        (self.projects["run-a"] / "device.cmd").write_text("# tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Frozen scientific input data changed"):
            self.br.execute_batch(
                profile_path=self.profile_path,
                jobs_path=self.jobs_path,
                work_dir=self.work_dir,
                phase="check",
                dry_run=True,
                skip_controller_guard=True,
                skip_idle_check=True,
            )

    def test_resume_skips_collected_adopts_running_and_submits_only_new(self):
        # run-a is already collected and released; run-b has not been started.
        run_a_dir = self.state_root / "runs" / "run-a"
        run_a_dir.mkdir(parents=True)
        archive = run_a_dir / "results.tar"
        archive.write_bytes(b"fake-archive")
        (run_a_dir / "manifest.json").write_text(json.dumps({
            "run_id": "run-a",
            "parallel_policy": {"slot": 0},
            "project_directory": str(self.projects["run-a"]),
            "input_sha256": {"project.json": sha(self.projects["run-a"] / "project.json"),
                             "device.cmd": sha(self.projects["run-a"] / "device.cmd")},
            "state": "COLLECTED",
            "collection_verified": True,
            "parallel_slot_released": True,
            "results_sha256": sha(archive),
            "remote_exit_code": 0,
        }), encoding="utf-8")

        # Without --resume, refuses to overwrite or silently ignore existing run-a.
        with self.assertRaisesRegex(RuntimeError, "--resume"):
            self.br.execute_batch(
                profile_path=self.profile_path,
                jobs_path=self.jobs_path,
                work_dir=self.work_dir,
                phase="resume-test",
                dry_run=True,
                skip_controller_guard=True,
                skip_idle_check=True,
            )

        # With --resume, skips run-a and schedules only run-b.
        summary = self.br.execute_batch(
            profile_path=self.profile_path,
            jobs_path=self.jobs_path,
            work_dir=self.work_dir,
            phase="resume-test",
            resume=True,
            dry_run=True,
            skip_controller_guard=True,
            skip_idle_check=True,
        )
        self.assertEqual(summary["already_collected"], ["run-a"])
        self.assertEqual(summary["to_submit"], ["run-b"])
        self.assertEqual(summary["already_active"], [])

    def test_preflight_rejection_exit_75_is_recorded_without_poisoning_retry(self):
        fake_runner = self.tmp / "fake_tcad.py"
        fake_runner.write_text(
            "import sys\n"
            "print('PREFLIGHT_REJECTED: slot busy', file=sys.stderr)\n"
            "sys.exit(75)\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "Preflight rejected for run-a"):
            self.br.execute_batch(
                profile_path=self.profile_path,
                jobs_path=self.jobs_path,
                work_dir=self.work_dir,
                phase="preflight-fail",
                python_bin=sys.executable,
                skip_controller_guard=True,
                skip_idle_check=True,
                runner_path=fake_runner,
                cwd=self.tmp,
            )
        events = [json.loads(line) for line in (self.work_dir / "batch-events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(e["state"] == "PREFLIGHT_REJECTED" and e["run_id"] == "run-a" for e in events))
        # No dirty manifest was created; a second attempt can immediately retry without manual cleanup!
        self.assertFalse((self.state_root / "runs" / "run-a" / "manifest.json").exists())
        retry = self.br.execute_batch(
            profile_path=self.profile_path,
            jobs_path=self.jobs_path,
            work_dir=self.work_dir,
            phase="preflight-retry",
            dry_run=True,
            skip_controller_guard=True,
            skip_idle_check=True,
        )
        self.assertEqual(retry["to_submit"], ["run-a", "run-b"])


if __name__ == "__main__":
    unittest.main()
