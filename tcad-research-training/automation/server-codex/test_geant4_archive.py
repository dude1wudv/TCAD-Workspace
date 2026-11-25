"""Offline regression tests for the Geant4 cold-archive receipt contract."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from geant4_archive import RECEIPT, verify_cold


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2) + "\n").encode("utf-8"))


class VerifyColdTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        operation_dir = self.root / "geant4-fixture-a"
        operation_dir.mkdir()
        self.operation_path = operation_dir / "operation.json"
        self.receipt_path = operation_dir / "transport-archive-offload.json"
        # Only the two JSON files remain locally after offload.
        steps = b"event_id,step_id\n0,1\n"
        raw = b"fixture archive containing the step table\n" + steps
        self.record = {
            "schema": "dram-see-v4-transport-operation-v2",
            "label": operation_dir.name,
            "origin": "native_pipeline",
            "synthetic": False,
            "state": "COLLECTED_PENDING_AUDIT",
            "collection_verified": True,
            "parallel_slot_released": True,
            "remote_exit_code": 0,
            "operation_task_exit_code": 0,
            "collection_exit_code": 0,
            "archive_sha256": hashlib.sha256(raw).hexdigest(),
            "collected_bytes": len(raw),
        }
        self.receipt = {
            "schema": "tcad-geant4-cold-archive-v1",
            "run_id": operation_dir.name,
            "archive_sha256": self.record["archive_sha256"],
            "archive_bytes": self.record["collected_bytes"],
            "raw": {
                "file_id": "fixture-drive-file-a",
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "md5": hashlib.md5(raw).hexdigest(),
            },
            "steps": {"bytes": len(steps), "sha256": hashlib.sha256(steps).hexdigest()},
            "primary_ledger_sha256": hashlib.sha256(b"event_id\n0\n").hexdigest(),
            "cloud_verified": True,
        }
        self.write_bound_receipt(self.record)

    def write_bound_receipt(self, record):
        write_json(self.operation_path, record)
        write_json(self.receipt_path, dict(
            self.receipt,
            operation_sha256=hashlib.sha256(self.operation_path.read_bytes()).hexdigest(),
        ))

    def test_accepts_verified_receipt_with_no_local_archive(self):
        self.assertEqual(RECEIPT, self.receipt_path.name)
        self.assertIs(verify_cold(self.operation_path, self.record), True)

    def test_rejects_changed_operation_bytes_even_when_json_is_unchanged(self):
        self.operation_path.write_bytes(self.operation_path.read_bytes() + b"\n")
        self.assertIs(verify_cold(self.operation_path, self.record), False)

    def test_rejects_ineligible_operation_even_with_matching_digest(self):
        for field, value in (
            ("parallel_slot_released", False),
            ("collection_verified", False),
            ("remote_exit_code", 1),
            ("operation_task_exit_code", 1),
            ("collection_exit_code", 1),
            ("state", "FAILED_COLLECTED"),
            ("schema", "dram-see-v4-transport-operation-v1"),
            ("origin", "fixture"),
            ("synthetic", True),
        ):
            with self.subTest(field=field):
                record = dict(self.record, **{field: value})
                self.write_bound_receipt(record)
                self.assertIs(verify_cold(self.operation_path, record), False)

    def test_rejects_tampered_receipt_fields(self):
        receipt = json.loads(self.receipt_path.read_bytes())
        wrong_sha256 = hashlib.sha256(b"different archive").hexdigest()
        for section, field, value in (
            (None, "schema", "unknown-schema"),
            (None, "cloud_verified", False),
            (None, "archive_sha256", wrong_sha256),
            (None, "archive_bytes", self.record["collected_bytes"] + 1),
            ("raw", "file_id", ""),
            ("raw", "bytes", 0),
            ("raw", "sha256", "invalid-sha256"),
            ("raw", "md5", "invalid-md5"),
            ("steps", "bytes", 0),
            ("steps", "sha256", "invalid-sha256"),
            (None, "primary_ledger_sha256", "invalid-sha256"),
        ):
            with self.subTest(section=section, field=field):
                changed = copy.deepcopy(receipt)
                fields = changed[section] if section else changed
                fields[field] = value
                write_json(self.receipt_path, changed)
                self.assertIs(verify_cold(self.operation_path, self.record), False)

    def test_rejects_missing_receipt(self):
        self.receipt_path.unlink()
        self.assertIs(verify_cold(self.operation_path, self.record), False)

    def test_rejects_receipt_missing_primary_ledger_digest(self):
        del self.receipt["primary_ledger_sha256"]
        self.write_bound_receipt(self.record)
        self.assertIs(verify_cold(self.operation_path, self.record), False)

    def test_rejects_missing_original_operation(self):
        self.operation_path.unlink()
        self.assertIs(verify_cold(self.operation_path, self.record), False)

    def test_rejects_receipt_from_another_run_even_with_matching_digest(self):
        self.receipt["run_id"] = "geant4-fixture-b"
        self.write_bound_receipt(self.record)
        self.assertIs(verify_cold(self.operation_path, self.record), False)

    def test_rejects_symlink_to_valid_receipt(self):
        target = self.root / "receipt-copy.json"
        self.receipt_path.rename(target)
        try:
            self.receipt_path.symlink_to(target)
        except OSError as exc:
            if sys.platform == "win32" and getattr(exc, "winerror", None) in (5, 50, 1314):
                self.skipTest(f"Windows could not create a test symlink: {exc}")
            raise
        self.assertIs(verify_cold(self.operation_path, self.record), False)


if __name__ == "__main__":
    unittest.main()
