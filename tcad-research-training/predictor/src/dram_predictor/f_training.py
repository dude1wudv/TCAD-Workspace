"""Condition-batched F training; no solver calls or fitting at import time.

Native per-state Poisson counts take precedence over cross-fitted proxy labels.
All feature and loss scales come from the fit view. An optional disjoint view
can select an epoch, but cannot fit preprocessing or create a prediction head.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .config import Config
from .data import F_FEATURES, DataError, LeakageError, View, digest, file_hash, read_json, write_json
from .features import Encoder, record
from .losses import poisson_count_loss, proxy_cross_section_loss
from .models import CrossSectionNet


def _number(value: Any, name: str, *, positive=False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (result <= 0 if positive else result < 0):
        raise DataError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return result


def _condition_records(conditions: list[dict], domains: list[str] | None = None) -> list[dict]:
    for condition in conditions:
        features = condition.get("features")
        if not isinstance(features, dict):
            raise DataError("F condition requires explicit pre-simulation features")
        unexpected = set(features) - set(F_FEATURES) - {"theta_deg", "phi_deg"}
        if unexpected:
            raise LeakageError(f"Unapproved F pre-simulation feature(s): {sorted(unexpected)}")
        if domains is not None and condition.get("domain") not in domains:
            raise DataError("F cannot predict another model domain")
    return [record(condition) for condition in conditions]


def _check_proxy_footprint(row: dict, condition: dict, target_sources: set[str],
                           target_controls: set[str]) -> None:
    footprint = row.get("training_footprint")
    if "training_footprint" not in row and row.get("status") != "ready":
        return
    if not isinstance(footprint, dict):
        raise DataError("Ready proxy requires an explicit training_footprint")
    for field in ("profile_ids", "source_primary_ids", "condition_ids", "source_control_ids"):
        values = footprint.get(field)
        if not isinstance(values, (list, tuple)) or any(not isinstance(x, str) or not x for x in values):
            raise DataError(f"Proxy training_footprint lacks explicit {field}")
    if condition["profile_id"] in footprint["profile_ids"]:
        raise LeakageError("Proxy model fitted its own target profile")
    if target_sources & set(footprint["source_primary_ids"]):
        raise LeakageError("Proxy model fitted its own target primary source")
    if condition["condition_id"] in footprint["condition_ids"]:
        raise LeakageError("Proxy model fitted its own target condition")
    if target_controls & set(footprint["source_control_ids"]):
        raise LeakageError("Proxy model fitted a reused target control source")


@dataclass
class _Supervision:
    conditions: list[dict]
    counts: torch.Tensor
    exposures: torch.Tensor
    native_mask: torch.Tensor
    targets: torch.Tensor
    weights: torch.Tensor
    proxy_mask: torch.Tensor
    provenance: list[dict]
    skipped: list[dict]
    native_precedence: list[dict]

    @property
    def trained_states(self) -> list[int]:
        return [i for i in range(2) if bool((self.native_mask | self.proxy_mask)[:, i].any())]

    @property
    def active_indices(self) -> torch.Tensor:
        return torch.where((self.native_mask | self.proxy_mask).any(dim=1))[0]

    def restrict_states(self, states: list[int]) -> "_Supervision":
        allowed = torch.tensor([i in states for i in range(2)], dtype=torch.bool)
        return _Supervision(
            self.conditions, self.counts, self.exposures, self.native_mask & allowed,
            self.targets, self.weights, self.proxy_mask & allowed, self.provenance,
            self.skipped, self.native_precedence,
        )


def _supervision(view: View, proxies: list[dict] | None) -> _Supervision:
    conditions = view.conditions
    indices = {row["condition_id"]: i for i, row in enumerate(conditions)}
    shape = (len(conditions), 2)
    counts = torch.full(shape, float("nan"), dtype=torch.float64)
    exposures = torch.full(shape, float("nan"), dtype=torch.float64)
    targets = torch.full(shape, float("nan"), dtype=torch.float64)
    weights = torch.zeros(shape, dtype=torch.float64)
    native_mask = torch.zeros(shape, dtype=torch.bool)
    proxy_mask = torch.zeros(shape, dtype=torch.bool)
    sources = {cid: set() for cid in indices}
    controls: dict[str, set[str]] = {}
    for control in view.controls:
        source = control.get("source_control_id", control["control_id"])
        if not isinstance(source, str) or not source:
            raise DataError("Control requires a nonempty physical source identity")
        controls.setdefault(control["profile_id"], set()).add(source)
    for primary in view.primaries:
        sources[primary["condition_id"]].add(primary["source_primary_id"])
    for row in view.counts:
        cid, state = row["condition_id"], row.get("state")
        if cid not in indices:
            raise LeakageError("Native count lies outside the F view")
        if type(state) is not int or state not in (0, 1) or row.get("count_model") != "poisson":
            raise DataError("F native counts require an explicit per-state Poisson contract")
        i = indices[cid]
        if native_mask[i, state]:
            raise DataError("Duplicate condition/state native counts must be merged explicitly")
        count = row.get("bit_errors")
        if type(count) is not int or count < 0:
            raise DataError("Native bit_errors must be a nonnegative integer")
        n_bits = row.get("n_bits")
        if type(n_bits) is not int or n_bits < 1 or n_bits != conditions[i]["n_bits"]:
            raise DataError("Native exposure has an invalid bit denominator")
        exposure = _number(row.get("fluence_cm2"), "fluence_cm2", positive=True) * n_bits
        if not math.isfinite(exposure):
            raise DataError("Native exposure exceeds finite numerical range")
        counts[i, state], exposures[i, state] = count, exposure
        native_mask[i, state] = True
        sources[cid].update(row.get("source_primary_ids", []))
    seen, provenance, skipped, precedence = set(), [], [], []
    for row in proxies or []:
        cid = row.get("condition_id")
        if cid not in indices:
            raise LeakageError("Proxy condition lies outside the F view")
        i = indices[cid]
        _check_proxy_footprint(row, conditions[i], sources[cid],
                               controls.get(conditions[i]["profile_id"], set()))
        provenance.append({
            **copy.deepcopy({key: value for key, value in row.items()
                             if key not in {"sigma_cm2_per_bit", "weights"}}),
            "proxy_record_sha256": digest(row),
        })
        if row.get("status") != "ready":
            skipped.append({"condition_id": cid, "reason": "proxy_not_ready"})
            continue
        if cid in seen:
            raise DataError("Duplicate ready proxy conditions are not independent observations")
        seen.add(cid)
        values, confidence = row.get("sigma_cm2_per_bit"), row.get("weights")
        if (not isinstance(values, (list, tuple)) or len(values) != 2
                or not isinstance(confidence, (list, tuple)) or len(confidence) != 2):
            raise DataError("Ready proxy requires two state targets and weights")
        for state in range(2):
            # Audit even suppressed proxy heads: native precedence must not
            # legitimize malformed or unauditable ready input.
            target = None if values[state] is None else _number(values[state], "proxy cross section")
            weight = None if confidence[state] is None else _number(confidence[state], "proxy confidence weight")
            if native_mask[i, state]:
                precedence.append({"condition_id": cid, "state": state,
                                   "reason": "native_count_takes_precedence"})
                continue
            if target is None or weight is None:
                continue
            if weight == 0:
                continue
            targets[i, state], weights[i, state] = target, weight
            proxy_mask[i, state] = True
    return _Supervision(conditions, counts, exposures, native_mask, targets, weights,
                        proxy_mask, provenance, skipped, precedence)


def _scale(data: _Supervision) -> tuple[float, dict]:
    native = (data.counts[data.native_mask] / data.exposures[data.native_mask]).tolist()
    proxy = data.targets[data.proxy_mask].tolist()
    positive = [value for value in native + proxy if value > 0]
    if positive:
        scale = float(np.median(positive))
        source = "median_positive_training_targets"
        count = len(positive)
    elif data.native_mask.any():
        scale = float(np.median((1. / data.exposures[data.native_mask]).tolist()))
        source = "median_inverse_training_native_exposure"
        count = int(data.native_mask.sum())
    else:
        areas = [_number(data.conditions[i]["source_area_cm2"], "source_area_cm2", positive=True)
                 for i in data.active_indices.tolist()]
        if not areas:
            raise DataError("F has no usable supervision or physical scale")
        scale = float(np.median(areas))
        source = "median_training_source_area_cm2"
        count = len(areas)
    if not math.isfinite(scale) or scale <= 0:
        raise DataError("F training-side cross-section scale is not finite and positive")
    return scale, {"source": source, "contributing_values": count,
                   "units": "cm2_per_bit", "training_side_only": True,
                   "note": "Numerical scale only; no pseudocount, target replacement, or physical bound."}


def _loss(pred: torch.Tensor, data: _Supervision, scale: float,
          indices: torch.Tensor | None = None) -> torch.Tensor:
    idx = slice(None) if indices is None else indices
    native = poisson_count_loss(pred, data.counts[idx], data.exposures[idx], data.native_mask[idx])
    proxy = proxy_cross_section_loss(pred, data.targets[idx], data.proxy_mask[idx],
                                     scale, data.weights[idx], max_weight=1.)
    return native + proxy


def _new_model(encoder: Encoder, config: Config, scale: float) -> CrossSectionNet:
    model = CrossSectionNet(encoder.width, config.f_hidden, scale).double()
    # The network constructor starts with a default-dtype buffer. Refill after
    # conversion so a small physical scale is represented at float64 precision.
    with torch.no_grad():
        model.sigma_scale.fill_(scale)
    return model


@dataclass
class FArtifact:
    model: CrossSectionNet
    encoder: Encoder
    config: Config
    metadata: dict

    @property
    def sigma_scale(self) -> float:
        return float(self.metadata["sigma_scale"])

    @property
    def trained_states(self) -> list[int]:
        return list(self.metadata["trained_states"])

    def _predict_tensor(self, conditions: list[dict]) -> torch.Tensor:
        rows = _condition_records(conditions, self.metadata["training_domains"])
        x = torch.as_tensor(self.encoder.transform(rows), dtype=torch.float64)
        self.model.eval()
        with torch.no_grad():
            result = self.model(x)
        if not torch.isfinite(result).all():
            raise DataError("F produced a nonfinite prediction")
        return result

    def predict(self, conditions: list[dict]) -> list[dict]:
        if not conditions:
            return []
        result = self._predict_tensor(conditions).tolist()
        outside = self.encoder.outside_support(_condition_records(conditions, self.metadata["training_domains"]))
        return [{
            "condition_id": condition["condition_id"],
            "sigma_cm2_per_bit": [values[state] if state in self.trained_states else None
                                  for state in range(2)],
            "out_of_support": support,
        } for condition, values, support in zip(conditions, result, outside)]

    def evaluate(self, view: View, proxies: list[dict] | None = None) -> dict:
        data = _supervision(view, proxies).restrict_states(self.trained_states)
        native_count, proxy_states = int(data.native_mask.sum()), int(data.proxy_mask.sum())
        report = {"native_poisson_nll": None, "native_count_rows": native_count,
                  "proxy_asinh_mae": None, "proxy_rows": int(data.proxy_mask.any(dim=1).sum()),
                  "proxy_state_labels": proxy_states}
        if not native_count and not proxy_states:
            return report
        pred = self._predict_tensor(data.conditions)
        if native_count:
            report["native_poisson_nll"] = float(poisson_count_loss(
                pred, data.counts, data.exposures, data.native_mask))
        if proxy_states:
            report["proxy_asinh_mae"] = float((
                torch.asinh(pred[data.proxy_mask] / self.sigma_scale)
                - torch.asinh(data.targets[data.proxy_mask] / self.sigma_scale)
            ).abs().mean())
        return report

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.mkdir(parents=True, exist_ok=True)
        model_path, manifest_path = destination / "model.pt", destination / "artifact.json"
        if model_path.exists() or manifest_path.exists():
            raise DataError("Refusing to overwrite an existing F artifact")
        with model_path.open("xb") as stream:
            torch.save(self.model.state_dict(), stream)
        payload = {
            "format_version": 1, "artifact_type": "F_cross_section",
            "model_file": "model.pt", "model_sha256": file_hash(model_path),
            "encoder": self.encoder.to_dict(), "config": self.config.to_dict(),
            "metadata": copy.deepcopy(self.metadata),
        }
        payload["artifact_sha256"] = digest(payload)
        write_json(manifest_path, payload)
        return manifest_path

    @classmethod
    def load(cls, path: str | Path) -> "FArtifact":
        path = Path(path)
        manifest_path = path / "artifact.json" if path.is_dir() else path
        payload = read_json(manifest_path)
        expected = payload.pop("artifact_sha256", None)
        if expected != digest(payload):
            raise DataError("F artifact metadata hash mismatch")
        if (payload.get("format_version") != 1 or payload.get("artifact_type") != "F_cross_section"
                or payload.get("model_file") != "model.pt"):
            raise DataError("Unsupported F artifact format")
        model_path = manifest_path.parent / "model.pt"
        if file_hash(model_path) != payload.get("model_sha256"):
            raise DataError("F model hash mismatch")
        config = Config.from_dict(payload["config"])
        encoder = Encoder.from_dict(payload["encoder"])
        if encoder.mode != "F":
            raise LeakageError("F artifact requires an F-only feature encoder")
        metadata = payload["metadata"]
        scale = _number(metadata["sigma_scale"], "sigma_scale", positive=True)
        domains = metadata.get("training_domains")
        if not isinstance(domains, list) or not domains or any(not isinstance(d, str) or not d for d in domains):
            raise DataError("F artifact has no explicit training domains")
        states = metadata.get("trained_states")
        if (not isinstance(states, list) or not states or len(set(states)) != len(states)
                or any(type(state) is not int or state not in (0, 1) for state in states)):
            raise DataError("F artifact has invalid trained_states")
        with torch.random.fork_rng(devices=[]):
            model = _new_model(encoder, config, scale)
        state = torch.load(model_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=True)
        if float(model.sigma_scale) != scale:
            raise DataError("F stored model and metadata scales disagree")
        model.eval()
        return cls(model, encoder, config, metadata)


def fit_f_core(
    view: View,
    proxies: list[dict],
    config: Config,
    *,
    stop_view: View | None = None,
    stop_proxies: list[dict] | None = None,
    epochs: int | None = None,
) -> FArtifact:
    """Fit only ``view``; optional stopping labels choose an epoch, never a scale."""
    if epochs is not None and (type(epochs) is not int or epochs < 1):
        raise DataError("Explicit F epochs must be a positive integer")
    if stop_view is None and stop_proxies:
        raise DataError("stop_proxies requires an explicit disjoint stop_view")
    if stop_view is not None:
        view.assert_disjoint(stop_view)
    data = _supervision(view, proxies)
    states = data.trained_states
    if not states:
        raise DataError("F has no usable native-count or ready proxy supervision")
    stop_data = _supervision(stop_view, stop_proxies).restrict_states(states) if stop_view is not None else None
    valid_stop = stop_data is not None and bool(len(stop_data.active_indices))
    select_epoch = valid_stop and epochs is None
    domains = sorted({condition["domain"] for condition in data.conditions})
    encoder = Encoder("F").fit(_condition_records(data.conditions, domains))
    scale, scale_source = _scale(data)
    x = torch.as_tensor(encoder.transform(_condition_records(data.conditions, domains)), dtype=torch.float64)
    stop_x = (torch.as_tensor(encoder.transform(_condition_records(stop_data.conditions, domains)),
                              dtype=torch.float64)
              if valid_stop else None)
    total_epochs = config.max_epochs if epochs is None else epochs
    history, best_state, best_score, stale = [], None, math.inf, 0
    selected_epochs = total_epochs
    torch.set_num_threads(config.threads)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(config.seed)
        model = _new_model(encoder, config, scale)
        optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate,
                                      weight_decay=config.weight_decay)
        rng = torch.Generator().manual_seed(config.seed)
        active = data.active_indices
        for epoch in range(1, total_epochs + 1):
            model.train()
            order = active[torch.randperm(len(active), generator=rng)]
            for indices in order.split(config.f_batch_conditions):
                optimizer.zero_grad(set_to_none=True)
                loss = _loss(model(x[indices]), data, scale, indices)
                if not torch.isfinite(loss):
                    raise DataError("F training loss is nonfinite")
                loss.backward()
                if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in model.parameters()):
                    raise DataError("F training gradient is nonfinite")
                optimizer.step()
            model.eval()
            with torch.no_grad():
                training_loss = float(_loss(model(x), data, scale))
                stopping_loss = float(_loss(model(stop_x), stop_data, scale)) if stop_x is not None else None
            if not math.isfinite(training_loss) or (stopping_loss is not None and not math.isfinite(stopping_loss)):
                raise DataError("F evaluation loss is nonfinite")
            history.append({"epoch": epoch, "training_loss": training_loss, "stopping_loss": stopping_loss})
            if select_epoch:
                if stopping_loss < best_score:
                    best_score, stale, selected_epochs = stopping_loss, 0, epoch
                    best_state = copy.deepcopy(model.state_dict())
                else:
                    stale += 1
                if stale >= config.patience:
                    break
        if select_epoch:
            model.load_state_dict(best_state)
    model.eval()
    metadata = {
        "sigma_scale": scale, "scale_provenance": scale_source,
        "trained_states": states, "selected_epochs": selected_epochs,
        "epochs_run": len(history), "history": history, "seed": config.seed,
        "stopping_mode": "disjoint_epoch_selection" if select_epoch else "fixed_epochs",
        "stopping_reason": ("disjoint_epoch_selection" if select_epoch else
                            "no_valid_stop" if not valid_stop else "explicit_epochs"),
        "training_footprint": copy.deepcopy(view.footprint()),
        "stopping_footprint": copy.deepcopy(stop_view.footprint()) if stop_view is not None else None,
        "training_fingerprint": view.fingerprint(),
        "training_kind": view.snapshot.manifest["kind"],
        "training_domains": domains,
        "encoder_condition_ids": [row["condition_id"] for row in data.conditions],
        "supervised_condition_ids": [data.conditions[i]["condition_id"] for i in data.active_indices.tolist()],
        "native_count_rows": int(data.native_mask.sum()),
        "proxy_rows": int(data.proxy_mask.any(dim=1).sum()),
        "proxy_state_labels": int(data.proxy_mask.sum()),
        "proxy_provenance": data.provenance,
        "skipped_proxies": data.skipped,
        "native_precedence": data.native_precedence,
        "native_loss": "mean_poisson_nll_with_lgamma_constant",
        "proxy_loss": "confidence_weighted_asinh_huber_weight_cap_1",
        "objective": "sum_of_separately_normalized_native_and_proxy_losses",
        "dtype": "float64", "threads": config.threads,
    }
    return FArtifact(model, encoder, config, metadata)
