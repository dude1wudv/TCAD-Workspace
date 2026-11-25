"""Synthetic r0.6 intake and preparation checks."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from dram_predictor.cli import main
from dram_predictor.data import DataError, LeakageError, Snapshot, file_hash, read_json, write_json
from dram_predictor.ingest import build_snapshot
from dram_predictor.pipeline import aggregate_view, prepare, readiness
from dram_predictor.r_training import response_samples
from fixtures import make_snapshot, read_rows, rewrite_table


class R06SnapshotTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.manifest_path = make_snapshot(self.root, profiles=3, conditions_per_profile=1,
                                           primaries_per_condition=3, with_counts=False, with_sealed=False)
        self.deck = "synthetic-r06-hold-test"
        manifest = read_json(self.manifest_path)
        manifest.update(simulation_revision="0.6", deck_timing_version=self.deck, source_time_ns=22.)
        manifest["sealed"] = {"responses_file": "sealed-poison.jsonl"}
        self.root.joinpath("sealed-poison.jsonl").write_text("sealed data must stay closed\n", encoding="utf-8")
        write_json(self.manifest_path, manifest)
        self.conditions = read_rows(self.root / "conditions.jsonl")
        self.primaries = read_rows(self.root / "primaries.jsonl")
        self.responses = [row for row in read_rows(self.root / "responses.jsonl") if row["state"] == 1]
        self.controls = read_rows(self.root / "controls.jsonl")
        for condition in self.conditions:
            condition.update(radiation_id="G2", split="development", holdout=None)
        for primary in self.primaries:
            primary.pop("sampling")
        for row in self.responses + self.controls:
            row.update(deck_timing_version=self.deck, input_sha256={"synthetic-input": "a" * 64})
        for row in self.responses:
            row.update(radiation_id="G2", source_time_ns=22., source_shape_id="pool-event",
                       scale_factor=1., selection_mechanism="simple_random",
                       inclusion_probability=1., statistics_eligible=False)
        for control in self.controls:
            control.update(source_time_ns=None, selection_mechanism="no_particle_control")
        self.save()

    def save(self):
        for name, rows in (("conditions.jsonl", self.conditions), ("primaries.jsonl", self.primaries),
                           ("responses.jsonl", self.responses), ("controls.jsonl", self.controls)):
            rewrite_table(self.manifest_path, name, rows)

    def test_cli_ingest_prepare_retains_b1_only_and_closes_holdout_labels(self):
        for profile, radiation, cohort, length, energy in [
            (self.conditions[0]["profile_id"], "C2", "radiation_holdout", 11.4, 20.),
            (self.conditions[0]["profile_id"], "C3", "radiation_holdout", 11.4, 150.),
            ("H0-long-channel", "G2", "profile_holdout", 16.8, 20.),
            ("H1-lhs-holdout-a", "G2", "profile_holdout", 11.69, 20.),
            ("H2-lhs-holdout-b", "G2", "profile_holdout", 14.07, 20.),
        ]:
            row = deepcopy(self.conditions[0])
            row.update(condition_id=f"{profile}/{radiation}", profile_id=profile, radiation_id=radiation, cohort=cohort,
                       split=cohort, holdout=cohort.removesuffix("_holdout"))
            row["features"].update(gate_length_nm=length, incident_energy_MeV=energy)
            self.conditions.append(row)
        self.save()
        export = self.root / "export"
        prepared = self.root / "prepared"
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["ingest", str(self.manifest_path), "--out", str(export)]), 0)
            self.assertEqual(main(["prepare", str(export / "manifest.json"), "--out", str(prepared)]), 0)
        status = read_json(prepared / "readiness.json")
        self.assertEqual(status["development_response_rows_by_state"], [0, 9])
        self.assertEqual(status["supervised_upset_rows_by_state"], [0, 9])
        self.assertEqual(status["conditions"]["profile_holdout"], 3)
        self.assertEqual(status["conditions"]["radiation_holdout"], 2)
        self.assertEqual(status["split_status"], "frozen")
        self.assertFalse(status["sealed_labels_opened"])
        self.assertFalse(status["training_started"])
        snapshot = Snapshot.load(export / "manifest.json")
        with self.assertRaises(LeakageError):
            snapshot.view({"H1-lhs-holdout-a/G2"})

    def test_development_cannot_claim_frozen_radiation_holdout(self):
        self.conditions[0]["radiation_id"] = "C2"
        self.save()
        with self.assertRaisesRegex(LeakageError, "split/holdout"):
            Snapshot.load(self.manifest_path)

    def test_bad_timing_scale_probability_and_input_map_fail(self):
        for field, value in [("source_time_ns", 15.), ("deck_timing_version", "legacy"),
                             ("scale_factor", 2.), ("inclusion_probability", 0.),
                             ("inclusion_probability", 1.01), ("input_sha256", "a" * 64)]:
            with self.subTest(field=field, value=value):
                rewrite_table(self.manifest_path, "responses.jsonl",
                              [dict(self.responses[0], **{field: value})])
                with self.assertRaisesRegex(DataError, field.replace("scale_factor", "scale")):
                    Snapshot.load(self.manifest_path)

    def test_scaled_sibling_responses_and_same_scale_repair_keep_physical_lineage(self):
        base = self.responses[1]
        scaled = dict(base, response_id="synthetic-scaled", run_id="synthetic-scaled-run",
                      scale_factor=3., selection_mechanism="threshold_scaled",
                      inclusion_probability=None, source_shape_id="shape-a")
        repaired = dict(scaled, response_id="synthetic-repair", run_id="synthetic-repair-run",
                        supersedes=scaled["response_id"])
        rewrite_table(self.manifest_path, "responses.jsonl", [base, scaled, repaired])
        snapshot = Snapshot.load(self.manifest_path)
        self.assertEqual({row["scale_factor"] for row in snapshot.responses}, {1., 3.})
        self.assertEqual([row["response_id"] for row in snapshot.superseded], ["synthetic-scaled"])
        repaired["scale_factor"] = 10.
        rewrite_table(self.manifest_path, "responses.jsonl", [base, scaled, repaired])
        with self.assertRaisesRegex(LeakageError, "frozen sampling design"):
            Snapshot.load(self.manifest_path)

    def test_b1_proxy_and_missing_mapping_do_not_invent_b0_or_zero(self):
        missing = self.primaries[0]
        missing.update(source_features=None, source_off=None)
        self.responses[0].update(status="failed", labels={}, masks={})
        self.save()
        snapshot = Snapshot.load(self.manifest_path)
        scope = snapshot.view(snapshot.development_conditions)
        predicted = Mock(side_effect=lambda samples: [
            {"primary_id": sample["primary"]["primary_id"], "state": sample["state"],
             "bit_id": sample["bit"]["bit_id"], "probability": .25} for sample in samples
        ])
        artifact = SimpleNamespace(predict_samples=predicted, metadata={
            "training_footprint": {"profile_ids": [], "source_primary_ids": [], "source_control_ids": []},
            "trained_heads": ["upset"], "upset_states": [1], "probability_calibration": {},
            "training_fingerprint": "synthetic-only",
        })
        rows = {row["condition_id"]: row for row in aggregate_view(artifact, scope)}
        self.assertEqual(rows[missing["condition_id"]]["status"], "pending")
        self.assertIsNone(rows[self.conditions[1]["condition_id"]]["sigma_cm2_per_bit"][0])
        self.assertAlmostEqual(rows[self.conditions[1]["condition_id"]]["sigma_cm2_per_bit"][1], 2.5e-9)
        self.assertTrue(all(s["state"] == 1 for call in predicted.call_args_list for s in call.args[0]))

    def test_r06_trace_uses_declared_source_time_and_same_state_control(self):
        row = self.responses[0]
        specs = {}
        for name, csv in {"signal": "t,v\n21,1\n22,2\n30,3\n",
                          "control": "t,v\n21,1\n22,1\n30,1\n"}.items():
            path = self.root / f"{name}.csv"
            path.write_text(csv, encoding="utf-8")
            specs[name] = {"path": path.name, "sha256": file_hash(path), "format": "csv",
                           "time_column": "t", "voltage_column": "v", "time_unit": "ns", "voltage_unit": "V"}
        protocol = self.conditions[0]["protocol_id"]
        row.update(labels={}, masks={}, trace=specs["signal"], control_trace=specs["control"],
                   matching_control={"state": 1, "profile_id": self.conditions[0]["profile_id"],
                                     "protocol_id": protocol, "deck_timing_version": self.deck})
        rewrite_table(self.manifest_path, "responses.jsonl", [row])
        snapshot = Snapshot.load(build_snapshot(self.manifest_path, self.root / "matched"))
        self.assertEqual(snapshot.responses[0]["labels"]["delta_voltage_V"][:2], [.5, 1.])
        self.assertNotIn("upset", snapshot.responses[0]["labels"])
        row["matching_control"]["deck_timing_version"] = "different"
        rewrite_table(self.manifest_path, "responses.jsonl", [row])
        snapshot = Snapshot.load(build_snapshot(self.manifest_path, self.root / "mismatch"))
        self.assertEqual(snapshot.responses[0]["status"], "failed")
        self.assertIn("deck timing differs", snapshot.responses[0]["extraction_error"])

    def test_all_missing_waveform_does_not_require_a_source_mapping(self):
        self.primaries[0].update(source_features=None, source_off=None)
        row = self.responses[0]
        row.update(status="unresolved", labels={"delta_voltage_V": [None] * 8},
                   masks={"delta_voltage_V": True})
        self.save()
        snapshot = Snapshot.load(self.manifest_path)
        samples = response_samples(snapshot.view(snapshot.development_conditions))
        self.assertEqual(len(snapshot.responses), 9)
        self.assertEqual(len(samples), 8)
        self.assertEqual(readiness(snapshot)["supervised_response_rows_by_head"]["delta_voltage_V"], 8)

    def test_transport_only_preserves_unmapped_complete_pool(self):
        manifest = read_json(self.manifest_path)
        manifest.update(data_stage="transport_only", sample_times_ns=None)
        write_json(self.manifest_path, manifest)
        self.responses.clear()
        self.controls.clear()
        for row in self.primaries:
            row.update(source_features=None, source_off=None)
        self.save()
        snapshot = Snapshot.load(self.manifest_path)
        status = prepare(snapshot, self.root / "transport")
        self.assertEqual(status["split_status"], "pending")
        self.assertFalse(status["R_ready"])
        self.assertFalse(status["F_ready"])
