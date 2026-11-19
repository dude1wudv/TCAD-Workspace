"""Synthetic software fixtures only; no transport or scientific acceptance claim."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("r06_sampling", ROOT / "scripts/r06_sampling.py")
sampling = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sampling)


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.frame = {
            "schema": "r06-primary-frame-v1", "frame_id": "SOFTWARE_FIXTURE",
            "transport_run_id": "synthetic-transport-not-real",
            "transport_input_sha256": "a" * 64,
            "response_context_sha256": "d" * 64,
            "complete_primary_ledger_verified": True,
            "frame_evidence_sha256": "b" * 64,
            "condition": {"profile_id": "D0-nominal", "radiation_id": "G0"},
            "N_primary": 10, "source_area_cm2": 2.0,
            "events": [
                {"event_id": str(i), "deposition_energy_eV": 0.0 if i < 4 else float(i),
                 "coarse_stratum": "raw" + str(i // 2)}
                for i in range(10)
            ],
        }

    def draw(self, q=3, seed=20261117, **kwargs):
        return sampling.select(self.frame, q, seed,
                               expected_frame_sha256=sampling.digest(self.frame), **kwargs)

    def labels(self, selection, bit=1, y=1):
        return [{
            "selection_sha256": selection["selection_sha256"],
            "event_id": row["event_id"], "stored_bit": bit,
            "status": "accepted", "accepted": True, "scientific_acceptance": "accepted",
            "acceptance_evidence_sha256": "c" * 64, "y": y,
        } for row in selection["draws"] if row["stored_bit"] == bit]

    def test_small_q_merges_partition_with_full_frame_positive_support(self):
        for q in (1, 2, 3, 7, 10):
            selection = self.draw(q)
            layers = selection["design"]["strata"]
            self.assertLessEqual(len(layers), q)
            self.assertEqual(sum(h["N_h"] for h in layers), 10)
            self.assertEqual(sum(h["q_h"] for h in layers), q)
            ids = [event_id for h in layers for event_id in h["event_ids"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(set(ids), {str(i) for i in range(10)})
            self.assertTrue(all(1 <= h["q_h"] <= h["N_h"] for h in layers))
            self.assertFalse(selection["statistics_eligible"])
            self.assertIsNone(selection["scientific_labels"])
            for row in selection["draws"]:
                layer = next(h for h in layers if h["stratum_id"] == row["stratum_id"])
                self.assertEqual(row["inclusion_probability"], layer["q_h"] / layer["N_h"])
            sampling.validate_selection(self.frame, selection)

    def test_q1_is_full_frame_uniform_not_a_fine_layer(self):
        selected = set()
        for seed in range(100):
            selection = self.draw(1, seed)
            self.assertEqual(len(selection["design"]["strata"]), 1)
            self.assertEqual(selection["design"]["strata"][0]["N_h"], 10)
            self.assertEqual(selection["draws"][0]["pi1"], 0.1)
            selected.add(selection["draws"][0]["event_id"])
        self.assertEqual(selected, {str(i) for i in range(10)})

    def test_srs_is_n_over_n_and_ignores_predeclared_strata(self):
        selection = self.draw(3, method="simple_random")
        self.assertEqual(len(selection["design"]["strata"]), 1)
        self.assertTrue(all(row["inclusion_probability"] == 0.3 for row in selection["draws"]))
        labels = self.labels(selection)
        labels[0]["y"] = 0
        ht = sampling.estimate(self.frame, selection, labels, estimator="ht")
        ordinary = sampling.estimate(self.frame, selection, labels, estimator="srs")
        self.assertAlmostEqual(ht["cross_section_cm2_per_observed_bit"], 2.0 * 2 / 3)
        self.assertAlmostEqual(ordinary["cross_section_cm2_per_observed_bit"],
                               ht["cross_section_cm2_per_observed_bit"])
        self.assertTrue(ht["statistics_eligible"])
        self.assertFalse(ht["uncertainty_assessed"])

    def test_b0_uniform_matched_subset_and_product_probability(self):
        selection = self.draw(4, b0_count=2)
        b1 = {row["event_id"]: row for row in selection["draws"] if row["stored_bit"] == 1}
        b0 = [row for row in selection["draws"] if row["stored_bit"] == 0]
        self.assertEqual(len(b1), 4)
        self.assertEqual(len(b0), 2)
        for row in b0:
            self.assertIn(row["event_id"], b1)
            self.assertEqual(row["matched_b1_event_id"], row["event_id"])
            self.assertEqual(row["conditional_b0_probability"], 0.5)
            self.assertEqual(row["inclusion_probability"], b1[row["event_id"]]["pi1"] * 0.5)
        result = sampling.estimate(self.frame, selection, self.labels(selection, 0), stored_bit=0)
        self.assertGreater(result["cross_section_cm2_per_observed_bit"], 0)
        srs = self.draw(4, method="simple_random", b0_count=2)
        ordinary = sampling.estimate(self.frame, srs, self.labels(srs, 0), stored_bit=0, estimator="srs")
        self.assertEqual(ordinary["cross_section_cm2_per_observed_bit"], 2.0)

    def test_unallocated_b0_cell_cannot_be_estimated(self):
        selection = self.draw()
        self.assertFalse(selection["b0_condition_inference_supported"])
        with self.assertRaisesRegex(ValueError, "no allocated b0"):
            sampling.estimate(self.frame, selection, [], stored_bit=0)

    def test_zero_deposition_events_are_retained_but_never_auto_labeled(self):
        selection = self.draw(10)
        zeros = [row for row in selection["draws"] if row["deposition_energy_eV"] == 0]
        self.assertEqual(len(zeros), 4)
        self.assertTrue(all("y" not in row for row in zeros))
        labels = [row for row in self.labels(selection) if row["event_id"] not in {"0", "1", "2", "3"}]
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            sampling.estimate(self.frame, selection, labels)

    def test_frame_duplicate_missing_unverified_and_bad_values_are_rejected(self):
        changes = [
            lambda f: f["events"].pop(),
            lambda f: f["events"].append(copy.deepcopy(f["events"][0])),
            lambda f: f["events"][1].update(event_id="0"),
            lambda f: f["events"][0].pop("event_id"),
            lambda f: f["events"][0].pop("deposition_energy_eV"),
            lambda f: f["events"][0].update(deposition_energy_eV=float("nan")),
            lambda f: f.update(complete_primary_ledger_verified=False),
            lambda f: f.update(N_primary=True),
            lambda f: f.update(source_area_cm2=0),
            lambda f: f["condition"].pop("radiation_id"),
        ]
        for change in changes:
            altered = copy.deepcopy(self.frame)
            change(altered)
            with self.subTest(change=change), self.assertRaises(ValueError):
                sampling.validate_frame(altered)
        altered = copy.deepcopy(self.frame)
        altered["events"][0].pop("coarse_stratum")
        with self.assertRaisesRegex(ValueError, "missing coarse stratum"):
            sampling.select(altered, 3, 1, expected_frame_sha256=sampling.digest(altered))

    def test_seed_full_frame_and_weight_records_are_replayed_not_trusted(self):
        selection = self.draw()
        self.assertEqual(selection, self.draw())
        for path, value in (
                (("frame_sha256",), "d" * 64),
                (("draws", 0, "inclusion_probability"), 1.0),
                (("design", "strata", 0, "N_h"), 999),
                (("design", "seed"), 999),
                (("statistics_eligible",), True)):
            altered = copy.deepcopy(selection)
            target = altered
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                sampling.validate_selection(self.frame, altered)
        altered_frame = copy.deepcopy(self.frame)
        altered_frame["events"][9]["deposition_energy_eV"] += 1
        with self.assertRaisesRegex(ValueError, "frame hash"):
            sampling.validate_selection(altered_frame, selection)

    def test_duplicate_missing_extra_wrong_bit_unaccepted_labels_rejected(self):
        selection = self.draw()
        changes = [
            lambda ls: ls.append(copy.deepcopy(ls[0])),
            lambda ls: ls.pop(),
            lambda ls: ls[0].update(event_id="not-selected"),
            lambda ls: ls[0].update(stored_bit=0),
            lambda ls: ls[0].update(status="planned"),
            lambda ls: ls[0].update(accepted=False),
            lambda ls: ls[0].update(scientific_acceptance="pending"),
            lambda ls: ls[0].update(acceptance_evidence_sha256=None),
            lambda ls: ls[0].update(selection_sha256="f" * 64),
            lambda ls: ls[0].update(y=True),
        ]
        for change in changes:
            labels = self.labels(selection)
            change(labels)
            with self.subTest(change=change), self.assertRaises(ValueError):
                sampling.estimate(self.frame, selection, labels)

    def test_unequal_layer_ht_formula_and_ordinary_srs_refused(self):
        selection = self.draw(3)
        probabilities = [row["inclusion_probability"] for row in selection["draws"]]
        self.assertGreater(len(set(probabilities)), 1)
        result = sampling.estimate(self.frame, selection, self.labels(selection))
        self.assertAlmostEqual(result["cross_section_cm2_per_observed_bit"],
                               2.0 / 10 * sum(1 / p for p in probabilities))
        with self.assertRaisesRegex(ValueError, "ordinary SRS invalid"):
            sampling.estimate(self.frame, selection, self.labels(selection), estimator="srs")

    def test_overlap_reuses_solver_work_but_does_not_pool_estimates(self):
        # Census guarantees overlapping independently specified S and R designs.
        stratified = self.draw(10, 1)
        random = self.draw(10, 2, method="simple_random")
        reuse = sampling.reuse_plan([stratified, random])
        self.assertEqual(len(reuse["solver_work"]), 10)
        self.assertEqual(reuse["draw_references"], 20)
        self.assertEqual(reuse["unique_original_primary_count"], 10)
        self.assertTrue(all(len(row["design_references"]) == 2 for row in reuse["solver_work"]))
        with self.assertRaisesRegex(ValueError, "missing or extra|duplicate"):
            sampling.estimate(self.frame, stratified, self.labels(stratified) + self.labels(random))
        with self.assertRaisesRegex(ValueError, "union designs forbidden"):
            sampling.estimate(self.frame, stratified, self.labels(stratified), estimator="union")
        other_context = copy.deepcopy(self.frame)
        other_context["response_context_sha256"] = "e" * 64
        other_draw = sampling.select(other_context, 10, 3,
                                     expected_frame_sha256=sampling.digest(other_context))
        separate = sampling.reuse_plan([stratified, other_draw])
        self.assertEqual(len(separate["solver_work"]), 20)
        self.assertEqual(separate["unique_original_primary_count"], 10)

    def test_cli_executable_hash_select_and_frozen_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = Path(directory) / "frame.json"
            output = Path(directory) / "selected.json"
            frame.write_text(json.dumps(self.frame), encoding="utf-8")
            stream = io.StringIO()
            with redirect_stdout(stream):
                sampling.main(["frame-hash", str(frame)])
            self.assertEqual(stream.getvalue().strip(), sampling.digest(self.frame))
            argv = ["select", str(frame), "--frame-sha256", sampling.digest(self.frame),
                    "--q", "3", "--seed", "20", "--b0-count", "1", "--output", str(output)]
            with redirect_stdout(io.StringIO()):
                sampling.main(argv)
            selected = json.loads(output.read_text(encoding="utf-8"))
            sampling.validate_selection(self.frame, selected)
            before = output.read_bytes()
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                sampling.main(argv)
            self.assertEqual(before, output.read_bytes())


if __name__ == "__main__":
    unittest.main()
