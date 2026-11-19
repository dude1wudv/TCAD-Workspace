"""Tiny synthetic end-to-end checks; never launches solvers or native-data fits."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dram_predictor import cli
from dram_predictor.config import Config
from dram_predictor.data import DataError, LeakageError, Snapshot, digest, read_json
from dram_predictor.f_training import FArtifact
from dram_predictor.pipeline import (
    cross_validate, fit_final, frozen_folds, prepare, run_search, selection_score,
)
from dram_predictor.r_training import RArtifact, response_samples
from fixtures import make_fixture, read_rows, rewrite_table


class PipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.manifest = make_fixture(
            cls.root / "synthetic", profiles=12, conditions_per_profile=2, primaries_per_condition=4)
        cls.config = Config(max_epochs=2, patience=1, r_hidden=(4, 4), f_hidden=(4, 4))
        cls.sealed_attempts = []
        original = Path.open
        sealed_root = (cls.manifest.parent / "sealed").resolve()

        def guarded(file, *args, **kwargs):
            if file.resolve().is_relative_to(sealed_root):
                cls.sealed_attempts.append(str(file))
                raise AssertionError("Sealed labels must not be opened by preparation or fitting")
            return original(file, *args, **kwargs)

        with patch.object(Path, "open", guarded):
            cls.snapshot = Snapshot.load(cls.manifest)
            cls.prepared = cls.root / "prepared"
            cls.preparation = prepare(cls.snapshot, cls.prepared)
            cls.cv = cross_validate(cls.snapshot, cls.config, cache_dir=cls.root / "cv-cache",
                                    split_path=cls.prepared / "splits.json")
            cls.final_dir = cls.root / "final"
            cls.final = fit_final(cls.snapshot, cls.config, cls.final_dir)
            cls.r_model = RArtifact.load(cls.final_dir / "R")
            cls.f_model = FArtifact.load(cls.final_dir / "F")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_outer_three_inner_two_folds_are_ready_and_source_disjoint(self):
        self.assertEqual(len(self.cv["folds"]), 3)
        seen = set()
        for fold in self.cv["folds"]:
            self.assertEqual(fold["R"]["status"], "ready", fold["R"])
            self.assertEqual(fold["F"]["status"], "ready", fold["F"])
            training = set(fold["train"]["condition_ids"])
            validation = set(fold["validation"]["condition_ids"])
            self.assertFalse(training & validation)
            self.assertFalse(seen & validation)
            seen |= validation
            self.assertEqual(len(fold["inner_cross_fit"]), 2)
            inner_seen = set()
            for inner in fold["inner_cross_fit"]:
                self.assertEqual(inner["status"], "ready")
                self.assertFalse(set(inner["train"]["profile_ids"]) &
                                 set(inner["validation"]["profile_ids"]))
                self.assertFalse(set(inner["train"]["source_primary_ids"]) &
                                 set(inner["validation"]["source_primary_ids"]))
                self.assertTrue(set(inner["train"]["condition_ids"]) <= training)
                self.assertTrue(set(inner["validation"]["condition_ids"]) <= training)
                inner_seen.update(inner["validation"]["condition_ids"])
            self.assertEqual(inner_seen, training)
            self.assertEqual(fold["proxy_ready"], len(training))
        self.assertEqual(seen, self.snapshot.development_conditions)
        self.assertEqual(self.cv["selection_score"]["complete_native_folds"], 3)
        self.assertIsNotNone(self.cv["selection_score"]["native_poisson_nll"])

    def test_F_stopping_proxies_are_created_inside_C_without_S_sources(self):
        for outer in self.cv["folds"]:
            selection = outer["F"]["epoch_selection"]
            self.assertEqual(selection["status"], "nested_grouped_stop")
            core, stop = selection["fit"], selection["stop"]
            core_profiles, stop_profiles = set(core["profile_ids"]), set(stop["profile_ids"])
            stop_sources = set(stop["source_primary_ids"])
            self.assertFalse(core_profiles & stop_profiles)
            self.assertEqual(core_profiles | stop_profiles, set(outer["train"]["profile_ids"]))
            self.assertEqual(len(selection["inner_R_folds"]), 2)
            for inner in selection["inner_R_folds"]:
                for side in ("train", "validation"):
                    self.assertTrue(set(inner[side]["profile_ids"]) <= core_profiles)
                    self.assertFalse(set(inner[side]["profile_ids"]) & stop_profiles)
                    self.assertFalse(set(inner[side]["source_primary_ids"]) & stop_sources)

    def test_final_F_proxies_retain_three_fold_lineage_and_never_use_full_scope_R(self):
        self.assertEqual(self.final["R"]["status"], "ready", self.final["R"])
        self.assertEqual(self.final["F"]["status"], "ready", self.final["F"])
        audit = read_json(self.final_dir / "R_three_fold_provenance.json")
        proxies = read_json(self.final_dir / "F_development_oof_proxies.json")
        self.assertEqual(len(audit), 3)
        self.assertEqual({r["condition_id"] for r in proxies}, self.snapshot.development_conditions)
        outer_R_keys = {r["R_cache_key"] for r in audit}
        self.assertNotIn(self.r_model.metadata["cache_key"], outer_R_keys)
        for proxy in proxies:
            self.assertEqual(proxy["status"], "ready")
            condition = self.snapshot.conditions[proxy["condition_id"]]
            trained = proxy["training_footprint"]
            self.assertNotIn(condition["profile_id"], trained["profile_ids"])
            self.assertNotIn(condition["condition_id"], trained["condition_ids"])
            target_sources = {p["source_primary_id"] for p in self.snapshot.primaries.values()
                              if p["condition_id"] == condition["condition_id"]}
            self.assertFalse(target_sources & set(trained["source_primary_ids"]))
            self.assertIn(proxy["provenance"]["R_cache_key"], outer_R_keys)
            self.assertNotEqual(proxy["provenance"]["R_cache_key"], self.r_model.metadata["cache_key"])
            self.assertFalse(proxy["native_truth"])
        self.assertEqual(self.f_model.metadata["proxy_state_labels"], 0)
        self.assertGreater(self.f_model.metadata["native_count_rows"], 0)
        self.assertTrue(self.f_model.metadata["native_precedence"])
        self.assertEqual(self.final["model_card"]["synthetic_only"], True)
        self.assertFalse(self.final["model_card"]["scientific_accuracy_claim"])
        calibration = self.r_model.metadata["probability_calibration"]
        self.assertEqual(calibration["status"], "estimated_oof_for_refit")
        self.assertFalse(calibration["independent_calibration_validation"])
        development_ids = set(self.snapshot.view(self.snapshot.development_conditions).footprint()["response_ids"])
        self.assertTrue(set(calibration["response_ids"]) <= development_ids)

    def test_proxy_only_R_A_F_path_trains_without_native_counts(self):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot.counts = []
        result = fit_final(snapshot, self.config, self.root / "proxy-only-final")
        self.assertEqual(result["R"]["status"], "ready")
        self.assertEqual(result["F"]["status"], "ready")
        model = FArtifact.load(self.root / "proxy-only-final" / "F")
        self.assertEqual(model.metadata["native_count_rows"], 0)
        self.assertEqual(model.metadata["proxy_state_labels"], len(snapshot.development_conditions) * 2)
        self.assertEqual(model.trained_states, [0, 1])
        self.assertTrue(all(p["probability_status"] == "uncalibrated"
                            for p in model.metadata["proxy_provenance"]))
        self.assertEqual(model.metadata["epoch_selection"]["status"], "nested_grouped_stop")

    def test_saved_R_and_F_preserve_predictions_and_unknown_domains_fail(self):
        view = self.snapshot.view(self.snapshot.development_conditions)
        conditions = view.conditions[:3]
        samples = response_samples(view)[:5]
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            path = Path(directory)
            self.r_model.save(path / "R")
            self.f_model.save(path / "F")
            self.assertEqual(self.r_model.predict_samples(samples),
                             RArtifact.load(path / "R").predict_samples(samples))
            self.assertEqual(self.f_model.predict(conditions),
                             FArtifact.load(path / "F").predict(conditions))
        foreign = copy.deepcopy(conditions)
        foreign[0]["domain"] = "unseen-device-model-not-trained"
        with self.assertRaisesRegex(DataError, "domain"):
            self.f_model.predict(foreign)
        foreign_samples = copy.deepcopy(samples)
        foreign_samples[0]["condition"]["domain"] = "unseen-device-model-not-trained"
        with self.assertRaisesRegex(DataError, "domain"):
            self.r_model.predict_samples(foreign_samples)

    def test_sealed_labels_were_never_opened_during_prepare_CV_or_final(self):
        self.assertEqual(self.sealed_attempts, [])
        self.assertFalse(self.preparation["sealed_labels_opened"])
        self.assertFalse(self.cv["sealed_labels_read"])
        self.assertFalse(self.final["sealed_labels_read"])
        self.assertNotIn(str(self.manifest.parent / "sealed" / "labels.jsonl"),
                         self.snapshot.read_files)

    def test_R_missing_upset_or_mechanism_does_not_block_native_F_supervision(self):
        for missing in ("upset", "mechanism"):
            with self.subTest(missing=missing):
                changed = copy.deepcopy(self.snapshot)
                if missing == "upset":
                    for response in changed.responses:
                        response["labels"]["upset"] = None
                else:
                    changed.controls = []
                report = cross_validate(changed, self.config)
                for fold in report["folds"]:
                    self.assertEqual(fold["F"]["status"], "ready", fold["F"])
                    self.assertGreater(fold["F"]["metrics"]["native_count_rows"], 0)
                    self.assertEqual(fold["proxy_ready"], 0)
                    if missing == "mechanism":
                        self.assertEqual(fold["R"]["status"], "pending")
                    else:
                        self.assertEqual(fold["R"]["status"], "ready")
                        self.assertNotIn("upset", fold["R"]["metrics"]["heads"])


class PipelineCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = make_fixture(self.root / "synthetic", profiles=6)
        self.snapshot = Snapshot.load(self.manifest)

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = cli.main(list(map(str, args)))
        return status, stdout.getvalue(), stderr.getvalue()

    def block_fitting(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        mocks = []
        for name in ("cross_validate", "run_search", "fit_final", "fit_r", "fit_f"):
            mocks.append(stack.enter_context(patch(
                f"dram_predictor.pipeline.{name}",
                side_effect=AssertionError("This command must not invoke a fit"))))
        mocks.append(stack.enter_context(patch(
            "dram_predictor.f_training.fit_f_core",
            side_effect=AssertionError("This command must not invoke an optimizer"))))
        return mocks

    def test_train_without_execute_is_read_only_for_all_stages(self):
        mocks = self.block_fitting()
        for stage in ("cv", "search", "final", "ablations"):
            with self.subTest(stage=stage):
                output = self.root / f"must-not-create-{stage}"
                status, stdout, stderr = self.invoke(
                    "train", self.manifest, "--stage", stage, "--out", output)
                self.assertEqual(status, 0, stderr)
                result = json.loads(stdout)
                self.assertFalse(result["training_started"])
                self.assertEqual(result["requested_stage"], stage)
                self.assertFalse(output.exists())
        self.assertTrue(all(mock.call_count == 0 for mock in mocks))

    def test_inspect_and_prepare_freeze_valid_hash_without_training(self):
        mocks = self.block_fitting()
        status, stdout, stderr = self.invoke("inspect", self.manifest)
        self.assertEqual(status, 0, stderr)
        self.assertFalse(json.loads(stdout)["training_started"])
        destination = self.root / "prepared"
        status, stdout, stderr = self.invoke("prepare", self.manifest, "--out", destination)
        self.assertEqual(status, 0, stderr)
        report = json.loads(stdout)
        self.assertFalse(report["training_started"])
        self.assertEqual(report["split_status"], "frozen")
        frozen = read_json(destination / "splits.json")
        checksum = frozen.pop("split_hash")
        self.assertEqual(checksum, digest(frozen))
        self.assertEqual(checksum, report["split_hash"])
        self.assertEqual(len(frozen_folds(
            self.snapshot.view(self.snapshot.development_conditions), destination / "splits.json")), 3)
        self.assertTrue(all(mock.call_count == 0 for mock in mocks))

    def test_changed_snapshot_is_rejected_before_execute_can_fit(self):
        prepared = self.root / "prepared"
        prepare(self.snapshot, prepared)
        rows = read_rows(self.manifest.parent / "responses.jsonl")
        rows[0]["labels"]["margin_V"] += .123
        rewrite_table(self.manifest, "responses.jsonl", rows)
        mocks = self.block_fitting()
        status, stdout, stderr = self.invoke(
            "train", self.manifest, "--execute", "--stage", "final",
            "--prepared", prepared, "--out", self.root / "must-not-train")
        self.assertEqual(status, 2)
        self.assertEqual(stdout, "")
        self.assertIn("Snapshot changed after preparation", stderr)
        self.assertTrue(all(mock.call_count == 0 for mock in mocks))
        self.assertFalse((self.root / "must-not-train").exists())

    def test_tampered_frozen_split_is_rejected(self):
        prepared = self.root / "prepared"
        prepare(self.snapshot, prepared)
        path = prepared / "splits.json"
        payload = read_json(path)
        payload["split_seed"] += 1
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(LeakageError, "hash mismatch"):
            frozen_folds(self.snapshot.view(self.snapshot.development_conditions), path)

    def test_execute_without_prepared_split_cannot_train(self):
        mocks = self.block_fitting()
        status, _, stderr = self.invoke("train", self.manifest, "--execute", "--out", self.root / "out")
        self.assertEqual(status, 2)
        self.assertIn("--prepared", stderr)
        self.assertTrue(all(mock.call_count == 0 for mock in mocks))

    def test_search_runs_twelve_candidates_then_two_extra_seeds_and_keeps_native_priority(self):
        calls = []

        def fake_cv(snapshot, config, **kwargs):
            index = len(calls)
            calls.append((snapshot, config, kwargs))
            # Candidate 0 has the best R score but one failed F fold. Candidate 2
            # has the best complete native score and must remain eligible.
            native = None if index == 0 else .2 if index == 2 or index >= 12 else 1. + index
            folds = []
            for number in range(3):
                f = ({"status": "pending", "reason": "synthetic missing F fold"}
                     if native is None and number == 0 else
                     {"status": "ready", "metrics": {"native_poisson_nll": native or .01}})
                folds.append({"F": f, "R": {"status": "ready", "metrics": {
                    "heads": {"upset": {"brier": .001 if index == 0 else .2}}}}})
            result = {"folds": folds, "config": config.to_dict(),
                      "kind": "synthetic_fixture", "sealed_labels_read": False}
            result["selection_score"] = selection_score(result)
            return result

        base = Config(max_epochs=2, patience=1, r_hidden=(4, 4), f_hidden=(4, 4))
        output = self.root / "mocked-search"
        with patch("dram_predictor.pipeline.cross_validate", side_effect=fake_cv):
            selected = run_search(self.snapshot, base, output)
        self.assertEqual(len(calls), 14)
        self.assertEqual([config.seed for _, config, _ in calls[:12]], [1729] * 12)
        self.assertEqual([config.seed for _, config, _ in calls[12:]], [2718, 31415])
        self.assertEqual(len({digest(config.to_dict()) for _, config, _ in calls[:12]}), 12)
        self.assertEqual(selected["candidate"], 2)
        self.assertEqual(selected["criterion"], "native_poisson_nll")
        self.assertEqual(selected["qualification"], "native_count_development_selection")
        manifest = read_json(output / "search_manifest.json")
        self.assertEqual(len(manifest["configurations"]), 12)
        self.assertEqual(manifest["selected_repeats"], [1729, 2718, 31415])
        self.assertEqual(set(read_json(output / "stability.json")["scores"]), {"1729", "2718", "31415"})


if __name__ == "__main__":
    unittest.main()
