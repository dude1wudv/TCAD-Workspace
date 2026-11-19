"""Transport intake checks with artificial metadata only; no optimizer is run."""
from __future__ import annotations

from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dram_predictor.config import Config
from dram_predictor.data import DataError, LeakageError, Snapshot, View, read_json
from dram_predictor.f_training import fit_f_core
from dram_predictor.pipeline import cross_validate, fit_final, prepare, readiness, run_search
from dram_predictor.r_training import fit_r, fit_r_core
from fixtures import make_fixture


class TransportStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.conditions = [{
            "condition_id": "test-condition",
            "profile_id": "test-profile",
            "domain": "synthetic-LPDDR5-test-only",
            "cohort": "development",
            "features": {"gate_length_nm": 14.0, "incident_energy_MeV": 10.0,
                         "capacitance_fF": None},
            "categories": {"particle": "proton", "structure_family": "test-BCAT"},
            "source_area_cm2": None, "n_bits": None, "primary_count": 2,
            "raw_transport": {"run_id": "artificial-run", "source_plane_side_nm": 200.0},
        }]
        self.primaries = [{
            "primary_id": f"test-primary-{i}", "condition_id": "test-condition",
            "source_primary_id": f"artificial-run:event:{i}",
            "source_hash": hashlib.sha256(f"artificial-event-{i}".encode()).hexdigest(),
            "pool_member": True, "sampling": None, "source_off": None,
            "source_features": {"deposited_energy_MeV": float(i) * 0.001,
                                "generated_charge_fC": None, "source_duration_ns": None},
            "raw_transport": {"event_id": i, "deposited_energy_keV": float(i)},
        } for i in range(2)]
        self.responses = []
        self.controls = []
        self.counts = []
        self.manifest = {
            "schema_version": 1, "plan_id": "dram-se-ddr5-lpddr5",
            "simulation_revision": "0.4", "kind": "synthetic_fixture",
            "data_stage": "transport_only",
            "conditions_file": "conditions.jsonl", "primaries_file": "primaries.jsonl",
            "development": {"responses_file": "responses.jsonl", "controls_file": "controls.jsonl",
                            "counts_file": "counts.jsonl"},
            "sealed": {"responses_file": "sealed/never-read.jsonl"},
        }

    def write(self):
        tables = {"conditions.jsonl": self.conditions, "primaries.jsonl": self.primaries,
                  "responses.jsonl": self.responses, "controls.jsonl": self.controls,
                  "counts.jsonl": self.counts}
        hashes = {}
        for name, rows in tables.items():
            raw = "".join(json.dumps(row) + "\n" for row in rows).encode()
            (self.root / name).write_bytes(raw)
            hashes[name] = hashlib.sha256(raw).hexdigest()
        self.manifest["files_sha256"] = hashes
        path = self.root / "manifest.json"
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        return path

    def test_missing_and_null_unknown_physics_are_preserved_without_defaults(self):
        for omit in (False, True):
            with self.subTest(omit=omit):
                if omit:
                    self.conditions[0]["features"].pop("capacitance_fF")
                    for field in ("source_area_cm2", "n_bits"):
                        self.conditions[0].pop(field)
                    for primary in self.primaries:
                        for field in ("source_off", "sampling"):
                            primary.pop(field)
                        for field in ("generated_charge_fC", "source_duration_ns"):
                            primary["source_features"].pop(field)
                snapshot = Snapshot.load(self.write())
                self.assertEqual(snapshot.conditions["test-condition"], self.conditions[0])
                self.assertEqual(list(snapshot.primaries.values()), self.primaries)
                self.assertEqual(snapshot.responses, [])
                self.assertEqual(snapshot.controls, [])
                self.assertEqual(snapshot.counts, [])

    def test_supplied_known_mapping_fields_must_remain_valid(self):
        self.conditions[0]["features"]["capacitance_fF"] = 2.0
        self.conditions[0].update(source_area_cm2=1e-8, n_bits=1)
        for primary in self.primaries:
            primary.update(sampling="random", source_off=False)
            primary["source_features"].update(generated_charge_fC=0.2, source_duration_ns=0.01)
        self.assertEqual(Snapshot.load(self.write()).data_stage, "transport_only")

    def test_invalid_nonnull_unknown_fields_are_rejected(self):
        cases = (
            ("condition", "source_area_cm2", -1.0),
            ("condition", "source_area_cm2", 0.0),
            ("feature", "capacitance_fF", -1.0),
            ("feature", "capacitance_fF", True),
            ("source", "generated_charge_fC", -1.0),
            ("source", "source_duration_ns", -1.0),
            ("source", "deposited_energy_MeV", -1.0),
            ("source", "spread_x_nm", -1.0),
            ("primary", "source_off", 0),
            ("primary", "sampling", "not-selected"),
        )
        for location, key, value in cases:
            with self.subTest(location=location, key=key, value=value):
                condition, primary = copy.deepcopy(self.conditions), copy.deepcopy(self.primaries)
                target = {"condition": self.conditions[0], "feature": self.conditions[0]["features"],
                          "source": self.primaries[0]["source_features"],
                          "primary": self.primaries[0]}[location]
                target[key] = value
                with self.assertRaises(DataError):
                    Snapshot.load(self.write())
                self.conditions, self.primaries = condition, primary

    def test_nonfinite_raw_metadata_is_rejected(self):
        self.primaries[0]["raw_transport"]["unusable_number"] = float("nan")
        with self.assertRaisesRegex(DataError, "nonfinite JSON"):
            Snapshot.load(self.write())
        self.primaries[0]["raw_transport"]["unusable_number"] = float("inf")
        path = self.write()
        table = self.root / "primaries.jsonl"
        table.write_text(table.read_text().replace("Infinity", "1e309"), encoding="utf-8")
        self.manifest["files_sha256"]["primaries.jsonl"] = hashlib.sha256(table.read_bytes()).hexdigest()
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaisesRegex(DataError, "finite numbers"):
            Snapshot.load(path)

    def test_source_off_cannot_be_inferred_from_zero_deposit(self):
        self.primaries[0]["source_off"] = True
        with self.assertRaisesRegex(DataError, "Source-off conflicts"):
            Snapshot.load(self.write())

    def test_complete_pool_and_explicit_membership_are_required(self):
        for mutation in ("missing", "extra", "duplicate_source", "not_pool", "unknown_condition"):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.primaries)
                if mutation == "missing":
                    self.primaries.pop()
                elif mutation == "extra":
                    extra = copy.deepcopy(self.primaries[0])
                    extra.update(primary_id="extra", source_primary_id="extra-source")
                    self.primaries.append(extra)
                elif mutation == "duplicate_source":
                    self.primaries[1]["source_primary_id"] = self.primaries[0]["source_primary_id"]
                elif mutation == "not_pool":
                    self.primaries[0]["pool_member"] = None
                else:
                    self.primaries[0]["condition_id"] = "absent"
                with self.assertRaises(DataError):
                    Snapshot.load(self.write())
                self.primaries = original

    def test_source_identity_and_hash_are_not_optional(self):
        for key, value in (("source_primary_id", ""), ("source_primary_id", 123),
                           ("source_hash", "not-a-hash"), ("primary_id", " ")):
            with self.subTest(key=key):
                original = copy.deepcopy(self.primaries)
                self.primaries[0][key] = value
                with self.assertRaises(DataError):
                    Snapshot.load(self.write())
                self.primaries = original

    def test_declared_pool_size_must_be_positive_integer(self):
        for value in (None, True, 2.0, 0):
            with self.subTest(value=value):
                self.conditions[0]["primary_count"] = value
                with self.assertRaisesRegex(DataError, "primary_count"):
                    Snapshot.load(self.write())

    def test_stage_plan_domain_and_frozen_cohort_checks_stay_strict(self):
        original = copy.deepcopy(self.manifest)
        for field, value in (("data_stage", "partial"), ("simulation_revision", "0.3"),
                             ("plan_id", "old-plan")):
            with self.subTest(field=field):
                self.manifest[field] = value
                with self.assertRaises(DataError):
                    Snapshot.load(self.write())
                self.manifest = copy.deepcopy(original)
        for key, value in (("domain", ""), ("cohort", "unknown")):
            with self.subTest(key=key):
                original_condition = copy.deepcopy(self.conditions)
                self.conditions[0][key] = value
                with self.assertRaises(DataError):
                    Snapshot.load(self.write())
                self.conditions = original_condition
        self.conditions[0]["features"]["incident_energy_MeV"] = 150.0
        with self.assertRaises(LeakageError):
            Snapshot.load(self.write())

    def test_primary_cannot_cross_cohorts(self):
        condition = copy.deepcopy(self.conditions[0])
        condition.update(condition_id="sealed-condition", cohort="new_combination", primary_count=1)
        self.conditions.append(condition)
        primary = copy.deepcopy(self.primaries[0])
        primary.update(primary_id="sealed-primary", condition_id="sealed-condition")
        self.primaries.append(primary)
        with self.assertRaisesRegex(LeakageError, "crosses development"):
            Snapshot.load(self.write())

    def test_mixed_domains_are_rejected(self):
        condition = copy.deepcopy(self.conditions[0])
        condition.update(condition_id="other-condition", profile_id="other-profile", domain="other-domain")
        self.conditions.append(condition)
        with self.assertRaisesRegex(DataError, "Separate DDR5/LPDDR5"):
            Snapshot.load(self.write())

    def test_transport_tables_cannot_carry_any_supervision_rows(self):
        for table, row in (
            (self.responses, {"response_id": "response", "labels": None}),
            (self.controls, {"control_id": "control"}),
            (self.counts, {"count_id": "count"}),
        ):
            with self.subTest(row=row):
                table.append(row)
                with self.assertRaisesRegex(LeakageError, "empty response, control and count"):
                    Snapshot.load(self.write())
                table.clear()

    def test_supervision_cannot_hide_in_raw_metadata(self):
        for target in (self.conditions[0]["raw_transport"], self.primaries[0]["raw_transport"]):
            target["labels"] = {"upset": 0}
            with self.assertRaisesRegex(LeakageError, "cannot contain response labels"):
                Snapshot.load(self.write())
            target.pop("labels")

    def test_transport_tables_require_verified_hashes(self):
        path = self.write()
        with (self.root / "primaries.jsonl").open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaisesRegex(DataError, "Hash mismatch"):
            Snapshot.load(path)
        path = self.write()
        self.manifest["files_sha256"].pop("primaries.jsonl")
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaisesRegex(DataError, "explicit SHA256"):
            Snapshot.load(path)

    def test_prepare_preserves_unknowns_and_does_not_read_sealed_or_freeze_splits(self):
        path = self.write()
        originals = {p: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        open_path = Path.open

        def guarded(file, *args, **kwargs):
            if "sealed" in file.parts:
                raise AssertionError("sealed data must not be opened")
            return open_path(file, *args, **kwargs)

        with patch.object(Path, "open", guarded):
            snapshot = Snapshot.load(path)
            report = prepare(snapshot, self.root / "prepared")
        self.assertEqual(report["condition_count"], 1)
        self.assertEqual(report["primaries"], 2)
        self.assertEqual(report["primaries_by_condition"], {"test-condition": 2})
        self.assertFalse(report["R_ready"])
        self.assertFalse(report["F_ready"])
        self.assertFalse(report["training_started"])
        self.assertFalse(report["sealed_labels_opened"])
        self.assertEqual(report["split_status"], "pending")
        self.assertFalse((self.root / "prepared" / "splits.json").exists())
        self.assertEqual(read_json(self.root / "prepared" / "readiness.json"), report)
        self.assertTrue(all(p.read_bytes() == raw for p, raw in originals.items()))

    def test_transport_views_and_pipeline_training_entrypoints_are_blocked(self):
        snapshot = Snapshot.load(self.write())
        config = Config()
        attempts = (
            lambda: snapshot.view(snapshot.development_conditions),
            lambda: View(snapshot, frozenset(snapshot.development_conditions)),
            lambda: cross_validate(snapshot, config),
            lambda: run_search(snapshot, config, self.root / "search"),
            lambda: fit_final(snapshot, config, self.root / "final"),
        )
        with patch("torch.optim.AdamW", side_effect=AssertionError("Optimizer must not run")):
            for attempt in attempts:
                with self.assertRaisesRegex(DataError, "transport_only"):
                    attempt()
        self.assertFalse((self.root / "search").exists())
        self.assertFalse((self.root / "final").exists())

    def test_existing_view_cannot_bypass_stage_at_low_level_training_functions(self):
        snapshot = Snapshot.load(self.write())
        snapshot.manifest["data_stage"] = "model_ready"
        stale_view = snapshot.view(snapshot.development_conditions)
        snapshot.manifest["data_stage"] = "transport_only"
        with ExitStack() as stack:
            stack.enter_context(patch("torch.optim.AdamW", side_effect=AssertionError("Optimizer must not run")))
            stack.enter_context(patch("torch.manual_seed", side_effect=AssertionError("Training must not start")))
            for call in (lambda: fit_r(stale_view, Config()),
                         lambda: fit_r_core(stale_view, Config()),
                         lambda: fit_f_core(stale_view, [], Config())):
                with self.assertRaisesRegex(DataError, "transport_only"):
                    call()

    def test_default_complete_snapshot_validation_is_not_relaxed(self):
        path = make_fixture(self.root / "complete", profiles=3, conditions_per_profile=1)
        snapshot = Snapshot.load(path)
        self.assertEqual(snapshot.data_stage, "model_ready")
        self.assertEqual(readiness(snapshot)["kind"], "synthetic_fixture")
        for stage in (None, "model_ready"):
            self.manifest.pop("data_stage", None)
            if stage is not None:
                self.manifest["data_stage"] = stage
            with self.subTest(stage=stage), self.assertRaisesRegex(DataError, "capacitance_fF"):
                Snapshot.load(self.write())


if __name__ == "__main__":
    unittest.main()
