import unittest

from dram_predictor.calibration import temperature_from_oof
from dram_predictor.data import LeakageError


class CalibrationTests(unittest.TestCase):
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
