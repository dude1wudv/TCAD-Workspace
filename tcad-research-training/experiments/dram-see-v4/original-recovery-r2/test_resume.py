"""Isolated resume and cleanup handoff checks; never launch a real child."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
R1 = HERE.parent / "original-recovery-r1"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(R1))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load("_r2_resume_campaign_runner", HERE / "campaign_runner.py")
continuation = load("_r2_resume_continue", HERE / "continue.py")
guard = continuation.release_guard


class ResumeIntegrationTests(unittest.TestCase):
    def test_resume_contract_binds_passed_a6_gate_and_outcome_bytes(self):
        contract = json.loads((HERE / "resume-contract.json").read_text(encoding="utf-8"))
        for key in ("old_owner", "failure", "a6_gate", "a6_outcome"):
            path = ROOT / contract[key]["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), contract[key]["sha256"])
        old_owner = json.loads((ROOT / contract["old_owner"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(old_owner["state"], "PAUSED_ON_RECORDED_FAILURE_NO_RETRY")
        self.assertEqual(len(old_owner["stages"]), 1)
        self.assertEqual(old_owner["stages"][0]["exit_code"], 1)
        gate = json.loads((ROOT / contract["a6_gate"]["path"]).read_text(encoding="utf-8"))
        outcome = json.loads((ROOT / contract["a6_outcome"]["path"]).read_text(encoding="utf-8"))
        self.assertIs(gate["passed"], True)
        self.assertIs(outcome["passed"], True)
        self.assertEqual(gate["role_id"], "a6-b1-time")

    def test_clean_preflight_accepts_only_recorded_idle_owner_and_valid_evidence(self):
        result, old_scheduler = self._preflight()
        self.assertEqual(result["path"], (HERE / "resume-contract.json").resolve().relative_to(ROOT).as_posix())
        self.assertEqual(old_scheduler.pid_alive.call_count, 2)
        old_scheduler.check_gate.assert_called_once_with("a6-b1-time")

    def test_existing_a6_outcome_reuses_postprocess_then_runs_r2_cleanup_only(self):
        label = "r5-a6-b1-time-r1"
        role = {"role_id": "a6-b1-time", "case_id": "A6"}
        execution = {"label": label, "role_id": role["role_id"], "run_id": "fixture-run",
                    "state": "RUNNER_EXITED", "runner_exit_code": 0}
        audit = Path("mock-existing-field-audit.json")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner.STATE = root / "state"
            runner.R5 = root / "r5"
            execution_path = runner.R5 / "launches" / label / "execution.json"
            execution_path.parent.mkdir(parents=True)
            execution_path.write_text(json.dumps(execution), encoding="utf-8")
            outcome_path = runner.STATE / "outcomes" / (label + ".json")
            outcome_path.parent.mkdir(parents=True)
            outcome_path.write_text(json.dumps({"passed": True, "role_id": role["role_id"]}), encoding="utf-8")
            with mock.patch.object(runner.a, "validate_invocation"), \
                 mock.patch.object(runner, "postprocess", return_value=audit) as postprocess, \
                 mock.patch.object(runner.a, "accept") as accept, \
                 mock.patch.object(runner, "cleanup_duplicates", return_value={"passed": True}) as cleanup, \
                 mock.patch.object(runner, "update"), mock.patch.object(runner, "budget") as budget:
                self.assertTrue(runner.process_finished(role, label))
            postprocess.assert_called_once_with(label, Path(runner.ROOT / "local_runtime/runs" / "fixture-run"))
            accept.assert_not_called()
            cleanup.assert_called_once_with(role, label)
            budget.assert_called_once_with()

    def test_adopt_loop_can_submit_only_the_two_unattempted_fine_roles(self):
        campaign = json.loads((runner.HERE / "campaign.json").read_text(encoding="utf-8"))
        executions = [json.loads(p.read_text(encoding="utf-8"))
                      for p in runner.R5.joinpath("launches").glob("*/execution.json")]
        gates = runner.STATE / "gates"
        fine = [r for r in campaign["roles"] if r.get("variant") == "fine" and r.get("case_id") != "A0"]
        eligible = [r["role_id"] for r in fine
                    if not (gates / (r["role_id"] + ".json")).exists()
                    and not any(e.get("role_id") == r["role_id"] for e in executions)]
        self.assertEqual(eligible, ["a1-b1-fine", "a5-b1-fine"])

        tree = ast.parse((HERE / "campaign_runner.py").read_text(encoding="utf-8"))
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run")
        source = ast.get_source_segment((HERE / "campaign_runner.py").read_text(encoding="utf-8"), run)
        self.assertIn("if gatefile.exists():", source)
        self.assertIn("if prior:", source)
        self.assertIn("continue", source[source.index("if gatefile.exists():"):source.index("if prior:")])
        self.assertIn("continue", source[source.index("if prior:"):source.index("missing=")])
        self.assertLess(source.index("if prior:"), source.index("label='r5-'+key+'-r1'"))

    def _preflight(self, *, owner_alive=False, changed_failure=False, a6_passed=True):
        original_read = guard.proof.read
        original_sha = guard.proof.sha
        contract = original_read(HERE / "resume-contract.json")
        old_owner = {"state": "PAUSED_ON_RECORDED_FAILURE_NO_RETRY", "owner_pid": 100,
                     "stages": [{"pid": 200, "exit_code": 1}]}
        a6_outcome = {"passed": a6_passed}
        item_paths = {str((guard.proof.ROOT / contract[name]["path"]).resolve()): contract[name]["sha256"]
                      for name in ("old_owner", "failure", "a6_gate", "a6_outcome")}

        def read(path):
            resolved = str(Path(path).resolve())
            if resolved == str((HERE / "resume-contract.json").resolve()):
                return copy.deepcopy(contract)
            if resolved == str((guard.proof.ROOT / contract["old_owner"]["path"]).resolve()):
                return copy.deepcopy(old_owner)
            if resolved == str((guard.proof.ROOT / contract["a6_outcome"]["path"]).resolve()):
                return copy.deepcopy(a6_outcome)
            return original_read(path)

        def digest(path):
            resolved = str(Path(path).resolve())
            if changed_failure and resolved == str((guard.proof.ROOT / contract["failure"]["path"]).resolve()):
                return "0" * 64
            if resolved in item_paths:
                return item_paths[resolved]
            return original_sha(path)

        old_scheduler = mock.Mock(pid_alive=mock.Mock(return_value=owner_alive))
        old_scheduler.check_gate = mock.Mock()
        with mock.patch.object(guard, "check_release"), \
             mock.patch.object(guard.proof, "read", side_effect=read), \
             mock.patch.object(guard.proof, "sha", side_effect=digest), \
             mock.patch.object(guard.proof, "module", return_value=old_scheduler):
            return guard.preflight_resume(), old_scheduler

    def test_resume_preflight_rejects_live_owner_changed_failure_and_missing_a6_pass(self):
        for kwargs, message in [
            ({"owner_alive": True}, "Previous continuation still alive"),
            ({"changed_failure": True}, "Original resume evidence changed: failure"),
            ({"a6_passed": False}, "A6 has not passed"),
        ]:
            with self.subTest(**kwargs), self.assertRaisesRegex(ValueError, message):
                self._preflight(**kwargs)

    def test_r2_owner_uses_shared_lock_adopts_a6_then_stops_before_pilot_on_2d_failure(self):
        class FailedChild:
            pid = 515151

            @staticmethod
            def wait():
                return 23

        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state"
            (state / "continuation").mkdir(parents=True)
            with mock.patch.object(continuation, "OWNER", state / "continuation-r2"), \
                 mock.patch.object(continuation.proof, "STATE", state), \
                 mock.patch.object(guard, "check_release", return_value={"passed": True}), \
                 mock.patch.object(guard, "preflight_resume", return_value={"path": "fixture"}), \
                 mock.patch.object(continuation.msvcrt, "locking"), \
                 mock.patch.object(continuation.subprocess, "Popen", return_value=FailedChild()) as popen:
                self.assertEqual(continuation.main(), 23)
            popen.assert_called_once()
            command = popen.call_args.args[0]
            self.assertTrue(any(str(arg).endswith("campaign_runner.py") for arg in command))
            self.assertIn("--adopt", command)
            self.assertIn("r5-a6-b1-time-r1", command)
            self.assertFalse(any("pilot_runner.py" in str(arg) for arg in command))
            lock_path = state / "continuation/owner.lock"
            self.assertTrue(lock_path.is_file())
            record = json.loads((state / "continuation-r2/execution.json").read_text(encoding="utf-8"))
            self.assertEqual(record["state"], "PAUSED_ON_RECORDED_FAILURE_NO_RETRY")
            self.assertEqual(len(record["stages"]), 1)

    def test_unresolved_a6_invocation_cannot_reuse_saved_pass_or_cleanup(self):
        label = "r5-a6-b1-time-r1"
        role = {"role_id": "a6-b1-time", "case_id": "A6"}
        execution = {"label": label, "role_id": role["role_id"], "state": "RUNNING",
                    "runner_exit_code": None}
        with mock.patch.object(runner, "read", return_value=execution), \
             mock.patch.object(runner.a, "validate_invocation"), \
             mock.patch.object(runner.a, "accept") as accept, \
             mock.patch.object(runner, "postprocess") as postprocess, \
             mock.patch.object(runner, "cleanup_duplicates") as cleanup:
            with self.assertRaisesRegex(ValueError, "Invocation unresolved"):
                runner.process_finished(role, label)
        accept.assert_not_called()
        postprocess.assert_not_called()
        cleanup.assert_not_called()

    def test_campaign_core_ast_unchanged_outside_release_and_planner_references(self):
        old_path = R1 / "campaign_runner.py"
        new_path = HERE / "campaign_runner.py"
        old_lines = old_path.read_text(encoding="utf-8").splitlines()
        new_lines = new_path.read_text(encoding="utf-8").splitlines()
        old_functions = {n.name: n for n in ast.parse("\n".join(old_lines)).body if isinstance(n, ast.FunctionDef)}
        new_functions = {n.name: n for n in ast.parse("\n".join(new_lines)).body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(set(old_functions), set(new_functions))
        changed = [name for name in old_functions
                   if ast.dump(old_functions[name], include_attributes=False) !=
                   ast.dump(new_functions[name], include_attributes=False)]
        self.assertEqual(set(changed), {"cleanup_duplicates", "run", "check_release"})

        def source(lines, node):
            return "\n".join(lines[node.lineno - 1:node.end_lineno])

        old_cleanup = source(old_lines, old_functions["cleanup_duplicates"])
        new_cleanup = source(new_lines, new_functions["cleanup_duplicates"])
        self.assertEqual(new_cleanup.replace(
            "module(REVISION/'cleanup_plan.py','_serial_cleanup_plan_r2')",
            "module(HERE/'cleanup_plan.py','_serial_cleanup_plan')"), old_cleanup)
        old_run = source(old_lines, old_functions["run"])
        new_run = source(new_lines, new_functions["run"])
        self.assertEqual(new_run.replace("'Adopted role did not pass; keep downstream queue paused'",
                                         "'Recovered A1 did not pass; keep downstream queue paused'"), old_run)
        old_release = source(old_lines, old_functions["check_release"])
        new_release = source(new_lines, new_functions["check_release"])
        self.assertEqual(new_release.replace("    release_guard.check_release()\n", "", 1), old_release)


if __name__ == "__main__":
    unittest.main()
