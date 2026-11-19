"""Isolated regression checks for the one-run recovery controller."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proof = load("_recovery_integration_proof", HERE / "recovery_proof.py")
runner = load("_recovery_integration_campaign_runner", HERE / "campaign_runner.py")
continuation = load("_recovery_integration_continue", HERE / "continue.py")


class RecoveryIntegrationTests(unittest.TestCase):
    def test_proof_accepts_only_exact_original_path_and_unchanged_record(self):
        record = proof.read(proof.EXECUTION_PATH)
        self.assertIsNone(record["runner_exit_code"])
        self.assertIsNone(record.get("ssh_exit_code"))
        accepted = proof.verify_execution(proof.EXECUTION_PATH, record)
        self.assertFalse(accepted["original_execution_contract_passed"])
        self.assertIsNone(accepted["original_runner_exit_code"])
        self.assertIsNone(accepted["original_ssh_exit_code"])
        self.assertFalse(accepted["engineering_marker_present"])

        changed = dict(record, state="RUNNER_EXITED", runner_exit_code=0)
        with self.assertRaisesRegex(ValueError, "Original invocation bytes or supplied record changed"):
            proof.verify_execution(proof.EXECUTION_PATH, changed)
        with tempfile.TemporaryDirectory() as temp:
            wrong_path = Path(temp) / "execution.json"
            wrong_path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Recovery is not authorized for this execution path"):
                proof.verify_execution(wrong_path, record)
            with self.assertRaisesRegex(ValueError, "outside the exact allowlist"):
                proof.verify(Path(temp))

    def test_finished_original_without_run_id_uses_allowlisted_run_and_stops_on_failed_acceptance(self):
        original = {
            "label": proof.LABEL,
            "role_id": "a1-b1-time",
            "state": "RUNNING",
            "runner_exit_code": None,
            "ssh_exit_code": None,
        }
        self.assertNotIn("run_id", original)
        role = {"role_id": "a1-b1-time", "case_id": "A1", "requires": []}
        with tempfile.TemporaryDirectory() as temp:
            runner.STATE = Path(temp) / "state"
            audit = Path(temp) / "mock-audit.json"
            with mock.patch.object(runner, "read", return_value=original), \
                 mock.patch.object(runner.a, "validate_invocation"), \
                 mock.patch.object(runner.proof, "verify_execution"), \
                 mock.patch.object(runner, "postprocess", return_value=audit) as postprocess, \
                 mock.patch.object(runner, "update") as update, \
                 mock.patch.object(runner, "call") as dispatch, \
                 mock.patch.object(runner.a, "accept", return_value={"passed": False}) as accept, \
                 mock.patch.object(runner, "budget") as budget:
                self.assertFalse(runner.process_finished(role, proof.LABEL))
            postprocess.assert_called_once_with(proof.LABEL, proof.RUN_FOLDER)
            accept.assert_called_once_with(role["role_id"], proof.LABEL, audit)
            update.assert_called_once()
            dispatch.assert_not_called()
            budget.assert_called_once_with()

    def test_failed_two_dimensional_child_never_starts_pilot_child(self):
        class FailedChild:
            pid = 424242

            @staticmethod
            def wait():
                return 17

        with tempfile.TemporaryDirectory() as temp:
            continuation.OWNER = Path(temp) / "continuation"
            with mock.patch.object(continuation.proof, "check_release", return_value={"passed": True}), \
                 mock.patch.object(continuation.proof, "verify", return_value={"passed": True}), \
                 mock.patch.object(continuation.msvcrt, "locking"), \
                 mock.patch.object(continuation.subprocess, "Popen", return_value=FailedChild()) as popen:
                self.assertEqual(continuation.main(), 17)
            popen.assert_called_once()
            argv = popen.call_args.args[0]
            self.assertTrue(any(str(arg).endswith("campaign_runner.py") for arg in argv))
            record = json.loads((continuation.OWNER / "execution.json").read_text(encoding="utf-8"))
            self.assertEqual(record["state"], "PAUSED_ON_RECORDED_FAILURE_NO_RETRY")
            self.assertEqual(len(record["stages"]), 1)
            self.assertEqual(record["stages"][0]["name"], "two-dimensional")
            self.assertEqual(record["stages"][0]["exit_code"], 17)


if __name__ == "__main__":
    unittest.main()
