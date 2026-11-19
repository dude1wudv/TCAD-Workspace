"""Small artificial r0.4 bundles; no private data, server, solver or fitting."""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dram_predictor.data import DataError, Snapshot, read_json
from dram_predictor.features import record
from dram_predictor.r04_transport import (
    BATCH, GEOMETRY, POLICY, PROVENANCE, R04, REGISTER, SELECTION,
    Bundle, build_transport_snapshot, convert_events,
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()


class ArtificialBundle:
    """The fixture reproduces field names, not any scientific observations."""
    def __init__(self, root, count=12):
        self.root = Path(root)
        self.run = "auto-r04-artificial-transport-run"
        self.snapshot = R04 + "data/snapshots/20261116-p000-c00-repair1"
        self.operation_path = (
            "local_runtime/cloud-benchmark/centos79-guest-artificial/dram-see-v4/transport-probe/"
            f"operations/{self.run}/operation.json"
        )
        self.archive_path = self.operation_path.replace("operation.json", "results.tar")
        self.archive_hash = sha(b"artificial remote archive evidence")
        self.geometry = {
            "model_id": "artificial-r04-profile", "calibrated_product": False,
            "construction": "artificial_two_terminal_structure",
            "coordinate_contract": {"beam_normal_direction": [0, 0, -1]},
            "parameters_nm": {"Lgt": 14, "Wfin": 8, "Tox": 6},
            "sensitive_bits": 1, "storage_node_roles": ["artificial_SN"],
            "regions": [{"role": "artificial_SN", "lo_nm": [0, 0, 0], "hi_nm": [2, 2, 2]}],
        }
        self.parameters = {"source_pdf": "artificial-software-test-only.pdf"}
        self.request = {
            "schema": "dram-se-r04-transport-request-v1",
            "id": "r04-artificial-p000-c00-proton-v1",
            "profile_id": self.geometry["model_id"], "condition_id": "p000-c00",
            "device_family": "lpddr5_research_literature_representative",
            "commercial_product_calibrated": False,
            "particle": "proton", "incident_energy_MeV": 10, "theta_deg": 0, "phi_deg": 0,
            "seed": 17, "event_count": count, "split": "development",
            "source_plane": {
                "normal_toward_device": [0, 0, -1], "u_axis": [1, 0, 0], "v_axis": [0, -1, 0],
                "center_nm": [0, 0, 100], "u_offsets_nm": [-10, 10], "v_offsets_nm": [-10, 10],
                "area_nm2": 400.0, "area_cm2": 4e-12,
                "sampling": "independent_uniform_u_v_per_primary_in_beam_perpendicular_plane",
            },
            "physics": "artificial-software-test-only",
        }
        self.policy = {
            "schema": "dram-se-r04-event-handoff-selection-policy-r1",
            "development_only": True, "fidelity": "raw_transport_event_unmapped",
            "is_tcad_source": False,
            "preselected_random_response": {
                "event_ids": list(range(min(6, count))), "fixed_before_transport_outcome": True,
                "selection_uses_deposition": False,
            },
            "development_enrichment": {
                "count_per_condition": 6, "requires_eligible_count_at_least": 6,
                "population_frequency_weight": None, "random_sampling": False,
            },
            "electrical_response_status": "unsolved", "upset_label": "unknown",
        }
        self.selected_overrides = {}
        self.operation_overrides = {}
        self.input_hash_overrides = {}
        self.summary_overrides = {}
        self.batch_overrides = {}
        self.extra_selection = []

    def events(self):
        result = []
        for event in range(self.request["event_count"]):
            key = f"{self.request['id']}:{self.request['seed']}:{event}"
            result.append({
                "event_key": key, "group_id": key, "event_id": str(event),
                "input_task_id": self.request["id"], "transport_run_id": self.run,
                "profile_id": self.request["profile_id"], "condition_id": self.request["condition_id"],
                "split": self.request["split"], "device_family": self.request["device_family"],
                "seed": str(self.request["seed"]), "primary_count": "1", "event_complete": "1",
                "incident_energy_MeV": str(self.request["incident_energy_MeV"]),
                "theta_deg": str(self.request["theta_deg"]), "phi_deg": str(self.request["phi_deg"]),
                "source_area_cm2": str(self.request["source_plane"]["area_cm2"]),
                "source_x_um": "-0.001", "source_y_um": "0.001", "source_z_um": "0.1",
                "ionizing_si_MeV": "0" if event == 0 else str(event * 1e-6),
                "zero_si_ionizing": "1" if event == 0 else "0",
                "hadronic_step_count": "0", "step_count": "2", "track_count": "1",
                "preselected_random_response": "1" if event < 6 else "0",
                "electrical_response_status": "unsolved", "upset_label": "unknown",
            })
        return result

    def selected(self):
        result = {}
        for row in self.events():
            event = int(row["event_id"])
            selection = {
                key: row[key] for key in ("event_key", "group_id", "input_task_id", "transport_run_id",
                                         "profile_id", "condition_id", "seed", "split",
                                         "ionizing_si_MeV", "electrical_response_status", "upset_label")
            }
            selection.update(
                event_id=event, zero_si_ionizing=int(row["zero_si_ionizing"]),
                selection_mechanism=("preselected_random_response" if event < 6 else "development_enrichment"),
                empirical_quantile_j=(event - 5 if event >= 6 else None),
                eligible_pool_count=(self.request["event_count"] - 6 if event >= 6 else None),
                zero_based_rank=(event - 6 if event >= 6 else None),
            )
            selection.update(self.selected_overrides.get(event, {}))
            result[row["event_key"]] = selection
        return result

    def summary(self):
        count = self.request["event_count"]
        return {
            "schema": "dram-se-r04-development-transport-dataset-v1",
            "input_task_id": self.request["id"], "transport_run_id": self.run,
            "audit": {"primary_count": count, "zero_si_ionizing_count": 1,
                      "hadronic_event_count": 0, "step_count": 2 * count, "track_count": count},
        }

    def write(self):
        files = {}
        files[GEOMETRY], files[PROVENANCE] = encoded(self.geometry), encoded(self.parameters)
        self.request["geometry_sha256"] = sha(files[GEOMETRY])
        register = {
            "schema": "dram-se-r04-first-development-v1", "cohort": "development",
            "target_labels_seen": False, "profile_id": self.geometry["model_id"],
            "conditions": [self.request],
        }
        files[REGISTER], files[POLICY] = encoded(register), encoded(self.policy)
        files[SELECTION] = encoded({"policy_sha256": sha(files[POLICY]),
                                    "events": list(self.selected().values()) + self.extra_selection})
        extractor = R04 + "data/extract_transport.py"
        files[extractor] = b"# Artificial frozen extractor identity, never executed.\n"
        csv_text = io.StringIO(newline="")
        writer = csv.DictWriter(csv_text, fieldnames=list(self.events()[0]))
        writer.writeheader()
        writer.writerows(self.events())
        files[self.snapshot + "/events.csv"] = csv_text.getvalue().encode()
        input_hashes = {
            "geometry.json": sha(files[GEOMETRY]), "parameter-provenance.json": sha(files[PROVENANCE]),
            "request.json": sha(encoded(self.request)),
        }
        input_hashes.update(self.input_hash_overrides)
        operation = {
            "label": self.run, "state": "COLLECTED_PENDING_AUDIT", "synthetic": False,
            "origin": "native_pipeline",
            "collection_verified": True, "remote_exit_code": 0, "collection_exit_code": 0,
            "operation_task_exit_code": 0, "collection_snapshot": {"sha256": self.archive_hash, "bytes": 42},
            "input_sha256": input_hashes,
        }
        operation.update(self.operation_overrides)
        files[self.operation_path] = encoded(operation)
        summary = self.summary()
        summary.update(
            conditions_sha256=sha(files[REGISTER]), input_sha256=input_hashes,
            output_events_sha256=sha(files[self.snapshot + "/events.csv"]),
            archive_sha256=self.archive_hash, extractor_sha256=sha(files[extractor]),
            original_operation_json="/home/tcad/course-workspace/" + self.operation_path,
            operation_json_sha256=sha(files[self.operation_path]),
            original_archive="/home/tcad/course-workspace/" + self.archive_path,
            source_area_cm2=self.request["source_plane"]["area_cm2"],
            scientific_acceptance="not_assessed", upset_labels="unknown",
        )
        summary.update(self.summary_overrides)
        files[self.snapshot + "/summary.json"] = encoded(summary)
        entry = {
            "snapshot": self.snapshot, "summary_sha256": sha(files[self.snapshot + "/summary.json"]),
            "events_sha256": sha(files[self.snapshot + "/events.csv"]),
            "operation": self.operation_path, "operation_sha256": sha(files[self.operation_path]),
            "archive": self.archive_path, "archive_sha256": self.archive_hash,
            "extractor_sha256": sha(files[extractor]),
        }
        count = self.request["event_count"]
        batch = {
            "schema": "dram-se-r04-native-transport-batch-v1", "condition_count": 1,
            "conditions": [{"condition_id": self.request["condition_id"], "split": self.request["split"]}],
            "snapshots": [entry], "independent_primary_records": count,
            "zero_si_ionizing_count": 1, "positive_si_ionizing_count": count - 1,
            "step_count": 2 * count, "track_count": count,
        }
        batch.update(self.batch_overrides)
        files[BATCH] = encoded(batch)
        receipt = {
            "schema": "r04-readonly-copy-v1", "sealed_accessed": False,
            "remote_workspace": "/home/tcad/course-workspace",
            "utc": "2000-01-01T00:00:00Z", "files": [],
            "archive_verification": [{
                "run_id": self.run, "sha256": self.archive_hash, "stable_during_hash": True,
                "remote_path": "/home/tcad/course-workspace/" + self.archive_path,
                "downloaded": False, "size_bytes": 42,
            }],
        }
        for name, raw in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            receipt["files"].append({
                "relative_path": name, "sha256": sha(raw), "size_bytes": len(raw),
                "remote_path": "/home/tcad/course-workspace/" + name, "stable_during_read": True,
            })
        (self.root / "copy-receipt.json").write_bytes(encoded(receipt))
        return self.root


class ConvertEventTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ArtificialBundle(Path("unused"), count=2)
        self.rows = self.fixture.events()

    def convert(self, rows=None, selected=None):
        return convert_events(self.rows if rows is None else rows, self.fixture.request,
                              self.fixture.summary(), sha(b"artificial events"),
                              self.fixture.selected() if selected is None else selected)

    def test_zero_deposition_never_becomes_source_off_or_an_electrical_label(self):
        for row in self.rows:
            row["preselected_random_response"] = "0"
        converted, stats = self.convert(selected={})
        self.assertEqual(len(converted), 2)
        self.assertEqual(stats["zero_si_ionizing_count"], 1)
        self.assertTrue(converted[0]["transport"]["zero_si_ionizing"])
        self.assertEqual(converted[0]["transport"]["ionizing_si_MeV"], 0.0)
        for row in converted:
            self.assertIsNone(row["source_off"])
            self.assertIsNone(row["sampling"])
            self.assertTrue(all(value is None for value in row["source_features"].values()))
            self.assertNotIn("labels", row)
            self.assertFalse(row["transport"]["source_position_is_strike_position"])

    def test_duplicate_missing_and_out_of_range_primary_are_rejected(self):
        cases = [self.rows[:1], [self.rows[0], self.rows[0]],
                 [self.rows[0], {**self.rows[1], "event_id": "2"}]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(DataError):
                self.convert(rows)

    def test_failed_unknown_identity_and_false_zero_are_rejected(self):
        for field, value in (
            ("event_complete", "0"), ("primary_count", "2"), ("condition_id", "unknown"),
            ("profile_id", "wrong-profile"), ("input_task_id", "legacy-task"),
            ("split", "high_energy"), ("electrical_response_status", "failed"),
            ("upset_label", "0"), ("zero_si_ionizing", "0"),
            ("incident_energy_MeV", "10000"), ("source_area_cm2", "400"),
        ):
            with self.subTest(field=field):
                rows = copy.deepcopy(self.rows)
                rows[0][field] = value
                with self.assertRaises(DataError):
                    self.convert(rows)

    def test_negative_nonfinite_and_boolean_consumed_numerics_are_rejected(self):
        for field, value in (
            ("ionizing_si_MeV", "-1"), ("ionizing_si_MeV", "NaN"),
            ("source_x_um", "Infinity"), ("track_count", "0"),
            ("step_count", "-1"), ("hadronic_step_count", "-1"),
            ("incident_energy_MeV", True),
        ):
            with self.subTest(field=field, value=value):
                rows = copy.deepcopy(self.rows)
                rows[0][field] = value
                with self.assertRaises(DataError):
                    self.convert(rows)

    def test_unknown_selection_mechanism_is_rejected(self):
        selected = self.fixture.selected()
        selected[self.rows[0]["event_key"]]["selection_mechanism"] = "unknown"
        with self.assertRaisesRegex(DataError, "selection mechanism"):
            self.convert(selected=selected)

    def test_selection_cannot_change_source_identity_or_status(self):
        for field, value in (
            ("profile_id", "wrong-profile"), ("input_task_id", "old-v4-physics"),
            ("seed", "999"), ("split", "new_combination"), ("zero_si_ionizing", 0),
            ("electrical_response_status", "failed"), ("upset_label", "1"),
        ):
            with self.subTest(field=field):
                selected = self.fixture.selected()
                selected[self.rows[0]["event_key"]][field] = value
                with self.assertRaises(DataError):
                    self.convert(selected=selected)

    def test_random_selection_must_match_raw_preselection_flag(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["preselected_random_response"] = "0"
        with self.assertRaises(DataError):
            self.convert(rows)


class BundleIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fixture(self, name="bundle"):
        return ArtificialBundle(self.root / name)

    def build(self, fixture, name="output"):
        return build_transport_snapshot(fixture.write(), self.root / name)

    def test_legacy_runner_directory_does_not_turn_native_r04_into_legacy_physics(self):
        fixture = self.fixture()
        self.assertIn("/dram-see-v4/", fixture.operation_path)
        with patch("torch.optim.AdamW", side_effect=AssertionError("No optimizer may run")):
            result = self.build(fixture)
        snapshot = Snapshot.load(result["manifest"])
        quality = read_json(Path(result["quality_report"]))
        self.assertEqual((len(snapshot.conditions), len(snapshot.primaries)), (1, 12))
        self.assertEqual(snapshot.data_stage, "transport_only")
        self.assertFalse(quality["legacy_physics_imported"])
        self.assertFalse(quality["training_started"])
        self.assertEqual(quality["selected_response_candidates"], {"random": 6, "enriched": 6})
        self.assertEqual(quality["native_responses"], 0)
        self.assertEqual(record(snapshot.conditions["p000-c00"])["direction_z"], -1.0)
        self.assertEqual(snapshot.conditions["p000-c00"]["provenance"]["source_angles_deg"],
                         {"theta": 0, "phi": 0})

    def test_unknown_sealed_and_missing_selected_events_are_rejected(self):
        for mode in ("unknown", "sealed", "missing"):
            with self.subTest(mode=mode):
                fixture = self.fixture(mode)
                if mode == "unknown":
                    fixture.selected_overrides[0] = {"condition_id": "p999-c00"}
                elif mode == "sealed":
                    fixture.selected_overrides[0] = {"split": "high_energy"}
                else:
                    extra = copy.deepcopy(next(iter(fixture.selected().values())))
                    extra.update(event_key="absent-event", group_id="absent-event", event_id=100)
                    fixture.extra_selection.append(extra)
                with self.assertRaises(DataError):
                    self.build(fixture, "out-" + mode)

    def test_failed_synthetic_and_unverified_operations_are_rejected(self):
        for i, change in enumerate((
            {"state": "RUNNING"}, {"synthetic": True}, {"collection_verified": False},
            {"remote_exit_code": 1}, {"collection_exit_code": 1}, {"operation_task_exit_code": 1},
        )):
            with self.subTest(change=change):
                fixture = self.fixture(str(i))
                fixture.operation_overrides.update(change)
                with self.assertRaises(DataError):
                    self.build(fixture, f"out-{i}")

    def test_request_physics_identity_must_match_r04_registry_and_geometry(self):
        for i, change in enumerate((
            {"schema": "dram-see-v4-request"}, {"profile_id": "old-v4-physical-profile"},
        )):
            with self.subTest(change=change):
                fixture = self.fixture(str(i))
                fixture.request.update(change)
                with self.assertRaises(DataError):
                    self.build(fixture, f"out-{i}")

    def test_parameter_provenance_must_match_frozen_operation_input(self):
        fixture = self.fixture()
        fixture.input_hash_overrides["parameter-provenance.json"] = sha(b"different parameter source")
        with self.assertRaises(DataError):
            self.build(fixture)

    def test_area_units_and_source_distribution_cannot_be_silently_assumed(self):
        for i, change in enumerate((
            {"area_nm2": 4e-12},
            {"sampling": "gaussian"},
            {"u_offsets_nm": [-20, 20]},
        )):
            with self.subTest(change=change):
                fixture = self.fixture(str(i))
                fixture.request["source_plane"].update(change)
                with self.assertRaises(DataError):
                    self.build(fixture, f"out-{i}")

    def test_selection_policy_cannot_relabel_outcome_enrichment_as_preselected_random(self):
        fixture = self.fixture()
        fixture.policy["preselected_random_response"]["selection_uses_deposition"] = True
        with self.assertRaises(DataError):
            self.build(fixture)

    def test_operation_locator_cannot_read_from_a_sealed_directory(self):
        fixture = self.fixture()
        fixture.operation_path = R04 + "data/sealed/operation.json"
        fixture.write()
        original = Path.read_bytes
        sealed = (fixture.root / fixture.operation_path).resolve()

        def guarded(path):
            if path.resolve() == sealed:
                raise AssertionError("Sealed locator must be rejected before reading")
            return original(path)

        with patch.object(Path, "read_bytes", guarded), self.assertRaises(DataError):
            build_transport_snapshot(fixture.root, self.root / "output")

    def test_copied_hash_stability_and_frozen_expected_hash_are_verified(self):
        for mode in ("copied_hash", "unstable", "expected_hash"):
            with self.subTest(mode=mode):
                fixture = self.fixture(mode)
                fixture.write()
                if mode == "copied_hash":
                    with (fixture.root / GEOMETRY).open("ab") as stream:
                        stream.write(b" ")
                elif mode == "unstable":
                    receipt = read_json(fixture.root / "copy-receipt.json")
                    next(r for r in receipt["files"] if r["relative_path"] == GEOMETRY)["stable_during_read"] = False
                    (fixture.root / "copy-receipt.json").write_bytes(encoded(receipt))
                bundle = Bundle(fixture.root)
                with self.assertRaises(DataError):
                    bundle.raw(GEOMETRY, sha(b"wrong") if mode == "expected_hash" else None)

    def test_receipt_paths_cannot_escape_bundle(self):
        bundle_root = self.root / "bundle"
        bundle_root.mkdir()
        outside = self.root / "outside.txt"
        outside.write_bytes(b"must not read")
        relative = "../outside.txt"
        receipt = {
            "schema": "r04-readonly-copy-v1", "sealed_accessed": False,
            "files": [{"relative_path": relative, "sha256": sha(outside.read_bytes()),
                       "size_bytes": outside.stat().st_size, "stable_during_read": True,
                       "remote_path": "/outside.txt"}],
        }
        (bundle_root / "copy-receipt.json").write_bytes(encoded(receipt))
        bundle = Bundle(bundle_root)
        original = Path.read_bytes

        def guarded(path):
            if path.resolve() == outside:
                raise AssertionError("Escaping file must not be read")
            return original(path)

        with patch.object(Path, "read_bytes", guarded), self.assertRaisesRegex(DataError, "escapes"):
            bundle.raw(relative)


if __name__ == "__main__":
    unittest.main()
