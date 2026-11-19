import tempfile
from pathlib import Path
import unittest

from dram_predictor.baselines import ablations, constant_native_baseline
from dram_predictor.config import Config
from dram_predictor.data import Snapshot
from dram_predictor.splits import grouped_folds
from fixtures import make_fixture


class BaselineTests(unittest.TestCase):
    def test_constant_count_baseline_and_four_response_ablations(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Snapshot.load(make_fixture(Path(directory), profiles=6, conditions_per_profile=1))
            view = snapshot.view(snapshot.development_conditions)
            fold = grouped_folds(view)[0]
            baseline = constant_native_baseline(fold.train, fold.validation)
            self.assertAlmostEqual(baseline["native_poisson_nll"], 1.)
            self.assertEqual(baseline["infinite_nll_rows"], 0)
            result = ablations(snapshot, Config(max_epochs=1, patience=1, r_hidden=(4, 4)))
            self.assertFalse(result["sealed_labels_read"])
            for entry in result["folds"]:
                for name in ("mechanism_only", "plain_mlp", "hybrid_no_regularizer",
                             "hybrid_selected_regularizer"):
                    self.assertEqual(entry[name]["status"], "ready")
                    self.assertIn("delta_voltage_V", entry[name]["R_metrics"]["heads"])
                self.assertNotIn("upset", entry["mechanism_only"]["R_metrics"]["heads"])
