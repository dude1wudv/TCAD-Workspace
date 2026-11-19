"""Synthetic file fixtures only; no solver, server, native labels, or fitting."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dram_predictor.ingest import (
    IntakeError, LabelIsolationError, build_snapshot, extract_paired_trace,
    parse_csv, parse_dfise,
)


class ParserTests(unittest.TestCase):
    def test_csv_and_dfise_have_identical_numeric_semantics(self):
        expected = (["t", "v"], [{"t": 0., "v": 1.}, {"t": 2., "v": .5}])
        self.assertEqual(parse_csv("t,v\n0,1\n2,.5\n"), expected)
        self.assertEqual(parse_dfise(
            'DF-ISE text\nInfo { datasets=["t" "v"] }\nData { 0 1 2 5D-1 }'), expected)

    def test_bad_or_empty_numeric_files_are_rejected(self):
        bad_csv = ["", "t,v\n", "t,t\n0,1\n", "t,v\n0,\n", "t,v\n0,nan\n", "t,v\n0,1,2\n"]
        for text in bad_csv:
            with self.subTest(text=text), self.assertRaises(IntakeError):
                parse_csv(text)
        bad_dfise = ['datasets=["t" "v"] Data{0}', 'datasets=["t"] Data{inf}',
                     'datasets=["t"] Data{}', 'datasets=["t"] Data{0',
                     'datasets=["t"] Data{0} Data{1}']
        for text in bad_dfise:
            with self.subTest(text=text), self.assertRaises(IntakeError):
                parse_dfise(text)


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dram-ingest-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.signal = self.write("signal.csv", "t,v,i\n0,1,0\n1,1.5,2\n3,2,2\n")
        self.control = self.write("control.csv",
                                  "t,v,i\n0,1000,0\n0.5e-9,1000,1e-6\n2e-9,1200,1e-6\n3e-9,1300,0\n")
        self.condition = {
            "condition_id": "dev-c0", "profile_id": "p0", "cohort": "development",
            "domain": "synthetic_l08", "features": {"incident_energy_MeV": 20,
                "gate_length_nm": 14, "capacitance_fF": 20, "theta_deg": 0, "phi_deg": 0},
            "categories": {"particle": "proton", "structure_family": "synthetic_l08"},
            "source_area_cm2": 1e-8, "n_bits": 1, "area_normalization_validated": False,
            "primary_count": 1, "source_distribution": "uniform",
        }
        self.sealed_condition = copy.deepcopy(self.condition)
        self.sealed_condition.update(condition_id="sealed-c0", cohort="new_combination")
        self.primary = {
            "primary_id": "dev-primary", "condition_id": "dev-c0",
            "source_primary_id": "transport-1/0", "source_features": {
                "generated_charge_fC": 1., "deposited_energy_MeV": .01, "source_duration_ns": .1},
            "source_off": False, "pool_member": True, "sampling": "random", "source_hash": "a" * 64,
        }
        self.sealed_primary = copy.deepcopy(self.primary)
        self.sealed_primary.update(primary_id="sealed-primary", condition_id="sealed-c0",
                                   source_primary_id="transport-sealed/0")
        self.response = {
            "response_id": "r0", "primary_id": "dev-primary", "state": 1, "bit_id": 0,
            "status": "valid", "labels": {"upset": None, "margin_V": None},
            "source_hash": "b" * 64, "run_id": "synthetic-r0", "mechanism_validated": True,
            "trace": self.spec("signal.csv", "ns", "V", "uA"),
            "control_trace": self.spec("control.csv", "s", "mV", "A"),
            "injection_time_ns": 1., "port_current_sign": -1, "charge_window_ns": [-1., 2.],
            "protocol_id": "synthetic-hold",
            "matching_control": {"control_id": "control0", "profile_id": "p0", "state": 1,
                                 "protocol_id": "synthetic-hold"},
        }
        self.controls = [{
            "control_id": "control0", "profile_id": "p0", "cohort": "development", "state": 1,
            "time_ns": [0., 1., 3.], "voltage_V": [1., .8, .5], "reference_voltage_V": 0.,
            "capacitance_fF": 20., "mechanism_validated": True, "source_hash": "c" * 64,
            "run_id": "synthetic-control",
        }]
        self.manifest = {
            "schema_version": 1, "plan_id": "dram-se-ddr5-lpddr5",
            "simulation_revision": "0.4", "kind": "synthetic_fixture",
            "sample_times_ns": [-1., 0., 2.],
            "conditions_file": "conditions.jsonl", "primaries_file": "primaries.jsonl",
            "development": {"responses_file": "responses.jsonl", "controls_file": "controls.jsonl",
                            "counts_file": "counts.jsonl"},
            "sealed": {"responses_file": "sealed-poison.jsonl"},
        }
        self.poison = self.write("sealed-poison.jsonl", "THIS MUST NEVER BE OPENED")

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def spec(self, name, time_unit, voltage_unit, current_unit):
        return {"path": name, "sha256": hashlib.sha256((self.root / name).read_bytes()).hexdigest(),
                "format": "csv", "time_column": "t", "voltage_column": "v", "current_column": "i",
                "time_unit": time_unit, "voltage_unit": voltage_unit, "current_unit": current_unit}

    def prepare(self):
        for name, rows in {
            "conditions.jsonl": [self.condition, self.sealed_condition],
            "primaries.jsonl": [self.primary, self.sealed_primary],
            "responses.jsonl": [self.response], "controls.jsonl": self.controls, "counts.jsonl": [],
        }.items():
            self.write(name, "".join(json.dumps(row) + "\n" for row in rows))
        return self.write("intake.json", json.dumps(self.manifest))

    def build(self):
        return build_snapshot(self.prepare(), self.root / "snapshot")

    def test_union_grid_integration_and_paired_interpolation_preserve_units_and_sign(self):
        labels = extract_paired_trace(self.response, self.condition, [-1., 0., 2.], self.root)
        self.assertAlmostEqual(labels["port_charge_fC"], -2.75, places=12)
        for observed, expected in zip(labels["delta_voltage_V"], [0., 1.5 - (1 + .2 / 3), .7]):
            self.assertAlmostEqual(observed, expected, places=12)
        self.assertNotIn("upset", labels)
        self.assertNotIn("margin_V", labels)

    def test_bad_units_missing_matching_metadata_and_coverage_fail_extraction(self):
        variants = []
        bad = copy.deepcopy(self.response); bad["trace"]["time_unit"] = "ms"; variants.append(bad)
        bad = copy.deepcopy(self.response); bad["control_trace"]["voltage_unit"] = "kV"; variants.append(bad)
        bad = copy.deepcopy(self.response); bad["trace"]["current_unit"] = "mA"; variants.append(bad)
        bad = copy.deepcopy(self.response); bad.pop("matching_control"); variants.append(bad)
        bad = copy.deepcopy(self.response); bad["matching_control"]["state"] = 0; variants.append(bad)
        bad = copy.deepcopy(self.response); bad["matching_control"]["profile_id"] = "other"; variants.append(bad)
        bad = copy.deepcopy(self.response); bad["matching_control"]["protocol_id"] = "other"; variants.append(bad)
        bad = copy.deepcopy(self.response); bad["charge_window_ns"] = [-2., 2.]; variants.append(bad)
        bad = copy.deepcopy(self.response); bad["trace"]["sha256"] = "0" * 64; variants.append(bad)
        for i, row in enumerate(variants):
            with self.subTest(variant=i), self.assertRaises(IntakeError):
                extract_paired_trace(row, self.condition, [-1., 0., 2.], self.root)
        with self.assertRaises(IntakeError):
            extract_paired_trace(self.response, self.condition, [-1., 3.], self.root)
        with self.assertRaises(IntakeError):
            extract_paired_trace(self.response, self.condition, [], self.root)
        with self.assertRaises(IntakeError):
            extract_paired_trace(self.response, self.condition, [0., 0.], self.root)

    def test_duplicate_raw_time_is_not_silently_dropped(self):
        self.write("signal.csv", "t,v,i\n0,1,0\n0,2,1\n3,2,2\n")
        self.response["trace"] = self.spec("signal.csv", "ns", "V", "uA")
        with self.assertRaisesRegex(IntakeError, "strictly increasing"):
            extract_paired_trace(self.response, self.condition, [0., 2.], self.root)

    def test_dfise_trace_uses_same_explicit_unit_and_pair_contract(self):
        self.write("signal.plt", 'DF-ISE text\nInfo { datasets=["t" "v" "i"] }\n'
                   'Data { 0 1 0 1 1.5 2 3 2 2 }')
        self.response["trace"] = self.spec("signal.plt", "ns", "V", "uA")
        self.response["trace"]["format"] = "dfise"
        labels = extract_paired_trace(self.response, self.condition, [-1., 0., 2.], self.root)
        self.assertAlmostEqual(labels["port_charge_fC"], -2.75, places=12)

    def test_snapshot_hashes_masks_and_sealed_poison_not_opened(self):
        path = self.prepare()
        read_bytes = Path.read_bytes
        def guarded(file):
            if file.resolve() == self.poison.resolve():
                raise AssertionError("Sealed label was opened")
            return read_bytes(file)
        with patch.object(Path, "read_bytes", guarded):
            output = build_snapshot(path, self.root / "snapshot")
        manifest = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(manifest["sealed_external"]["accessed"])
        self.assertEqual(manifest["sealed"], {})
        self.assertFalse((output.parent / self.poison.name).exists())
        self.assertEqual(len(manifest["files_sha256"]), 5)
        for name, expected in manifest["files_sha256"].items():
            self.assertEqual(hashlib.sha256((output.parent / name).read_bytes()).hexdigest(), expected)
        result = json.loads((output.parent / manifest["development"]["responses_file"]).read_text())
        self.assertTrue(result["masks"]["delta_voltage_V"])
        self.assertAlmostEqual(result["labels"]["port_charge_fC"], -2.75)
        self.assertIsNone(result["labels"]["upset"])
        self.assertIsNone(result["labels"]["margin_V"])
        self.assertFalse(manifest["ingestion"]["training_started"])
        self.assertEqual(manifest["ingestion"]["omissions"], [])

    def test_sealed_condition_is_rejected_before_poison_trace_read(self):
        self.response["primary_id"] = "sealed-primary"
        self.response["trace"]["path"] = self.poison.name
        self.response["trace"]["sha256"] = "0" * 64
        path = self.prepare()
        read_bytes = Path.read_bytes
        def guarded(file):
            if file.resolve() == self.poison.resolve():
                raise AssertionError("Poison trace was opened")
            return read_bytes(file)
        with patch.object(Path, "read_bytes", guarded), self.assertRaises(LabelIsolationError):
            build_snapshot(path, self.root / "snapshot")
        self.assertFalse((self.root / "snapshot").exists())

    def test_trace_inside_declared_sealed_directory_is_never_opened(self):
        self.manifest["sealed"]["waveforms"] = "sealed-traces"
        self.response["trace"]["path"] = "sealed-traces/poison.csv"
        self.response["trace"]["sha256"] = "0" * 64
        path = self.prepare()
        read_bytes = Path.read_bytes
        def guarded(file):
            if file.name == "poison.csv":
                raise AssertionError("Sealed waveform was opened")
            return read_bytes(file)
        with patch.object(Path, "read_bytes", guarded), self.assertRaises(LabelIsolationError):
            build_snapshot(path, self.root / "snapshot")

    def test_development_file_aliasing_sealed_reference_is_never_read(self):
        self.manifest["sealed"]["responses_file"] = "responses.jsonl"
        path = self.prepare()
        read_bytes = Path.read_bytes
        def guarded(file):
            if file.name == "responses.jsonl":
                raise AssertionError("Sealed response table was opened")
            return read_bytes(file)
        with patch.object(Path, "read_bytes", guarded), self.assertRaises(LabelIsolationError):
            build_snapshot(path, self.root / "snapshot")

    def test_invalid_extraction_records_failed_masked_row_and_omission(self):
        self.response.pop("matching_control")
        output = self.build()
        manifest = json.loads(output.read_text())
        result = json.loads((output.parent / "development.responses.jsonl").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertTrue(all(value is None for value in result["labels"].values()))
        self.assertTrue(all(value is False for value in result["masks"].values()))
        self.assertIn("matching", manifest["ingestion"]["omissions"][0]["reason"])

    def test_unresolved_response_does_not_read_trace_or_become_zero(self):
        self.response["status"] = "unresolved"
        self.response["trace"]["path"] = self.poison.name
        output = self.build()
        result = json.loads((output.parent / "development.responses.jsonl").read_text())
        self.assertEqual(result["status"], "unresolved")
        self.assertIsNone(result["labels"]["upset"])
        self.assertFalse(result["masks"]["upset"])

    def test_declared_binary_label_retained_without_threshold_inference(self):
        self.response["labels"].update(upset=0, margin_V=-123.)
        output = self.build()
        result = json.loads((output.parent / "development.responses.jsonl").read_text())
        self.assertEqual(result["labels"]["upset"], 0)
        self.assertEqual(result["labels"]["margin_V"], -123.)

    def test_missing_current_has_no_fabricated_charge(self):
        self.response.pop("charge_window_ns")
        self.response["trace"].pop("current_column")
        self.response["control_trace"].pop("current_column")
        output = self.build()
        result = json.loads((output.parent / "development.responses.jsonl").read_text())
        self.assertIsNone(result["labels"]["port_charge_fC"])
        self.assertFalse(result["masks"]["port_charge_fC"])

    def test_declared_global_hash_cannot_be_overridden_by_trace_hash(self):
        self.manifest["files_sha256"] = {"signal.csv": "0" * 64}
        output = self.build()
        result = json.loads((output.parent / "development.responses.jsonl").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertIn("SHA256 mismatch", result["extraction_error"])

    def test_response_null_labels_and_masks_allow_only_derived_continuous_heads(self):
        self.response["labels"] = None
        self.response["masks"] = None
        output = self.build()
        result = json.loads((output.parent / "development.responses.jsonl").read_text())
        self.assertEqual(set(result["labels"]), {"delta_voltage_V", "port_charge_fC"})
        self.assertTrue(result["masks"]["delta_voltage_V"])

    def test_extraction_does_not_override_explicit_failed_quality_mask(self):
        self.response["masks"] = {"delta_voltage_V": False, "port_charge_fC": False}
        output = self.build()
        result = json.loads((output.parent / "development.responses.jsonl").read_text())
        self.assertFalse(result["masks"]["delta_voltage_V"])
        self.assertFalse(result["masks"]["port_charge_fC"])
        self.assertAlmostEqual(result["labels"]["port_charge_fC"], -2.75)

    def test_empty_development_tables_stay_empty(self):
        intake = self.prepare()
        self.write("responses.jsonl", "")
        self.write("controls.jsonl", "")
        output = build_snapshot(intake, self.root / "snapshot")
        self.assertEqual((output.parent / "development.responses.jsonl").read_bytes(), b"")
        self.assertEqual((output.parent / "development.controls.jsonl").read_bytes(), b"")
        self.assertEqual((output.parent / "development.counts.jsonl").read_bytes(), b"")

    def test_supervision_in_metadata_is_rejected(self):
        self.sealed_condition["features"]["upset"] = 1
        with self.assertRaisesRegex(LabelIsolationError, "supervision"):
            self.build()
        self.assertFalse((self.root / "snapshot").exists())

    def test_schema_boolean_and_missing_profile_are_rejected(self):
        self.manifest["schema_version"] = True
        with self.assertRaisesRegex(IntakeError, "r0.4"):
            self.build()
        self.manifest["schema_version"] = 1
        self.condition.pop("profile_id")
        self.response["matching_control"]["profile_id"] = None
        with self.assertRaises(IntakeError):
            extract_paired_trace(self.response, self.condition, [0.], self.root)
        with self.assertRaisesRegex(IntakeError, "profile_id"):
            self.build()

    def test_raw_control_failure_remains_unusable_for_calibration(self):
        self.controls[0]["trace"] = copy.deepcopy(self.response["control_trace"])
        self.controls[0]["trace"]["sha256"] = "0" * 64
        output = self.build()
        control = json.loads((output.parent / "development.controls.jsonl").read_text())
        self.assertFalse(control["mechanism_validated"])
        self.assertEqual(control["time_ns"], [])
        self.assertEqual(control["voltage_V"], [])

    def test_legacy_generation_and_declared_table_hash_mismatch_are_rejected(self):
        self.manifest["generation"] = "dram-see-v4"
        with self.assertRaisesRegex(IntakeError, "Historical"):
            self.build()
        self.manifest.pop("generation")
        self.manifest["files_sha256"] = {"conditions.jsonl": "0" * 64}
        with self.assertRaisesRegex(IntakeError, "SHA256 mismatch"):
            self.build()
        self.assertFalse((self.root / "snapshot").exists())

    def test_existing_snapshot_is_immutable(self):
        output = self.build()
        before = output.read_bytes()
        with self.assertRaisesRegex(IntakeError, "new directory"):
            self.build()
        self.assertEqual(output.read_bytes(), before)

    def test_source_path_cannot_escape_intake_root(self):
        self.response["trace"]["path"] = "../outside.csv"
        with self.assertRaisesRegex(IntakeError, "escapes"):
            extract_paired_trace(self.response, self.condition, [0., 2.], self.root)


if __name__ == "__main__":
    unittest.main()
