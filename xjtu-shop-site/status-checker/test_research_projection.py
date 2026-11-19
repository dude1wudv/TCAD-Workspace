import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from progress_store import init_store, load_public_progress, set_progress
from research_projection import (
    RESEARCH_CACHE_MAX_BYTES, build_research, execution, load_cached_research, load_stats_snapshot,
    save_cached_research,
)


UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
INPUT_SHA256 = "1" * 64
RESULTS_SHA256 = "2" * 64


def case(case_id, cohort, pair_id=None, **extra):
    value = {
        "case_id": case_id,
        "cohort": cohort,
        "kind": "response",
        "condition_id": "m1-r05-D0-C0",
        "profile_id": "m1-r05-P0",
        "pair_id": pair_id,
    }
    value.update(extra)
    return value


def plan(cases):
    return {
        "schema_version": 1,
        "revision": "r0.5",
        "cases": cases,
        "conditions": [{
            "id": "m1-r05-D0-C0",
            "cohort": "core",
            "parameters": {
                "Lg": {"value": 1.02, "unit": "1", "representation": "baseline_multiplier"},
                "Tox": {"value": 4.0, "unit": "nm", "representation": "absolute"},
                "unrecognized_parameter": {"value": "private-value", "unit": "secret", "representation": "absolute"},
            },
        }],
        "profiles": [{"id": "m1-r05-P0", "parameters": {
            "Wfin": {"value": 0.98, "unit": "1", "representation": "baseline_multiplier"},
        }}],
    }


class ResearchProjectionTests(unittest.TestCase):
    def test_execution_requires_explicit_running_and_never_infers_it_from_occupancy(self):
        for status in (None, "unknown", "reconciliation_pending", "pending"):
            with self.subTest(status=status):
                self.assertEqual(execution({}, {"occupied": True, "status": status}, True), "pending")
        self.assertEqual(execution({}, {"occupied": False, "status": "RUNNING"}, True), "running")
        self.assertEqual(execution({}, {"occupied": True, "status": "running"}, False), "pending")

    def test_only_confirmed_unlaunched_failure_is_a_terminal_execution_failure(self):
        record = {"status": "failed_unlaunched", "occupied": True}
        for value in (False, None, "true"):
            with self.subTest(value=value):
                self.assertEqual(execution({}, dict(record, terminal_reconciled=value), True), "pending")
        self.assertEqual(execution({}, dict(record, terminal_reconciled=True), True), "failed")
        self.assertEqual(execution({}, dict(record, terminal_reconciled=True), False), "failed")

    def test_r05_unlaunched_failure_is_not_counted_as_an_archive(self):
        result = self.project(
            plan([case("m1-r05-unlaunched", "core", run_ids=["private-unlaunched"])]),
            observation={"utc": NOW.isoformat(), "runs": [{
                "run_id": "private-unlaunched", "status": "failed_unlaunched",
                "terminal_reconciled": True, "occupied": True,
            }]},
        )
        self.assertEqual(result["counts"]["core"]["failed"], 1)
        self.assertEqual(result["counts"]["core"]["archived"], 0)
        self.assertEqual(result["counts"]["core"]["running"], 0)
        self.assertEqual(result["counts"]["core"]["accepted"], 0)

    def project(self, value, manifests=None, observation=None, progress=None,
                runtime=None, work_items=None, evidence_files=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            for relative_path, payload in (evidence_files or {}).items():
                evidence_path = path.parent / relative_path
                evidence_path.parent.mkdir(parents=True, exist_ok=True)
                evidence_path.write_text(json.dumps(payload), encoding="utf-8")
            return build_research(
                path, manifests or {}, observation or {}, progress or [], now=NOW,
                runtime=runtime, work_items=work_items,
            )

    @staticmethod
    def successful_manifest(run_id, **extra):
        value = {
            "run_id": run_id,
            "state": "COLLECTED",
            "collection_verified": True,
            "remote_exit_code": 0,
            "collection_exit_code": 0,
            "tool_exit_codes": {"transport": 0, "device": 0},
            "input_sha256": INPUT_SHA256,
            "results_sha256": RESULTS_SHA256,
        }
        value.update(extra)
        return value

    def test_cohort_denominators_and_pair_deduplication(self):
        result = self.project(plan([
            case("m1-r05-D0-core-a", "core", "pair-core"),
            case("m1-r05-D0-core-b", "core", "pair-core"),
            case("m1-r05-D0-reserve-a", "reserve", "pair-reserve"),
            case("m1-r05-D0-reserve-b", "reserve", "pair-reserve"),
            case("m1-r05-D0-control-a", "control", "pair-control", kind="control"),
            case("m1-r05-D0-control-b", "control", "pair-control", kind="control"),
        ]))
        for cohort in ("core", "reserve", "control"):
            self.assertEqual(result["counts"][cohort]["planned"], 2)
        self.assertEqual(result["counts"]["core"]["pairs"], 1)
        self.assertEqual(result["counts"]["reserve"]["pairs"], 1)
        self.assertEqual(result["counts"]["control"]["pairs"], 0)

    def test_retry_failure_then_success_is_one_solved_case(self):
        first = {"run_id": "private-run-fail", "state": "FAILED_COLLECTED",
                 "collection_verified": True, "remote_exit_code": 1,
                 "collection_exit_code": 0, "tool_exit_codes": {"device": 1}}
        second = self.successful_manifest("private-run-success")
        result = self.project(
            plan([case("m1-r05-D0-retry", "core", run_ids=["private-run-fail", "private-run-success"])]),
            {"private-run-fail": first, "private-run-success": second},
        )
        self.assertEqual(result["counts"]["core"]["planned"], 1)
        self.assertEqual(result["counts"]["core"]["solved"], 1)
        self.assertEqual(result["cases"][0]["attempts"], 2)

    def test_collected_without_original_collection_and_tool_proof_is_not_solved(self):
        for manifest in (
            {"state": "COLLECTED", "remote_exit_code": 0, "collection_exit_code": 0,
             "tool_exit_codes": {"device": 0}},
            {"state": "COLLECTED", "collection_verified": True,
             "remote_exit_code": 0, "collection_exit_code": 0, "tool_exit_codes": {}},
        ):
            with self.subTest(manifest=manifest):
                result = self.project(
                    plan([case("m1-r05-D0-unproven", "core", run_ids=["run-a"])]),
                    {"run-a": manifest},
                )
                self.assertEqual(result["counts"]["core"]["solved"], 0)
                self.assertNotIn(result["cases"][0]["state"], ("solved", "accepted"))

    def test_acceptance_requires_solved_and_explicit_evidence(self):
        cases = [
            case("m1-r05-D0-no-evidence", "core", run_ids=["run-a"], accepted=True),
            case("m1-r05-D0-arbitrary-reference", "core", run_ids=["run-b"], accepted=True,
                 acceptance_evidence="record:sha256-0123456789abcdef"),
            case("m1-r05-D0-with-evidence", "core", run_ids=["run-b"], accepted=True,
                 acceptance_evidence="evidence/accepted.json"),
        ]
        evidence = {
            "status": "accepted",
            "case_id": "m1-r05-D0-with-evidence",
            "run_id": "run-b",
            "input_sha256": INPUT_SHA256,
            "results_sha256": RESULTS_SHA256,
        }
        result = self.project(plan(cases), {
            "run-a": self.successful_manifest("run-a"),
            "run-b": self.successful_manifest("run-b"),
        }, evidence_files={"evidence/accepted.json": evidence})
        self.assertEqual(result["counts"]["core"]["solved"], 3)
        self.assertEqual(result["counts"]["core"]["accepted"], 1)
        self.assertEqual([item["state"] for item in result["cases"]],
                         ["solved", "solved", "accepted"])

    def test_acceptance_evidence_must_match_case_run_and_manifest_hashes(self):
        mismatches = (
            {"case_id": "m1-r05-D0-other-case"},
            {"run_id": "other-run"},
            {"input_sha256": "3" * 64},
            {"results_sha256": "4" * 64},
            {"input_sha256": "not-a-sha256"},
            {"results_sha256": "not-a-sha256"},
        )
        for index, mismatch in enumerate(mismatches):
            with self.subTest(mismatch=mismatch):
                case_id = "m1-r05-D0-evidence-check-{}".format(index)
                evidence = {
                    "status": "accepted",
                    "case_id": case_id,
                    "run_id": "run-a",
                    "input_sha256": INPUT_SHA256,
                    "results_sha256": RESULTS_SHA256,
                }
                evidence.update(mismatch)
                result = self.project(
                    plan([case(case_id, "core", run_ids=["run-a"], accepted=True,
                               acceptance_evidence="evidence/check.json")]),
                    {"run-a": self.successful_manifest("run-a")},
                    evidence_files={"evidence/check.json": evidence},
                )
                self.assertEqual(result["counts"]["core"]["solved"], 1)
                self.assertEqual(result["counts"]["core"]["accepted"], 0)
                self.assertEqual(result["cases"][0]["state"], "solved")

    def test_codex_resolved_annotation_does_not_change_execution_or_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "progress.sqlite3"
            init_store(db)
            set_progress(
                db, case_id="m1-r05-D0-annotated", issue="solver_failure",
                action="resolved", phase="validation", note="已整理复查记录",
                next_step="等待原始收集", evidence="/private/evidence/record.json",
            )
            progress = load_public_progress(db)
            result = self.project(
                plan([case("m1-r05-D0-annotated", "core")]), progress=progress,
            )
        self.assertEqual(result["counts"]["core"]["solved"], 0)
        self.assertEqual(result["counts"]["core"]["accepted"], 0)
        self.assertEqual(result["cases"][0]["state"], "pending")
        self.assertNotIn("/private/evidence/record.json", json.dumps(result))

    def test_only_fresh_observation_can_report_running(self):
        value = plan([case("m1-r05-D0-running", "core", run_ids=["run-active"])])
        fresh = {"utc": NOW.isoformat(), "runs": [{"run_id": "run-active", "status": "running"}]}
        stale = {"utc": (NOW - dt.timedelta(seconds=181)).isoformat(),
                 "runs": [{"run_id": "run-active", "status": "running"}]}
        self.assertEqual(self.project(value, observation=fresh)["cases"][0]["state"], "running")
        result = self.project(value, observation=stale)
        self.assertEqual(result["cases"][0]["state"], "pending")
        self.assertTrue(result["observation_stale"])

    def test_work_item_case_id_binds_through_runtime_intent(self):
        run_id = "private-runtime-run"
        result = self.project(
            plan([case("m1-r05-D0-from-task", "core")]),
            {run_id: self.successful_manifest(run_id)},
            runtime={"intents": {"task-public-1": {"run_id": run_id}}},
            work_items={"tasks": [{"id": "task-public-1", "case_id": "m1-r05-D0-from-task"}]},
        )
        self.assertEqual(result["counts"]["core"]["solved"], 1)

    def test_benchmark_manifest_does_not_bind_a_research_case(self):
        benchmark = self.successful_manifest(
            "benchmark-run", case_id="m1-r05-D0-benchmark", kind="benchmark",
        )
        result = self.project(
            plan([case("m1-r05-D0-benchmark", "core")]),
            {"benchmark-run": benchmark},
        )
        self.assertEqual(result["counts"]["core"]["solved"], 0)
        self.assertEqual(result["cases"][0]["state"], "pending")

    def test_public_projection_omits_paths_run_ids_private_values_and_unknown_parameters(self):
        private_path = "/srv/private/absolute-evidence.json"
        value = plan([case(
            "m1-r05-D0-public", "core", run_ids=["private-run-identifier"],
            accepted=True, acceptance_evidence="evidence/private.json",
        )])
        evidence = {
            "status": "accepted",
            "case_id": "m1-r05-D0-public",
            "run_id": "private-run-identifier",
            "input_sha256": INPUT_SHA256,
            "results_sha256": RESULTS_SHA256,
        }
        result = self.project(value, {
            "private-run-identifier": self.successful_manifest(
                "private-run-identifier", private_path=private_path,
                internal_address="203.0.113.10",
            ),
        }, evidence_files={"evidence/private.json": evidence})
        encoded = json.dumps(result)
        for secret in (private_path, "private-run-identifier", "203.0.113.10", "private-value"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(result["conditions"][0]["parameters"]["Lg_relative"], 1.02)
        self.assertEqual(result["profiles"][0]["parameters"]["Wfin_relative"], 0.98)
        self.assertNotIn("Tox_relative", result["conditions"][0]["parameters"])
        self.assertNotIn("unrecognized_parameter", encoded)
        self.assertEqual(result["cases"][0]["state"], "accepted")

    def test_absolute_unverified_acceptance_reference_does_not_accept(self):
        result = self.project(
            plan([case("m1-r05-D0-absolute-ref", "core", run_ids=["run-a"], accepted=True,
                       acceptance_evidence="/private/unverified/path.json")]),
            {"run-a": self.successful_manifest("run-a")},
        )
        self.assertEqual(result["counts"]["core"]["solved"], 1)
        self.assertEqual(result["counts"]["core"]["accepted"], 0)
        self.assertEqual(result["cases"][0]["state"], "solved")

    def test_duplicate_public_case_ids_and_malformed_json_fail(self):
        duplicate = case("m1-r05-D0-duplicate", "core")
        with self.assertRaises(ValueError):
            self.project(plan([duplicate, dict(duplicate)]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text('{"schema_version": 1,', encoding="utf-8")
            with self.assertRaises(ValueError):
                build_research(path, {}, {}, [], now=NOW)

    def test_real_month_one_plan_is_optional_read_only_compatibility_check(self):
        path = Path(__file__).resolve().parents[2] / "tcad-research-training" / "plans" / "dram-se-ddr5-lpddr5" / "month-one-cases-r05.json"
        if not path.is_file():
            self.skipTest("local r0.5 plan is not present")
        result = build_research(path, {}, {}, [], now=NOW)
        self.assertEqual(result["schema_version"], 1)
        self.assertTrue(result["available"])
        self.assertEqual(result["revision"], "r0.5")
        self.assertTrue(result["cases"])


class SelfDescribingProjectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / "plan.json"
        self.devices = ["dramx-nominal", "dramx-holdout"]
        self.identities = [f"r07-{name}-dramx-b1" for name in ("trial-a", "trial-b", "blind", "profile-blind")]
        self.plan = {
            "schema_version": 1, "revision": "r0.7",
            "blocks": [{"id": "Trial"}, {"id": "Blind", "sealed": True}],
            "cases": [{"case_id": identity, "cohort": group, "profile_id": device, **extra}
                      for identity, group, device, extra in zip(self.identities,
                          ("Trial", "Trial", "Blind", "ProfileBlind"),
                          [self.devices[0]] * 3 + [self.devices[1]],
                          ({"statistics_intent": True}, {}, {}, {"holdout": "profile"}))],
            "budget": {"block_case_counts": {"Trial": 2, "Blind": 1, "ProfileBlind": 1}, "total_cases": 4},
            "profiles": [{"id": self.devices[0], "parameters": {
                "requested_threads": 4, "body_thickness_nm": 87.5, "polarity": "nmos",
                "license_server": 142, "api_key": 99, "bad/name": 1, "mode": "https://private.example",
                "secret_path": "C:\\private", "unitless": float("inf"), "control": "x\x00y",
            }}, {"id": self.devices[1], "partition": "profile_holdout", "parameters": {"body_thickness_nm": 123}}],
            "radiations": [{"id": "proton-training", "energy_MeV": 5, "extra_physics": 42},
                           {"id": "proton-blind", "role": "radiation_holdout", "energy_MeV": 777}],
        }
        self.path.write_text(json.dumps(self.plan), encoding="utf-8")

    def project(self, **kwargs):
        return build_research(self.path, kwargs.pop("manifests", {}), kwargs.pop("observation", {}), [], now=NOW, **kwargs)

    def test_scheduler_fusion_preserves_formal_plan_and_hides_sealed_cases(self):
        visible_a, visible_b, sealed_a, sealed_b = self.identities
        tasks = [{"id": f"RUN-{index}", "kind": "formal", "case_id": identity, "state": "running",
                  "requested_threads": 4, "cpu_set": [0, 1, 2, 3]} for index, identity in enumerate(self.identities)]
        tasks += [{"id": "P0-task", "kind": "diagnostic", "state": "running"}] * 2
        tasks += [{"id": "repair-task", "kind": "diagnostic", "scope": "mesh_diagnostic", "state": "running"}]
        runtime = {"intents": {
            "formal-task": {"run_id": "run-formal", "scientific_admission": {"case_id": visible_a}},
            "P0-task": {"run_id": "run-diag", "scientific_admission": {"scope": "p0_diagnostic"}},
            "P0-with-projected-id": {"run_id": "run-second-diag", "scientific_admission": {"scope": "p0_diagnostic"}},
        }}
        tasks.append({"id": "RUN-diagnostic", "kind": "diagnostic", "state": "running"})
        result = self.project(
            scheduler={"layout_widths": [4], "tasks": tasks}, runtime=runtime,
            manifests={"run-second-diag": {"_scheduler_task_id": "RUN-diagnostic"}},
            observation={"utc": NOW.isoformat(), "runs": [{"run_id": "run-formal", "status": "running"}]},
        )
        self.assertEqual(result["revision"], "r0.7")
        self.assertEqual(result["totals"]["planned"], 4)
        self.assertEqual(result["totals"]["running"], 2)
        self.assertEqual(result["counts"]["Trial"]["running"], 2)
        self.assertEqual([(block["id"], block["sealed"], block["running"]) for block in result["blocks"]],
                         [("Trial", False, 2), ("Blind", True, 0), ("ProfileBlind", True, 0)])
        self.assertEqual([(case["case_id"], case["state"], case["attempts"]) for case in result["cases"]],
                         [(visible_a, "running", 1), (visible_b, "running", 1)])
        self.assertEqual(result["diagnostics"]["P0"]["planned"], 2)
        self.assertEqual(result["diagnostics"]["P0"]["running"], 2)
        self.assertEqual(result["diagnostics"]["mesh_diagnostic"]["running"], 1)
        self.assertEqual(result["profiles"][0]["parameters"], {
            "requested_threads": 4, "body_thickness_nm": 87.5, "polarity": "nmos",
        })
        self.assertEqual(result["radiations"][0]["parameters"]["extra_physics"], 42)
        self.assertEqual(result["profiles"][1]["parameters"], {})
        self.assertEqual(result["radiations"][1]["parameters"], {})
        for identity in (sealed_a, sealed_b, "RUN-diagnostic", "P0-task", "run-diag"):
            self.assertNotIn(identity, json.dumps(result))

    def test_statistics_snapshot_requires_known_schema_hashes_and_matching_plan(self):
        path = self.directory / "statistics.json"
        self.assertIsNone(load_stats_snapshot(path))
        self.assertEqual(self.project()["statistics_snapshot_status"], "not_connected")
        path.write_text("{malformed json", encoding="utf-8")
        self.assertIsNone(load_stats_snapshot(path))
        data = {"schema": "tcad-r07-statistics-snapshot-v1", "statistics_eligible_cases": 1,
                "plan_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(), "evidence_sha256": INPUT_SHA256}
        for change in ({"schema": "not-a-statistics-snapshot"}, {"evidence_sha256": "invalid"},
                       {"statistics_eligible_cases": True}):
            path.write_text(json.dumps(dict(data, **change)), encoding="utf-8")
            self.assertIsNone(load_stats_snapshot(path))
        path.write_text(json.dumps(dict(data, plan_sha256=INPUT_SHA256)), encoding="utf-8")
        self.assertEqual(self.project(stats_snapshot=load_stats_snapshot(path))["statistics_snapshot_status"], "not_connected")
        path.write_text(json.dumps(data), encoding="utf-8")
        result = self.project(stats_snapshot=load_stats_snapshot(path))
        self.assertEqual(result["statistics_snapshot_status"], "connected")
        self.assertEqual(result["budget"]["statistics_eligible_cases"], 1)
        self.assertNotIn(data["plan_sha256"], json.dumps(result))

    def test_cache_round_trip_preserves_previous_snapshot_on_invalid_save(self):
        path = self.directory / "private-cache.json"
        self.assertEqual(load_cached_research(path), (None, None))
        result = self.project()
        save_cached_research(path, result)
        self.assertEqual(load_cached_research(path)[0], result)
        self.assertTrue(load_cached_research(path)[1].endswith("Z"))
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        for value in ([], {"payload": "x" * RESEARCH_CACHE_MAX_BYTES}):
            with self.assertRaises(ValueError):
                save_cached_research(path, value)
            self.assertEqual(load_cached_research(path)[0], result)
        for invalid in (b"[]", b"{corrupt", b"x" * (RESEARCH_CACHE_MAX_BYTES + 1)):
            path.write_bytes(invalid)
            self.assertEqual(load_cached_research(path), (None, None))
        self.assertEqual(set(self.directory.iterdir()), {self.path, path})


if __name__ == "__main__":
    unittest.main()
