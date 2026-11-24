"""R -> complete-pool A -> F with nested provenance scopes and sealed-label isolation."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

import numpy as np

from .aggregation import aggregate_condition
from .config import Config, search_space
from .data import (
    DataError, LeakageError, Snapshot, View, bits_for, digest, has_mapped_source,
    has_supervised_head, head_valid, read_json, write_json,
)
from .r_training import fit_r
from .splits import Fold, connected_groups, grouped_folds, split_manifest, stopping_split


def readiness(snapshot: Snapshot) -> dict:
    if snapshot.data_stage == "transport_only":
        actual = dict.fromkeys(snapshot.conditions, 0)
        for primary in snapshot.primaries.values():
            actual[primary["condition_id"]] += 1
        return {
            **snapshot.summary(),
            "condition_count": len(snapshot.conditions),
            "profile_count": len({c["profile_id"] for c in snapshot.conditions.values()}),
            "source_primary_count": len({p["source_primary_id"] for p in snapshot.primaries.values()}),
            "primaries_by_condition": actual,
            "declared_primaries_by_condition": {
                k: c["primary_count"] for k, c in snapshot.conditions.items()},
            "supervised_response_rows_by_head": {
                h: 0 for h in ("delta_voltage_V", "port_charge_fC", "margin_V", "upset")},
            "mechanism_controls_marked_applicable": 0,
            "native_count_rows": 0,
            "R_ready": False, "F_ready": False,
            "R": {"ready": False, "status": "pending",
                  "reason": "transport_only: no verified TCAD response/source mapping or readout labels"},
            "F": {"ready": False, "status": "pending",
                  "reason": "transport_only: no native error counts or calibrated cross-section supervision"},
            "notes": [
                "Archived transport metadata and complete primary pools are retained without inventing missing physics.",
                "Transport presence does not establish TCAD mapping, SEU labels or area-normalized cross sections.",
                "Training, solver calls, remote mutation and sealed label reads are not performed.",
            ],
        }
    view = snapshot.view(snapshot.development_conditions)
    responses = view.responses
    heads = {h: sum(has_supervised_head(r, h) for r in responses)
             for h in ("delta_voltage_V", "port_charge_fC", "margin_V", "upset")}
    report = {
        **snapshot.summary(), "independent_source_groups": len(connected_groups(view)),
        "supervised_response_rows_by_head": heads,
        "mechanism_controls_marked_applicable": sum(c.get("mechanism_validated") is True for c in view.controls),
        "native_count_rows": len(view.counts),
        "notes": [
            "Counts indicate data presence, not scientific qualification or sufficient statistics.",
            "Missing R labels do not stop simulation or invalidate usable native F supervision.",
            "No native/synthetic training, solver call, remote mutation or sealed label read occurs in prepare.",
        ],
    }
    if snapshot.simulation_revision == "0.6":
        report["development_response_rows_by_state"] = [
            sum(row["state"] == state for row in responses) for state in (0, 1)]
        report["supervised_upset_rows_by_state"] = [
            sum(row["state"] == state and has_supervised_head(row, "upset") for row in responses)
            for state in (0, 1)]
    return report


def prepare(snapshot: Snapshot, output_dir) -> dict:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    report = readiness(snapshot)
    if snapshot.data_stage == "transport_only":
        report.update(
            split_status="pending",
            split_reason="transport_only: training splits are not frozen before model data are ready",
            snapshot_manifest=snapshot.read_files[0],
            transport_fingerprint=digest({
                "data_stage": snapshot.data_stage,
                "conditions": snapshot.conditions, "primaries": snapshot.primaries,
                "kind": snapshot.manifest["kind"]}),
        )
        write_json(output / "readiness.json", report)
        return report
    view = snapshot.view(snapshot.development_conditions)
    try:
        splits = split_manifest(view)
        write_json(output / "splits.json", splits)
        report["split_status"] = "frozen"
        report["split_hash"] = splits["split_hash"]
    except LeakageError as exc:
        report.update(split_status="pending", split_reason=str(exc))
    report["snapshot_manifest"] = snapshot.read_files[0]
    report["development_fingerprint"] = view.fingerprint()
    write_json(output / "readiness.json", report)
    return report


def frozen_folds(view: View, path=None, seed=20261116):
    view.snapshot.require_model_stage()
    if path is None:
        return grouped_folds(view, 3, seed)
    payload = read_json(Path(path))
    expected = payload.pop("split_hash", None)
    if digest(payload) != expected:
        raise LeakageError("Frozen split hash mismatch")
    if payload["development_fingerprint"] != view.fingerprint():
        raise LeakageError("Snapshot changed after preparation; explicitly version and prepare the new snapshot")
    folds = []
    seen = set()
    for item in payload["folds"]:
        train = view.snapshot.view(item["train"]["condition_ids"])
        held = view.snapshot.view(item["validation"]["condition_ids"])
        if train.condition_ids | held.condition_ids != view.condition_ids:
            raise LeakageError("Frozen fold does not cover this development scope")
        train.assert_disjoint(held)
        if seen & held.condition_ids:
            raise LeakageError("Frozen validation folds overlap")
        if train.footprint() != item["train"] or held.footprint() != item["validation"]:
            raise LeakageError("Frozen source footprint changed")
        seen.update(held.condition_ids)
        folds.append(Fold(item["fold"], train, held))
    if seen != set(view.condition_ids) or len(folds) != 3:
        raise LeakageError("Expected three complete frozen development folds")
    return folds


def aggregate_view(artifact, view: View) -> list[dict]:
    view.snapshot.require_model_stage()
    footprint = artifact.metadata["training_footprint"]
    if set(footprint["profile_ids"]) & view.profiles or set(footprint["source_primary_ids"]) & view.source_ids:
        raise LeakageError("Proxy generation requires an R model fitted outside every target source group")
    controls = {c.get("source_control_id", c["control_id"]) for c in view.controls}
    if controls & set(footprint.get("source_control_ids", [])):
        raise LeakageError("R proxy generation reuses a target control source")
    rows = []
    if "upset" not in artifact.metadata["trained_heads"]:
        return [{"condition_id": c["condition_id"], "status": "pending",
                 "reason": "R has no supervised two-class upset head"} for c in view.conditions]
    r06 = view.snapshot.simulation_revision == "0.6"
    states = artifact.metadata.get("upset_states", ()) if r06 else (0, 1)
    conditions = view.conditions
    pools = {condition["condition_id"]: [] for condition in conditions}
    for primary in view.primaries:
        pools[primary["condition_id"]].append(primary)
    for condition in conditions:
        condition_id = condition["condition_id"]
        pool = pools[condition_id]
        if r06 and (not states or any(p["pool_member"] and not has_mapped_source(p) for p in pool)):
            reason = ("R has no state with supervised two-class upset" if not states
                      else "Complete-pool R prediction requires mapped source features for every pool primary")
            rows.append({"condition_id": condition_id, "status": "pending", "reason": reason})
            continue
        samples = [{"condition": condition, "primary": p, "state": state, "bit": bit}
                   for p in pool if p.get("pool_member") is True
                   for state in states for bit in bits_for(condition)]
        probabilities = artifact.predict_samples(samples) if samples else []
        calibration = artifact.metadata["probability_calibration"]
        status = "calibrated" if calibration.get("status") == "calibrated" else "uncalibrated"
        estimate = aggregate_condition(
            condition, pool, probabilities, probability_status=status, states=states,
            provenance={"R_cache_key": artifact.metadata.get("cache_key"),
                        "R_training_fingerprint": artifact.metadata["training_fingerprint"],
                        "training_footprint": footprint, "probability_calibration": calibration})
        estimate["training_footprint"] = footprint
        rows.append(estimate)
    return rows


def cross_fit_proxies(view: View, config: Config, n_splits=2, *, cache_dir=None,
                      collect_probability_calibration=False) -> tuple[list[dict], list[dict]]:
    view.snapshot.require_model_stage()
    rows, audit = [], []
    for fold in grouped_folds(view, n_splits, config.split_seed):
        try:
            artifact = fit_r(fold.train, config, cache_dir=cache_dir)
            estimates = aggregate_view(artifact, fold.validation)
            audit.append({"fold": fold.number, "status": "ready",
                          "R_cache_key": artifact.metadata["cache_key"], **fold.to_dict()})
            if collect_probability_calibration:
                from .calibration import random_oof_records
                audit[-1]["random_oof_probability_records"] = random_oof_records(artifact, fold.validation)
        except DataError as exc:
            if isinstance(exc, LeakageError):
                raise
            estimates = [{"condition_id": c["condition_id"], "status": "pending", "reason": str(exc)}
                         for c in fold.validation.conditions]
            audit.append({"fold": fold.number, "status": "pending", "reason": str(exc), **fold.to_dict()})
        rows.extend(estimates)
    if {r["condition_id"] for r in rows} != set(view.condition_ids):
        raise LeakageError("Cross-fit proxy coverage differs from requested development scope")
    return rows, audit


def fit_f(view: View, proxies, config: Config, *, cache_dir=None):
    view.snapshot.require_model_stage()
    from .f_training import fit_f_core
    split = stopping_split(view, config.split_seed, config.stopping_fraction)
    epochs = config.max_epochs
    selection = {"status": "fixed_epochs_fallback", "reason": "too few independent groups"}
    if split:
        core, stop = split
        try:
            # C's proxies are made exclusively by R models fitted within C.
            # S's proxies are made by a separate R fitted only to C.
            core_proxy, core_audit = cross_fit_proxies(core, config, 2, cache_dir=cache_dir)
            try:
                core_r = fit_r(core, config, cache_dir=cache_dir)
                stop_proxy = aggregate_view(core_r, stop)
            except DataError as exc:
                if isinstance(exc, LeakageError):
                    raise
                stop_proxy = []
            selected = fit_f_core(core, core_proxy, config, stop_view=stop, stop_proxies=stop_proxy)
            epochs = selected.metadata["selected_epochs"]
            selection = {"status": ("nested_grouped_stop" if
                          selected.metadata["stopping_mode"] == "disjoint_epoch_selection" else
                          "fixed_epochs_fallback"),
                         "reason": selected.metadata["stopping_reason"],
                         "fit": core.footprint(), "stop": stop.footprint(),
                         "inner_R_folds": core_audit, "selected_epochs": epochs,
                         "F_stopping": {"mode": selected.metadata["stopping_mode"],
                                        "epochs_run": selected.metadata["epochs_run"]}}
        except DataError as exc:
            if isinstance(exc, LeakageError) and len(connected_groups(core)) >= 2:
                raise
            selection = {"status": "fixed_epochs_fallback", "reason": str(exc),
                         "stop_not_used_for_fit": stop.footprint()}
    artifact = fit_f_core(view, proxies, config, epochs=epochs)
    artifact.metadata["epoch_selection"] = selection
    artifact.metadata["final_fit_proxy_policy"] = "R out-of-fold labels; never full-scope in-sample R labels"
    return artifact


def cross_validate(snapshot: Snapshot, config: Config, *, cache_dir=None, split_path=None) -> dict:
    snapshot.require_model_stage()
    view = snapshot.view(snapshot.development_conditions)
    records = []
    started = time.monotonic()
    for fold in frozen_folds(view, split_path, config.split_seed):
        item = {**fold.to_dict(), "R": {"status": "pending"}, "F": {"status": "pending"}}
        proxies, audit = cross_fit_proxies(fold.train, config, 2, cache_dir=cache_dir)
        item["inner_cross_fit"] = audit
        item["proxy_ready"] = sum(p["status"] == "ready" for p in proxies)
        validation_proxy = []
        try:
            r_model = fit_r(fold.train, config, cache_dir=cache_dir)
            item["R"] = {"status": "ready", "metrics": r_model.evaluate(fold.validation),
                         "cache_key": r_model.metadata["cache_key"]}
            validation_proxy = aggregate_view(r_model, fold.validation)
        except DataError as exc:
            if isinstance(exc, LeakageError):
                raise
            item["R"]["reason"] = str(exc)
        try:
            f_model = fit_f(fold.train, proxies, config, cache_dir=cache_dir)
            item["F"] = {"status": "ready", "metrics": f_model.evaluate(fold.validation, validation_proxy),
                         "epoch_selection": f_model.metadata["epoch_selection"]}
        except DataError as exc:
            if isinstance(exc, LeakageError):
                raise
            item["F"]["reason"] = str(exc)
        records.append(item)
    report = {
        "config": config.to_dict(), "folds": records, "elapsed_seconds": time.monotonic()-started,
        "kind": snapshot.manifest["kind"], "sealed_labels_read": False,
        "score_interpretation": "development_selection_score_not_unbiased_final_generalization",
    }
    report["selection_score"] = selection_score(report)
    return report


def selection_score(report) -> dict:
    native, response = [], []
    all_native, all_response = True, True
    for fold in report["folds"]:
        metrics = fold["F"].get("metrics", {})
        score = metrics.get("native_poisson_nll")
        if score is not None and np.isfinite(score):
            native.append(score)
        else:
            all_native = False
        rm = fold["R"].get("metrics", {}).get("heads", {})
        scores = [v.get("brier", v.get("normalized_mae")) for v in rm.values()]
        scores = [v for v in scores if v is not None and np.isfinite(v)]
        if scores:
            response.append(float(np.mean(scores)))
        else:
            all_response = False
    return {"native_poisson_nll": float(np.mean(native)) if all_native and native else None,
            "R_mean_normalized_error": float(np.mean(response)) if all_response and response else None,
            "complete_native_folds": len(native), "complete_R_folds": len(response)}


def run_search(snapshot, base: Config, output_dir, *, split_path=None):
    snapshot.require_model_stage()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    candidates = search_space(base)
    write_json(output / "search_manifest.json", {
        "configurations": [c.to_dict() for c in candidates], "single_search_seed": 1729,
        "selected_repeats": [1729, 2718, 31415], "training_parallelism": 1,
        "sealed_labels_read": False, "deferred_stages": ["final blind evaluation"],
    })
    reports = []
    for i, config in enumerate(candidates):
        report = cross_validate(snapshot, config, cache_dir=output / "cache", split_path=split_path)
        write_json(output / f"candidate_{i:02d}.json", report)
        reports.append(report)
    # Choose on the same criterion for every candidate; an incomplete candidate
    # cannot win just by skipping a difficult validation fold.
    metric = ("native_poisson_nll" if any(r["selection_score"]["native_poisson_nll"] is not None
                                        for r in reports) else "R_mean_normalized_error")
    eligible = [i for i, r in enumerate(reports) if r["selection_score"][metric] is not None]
    if not eligible:
        raise DataError("No complete development score; reports retained, no winner fabricated")
    index = min(eligible, key=lambda i: (reports[i]["selection_score"][metric],
                                      sum(candidates[i].r_hidden)+sum(candidates[i].f_hidden), i))
    chosen = candidates[index]
    selected = {"candidate": index, "criterion": metric, "config": chosen.to_dict(),
                "selection_score": reports[index]["selection_score"],
                "qualification": ("native_count_development_selection" if metric == "native_poisson_nll"
                                  else "R_only_research_selection_F_accuracy_not_established")}
    write_json(output / "selected.json", selected)
    repeats = {"1729": reports[index]}
    for seed in (2718, 31415):
        report = cross_validate(snapshot, replace(chosen, seed=seed),
                                cache_dir=output / "cache", split_path=split_path)
        write_json(output / f"selected_seed_{seed}.json", report)
        repeats[str(seed)] = report
    write_json(output / "stability.json", {
        "scores": {s: r["selection_score"] for s, r in repeats.items()},
        "interpretation": "seed variation is not a calibrated 95-percent prediction interval"})
    return selected


def fit_final(snapshot, config: Config, output_dir) -> dict:
    snapshot.require_model_stage()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    view = snapshot.view(snapshot.development_conditions)
    proxies, audit = cross_fit_proxies(view, config, 3, cache_dir=output / "cache",
                                     collect_probability_calibration=True)
    write_json(output / "F_development_oof_proxies.json", proxies)
    write_json(output / "R_three_fold_provenance.json", audit)
    report = {"kind": snapshot.manifest["kind"], "sealed_labels_read": False,
              "R": {"status": "pending"}, "F": {"status": "pending"},
              "development_fingerprint": view.fingerprint(), "config": config.to_dict()}
    try:
        model = fit_r(view, config, cache_dir=output / "cache")
        if "upset" in model.metadata["trained_heads"]:
            from .calibration import temperature_from_oof
            model.metadata["probability_calibration"] = temperature_from_oof(audit)
        model.save(output / "R")
        report["R"] = {"status": "ready", "trained_heads": model.metadata["trained_heads"]}
    except DataError as exc:
        if isinstance(exc, LeakageError):
            raise
        report["R"]["reason"] = str(exc)
    try:
        model = fit_f(view, proxies, config, cache_dir=output / "cache")
        model.save(output / "F")
        report["F"] = {"status": "ready", "trained_states": model.metadata.get("trained_states")}
    except DataError as exc:
        if isinstance(exc, LeakageError):
            raise
        report["F"]["reason"] = str(exc)
    report["model_card"] = {
        "scope": "proton; one explicitly declared DDR5 or LPDDR5 domain",
        "synthetic_only": snapshot.manifest["kind"] == "synthetic_fixture",
        "scientific_accuracy_claim": False,
        "F_label_policy": "native per-state counts or three-fold out-of-fit R/A proxies",
        "source_versions": snapshot.manifest,
        "limitations": [
            "No test labels read; no external validation or graduation conclusion.",
            "Constant-C RC is only an explicitly applicable local approximation.",
            "No generic language model is trained by this package.",
            "No flux implies cross sections only; no independent error-rate verification.",
        ],
    }
    write_json(output / "model_card.json", report)
    return report
