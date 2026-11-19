"""Synthetic probability tables only; no solver or fitted native model is used."""
from __future__ import annotations

import copy
import math
import unittest

from dram_predictor.aggregation import aggregate_condition, mix_cross_sections, rate_from_flux


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


if __name__ == "__main__":
    unittest.main()
