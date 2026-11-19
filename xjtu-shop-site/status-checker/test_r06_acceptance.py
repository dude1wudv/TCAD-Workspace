import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research_projection import build_research
from test_r06_projection import NOW, RESULT_HASH, r06_plan, solved


class R06ExternalAcceptanceTests(unittest.TestCase):
    """All evidence here is temporary synthetic test data, never research data."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        self.plan_path = self.workspace / "plans/dram/month-one-cases-r06.json"
        self.plan_path.parent.mkdir(parents=True)
        plan = r06_plan()
        self.case_id = next(case["case_id"] for case in plan["cases"] if case["block"] == "S")
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
        self.original_plan = self.plan_path.read_bytes()
        self.inputs = {"device.cmd": "1" * 64, "mesh/model.tdr": "2" * 64, "source/native.dat": "3" * 64}
        self.manifests = {"private-run": solved("private-run", input_sha256=self.inputs)}
        self.runtime = {"intents": {"private-task": {
            "run_id": "private-run", "scientific_admission": {"case_id": self.case_id},
        }}}
        self.proof = self.plan_path.parent / "r06-gate/results/proof.txt"
        self.proof.parent.mkdir(parents=True)
        self.proof.write_bytes(b"synthetic acceptance test fixture; no scientific conclusion")
        self.record_path = self.plan_path.parent / "r06-gate/results/case-acceptance" / (self.case_id + ".json")
        self.record_path.parent.mkdir()
        self.record = {
            "schema": "tcad-r06-case-acceptance-v1", "status": "accepted",
            "case_id": self.case_id, "run_id": "private-run",
            "input_sha256": dict(self.inputs), "results_sha256": RESULT_HASH,
            "evidence": [{"path": "r06-gate/results/proof.txt",
                          "sha256": hashlib.sha256(self.proof.read_bytes()).hexdigest()}],
        }

    def write_record(self, value=None):
        self.record_path.write_text(json.dumps(self.record if value is None else value), encoding="utf-8")

    def project(self):
        result = build_research(self.plan_path, self.manifests, {}, [], now=NOW, runtime=self.runtime)
        self.assertEqual(self.plan_path.read_bytes(), self.original_plan)
        return result

    def test_native_input_map_accepts_without_changing_any_frozen_plan_bytes_or_flags(self):
        self.write_record()
        original_hash = hashlib.sha256(self.original_plan).hexdigest()
        result = self.project()
        self.assertEqual(result["totals"]["accepted"], 1)
        self.assertEqual(result["totals"]["planned"], 396)
        self.assertEqual(result["counts"]["S"]["accepted"], 1)
        self.assertEqual(result["budget"]["statistics_eligible_cases"], 0)
        self.assertEqual(result["budget"]["manifest_eligible_cases"], 0)
        self.assertEqual(result["statistics_snapshot_status"], "not_connected")
        self.assertTrue(all(not case["statistics_eligible"] for case in result["cases"]))
        frozen = json.loads(self.plan_path.read_text(encoding="utf-8"))
        self.assertTrue(all(case["accepted"] is False for case in frozen["cases"]))
        self.assertEqual(hashlib.sha256(self.plan_path.read_bytes()).hexdigest(), original_hash)
        public = json.dumps(result)
        for private in ("private-run", "private-task", "proof.txt", str(self.workspace),
                        "1" * 64, "2" * 64, "3" * 64, "device.cmd"):
            self.assertNotIn(private, public)

    def test_record_must_match_schema_status_case_and_bound_run(self):
        for field, value in (("schema", "wrong-schema"), ("status", "pending"),
                             ("case_id", "r06-s-another-b1"), ("run_id", "another-run")):
            with self.subTest(field=field):
                record = dict(self.record, **{field: value})
                self.write_record(record)
                self.assertEqual(self.project()["totals"]["accepted"], 0)

    def test_new_revision_uses_declared_gate_and_keeps_original_evidence_checks(self):
        identity = "r07-response-dramx-b1"
        plan = {"schema_version": 1, "revision": "r0.7", "gate_dir": "private-gate/results",
                "cases": [{"case_id": identity, "block": "Response", "run_ids": ["private-run"],
                           "accepted": True}]}
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
        self.original_plan = self.plan_path.read_bytes()
        self.runtime = {"intents": {"task": {"run_id": "private-run", "scientific_admission": {"case_id": identity}}}}
        self.record_path = self.plan_path.parent / "private-gate/results/case-acceptance" / (identity + ".json")
        self.record_path.parent.mkdir(parents=True)
        self.assertEqual(self.project()["totals"]["accepted"], 0)
        record = dict(self.record, schema="tcad-r07-case-acceptance-v1", case_id=identity)
        self.write_record(record)
        self.assertEqual(self.project()["totals"]["accepted"], 1)
        self.write_record(dict(record, results_sha256="0" * 64))
        self.assertEqual(self.project()["totals"]["accepted"], 0)

    def test_input_hash_map_must_be_complete_and_every_value_must_be_64_hex(self):
        for inputs in (None, {}, "1" * 64, {"device.cmd": "1" * 64},
                       dict(self.inputs, **{"extra.cmd": "4" * 64}),
                       dict(self.inputs, **{"device.cmd": "not-a-hash"}),
                       dict(self.inputs, **{"device.cmd": "4" * 64}),
                       dict(self.inputs, **{"device.cmd": None})):
            with self.subTest(inputs=inputs):
                self.write_record(dict(self.record, input_sha256=inputs))
                self.assertEqual(self.project()["totals"]["accepted"], 0)
        record = dict(self.record)
        record.pop("input_sha256")
        self.write_record(record)
        self.assertEqual(self.project()["totals"]["accepted"], 0)

    def test_results_hash_and_nonempty_evidence_are_required(self):
        for change in ({"results_sha256": None}, {"results_sha256": "bad"}, {"results_sha256": "f" * 64},
                       {"evidence": None}, {"evidence": []}, {"evidence": {}},
                       {"evidence": [{}]}, {"evidence": [{"path": "r06-gate/results/proof.txt"}]}):
            with self.subTest(change=change):
                self.write_record(dict(self.record, **change))
                self.assertEqual(self.project()["totals"]["accepted"], 0)
        record = dict(self.record)
        record.pop("evidence")
        self.write_record(record)
        self.assertEqual(self.project()["totals"]["accepted"], 0)

    def test_record_and_evidence_are_size_bounded_and_large_archive_is_not_hashed(self):
        oversized_record = dict(self.record, padding="x" * (1024 * 1024))
        self.write_record(oversized_record)
        with self.assertRaises(ValueError):
            self.project()

        self.write_record()
        archive = self.plan_path.parent / "r06-gate/results/large-results.tar"
        archive.write_bytes(b"archive fixture" + b"\0" * (4 * 1024 * 1024))
        record = copy.deepcopy(self.record)
        record["evidence"] = [{"path": "r06-gate/results/large-results.tar",
                               "sha256": "0" * 64}]
        self.write_record(record)
        with patch("research_projection.hashlib.sha256", side_effect=AssertionError("large file was hashed")):
            with self.assertRaises(ValueError):
                self.project()

    def test_evidence_count_is_bounded(self):
        evidence = [dict(self.record["evidence"][0], path="r06-gate/results/proof.txt") for _ in range(17)]
        self.write_record(dict(self.record, evidence=evidence))
        with self.assertRaises(ValueError):
            self.project()

    def test_nonfinite_constants_and_duplicate_json_keys_are_rejected(self):
        self.record_path.write_text(
            '{"schema":"tcad-r06-case-acceptance-v1","schema":"duplicate"}',
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            self.project()
        self.record_path.write_text('{"results_sha256":NaN}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.project()
        self.record_path.write_text('{"results_sha256":Infinity}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.project()

    def test_all_referenced_evidence_files_must_exist_and_match_hash(self):
        good = self.record["evidence"][0]
        for evidence in (
            [{"path": good["path"], "sha256": "f" * 64}],
            [{"path": good["path"], "sha256": "missing-hash"}],
            [{"path": "absent.txt", "sha256": good["sha256"]}],
            [good, {"path": "absent.txt", "sha256": good["sha256"]}],
        ):
            with self.subTest(evidence=evidence):
                self.write_record(dict(self.record, evidence=evidence))
                self.assertEqual(self.project()["totals"]["accepted"], 0)

    def test_missing_record_or_evidence_is_unaccepted_and_creates_nothing(self):
        self.assertEqual(self.project()["totals"]["accepted"], 0)
        self.assertFalse(self.record_path.exists())
        self.write_record()
        self.proof.unlink()
        self.assertEqual(self.project()["totals"]["accepted"], 0)
        self.assertFalse(self.proof.exists())

    def test_no_scientific_credit_without_actual_successful_collection(self):
        self.write_record()
        for change in ({"collection_verified": False}, {"state": "FAILED_COLLECTED"},
                       {"remote_exit_code": 1}, {"collection_exit_code": 1},
                       {"tool_exit_codes": {}}, {"tool_exit_codes": {"device": 1}}):
            with self.subTest(change=change):
                self.manifests = {"private-run": solved("private-run", input_sha256=self.inputs, **change)}
                self.assertEqual(self.project()["totals"]["accepted"], 0)

    def test_malformed_or_duplicate_record_fields_fail_closed(self):
        for raw in ('{broken', '[]', '{"schema":1,"schema":2}', '\ufffd'):
            with self.subTest(raw=raw):
                self.record_path.write_text(raw, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.project()
        self.record_path.write_bytes(b"\xff")
        with self.assertRaises(ValueError):
            self.project()

    def test_evidence_traversal_outside_workspace_and_directory_are_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "proof.txt"
            external.write_bytes(self.proof.read_bytes())
            for reference in ("../dram/r06-gate/results/proof.txt", r"..\dram\proof.txt",
                              str(external), str(self.proof.parent)):
                with self.subTest(reference=reference):
                    record = copy.deepcopy(self.record)
                    record["evidence"][0]["path"] = reference
                    self.write_record(record)
                    with self.assertRaises(ValueError):
                        self.project()

    def test_absolute_evidence_inside_workspace_is_supported(self):
        proof = self.workspace / "evidence.txt"
        proof.write_bytes(self.proof.read_bytes())
        record = copy.deepcopy(self.record)
        record["evidence"][0]["path"] = str(proof)
        self.write_record(record)
        self.assertEqual(self.project()["totals"]["accepted"], 1)

    def test_record_and_evidence_symlinks_are_rejected(self):
        target = self.workspace / "private-target.json"
        target.write_text(json.dumps(self.record), encoding="utf-8")
        try:
            self.record_path.symlink_to(target)
        except OSError:
            self.skipTest("symlink creation is unavailable on this system")
        with self.assertRaises(ValueError):
            self.project()
        self.record_path.unlink()
        self.write_record()
        proof_link = self.plan_path.parent / "proof-link"
        proof_link.symlink_to(self.proof)
        record = copy.deepcopy(self.record)
        record["evidence"][0]["path"] = str(proof_link)
        self.write_record(record)
        with self.assertRaises(ValueError):
            self.project()

    def test_symlinked_acceptance_directory_is_rejected(self):
        directory = self.workspace / "record-target"
        directory.mkdir()
        (directory / self.record_path.name).write_text(json.dumps(self.record), encoding="utf-8")
        self.record_path.parent.rmdir()
        try:
            self.record_path.parent.symlink_to(directory, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable on this system")
        with self.assertRaises(ValueError):
            self.project()


if __name__ == "__main__":
    unittest.main()
