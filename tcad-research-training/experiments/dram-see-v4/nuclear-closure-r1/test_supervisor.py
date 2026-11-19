"""Isolated scheduler checks. No real paths, SSH, operations, or child processes."""
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VALIDATION_DEV = ROOT / "local_runtime/dram-see-v4/nuclear-closure-r1/validation-dev"
sys.path.insert(0, str(HERE))
import common as c
import supervisor as s
import transport as t


def sandbox(test):
    temp = tempfile.TemporaryDirectory(prefix="supervisor-", dir=VALIDATION_DEV)
    test.addCleanup(temp.cleanup)
    root = Path(temp.name) / "root"
    root.mkdir()
    rt = root / "local_runtime/dram-see-v4/nuclear-closure-r1"
    old = root / "local_runtime/dram-see-v4/transport-probe"
    here = root / "experiments/dram-see-v4/nuclear-closure-r1"
    for path in (rt, old, here, root / "experiments/dram-see-v4/source-interface-3d-r1"):
        path.mkdir(parents=True, exist_ok=True)
    stack = ExitStack()
    test.addCleanup(stack.close)
    for name, value in (("ROOT", root), ("RT", rt), ("OLD_OPS", old),
                        ("HERE", here), ("GEOMETRY", root / "experiments/dram-see-v4/source-interface-3d-r1/geometry-contract.json")):
        stack.enter_context(mock.patch.object(c, name, value))
    stack.enter_context(mock.patch.object(s, "OWNER_LOCK", rt / "isolated-owner.lock"))
    return root, rt, old, here, stack


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def limits():
    return {"budgets": {"transport_primary_calls": 107, "transport_corrective_calls": 2,
                        "transport_unique_primaries": 1000008, "transport_replay_primaries": 20000,
                        "tcad_total": 18, "tcad_corrective": 4},
            "old_plan": {"status": "SUPERSEDED_PARTIAL"}}


class SupervisorIsolationTests(unittest.TestCase):
    def test_owner_lock_acquires_and_releases_only_an_explicit_temporary_path(self):
        with tempfile.TemporaryDirectory(prefix="lock-", dir=VALIDATION_DEV) as temp:
            lock = Path(temp) / "owner.lock"
            fake = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=mock.Mock())
            with mock.patch.object(s.sys, "platform", "win32"), \
                 mock.patch.dict(sys.modules, {"msvcrt": fake}):
                with s.ownership(lock):
                    self.assertTrue(lock.is_file())
            self.assertEqual([call.args[1] for call in fake.locking.call_args_list], [1, 2])
            supervisor_source = (HERE / "supervisor.py").read_text(encoding="utf-8")
            continue_source = (HERE / "continue.py").read_text(encoding="utf-8")
            self.assertIn("OWNER_LOCK=c.ROOT/'local_runtime/dram-see-v4/interface-completion-r1/recovery-20261014/continuation/owner.lock'", supervisor_source)
            self.assertIn("with s.ownership():", continue_source)

    def test_existing_unknown_or_failed_attempt_is_never_resent(self):
        root, rt, old, _, stack = sandbox(self)
        stack.enter_context(mock.patch.object(c, "contract", return_value=limits()))
        inputs = root / "inputs/request"
        inputs.mkdir(parents=True)
        (inputs / "request.json").write_text("{}", encoding="utf-8")
        label = "nc-r1-h-000"
        write_json(rt / "attempts" / f"{label}.json", {"label": label, "kind": "transport", "request": {"label": label}})
        operation = old / "operations" / label / "operation.json"
        write_json(operation, {"state": "RUNNING", "ssh_exit_code": None,
                               "remote_exit_code": None, "collection_exit_code": None})
        with mock.patch.object(s, "preflight") as preflight, \
             mock.patch.object(s.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "Prior attempt unknown/failed"):
                s.operation(label, inputs, "transport", {"label": label})
        preflight.assert_not_called()
        popen.assert_not_called()
        self.assertEqual(json.loads(operation.read_text(encoding="utf-8"))["state"], "RUNNING")

    def test_reserved_attempt_without_original_receipt_is_not_resent(self):
        root, rt, old, _, stack = sandbox(self)
        inputs = root / "inputs/request"
        inputs.mkdir(parents=True)
        label = "nc-r1-h-001"
        write_json(rt / "attempts" / f"{label}.json", {"label": label, "kind": "transport", "request": None})
        with mock.patch.object(s, "preflight") as preflight, \
             mock.patch.object(s.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "Reserved attempt has no original receipt"):
                s.operation(label, inputs, "transport")
        preflight.assert_not_called()
        popen.assert_not_called()
        self.assertFalse((old / "operations" / label).exists())

    def test_failed_mock_child_remains_conservatively_reserved_and_cannot_retry(self):
        root, rt, old, _, stack = sandbox(self)
        stack.enter_context(mock.patch.object(c, "contract", return_value=limits()))
        request = {"label": "nc-r1-h-mock-failure", "event_count": 1000}
        stack.enter_context(mock.patch.object(t, "request", return_value=request))
        stack.enter_context(mock.patch.object(s, "preflight", return_value={"path": "fixture"}))
        budget = mock.Mock(return_value={"schema": "fixture-budget", "transport_normal_calls": 0,
            "transport_unique_primaries_requested": 0})
        stack.enter_context(mock.patch.object(s, "budget", budget))
        class Child:
            pid = 777001
            @staticmethod
            def wait(): return 42
        popen = mock.Mock(return_value=Child())
        stack.enter_context(mock.patch.object(s.subprocess, "Popen", popen))
        stack.enter_context(mock.patch.object(s, "update_status"))
        inputs = root / "inputs/request"
        inputs.mkdir(parents=True)
        (inputs / "input.txt").write_text("fixture only", encoding="utf-8")
        label = "nc-r1-h-mock-failure"
        with self.assertRaisesRegex(ValueError, "Operation failed or unknown"):
            s.operation(label, inputs, "transport", request)
        attempt = json.loads((rt / "attempts" / f"{label}.json").read_text(encoding="utf-8"))
        self.assertEqual(attempt["state"], "FAILED_OR_UNKNOWN")
        self.assertEqual(attempt["exit_code"], 42)
        self.assertEqual(attempt["request"]["event_count"], 1000)
        self.assertEqual(popen.call_count, 1)
        with self.assertRaisesRegex(ValueError, "Reserved attempt has no original receipt"):
            s.operation(label, inputs, "transport", attempt["request"])
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(budget.call_count, 3)
        self.assertFalse((old / "operations" / label / "operation.json").exists())

    def test_budget_counts_failed_and_unknown_reservations_without_deduplicating_replays(self):
        _, rt, old, _, stack = sandbox(self)
        stack.enter_context(mock.patch.object(c, "contract", return_value=limits()))
        rows = [
            {"label": "primary-a", "kind": "transport", "request": {"label": "a", "event_count": 1000}, "state": "FAILED_OR_UNKNOWN"},
            {"label": "primary-b", "kind": "transport", "request": {"label": "b", "event_count": 9000}, "state": "RUNNING"},
            {"label": "primary-c", "kind": "transport", "request": {"label": "c", "event_count": 990008}, "state": "RESERVED"},
            {"label": "replay-a", "kind": "transport", "request": {"label": "a", "event_count": 10000}, "corrective": True, "state": "FAILED_OR_UNKNOWN"},
            {"label": "replay-b", "kind": "transport", "request": {"label": "b", "event_count": 10000}, "corrective": True, "state": "EXECUTED"},
            {"label": "tcad-primary", "kind": "tcad", "request": None, "state": "RESERVED"},
            {"label": "tcad-correction", "kind": "tcad", "request": None, "corrective": True, "state": "FAILED_OR_UNKNOWN"},
        ]
        for row in rows:
            write_json(rt / "attempts" / (row["label"] + ".json"), row)
        result = s.budget()
        self.assertEqual(result["transport_normal_calls"], 3)
        self.assertEqual(result["transport_corrective_calls"], 2)
        self.assertEqual(result["transport_unique_primaries_requested"], 1000008)
        self.assertEqual(result["transport_replay_primaries"], 20000)
        self.assertEqual(result["tcad_calls"], 2)
        self.assertEqual(result["tcad_corrective_calls"], 1)
        self.assertEqual(result["reservations"], len(rows))
        self.assertFalse(list((old / "operations").glob("nc-r1-*/operation.json")))


if __name__ == "__main__":
    unittest.main()
