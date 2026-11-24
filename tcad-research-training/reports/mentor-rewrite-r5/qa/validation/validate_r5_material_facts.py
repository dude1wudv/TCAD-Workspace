from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
EXPECTED_DELIVERY_MANIFEST_SHA256 = "6736d751c7a5b9b1f1bcdaa897eaef29f4810600603fc31faa74bf2c57930c9e"
BASE = ROOT / "reports/final-r4"
COURSE = ROOT / "reports/mentor-rewrite-r5/materials/course-materials.tex"
BRIEF = ROOT / "reports/mentor-brief-r4/visual-v3/project-brief.tex"
OUT = ROOT / "reports/mentor-rewrite-r5/qa/validation"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def check(condition: bool, label: str, detail=None):
    checks.append({"check": label, "passed": bool(condition), "detail": detail})
    if not condition:
        failures.append(label)


checks: list[dict] = []
failures: list[str] = []
course = COURSE.read_text(encoding="utf-8")
brief = BRIEF.read_text(encoding="utf-8")
models = read_json(BASE / "data/frozen-models.json")
summary = read_json(BASE / "data/snapshot/summary.json")
failures_data = read_json(BASE / "data/snapshot/original-failures.json")
responses = read_csv(BASE / "data/snapshot/responses.csv")
scores = read_csv(BASE / "data/snapshot/prediction-scores.csv")
extensions = read_csv(BASE / "data/snapshot/extension-cases.csv")

manifest_path = BASE / "delivery-manifest.json"
manifest_sha = sha256(manifest_path)
manifest = read_json(manifest_path)
check(manifest_sha == EXPECTED_DELIVERY_MANIFEST_SHA256, "delivery_manifest_sha256", {"actual": manifest_sha, "expected": EXPECTED_DELIVERY_MANIFEST_SHA256})
preservation = manifest.get("scientific_input_preserved", {})
check(preservation == {"independent_events": 64, "main_responses": 128, "frozen_test_predictions": 64, "historical_failed_rows": 7, "main_response_aliases": 4, "unknown_original_exit_codes_preserved": True}, "delivery_manifest_scientific_input_preserved", preservation)
check(manifest.get("new_solver_calls") == 0, "delivery_manifest_no_new_solver_calls", manifest.get("new_solver_calls"))

# Targeted byte-binding audit: all snapshot data files and the final package's
# science/source figures, as listed in the old final-r4 delivery manifest.
bound_hashes = manifest["files_sha256"]
selected = [k for k in bound_hashes if k.startswith("data/snapshot/") or (k.startswith("figures/") and Path(k).suffix.lower() in {".png", ".pdf", ".svg"})]
hash_evidence = []
for rel in sorted(selected):
    p = BASE / Path(rel)
    actual = sha256(p) if p.is_file() else None
    expected = bound_hashes[rel]
    hash_evidence.append({"path": rel, "expected_sha256": expected, "actual_sha256": actual, "matches": actual == expected})
check(bool(selected) and all(x["matches"] for x in hash_evidence), "targeted_snapshot_and_figure_hashes", {"checked_count": len(selected), "mismatches": [x["path"] for x in hash_evidence if not x["matches"]]})
snapshot_manifest = read_json(BASE / "data/snapshot/snapshot-manifest.json")
check(manifest.get("snapshot_manifest_sha256") == sha256(BASE / "data/snapshot/snapshot-manifest.json"), "delivery_snapshot_manifest_binding", {"delivery": manifest.get("snapshot_manifest_sha256"), "actual": sha256(BASE / "data/snapshot/snapshot-manifest.json")})

# Independent response/event structure and course-level counts.
event_labels = {r["event_label"] for r in responses}
paired = all({x["stored_bit"] for x in responses if x["event_label"] == label} == {"0", "1"} for label in event_labels)
check(len(event_labels) == 64 and len(responses) == 128 and paired, "64_independent_events_128_paired_responses", {"events": len(event_labels), "responses": len(responses), "all_events_have_both_bits": paired})
check(summary.get("planned_independent_events") == 64 and summary.get("planned_main_responses") == 128 and summary.get("measured_main_responses") == 128 and summary.get("events_with_both_measured_responses") == 64, "snapshot_event_response_counts", {k: summary.get(k) for k in ["planned_independent_events", "planned_main_responses", "measured_main_responses", "events_with_both_measured_responses"]})
counts = summary["main_threshold_counts"]
expected_counts = {"correct": 96, "criterion_error": 20, "critical": 8, "numerically_uncertain": 4}
check(all(counts.get(k) == v for k, v in expected_counts.items()), "snapshot_5mV_classification_counts", {k: counts.get(k) for k in expected_counts})
for value in ("96", "20", "8", "4"):
    check(value in brief, f"brief_contains_threshold_count_{value}")

# Training design is read from the frozen model record, independently of prose.
configuration = models["configuration"]
model_records = models["models"]
expected_features = ["Qdep_fC", "Qdep_fC/L_um", "Qdep_fC*sin(theta)"]
check(models.get("train_paired_responses") == 64 and models.get("train_independent_events") == 32, "frozen_model_training_event_response_counts", {"events": models.get("train_independent_events"), "responses": models.get("train_paired_responses")})
check(configuration.get("train_lengths_um") == [0.18, 0.35] and configuration.get("holdout_lengths_um") == [0.25] and configuration.get("extrapolation_lengths_um") == [0.45], "frozen_model_split_lengths", {k: configuration.get(k) for k in ["train_lengths_um", "holdout_lengths_um", "extrapolation_lengths_um"]})
check(models.get("feature_names") == expected_features and configuration.get("features") == expected_features, "frozen_model_features", models.get("feature_names"))
check(len(model_records) == 4 and all(m.get("training_response_n") == 32 and m.get("ridge", {}).get("training_n") == 32 and m.get("selected_alpha") == 0.1 and m.get("ridge", {}).get("alpha") == 0.1 for m in model_records.values()), "four_models_32_each_lambda_0_1", {k: {"n": v.get("training_response_n"), "alpha": v.get("selected_alpha")} for k, v in model_records.items()})
fold_evidence = {}
fold_ok = True
for model_name, record in model_records.items():
    folds = record.get("cv_folds", [])
    details = [(len(f.get("training_event_labels", [])), len(f.get("validation_event_labels", []))) for f in folds]
    fold_evidence[model_name] = details
    fold_ok = fold_ok and len(folds) == 8 and all(a == 28 and b == 4 for a, b in details)
check(fold_ok, "eight_grouped_cv_folds_each_28_train_4_validation", fold_evidence)
check("8组" in course and "28条" in course and "4条" in course and "8轮" in course, "course_cv_prose_8_folds_28_plus_4")
check("64次响应" in course and "每个模型使用32条" in course and "4个模型" in course, "course_training_prose_counts")
check("岭回归" in brief and "4个模型" in brief and "64次仿真响应" in brief and "64条预测" in brief, "brief_training_prose_counts")
for feature_text in (r"Q_{\mathrm{dep}}", r"Q_{\mathrm{dep}}/L", r"Q_{\mathrm{dep}}\sin\theta"):
    check(feature_text in course, "course_feature_" + feature_text, feature_text)
check("0.1" in course and "0.1" in brief, "lambda_0_1_present_in_both_materials")

# Eight test RMSE values are independently regenerated from the score CSV and
# compared with both displayed tables (four per target, two test lengths).
ridge_rows = [r for r in scores if r["model"] == "ridge"]
display_expected = {}
for r in ridge_rows:
    key = (r["target"], r["stored_bit"], r["split"])
    display_expected[key] = f'{float(r["RMSE"]):.4f}'
test_keys = [k for k in display_expected if k[2] in {"holdout", "extrapolation"}]
check(len(test_keys) == 8, "eight_ridge_test_rmse_source_rows", {"count": len(test_keys), "values": {"/".join(k): display_expected[k] for k in sorted(test_keys)}})
rmse_tokens = [display_expected[k] for k in sorted(test_keys)]
check(all(token in course and token in brief for token in rmse_tokens), "eight_rmse_values_match_both_tables", rmse_tokens)

# Extension scope, with boundary event aliases normalized to their physical
# response identity; variant reruns do not become new independent objects.
oxide_rows = [r for r in extensions if r["stage"] == "oxide"]
boundary_rows = [r for r in extensions if r["stage"] == "boundary" and r["role"] == "event"]
boundary_objects = set()
for r in boundary_rows:
    tag = r["tag"]
    tag = re.sub(r"-s(?:0p5-m1|1-m0p7)$", "", tag)
    boundary_objects.add(tag)
check(len(oxide_rows) == 14, "fourteen_oxide_extension_rows", len(oxide_rows))
check(len(boundary_objects) == 2, "two_boundary_response_objects", sorted(boundary_objects))
check("14" in course and "氧化层" in course and "2个" in course and "边界" in course, "course_extension_counts")
check("14" in brief and "氧化层" in brief and "2" in brief and "边界响应" in brief, "brief_extension_counts")

# The demonstration section is framed as an agenda, not fabricated student
# activity; original unknown exit codes remain null in the bound source record.
demo = course[course.index(r"\titleline{作品演示安排}"):course.index(r"\newpage", course.index(r"\titleline{作品演示安排}"))]
check("安排" in demo and "演示顺序" in demo and "现场演示的安排" in course, "student_demo_is_future_agenda")
aliases = failures_data["alias_originals"]
alias_status = {k: (v.get("state"), v.get("runner_exit_code")) for k, v in aliases.items()}
check(len(aliases) == 4 and all(state == "FAILED" and code is None for state, code in alias_status.values()), "four_original_aliases_still_failed_with_null_codes", alias_status)
check("null（未观测）" in (BASE / "tables/failed-aliases.tex").read_text(encoding="utf-8"), "original_unknown_code_not_replaced_in_table")

result = {
    "schema": "mentor-rewrite-r5-material-fact-validation-v1",
    "status": "PASS" if not failures else "FAIL",
    "inputs": {
        "course_tex": {"path": str(COURSE.relative_to(ROOT)), "sha256": sha256(COURSE)},
        "brief_tex": {"path": str(BRIEF.relative_to(ROOT)), "sha256": sha256(BRIEF)},
        "delivery_manifest_sha256": manifest_sha,
        "frozen_models_sha256": sha256(BASE / "data/frozen-models.json"),
        "snapshot_manifest_sha256": sha256(BASE / "data/snapshot/snapshot-manifest.json"),
        "bound_scientific_data_and_figures_checked": len(hash_evidence),
    },
    "checks": checks,
    "failures": failures,
    "hash_evidence": hash_evidence,
    "limits": [
        "No simulation, solver, model fitting, compilation, or visual inspection was performed.",
        "The root agent owns all page-by-page visual review.",
        "This is a targeted audit of the two named TeX sources and manifest-bound snapshot science inputs/figures; it is not a re-audit of original archives or the complete package.",
    ],
}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "material-fact-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": result["status"], "check_count": len(checks), "failure_count": len(failures), "failures": failures, "manifest_sha256": manifest_sha, "bound_science_files_checked": len(hash_evidence), "output": str((OUT / 'material-fact-validation.json').relative_to(ROOT))}, ensure_ascii=False, indent=2))
raise SystemExit(1 if failures else 0)
