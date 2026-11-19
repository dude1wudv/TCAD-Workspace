"""Offline admission tests; native submissions are intercepted by old fixtures."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load("r06_gate_tested", "r06_gate.py")
fixtures = load("r06_runtime_fixtures", "test_runtime.py")


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = {"id": "r06-p0-zero-v1", "backend": "tcad", "project": "inputs/zero"}
        project = self.root / self.task["project"]
        self.save("inputs/zero/project.json", {
            "native_threads": 2, "native_cores": 2,
            "steps": [{"tool": "sdevice", "args": ["device.cmd"]}]})
        (project / "device.cmd").write_text("Transient(InitialTime=0 FinalTime=35e-9) {}", encoding="utf-8")
        (project / "nodal-source.dat").write_text(
            "R04_NODAL_SOURCE 1 1 0 0\nunits um s cm3 cm^-3_s^-1 pairs\nN R 0 0 0 1\n",
            encoding="utf-8")
        self.envelope = {"plan_id": gate.PLAN, "revision": gate.REVISION, "owner": gate.OWNER}
        self.manifest = {
            "plan_id": gate.PLAN, "revision": gate.REVISION,
            "profiles": [{"id": "D0-nominal", "partition": "development",
                          "crn_group_id": "crn-d0"}],
            "radiations": [{"id": "G0", "role": "development"}],
            "cases": [{"case_id": "r06-t-d0", "block": "T", "kind": "response",
                       "profile_id": "D0-nominal", "radiation_id": "G0", "stored_bit": 1,
                       "crn_group_id": "crn-d0", "holdout": None, "statistics_intent": False,
                       "deck_timing_version": "r06-hold-window-v1", "source_time_ns": 22.0}]}
        self.save("manifest.json", self.manifest)
        (self.root / "authority.md").write_text("Approved research authority", encoding="utf-8")
        self.contract = dict(self.envelope, schema="tcad-r06-scientific-gate-contract-v1",
                             manifest=self.ref("manifest.json"), authority=self.ref("authority.md"),
                             p0_admissions_dir="p0", production_admissions_dir="production",
                             max_p0_tasks=64, max_p0_particle_tasks=12)
        self.save("contract.json", self.contract)
        self.policy = {"scientific_gate": {
            "schema": "tcad-r06-scientific-gate-policy-v1", "contract": self.ref("contract.json"),
            "deferred_task_ids": ["old-task"]}}
        self.save("diagnostic.json", {
            "schema": "tcad-r06-diagnostic-plan-v1", "recipe_id": "zero_whr",
            "profile_id": "D0-nominal", "frozen_before_submission": True,
            "acceptance_criteria": "Check converged write hold and read margins against frozen criteria."})
        self.admission = dict(
            self.envelope, schema="tcad-r06-p0-admission-v1", scope="p0_diagnostic",
            task_id=self.task["id"], backend="tcad", project=self.task["project"],
            input_sha256=gate.input_hashes(project), formal_case_id=None,
            statistics_eligible=False, budget_account="p0_diagnostics",
            recipe_id="zero_whr", profile_id="D0-nominal",
            purpose="New-version matched zero qualification", created_at="2026-11-17T17:00:00Z",
            diagnostic_plan=self.ref("diagnostic.json"))
        self.save("p0/" + self.task["id"] + ".json", self.admission)

    def save(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def ref(self, name):
        return {"path": name, "sha256": gate.sha(self.root / name)}

    def verify(self):
        return gate.verify(self.root, self.policy, self.task)

    def production(self):
        self.task = {"id": "r06-t-run-v1", "backend": "tcad", "project": "inputs/zero"}
        proof = {"status": "passed", "evidence": [self.ref("authority.md")]}
        self.science = dict(
            self.envelope, schema="tcad-r06-p0-scientific-gate-v1",
            manifest_sha256=self.contract["manifest"]["sha256"], p1_authorized=True,
            numerics=copy.deepcopy(proof), logging=copy.deepcopy(proof),
            timing=copy.deepcopy(proof), source_integral=dict(copy.deepcopy(proof), relative_error=1e-12),
            profiles={"D0-nominal": dict(copy.deepcopy(proof), qualified_bits=[0, 1])},
            deck_timing_version="r06-hold-window-v1", source_time_ns=22.0)
        self.save("science.json", self.science)
        self.admission = dict(
            self.envelope, schema="tcad-r06-production-admission-v1",
            task_id=self.task["id"], backend="tcad", project=self.task["project"],
            scope="development_production", created_at="2026-11-17T17:00:00Z",
            input_sha256=gate.input_hashes(self.root / self.task["project"]),
            case_id="r06-t-d0", profile_id="D0-nominal", radiation_id="G0",
            stored_bit=1, block="T", manifest_sha256=self.contract["manifest"]["sha256"],
            p0_gate=self.ref("science.json"))
        self.save("production/" + self.task["id"] + ".json", self.admission)

    def rebind_science(self):
        self.save("science.json", self.science)
        self.admission["p0_gate"] = self.ref("science.json")
        self.save("production/" + self.task["id"] + ".json", self.admission)

    def test_legacy_missing_policy_only_and_enabled_invalid_policy_fails_closed(self):
        self.assertEqual(gate.verify(self.root, {}, self.task), {"scope": "legacy"})
        for value in (None, {}, [], {"schema": "bad"}):
            with self.subTest(value=value), self.assertRaises(gate.Pending):
                gate.verify(self.root, {"scientific_gate": value}, self.task)

    def test_hash_bound_zero_recipe_admitted_without_scientific_pass_claim(self):
        self.assertEqual(self.verify()["scope"], "p0_diagnostic")
        self.assertNotIn("passed", self.verify())

    def test_legacy_new_task_is_held_and_bad_manifest_cannot_fall_back(self):
        for task_id in ("old-task", "another-old-id"):
            task = dict(self.task, id=task_id)
            with self.assertRaises(gate.Pending):
                gate.verify(self.root, self.policy, task)
        (self.root / "manifest.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(gate.Pending):
            self.verify()

    def test_changed_inputs_wrong_recipe_and_formal_credit_are_rejected(self):
        for key, value in (("recipe_id", "arbitrary"), ("formal_case_id", "r06-t-d0"),
                           ("statistics_eligible", True), ("input_sha256", {})):
            with self.subTest(key=key):
                modified = dict(self.admission, **{key: value})
                self.save("p0/" + self.task["id"] + ".json", modified)
                with self.assertRaises(gate.Pending):
                    self.verify()
        self.save("p0/" + self.task["id"] + ".json", self.admission)
        (self.root / "inputs/zero/device.cmd").write_text("changed", encoding="utf-8")
        with self.assertRaises(gate.Pending):
            self.verify()

    def test_zero_recipe_cannot_hide_nonzero_source_or_excessive_duration(self):
        for filename, content in (
                ("nodal-source.dat", "R04_NODAL_SOURCE 1 1 1 1\n"),
                ("device.cmd", "Transient(FinalTime=1e-6) {}")):
            with self.subTest(filename=filename):
                path = self.root / "inputs/zero" / filename
                original = path.read_bytes()
                path.write_text(content, encoding="utf-8")
                self.admission["input_sha256"] = gate.input_hashes(path.parent)
                self.save("p0/" + self.task["id"] + ".json", self.admission)
                with self.assertRaises(gate.Pending):
                    self.verify()
                path.write_bytes(original)

    def test_production_requires_all_common_decisions_and_target_profile(self):
        self.production()
        self.assertEqual(self.verify()["scope"], "development_production")
        for key in ("numerics", "logging", "timing", "source_integral"):
            original = copy.deepcopy(self.science[key])
            self.science[key]["status"] = "failed"
            self.rebind_science()
            with self.subTest(key=key), self.assertRaises(gate.Pending):
                self.verify()
            self.science[key] = original
        self.science["profiles"]["D0-nominal"]["qualified_bits"] = [1]
        self.rebind_science()
        with self.assertRaises(gate.Pending):
            self.verify()

    def test_failed_other_profile_does_not_block_qualified_branch(self):
        self.production()
        self.science["profiles"]["D1-short-channel"] = {"status": "failed"}
        self.rebind_science()
        self.assertEqual(self.verify()["case_id"], "r06-t-d0")

    def test_stale_evidence_wrong_time_and_integral_error_rejected(self):
        self.production()
        for key, value in (("source_time_ns", 15.003),
                           ("manifest_sha256", "0" * 64)):
            original = self.science[key]
            self.science[key] = value
            self.rebind_science()
            with self.subTest(key=key), self.assertRaises(gate.Pending):
                self.verify()
            self.science[key] = original
        self.science["source_integral"]["relative_error"] = 1e-9
        self.rebind_science()
        with self.assertRaises(gate.Pending):
            self.verify()
        self.science["source_integral"]["relative_error"] = 0
        self.rebind_science()
        (self.root / "authority.md").write_text("changed evidence", encoding="utf-8")
        with self.assertRaises(gate.Pending):
            self.verify()

    def test_paths_and_missing_evidence_are_rejected(self):
        for path in ("../outside", "/absolute", "C:/outside", "dir\\file"):
            with self.subTest(path=path), self.assertRaises(gate.Pending):
                gate.path_at(self.root, path)
        self.production()
        self.science["logging"]["evidence"] = []
        self.rebind_science()
        with self.assertRaises(gate.Pending):
            self.verify()

    def test_transport_has_separate_admission_and_no_missing_frame_deadlock(self):
        self.production()
        self.task["backend"] = "geant4"
        self.admission.update(backend="geant4", scope="transport_pool")
        self.save("pool-request.json", {
            "schema": "tcad-r06-transport-request-v1", "profile_id": "D0-nominal",
            "crn_group_id": "crn-d0", "radiation_id": "G0", "primary_count": 100000,
            "seed": 20261117, "uniform_source_area_sampling": True,
            "retain_zero_deposition_primaries": True, "source_area_cm2": 1e-8})
        self.admission["pool_request"] = self.ref("pool-request.json")
        self.save("production/" + self.task["id"] + ".json", self.admission)
        self.assertEqual(self.verify()["scope"], "transport_pool")
        request = gate.read(self.root / "pool-request.json")
        request["primary_count"] = 1000000
        self.save("pool-request.json", request)
        self.admission["pool_request"] = self.ref("pool-request.json")
        self.save("production/" + self.task["id"] + ".json", self.admission)
        with self.assertRaises(gate.Pending):
            self.verify()

    def test_holdout_requires_hash_bound_development_freeze(self):
        self.production()
        self.manifest["cases"][0].update(block="HP", holdout="device")
        self.save("manifest.json", self.manifest)
        self.contract["manifest"] = self.ref("manifest.json")
        self.save("contract.json", self.contract)
        self.policy["scientific_gate"]["contract"] = self.ref("contract.json")
        self.admission.update(scope="holdout_evaluation", block="HP",
                              manifest_sha256=self.contract["manifest"]["sha256"])
        self.science["manifest_sha256"] = self.contract["manifest"]["sha256"]
        self.rebind_science()
        with self.assertRaises(gate.Pending):
            self.verify()
        frozen = dict(self.envelope, schema="tcad-r06-training-freeze-v1",
                      frozen=True, holdout_used_for_training=False)
        frozen.update({key: self.ref("authority.md") for key in
                       ("model", "preprocessing", "split", "calibration", "acquisition")})
        self.save("freeze.json", frozen)
        self.admission["training_freeze"] = self.ref("freeze.json")
        self.save("production/" + self.task["id"] + ".json", self.admission)
        first = self.verify()
        self.assertEqual(first["scope"], "holdout_evaluation")
        (self.root / "model-v2.bin").write_bytes(b"another development model")
        frozen["model"] = self.ref("model-v2.bin")
        self.save("freeze-v2.json", frozen)
        self.admission["training_freeze"] = self.ref("freeze-v2.json")
        self.save("production/" + self.task["id"] + ".json", self.admission)
        with self.assertRaisesRegex(gate.Pending, "another frozen development version"):
            gate.verify(self.root, self.policy, self.task, intents={
                "first-holdout-pool": {"scientific_admission": {
                    "scope": "transport_pool", "training_freeze": first["training_freeze"]}}})

    def test_al_assignment_must_be_frozen_and_cannot_use_holdout(self):
        self.production()
        self.manifest["cases"][0].update(block="AL", profile_id=None,
                                         radiation_id=None, stored_bit=1)
        self.save("manifest.json", self.manifest)
        self.contract["manifest"] = self.ref("manifest.json")
        self.save("contract.json", self.contract)
        self.policy["scientific_gate"]["contract"] = self.ref("contract.json")
        self.admission.update(block="AL", manifest_sha256=self.contract["manifest"]["sha256"])
        self.science["manifest_sha256"] = self.contract["manifest"]["sha256"]
        self.rebind_science()
        decision = dict(
            self.envelope, schema="tcad-r06-al-acquisition-v1",
            case_id="r06-t-d0", holdout_used=False, profile_id="D0-nominal",
            radiation_id="G0", stored_bit=1)
        decision.update({key: self.ref("authority.md") for key in
                         ("development_snapshot", "candidate_model", "selection_rule",
                          "event_provenance", "response_context")})
        decision.update(event_id="17", transport_run_id="native-transport",
                        response_input_sha256=self.admission["input_sha256"])
        self.save("acquisition.json", decision)
        self.admission["acquisition"] = self.ref("acquisition.json")
        self.save("production/" + self.task["id"] + ".json", self.admission)
        self.assertEqual(self.verify()["scope"], "development_production")
        self.admission["stored_bit"] = decision["stored_bit"] = 0
        self.save("acquisition.json", decision)
        self.admission["acquisition"] = self.ref("acquisition.json")
        self.save("production/" + self.task["id"] + ".json", self.admission)
        with self.assertRaises(gate.Pending):
            self.verify()
        self.admission["stored_bit"] = decision["stored_bit"] = 1
        decision["holdout_used"] = True
        self.save("acquisition.json", decision)
        self.admission["acquisition"] = self.ref("acquisition.json")
        self.save("production/" + self.task["id"] + ".json", self.admission)
        with self.assertRaises(gate.Pending):
            self.verify()

    def test_p0_budget_counts_durable_intents_not_unsubmitted_drafts(self):
        for index in range(65):
            self.save("p0/draft-" + str(index) + ".json", {})
        self.assertEqual(self.verify()["scope"], "p0_diagnostic")
        intents = {str(index): {"scientific_admission": {
            "scope": "p0_diagnostic", "recipe_id": "zero_whr"}} for index in range(64)}
        with self.assertRaises(gate.Pending):
            gate.verify(self.root, self.policy, self.task, intents=intents)

    def test_pmi_build_uses_exact_frozen_compile_only_recipe(self):
        project = self.root / "inputs/build"
        project.mkdir()
        for name, raw in {
            "task.sh": gate.BUILD_TASK, "compile-in-original-vm.sh": "# frozen compile command\n",
            "pmi_r04_nodal.C": "// frozen source\n", "nodal_source.hpp": "// node physics\n",
            "voxel_source.hpp": "// voxel physics\n", "build-inputs.sha256": "frozen table\n",
        }.items():
            (project / name).write_text(raw, encoding="utf-8")
        headers = {name: gate.sha(project / name) for name in ("nodal_source.hpp", "voxel_source.hpp")}
        self.save("inputs/build/build-request.json", {
            "schema": "tcad-r06-pmi-build-request-v1", "solver_called": False,
            "headers_sha256": headers,
            "command": ["/usr/synopsys/sentaurus/W-2024.09/bin/cmi", "-O", "-v", "pmi_r04_nodal.C"]})
        self.contract["pmi_build_recipe"] = {
            "compile_script": self.ref("inputs/build/compile-in-original-vm.sh"),
            "source": self.ref("inputs/build/pmi_r04_nodal.C"), "headers_sha256": headers}
        self.save("contract.json", self.contract)
        self.policy["scientific_gate"]["contract"] = self.ref("contract.json")
        self.task = dict(self.task, backend="geant4", project="inputs/build")
        self.save("build-diagnostic.json", {
            "schema": "tcad-r06-diagnostic-plan-v1", "recipe_id": "pmi_build",
            "profile_id": "D0-nominal", "frozen_before_submission": True,
            "acceptance_criteria": "Compile the frozen source in the original VM, never run a solver."})
        self.admission.update(
            backend="geant4", project="inputs/build", recipe_id="pmi_build",
            input_sha256=gate.input_hashes(project), diagnostic_plan=self.ref("build-diagnostic.json"))
        self.save("p0/" + self.task["id"] + ".json", self.admission)
        self.assertEqual(self.verify()["recipe_id"], "pmi_build")
        (project / "task.sh").write_text(gate.BUILD_TASK + "echo unapproved\n", encoding="utf-8")
        self.admission["input_sha256"] = gate.input_hashes(project)
        self.save("p0/" + self.task["id"] + ".json", self.admission)
        with self.assertRaises(gate.Pending):
            self.verify()

    def test_formal_case_claim_requires_explicit_repair_lineage(self):
        self.production()
        first = self.verify()
        intents = {"previous-task": {"scientific_admission": first, "repair_of": None}}
        with self.assertRaises(gate.Pending):
            gate.verify(self.root, self.policy, self.task, intents=intents)
        repaired = dict(self.task, repair_of="previous-task")
        self.assertEqual(gate.verify(self.root, self.policy, repaired, intents=intents)["case_id"],
                         "r06-t-d0")
        foreign = copy.deepcopy(first)
        foreign["case_id"] = foreign["scientific_object"]["case_id"] = "another-formal-case"
        with self.assertRaisesRegex(gate.Pending, "parent's exact scientific object"):
            gate.verify(self.root, self.policy, repaired, intents={
                "previous-task": {"scientific_admission": foreign, "repair_of": None}})

    def test_sampling_cell_allocation_and_unique_case_draw_mapping(self):
        case = dict(self.manifest["cases"][0], block="S", statistics_intent=True)
        another = dict(case, case_id="r06-s-second")
        manifest = dict(self.manifest, cases=[case, another])
        selected = {"selection_sha256": "1" * 64,
                    "design": {"method": "stratified", "q": 2, "b0_count": 0},
                    "draws": [{"event_id": "A", "stored_bit": 1},
                              {"event_id": "B", "stored_bit": 1}]}
        mapping = dict(self.envelope, schema="tcad-r06-cell-case-binding-v1",
                       block="S", profile_id=case["profile_id"], radiation_id=case["radiation_id"],
                       manifest_sha256=self.contract["manifest"]["sha256"],
                       selection_sha256=selected["selection_sha256"],
                       case_draws=[{"case_id": case["case_id"], "event_id": "A", "stored_bit": 1},
                                   {"case_id": another["case_id"], "event_id": "B", "stored_bit": 1}])
        self.save("draw-map.json", mapping)
        admission = {"case_draw_map": self.ref("draw-map.json"), "event_id": "A"}
        gate.case_draw_binding(self.root, self.contract, manifest, admission, case, selected)
        selected["design"]["q"] = 1
        with self.assertRaises(gate.Pending):
            gate.case_draw_binding(self.root, self.contract, manifest, admission, case, selected)
        selected["design"]["q"] = 2
        mapping["case_draws"][1]["event_id"] = "A"
        self.save("draw-map.json", mapping)
        admission["case_draw_map"] = self.ref("draw-map.json")
        with self.assertRaises(gate.Pending):
            gate.case_draw_binding(self.root, self.contract, manifest, admission, case, selected)


class RuntimeAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RuntimeTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_invalid_enabled_gate_creates_no_intent_or_runner_call(self):
        f = self.fixture
        f.task("r06-new-input")
        f.policy["scientific_gate"] = {}
        engine = f.engine()
        observation = engine.tick()
        self.assertFalse(engine.intents)
        self.assertEqual(f.calls, [])
        self.assertEqual(observation["pending_tasks"][0]["reason"], "scientific_gate_pending")

    def test_existing_intent_reconciles_when_new_submissions_are_gated(self):
        f = self.fixture
        f.task("old-submitted")
        engine = f.engine()
        engine.tick()
        previous = copy.deepcopy(engine.intents)
        engine.policy["scientific_gate"] = {}
        f.task("r06-new-input")
        observation = engine.tick()
        self.assertEqual(set(engine.intents), {"old-submitted"})
        self.assertEqual(engine.intents["old-submitted"]["task_digest"],
                         previous["old-submitted"]["task_digest"])
        self.assertTrue(any(command[1] == "status" for command in f.calls))
        self.assertTrue(any(item["reason"] == "scientific_gate_pending"
                            for item in observation["pending_tasks"]))

    def test_verified_unlaunched_is_failed_terminal_not_collected_or_success(self):
        f = self.fixture
        f.task("old-transport", backend="geant4")
        engine = f.engine()
        engine.tick()
        intent = engine.intents["old-transport"]
        path = f.record_path("geant4", intent["run_id"])
        record = fixtures.runtime.read_json(path)
        record["state"] = "FAILED_BEFORE_LAUNCH"
        f.save(path, record)
        f.calls.clear()
        with patch.object(engine, "_unlaunched", return_value=True):
            observation = engine.tick(allow_submit=False)
        view = observation["runs"][0]
        self.assertEqual(observation["active_count"], 0)
        self.assertFalse(view["success"])
        self.assertFalse(view["collected"])
        self.assertTrue(view["terminal_reconciled"])
        self.assertEqual(f.calls, [])
        self.assertEqual(observation["repair_requests"][0]["reason"], "original_run_failed_unlaunched")

    def test_policy_gate_changes_execution_binding(self):
        controller = load("r06_controller_binding_tested", "controller.py")
        self.assertNotEqual(controller.binding({}),
                            controller.binding({"scientific_gate": {}}))


if __name__ == "__main__":
    unittest.main()
