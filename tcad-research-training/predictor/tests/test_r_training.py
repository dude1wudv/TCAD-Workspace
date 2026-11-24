"""Synthetic-only tests for R fitting, inference and training-scope isolation."""
from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from dram_predictor.config import Config
from dram_predictor.data import DataError, LeakageError, Snapshot
from dram_predictor.r_training import (
    RArtifact, fit_r, fit_r_core, primary_batches, response_samples, sample_record, targets,
)
from dram_predictor.splits import grouped_folds, stopping_split
from fixtures import make_fixture


class ResponseTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.snapshot = Snapshot.load(make_fixture(cls.root / "snapshot"))
        cls.config = Config(max_epochs=2, patience=1, r_hidden=(8, 8), f_hidden=(8, 8))
        cls.outer = grouped_folds(cls.snapshot.view(cls.snapshot.development_conditions))[0]
        cls.core, cls.stop = stopping_split(cls.outer.train)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def assert_same_model(self, left, right):
        self.assertEqual(set(left.model.state_dict()), set(right.model.state_dict()))
        for name, value in left.model.state_dict().items():
            torch.testing.assert_close(value, right.model.state_dict()[name], rtol=0, atol=0)
        self.assertEqual(left.encoder.to_dict(), right.encoder.to_dict())
        self.assertEqual(left.device_encoder.to_dict(), right.device_encoder.to_dict())
        self.assertEqual(left.mechanism.to_dict(), right.mechanism.to_dict())

    @staticmethod
    def poison_scope(snapshot, view):
        """Change only excluded labels/control values, retaining all physical IDs."""
        changed = copy.deepcopy(snapshot)
        response_ids = {r["response_id"] for r in view.responses}
        control_ids = {c["control_id"] for c in view.controls}
        for row in changed.responses:
            if row["response_id"] in response_ids:
                row["labels"]["delta_voltage_V"] = [1e20] * len(snapshot.times)
                row["labels"]["port_charge_fC"] = -1e20
                row["labels"]["margin_V"] = 1e20
                row["labels"]["upset"] = 1 - row["labels"]["upset"]
        for row in changed.controls:
            if row["control_id"] in control_ids:
                row["voltage_V"] = [1e20] * len(row["time_ns"])
                row["reference_voltage_V"] = -1e20
        return changed

    def test_core_calibration_preprocessing_and_provenance_use_only_fit_side(self):
        artifact = fit_r_core(self.core, self.config, stop_view=self.stop)
        self.assertEqual(artifact.metadata["training_footprint"], self.core.footprint())
        self.assertEqual(artifact.metadata["stopping"]["fit"], self.core.footprint())
        self.assertEqual(artifact.metadata["stopping"]["stop"], self.stop.footprint())
        self.assertEqual(artifact.metadata["stopping"]["status"], "grouped_stop")
        used_controls = set(artifact.mechanism.control_source_ids)
        used_responses = set(artifact.mechanism.response_source_ids)
        self.assertEqual(used_controls, {r["control_id"] for r in self.core.controls})
        self.assertEqual(used_responses, {r["response_id"] for r in self.core.responses})
        for held in (self.stop, self.outer.validation):
            self.assertFalse(used_controls & {r["control_id"] for r in held.controls})
            self.assertFalse(used_responses & {r["response_id"] for r in held.responses})
        self.assertTrue(all(torch.isfinite(p).all() for p in artifact.model.parameters()))
        self.assertIn(artifact.metadata["selected_epochs"], (1, 2))

    def test_external_validation_labels_and_controls_cannot_change_core_fit(self):
        reference = fit_r_core(self.core, self.config, stop_view=self.stop)
        poisoned = self.poison_scope(self.snapshot, self.outer.validation)
        actual = fit_r_core(poisoned.view(self.core.condition_ids), self.config,
                            stop_view=poisoned.view(self.stop.condition_ids))
        self.assert_same_model(reference, actual)
        self.assertEqual(reference.metadata, actual.metadata)

    def test_full_fit_refits_only_scope_and_external_poison_cannot_change_weights(self):
        reference = fit_r(self.outer.train, self.config)
        poisoned = self.poison_scope(self.snapshot, self.outer.validation)
        actual = fit_r(poisoned.view(self.outer.train.condition_ids), self.config)
        self.assert_same_model(reference, actual)
        self.assertEqual(reference.metadata, actual.metadata)
        self.assertEqual(reference.metadata["training_footprint"], self.outer.train.footprint())
        selected = reference.metadata["epoch_selection"]
        self.assertEqual(selected["status"], "grouped_stop")
        fit_profiles, stop_profiles = set(selected["fit"]["profile_ids"]), set(selected["stop"]["profile_ids"])
        self.assertFalse(fit_profiles & stop_profiles)
        self.assertEqual(fit_profiles | stop_profiles, self.outer.train.profiles)
        self.assertFalse((fit_profiles | stop_profiles) & self.outer.validation.profiles)
        calibration = reference.metadata["probability_calibration"]
        self.assertEqual(calibration["status"], "unavailable")
        self.assertNotIn("temperature", calibration)
        diagnostic = reference.metadata["stopping_calibration_diagnostic"]
        self.assertEqual(diagnostic["status"], "calibrated")
        calibration_ids = set(diagnostic["response_ids"])
        stop_ids = set(selected["stop"]["response_ids"])
        self.assertTrue(calibration_ids <= stop_ids)
        random_ids = {
            s["response"]["response_id"] for s in response_samples(self.outer.train)
            if s["primary"]["sampling"] == "random"
        }
        self.assertTrue(calibration_ids <= random_ids)

    def test_nonpositive_explicit_epochs_cannot_publish_untrained_heads(self):
        for epochs in (0, -1, True):
            with self.subTest(epochs=epochs), self.assertRaises(DataError):
                fit_r_core(self.core, self.config, epochs=epochs)

    def test_stopping_labels_do_not_fit_encoders_scales_or_mechanism(self):
        reference = fit_r_core(self.core, self.config, stop_view=self.stop)
        poisoned = self.poison_scope(self.snapshot, self.stop)
        actual = fit_r_core(poisoned.view(self.core.condition_ids), self.config,
                            stop_view=poisoned.view(self.stop.condition_ids))
        # Stopping labels may select a different epoch, but cannot calibrate physics.
        self.assertEqual(reference.encoder.to_dict(), actual.encoder.to_dict())
        self.assertEqual(reference.device_encoder.to_dict(), actual.device_encoder.to_dict())
        self.assertEqual(reference.mechanism.to_dict(), actual.mechanism.to_dict())
        self.assertEqual(reference.metadata["scales"], actual.metadata["scales"])
        self.assertEqual(reference.metadata["training_fingerprint"], actual.metadata["training_fingerprint"])

    def test_overlapping_stop_scope_is_rejected_before_optimizer(self):
        with patch("dram_predictor.r_training.torch.optim.AdamW",
                   side_effect=AssertionError("Optimizer must not be reached")):
            with self.assertRaises(LeakageError):
                fit_r_core(self.core, self.config, stop_view=self.core)
        # Different profile names still cannot hide a reused global source.
        changed = copy.deepcopy(self.snapshot)
        fit_source = self.core.primaries[0]["source_primary_id"]
        changed.primaries[self.stop.primaries[0]["primary_id"]]["source_primary_id"] = fit_source
        with self.assertRaises(LeakageError):
            fit_r_core(changed.view(self.core.condition_ids), self.config,
                       stop_view=changed.view(self.stop.condition_ids))

    def test_global_source_minibatches_keep_reused_events_states_and_bits_together(self):
        samples = copy.deepcopy(response_samples(self.core))
        original = samples[0]
        other_primary = next(s["primary"] for s in samples
                             if s["primary"]["primary_id"] != original["primary"]["primary_id"])
        other_primary["source_primary_id"] = original["primary"]["source_primary_id"]
        extra = copy.deepcopy(original)
        extra["bit"]["bit_id"] = "synthetic-second-bit"
        extra["response"]["bit_id"] = "synthetic-second-bit"
        samples.append(extra)
        batches = list(primary_batches(samples, batch_groups=3, rng=np.random.default_rng(18)))
        self.assertEqual(sorted(i for batch in batches for i in batch.tolist()), list(range(len(samples))))
        source_batches = {}
        for batch_number, batch in enumerate(batches):
            batch_sources = set()
            for index in batch.tolist():
                source = samples[index]["primary"]["source_primary_id"]
                source_batches.setdefault(source, set()).add(batch_number)
                batch_sources.add(source)
            self.assertLessEqual(len(batch_sources), 3)
        self.assertTrue(all(len(numbers) == 1 for numbers in source_batches.values()))
        shared = original["primary"]["source_primary_id"]
        self.assertGreater(sum(s["primary"]["source_primary_id"] == shared for s in samples), 2)

    def test_saved_artifact_restores_exact_predictions_and_rejects_weight_tampering(self):
        artifact = fit_r_core(self.core, self.config)
        samples = response_samples(self.outer.validation)[:9]
        expected = artifact.predict_samples(samples, batch_size=5)
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            path = Path(directory)
            artifact.save(path)
            restored = RArtifact.load(path)
            self.assert_same_model(artifact, restored)
            self.assertEqual(expected, restored.predict_samples(samples, batch_size=5))
            weights = path / "weights.pt"
            weights.write_bytes(weights.read_bytes() + b"synthetic-test-tampering")
            with self.assertRaisesRegex(DataError, "type/hash mismatch"):
                RArtifact.load(path)

    def test_unsupervised_and_single_class_upset_do_not_publish_probabilities(self):
        for value in (None, 0, 1):
            with self.subTest(upset_labels=value):
                changed = copy.deepcopy(self.snapshot)
                for row in changed.responses:
                    row["labels"]["upset"] = value
                trained = fit_r_core(changed.view(self.core.condition_ids), self.config)
                self.assertNotIn("upset", trained.metadata["trained_heads"])
                predictions = trained.predict_samples(response_samples(self.outer.validation)[:4])
                self.assertTrue(all(r["upset_logit"] is None and r["probability"] is None
                                    for r in predictions))
                self.assertTrue(all(r["delta_voltage_V"] is not None for r in predictions))

    def r06_snapshot(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot.manifest.update(simulation_revision="0.6", source_time_ns=22.,
                                 deck_timing_version="r06-hold-window-v1")
        return snapshot

    def test_r06_response_scale_reaches_network_mechanism_and_regularizer_once(self):
        snapshot = self.r06_snapshot()
        view = snapshot.view(self.core.condition_ids)
        primary = next(p for p in view.primaries if not p["source_off"])
        source = copy.deepcopy(primary["source_features"])
        for row in view.responses:
            row.update(scale_factor=3. if row["state"] == 0 else 10., source_time_ns=22.,
                       deck_timing_version="r06-hold-window-v1", selection_mechanism="threshold_scaled")
        samples = response_samples(view)
        artifact = fit_r_core(view, self.config, epochs=1)
        reference = fit_r_core(self.core, self.config, epochs=1)
        gains = {r["id"]: r["fitted_gain"] for r in artifact.mechanism.calibration_records
                 if "fitted_gain" in r}
        reference_gains = {r["id"]: r["fitted_gain"] for r in reference.mechanism.calibration_records
                           if "fitted_gain" in r}
        inputs = artifact._inputs(samples)
        self.assertNotIn("source_time_ns", artifact.encoder.numeric)
        self.assertEqual(artifact.metadata["sample_times_ns"], snapshot.times)
        for i, sample in enumerate(samples):
            if sample["primary"] is not primary:
                continue
            row = sample_record(sample)
            response = sample["response"]
            scale, identity = response["scale_factor"], response["response_id"]
            self.assertEqual(row["generated_charge_fC"], source["generated_charge_fC"] * scale)
            self.assertAlmostEqual(float(inputs["generated_charge_fC"][i]), row["generated_charge_fC"])
            self.assertAlmostEqual(float(inputs["source_duration_ns"][i]), source["source_duration_ns"])
            self.assertEqual(row["deposited_energy_MeV"], source["deposited_energy_MeV"])
            self.assertEqual(row["source_time_ns"], 22.)
            self.assertEqual(row["deck_timing_version"], "r06-hold-window-v1")
            self.assertAlmostEqual(gains[identity], reference_gains[identity] / scale)
        charges = [sample_record(s)["generated_charge_fC"] for s in samples if not s["primary"]["source_off"]]
        self.assertEqual(artifact.metadata["charge_regularizer_scale_fC"], float(np.median(charges)))
        self.assertEqual(primary["source_features"], source)

    def test_r06_predict_r_checks_explicit_timing_against_artifact(self):
        snapshot = self.r06_snapshot()
        artifact = fit_r_core(snapshot.view(self.core.condition_ids), self.config, epochs=1)
        self.assertEqual(artifact.metadata["simulation_revision"], "0.6")
        self.assertEqual(artifact.metadata["source_time_ns"], 22.)
        self.assertEqual(artifact.metadata["deck_timing_version"], "r06-hold-window-v1")
        sample = next(s for s in response_samples(snapshot.view(self.outer.validation.condition_ids))
                      if not s["primary"]["source_off"])
        sample = {key: sample[key] for key in ("condition", "primary", "state", "bit")}
        expected = artifact.predict_samples([sample])
        primary = {**sample["primary"], "source_time_ns": 22., "deck_timing_version": "r06-hold-window-v1"}
        self.assertEqual(artifact.predict_samples([{**sample, "primary": primary}]), expected)
        scaled = {**sample, "primary": {**primary, "scale_factor": 3.}}
        overridden = {**scaled, "response": {"scale_factor": 10., "deck_timing_version": "r06-hold-window-v1"}}
        charge = sample["primary"]["source_features"]["generated_charge_fC"]
        torch.testing.assert_close(artifact._inputs([scaled, overridden])["generated_charge_fC"],
                                   torch.tensor([charge * 3., charge * 10.]))
        for field, wrong_value in (("source_time_ns", 15.), ("deck_timing_version", "other-deck")):
            for source in ("primary", "response"):
                with self.subTest(field=field, source=source), self.assertRaisesRegex(DataError, field):
                    supplied = {**sample, "primary": primary}
                    supplied[source] = {**supplied.get(source, {}), field: wrong_value}
                    artifact.predict_samples([supplied])

    def test_r04_sample_and_artifact_ignore_incidental_r06_metadata(self):
        sample = next(s for s in response_samples(self.outer.validation) if not s["primary"]["source_off"])
        extras = {"source_time_ns": 22., "deck_timing_version": "r06-hold-window-v1", "scale_factor": 10.}
        annotated = {**sample, "primary": {**sample["primary"], **extras},
                     "response": {**sample["response"], **extras}}
        self.assertEqual(sample_record(annotated), sample_record(sample))
        artifact = fit_r_core(self.core, self.config, epochs=1)
        self.assertNotIn("simulation_revision", artifact.metadata)
        self.assertNotIn("source_time_ns", artifact.metadata)
        self.assertEqual(artifact.predict_samples([annotated]), artifact.predict_samples([sample]))

    def test_r06_sparse_supervision_and_artifact_state_support(self):
        snapshot = self.r06_snapshot()
        fit_ids = {r["response_id"] for r in self.core.responses}
        incomplete_id = self.core.primaries[0]["primary_id"]
        snapshot.responses = [r for r in snapshot.responses if r["response_id"] not in fit_ids
                              or r["state"] == 1 or r["primary_id"] == incomplete_id]
        pending = [r for r in snapshot.responses if r["primary_id"] == incomplete_id]
        snapshot.primaries[incomplete_id].update(source_features=None, source_off=None)
        for row in pending:
            row["labels"] = {"delta_voltage_V": [None] * len(snapshot.times), "upset": 0}
            row["masks"]["upset"] = False
        view = snapshot.view(self.core.condition_ids)
        samples = response_samples(view)
        self.assertEqual({s["state"] for s in samples}, {1})
        self.assertEqual(len(samples), len(view.responses) - len(pending))
        self.assertEqual(len(view.footprint()["response_ids"]), len(view.responses))
        artifact = fit_r_core(view, self.config, epochs=1)
        self.assertEqual(artifact.metadata["upset_states"], [1])
        held = snapshot.view(self.outer.validation.condition_ids)
        samples = response_samples(held)
        predictions = artifact.predict_samples(samples)
        for row in predictions:
            self.assertEqual(row["upset_logit"] is not None, row["state"] == 1)
            self.assertEqual(row["probability"] is not None, row["state"] == 1)
        self.assertEqual(artifact.evaluate(held)["heads"]["upset"]["n"],
                         sum(s["state"] == 1 for s in samples))
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            artifact.save(directory)
            restored = RArtifact.load(directory)
            self.assertEqual(restored.metadata["upset_states"], [1])
            self.assertEqual(restored.metadata["source_time_ns"], 22.)
            self.assertEqual(restored.metadata["deck_timing_version"], "r06-hold-window-v1")
            self.assertEqual(restored.predict_samples(samples), predictions)

    def test_r06_pooled_classes_do_not_qualify_either_state(self):
        snapshot = self.r06_snapshot()
        view = snapshot.view(self.core.condition_ids)
        for row in view.responses:
            row["labels"]["upset"] = row["state"]
        artifact = fit_r_core(view, self.config, epochs=1)
        self.assertEqual(artifact.metadata["upset_states"], [])
        self.assertNotIn("upset", artifact.metadata["trained_heads"])
        snapshot.manifest["simulation_revision"] = "0.4"
        legacy = fit_r_core(view, self.config, epochs=1)
        self.assertNotIn("upset_states", legacy.metadata)
        self.assertIn("upset", legacy.metadata["trained_heads"])

    def test_mechanism_only_never_constructs_optimizer_or_auxiliary_predictions(self):
        with patch("dram_predictor.r_training.torch.optim.AdamW",
                   side_effect=AssertionError("Analytic model cannot need an optimizer")):
            artifact = fit_r(self.outer.train, replace(self.config, mode="mechanism_only"))
        self.assertEqual(artifact.metadata["selected_epochs"], 0)
        self.assertEqual(artifact.metadata["trained_heads"], ["delta_voltage_V"])
        self.assertFalse(list(artifact.model.parameters()))
        predictions = artifact.predict_samples(response_samples(self.outer.validation)[:4])
        self.assertTrue(all(row["delta_voltage_V"] is not None for row in predictions))
        for row in predictions:
            for key in ("port_charge_fC", "margin_V", "upset_logit", "probability"):
                self.assertIsNone(row[key])

    def test_missing_continuous_labels_remain_nan_and_unsupervised_heads_stay_null(self):
        changed = copy.deepcopy(self.snapshot)
        for row in changed.responses:
            for head in ("delta_voltage_V", "port_charge_fC", "margin_V"):
                row["labels"][head] = None
        view = changed.view(self.core.condition_ids)
        labels, masks = targets(response_samples(view), changed.times)
        for head in ("delta_voltage_V", "port_charge_fC", "margin_V"):
            self.assertTrue(torch.isnan(labels[head]).all())
            self.assertFalse(masks[head].any())
        # The plain ablation can train the valid binary head without RC labels.
        artifact = fit_r_core(view, replace(self.config, mode="plain"))
        self.assertEqual(artifact.metadata["trained_heads"], ["upset"])
        for row in artifact.predict_samples(response_samples(self.outer.validation)[:4]):
            for head in ("delta_voltage_V", "port_charge_fC", "margin_V"):
                self.assertIsNone(row[head])
            self.assertIsNotNone(row["probability"])
        # A hybrid model cannot fabricate its missing calibration from defaults.
        with self.assertRaisesRegex(DataError, "identifiable training controls/responses"):
            fit_r_core(view, self.config)

    def test_failed_and_partial_targets_are_masked_without_converting_them_to_zeros(self):
        samples = copy.deepcopy(response_samples(self.core)[:3])
        failed, partial = samples[0]["response"], samples[1]["response"]
        failed["status"] = "failed"
        failed["labels"] = {
            "delta_voltage_V": [7.] * len(self.snapshot.times),
            "port_charge_fC": 9., "margin_V": .3, "upset": 1,
        }
        partial["labels"]["delta_voltage_V"][2] = None
        partial["labels"]["port_charge_fC"] = None
        partial["status"] = "unresolved"
        labels, masks = targets(samples, self.snapshot.times)
        for head in ("delta_voltage_V", "port_charge_fC", "margin_V", "upset"):
            self.assertFalse(masks[head][0].any())
        self.assertEqual(float(labels["port_charge_fC"][0]), 9.)
        self.assertTrue(torch.isnan(labels["delta_voltage_V"][1, 2]))
        self.assertFalse(masks["delta_voltage_V"][1, 2])
        self.assertTrue(masks["delta_voltage_V"][1, 3])
        self.assertFalse(masks["upset"][1])
        self.assertTrue(torch.isnan(labels["port_charge_fC"][1]))
        self.assertFalse(masks["port_charge_fC"][1])

    def test_all_failed_rows_cannot_produce_a_trained_artifact(self):
        changed = copy.deepcopy(self.snapshot)
        for row in changed.responses:
            row["status"] = "failed"
        for mode in ("hybrid", "plain"):
            with self.subTest(mode=mode):
                with self.assertRaises(DataError):
                    fit_r_core(changed.view(self.core.condition_ids), replace(self.config, mode=mode))

    def test_scope_cache_reuses_artifact_without_running_optimizer_again(self):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            first = fit_r(self.outer.train, self.config, cache_dir=directory)
            with patch("dram_predictor.r_training.torch.optim.AdamW",
                       side_effect=AssertionError("Cache hit must not retrain")):
                cached = fit_r(self.outer.train, self.config, cache_dir=directory)
            self.assert_same_model(first, cached)
            self.assertEqual(first.metadata, cached.metadata)


if __name__ == "__main__":
    unittest.main()
