"""Scope-local response fitting, grouped stopping, and auditable deployment artifacts."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from .config import Config
from .data import DataError, View, bits_for, digest, file_hash, has_supervised_head, head_valid, read_json, write_json
from .features import Encoder, SOURCE_TIMING_FIELDS, record, source_off_record
from .losses import masked_bce, masked_huber
from .mechanism import MechanismCalibrator
from .models import ResponseNet
from .splits import stopping_split

HEADS = ("delta_voltage_V", "port_charge_fC", "margin_V", "upset")
SOURCE_OVERRIDE_FIELDS = ("scale_factor",) + SOURCE_TIMING_FIELDS


def response_samples(view: View) -> list[dict]:
    revision = view.snapshot.simulation_revision
    result = []
    for response in sorted(view.responses, key=lambda r: r["response_id"]):
        if revision == "0.6" and not any(has_supervised_head(response, head) for head in HEADS):
            continue
        primary = view.snapshot.primaries[response["primary_id"]]
        condition = view.snapshot.conditions[primary["condition_id"]]
        bit = next(b for b in bits_for(condition)
                   if str(b["bit_id"]) == str(response.get("bit_id", "0")))
        result.append({"condition": condition, "primary": primary, "state": response["state"],
                       "bit": bit, "response": response, "simulation_revision": revision})
    return result


def sample_record(sample, *, simulation_revision=None):
    revision = simulation_revision or sample.get("simulation_revision")
    primary = sample["primary"]
    response = sample.get("response") or {}
    if revision == "0.4":
        primary = {key: value for key, value in primary.items() if key not in SOURCE_OVERRIDE_FIELDS}
    elif revision == "0.6" or (revision is None and response.get("deck_timing_version") is not None):
        overrides = {key: response[key] for key in SOURCE_OVERRIDE_FIELDS if key in response}
        primary = {**primary, **overrides}
    return record(sample["condition"], primary, sample["state"], sample["bit"])


def random_calibration_samples(view):
    r06 = view.snapshot.simulation_revision == "0.6"
    result = []
    for sample in response_samples(view):
        response = sample["response"]
        random = (response.get("selection_mechanism") == "simple_random" if r06
                  else sample["primary"].get("sampling") == "random")
        if random and head_valid(response, "upset") and (response.get("labels") or {}).get("upset") is not None:
            result.append(sample)
    return result


def targets(samples, times):
    labels, masks = {}, {}
    for head in HEADS:
        values, valid = [], []
        for sample in samples:
            row = sample["response"]
            value = (row.get("labels") or {}).get(head)
            if head == "delta_voltage_V":
                value = value if value is not None else [None] * len(times)
                values.append([np.nan if x is None else x for x in value])
            else:
                values.append(np.nan if value is None else value)
            valid.append(head_valid(row, head))
        array = np.asarray(values, dtype=np.float32)
        mask = np.asarray(valid, dtype=bool)
        if array.ndim == 2:
            mask = mask[:, None]
        labels[head] = torch.as_tensor(array)
        masks[head] = torch.as_tensor(mask & np.isfinite(array))
    return labels, masks


def primary_batches(samples, batch_groups, rng):
    """All observed responses to the same transport event share a minibatch."""
    groups = {}
    for i, sample in enumerate(samples):
        groups.setdefault(sample["primary"]["source_primary_id"], []).append(i)
    keys = sorted(groups)
    rng.shuffle(keys)
    for start in range(0, len(keys), batch_groups):
        yield torch.tensor([i for key in keys[start:start + batch_groups] for i in groups[key]],
                           dtype=torch.long)


def _masked_calibration(view, samples, source_records, device_encoder):
    controls = copy.deepcopy(view.controls)
    by_profile = {c["profile_id"]: c for c in view.conditions}
    control_records = [record(by_profile[c["profile_id"]], state=c["state"]) for c in controls]
    rows, features = [], []
    for sample, source in zip(samples, source_records):
        r, c, p = sample["response"], sample["condition"], sample["primary"]
        values = (r.get("labels") or {}).get("delta_voltage_V")
        if not head_valid(r, "delta_voltage_V") or values is None:
            continue
        rows.append({k: r[k] for k in ("response_id", "source_hash", "run_id", "state")})
        rows[-1].update(profile_id=c["profile_id"], time_ns=view.snapshot.times,
                        delta_voltage_V=values, capacitance_fF=c["features"]["capacitance_fF"],
                        mechanism_validated=r.get("mechanism_validated") is True,
                        generated_charge_fC=source["generated_charge_fC"],
                        source_duration_ns=p["source_features"]["source_duration_ns"])
        features.append(record(c, state=r["state"]))
    if not controls or not rows:
        raise DataError("R mechanism pending: identifiable training controls/responses are missing")
    try:
        return MechanismCalibrator().fit(device_encoder.transform(control_records), controls,
                                         device_encoder.transform(features), rows)
    except ValueError as exc:
        raise DataError(f"R mechanism pending: {exc}") from exc


@dataclass
class RArtifact:
    model: ResponseNet
    encoder: Encoder
    device_encoder: Encoder
    mechanism: MechanismCalibrator | None
    config: Config
    metadata: dict

    def _records(self, samples):
        revision = self.metadata.get("simulation_revision", "0.4")
        rows = [sample_record(s, simulation_revision=revision) for s in samples]
        if revision == "0.6":
            if any(s.get("simulation_revision", revision) != revision for s in samples):
                raise DataError("R artifact simulation_revision mismatch")
            for field in SOURCE_TIMING_FIELDS:
                if any(field in row and row[field] != self.metadata[field] for row in rows):
                    raise DataError(f"R artifact {field} mismatch")
        return rows

    def _inputs(self, samples, *, rows=None):
        domains = set(self.metadata.get("training_domains", []))
        if domains and any(s["condition"].get("domain") not in domains for s in samples):
            raise DataError("R artifact does not support this device/model domain")
        if rows is None:
            rows = self._records(samples)
        device_rows = [record(s["condition"], state=s["state"]) for s in samples]
        # Plain ablation ignores these two API placeholders; they are not fitted physics.
        physics = (self.mechanism.predict(self.device_encoder.transform(device_rows))
                   if self.mechanism else {"tau_ns": np.ones(len(rows)), "gain": np.zeros(len(rows))})
        return {
            "x": torch.from_numpy(self.encoder.transform(rows)),
            "x_off": torch.from_numpy(self.encoder.transform([source_off_record(r) for r in rows])),
            "capacitance_fF": torch.tensor([s["condition"]["features"]["capacitance_fF"] for s in samples]),
            "tau_ns": torch.as_tensor(physics["tau_ns"], dtype=torch.float32),
            "gain": torch.as_tensor(physics["gain"], dtype=torch.float32),
            "generated_charge_fC": torch.tensor([r["generated_charge_fC"] for r in rows]),
            "source_duration_ns": torch.tensor(
                [s["primary"]["source_features"]["source_duration_ns"] for s in samples]),
        }

    def predict_samples(self, samples, batch_size=1024):
        """Metadata-only inference. Unsupervised auxiliary heads are returned as null."""
        result = []
        self.model.eval()
        upset_states = self.metadata.get("upset_states")
        for start in range(0, len(samples), batch_size):
            part = samples[start:start + batch_size]
            rows = self._records(part)
            inputs = self._inputs(part, rows=rows)
            with torch.no_grad():
                out = self.model(**inputs, time_ns=torch.tensor(self.metadata["sample_times_ns"]))
            support = self.encoder.outside_support(rows)
            trained = self.metadata["trained_heads"]
            for i, sample in enumerate(part):
                row = {"primary_id": sample["primary"]["primary_id"], "state": sample["state"],
                       "bit_id": str(sample["bit"]["bit_id"]),
                       "condition_id": sample["condition"]["condition_id"],
                       "out_of_support": support[i]}
                for head in HEADS:
                    key = "upset_logit" if head == "upset" else head
                    value = out[key][i].detach().cpu().numpy()
                    supported = head in trained and (head != "upset" or upset_states is None
                                                     or sample["state"] in upset_states)
                    row[key] = value.tolist() if supported and np.isfinite(value).all() else None
                if row["upset_logit"] is not None:
                    calibration = self.metadata.get("probability_calibration", {})
                    temperature = calibration.get("temperature", 1.)
                    probability = float(torch.sigmoid(torch.tensor(row["upset_logit"] / temperature)))
                    row["probability"] = probability
                else:
                    row["probability"] = None
                result.append(row)
        return result

    def evaluate(self, view: View):
        samples = response_samples(view)
        predictions = self.predict_samples(samples)
        labels, masks = targets(samples, self.metadata["sample_times_ns"])
        metrics = {"response_rows": len(samples), "heads": {}}
        for head in HEADS:
            key = "upset_logit" if head == "upset" else head
            if head not in self.metadata["trained_heads"]:
                continue
            values = [p[key] for p in predictions]
            mask = masks[head].numpy()
            if head == "upset" and "upset_states" in self.metadata:
                mask = mask & np.asarray([v is not None for v in values], dtype=bool)
            elif any(v is None for v in values):
                continue
            if not mask.any():
                continue
            y = labels[head].numpy()[mask]
            p = np.asarray(values, dtype=float)[mask]
            if head == "upset":
                probability = np.asarray([x["probability"] for x in predictions], dtype=float)[mask]
                metrics["heads"][head] = {
                    "n": len(y), "positive": int(y.sum()),
                    "brier": float(np.mean((probability - y) ** 2)),
                    "bce": float(np.mean(np.logaddexp(0, p) - y * p)),
                }
            else:
                metrics["heads"][head] = {"n": len(y), "mae": float(np.abs(p-y).mean()),
                                         "rmse": float(np.sqrt(((p-y)**2).mean())),
                                         "normalized_mae": float(np.abs(p-y).mean() /
                                                                 self.metadata["scales"][head])}
        metrics["scientific_status"] = ("synthetic_software_check" if
            view.snapshot.manifest["kind"] == "synthetic_fixture" else "development_score")
        return metrics

    def save(self, path):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        if (path / "weights.pt").exists() or (path / "artifact.json").exists():
            raise DataError("Refusing to overwrite an existing R artifact")
        torch.save(self.model.state_dict(), path / "weights.pt")
        value = {
            "schema_version": 1, "type": "R", "config": self.config.to_dict(),
            "encoder": self.encoder.to_dict(), "device_encoder": self.device_encoder.to_dict(),
            "mechanism": self.mechanism.to_dict() if self.mechanism else None,
            "metadata": self.metadata, "weights_sha256": file_hash(path / "weights.pt")}
        value["artifact_sha256"] = digest(value)
        write_json(path / "artifact.json", value)

    @classmethod
    def load(cls, path):
        path = Path(path)
        value = read_json(path / "artifact.json")
        expected = value.pop("artifact_sha256", None)
        if expected != digest(value):
            raise DataError("R artifact metadata hash mismatch")
        if value.get("type") != "R" or file_hash(path / "weights.pt") != value["weights_sha256"]:
            raise DataError("R artifact type/hash mismatch")
        cfg = Config.from_dict(value["config"])
        encoder = Encoder.from_dict(value["encoder"])
        model = ResponseNet(encoder.width, cfg.r_hidden, cfg.residual_bins, cfg.mode,
                            window_ns=max(value["metadata"]["sample_times_ns"]))
        model.load_state_dict(torch.load(path / "weights.pt", map_location="cpu", weights_only=True))
        return cls(model, encoder, Encoder.from_dict(value["device_encoder"]),
                   MechanismCalibrator.from_dict(value["mechanism"]) if value["mechanism"] else None,
                   cfg, value["metadata"])


def _loss(model, inputs, labels, masks, indices, artifact):
    cfg, meta = artifact.config, artifact.metadata
    prediction = model(**{k: v[indices] for k, v in inputs.items()},
                       time_ns=torch.tensor(meta["sample_times_ns"]))
    loss = prediction["delta_voltage_V"].sum() * 0.
    for head in meta["trained_heads"]:
        if head == "upset":
            loss = loss + masked_bce(prediction["upset_logit"], labels[head][indices], masks[head][indices])
        else:
            loss = loss + masked_huber(prediction[head], labels[head][indices],
                                      masks[head][indices], scale=meta["scales"][head])
    if cfg.mode == "hybrid" and cfg.residual_penalty:
        coef = prediction["residual_coefficients"] / meta["charge_regularizer_scale_fC"]
        loss = loss + cfg.residual_penalty * (coef.square().mean() + coef.diff(dim=1).square().mean())
    return loss


def fit_r_core(view: View, config: Config, *, stop_view=None, epochs=None) -> RArtifact:
    if epochs is not None and (isinstance(epochs, bool) or not isinstance(epochs, int) or epochs < 1):
        raise DataError("Explicit R epochs must be a positive integer")
    if stop_view is not None:
        view.assert_disjoint(stop_view)
    samples = response_samples(view)
    if not samples or not view.snapshot.times or max(view.snapshot.times) <= 0:
        raise DataError("R pending: no response rows or frozen response time grid")
    torch.set_num_threads(config.threads)
    torch.manual_seed(config.seed)
    rows = [sample_record(s) for s in samples]
    encoder = Encoder("R").fit(rows + [source_off_record(r) for r in rows])
    device_rows = [record(c, state=state) for c in view.conditions for state in (0, 1)]
    device_encoder = Encoder("device").fit(device_rows)
    mechanism = (_masked_calibration(view, samples, rows, device_encoder)
                 if config.mode != "plain" else None)
    labels, masks = targets(samples, view.snapshot.times)
    trained = [h for h in HEADS if masks[h].any()]
    if config.mode == "mechanism_only":
        trained = [h for h in trained if h == "delta_voltage_V"]
    upset_states = None
    if view.snapshot.simulation_revision == "0.6":
        states = torch.tensor([sample["state"] for sample in samples])
        upset_states = [state for state in (0, 1) if "upset" in trained and
                        torch.unique(labels["upset"][masks["upset"] & (states == state)]).numel() == 2]
        if "upset" in trained and not upset_states:
            trained.remove("upset")
    elif "upset" in trained and torch.unique(labels["upset"][masks["upset"]]).numel() < 2:
        trained.remove("upset")
    if not trained:
        raise DataError("R pending: no supported supervised heads")
    scales = {}
    for h in trained:
        if h != "upset":
            value = float(torch.sqrt(torch.mean(labels[h][masks[h]].square())))
            scales[h] = value if value > 1e-12 else 1.
    charges = [r["generated_charge_fC"] for r in rows]
    positive_charges = [q for q in charges if q > 0]
    metadata = {
        "training_fingerprint": view.fingerprint(), "training_footprint": view.footprint(),
        "sample_times_ns": view.snapshot.times, "trained_heads": trained, "scales": scales,
        "kind": view.snapshot.manifest["kind"],
        "training_domains": sorted({c["domain"] for c in view.conditions}),
        "charge_regularizer_scale_fC": float(np.median(positive_charges)) if positive_charges else 1.,
        "probability_calibration": {"status": "unavailable", "reason": "no out-of-fit random calibration yet"},
        "batch_unit": "global source_primary_id with all paired states and bits",
        "capacitor_charge_status": "derived_constant_C_relation_not_independent_validation",
    }
    if upset_states is not None:
        metadata.update(simulation_revision=view.snapshot.simulation_revision, upset_states=upset_states,
                        batch_unit="global source_primary_id with all observed responses",
                        **{field: view.snapshot.manifest[field] for field in SOURCE_TIMING_FIELDS})
    model = ResponseNet(encoder.width, config.r_hidden, config.residual_bins,
                        config.mode, window_ns=max(view.snapshot.times))
    artifact = RArtifact(model, encoder, device_encoder, mechanism, config, metadata)
    if config.mode == "mechanism_only":
        metadata.update(selected_epochs=0, stopping={"status": "no_optimizer_for_mechanism_only"})
        return artifact
    inputs = artifact._inputs(samples, rows=rows)
    stop = None
    if stop_view is not None and stop_view.responses:
        ss = response_samples(stop_view)
        sl, sm = targets(ss, view.snapshot.times)
        if any(sm[h].any() for h in trained):
            stop = (artifact._inputs(ss), sl, sm, torch.arange(len(ss)))
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate,
                                  weight_decay=config.weight_decay)
    rng = np.random.default_rng(config.seed)
    max_epochs = epochs if epochs is not None else config.max_epochs
    best, best_epoch, stale, best_weights = float("inf"), max_epochs, 0, None
    for epoch in range(1, max_epochs + 1):
        model.train()
        for indices in primary_batches(samples, config.r_batch_groups, rng):
            if not any(masks[h][indices].any() for h in trained):
                continue
            optimizer.zero_grad(set_to_none=True)
            loss = _loss(model, inputs, labels, masks, indices, artifact)
            if not torch.isfinite(loss):
                raise DataError("Nonfinite R objective; no checkpoint published")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 10.)
            optimizer.step()
        if stop is not None and epochs is None:
            model.eval()
            with torch.no_grad():
                score = float(_loss(model, *stop, artifact))
            if np.isfinite(score) and score < best - 1e-8:
                best, best_epoch, stale = score, epoch, 0
                best_weights = copy.deepcopy(model.state_dict())
            else:
                stale += 1
            if stale >= config.patience:
                break
    if stop is not None and epochs is None and best_weights is not None:
        model.load_state_dict(best_weights)
    metadata["selected_epochs"] = best_epoch
    metadata["stopping"] = {
        "status": "grouped_stop" if stop is not None and epochs is None else "fixed_epochs",
        "fit": view.footprint(), "stop": stop_view.footprint() if stop_view else None,
        "best_objective": best if np.isfinite(best) else None,
    }
    return artifact


def _temperature_from_stop(model, view):
    samples = random_calibration_samples(view)
    predictions = model.predict_samples(samples)
    rows = [(s, p) for s, p in zip(samples, predictions)
            if p["upset_logit"] is not None]
    y = np.asarray([s["response"]["labels"]["upset"] for s, p in rows], dtype=float)
    independent = {s["primary"]["source_primary_id"] for s, p in rows}
    # This is a declared software floor, not proof of adequate rare-event statistics.
    if len(independent) < 4 or len(np.unique(y)) < 2:
        return {"status": "unavailable", "reason": "insufficient random out-of-fit classes/events",
                "independent_primaries": len(independent), "positive": int(y.sum())}
    logits = np.asarray([p["upset_logit"] for s, p in rows])
    temperatures = np.exp(np.linspace(np.log(.25), np.log(4.), 65))
    scores = [float(np.mean(np.logaddexp(0, logits/t) - y*logits/t)) for t in temperatures]
    index = int(np.argmin(scores))
    return {"status": "calibrated", "method": "bounded_temperature_on_random_grouped_stop",
            "temperature": float(temperatures[index]), "bce": scores[index],
            "response_ids": [s["response"]["response_id"] for s, p in rows],
            "independent_primaries": len(independent), "positive": int(y.sum()),
            "source_footprint": view.footprint(),
            "limitation": "development calibration; small counts do not establish population accuracy"}


def fit_r(view: View, config: Config, *, cache_dir=None) -> RArtifact:
    """Select epochs inside this scope, then refit all of this scope."""
    implementation = {p.name: file_hash(p) for p in Path(__file__).parent.glob("*.py")}
    r_config = {k: v for k, v in config.to_dict().items() if not k.startswith("f_")}
    key = digest({"format": 1, "implementation": implementation,
                  "scope": view.fingerprint(), "R_config": r_config})
    cache = Path(cache_dir) / ("R_" + key) if cache_dir else None
    if cache and (cache / "artifact.json").exists():
        artifact = RArtifact.load(cache)
        if artifact.metadata.get("cache_key") != key:
            raise DataError("R cache key mismatch")
        return artifact
    split = stopping_split(view, config.split_seed, config.stopping_fraction)
    selection, calibration, epochs = None, None, config.max_epochs
    if split and config.mode != "mechanism_only":
        core, stop = split
        try:
            selected = fit_r_core(core, config, stop_view=stop)
            epochs = selected.metadata["selected_epochs"]
            selection = selected.metadata["stopping"]
            if "upset" in selected.metadata["trained_heads"]:
                calibration = _temperature_from_stop(selected, stop)
        except DataError as exc:
            selection = {"status": "fixed_epochs_fallback", "reason": str(exc),
                         "stop_not_used_for_fit": stop.footprint()}
    else:
        selection = {"status": "fixed_epochs_fallback", "reason": "too few independent groups or analytic mode"}
    artifact = fit_r_core(view, config, epochs=epochs)
    artifact.metadata.update(cache_key=key, epoch_selection=selection)
    if calibration and "upset" in artifact.metadata["trained_heads"]:
        # The stopping model has changed during all-scope refitting. Its fitted
        # temperature is useful audit evidence, NOT calibration of this artifact.
        artifact.metadata["stopping_calibration_diagnostic"] = calibration
        artifact.metadata["probability_calibration"] = {
            "status": "unavailable",
            "reason": "stopping-model temperature not transferred to a different refitted model",
            "next_step": "estimate temperature from prescribed development out-of-fold logits",
        }
    if cache:
        artifact.save(cache)
    return artifact
