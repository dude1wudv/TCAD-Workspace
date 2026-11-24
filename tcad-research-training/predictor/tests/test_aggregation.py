"""Synthetic probability tables and r0.6 sampling receipts."""
from __future__ import annotations

import copy
import importlib.util
import math
import unittest
from pathlib import Path

from dram_predictor.aggregation import (
    aggregate_condition,
    estimate_r06_cross_section,
    mix_cross_sections,
    rate_from_flux,
)
from dram_predictor.data import digest


def fixture():
    condition = {
        "condition_id": "synthetic-c", "source_distribution": "uniform",
        "area_normalization_validated": True, "source_area_cm2": 4e-8,
        "n_bits": 2, "primary_count": 2,
        "bits": [
            {"bit_id": "a", "x_nm": 0., "y_nm": 0., "z_nm": 0.},
            {"bit_id": "b", "x_nm": 10., "y_nm": 0., "z_nm": 0.},
        ],
    }
    primaries = [
        {
            "primary_id": f"p{i}", "condition_id": condition["condition_id"],
            "source_primary_id": f"source-{i}", "source_hash": f"synthetic-hash-{i}",
            "pool_member": True, "sampling": "random", "source_off": i == 0,
            "source_features": {"deposited_energy_MeV": float(i)},
        }
        for i in range(2)
    ]
    values = {
        ("p0", 0): [0., 0.], ("p0", 1): [0., 0.],
        ("p1", 0): [0.2, 0.4], ("p1", 1): [0.6, 0.8],
    }
    probabilities = [
        {"primary_id": primary, "state": state, "bit_id": bit, "probability": value}
        for (primary, state), row in values.items()
        for bit, value in zip(("a", "b"), row)
    ]
    return condition, primaries, probabilities


class AggregationTests(unittest.TestCase):
    def test_full_pool_keeps_zero_source_and_does_not_double_state_denominator(self):
        c, primaries, probabilities = fixture()
        result = aggregate_condition(c, primaries, probabilities, provenance={"kind": "synthetic"})
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["n_primaries"], 2)
        self.assertEqual(result["n_source_off_primaries"], 1)
        self.assertEqual(result["n_bits"], 2)
        self.assertAlmostEqual(result["sigma_cm2_per_bit"][0] / c["source_area_cm2"], 0.15)
        self.assertAlmostEqual(result["sigma_cm2_per_bit"][1] / c["source_area_cm2"], 0.35)
        self.assertEqual(result["weights"], [0.25, 0.25])
        self.assertFalse(result["native_truth"])
        self.assertEqual(result["label_kind"], "model_derived_proxy")
        self.assertEqual(result["provenance"], {"kind": "synthetic"})
        self.assertIn("not a full prediction interval", result["uncertainty_scope"])
        self.assertAlmostEqual(
            result["transport_mc_standard_error_cm2_per_bit"][0] / c["source_area_cm2"], 0.15
        )

    def test_missing_primary_is_pending_not_a_shrunk_denominator(self):
        c, primaries, probabilities = fixture()
        result = aggregate_condition(c, primaries[1:], probabilities)
        self.assertEqual(result["status"], "pending")
        self.assertIn("incomplete primary pool", result["reason"])
        self.assertNotIn("sigma_cm2_per_bit", result)

    def test_missing_event_bit_or_state_is_not_filled_with_zero(self):
        c, primaries, probabilities = fixture()
        for reduced in (
            probabilities[1:],
            [p for p in probabilities if p["state"] == 0],
            [p for p in probabilities if p["primary_id"] == "p1"],
            [p for p in probabilities if p["bit_id"] == "a"],
        ):
            result = aggregate_condition(c, primaries, reduced)
            self.assertEqual(result["status"], "pending")
            self.assertNotIn("sigma_cm2_per_bit", result)
            self.assertIn("missing is not a zero", result["reason"])

    def test_explicit_proxy_state_subset_keeps_fixed_state_positions(self):
        c, primaries, probabilities = fixture()
        full = aggregate_condition(c, primaries, probabilities, probability_status="calibrated")
        for state in (0, 1):
            with self.subTest(state=state):
                rows = [row for row in probabilities if row["state"] == state]
                result = aggregate_condition(c, primaries, rows, states=(state,), probability_status="calibrated")
                self.assertEqual(result["status"], "ready")
                for key in ("sigma_cm2_per_bit", "weights", "transport_mc_standard_error_cm2_per_bit"):
                    self.assertEqual(result[key][state], full[key][state])
                    self.assertIsNone(result[key][1 - state])
                self.assertEqual(aggregate_condition(c, primaries, rows[1:], states=(state,))["status"], "pending")
        for states in ((), (0, 0), (True,), (1.0,), (2,)):
            with self.subTest(states=states):
                result = aggregate_condition(c, primaries, probabilities, states=states)
                self.assertEqual(result["status"], "pending")
                self.assertNotIn("sigma_cm2_per_bit", result)

    def test_area_unverified_nonuniform_or_missing_positions_remain_pending(self):
        for patch in (
            {"area_normalization_validated": False, "simulation_dimension": "2D"},
            {"source_distribution": "importance_sampled"},
            {"source_area_cm2": 0.0},
            {"bits": [{"bit_id": "a"}, {"bit_id": "b"}]},
            {"n_bits": 3},
        ):
            c, primaries, probabilities = fixture()
            c.update(patch)
            result = aggregate_condition(c, primaries, probabilities)
            self.assertEqual(result["status"], "pending")
            self.assertNotIn("sigma_cm2_per_bit", result)

    def test_out_of_pool_enrichment_excluded_but_in_pool_enrichment_retained(self):
        c, primaries, probabilities = fixture()
        primaries[1]["sampling"] = "enriched"
        extra = copy.deepcopy(primaries[1])
        extra.update(primary_id="extra", source_primary_id="extra-source", pool_member=False)
        primaries.append(extra)
        probabilities.append({"primary_id": "extra", "state": 0, "bit_id": "a", "probability": 1.0})
        result = aggregate_condition(c, primaries, probabilities)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["n_primaries"], 2)
        self.assertAlmostEqual(result["sigma_cm2_per_bit"][0], 6e-9)
        self.assertEqual(result["aggregation_audit"]["excluded_nonpool_primary_ids"], ["extra"])
        self.assertEqual(result["aggregation_audit"]["ignored_probability_primary_ids"], ["extra"])

    def test_original_source_aliases_count_once_and_conflicts_rejected(self):
        c, primaries, probabilities = fixture()
        duplicate = copy.deepcopy(primaries[1])
        duplicate["primary_id"] = "p1-alias"
        primaries.append(duplicate)
        alias_predictions = [
            {**p, "primary_id": "p1-alias"} for p in probabilities if p["primary_id"] == "p1"
        ]
        result = aggregate_condition(c, primaries, probabilities + alias_predictions)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["n_primaries"], 2)
        self.assertEqual(result["aggregation_audit"]["duplicate_source_alias_count"], 1)
        alias_predictions[0]["probability"] = 0.99
        result = aggregate_condition(c, primaries, probabilities + alias_predictions)
        self.assertEqual(result["status"], "pending")
        self.assertIn("conflicting probabilities", result["reason"])
        duplicate["source_hash"] = "different-source"
        result = aggregate_condition(c, primaries, probabilities)
        self.assertEqual(result["status"], "pending")
        self.assertIn("conflicting source provenance", result["reason"])

    def test_invalid_probabilities_are_not_clipped(self):
        for invalid in (float("nan"), float("inf"), -0.01, 1.01, True, None):
            c, primaries, probabilities = fixture()
            probabilities[0]["probability"] = invalid
            result = aggregate_condition(c, primaries, probabilities)
            self.assertEqual(result["status"], "pending")
            self.assertNotIn("sigma_cm2_per_bit", result)

    def test_calibrated_proxy_remains_proxy(self):
        c, primaries, probabilities = fixture()
        result = aggregate_condition(c, primaries, probabilities, probability_status="calibrated")
        self.assertEqual(result["weights"], [1., 1.])
        self.assertFalse(result["native_truth"])
        self.assertEqual(result["label_kind"], "model_derived_proxy")

    def test_single_primary_has_no_estimated_standard_error(self):
        c, primaries, probabilities = fixture()
        c["primary_count"] = 1
        result = aggregate_condition(c, primaries[:1], probabilities)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["sigma_cm2_per_bit"], [0., 0.])
        self.assertEqual(result["transport_mc_standard_error_cm2_per_bit"], [None, None])

    def test_other_condition_is_ignored_and_inputs_are_not_mutated(self):
        c, primaries, probabilities = fixture()
        primaries.append({"condition_id": "another", "primary_id": "different"})
        before = copy.deepcopy((c, primaries, probabilities))
        result = aggregate_condition(c, {p["primary_id"]: p for p in primaries}, probabilities)
        self.assertEqual(result["status"], "ready")
        self.assertEqual((c, primaries, probabilities), before)


class RateTests(unittest.TestCase):
    def test_state_mixture_and_integrated_spectral_rate(self):
        self.assertAlmostEqual(mix_cross_sections([2e-8, 6e-8], [0.75, 0.25]), 3e-8)
        rate = rate_from_flux([[2e-8, 6e-8], [1e-8, 5e-8]], [0.75, 0.25], [100., 200.])
        self.assertAlmostEqual(rate, 7e-6)

    def test_missing_flux_has_no_rate(self):
        self.assertIsNone(rate_from_flux([[0., 2e-8]], [0.5, 0.5], None))
        self.assertEqual(mix_cross_sections([0., 2e-8], [0.5, 0.5]), 1e-8)
        self.assertEqual(rate_from_flux([[0., 2e-8]], [0.5, 0.5], [0.]), 0.)

    def test_explicit_units_checked_and_differential_flux_rejected(self):
        sigma = {"values": [[2e-8, 6e-8]], "unit": "cm2/bit"}
        flux = {"values": [100.], "unit": "cm^-2 s^-1"}
        self.assertAlmostEqual(rate_from_flux(sigma, [0.75, 0.25], flux), 3e-6)
        with self.assertRaises(ValueError):
            rate_from_flux(sigma, [0.75, 0.25], {**flux, "unit": "cm^-2 s^-1 MeV^-1"})
        with self.assertRaises(ValueError):
            mix_cross_sections({"values": [1., 2.], "unit": "m2/bit"}, [0.5, 0.5])

    def test_invalid_lengths_weights_or_flux_are_rejected(self):
        cases = (
            ([[1., 2.]], [1., 1.], [1.]),
            ([[1., 2.]], [-0.5, 1.5], [1.]),
            ([[1., 2.]], [0.5, 0.5], [-1.]),
            ([[1., 2.]], [0.5, 0.5], [math.nan]),
            ([[1., 2.]], [0.5, 0.5], [1., 2.]),
            ([[1., 2., 3.]], [0.5, 0.5], [1.]),
            ([], [0.5, 0.5], []),
        )
        for sigma, weights, flux in cases:
            with self.assertRaises(ValueError):
                rate_from_flux(sigma, weights, flux)


class R06DesignEstimationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script = Path(__file__).resolve().parents[2] / "scripts" / "r06_sampling.py"
        spec = importlib.util.spec_from_file_location("r06_sampling", script)
        cls.sampling = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.sampling)

    def receipt(self, *, block="S", q=2, b0_count=0, one_stratum=False):
        frame = {
            "schema": "r06-primary-frame-v1", "frame_id": "test-frame",
            "transport_run_id": "test-transport", "transport_input_sha256": "a" * 64,
            "response_context_sha256": "b" * 64, "complete_primary_ledger_verified": True,
            "frame_evidence_sha256": "c" * 64, "condition": {"profile_id": "D0", "radiation_id": "G0"},
            "N_primary": 8, "source_area_cm2": 2.0,
            "events": [{"event_id": str(i), "deposition_energy_eV": i} for i in range(8)],
        }
        if not one_stratum:
            for event in frame["events"]:
                event["coarse_stratum"] = "low" if event["deposition_energy_eV"] < 2 else "high"
        selection = self.sampling.select(
            frame, q, 12, expected_frame_sha256=self.sampling.digest(frame),
            method="simple_random" if block == "R" else "stratified", b0_count=b0_count,
        )
        binding = {
            "schema": "tcad-r06-cell-case-binding-v1",
            **selection["condition"], "block": block, "manifest_sha256": "d" * 64,
            "selection_sha256": selection["selection_sha256"],
            "case_draws": [
                {"event_id": row["event_id"], "stored_bit": row["stored_bit"], "case_id": f"{block}-{i}"}
                for i, row in enumerate(selection["draws"])
            ],
        }
        return selection, binding

    def labels(self, selection, binding, bit=1):
        return [
            {
                **case, "selection_sha256": selection["selection_sha256"], "y": 1,
                "status": "accepted", "accepted": True, "scientific_acceptance": "accepted",
                "acceptance_evidence_sha256": "e" * 64, "statistics_eligible": True,
                "selection_mechanism": "simple_random" if binding["block"] == "R" else "stratified_pi",
                "scale_factor": 1.0, "stratum_id": draw["stratum_id"],
                "inclusion_probability": draw["inclusion_probability"],
            }
            for draw, case in zip(selection["draws"], binding["case_draws"]) if draw["stored_bit"] == bit
        ]

    def estimate(self, selection, binding, labels, bit=1, **kwargs):
        options = {"expected_selection_sha256": selection["selection_sha256"],
                   "area_normalization_validated": True, **kwargs}
        return estimate_r06_cross_section(selection, binding, labels, stored_bit=bit, **options)

    def test_srs_uses_n_over_n_primary_and_finite_population_variance(self):
        selection, binding = self.receipt(block="R")
        labels = self.labels(selection, binding)
        labels[0]["y"] = 0
        result = self.estimate(selection, binding, labels)
        self.assertEqual(result["cross_section_cm2_per_observed_bit"], 1.0)
        self.assertEqual(result["design_variance_cm4_per_observed_bit_squared"], 0.75)
        self.assertIsNone(result["variance_unavailable_reason"])
        self.assertEqual(result["block"], "R")
        self.assertEqual(result["stored_bit"], 1)
        self.assertEqual(result["N_primary"], 8)
        self.assertEqual(result["selected_primary_count"], 2)
        self.assertEqual(result["selection_sha256"], selection["selection_sha256"])
        self.assertEqual(result["response_context_sha256"], selection["response_context_sha256"])
        self.assertEqual([row["inclusion_probability"] for row in result["selected_draws"]], [0.25, 0.25])

    def test_stratified_blocks_use_unequal_weights_and_report_singleton_variance(self):
        for block in ("S", "HR", "HP"):
            with self.subTest(block=block):
                selection, binding = self.receipt(block=block)
                labels = self.labels(selection, binding)
                for row in labels:
                    row["y"] = int(row["inclusion_probability"] < 0.5)
                result = self.estimate(selection, binding, labels[::-1])
                self.assertEqual(result["cross_section_cm2_per_observed_bit"], 1.5)
                self.assertEqual(result["block"], block)
                self.assertIsNone(result["design_variance_cm4_per_observed_bit_squared"])
                self.assertIn("fewer than two", result["variance_unavailable_reason"])

    def test_b0_uses_unconditional_product_even_if_subset_misses_a_stratum(self):
        selection, binding = self.receipt(q=2, b0_count=1)
        labels = self.labels(selection, binding, bit=0)
        draw = next(row for row in selection["draws"] if row["stored_bit"] == 0)
        result = self.estimate(selection, binding, labels, bit=0)
        layer = next(h for h in selection["design"]["strata"] if h["stratum_id"] == draw["stratum_id"])
        self.assertEqual(result["cross_section_cm2_per_observed_bit"], 2.0 * layer["N_h"] / 4)
        self.assertEqual(result["conditional_b0_probability"], 0.5)
        self.assertEqual(result["selected_draws"][0]["inclusion_probability"], 0.5 / layer["N_h"])
        self.assertIsNone(result["design_variance_cm4_per_observed_bit_squared"])
        self.assertIn("joint inclusion", result["variance_unavailable_reason"])
        with self.assertRaisesRegex(ValueError, "missing selected outcomes"):
            self.estimate(selection, binding, [], bit=0)
        labels[0]["statistics_eligible"] = False
        with self.assertRaisesRegex(ValueError, "statistical eligibility"):
            self.estimate(selection, binding, labels, bit=0)

    def test_b0_one_stratum_is_marginally_simple_random(self):
        selection, binding = self.receipt(q=4, b0_count=2, one_stratum=True)
        labels = self.labels(selection, binding, bit=0)
        labels[0]["y"] = 0
        result = self.estimate(selection, binding, labels, bit=0)
        self.assertEqual(result["cross_section_cm2_per_observed_bit"], 1.0)
        self.assertEqual(result["design_variance_cm4_per_observed_bit_squared"], 0.75)

    def test_absent_state_and_missing_zero_deposition_outcome_raise(self):
        selection, binding = self.receipt(q=8)
        with self.assertRaisesRegex(ValueError, "no allocated sample"):
            self.estimate(selection, binding, [], bit=0)
        labels = self.labels(selection, binding)
        with self.assertRaisesRegex(ValueError, "missing selected outcomes"):
            self.estimate(selection, binding, [row for row in labels if row["event_id"] != "0"])
        for row in labels:
            row["y"] = 0
        result = self.estimate(selection, binding, labels)
        self.assertEqual(result["cross_section_cm2_per_observed_bit"], 0)
        self.assertEqual(result["design_variance_cm4_per_observed_bit_squared"], 0)

    def test_requires_verified_area_and_supported_block(self):
        selection, binding = self.receipt()
        labels = self.labels(selection, binding)
        with self.assertRaisesRegex(ValueError, "source-area normalization"):
            self.estimate(selection, binding, labels, area_normalization_validated=False)
        for block in ("AL", "T", "Z"):
            with self.subTest(block=block), self.assertRaisesRegex(ValueError, "requires block"):
                self.estimate(selection, {**binding, "block": block}, labels)
        with self.assertRaisesRegex(ValueError, "sampling method"):
            self.estimate(selection, {**binding, "block": "R"}, labels)

    def test_rejects_adaptive_threshold_control_and_invalid_labels(self):
        selection, binding = self.receipt(block="HP")
        labels = self.labels(selection, binding)
        for changes in (
            {"selection_mechanism": "active_learning"}, {"selection_mechanism": "threshold_scaled"},
            {"selection_mechanism": "no_particle_control"}, {"scale_factor": 3.0},
            {"status": "pending"}, {"accepted": False}, {"scientific_acceptance": "pending"},
            {"acceptance_evidence_sha256": None}, {"statistics_eligible": False},
            {"y": True}, {"y": 1.0}, {"y": None}, {"y": 2},
            {"event_id": "other"}, {"selection_sha256": "f" * 64},
            {"stored_bit": 0}, {"case_id": "foreign"}, {"stratum_id": "other"}, {"inclusion_probability": 1.0},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.estimate(selection, binding, [{**labels[0], **changes}, *labels[1:]])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.estimate(selection, binding, [*labels, labels[0]])

    def test_rejects_changed_selection_even_if_rehashed(self):
        selection, binding = self.receipt()
        labels = self.labels(selection, binding)
        pin = selection["selection_sha256"]
        selection["draws"][0]["event_id"] = "swapped"
        with self.assertRaisesRegex(ValueError, "contents differ"):
            self.estimate(selection, binding, labels)
        selection.pop("selection_sha256")
        selection["selection_sha256"] = binding["selection_sha256"] = digest(selection)
        with self.assertRaisesRegex(ValueError, "SHA differs"):
            self.estimate(selection, binding, labels, expected_selection_sha256=pin)

    def test_rejects_incomplete_or_inconsistent_frozen_design(self):
        for change, reason in (
            (lambda s: s.update(N_primary=9), "complete denominator"),
            (lambda s: s["design"]["strata"][0].update(q_h=0), "q_h"),
            (lambda s: s["draws"].pop(), "incomplete stratum draws"),
            (lambda s: s["draws"][0].update(inclusion_probability=1.0), "differs from the design"),
            (lambda s: s["draws"][0].update(conditional_b0_probability=1.0), "differs from the design"),
            (lambda s: s["draws"][0].update(stratum_id="other"), "mis-stratified"),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                selection, binding = self.receipt()
                change(selection)
                selection.pop("selection_sha256")
                selection["selection_sha256"] = binding["selection_sha256"] = digest(selection)
                self.estimate(selection, binding, [])
        selection, binding = self.receipt()
        binding["case_draws"].pop()
        with self.assertRaisesRegex(ValueError, "incomplete or duplicate case/draw"):
            self.estimate(selection, binding, [])


if __name__ == "__main__":
    unittest.main()
