from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from dram_predictor.calibration import random_oof_records, temperature_from_oof
from dram_predictor.data import LeakageError, Snapshot
from dram_predictor.r_training import _temperature_from_stop
from fixtures import make_fixture


class CalibrationTests(unittest.TestCase):
    def test_oof_and_stopping_calibration_use_revision_specific_random_draws(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Snapshot.load(make_fixture(Path(directory), profiles=3, conditions_per_profile=1))
        target = sorted(snapshot.development_conditions)[0]
        validation = snapshot.view([target])
        fit = snapshot.view(snapshot.development_conditions - {target})
        model = Mock(metadata={"trained_heads": ["upset"], "training_footprint": fit.footprint()})
        model.predict_samples.side_effect = lambda samples: [
            {"upset_logit": 1. if s["response"]["labels"]["upset"] else -1.} for s in samples]

        legacy_ids = {row["response_id"] for row in validation.responses
                      if snapshot.primaries[row["primary_id"]]["sampling"] == "random"}
        simple_ids = set()
        for index, primary in enumerate(validation.primaries):
            for row in validation.responses:
                if row["primary_id"] != primary["primary_id"]:
                    continue
                if index < 4 and row["state"] == 1:
                    row.update(selection_mechanism="simple_random", inclusion_probability=.5)
                    simple_ids.add(row["response_id"])
                else:
                    row["selection_mechanism"] = ("stratified_pi", "threshold_scaled", "active_learning",
                                                  "random", None, "simple_random")[index]
                    row["inclusion_probability"] = .25 if index in (0, 5) else None
                    if index == 5:
                        row["masks"]["upset"] = False
                        legacy_ids.discard(row["response_id"])

        for revision, expected in (("0.4", legacy_ids), ("0.6", simple_ids)):
            with self.subTest(revision=revision):
                snapshot.manifest["simulation_revision"] = revision
                oof = random_oof_records(model, validation)
                self.assertEqual({row["response_id"] for row in oof}, expected)
                if revision == "0.6":
                    self.assertEqual({row["state"] for row in oof}, {1})
                    self.assertEqual(len({row["source_primary_id"] for row in oof}), 4)
                diagnostic = _temperature_from_stop(model, validation)
                if revision == "0.6":
                    self.assertEqual(diagnostic["status"], "calibrated")
                    self.assertEqual(set(diagnostic["response_ids"]), expected)
                else:
                    self.assertEqual(diagnostic["status"], "unavailable")
                    self.assertEqual(diagnostic["independent_primaries"], 3)
                called_samples = model.predict_samples.call_args.args[0]
                self.assertEqual({s["response"]["response_id"] for s in called_samples}, expected)

    def records(self):
        return [{"response_id": f"r{i}", "source_primary_id": f"p{i}",
                 "label": i % 2, "logit": (2. if i % 2 else -2.)} for i in range(12)]

    def test_oof_estimate_is_not_independent_validation(self):
        records = self.records()
        result = temperature_from_oof([
            {"random_oof_probability_records": records[i:i+4]} for i in (0, 4, 8)])
        self.assertEqual(result["status"], "estimated_oof_for_refit")
        self.assertFalse(result["independent_calibration_validation"])
        self.assertEqual(result["independent_primaries"], 12)
        self.assertGreaterEqual(result["temperature"], .25)
        self.assertLessEqual(result["temperature"], 4.)

    def test_one_class_is_unavailable(self):
        records = self.records()
        for row in records:
            row["label"] = 0
        self.assertEqual(temperature_from_oof(
            [{"random_oof_probability_records": records}])["status"], "unavailable")

    def test_duplicate_oof_label_rejected(self):
        records = self.records()
        with self.assertRaises(LeakageError):
            temperature_from_oof([{"random_oof_probability_records": records},
                                  {"random_oof_probability_records": records[:1]}])

    def test_reused_primary_has_equal_total_weight(self):
        records = self.records()
        base = temperature_from_oof([{"random_oof_probability_records": records}])
        duplicate = [{**r, "response_id": r["response_id"] + "-paired"} for r in records[:4]]
        result = temperature_from_oof([{"random_oof_probability_records": records + duplicate}])
        self.assertAlmostEqual(result["temperature"], base["temperature"])
        self.assertAlmostEqual(result["development_bce"], base["development_bce"])
