"""Probability calibration from already-produced, random, out-of-fold evidence."""
from collections import Counter
import numpy as np

from .data import LeakageError
from .r_training import random_calibration_samples


def random_oof_records(artifact, validation):
    fit = artifact.metadata["training_footprint"]
    if (set(fit["profile_ids"]) & validation.profiles or
            set(fit["source_primary_ids"]) & validation.source_ids or
            set(fit["source_control_ids"]) &
            {c.get("source_control_id", c["control_id"]) for c in validation.controls}):
        raise LeakageError("Probability calibration predictions must exclude target sources")
    if "upset" not in artifact.metadata["trained_heads"]:
        return []
    samples = random_calibration_samples(validation)
    return [{
        "response_id": s["response"]["response_id"], "condition_id": s["condition"]["condition_id"],
        "source_primary_id": s["primary"]["source_primary_id"], "state": s["state"],
        "label": s["response"]["labels"]["upset"], "logit": p["upset_logit"],
    } for s, p in zip(samples, artifact.predict_samples(samples)) if p["upset_logit"] is not None]


def temperature_from_oof(fold_records):
    """Reuse three prescribed R folds; never add fitting runs or read test labels."""
    records = [r for f in fold_records for r in f.get("random_oof_probability_records", [])]
    ids = [r["response_id"] for r in records]
    if len(ids) != len(set(ids)):
        raise LeakageError("A calibration response occurs in more than one OOF fold")
    counts = Counter(r["source_primary_id"] for r in records)
    labels = np.asarray([r["label"] for r in records], dtype=float)
    if len(counts) < 4 or len(np.unique(labels)) < 2:
        return {"status": "unavailable", "reason": "insufficient independent random OOF events/classes",
                "independent_primaries": len(counts), "positive": int(labels.sum())}
    logits = np.asarray([r["logit"] for r in records], dtype=float)
    if not np.isfinite(logits).all() or not np.isin(labels, [0, 1]).all():
        raise LeakageError("Invalid random OOF calibration label/logit")
    weights = np.asarray([1. / counts[r["source_primary_id"]] for r in records])
    temperatures = np.exp(np.linspace(np.log(.25), np.log(4.), 65))
    objectives = [float(np.average(np.logaddexp(0, logits/t) - labels*logits/t, weights=weights))
                  for t in temperatures]
    index = int(np.argmin(objectives))
    return {"status": "estimated_oof_for_refit",
            "method": "bounded_temperature_from_prescribed_three_fold_development_random_predictions",
            "temperature": float(temperatures[index]), "development_bce": objectives[index],
            "independent_primaries": len(counts), "positive": int(labels.sum()),
            "response_ids": ids, "weighting": "equal total weight per source_primary_id",
            "independent_calibration_validation": False,
            "limitation": "OOF estimate applied to final refit; final calibration requires frozen independent evaluation"}
