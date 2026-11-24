import copy
import unittest

from dram_predictor.data import DataError, LeakageError
from dram_predictor.features import Encoder, record, source_off_record


class R06FeatureTests(unittest.TestCase):
    def setUp(self):
        self.condition = {"features": {"capacitance_fF": 20., "incident_energy_MeV": 120.},
                          "categories": {"structure_family": "lpddr5", "particle": "proton"}}
        self.primary = {
            "source_features": {"generated_charge_fC": 2., "deposited_energy_MeV": .04,
                                "source_duration_ns": .003, "hit_x_nm": 5., "spread_x_nm": 2.},
            "source_off": False, "scale_factor": 3., "source_time_ns": 22.,
            "deck_timing_version": "r06-hold-window-v1",
        }

    def test_predict_r_primary_defaults_scale_only_injected_charge(self):
        before = copy.deepcopy(self.primary)
        row = record(self.condition, self.primary)
        self.assertEqual(row["generated_charge_fC"], 6.)
        for name in self.primary["source_features"].keys() - {"generated_charge_fC"}:
            self.assertEqual(row[name], self.primary["source_features"][name])
        for name in ("source_time_ns", "deck_timing_version"):
            self.assertEqual(row[name], self.primary[name])
        self.assertEqual(self.primary, before)
        self.assertNotIn("scale_factor", row)

    def test_off_source_preserves_native_deposition_and_encoder_counterfactual(self):
        self.primary["source_off"] = True
        self.primary["source_features"]["generated_charge_fC"] = 0.
        row = record(self.condition, self.primary)
        self.assertEqual(row["deposited_energy_MeV"], .04)
        self.assertEqual(row["generated_charge_fC"], 0.)
        self.assertEqual(row, source_off_record(row))

    def test_f_rejects_response_metadata_and_keeps_pre_sim_record(self):
        baseline = record(self.condition)
        self.condition.update(source_time_ns=22., deck_timing_version="r06-hold-window-v1")
        self.assertEqual(record(self.condition), baseline)
        encoder = Encoder("F").fit([baseline])
        for name, value in (("scale_factor", 3.), ("selection_mechanism", "simple_random"),
                            ("inclusion_probability", .25), ("source_time_ns", 22.),
                            ("deck_timing_version", "r06-hold-window-v1")):
            with self.subTest(field=name):
                row = {**baseline, name: value}
                with self.assertRaises(LeakageError):
                    Encoder("F").fit([row])
                with self.assertRaises(LeakageError):
                    encoder.transform([row])

    def test_predict_r_rejects_invalid_primary_scale(self):
        for scale in (0., -1., float("inf"), float("nan"), True, "3"):
            with self.subTest(scale=scale), self.assertRaisesRegex(DataError, "scale_factor"):
                record(self.condition, {**self.primary, "scale_factor": scale})
