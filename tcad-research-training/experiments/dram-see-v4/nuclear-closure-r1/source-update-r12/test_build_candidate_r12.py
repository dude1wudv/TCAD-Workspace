"""Isolated dispatch guards and deterministic preparation; no native launches."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_candidate_r12 as b


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tmp = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.here = self.tmp / "candidate"
        self.runtime = self.tmp / "runtime"
        self.here.mkdir(); self.runtime.mkdir()
        for key, value in (("ROOT", self.tmp), ("RT", self.runtime)):
            self.stack.enter_context(patch.object(b.c, key, value))
        self.stack.enter_context(patch.object(b, "HERE", self.here))
        self.stack.enter_context(patch.object(b.s, "operation", side_effect=AssertionError("No launch in tests")))
        b.c.write(self.runtime / "active-entry.json", dict(execution_enabled=False, execution_mode="READ_ONLY_HOLD"))
        for name in b.SOURCE_NAMES + ("build_candidate_r12.py",):
            (self.here / name).write_text("fixture " + name)
        self.value = dict(scope="engineering_build_only", execution_enabled=True,
                          tcad_execution_enabled=False,
                          production_hold=b.c.ref(self.runtime / "active-entry.json"),
                          files=[b.c.ref(self.here / name) for name in b.SOURCE_NAMES + ("build_candidate_r12.py",)])

    def save(self):
        b.c.write(self.here / "release-build-only.json", self.value, exclusive=False)

    def test_only_complete_build_release_is_accepted(self):
        self.save()
        self.assertEqual(b.release(), b.c.ref(self.here / "release-build-only.json"))

    def test_solver_permission_or_wrong_scope_rejected(self):
        for key, wrong in (("tcad_execution_enabled", True), ("execution_enabled", False),
                           ("scope", "device")):
            with self.subTest(key=key):
                old = self.value[key]; self.value[key] = wrong; self.save()
                with self.assertRaises(ValueError): b.release()
                self.value[key] = old

    def test_changed_hold_and_source_are_rejected(self):
        self.save()
        (self.runtime / "active-entry.json").write_text('{"execution_enabled":true}')
        with self.assertRaises(ValueError): b.release()
        self.value["production_hold"] = b.c.ref(self.runtime / "active-entry.json")
        self.save()
        (self.here / b.SOURCE_NAMES[0]).write_text("modified")
        with self.assertRaises(ValueError): b.release()

    def test_unbound_source_rejected(self):
        self.value["files"].pop(); self.save()
        with self.assertRaises(ValueError): b.release()

    def test_matching_hash_cannot_enable_production(self):
        (self.runtime / "active-entry.json").write_text('{"execution_enabled":true,"execution_mode":"RUN"}')
        self.value["production_hold"] = b.c.ref(self.runtime / "active-entry.json")
        self.save()
        with self.assertRaises(ValueError): b.release()

    def test_any_existing_attempt_or_operation_blocks_redispatch(self):
        attempt, operation = self.tmp / "attempt.json", self.tmp / "operation"
        b.assert_fresh(attempt, operation)
        for state in ("RESERVED", "RUNNING", "FAILED_OR_UNKNOWN", "EXECUTED"):
            attempt.write_text(json.dumps(dict(state=state, exit_code=None)))
            with self.subTest(state=state), self.assertRaises(ValueError):
                b.assert_fresh(attempt, operation)
        attempt.unlink()  # isolated TemporaryDirectory fixture only
        operation.mkdir()
        with self.assertRaises(ValueError): b.assert_fresh(attempt, operation)


class PreparationTests(unittest.TestCase):
    def test_child_exit_does_not_hide_unknown_remote_state(self):
        a = dict(state="EXECUTED", exit_code=0, finished_utc="fixture")
        op = dict(state="COLLECTED_PENDING_AUDIT", ssh_exit_code=0,
                  remote_exit_code=0, collection_exit_code=0, archive_sha256="fixture")
        self.assertEqual(b.operation_end_state(a, op), "READ_ONLY_HOLD")
        for field in ("ssh_exit_code", "remote_exit_code", "collection_exit_code"):
            with self.subTest(field=field):
                self.assertEqual(b.operation_end_state(a, {**op, field: None}), "RECOVERY_REQUIRED")
        self.assertEqual(b.operation_end_state({**a, "state": "RUNNING"}, op), "RECOVERY_REQUIRED")
        self.assertEqual(b.operation_end_state(a, {}), "RECOVERY_REQUIRED")
        self.assertEqual(b.operation_end_state(a, {**op, "collection_exit_code": 1}), "RECOVERY_REQUIRED")

    def test_original_namespace_is_byte_identical(self):
        identity = b.c.read(b.HERE / "source-identity.json")
        original = b.c.check_ref(identity["original"]).read_bytes()
        copied = b.c.check_ref(identity["candidate"]).read_bytes()
        lo, hi = identity["original_namespace_byte_range"]
        namespace = original[lo:hi]
        self.assertEqual(hashlib.sha256(namespace).hexdigest(), identity["namespace_sha256"])
        self.assertEqual(copied.count(namespace), 1)

    def test_package_deterministic_and_original_oracles_bound(self):
        with patch.object(b, "release", return_value={"path": "isolated-release", "sha256": "0"*64}), \
             patch.object(b.s, "operation", side_effect=AssertionError("No native dispatch")):
            first, vectors = b.package()
            second, _ = b.package()
        self.assertEqual(first, second)
        self.assertEqual([v["name"] for v in vectors["vectors"]],
                         ["zero", "point", "line", "zero_chord_delayed", "tail", "subdivided"])
        task = first["task.sh"].decode()
        self.assertNotRegex(task, r"(?mi)^\s*(?:[^\n ]*/)?(?:sdevice|svisual|snmesh|sde)(?:\s|$)")
        self.assertIn('"$CMI" -O -v pmi_nuclear_qy_r12.C', task)
        self.assertIn("./context_test > context-result.json", task)
        self.assertEqual(task.count("./source_probe probes/"), 6)
        expected = dict(line.split("  ", 1)[::-1]
                        for line in first["expected-sha256.txt"].decode().splitlines())
        for name, raw in first.items():
            if name in ("expected-sha256.txt", "task.sh"): continue
            self.assertEqual(expected[name], hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
