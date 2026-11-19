import datetime as dt
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from status_checker import (
    build_activity_feed, build_freshness_health, build_service_health, build_simulation_health,
    build_status, main, overall_state, research_site_state, simulation_status, write_json_atomic,
)


UTC = dt.timezone.utc
SNAPSHOT = dt.datetime(2026, 11, 17, 3, tzinfo=UTC)


def fake_runner(*args, **kwargs):
    unit = args[0][2]
    if unit == "tcad-autonomy.service":
        return SimpleNamespace(returncode=0, stdout="active\n")
    return SimpleNamespace(returncode=3, stdout="inactive\n")


class StatusCheckerTests(unittest.TestCase):
    def test_occupied_reconciliation_pending_does_not_claim_native_running(self):
        observation, runtime, runs, source = self.make_inputs()
        for status in ("reconciliation_pending", "pending", "unknown", None):
            with self.subTest(status=status):
                source["runs"] = [dict(source["runs"][-1], status=status, occupied=True)]
                observation.write_text(json.dumps(source), encoding="utf-8")
                result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
                self.assertEqual(result["state"], "idle")
                self.assertEqual(result["running_groups"], 0)
                self.assertEqual(result["pending_groups"], 1)
                self.assertEqual(result["failed_groups"], 0)
                self.assertEqual(result["current_runs"], [])
                self.assertEqual(result["cumulative_runtime_seconds"], 0)

    def test_only_explicit_running_status_creates_current_run_even_without_occupancy(self):
        observation, runtime, runs, source = self.make_inputs()
        source["runs"] = [dict(source["runs"][-1], status="RUNNING", occupied=False)]
        observation.write_text(json.dumps(source), encoding="utf-8")
        result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(result["state"], "running")
        self.assertEqual(result["running_groups"], 1)
        self.assertEqual(result["pending_groups"], 0)
        self.assertEqual(len(result["current_runs"]), 1)

    def test_reconciled_unlaunched_failure_is_failed_without_archive_or_runtime_credit(self):
        observation, runtime, runs, source = self.make_inputs()
        source["runs"] = [dict(source["runs"][-1], status="failed_unlaunched", terminal_reconciled=True,
                              occupied=True)]
        observation.write_text(json.dumps(source), encoding="utf-8")
        result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(result["failed_groups"], 1)
        self.assertEqual(result["pending_groups"], 0)
        self.assertEqual(result["running_groups"], 0)
        self.assertEqual(result["completed_groups"], 0)
        self.assertEqual(result["successful_groups"], 0)
        self.assertEqual(result["completion_rate"], 0)
        self.assertEqual(result["current_runs"], [])
        self.assertEqual(result["recent_activity"], [])
        self.assertEqual(result["completed_runtime_seconds"], 0)
        self.assertEqual(result["cumulative_runtime_seconds"], 0)

    def test_unlaunched_failure_without_terminal_reconciliation_remains_pending(self):
        observation, runtime, runs, source = self.make_inputs()
        source["runs"] = [dict(source["runs"][-1], status="failed_unlaunched", terminal_reconciled=False)]
        observation.write_text(json.dumps(source), encoding="utf-8")
        result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(result["failed_groups"], 0)
        self.assertEqual(result["pending_groups"], 1)
        self.assertEqual(result["current_runs"], [])

    def test_full_r06_payload_keeps_p0_separate_and_filters_holdout_and_private_metadata(self):
        from test_r06_projection import r06_plan
        observation, runtime, runs, source = self.make_inputs()
        plan_path = observation.parent / "r06-plan.json"
        plan_path.write_text(json.dumps(r06_plan()), encoding="utf-8")
        source["runs"][0]["case_id"] = "r06-hr-case-000-b1"
        source["runs"][1]["case_id"] = "r06-z-case-000-b1"
        observation.write_text(json.dumps(source), encoding="utf-8")
        runtime.write_text(json.dumps({"intents": {
            source["runs"][0]["id"]: {"run_id": source["runs"][0]["run_id"], "scientific_admission": {
                "scope": "holdout_evaluation", "case_id": "r06-hr-case-000-b1",
            }},
            source["runs"][1]["id"]: {"run_id": source["runs"][1]["run_id"], "scientific_admission": {
                "scope": "p0_diagnostic", "diagnostic_plan": "/private/diagnostic.json",
            }},
        }}), encoding="utf-8")
        with (
            patch("status_checker.PLAN_PATH", plan_path),
            patch("status_checker.PROGRESS_PATH", observation.parent / "unused.sqlite3"),
            patch("status_checker.WORK_ITEMS_PATH", observation.parent / "unused-work-items.json"),
            patch("status_checker.system_metrics", return_value={}),
        ):
            result = build_status(runner=fake_runner, observation_path=observation,
                                  runtime_path=runtime, runs_root=runs)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["research"]["totals"]["planned"], 396)
        self.assertEqual(result["research"]["totals"]["solved"], 0)
        self.assertEqual(result["research"]["totals"]["accepted"], 0)
        self.assertEqual(result["research"]["diagnostics"]["P0"]["planned"], 1)
        self.assertEqual(len(result["research"]["cases"]), 338)
        serialized = json.dumps(result).lower()
        for forbidden in ("r06-hr-case", "/private/", "run_id", "r04-l08", "127.0.0.1", "ssh", "lm_license_file"):
            self.assertNotIn(forbidden, serialized)

    def test_r06_runtime_admission_case_identity_is_public_without_work_item_mapping(self):
        observation, runtime, runs, source = self.make_inputs()
        identity = "r06-s-d0-nominal-p00-b1"
        runtime.write_text(json.dumps({"intents": {
            source["runs"][1]["id"]: {"run_id": "auto-active",
                                     "scientific_admission": {"scope": "development_production", "case_id": identity}},
        }}), encoding="utf-8")
        result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        active = result["current_runs"][0]
        self.assertEqual(active["case_id"], identity)
        self.assertEqual(active["public_id"], identity)
        self.assertEqual(active["group"], identity)

    def test_p0_card_is_diagnostic_without_formal_case_identity_or_parameters(self):
        observation, runtime, runs, source = self.make_inputs()
        source["runs"][1].update(case_id="r06-z-d0-nominal-b0", parameters={"energy_MeV": 20})
        observation.write_text(json.dumps(source), encoding="utf-8")
        runtime.write_text(json.dumps({"intents": {
            source["runs"][1]["id"]: {"scientific_admission": {"scope": "p0_diagnostic"}},
        }}), encoding="utf-8")
        result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        active = result["current_runs"][0]
        self.assertEqual(active["kind"], "diagnostic")
        self.assertEqual(active["group"], "P0 诊断")
        self.assertIsNone(active["case_id"])
        self.assertIsNone(active["public_id"])
        self.assertEqual(active["parameters"], {})

    def test_sealed_holdout_has_no_live_or_recent_per_case_cards(self):
        observation, runtime, runs, source = self.make_inputs()
        identities = ("r06-hr-d0-nominal-p00-b1", "r06-hp-h0-long-channel-threshold0-b1")
        runtime.write_text(json.dumps({"intents": {
            item["id"]: {"run_id": item["run_id"], "scientific_admission": {
                "scope": "holdout_evaluation", "case_id": identity,
            }} for item, identity in zip(source["runs"], identities)
        }}), encoding="utf-8")
        with patch("status_checker.read_input_parameters") as reader:
            result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        reader.assert_not_called()
        self.assertEqual(result["current_runs"], [])
        self.assertEqual(result["recent_activity"], [])
        self.assertTrue(all(identity not in json.dumps(result) for identity in identities))

    def test_sealed_identity_from_observation_alone_cannot_be_published(self):
        observation, runtime, runs, source = self.make_inputs()
        source["runs"][1].update(case_id="r06-hp-h0-threshold-b1", public_id="DEV-P000-C01-E0-B1")
        observation.write_text(json.dumps(source), encoding="utf-8")
        result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(result["current_runs"], [])

    def test_sealed_transport_pool_does_not_expose_inputs(self):
        observation, runtime, runs, source = self.make_inputs()
        runtime.write_text(json.dumps({"intents": {
            source["runs"][1]["id"]: {"scientific_admission": {
                "scope": "transport_pool", "pool": ["private-pool", "C2"],
                "training_freeze": {"path": "/private/model", "sha256": "f" * 64},
            }},
        }}), encoding="utf-8")
        with patch("status_checker.read_input_parameters") as reader:
            result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        reader.assert_not_called()
        self.assertEqual(result["current_runs"], [])

    def test_runtime_can_bind_card_by_run_when_observation_has_no_task_identity(self):
        observation, runtime, runs, source = self.make_inputs()
        identity = "r06-z-d0-nominal-b0"
        runtime.write_text(json.dumps({"intents": {
            "another-task-key": {"run_id": "auto-active", "scientific_admission": {"case_id": identity}},
        }}), encoding="utf-8")
        result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(result["current_runs"][0]["case_id"], identity)

    def test_actual_input_parameters_and_development_alias(self):
        observation, runtime, runs, payload = self.make_inputs()
        with patch("status_checker.read_input_parameters", return_value={"energy_MeV": 1, "temperature_K": 300, "stored_bit": 1}):
            result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        active = result["current_runs"][0]
        self.assertEqual(active["public_id"], "DEV-P000-C01-E0-B1")
        self.assertEqual(active["parameters"]["energy_MeV"], 1)
        self.assertEqual(active["parameters"]["stored_bit"], 1)

    def test_verified_collection_supersedes_old_running_snapshot(self):
        observation, runtime, runs, payload = self.make_inputs()
        path = runs / "auto-active" / "manifest.json"
        path.parent.mkdir()
        path.write_text(json.dumps({
            "run_id": "auto-active", "state": "FAILED_COLLECTED",
            "collection_verified": True, "remote_exit_code": 143,
            "collection_exit_code": 0, "tool_exit_codes": {"device": 143},
        }), encoding="utf-8")
        result = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(result["running_groups"], 0)
        self.assertEqual(result["current_runs"], [])
        self.assertEqual(result["failed_groups"], 1)

    def test_benchmark_unknown_success_and_source_freshness(self):
        observation, runtime, runs, payload = self.make_inputs()
        payload.update(fresh_max_age_seconds=90, capacity=4, requested_threads=2)
        payload["runs"] = [{
            "id": "private-probe", "run_id": "private-probe", "public_id": "BENCH-MC2-4-01",
            "status": "RUNNING", "occupied": True, "collected": False, "success": None,
            "backend": "tcad", "kind": "performance_probe", "requested_threads": 2,
            "parameters": {"numerical_threads": 2, "grid_points": 95993, "path": "/private"},
        }]
        observation.write_text(json.dumps(payload), encoding="utf-8")
        result = simulation_status(observation, runtime, runs, now=SNAPSHOT + dt.timedelta(seconds=91))
        self.assertTrue(result["observation_stale"])
        self.assertEqual(result["freshness_threshold_seconds"], 90)
        self.assertEqual(result["current_runs"][0]["kind"], "benchmark")
        self.assertEqual(result["current_runs"][0]["group"], "BENCH-MC2-4-01")
        self.assertNotIn("private", json.dumps(result))

    def test_site_health_checks_files_service_and_verified_https(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="active\n")
            self.assertEqual(research_site_state(good, root), "offline")
            (root / "index.html").write_text("site", encoding="utf-8")
            self.assertEqual(research_site_state(good, root), "operational")
            def https_failure(command, **kwargs):
                return SimpleNamespace(returncode=0 if command[0] == "systemctl" else 60, stdout="active\n")
            self.assertEqual(research_site_state(https_failure, root), "degraded")
            def inactive(command, **kwargs):
                return SimpleNamespace(returncode=3, stdout="inactive\n")
            self.assertEqual(research_site_state(inactive, root), "offline")

    def make_inputs(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        observation = root / "observation.json"
        runtime = root / "runtime.json"
        runs = root / "runs"
        completed_key = "r04-l08-p000-c00-event7377-nodal-whr-b0-r1"
        completed_id = f"auto-{completed_key}-aabb"
        active_key = "r04-l08-p000-c01-event0-nodal-whr-b1-r1"
        payload = {
            "utc": "2026-11-17T03:00:00Z",
            "queue_complete": False,
            "runs": [
                {
                    "id": completed_key,
                    "run_id": completed_id,
                    "backend": "tcad",
                    "status": "succeeded",
                    "collected": True,
                    "success": True,
                    "occupied": False,
                },
                {
                    "id": active_key,
                    "run_id": "auto-active",
                    "backend": "tcad",
                    "status": "running",
                    "collected": False,
                    "success": False,
                    "occupied": True,
                },
            ],
        }
        observation.write_text(json.dumps(payload), encoding="utf-8")
        started = SNAPSHOT - dt.timedelta(minutes=15)
        runtime.write_text(
            json.dumps({"intents": {active_key: {"submission_intent_at": started.timestamp()}}}),
            encoding="utf-8",
        )
        manifest_path = runs / completed_id / "manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(
            json.dumps({
                "run_id": completed_id,
                "started_utc": "2026-11-17T02:00:00Z",
                "collected_utc": "2026-11-17T02:30:00Z",
            }),
            encoding="utf-8",
        )
        return observation, runtime, runs, payload

    def test_overall_state(self):
        self.assertEqual(overall_state(["operational", "operational"]), "operational")
        self.assertEqual(overall_state(["operational", "offline"]), "degraded")
        self.assertEqual(overall_state(["offline", "offline"]), "offline")

    def test_task_failure_does_not_offline_the_site_and_uncollected_has_its_own_state(self):
        services = [
            {"id": "research-site", "state": "operational"},
            {"id": "tcad-controller", "state": "operational"},
            {"id": "simulation-runtime", "state": "operational"},
        ]
        scheduler = {
            "observed_at": "2026-11-17T03:00:00Z",
            "observation_stale": False,
            "virtual_machine": {"daemon_health": {"lmgrd": {"alive": True, "elapsed_seconds": 5}}},
            "tasks": [
                {"id": "RUN-aaaaaaaaaaaa", "state": "failed", "health": None},
                {"id": "RUN-bbbbbbbbbbbb", "state": "uncollected", "health": "collection_overdue"},
            ],
        }
        self.assertEqual(build_service_health(services, scheduler, {})["state"], "operational")
        self.assertEqual(build_simulation_health(scheduler, {})["state"], "awaiting_collection")
        feed = build_activity_feed(scheduler, {}, dt.datetime(2026, 11, 17, 3, 1, tzinfo=UTC))
        self.assertEqual(feed["mode"], "idle")
        self.assertEqual(feed["live_items"][0]["state"], "uncollected")

    def test_freshness_reports_cache_fallback_and_probe_age(self):
        scheduler = {"observed_at": "2026-11-17T03:00:00Z", "observation_stale": False}
        research = {"available": True, "projection_state": "cached_stale",
                    "projected_at": "2026-11-17T02:55:00Z"}
        health = build_freshness_health(scheduler, research, dt.datetime(2026, 11, 17, 3, 1, tzinfo=UTC))
        self.assertEqual(health["state"], "delayed")
        self.assertEqual(health["scheduler_age_seconds"], 60)
        self.assertEqual(health["scheduler_threshold_seconds"], 180)
        self.assertEqual(health["research_projection_state"], "cached_stale")

    def test_build_status_is_redacted(self):
        with patch("status_checker.system_metrics", return_value={}):
            payload = build_status(runner=fake_runner)
        self.assertEqual(payload["overall"], "degraded")
        self.assertEqual(payload["services"][1]["state"], "operational")
        self.assertEqual(payload["services"][2]["state"], "offline")
        serialized = json.dumps(payload)
        for forbidden in ("127.0.0.1", "/srv/", "run_id", "ssh", "lm_license_file"):
            self.assertNotIn(forbidden, serialized.lower())

    def test_maintenance_overrides_overall(self):
        with patch("status_checker.system_metrics", return_value={}):
            payload = build_status("Scheduled maintenance", runner=fake_runner)
        self.assertEqual(payload["overall"], "maintenance")
        self.assertEqual(payload["maintenance"], "Scheduled maintenance")

    def test_simulation_summary_is_redacted_and_counts_groups(self):
        observation, runtime, runs, _ = self.make_inputs()
        payload = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(payload["total_groups"], 2)
        self.assertEqual(payload["completed_groups"], 1)
        self.assertEqual(payload["running_groups"], 1)
        self.assertEqual(payload["pending_groups"], 0)
        self.assertEqual(payload["completion_rate"], 50.0)
        self.assertEqual(payload["current_runs"][0]["group"], "C01 · Event 0 · B1")
        serialized = json.dumps(payload)
        for forbidden in ("run_id", "auto-active", "r04-l08", "/home/", "/var/", "ssh", "license"):
            self.assertNotIn(forbidden, serialized.lower())

    def test_freshness_boundary_and_stale_snapshot_do_not_advance_elapsed(self):
        observation, runtime, runs, _ = self.make_inputs()
        for age, stale in ((0, False), (180, False), (180.1, True), (181, True), (21600, True)):
            with self.subTest(age=age):
                payload = simulation_status(observation, runtime, runs, now=SNAPSHOT + dt.timedelta(seconds=age))
                self.assertTrue(payload["observed"])
                self.assertIs(payload["observation_stale"], stale)
                self.assertEqual(payload["observation_age_seconds"], int(age))
                self.assertEqual(payload["freshness_threshold_seconds"], 180)
                self.assertEqual(payload["updated_at"], "2026-11-17T03:00:00Z")
                self.assertEqual(payload["current_runs"][0]["elapsed_seconds"], 900)
                self.assertEqual(payload["current_elapsed_seconds"], 900)
                self.assertEqual(payload["completed_runtime_seconds"], 1800)
                self.assertEqual(payload["cumulative_runtime_seconds"], 2700)

    def test_runtime_is_sum_of_record_spans_even_when_runs_overlap(self):
        observation, runtime, runs, source = self.make_inputs()
        second = dict(source["runs"][1], id="second", run_id="auto-second")
        source["runs"].append(second)
        observation.write_text(json.dumps(source), encoding="utf-8")
        manifest = runs / "auto-second" / "manifest.json"
        manifest.parent.mkdir()
        manifest.write_text(
            json.dumps({"run_id": "auto-second", "started_utc": "2026-11-17T02:50:00Z"}),
            encoding="utf-8",
        )
        payload = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(payload["duration_basis"], "record_span")
        self.assertEqual(payload["current_elapsed_seconds"], 900)
        self.assertEqual(payload["completed_runtime_seconds"], 1800)
        self.assertEqual(payload["cumulative_runtime_seconds"], 3300)

    def test_missing_observation_is_unknown(self):
        observation, runtime, runs, _ = self.make_inputs()
        observation.unlink()
        payload = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(payload["state"], "unknown")
        self.assertFalse(payload["observed"])
        for field in (
            "observation_stale", "observation_age_seconds", "updated_at", "queue_complete",
            "total_groups", "running_groups", "completed_groups", "successful_groups",
            "failed_groups", "pending_groups", "completion_rate", "current_elapsed_seconds",
            "completed_runtime_seconds", "cumulative_runtime_seconds", "last_completed_at",
        ):
            self.assertIsNone(payload[field], field)
        self.assertEqual(payload["current_runs"], [])
        self.assertEqual(payload["recent_activity"], [])

    def test_empty_observation_object_is_unknown(self):
        observation, runtime, runs, _ = self.make_inputs()
        observation.write_text("{}", encoding="utf-8")
        payload = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertFalse(payload["observed"])
        self.assertIsNone(payload["total_groups"])
        self.assertIsNone(payload["queue_complete"])

    def test_observed_empty_queue_is_known_and_queue_complete_requires_boolean(self):
        observation, runtime, runs, _ = self.make_inputs()
        source = {"utc": "2026-11-17T03:00:00Z", "runs": [], "queue_complete": True}
        observation.write_text(json.dumps(source), encoding="utf-8")
        payload = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertTrue(payload["observed"])
        self.assertEqual(payload["state"], "idle")
        self.assertEqual(payload["total_groups"], 0)
        self.assertEqual(payload["pending_groups"], 0)
        self.assertEqual(payload["cumulative_runtime_seconds"], 0)
        self.assertIs(payload["queue_complete"], True)
        del source["queue_complete"]
        observation.write_text(json.dumps(source), encoding="utf-8")
        self.assertIsNone(simulation_status(observation, runtime, runs, now=SNAPSHOT)["queue_complete"])

    def test_unknown_start_is_null_instead_of_zero_and_totals_are_not_partial(self):
        observation, runtime, runs, _ = self.make_inputs()
        runtime.unlink()
        payload = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertIsNone(payload["current_runs"][0]["started_at"])
        self.assertIsNone(payload["current_runs"][0]["elapsed_seconds"])
        self.assertIsNone(payload["current_elapsed_seconds"])
        self.assertIsNone(payload["cumulative_runtime_seconds"])
        self.assertEqual(payload["completed_runtime_seconds"], 1800)

    def test_completed_group_without_timestamps_has_unknown_duration(self):
        observation, runtime, runs, source = self.make_inputs()
        source["runs"] = source["runs"][:1]
        observation.write_text(json.dumps(source), encoding="utf-8")
        next(runs.rglob("manifest.json")).unlink()
        payload = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(payload["completed_groups"], 1)
        self.assertIsNone(payload["completed_runtime_seconds"])
        self.assertIsNone(payload["cumulative_runtime_seconds"])
        self.assertIsNone(payload["last_completed_at"])

    def test_pending_manifest_update_is_not_completed_activity_or_runtime(self):
        observation, runtime, runs, source = self.make_inputs()
        source["runs"] = [dict(source["runs"][0], status="pending", collected=False, success=False)]
        observation.write_text(json.dumps(source), encoding="utf-8")
        payload = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(payload["pending_groups"], 1)
        self.assertEqual(payload["recent_activity"], [])
        self.assertEqual(payload["completed_runtime_seconds"], 0)
        self.assertIsNone(payload["last_completed_at"])

    def test_untrusted_metadata_is_not_exposed_and_invalid_times_stay_unknown(self):
        observation, runtime, runs, source = self.make_inputs()
        private = "/home/private/full-runid ssh 10.111.138.80 license"
        source["runs"][1]["id"] = private
        source["private_command"] = private
        observation.write_text(json.dumps(source), encoding="utf-8")
        runtime.write_text(json.dumps({"intents": {private: {"submission_intent_at": float("inf")}}}), encoding="utf-8")
        manifest = next(runs.rglob("manifest.json"))
        manifest.write_text(json.dumps({
            "run_id": source["runs"][0]["run_id"],
            "started_utc": {"private": private},
            "collected_utc": private,
            "updated_utc": "2026-11-17T02:30:00+00:00",
        }), encoding="utf-8")
        payload = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        serialized = json.dumps(payload)
        for forbidden in (private, "/home/", "full-runid", "ssh", "10.111.138.80", "license", "run_id"):
            self.assertNotIn(forbidden, serialized)
        self.assertIsNone(payload["current_runs"][0]["elapsed_seconds"])
        self.assertIsNone(payload["completed_runtime_seconds"])
        self.assertEqual(payload["last_completed_at"], "2026-11-17T02:30:00Z")

    def test_reversed_or_naive_record_times_are_unknown(self):
        observation, runtime, runs, source = self.make_inputs()
        manifest = next(runs.rglob("manifest.json"))
        for started_at in ("2026-11-17T04:00:00Z", "2026-11-17T02:00:00"):
            with self.subTest(started_at=started_at):
                manifest.write_text(json.dumps({
                    "run_id": source["runs"][0]["run_id"],
                    "started_utc": started_at,
                    "collected_utc": "2026-11-17T02:30:00Z",
                }), encoding="utf-8")
                self.assertIsNone(simulation_status(observation, runtime, runs, now=SNAPSHOT)["completed_runtime_seconds"])

    def test_equal_completion_times_do_not_compare_activity_dictionaries(self):
        observation, runtime, runs, source = self.make_inputs()
        source["runs"].append(dict(source["runs"][0], id="another-group"))
        observation.write_text(json.dumps(source), encoding="utf-8")
        payload = simulation_status(observation, runtime, runs, now=SNAPSHOT)
        self.assertEqual(len(payload["recent_activity"]), 2)

    def assert_failed_update_preserves_output(self, observation, runtime, runs):
        target = observation.parent / "public-status.json"
        previous = b'{"generated_at":"old","simulation":{"observed":true}}\n'
        target.write_bytes(previous)
        output = io.StringIO()
        with (
            patch("sys.argv", ["status_checker.py", "--output", str(target)]),
            patch("status_checker.build_status", side_effect=lambda _: simulation_status(observation, runtime, runs)),
            patch("sys.stderr", output),
        ):
            self.assertEqual(main(), 1)
        self.assertEqual(target.read_bytes(), previous)
        self.assertEqual(output.getvalue(), "Status update failed; previous output retained.\n")
        self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_malformed_observation_preserves_previous_public_output(self):
        observation, runtime, runs, source = self.make_inputs()
        malformed = [
            "{broken",
            "[]",
            json.dumps(dict(source, runs=[None])),
            json.dumps(dict(source, runs=[{"occupied": "false"}])),
            json.dumps(dict(source, runs=[{"status": "failed_unlaunched", "terminal_reconciled": "true"}])),
            json.dumps(dict(source, runs=[{"status": {}}])),
            json.dumps(dict(source, runs={})),
            json.dumps(dict(source, queue_complete="false")),
            json.dumps(dict(source, utc={"private": "/var/private ssh 10.0.0.1"})),
            json.dumps(dict(source, utc="2026-11-17T03:00:00")),
            json.dumps({"utc": source["utc"]}),
        ]
        for raw in malformed:
            with self.subTest(raw=raw):
                observation.write_text(raw, encoding="utf-8")
                self.assert_failed_update_preserves_output(observation, runtime, runs)
        observation.write_bytes(b"\xff")
        self.assert_failed_update_preserves_output(observation, runtime, runs)

    def test_malformed_runtime_or_manifest_preserves_previous_public_output(self):
        observation, runtime, runs, _ = self.make_inputs()
        for path in (runtime, next(runs.rglob("manifest.json"))):
            with self.subTest(path=path.name):
                previous = path.read_bytes()
                path.write_text("[", encoding="utf-8")
                self.assert_failed_update_preserves_output(observation, runtime, runs)
                path.write_bytes(previous)

    def test_atomic_write(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "status.json"
            payload = {"overall": "operational", "services": [], "maintenance": None}
            write_json_atomic(target, payload)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_atomic_write_chmods_before_replace_on_every_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "status.json"
            target.write_text('{"overall": "offline"}\n', encoding="utf-8")
            events = []
            original_chmod = Path.chmod
            original_replace = Path.replace

            def chmod(source, mode):
                self.assertEqual(mode, 0o644)
                events.append("chmod")
                return original_chmod(source, mode)

            def replace(source, destination):
                self.assertEqual(events, ["chmod"])
                self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["overall"], "offline")
                events.append("replace")
                return original_replace(source, destination)

            with (
                patch.object(Path, "chmod", autospec=True, side_effect=chmod),
                patch.object(Path, "replace", autospec=True, side_effect=replace),
            ):
                write_json_atomic(target, {"overall": "operational"})
            self.assertEqual(events, ["chmod", "replace"])
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["overall"], "operational")

    def test_atomic_write_failure_retains_previous_bytes_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "status.json"
            previous = b'{"overall":"operational"}\n'
            target.write_bytes(previous)
            for value in (object(), float("nan")):
                with self.subTest(value=type(value).__name__):
                    with self.assertRaises((TypeError, ValueError)):
                        write_json_atomic(target, {"bad": value})
                    self.assertEqual(target.read_bytes(), previous)
                    self.assertEqual(list(target.parent.glob("*.tmp")), [])
            with patch.object(Path, "replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    write_json_atomic(target, {"overall": "offline"})
            self.assertEqual(target.read_bytes(), previous)
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    @unittest.skipUnless(os.name == "posix", "requires POSIX permission bits")
    def test_atomic_write_is_readable_at_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "status.json"
            target.write_text('{"overall": "offline"}\n', encoding="utf-8")
            target.chmod(0o600)
            payload = {"overall": "operational", "services": [], "maintenance": None}
            original_replace = Path.replace

            def replace_and_check_permissions(source, destination):
                self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o644)
                self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["overall"], "offline")
                result = original_replace(source, destination)
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o644)
                self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), payload)
                return result

            with patch.object(Path, "replace", autospec=True, side_effect=replace_and_check_permissions) as replace:
                write_json_atomic(target, payload)

            replace.assert_called_once()
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
