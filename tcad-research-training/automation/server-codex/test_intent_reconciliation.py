"""Offline evidence binding tests; no native launch or remote access."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location("tested_intent_reconciliation", HERE / "intent_reconciliation.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class IntentSubjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.workspace = self.base / "workspace"
        shared = self.workspace / "experiments/dram-see-v4/transport-probe/launch_reconciliation.py"
        shared.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "experiments/dram-see-v4/transport-probe/launch_reconciliation.py", shared)
        self.v = m.verifier(self.workspace)
        self.cfg = dict(backend="ssh-runtime", ssh_target="fixture-only", runtime_entry="/fixture/entry",
                        remote_root="/fixture/pool", local_state_root=str(
                            self.workspace / "local_runtime/cloud-benchmark/profile"),
                        parallel_capacity=4, requested_threads=2,
                        cpu_sets=[[0, 1], [2, 3], [4, 5], [6, 7]])
        profile = self.workspace / "profile.json"
        self.save(profile, self.cfg)
        project = self.workspace / "projects/a"
        project.mkdir(parents=True)
        (project / "device.cmd").write_text("fixture only")
        hashes = {"device.cmd": self.v.digest((project / "device.cmd").read_bytes())}
        self.intent = dict(backend="tcad", run_id="auto-fixture", slot=0, project="projects/a",
                           connection=dict(path=str(profile), sha256=self.v.digest(profile.read_bytes())),
                           input_sha256=hashes, input_digest=self.v.canonical_sha256(hashes),
                           task_digest="a" * 64, submission_intent_at=1,
                           requested_resources=dict(schema="tcad-shared-gate-slots-r4", capacity=4,
                                                    cpu_set=[0, 1], requested_threads=2),
                           repair_of=None, repair_reason="", scientific_admission={"scope": "p0_diagnostic"},
                           probe_failures=1, next_probe_at=2,
                           reconciliation_error=dict(ok=False, kind="runner_error", returncode=1,
                                                     detail=m.PREFLIGHT_ERROR))
        historical = self.base / "historical-runner.py"
        historical.write_bytes(b"offline historical runner fixture")
        self.old_hash = self.v.digest(historical.read_bytes())
        self.pin_patch = patch.object(m, "PREFLIGHT_RUNNER_SHA", self.old_hash)
        self.pin_patch.start()
        self.addCleanup(self.pin_patch.stop)
        readback = self.workspace / (
            "experiments/dram-se-r06/p0-bootstrap-activation-r1/original-submission-readback.json")
        self.save(readback, {"original_intents": {"task-a": copy.deepcopy(self.intent)}})
        diagnosis = readback.with_name("launch-diagnosis.json")
        self.save(diagnosis, dict(schema="tcad-r06-launch-preflight-diagnosis-v1",
                                 task_id="task-a", run_id="auto-fixture",
                                 utc="2026-01-01T00:00:00+00:00",
                                 read_only_reproduction_matches_original_stderr=True,
                                 original_stderr=m.PREFLIGHT_ERROR,
                                 evidence_bindings={"scripts/tcad.py": self.old_hash,
                                                    readback.relative_to(self.workspace).as_posix():
                                                        self.v.digest(readback.read_bytes())}))
        self.evidence = {key: dict(path=str(p), sha256=self.v.digest(p.read_bytes()))
                         for key, p in (("diagnosis", diagnosis), ("runner", historical))}

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def subject(self, intent=None):
        return m.frozen_subject(self.workspace, "task-a", intent or self.intent, self.evidence)

    def test_mutable_probe_changes_do_not_change_subject_or_original_intent(self):
        before = copy.deepcopy(self.intent)
        frozen = self.subject()
        updated = copy.deepcopy(self.intent)
        updated.update(next_probe_at=90, probe_failures=10,
                       reconciliation_error={"kind": "runner_error", "detail": "later missing manifest"})
        self.assertEqual(frozen, self.subject(updated))
        self.assertEqual(self.intent, before)
        self.assertIsNone(frozen["script_sha256"])

    def test_immutable_changes_are_rejected_including_lineage_and_science(self):
        for key, value in (("submission_intent_at", 3), ("task_digest", "b" * 64),
                           ("repair_of", "different"), ("scientific_admission", {"scope": "production"})):
            altered = copy.deepcopy(self.intent)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.subject(altered)

    def test_project_metadata_uses_runtime_comparison_digest_but_keeps_raw_input_sha(self):
        project = self.workspace / "projects/a/project.json"
        self.save(project, {"name": "display-name", "s2_geometry": {"run_id": "metadata-only", "mode": "fixture"},
                            "steps": []})
        hashes = dict(self.intent["input_sha256"], **{"project.json": self.v.digest(project.read_bytes())})
        comparison = dict(hashes, **{"project.json": self.v.canonical_sha256(
            {"s2_geometry": {"mode": "fixture"}, "steps": []})})
        self.intent.update(input_sha256=hashes, input_digest=self.v.canonical_sha256(comparison))
        readback = self.workspace / (
            "experiments/dram-se-r06/p0-bootstrap-activation-r1/original-submission-readback.json")
        self.save(readback, {"original_intents": {"task-a": copy.deepcopy(self.intent)}})
        diagnosis = Path(self.evidence["diagnosis"]["path"])
        data = json.loads(diagnosis.read_text())
        data["evidence_bindings"][readback.relative_to(self.workspace).as_posix()] = self.v.digest(readback.read_bytes())
        self.save(diagnosis, data)
        self.evidence["diagnosis"]["sha256"] = self.v.digest(diagnosis.read_bytes())
        subject = self.subject()
        self.assertEqual(subject["intent"]["input_sha256"], hashes)
        self.assertNotEqual(self.intent["input_digest"], self.v.canonical_sha256(hashes))
        altered = copy.deepcopy(self.intent)
        altered["input_digest"] = self.v.canonical_sha256(hashes)
        with self.assertRaisesRegex(ValueError, "input/task digest"):
            self.subject(altered)

    def test_any_native_directory_even_without_manifest_is_rejected(self):
        native = Path(self.cfg["local_state_root"]) / "runs" / self.intent["run_id"]
        native.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "directory exists"):
            self.subject()

    def test_input_evidence_and_historical_runner_drift_are_rejected(self):
        for path in (self.workspace / "projects/a/device.cmd",
                     Path(self.evidence["diagnosis"]["path"]), Path(self.evidence["runner"]["path"])):
            original = path.read_bytes()
            path.write_bytes(original + b"\nchanged")
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.subject()
            path.write_bytes(original)

    def test_absent_sidecar_is_not_evidence(self):
        self.assertFalse(m.verified_receipt(self.workspace, self.base / "state", "task-a", self.intent))

    def test_malformed_sidecar_fails_closed(self):
        path = m.receipt_path(self.base / "state", self.intent)
        self.save(path, {"schema": m.SCHEMA, "success": True})
        with self.assertRaises(ValueError):
            m.verified_receipt(self.workspace, self.base / "state", "task-a", self.intent)

    def test_publish_does_not_replace_an_existing_receipt(self):
        reference = self.base / "runtime.json"
        self.save(reference, {})
        path = self.base / "sidecar/a.json"
        m.publish(path, {"first": True}, reference)
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            m.publish(path, {"replacement": True}, reference)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
