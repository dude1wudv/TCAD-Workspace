"""Isolated continuation phase/recovery tests; every mutable path is temporary."""
from contextlib import ExitStack, nullcontext
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VALIDATION_DEV = ROOT / "local_runtime/dram-see-v4/nuclear-closure-r1/validation-dev"
sys.path.insert(0, str(HERE))
import common as c
import supervisor as s
import transport as t

_spec = __import__("importlib.util", fromlist=["spec_from_file_location"])
continue_module = _spec.module_from_spec(_spec.spec_from_file_location("_nc_continue_validation", HERE / "continue.py"))
_spec.spec_from_file_location("_nc_continue_validation", HERE / "continue.py").loader.exec_module(continue_module)


def sandbox(test, prefix="continue-"):
    temp = tempfile.TemporaryDirectory(prefix=prefix, dir=VALIDATION_DEV)
    test.addCleanup(temp.cleanup)
    root = Path(temp.name) / "root"
    root.mkdir()
    rt = root / "local_runtime/dram-see-v4/nuclear-closure-r1"
    old = root / "local_runtime/dram-see-v4/transport-probe"
    here = root / "experiments/dram-see-v4/nuclear-closure-r1"
    geometry = root / "experiments/dram-see-v4/source-interface-3d-r1/geometry-contract.json"
    for path in (rt, old, here, geometry.parent):
        path.mkdir(parents=True, exist_ok=True)
    stack = ExitStack()
    test.addCleanup(stack.close)
    for module in (c,):
        for name, value in (("ROOT", root), ("RT", rt), ("OLD_OPS", old),
                            ("HERE", here), ("GEOMETRY", geometry)):
            stack.enter_context(mock.patch.object(module, name, value))
    stack.enter_context(mock.patch.object(s, "OWNER_LOCK", rt / "isolated-owner.lock"))
    return root, rt, old, here, stack


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_contract():
    return {"budgets": {
        "transport_primary_calls": 107, "transport_corrective_calls": 2,
        "transport_unique_primaries": 1000008, "transport_replay_primaries": 20000,
        "tcad_total": 18, "tcad_corrective": 4,
        "minimum_local_free_GiB": 0, "minimum_remote_free_GiB": 0,
        "minimum_remote_available_memory_GiB": 0, "storage_GiB": 10,
    }, "old_plan": {"status": "SUPERSEDED_PARTIAL"},
     "transport": {"stage_order": ["P0", "N1"]}}


def setup_transport_stage(test, rows, stage="P0"):
    root, rt, old, here, stack = sandbox(test)
    stack.enter_context(mock.patch.object(c, "contract", return_value=test_contract()))
    release_check = mock.Mock()
    stack.enter_context(mock.patch.object(c, "check_release", release_check))
    test.release_check = release_check
    stack.enter_context(mock.patch.object(t, "contract", return_value={"requests": rows}))
    build = old / "operations" / t.BUILD_LABEL
    build.mkdir(parents=True)
    stack.enter_context(mock.patch.object(t, "assert_operation_complete"))
    compile_inputs = old / "inputs" / t.BUILD_LABEL
    compile_inputs.mkdir(parents=True, exist_ok=True)
    stack.enter_context(mock.patch.object(t, "compile_inputs", return_value=compile_inputs))
    stack.enter_context(mock.patch.object(t, "prepare", side_effect=lambda label, b: old / "inputs" / label))
    return root, rt, old, here, stack, build


class ContinueStageTests(unittest.TestCase):
    def test_started_stage_finishes_every_request_before_witness_selection(self):
        rows = [
            {"label": "req-a", "closure_stage": "P0", "mode": "init", "arm": "H", "event_count": 1},
            {"label": "req-b", "closure_stage": "P0", "mode": "init", "arm": "E", "event_count": 1},
        ]
        root, rt, old, _, stack, build = setup_transport_stage(self, rows)
        completed = []
        def operation(label, inputs, kind, request=None, timeout=172800):
            if kind == "compile":
                self.release_check.assert_called_once_with("transport")
                return build
            self.assertGreaterEqual(self.release_check.call_count, 2)
            self.assertEqual(kind, "transport")
            self.assertEqual(request["label"], label)
            return old / "operations" / label
        def audit(label):
            completed.append(label)
            path = rt / "transport/audits" / label / "audit.json"
            write_json(path, {"passed": True})
            return {"passed": True}
        def choose(stage):
            self.assertEqual(stage, "P0")
            self.assertEqual(completed, ["req-a", "req-b"])
            self.assertFalse((rt / "transport/stages/P0.json").exists())
            path = rt / "transport/runs/fixture/record.json"
            write_json(path, {"fixture": True})
            return {"record": c.ref(path), "witness": {"event_id": 7}}
        stack.enter_context(mock.patch.object(s, "operation", side_effect=operation))
        stack.enter_context(mock.patch.object(s, "update_status"))
        stack.enter_context(mock.patch.object(t, "collect"))
        stack.enter_context(mock.patch.object(t, "audit", side_effect=audit))
        stack.enter_context(mock.patch.object(t, "choose", side_effect=choose))
        self.assertTrue(continue_module.transport_stage())
        stage = json.loads((rt / "transport/stages/P0.json").read_text(encoding="utf-8"))
        self.assertTrue(stage["passed"])
        self.assertTrue(stage["qualifying_event_found"])
        self.assertTrue((rt / "selected-event.json").is_file())
        self.assertFalse((rt / "transport/sampling-window.json").exists(), "P0 must not start the 48h sampling clock")

    def test_written_stage_without_selected_event_reproduces_selection_after_crash(self):
        rows = [{"label": "req-a", "closure_stage": "P0", "mode": "init", "arm": "H", "event_count": 1}]
        _, rt, old, _, stack, build = setup_transport_stage(self, rows)
        audit_path = write_json(rt / "transport/audits/req-a/audit.json", {"passed": True})
        write_json(rt / "transport/stages/P0.json", {"stage": "P0", "passed": True,
            "qualifying_event_found": True, "audits": [c.ref(audit_path)]})
        selected_record = write_json(rt / "transport/runs/fixture/record.json", {"fixture": "recovered"})
        chosen = {"record": c.ref(selected_record), "event_id": 5}
        stack.enter_context(mock.patch.object(s, "operation", return_value=build))
        stack.enter_context(mock.patch.object(s, "update_status"))
        chooser = mock.Mock(return_value=chosen)
        stack.enter_context(mock.patch.object(t, "choose", chooser))
        with mock.patch.object(t, "prepare") as prepare, mock.patch.object(t, "collect") as collect:
            self.assertTrue(continue_module.transport_stage())
        self.release_check.assert_called_once_with("transport")
        chooser.assert_called_once_with("P0")
        prepare.assert_not_called()
        collect.assert_not_called()
        self.assertEqual(json.loads((rt / "selected-event.json").read_text(encoding="utf-8")), chosen)

    def test_expired_window_collects_registered_operation_but_blocks_new_request(self):
        rows = [
            {"label": "registered", "closure_stage": "N1", "mode": "events", "arm": "H", "event_count": 11},
            {"label": "not-started", "closure_stage": "N1", "mode": "events", "arm": "H", "event_count": 13},
        ]
        _, rt, old, _, stack, build = setup_transport_stage(self, rows, "N1")
        first_attempt = {"label": "registered", "kind": "transport", "request": rows[0]}
        write_json(rt / "attempts/registered.json", first_attempt)
        receipt = old / "operations/registered/operation.json"
        write_json(receipt, {"state": "COLLECTED_PENDING_AUDIT", "ssh_exit_code": 0,
            "remote_exit_code": 0, "collection_exit_code": 0})
        deadline = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
        write_json(rt / "transport/sampling-window.json", {"deadline_utc": deadline})
        audit_path = rt / "transport/audits/registered/audit.json"
        write_json(audit_path, {"passed": True})
        collect_calls = []
        real_operation = s.operation
        def reconcile(label, inputs, kind, request=None, timeout=172800):
            if kind == "compile":
                return build
            return real_operation(label, inputs, kind, request, timeout)
        stack.enter_context(mock.patch.object(s, "operation", side_effect=reconcile))
        stack.enter_context(mock.patch.object(s, "assert_no_competing_scheduler"))
        stack.enter_context(mock.patch.object(s, "preflight", side_effect=AssertionError("must not preflight a new request")))
        stack.enter_context(mock.patch.object(s, "update_status"))
        stack.enter_context(mock.patch.object(t, "assert_operation_complete"))
        prepare = mock.Mock()
        stack.enter_context(mock.patch.object(t, "prepare", prepare))
        stack.enter_context(mock.patch.object(t, "collect", side_effect=lambda op: collect_calls.append(Path(op))))
        stack.enter_context(mock.patch.object(t, "audit", return_value={"passed": True}))
        self.assertFalse(continue_module.transport_stage())
        self.assertEqual(collect_calls, [old / "operations/registered"])
        prepare.assert_not_called()
        self.assertFalse((rt / "attempts/not-started.json").exists())
        self.assertFalse((rt / "transport/stages/N1.json").exists())

    def _main_fixture(self, source_release=False):
        root, rt, _, here, stack = sandbox(self, "release-")
        stack.enter_context(mock.patch.object(s, "ownership", return_value=nullcontext()))
        stack.enter_context(mock.patch.object(s, "local_processes", return_value=[]))
        stack.enter_context(mock.patch.object(s, "assert_no_competing_scheduler"))
        stack.enter_context(mock.patch.object(s, "budget", return_value={"schema": "fixture-budget"}))
        statuses = []
        stack.enter_context(mock.patch.object(s, "update_status", side_effect=lambda **kw: statuses.append(kw.copy())))
        checks = []
        events = []
        stack.enter_context(mock.patch.object(c, "check_release", side_effect=lambda stage: (checks.append(stage), events.append("release:" + stage), {"stage": stage})[-1]))
        stack.enter_context(mock.patch.object(continue_module, "transport_stage", side_effect=lambda: events.append("transport_stage") or True))
        if source_release:
            (here / "release-source.json").write_text("{}", encoding="utf-8")
        return rt, here, stack, statuses, checks, events

    def test_missing_source_release_waits_without_compilation_or_qualification(self):
        rt, _, stack, statuses, checks, events = self._main_fixture(source_release=False)
        with mock.patch.object(c, "module") as module:
            self.assertEqual(continue_module.main(), 0)
        self.assertEqual(checks, [])
        self.assertEqual(events, ["transport_stage"])
        module.assert_not_called()
        self.assertTrue(any(row.get("state") == "WAITING_SOURCE_RELEASE" and row.get("scientific_passed") is False for row in statuses))
        self.assertTrue((rt / "budget.json").is_file())
        self.assertFalse((rt / "failures").exists())

    def test_source_release_allows_compile_and_qualification_but_missing_device_waits(self):
        rt, here, stack, statuses, checks, events = self._main_fixture(source_release=True)
        pmi = mock.Mock()
        campaign = mock.Mock()
        def module(path, name):
            if Path(path).name == "native_compile.py": return pmi
            if Path(path).name == "campaign.py": return campaign
            raise AssertionError(f"unexpected module import: {path}")
        stack.enter_context(mock.patch.object(c, "module", side_effect=module))
        self.assertEqual(continue_module.main(), 0)
        pmi.ensure_compiled.assert_called_once_with()
        campaign.qualify.assert_called_once_with()
        campaign.run.assert_not_called()
        self.assertFalse((here / "release-device.json").exists())
        self.assertEqual(checks, ["source"])
        self.assertEqual(events, ["transport_stage", "release:source"])
        self.assertTrue(any(row.get("state") == "WAITING_DEVICE_RELEASE" and row.get("scientific_passed") is False for row in statuses))
        self.assertTrue((rt / "budget.json").is_file())
        self.assertFalse((rt / "failures").exists())

    def test_missing_release_waits_clear_stale_positive_scientific_status(self):
        root, rt, old, here, stack = sandbox(self, "stale-status-")
        stack.enter_context(mock.patch.object(s, "ownership", return_value=nullcontext()))
        stack.enter_context(mock.patch.object(s, "local_processes", return_value=[]))
        stack.enter_context(mock.patch.object(s, "assert_no_competing_scheduler"))
        stack.enter_context(mock.patch.object(s, "budget", return_value={"schema": "fixture-budget"}))
        stack.enter_context(mock.patch.object(continue_module, "transport_stage", return_value=True))
        write_json(rt / "status.json", {"schema": "nuclear-closure-status-r1", "scientific_passed": True})
        with mock.patch.object(c, "module") as module:
            self.assertEqual(continue_module.main(), 0)
        source_wait = json.loads((rt / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(source_wait["state"], "WAITING_SOURCE_RELEASE")
        self.assertIs(source_wait.get("scientific_passed"), False)
        module.assert_not_called()

        (here / "release-source.json").write_text("{}", encoding="utf-8")
        pmi = mock.Mock()
        campaign = mock.Mock()
        with mock.patch.object(c, "check_release"), mock.patch.object(c, "module", side_effect=[pmi, campaign]):
            self.assertEqual(continue_module.main(), 0)
        device_wait = json.loads((rt / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(device_wait["state"], "WAITING_DEVICE_RELEASE")
        self.assertIs(device_wait.get("scientific_passed"), False)
        campaign.run.assert_not_called()


class SupervisorReservationTests(unittest.TestCase):
    def test_real_windows_lock_excludes_child_process_and_releases(self):
        root, rt, _, _, stack = sandbox(self, "cross-process-lock-")
        lock_path = rt / "isolated-owner.lock"
        child_code = (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0, {str(HERE)!r}); "
            "import supervisor as s; p=Path(sys.argv[1]); "
            "\ntry:\n with s.ownership(p): pass\n"
            "except RuntimeError:\n print('LOCK_BUSY'); raise SystemExit(23)\n"
            "else:\n print('LOCK_ACQUIRED')"
        )
        with s.ownership(lock_path):
            busy = subprocess.run([sys.executable, "-B", "-c", child_code, str(lock_path)],
                cwd=root, capture_output=True, text=True, timeout=20)
            self.assertEqual(busy.returncode, 23, busy.stdout + busy.stderr)
            self.assertIn("LOCK_BUSY", busy.stdout)
        released = subprocess.run([sys.executable, "-B", "-c", child_code, str(lock_path)],
            cwd=root, capture_output=True, text=True, timeout=20)
        self.assertEqual(released.returncode, 0, released.stdout + released.stderr)
        self.assertIn("LOCK_ACQUIRED", released.stdout)

    def test_transport_budget_exhaustion_precedes_preflight_and_reservation(self):
        root, rt, old, _, stack = sandbox(self, "budget-")
        contract = test_contract()
        contract["budgets"]["transport_unique_primaries"] = 10
        stack.enter_context(mock.patch.object(c, "contract", return_value=contract))
        old_req = {"label": "old", "event_count": 9}
        write_json(rt / "attempts/old.json", {"label": "old", "kind": "transport", "request": old_req, "state": "FAILED_OR_UNKNOWN"})
        inputs = root / "inputs/new"
        inputs.mkdir(parents=True)
        request = {"label": "new", "event_count": 2}
        stack.enter_context(mock.patch.object(t, "request", return_value=request))
        with mock.patch.object(s, "preflight") as preflight, mock.patch.object(s.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "Unique primary allocation exhausted"):
                s.operation("new", inputs, "transport", request)
        preflight.assert_not_called()
        popen.assert_not_called()
        self.assertFalse((rt / "attempts/new.json").exists())
        self.assertFalse((old / "operations/new").exists())

    def test_preflight_records_conditional_transport_output_forecast(self):
        root, rt, _, _, stack = sandbox(self, "forecast-")
        contract = test_contract()
        stack.enter_context(mock.patch.object(c, "contract", return_value=contract))
        record_dir = rt / "transport/runs/fixture"
        record_dir.mkdir(parents=True)
        output = record_dir / "raw.bin"
        output.write_bytes(b"x" * 200)
        write_json(record_dir / "record.json", {"request": {"event_count": 2}, "output_sha256": {"raw.bin": "fixture"}})
        stack.enter_context(mock.patch.object(s, "local_processes", return_value=[]))
        stack.enter_context(mock.patch.object(s, "remote_probe", return_value={"active_solver_lines": [], "values": {
            "FREE_KIB": 10**9, "AVAILABLE_MEMORY_KIB": 10**9, "STAGE_KIB": 0, "LOCK_FREE": 1}}))
        stack.enter_context(mock.patch.object(s, "storage_bytes", return_value=0))
        request = {"label": "next", "event_count": 3}
        s.preflight("next", request)
        evidence = json.loads(next((rt / "preflights").glob("*/evidence.json")).read_text(encoding="utf-8"))
        self.assertEqual(evidence["conditional_transport_output_bytes"], 32 * 1024**2)
        self.assertEqual(evidence["label"], "next")
        self.assertTrue(evidence["budget"]["transport_unique_primaries_requested"] == 0)


if __name__ == "__main__":
    unittest.main()





