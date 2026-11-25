"""Prepare a fixed, read-only-derived writing evidence package and data plots.

Run with the existing analysis Python. The first successful capture preserves
the current ledger bytes once. Later runs reuse only the saved source copies;
they do not refresh progress, dispatch solvers, or import experiment runners.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np


OUT = Path(__file__).resolve().parent
ROOT = OUT.parent.parent
DATA = OUT / "data"
FIGURES = OUT / "figures"
TABLES = OUT / "tables"
SNAPSHOTS = DATA / "source-snapshots"
SOURCE_MAP = DATA / "source-map.json"
PRED = "experiments/dram-see-v3/r50-main/data/predictions/"
REF = "experiments/dram-see-v3/r50-main/data/delivery/20261010T2022Z-references/"
PROBE = "experiments/dram-see-v3/data/diagnostics/precharge-r50-r1/"
UTC8 = timezone(timedelta(hours=-8))
COLORS = ["#176A8B", "#CA7A20", "#237B5A", "#92568D"]
SOURCE_RECORDS: dict[str, dict] = {}
FIGURE_RECORDS: list[dict] = []


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def csv_write(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    assert rows or fields, "CSV columns must be explicit when empty"
    fields = fields or list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def source(path: str, name: str, category: str, version: str, use: str,
           can_write: str, cannot_write: str) -> bytes:
    """Capture only explicitly named nonsecret sources; reuse their bytes later."""
    saved = SNAPSHOTS / name
    if path in SOURCE_RECORDS:
        record = SOURCE_RECORDS[path]
        blob = (ROOT / record["copy_path"]).read_bytes()
        if sha(blob) != record["sha256"]:
            raise ValueError(f"Saved source hash changed: {path}")
        return blob
    if saved.exists():
        raise ValueError(f"Unregistered source copy exists: {saved}")
    source_path = ROOT / path
    blob = source_path.read_bytes()
    saved.write_bytes(blob)
    SOURCE_RECORDS[path] = {
        "source_path": path, "absolute_source_path": str(source_path),
        "copy_path": rel(saved), "sha256": sha(blob), "bytes": len(blob),
        "category": category, "version": version, "use": use,
        "evidence_type": "immutable_input",
        "can_write": can_write, "cannot_write": cannot_write,
    }
    # Persist after each successful capture, so interrupted preparation never
    # silently replaces a source with a later live version.
    dump(SOURCE_MAP, SOURCE_RECORDS)
    return blob


def jsource(path: str, name: str, category: str, version: str, use: str,
            can_write: str, cannot_write: str):
    return json.loads(source(path, name, category, version, use, can_write, cannot_write))


def csv_source(path: str, name: str, category: str, version: str, use: str,
               can_write: str, cannot_write: str) -> list[dict]:
    blob = source(path, name, category, version, use, can_write, cannot_write)
    return list(csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))))


def capture_ledger() -> tuple[dict, dict]:
    metadata_path = DATA / "snapshot-metadata.json"
    ledger_path = DATA / "ledger-snapshot.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        blob = ledger_path.read_bytes()
        assert sha(blob) == metadata["ledger_sha256"]
    else:
        if ledger_path.exists():
            raise ValueError("Ledger copy exists without capture metadata; do not overwrite it")
        live_path = ROOT / "local_runtime/dram-see-v3/ledger.json"
        before = datetime.now(timezone.utc)
        blob = live_path.read_bytes()  # Exactly one read of the live ledger.
        captured = datetime.now(timezone.utc)
        json.loads(blob)  # Reject a partial write without creating a snapshot.
        ledger_path.write_bytes(blob)
        metadata = {
            "schema": "dram-final-writing-ledger-snapshot-v1",
            "read_started_utc": before.isoformat(), "captured_utc": captured.isoformat(),
            "captured_user_utc_minus_8": captured.astimezone(UTC8).isoformat(),
            "source_path": rel(live_path), "ledger_sha256": sha(blob), "bytes": len(blob),
            "scope": "One local ledger byte snapshot for manuscript status; not a live-process or remote-job check",
            "remote_or_process_check_performed": False,
            "evidence_type": "live_observation",
            "verification_target": "Saved ledger-snapshot.json only; the live ledger may continue changing",
            "snapshot_is_complete_experiment": False,
        }
        dump(metadata_path, metadata)
    return json.loads(blob), metadata


def style() -> dict:
    candidates = ["Microsoft YaHei", "Noto Sans CJK SC", "SimHei"]
    fonts = {font.name: font.fname for font in font_manager.fontManager.ttflist}
    chosen = next((name for name in candidates if name in fonts), "DejaVu Sans")
    plt.rcParams.update({
        "font.family": chosen, "font.size": 8.4, "axes.titlesize": 9.1,
        "axes.labelsize": 8.3, "xtick.labelsize": 7.6, "ytick.labelsize": 7.6,
        "legend.fontsize": 7.3, "figure.facecolor": "white", "axes.facecolor": "white",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.unicode_minus": False, "pdf.fonttype": 42, "ps.fonttype": 42,
        "savefig.facecolor": "white", "savefig.dpi": 320,
    })
    return {"font": chosen, "font_path": fonts.get(chosen), "matplotlib": matplotlib.__version__, "numpy": np.__version__}


def save_figure(fig, name: str, title: str, source_paths: list[str], data_files: list[str],
                scope: str, metadata: dict, details: dict | None = None) -> None:
    created = datetime.fromisoformat(metadata["captured_utc"])
    png, pdf = FIGURES / f"{name}.png", FIGURES / f"{name}.pdf"
    fig.savefig(png, dpi=320, metadata={"Software": "prepare_evidence.py; scientific data plot"})
    fig.savefig(pdf, metadata={"Title": title, "Author": "DRAM SEE evidence package",
                              "Subject": scope, "CreationDate": created, "ModDate": created})
    plt.close(fig)
    entry = {
        "schema": "dram-final-data-figure-v1", "name": name, "title": title,
        "kind": "scientific_data_plot", "not_native_visual_export": True,
        "not_gui_screenshot": True, "scope": scope,
        "source_files": [{"path": p, "sha256": SOURCE_RECORDS[p]["sha256"]} for p in source_paths],
        "data_files": [{"path": f"data/{f}", "sha256": sha((DATA / f).read_bytes())} for f in data_files],
        "outputs": [{"path": f"figures/{p.name}", "sha256": sha(p.read_bytes())} for p in [png, pdf]],
        "script_sha256": sha(Path(__file__).read_bytes()), "visual_review": "PENDING_ROOT_IMAGE_INSPECTION",
        "raw_archives_reaudited_this_generation": False, "details": details or {},
    }
    dump(FIGURES / f"{name}.sources.json", entry)
    FIGURE_RECORDS.append(entry)


def make_tables(evidence: dict) -> None:
    local = datetime.fromisoformat(evidence["snapshot"]["captured_user_utc_minus_8"])
    date = local.strftime("%Y-%m-%d %H:%M") + r"\,UTC$-08{:}00$"
    counts = evidence["progress"]["logical_counts"]
    macros = {
        "EvidenceDate": date, "TrainVerified": counts["train"]["VERIFIED"],
        "HoldoutVerified": counts["holdout"]["VERIFIED"], "HoldoutRunning": counts["holdout"]["RUNNING"],
        "HoldoutMissing": counts["holdout"]["UNSUBMITTED"],
        "ExtrapVerified": counts["extrapolation"]["VERIFIED"], "ExtrapRunning": counts["extrapolation"]["RUNNING"],
        "ExtrapMissing": counts["extrapolation"]["UNSUBMITTED"],
    }
    (TABLES / "snapshot.tex").write_text("% Fixed local-ledger snapshot; do not interpret RUNNING as a live process check.\n" +
        "\n".join("\\newcommand{\\" + k + "}{" + str(v) + "}" for k, v in macros.items()) + "\n", encoding="utf-8")
    lines = [r"\begin{tabular}{llrrrr}", r"\toprule", r"阶段 & 栅长 / $\mu$m & 计划响应 & 已验证 & 在途 & 待提交 \\", r"\midrule"]
    for split, name, lengths in [("train", "训练", "0.18 / 0.35"), ("holdout", "域内留出", "0.25"), ("extrapolation", "域外外推", "0.45")]:
        c = counts[split]
        lines.append(f"{name} & {lengths} & {c['planned']} & {c['VERIFIED']} & {c['RUNNING']} & {c['UNSUBMITTED']} " + r"\\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    (TABLES / "progress.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    lines = [r"\begin{tabular}{clrr}", r"\toprule", r"存储位 & 目标（单位） & 岭回归 RMSE & 均值基准 RMSE \\", r"\midrule"]
    for row in evidence["training"]["cv"]:
        target = r"$\Delta Q$ (fC)" if row["target"] == "deltaQ_fC" else r"$\Delta M$ (mV)"
        lines.append(f"{row['stored_bit']} & {target} & {row['ridge_cv_rmse']:.6f} & {row['baseline_cv_rmse']:.6f} " + r"\\")
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    (TABLES / "training-cv.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot_d1(rows: list[dict], metadata: dict) -> list[dict]:
    alpha = next(row for row in rows if row["tag"] == "rodiag1-alpha-match")
    physical = next(row for row in rows if row["tag"] == "rodiag1-matched-ref-r3")
    assert alpha["state"] == physical["state"] == "VERIFIED"
    points = [
        {"reference": "Fixed 0.5 V reference", "D_mV": float(alpha["D_mV"]), "run_id": alpha["run_id"], "scope": "D1 historical diagnostic"},
        {"reference": "Offline matched neutral", "D_mV": float(alpha["offline_center_BL_reference_D_mV"]), "run_id": alpha["run_id"], "scope": "D1 historical diagnostic"},
        {"reference": "Physical matched branch", "D_mV": float(physical["D_mV"]), "run_id": physical["run_id"], "scope": "D1 historical diagnostic"},
    ]
    csv_write(DATA / "d1-reference-comparison.csv", points)
    fig, ax = plt.subplots(figsize=(5.83, 2.9))
    bars = ax.bar(range(3), [p["D_mV"] for p in points], width=.57, color=[COLORS[1], COLORS[0], COLORS[2]])
    ax.axhline(0, color="#303840", lw=.8)
    for y in [-5, 5]: ax.axhline(y, color="#A2ABB1", ls="--", lw=.8)
    ax.set_xticks(range(3), ["Fixed 0.5 V", "Matched neutral\n(offline)", "Matched branch\n(physical)"])
    ax.set_ylabel("D at 4 ns / mV")
    ax.set_title("D1: reference choice changes the readout difference", pad=12)
    ax.set_ylim(-13, 7.5)
    for bar, point in zip(bars, points):
        v = point["D_mV"]
        ax.text(bar.get_x() + bar.get_width()/2, v + (.45 if v >= 0 else -.55), f"{v:+.6f}", ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
    ax.text(.99, .97, "Dashed lines: ±5 mV\nHistorical D1; not R50-main", transform=ax.transAxes, va="top", ha="right", fontsize=7.4, color="#505B62", bbox={"facecolor": "white", "edgecolor": "none", "pad": 2.0})
    fig.subplots_adjust(left=.12, right=.98, bottom=.22, top=.85)
    save_figure(fig, "d1-reference-comparison", "D1 reference comparison", ["experiments/dram-readout-offset-d1/data/summary.csv"], ["d1-reference-comparison.csv"], "Historical D1 reference diagnostic; no R50-main sample", metadata, {"observations": points})
    return points


def plot_probe(rows: list[dict], metadata: dict) -> list[dict]:
    points = [{**row, "signed_error_uV": float(row["BL_error_uV"]), "absolute_error_uV": abs(float(row["BL_error_uV"]))} for row in rows if row["role"] == "event"]
    points.sort(key=lambda row: 0 if row["model"] == "R100" else 1)
    assert len(points) == 2 and points[0]["complete_raw_audit_state"] == "FAILED"
    csv_write(DATA / "r50-precharge.csv", points)
    fig, ax = plt.subplots(figsize=(5.83, 2.85))
    ax.bar([0, 1], [row["absolute_error_uV"] for row in points], width=.52, color=[COLORS[1], COLORS[2]])
    ax.axhline(10, color="#A84036", ls="--", lw=1.2)
    ax.text(.97, 10.35, "Unchanged tolerance: 10 µV", transform=ax.get_yaxis_transform(), ha="right", color="#A84036", fontsize=7.6)
    ax.set_xticks([0, 1], ["100 Ω: FAILED\nhistorical diagnostic", "50 Ω: PASSED\nindependent probe"])
    ax.set_ylim(0, 16)
    ax.set_ylabel("Absolute BL precharge error at 3 ns / µV")
    ax.set_title("One fixed event: precharge-circuit revision", pad=12)
    for i, row in enumerate(points): ax.text(i, row["absolute_error_uV"] + .35, f"{row['absolute_error_uV']:.6f}", ha="center", fontsize=8.2)
    fig.subplots_adjust(left=.14, right=.98, bottom=.24, top=.85)
    save_figure(fig, "r50-precharge", "R100 to R50 independent probe", [PROBE + "precharge-checks.csv"], ["r50-precharge.csv"], "Same event and unchanged tolerance; R100 remains FAILED; R50 probe excluded from main matrix", metadata, {"signed_values_preserved": True})
    return points


def plot_training(train: list[dict], metadata: dict) -> list[dict]:
    rows = []
    for row in train:
        raw = row["classification"]["0.005"]
        uncertain = row["classification_numerically_uncertain_thresholds_mV"]
        rows.append({
            "event_label": row["event_label"], "seed": row["seed"], "condition_id": row["condition_id"],
            "replicate": row["replicate"], "gate_length_um": row["gate_length_um"], "particle": row["particle"],
            "angle_deg": row["angle_deg"], "stored_bit": row["stored_bit"], "split": row["split"],
            "Qdep_fC": row["Qdep_fC"], "deltaQ_fC": row["targets"]["deltaQ_fC"], "deltaM_mV": row["targets"]["deltaM_mV"],
            "raw_classification_5mV": raw,
            "effective_classification_5mV": "numerically_uncertain" if 5.0 in uncertain else raw,
            "uncertain_thresholds_mV": json.dumps(uncertain), "continuous_valid": row["continuous_valid"],
            "signal_run_id": row["sources"]["signal"]["run_id"],
            "signal_archive_sha256": row["sources"]["signal"]["archive_sha256"],
        })
    assert len(rows) == 64 and {r["gate_length_um"] for r in rows} == {.18, .35}
    assert len({r["event_label"] for r in rows}) == 32 and all(r["continuous_valid"] for r in rows)
    csv_write(DATA / "r50-training-responses.csv", rows)
    fig, axes = plt.subplots(2, 2, figsize=(5.83, 4.65), sharex=True)
    groups = [("alpha", 0), ("alpha", 30), ("proton", 0), ("proton", 30)]
    for column, bit in enumerate([0, 1]):
        for row_index, (target, unit, symbol) in enumerate([("deltaQ_fC", "fC", "ΔQ"), ("deltaM_mV", "mV", "ΔM")]):
            ax = axes[row_index, column]
            for group_index, (particle, angle) in enumerate(groups):
                for length, marker in [(.18, "o"), (.35, "s")]:
                    subset = [r for r in rows if (r["stored_bit"], r["particle"], r["angle_deg"], r["gate_length_um"]) == (bit, particle, angle, length)]
                    assert len(subset) == 4
                    ax.scatter([r["Qdep_fC"] for r in subset], [r[target] for r in subset], s=22, marker=marker,
                               facecolors="none" if length == .35 else COLORS[group_index], edgecolors=COLORS[group_index], linewidths=.8, alpha=.9)
            ax.axhline(0, lw=.6, color="#CCD1D3")
            ax.grid(axis="y", color="#E9EDEF", linewidth=.5)
            ax.set_ylabel(f"{symbol} / {unit}")
            if row_index == 0: ax.set_title(f"Stored bit {bit}")
            else: ax.set_xlabel("Geant4 Qdep / fC")
    handles = [plt.Line2D([], [], marker="o", ls="", color=COLORS[i], label=f"{p}, {a}°", markersize=4.5) for i, (p, a) in enumerate(groups)]
    handles += [plt.Line2D([], [], marker="o", ls="", color="#435058", label="L = 0.18 µm", markersize=4.5),
                plt.Line2D([], [], marker="s", ls="", color="#435058", markerfacecolor="none", label="L = 0.35 µm", markersize=4.5)]
    fig.suptitle("R50 frozen training data: all 32 events / 64 paired responses", fontsize=9.2, y=.98)
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.53, .012), ncol=3, frameon=False, columnspacing=1.2)
    fig.subplots_adjust(left=.12, right=.98, top=.87, bottom=.23, wspace=.39, hspace=.36)
    save_figure(fig, "r50-training-response", "R50 training response points", [PRED + "training-data.json", PRED + "freeze.json"], ["r50-training-responses.csv"], "All frozen training observations only; no .25/.45 um target values; no fitted or synthetic points", metadata, {"rows": 64, "independent_events": 32, "observations_each_metric": 64, "gate_lengths_um": [.18, .35], "no_jitter_or_point_omission": True})
    return rows


def plot_cv(models: dict, metadata: dict) -> list[dict]:
    rows = []
    for key, model in models["models"].items():
        chosen = next(score for score in model["cv_alpha_scores"] if score["alpha"] == model["selected_alpha"])
        rows.append({"model": key, "stored_bit": model["stored_bit"], "target": model["target"],
                     "unit": "fC" if model["target"] == "deltaQ_fC" else "mV", "selected_alpha": model["selected_alpha"],
                     "ridge_cv_rmse": chosen["mean_fold_rmse"], "baseline_cv_rmse": model["training_mean"]["cv_mean_fold_rmse"],
                     "training_responses_per_model": model["training_response_n"], "folds": len(model["cv_folds"]),
                     "scope": "Mean of training LOCO fold RMSE; not independent holdout or extrapolation test"})
    csv_write(DATA / "r50-training-cv.csv", rows)
    fig, axes = plt.subplots(1, 2, figsize=(5.83, 3.15))
    for ax, target, unit, label in zip(axes, ["deltaQ_fC", "deltaM_mV"], ["fC", "mV"], ["ΔQ", "ΔM"]):
        subset = sorted([r for r in rows if r["target"] == target], key=lambda r: r["stored_bit"])
        x, width = np.arange(2), .33
        for offset, key, color, name in [(-width/2, "ridge_cv_rmse", COLORS[0], "Ridge"), (width/2, "baseline_cv_rmse", COLORS[1], "Training mean")]:
            vals = [r[key] for r in subset]
            ax.bar(x+offset, vals, width=width, color=color, label=name)
            for xx, val in zip(x+offset, vals): ax.text(xx, val+max(r["baseline_cv_rmse"] for r in subset)*.025, f"{val:.3f}", ha="center", fontsize=7.1)
        ax.set_xticks(x, ["Bit 0", "Bit 1"])
        ax.set_title(label + " prediction")
        ax.set_ylabel("Mean fold RMSE / " + unit)
        ax.set_ylim(0, max(r["baseline_cv_rmse"] for r in subset)*1.22)
        ax.grid(axis="y", color="#E9EDEF", linewidth=.5)
        ax.set_axisbelow(True)
    fig.suptitle("Training cross-validation (8 physical-condition LOCO folds)", fontsize=9.1, y=.98)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(.5, .01))
    fig.subplots_adjust(left=.11, right=.98, top=.79, bottom=.22, wspace=.39)
    save_figure(fig, "r50-training-cv", "Training LOCO cross-validation", [PRED + "models.json", PRED + "freeze.json"], ["r50-training-cv.csv"], "Training model-selection evidence only; independent test metrics remain unreported", metadata, {"folds": 8, "alpha_candidates": [0, .01, .1, 1, 10], "selected_alphas": [r["selected_alpha"] for r in rows]})
    return rows


def plot_reference(summary: dict, metadata: dict) -> list[dict]:
    rows, curve_rows = [], []
    curves = list(summary["curves"].values())
    assert len(curves) == 12 and summary["physical_revision"] == "r50-main-r1"
    for curve in curves:
        p = curve["parameters"]
        assert p["charge_pc"] == 0.0 and p["oxide_nm"] == 5.0
        audit = summary["audited_runs"][curve["run_id"]]
        assert audit["audit_status"] == "R50_MAIN_NUMERICAL_CONTRACT_PASSED"
        rows.append({"gate_length_um": p["gate_length_um"], "role": "neutral" if p["neutral"] else f"bit{p['stored_bit']}",
                     "target_SN_V": p["target_voltage_V"], "initial_SN_V": audit["initial_SN_V"],
                     "initial_error_V": audit["initial_error_V"], "final_BL_V": audit["final_BL_V"],
                     "run_id": curve["run_id"], "archive_sha256": curve["archive_sha256"],
                     "scope": "R50 unirradiated baseline / neutral reference"})
        for point in curve["points"]:
            curve_rows.append({"run_id": curve["run_id"], "gate_length_um": p["gate_length_um"],
                               "role": "neutral" if p["neutral"] else f"bit{p['stored_bit']}", **point})
    rows.sort(key=lambda r: (r["gate_length_um"], r["target_SN_V"]))
    csv_write(DATA / "r50-reference-baselines.csv", rows)
    csv_write(DATA / "r50-reference-curves.csv", curve_rows)
    fig, axes = plt.subplots(1, 2, figsize=(5.83, 3.1))
    labels = {"bit0": "Stored 0", "neutral": "Neutral", "bit1": "Stored 1"}
    for role, color, marker in [("bit0", COLORS[0], "o"), ("neutral", "#7C858B", "^"), ("bit1", COLORS[2], "s")]:
        subset = [r for r in rows if r["role"] == role]
        axes[0].plot([r["gate_length_um"] for r in subset], [r["initial_SN_V"] for r in subset], ls="", marker=marker, color=color, markersize=4.5, label=labels[role])
        c = next(c for c in curves if c["parameters"]["gate_length_um"] == .18 and ("neutral" if c["parameters"]["neutral"] else f"bit{c['parameters']['stored_bit']}") == role)
        points = [p for p in c["points"] if p["time_ns"] >= 3.0]
        axes[1].plot([p["time_ns"] for p in points], [p["BL_V"] for p in points], color=color, lw=1.2, label=labels[role])
    axes[0].set_xlabel("Gate length / µm")
    axes[0].set_ylabel("Prestrike storage-node voltage / V")
    axes[0].set_xticks([.18, .25, .35, .45])
    axes[0].set_ylim(0, 1)
    axes[0].set_title("Controlled initial states")
    axes[1].set_xlabel("Time / ns")
    axes[1].set_ylabel("Bitline voltage / V")
    axes[1].set_xlim(3, 4)
    axes[1].set_title("Unirradiated readout, L = 0.18 µm", fontsize=8.1)
    for ax in axes: ax.grid(color="#E9EDEF", lw=.5)
    handles, labels_ = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels_, ncol=3, frameon=False, loc="lower center", bbox_to_anchor=(.52, .01))
    fig.suptitle("R50 reference validation: no particle excitation", fontsize=9.1, y=.98)
    fig.subplots_adjust(left=.11, right=.98, top=.79, bottom=.24, wspace=.47)
    save_figure(fig, "r50-reference", "R50 unirradiated reference", [REF + "summary.json", "experiments/dram-see-v3/r50-main/data/delivery-reviews/20261010T2022Z-references.md"], ["r50-reference-baselines.csv", "r50-reference-curves.csv"], "Previously reviewed reference snapshot; baseline-only observations, not particle results; right panel uses L=.18 um", metadata,
                {"reference_snapshot_utc": summary["generated_utc"], "curves": 12, "initial_states": 12, "display_thinning": "Inherited audited snapshot points; phase boundaries and full 3.8-4 ns retained"})
    return rows


def main() -> None:
    for directory in [DATA, FIGURES, TABLES, SNAPSHOTS]: directory.mkdir(parents=True, exist_ok=True)
    if SOURCE_MAP.exists(): SOURCE_RECORDS.update(json.loads(SOURCE_MAP.read_text(encoding="utf-8")))
    ledger, capture = capture_ledger()
    boundary = "No commercial DRAM reliability, calibrated bit-flip probability, or radiation cross section"
    design = jsource("experiments/dram-see-v3/r50-main/design.json", "r50-design.json", "model", "r50-main-r1", "Frozen matrix and scientific contract", "Planned 64 independent events / 128 paired responses and model assumptions", boundary)
    freeze = jsource(PRED + "freeze.json", "prediction-freeze.json", "validation", "r50-main-r1, 2026-10-11 prediction freeze", "Pre-test model/prediction freeze", "32 training events / 64 responses and 64 frozen test predictions", "No completed independent prediction validation from freeze alone")
    checksum = source(PRED + "freeze.sha256", "prediction-freeze.sha256", "validation", "r50-main-r1", "Freeze checksum", "Freeze integrity", "Not a new raw simulation audit").decode().strip()
    assert sha((SNAPSHOTS / "prediction-freeze.json").read_bytes()) == checksum
    frozen_data = {}
    frozen_checks = []
    for name in ["models.json", "training-data.json", "test-inputs.json", "predictions.json", "ledger-snapshot.json", "provenance.json"]:
        blob = source(PRED + name, "frozen-" + name, "prediction", "r50-main-r1 prediction freeze", "Frozen model/training/test-input evidence", "Frozen training and pre-test predictions", "No unseen test/extrapolation score")
        expected = freeze["files_sha256"][PRED + name]
        assert sha(blob) == expected, f"Freeze-bound file mismatch: {name}"
        frozen_checks.append({"path": PRED+name, "expected_sha256": expected, "actual_sha256": sha(blob), "matched": True})
        frozen_data[name] = json.loads(blob)
    assert SOURCE_RECORDS["experiments/dram-see-v3/r50-main/design.json"]["sha256"] == freeze["design_sha256"]
    r3 = jsource("local_runtime/dram-see-v3/physical-revisions/r50-main-restart-r3/plan.json", "r3-plan.json", "status", "r50-main-restart-r3", "Explicit logical retry mapping", "Preserved FAILED originals and unique logical aliases", "Retry is not a new independent event")
    aliases = {"v3-r50-main-l035-alpha-a30-s202610394-b1": "v3-r50-main-retry-r2-l035-alpha-a30-s202610394-b1", **r3["aliases"]}
    assert len(aliases) == 3
    alias_rows = []
    for original, retry in aliases.items():
        assert ledger["runs"][original]["state"] == "FAILED"
        assert ledger["runs"][retry]["state"] == "VERIFIED"
        alias_rows.append({"canonical_response_id": original, "retry_alias": retry, "preserved_original_state": "FAILED", "retry_state_at_snapshot": "VERIFIED", "retry_run_id": ledger["runs"][retry]["run_id"], "additional_independent_events": 0})
    slots = []
    for event in design["events"]:
        for bit in event["paired_bits"]:
            canonical = f"v3-r50-main-{event['label']}-b{bit}"
            actual = aliases.get(canonical, canonical)
            row = ledger["runs"].get(actual, {})
            slots.append({"event_label": event["label"], "stored_bit": bit, "split": event["split"], "gate_length_um": event["gate_length_um"], "canonical_response_id": canonical, "actual_ledger_tag": actual, "state": row.get("state", "UNSUBMITTED"), "run_id": row.get("run_id"), "preserved_failed_original": actual != canonical})
    counts = {}
    for split in ["train", "holdout", "extrapolation"]:
        values = [r for r in slots if r["split"] == split]
        c = Counter(r["state"] for r in values)
        counts[split] = {"planned": len(values), **{state: c[state] for state in ["VERIFIED", "RUNNING", "UNSUBMITTED", "FAILED"]}}
        assert sum(counts[split][state] for state in ["VERIFIED", "RUNNING", "UNSUBMITTED", "FAILED"]) == len(values)
    csv_write(DATA / "main-response-status.csv", slots)
    csv_write(DATA / "retry-aliases.csv", alias_rows)
    d1 = csv_source("experiments/dram-readout-offset-d1/data/summary.csv", "d1-summary.csv", "validation", "D1 historical, matched-ref-r3", "Reference choice diagnostic", "Recorded D1 fixed/offline/physical reference values", "D1 is not a R50-main event or additional training sample")
    probe = csv_source(PROBE + "precharge-checks.csv", "probe-precharge-checks.csv", "validation", "r50-probe-v1", "Precharge revision local validation", "Same fixed event with unchanged 10 uV gate", "Probe excluded from all main-matrix counts")
    reference = jsource(REF + "summary.json", "r50-reference-summary.json", "figure", "20261010T2022Z-references", "Reviewed baseline data and curves", "20 completed reference audits and baseline curves", "Snapshot had zero valid main particle responses; not current final report")
    assert sha((SNAPSHOTS / "r50-reference-summary.json").read_bytes()) == "cc7b5710cbbe887bfaa464e10cf681cd0ad4a8122194c34e6a67f9c9c8372998"
    numerical_path = "experiments/dram-see-v3/r50-main/data/numerical/preregistered.json"
    numerical = jsource(numerical_path, "r50-numerical-preregistered.json", "validation", "r50-main-r1 preregistered point", "Step/mesh sensitivity at the registered event", "This point passes 0.5 mV / 0.01 fC and stable classification", "Not full-matrix grid independence or completed boundary checks")
    provenance = frozen_data["provenance.json"]
    assert numerical["continuous_passed"] and numerical["classification_stable"]
    additional = [
        ("docs/course-project-syllabus.md", "course-syllabus.md", "course", "course requirements", "Course requirement mapping", "Required deliverables and human work pending", "No invented student roles, teacher approval, defense or grade"),
        ("experiments/dram-see-v3/r50-main/demo-implementation.md", "r50-demo-implementation.md", "AI", "R50 bounded mapping", "Natural-language interaction scope", "Bounded template to frozen matrix mapping", "Not unrestricted natural language or automatic solver dispatch"),
        ("experiments/dram-see-v3/r50-main/data/demo/20261010T1842Z-mapping/acceptance.json", "r50-demo-acceptance.json", "AI", "20261010T1842Z-mapping", "Recorded mapping acceptance", "Software mapping, audit and rejection evidence", "Not student field demonstration or new simulation"),
        (REF + "materials/methods-and-ai.md", "methods-and-ai.md", "interface", "reference-stage draft", "Geant4 to TCAD contract and AI disclosure", "3.6 eV/pair, finite track charge transfer, fixed-source audit", "No independently measured AI speedup or full material-stack transport"),
        ("experiments/dram-see-v3/r50-main/data/delivery-reviews/20261010T2022Z-references.md", "r50-reference-review.md", "figure", "reference-stage review", "Existing visual/reference review", "Previously reviewed six historical data plots", "Newly generated plots are not yet visually accepted"),
        ("experiments/dram-see-v3/precharge-r50-report.md", "r50-probe-report.md", "validation", "r50-probe-v1 completed report", "Probe provenance and interpretation", "Local circuit sensitivity with original FAILED preserved", "No promotion of old R100 FAILED response"),
        ("experiments/dram-see-v3/r50-main/restart-r3/downstream-notes.md", "r3-downstream-notes.md", "status", "r50-main-restart-r3", "Remaining dependencies and alias-aware reporting", "Extensions / boundary / native / delivery still need their own evidence", "No execution of old extension/delivery controllers"),
    ]
    for args in additional: source(*args)
    # Historical reports are retained as evidence for the historical discussion;
    # they never become R50 training rows or proof of completed current testing.
    historical_boundary = "Historical stage evidence only; not R50 data, current completion, or a fresh raw-archive audit"
    historical = [
        ("experiments/dram-see-v1/report.md", "historical-v1-report.md", "historical", "DRAM SEE v1, 2026-10-09", "Historical chain, initialization and limited prediction results", "Reported v1 16-condition matrix and limitations", historical_boundary),
        ("experiments/dram-see-v1/delivery.md", "historical-v1-delivery.md", "historical", "DRAM SEE v1 delivery", "Historical artifact and provenance entry points", "Recorded v1 delivery scope and artifact locations", historical_boundary),
        ("experiments/dram-see-v1/data/results.json", "historical-v1-results.json", "historical", "DRAM SEE v1 final derived summary", "Exact v1 response and fitting metrics cited in the course report", "v1 deterministic-matrix fit/holdout/extrapolation metrics with original scope", historical_boundary),
        ("experiments/dram-see-v1/data/model-frozen.json", "historical-v1-model-frozen.json", "historical", "DRAM SEE v1 model frozen 2026-10-09", "Historical coefficient freeze and visibility boundary", "v1 OLS coefficient freeze; original observed-case and extrapolation visibility", historical_boundary),
        ("experiments/dram-see-v1/data/extrapolation-forecasts.json", "historical-v1-extrapolation-forecasts.json", "historical", "DRAM SEE v1 extrapolation preregistration", "Historical per-case extrapolation predictions", "Recorded v1 forecasts; not a claim of blind interpolation testing", historical_boundary),
        ("experiments/dram-see-v2/report.md", "historical-v2-report.md", "historical", "DRAM SEE v2, 2026-10-10 report", "Controlled-state paired response and small-sample interpretation", "8 independent events / 16 paired responses, original reference and uncertainty limits", historical_boundary),
        ("experiments/dram-see-v2/data/summary/delivery-index.json", "historical-v2-delivery-index.json", "historical", "DRAM SEE v2 delivery index", "Historical derived/raw archive hash references", "Index contents and original evidence paths; copied index only", "Referenced raw tar hashes were not revalidated; no promotion into R50"),
        ("experiments/dram-readout-offset-d1/report.md", "historical-d1-report.md", "historical", "D1 effective design-r4 report", "Historical terminal-integral and reference values", "D1 nine-condition diagnostic and port-charge quantities", historical_boundary),
        ("experiments/dram-readout-offset-d1/interpretation.md", "historical-d1-interpretation.md", "historical", "D1 effective design-r4 interpretation", "Readout offset, displacement-current and conservation interpretation", "State-dependent offset and matching-reference interpretation; gate displacement is not oxide carrier transport", "No unique internal-capacitance decomposition, real sense-amplifier calibration, or new raw re-audit"),
        ("reports/paper/report.tex", "inherited-stage-report.tex", "inherited_artifact", "Existing stage manuscript, copied at evidence-package extension", "Inventory of an existing editable stage manuscript", "Historical manuscript availability and its own stage-limited content", "Not this final writing package or proof of completed current experiments"),
        ("reports/paper/report.pdf", "inherited-stage-report.pdf", "inherited_artifact", "Existing rendered stage manuscript, copied at evidence-package extension", "Inventory of an existing rendered stage artifact", "Inherited PDF availability only; no new rendering or content audit", "Not the two new final-package PDFs or proof of current completion"),
    ]
    for args in historical: source(*args)
    chapters_by_category = {
        "course": "课程报告第1章、附录A/B",
        "model": "课程报告第2/4章；论文第2/3节",
        "prediction": "课程报告第4/5章；论文第5节",
        "validation": "课程报告第4–6章；论文第4–5节",
        "figure": "课程报告第5章；论文第4节",
        "AI": "课程报告第3章、附录C；论文第3节",
        "interface": "课程报告第3章；论文第2/3节",
        "status": "课程报告第5章、附录B；论文证据来源与复核范围",
        "historical": "课程报告第1–3章、第5.2节、第6章、附录A–C",
        "inherited_artifact": "课程报告附录C（既有阶段产物）；论文证据来源与复核范围",
    }
    for path, record in SOURCE_RECORDS.items():
        record["chapter_mapping"] = chapters_by_category[record["category"]]
        if "dram-readout-offset-d1" in path:
            record["chapter_mapping"] = "课程报告第5.2节、第6.2节；论文第4.1节"
        record["raw_reaudit_this_pass"] = False
    dump(SOURCE_MAP, SOURCE_RECORDS)
    plotting = style()
    d1_points = plot_d1(d1, capture)
    probe_points = plot_probe(probe, capture)
    train = frozen_data["training-data.json"]
    training_rows = plot_training(train, capture)
    cv = plot_cv(frozen_data["models.json"], capture)
    reference_rows = plot_reference(reference, capture)
    classification = {}
    for epsilon in [2.5, 5.0, 10.0]:
        raw = Counter(r["classification"][str(epsilon/1000)] for r in train)
        effective = Counter("numerically_uncertain" if epsilon in r["classification_numerically_uncertain_thresholds_mV"] else r["classification"][str(epsilon/1000)] for r in train)
        classification[str(epsilon)] = {"raw": dict(raw), "effective": dict(effective)}
    numeric_rows = [{"step_scale": r["variation"]["step"], "mesh_scale": r["variation"]["mesh"], "M_difference_mV": 1000*r["differences_V"]["M4_V"], "deltaQ_difference_fC": r["deltaQ_difference_fC"], "readout_tolerance_mV": 1000*r["tolerances"]["readout_V"], "deltaQ_tolerance_fC": r["tolerances"]["deltaQ_fC"], "continuous_passed": r["continuous_passed"], "classification_stable": r["classification_stable"]} for r in numerical["comparisons"]]
    csv_write(DATA / "r50-preregistered-numerical.csv", numeric_rows)
    evidence = {
        "schema": "dram-final-writing-evidence-v1", "git_commit_context": design["git_commit"],
        "snapshot": capture,
        "progress": {"planned_independent_events": 64, "planned_paired_responses": 128, "logical_counts": counts, "retry_aliases": alias_rows,
                     "settled_solver_seconds_all_versions": sum(r.get("charged_solver_s", 0) or 0 for r in ledger["runs"].values()),
                     "running_ledger_tags": [k for k, r in ledger["runs"].items() if r["state"] == "RUNNING"],
                     "running_is_index_state_only": True, "test_or_extrapolation_scores_in_this_package": False},
        "freeze": {k: v for k, v in freeze.items() if k != "files_sha256"},
        "freeze_integrity": {"freeze_sha256": checksum, "freeze_checksum_matches": True, "bound_core_files": frozen_checks, "all_six_core_files_match": True, "other_bound_files_rechecked": False},
        "model": {"physical_revision": design["physical_revision"], "scope": design["scope"], "metrics": design["metrics"], "source": design["source"], "gates": design["gates"], "statistics": design["statistics"], "prediction": design["prediction"], "oxide_extension": design["oxide_extension"]},
        "training": {"independent_events": len({r["event_label"] for r in train}), "paired_responses": len(train), "continuous_valid": sum(r["continuous_valid"] for r in train), "classification_by_threshold_mV": classification, "cv": cv,
                     "cv_is_training_only": True, "no_test_based_tuning": "The copied freeze records test_responses_seen=0; this generator does not fit models or inspect test target metrics"},
        "completed_gate_records": {k: {"state": v.get("state"), "cases": len(v.get("cases", []))} for k, v in provenance["gates"].items()},
        "d1_reference": d1_points, "r50_probe_precharge": probe_points,
        "r50_reference_snapshot": {"generated_utc": reference["generated_utc"], "sha256": SOURCE_RECORDS[REF+"summary.json"]["sha256"], "audited_runs": len(reference["audited_runs"]), "baseline_rows": reference_rows, "source_snapshot_valid_particle_responses": reference["measured_main_responses"]},
        "preregistered_numerical": numeric_rows,
        "limitations": ["No solver / SSH / remote or process checks", "No full raw-tar re-audit in this writing pass", "No current test or extrapolation performance claim", "No completed oxide extension / boundary validation claim", "No commercial reliability / calibrated bit flip / cross section claim", "No AI speedup claim", "New PNGs need root visual review", "Actual student roles, teacher review, resource handoff, defense and assessment remain human evidence"],
        "plotting_environment": plotting, "generator_sha256": sha(Path(__file__).read_bytes()),
    }
    dump(DATA / "evidence.json", evidence)
    make_tables(evidence)
    dump(FIGURES / "index.json", {"schema": "dram-final-figure-index-v1", "figures": FIGURE_RECORDS, "visual_review": "PENDING_ROOT_IMAGE_INSPECTION"})
    # Keep a concise index of what every source can and cannot support.
    index_rows = []
    for i, record in enumerate(SOURCE_RECORDS.values(), 1):
        index_rows.append({"evidence_id": f"E{i:02d}", **record, "output_scope": "data/evidence.json; tables/; figures/ (see each figure .sources.json)", "raw_reaudit_this_pass": False})
    ledger_record = {
        "source_path": capture["source_path"], "absolute_source_path": str(ROOT/capture["source_path"]),
        "copy_path": rel(DATA/"ledger-snapshot.json"), "sha256": capture["ledger_sha256"], "bytes": capture["bytes"],
        "category": "status", "version": capture["captured_utc"], "use": "Frozen local-ledger status counts",
        "evidence_type": "live_observation", "can_write": "Logical progress at the stated capture time",
        "cannot_write": "Current live process status, remote health, future completion or independent raw acceptance",
        "chapter_mapping": "课程报告第5.1节、附录B；论文证据来源与复核范围",
        "raw_reaudit_this_pass": False,
    }
    index_rows.append({"evidence_id": f"E{len(index_rows)+1:02d}", **ledger_record,
                       "output_scope": "data/evidence.json; tables/snapshot.tex; tables/progress.tex", "raw_reaudit_this_pass": False})
    csv_write(OUT / "evidence-index.csv", index_rows)
    outputs = []
    for directory in [DATA, FIGURES, TABLES]:
        for p in sorted(directory.rglob("*")):
            if p.is_file() and p.name != "workflow.tex": outputs.append({"path": p.relative_to(OUT).as_posix(), "sha256": sha(p.read_bytes()), "bytes": p.stat().st_size})
    outputs.append({"path": "evidence-index.csv", "sha256": sha((OUT/"evidence-index.csv").read_bytes()), "bytes": (OUT/"evidence-index.csv").stat().st_size})
    dump(OUT / "sources.json", {"schema": "dram-final-evidence-sources-v1", "captured_utc": capture["captured_utc"], "generator": {"path": "prepare_evidence.py", "sha256": sha(Path(__file__).read_bytes())}, "source_records": [*SOURCE_RECORDS.values(), ledger_record], "ledger_snapshot": capture, "outputs": outputs, "scope": "Writing evidence derived from fixed copied sources, not a new scientific raw audit or final full-matrix report"})
    assert len(FIGURE_RECORDS) == 5 and counts["train"]["VERIFIED"] == 64
    assert all(math.isfinite(float(r[key])) for r in training_rows for key in ["Qdep_fC", "deltaQ_fC", "deltaM_mV"])
    checks = {"state": "PASSED", "ledger_snapshot_once_and_preserved": True, "six_freeze_files_match": True, "three_failed_originals_preserved_with_verified_aliases": True, "training_rows": 64, "training_independent_events": 32, "figures_png_pdf_sources": 5, "finite_training_numbers": True, "no_raw_reaudit": True, "no_visual_review": True}
    # Self-check is placed in data then indexed without recursively hashing itself.
    dump(DATA / "self-check.json", checks)
    source_manifest = json.loads((OUT/"sources.json").read_text(encoding="utf-8"))
    source_manifest["outputs"].append({"path": "data/self-check.json", "sha256": sha((DATA/"self-check.json").read_bytes()), "bytes": (DATA/"self-check.json").stat().st_size})
    # Avoid duplicate entries on a reproducibility rerun.
    source_manifest["outputs"] = list({v["path"]: v for v in source_manifest["outputs"]}.values())
    dump(OUT/"sources.json", source_manifest)
    print(json.dumps({"output": str(OUT), "captured_utc": capture["captured_utc"], "captured_user_utc_minus_8": capture["captured_user_utc_minus_8"], "logical_counts": counts, "checks": checks}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
