# -*- coding: utf-8 -*-
"""Contract tests for the local r0.6 planning manifest."""

from collections import Counter
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_r06_case_manifest.py"
spec = importlib.util.spec_from_file_location("build_r06_case_manifest", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class TestR06Manifest(unittest.TestCase):
    def setUp(self):
        self.data = module.build("2026-11-17T00:00:00Z", module.budget_sha())

    def test_budget_and_block_counts(self):
        self.assertEqual(len(self.data["cases"]), 396)
        self.assertEqual(
            {b["id"]: b["case_count"] for b in self.data["blocks"]},
            {"Z": 26, "T": 68, "S": 150, "R": 12, "HR": 28, "HP": 30, "AL": 82},
        )
        self.assertEqual(sum(c["statistics_eligible"] for c in self.data["cases"]), 0)
        self.assertEqual(sum(c["statistics_intent"] for c in self.data["cases"]), 214)
        self.assertEqual(sum(c["selection_mechanism"] == "threshold_scaled" for c in self.data["cases"]), 74)
        self.assertEqual(sum(c["selection_mechanism"] == "active_learning" for c in self.data["cases"]), 82)

    def test_profile_geometry_and_axiswise_sparse_holdouts(self):
        self.assertEqual(len(self.data["profiles"]), 13)
        self.assertEqual(len(self.data["radiations"]), 10)
        self.assertEqual(len([p for p in self.data["profiles"] if p["partition"] == "development"]), 10)
        self.assertEqual(len([p for p in self.data["profiles"] if p["partition"] == "profile_holdout"]), 3)
        self.assertEqual(self.data["lhs_evidence"]["seed"], 20261117)
        self.assertTrue(self.data["lhs_evidence"]["anchor_aware"])
        evidence = self.data["lhs_evidence"]["axiswise_sparse_holdout_evidence"]
        self.assertGreater(evidence["min_normalized_interior_margin"], 0.0)
        self.assertEqual(evidence["support_geometry"], "axiswise_development_bounding_box")
        self.assertFalse(evidence["convex_hull_verified"])
        for profile in self.data["profiles"]:
            vals = {k: v["value"] for k, v in profile["parameters"].items()}
            self.assertTrue(module.geometry_domain_ok(vals), profile["id"])

    def test_existing_case_ids_coordinates_and_allocations_are_preserved(self):
        existing = json.loads(module.OUTPUT.read_text(encoding="utf-8"))
        self.assertEqual(
            {p["id"]: p["parameters"] for p in self.data["profiles"]},
            {p["id"]: p["parameters"] for p in existing["profiles"]},
        )
        frozen = ("case_id", "block", "profile_id", "radiation_id", "stored_bit",
                  "pair_id", "sample_index", "scale_factor", "source_time_ns", "split")
        self.assertEqual(
            [{key: case[key] for key in frozen} for case in self.data["cases"]],
            [{key: case[key] for key in frozen} for case in existing["cases"]],
        )

    def test_timing_and_statistics_boundaries(self):
        self.assertFalse(self.data["timing_contract"]["p0_user_review_required"])
        self.assertTrue(self.data["timing_contract"]["execution_authorized"])
        self.assertTrue(self.data["timing_contract"]["p0_evidence_required"])
        self.assertEqual(self.data["timing_contract"]["source_time_status"],
                         "candidate_pending_p0_evidence")
        responses = [c for c in self.data["cases"] if c["kind"] == "response"]
        self.assertTrue(all(c["source_time_ns"] == 22.0 for c in responses))
        self.assertTrue(all(c["deck_timing_version"] == "r06-hold-window-v1" for c in responses))
        self.assertTrue(all(
            c["statistics_eligible"] is False
            for c in self.data["cases"]
            if c["selection_mechanism"] in {"threshold_scaled", "active_learning"}
        ))
        self.assertTrue(all(c["inclusion_probability"] is not None for c in self.data["cases"] if c["statistics_intent"]))
        self.assertTrue(all(c["statistics_eligible"] is False for c in self.data["cases"] if c["kind"] == "zero"))

    def test_planned_probabilities_and_acceptance_cannot_be_promoted(self):
        for case in self.data["cases"]:
            self.assertFalse(case["statistics_eligible"])
            if case["statistics_intent"]:
                probability = case["inclusion_probability"]
                self.assertIsNone(probability["value"])
                self.assertIsNone(probability["frame_hash"])
                self.assertFalse(probability["frozen_before_sampling"])
                if case["stored_bit"] == 0:
                    self.assertEqual(probability["formula"], "(q_h/N_h)*rho0")
                    self.assertTrue(probability["matched_subset_required"])
                elif case["block"] == "R":
                    self.assertEqual(probability["formula"], "n/N_primary")
        for field, value in (("accepted", True), ("statistics_eligible", True)):
            altered = copy.deepcopy(self.data)
            altered["cases"][100][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.validate(altered, module.budget_sha())

    def test_threshold_radiation_and_al_fixes(self):
        t_cases = [c for c in self.data["cases"] if c["block"] == "T"]
        self.assertTrue(all(c["scale_factor"] > 1.0 for c in t_cases))
        self.assertTrue(all(c["radiation_id"] in {"G0", "C1"} for c in t_cases))
        self.assertTrue(all(c["adaptive_bracketing"] is True for c in t_cases))

        s_b1 = [c for c in self.data["cases"] if c["block"] == "S" and c["stored_bit"] == 1]
        self.assertEqual(len({(c["profile_id"], c["radiation_id"]) for c in s_b1}), 80)
        self.assertEqual(set(Counter(c["radiation_id"] for c in s_b1).values()), {15})

        r_cases = [c for c in self.data["cases"] if c["block"] == "R"]
        self.assertEqual({c["radiation_id"] for c in r_cases}, set(module.DEV_RADIATION_IDS))

        hr_b1 = [c for c in self.data["cases"] if c["block"] == "HR" and c["stored_bit"] == 1]
        self.assertEqual(Counter(c["radiation_id"] for c in hr_b1), {"C2": 12, "C3": 12})

        al_cases = [c for c in self.data["cases"] if c["block"] == "AL"]
        self.assertTrue(all(c["profile_id"] is None and c["radiation_id"] is None and c["crn_group_id"] is None for c in al_cases))

    def test_crn_mapping_and_pair_alignment(self):
        profiles = {p["id"]: p for p in self.data["profiles"]}
        self.assertEqual(profiles["D0-nominal"]["crn_group_id"], profiles["D3-low-acceptor"]["crn_group_id"])
        self.assertNotEqual(profiles["D1-short-channel"]["crn_group_id"], profiles["D0-nominal"]["crn_group_id"])
        self.assertNotEqual(profiles["D2-narrow-fin"]["crn_group_id"], profiles["D0-nominal"]["crn_group_id"])
        dev_crns = {p["crn_group_id"] for p in profiles.values() if p["partition"] == "development"}
        hold_crns = {p["crn_group_id"] for p in profiles.values() if p["partition"] == "profile_holdout"}
        self.assertFalse(dev_crns & hold_crns)

        pairs = {}
        for case in self.data["cases"]:
            if case["pair_id"] is not None:
                pairs.setdefault(case["pair_id"], []).append(case)
        self.assertEqual(len(pairs), 13 + 30 + 4 + 6)
        for pair_id, members in pairs.items():
            self.assertEqual(len(members), 2, pair_id)
            self.assertEqual({m["stored_bit"] for m in members}, {0, 1}, pair_id)
            self.assertEqual(members[0]["profile_id"], members[1]["profile_id"], pair_id)
            self.assertEqual(members[0]["radiation_id"], members[1]["radiation_id"], pair_id)

    def test_anchor_aware_maximin_beats_random_lhs_reference(self):
        bounds = module.LHS_BOUNDS
        anchors = module.anchor_points()
        selected, evidence = module.maximin_lhs(6, bounds, module.LOG_AXES, seed=20261117, candidates=10000, anchors=anchors)
        random_scores = module.random_lhs_scores(200, 6, bounds, module.LOG_AXES, seed=7, anchors=anchors)
        random_scores.sort()
        q95 = random_scores[int(0.95 * len(random_scores)) - 1]
        self.assertEqual(evidence["min_pairwise_distance"], module.min_pairwise_distance(selected, bounds, module.LOG_AXES, anchors=anchors))
        self.assertGreaterEqual(evidence["min_pairwise_distance"], q95)


if __name__ == "__main__":
    unittest.main()
