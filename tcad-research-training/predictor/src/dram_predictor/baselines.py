"""Predeclared simple baselines and response ablations, scored on identical groups."""
from dataclasses import replace
import math

from .data import DataError, LeakageError
from .pipeline import frozen_folds
from .r_training import fit_r


def constant_native_baseline(train, validation):
    train.assert_disjoint(validation)
    values = []
    for state in (0, 1):
        records = [r for r in train.counts if r["state"] == state]
        exposure = sum(r["fluence_cm2"] * r["n_bits"] for r in records)
        values.append(sum(r["bit_errors"] for r in records) / exposure if exposure else None)
    scores = []
    infinite = 0
    for row in validation.counts:
        sigma = values[row["state"]]
        if sigma is None:
            continue
        expected = sigma * row["fluence_cm2"] * row["n_bits"]
        k = row["bit_errors"]
        if expected == 0 and k:
            infinite += 1
        else:
            scores.append(expected - (k * math.log(expected) if k else 0.) + math.lgamma(k + 1))
    return {"sigma_cm2_per_bit": values, "training_footprint": train.footprint(),
            "native_poisson_nll": (sum(scores)/len(scores) if scores and not infinite else None),
            "infinite_nll_rows": infinite, "scored_rows": len(scores) + infinite,
            "method": "training-only per-state constant Poisson MLE; no pseudocount"}


def ablations(snapshot, config, *, split_path=None, cache_dir=None):
    settings = {
        "mechanism_only": replace(config, mode="mechanism_only", residual_penalty=0.),
        "plain_mlp": replace(config, mode="plain", residual_penalty=0.),
        "hybrid_no_regularizer": replace(config, mode="hybrid", residual_penalty=0.),
        "hybrid_selected_regularizer": replace(config, mode="hybrid"),
    }
    records = []
    view = snapshot.view(snapshot.development_conditions)
    for fold in frozen_folds(view, split_path, config.split_seed):
        item = {"fold": fold.number, "F_constant": constant_native_baseline(fold.train, fold.validation)}
        for name, cfg in settings.items():
            try:
                model = fit_r(fold.train, cfg, cache_dir=cache_dir)
                item[name] = {"status": "ready", "R_metrics": model.evaluate(fold.validation)}
            except DataError as exc:
                if isinstance(exc, LeakageError):
                    raise
                item[name] = {"status": "pending", "reason": str(exc)}
        records.append(item)
    return {"folds": records, "sealed_labels_read": False, "kind": snapshot.manifest["kind"],
            "comparison": "Compare common observed heads; mechanism-only has no invented binary/port head.",
            "tree_baseline": "not implemented; constant native-count baseline provided"}
