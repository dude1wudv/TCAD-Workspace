"""Small synthetic optimizer checks; never scientific training or server work."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch

from dram_predictor.config import Config
from dram_predictor.data import DataError, LeakageError, Snapshot
from dram_predictor.f_training import FArtifact, fit_f_core
from fixtures import make_snapshot


class FTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-f-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        path = make_snapshot(self.root / "data", profiles=4, conditions_per_profile=1,
                             primaries_per_condition=6, with_sealed=False)
        self.snapshot = Snapshot.load(path)
        ids = sorted(self.snapshot.development_conditions)
        self.train = self.snapshot.view(ids[:2])
        self.stop = self.snapshot.view(ids[2:])
        self.config = Config(f_hidden=(4,), max_epochs=4, patience=2,
                             learning_rate=.01, f_batch_conditions=1, seed=13)

    def proxies(self, view=None, values=(1e-8, 2e-8), weights=(1., 1.)):
        view = self.train if view is None else view
        return [{"condition_id": c["condition_id"], "sigma_cm2_per_bit": list(values),
                 "weights": list(weights), "status": "ready",
                 "training_footprint": {"profile_ids": ["synthetic-outside-target"],
                                        "source_primary_ids": ["synthetic-foreign-primary"],
                                        "condition_ids": ["synthetic-foreign-condition"],
                                        "source_control_ids": []},
                 "origin": "synthetic-test-only"}
                for c in view.conditions]

    def without_counts(self):
        self.snapshot.counts = []

    def test_native_counts_override_same_state_proxy_and_do_not_change_scale(self):
        baseline = fit_f_core(self.train, [], self.config, epochs=2)
        proxies = self.proxies(values=(1e90, 1e90))
        mixed = fit_f_core(self.train, proxies, self.config, epochs=2)
        self.assertEqual(mixed.metadata["native_count_rows"], 4)
        self.assertEqual(mixed.metadata["proxy_state_labels"], 0)
        self.assertEqual(len(mixed.metadata["native_precedence"]), 4)
        self.assertEqual(mixed.sigma_scale, baseline.sigma_scale)
        self.assertEqual(mixed.predict(self.train.conditions), baseline.predict(self.train.conditions))
        self.assertEqual(mixed.metadata["proxy_provenance"][0]["origin"], "synthetic-test-only")

    def test_native_and_proxy_supervise_different_states(self):
        self.snapshot.counts = [r for r in self.snapshot.counts if r["state"] == 0]
        artifact = fit_f_core(self.train, self.proxies(values=(1e90, 1e-8)), self.config, epochs=2)
        self.assertEqual(artifact.metadata["native_count_rows"], 2)
        self.assertEqual(artifact.metadata["proxy_state_labels"], 2)
        self.assertEqual(artifact.trained_states, [0, 1])
        self.assertAlmostEqual(artifact.sigma_scale, (1 / 3e8 + 1e-8) / 2, delta=1e-23)
        report = artifact.evaluate(self.train, self.proxies(values=(1e90, 1e-8)))
        self.assertEqual(report["native_count_rows"], 2)
        self.assertEqual(report["proxy_rows"], 2)
        self.assertTrue(math.isfinite(report["native_poisson_nll"]))
        self.assertTrue(math.isfinite(report["proxy_asinh_mae"]))

    def test_zero_native_counts_use_exposure_scale_without_pseudocount(self):
        for row in self.snapshot.counts:
            row["bit_errors"] = 0
        before = copy.deepcopy(self.snapshot.counts)
        artifact = fit_f_core(self.train, [], self.config, epochs=2)
        self.assertAlmostEqual(artifact.sigma_scale, 1 / 3e8, delta=1e-23)
        self.assertEqual(artifact.metadata["scale_provenance"]["source"],
                         "median_inverse_training_native_exposure")
        self.assertEqual(self.snapshot.counts, before)
        predictions = {r["condition_id"]: r["sigma_cm2_per_bit"]
                       for r in artifact.predict(self.train.conditions)}
        expected = sum(predictions[c["condition_id"]][c["state"]] * c["fluence_cm2"] * c["n_bits"]
                       for c in self.train.counts) / len(self.train.counts)
        self.assertAlmostEqual(artifact.evaluate(self.train)["native_poisson_nll"], expected)

    def test_zero_proxy_scale_is_declared_training_area_not_fake_positive_label(self):
        self.without_counts()
        proxies = self.proxies(values=(0., 0.))
        before = copy.deepcopy(proxies)
        artifact = fit_f_core(self.train, proxies, self.config, epochs=2)
        self.assertEqual(artifact.sigma_scale, 1e-8)
        self.assertEqual(artifact.metadata["scale_provenance"]["source"],
                         "median_training_source_area_cm2")
        self.assertEqual(proxies, before)
        self.assertEqual(artifact.trained_states, [0, 1])

    def test_unsupervised_state_is_none_and_cannot_be_scored(self):
        self.snapshot.counts = [row for row in self.snapshot.counts
                                if row["condition_id"] not in self.train.condition_ids or row["state"] == 0]
        artifact = fit_f_core(self.train, [], self.config, epochs=2)
        self.assertEqual(artifact.trained_states, [0])
        self.assertTrue(all(row["sigma_cm2_per_bit"][1] is None
                            for row in artifact.predict(self.stop.conditions)))
        report = artifact.evaluate(self.stop)
        self.assertEqual(report["native_count_rows"], 2)
        self.assertIsNone(report["proxy_asinh_mae"])

    def test_no_usable_supervision_raises_and_empty_evaluation_is_none(self):
        artifact = fit_f_core(self.train, [], self.config, epochs=1)
        self.without_counts()
        empty = artifact.evaluate(self.train)
        self.assertEqual(empty["native_count_rows"], 0)
        self.assertEqual(empty["proxy_rows"], 0)
        self.assertIsNone(empty["native_poisson_nll"])
        self.assertIsNone(empty["proxy_asinh_mae"])
        for proxies in ([], self.proxies(weights=(0., 0.))):
            with self.subTest(proxies=bool(proxies)), self.assertRaisesRegex(DataError, "no usable"):
                fit_f_core(self.train, proxies, self.config, epochs=1)

    def test_proxy_footprint_cannot_contain_target_profile_or_primary(self):
        self.without_counts()
        bad = self.proxies()
        bad[0]["training_footprint"]["profile_ids"] = [self.train.conditions[0]["profile_id"]]
        with self.assertRaisesRegex(LeakageError, "target profile"):
            fit_f_core(self.train, bad, self.config, epochs=1)
        bad = self.proxies()
        cid = bad[0]["condition_id"]
        source = next(p["source_primary_id"] for p in self.train.primaries if p["condition_id"] == cid)
        bad[0]["training_footprint"]["source_primary_ids"] = [source]
        with self.assertRaisesRegex(LeakageError, "target primary"):
            fit_f_core(self.train, bad, self.config, epochs=1)
        bad = self.proxies()
        bad[0]["training_footprint"].pop("source_primary_ids")
        with self.assertRaisesRegex(DataError, "source_primary_ids"):
            fit_f_core(self.train, bad, self.config, epochs=1)

    def test_ready_proxy_requires_complete_footprint_even_with_native_precedence(self):
        for field in ("training_footprint", "source_control_ids", "condition_ids"):
            bad = self.proxies()
            if field == "training_footprint":
                bad[0].pop(field)
            else:
                bad[0]["training_footprint"].pop(field)
            with self.subTest(field=field), self.assertRaisesRegex(DataError, field):
                fit_f_core(self.train, bad, self.config, epochs=1)

    def test_pending_proxy_can_omit_footprint_without_creating_supervision(self):
        pending = [{"condition_id": c["condition_id"], "status": "pending"}
                   for c in self.train.conditions]
        artifact = fit_f_core(self.train, pending, self.config, epochs=1)
        self.assertEqual(artifact.metadata["proxy_state_labels"], 0)
        self.assertEqual(len(artifact.metadata["skipped_proxies"]), len(pending))

    def test_cross_profile_control_alias_is_a_leak_despite_native_precedence(self):
        target_profile = self.train.conditions[0]["profile_id"]
        control = next(c for c in self.train.controls if c["profile_id"] == target_profile)
        control["source_control_id"] = "synthetic-shared-physical-control"
        bad = self.proxies()
        bad[0]["training_footprint"]["source_control_ids"] = [control["source_control_id"]]
        self.assertNotIn(target_profile, bad[0]["training_footprint"]["profile_ids"])
        with self.assertRaisesRegex(LeakageError, "target control source"):
            fit_f_core(self.train, bad, self.config, epochs=1)

    def test_malformed_ready_target_is_not_hidden_by_native_precedence(self):
        bad = self.proxies(values=(-1., 1.))
        with self.assertRaisesRegex(DataError, "proxy cross section"):
            fit_f_core(self.train, bad, self.config, epochs=1)

    def test_proxy_weight_cap_is_one_and_recorded(self):
        self.without_counts()
        capped = fit_f_core(self.train, self.proxies(weights=(100., 100.)), self.config, epochs=2)
        unit = fit_f_core(self.train, self.proxies(weights=(1., 1.)), self.config, epochs=2)
        self.assertEqual(capped.predict(self.train.conditions), unit.predict(self.train.conditions))
        self.assertEqual(capped.metadata["proxy_loss"], "confidence_weighted_asinh_huber_weight_cap_1")

    def test_outside_view_proxy_and_overlapping_stop_view_are_rejected(self):
        with self.assertRaisesRegex(LeakageError, "outside"):
            fit_f_core(self.train, self.proxies(self.stop), self.config, epochs=1)
        with self.assertRaises(LeakageError):
            fit_f_core(self.train, [], self.config, stop_view=self.train, epochs=1)

    def test_fixed_epoch_weights_and_scales_do_not_depend_on_stop_labels(self):
        first = fit_f_core(self.train, [], self.config, stop_view=self.stop, epochs=3)
        for row in self.stop.counts:
            row["bit_errors"] = 1000
        second = fit_f_core(self.train, [], self.config, stop_view=self.stop, epochs=3)
        self.assertEqual(first.encoder.to_dict(), second.encoder.to_dict())
        self.assertEqual(first.sigma_scale, second.sigma_scale)
        self.assertEqual(first.predict(self.train.conditions), second.predict(self.train.conditions))
        self.assertNotEqual(first.metadata["history"][0]["stopping_loss"],
                            second.metadata["history"][0]["stopping_loss"])
        self.assertEqual(second.metadata["selected_epochs"], 3)
        self.assertEqual(second.metadata["stopping_mode"], "fixed_epochs")

    def test_stopping_selects_best_epoch_and_restores_that_state(self):
        for row in self.train.counts:
            row["bit_errors"] = 100
        for row in self.stop.counts:
            row["bit_errors"] = 0
        stopped = fit_f_core(self.train, [], self.config, stop_view=self.stop)
        history = stopped.metadata["history"]
        expected = min(history, key=lambda row: row["stopping_loss"])["epoch"]
        self.assertEqual(stopped.metadata["selected_epochs"], expected)
        self.assertLess(stopped.metadata["selected_epochs"], stopped.metadata["epochs_run"])
        refit = fit_f_core(self.train, [], self.config, epochs=expected)
        self.assertEqual(stopped.predict(self.train.conditions), refit.predict(self.train.conditions))

    def test_stopping_head_cannot_create_a_training_head(self):
        self.snapshot.counts = [
            row for row in self.snapshot.counts
            if (row["condition_id"] in self.train.condition_ids and row["state"] == 0)
            or (row["condition_id"] in self.stop.condition_ids and row["state"] == 1)]
        fallback = fit_f_core(self.train, [], self.config, stop_view=self.stop)
        self.assertEqual(fallback.metadata["stopping_mode"], "fixed_epochs")
        self.assertEqual(fallback.metadata["stopping_reason"], "no_valid_stop")
        self.assertEqual(fallback.metadata["selected_epochs"], self.config.max_epochs)
        fixed = fit_f_core(self.train, [], self.config, stop_view=self.stop, epochs=2)
        self.assertEqual(fixed.trained_states, [0])

    def test_poisson_score_includes_log_factorial_constant(self):
        for row in self.train.counts:
            row["bit_errors"] = 4
        artifact = fit_f_core(self.train, [], self.config, epochs=1)
        predictions = {r["condition_id"]: r["sigma_cm2_per_bit"]
                       for r in artifact.predict(self.train.conditions)}
        values = []
        for row in self.train.counts:
            lam = predictions[row["condition_id"]][row["state"]] * row["fluence_cm2"] * row["n_bits"]
            values.append(lam - row["bit_errors"] * math.log(lam) + math.lgamma(row["bit_errors"] + 1))
        self.assertAlmostEqual(artifact.evaluate(self.train)["native_poisson_nll"],
                               sum(values) / len(values), places=12)

    def test_source_quantities_do_not_enter_f_encoder(self):
        self.train.conditions[0]["features"]["generated_charge_fC"] = 100.
        with self.assertRaisesRegex(LeakageError, "Unapproved"):
            fit_f_core(self.train, [], self.config, epochs=1)

    def test_direct_prediction_rejects_another_domain_and_posterior_features(self):
        artifact = fit_f_core(self.train, [], self.config, epochs=1)
        condition = copy.deepcopy(self.train.conditions[0])
        condition["domain"] = "other-route-even-with-same-structure-name"
        with self.assertRaisesRegex(DataError, "another model domain"):
            artifact.predict([condition])
        condition = copy.deepcopy(self.train.conditions[0])
        condition["features"]["upset"] = 1.
        with self.assertRaisesRegex(LeakageError, "Unapproved"):
            artifact.predict([condition])

    def test_artifact_roundtrip_hash_verification_and_weights_only_loading(self):
        artifact = fit_f_core(self.train, [], self.config, epochs=2)
        path = artifact.save(self.root / "artifact")
        actual_load = torch.load
        with patch("dram_predictor.f_training.torch.load", wraps=actual_load) as loader:
            restored = FArtifact.load(path)
            self.assertTrue(loader.call_args.kwargs["weights_only"])
        self.assertEqual(artifact.predict(self.train.conditions), restored.predict(self.train.conditions))
        with self.assertRaisesRegex(DataError, "overwrite"):
            artifact.save(path.parent)
        with (path.parent / "model.pt").open("ab") as stream:
            stream.write(b"synthetic corruption")
        with patch("dram_predictor.f_training.torch.load") as loader:
            with self.assertRaisesRegex(DataError, "model hash"):
                FArtifact.load(path)
            loader.assert_not_called()

    def test_metadata_corruption_and_outside_support_are_explicit(self):
        artifact = fit_f_core(self.train, [], self.config, epochs=1)
        condition = copy.deepcopy(self.train.conditions[0])
        condition["features"]["gate_length_nm"] = 16.2
        self.assertIn("gate_length_nm", artifact.predict([condition])[0]["out_of_support"])
        path = artifact.save(self.root / "artifact")
        metadata = json.loads(path.read_text())
        metadata["metadata"]["sigma_scale"] *= 10
        path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(DataError, "metadata hash"):
            FArtifact.load(path)


if __name__ == "__main__":
    unittest.main()
