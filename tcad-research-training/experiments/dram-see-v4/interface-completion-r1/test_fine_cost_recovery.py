"""Focused offline recovery tests for the fine A0 cost evidence path.

These fixtures test binding and retry control only; they are not TCAD evidence.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FineCostAuditRecoveryTests(unittest.TestCase):
    run_id = "20261013T181717Z-v4-source-interface-r5-a0-b1-fine-26fc3f1a"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fine-cost-audit-")
        self.root = Path(self.temp.name)
        self.probe = load_module("fine_cost_probe_under_test", HERE / "fine_cost_probe.py")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(mock.patch.stopall)

        self.contract = self.root / "experiments/dram-see-v4/source-interface-r5/source_contract.json"
        self.contract.parent.mkdir(parents=True, exist_ok=True)
        self.contract.write_text("frozen contract fixture\n", encoding="utf-8")

        self.run = self.root / "local_runtime/runs" / self.run_id
        self.run.mkdir(parents=True)
        self.parameters = {
            "schema": "dram-see-v4-source-interface-r5", "case_id": "A0", "stored_bit": 1,
            "variant": "fine", "mesh_scale": 0.25, "pulse_max_step_s": 5e-13,
            "source_count": 0, "source_charge_fC": 0.0,
            "source_contract_sha256": digest(self.contract),
        }
        self.archive = self.run / "results.tar"
        members = {"parameters.json": (json.dumps(self.parameters, sort_keys=True) + "\n").encode(),
                   "transient_des.log": b""}
        members.update({f"gfield_{i}_access_des.tdr": ("frame-" + str(i)).encode() for i in range(5)})
        with tarfile.open(self.archive, "w:") as tar:
            for name, raw in members.items():
                import io
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                tar.addfile(info, io.BytesIO(raw))
        self.manifest = {
            "run_id": self.run_id, "state": "COLLECTED", "ssh_exit_code": 0,
            "results_sha256": digest(self.archive),
            "input_sha256": {"parameters.json": hashlib.sha256(members["parameters.json"]).hexdigest()},
            "remote_directory": "/srv/remote/runs/" + self.run_id,
        }
        write_json(self.run / "manifest.json", self.manifest)

        self.campaign = self.root / "campaign.json"
        self.campaign.write_text("campaign fixture\n", encoding="utf-8")
        self.audit_path = self.root / "audit/source-audit.json"
        self.audit = {
            "schema": "dram-see-v4-source-interface-r5-audit", "passed": True,
            "run_id": self.run_id, "archive_sha256": self.manifest["results_sha256"],
            "parameters": self.parameters, "errors": [],
            "checks": {"raw_archive": {"passed": True}, "source_identity": {"passed": True}},
        }
        self.gate_path = self.root / "gate.json"
        self.gate = {
            "schema": "dram-see-v4-completion-role-gate-r1", "role_id": "a0-b1-fine",
            "passed": True, "campaign_sha256": digest(self.campaign), "run_id": self.run_id,
            "evidence": [],
        }
        self.write_audit_and_gate()
        self.patches = [
            mock.patch.object(self.probe, "ROOT", self.root),
            mock.patch.object(self.probe, "GATE", self.gate_path),
            mock.patch.object(self.probe, "CAMPAIGN", self.campaign),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_audit_and_gate(self, *, reference_pass=False):
        write_json(self.audit_path, self.audit)
        self.gate["evidence"] = [{"path": self.audit_path.relative_to(self.root).as_posix(),
                                  "sha256": digest(self.audit_path), "requires_pass": reference_pass}]
        write_json(self.gate_path, self.gate)

    def verify_rejects(self):
        with self.assertRaises((ValueError, KeyError, TypeError)):
            self.probe.verify_run(self.run_id)

    def test_passing_audit_is_accepted_when_gate_reference_requires_pass_is_false(self):
        self.write_audit_and_gate(reference_pass=False)
        result, remote = self.probe.verify_run(self.run_id)
        self.assertEqual(result["source_audit_sha256"], digest(self.audit_path))
        self.assertEqual(result["source_archive_sha256"], self.manifest["results_sha256"])
        self.assertEqual(remote, self.manifest["remote_directory"])

    def test_passing_audit_is_rejected_when_audit_passed_is_false_even_if_reference_is_false(self):
        self.audit["passed"] = False
        self.write_audit_and_gate(reference_pass=False)
        self.verify_rejects()

    def test_missing_passed_field_is_rejected(self):
        self.audit.pop("passed")
        self.write_audit_and_gate(reference_pass=False)
        self.verify_rejects()

    def test_nonempty_audit_errors_are_rejected(self):
        self.audit["errors"] = ["fixture failure"]
        self.write_audit_and_gate(reference_pass=False)
        self.verify_rejects()

    def test_missing_audit_errors_array_is_rejected(self):
        self.audit.pop("errors")
        self.write_audit_and_gate(reference_pass=False)
        self.verify_rejects()

    def test_failed_or_missing_audit_checks_are_rejected(self):
        for checks in ({"raw_archive": {"passed": False}}, {}):
            with self.subTest(checks=checks):
                self.audit["checks"] = checks
                self.write_audit_and_gate(reference_pass=False)
                self.verify_rejects()
                self.audit["checks"] = {"raw_archive": {"passed": True}}

    def test_malformed_audit_checks_are_rejected(self):
        for checks in (["not-a-check-object"], {"raw_archive": "not-a-check-object"}, {"raw_archive": {}}):
            with self.subTest(checks=checks):
                self.audit["checks"] = checks
                self.write_audit_and_gate(reference_pass=False)
                self.verify_rejects()
                self.audit["checks"] = {"raw_archive": {"passed": True}}

    def test_wrong_audit_schema_is_rejected(self):
        self.audit["schema"] = "wrong-schema"
        self.write_audit_and_gate(reference_pass=False)
        self.verify_rejects()

    def test_audit_run_id_mismatch_is_rejected(self):
        self.audit["run_id"] = "different-run"
        self.write_audit_and_gate(reference_pass=False)
        self.verify_rejects()

    def test_audit_archive_mismatch_is_rejected(self):
        self.audit["archive_sha256"] = "0" * 64
        self.write_audit_and_gate(reference_pass=False)
        self.verify_rejects()

    def test_zero_or_multiple_matching_audits_are_rejected(self):
        self.gate["evidence"] = []
        write_json(self.gate_path, self.gate)
        self.verify_rejects()

        second = self.root / "audit/second-audit.json"
        write_json(second, self.audit)
        self.gate["evidence"] = [
            {"path": self.audit_path.relative_to(self.root).as_posix(), "sha256": digest(self.audit_path), "requires_pass": False},
            {"path": second.relative_to(self.root).as_posix(), "sha256": digest(second), "requires_pass": False},
        ]
        write_json(self.gate_path, self.gate)
        self.verify_rejects()

    def test_tampered_gate_reference_hash_is_rejected(self):
        self.audit_path.write_text("tampered\n", encoding="utf-8")
        self.verify_rejects()

    def test_wrong_gate_run_id_is_rejected(self):
        self.gate["run_id"] = "different-run"
        write_json(self.gate_path, self.gate)
        self.verify_rejects()


class FineCostRunnerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fine-cost-runner-")
        self.root = Path(self.temp.name)
        self.runner = load_module("campaign_runner_under_test", HERE / "campaign_runner.py")
        self.addCleanup(self.temp.cleanup)
        self.state = self.root / "local_runtime/dram-see-v4/interface-completion-r1"
        self.rt = self.root / "local_runtime/dram-see-v4"
        self.v4 = self.root / "experiments/dram-see-v4"
        self.state.mkdir(parents=True)
        for name, value in (("STATE", self.state), ("RT", self.rt), ("V4", self.v4), ("ROOT", self.root)):
            patcher = mock.patch.object(self.runner, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_existing_cost_operation_is_summarized_without_reprepare_or_reexecution(self):
        label = "r5-a0-fine-recovery-cost"
        run_id = "20261013T181717Z-v4-source-interface-r5-a0-b1-fine-26fc3f1a"
        opdir = self.rt / "transport-probe/operations" / (label + "-cost")
        output = self.state / "cost-probes" / (label + "-cost")
        opdir.mkdir(parents=True)
        output.mkdir(parents=True)
        probe = mock.Mock()
        probe.summarize.side_effect = AssertionError("existing output must not be regenerated")
        self.runner.module = mock.Mock(return_value=probe)
        self.runner.read = mock.Mock(side_effect=lambda path: (
            {"state": "COLLECTED_PENDING_AUDIT", "ssh_exit_code": 0, "remote_exit_code": 0,
             "collection_exit_code": 0} if Path(path).name == "operation.json" else
            {"passed": True, "source_run_id": run_id, "mesh_node_count": 321, "solver_wallclock_s": 12.5}
        ))
        self.runner.call = mock.Mock(side_effect=AssertionError("must not execute an existing operation"))
        self.runner.a.reference = mock.Mock(return_value={"path": "fixture"})
        self.runner.a.save_new = mock.Mock()
        result = self.runner.fine_cost(label, Path(run_id))
        self.assertTrue(result["passed"])
        self.assertEqual(result["operation_label"], label + "-cost")
        probe.prepare.assert_not_called()
        probe.summarize.assert_not_called()
        self.runner.call.assert_not_called()

    def test_existing_resource_evidence_gets_a_fresh_preflight_label(self):
        label = "r5-a0-fine-recovery"
        opname = label + "-cost"
        existing = self.state / "resources" / (opname + "-resource")
        existing.mkdir(parents=True)
        observed = {}
        resources = mock.Mock()

        def check(profile, resource_label):
            observed.update(profile=profile, label=resource_label)
            self.assertEqual(profile, "fine")
            self.assertNotEqual(resource_label, existing.name)
            self.assertFalse((self.state / "resources" / resource_label).exists())
            fresh = self.state / "resources" / resource_label
            fresh.mkdir(parents=True)
            (fresh / "record.json").write_text('{"passed":true}\n', encoding="utf-8")
            return {"passed": True, "path": str(fresh / "record.json")}

        resources.check.side_effect = check
        probe = mock.Mock()
        probe.prepare.side_effect = lambda run_id, operation_label: (
            (self.rt / "transport-probe/inputs" / operation_label).mkdir(parents=True, exist_ok=True)
        )
        self.runner.module = mock.Mock(side_effect=lambda path, _name: resources if Path(path).name == "resources.py" else probe)
        prior = self.rt / "transport-probe/operations/r5-extractor-five-r1"
        prior.mkdir(parents=True)
        (prior / "operation.json").write_text("{}\n", encoding="utf-8")
        collected = prior / "collected"
        collected.mkdir()
        for i in range(5):
            (collected / f"gfield_{i}_access_des.tdr").write_bytes(b"native-frame")
        self.runner.read = mock.Mock(side_effect=lambda path: (
            {"tdr_bytes": {f"gfield_{i}_access_des.tdr": 11 for i in range(5)}}
            if Path(path).name == "source-evidence.json" else
            {"started_utc": "2026-10-13T00:00:00+00:00", "finished_utc": "2026-10-13T00:00:01+00:00"}
            if Path(path).name == "operation.json" and Path(path).parent == prior else
            {"state": "COLLECTED_PENDING_AUDIT", "ssh_exit_code": 0, "remote_exit_code": 0,
             "collection_exit_code": 0} if Path(path).name == "operation.json" else
            {"passed": True, "source_run_id": "source-run", "mesh_node_count": None, "solver_wallclock_s": None}
        ))
        self.runner.sha = mock.Mock(return_value="a" * 64)
        self.runner.rel = mock.Mock(side_effect=lambda path: Path(path).as_posix())
        self.runner.a.reference = mock.Mock(return_value={"path": "fixture"})
        self.runner.a.save_new = mock.Mock()

        def invoke(argv, stem):
            if stem.endswith("-run"):
                operation_dir = self.rt / "transport-probe/operations" / opname
                operation_dir.mkdir(parents=True, exist_ok=True)
                (operation_dir / "operation.json").write_text("{}\n", encoding="utf-8")
            return 0
        self.runner.call = mock.Mock(side_effect=invoke)
        result = self.runner.fine_cost(label, Path("source-run"))
        self.assertTrue(result["passed"])
        self.assertEqual(observed["label"].startswith(opname + "-resource-"), True)
        self.assertTrue((self.state / "resources" / observed["label"] / "record.json").is_file())
        self.assertEqual(self.runner.call.call_count, 1)
        probe.prepare.assert_called_once_with("source-run", opname)

    def test_completed_fine_adoption_reuses_source_and_orders_cost_before_budget(self):
        label = "r5-a0-b1-fine-r1"
        run_id = "20261013T181717Z-v4-source-interface-r5-a0-b1-fine-26fc3f1a"
        role = {"role_id": "a0-b1-fine", "case_id": "A0", "variant": "fine"}
        execution = {"label": label, "role_id": role["role_id"], "state": "RUNNER_EXITED",
                     "runner_exit_code": 0, "run_id": run_id}
        self.runner.R5 = self.root / "source-interface-r5"
        launch = self.runner.R5 / "launches" / label
        launch.mkdir(parents=True)
        (launch / "execution.json").write_text("{}\n", encoding="utf-8")
        events = []
        self.runner.read = mock.Mock(return_value=execution)
        self.runner.a.validate_invocation = mock.Mock()
        self.runner.a.accept = mock.Mock(side_effect=lambda *args: (events.append("accept") or {"passed": True}))
        self.runner.a.reference = mock.Mock(return_value={"path": "fixture"})
        self.runner.a.save_new = mock.Mock()
        self.runner.fine_cost = mock.Mock(side_effect=lambda *args: events.append("fine_cost"))
        self.runner.budget = mock.Mock(side_effect=lambda: events.append("budget"))
        self.runner.update = mock.Mock()

        result = self.runner.process_finished(role, label)
        self.assertTrue(result)
        self.assertEqual(events, ["accept", "fine_cost", "budget"])
        self.runner.fine_cost.assert_called_once_with(label, self.root / "local_runtime/runs" / run_id)
        self.runner.call = mock.Mock(side_effect=AssertionError("adoption must not invoke a source runner"))
        self.runner.call.assert_not_called()


class FineCostBudgetRecoveryTests(unittest.TestCase):
    run_id = "20261013T181717Z-v4-source-interface-r5-a0-b1-fine-26fc3f1a"
    archive_sha = "a" * 64
    frame_names = [f"gfield_{i}_access_des.tdr" for i in range(5)]
    native_names = ["source-evidence.json", "cost_probe.tcl", "cost-timing.csv", "cost-field-inventory.csv",
                    "cost-status.txt", "svisual.log", "svisual-exit-code.txt", "execution.log", "affinity.txt", "run.sh"]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fine-cost-budget-")
        self.root = Path(self.temp.name)
        self.reporter = load_module("budget_report_under_test", HERE / "budget_report.py")
        self.addCleanup(self.temp.cleanup)
        self.state = self.root / "local_runtime/dram-see-v4/interface-completion-r1"
        self.rt = self.root / "local_runtime/dram-see-v4"
        self.here = self.root / "experiments/dram-see-v4/interface-completion-r1"
        self.campaign = self.here / "campaign.json"
        self.campaign.parent.mkdir(parents=True)
        self.campaign.write_text("campaign fixture\n", encoding="utf-8")
        for name, value in (("ROOT", self.root), ("RT", self.rt), ("STATE", self.state),
                            ("HERE", self.here), ("CAMPAIGN", self.campaign)):
            patcher = mock.patch.object(self.reporter, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def build_fixture(self, *, audit_overrides=None, audit_remove=(), gate_run_id=None, evidence_count=1):
        shutil.rmtree(self.root / "local_runtime", ignore_errors=True)
        state, rt = self.state, self.rt
        op_label = "r5-a0-fine-cost"
        run = self.root / "local_runtime/runs" / self.run_id
        run.mkdir(parents=True)
        raw_archive = run / "results.tar"
        raw_archive.write_bytes(b"raw solver archive fixture")
        manifest = {"run_id": self.run_id, "state": "COLLECTED", "ssh_exit_code": 0,
                    "results_sha256": self.archive_sha}
        manifest_path = run / "manifest.json"
        write_json(manifest_path, manifest)

        gate_path = state / "gates/a0-b1-fine.json"
        audit_path = rt / "source-interface-r5/audits/source-audit/audit.json"
        audit = {"schema": "dram-see-v4-source-interface-r5-audit", "passed": True,
                 "run_id": self.run_id, "archive_sha256": self.archive_sha, "errors": [],
                 "checks": {"archive": {"passed": True}},
                 "parameters": {"case_id": "A0", "stored_bit": 1, "variant": "fine", "mesh_scale": .25}}
        audit.update(audit_overrides or {})
        for key in audit_remove:
            audit.pop(key, None)
        write_json(audit_path, audit)
        audit_ref = audit_path.relative_to(self.root).as_posix()
        evidence = [{"path": audit_ref, "sha256": digest(audit_path), "requires_pass": False} for _ in range(evidence_count)]
        gate = {"schema": "dram-see-v4-completion-role-gate-r1", "role_id": "a0-b1-fine",
                "passed": True, "run_id": gate_run_id or self.run_id,
                "campaign_sha256": digest(self.campaign), "evidence": evidence}
        write_json(gate_path, gate)

        source = {"schema": "dram-see-v4-fine-cost-source-r1", "source_run_id": self.run_id,
                  "source_archive_sha256": self.archive_sha, "source_archive_bytes": raw_archive.stat().st_size,
                  "source_manifest_sha256": digest(manifest_path), "source_field_acceptance": False,
                  "new_sdevice_solves": 0, "source_manifest_sha256": digest(manifest_path),
                  "gate_path": gate_path.relative_to(self.root).as_posix(), "gate_sha256": digest(gate_path),
                  "campaign_sha256": digest(self.campaign), "source_audit_path": audit_ref,
                  "source_audit_sha256": digest(audit_path), "tdr_sha256": {n: str(i) * 64 for i, n in enumerate(self.frame_names, 1)},
                  "tdr_bytes": {n: 10 + i for i, n in enumerate(self.frame_names)},
                  "mesh_node_count": None, "mesh_node_definition": "fixture only",
                  "mesh_node_log_evidence": [], "solver_wallclock_s": None,
                  "solver_wallclock_log_evidence": []}

        opdir = rt / "transport-probe/operations" / op_label
        collected = opdir / "collected"
        collected.mkdir(parents=True)
        (opdir / "results.tar").write_bytes(b"native operation archive fixture")
        op_record = {"state": "COLLECTED_PENDING_AUDIT", "ssh_exit_code": 0, "remote_exit_code": 0,
                     "collection_exit_code": 0, "archive_sha256": "b" * 64,
                     "started_utc": "2026-10-13T00:00:00+00:00", "finished_utc": "2026-10-13T00:00:01+00:00"}
        write_json(opdir / "operation.json", op_record)
        write_json(collected / "source-evidence.json", source)
        for name in self.native_names[1:]:
            (collected / name).write_text("native metadata fixture\n", encoding="utf-8")
        timing = "source_file,load_ms,query_ms,release_ms,total_ms,status\n" + "".join(
            f"{name},1,2,3,6,OK\n" for name in self.frame_names)
        (collected / "cost-timing.csv").write_text(timing, encoding="utf-8")
        for name in self.frame_names:
            (collected / name).write_bytes(b"frame")

        cost = {"schema": "dram-see-v4-fine-a0-cost-probe-r1", "passed": True,
                "source_run_id": self.run_id, "source_archive_sha256": self.archive_sha,
                "source_archive_bytes": raw_archive.stat().st_size, "source_gate_sha256": digest(gate_path),
                "mesh_node_count": None, "mesh_node_definition": "fixture only", "mesh_node_log_evidence": [],
                "solver_wallclock_s": None, "solver_wallclock_log_evidence": [],
                "frames": [{"source_file": n, "load_ms": 1, "query_ms": 2, "release_ms": 3, "total_ms": 6} for n in self.frame_names],
                "tdr_bytes": source["tdr_bytes"], "five_frame_bytes": sum(source["tdr_bytes"].values()),
                "native_timing_totals_ms": {"load_ms": 5, "query_ms": 10, "release_ms": 15, "total_ms": 30},
                "native_load_inventory_release_seconds_per_frame": .006, "operation_elapsed_s": 1.0,
                "fields_unknown": None, "full_11roi_extraction_measured_s": None,
                "full_11roi_extraction_estimate_s": None, "source_field_acceptance": False, "new_sdevice_solves": 0}
        cost_path = state / "cost-probes" / op_label / "cost.json"
        write_json(cost_path, cost)
        receipt = {"schema": "dram-see-v4-fine-cost-native-receipt-r1", "passed": True,
                   "source_run_id": self.run_id, "source_archive_sha256": self.archive_sha,
                   "source_field_acceptance": False, "new_sdevice_solves": 0,
                   "ssh_exit_code": 0, "remote_exit_code": 0, "collection_exit_code": 0, "svisual_exit_code": 0,
                   "cost_report_sha256": digest(cost_path), "operation_path": opdir.relative_to(self.root).as_posix(),
                   "operation_record_sha256": digest(opdir / "operation.json"),
                   "operation_archive_sha256": op_record["archive_sha256"],
                   "source_evidence_sha256": digest(collected / "source-evidence.json"),
                   "source_manifest_sha256": digest(manifest_path), "tdr_before_sha256": source["tdr_sha256"],
                   "tdr_after_sha256": source["tdr_sha256"],
                   "native_outputs_sha256": {n: digest(collected / n) for n in self.native_names}}
        write_json(cost_path.parent / "cost-probe-receipt.json", receipt)
        for name, value in (("ROOT", self.root), ("RT", rt), ("STATE", state), ("HERE", self.here),
                            ("CAMPAIGN", self.campaign)):
            setattr(self.reporter, name, value)
        sources = {self.campaign.relative_to(self.root).as_posix(): {"sha256": digest(self.campaign)}}
        warnings = []
        return sources, warnings

    def assert_rejected(self, **kwargs):
        sources, warnings = self.build_fixture(**kwargs)
        records = self.reporter._fine_cost_records(sources, warnings)
        self.assertEqual(records, [])
        self.assertTrue(any("Fine cost rejected" in item["error"] for item in warnings), warnings)

    def test_false_gate_reference_does_not_hide_exact_passing_source_audit(self):
        sources, warnings = self.build_fixture()
        records = self.reporter._fine_cost_records(sources, warnings)
        self.assertEqual(len(records), 1, warnings)
        self.assertEqual(records[0]["source_run_id"], self.run_id)

    def test_failed_source_audit_is_rejected_even_with_false_gate_reference(self):
        self.assert_rejected(audit_overrides={"passed": False})

    def test_missing_errors_array_is_rejected(self):
        self.assert_rejected(audit_remove=("errors",))

    def test_missing_errors_or_checks_or_failed_check_is_rejected(self):
        for override in ({"errors": ["fixture error"]}, {"checks": {}},
                         {"checks": {"archive": {"passed": False}}},
                         {"checks": ["not-a-check-object"]}, {"checks": {"archive": "not-a-check-object"}},
                         {"checks": {"archive": {}}}):
            with self.subTest(override=override):
                self.assert_rejected(audit_overrides=override)

    def test_wrong_source_audit_schema_or_run_or_archive_is_rejected(self):
        for override in ({"schema": "wrong"}, {"run_id": "other-run"}, {"archive_sha256": "0" * 64}):
            with self.subTest(override=override):
                self.assert_rejected(audit_overrides=override)

    def test_zero_or_duplicate_matching_source_audit_is_rejected(self):
        self.assert_rejected(evidence_count=0)
        self.assert_rejected(evidence_count=2)

    def test_wrong_gate_run_id_is_rejected(self):
        self.assert_rejected(gate_run_id="other-run")


if __name__ == "__main__":
    unittest.main()
