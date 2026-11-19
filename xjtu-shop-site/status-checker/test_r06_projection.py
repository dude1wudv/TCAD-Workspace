import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from research_projection import build_research


NOW = dt.datetime(2026, 11, 17, 12, tzinfo=dt.timezone.utc)
INPUT_HASH = "1" * 64
RESULT_HASH = "2" * 64
R06_BLOCKS = {"Z": 26, "T": 68, "S": 150, "R": 12, "HR": 28, "HP": 30, "AL": 82}


def r06_plan():
    cases = []
    for block, size in R06_BLOCKS.items():
        for index in range(size):
            cases.append({
                "case_id": "r06-{}-case-{:03d}-b1".format(block.lower(), index),
                "block": block, "profile_id": "D0", "stored_bit": 1,
                "radiation_id": None if block == "Z" else "G0", "sample_index": index,
                "deck_timing_version": "r06-hold-window-v1",
                "statistics_intent": block in {"S", "R", "HR"} or block == "HP" and index < 24,
                "statistics_eligible": False, "run_ids": [], "accepted": False,
            })
    return {
        "schema_version": 1, "revision": "r0.6", "updated_at": NOW.isoformat(),
        "budget": {"block_case_counts": dict(R06_BLOCKS), "total_cases": 396, "zero_cases": 26,
                   "profile_count": 13, "radiation_count": 10, "statistics_intent_cases": 214},
        "timing_contract": {
            "deck_timing_version": "r06-hold-window-v1",
            "hold_window_ns": [18.2, 30.0],
        },
        "cases": cases,
        "profiles": [{"id": "D{}".format(index), "partition": "development" if index < 10 else "profile_holdout",
                      "parameters": {"Lg": {"value": 1.02, "unit": "baseline_multiplier"},
                                     "NA": {"value": 0.5, "unit": "baseline_multiplier"}}}
                     for index in range(13)],
        "radiations": [{"id": "G{}".format(index), "energy_MeV": index + 1,
                        "role": "development" if index < 8 else "radiation_holdout"}
                       for index in range(10)],
    }


def solved(run_id, **extra):
    return {
        "run_id": run_id, "state": "COLLECTED", "collection_verified": True,
        "remote_exit_code": 0, "collection_exit_code": 0, "tool_exit_codes": {"device": 0},
        "input_sha256": INPUT_HASH, "results_sha256": RESULT_HASH, **extra,
    }


class R06ProjectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.plan_path = Path(directory.name) / "plan.json"
        self.plan = r06_plan()

    def project(self, manifests=None, runtime=None, observation=None, work_items=None, progress=None):
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        return build_research(self.plan_path, manifests or {}, observation or {}, progress or [],
                              now=NOW, runtime=runtime, work_items=work_items)

    def row(self, block):
        return next(row for row in self.plan["cases"] if row["block"] == block)

    def test_frozen_budget_all_slots_include_z_and_no_qualified_statistics(self):
        result = self.project()
        self.assertEqual(result["revision"], "r0.6")
        self.assertEqual(result["totals"]["planned"], 396)
        self.assertEqual(result["totals"]["remaining"], 396)
        self.assertEqual(result["totals"]["accepted"], 0)
        self.assertEqual(result["budget"], {
            "total_cases": 396, "zero_cases": 26, "profile_count": 13, "radiation_count": 10,
            "statistics_intent_cases": 214, "statistics_eligible_cases": 0, "manifest_eligible_cases": 0,
        })
        self.assertEqual({key: value["planned"] for key, value in result["counts"].items()}, R06_BLOCKS)
        self.assertEqual(len(result["cases"]), 338)
        self.assertEqual(len(result["profiles"]), 13)
        self.assertEqual(len(result["radiations"]), 10)

    def test_runtime_admission_binds_without_work_item_case_id(self):
        identity = self.row("S")["case_id"]
        result = self.project(
            {"private-run": solved("private-run")},
            runtime={"intents": {"private-task": {"run_id": "private-run",
                       "scientific_admission": {"scope": "development_production", "case_id": identity}}}},
            work_items={"tasks": [{"id": "private-task"}]},
        )
        self.assertEqual(result["counts"]["S"]["solved"], 1)
        self.assertEqual(result["counts"]["S"]["accepted"], 0)
        self.assertEqual(result["totals"]["planned"], 396)
        self.assertNotIn("private-run", json.dumps(result))
        self.assertNotIn("private-task", json.dumps(result))

    def test_admission_overrides_old_work_item_and_manifest_identity(self):
        original = self.row("S")["case_id"]
        actual = self.row("R")["case_id"]
        result = self.project(
            {"private-run": solved("private-run", case_id=original)},
            runtime={"intents": {"task": {"run_id": "private-run",
                       "scientific_admission": {"case_id": actual}}}},
            work_items={"tasks": [{"id": "task", "case_id": original}]},
        )
        self.assertEqual(result["counts"]["S"]["solved"], 0)
        self.assertEqual(result["counts"]["R"]["solved"], 1)

    def test_admission_without_case_id_cannot_fall_back_to_legacy_or_explicit_run_tag(self):
        row = self.row("S")
        row["run_ids"] = ["pool-run"]
        result = self.project(
            {"pool-run": solved("pool-run", case_id=row["case_id"])},
            runtime={"intents": {"pool-task": {"run_id": "pool-run",
                       "scientific_admission": {"scope": "transport_pool"}}}},
            work_items={"tasks": [{"id": "pool-task", "case_id": row["case_id"]}]},
        )
        self.assertEqual(result["totals"]["solved"], 0)
        self.assertEqual(result["totals"]["accepted"], 0)

    def test_p0_never_fills_formal_slots_even_with_stale_case_tags(self):
        row = self.row("Z")
        row["run_ids"] = ["p0-run"]
        result = self.project(
            {"p0-run": solved("p0-run", case_id=row["case_id"])},
            runtime={"intents": {"p0-task": {"run_id": "p0-run", "scientific_admission": {
                "scope": "p0_diagnostic", "case_id": row["case_id"], "formal_case_id": None,
            }}}},
            work_items={"tasks": [{"id": "p0-task", "case_id": row["case_id"]}]},
        )
        self.assertEqual(result["totals"]["solved"], 0)
        self.assertEqual(result["totals"]["accepted"], 0)
        self.assertEqual(result["totals"]["planned"], 396)
        self.assertEqual(result["diagnostics"]["P0"]["solved"], 1)
        self.assertFalse(result["diagnostics"]["P0"]["included_in_formal_plan"])
        self.assertNotIn("accepted", result["diagnostics"]["P0"])

    def test_full_whr_p0_reuse_binds_only_the_matching_z_case(self):
        row = self.row("Z")
        run_id = "p0-full-whr"
        inputs = {"device.cmd": "4" * 64, "mesh/model.tdr": "5" * 64}
        manifests = {run_id: solved(run_id, input_sha256=inputs)}
        runtime = {"intents": {"p0-task": {"run_id": run_id, "scientific_admission": {
            "scope": "p0_diagnostic", "recipe_id": "zero_whr", "profile_id": "D0",
        }}}}
        proof = self.plan_path.parent / "z-reuse-proof.txt"
        proof.write_text("synthetic full-WHR reuse fixture", encoding="utf-8")
        reuse_path = self.plan_path.parent / "r06-gate/results/z-baseline-reuse" / (row["case_id"] + ".json")
        reuse_path.parent.mkdir(parents=True)
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        record = {
            "schema": "tcad-r06-z-baseline-reuse-v1", "status": "validated",
            "case_id": row["case_id"], "run_id": run_id, "recipe_id": "zero_whr",
            "profile_id": "D0", "stored_bit": 1,
            "plan_sha256": hashlib.sha256(self.plan_path.read_bytes()).hexdigest(),
            "run_kind": "full_whr_baseline", "is_prefix": False,
            "timing_contract": {
                "deck_timing_version": "r06-hold-window-v1",
                "hold_window_ns": [18.2, 30.0],
                "timing_sha256": "6" * 64,
            },
            "profile_qualification": {
                "status": "passed", "profile_id": "D0", "qualified_bits": [0, 1],
            },
            "input_sha256": inputs, "results_sha256": RESULT_HASH,
            "evidence": [{"path": "z-reuse-proof.txt",
                          "sha256": hashlib.sha256(proof.read_bytes()).hexdigest()}],
        }
        reuse_path.write_text(json.dumps(record), encoding="utf-8")
        result = self.project(manifests, runtime=runtime)
        self.assertEqual(result["diagnostics"]["P0"]["solved"], 1)
        self.assertEqual(result["counts"]["Z"]["solved"], 1)
        self.assertEqual(result["counts"]["Z"]["accepted"], 0)

        record["run_kind"] = "short_prefix"
        reuse_path.write_text(json.dumps(record), encoding="utf-8")
        result = self.project(manifests, runtime=runtime)
        self.assertEqual(result["diagnostics"]["P0"]["solved"], 1)
        self.assertEqual(result["counts"]["Z"]["solved"], 0)

    def test_current_p0_only_runtime_leaves_all_formal_cases_pending(self):
        runtime = {"intents": {
            "p0-one": {"run_id": "one", "scientific_admission": {"scope": "p0_diagnostic"}},
            "p0-two": {"run_id": "two", "scientific_admission": {"scope": "p0_diagnostic"}},
            "p0-three": {"scientific_admission": {"scope": "p0_diagnostic"}},
        }}
        result = self.project({"one": solved("one")}, runtime=runtime,
                              observation={"utc": NOW.isoformat(), "runs": [
                                  {"run_id": "two", "occupied": True, "status": "running"},
                              ]})
        self.assertEqual(result["diagnostics"]["P0"]["planned"], 3)
        self.assertEqual(result["diagnostics"]["P0"]["solved"], 1)
        self.assertEqual(result["diagnostics"]["P0"]["running"], 1)
        self.assertEqual(result["totals"]["running"], 0)
        self.assertEqual(result["totals"]["solved"], 0)
        self.assertTrue(all(row["state"] == "pending" for row in result["cases"]))

    def test_p0_occupancy_is_pending_and_confirmed_unlaunched_failure_is_not_archived(self):
        runtime = {"intents": {
            "pending-task": {"run_id": "pending-run", "scientific_admission": {"scope": "p0_diagnostic"}},
            "failed-task": {"run_id": "unlaunched-run", "scientific_admission": {"scope": "p0_diagnostic"}},
        }}
        result = self.project(runtime=runtime, observation={"utc": NOW.isoformat(), "runs": [
            {"run_id": "pending-run", "status": "reconciliation_pending", "occupied": True},
            {"run_id": "unlaunched-run", "status": "failed_unlaunched", "occupied": True,
             "terminal_reconciled": True},
        ]})
        self.assertEqual(result["diagnostics"]["P0"]["planned"], 2)
        self.assertEqual(result["diagnostics"]["P0"]["running"], 0)
        self.assertEqual(result["diagnostics"]["P0"]["failed"], 1)
        self.assertEqual(result["diagnostics"]["P0"]["archived"], 0)
        self.assertEqual(result["diagnostics"]["P0"]["solved"], 0)
        self.assertEqual(result["totals"]["planned"], 396)
        self.assertTrue(all(result["totals"][field] == 0 for field in ("archived", "solved", "failed", "accepted", "running")))

    def test_formal_unlaunched_failure_does_not_create_an_archive(self):
        row = self.row("Z")
        result = self.project(
            runtime={"intents": {"task": {"run_id": "unlaunched", "scientific_admission": {"case_id": row["case_id"]}}}},
            observation={"utc": NOW.isoformat(), "runs": [{
                "run_id": "unlaunched", "status": "failed_unlaunched", "terminal_reconciled": True,
            }]},
        )
        self.assertEqual(result["counts"]["Z"]["failed"], 1)
        self.assertEqual(result["counts"]["Z"]["archived"], 0)
        self.assertEqual(result["counts"]["Z"]["solved"], 0)
        self.assertEqual(result["totals"]["accepted"], 0)
        self.assertEqual(next(case for case in result["cases"] if case["case_id"] == row["case_id"])["state"], "failed")

    def test_zero_mapping_engineering_completion_requires_separate_acceptance(self):
        row = self.row("Z")
        runtime = {"intents": {"baseline": {"run_id": "baseline-run",
                   "scientific_admission": {"scope": "development_production", "case_id": row["case_id"]}}}}
        inputs = {"device.cmd": INPUT_HASH, "mesh.tdr": "3" * 64}
        manifests = {"baseline-run": solved("baseline-run", input_sha256=inputs)}
        result = self.project(manifests, runtime=runtime)
        self.assertEqual(result["counts"]["Z"]["solved"], 1)
        self.assertEqual(result["counts"]["Z"]["accepted"], 0)
        proof = self.plan_path.parent / "proof.txt"
        proof.write_text("synthetic test fixture only", encoding="utf-8")
        evidence = {"schema": "tcad-r06-case-acceptance-v1", "status": "accepted",
                    "case_id": row["case_id"], "run_id": "baseline-run",
                    "input_sha256": inputs, "results_sha256": RESULT_HASH,
                    "evidence": [{"path": "proof.txt", "sha256": hashlib.sha256(proof.read_bytes()).hexdigest()}]}
        external = self.plan_path.parent / "r06-gate/results/case-acceptance" / (row["case_id"] + ".json")
        external.parent.mkdir(parents=True)
        external.write_text(json.dumps(evidence), encoding="utf-8")
        result = self.project(manifests, runtime=runtime)
        self.assertEqual(result["counts"]["Z"]["accepted"], 1)
        evidence["results_sha256"] = "3" * 64
        external.write_text(json.dumps(evidence), encoding="utf-8")
        self.assertEqual(self.project(manifests, runtime=runtime)["counts"]["Z"]["accepted"], 0)

    def test_retries_preserve_denominator_and_require_original_collection_proof(self):
        row = self.row("S")
        row["run_ids"] = ["failed", "good", "unverified"]
        result = self.project({
            "failed": solved("failed", state="FAILED_COLLECTED", remote_exit_code=1),
            "good": solved("good"),
            "unverified": solved("unverified", collection_verified=False),
        })
        self.assertEqual(result["counts"]["S"]["solved"], 1)
        self.assertEqual(result["counts"]["S"]["planned"], 150)
        self.assertEqual(next(c for c in result["cases"] if c["case_id"] == row["case_id"])["attempts"], 3)
        row["run_ids"] = ["unverified"]
        self.assertEqual(self.project({"unverified": solved("unverified", tool_exit_codes={})})["totals"]["solved"], 0)

    def test_sealed_holdouts_publish_only_block_engineering_counts(self):
        row = self.row("HR")
        row["run_ids"] = ["sealed-run"]
        row["scientific_label"] = {"private_label": "flip", "voltage": 0.123456789}
        progress = [{"case_id": row["case_id"], "note": "private-holdout-note"},
                    {"case_id": "DEV-P000-C00-E777-B1", "note": "private-holdout-alias-note"}]
        result = self.project(
            {"sealed-run": solved("sealed-run", case_id=row["case_id"], private_path="/srv/private")},
            runtime={"intents": {"task": {"run_id": "sealed-run", "scientific_admission": {
                "scope": "holdout_evaluation", "case_id": row["case_id"],
            }}}},
            observation={"utc": NOW.isoformat(), "runs": [
                {"id": "r04-p000-c00-event777-b1", "run_id": "sealed-run"},
            ]}, progress=progress,
        )
        self.assertEqual(result["counts"]["HR"]["solved"], 1)
        self.assertTrue(next(block for block in result["blocks"] if block["id"] == "HR")["sealed"])
        serialized = json.dumps(result)
        for private in (row["case_id"], "private_label", "private-holdout-note", "private-holdout-alias-note",
                        "sealed-run", "/srv/private", "voltage"):
            self.assertNotIn(private, serialized)
        self.assertTrue(all(case["block"] not in {"HR", "HP"} for case in result["cases"]))

    def test_profile_and_radiation_holdout_parameters_remain_sealed(self):
        result = self.project()
        self.assertEqual(sum(profile["sealed"] for profile in result["profiles"]), 3)
        self.assertEqual(sum(radiation["sealed"] for radiation in result["radiations"]), 2)
        self.assertTrue(all(not item["parameters"] for item in result["profiles"] + result["radiations"] if item["sealed"]))
        self.assertEqual(result["profiles"][0]["parameters"]["Lg_relative"], 1.02)

    def test_progress_ids_allow_development_r06_and_benchmark_but_not_holdout_or_unknown(self):
        identity = self.row("S")["case_id"]
        progress = [{"case_id": identity}, {"case_id": self.row("HP")["case_id"]},
                    {"case_id": "r06-unknown-case"}, {"case_id": "BENCH-test"}]
        result = self.project(progress=progress)
        self.assertEqual([entry["case_id"] for entry in result["progress"]], [identity, "BENCH-test"])
        self.assertEqual(result["totals"]["accepted"], 0)

    def test_plan_cannot_grant_statistics_eligibility_or_expose_labels(self):
        row = self.row("S")
        row.update(statistics_eligible=True, scientific_label={"accepted_flip": 1})
        result = self.project()
        self.assertEqual(result["budget"]["statistics_eligible_cases"], 0)
        self.assertTrue(all(not item["statistics_eligible"] for item in result["cases"]))
        self.assertNotIn("scientific_label", json.dumps(result))
        self.assertEqual(result["statistics_basis"], "external_qualified_snapshot_required")

    def test_invalid_budget_or_duplicate_case_fails_closed(self):
        original = copy.deepcopy(self.plan)
        for mutate in (
            lambda value: value["cases"].pop(0),
            lambda value: value["cases"][0].update(case_id=value["cases"][1]["case_id"]),
            lambda value: value["profiles"].pop(),
            lambda value: value["radiations"].pop(),
            lambda value: value["cases"][30].update(statistics_intent=True),
        ):
            self.plan = copy.deepcopy(original)
            mutate(self.plan)
            with self.assertRaises(ValueError):
                self.project()

    def test_stale_running_snapshot_does_not_fill_formal_running_counts(self):
        identity = self.row("S")["case_id"]
        result = self.project(runtime={"intents": {"task": {"run_id": "run",
                              "scientific_admission": {"case_id": identity}}}},
                              observation={"utc": (NOW - dt.timedelta(seconds=181)).isoformat(),
                                           "runs": [{"run_id": "run", "occupied": True, "status": "running"}]})
        self.assertTrue(result["observation_stale"])
        self.assertEqual(result["totals"]["running"], 0)

    def test_benchmark_cannot_fill_formal_case_even_with_explicit_plan_mapping(self):
        row = self.row("S")
        row["run_ids"] = ["bench"]
        result = self.project({"bench": solved("bench", kind="performance_probe", case_id=row["case_id"])})
        self.assertEqual(result["totals"]["solved"], 0)

    def test_bad_runtime_admission_fails_closed(self):
        for runtime in ({"intents": []}, {"intents": {"bad": None}},
                        {"intents": {"bad": {"scientific_admission": []}}}):
            with self.subTest(runtime=runtime), self.assertRaises(ValueError):
                self.project(runtime=runtime)

    def test_actual_frozen_r06_manifest_read_only(self):
        path = Path(__file__).resolve().parents[2] / "tcad-research-training/plans/dram-se-ddr5-lpddr5/month-one-cases-r06.json"
        if not path.is_file():
            self.skipTest("local r0.6 plan is not present")
        result = build_research(path, {}, {}, [], now=NOW)
        self.assertEqual(result["totals"]["planned"], 396)
        self.assertEqual(result["budget"]["statistics_intent_cases"], 214)
        self.assertEqual(result["budget"]["statistics_eligible_cases"], 0)
        self.assertEqual(len(result["cases"]), 338)
        self.assertEqual(len(result["profiles"]), 13)
        self.assertEqual(len(result["radiations"]), 10)


if __name__ == "__main__":
    unittest.main()
