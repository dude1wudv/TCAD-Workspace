"""Adversarial tests of scientific data isolation, using artificial samples."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from dram_predictor.data import DataError, LeakageError, Snapshot, head_valid
from dram_predictor.features import Encoder, record
from dram_predictor.splits import connected_groups, grouped_folds, split_manifest, stopping_split
from fixtures import make_fixture, make_snapshot, read_rows, rewrite_table


class DataIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fixture(self, **kwargs):
        return make_fixture(self.root, **kwargs)

    def test_frozen_plan_42_profiles_make_28_14_profile_folds(self):
        path = self.fixture(profiles=42, conditions_per_profile=6)
        snapshot = Snapshot.load(path)
        folds = grouped_folds(snapshot.view(snapshot.development_conditions))
        self.assertEqual(len(folds), 3)
        validated = set()
        for fold in folds:
            self.assertEqual((len(fold.train.profiles), len(fold.validation.profiles)), (28, 14))
            self.assertEqual((len(fold.train.conditions), len(fold.validation.conditions)), (168, 84))
            self.assertFalse(fold.train.source_ids & fold.validation.source_ids)
            self.assertFalse(validated & fold.validation.condition_ids)
            validated |= fold.validation.condition_ids
            # Both states and all descendants stay attached to their source.
            train_primaries = {r["primary_id"] for r in fold.train.responses}
            validation_primaries = {r["primary_id"] for r in fold.validation.responses}
            self.assertFalse(train_primaries & validation_primaries)
        self.assertEqual(validated, snapshot.development_conditions)

    def test_shared_transport_event_connects_profiles_before_split(self):
        path = self.fixture()
        rows = read_rows(self.root / "primaries.jsonl")
        a = next(r for r in rows if r["condition_id"].startswith("synthetic-profile-000:"))
        b = next(r for r in rows if r["condition_id"].startswith("synthetic-profile-001:"))
        b["source_primary_id"], b["source_hash"] = a["source_primary_id"], a["source_hash"]
        rewrite_table(path, "primaries.jsonl", rows)
        snapshot = Snapshot.load(path)
        view = snapshot.view(snapshot.development_conditions)
        self.assertEqual(len(connected_groups(view)), 11)
        for fold in grouped_folds(view):
            self.assertEqual("synthetic-profile-000" in fold.train.profiles,
                             "synthetic-profile-001" in fold.train.profiles)
            fold.train.assert_disjoint(fold.validation)

    def test_shared_control_also_connects_profiles(self):
        path = self.fixture()
        rows = read_rows(self.root / "controls.jsonl")
        rows[0]["source_control_id"] = "synthetic-control-reused"
        rows[2]["source_control_id"] = "synthetic-control-reused"
        rewrite_table(path, "controls.jsonl", rows)
        snapshot = Snapshot.load(path)
        view = snapshot.view(snapshot.development_conditions)
        self.assertEqual(len(connected_groups(view)), 11)
        for fold in grouped_folds(view):
            self.assertEqual("synthetic-profile-000" in fold.train.profiles,
                             "synthetic-profile-001" in fold.train.profiles)

    def test_transitive_event_control_and_count_reuse_forms_one_group(self):
        path = self.fixture()
        primaries = read_rows(self.root / "primaries.jsonl")
        source_a = next(r for r in primaries if r["condition_id"].startswith("synthetic-profile-000:"))
        source_b = next(r for r in primaries if r["condition_id"].startswith("synthetic-profile-001:"))
        source_b["source_primary_id"] = source_a["source_primary_id"]
        source_b["source_hash"] = source_a["source_hash"]
        rewrite_table(path, "primaries.jsonl", primaries)
        controls = read_rows(self.root / "controls.jsonl")
        controls[2]["source_control_id"] = controls[4]["source_control_id"] = "synthetic-B-C-control"
        rewrite_table(path, "controls.jsonl", controls)
        counts = read_rows(self.root / "counts.jsonl")
        counts[8]["source_primary_ids"].append("synthetic-independent-C-D-exposure:0")
        counts[12]["source_primary_ids"].append("synthetic-independent-C-D-exposure:0")
        rewrite_table(path, "counts.jsonl", counts)
        snapshot = Snapshot.load(path)
        view = snapshot.view(snapshot.development_conditions)
        self.assertEqual(len(connected_groups(view)), 9)
        linked = {f"synthetic-profile-{i:03d}" for i in range(4)}
        for fold in grouped_folds(view):
            self.assertIn(len(linked & fold.train.profiles), (0, 4))
            self.assertIn(len(linked & fold.validation.profiles), (0, 4))
            fold.train.assert_disjoint(fold.validation)

    def test_native_count_cannot_hide_a_sealed_transport_source(self):
        path = self.fixture()
        rows = read_rows(self.root / "counts.jsonl")
        primary = next(r for r in read_rows(self.root / "primaries.jsonl")
                       if r["condition_id"] == "synthetic-sealed:high_energy")
        rows[0]["source_primary_ids"].append(primary["source_primary_id"])
        rewrite_table(path, "counts.jsonl", rows)
        with self.assertRaisesRegex(LeakageError, "reuses a sealed primary"):
            Snapshot.load(path)

    def test_cannot_manufacture_three_folds_from_two_connected_groups(self):
        path = self.fixture(profiles=2)
        snapshot = Snapshot.load(path)
        with self.assertRaisesRegex(LeakageError, "Need 3 independent"):
            grouped_folds(snapshot.view(snapshot.development_conditions))

    def test_known_profile_test_is_allowed_but_test_view_is_not_fit_scope(self):
        snapshot = Snapshot.load(self.fixture())
        development_profiles = {snapshot.conditions[k]["profile_id"]
                                for k in snapshot.development_conditions}
        self.assertIn(snapshot.conditions["synthetic-sealed:new_combination"]["profile_id"],
                      development_profiles)
        self.assertIn(snapshot.conditions["synthetic-sealed:high_energy"]["profile_id"],
                      development_profiles)
        self.assertNotIn(snapshot.conditions["synthetic-sealed:device_extrapolation"]["profile_id"],
                         development_profiles)
        with self.assertRaises(LeakageError):
            snapshot.view(["synthetic-sealed:new_combination"])

    def test_reused_primary_cannot_cross_into_known_profile_test(self):
        path = self.fixture()
        rows = read_rows(self.root / "primaries.jsonl")
        held = next(r for r in rows if r["condition_id"] == "synthetic-sealed:new_combination")
        held["source_primary_id"] = rows[0]["source_primary_id"]
        rewrite_table(path, "primaries.jsonl", rows)
        with self.assertRaisesRegex(LeakageError, "crosses development"):
            Snapshot.load(path)

    def test_unseen_profile_control_cannot_enter_calibration_table(self):
        path = self.fixture()
        rows = read_rows(self.root / "controls.jsonl")
        held = copy.deepcopy(rows[0])
        held.update(control_id="poison-test-control", profile_id="synthetic-unseen-profile",
                    cohort="device_extrapolation")
        rows.append(held)
        rewrite_table(path, "controls.jsonl", rows)
        with self.assertRaisesRegex(LeakageError, "control entered development"):
            Snapshot.load(path)

    def test_known_profile_sealed_controls_and_responses_are_still_rejected(self):
        path = self.fixture()
        controls = read_rows(self.root / "controls.jsonl")
        controls[0]["cohort"] = "new_combination"
        rewrite_table(path, "controls.jsonl", controls)
        with self.assertRaises(LeakageError):
            Snapshot.load(path)
        controls[0]["cohort"] = "development"
        rewrite_table(path, "controls.jsonl", controls)
        responses = read_rows(self.root / "responses.jsonl")
        responses[0]["primary_id"] = "synthetic-sealed:new_combination:primary:0"
        rewrite_table(path, "responses.jsonl", responses)
        with self.assertRaisesRegex(LeakageError, "sealed/unknown primary"):
            Snapshot.load(path)

    def test_repair_replaces_one_label_without_doubling_primary_or_states(self):
        path = self.fixture()
        before = Snapshot.load(path)
        rows = read_rows(self.root / "responses.jsonl")
        old = rows[0]
        old["status"] = "failed"
        repaired = copy.deepcopy(old)
        repaired.update(response_id=old["response_id"] + ":repair", status="valid",
                        supersedes=old["response_id"], run_id=old["run_id"] + ":repair")
        rows.append(repaired)
        rewrite_table(path, "responses.jsonl", rows)
        after = Snapshot.load(path)
        self.assertEqual(len(after.responses), len(before.responses))
        self.assertEqual(len(after.primaries), len(before.primaries))
        self.assertEqual(len(after.superseded), 1)
        active = {r["response_id"] for r in after.responses}
        self.assertNotIn(old["response_id"], active)
        self.assertIn(repaired["response_id"], active)

    def test_silent_duplicate_and_identity_changing_repair_are_rejected(self):
        path = self.fixture()
        rows = read_rows(self.root / "responses.jsonl")
        duplicate = copy.deepcopy(rows[0])
        duplicate["response_id"] += ":duplicate"
        rows.append(duplicate)
        rewrite_table(path, "responses.jsonl", rows)
        with self.assertRaisesRegex(DataError, "Multiple active"):
            Snapshot.load(path)
        duplicate["supersedes"] = rows[0]["response_id"]
        duplicate["state"] = 1 - rows[0]["state"]
        rewrite_table(path, "responses.jsonl", rows)
        with self.assertRaisesRegex(LeakageError, "changes primary/state/bit"):
            Snapshot.load(path)

    def test_repair_cycles_and_conflicting_branches_are_rejected(self):
        path = self.fixture()
        rows = read_rows(self.root / "responses.jsonl")
        a = rows[0]
        b, c = copy.deepcopy(a), copy.deepcopy(a)
        b.update(response_id=a["response_id"] + ":repair-b", supersedes=a["response_id"])
        c.update(response_id=a["response_id"] + ":repair-c", supersedes=a["response_id"])
        rewrite_table(path, "responses.jsonl", rows + [b, c])
        with self.assertRaisesRegex(DataError, "Conflicting repair branches"):
            Snapshot.load(path)
        a["supersedes"] = b["response_id"]
        rewrite_table(path, "responses.jsonl", rows + [b])
        with self.assertRaisesRegex(DataError, "Cyclic repair lineage"):
            Snapshot.load(path)

    def test_missing_failed_and_unresolved_are_not_automatic_negatives(self):
        row = {"status": "failed", "masks": {"upset": True, "delta_voltage_V": True},
               "upset_definition_id": "synthetic-test-only"}
        self.assertFalse(head_valid(row, "upset"))
        self.assertFalse(head_valid(row, "delta_voltage_V"))
        row["status"] = "unresolved"
        self.assertFalse(head_valid(row, "upset"))
        self.assertTrue(head_valid(row, "delta_voltage_V"))
        row["status"] = "valid"
        del row["upset_definition_id"]
        self.assertFalse(head_valid(row, "upset"))

    def test_generation_mismatch_and_postsimulation_condition_feature_rejected(self):
        path = self.fixture()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["simulation_revision"] = "v3"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(DataError, "historical v3/v4"):
            Snapshot.load(path)
        manifest["simulation_revision"] = "0.4"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        rows = read_rows(self.root / "conditions.jsonl")
        rows[0]["features"]["collected_charge_fC"] = 1.
        rewrite_table(path, "conditions.jsonl", rows)
        with self.assertRaisesRegex(LeakageError, "Unapproved/pre-simulation"):
            Snapshot.load(path)

    def test_sealed_poison_or_missing_files_are_never_opened(self):
        path = self.fixture()
        original = Path.open
        touched = []

        def guarded(file, *args, **kwargs):
            if "sealed" in file.parts:
                raise AssertionError("A sealed label file was opened")
            touched.append(file.name)
            return original(file, *args, **kwargs)

        with patch.object(Path, "open", guarded):
            snapshot = Snapshot.load(path)
            split = split_manifest(snapshot.view(snapshot.development_conditions))
        self.assertFalse(any("sealed" in p for p in snapshot.read_files))
        self.assertEqual(len(split["sealed"]["new_combination"]), 1)
        self.assertNotIn("labels.jsonl", touched)

    def test_sealed_labels_cannot_change_development_fingerprint_or_splits(self):
        path = self.fixture()
        initial = Snapshot.load(path)
        original = split_manifest(initial.view(initial.development_conditions))
        (self.root / "sealed" / "labels.jsonl").write_text(
            json.dumps({"upset": 1, "voltage_V": [1e100], "invalid": "not a response"}) + "\n",
            encoding="utf-8")
        changed = Snapshot.load(path)
        self.assertEqual(original, split_manifest(changed.view(changed.development_conditions)))
        (self.root / "sealed" / "labels.jsonl").unlink()
        absent = Snapshot.load(path)
        self.assertEqual(original, split_manifest(absent.view(absent.development_conditions)))

    def test_development_path_cannot_alias_sealed_file(self):
        path = self.fixture()
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["development"]["responses_file"] = manifest["sealed"]["responses_file"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(LeakageError, "aliases a sealed"):
            Snapshot.load(path)

    def test_labels_do_not_change_fold_membership_or_training_fingerprint(self):
        path = self.fixture()
        snapshot = Snapshot.load(path)
        fold = grouped_folds(snapshot.view(snapshot.development_conditions))[0]
        fit_digest = fold.train.fingerprint()
        original_ids = [(f.train.condition_ids, f.validation.condition_ids)
                        for f in grouped_folds(snapshot.view(snapshot.development_conditions))]
        held_primaries = {p["primary_id"] for p in fold.validation.primaries}
        rows = read_rows(self.root / "responses.jsonl")
        for row in rows:
            if row["primary_id"] in held_primaries:
                row["labels"]["port_charge_fC"] = 1e99
                row["labels"]["delta_voltage_V"] = [1e88] * len(snapshot.times)
                row["labels"]["upset"] = 1 - row["labels"]["upset"]
        rewrite_table(path, "responses.jsonl", rows)
        tainted = Snapshot.load(path)
        new_folds = grouped_folds(tainted.view(tainted.development_conditions))
        self.assertEqual(original_ids, [(f.train.condition_ids, f.validation.condition_ids) for f in new_folds])
        self.assertEqual(fit_digest, new_folds[0].train.fingerprint())

    def test_each_nested_training_subset_contains_both_synthetic_classes(self):
        snapshot = Snapshot.load(self.fixture())
        view = snapshot.view(snapshot.development_conditions)
        for outer in grouped_folds(view):
            for inner in grouped_folds(outer.train, n_splits=2):
                fit, stop = stopping_split(inner.train)
                for part in (fit, stop, inner.validation):
                    classes = {r["labels"]["upset"] for r in part.responses
                               if head_valid(r, "upset")}
                    self.assertEqual(classes, {0, 1})
                fit.assert_disjoint(stop)
                fit.assert_disjoint(inner.validation)
                fit.assert_disjoint(outer.validation)

    def test_early_stopping_uses_whole_groups(self):
        snapshot = Snapshot.load(self.fixture())
        train, stop = stopping_split(snapshot.view(snapshot.development_conditions))
        train.assert_disjoint(stop)
        self.assertEqual(train.condition_ids | stop.condition_ids, snapshot.development_conditions)
        self.assertTrue(stop.condition_ids)


class FeatureBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.snapshot = Snapshot.load(make_fixture(Path(self.tmp.name)))
        self.fold = grouped_folds(self.snapshot.view(self.snapshot.development_conditions))[0]

    def test_encoder_fits_train_only_and_outside_values_do_not_mutate_it(self):
        training = [record(c) for c in self.fold.train.conditions]
        encoder = Encoder("F").fit(training)
        state = copy.deepcopy(encoder.to_dict())
        poisoned = record(self.fold.validation.conditions[0])
        poisoned["capacitance_fF"] = 1e40
        prediction_inputs = encoder.transform([poisoned])
        self.assertTrue(np.isfinite(prediction_inputs).all())
        self.assertIn("capacitance_fF", encoder.outside_support([poisoned])[0])
        self.assertEqual(state, encoder.to_dict())
        self.assertNotIn("profile_id", encoder.numeric)
        self.assertNotIn("seed", encoder.numeric)

    def test_F_rejects_postsimulation_fields_even_when_unselected(self):
        row = record(self.fold.train.conditions[0])
        row["deposited_energy_MeV"] = 0.5
        with self.assertRaisesRegex(LeakageError, "cannot consume"):
            Encoder("F").fit([row])
        encoder = Encoder("F").fit([record(c) for c in self.fold.train.conditions])
        with self.assertRaises(LeakageError):
            encoder.transform([row])

    def test_unknown_species_is_not_encoded_as_known_proton(self):
        encoder = Encoder("F").fit([record(c) for c in self.fold.train.conditions])
        row = record(self.fold.validation.conditions[0])
        row["particle"] = "neutron"
        with self.assertRaisesRegex(DataError, "Unsupported categorical"):
            encoder.transform([row])

    def test_roundtrip_retains_training_statistics_and_forbidden_columns_rejected(self):
        rows = [record(c) for c in self.fold.train.conditions]
        encoder = Encoder("F").fit(rows)
        loaded = Encoder.from_dict(encoder.to_dict())
        np.testing.assert_array_equal(encoder.transform(rows), loaded.transform(rows))
        malformed = encoder.to_dict()
        malformed["numeric"] = list(malformed["numeric"]) + ["generated_charge_fC"]
        with self.assertRaises(LeakageError):
            Encoder.from_dict(malformed)


if __name__ == "__main__":
    unittest.main()
