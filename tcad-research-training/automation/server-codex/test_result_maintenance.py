"""Offline checks for the handoff and frozen-reader storage compatibility."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("result_maintenance_tested", HERE / "result_maintenance.py")
maintenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maintenance)


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.folder = self.root / "runs/run-1"
        self.folder.mkdir(parents=True)
        self.manifest = {
            "run_id": "run-1", "state": "COLLECTED", "remote_exit_code": 0,
            "collection_verified": True, "parallel_slot_released": True,
            "results_sha256": "a" * 64,
        }
        self.save(self.folder / "manifest.json", self.manifest)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.evidence = self.cache / "extraction.json"
        self.save(self.evidence, {
            "synthetic": False, "provenance": {
                "run_id": "run-1", "archive_sha256": self.manifest["results_sha256"],
                "manifest_sha256": maintenance.sha(self.folder / "manifest.json"),
            },
        })
        self.save(self.cache / "receipt.json", {"extraction_sha256": maintenance.sha(self.evidence)})

    @staticmethod
    def save(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_ready_binds_original_and_keeps_scientific_scope(self):
        marker = maintenance.ready(self.folder, self.evidence)
        self.assertFalse(marker["is_scientific_acceptance"])
        self.assertEqual(marker["run_id"], "run-1")
        self.assertEqual(maintenance.ready(self.folder, self.evidence), marker)
        self.evidence.write_text("changed", encoding="utf-8")
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            maintenance.ready(self.folder, self.evidence)

    def test_unreleased_and_other_run_evidence_cannot_authorize_cleanup(self):
        self.manifest["parallel_slot_released"] = False
        self.save(self.folder / "manifest.json", self.manifest)
        with self.assertRaises(ValueError):
            maintenance.ready(self.folder, self.evidence)
        self.manifest["parallel_slot_released"] = True
        self.save(self.folder / "manifest.json", self.manifest)
        self.save(self.evidence, {"synthetic": False, "provenance": {"run_id": "other"}})
        with self.assertRaises(ValueError):
            maintenance.ready(self.folder, self.evidence)
        self.assertFalse((self.folder / "retention-ready.json").exists())

    def test_wrapper_restores_original_and_reclaims_even_if_reader_refuses(self):
        reader = self.root / "multicore-response-reader-r1/extract.py"
        reader.parent.mkdir()
        reader.write_text("# frozen fixture", encoding="utf-8")

        class Retained:
            def __init__(self):
                self.calls = []

            def restore(self, folder):
                self.calls.append(("restore", folder))
                (folder / "results.tar").write_bytes(b"exact original")

            def dematerialize(self, folder):
                self.calls.append(("dematerialize", folder))
                (folder / "results.tar").unlink()

        module = Retained()
        def reader_call(*unused, **kwargs):
            # Maintenance cannot remove the pathname while the frozen reader
            # is running, even though restore's inner lock has been released.
            with self.assertRaises(OSError):
                with maintenance.transaction(self.folder, blocking=False):
                    self.fail("Storage worker entered an active reader transaction")
            class Result:
                returncode = 2
            return Result()

        with patch.object(maintenance, "retention", return_value=module), \
                patch.object(maintenance.subprocess, "run", side_effect=reader_call):
            self.assertEqual(maintenance.read_with_original(reader, ["extract", str(self.folder), "inputs"]), 2)
        self.assertEqual([kind for kind, _ in module.calls], ["restore", "dematerialize"])
        self.assertFalse((self.folder / "results.tar").exists())

    def test_busy_consumer_prevents_all_maintenance_mutations(self):
        with maintenance.transaction(self.folder), \
                patch.object(maintenance, "_maintain") as mutate:
            with self.assertRaises(OSError):
                maintenance.maintain(self.folder, "unused-profile")
            mutate.assert_not_called()

    def test_incomplete_review_cannot_retire_lossless_backup(self):
        proof = self.root / "review.json"
        self.save(proof, {"schema": "tcad-result-retention-release-v1", "scientific_review_complete": False})
        with patch.object(maintenance, "retention") as factory:
            factory.return_value.verify_retained.return_value = True
            with self.assertRaises(ValueError):
                maintenance.finalize(self.folder, proof)
        self.assertFalse((self.folder / "raw-backup-release.json").exists())

    def test_completed_review_can_keep_only_verified_key_data(self):
        raw = self.folder / "results.tar"
        with tarfile.open(raw, "w") as archive:
            payload = b"t,V\n0,1\n1,0\n"
            entry = tarfile.TarInfo("numerics.plt")
            entry.size = len(payload)
            archive.addfile(entry, io.BytesIO(payload))
        self.manifest["results_sha256"] = maintenance.sha(raw)
        self.manifest["collected_bytes"] = raw.stat().st_size
        self.save(self.folder / "manifest.json", self.manifest)
        manifest_bytes = (self.folder / "manifest.json").read_bytes()
        module = maintenance.retention()
        module.compact(self.folder)
        kept = self.root / "readpoint.json"
        self.save(kept, {"fixture": True, "exact_comparison_saved": True})
        proof = self.root / "release.json"
        self.save(proof, {
            "schema": "tcad-result-retention-release-v1", "run_id": self.folder.name,
            "original_archive_sha256": self.manifest["results_sha256"],
            "manifest_sha256": maintenance.sha(self.folder / "manifest.json"),
            "scientific_review_complete": True, "release_original_archive": True,
            "key_evidence": [{"path": str(kept), "sha256": maintenance.sha(kept)}],
        })
        self.assertTrue(maintenance.finalize(self.folder, proof)["key_data_only"])
        self.assertFalse((self.folder / "results.raw.tar.gz").exists())
        self.assertTrue((self.folder / "results.essential.tar.gz").is_file())
        self.assertTrue(module.verify_retained(self.folder, self.manifest))
        self.assertEqual((self.folder / "manifest.json").read_bytes(), manifest_bytes)
        with self.assertRaises(ValueError):
            module.restore(self.folder)


if __name__ == "__main__":
    unittest.main()
