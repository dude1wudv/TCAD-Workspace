"""Offline failure-path checks for the frozen S2 first-four review package.

Synthetic arrays and temporary package copies are adversarial unit fixtures only;
they are never represented as native results or qualification evidence.
"""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
S2 = HERE.parent
ROOT = S2.parents[2]
PACKAGE = Path(os.environ.get("S2_REVIEW_PACKAGE", str(ROOT / "local_runtime/dram-see-v4/s2-inputs-r1/20261016T050606Z/packages-r2"))).resolve()
RUN = PACKAGE.parent
MODEL_PATH = ROOT / "experiments/dram-see-v4/course-plan-r13/model-contract.proposed.json"
BUDGET_PATH = ROOT / "experiments/dram-see-v4/course-plan-r13/budget.proposed.json"
sys.path.insert(0, str(S2))

import alpha
import decks
import field_audit
import geometry
import mesh_resource_guard
import metrics
import prepare


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class S2FirstFourReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = read_json(MODEL_PATH)
        cls.preparation = read_json(PACKAGE / "preparation.json")
        cls.budget = read_json(PACKAGE / "budget.proposed.json")

    def test_preparation_code_hashes_bind_review_package_to_frozen_source(self):
        for name, expected in self.preparation["code_sha256"].items():
            actual = hashlib.sha256((S2 / name).read_bytes()).hexdigest()
            self.assertEqual(actual, expected, name)
        self.assertEqual(self.preparation["model_sha256"], decks.PARENT_MODEL_SHA256)
        self.assertEqual(self.preparation["budget_proposal_sha256"],
                         hashlib.sha256(BUDGET_PATH.read_bytes()).hexdigest())

    def test_exact_first_four_are_review_only_source_free_and_have_no_fake_mesh(self):
        expected = ["B1-D2", "B1-D3", "B1-A0-main-b0", "B1-A0-main-b1"]
        self.assertEqual(list(decks.SCOPE_ROLES), expected)
        self.assertEqual(self.preparation["role_order"], expected)
        self.assertEqual(self.budget["B1_first_slice"]["role_ids"], expected)
        self.assertFalse(self.preparation["execution_enabled"])
        self.assertEqual(self.preparation["native_authorized"], 0)
        self.assertEqual(self.preparation["native_calls"], 0)
        for role in expected:
            folder = PACKAGE / "roles" / role
            self.assertTrue(folder.is_dir())
            self.assertFalse((folder / "project.json").exists())
            self.assertFalse(list(folder.glob("*.tdr")))
            project = read_json(folder / "project.review.json")
            self.assertFalse(project["execution_enabled"])
            device = (folder / "device.cmd").read_text(encoding="utf-8")
            if role.startswith("B1-A0"):
                self.assertNotIn("HeavyIon(", device)
                self.assertNotIn("PMI", device)
                spec = read_json(folder / "source-spec.json")
                self.assertEqual(spec["case"], "A0")
                self.assertFalse(spec["source_configured"])
                self.assertEqual(spec["amplitude"], 0.0)
                evidence = read_json(folder / "native-evidence.required.json")
                self.assertFalse(evidence["actual_native_evidence_present"])
                self.assertTrue(evidence["not_a_receipt"])
                self.assertFalse((folder / "native-source-receipt.json").exists())
                self.assertFalse((folder / "field-extraction-record.json").exists())
                # The future read-only field auditor binds these archived source
                # references even for A0, while the device deck remains source-free.
                for required in ("source-contract.json", "alpha-reference.json", "alpha-profile.csv"):
                    archived = folder / required
                    alpha_ref = PACKAGE / "alpha-audit" / required
                    self.assertTrue(archived.is_file(), required)
                    self.assertEqual(hashlib.sha256(archived.read_bytes()).digest(),
                                     hashlib.sha256(alpha_ref.read_bytes()).digest(), required)
            if role in ("B1-D2", "B1-D3"):
                self.assertTrue((folder / "geometry.scm").is_file())
        result = prepare.verify(PACKAGE)
        self.assertEqual(result["status"], "OFFLINE_PACKAGE_INTEGRITY_PASS")
        self.assertFalse(result["native_qualified"])

    def test_both_a0_roles_require_the_same_future_d3_mesh_without_rebuilding(self):
        d3_manifest = hashlib.sha256(
            (PACKAGE / "roles/B1-D3/input-manifest.json").read_bytes()
        ).hexdigest()
        required = []
        for bit in (0, 1):
            folder = PACKAGE / "roles" / f"B1-A0-main-b{bit}"
            mesh = read_json(folder / "mesh-import.required.json")
            project = read_json(folder / "project.review.json")
            required.append(mesh)
            self.assertEqual(mesh["producer_role"], "B1-D3")
            self.assertEqual(mesh["producer_input_manifest_sha256"], d3_manifest)
            self.assertIsNone(mesh["actual_mesh_sha256"])
            self.assertFalse(mesh["resolved"])
            self.assertFalse((folder / "geometry.scm").exists())
            self.assertEqual([s["tool"] for s in project["steps"]], ["sdevice"])
        self.assertEqual(required[0], required[1])

    def test_full_timeline_and_global_half_step_rule(self):
        main = decks.transient_segments(self.model, 1)
        half = decks.transient_segments(self.model, .5)
        expected = [t * 1e-9 for t in decks.TIMING_NS]
        self.assertEqual([main[0]["start_s"]] + [s["end_s"] for s in main], expected)
        self.assertAlmostEqual(main[-1]["end_s"], 25e-9, places=22)
        self.assertEqual(len(main), len(half))
        self.assertTrue(all(math.isclose(h["max_step_s"], m["max_step_s"] / 2, rel_tol=0, abs_tol=0)
                            for m, h in zip(main, half)))
        pulse = [s for s in main if s["source_window"]]
        self.assertEqual(len(pulse), 1)
        self.assertEqual(pulse[0]["max_step_s"], .04e-12)
        self.assertEqual([s["max_step_s"] for s in half if s["source_window"]], [.02e-12])
        self.assertEqual(decks.transient_segments(self.model)[0]["start_s"], 0)
        with self.assertRaises(ValueError):
            decks.transient_segments(self.model, .25)

    def test_write_uses_access_transistor_after_common_clamp_is_released(self):
        for bit, expected_drive in ((0, "0"), (1, "1.2")):
            deck = decks.render_transient(self.model, bit)
            clamp = deck.index("Set(sn=0.6)")
            release = deck.index("Unset(sn)")
            write = deck.index("Cell access (\"source\"=sn \"drain\"=bl")
            first_transient = deck.index("Transient(")
            self.assertLess(clamp, release)
            self.assertLess(release, first_transient)
            self.assertLess(write, first_transient)
            self.assertIn(f"Vsource_pset vdrive (drive 0) {{pwl=(0 {expected_drive} ", deck)
            self.assertIn("20e-9 -0.5 20.1e-9 1.8", deck)
            self.assertNotIn("Set(sn=0.12)", deck)
            self.assertNotIn("Set(sn=1.08)", deck)

    def test_physics_hashes_and_units_are_bound_in_packages(self):
        expected_cards = decks.MATERIAL_HASHES
        for role in decks.SCOPE_ROLES:
            folder = PACKAGE / "roles" / role
            physics = read_json(folder / "physics-manifest.json")
            self.assertEqual(physics["default_cards_sha256"], expected_cards)
            for card, digest in expected_cards.items():
                actual = hashlib.sha256((folder / card).read_bytes()).hexdigest()
                self.assertEqual(actual, digest)
            self.assertFalse(physics["native_syntax_verified"])
            self.assertFalse(physics["native_calibration"])
            self.assertFalse(physics["execution_enabled"])
            geom = read_json(folder / "geometry-contract.json")
            self.assertEqual(geom["length_unit"], "um")
            self.assertEqual(geom["doping"]["donor_species"], "ArsenicActiveConcentration")
            self.assertEqual(geom["doping"]["acceptor_species"], "BoronActiveConcentration")
            self.assertEqual(geom["measure_unit"], "um^2" if role == "B1-D2" else "um^3")
            role_contract = read_json(folder / "role-contract.json")
            self.assertEqual(role_contract["parent_model_file_sha256"], decks.PARENT_MODEL_SHA256)
        field = read_json(PACKAGE / "alpha-audit/field-contract.json")
        self.assertEqual(field["conversion"]["um3_to_cm3"], 1e-12)
        self.assertEqual(field["conversion"]["C_to_fC"], 1e15)
        alpha_reference = read_json(PACKAGE / "alpha-audit/alpha-reference.json")
        self.assertFalse(alpha_reference["is_tcad_result"])

    def test_alpha_adapter_is_fixed_to_a0_supported_contract_and_table_units(self):
        alpha.validate_model(self.model)
        rows = alpha.load_profile(PACKAGE / "alpha-audit/alpha-profile.csv")
        self.assertEqual(len(rows), 101)
        self.assertTrue(all(row["electronic_pC_um"] > 0 for row in rows))
        for case, bit, variant in (("A0", 0, "main"), ("A0", 1, "main")):
            spec = alpha.source_spec(case, bit, variant)
            self.assertFalse(spec["source_configured"])
            self.assertEqual(spec["matched_A0"], {"stored_bit": bit, "numerical_variant": variant})
            physics, source_par = alpha.render_source(rows, case)
            self.assertNotIn("HeavyIon(", physics)
            self.assertNotIn("LET_f", physics)
            self.assertNotIn("HeavyIon(", source_par)
        physics, source_par = alpha.render_source(rows, "Aalpha")
        self.assertIn("Gaussian PicoCoulomb", physics)
        self.assertIn("LET_f=", physics)
        self.assertIn("Wt_hi=[0.050000000000000003", physics)
        self.assertIn("s_hi = 2.0000000000000001e-13", source_par)
        self.assertEqual(alpha.source_spec("Aalpha", 0, "time")["source_max_step_s"], .02e-12)
        self.assertEqual(alpha.source_spec("Aalpha", 0, "main")["source_max_step_s"], .04e-12)
        with self.assertRaises(ValueError):
            alpha.source_spec("Aalpha", True, "main")

    def test_geometry_and_field_extractor_are_review_only_and_bound(self):
        report = geometry.validate_geometry(self.model)
        self.assertTrue(report["passed"], report["errors"])
        self.assertFalse(report["native_qualified"])
        d3 = geometry.describe_geometry(self.model, 3)
        d2 = geometry.describe_geometry(self.model, 2)
        self.assertEqual(d3["length_unit"], "um")
        self.assertEqual(d2["measure_unit"], "um^2")
        self.assertEqual(d3["measure_unit"], "um^3")
        self.assertAlmostEqual(d3["measures"]["silicon"], .9599273161065788, places=12)
        self.assertEqual(self.preparation["model_sha256"], decks.PARENT_MODEL_SHA256)
        tcl = (S2 / "extract_fields.tcl").read_text(encoding="utf-8")
        for token in ("GROUP_BEFORE", "FRAME_BEFORE", "FRAME_AFTER", "GROUP_AFTER",
                      "field-measurements.csv", "diagnostic-status.txt", "FIELD_AUDIT_COMPLETED"):
            self.assertIn(token, tcl)
        self.assertIn("{WRONLY CREAT EXCL}", tcl)
        self.assertNotIn("exec sdevice", tcl.lower())

    def test_continuous_per_be_kcl_detects_cancelling_integral_counterexample(self):
        data = {
            "time_s": [0.0, 1e-9, 2e-9, 25e-9],
            "v_sn_V": [0.6, 0.6, 0.6, 0.6],
            "v_bl_V": [0.6, 0.6, 0.6, 0.6],
            "i_sn_A": [0.0, 2e-4, -2e-4, 0.0],
        }
        result = metrics.kcl(data)
        self.assertFalse(result["passed"])
        self.assertFalse(result["per_step"][0]["passed"])
        self.assertFalse(result["per_step"][1]["passed"])
        net_integral_fC = math.fsum(row["terminal_integral_fC"] for row in result["per_step"])
        self.assertAlmostEqual(net_integral_fC, 0.0, places=12)

    def test_read_window_is_time_weighted_not_sample_mean_counterexample(self):
        t = [21.9e-9, 21.91e-9, 22e-9]
        v = [.6, 1.2, 1.2]
        _, _, read_mean = metrics.voltage_window(t, v, 21.9e-9, 22e-9)
        sample_mean = math.fsum(v) / len(v)
        self.assertAlmostEqual(read_mean, 1.17, places=12)
        self.assertAlmostEqual(sample_mean, 1.0, places=12)
        self.assertNotAlmostEqual(read_mean, sample_mean)

    def test_changed_parent_model_is_refused(self):
        changed = copy.deepcopy(self.model)
        changed["geometry"]["silicon_domain_nm"]["x"][0] -= 1
        with self.assertRaisesRegex(ValueError, "exact frozen r13 model"):
            decks.validate_model(changed)

    def test_package_tamper_and_missing_file_are_refused(self):
        with tempfile.TemporaryDirectory(prefix="s2-tamper-") as temp:
            altered = Path(temp) / "altered"
            shutil.copytree(PACKAGE, altered)
            target = altered / "roles/B1-D3/device.cmd"
            target.write_text(target.read_text(encoding="utf-8") + "* changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing/changed"):
                prepare.verify(altered)
        with tempfile.TemporaryDirectory(prefix="s2-missing-") as temp:
            missing = Path(temp) / "missing"
            shutil.copytree(PACKAGE, missing)
            (missing / "roles/B1-D3/device.cmd").unlink()
            with self.assertRaisesRegex(ValueError, "missing/changed"):
                prepare.verify(missing)

    def test_unapproved_mesh_guard_fails_closed_before_native_observation(self):
        folder = PACKAGE / "roles/B1-A0-main-b0"
        policy = read_json(folder / "resource-policy.json")
        self.assertFalse(policy["approved"])
        with self.assertRaisesRegex(ValueError, "Review-only/unapproved"):
            mesh_resource_guard.evaluate(policy, 100 * mesh_resource_guard.GIB, 100 * mesh_resource_guard.GIB)
        with self.assertRaisesRegex(ValueError, "Review-only/unapproved"):
            mesh_resource_guard.inspect(folder)

    def test_native_field_audit_refuses_empty_receipts_without_launch(self):
        with tempfile.TemporaryDirectory(prefix="s2-no-native-receipt-") as temp:
            empty = Path(temp)
            result = field_audit.audit_native(empty, empty, PACKAGE / "alpha-audit")
        self.assertFalse(result["passed"])
        self.assertFalse(result["native_qualified"])
        self.assertEqual(result["native_jobs_started"], 0)
        self.assertIn("Native receipt missing", result["errors"][0])
        self.assertEqual(field_audit.validate_spec(alpha.source_spec("A0", 0, "main"))["case"], "A0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
